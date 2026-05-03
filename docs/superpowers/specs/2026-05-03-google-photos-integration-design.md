# Google Photos Integration — Design

**Date:** 2026-05-03
**Status:** Approved (pending spec review)
**Owner:** Brett Swaim

## Goal

Let the owner pull photos and videos from their Google Photos library into Skylight without downloading them locally first. The current flow forces a download-then-upload round trip; this replaces it with an in-app picker.

## Non-goals

- A search box inside Skylight that queries Google Photos. The Google Photos Library API was restricted in 2025 to app-created content only, so programmatic search of the user's library is no longer possible. The Picker API (Google-hosted UI) is the only sanctioned path.
- Multi-user identity. Skylight is a single-PIN app and stays that way. "Owner" is a single hardcoded identity, not a user system.
- Background sync of Google albums into Skylight. This is a manual, picker-driven import every time.

## Threat model

The realistic threat is **a casual house guest who has the upload PIN**. The guest must not be able to use the import feature to browse the owner's broader Google Photos library.

Two complementary defenses, neither implemented by us:

1. **Owner-email allowlist on OAuth callback.** A guest who clicks "Connect Google Photos" and authorizes with their own Google account is rejected at the callback — we never store their token, the existing token is untouched.
2. **Google's own picker-session login enforcement.** The Picker UI requires the browser session to be logged in as the same Google account that authorized the picker session. A guest in their own browser hits Google's login screen and cannot proceed without the owner's Google password.

**Out of scope for this design:** A guest who has physical access to a browser already logged into the owner's Google account. That is a Google-session compromise, not a Skylight one.

## Architecture

```
Browser                          Skylight backend                 Google
   │                                  │                              │
   │ click "Import from Google"       │                              │
   │ (PIN already validated)          │                              │
   ├──── POST /api/google/picker/session ───▶                        │
   │                                  ├──── refresh access token ───▶│
   │                                  │◄────────── token ────────────│
   │                                  ├──── POST /v1/sessions ──────▶│
   │                                  │◄──── pickerUri, session_id ──│
   │◄──── pickerUri, session_id ──────┤                              │
   │                                  │                              │
   ├─ window.open(pickerUri) ─────────┼─────────────────────────────▶│
   │                                  │                              │ (user picks
   │ poll every 3s:                   │                              │  photos in
   ├──── GET /picker/session/{id} ───▶│                              │  Google's UI)
   │                                  ├──── GET /v1/sessions/{id} ──▶│
   │                                  │◄──── mediaItemsSet=true ─────│
   │◄──── status: ready ──────────────┤                              │
   │                                  │                              │
   ├──── POST /picker/session/{id}/import ─▶                         │
   │                                  ├──── list mediaItems ────────▶│
   │                                  │◄──── items[] ────────────────│
   │                                  │ for each item:               │
   │                                  │   GET baseUrl?d ────────────▶│
   │                                  │◄──── original bytes ─────────│
   │                                  │   sha256 → dedup check       │
   │                                  │   Pillow/ffmpeg pipeline     │
   │                                  │   MediaStore.add()           │
   │◄──── per-item results ───────────┤                              │
```

The defining choice: **imported bytes go through the same `upload.py` pipeline as a manually uploaded file.** Pillow EXIF rotation, 2560×1440 resize, JPEG q85 re-encode, ffmpeg audio strip, and the SHA-256 dedup check all reuse without modification. One pipeline, one set of guarantees.

## OAuth setup (one-time, manual)

The owner does this in Google Cloud Console:

1. Create a GCP project (or reuse one).
2. Enable the **Photos Picker API**.
3. Configure OAuth consent screen → User Type **External**, publishing status **Testing**, add `brett@swaimdesign.com` as a test user.
4. Create OAuth 2.0 credentials, type **Web application**.
   - Authorized redirect URI: `https://photos.2azone.com/api/google/oauth/callback`
5. Save the `client_id` and `client_secret` into `config/settings.json`.

`config/settings.json` gains three new fields:

```json
{
    "pin": "5819",
    "google_owner_email": "brett@swaimdesign.com",
    "google_client_id": "xxxx.apps.googleusercontent.com",
    "google_client_secret": "GOCSPX-xxxx"
}
```

`config/settings.example.json` gains the same fields with placeholder values.

### Token expiry

Apps in "Testing" status get refresh tokens that **expire after 7 days** of inactivity. The decision is to live with this and reconnect manually when needed. The button state machine surfaces the expiry as **"Reconnect Google Photos"** when the refresh fails.

### OAuth callback owner-email check

After exchanging the code for tokens, the backend calls Google's `https://www.googleapis.com/oauth2/v3/userinfo` endpoint with the access token, retrieves the `email` claim, and compares it case-insensitively to `google_owner_email`. Mismatch → discard tokens, return HTTP 403 with a clear message ("This app is owned by someone else"). Match → persist tokens.

## Token storage

Single file at `config/google_token.json` (gitignored, mode 0600), sibling to `settings.json` so it survives deploys (which only touch the code tree). Schema:

```json
{
    "refresh_token": "1//...",
    "access_token": "ya29...",
    "access_token_expires_at": "2026-05-03T17:42:00Z",
    "owner_email": "brett@swaimdesign.com",
    "connected_at": "2026-05-03T16:42:00Z"
}
```

Reads/writes are guarded by a `threading.Lock` (same pattern as `MediaStore`). The file is owned by the systemd service user; nginx and other system users have no read access.

## API endpoints

All `/api/google/*` endpoints except `GET /api/google/status` and `GET /api/google/oauth/callback` require `X-Upload-PIN`. The picker and import endpoints return HTTP 401 with `{"detail": "Google account not connected"}` if no token is stored, and HTTP 401 with `{"detail": "Google authorization expired, please reconnect"}` if the refresh token is no longer valid. `oauth/start` always works (PIN-gated) — it is the way to (re)authorize and must not depend on token state.

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/google/status` | — | Returns `{authorized, expired, owner_email}` for button state |
| GET | `/api/google/oauth/start` | PIN | Redirects to Google consent screen |
| GET | `/api/google/oauth/callback` | — (state-protected) | Receives Google's redirect, validates owner email, persists tokens |
| POST | `/api/google/disconnect` | PIN | Revokes the refresh token at Google, then deletes the local token file |
| POST | `/api/google/picker/session` | PIN | Creates a picker session, returns `{picker_uri, session_id}` |
| GET | `/api/google/picker/session/{id}` | PIN | Polls session — returns `{status: pending\|ready\|expired}` |
| POST | `/api/google/picker/session/{id}/import` | PIN | Downloads and ingests selected items, returns per-item results |
| DELETE | `/api/google/picker/session/{id}` | PIN | Tells Google to delete the session |

The OAuth callback uses a CSRF `state` parameter generated server-side, stored in a short-lived in-memory dict keyed by state value, expired after 10 minutes. The state is the gate; no PIN header is required because the redirect comes from Google, not the user's frontend code.

## Import semantics

**Per-item processing loop:**
1. Download `baseUrl + "=d"` for original bytes (Picker URL convention; without `=d` you get a thumbnail).
2. Hash raw bytes (SHA-256). Look up in `MediaStore.find_by_hash`. If duplicate, record as duplicate, skip to next item — *do not* save bytes to disk.
3. Otherwise, route by MIME type into the existing pipeline:
   - Image: Pillow open, EXIF auto-rotate, resize to 2560×1440 max, save as JPEG q85.
   - Video: ffmpeg audio strip, save as-is.
4. `MediaStore.add(content_sha256=hash, ...)`.
5. Append result to the response array.

**Failure handling:** Per-item failures (download error, corrupt image, ffmpeg crash) log a warning and continue. The endpoint always returns 200 with a structured result:

```json
{
    "imported": 49,
    "duplicates": 1,
    "failed": [
        {"google_id": "...", "filename": "video.mov", "reason": "ffmpeg timeout"}
    ]
}
```

**One-shot constraint:** Picker baseUrls expire after 60 minutes, and the picker session can only be queried for selected items while it exists. We download each item to disk *before* moving to the next — a mid-batch crash loses only the in-flight item, not the queue. We do not retry within a single import call; the user re-picks if needed.

**Concurrency:** No queue, no background worker. The import POST blocks until the full batch is processed. Acceptable for the few-dozen-photo case; revisit if usage patterns change.

**Session cleanup:** After a successful import, the backend issues `DELETE /v1/sessions/{id}` to Google. If the import endpoint crashes before cleanup, sessions auto-expire after 24 hours on Google's side.

## Frontend changes

**Upload tab gains one button** below the drop zone, separated by a visual `─── or ───` divider. State machine driven by `GET /api/google/status`:

| Backend state | Button label | Behavior on click |
|---------------|--------------|-------------------|
| `authorized: false` | **"Connect Google Photos"** | `window.open('/api/google/oauth/start', '_blank')` |
| `authorized: true, expired: false` | **"Import from Google Photos"** 📷 | Opens picker session |
| `authorized: true, expired: true` | **"Reconnect Google Photos"** ⚠ | Reuses Connect flow; replaces token on success |

**Import flow on the frontend:**
1. POST to `/api/google/picker/session`, get `{picker_uri, session_id}`.
2. `window.open(picker_uri, 'gp_picker', 'width=900,height=700')`.
3. Show a small inline panel above the upload queue: "Waiting for selection in Google Photos..."
4. Poll `GET /api/google/picker/session/{id}` every 3 seconds. Stop polling on `ready` or after 5 minutes (timeout shows an error toast).
5. On `ready`, panel changes to "Importing N items..."
6. POST to `/import`. Each per-item success prepends a "done" item to the upload queue (reuse the existing `Upload.createQueueItem` component).
7. Final toast: `Imported 49, 1 duplicate skipped, 0 failed`.

No changes to the PIN screen, Gallery tab, or any existing route.

## File / module layout

**New files:**
- `backend/google_photos.py` — `GooglePhotosClient` class. Token store (load/save/lock), OAuth helpers, Picker REST client, owner-email check.
- `backend/routers/google.py` — the eight endpoints listed above. Thin wrapper that calls into `GooglePhotosClient`.
- `frontend/js/components/google_import.js` — button state, picker window management, polling loop, import call.

**Modified files:**
- `backend/main.py` — register the new router.
- `backend/config.py` — already supports arbitrary keys via `get_config_value`; no code change needed, just new keys at runtime.
- `config/settings.example.json` — add the three new fields with placeholder values.
- `frontend/index.html` — load `google_import.js` after `upload.js`; add the button + divider markup to the Upload tab.
- `frontend/js/components/app.js` — call `GoogleImport.init()` after `Upload.init()`.
- `requirements.txt` — add `google-auth`, `google-auth-oauthlib`, `httpx`.
- `.gitignore` — add `config/google_token.json`.

**Unchanged:** `backend/media.py`, `backend/routers/upload.py`, `backend/routers/media.py`, the systemd unit, the Nginx config, the deploy script.

## Dependencies

| Package | Why |
|---------|-----|
| `google-auth>=2.0` | Refresh token mechanics, credential object lifecycle |
| `google-auth-oauthlib>=1.0` | Authorization URL building, code-for-token exchange |
| `httpx>=0.25` | Picker REST API calls (no official Python SDK exists for the Picker API) |

All three are pip-installable, no system packages required.

## Open questions / future work

- **Bulk album mirror.** Out of scope for this iteration. The Picker API does support album-scoped sessions, so this could be added later as a "Mirror album" feature without redesigning anything.
- **Production OAuth status without verification.** If weekly reconnect becomes annoying, the app can be moved to "Production" status (no verification), which makes refresh tokens persistent. Trade-off: a one-time scary "unverified app" warning during authorization. Decision deferred until the pain is real.
- **Per-item resumability.** Currently a mid-batch crash forces re-picking the lost item. If this becomes a real issue (large batches, flaky network), we could persist the picked-item list in the picker session row before downloading, and offer a "resume" path. Not worth building speculatively.
