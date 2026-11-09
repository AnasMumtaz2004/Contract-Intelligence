from datetime import date

from app.ingestion.metadata import read_suggestion


def test_valid_reply_is_read():
    """A correct JSON reply should give the three values."""
    reply = '{"vendor_name": "Acme Corp", "document_type": "Amendment", "effective_date": "2024-03-01"}'
    suggestion = read_suggestion(reply)
    assert suggestion["vendor_name"] == "Acme Corp"
    assert suggestion["document_type"] == "Amendment"
    assert suggestion["effective_date"] == date(2024, 3, 1)


def test_code_fences_unknown_values_and_bad_dates_are_cleaned():
    """Markdown fences are removed, Unknown becomes empty, a bad type becomes Other, a bad date becomes None."""
    reply = '```json\n{"vendor_name": "Unknown", "document_type": "License", "effective_date": "next week"}\n```'
    suggestion = read_suggestion(reply)
    assert suggestion["vendor_name"] == ""
    assert suggestion["document_type"] == "Other"
    assert suggestion["effective_date"] is None


def test_broken_json_gives_an_empty_suggestion():
    """If the reply is not JSON, nothing should crash."""
    suggestion = read_suggestion("Sorry, I cannot help with that.")
    assert suggestion["vendor_name"] == ""
    assert suggestion["document_type"] == "Other"
    assert suggestion["effective_date"] is None