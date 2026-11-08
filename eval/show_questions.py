import json
import sys
from pathlib import Path

EVAL_FOLDER = Path(__file__).resolve().parent

# By default only the start of each expected answer is shown
MAX_ANSWER_CHARS = 220


def main() -> None:
    """Print one short entry per question, so the questions can be reviewed quickly."""
    # The first argument that does not start with "--" is the file name
    file_name = "questions.jsonl"
    for argument in sys.argv[1:]:
        if not argument.startswith("--"):
            file_name = argument

    # With --full the whole expected answer is printed
    max_chars = MAX_ANSWER_CHARS
    if "--full" in sys.argv:
        max_chars = 100000

    count = 0
    with open(EVAL_FOLDER / file_name, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line == "":
                continue
            record = json.loads(line)
            count += 1

            # Level 2 repeats the level 1 answer, so it is skipped to keep the list short
            if record["level"] == 2:
                continue

            print(record["id"], "| level", record["level"], "|", record["vendor_name"], "|", record["category"])
            print("   Q:", record["question"])
            if record["answerable"]:
                answer = " ".join(record["expected_answer"].split())
                print("   A:", answer[:max_chars])
            else:
                print("   A: (this clause is NOT in the contract)")

    print("Total questions in", file_name, ":", count)


if __name__ == "__main__":
    main()