import re

# Matches lines like "12.3 Limitation of Liability" or "5. Payment"
NUMBERED_PATTERN = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+(.+)$")

# Matches lines like "ARTICLE V" or "Section 5. Payment"
KEYWORD_PATTERN = re.compile(r"^(?:article|section)\s+(\d+(?:\.\d+)*|[IVXLC]+)\b[.:\-\s]*(.*)$", re.IGNORECASE)

# Small words that may stay lowercase in a title, like "Limitation of Liability"
SMALL_WORDS = ["a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"]

# A heading is never longer than this many words
MAX_HEADING_WORDS = 8


def make_heading(text: str) -> str:
    """Use the text before the first period as the heading and keep it short."""
    # Many contracts write "5.1 Payment. The customer shall..." on one line
    heading = text.split(". ")[0]
    heading = heading.strip()
    heading = heading.rstrip(".")
    if len(heading) > 60:
        heading = heading[:60]
    return heading


def looks_like_title(text: str) -> bool:
    """Check if a text looks like a heading: only a few words, each starting with a capital letter."""
    words = text.split()
    if len(words) == 0 or len(words) > MAX_HEADING_WORDS:
        return False

    for word in words:
        if word.lower() in SMALL_WORDS:
            continue
        first_letter = word[0]
        if not (first_letter.isupper() or first_letter.isdigit()):
            return False
    return True


def check_heading(line: str) -> dict | None:
    """Return the section number and heading if the line looks like a heading, else None."""
    # Table of contents lines have dot leaders like "Payment ........ 12"
    if "...." in line:
        return None

    numbered_match = NUMBERED_PATTERN.match(line)
    if numbered_match is not None:
        number = numbered_match.group(1)
        rest = numbered_match.group(2)

        # Skip lines that start with a year or a big number
        first_part = int(number.split(".")[0])
        if first_part > 99:
            return None

        # Real headings start with a capital letter
        if not rest[0].isupper():
            return None

        # A single number like "5." is also used for list items.
        # A long line is only a heading if it starts with a short title, like "3. Term. This Agreement..."
        is_single_number = "." not in number
        if is_single_number and len(rest.split()) > MAX_HEADING_WORDS:
            first_sentence = rest.split(". ")[0].rstrip(".")
            if not looks_like_title(first_sentence):
                return None

        return {"number": number, "heading": make_heading(rest)}

    keyword_match = KEYWORD_PATTERN.match(line)
    if keyword_match is not None:
        number = keyword_match.group(1).upper()
        rest = keyword_match.group(2).strip()

        # "Section 5 shall apply..." is a sentence, not a heading
        if rest != "" and not rest[0].isupper():
            return None
        if len(line) > 80:
            return None

        if rest == "":
            heading = line
        else:
            heading = make_heading(rest)
        return {"number": number, "heading": heading}

    return None


def new_section(number: str | None, heading: str, page_number: int) -> dict:
    """Create an empty section that starts on the given page."""
    level = 1
    parent_number = None

    if number is not None:
        parts = number.split(".")
        level = len(parts)
        # The parent of "12.3" is "12"
        if len(parts) > 1:
            parent_number = ".".join(parts[:-1])

    return {
        "number": number,
        "heading": heading,
        "level": level,
        "parent_number": parent_number,
        "page_start": page_number,
        "page_end": page_number,
        "lines": [],
    }


def find_sections(pages: list[dict]) -> list[dict]:
    """Group all lines of the document into sections, using the headings we can detect."""
    sections = []
    current_section = None

    for page in pages:
        page_number = page["page_number"]

        for line in page["lines"]:
            heading = check_heading(line)

            if heading is not None:
                # A new heading closes the old section and starts a new one
                current_section = new_section(heading["number"], heading["heading"], page_number)
                sections.append(current_section)
            elif current_section is None:
                # Text before the first heading goes into a "Preamble" section
                current_section = new_section(None, "Preamble", page_number)
                sections.append(current_section)

            # We keep the page number of every line so chunks can point to the right page
            current_section["lines"].append({"page": page_number, "text": line})
            current_section["page_end"] = page_number

    return sections


def get_section_text(section: dict) -> str:
    """Join the lines of a section into one text."""
    texts = []
    for line in section["lines"]:
        texts.append(line["text"])
    return "\n".join(texts)