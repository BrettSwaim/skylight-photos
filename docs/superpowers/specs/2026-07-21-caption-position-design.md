# Drag-to-Position Captions — Design

**Date:** 2026-07-21
**Status:** Approved

## Goal

Let the user drag the caption to any spot on each photo from the preview
screen, per photo, and have the server render it there. Position is preserved
through re-style.

## Decisions (confirmed with Brett)

- **Free drag**, **per photo**.
- Preview screen steps through all selected photos; dragging is optional
  (skip = default position for that photo).
- Style stays batch-level; only position is per-photo.
- Web upload keeps fixed positions (app is the primary path).

## Position model

Normalized center `(px, py)`, each in [0,1], = where the caption box's CENTER
sits. Renderer computes its own box size, positions center at `(px*W, py*H)`,
then clamps so the whole box stays on-image. `pos=None` → current default
anchor per style. Banner is full-width: `px` ignored, `py` sets bar center.

## Backend

- `caption.py`: `render_caption(img, place, date, style, pos=None)` and each
  `_draw_*` gains `pos`. Helper `_place_box(img, box_w, box_h, pos, default_xy)`
  returns clamped top-left. Renderers compute box, then draw at that origin.
- `ingest.render_preview(..., pos)` and `_process_image(..., pos)` /
  `restyle_display(..., pos)` thread it through.
- `/api/preview` and `/api/upload` (upload.py): optional `pos_x`, `pos_y` Form
  floats. Parsed, clamped to [0,1], passed down.
- `/api/media/{id}/restyle`: uses stored `caption_pos_x/y` (position preserved;
  re-style changes only the look).
- `media.py`: store `caption_pos_x`, `caption_pos_y` on items.

## App (v1.5)

`PreviewActivity` reworked to a per-photo positioner:
- Receives the full selected URI list + index.
- Shows photo i with "i/N" and Next/Done. Style tabs still set batch style.
- **Drag:** ACTION_DOWN → swap to locally-decoded clean photo + draw a caption
  "ghost" proxy at current pos; ACTION_MOVE → move ghost; ACTION_UP → compute
  normalized center, call `/api/preview` with pos, show exact render, hide ghost.
- Per-photo position kept in a map; Done returns it (result Intent: uri→"x,y").
- MainActivity stores positions, passes to UploadActivity → Uploader → upload
  with `pos_x/pos_y` per job. No preview / skipped photo → no pos (server default).

`Api.preview` / `Api.upload` gain optional pos params (omit when null).

## Testing

- Unit (`tests/test_caption.py`): renderer draws caption near a requested
  center; clamps at extreme pos (0,0 and 1,1) so bright caption pixels stay
  within bounds; restyle preserves stored pos.
- Endpoint: preview with pos_x/pos_y returns image; upload stores pos.
- On-phone (Brett): drag caption on 2-3 photos, upload, confirm placement.

## Out of scope

- Repositioning from the "On the Frame" manage screen (restyle keeps stored pos).
- Web drag positioning.
- Per-photo style.
