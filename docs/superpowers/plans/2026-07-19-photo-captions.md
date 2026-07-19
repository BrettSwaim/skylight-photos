# Photo Captions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Burn "City, Country MM/DD/YYYY" captions onto photos at ingest, sourced from EXIF GPS + date, so the Skylight frame displays them.

**Architecture:** New `backend/caption.py` module (EXIF extraction from original bytes, offline reverse geocoding, Pillow text drawing) called from `_process_image` in `backend/ingest.py` between resize and save. Caption failures never fail an upload. Caption text stored on the media item.

**Tech Stack:** Python 3.10, Pillow, `reverse_geocoder` (offline GeoNames), `pycountry`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-19-photo-captions-design.md`
- Caption rules: place + date → `"Montepulciano, Italy 06/01/2026"`; GPS missing → date only; date missing → place only; neither → no caption.
- Date format `MM/DD/YYYY` from EXIF `DateTimeOriginal` (0x9003 in Exif IFD 0x8769), fallback `DateTime` (0x0132).
- Placement bottom-left: white text, dark offset shadow, font size `max(16, int(img.height * 0.035))`, padding `int(size * 0.8)`.
- Font: DejaVu Sans Bold on Linux, Arial Bold on Windows dev, PIL default as last resort.
- `reverse_geocoder` MUST be called with `mode=1` (single-process — mode 2 spawns multiprocessing workers, which breaks under uvicorn).
- Captioning is wrapped in try/except; on any error, log a warning and save the photo clean.
- Videos untouched. No test framework exists — tests are standalone `python tests/test_caption.py` scripts with asserts.
- Commit convention: descriptive message + Claude co-author trailer (see repo history).

---

### Task 1: `backend/caption.py` with standalone test

**Files:**
- Create: `backend/caption.py`
- Test: `tests/test_caption.py`

**Interfaces:**
- Produces: `extract_exif_info(content: bytes) -> tuple[Optional[datetime], Optional[tuple[float, float]]]`
- Produces: `build_caption(dt: Optional[datetime], latlon: Optional[tuple[float, float]]) -> Optional[str]`
- Produces: `draw_caption(img: PIL.Image.Image, text: str) -> PIL.Image.Image` (mutates and returns img)

- [ ] **Step 1: Install deps locally for testing**

```bash
python -m pip install reverse_geocoder pycountry Pillow
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_caption.py
"""Standalone tests: python tests/test_caption.py"""
import io
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
from backend.caption import _to_deg, build_caption, draw_caption, extract_exif_info


def test_to_deg():
    assert abs(_to_deg((43.0, 5.0, 33.36), "N") - 43.0926) < 0.001
    assert _to_deg((43.0, 5.0, 33.36), "S") < 0


def test_extract_date_only():
    img = Image.new("RGB", (100, 80), (10, 20, 30))
    exif = Image.Exif()
    exif[0x0132] = "2026:06:01 14:00:00"
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    dt, latlon = extract_exif_info(buf.getvalue())
    assert dt == datetime(2026, 6, 1, 14, 0, 0)
    assert latlon is None


def test_extract_no_exif():
    img = Image.new("RGB", (100, 80), (10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    dt, latlon = extract_exif_info(buf.getvalue())
    assert dt is None
    assert latlon is None


def test_build_caption_montepulciano():
    # Montepulciano, Italy
    text = build_caption(datetime(2026, 6, 1), (43.0926, 11.7868))
    assert text == "Montepulciano, Italy 06/01/2026", text


def test_build_caption_date_only():
    assert build_caption(datetime(2026, 6, 1), None) == "06/01/2026"


def test_build_caption_none():
    assert build_caption(None, None) is None


def test_draw_caption_changes_pixels():
    img = Image.new("RGB", (800, 600), (0, 0, 0))
    before = list(img.getdata())[:1000]
    draw_caption(img, "Montepulciano, Italy 06/01/2026")
    # bottom-left region must now contain white pixels
    px = img.crop((0, 500, 400, 600))
    assert any(p == (255, 255, 255) for p in px.getdata())


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("All tests passed")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python tests/test_caption.py`
Expected: `ModuleNotFoundError: No module named 'backend.caption'`

- [ ] **Step 4: Write the implementation**

```python
# backend/caption.py
"""EXIF caption pipeline: extract date/GPS, reverse-geocode offline, draw overlay."""

import io
import logging
from datetime import datetime
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]

EXIF_IFD = 0x8769
GPS_IFD = 0x8825
TAG_DATETIME_ORIGINAL = 0x9003
TAG_DATETIME = 0x0132


def _to_deg(dms, ref) -> float:
    """Convert EXIF (deg, min, sec) rationals + hemisphere ref to signed degrees."""
    deg = float(dms[0]) + float(dms[1]) / 60 + float(dms[2]) / 3600
    return -deg if ref in ("S", "W") else deg


def extract_exif_info(content: bytes) -> Tuple[Optional[datetime], Optional[Tuple[float, float]]]:
    """Read shot datetime and GPS lat/lon from original image bytes."""
    dt = None
    latlon = None
    try:
        with Image.open(io.BytesIO(content)) as img:
            exif = img.getexif()

            date_str = None
            try:
                date_str = exif.get_ifd(EXIF_IFD).get(TAG_DATETIME_ORIGINAL)
            except Exception:
                pass
            if not date_str:
                date_str = exif.get(TAG_DATETIME)
            if date_str:
                try:
                    dt = datetime.strptime(str(date_str).strip(), "%Y:%m:%d %H:%M:%S")
                except ValueError:
                    pass

            try:
                gps = exif.get_ifd(GPS_IFD)
                lat, lat_ref = gps.get(2), gps.get(1)
                lon, lon_ref = gps.get(4), gps.get(3)
                if lat and lon and lat_ref and lon_ref:
                    latlon = (_to_deg(lat, lat_ref), _to_deg(lon, lon_ref))
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"EXIF extraction failed: {e}")
    return dt, latlon


def reverse_geocode(lat: float, lon: float) -> Optional[str]:
    """Coordinates -> 'City, Country' using the offline GeoNames dataset."""
    try:
        import pycountry
        import reverse_geocoder

        # mode=1: single-process — required under uvicorn
        res = reverse_geocoder.search([(lat, lon)], mode=1)[0]
        city = res.get("name")
        country = None
        cc = res.get("cc")
        if cc:
            entry = pycountry.countries.get(alpha_2=cc)
            country = entry.name if entry else cc
        if city and country:
            return f"{city}, {country}"
        return city or country
    except Exception as e:
        logger.warning(f"Reverse geocode failed for ({lat}, {lon}): {e}")
        return None


def build_caption(dt: Optional[datetime], latlon: Optional[Tuple[float, float]]) -> Optional[str]:
    """Compose caption text per spec; None when there is nothing to show."""
    place = reverse_geocode(*latlon) if latlon else None
    date = dt.strftime("%m/%d/%Y") if dt else None
    if place and date:
        return f"{place} {date}"
    return place or date


def _load_font(size: int):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_caption(img: Image.Image, text: str) -> Image.Image:
    """Draw white text with a dark offset shadow in the bottom-left corner."""
    draw = ImageDraw.Draw(img)
    size = max(16, int(img.height * 0.035))
    font = _load_font(size)
    pad = int(size * 0.8)
    x = pad
    y = img.height - size - pad
    offset = max(1, size // 14)
    draw.text((x + offset, y + offset), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=(255, 255, 255))
    return img
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python tests/test_caption.py`
Expected: `PASS` for all 7 tests, `All tests passed`

- [ ] **Step 6: Commit**

```bash
git add backend/caption.py tests/test_caption.py
git commit -m "Add caption module: EXIF extract, offline geocode, Pillow overlay"
```

---

### Task 2: Wire captions into ingest + store caption field

**Files:**
- Modify: `backend/ingest.py` (`_process_image` signature and body, `ingest_bytes` image branch and `store.add` call)
- Modify: `backend/media.py:35-55` (`MediaStore.add` — new `caption` kwarg)
- Test: extend `tests/test_caption.py` with an ingest integration test

**Interfaces:**
- Consumes: `extract_exif_info`, `build_caption`, `draw_caption` from Task 1.
- Produces: `_process_image(content, dest) -> tuple[int, int, int, Optional[str]]` (width, height, size_bytes, caption); media items gain a `"caption"` key.

- [ ] **Step 1: Write the failing integration test** (append to `tests/test_caption.py`)

```python
def test_ingest_burns_caption(tmp_dir=None):
    import tempfile
    from backend.ingest import ingest_bytes
    from backend.media import MediaStore

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        img = Image.new("RGB", (800, 600), (0, 0, 0))
        exif = Image.Exif()
        exif[0x0132] = "2026:06:01 14:00:00"
        buf = io.BytesIO()
        img.save(buf, "JPEG", exif=exif)

        store = MediaStore(td)
        status, item = ingest_bytes(
            content=buf.getvalue(),
            content_type="image/jpeg",
            original_name="t.jpg",
            uploads_dir=td,
            store=store,
        )
        assert status == "added"
        assert item["caption"] == "06/01/2026", item
        # caption pixels present in saved file
        with Image.open(td / item["filename"]) as saved:
            px = saved.crop((0, 500, 400, 600))
            assert any(p[0] > 240 and p[1] > 240 and p[2] > 240 for p in px.getdata())
```

(Also add `test_ingest_burns_caption()` to the `__main__` runner — it is picked up automatically by the `globals()` loop.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_caption.py`
Expected: `KeyError: 'caption'` (or assert failure) in `test_ingest_burns_caption`

- [ ] **Step 3: Implement**

In `backend/media.py`, add the kwarg and item key:

```python
    def add(self, filename: str, original_name: str, media_type: str,
            width: Optional[int] = None, height: Optional[int] = None,
            size_bytes: int = 0, duration: Optional[float] = None,
            content_sha256: Optional[str] = None,
            caption: Optional[str] = None) -> dict:
        """Add a media item and return its metadata."""
        item = {
            "id": uuid4().hex[:12],
            "filename": filename,
            "original_name": original_name,
            "media_type": media_type,  # "image" or "video"
            "width": width,
            "height": height,
            "size_bytes": size_bytes,
            "duration": duration,
            "content_sha256": content_sha256,
            "caption": caption,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
```

In `backend/ingest.py`:

1. Add import at top: `from backend.caption import build_caption, draw_caption, extract_exif_info`
2. Replace `_process_image` with:

```python
def _process_image(content: bytes, dest: Path) -> Tuple[int, int, int, Optional[str]]:
    """Process and save an image. Returns (width, height, bytes_on_disk, caption)."""
    with Image.open(io.BytesIO(content)) as src:
        img = src.convert("RGB") if src.mode != "RGB" else src.copy()

    try:
        exif = img._getexif()
        if exif:
            for tag, val in exif.items():
                if ExifTags.TAGS.get(tag) == "Orientation":
                    if val == 3:
                        img = img.rotate(180, expand=True)
                    elif val == 6:
                        img = img.rotate(270, expand=True)
                    elif val == 8:
                        img = img.rotate(90, expand=True)
                    break
    except (AttributeError, KeyError):
        pass

    width, height = img.size
    if width > MAX_WIDTH or height > MAX_HEIGHT:
        img.thumbnail((MAX_WIDTH, MAX_HEIGHT), Image.LANCZOS)
        width, height = img.size

    caption = None
    try:
        dt, latlon = extract_exif_info(content)
        caption = build_caption(dt, latlon)
        if caption:
            draw_caption(img, caption)
    except Exception as e:
        logger.warning(f"Captioning failed, saving clean: {e}")
        caption = None

    img.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True)
    img.close()
    return width, height, dest.stat().st_size, caption
```

3. In `ingest_bytes`, image branch: change

```python
            width, height, size_bytes = _process_image(content, filepath)
```

to

```python
            width, height, size_bytes, caption = _process_image(content, filepath)
```

initialize `caption: Optional[str] = None` next to the `width`/`height` declarations (so the video branch has it defined), and pass `caption=caption` to `store.add(...)`.

- [ ] **Step 4: Run all tests to verify they pass**

Run: `python tests/test_caption.py`
Expected: all PASS including `test_ingest_burns_caption`

- [ ] **Step 5: Commit**

```bash
git add backend/ingest.py backend/media.py tests/test_caption.py
git commit -m "Burn EXIF location/date caption onto images at ingest"
```

---

### Task 3: Dependencies, deploy, prod e2e verification

**Files:**
- Modify: `requirements.txt` (append `reverse_geocoder>=1.5.1` and `pycountry>=23.12.11`)

**Interfaces:**
- Consumes: everything above; deploy script installs requirements into the server venv.

- [ ] **Step 1: Add dependencies**

Append to `requirements.txt`:

```
reverse_geocoder>=1.5.1
pycountry>=23.12.11
```

- [ ] **Step 2: Commit and push**

```bash
git add requirements.txt
git commit -m "Add reverse_geocoder and pycountry for photo captions"
git push
```

- [ ] **Step 3: Deploy**

Run: `ssh webserver "cd /opt/skylight-photos && bash deploy/deploy.sh"`
Expected: pip installs the two new packages; service restarts clean. Then:
`ssh webserver "sudo systemctl is-active skylight-photos-api && curl -s localhost:8007/health"`
Expected: `active` and healthy JSON.

- [ ] **Step 4: Prod e2e — GPS photo**

Create a GPS-tagged JPEG (Montepulciano coords) in the scratchpad, upload via the real UI with Playwright (PIN 5819), then download the processed file via `/api/media/{id}/file` and confirm the caption text "Montepulciano, Italy" is visibly rendered (read the image back). Also upload a plain no-EXIF image and confirm it saves with `caption: null` and no overlay. Delete both test items afterward via `DELETE /api/media/{id}` with the PIN header.

- [ ] **Step 5: Final verification + push**

Run: `python tests/test_caption.py` one final time locally; `git push`. Report results with the downloaded prod image as evidence.
