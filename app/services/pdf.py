"""Printable ticket sheets: every ticket of a game in one PDF, each with its number.

Pure layout code (no database or web imports): it is handed plain data and returns bytes.
"""

from dataclasses import dataclass
from io import BytesIO

from reportlab.lib.colors import HexColor, black, gray
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from app.services.branding import on_color

PAPER_SIZES = {"letter": letter, "a4": A4}
TICKETS_PER_PAGE = {1: (1, 1), 2: (1, 2), 4: (2, 2)}  # per page -> (columns, rows)

PAGE_MARGIN = 28
TICKET_INSET = 8  # space between a ticket and the cut line around it
HEADER_HEIGHT = 26
FOOTER_HEIGHT = 16
LEADING = 1.15
MIN_FONT = 5.0


@dataclass(frozen=True)
class BrandStyle:
    """The host's ticket branding. Every part is optional."""

    accent: str | None = None  # "#rrggbb": header band and square borders
    header_text: str = ""  # shown instead of the game name
    footer_text: str = ""
    logo_png: bytes | None = None  # already validated by services.branding.process_logo


@dataclass(frozen=True)
class Fonts:
    regular: str = "Helvetica"
    bold: str = "Helvetica-Bold"
    unicode: bool = False  # the built-in fonts only cover Western European text


def load_fonts(regular_path: str | None = None, bold_path: str | None = None) -> Fonts:
    """Use the built-in fonts, or a TrueType font the host supplies for other alphabets."""
    if not regular_path:
        return Fonts()
    from reportlab.pdfbase.ttfonts import TTFont

    pdfmetrics.registerFont(TTFont("TicketFont", regular_path))
    bold = "TicketFont"
    if bold_path:
        pdfmetrics.registerFont(TTFont("TicketFont-Bold", bold_path))
        bold = "TicketFont-Bold"
    return Fonts("TicketFont", bold, unicode=True)


def printable(text: str, fonts: Fonts) -> str:
    """Characters the font can't draw would come out as black boxes, so show '?' instead."""
    text = " ".join(text.split())
    return text if fonts.unicode else text.encode("cp1252", "replace").decode("cp1252")


def fit_text(text: str, font: str, max_size: float, width: float, height: float):
    """Largest font size (down to MIN_FONT) at which the wrapped text fits the box.

    Returns (size, lines). If even the smallest size is too tall the text is cut with an ellipsis.
    """
    size = max_size
    while size >= MIN_FONT:
        lines = simpleSplit(text, font, size, width)
        fits_height = len(lines) * size * LEADING <= height
        fits_width = all(pdfmetrics.stringWidth(line, font, size) <= width for line in lines)
        if fits_height and fits_width:
            return size, lines
        size -= 0.5
    size = MIN_FONT
    lines = simpleSplit(text, font, size, width)
    room = max(1, int(height // (size * LEADING)))
    if len(lines) > room:
        lines = lines[:room]
        lines[-1] = shorten(lines[-1] + "\u2026", font, size, width)
    return size, [shorten(line, font, size, width) for line in lines]


def shorten(text: str, font: str, size: float, width: float) -> str:
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "\u2026", font, size) > width:
        text = text[:-1]
    return text + "\u2026"


def _draw_cell(c, x, y, w, h, title, artist, fonts, border):
    c.setStrokeColor(border)
    c.setFillColor(black)
    c.setLineWidth(0.6)
    c.rect(x, y, w, h)
    pad = 3
    inner_w, inner_h = w - 2 * pad, h - 2 * pad
    title_size, title_lines = fit_text(title, fonts.bold, min(14, w / 5), inner_w, inner_h * 0.66)
    artist_size, artist_lines = 0, []
    if artist:
        artist_size, artist_lines = fit_text(artist, fonts.regular, max(MIN_FONT, title_size - 1), inner_w, inner_h * 0.3)
    gap = 2 if artist_lines else 0
    block = len(title_lines) * title_size * LEADING + gap + len(artist_lines) * artist_size * LEADING
    cursor = y + h / 2 + block / 2  # top of the text block, which is centred in the cell
    centre = x + w / 2
    for font, size, lines in ((fonts.bold, title_size, title_lines), (fonts.regular, artist_size, artist_lines)):
        for line in lines:
            cursor -= size * LEADING
            c.setFont(font, size)
            c.drawCentredString(centre, cursor + size * 0.28, line)
        cursor -= gap


def _draw_ticket(c, x, y, w, h, *, game_name, number, size, cells, fonts, brand, logo):
    """Draw one ticket in the box whose lower-left corner is (x, y)."""
    accent = HexColor(brand.accent) if brand.accent else None
    ink = HexColor(on_color(brand.accent)) if accent else black
    top = y + h
    if accent:
        c.setFillColor(accent)
        c.rect(x, top - HEADER_HEIGHT, w, HEADER_HEIGHT, stroke=0, fill=1)
    c.setFillColor(ink)

    left = x + 4
    if logo is not None:
        logo_w, logo_h = logo.getSize()
        height = HEADER_HEIGHT - 6
        width = min(height * logo_w / logo_h, w * 0.35)
        height = width * logo_h / logo_w
        c.drawImage(logo, left, top - HEADER_HEIGHT + (HEADER_HEIGHT - height) / 2, width=width, height=height, mask="auto")
        left += width + 6

    number_text = f"Ticket {number}"
    number_width = pdfmetrics.stringWidth(number_text, fonts.bold, 14)
    c.setFont(fonts.bold, 12)
    title = printable(brand.header_text, fonts) or game_name
    c.drawString(left, top - HEADER_HEIGHT + 8, shorten(title, fonts.bold, 12, x + w - number_width - 12 - left))
    c.setFont(fonts.bold, 14)
    c.drawRightString(x + w - 4, top - HEADER_HEIGHT + 8, number_text)

    footer = printable(brand.footer_text, fonts)
    grid_bottom = y + (FOOTER_HEIGHT if footer else 0)
    if footer:
        c.setFillColor(gray)
        c.setFont(fonts.regular, 8)
        c.drawCentredString(x + w / 2, y + 4, shorten(footer, fonts.regular, 8, w - 8))

    grid_top = top - HEADER_HEIGHT
    cell_w = w / size
    cell_h = (grid_top - grid_bottom) / size
    border = accent if accent else black
    for row in range(size):
        for col in range(size):
            title_text, artist = cells[row * size + col]
            _draw_cell(
                c, x + col * cell_w, grid_top - (row + 1) * cell_h, cell_w, cell_h,
                printable(title_text, fonts), printable(artist, fonts), fonts, border,
            )


def _draw_cut_lines(c, page_w, page_h, cols, rows, slot_w, slot_h):
    c.saveState()
    c.setDash(3, 3)
    c.setLineWidth(0.4)
    c.setStrokeGray(0.5)
    for col in range(1, cols):
        x = PAGE_MARGIN + col * slot_w
        c.line(x, 0, x, page_h)
    for row in range(1, rows):
        y = page_h - PAGE_MARGIN - row * slot_h
        c.line(0, y, page_w, y)
    c.restoreState()


def build_tickets_pdf(
    game_name: str,
    size: int,
    tickets: list[tuple[int, list[tuple[str, str]]]],
    *,
    paper: str = "letter",
    per_page: int = 2,
    fonts: Fonts | None = None,
    brand: BrandStyle | None = None,
) -> bytes:
    """tickets: [(ticket number, [(title, artist) per square, row-major]), ...]"""
    if not tickets:
        raise ValueError("there are no tickets to print")
    if paper not in PAPER_SIZES:
        raise ValueError(f"unknown paper size {paper!r}")
    if per_page not in TICKETS_PER_PAGE:
        raise ValueError(f"tickets per page must be one of {sorted(TICKETS_PER_PAGE)}")
    fonts = fonts or Fonts()
    brand = brand or BrandStyle()
    try:
        logo = ImageReader(BytesIO(brand.logo_png)) if brand.logo_png else None
    except Exception:  # an unreadable logo must never stop tickets from printing
        logo = None
    page_w, page_h = PAPER_SIZES[paper]
    cols, rows = TICKETS_PER_PAGE[per_page]
    slot_w = (page_w - 2 * PAGE_MARGIN) / cols
    slot_h = (page_h - 2 * PAGE_MARGIN) / rows

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_w, page_h))
    c.setTitle(printable(f"{game_name} tickets", fonts))
    for index, (number, cells) in enumerate(tickets):
        slot = index % per_page
        if slot == 0:
            if index:
                c.showPage()
            _draw_cut_lines(c, page_w, page_h, cols, rows, slot_w, slot_h)
        col, row = slot % cols, slot // cols
        x = PAGE_MARGIN + col * slot_w + TICKET_INSET
        y = page_h - PAGE_MARGIN - (row + 1) * slot_h + TICKET_INSET
        _draw_ticket(
            c, x, y, slot_w - 2 * TICKET_INSET, slot_h - 2 * TICKET_INSET,
            game_name=printable(game_name, fonts), number=number, size=size, cells=cells, fonts=fonts,
            brand=brand, logo=logo,
        )
    c.save()
    return buffer.getvalue()


def fonts_from_settings(settings) -> Fonts:
    """The configured TrueType font, or the built-in one if none is set or it can't be loaded."""
    try:
        return load_fonts(settings.pdf_font, settings.pdf_font_bold)
    except Exception:
        return load_fonts()
