import json
from pathlib import Path

EVAL_FOLDER = Path(__file__).resolve().parent

# Questions that the review found to be bad
KNOWN_BAD_IDS = {
    "questions.jsonl": ["q014", "q015", "q021", "q022", "q027", "q028", "q032", "q033"],
    "questions_amendments.jsonl": ["a002"],
}


def read_records(path: Path) -> list[dict]:
    """Read all questions from one .jsonl file."""
    records = []
    with open(path, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line == "":
                continue
            records.append(json.loads(line))
    return records


def main() -> None:
    """Print the state of every questions file, so you can see what is left to do."""
    for path in sorted(EVAL_FOLDER.glob("questions*.jsonl")):
        records = read_records(path)
        print(path.name, ":", len(records), "questions")

        counts = {}
        ids = []
        level_7_ids = []
        for record in records:
            level = record["level"]
            counts[level] = counts.get(level, 0) + 1
            ids.append(record["id"])
            if level == 7:
                level_7_ids.append(record["id"])

        for level in sorted(counts.keys()):
            print("   level", level, ":", counts[level])
        if len(level_7_ids) > 0:
            print("   level 7 ids:", level_7_ids)

        still_present = []
        for bad_id in KNOWN_BAD_IDS.get(path.name, []):
            if bad_id in ids:
                still_present.append(bad_id)
        if len(still_present) > 0:
            print("   KNOWN-BAD questions still present:", still_present)

        # The q007 question needs a decision, so its whole answer is shown
        for record in records:
            if record["id"] == "q007":
                print("   q007 (read this and decide):")
                print("  ", " ".join(record["expected_answer"].split()))


if __name__ == "__main__":
    main()