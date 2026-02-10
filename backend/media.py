"""JSON-based media metadata manager (no database)."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4


class MediaStore:
    """Thread-safe JSON file-backed media metadata store."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.meta_path = data_dir / "media.json"
        self._lock = threading.Lock()
        self._media: list[dict] = []
        self._load()

    def _load(self):
        """Load metadata from disk."""
        if self.meta_path.exists():
            with open(self.meta_path, "r", encoding="utf-8") as f:
                self._media = json.load(f)
        else:
            self._media = []

    def _save(self):
        """Persist metadata to disk."""
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self._media, f, indent=2)

    def add(self, filename: str, original_name: str, media_type: str,
            width: Optional[int] = None, height: Optional[int] = None,
            size_bytes: int = 0, duration: Optional[float] = None) -> dict:
        """Add a media item and return its metadata."""
        item = {
            "id": uuid4().hex[:12],
            "filename": filename,
            "original_name": original_name,
            "media_type": media_type,  # "image" or "video"
            "width": width,
            "height": height,
            "size_bytes": size_bytes,
            "duration": duration,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._media.append(item)
            self._save()
        return item

    def list_all(self) -> list[dict]:
        """Return all media items."""
        with self._lock:
            return list(self._media)

    def get(self, media_id: str) -> Optional[dict]:
        """Get a single media item by ID."""
        with self._lock:
            for item in self._media:
                if item["id"] == media_id:
                    return item
        return None

    def delete(self, media_id: str) -> Optional[dict]:
        """Remove a media item by ID and return it."""
        with self._lock:
            for i, item in enumerate(self._media):
                if item["id"] == media_id:
                    removed = self._media.pop(i)
                    self._save()
                    return removed
        return None

    def count(self) -> int:
        """Return total number of media items."""
        with self._lock:
            return len(self._media)
