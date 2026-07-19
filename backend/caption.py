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


def build_caption(
    dt: Optional[datetime],
    latlon: Optional[Tuple[float, float]],
    place_override: Optional[str] = None,
) -> Optional[str]:
    """Compose caption text; None when there is nothing to show.

    place_override (user-supplied location) beats GPS when present.
    """
    place = place_override or (reverse_geocode(*latlon) if latlon else None)
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
