from app.rag import build_context, find_cited_numbers
from app.retrieval.search import build_keyword_query, merge_with_rrf


def make_item(chunk_id: int) -> dict:
    """Make a small fake search result."""
    return {
        "chunk_id": chunk_id,
        "file_name": "a.pdf",
        "document_type": "Other",
        "effective_date": "",
        "section_path": "1 Term",
        "page_number": 1,
        "content": "text",
    }


def test_keyword_query_drops_short_and_repeated_words():
    """Short words and repeated words should not appear in the query."""
    query = build_keyword_query("What is the cap on liability, liability?")
    assert query == "what | the | cap | liability"


def test_keyword_query_has_no_search_syntax():
    """Symbols like ! & : must be removed so they cannot break the query."""
    query = build_keyword_query("termination! & (notice): period")
    assert query == "termination | notice | period"


def test_rrf_puts_chunk_found_by_both_searches_first():
    """A chunk that appears in both lists should beat chunks that appear in one."""
    vector_results = [make_item(1), make_item(2)]
    keyword_results = [make_item(2), make_item(3)]

    merged = merge_with_rrf([vector_results, keyword_results], 60)

    chunk_ids = []
    for item in merged:
        chunk_ids.append(item["chunk_id"])
    assert chunk_ids == [2, 1, 3]


def test_find_cited_numbers_reads_single_and_grouped_numbers():
    """Both [1] and [2, 3] should be found, and invalid numbers ignored."""
    answer = "Fees are due monthly [1]. Either side may end it [2, 3] and [1] again [9]."
    assert find_cited_numbers(answer, 3) == [1, 2, 3]


def test_build_context_numbers_the_sources():
    """Each chunk should get a number, a file name, a document type, a section path and a page."""
    context = build_context([make_item(1), make_item(2)])
    assert "[1] a.pdf | Other | 1 Term | page 1" in context
    assert "[2] a.pdf | Other | 1 Term | page 1" in context


def test_build_context_shows_the_effective_date_and_cross_references():
    """An amendment shows its date, and a cross-reference chunk is marked."""
    item = make_item(1)
    item["document_type"] = "Amendment"
    item["effective_date"] = "2024-03-01"
    item["file_name"] = "synthetic/amendments/x_amendment_1.pdf"
    item["via_cross_reference"] = True

    context = build_context([item])
    assert "[1] x_amendment_1.pdf | Amendment, effective 2024-03-01 | 1 Term | page 1 | referenced section" in context