"""Google Photos integration — token store, OAuth, and Picker client."""

import json
import logging
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import httpx
from google_auth_oauthlib.flow import Flow

logger = logging.getLogger(__name__)

# Scopes requested at OAuth time. The picker scope is the actual feature; openid+email
# are required so the userinfo endpoint will return the user's email for the owner-allowlist check.
PICKER_SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"
EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
OPENID_SCOPE = "openid"
OAUTH_SCOPES = [PICKER_SCOPE, EMAIL_SCOPE, OPENID_SCOPE]


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

    def _build_flow(self, redirect_uri: str) -> Flow:
        """Construct a google_auth_oauthlib Flow for this client's credentials."""
        return Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [redirect_uri],
                }
            },
            scopes=OAUTH_SCOPES,
            redirect_uri=redirect_uri,
        )

    def start_oauth(self, redirect_uri: str) -> Tuple[str, str, str]:
        """Generate an OAuth URL, CSRF state, and PKCE verifier. Returns (url, state, code_verifier).

        The code_verifier must be persisted by the caller and passed back to complete_oauth —
        google_auth_oauthlib auto-enables PKCE, and the verifier lives only on this Flow instance.
        """
        flow = self._build_flow(redirect_uri)
        state = secrets.token_urlsafe(32)
        url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        return url, state, flow.code_verifier

    def complete_oauth(self, code: str, redirect_uri: str, code_verifier: Optional[str] = None) -> Tuple[bool, str]:
        """Exchange code for tokens, validate owner email, persist. Returns (ok, message).

        code_verifier must match the one returned by the corresponding start_oauth call (PKCE).
        """
        flow = self._build_flow(redirect_uri)
        if code_verifier:
            flow.code_verifier = code_verifier
        try:
            flow.fetch_token(code=code)
        except Exception as e:
            logger.error(f"Token exchange failed: {e}")
            return False, "Failed to exchange authorization code"

        creds = flow.credentials

        # Verify the owner's identity by reading userinfo
        try:
            resp = httpx.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {creds.token}"},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Userinfo lookup failed: {e}")
            return False, "Could not verify Google account"

        if not data.get("email_verified", False):
            return False, "Google account email is not verified"
        email = data.get("email", "").lower().strip()
        if not email:
            return False, "Google did not return an email"
        if not self.owner_email:
            logger.error("google_owner_email is not configured; refusing to authorize")
            return False, "Server is not configured with an owner email"
        if email != self.owner_email:
            logger.warning(f"OAuth attempt by non-owner: {email}")
            return False, "This app is owned by someone else"

        if not creds.refresh_token:
            return False, "No refresh token returned by Google (try revoking access at myaccount.google.com and retry)"

        with self._lock:
            self._token = {
                "refresh_token": creds.refresh_token,
                "access_token": creds.token,
                "access_token_expires_at": creds.expiry.replace(tzinfo=timezone.utc).isoformat() if creds.expiry else None,
                "owner_email": email,
                "connected_at": datetime.now(timezone.utc).isoformat(),
                "refresh_failed": False,
            }
            self._save()
        logger.info(f"OAuth completed for {email}")
        return True, "Connected"
