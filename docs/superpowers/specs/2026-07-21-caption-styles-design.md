# Decorative Caption Styles — Design

**Date:** 2026-07-21
**Status:** Approved

## Goal

Replace the single plain-white-text caption with selectable decorative styles
(pill sticker, banner, script), chosen per upload batch from the Android app
and web UI. Instagram / Creative Memories feel.

## Decisions (confirmed with Brett)

- Ship three styles: **pill** (default), **banner**, **script**. Polaroid and
  classic-only are dropped from the picker; classic remains an internal
  fallback.
- Default when unspecified: **pill**.
- Script sample's shadow was too weak — use a blurred drop-shadow layer.
- Re-styling existing photos = delete + re-upload (originals untouched). A
  server-side bulk re-style tool is explicitly out of scope.

## Architecture

`backend/caption.py` refactor — split text-building from drawing:

| Function | Purpose |
|----------|---------|
| `build_caption_text(dt, latlon, place_override)` | Returns `(place, date)` tuple of strings-or-None (renamed from build_caption; the combined text is now the renderer's job). |
| `render_caption(img, place, date, style)` | Dispatcher → `_draw_pill` / `_draw_banner` / `_draw_script` / `_draw_classic`. Unknown/blank style → pill. Returns the (possibly new) image. |
| `_draw_pill/_banner/_script/_classic` | One self-contained renderer each. Each takes `(img, place, date)` and returns an image. |

Renderers must handle date-only (place=None) and place-only gracefully.

`STYLES = {"pill", "banner", "script", "classic"}`; `DEFAULT_STYLE = "pill"`.

## Data flow

`upload.py` gains a `style` Form field (mirrors existing `location`):
`upload_media → ingest_bytes(style=...) → _process_image(style=...) →
render_caption(...)`. Chosen style stored on the media item as `caption_style`.

Web `api.js uploadFile` adds `style` to the multipart form; the upload page
gets a style `<select>` (Pill/Banner/Script) remembered in localStorage.

Android: a horizontal chip row (Pill/Banner/Script) on the upload/main screen;
selection stored in Prefs, sent as the `style` form part. App → v1.3.

## Fonts

Committed under `backend/fonts/` (deployed with the app):
- `GreatVibes-Regular.ttf` — script style.
- Pill/banner use Arial Bold (Windows) / DejaVu Sans Bold (Linux) via the
  existing FONT_CANDIDATES fallback list.
Map-pin icon drawn in code (`_draw_pin`), no image asset.

## Testing

- Unit (standalone `tests/test_caption.py`): each of pill/banner/script
  produces distinct non-blank pixels for place+date and for date-only; unknown
  style falls back without error; `caption_style` stored on the item.
- Prod e2e: upload one GPS+location image per style, pull processed file back,
  verify the style rendered; delete test items after.

## Out of scope (future)

- Server-side "re-style existing photos" batch endpoint.
- Polaroid / additional styles (dispatcher makes adding trivial later).
