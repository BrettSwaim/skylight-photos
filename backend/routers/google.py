"""Google Photos endpoints — OAuth, status, picker, import."""

import html
import logging
import threading
import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.config import get_config_value

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/google", tags=["google"])

# In-memory CSRF state store: {state: (expires_at_unix, pkce_code_verifier)}
_oauth_states: dict[str, tuple[float, str]] = {}
_states_lock = threading.Lock()
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
    with _states_lock:
        expired = [s for s, (exp, _v) in _oauth_states.items() if exp < now]
        for s in expired:
            _oauth_states.pop(s, None)


def _store_state(state: str, code_verifier: str):
    with _states_lock:
        _oauth_states[state] = (time.time() + _STATE_TTL_SECONDS, code_verifier)


def _consume_state(state: str) -> Optional[tuple[float, str]]:
    with _states_lock:
        return _oauth_states.pop(state, None)


@router.get("/status")
async def google_status():
    """Public — returns button state info."""
    return _get_client().get_status()


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
    url, state, code_verifier = _get_client().start_oauth(redirect_uri)
    _store_state(state, code_verifier)
    return RedirectResponse(url)


@router.get("/oauth/callback", name="oauth_callback")
async def oauth_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """Receives Google's redirect. State-protected, no PIN required."""
    if error:
        return HTMLResponse(_callback_html(False, f"Google returned an error: {error}"), status_code=400)
    if not code or not state:
        return HTMLResponse(_callback_html(False, "Missing code or state"), status_code=400)

    _prune_states()
    entry = _consume_state(state)
    if entry is None or entry[0] < time.time():
        return HTMLResponse(_callback_html(False, "Authorization session expired — please try again"), status_code=400)
    _expires, code_verifier = entry

    redirect_uri = _redirect_uri_for(request)
    ok, message = _get_client().complete_oauth(code, redirect_uri, code_verifier=code_verifier)
    status_code = 200 if ok else 403
    return HTMLResponse(_callback_html(ok, message), status_code=status_code)


def _callback_html(ok: bool, message: str) -> str:
    """Tiny HTML page shown to the user after OAuth completes (or fails)."""
    color = "#0a7" if ok else "#a30"
    title = "Connected" if ok else "Authorization failed"
    safe_message = html.escape(message)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: system-ui; max-width: 480px; margin: 4em auto; padding: 1em; text-align: center; }}
h1 {{ color: {color}; }}
button {{ font-size: 1em; padding: 0.5em 1em; cursor: pointer; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p>{safe_message}</p>
<button onclick="window.close()">Close window</button>
<script>
  // If opened as a popup, the parent will detect closure and refresh status
  if (window.opener) {{ try {{ window.opener.postMessage({{ type: 'google-oauth', ok: {str(ok).lower()} }}, '*'); }} catch(e) {{}} }}
</script>
</body>
</html>"""


@router.post("/disconnect")
async def disconnect(x_upload_pin: str = Header(...)):
    """PIN-gated. Revokes the refresh token at Google and deletes local token."""
    _verify_pin(x_upload_pin)
    revoked = _get_client().disconnect()
    return {"status": "ok", "revoked_at_google": revoked}


def _parse_poll_interval(raw, default: int = 3) -> int:
    """Parse Google's pollInterval (e.g. '3s', '3.5s'). Falls back to default on anything weird."""
    if not raw:
        return default
    try:
        return max(1, int(float(str(raw).rstrip("s"))))
    except (ValueError, TypeError):
        return default


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

    session_id = session.get("id")
    picker_uri = session.get("pickerUri")
    if not session_id or not picker_uri:
        logger.error(f"Picker session response missing fields: {list(session.keys())}")
        raise HTTPException(status_code=502, detail="Unexpected Google Picker response")

    return {
        "session_id": session_id,
        "picker_uri": picker_uri,
        "polling_interval_seconds": _parse_poll_interval(
            session.get("pollingConfig", {}).get("pollInterval")
        ),
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


@router.post("/picker/session/{session_id}/import")
def import_picked_media(session_id: str, x_upload_pin: str = Header(...)):
    """PIN-gated. Lists picked items, downloads each, ingests via the shared pipeline.

    Synchronous on purpose: the body uses blocking httpx + Pillow + ffmpeg and can run for
    minutes. Declaring this as ``def`` lets FastAPI dispatch it on the threadpool so the
    event loop stays responsive for status polls and gallery loads during a batch import.
    """
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
