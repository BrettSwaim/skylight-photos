# Google Photos Picker Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Import from Google Photos" button to skylight-photos that lets the owner pick photos from their Google Photos library via Google's hosted Picker UI and pulls them through the existing upload pipeline.

**Architecture:** OAuth + Google Photos Picker API with a single hardcoded owner identity. New `GooglePhotosClient` handles token persistence, OAuth flow, and Picker session lifecycle. The existing `upload.py` byte-processing pipeline (Pillow + ffmpeg + SHA-256 dedup + MediaStore) is extracted into a shared `ingest_bytes` helper consumed by both the manual upload route and the new Google import route. New `frontend/js/components/google_import.js` adds the UI.

**Tech Stack:** FastAPI, Python 3.10+, vanilla JS, `google-auth` for OAuth, `httpx` for Picker REST calls.

**Spec reference:** `docs/superpowers/specs/2026-05-03-google-photos-integration-design.md`

---

## File Structure

**New files:**
- `backend/google_photos.py` — `GooglePhotosClient` (token store + OAuth + Picker REST client)
- `backend/routers/google.py` — eight new HTTP endpoints
- `backend/ingest.py` — shared bytes-to-MediaItem pipeline extracted from upload.py
- `frontend/js/components/google_import.js` — button state machine + picker window + polling

**Modified files:**
- `backend/main.py` — register google router
- `backend/routers/upload.py` — call `ingest.process_bytes()` instead of inline pipeline
- `requirements.txt` — add google-auth, google-auth-oauthlib, httpx
- `config/settings.example.json` — add 3 new fields
- `.gitignore` — add `config/google_token.json`
- `frontend/index.html` — load google_import.js, add button + state span
- `frontend/js/app.js` — wire `GoogleImport.init()`

## Implementer notes

- **No test framework exists.** Verification is manual via curl, browser, log inspection. Each task lists what to check.
- **Auto-commit-and-push convention applies** (per CLAUDE.md). Push after each task.
- **Dev server:** `PYTHONPATH=. venv/Scripts/uvicorn backend.main:app --reload --port 8007` (Windows) or swap `Scripts` for `bin` on Linux. URL: `http://127.0.0.1:8007/`.
- **Dev PIN:** read from `config/settings.json["pin"]` (typically `5819`).
- **Owner email:** `brett@swaimdesign.com` (set in settings.json by Task 1).
- **Don't deploy until Task 9.** All earlier verification happens against the local dev server.

---

### Task 1: Set up OAuth credentials and config schema

**What this does:** Creates the GCP OAuth credentials, populates settings, gitignores the token file, installs Python deps. After this task the project can import `google_auth_oauthlib` and `httpx`, but no functional endpoints yet.

**Files:**
- Modify: `config/settings.example.json`
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Manual (gitignored): `config/settings.json`
- Manual (browser): Google Cloud Console

- [ ] **Step 1: Create the GCP OAuth client (manual, in browser)**

1. Open https://console.cloud.google.com/. Create a new project named **"skylight-photos"** (or pick an existing one).
2. Top search bar → **"Photos Picker API"** → click the result → **Enable**.
3. Left nav → **APIs & Services** → **OAuth consent screen**:
   - User Type: **External**
   - App name: `Skylight Photos`
   - User support email: `brett@swaimdesign.com`
   - Developer contact: `brett@swaimdesign.com`
   - Save & Continue
   - Scopes step: Save & Continue (no scopes needed here)
   - Test users: add `brett@swaimdesign.com`. Save & Continue.
   - Publishing status stays **Testing** — that is intentional (per the spec, accept the 7-day reconnect cadence).
4. Left nav → **Credentials** → **Create Credentials** → **OAuth client ID**:
   - Application type: **Web application**
   - Name: `Skylight Photos Web`
   - Authorized redirect URIs (add BOTH):
     - `https://photos.2azone.com/api/google/oauth/callback`
     - `http://localhost:8007/api/google/oauth/callback`
   - Create.
5. Copy the **Client ID** and **Client Secret** from the resulting dialog.

Verification: Client ID looks like `xxxxxx.apps.googleusercontent.com`. Client secret looks like `GOCSPX-xxxxxxxx`.

- [ ] **Step 2: Update `config/settings.example.json`**

Replace the contents with:

```json
{
    "pin": "1234",
    "max_upload_mb": 500,
    "image_max_width": 2560,
    "image_max_height": 1440,
    "jpeg_quality": 85,
    "google_owner_email": "you@example.com",
    "google_client_id": "REPLACE_WITH_CLIENT_ID.apps.googleusercontent.com",
    "google_client_secret": "REPLACE_WITH_CLIENT_SECRET"
}
```

- [ ] **Step 3: Update local `config/settings.json` (gitignored — do NOT commit)**

Add the three new keys to your existing local settings file. Final shape:

```json
{
    "pin": "5819",
    "google_owner_email": "brett@swaimdesign.com",
    "google_client_id": "<paste from Step 1>",
    "google_client_secret": "<paste from Step 1>"
}
```

- [ ] **Step 4: Add token file to `.gitignore`**

Append a single line to `.gitignore`:

```
config/google_token.json
```

Verify with: `grep google_token .gitignore` — must print the line.

- [ ] **Step 5: Add Python dependencies to `requirements.txt`**

Append these three lines to `requirements.txt`:

```
google-auth>=2.30.0
google-auth-oauthlib>=1.2.0
httpx>=0.27.0
```

Then install:

```bash
venv/Scripts/pip install -r requirements.txt
```

(On Linux: `venv/bin/pip install -r requirements.txt`)

Verify imports work:

```bash
venv/Scripts/python -c "from google_auth_oauthlib.flow import Flow; import httpx; print('ok')"
```

Expected output: `ok`

- [ ] **Step 6: Commit**

```bash
git add config/settings.example.json requirements.txt .gitignore
git commit -m "Add Google Photos integration scaffolding (config + deps)"
git push
```

Verify with `git status` — `config/settings.json` should NOT appear in the commit (it's gitignored).

---

### Task 2: Token storage skeleton in `GooglePhotosClient`

**What this does:** Creates the new module with a thread-safe JSON-backed token store. No HTTP yet — just persistence and status reporting.

**Files:**
- Create: `backend/google_photos.py`

- [ ] **Step 1: Create `backend/google_photos.py` with the token store**

```python
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
        self._lock = threading.Lock()
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
```

- [ ] **Step 2: Quick REPL verification**

```bash
venv/Scripts/python -c "
from pathlib import Path
from backend.google_photos import GooglePhotosClient
c = GooglePhotosClient(Path('config/google_token.json'), 'cid', 'csecret', 'a@b.com')
print('authorized:', c.is_authorized())
print('status:', c.get_status())
"
```

Expected output:
```
authorized: False
status: {'authorized': False, 'expired': False, 'owner_email': 'a@b.com'}
```

- [ ] **Step 3: Commit**

```bash
git add backend/google_photos.py
git commit -m "Add GooglePhotosClient skeleton with token store"
git push
```

---

### Task 3: OAuth flow — start + callback

**What this does:** Implements the authorization flow. After this task you can complete OAuth end-to-end and have a token persisted.

**Files:**
- Modify: `backend/google_photos.py`
- Create: `backend/routers/google.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Extend `GooglePhotosClient` with OAuth methods**

Add these imports to the top of `backend/google_photos.py`:

```python
import secrets
import time
from typing import Tuple

import httpx
from google_auth_oauthlib.flow import Flow
```

Add these methods to the `GooglePhotosClient` class:

```python
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
            scopes=[PICKER_SCOPE],
            redirect_uri=redirect_uri,
        )

    def start_oauth(self, redirect_uri: str) -> Tuple[str, str]:
        """Generate an OAuth URL and CSRF state. Returns (url, state)."""
        flow = self._build_flow(redirect_uri)
        state = secrets.token_urlsafe(32)
        url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        return url, state

    def complete_oauth(self, code: str, redirect_uri: str) -> Tuple[bool, str]:
        """Exchange code for tokens, validate owner email, persist. Returns (ok, message)."""
        flow = self._build_flow(redirect_uri)
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
            email = resp.json().get("email", "").lower().strip()
        except Exception as e:
            logger.error(f"Userinfo lookup failed: {e}")
            return False, "Could not verify Google account"

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
```

- [ ] **Step 2: Create `backend/routers/google.py`**

```python
"""Google Photos endpoints — OAuth, status, picker, import."""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.config import get_config_value

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/google", tags=["google"])

# In-memory CSRF state store: {state: expires_at_unix}
_oauth_states: dict[str, float] = {}
_STATE_TTL_SECONDS = 600  # 10 minutes


def _verify_pin(pin: str):
    correct_pin = get_config_value("pin", "1234")
    if pin != correct_pin:
        raise HTTPException(status_code=403, detail="Invalid PIN")


def _get_client():
    """Lazy-fetch the GooglePhotosClient from main."""
    from backend.main import google_client
    return google_client


def _redirect_uri_for(request: Request) -> str:
    """Compute the OAuth redirect URI for this request's host."""
    return str(request.url_for("oauth_callback"))


def _prune_states():
    now = time.time()
    expired = [s for s, t in _oauth_states.items() if t < now]
    for s in expired:
        _oauth_states.pop(s, None)


@router.get("/status")
async def google_status():
    """Public — returns button state info."""
    return _get_client().get_status()


@router.get("/oauth/start")
async def oauth_start(request: Request, x_upload_pin: str = Header(...)):
    """PIN-gated. Redirects to Google's consent screen."""
    _verify_pin(x_upload_pin)
    _prune_states()
    redirect_uri = _redirect_uri_for(request)
    url, state = _get_client().start_oauth(redirect_uri)
    _oauth_states[state] = time.time() + _STATE_TTL_SECONDS
    return RedirectResponse(url)


@router.get("/oauth/callback", name="oauth_callback")
async def oauth_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """Receives Google's redirect. State-protected, no PIN required."""
    if error:
        return HTMLResponse(_callback_html(False, f"Google returned an error: {error}"), status_code=400)
    if not code or not state:
        return HTMLResponse(_callback_html(False, "Missing code or state"), status_code=400)

    _prune_states()
    expires = _oauth_states.pop(state, None)
    if expires is None or expires < time.time():
        return HTMLResponse(_callback_html(False, "Authorization session expired — please try again"), status_code=400)

    redirect_uri = _redirect_uri_for(request)
    ok, message = _get_client().complete_oauth(code, redirect_uri)
    status_code = 200 if ok else 403
    return HTMLResponse(_callback_html(ok, message), status_code=status_code)


def _callback_html(ok: bool, message: str) -> str:
    """Tiny HTML page shown to the user after OAuth completes (or fails)."""
    color = "#0a7" if ok else "#a30"
    title = "Connected" if ok else "Authorization failed"
    return f"""<!DOCTYPE html>
<html>
<head><title>{title}</title>
<style>
body {{ font-family: system-ui; max-width: 480px; margin: 4em auto; padding: 1em; text-align: center; }}
h1 {{ color: {color}; }}
button {{ font-size: 1em; padding: 0.5em 1em; cursor: pointer; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p>{message}</p>
<button onclick="window.close()">Close window</button>
<script>
  // If opened as a popup, the parent will detect closure and refresh status
  if (window.opener) {{ try {{ window.opener.postMessage({{ type: 'google-oauth', ok: {str(ok).lower()} }}, '*'); }} catch(e) {{}} }}
</script>
</body>
</html>"""
```

- [ ] **Step 3: Wire the router into `backend/main.py`**

Edit `backend/main.py`:

```python
"""Main FastAPI application for Skylight Photos."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import get_config_value
from backend.google_photos import GooglePhotosClient
from backend.media import MediaStore
from backend.routers import google, media, upload

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Skylight Photos",
    description="Photo/video upload service for Skylight MAX digital frame",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://photos.2azone.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

project_root = Path(__file__).parent.parent
uploads_dir = project_root / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)

media_store = MediaStore(uploads_dir)

google_client = GooglePhotosClient(
    token_path=project_root / "config" / "google_token.json",
    client_id=get_config_value("google_client_id", ""),
    client_secret=get_config_value("google_client_secret", ""),
    owner_email=get_config_value("google_owner_email", ""),
)

app.include_router(upload.router, prefix="/api")
app.include_router(media.router, prefix="/api")
app.include_router(google.router, prefix="/api")


@app.post("/api/verify-pin")
async def verify_pin(body: dict):
    pin = body.get("pin", "")
    correct = get_config_value("pin", "1234")
    if pin == correct:
        return {"valid": True}
    return {"valid": False}


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "skylight-photos",
        "version": "1.0.0",
        "media_count": media_store.count(),
    }


if uploads_dir.exists():
    app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

frontend_path = project_root / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
```

- [ ] **Step 4: Start the dev server and verify status endpoint**

Start server:

```bash
PYTHONPATH=. venv/Scripts/uvicorn backend.main:app --reload --port 8007
```

In another terminal:

```bash
curl -s http://127.0.0.1:8007/api/google/status
```

Expected output (one line):
```json
{"authorized":false,"expired":false,"owner_email":"brett@swaimdesign.com"}
```

- [ ] **Step 5: Walk through OAuth end-to-end manually**

In your browser, open: `http://localhost:8007/api/google/oauth/start` — but this requires a PIN header, so use this curl approach instead:

```bash
curl -i -H "X-Upload-PIN: 5819" http://localhost:8007/api/google/oauth/start
```

Expected: HTTP 307 redirect with a `location:` header pointing to `https://accounts.google.com/o/oauth2/auth?...`. Copy that URL into your browser. Authorize as `brett@swaimdesign.com`. Browser eventually lands on `http://localhost:8007/api/google/oauth/callback?code=...` and shows a green "Connected" page.

Verify the token persisted:

```bash
ls config/google_token.json
cat config/google_token.json
```

The file should exist; `refresh_token` should be present; `owner_email` should be `brett@swaimdesign.com`.

Verify the status flips:

```bash
curl -s http://127.0.0.1:8007/api/google/status
```

Expected: `{"authorized":true,"expired":false,"owner_email":"brett@swaimdesign.com"}`

- [ ] **Step 6: Verify owner-email rejection**

This requires a second Google account. If you don't have one handy, skip this step and document it as deferred — but if you do:

1. Delete `config/google_token.json` so we start fresh: `rm config/google_token.json`.
2. Repeat Step 5 but log in to Google as a different account (use an incognito window).
3. Expected: callback page is RED with text "This app is owned by someone else". `config/google_token.json` does NOT exist after.

- [ ] **Step 7: Commit**

```bash
git add backend/google_photos.py backend/routers/google.py backend/main.py
git commit -m "Add Google OAuth flow with owner-email allowlist"
git push
```

---

### Task 4: Access token refresh + disconnect endpoint

**What this does:** Adds the silent-refresh logic so subsequent calls don't redo OAuth, plus the disconnect endpoint that revokes upstream and clears local state.

**Files:**
- Modify: `backend/google_photos.py`
- Modify: `backend/routers/google.py`

- [ ] **Step 1: Extend `GooglePhotosClient` with refresh + disconnect**

Add to `backend/google_photos.py`:

```python
    def get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed.

        Raises HTTPException(401) if no refresh token or refresh fails.
        """
        from fastapi import HTTPException

        with self._lock:
            if not self._token or not self._token.get("refresh_token"):
                raise HTTPException(status_code=401, detail="Google account not connected")

            access_token = self._token.get("access_token")
            expires_at = self._token.get("access_token_expires_at")

            # If still valid for >60 seconds, reuse
            if access_token and expires_at:
                try:
                    expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    if (expires_dt - datetime.now(timezone.utc)).total_seconds() > 60:
                        return access_token
                except ValueError:
                    pass

            # Refresh
            try:
                resp = httpx.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "refresh_token": self._token["refresh_token"],
                        "grant_type": "refresh_token",
                    },
                    timeout=10.0,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"Refresh failed: {e}")
                self._token["refresh_failed"] = True
                self._save()
                raise HTTPException(status_code=401, detail="Google authorization expired, please reconnect")

            new_access = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            new_expires = datetime.now(timezone.utc).timestamp() + expires_in

            self._token["access_token"] = new_access
            self._token["access_token_expires_at"] = datetime.fromtimestamp(new_expires, timezone.utc).isoformat()
            self._token["refresh_failed"] = False
            self._save()
            return new_access

    def disconnect(self) -> bool:
        """Revoke the refresh token at Google, then delete locally. Returns success."""
        revoked = False
        with self._lock:
            refresh_token = self._token.get("refresh_token") if self._token else None

        if refresh_token:
            try:
                resp = httpx.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": refresh_token},
                    timeout=10.0,
                )
                revoked = resp.status_code == 200
            except Exception as e:
                logger.warning(f"Revoke call failed (continuing with local clear): {e}")

        self.clear_token()
        return revoked
```

- [ ] **Step 2: Add `disconnect` endpoint to `backend/routers/google.py`**

Append to the bottom of the file:

```python
@router.post("/disconnect")
async def disconnect(x_upload_pin: str = Header(...)):
    """PIN-gated. Revokes the refresh token at Google and deletes local token."""
    _verify_pin(x_upload_pin)
    revoked = _get_client().disconnect()
    return {"status": "ok", "revoked_at_google": revoked}
```

- [ ] **Step 3: Verify refresh works**

Restart the dev server (autoreload should handle this, but if not: Ctrl-C and rerun the uvicorn command).

Force a refresh by manually expiring the access token. Edit `config/google_token.json` and set `access_token_expires_at` to `2020-01-01T00:00:00+00:00`. Then trigger a refresh by calling any endpoint that uses `get_access_token()`. We don't have one yet, so do a REPL test:

```bash
venv/Scripts/python -c "
import asyncio
from backend.main import google_client
print(google_client.get_access_token()[:20] + '...')
"
```

Expected: prints the first 20 chars of a fresh access token. Then check `config/google_token.json` — `access_token_expires_at` should now be ~1 hour in the future.

- [ ] **Step 4: Verify disconnect**

```bash
curl -X POST -H "X-Upload-PIN: 5819" http://127.0.0.1:8007/api/google/disconnect
```

Expected: `{"status":"ok","revoked_at_google":true}` (or `false` if Google's revoke endpoint had an issue, but local clear still happens).

Verify local state:

```bash
ls config/google_token.json
```

Expected: file does not exist.

```bash
curl -s http://127.0.0.1:8007/api/google/status
```

Expected: `{"authorized":false,...}`

- [ ] **Step 5: Re-authorize to set up for the next task**

Repeat Task 3 Step 5 to get a fresh token in place. (You'll need this for Task 5.)

- [ ] **Step 6: Commit**

```bash
git add backend/google_photos.py backend/routers/google.py
git commit -m "Add Google access token refresh and disconnect endpoint"
git push
```

---

### Task 5: Picker session lifecycle

**What this does:** Adds the three Picker session endpoints (create, poll, delete). After this task you can manually drive a picker session via curl + browser.

**Files:**
- Modify: `backend/google_photos.py`
- Modify: `backend/routers/google.py`

- [ ] **Step 1: Add Picker REST methods to `GooglePhotosClient`**

Append to the class in `backend/google_photos.py`:

```python
    _PICKER_BASE = "https://photospicker.googleapis.com/v1"

    def _picker_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.get_access_token()}"}

    def create_picker_session(self) -> dict:
        """Create a picker session. Returns the session dict from Google."""
        resp = httpx.post(
            f"{self._PICKER_BASE}/sessions",
            headers=self._picker_headers(),
            json={},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        # Google returns: {id, pickerUri, pollingConfig, mediaItemsSet, expireTime, ...}
        return data

    def get_picker_session(self, session_id: str) -> dict:
        """Get current state of a picker session."""
        resp = httpx.get(
            f"{self._PICKER_BASE}/sessions/{session_id}",
            headers=self._picker_headers(),
            timeout=10.0,
        )
        if resp.status_code == 404:
            return {"id": session_id, "expired": True}
        resp.raise_for_status()
        return resp.json()

    def delete_picker_session(self, session_id: str) -> bool:
        """Delete a picker session. Returns True on success."""
        try:
            resp = httpx.delete(
                f"{self._PICKER_BASE}/sessions/{session_id}",
                headers=self._picker_headers(),
                timeout=10.0,
            )
            return resp.status_code in (200, 204, 404)
        except Exception as e:
            logger.warning(f"Picker session delete failed: {e}")
            return False
```

- [ ] **Step 2: Add three picker endpoints to `backend/routers/google.py`**

Append:

```python
@router.post("/picker/session")
async def create_picker_session(x_upload_pin: str = Header(...)):
    """PIN-gated. Creates a Google Picker session."""
    _verify_pin(x_upload_pin)
    try:
        session = _get_client().create_picker_session()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Picker session create failed: {e}")
        raise HTTPException(status_code=502, detail="Could not create Google Picker session")
    return {
        "session_id": session["id"],
        "picker_uri": session["pickerUri"],
        "polling_interval_seconds": int(session.get("pollingConfig", {}).get("pollInterval", "3s").rstrip("s")) or 3,
    }


@router.get("/picker/session/{session_id}")
async def get_picker_session(session_id: str, x_upload_pin: str = Header(...)):
    """PIN-gated. Returns picker session state: pending, ready, or expired."""
    _verify_pin(x_upload_pin)
    try:
        session = _get_client().get_picker_session(session_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Picker session poll failed: {e}")
        raise HTTPException(status_code=502, detail="Could not poll Google Picker session")

    if session.get("expired"):
        return {"status": "expired"}
    if session.get("mediaItemsSet"):
        return {"status": "ready"}
    return {"status": "pending"}


@router.delete("/picker/session/{session_id}")
async def delete_picker_session(session_id: str, x_upload_pin: str = Header(...)):
    """PIN-gated. Deletes a picker session at Google."""
    _verify_pin(x_upload_pin)
    deleted = _get_client().delete_picker_session(session_id)
    return {"status": "ok", "deleted": deleted}
```

- [ ] **Step 3: Manually verify the picker flow**

Create a session:

```bash
curl -s -X POST -H "X-Upload-PIN: 5819" http://127.0.0.1:8007/api/google/picker/session
```

Expected output (formatted):
```json
{
  "session_id": "...",
  "picker_uri": "https://photos.google.com/picker/...",
  "polling_interval_seconds": 3
}
```

Save the `session_id` and open the `picker_uri` in your browser. Log in as `brett@swaimdesign.com` if prompted. Pick 1 photo. Click confirm/done.

Poll the session (substitute the real session_id):

```bash
curl -s -H "X-Upload-PIN: 5819" http://127.0.0.1:8007/api/google/picker/session/SESSION_ID_HERE
```

Expected: `{"status":"ready"}` (after picking) or `{"status":"pending"}` (before).

- [ ] **Step 4: Clean up the session**

```bash
curl -s -X DELETE -H "X-Upload-PIN: 5819" http://127.0.0.1:8007/api/google/picker/session/SESSION_ID_HERE
```

Expected: `{"status":"ok","deleted":true}`

Subsequent polls should return `{"status":"expired"}`.

- [ ] **Step 5: Commit**

```bash
git add backend/google_photos.py backend/routers/google.py
git commit -m "Add Google Picker session create/poll/delete endpoints"
git push
```

---

### Task 6: Extract upload pipeline into shared `ingest` module

**What this does:** Refactors the byte-processing pipeline out of `upload.py` so the upcoming Google import endpoint can reuse it. No behavior change. The existing manual upload flow continues to work identically.

**Files:**
- Create: `backend/ingest.py`
- Modify: `backend/routers/upload.py`

- [ ] **Step 1: Create `backend/ingest.py`**

```python
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


def _process_image(content: bytes, dest: Path) -> Tuple[int, int, int]:
    """Process and save an image. Returns (width, height, bytes_on_disk)."""
    img = Image.open(io.BytesIO(content))
    img = img.convert("RGB") if img.mode != "RGB" else img

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

    img.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return width, height, dest.stat().st_size


def ingest_bytes(
    content: bytes,
    content_type: str,
    original_name: str,
    uploads_dir: Path,
    store: MediaStore,
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

    if content_type in IMAGE_TYPES:
        media_type = "image"
        filename = f"{uid}.jpg"
        filepath = uploads_dir / filename
        try:
            width, height, size_bytes = _process_image(content, filepath)
        except Exception as e:
            logger.error(f"Image processing failed: {e}")
            raise HTTPException(status_code=400, detail="Failed to process image")
    else:
        media_type = "video"
        ext = VIDEO_EXT_MAP.get(content_type, ".mp4")
        filename = f"{uid}{ext}"
        filepath = uploads_dir / filename
        size_bytes = _strip_video_audio(content, filepath)

    item = store.add(
        filename=filename,
        original_name=original_name,
        media_type=media_type,
        width=width,
        height=height,
        size_bytes=size_bytes,
        duration=duration,
        content_sha256=content_hash,
    )
    logger.info(f"Ingested {media_type}: {original_name} -> {filename}")
    return "added", item
```

- [ ] **Step 2: Refactor `backend/routers/upload.py` to use `ingest_bytes`**

Replace the entire contents of `backend/routers/upload.py` with:

```python
"""Upload router — POST /api/upload, DELETE /api/media/{id}."""

import logging
from pathlib import Path

from fastapi import APIRouter, File, Header, HTTPException, UploadFile

from backend.config import get_config_value
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
):
    """Upload a photo or video."""
    _verify_pin(x_upload_pin)
    content = await file.read()

    status, item = ingest_bytes(
        content=content,
        content_type=file.content_type or "",
        original_name=file.filename or "unknown",
        uploads_dir=_get_uploads_dir(),
        store=_get_store(),
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
```

- [ ] **Step 3: Regression-check the manual upload path**

Restart dev server. Open `http://127.0.0.1:8007/`, log in with PIN, drag in a fresh photo. Verify:
- Upload completes successfully
- Photo appears in the gallery
- Re-dragging the same photo produces a "Already uploaded as ..." toast

If anything regressed, the diff in `upload.py` is your bug.

- [ ] **Step 4: Commit**

```bash
git add backend/ingest.py backend/routers/upload.py
git commit -m "Extract upload byte-processing pipeline into shared ingest module"
git push
```

---

### Task 7: Import endpoint

**What this does:** Adds the import endpoint that lists picked items, downloads each, and feeds them through `ingest_bytes`. Per-item failures don't kill the batch.

**Files:**
- Modify: `backend/google_photos.py`
- Modify: `backend/routers/google.py`

- [ ] **Step 1: Add `list_session_media_items` and `download_media_item` to `GooglePhotosClient`**

Append to the class:

```python
    def list_session_media_items(self, session_id: str) -> list[dict]:
        """Return all picked media items for a session, paginating as needed."""
        items: list[dict] = []
        page_token: Optional[str] = None
        while True:
            params: dict = {"sessionId": session_id, "pageSize": 100}
            if page_token:
                params["pageToken"] = page_token
            resp = httpx.get(
                f"{self._PICKER_BASE}/mediaItems",
                headers=self._picker_headers(),
                params=params,
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("mediaItems", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return items

    def download_media_item(self, base_url: str) -> bytes:
        """Download original-resolution bytes for a Picker mediaItem."""
        # The "=d" suffix is the Picker convention for original bytes
        url = base_url + ("=d" if "=" not in base_url.rsplit("/", 1)[-1] else "")
        resp = httpx.get(
            url,
            headers=self._picker_headers(),
            timeout=120.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return resp.content
```

- [ ] **Step 2: Add the import endpoint to `backend/routers/google.py`**

Append:

```python
@router.post("/picker/session/{session_id}/import")
async def import_picked_media(session_id: str, x_upload_pin: str = Header(...)):
    """PIN-gated. Lists picked items, downloads each, ingests via the shared pipeline."""
    _verify_pin(x_upload_pin)
    from backend.ingest import ingest_bytes
    from backend.main import media_store, uploads_dir

    client = _get_client()

    try:
        items = client.list_session_media_items(session_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List picked items failed for session {session_id}: {e}")
        raise HTTPException(status_code=502, detail="Could not retrieve picked items")

    imported: list[dict] = []
    duplicates: list[dict] = []
    failed: list[dict] = []

    for picker_item in items:
        media_file = picker_item.get("mediaFile") or {}
        google_id = picker_item.get("id", "")
        base_url = media_file.get("baseUrl", "")
        mime_type = media_file.get("mimeType", "")
        filename = media_file.get("filename") or media_file.get("mediaFileMetadata", {}).get("filename") or "from-google-photos"

        if not base_url:
            failed.append({"google_id": google_id, "filename": filename, "reason": "no baseUrl"})
            continue

        try:
            content = client.download_media_item(base_url)
        except Exception as e:
            logger.warning(f"Download failed for {google_id}: {e}")
            failed.append({"google_id": google_id, "filename": filename, "reason": f"download error: {e}"})
            continue

        try:
            status, item = ingest_bytes(
                content=content,
                content_type=mime_type,
                original_name=filename,
                uploads_dir=uploads_dir,
                store=media_store,
            )
        except HTTPException as e:
            failed.append({"google_id": google_id, "filename": filename, "reason": e.detail})
            continue
        except Exception as e:
            logger.warning(f"Ingest failed for {google_id}: {e}")
            failed.append({"google_id": google_id, "filename": filename, "reason": f"processing error: {e}"})
            continue

        if status == "duplicate":
            duplicates.append({"google_id": google_id, "filename": filename, "existing_id": item["id"]})
        else:
            imported.append(item)

    # Best-effort session cleanup
    client.delete_picker_session(session_id)

    return {
        "imported": imported,
        "duplicates": duplicates,
        "failed": failed,
        "summary": {
            "imported": len(imported),
            "duplicates": len(duplicates),
            "failed": len(failed),
        },
    }
```

- [ ] **Step 3: End-to-end import test via curl + browser**

Create a fresh picker session:

```bash
curl -s -X POST -H "X-Upload-PIN: 5819" http://127.0.0.1:8007/api/google/picker/session
```

Open the `picker_uri` in your browser, pick 2-3 photos, confirm. Save the `session_id`.

Verify ready:

```bash
curl -s -H "X-Upload-PIN: 5819" http://127.0.0.1:8007/api/google/picker/session/SESSION_ID
```

Expected: `{"status":"ready"}`.

Run the import:

```bash
curl -s -X POST -H "X-Upload-PIN: 5819" http://127.0.0.1:8007/api/google/picker/session/SESSION_ID/import
```

Expected: a JSON response with `summary.imported` matching the count of photos you picked, `summary.duplicates: 0`, `summary.failed: 0`.

Verify gallery:

```bash
curl -s http://127.0.0.1:8007/api/media | python -c "import sys,json;d=json.load(sys.stdin);print(len(d),'items')"
```

The count should have increased by however many you imported. Open `http://127.0.0.1:8007/`, log in, switch to Gallery — the new photos should be visible at the top.

- [ ] **Step 4: Verify dedup**

Repeat Step 3 picking ONE of the same photos you just imported. The summary should report `imported: 0, duplicates: 1, failed: 0`. The gallery item count should be unchanged.

- [ ] **Step 5: Commit**

```bash
git add backend/google_photos.py backend/routers/google.py
git commit -m "Add Google Photos import endpoint that downloads and ingests picked items"
git push
```

---

### Task 8: Frontend integration

**What this does:** Adds the visible button on the Upload tab and wires the picker → poll → import flow.

**Files:**
- Create: `frontend/js/components/google_import.js`
- Modify: `frontend/index.html`
- Modify: `frontend/js/app.js`
- Modify: `frontend/js/api.js`

- [ ] **Step 1: Add Google API methods to `frontend/js/api.js`**

Append inside the `API` object (just before the closing `}`):

```javascript
    async googleStatus() {
        const resp = await fetch(`${Config.API_BASE}/google/status`);
        if (!resp.ok) throw new Error('Status fetch failed');
        return resp.json();
    },

    googleOAuthStartUrl() {
        // Browsers can't send custom headers on full-page navigation,
        // so the start endpoint must be hit via fetch and the resulting
        // redirect URL opened in a new window. We do this in google_import.js.
        return `${Config.API_BASE}/google/oauth/start`;
    },

    async googleCreatePickerSession() {
        const resp = await fetch(`${Config.API_BASE}/google/picker/session`, {
            method: 'POST',
            headers: { 'X-Upload-PIN': this.getPin() },
        });
        if (resp.status === 401) throw new Error('Google account not connected');
        if (resp.status === 403) { this.clearPin(); throw new Error('Invalid PIN'); }
        if (!resp.ok) throw new Error('Could not create picker session');
        return resp.json();
    },

    async googlePollPickerSession(sessionId) {
        const resp = await fetch(`${Config.API_BASE}/google/picker/session/${sessionId}`, {
            headers: { 'X-Upload-PIN': this.getPin() },
        });
        if (!resp.ok) throw new Error('Poll failed');
        return resp.json();
    },

    async googleImportPickerSession(sessionId) {
        const resp = await fetch(`${Config.API_BASE}/google/picker/session/${sessionId}/import`, {
            method: 'POST',
            headers: { 'X-Upload-PIN': this.getPin() },
        });
        if (!resp.ok) throw new Error('Import failed');
        return resp.json();
    },
```

- [ ] **Step 2: Add the button + state UI to `frontend/index.html`**

Replace the Upload tab block (lines 38-50 of the existing file) with:

```html
        <!-- Upload Tab -->
        <div id="tab-upload" class="tab-content active">
            <div id="drop-zone" class="drop-zone">
                <div class="drop-zone-content">
                    <div class="drop-icon">+</div>
                    <p>Tap to select or drag & drop</p>
                    <p class="drop-hint">Photos & videos up to 500MB</p>
                </div>
                <input type="file" id="file-input" multiple
                       accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm,video/x-matroska">
            </div>

            <div class="google-divider"><span>or</span></div>

            <button id="google-import-btn" class="btn btn-primary google-import-btn" hidden>
                <span id="google-import-btn-label">Loading...</span>
            </button>
            <div id="google-import-status" class="google-import-status hidden"></div>

            <div id="upload-queue" class="upload-queue"></div>
        </div>
```

Add the `google_import.js` script tag in the script block at the bottom, AFTER `upload.js` and BEFORE `app.js`:

```html
    <script src="/js/config.js"></script>
    <script src="/js/toast.js"></script>
    <script src="/js/api.js"></script>
    <script src="/js/components/upload.js"></script>
    <script src="/js/components/gallery.js"></script>
    <script src="/js/components/google_import.js"></script>
    <script src="/js/app.js"></script>
```

- [ ] **Step 3: Add minimal CSS for the new elements**

Append to `frontend/css/styles.css`:

```css
/* Google Photos import */
.google-divider {
    display: flex;
    align-items: center;
    margin: 1.5em 0;
    color: #888;
    font-size: 0.9em;
}
.google-divider::before,
.google-divider::after {
    content: '';
    flex: 1;
    border-bottom: 1px solid #ddd;
}
.google-divider span {
    padding: 0 1em;
}
.google-import-btn {
    width: 100%;
    margin-bottom: 1em;
}
.google-import-status {
    padding: 0.75em 1em;
    margin-bottom: 1em;
    background: #f4f6f8;
    border-radius: 6px;
    font-size: 0.9em;
}
.google-import-status.hidden { display: none; }
```

- [ ] **Step 4: Create `frontend/js/components/google_import.js`**

```javascript
/**
 * Google Photos import component — Upload-tab button, picker window, polling, ingest.
 */
const GoogleImport = {
    POLL_INTERVAL_MS: 3000,
    POLL_TIMEOUT_MS: 5 * 60 * 1000,

    async init() {
        this.btn = document.getElementById('google-import-btn');
        this.btnLabel = document.getElementById('google-import-btn-label');
        this.statusEl = document.getElementById('google-import-status');
        this.btn.addEventListener('click', () => this.onClick());

        // Listen for the OAuth callback page posting back via window.opener
        window.addEventListener('message', (e) => {
            if (e.data && e.data.type === 'google-oauth') {
                this.refreshState();
            }
        });

        await this.refreshState();
    },

    async refreshState() {
        try {
            const status = await API.googleStatus();
            this.btn.hidden = false;
            if (!status.authorized) {
                this.btnLabel.textContent = 'Connect Google Photos';
                this.mode = 'connect';
            } else if (status.expired) {
                this.btnLabel.textContent = 'Reconnect Google Photos';
                this.mode = 'reconnect';
            } else {
                this.btnLabel.textContent = '📷 Import from Google Photos';
                this.mode = 'import';
            }
        } catch (err) {
            console.error('Google status fetch failed:', err);
            this.btn.hidden = true;
        }
    },

    async onClick() {
        if (this.mode === 'connect' || this.mode === 'reconnect') {
            this.openOAuth();
        } else if (this.mode === 'import') {
            await this.startImport();
        }
    },

    openOAuth() {
        // window.open() cannot set custom headers, so we pass the PIN as a query param.
        // The backend's /oauth/start accepts ?pin= as an alternative to X-Upload-PIN (see Step 5).
        // The popup lands on Google's consent screen, then on our /oauth/callback page,
        // which closes itself and posts a message back to refresh button state.
        const url = `${API.googleOAuthStartUrl()}?pin=${encodeURIComponent(API.getPin())}`;
        window.open(url, 'gp_oauth', 'width=520,height=640');
    },

    async startImport() {
        this.statusEl.classList.remove('hidden');
        this.statusEl.textContent = 'Creating picker session...';
        let session;
        try {
            session = await API.googleCreatePickerSession();
        } catch (err) {
            this.statusEl.textContent = '';
            this.statusEl.classList.add('hidden');
            Toast.error(err.message);
            if (err.message.includes('not connected') || err.message.includes('expired')) {
                await this.refreshState();
            }
            return;
        }

        const popup = window.open(session.picker_uri, 'gp_picker', 'width=900,height=700');
        if (!popup) {
            Toast.error('Popup blocked — allow popups for this site and try again');
            this.statusEl.classList.add('hidden');
            return;
        }
        this.statusEl.textContent = 'Waiting for selection in Google Photos...';

        const ready = await this.pollUntilReady(session.session_id);
        if (!ready) {
            this.statusEl.textContent = '';
            this.statusEl.classList.add('hidden');
            Toast.error('Picker session expired or timed out');
            return;
        }

        this.statusEl.textContent = 'Importing... this may take a moment';
        try {
            const result = await API.googleImportPickerSession(session.session_id);
            this.statusEl.classList.add('hidden');
            const s = result.summary;
            const parts = [];
            if (s.imported) parts.push(`${s.imported} imported`);
            if (s.duplicates) parts.push(`${s.duplicates} duplicate${s.duplicates === 1 ? '' : 's'} skipped`);
            if (s.failed) parts.push(`${s.failed} failed`);
            Toast.success(parts.join(', ') || 'Nothing to import');

            // Refresh gallery if visible
            if (document.getElementById('tab-gallery').classList.contains('active')) {
                Gallery.load();
            }
        } catch (err) {
            this.statusEl.classList.add('hidden');
            Toast.error(err.message);
        }
    },

    async pollUntilReady(sessionId) {
        const start = Date.now();
        while (Date.now() - start < this.POLL_TIMEOUT_MS) {
            try {
                const result = await API.googlePollPickerSession(sessionId);
                if (result.status === 'ready') return true;
                if (result.status === 'expired') return false;
            } catch (err) {
                console.warn('poll error', err);
            }
            await new Promise(r => setTimeout(r, this.POLL_INTERVAL_MS));
        }
        return false;
    },
};
```

- [ ] **Step 5: Update `oauth/start` to also accept `?pin=` query param (browser popup workaround)**

This unblocks the popup OAuth flow since `window.open()` cannot set custom headers.

In `backend/routers/google.py`, replace the `oauth_start` function:

```python
@router.get("/oauth/start")
async def oauth_start(
    request: Request,
    pin: Optional[str] = None,
    x_upload_pin: Optional[str] = Header(None),
):
    """PIN-gated. Redirects to Google's consent screen.

    Accepts PIN via X-Upload-PIN header or ?pin= query param (the latter is needed
    for window.open() popups since browsers can't set headers on navigation).
    """
    pin_value = x_upload_pin or pin
    if not pin_value:
        raise HTTPException(status_code=403, detail="Missing PIN")
    _verify_pin(pin_value)
    _prune_states()
    redirect_uri = _redirect_uri_for(request)
    url, state = _get_client().start_oauth(redirect_uri)
    _oauth_states[state] = time.time() + _STATE_TTL_SECONDS
    return RedirectResponse(url)
```

- [ ] **Step 6: Wire `GoogleImport.init()` into `frontend/js/app.js`**

In the `init()` method of `App`, add `GoogleImport.init()` after `Gallery.init()`:

```javascript
    init() {
        Upload.init();
        Gallery.init();
        GoogleImport.init();
        this.bindEvents();

        const savedPin = API.getPin();
        if (savedPin) {
            this.enterApp();
        }
    },
```

- [ ] **Step 7: Browser verification**

Restart dev server. Open `http://127.0.0.1:8007/` (use a hard refresh: Ctrl-Shift-R). Log in with PIN.

Visual checks on the Upload tab:
- Drop zone is visible at top
- A "─── or ───" divider sits below it
- Below that, a button. If you completed Task 3-7 correctly with a working token, it reads "📷 Import from Google Photos". If you disconnected since, it reads "Connect Google Photos".

Click the button:
- **If "Connect Google Photos"**: a popup window opens to Google's consent screen. Authorize. Popup closes itself. Main page button updates to "📷 Import from Google Photos" without a refresh.
- **If "Import from Google Photos"**: a popup opens to the picker UI. Pick 1 photo. Click confirm. Popup closes. Main page shows "Importing..." then a green toast `1 imported`. Switch to Gallery tab — the photo is there.

- [ ] **Step 8: Commit**

```bash
git add backend/routers/google.py frontend/js/api.js frontend/js/components/google_import.js frontend/js/app.js frontend/index.html frontend/css/styles.css
git commit -m "Add Import from Google Photos button and picker flow to Upload tab"
git push
```

---

### Task 9: End-to-end smoke test on production server

**What this does:** Deploys the change and verifies the flow against `https://photos.2azone.com`. The "Testing" mode test-user list and the production redirect URI we set up in Task 1 should make this work without further GCP changes.

**Files:**
- No code changes. This is a deploy + manual QA task.

- [ ] **Step 1: Sanity-check the local working tree**

```bash
git status
```

Expected: working tree clean, branch up to date with origin/master.

- [ ] **Step 2: Deploy to webserver**

```bash
ssh webserver "cd /opt/skylight-photos && bash deploy/deploy.sh"
```

Expected: deploy.sh pulls the latest code, installs deps if needed, restarts systemd unit. The service should come back healthy.

Verify:

```bash
ssh webserver "sudo systemctl status skylight-photos-api --no-pager"
```

Expected: `active (running)`.

```bash
curl -s https://photos.2azone.com/health
```

Expected: `{"status":"healthy",...}`

- [ ] **Step 3: Update production `config/settings.json` with Google credentials**

The deploy script doesn't touch settings.json (it's gitignored). The production server needs its own copy with the same google_* keys you put in the local one in Task 1 Step 3.

```bash
ssh webserver "sudo cat /opt/skylight-photos/config/settings.json"
```

If the google_* keys are missing, edit them in. Use the editor on the server **only because settings.json is intentionally not in git** — this is the documented exception to the "never edit on servers" rule for genuinely server-local config:

```bash
ssh webserver "sudo nano /opt/skylight-photos/config/settings.json"
```

Add the three keys (`google_owner_email`, `google_client_id`, `google_client_secret`) with the same values from Task 1.

Then restart:

```bash
ssh webserver "sudo systemctl restart skylight-photos-api"
```

- [ ] **Step 4: Authorize against the production server**

Open `https://photos.2azone.com/`. Log in with PIN. The "Connect Google Photos" button should appear. Click it. Authorize as `brett@swaimdesign.com`. Popup should close with "Connected".

Verify:

```bash
curl -s https://photos.2azone.com/api/google/status
```

Expected: `{"authorized":true,...}`

- [ ] **Step 5: Import a photo from your phone**

Open `https://photos.2azone.com/` on your phone in a browser. Log in with PIN. Click "Import from Google Photos". Pick a recent photo from Google. Confirm.

Verify the toast says `1 imported`. Switch to Gallery — confirm the photo is at the top.

- [ ] **Step 6: Smoke-test dedup and disconnect on production**

Re-import the same photo: toast should say `0 imported, 1 duplicate skipped`.

Hit disconnect manually:

```bash
curl -s -X POST -H "X-Upload-PIN: 5819" https://photos.2azone.com/api/google/disconnect
```

Reload the UI: button should now read "Connect Google Photos".

- [ ] **Step 7: Reconnect and leave the system in a working state**

Click "Connect Google Photos" again, complete OAuth, verify button is back to "Import from Google Photos".

- [ ] **Step 8: Final commit (likely none — touch-ups only)**

If you discovered any bugs during E2E testing, fix them now and commit. Otherwise this task closes out the plan.

```bash
git status   # if clean, nothing to do
```

---

## Done.

Spec lives at `docs/superpowers/specs/2026-05-03-google-photos-integration-design.md`. Plan lives at `docs/superpowers/plans/2026-05-03-google-photos-integration.md`. The feature is live on `https://photos.2azone.com`.
