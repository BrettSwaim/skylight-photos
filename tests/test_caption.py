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
