# Full-Screen Viewer on the Frame Tab — Design

**Date:** 2026-07-21
**Status:** Approved

## Goal

Tap a photo in the app's "On the Frame" tab to open a full-screen viewer;
swipe between photos; delete or re-style from there. Multi-select moves to
long-press.

## Decisions (confirmed with Brett)

- **Tap = full-screen view.** **Long-press = toggle select** (bulk delete/restyle
  unchanged, still driven by the bottom bar).
- Viewer shows the full image from `/api/media/{id}/file`, swipeable between all
  frame items. Videos play in the viewer.
- Per-photo **Delete** and **Re-style** actions live in the viewer too.

## Architecture

- `ManageAdapter`: tap → open viewer at that index; long-press → toggle selection
  (existing selection logic). Tap no longer selects.
- `FullScreenActivity` + `FullScreenAdapter` (ViewPager2):
  - Receives parallel arrays (ids, types, hasMaster, styles) + start index.
  - Image page: full-res via `UrlImageLoader.loadFull` (separate larger cache).
  - Video page: `VideoView` with controls.
  - Overlay buttons: **Delete** (confirm → delete → remove page / close if last),
    **Re-style** (images with master only → style chooser → restyle → reload page
    cache-busted).
- `UrlImageLoader.loadFull(url)`: decode ~1600px, own small LruCache, bypasses the
  400px thumb cache.
- `ManageActivity.onResume` reloads the grid so viewer edits reflect on return.
- Dependency: `androidx.viewpager2:viewpager2:1.1.0`.

## Passing data

MediaItem isn't Parcelable → pass `ArrayList<String>` ids + types + styles and a
`BooleanArray` hasMaster + `Int` start index. Viewer rebuilds MediaItems; fileUrl
derives from id.

## Testing

- Build + sign + serve v1.7.
- On-phone (Brett): tap opens full view; swipe works; delete removes and returns;
  re-style updates the shown image; long-press still multi-selects in the grid.

## Out of scope

- Pinch-zoom in the viewer.
- Repositioning caption from the viewer (restyle keeps stored position).
