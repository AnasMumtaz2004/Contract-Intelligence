import argparse
import csv
import shutil
from pathlib import Path

import pymupdf

from build_dataset import CATEGORY_QUESTIONS, read_contract_labels
from text_utils import clean_file_name, load_cuad_by_title

EVAL_FOLDER = Path(__file__).resolve().parent
DATA_FOLDER = EVAL_FOLDER.parent / "data" / "cuad_subset"
SOURCES_FILE = DATA_FOLDER / "sources.csv"

# A good test contract is neither tiny nor huge
MIN_PAGES = 5
MAX_PAGES = 60
# Fewer words per page than this means the PDF is probably a scan
MIN_WORDS_PER_PAGE = 100
# We want contracts that have several of our clause types, and at least one missing
MIN_ANSWERED = 3


def find_cuad_json(cuad_folder: Path):
    """Find CUAD_v1.json somewhere inside the CUAD folder."""
    for path in cuad_folder.rglob("*.json"):
        name = path.name.lower().replace("_", "")
        if name == "cuadv1.json":
            return path
    return None


def find_pdfs(cuad_folder: Path) -> dict:
    """Return {file name without extension: path} for every PDF, even if it ends in .PDF."""
    pdfs = {}
    for path in cuad_folder.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".pdf":
            pdfs[path.stem] = path
    return pdfs


def count_labels(labels: dict) -> tuple:
    """Count how many of our clause types are present and how many are missing."""
    answered = 0
    missing = 0

    for category in CATEGORY_QUESTIONS:
        key = category.lower()
        if key not in labels:
            continue
        if len(labels[key]) > 0:
            answered += 1
        else:
            missing += 1
    return answered, missing


def make_vendor_name(title: str) -> str:
    """Make a readable vendor name from a CUAD title."""
    if "_" in title:
        name = title.split("_")[0]
    elif " - " in title:
        name = title.split(" - ")[0]
    else:
        name = title

    # Titles like "CERES,INC" become "Ceres Inc"
    name = name.replace(",", " ")
    name = " ".join(name.split())
    if name == "":
        name = title
    return name.title()


def check_pdf(pdf_path: Path) -> str:
    """Return an empty string if the PDF is a good test file, otherwise the reason it is not."""
    # Some files in a big dataset can be broken, so opening the PDF is protected
    try:
        pdf = pymupdf.open(str(pdf_path))
    except Exception:
        return "cannot open the PDF"

    page_count = len(pdf)
    if page_count < MIN_PAGES or page_count > MAX_PAGES:
        pdf.close()
        return "page count is " + str(page_count)

    # Only the first pages are checked, to keep this fast
    pages_to_check = min(page_count, 5)
    word_count = 0
    for page_index in range(pages_to_check):
        word_count += len(pdf[page_index].get_text().split())
    pdf.close()

    if word_count / pages_to_check < MIN_WORDS_PER_PAGE:
        return "little or no text (scanned?)"
    return ""


def pick_contracts(candidates_by_type: dict, pdf_by_title: dict, count: int) -> list[dict]:
    """Pick contracts one type at a time, so the sample has many different contract types."""
    selected = []
    used_vendors = set()
    type_names = sorted(candidates_by_type.keys())

    while len(selected) < count:
        took_any = False

        # One round: try to take one contract from every type
        for type_name in type_names:
            if len(selected) >= count:
                break

            candidates = candidates_by_type[type_name]
            while len(candidates) > 0:
                candidate = candidates.pop(0)

                # One contract per vendor keeps the questions clean
                if candidate["vendor_name"] in used_vendors:
                    continue

                reason = check_pdf(pdf_by_title[candidate["title"]])
                if reason != "":
                    print("  skipped", candidate["title"], "-", reason)
                    continue

                selected.append(candidate)
                used_vendors.add(candidate["vendor_name"])
                took_any = True
                break

        # No type had anything left to give
        if not took_any:
            break

    return selected


def copy_and_write_sources(selected: list[dict], pdf_by_title: dict) -> None:
    """Copy the chosen PDFs into data/cuad_subset and write sources.csv."""
    DATA_FOLDER.mkdir(parents=True, exist_ok=True)

    rows = []
    for candidate in selected:
        short_type = clean_file_name(candidate["type_name"])
        short_vendor = clean_file_name(candidate["vendor_name"])
        file_name = short_type + "_" + short_vendor + ".pdf"

        shutil.copy(pdf_by_title[candidate["title"]], DATA_FOLDER / file_name)

        rows.append(
            {
                "file_name": file_name,
                "vendor_name": candidate["vendor_name"],
                "document_type": "Other",
                "cuad_title": candidate["title"],
            }
        )

    with open(SOURCES_FILE, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["file_name", "vendor_name", "document_type", "cuad_title"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    """Choose a diverse set of good CUAD contracts and write sources.csv."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--cuad-folder", required=True, help="The unzipped CUAD folder")
    parser.add_argument("--count", type=int, default=24, help="How many contracts to pick")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing sources.csv")
    args = parser.parse_args()

    if SOURCES_FILE.exists() and not args.overwrite:
        print("sources.csv already exists. Run again with --overwrite to replace it.")
        return

    cuad_folder = Path(args.cuad_folder)
    json_path = find_cuad_json(cuad_folder)
    if json_path is None:
        print("Could not find CUAD_v1.json inside", cuad_folder)
        return

    pdf_by_title = find_pdfs(cuad_folder)
    contracts_by_title = load_cuad_by_title(str(json_path))
    print("Contracts in the JSON:", len(contracts_by_title), "| PDFs found:", len(pdf_by_title))

    # Keep only contracts that have a PDF and enough labelled clauses
    candidates_by_type = {}
    matched = 0
    for title in sorted(contracts_by_title.keys()):
        if title not in pdf_by_title:
            continue
        matched += 1

        labels = read_contract_labels(contracts_by_title[title])
        answered, missing = count_labels(labels)
        if answered < MIN_ANSWERED or missing < 1:
            continue

        # The folder the PDF sits in tells us the contract type, like "Development"
        type_name = pdf_by_title[title].parent.name
        candidate = {"title": title, "type_name": type_name, "vendor_name": make_vendor_name(title)}

        if type_name not in candidates_by_type:
            candidates_by_type[type_name] = []
        candidates_by_type[type_name].append(candidate)

    print("Titles that matched a PDF:", matched)
    if matched == 0:
        print("No JSON title matched a PDF file name. Check that both come from the same CUAD download.")
        return

    selected = pick_contracts(candidates_by_type, pdf_by_title, args.count)
    copy_and_write_sources(selected, pdf_by_title)

    print("Selected", len(selected), "contracts:")
    for candidate in selected:
        print("  ", candidate["type_name"], "|", candidate["vendor_name"])
    print("Wrote", SOURCES_FILE)


if __name__ == "__main__":
    main()