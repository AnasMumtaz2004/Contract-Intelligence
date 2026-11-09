from app.retrieval.cross_reference import find_referenced_numbers


def test_finds_section_numbers():
    """Section 12.3 and Article 4 should both be found, once each."""
    text = "Subject to Section 12.3 and Article 4, and again Section 12.3, the supplier shall pay."
    assert find_referenced_numbers(text) == ["12.3", "4"]


def test_a_trailing_period_is_not_part_of_the_number():
    """The period that ends a sentence must not be read as a decimal point."""
    assert find_referenced_numbers("See Section 5.") == ["5"]


def test_text_without_references_gives_an_empty_list():
    """Plain text has no references."""
    assert find_referenced_numbers("The customer shall pay all invoices.") == []