"""Upload router — POST /api/upload, DELETE /api/media/{id}."""

import logging
from pathlib import Path

from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

from backend.config import get_config_value
from backend.caption import DEFAULT_STYLE, STYLES
from backend.ingest import ingest_bytes

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


@router.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    x_upload_pin: str = Header(...),
    location: Optional[str] = Form(None),
    style: Optional[str] = Form(None),
):
    """Upload a photo or video. Optional location overrides GPS; style picks caption look."""
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
    )

    if status == "duplicate":
        raise HTTPException(
            status_code=409,
            detail=f"Already uploaded as '{item['original_name']}'",
        )

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

    filepath = _get_uploads_dir() / item["filename"]
    if filepath.exists():
        filepath.unlink()
        logger.info(f"Deleted: {item['filename']}")

    return {"status": "ok", "deleted": item["id"]}
