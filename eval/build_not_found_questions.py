import argparse
import json
from pathlib import Path

import pymupdf

from build_dataset import CATEGORY_QUESTIONS, read_contract_labels, read_sources
from text_utils import load_cuad_by_title

EVAL_FOLDER = Path(__file__).resolve().parent
CUAD_FOLDER = EVAL_FOLDER.parent / "data" / "cuad_subset"
MANIFEST_FILE = EVAL_FOLDER.parent / "data" / "synthetic" / "amendments" / "manifest.json"
OUTPUT_FILE = EVAL_FOLDER / "questions_not_found.jsonl"

# Words to look for, for each clause type. A clause counts as missing only if none of them appear anywhere.
KEYWORDS = {
    "Renewal Term": ["renew"],
    "Expiration Date": ["expire", "expiration"],
    "Termination For Convenience": ["convenience", "without cause"],
    "Audit Rights": ["audit"],
    "Non-Compete": ["compet"],
    "Insurance": ["insurance"],
    "Exclusivity": ["exclusiv"],
    "Anti-Assignment": ["assign"],
    "Governing Law": ["governed by", "governing law"],
    "Cap On Liability": ["liability"],
}


def read_pdf_text(pdf_path: Path) -> str:
    """Read all the text of a PDF as one lowercase line."""
    pdf = pymupdf.open(str(pdf_path))
    parts = []
    for page in pdf:
        parts.append(page.get_text())
    pdf.close()
    return " ".join(" ".join(parts).split()).lower()


def count_hits(text: str, keywords: list[str]) -> int:
    """Count how often the keywords appear in a text."""
    total = 0
    for keyword in keywords:
        total += text.count(keyword)
    return total


def read_amended_files() -> list[str]:
    """Return the file names of the contracts that have amendments. Their answers change, so we skip them."""
    if not MANIFEST_FILE.exists():
        return []

    with open(MANIFEST_FILE, encoding="utf-8") as file:
        manifest = json.load(file)

    files = []
    for family in manifest:
        files.append(family["base_file"])
    return files


def main() -> None:
    """Build questions about clauses that are really missing from a contract."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--cuad-json", required=True, help="Path to CUAD_v1.json")
    parser.add_argument("--skip-first", type=int, default=8, help="Contracts at the top of sources.csv that already have questions")
    parser.add_argument("--per-contract", type=int, default=2, help="Most questions for one contract")
    args = parser.parse_args()

    contracts_by_title = load_cuad_by_title(args.cuad_json)
    amended_files = read_amended_files()

    records = []
    for row in read_sources()[args.skip_first :]:
        if row["file_name"] in amended_files:
            continue
        if row["cuad_title"] not in contracts_by_title:
            continue

        labels = read_contract_labels(contracts_by_title[row["cuad_title"]])
        text = read_pdf_text(CUAD_FOLDER / row["file_name"])

        added = 0
        for category in CATEGORY_QUESTIONS:
            if added >= args.per_contract:
                break

            # CUAD says the clause is missing
            key = category.lower()
            if key not in labels or len(labels[key]) > 0:
                continue
            # And the PDF really has none of the typical words
            if count_hits(text, KEYWORDS.get(category, [category.lower()])) > 0:
                continue

            records.append(
                {
                    "id": "n" + str(len(records) + 1).zfill(3),
                    "level": 7,
                    "vendor_name": row["vendor_name"],
                    "file_name": row["file_name"],
                    "category": category,
                    "question": CATEGORY_QUESTIONS[category][0],
                    "expected_answer": "",
                    "supporting_text": "",
                    "must_mention": [],
                    "amendment_files": [],
                    "answerable": False,
                }
            )
            added += 1

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record) + "\n")

    print("Wrote", len(records), "not-found questions to", OUTPUT_FILE)


if __name__ == "__main__":
    main()