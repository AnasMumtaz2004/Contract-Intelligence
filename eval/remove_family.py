import argparse
import csv
import json
from pathlib import Path

EVAL_FOLDER = Path(__file__).resolve().parent
AMENDMENTS_FOLDER = EVAL_FOLDER.parent / "data" / "synthetic" / "amendments"
MANIFEST_FILE = AMENDMENTS_FOLDER / "manifest.json"
SOURCES_FILE = AMENDMENTS_FOLDER / "sources_amendments.csv"
QUESTIONS_FILE = EVAL_FOLDER / "questions_amendments.jsonl"


def remove_from_manifest(vendor_name: str) -> list[str]:
    """Remove the family from manifest.json. Returns the amendment PDF names that belonged to it."""
    with open(MANIFEST_FILE, encoding="utf-8") as file:
        manifest = json.load(file)

    kept_families = []
    pdf_names = []
    for family in manifest:
        if family["vendor_name"].lower() == vendor_name.lower():
            for amendment in family["amendments"]:
                pdf_names.append(amendment["file_name"])
        else:
            kept_families.append(family)

    with open(MANIFEST_FILE, "w", encoding="utf-8") as file:
        json.dump(kept_families, file, indent=2)
    return pdf_names


def remove_from_sources(vendor_name: str) -> int:
    """Remove the family's rows from sources_amendments.csv. Returns how many rows were removed."""
    with open(SOURCES_FILE, encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        field_names = reader.fieldnames
        rows = list(reader)

    kept_rows = []
    for row in rows:
        if row["vendor_name"].lower() != vendor_name.lower():
            kept_rows.append(row)

    with open(SOURCES_FILE, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=field_names)
        writer.writeheader()
        writer.writerows(kept_rows)
    return len(rows) - len(kept_rows)


def remove_from_questions(vendor_name: str) -> int:
    """Remove the family's questions from questions_amendments.jsonl. Returns how many were removed."""
    kept_lines = []
    removed_count = 0

    with open(QUESTIONS_FILE, encoding="utf-8") as file:
        for line in file:
            if line.strip() == "":
                continue
            record = json.loads(line)
            if record["vendor_name"].lower() == vendor_name.lower():
                removed_count += 1
            else:
                kept_lines.append(line.rstrip("\n"))

    with open(QUESTIONS_FILE, "w", encoding="utf-8") as file:
        for line in kept_lines:
            file.write(line + "\n")
    return removed_count


def main() -> None:
    """Remove one amendment family (PDFs, manifest, sources and questions)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor", required=True, help="Vendor name of the family, as in manifest.json")
    args = parser.parse_args()

    pdf_names = remove_from_manifest(args.vendor)
    if len(pdf_names) == 0:
        print("No family found for vendor:", args.vendor)
        return

    deleted_pdfs = 0
    for pdf_name in pdf_names:
        pdf_path = AMENDMENTS_FOLDER / pdf_name
        if pdf_path.exists():
            pdf_path.unlink()
            deleted_pdfs += 1

    removed_rows = remove_from_sources(args.vendor)
    removed_questions = remove_from_questions(args.vendor)

    print("Removed family for", args.vendor)
    print("  PDFs deleted:", deleted_pdfs)
    print("  source rows removed:", removed_rows)
    print("  questions removed:", removed_questions)


if __name__ == "__main__":
    main()