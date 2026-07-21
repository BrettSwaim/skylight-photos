# Style Preview + Frame Management — Design

**Date:** 2026-07-21
**Status:** Approved

## Goal

Two app-only features: (1) preview a caption style on your photo before
uploading; (2) manage photos already on the frame — bulk delete and re-style.

## Decisions (confirmed with Brett)

- **App only.** Web gallery unchanged.
- Management ops: **bulk select + delete** AND **re-style in place**.
- Preview is **exact** (server-side render), not an on-device approximation.

## Part 1 — Preview

Backend: `POST /api/preview` (PIN-gated via X-Upload-PIN).
- Multipart: `file` (image), `style`, `location` (optional).
- Runs the real pipeline: EXIF extract → build_caption_text → render_caption
  on a downscaled copy. Returns `image/jpeg` bytes. **Saves nothing.**
- Videos / unstyleable input → 400.

App: after selecting photos, a **Preview** button opens PreviewActivity showing
the first selected photo rendered, with Pill/Banner/Script tabs to compare.
Choosing a tab sets the active style (Prefs) then returns to upload. App
downsizes to ~1000px before POSTing to keep the round-trip fast.

## Part 2 — Manage

### Master-image storage (enables re-style)

Ingest change: `_process_image` saves TWO files —
- **master**: rotated + resized, **no caption** → `{uid}.master.jpg`
- **display**: master + caption → `{uid}.jpg` (unchanged name; frame serves this)

Store on the media item: `master_filename`, `caption_place`, `caption_date`,
plus existing `caption_style`. Delete removes both files.

Pre-existing items have no `master_filename` → re-style unavailable (graceful).

### Re-style endpoint

`POST /api/media/{id}/restyle` (PIN-gated), body `{style}`.
- 404 if id unknown; 409 if no master (pre-master photo).
- Re-render display from master + stored place/date + new style, overwrite the
  display file, update `caption` + `caption_style`. Return updated item.

### App "On the Frame" tab

- Bottom nav / tab switch between "Upload" and "On the Frame".
- Grid of `/api/media` thumbnails (served from `/api/media/{id}/file`), newest
  first, date headers.
- Multi-select → **Delete (n)** (one confirm, loop existing DELETE with progress).
- Per-item / selected **Re-style** → style chooser → calls restyle endpoint;
  disabled with a note for items lacking a master.

## Backend files touched

- `routers/media.py` — add `/preview` is upload-domain; put preview in
  `routers/upload.py` (shares ingest imports). Restyle in `routers/media.py`.
- `ingest.py` — master + display split; return/persist master name + place/date.
- `media.py` — new item fields; `delete` unlinks master too.
- `caption.py` — no change (already exposes render_caption).

## Testing

- Unit (`tests/test_caption.py` / new `tests/test_ingest_master.py`): ingest
  writes master + display; master has no caption pixels, display does; restyle
  swaps style and rewrites display; delete removes both files.
- Prod e2e: preview all three styles on a real photo; upload; re-style it to a
  different style and confirm the served file changed; bulk-delete test items.

## Out of scope

- Re-styling pre-master (legacy) photos.
- Web parity for preview/manage.
