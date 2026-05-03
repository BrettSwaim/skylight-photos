"""Google Photos integration — token store, OAuth, and Picker client."""

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Scope for the Photos Picker API
PICKER_SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"


class GooglePhotosClient:
    """Manages Google OAuth tokens and Picker API calls for the single owner."""

    def __init__(self, token_path: Path, client_id: str, client_secret: str, owner_email: str):
        self.token_path = token_path
        self.client_id = client_id
        self.client_secret = client_secret
        self.owner_email = owner_email.lower().strip()
        self._lock = threading.RLock()
        self._token: Optional[dict] = None
        self._load()

    def _load(self):
        """Load the token from disk if it exists."""
        if self.token_path.exists():
            try:
                with open(self.token_path, "r", encoding="utf-8") as f:
                    self._token = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Could not load google_token.json: {e}")
                self._token = None
        else:
            self._token = None

    def _save(self):
        """Persist the token to disk."""
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.token_path, "w", encoding="utf-8") as f:
            json.dump(self._token, f, indent=2)
        # Best-effort restrictive perms; ignore on Windows where chmod is a no-op
        try:
            self.token_path.chmod(0o600)
        except (OSError, NotImplementedError):
            pass

    def is_authorized(self) -> bool:
        """Return True if a refresh token is on file."""
        with self._lock:
            return bool(self._token and self._token.get("refresh_token"))

    def get_status(self) -> dict:
        """Return status dict for the /api/google/status endpoint."""
        with self._lock:
            if not self._token or not self._token.get("refresh_token"):
                return {
                    "authorized": False,
                    "expired": False,
                    "owner_email": self.owner_email,
                }
            return {
                "authorized": True,
                "expired": bool(self._token.get("refresh_failed", False)),
                "owner_email": self._token.get("owner_email", self.owner_email),
            }

    def clear_token(self):
        """Delete the local token file. Used by disconnect."""
        with self._lock:
            self._token = None
            if self.token_path.exists():
                self.token_path.unlink()
