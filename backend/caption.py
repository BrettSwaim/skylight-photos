"""EXIF caption pipeline: extract date/GPS, reverse-geocode offline, draw overlay."""

import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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


STYLES = {"pill", "banner", "script", "classic"}
DEFAULT_STYLE = "pill"

_FONT_DIR = Path(__file__).resolve().parent / "fonts"
_SCRIPT_FONT = str(_FONT_DIR / "GreatVibes-Regular.ttf")


def build_caption_text(
    dt: Optional[datetime],
    latlon: Optional[Tuple[float, float]],
    place_override: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Return (place, date) strings, either possibly None.

    place_override (user-supplied location) beats GPS when present.
    """
    place = place_override or (reverse_geocode(*latlon) if latlon else None)
    date = dt.strftime("%m/%d/%Y") if dt else None
    return place, date


def build_caption(
    dt: Optional[datetime],
    latlon: Optional[Tuple[float, float]],
    place_override: Optional[str] = None,
) -> Optional[str]:
    """Compose caption text as one string; None when there is nothing to show."""
    place, date = build_caption_text(dt, latlon, place_override)
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


def _load_script_font(size: int):
    try:
        return ImageFont.truetype(_SCRIPT_FONT, size)
    except OSError:
        return _load_font(size)


def _one_line(place: Optional[str], date: Optional[str]) -> str:
    if place and date:
        return f"{place} {date}"
    return place or date or ""


def _draw_pin(draw, x, y, size, color=(234, 67, 53)):
    """Map pin: circular head, triangular tail, white center dot."""
    r = size // 2
    cx, cy = x + r, y + r
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    draw.polygon(
        [
            (cx - int(r * 0.62), cy + int(r * 0.55)),
            (cx + int(r * 0.62), cy + int(r * 0.55)),
            (cx, y + size + int(size * 0.45)),
        ],
        fill=color,
    )
    dr = max(2, r // 2)
    draw.ellipse([cx - dr, cy - dr, cx + dr, cy + dr], fill=(255, 255, 255))


def _place(iw, ih, bw, bh, pos, default):
    """Clamped top-left for a bw×bh caption box whose CENTER goes at pos.

    pos is normalized (px, py) in [0,1]; None → the style's default anchor.
    """
    if pos is None:
        return default
    px, py = pos
    x = int(px * iw - bw / 2)
    y = int(py * ih - bh / 2)
    x = max(0, min(x, iw - bw))
    y = max(0, min(y, ih - bh))
    return x, y


def _draw_classic(img: Image.Image, place, date, pos=None) -> Image.Image:
    """White text with dark offset shadow."""
    text = _one_line(place, date)
    draw = ImageDraw.Draw(img)
    size = max(16, int(img.height * 0.035))
    font = _load_font(size)
    pad = int(size * 0.8)
    bw = int(draw.textlength(text, font=font))
    bh = int(size * 1.3)
    x, y = _place(img.width, img.height, bw, bh, pos,
                  (pad, img.height - size - pad))
    off = max(1, size // 14)
    draw.text((x + off, y + off), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=(255, 255, 255))
    return img


def _draw_pill(img: Image.Image, place, date, pos=None) -> Image.Image:
    """White rounded sticker with red map pin — Instagram location tag."""
    line1 = place or date
    line2 = date if place else None  # if only date, it's line1
    size = int(img.height * 0.034)
    f1 = _load_font(size)
    f2 = _load_font(int(size * 0.82))
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    pin = int(size * 0.9)
    w1 = d.textlength(line1, font=f1)
    w2 = d.textlength(line2, font=f2) if line2 else 0
    pad = int(size * 0.55)
    gap = int(size * 0.45)
    two = line2 is not None
    pill_h = int(size * (2.6 if two else 1.9))
    pill_w = int(pin + gap + max(w1, w2) + pad * 2 + size * 0.4)
    margin = int(img.height * 0.028)
    x, y = _place(img.width, img.height, pill_w, pill_h, pos,
                  (margin, img.height - pill_h - margin))
    d.rounded_rectangle(
        [x, y, x + pill_w, y + pill_h], radius=pill_h // 2, fill=(255, 255, 255, 235)
    )
    px = x + pad
    py = y + (pill_h - int(pin * 1.45)) // 2
    _draw_pin(d, px, py, pin)
    tx = px + pin + gap
    if two:
        d.text((tx, y + int(pill_h * 0.16)), line1, font=f1, fill=(30, 30, 30, 255))
        d.text((tx, y + int(pill_h * 0.55)), line2, font=f2, fill=(110, 110, 110, 255))
    else:
        d.text((tx, y + (pill_h - size) // 2), line1, font=f1, fill=(30, 30, 30, 255))
    img = img.convert("RGBA")
    img.alpha_composite(overlay)
    return img.convert("RGB")


def _draw_banner(img: Image.Image, place, date, pos=None) -> Image.Image:
    """Semi-transparent full-width strip: place left, date right. pos moves it vertically."""
    size = int(img.height * 0.032)
    f = _load_font(size)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    bar_h = int(size * 2.4)
    # full-width: only vertical position matters
    _, y = _place(img.width, img.height, img.width, bar_h, pos,
                  (0, img.height - bar_h))
    d.rectangle([0, y, img.width, y + bar_h], fill=(0, 0, 0, 150))
    pad = int(size * 0.9)
    ty = y + (bar_h - size) // 2
    if place:
        pin = int(size * 0.95)
        _draw_pin(d, pad, y + (bar_h - int(pin * 1.45)) // 2, pin, color=(255, 255, 255))
        d.text((pad + pin + int(size * 0.5), ty), place, font=f, fill=(255, 255, 255, 255))
        if date:
            w2 = d.textlength(date, font=f)
            d.text((img.width - w2 - pad, ty), date, font=f, fill=(220, 220, 220, 255))
    elif date:
        d.text((pad, ty), date, font=f, fill=(255, 255, 255, 255))
    img = img.convert("RGBA")
    img.alpha_composite(overlay)
    return img.convert("RGB")


def _draw_script(img: Image.Image, place, date, pos=None) -> Image.Image:
    """Large handwritten place with blurred drop shadow, small date beneath."""
    line1 = place or date
    line2 = date if place else None
    size = int(img.height * 0.085)
    f = _load_script_font(size)
    f2 = _load_font(int(size * 0.28))
    measure = ImageDraw.Draw(img)
    w1 = int(measure.textlength(line1, font=f))
    bw = max(w1, int(size * 0.25) + (int(measure.textlength(line2, font=f2)) if line2 else 0))
    bh = int(size * 1.45) if line2 else int(size * 1.1)
    pad = int(img.height * 0.03)
    x, y = _place(img.width, img.height, bw, bh, pos,
                  (pad + int(size * 0.2), img.height - int(size * 1.45)))

    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.text((x + 3, y + 3), line1, font=f, fill=(0, 0, 0, 220))
    shadow = shadow.filter(ImageFilter.GaussianBlur(5))

    out = img.convert("RGBA")
    out.alpha_composite(shadow)
    d = ImageDraw.Draw(out)
    d.text((x, y), line1, font=f, fill=(255, 255, 255, 255))
    if line2:
        d.text((x + int(size * 0.25), y + int(size * 1.02)), line2,
               font=f2, fill=(235, 235, 235, 255))
    return out.convert("RGB")


_RENDERERS = {
    "classic": _draw_classic,
    "pill": _draw_pill,
    "banner": _draw_banner,
    "script": _draw_script,
}


def render_caption(
    img: Image.Image,
    place: Optional[str],
    date: Optional[str],
    style: str = DEFAULT_STYLE,
    pos: Optional[Tuple[float, float]] = None,
) -> Image.Image:
    """Draw the caption in the chosen style at pos. Unknown style falls back."""
    renderer = _RENDERERS.get(style, _RENDERERS[DEFAULT_STYLE])
    return renderer(img, place, date, pos)


def draw_caption(img: Image.Image, text: str) -> Image.Image:
    """Back-compat: draw a pre-composed single string in classic style."""
    return _draw_classic(img, text, None)
