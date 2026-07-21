"""Standalone tests: python tests/test_caption.py"""
import io
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
from backend.caption import (
    _to_deg,
    build_caption,
    build_caption_text,
    draw_caption,
    extract_exif_info,
    render_caption,
)


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


def test_build_caption_place_override():
    text = build_caption(datetime(2026, 7, 19), None, place_override="Orvieto, Italy")
    assert text == "Orvieto, Italy 07/19/2026", text
    # override wins even when GPS is present
    text = build_caption(None, (43.0926, 11.7868), place_override="Custom Place")
    assert text == "Custom Place", text


def _has_bright_pixels(img, region=None):
    px = img.crop(region) if region else img
    return any(p[0] > 230 and p[1] > 230 and p[2] > 230 for p in px.getdata())


def test_each_style_renders_place_and_date():
    for style in ("pill", "banner", "script", "classic"):
        img = Image.new("RGB", (1000, 750), (40, 40, 40))
        out = render_caption(img, "Orvieto, Italy", "07/19/2026", style=style)
        assert out.size[0] >= 1000  # not blanked/broken
        assert _has_bright_pixels(out, (0, 500, 1000, 750)), f"{style} drew nothing"


def test_each_style_renders_date_only():
    for style in ("pill", "banner", "script", "classic"):
        img = Image.new("RGB", (1000, 750), (40, 40, 40))
        out = render_caption(img, None, "07/19/2026", style=style)
        assert _has_bright_pixels(out, (0, 500, 1000, 750)), f"{style} date-only drew nothing"


def test_unknown_style_falls_back():
    img = Image.new("RGB", (1000, 750), (40, 40, 40))
    out = render_caption(img, "Orvieto, Italy", "07/19/2026", style="nonsense")
    assert _has_bright_pixels(out, (0, 500, 1000, 750))


def test_build_caption_text_tuple():
    place, date = build_caption_text(datetime(2026, 7, 19), None, place_override="Orvieto")
    assert place == "Orvieto" and date == "07/19/2026"


def test_ingest_stores_style():
    import tempfile
    from backend.ingest import ingest_bytes
    from backend.media import MediaStore

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        img = Image.new("RGB", (800, 600), (0, 0, 0))
        exif = Image.Exif()
        exif[0x0132] = "2026:07:19 14:00:00"
        buf = io.BytesIO()
        img.save(buf, "JPEG", exif=exif)
        store = MediaStore(td)
        _, item = ingest_bytes(
            content=buf.getvalue(), content_type="image/jpeg",
            original_name="s.jpg", uploads_dir=td, store=store,
            place_override="Orvieto, Italy", style="banner",
        )
        assert item["caption_style"] == "banner", item


def test_ingest_writes_master_and_display():
    import tempfile
    from backend.ingest import ingest_bytes
    from backend.media import MediaStore

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        img = Image.new("RGB", (900, 700), (0, 0, 0))
        exif = Image.Exif()
        exif[0x0132] = "2026:07:19 14:00:00"
        buf = io.BytesIO()
        img.save(buf, "JPEG", exif=exif)
        store = MediaStore(td)
        _, item = ingest_bytes(
            content=buf.getvalue(), content_type="image/jpeg",
            original_name="m.jpg", uploads_dir=td, store=store,
            place_override="Orvieto, Italy", style="pill",
        )
        assert item["master_filename"], item
        assert item["caption_place"] == "Orvieto, Italy"
        assert item["caption_date"] == "07/19/2026"
        master = Image.open(td / item["master_filename"])
        display = Image.open(td / item["filename"])
        # master clean (no bright caption pixels bottom), display has them
        def bright(im):
            px = im.crop((0, int(im.height * 0.8), im.width, im.height))
            return sum(1 for p in px.getdata() if p[0] > 230 and p[1] > 230 and p[2] > 230)
        assert bright(master) == 0, "master should have no caption"
        assert bright(display) > 0, "display should show caption"


def test_restyle_rewrites_display():
    import tempfile
    from backend.ingest import ingest_bytes, restyle_display
    from backend.media import MediaStore

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        img = Image.new("RGB", (900, 700), (0, 0, 0))
        exif = Image.Exif()
        exif[0x0132] = "2026:07:19 14:00:00"
        buf = io.BytesIO()
        img.save(buf, "JPEG", exif=exif)
        store = MediaStore(td)
        _, item = ingest_bytes(
            content=buf.getvalue(), content_type="image/jpeg",
            original_name="r.jpg", uploads_dir=td, store=store,
            place_override="Orvieto, Italy", style="pill",
        )
        dest = td / item["filename"]
        before = dest.read_bytes()
        caption = restyle_display(
            td / item["master_filename"], dest,
            item["caption_place"], item["caption_date"], "script",
        )
        after = dest.read_bytes()
        assert caption == "Orvieto, Italy 07/19/2026"
        assert before != after, "display file should change after restyle"


def test_render_preview_returns_jpeg():
    from backend.ingest import render_preview
    img = Image.new("RGB", (900, 700), (10, 20, 30))
    exif = Image.Exif()
    exif[0x0132] = "2026:07:19 14:00:00"
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    out = render_preview(buf.getvalue(), "Orvieto, Italy", "banner")
    assert out[:2] == b"\xff\xd8", "should be JPEG bytes"
    assert len(out) > 1000


def test_ingest_place_override():
    import tempfile
    from backend.ingest import ingest_bytes
    from backend.media import MediaStore

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        img = Image.new("RGB", (800, 600), (0, 0, 0))
        exif = Image.Exif()
        exif[0x0132] = "2026:07:19 14:00:00"
        buf = io.BytesIO()
        img.save(buf, "JPEG", exif=exif)

        store = MediaStore(td)
        status, item = ingest_bytes(
            content=buf.getvalue(),
            content_type="image/jpeg",
            original_name="o.jpg",
            uploads_dir=td,
            store=store,
            place_override="Orvieto, Italy",
        )
        assert status == "added"
        assert item["caption"] == "Orvieto, Italy 07/19/2026", item


def test_draw_caption_changes_pixels():
    img = Image.new("RGB", (800, 600), (0, 0, 0))
    draw_caption(img, "Montepulciano, Italy 06/01/2026")
    # bottom-left region must now contain white pixels
    px = img.crop((0, 500, 400, 600))
    assert any(p == (255, 255, 255) for p in px.getdata())


def test_ingest_burns_caption():
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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("All tests passed")
