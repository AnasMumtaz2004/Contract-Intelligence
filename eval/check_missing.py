import json
from pathlib import Path

import pymupdf

EVAL_FOLDER = Path(__file__).resolve().parent
CUAD_FOLDER = EVAL_FOLDER.parent / "data" / "cuad_subset"
QUESTIONS_FILE = EVAL_FOLDER / "questions.jsonl"

# Words to look for, for each clause type
KEYWORDS = {
    "Renewal Term": ["renew"],
    "Expiration Date": ["expire", "expiration"],
    "Termination For Convenience": ["convenience", "without cause"],
    "Audit Rights": ["audit"],
    "Non-Compete": ["compet"],
    "Insurance": ["insurance"],
    "Exclusivity": ["exclusiv"],
    "Anti-Assignment": ["assign"],
}

# How much text to show on each side of a hit
SNIPPET_CHARS = 80
MAX_SNIPPETS = 3


def read_pdf_text(pdf_path: Path) -> str:
    """Read all the text of a PDF as one line."""
    pdf = pymupdf.open(str(pdf_path))
    parts = []
    for page in pdf:
        parts.append(page.get_text())
    pdf.close()
    return " ".join(" ".join(parts).split())


def find_snippets(text: str, keywords: list[str]) -> tuple:
    """Return the total number of hits and a few short snippets around them."""
    lower_text = text.lower()

    total_hits = 0
    for keyword in keywords:
        total_hits += lower_text.count(keyword)

    snippets = []
    for keyword in keywords:
        start = 0
        while len(snippets) < MAX_SNIPPETS:
            position = lower_text.find(keyword, start)
            if position == -1:
                break
            snippet_start = max(0, position - SNIPPET_CHARS)
            snippets.append(text[snippet_start : position + SNIPPET_CHARS])
            # Skip ahead so the snippets do not overlap
            start = position + SNIPPET_CHARS

    return total_hits, snippets


def main() -> None:
    """For every level 7 question, search the PDF for the clause that is supposed to be missing."""
    with open(QUESTIONS_FILE, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line == "":
                continue
            record = json.loads(line)
            if record["level"] != 7:
                continue

            keywords = KEYWORDS.get(record["category"], [record["category"].lower()])
            text = read_pdf_text(CUAD_FOLDER / record["file_name"])
            total_hits, snippets = find_snippets(text, keywords)

            print(record["id"], "|", record["vendor_name"], "|", record["category"], "| hits:", total_hits)
            for snippet in snippets:
                print("    ...", snippet, "...")


if __name__ == "__main__":
    main()