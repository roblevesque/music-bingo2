import io
import random
import re

import pytest
from PIL import Image

from app.services.branding import InvalidLogo, normalize_hex, on_color, process_logo
from app.services.pdf import BrandStyle, build_tickets_pdf


def image_bytes(fmt="PNG", size=(40, 20), color="red", mode="RGB"):
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, fmt)
    return out.getvalue()


def contrast(a, b):
    def lum(h):
        def ch(i):
            c = int(h[1 + 2 * i: 3 + 2 * i], 16) / 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * ch(0) + 0.7152 * ch(1) + 0.0722 * ch(2)
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("raw, expected", [("#5B4BDB", "#5b4bdb"), (" #abcdef ", "#abcdef"), ("5b4bdb", None),
                                           ("#fff", None), ("#gggggg", None), ("", None), ("#5b4bdb;x", None)])
def test_normalize_hex(raw, expected):
    assert normalize_hex(raw) == expected


def test_text_colour_is_always_readable():
    assert on_color("#ffffff") == "#000000" and on_color("#000000") == "#ffffff"
    rng = random.Random(3)
    for _ in range(300):
        colour = "#%06x" % rng.randrange(0x1000000)
        assert contrast(colour, on_color(colour)) >= 4.5, colour


def test_logo_is_normalised_to_a_png():
    png = process_logo(image_bytes("PNG"))
    assert Image.open(io.BytesIO(png)).format == "PNG"
    assert Image.open(io.BytesIO(process_logo(image_bytes("JPEG")))).format == "PNG"  # JPEG is re-encoded


def test_big_logos_are_shrunk_and_small_ones_left_alone():
    big = Image.open(io.BytesIO(process_logo(image_bytes(size=(2400, 1200)))))
    assert max(big.size) == 600 and big.size == (600, 300)  # aspect ratio kept
    small = Image.open(io.BytesIO(process_logo(image_bytes(size=(40, 20)))))
    assert small.size == (40, 20)


def test_transparency_is_kept():
    out = io.BytesIO()
    Image.new("RGBA", (10, 10), (255, 0, 0, 0)).save(out, "PNG")
    assert Image.open(io.BytesIO(process_logo(out.getvalue()))).getpixel((0, 0))[3] == 0


@pytest.mark.parametrize("data", [b"not an image", b"", b"<svg xmlns='http://www.w3.org/2000/svg'/>"])
def test_garbage_is_rejected(data):
    with pytest.raises(InvalidLogo):
        process_logo(data)


def test_other_image_formats_are_rejected():
    with pytest.raises(InvalidLogo):
        process_logo(image_bytes("GIF"))


def test_absurdly_large_images_are_rejected_before_decoding():
    with pytest.raises(InvalidLogo):
        process_logo(image_bytes(size=(5200, 5200), mode="L", color=0))


def sheets(count=2, size=3):
    return [(n, [(f"Song {n}-{i}", f"Artist {i}") for i in range(size * size)]) for n in range(1, count + 1)]


def pages(pdf):
    return len(re.findall(rb"/Type\s*/Page(?![a-z])", pdf))


@pytest.mark.parametrize("brand", [
    BrandStyle(),
    BrandStyle(accent="#5b4bdb"),
    BrandStyle(accent="#ffe066", header_text="Thursday Music Bingo", footer_text="The Rusty Anchor"),
    BrandStyle(footer_text="Only a footer"),
    BrandStyle(accent="#102030", header_text="\u65e5\u672c\u8a9e \u00f1", footer_text="\u00dcnicode \u2013 footer", logo_png=process_logo(image_bytes(size=(300, 100)))),
    BrandStyle(logo_png=process_logo(image_bytes(size=(10, 400)))),  # very tall logo
    BrandStyle(logo_png=b"definitely not a png"),  # a damaged logo must not stop printing
])
def test_pdf_builds_with_any_branding(brand):
    pdf = build_tickets_pdf("Pub Night", 3, sheets(3), per_page=2, brand=brand)
    assert pdf.startswith(b"%PDF") and pages(pdf) == 2


def test_a_logo_makes_the_pdf_bigger_and_unbranded_output_is_unchanged_in_shape():
    plain = build_tickets_pdf("Pub Night", 3, sheets(), per_page=2)
    with_logo = build_tickets_pdf("Pub Night", 3, sheets(), per_page=2,
                                  brand=BrandStyle(logo_png=process_logo(image_bytes(size=(300, 100), color="blue"))))
    assert len(with_logo) > len(plain) and pages(plain) == pages(with_logo) == 1
