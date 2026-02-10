"""Media router — GET /api/media, GET /api/media/{id}/file."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["media"])


def _get_store():
    from backend.main import media_store
    return media_store


def _get_uploads_dir() -> Path:
    from backend.main import uploads_dir
    return uploads_dir


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
