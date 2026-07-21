"""Upload router — POST /api/upload, DELETE /api/media/{id}."""

import logging
from pathlib import Path

from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Response, UploadFile

from backend.config import get_config_value
from backend.caption import DEFAULT_STYLE, STYLES
from backend.ingest import IMAGE_TYPES, ingest_bytes, render_preview

logger = logging.getLogger(__name__)

router = APIRouter(tags=["upload"])


def _get_store():
    from backend.main import media_store
    return media_store


def _get_uploads_dir() -> Path:
    from backend.main import uploads_dir
    return uploads_dir


def _verify_pin(pin: str):
    correct_pin = get_config_value("pin", "1234")
    if pin != correct_pin:
        raise HTTPException(status_code=403, detail="Invalid PIN")


def _parse_pos(pos_x, pos_y):
    """Two optional form floats → clamped (x, y) tuple in [0,1], or None."""
    if pos_x is None or pos_y is None:
        return None
    try:
        x = min(1.0, max(0.0, float(pos_x)))
        y = min(1.0, max(0.0, float(pos_y)))
        return (x, y)
    except (TypeError, ValueError):
        return None


@router.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    x_upload_pin: str = Header(...),
    location: Optional[str] = Form(None),
    style: Optional[str] = Form(None),
    pos_x: Optional[float] = Form(None),
    pos_y: Optional[float] = Form(None),
):
    """Upload a photo or video. Optional location overrides GPS; style + pos set the caption."""
    _verify_pin(x_upload_pin)
    content = await file.read()

    place_override = (location or "").strip()[:80] or None
    chosen_style = (style or "").strip().lower()
    if chosen_style not in STYLES:
        chosen_style = DEFAULT_STYLE

    status, item = ingest_bytes(
        content=content,
        content_type=file.content_type or "",
        original_name=file.filename or "unknown",
        uploads_dir=_get_uploads_dir(),
        store=_get_store(),
        place_override=place_override,
        style=chosen_style,
        pos=_parse_pos(pos_x, pos_y),
    )

    if status == "duplicate":
        raise HTTPException(
            status_code=409,
            detail=f"Already uploaded as '{item['original_name']}'",
        )

    return {"status": "ok", "media": item}


@router.post("/preview")
async def preview_caption(
    file: UploadFile = File(...),
    x_upload_pin: str = Header(...),
    location: Optional[str] = Form(None),
    style: Optional[str] = Form(None),
    pos_x: Optional[float] = Form(None),
    pos_y: Optional[float] = Form(None),
):
    """Render a caption preview onto the image and return it. Saves nothing."""
    _verify_pin(x_upload_pin)
    if (file.content_type or "") not in IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Preview supports images only")

    content = await file.read()
    place_override = (location or "").strip()[:80] or None
    chosen_style = (style or "").strip().lower()
    if chosen_style not in STYLES:
        chosen_style = DEFAULT_STYLE

    try:
        jpeg = render_preview(content, place_override, chosen_style, _parse_pos(pos_x, pos_y))
    except Exception as e:
        logger.error(f"Preview render failed: {e}")
        raise HTTPException(status_code=400, detail="Could not render preview")

    return Response(content=jpeg, media_type="image/jpeg")


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

    uploads = _get_uploads_dir()
    filepath = uploads / item["filename"]
    if filepath.exists():
        filepath.unlink()
        logger.info(f"Deleted: {item['filename']}")

    master = item.get("master_filename")
    if master:
        master_path = uploads / master
        if master_path.exists():
            master_path.unlink()

    return {"status": "ok", "deleted": item["id"]}
