"""Media router — GET /api/media, GET /api/media/{id}/file."""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Header, HTTPException
from fastapi.responses import FileResponse

from backend.caption import DEFAULT_STYLE, STYLES
from backend.config import get_config_value
from backend.ingest import restyle_display

logger = logging.getLogger(__name__)

router = APIRouter(tags=["media"])


def _get_store():
    from backend.main import media_store
    return media_store


def _get_uploads_dir() -> Path:
    from backend.main import uploads_dir
    return uploads_dir


def _verify_pin(pin: str):
    if pin != get_config_value("pin", "1234"):
        raise HTTPException(status_code=403, detail="Invalid PIN")


@router.get("/media")
async def list_media():
    """List all media items (used by APK and gallery)."""
    store = _get_store()
    items = store.list_all()
    return {
        "count": len(items),
        "media": items,
    }


@router.get("/media/{media_id}")
async def get_media(media_id: str):
    """Get metadata for a single media item."""
    store = _get_store()
    item = store.get(media_id)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")
    return item


@router.post("/media/{media_id}/restyle")
async def restyle_media(
    media_id: str,
    x_upload_pin: str = Header(...),
    style: str = Form(...),
):
    """Re-render an image's caption in a new style from its stored master."""
    _verify_pin(x_upload_pin)

    store = _get_store()
    item = store.get(media_id)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")
    if item.get("media_type") != "image":
        raise HTTPException(status_code=409, detail="Only images can be restyled")

    master_name = item.get("master_filename")
    if not master_name:
        raise HTTPException(
            status_code=409,
            detail="No master image — uploaded before re-style support",
        )

    chosen = (style or "").strip().lower()
    if chosen not in STYLES:
        chosen = DEFAULT_STYLE

    uploads = _get_uploads_dir()
    master_path = uploads / master_name
    if not master_path.exists():
        raise HTTPException(status_code=409, detail="Master file missing on disk")

    px, py = item.get("caption_pos_x"), item.get("caption_pos_y")
    pos = (px, py) if px is not None and py is not None else None

    dest = uploads / item["filename"]
    caption = restyle_display(
        master_path, dest,
        item.get("caption_place"), item.get("caption_date"), chosen, pos,
    )
    updated = store.update(
        media_id, caption=caption, caption_style=chosen if caption else None
    )
    logger.info(f"Restyled {item['filename']} -> {chosen}")
    return {"status": "ok", "media": updated}


@router.get("/media/{media_id}/file")
async def serve_media_file(media_id: str):
    """Serve the actual media file."""
    store = _get_store()
    item = store.get(media_id)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")

    filepath = _get_uploads_dir() / item["filename"]
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    # Determine content type
    ext = filepath.suffix.lower()
    content_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
    }
    content_type = content_types.get(ext, "application/octet-stream")

    return FileResponse(
        path=str(filepath),
        media_type=content_type,
        filename=item.get("original_name", item["filename"]),
    )
