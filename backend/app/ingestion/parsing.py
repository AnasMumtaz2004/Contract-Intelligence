import io
import re

import pymupdf

from app.config import settings

# Matches lines like "12", "Page 3" or "Page 3 of 10"
PAGE_NUMBER_PATTERN = re.compile(r"^(page\s+)?\d+(\s+of\s+\d+)?$", re.IGNORECASE)

# Matches lines that hold only a label, like "3.", "1.1", "(a)" or "B."
LABEL_PATTERN = re.compile(r"^(\d{1,3}(\.\d{1,3})*\.?|\(\w{1,4}\)|[A-Za-z]\.)$")

# The "|---|---|" line under a markdown table header
TABLE_SEPARATOR_PATTERN = re.compile(r"^\|[\s\-:|]+\|$")

# A real table has at least this many rows and columns.
# Smaller "tables" are usually boxes or signature blocks.
MIN_TABLE_ROWS = 3
MIN_TABLE_COLUMNS = 2
# A table that covers most of the page is usually a page frame, not a table
MAX_TABLE_PAGE_SHARE = 0.6
# Table cells hold few words. Prose inside a box has many words per cell.
MAX_WORDS_PER_CELL = 15


def clean_lines(raw_text: str) -> list[str]:
    """Split page text into lines and drop empty lines and page-number lines."""
    clean = []
    for line in raw_text.split("\n"):
        line = line.strip()
        if line == "":
            continue
        # Page numbers in footers would pollute the chunks
        if PAGE_NUMBER_PATTERN.match(line):
            continue
        clean.append(line)
    return clean


def join_label_lines(lines: list[str]) -> list[str]:
    """Join a lone label like '3.' or '(a)' with the line after it."""
    # Many PDFs put the number in its own column, so the PDF reader gives it a separate line
    joined = []
    index = 0

    while index < len(lines):
        line = lines[index]
        is_label = LABEL_PATTERN.match(line) is not None
        has_next_line = index + 1 < len(lines)

        if is_label and has_next_line:
            joined.append(line + " " + lines[index + 1])
            index += 2
        else:
            joined.append(line)
            index += 1

    return joined


def count_line_words(lines: list[str]) -> int:
    """Count the words in a list of lines."""
    total = 0
    for line in lines:
        total += len(line.split())
    return total


def parse_text_page(page) -> list[str]:
    """Read the normal text layer of a page."""
    raw_text = page.get_text("text")
    lines = clean_lines(raw_text)
    return join_label_lines(lines)


def looks_like_data_table(table, page) -> bool:
    """Check that a table is really a data table, and not a page frame or a box with paragraphs."""
    box = pymupdf.Rect(table.bbox)
    page_area = page.rect.width * page.rect.height
    if page_area > 0 and (box.width * box.height) / page_area > MAX_TABLE_PAGE_SHARE:
        return False

    # Reading the cells can fail on strange tables, and then we simply do not treat it as a table
    try:
        rows = table.extract()
    except Exception:
        return False

    word_total = 0
    cell_total = 0
    for row in rows:
        for cell in row:
            if cell is None or cell.strip() == "":
                continue
            cell_total += 1
            word_total += len(cell.split())

    if cell_total == 0:
        return False
    return word_total / cell_total <= MAX_WORDS_PER_CELL


def find_real_tables(page) -> list:
    """Find the tables on a page. Boxes, frames and signature blocks are ignored."""
    # find_tables can fail on strange pages, and one bad page must not stop the whole document
    try:
        finder = page.find_tables()
    except Exception:
        return []

    real_tables = []
    for table in finder.tables:
        if table.row_count < MIN_TABLE_ROWS or table.col_count < MIN_TABLE_COLUMNS:
            continue
        if not looks_like_data_table(table, page):
            continue
        real_tables.append(table)
    return real_tables


def table_to_lines(table) -> list[str]:
    """Turn a table into markdown rows, one line per row."""
    markdown = table.to_markdown()

    lines = []
    for line in markdown.split("\n"):
        line = line.strip()
        if line == "":
            continue
        if TABLE_SEPARATOR_PATTERN.match(line):
            continue
        lines.append(line)
    return lines


def parse_table_page(page, tables: list) -> list[str]:
    """Read a page with tables. Table text becomes markdown rows, other text stays as lines."""
    table_boxes = []
    for table in tables:
        table_boxes.append(pymupdf.Rect(table.bbox))

    # Each item is (vertical position, lines), so the page can be put back in reading order
    items = []

    for block in page.get_text("blocks"):
        # Block type 0 is text. Other types are pictures.
        if block[6] != 0:
            continue

        # A block whose center is inside a table is already part of the table
        center = pymupdf.Point((block[0] + block[2]) / 2, (block[1] + block[3]) / 2)
        is_inside_table = False
        for table_box in table_boxes:
            if table_box.contains(center):
                is_inside_table = True
        if is_inside_table:
            continue

        items.append((block[1], clean_lines(block[4])))

    for table in tables:
        items.append((table.bbox[1], table_to_lines(table)))

    items.sort(key=lambda item: item[0])

    lines = []
    for _position, item_lines in items:
        lines.extend(item_lines)
    return join_label_lines(lines)


def parse_ocr_page(page) -> list[str]:
    """Read a scanned page with OCR (Tesseract) and return its lines."""
    # These are imported here, so documents without scans never need Tesseract
    import pytesseract
    from PIL import Image

    if settings.tesseract_cmd != "":
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

    pixmap = page.get_pixmap(dpi=settings.ocr_dpi)
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    text = pytesseract.image_to_string(image, lang=settings.ocr_language)

    lines = clean_lines(text)
    return join_label_lines(lines)


def parse_pdf(file_path: str) -> list[dict]:
    """Read the text layer of a PDF. Scripts and tests use this simple version."""
    pages = []
    pdf = pymupdf.open(file_path)

    for page_index in range(len(pdf)):
        lines = parse_text_page(pdf[page_index])
        # Page numbers start at 1 for people, but PyMuPDF starts at 0
        pages.append({"page_number": page_index + 1, "lines": lines})

    pdf.close()
    return pages


def parse_with_router(file_path: str) -> dict:
    """Parse a PDF page by page. Each page goes through the path that fits it best."""
    pdf = pymupdf.open(file_path)

    pages = []
    table_page_count = 0
    ocr_page_count = 0
    pages_with_text = 0
    ocr_error = ""

    for page_index in range(len(pdf)):
        page = pdf[page_index]
        lines = parse_text_page(page)
        word_count = count_line_words(lines)
        has_picture = len(page.get_images()) > 0

        if word_count < settings.min_words_per_page and has_picture:
            # Few words and a picture on the page: it is probably a scan
            try:
                ocr_lines = parse_ocr_page(page)
                if count_line_words(ocr_lines) > word_count:
                    lines = ocr_lines
                    ocr_page_count += 1
            except Exception as error:
                # OCR may not be installed. We keep the page as it is and report the problem later.
                ocr_error = str(error)
        elif word_count >= settings.min_words_per_page:
            tables = find_real_tables(page)
            if len(tables) > 0:
                lines = parse_table_page(page, tables)
                table_page_count += 1

        if count_line_words(lines) >= settings.min_words_per_page:
            pages_with_text += 1
        pages.append({"page_number": page_index + 1, "lines": lines})

    pdf.close()

    parser_used = "pymupdf"
    if table_page_count > 0:
        parser_used += "+tables"
    if ocr_page_count > 0:
        parser_used += "+ocr"

    parse_quality = 0.0
    if len(pages) > 0:
        parse_quality = pages_with_text / len(pages)

    return {
        "pages": pages,
        "parser_used": parser_used,
        "parse_quality": parse_quality,
        "ocr_error": ocr_error,
    }


def count_words(pages: list[dict]) -> int:
    """Count all words in the parsed pages."""
    total = 0
    for page in pages:
        total += count_line_words(page["lines"])
    return total