import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

# The script reuses the backend code, so the backend folder is added to the import path
EVAL_FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_FOLDER.parent / "backend"))

from app.llm import ask_llm  # noqa: E402
from build_dataset import CATEGORY_QUESTIONS, read_contract_labels, read_sources  # noqa: E402
from text_utils import load_cuad_by_title  # noqa: E402

OUTPUT_FILE = EVAL_FOLDER / "questions_synthetic.jsonl"

# Pause between LLM calls to stay under the free-tier limits
PAUSE_SECONDS = 5
MAX_CLAUSE_CHARS = 400
MAX_SENTENCE_CHARS = 500
TARGET_CHARS = 700

# Terms that are too general to make a good question
SKIPPED_TERMS = ["agreement", "party", "parties"]

# A defined term looks like: "Affiliate" means any company that ...
DEFINITION_PATTERN = re.compile(
    r'["\u201c]([A-Z][A-Za-z\- ]{2,40})["\u201d]\s+(?:shall\s+mean|means|mean|refers\s+to)\s+([^.]{20,400}\.)'
)

# A cross-reference looks like: "subject to Section 12.3"
REFERENCE_PATTERN = re.compile(
    r"(?:subject to|pursuant to|in accordance with|as provided in|as set forth in|except as provided in)"
    r"\s+(?:Section|Article)\s+(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)

# How a clause type is named inside a multi-part question
CATEGORY_PHRASES = {
    "Governing Law": "the governing law",
    "Expiration Date": "the expiration date",
    "Renewal Term": "the renewal term",
    "Termination For Convenience": "termination for convenience",
    "Cap On Liability": "the liability cap",
    "Audit Rights": "audit rights",
    "Non-Compete": "non-compete restrictions",
    "Anti-Assignment": "restrictions on assignment",
    "Exclusivity": "exclusivity",
    "Insurance": "insurance requirements",
}

CROSS_REFERENCE_SYSTEM_PROMPT = """You write test questions for a contract question-answering system.
You are given a clause that refers to another section, and the text that is supposed to be that other section."""


def make_record(number: int, level: int, row: dict, category: str, question: str, expected: str, supporting: str) -> dict:
    """Build one question record."""
    return {
        "id": "s" + str(number).zfill(3),
        "level": level,
        "vendor_name": row["vendor_name"],
        "file_name": row["file_name"],
        "category": category,
        "question": question,
        "expected_answer": expected,
        "supporting_text": supporting,
        "must_mention": [],
        "answerable": True,
    }


def build_defined_term_question(context: str, contract_index: int):
    """Level 4: ask what a defined term means. The definition itself is the ground truth."""
    # The contract text has line breaks everywhere, so we make it one line first
    text = " ".join(context.split())

    definitions = []
    for match in DEFINITION_PATTERN.finditer(text):
        term = match.group(1).strip()
        if term.lower() in SKIPPED_TERMS:
            continue
        definition = term + " means " + match.group(2).strip()
        definitions.append({"term": term, "definition": definition})

    if len(definitions) == 0:
        return None

    # A different definition for each contract keeps the questions varied
    chosen = definitions[contract_index % len(definitions)]
    question = 'What does "' + chosen["term"] + '" mean in this agreement?'
    return {"question": question, "expected": chosen["definition"], "supporting": chosen["definition"]}


def build_multi_part_question(labels: dict, contract_index: int):
    """Level 6: ask about two clauses at once. Both clause texts are the ground truth."""
    categories = list(CATEGORY_PHRASES.keys())
    start = (contract_index * 3) % len(categories)
    categories = categories[start:] + categories[:start]

    chosen = []
    for category in categories:
        texts = labels.get(category.lower(), [])
        if len(texts) > 0:
            chosen.append(category)
        if len(chosen) == 2:
            break

    if len(chosen) < 2:
        return None

    first_text = " ".join(labels[chosen[0].lower()])[:MAX_CLAUSE_CHARS]
    second_text = " ".join(labels[chosen[1].lower()])[:MAX_CLAUSE_CHARS]
    both_texts = first_text + " " + second_text

    question = "What does this agreement say about " + CATEGORY_PHRASES[chosen[0]]
    question += " and " + CATEGORY_PHRASES[chosen[1]] + "?"
    return {"question": question, "expected": both_texts, "supporting": both_texts, "category": chosen[0] + " + " + chosen[1]}


def find_section_text(context: str, section_number: str, reference_position: int) -> str:
    """Find the text of a section in the raw contract text. Returns an empty string if not found."""
    # A section starts at the beginning of a line, like "12.3 Limitation of Liability"
    pattern = re.compile(r"(?m)^\s*(?:Section\s+)?" + re.escape(section_number) + r"[.)]?\s+[A-Z]")

    for match in pattern.finditer(context):
        # Skip matches that are the reference itself
        if abs(match.start() - reference_position) < 200:
            continue
        text = context[match.start() : match.start() + TARGET_CHARS]
        return " ".join(text.split())
    return ""


def find_cross_reference(context: str):
    """Find a sentence that points to another section, together with that section's text."""
    for match in REFERENCE_PATTERN.finditer(context):
        section_number = match.group(1)

        # The sentence that holds the reference
        sentence_start = context.rfind(".", 0, match.start()) + 1
        sentence_end = context.find(".", match.end())
        if sentence_end == -1:
            continue
        sentence = " ".join(context[sentence_start : sentence_end + 1].split())
        if len(sentence) < 40 or len(sentence) > MAX_SENTENCE_CHARS:
            continue

        target = find_section_text(context, section_number, match.start())
        if target == "":
            continue

        return {"section_number": section_number, "sentence": sentence, "target": target}
    return None


def parse_llm_json(text: str):
    """Read the LLM reply. Returns None if it said SKIP or did not send valid JSON."""
    text = text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    if text.startswith("SKIP"):
        return None

    # LLMs sometimes send broken JSON, so this try/catch is needed
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    if "question" not in data or "answer" not in data:
        return None
    return data


async def build_cross_reference_question(reference: dict):
    """Level 3: ask the LLM to write a question that needs both texts."""
    number = reference["section_number"]

    user_prompt = "CLAUSE:\n" + reference["sentence"] + "\n\n"
    user_prompt += "REFERENCED SECTION " + number + " (it may be the wrong text):\n" + reference["target"] + "\n\n"
    user_prompt += "Task: If the referenced text really looks like Section " + number + ", write ONE question that "
    user_prompt += "a business user could ask in everyday words, which can only be answered fully by combining both texts. "
    user_prompt += "Do not mention section numbers in the question. Write the answer in 1 to 3 sentences, "
    user_prompt += "using only the two texts.\n"
    user_prompt += "If the referenced text does not look like Section " + number + ", or the two texts do not need to be "
    user_prompt += "combined, reply with exactly: SKIP\n"
    user_prompt += 'Otherwise reply with JSON only: {"question": "...", "answer": "..."}'

    reply = await ask_llm("smart", CROSS_REFERENCE_SYSTEM_PROMPT, user_prompt)
    data = parse_llm_json(reply)
    if data is None:
        return None

    supporting = reference["sentence"] + " " + reference["target"]
    return {"question": data["question"], "expected": data["answer"], "supporting": supporting[:1200]}


async def main_async(args) -> None:
    """Build the level 3, 4 and 6 questions."""
    contracts_by_title = load_cuad_by_title(args.cuad_json)

    sources = read_sources()
    if args.max_contracts > 0:
        sources = sources[: args.max_contracts]

    records = []
    cross_count = 0

    for contract_index, row in enumerate(sources):
        title = row["cuad_title"]
        if title not in contracts_by_title:
            print("Title not found in the CUAD file, skipped:", title)
            continue

        contract = contracts_by_title[title]
        context = contract["paragraphs"][0]["context"]
        labels = read_contract_labels(contract)
        print("Contract", contract_index + 1, row["vendor_name"])

        defined = build_defined_term_question(context, contract_index)
        if defined is not None:
            record = make_record(len(records) + 1, 4, row, "Defined Term", defined["question"], defined["expected"], defined["supporting"])
            records.append(record)

        multi = build_multi_part_question(labels, contract_index)
        if multi is not None:
            record = make_record(len(records) + 1, 6, row, multi["category"], multi["question"], multi["expected"], multi["supporting"])
            records.append(record)

        if args.skip_llm or cross_count >= args.max_cross:
            continue

        reference = find_cross_reference(context)
        if reference is None:
            continue

        cross = await build_cross_reference_question(reference)
        await asyncio.sleep(PAUSE_SECONDS)
        if cross is None:
            print("  cross-reference candidate rejected")
            continue

        record = make_record(len(records) + 1, 3, row, "Cross Reference", cross["question"], cross["expected"], cross["supporting"])
        records.append(record)
        cross_count += 1

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record) + "\n")

    print("Wrote", len(records), "questions to", OUTPUT_FILE)
    for level in [3, 4, 6]:
        count = 0
        for record in records:
            if record["level"] == level:
                count += 1
        print("  level", level, ":", count)
    print("Now open the file and check every question and expected answer by hand.")


def main() -> None:
    """Read the command line arguments and run the builder."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--cuad-json", required=True, help="Path to CUAD_v1.json")
    parser.add_argument("--max-contracts", type=int, default=8, help="Only use the first N contracts (0 = all)")
    parser.add_argument("--max-cross", type=int, default=8, help="Most level 3 questions to create")
    parser.add_argument("--skip-llm", action="store_true", help="Skip level 3, which needs the LLM")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()