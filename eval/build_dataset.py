import argparse
import csv
import json
import re
from pathlib import Path

EVAL_FOLDER = Path(__file__).resolve().parent
SOURCES_FILE = EVAL_FOLDER.parent / "data" / "cuad_subset" / "sources.csv"
OUTPUT_FILE = EVAL_FOLDER / "questions.jsonl"

# For each contract we pick this many clauses that exist, and this many that are missing
ANSWERED_PER_CONTRACT = 2
MISSING_PER_CONTRACT = 1

# Longest clause text we keep as the expected answer
MAX_ANSWER_CHARS = 600

# CUAD category -> (direct question, everyday-words question)
CATEGORY_QUESTIONS = {
    "Governing Law": (
        "What law governs this agreement?",
        "Which state's or country's laws apply if we have a dispute about this contract?",
    ),
    "Expiration Date": (
        "When does this agreement expire?",
        "When does this contract run out?",
    ),
    "Renewal Term": (
        "What is the renewal term of this agreement?",
        "If this contract renews, for how long does it continue?",
    ),
    "Termination For Convenience": (
        "Can a party terminate this agreement for convenience?",
        "Can we cancel this contract early without giving a reason?",
    ),
    "Cap On Liability": (
        "Is there a cap on liability in this agreement?",
        "Is there a limit on how much one side can be made to pay if something goes wrong?",
    ),
    "Audit Rights": (
        "Does either party have audit rights?",
        "Can the other side check our books or records?",
    ),
    "Non-Compete": (
        "Does this agreement contain a non-compete clause?",
        "Are we stopped from working with competitors because of this contract?",
    ),
    "Anti-Assignment": (
        "Does this agreement restrict assignment?",
        "Can we hand this contract over to another company?",
    ),
    "Exclusivity": (
        "Does this agreement contain an exclusivity clause?",
        "Are we tied to only one supplier or customer under this contract?",
    ),
    "Insurance": (
        "Is either party required to maintain insurance?",
        "Do we have to carry insurance because of this contract?",
    ),
}


def read_sources() -> list[dict]:
    """Read sources.csv and return one dictionary per row."""
    with open(SOURCES_FILE, encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader)


def get_category(question_text: str) -> str:
    """Get the category name from a CUAD question, like Governing Law."""
    # CUAD questions put the category in double quotes
    match = re.search(r'"([^"]+)"', question_text)
    if match is None:
        return ""
    return match.group(1)


def read_contract_labels(contract: dict) -> dict:
    """Return {category (lowercase): list of answer texts} for one CUAD contract."""
    paragraph = contract["paragraphs"][0]

    labels = {}
    for qa in paragraph["qas"]:
        category = get_category(qa["question"])
        if category == "":
            continue

        answer_texts = []
        for answer in qa["answers"]:
            answer_texts.append(answer["text"])
        labels[category.lower()] = answer_texts
    return labels


def make_record(question_id: int, row: dict, category: str, level: int, question: str, answers: list[str]) -> dict:
    """Build one question record for questions.jsonl."""
    supporting_text = " ".join(answers)
    supporting_text = supporting_text[:MAX_ANSWER_CHARS]

    return {
        "id": "q" + str(question_id).zfill(3),
        "level": level,
        "vendor_name": row["vendor_name"],
        "file_name": row["file_name"],
        "category": category,
        "question": question,
        "expected_answer": supporting_text,
        "supporting_text": supporting_text,
        "answerable": len(answers) > 0,
    }


def build_records_for_contract(row: dict, labels: dict, contract_index: int, next_id: int) -> list[dict]:
    """Make the level 1, 2 and 7 questions for one contract."""
    categories = list(CATEGORY_QUESTIONS.keys())

    # Start at a different category for each contract, so the questions are not all the same
    start = contract_index % len(categories)
    categories = categories[start:] + categories[:start]

    records = []
    answered_count = 0
    missing_count = 0

    for category in categories:
        key = category.lower()
        if key not in labels:
            continue

        answers = labels[key]
        direct_question, everyday_question = CATEGORY_QUESTIONS[category]

        if len(answers) > 0 and answered_count < ANSWERED_PER_CONTRACT:
            # The same clause is asked twice: once directly (level 1), once in everyday words (level 2)
            records.append(make_record(next_id + len(records), row, category, 1, direct_question, answers))
            records.append(make_record(next_id + len(records), row, category, 2, everyday_question, answers))
            answered_count += 1
        elif len(answers) == 0 and missing_count < MISSING_PER_CONTRACT:
            # No annotated answer means the clause is not in the contract (level 7)
            records.append(make_record(next_id + len(records), row, category, 7, direct_question, []))
            missing_count += 1

    return records


def main() -> None:
    """Build eval/questions.jsonl from the CUAD labels of the contracts in sources.csv."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--cuad-json", required=True, help="Path to CUAD_v1.json")
    parser.add_argument("--max-contracts", type=int, default=0, help="Only use the first N contracts (0 = all)")
    args = parser.parse_args()

    with open(args.cuad_json, encoding="utf-8") as file:
        cuad = json.load(file)

    contracts_by_title = {}
    for contract in cuad["data"]:
        contracts_by_title[contract["title"]] = contract

    sources = read_sources()
    if args.max_contracts > 0:
        sources = sources[: args.max_contracts]

    all_records = []
    for contract_index, row in enumerate(sources):
        title = row["cuad_title"]
        if title not in contracts_by_title:
            print("Title not found in the CUAD file, skipped:", title)
            continue

        labels = read_contract_labels(contracts_by_title[title])
        records = build_records_for_contract(row, labels, contract_index, len(all_records) + 1)
        all_records.extend(records)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        for record in all_records:
            file.write(json.dumps(record) + "\n")

    print("Wrote", len(all_records), "questions to", OUTPUT_FILE)
    for level in [1, 2, 7]:
        count = 0
        for record in all_records:
            if record["level"] == level:
                count += 1
        print("  level", level, ":", count)
    print("Now open the file and check every question and expected answer by hand.")
    
    
if __name__ == "__main__":
    main()