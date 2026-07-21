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

from backend.caption import (
    DEFAULT_STYLE,
    build_caption,
    build_caption_text,
    extract_exif_info,
    render_caption,
)
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


def _orient_and_resize(content: bytes) -> Image.Image:
    """Return a clean RGB image: EXIF-rotated and downscaled. No caption."""
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

    if img.width > MAX_WIDTH or img.height > MAX_HEIGHT:
        img.thumbnail((MAX_WIDTH, MAX_HEIGHT), Image.LANCZOS)
    return img


def _caption_for(content: bytes, place_override: Optional[str]):
    """Return (place, date, caption_text) — any of which may be None."""
    dt, latlon = extract_exif_info(content)
    place, date = build_caption_text(dt, latlon, place_override=place_override)
    text = None
    if place or date:
        text = f"{place} {date}" if place and date else (place or date)
    return place, date, text


def render_preview(
    content: bytes,
    place_override: Optional[str],
    style: str,
    pos: Optional[Tuple[float, float]] = None,
) -> bytes:
    """Render the exact caption onto a downscaled copy and return JPEG bytes.

    Used by the preview endpoint — nothing is persisted.
    """
    img = _orient_and_resize(content)
    if img.width > 1280 or img.height > 1280:
        img.thumbnail((1280, 1280), Image.LANCZOS)
    place, date, _ = _caption_for(content, place_override)
    if place or date:
        img = render_caption(img, place, date, style=style, pos=pos)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=JPEG_QUALITY)
    return out.getvalue()


def _process_image(
    content: bytes,
    dest: Path,
    master_dest: Path,
    place_override: Optional[str] = None,
    style: str = DEFAULT_STYLE,
    pos: Optional[Tuple[float, float]] = None,
) -> dict:
    """Save clean master + captioned display file.

    Returns dict: width, height, size_bytes, caption, place, date, master_saved.
    """
    master = _orient_and_resize(content)
    width, height = master.size

    place = date = caption = None
    master_saved = False
    try:
        place, date, caption = _caption_for(content, place_override)
        # Persist the clean master so the display can be re-rendered later
        master.save(master_dest, "JPEG", quality=JPEG_QUALITY, optimize=True)
        master_saved = True
    except Exception as e:
        logger.warning(f"Master/caption prep failed: {e}")
        place = date = caption = None

    display = master
    if caption:
        try:
            display = render_caption(master.copy(), place, date, style=style, pos=pos)
        except Exception as e:
            logger.warning(f"Caption render failed, saving clean: {e}")
            display = master
            caption = None

    display.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return {
        "width": width,
        "height": height,
        "size_bytes": dest.stat().st_size,
        "caption": caption,
        "place": place,
        "date": date,
        "master_saved": master_saved,
    }


def restyle_display(
    master_path: Path,
    dest: Path,
    place: Optional[str],
    date: Optional[str],
    style: str,
    pos: Optional[Tuple[float, float]] = None,
) -> Optional[str]:
    """Re-render the display file from a stored master. Returns new caption text."""
    with Image.open(master_path) as m:
        master = m.convert("RGB")
    caption = None
    if place or date:
        caption = f"{place} {date}" if place and date else (place or date)
        display = render_caption(master.copy(), place, date, style=style, pos=pos)
    else:
        display = master
    display.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return caption


def ingest_bytes(
    content: bytes,
    content_type: str,
    original_name: str,
    uploads_dir: Path,
    store: MediaStore,
    place_override: Optional[str] = None,
    style: str = DEFAULT_STYLE,
    pos: Optional[Tuple[float, float]] = None,
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
    master_filename: Optional[str] = None
    place: Optional[str] = None
    date: Optional[str] = None

    if content_type in IMAGE_TYPES:
        media_type = "image"
        filename = f"{uid}.jpg"
        master_name = f"{uid}.master.jpg"
        filepath = uploads_dir / filename
        master_path = uploads_dir / master_name
        try:
            r = _process_image(
                content, filepath, master_path,
                place_override=place_override, style=style, pos=pos,
            )
            width, height = r["width"], r["height"]
            size_bytes, caption = r["size_bytes"], r["caption"]
            place, date = r["place"], r["date"]
            if r["master_saved"]:
                master_filename = master_name
        except Exception as e:
            logger.error(f"Image processing failed: {e}")
            filepath.unlink(missing_ok=True)
            master_path.unlink(missing_ok=True)
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
        caption_style=style if caption else None,
        master_filename=master_filename,
        caption_place=place,
        caption_date=date,
        caption_pos_x=pos[0] if pos else None,
        caption_pos_y=pos[1] if pos else None,
    )
    logger.info(f"Ingested {media_type}: {original_name} -> {filename}")
    return "added", item
