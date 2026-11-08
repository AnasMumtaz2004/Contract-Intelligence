from app.ingestion.chunking import chunk_sections
from app.ingestion.structure import check_heading, find_sections


def test_numbered_heading_is_detected():
    """A line like '12.3 Limitation of Liability' is a heading."""
    heading = check_heading("12.3 Limitation of Liability")
    assert heading is not None
    assert heading["number"] == "12.3"
    assert heading["heading"] == "Limitation of Liability"


def test_run_in_heading_uses_text_before_the_period():
    """In '5.1 Payment. The customer pays...' the heading is just 'Payment'."""
    heading = check_heading("5.1 Payment. The customer shall pay within thirty days.")
    assert heading is not None
    assert heading["heading"] == "Payment"


def test_normal_sentences_are_not_headings():
    """Body text must not be mistaken for a heading."""
    assert check_heading("the Customer shall pay all invoices.") is None
    assert check_heading("Section 5 shall apply to all orders.") is None
    assert check_heading("3.5 million dollars will be paid.") is None


def test_table_of_contents_line_is_not_a_heading():
    """Lines with dot leaders belong to the table of contents."""
    assert check_heading("5.1 Payment ........ 12") is None


def test_sections_get_parent_numbers():
    """Section 1.1 should point to section 1 as its parent."""
    pages = [
        {
            "page_number": 1,
            "lines": [
                "1. Definitions",
                "In this agreement the following words apply.",
                "1.1 Affiliate means a company under common control.",
                "2. Payment",
                "Fees are due within thirty days of the invoice.",
            ],
        }
    ]
    sections = find_sections(pages)

    assert len(sections) == 3
    assert sections[1]["number"] == "1.1"
    assert sections[1]["parent_number"] == "1"
    assert sections[1]["level"] == 2


def test_text_before_first_heading_becomes_preamble():
    """Text that comes before any heading goes into a Preamble section."""
    pages = [{"page_number": 1, "lines": ["This agreement is made today.", "1. Term"]}]
    sections = find_sections(pages)

    assert sections[0]["heading"] == "Preamble"
    assert sections[0]["number"] is None


def test_chunk_has_section_path_and_page():
    """A chunk should know its section path and the page it starts on."""
    pages = [
        {"page_number": 1, "lines": ["1. Term", "The initial term is two years from the start date."]},
        {"page_number": 2, "lines": ["2. Fees", "Fees are due monthly in advance by the customer."]},
    ]
    sections = find_sections(pages)
    chunks = chunk_sections(sections)

    assert len(chunks) == 2
    assert chunks[0]["section_path"] == "1 Term"
    assert chunks[0]["page_number"] == 1
    assert chunks[1]["section_path"] == "2 Fees"
    assert chunks[1]["page_number"] == 2


def test_child_chunk_path_includes_parent():
    """The path of section 1.1 should start with its parent section."""
    pages = [
        {
            "page_number": 1,
            "lines": [
                "1. Definitions",
                "The following words have these meanings here.",
                "1.1 Affiliate means a company under common control.",
            ],
        }
    ]
    chunks = chunk_sections(find_sections(pages))

    assert chunks[1]["section_path"] == "1 Definitions > 1.1 Affiliate means a company under common control"


def test_long_section_is_split_into_several_chunks():
    """A very long section must be cut into more than one chunk."""
    long_lines = ["1. Services"]
    for line_number in range(100):
        long_lines.append("The supplier will provide the agreed services to the customer on time.")

    pages = [{"page_number": 1, "lines": long_lines}]
    chunks = chunk_sections(find_sections(pages))

    assert len(chunks) > 1

def test_single_number_heading_with_a_run_in_title_is_detected():
    """'3. Term. This Agreement will...' is a heading called Term, even though the line is long."""
    heading = check_heading("3. Term. This Agreement will be in effect for three years from the Effective Date")
    assert heading is not None
    assert heading["number"] == "3"
    assert heading["heading"] == "Term"


def test_numbered_list_sentence_is_not_a_heading():
    """A long numbered sentence is a list item, not a heading."""
    line = "1. The Customer shall pay all invoices within thirty days of the date of receipt."
    assert check_heading(line) is None