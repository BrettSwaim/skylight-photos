# Skylight Uploader (Android APK) — Design

**Date:** 2026-07-19
**Status:** Approved

## Goal

Sideloadable Android app that uploads photos/videos to photos.2azone.com with
GPS EXIF intact, fixing the browser location-redaction problem so captions get
real locations automatically.

## Why an app

Android redacts GPS EXIF from every browser upload path (verified empirically
2026-07-19 on Pixel 10 Pro Fold). Native apps holding `ACCESS_MEDIA_LOCATION`
and reading via `MediaStore.setRequireOriginal()` receive unredacted originals.

## Decisions (confirmed with Brett)

- Phone uploader (frame slideshow APK is a possible later project).
- Photo entry: **both** an in-app camera-roll grid (guaranteed GPS) and a
  share-sheet target (GPS subject to Google Photos' hide-location setting).
- Server untouched — the app posts to the existing `/api/upload` with the
  `X-Upload-PIN` header; the existing caption pipeline handles the rest.

## Architecture

Location: `android/` inside the skylight-photos repo. Kotlin, classic Views
(no Compose), OkHttp + coroutines. minSdk 30, target 34. No third-party image
loader — thumbnails via `ContentResolver.loadThumbnail` + LruCache.

| Unit | Purpose |
|------|---------|
| `MainActivity` | Permission flow, MediaStore grid (images+videos, newest first), multi-select, Upload button. Receives ACTION_SEND / SEND_MULTIPLE and forwards to UploadActivity. |
| `UploadActivity` | Upload queue UI: per-file progress, Done / Already uploaded / Error + Retry, Retry all. |
| `Uploader` | Queue engine: 3 concurrent, auto-retry x2 with backoff for network/5xx, 409 = success ("Already uploaded"). Reads original bytes via `setRequireOriginal` (try/catch fallback to plain URI for share-target content). |
| `Api` | OkHttp calls: `POST /api/verify-pin`, `POST /api/upload` (multipart, PIN header, progress-tracking RequestBody). |
| `Prefs` | SharedPreferences: PIN. Server URL is a constant `https://photos.2azone.com`. |

Manifest: `INTERNET`, `READ_MEDIA_IMAGES`, `READ_MEDIA_VIDEO`,
`ACCESS_MEDIA_LOCATION`, plus `READ_EXTERNAL_STORAGE maxSdkVersion=32`.

## Build & distribution

- Built headlessly: JDK 21 (Microsoft, already installed), Gradle binary zip,
  Android SDK cmdline-tools in `%LOCALAPPDATA%\Android\Sdk`.
- Release APK signed with a keystore generated into `config/` (gitignored) so
  future builds update in place. Keystore password noted in the config dir.
- Published as `frontend/app.apk` (committed) → served at
  `https://photos.2azone.com/app.apk`; Brett sideloads by opening that URL.

## Verification

- Gradle `assembleRelease` succeeds; APK signature verified with apksigner.
- Upload path exercised against prod from a script (multipart with PIN).
- Final acceptance (on-phone, Brett): install, pick a trip photo in the grid,
  upload, gallery caption reads a real location (e.g. "Orvieto, Italy") with
  no manual location typed.

## Future (explicitly out of scope today)

- **Decorative caption styles** — Instagram/Creative Memories-style overlays
  (banners, script fonts, colored mats) selectable per batch instead of raw
  white text. Server-side: a `style` parameter to the caption renderer. Safe
  to iterate on since originals are never modified — items can be deleted and
  re-uploaded to re-render with a new style.
- Skylight MAX frame slideshow APK consuming `/api/media`.
