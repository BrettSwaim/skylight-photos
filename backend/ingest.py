"""Shared bytes-to-MediaItem pipeline. Used by manual upload and Google import."""

import hashlib
import io
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from uuid import uuid4

from fastapi import HTTPException
from PIL import ExifTags, Image

from backend.caption import build_caption, draw_caption, extract_exif_info
from backend.media import MediaStore

logger = logging.getLogger(__name__)

MAX_WIDTH = 2560
MAX_HEIGHT = 1440
JPEG_QUALITY = 85
MAX_BYTES = 500 * 1024 * 1024

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/x-matroska", "video/webm"}
ALLOWED_TYPES = IMAGE_TYPES | VIDEO_TYPES

VIDEO_EXT_MAP = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "video/webm": ".webm",
}


def _strip_video_audio(content: bytes, dest: Path) -> int:
    """Write video to dest with audio stripped via ffmpeg. Returns final file size."""
    with tempfile.NamedTemporaryFile(suffix=dest.suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(tmp_path), "-c:v", "copy", "-an", str(dest)],
            capture_output=True,
            timeout=300,
        )
        if result.returncode != 0:
            logger.warning(f"ffmpeg audio strip failed, saving original: {result.stderr.decode()[-200:]}")
            dest.write_bytes(content)
    finally:
        tmp_path.unlink(missing_ok=True)
    return dest.stat().st_size


def _process_image(
    content: bytes, dest: Path, place_override: Optional[str] = None
) -> Tuple[int, int, int, Optional[str]]:
    """Process and save an image. Returns (width, height, bytes_on_disk, caption)."""
    with Image.open(io.BytesIO(content)) as src:
        img = src.convert("RGB") if src.mode != "RGB" else src.copy()

    try:
        exif = img._getexif()
        if exif:
            for tag, val in exif.items():
                if ExifTags.TAGS.get(tag) == "Orientation":
                    if val == 3:
                        img = img.rotate(180, expand=True)
                    elif val == 6:
                        img = img.rotate(270, expand=True)
                    elif val == 8:
                        img = img.rotate(90, expand=True)
                    break
    except (AttributeError, KeyError):
        pass

    width, height = img.size
    if width > MAX_WIDTH or height > MAX_HEIGHT:
        img.thumbnail((MAX_WIDTH, MAX_HEIGHT), Image.LANCZOS)
        width, height = img.size

    caption = None
    try:
        dt, latlon = extract_exif_info(content)
        caption = build_caption(dt, latlon, place_override=place_override)
        if caption:
            draw_caption(img, caption)
    except Exception as e:
        logger.warning(f"Captioning failed, saving clean: {e}")
        caption = None

    img.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True)
    img.close()
    return width, height, dest.stat().st_size, caption


def ingest_bytes(
    content: bytes,
    content_type: str,
    original_name: str,
    uploads_dir: Path,
    store: MediaStore,
    place_override: Optional[str] = None,
) -> Tuple[str, dict]:
    """Validate, dedup, process, and store raw upload bytes.

    Returns (status, item) where status is "added" or "duplicate".
    Raises HTTPException for validation/processing failures.
    """
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {content_type}. "
                   f"Allowed: JPEG, PNG, WebP, MP4, MOV, MKV, WebM",
        )

    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 500MB)")

    content_hash = hashlib.sha256(content).hexdigest()
    existing = store.find_by_hash(content_hash)
    if existing:
        return "duplicate", existing

    uid = uuid4().hex[:12]
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    caption: Optional[str] = None

    if content_type in IMAGE_TYPES:
        media_type = "image"
        filename = f"{uid}.jpg"
        filepath = uploads_dir / filename
        try:
            width, height, size_bytes, caption = _process_image(
                content, filepath, place_override=place_override
            )
        except Exception as e:
            logger.error(f"Image processing failed: {e}")
            filepath.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Failed to process image")
    else:
        media_type = "video"
        ext = VIDEO_EXT_MAP.get(content_type, ".mp4")
        filename = f"{uid}{ext}"
        filepath = uploads_dir / filename
        try:
            size_bytes = _strip_video_audio(content, filepath)
        except Exception as e:
            logger.error(f"Video processing failed: {e}")
            filepath.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Failed to process video")

    item = store.add(
        filename=filename,
        original_name=original_name,
        media_type=media_type,
        width=width,
        height=height,
        size_bytes=size_bytes,
        duration=duration,
        content_sha256=content_hash,
        caption=caption,
    )
    logger.info(f"Ingested {media_type}: {original_name} -> {filename}")
    return "added", item
