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
async def oauth_start(request: Request, x_upload_pin: str = Header(...)):
    """PIN-gated. Redirects to Google's consent screen."""
    _verify_pin(x_upload_pin)
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
