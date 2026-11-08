from app.config import settings

# Chunks with fewer words than this are just headings, so we skip them
MIN_CHUNK_WORDS = 4


def make_section_label(section: dict) -> str:
    """Make a short label like '12.3 Exclusions' for a section."""
    if section["number"] is None:
        return section["heading"]
    return section["number"] + " " + section["heading"]


def build_section_path(section: dict, sections_by_number: dict) -> str:
    """Build a path like '12 Liability > 12.3 Exclusions' from the top parent down."""
    labels = [make_section_label(section)]

    parent_number = section["parent_number"]
    while parent_number is not None:
        parent = sections_by_number.get(parent_number)
        # The parent might be missing if the heading was not detected
        if parent is None:
            break
        labels.insert(0, make_section_label(parent))
        parent_number = parent["parent_number"]

    return " > ".join(labels)


def make_chunk(lines: list[str], page_number: int, section_path: str) -> dict:
    """Create one chunk from a list of lines."""
    return {
        "content": "\n".join(lines),
        "page_number": page_number,
        "section_path": section_path,
    }


def split_section_into_chunks(section: dict, section_path: str) -> list[dict]:
    """Cut one section into chunks of about chunk_max_words words."""
    max_words = settings.chunk_max_words
    # We never let a chunk grow past this, even without a sentence end
    hard_max_words = max_words + max_words // 2

    chunks = []
    current_lines = []
    current_words = 0
    current_page = section["page_start"]

    for line in section["lines"]:
        # A chunk gets the page number of its first line
        if len(current_lines) == 0:
            current_page = line["page"]

        current_lines.append(line["text"])
        current_words += len(line["text"].split())

        # We prefer to cut where a sentence ends
        ends_sentence = line["text"].endswith((".", ";", ":"))

        should_cut = False
        if current_words >= max_words and ends_sentence:
            should_cut = True
        if current_words >= hard_max_words:
            should_cut = True

        if should_cut:
            chunks.append(make_chunk(current_lines, current_page, section_path))
            current_lines = []
            current_words = 0

    # Save the last lines that did not fill a whole chunk
    if len(current_lines) > 0:
        chunks.append(make_chunk(current_lines, current_page, section_path))

    # Drop chunks that are too small to be useful
    useful_chunks = []
    for chunk in chunks:
        word_count = len(chunk["content"].split())
        if word_count >= MIN_CHUNK_WORDS:
            useful_chunks.append(chunk)
    return useful_chunks


def chunk_sections(sections: list[dict]) -> list[dict]:
    """Turn all sections into chunks. Each chunk remembers which section it came from."""
    # Look up sections by number to build the section paths.
    # If a number appears twice, the last one wins.
    sections_by_number = {}
    for section in sections:
        if section["number"] is not None:
            sections_by_number[section["number"]] = section

    all_chunks = []
    for section_index, section in enumerate(sections):
        section_path = build_section_path(section, sections_by_number)
        section_chunks = split_section_into_chunks(section, section_path)

        for chunk in section_chunks:
            chunk["section_index"] = section_index
            all_chunks.append(chunk)

    return all_chunks