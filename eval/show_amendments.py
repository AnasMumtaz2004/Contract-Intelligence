import json
from pathlib import Path

EVAL_FOLDER = Path(__file__).resolve().parent
MANIFEST_FILE = EVAL_FOLDER.parent / "data" / "synthetic" / "amendments" / "manifest.json"
QUESTIONS_FILE = EVAL_FOLDER / "questions_amendments.jsonl"


def main() -> None:
    """Print every amendment (old and new clause) and every level 5 question for review."""
    with open(MANIFEST_FILE, encoding="utf-8") as file:
        manifest = json.load(file)

    for family in manifest:
        print("=" * 70)
        print("Family", family["family"], "|", family["plan"], "|", family["vendor_name"])
        print("Base file:", family["base_file"])

        for amendment in family["amendments"]:
            section_label = amendment["section_label"]
            if section_label == "":
                section_label = "(section not found)"

            print("-" * 70)
            print("Amendment", amendment["number"], "| effective", amendment["effective_date"], "|", amendment["kind"])
            print("Replaces:", section_label)
            print("OLD (" + str(len(amendment["old_clause"].split())) + " words):")
            print(amendment["old_clause"])
            print("NEW (" + str(len(amendment["new_clause"].split())) + " words):")
            print(amendment["new_clause"])

    print("=" * 70)
    print("Level 5 questions")
    with open(QUESTIONS_FILE, encoding="utf-8") as file:
        for line in file:
            record = json.loads(line)
            print(record["id"], "|", record["variant"], "|", record["question"])
            print("    must mention one of:", record["must_mention"])


if __name__ == "__main__":
    main()