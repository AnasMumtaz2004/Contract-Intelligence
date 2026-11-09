import csv
import json
from pathlib import Path

EVAL_FOLDER = Path(__file__).resolve().parent
SCANNED_SOURCES = EVAL_FOLDER.parent / "data" / "synthetic" / "scanned" / "sources_scanned.csv"
QUESTIONS_FILE = EVAL_FOLDER / "questions.jsonl"
OUTPUT_FILE = EVAL_FOLDER / "questions_scanned.jsonl"

SCANNED_ENDING = " Scan"


def main() -> None:
    """Copy the questions of every scanned contract, so the scan and the original can be compared."""
    # Map: scanned vendor name -> scanned file name
    scanned_files = {}
    with open(SCANNED_SOURCES, encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            scanned_files[row["vendor_name"]] = row["file_name"]

    records = []
    with open(QUESTIONS_FILE, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line == "":
                continue
            original = json.loads(line)

            scanned_vendor = original["vendor_name"] + SCANNED_ENDING
            if scanned_vendor not in scanned_files:
                continue

            copy = dict(original)
            # The new id starts with "c" (for copy of a scan) so it never clashes
            copy["id"] = "c" + original["id"][1:]
            copy["vendor_name"] = scanned_vendor
            copy["file_name"] = scanned_files[scanned_vendor]
            records.append(copy)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record) + "\n")

    print("Wrote", len(records), "questions to", OUTPUT_FILE)


if __name__ == "__main__":
    main()