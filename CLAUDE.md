# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Skylight Photos is a self-hosted photo/video upload service for the **Skylight MAX digital picture frame**. It provides a PIN-protected web UI for uploading media and a REST API consumable by a Skylight APK. Deployed at `https://photos.2azone.com`.

## Tech Stack

- **Backend:** Python 3.10+ / FastAPI / Uvicorn / Pillow
- **Frontend:** Vanilla HTML/CSS/JS (no build tools, no framework, no Node.js)
- **Storage:** Flat-file JSON (`uploads/media.json`) + files on disk in `uploads/`
- **No database** — `MediaStore` class handles thread-safe JSON read/write with `threading.Lock`

## Development Commands

```bash
# Setup (one-time)
cp config/settings.example.json config/settings.json
python -m venv venv
venv/Scripts/pip install -r requirements.txt   # Windows
venv/bin/pip install -r requirements.txt       # Linux

# Run dev server
PYTHONPATH=. venv/Scripts/uvicorn backend.main:app --reload --port 8007   # Windows
PYTHONPATH=. venv/bin/uvicorn backend.main:app --reload --port 8007       # Linux

# Deploy to server
ssh webserver "cd /opt/skylight-photos && bash deploy/deploy.sh"

# Server management
sudo systemctl status|restart skylight-photos-api
sudo journalctl -u skylight-photos-api -f
```

No test suite exists. No linter is configured.

## Architecture

### Backend (`backend/`)

- `main.py` — FastAPI app entry point. Creates the `MediaStore` singleton (`media_store`), mounts routers under `/api`, serves `uploads/` and `frontend/` as static files.
- `config.py` — Loads `config/settings.json` with `lru_cache`. Only `pin` is actively read at runtime; image processing constants are hard-coded in `upload.py`.
- `media.py` — `MediaStore` class: thread-safe JSON-backed metadata store for uploaded media items.
- `routers/upload.py` — `POST /api/upload` (multipart), `DELETE /api/media/{id}`. Images are auto-rotated via EXIF, resized to max 2560x1440, re-encoded as JPEG quality 85. Videos stored as-is.
- `routers/media.py` — `GET /api/media`, `GET /api/media/{id}`, `GET /api/media/{id}/file`, `POST /api/verify-pin`.

### Frontend (`frontend/`)

Single-page app with two screens (PIN entry → main app with Upload/Gallery tabs).

**JS load order matters:** `config.js` → `toast.js` → `api.js` → `upload.js` → `gallery.js` → `app.js`

- `Config` — constants (API_BASE, allowed MIME types, max file size)
- `API` — all fetch/XHR calls; PIN stored in `localStorage` as `skylight_pin`, sent via `X-Upload-PIN` header
- `Upload` — drag-drop + file picker with per-file XHR progress bars (uses XMLHttpRequest, not fetch, for progress events)
- `Gallery` — grid view with lightbox modal and delete-with-confirm
- `App` — root controller wiring PIN flow, tabs, logout; auto-logs-out on 403

### Key Design Decisions

- **No CORS issues in production** — frontend and API served from same origin. CORS middleware exists for APK access.
- **Circular import avoidance** — routers import `media_store` and `uploads_dir` from `backend.main` inside functions, not at module level.
- **PIN auth model** — PIN is validated server-side, cached client-side in localStorage. Only upload and delete require PIN (reads are public).

## API Routes

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/verify-pin` | — | Validate PIN |
| POST | `/api/upload` | `X-Upload-PIN` | Upload file (multipart `file` field) |
| GET | `/api/media` | — | List all media |
| GET | `/api/media/{id}` | — | Get item metadata |
| GET | `/api/media/{id}/file` | — | Serve actual file |
| DELETE | `/api/media/{id}` | `X-Upload-PIN` | Delete item + file |
| GET | `/health` | — | Health check |

## Configuration

`config/settings.json` (gitignored, create from `config/settings.example.json`):
```json
{
    "pin": "1234",
    "max_upload_mb": 500,
    "image_max_width": 2560,
    "image_max_height": 1440,
    "jpeg_quality": 85
}
```

**Note:** Only `pin` is read from config at runtime. Image processing values are hard-coded in `upload.py`.

## Deployment

- **Server:** webserver (192.168.1.50), deployed to `/opt/skylight-photos`
- **Service:** systemd unit `skylight-photos-api.service` (uvicorn on `127.0.0.1:8007`)
- **Proxy:** Nginx reverse proxy with Let's Encrypt HTTPS
- **PYTHONPATH** must be set to the project root for `backend.*` imports to resolve (handled by systemd unit)
