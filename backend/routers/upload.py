"""Upload router — POST /api/upload, DELETE /api/media/{id}."""

import logging
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from PIL import Image

from backend.config import get_config_value

logger = logging.getLogger(__name__)

router = APIRouter(tags=["upload"])

# Max display resolution for Skylight MAX
MAX_WIDTH = 2560
MAX_HEIGHT = 1440
JPEG_QUALITY = 85

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/x-matroska", "video/webm"}
ALLOWED_TYPES = IMAGE_TYPES | VIDEO_TYPES


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


def _get_store():
    """Get the media store from app state (set in main.py)."""
    from backend.main import media_store
    return media_store


def _get_uploads_dir() -> Path:
    """Get the uploads directory."""
    from backend.main import uploads_dir
    return uploads_dir


def _verify_pin(pin: str):
    """Verify the upload PIN."""
    correct_pin = get_config_value("pin", "1234")
    if pin != correct_pin:
        raise HTTPException(status_code=403, detail="Invalid PIN")


@router.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    x_upload_pin: str = Header(...),
):
    """Upload a photo or video."""
    _verify_pin(x_upload_pin)

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. "
                   f"Allowed: JPEG, PNG, WebP, MP4, MOV, MKV, WebM"
        )

    content = await file.read()
    size_bytes = len(content)

    # 500MB limit
    if size_bytes > 500 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 500MB)")

    uploads = _get_uploads_dir()
    store = _get_store()
    uid = uuid4().hex[:12]

    width = height = None
    duration = None

    if file.content_type in IMAGE_TYPES:
        media_type = "image"
        ext = ".jpg"
        filename = f"{uid}{ext}"
        filepath = uploads / filename

        # Resize with Pillow
        try:
            img = Image.open(__import__("io").BytesIO(content))
            img = img.convert("RGB") if img.mode != "RGB" else img

            # Auto-rotate based on EXIF
            from PIL import ExifTags
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

            # Downscale if larger than display
            if width > MAX_WIDTH or height > MAX_HEIGHT:
                img.thumbnail((MAX_WIDTH, MAX_HEIGHT), Image.LANCZOS)
                width, height = img.size

            img.save(filepath, "JPEG", quality=JPEG_QUALITY, optimize=True)
            size_bytes = filepath.stat().st_size
        except Exception as e:
            logger.error(f"Image processing failed: {e}")
            raise HTTPException(status_code=400, detail="Failed to process image")
    else:
        media_type = "video"
        ext_map = {
            "video/mp4": ".mp4",
            "video/quicktime": ".mov",
            "video/x-matroska": ".mkv",
            "video/webm": ".webm",
        }
        ext = ext_map.get(file.content_type, ".mp4")
        filename = f"{uid}{ext}"
        filepath = uploads / filename

        size_bytes = _strip_video_audio(content, filepath)

    item = store.add(
        filename=filename,
        original_name=file.filename or "unknown",
        media_type=media_type,
        width=width,
        height=height,
        size_bytes=size_bytes,
        duration=duration,
    )

    logger.info(f"Uploaded {media_type}: {file.filename} -> {filename}")
    return {"status": "ok", "media": item}


@router.delete("/media/{media_id}")
async def delete_media(
    media_id: str,
    x_upload_pin: str = Header(...),
):
    """Delete a media item."""
    _verify_pin(x_upload_pin)

    store = _get_store()
    item = store.delete(media_id)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")

    # Delete file from disk
    filepath = _get_uploads_dir() / item["filename"]
    if filepath.exists():
        filepath.unlink()
        logger.info(f"Deleted: {item['filename']}")

    return {"status": "ok", "deleted": item["id"]}
