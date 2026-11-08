"""Ticket branding helpers: colours and logo images. No web framework or database."""

import io
import re

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_UPLOAD_BYTES = 1024 * 1024  # an uploaded logo may be at most 1 MB
MAX_PIXELS = 25_000_000  # refuse absurdly large images before decoding them
MAX_SIDE = 600  # logos are shrunk to fit this many pixels; plenty for a ticket header


class InvalidLogo(ValueError):
    """The upload isn't a usable PNG or JPEG. The message is safe to show to the host."""


def normalize_hex(value: str) -> str | None:
    """'#5B4BDB ' -> '#5b4bdb'; None if it isn't a six-digit hex colour."""
    value = value.strip()
    return value.lower() if HEX_RE.match(value) else None


def _luminance(hex_color: str) -> float:
    def channel(index: int) -> float:
        c = int(hex_color[1 + 2 * index: 3 + 2 * index], 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2)


def on_color(hex_color: str) -> str:
    """Black or white, whichever is easier to read on top of this colour."""
    return "#000000" if _luminance(hex_color) > 0.179 else "#ffffff"


def process_logo(data: bytes) -> bytes:
    """Validate an uploaded logo and return it as a clean PNG no larger than MAX_SIDE pixels.

    Re-encoding drops any metadata and guarantees something reportlab and browsers can display.
    """
    from PIL import Image, UnidentifiedImageError  # Pillow ships with reportlab

    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("PNG", "JPEG"):
                raise InvalidLogo("Please use a PNG or JPEG image.")
            if image.width * image.height > MAX_PIXELS:
                raise InvalidLogo("That image has too many pixels. Please use a smaller one.")
            image.load()
            logo = image.convert("RGBA")
    except InvalidLogo:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise InvalidLogo("That file couldn't be read as an image.") from None
    logo.thumbnail((MAX_SIDE, MAX_SIDE))  # only ever shrinks, keeps the aspect ratio
    out = io.BytesIO()
    logo.save(out, "PNG", optimize=True)
    return out.getvalue()
