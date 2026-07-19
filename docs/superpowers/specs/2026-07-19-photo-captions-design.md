# Photo Captions at Ingest — Design

**Date:** 2026-07-19
**Status:** Approved

## Goal

Burn a location + date caption (e.g. `Montepulciano, Italy 06/01/2026`) onto photos
at upload time, sourced from EXIF, so the Skylight frame displays it with zero
frame-side changes.

## Decisions (confirmed with Brett)

- **No GPS →** date-only caption. No date either → no caption.
- **Images only.** Videos untouched.
- **Always on.** No upload-time toggle.
- **Placement:** bottom-left, white bold text with dark soft shadow.
- **Geocoding:** offline via `reverse_geocoder` (GeoNames city db) + `pycountry`
  for country names. No network calls at ingest.

## Architecture

New module `backend/caption.py`:

| Function | Purpose |
|----------|---------|
| `extract_exif_info(content: bytes)` | Parse original upload bytes → (`datetime` or None, `(lat, lon)` or None). Reads `DateTimeOriginal` (fallback `DateTime`) and the GPS IFD. |
| `build_caption(dt, latlon)` | Reverse-geocode + format → `"City, Country MM/DD/YYYY"`, `"MM/DD/YYYY"`, `"City, Country"`, or None. |
| `draw_caption(img, text)` | Draw bottom-left on a PIL image. Font size ≈ 3.5% of image height, min 16px. DejaVu Sans Bold (server); fall back to PIL default if missing. Dark offset shadow for legibility. |

`ingest.py` `_process_image` changes:

1. Accepts the original `content` bytes (it already receives them).
2. After EXIF rotate + resize, before `img.save`: extract → build → draw.
3. Entire caption step wrapped in try/except — a caption failure logs a warning
   and saves the photo clean. Uploads never fail because of captioning.
4. Returns the caption text; `ingest_bytes` stores it as a `caption` field on
   the media item in `media.json`.

## Data notes

- EXIF must be read from the **original bytes** — the Pillow re-encode discards it.
- Google Photos imports: Google strips GPS from API downloads → these get
  date-only captions automatically. Direct uploads keep GPS.
- Existing uploads (pre-feature) lost their EXIF at re-encode and cannot be
  captioned retroactively. Recovery path: delete + re-upload originals.
- EXIF dates are local time as shot — formatted as-is, `MM/DD/YYYY`.

## Dependencies

- `reverse_geocoder` (pulls numpy/scipy) — offline nearest-city lookup.
- `pycountry` — ISO country code → display name.

## Testing

- Standalone script test for `caption.py` (EXIF extraction + caption formatting)
  with a synthetic GPS-tagged JPEG.
- Prod e2e: upload a GPS-tagged photo via the UI, download the processed file,
  verify the caption visually; upload a no-EXIF image, verify date-only/clean.
