import argparse
import json
from pathlib import Path

EVAL_FOLDER = Path(__file__).resolve().parent


def main() -> None:
    """Remove questions from a questions file, using their ids."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="questions.jsonl", help="Which questions file to change")
    parser.add_argument("--ids", nargs="+", required=True, help="Ids to remove, like q014 q015")
    args = parser.parse_args()

    path = EVAL_FOLDER / args.file

    kept_lines = []
    removed_ids = []
    with open(path, encoding="utf-8") as file:
        for line in file:
            if line.strip() == "":
                continue
            record = json.loads(line)
            if record["id"] in args.ids:
                removed_ids.append(record["id"])
            else:
                kept_lines.append(line.rstrip("\n"))

    with open(path, "w", encoding="utf-8") as file:
        for line in kept_lines:
            file.write(line + "\n")

    print("Removed:", removed_ids)
    for question_id in args.ids:
        if question_id not in removed_ids:
            print("Not found:", question_id)
    print("Questions left in", args.file, ":", len(kept_lines))


if __name__ == "__main__":
    main()