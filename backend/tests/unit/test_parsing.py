import pymupdf

from app.ingestion.parsing import clean_lines, count_words, join_label_lines, parse_pdf, parse_with_router


def test_clean_lines_removes_blanks_and_page_numbers():
    """Empty lines and page-number lines should disappear."""
    raw_text = "First line\n\n  Second line  \n12\nPage 3 of 10\n"
    lines = clean_lines(raw_text)
    assert lines == ["First line", "Second line"]


def test_join_label_lines_joins_a_lone_label_with_the_next_line():
    """A label like '3.' or '(a)' on its own line belongs to the line after it."""
    lines = ["3.", "Term. This Agreement lasts three years.", "(a)", "Fees are due monthly."]
    joined = join_label_lines(lines)
    assert joined == ["3. Term. This Agreement lasts three years.", "(a) Fees are due monthly."]


def test_join_label_lines_keeps_normal_lines_and_a_label_at_the_end():
    """Normal lines stay as they are, and a label with no next line is kept."""
    lines = ["Some normal text.", "1.1 Fees. Pay monthly.", "5."]
    assert join_label_lines(lines) == lines


def test_parse_pdf_reads_every_page(tmp_path):
    """A two-page PDF should give two pages with the right numbers."""
    pdf_path = tmp_path / "sample.pdf"

    pdf = pymupdf.open()
    first_page = pdf.new_page()
    first_page.insert_text((72, 72), "1. Term")
    second_page = pdf.new_page()
    second_page.insert_text((72, 72), "2. Fees")
    pdf.save(str(pdf_path))
    pdf.close()

    pages = parse_pdf(str(pdf_path))

    assert len(pages) == 2
    assert pages[0]["page_number"] == 1
    assert pages[0]["lines"] == ["1. Term"]
    assert pages[1]["page_number"] == 2
    assert pages[1]["lines"] == ["2. Fees"]


def test_count_words_adds_up_all_lines():
    """Word count should include every line on every page."""
    pages = [
        {"page_number": 1, "lines": ["one two three", "four five"]},
        {"page_number": 2, "lines": ["six"]},
    ]
    assert count_words(pages) == 6

def test_router_uses_the_plain_text_path_for_a_normal_page(tmp_path):
    """A normal text page needs no OCR and no table reading."""
    pdf_path = tmp_path / "normal.pdf"

    pdf = pymupdf.open()
    page = pdf.new_page()
    text = "The supplier shall deliver the goods on time and in good condition. " * 6
    page.insert_textbox(pymupdf.Rect(72, 72, 500, 500), text)
    pdf.save(str(pdf_path))
    pdf.close()

    result = parse_with_router(str(pdf_path))

    assert result["parser_used"] == "pymupdf"
    assert result["parse_quality"] == 1.0
    assert result["ocr_error"] == ""