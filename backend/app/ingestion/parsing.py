import re

import pymupdf

# Matches lines like "12", "Page 3" or "Page 3 of 10"
PAGE_NUMBER_PATTERN = re.compile(r"^(page\s+)?\d+(\s+of\s+\d+)?$", re.IGNORECASE)

# Matches lines that hold only a label, like "3.", "1.1", "(a)" or "B."
LABEL_PATTERN = re.compile(r"^(\d{1,3}(\.\d{1,3})*\.?|\(\w{1,4}\)|[A-Za-z]\.)$")


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


def parse_pdf(file_path: str) -> list[dict]:
    """Read a PDF and return a list of pages with their page number and lines."""
    pages = []
    pdf = pymupdf.open(file_path)

    for page_index in range(len(pdf)):
        page = pdf[page_index]
        raw_text = page.get_text("text")
        lines = clean_lines(raw_text)
        lines = join_label_lines(lines)
        # Page numbers start at 1 for people, but PyMuPDF starts at 0
        pages.append({"page_number": page_index + 1, "lines": lines})

    pdf.close()
    return pages


def count_words(pages: list[dict]) -> int:
    """Count all words in the parsed pages."""
    total = 0
    for page in pages:
        for line in page["lines"]:
            total += len(line.split())
    return total