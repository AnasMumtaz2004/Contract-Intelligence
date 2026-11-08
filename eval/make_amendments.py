import argparse
import asyncio
import csv
import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

# The script reuses the backend code, so the backend folder is added to the import path
EVAL_FOLDER = Path(__file__).resolve().parent
PROJECT_ROOT = EVAL_FOLDER.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.platypus import Paragraph, SimpleDocTemplate  # noqa: E402

from app.ingestion.parsing import parse_pdf  # noqa: E402
from app.ingestion.structure import find_sections, get_section_text  # noqa: E402
from app.llm import ask_llm  # noqa: E402
from build_dataset import CATEGORY_QUESTIONS, read_contract_labels, read_sources  # noqa: E402
from text_utils import clean_file_name, load_cuad_by_title, overlap_share  # noqa: E402

DATA_ROOT = PROJECT_ROOT / "data"
CUAD_FOLDER = DATA_ROOT / "cuad_subset"
AMENDMENTS_FOLDER = DATA_ROOT / "synthetic" / "amendments"
QUESTIONS_FILE = EVAL_FOLDER / "questions_amendments.jsonl"

MAX_CLAUSE_CHARS = 1500
# Pause between LLM calls to stay under the free-tier limits
PAUSE_SECONDS = 5
# A section must share at least this much text with the clause to count as a match
SECTION_MATCH_SHARE = 0.3

# Amendment number -> (date for the manifest, date written in the PDF)
AMENDMENT_DATES = [
    ("2024-03-01", "March 1, 2024"),
    ("2024-09-01", "September 1, 2024"),
]

DISCLAIMER = "This document was generated for software testing. It is not a real legal agreement."

REWRITE_SYSTEM_PROMPT = """You are a contract drafting assistant.
You rewrite one clause of a contract.

Rules:
1. Make only the change that is requested. Keep every other word as close to the original as possible.
2. Reply with the new clause text only, as one paragraph.
3. Do not add a section number, quotation marks, or any explanation."""

# Each plan describes one contract family.
# "checks" are words, and at least one of them must appear in the new clause.
FAMILY_PLANS = [
    {
        "name": "governing_law_single",
        "kind": "replace",
        "category": "Governing Law",
        "topic": "governing law",
        "base_keywords": ["law"],
        "question": "Which law currently governs this agreement?",
        "steps": [
            {
                "instruction": "Change the governing law so that the laws of the State of New York apply.",
                "summary": "the laws of the State of New York",
                "checks": ["new york"],
            },
        ],
    },
    {
        "name": "governing_law_chain",
        "kind": "replace",
        "category": "Governing Law",
        "topic": "governing law",
        "base_keywords": ["law"],
        "question": "Which law currently governs this agreement?",
        "steps": [
            {
                "instruction": "Change the governing law so that the laws of the State of New York apply.",
                "summary": "the laws of the State of New York",
                "checks": ["new york"],
            },
            {
                "instruction": "Change the governing law so that the laws of the State of California apply.",
                "summary": "the laws of the State of California",
                "checks": ["california"],
            },
        ],
    },
    {
        "name": "liability_cap",
        "kind": "replace",
        "category": "Cap On Liability",
        "topic": "limitation of liability",
        "base_keywords": ["liab"],
        "question": "What is the current cap on liability in this agreement?",
        "steps": [
            {
                "instruction": (
                    "Change the cap so that each party's total liability is limited to the fees paid or payable "
                    "in the twelve (12) months before the claim. Keep any exceptions to the cap as they are."
                ),
                "summary": "total liability limited to the fees paid or payable in the twelve (12) months before the claim",
                "checks": ["twelve", "12 months", "12) months"],
            },
        ],
    },
    {
        "name": "termination_notice",
        "kind": "replace",
        "category": "Termination For Convenience",
        "topic": "termination for convenience",
        "base_keywords": ["terminat"],
        "question": "How much notice is needed to terminate this agreement for convenience now?",
        "steps": [
            {
                "instruction": (
                    "Change only the notice period so that it is sixty (60) days' prior written notice. "
                    "Do not change which party may terminate."
                ),
                "summary": "sixty (60) days' prior written notice",
                "checks": ["sixty", "60"],
            },
        ],
    },
    {
        "name": "insurance_added",
        "kind": "add",
        "category": "Insurance",
        "topic": "insurance",
        "question": "What insurance must each party maintain under this agreement?",
        "clause_text": (
            "Insurance. Each party shall maintain commercial general liability insurance with limits of "
            "not less than $2,000,000 per occurrence throughout the term of this Agreement."
        ),
        "summary": "commercial general liability insurance of at least $2,000,000 per occurrence",
        "checks": ["2,000,000"],
    },
]


def clean_clause(text: str) -> str:
    """Remove quotes, a leading section number and extra spaces from a clause."""
    text = " ".join(text.split())
    text = text.strip('"').strip("\u201c").strip("\u201d")
    # The model sometimes starts with a section number like "12.3". We remove it.
    text = re.sub(r"^\d+(\.\d+)*[.)]?\s+", "", text)
    return text.strip()


def has_required_words(text: str, checks: list[str]) -> bool:
    """Check that at least one of the required words appears in the text."""
    lower_text = text.lower()
    for check in checks:
        if check.lower() in lower_text:
            return True
    return False


async def write_new_clause(old_clause: str, step: dict) -> str:
    """Ask the LLM to rewrite a clause. Returns an empty string if the change is missing."""
    print("  asking the LLM to rewrite the clause...")
    user_prompt = "ORIGINAL CLAUSE:\n" + old_clause + "\n\nCHANGE REQUEST:\n" + step["instruction"]
    user_prompt += "\n\nWrite the full new version of the clause."

    # Two tries: the second one reminds the model that the change was missing
    for attempt in range(2):
        text = await ask_llm("smart", REWRITE_SYSTEM_PROMPT, user_prompt)
        text = clean_clause(text)
        if has_required_words(text, step["checks"]):
            return text

        user_prompt += "\n\nYour last answer did not contain the requested change. Try again."
        await asyncio.sleep(PAUSE_SECONDS)

    return ""


def find_section_label(pdf_path: str, clause_text: str) -> str:
    """Find the section of the base contract that holds the clause, like 'Section 12.3'."""
    pages = parse_pdf(pdf_path)
    sections = find_sections(pages)

    best_section = None
    best_share = 0.0
    for section in sections:
        share = overlap_share(clause_text, get_section_text(section))
        if share > best_share:
            best_share = share
            best_section = section

    if best_section is None or best_share < SECTION_MATCH_SHARE:
        return ""
    if best_section["number"] is None:
        return ""
    return "Section " + best_section["number"]


def make_replace_sentence(section_label: str, topic: str, number: int) -> str:
    """Write the sentence that tells the reader which clause is replaced."""
    if section_label != "":
        target = section_label + " of the Agreement"
    else:
        target = "The provision of the Agreement on " + topic

    # The second amendment replaces a clause that the first amendment already changed
    if number > 1:
        target += " (as amended by Amendment No. " + str(number - 1) + ")"

    return target + " is deleted in its entirety and replaced with the following:"


def write_amendment_pdf(
    pdf_path: Path,
    number: int,
    vendor_name: str,
    date_text: str,
    intro_sentence: str,
    new_clause: str,
) -> None:
    """Create the amendment PDF. Headings are numbered, so our parser can find them."""
    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle(
        "AmendmentHeading", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=12, spaceBefore=12, spaceAfter=6
    )
    body_style = ParagraphStyle("AmendmentBody", parent=styles["Normal"], fontSize=11, leading=15, spaceAfter=8)
    clause_style = ParagraphStyle("AmendmentClause", parent=body_style, leftIndent=24)

    title = "AMENDMENT NO. " + str(number) + " TO AGREEMENT WITH " + vendor_name.upper()
    opening = 'This Amendment No. ' + str(number) + ' (the "Amendment") is made as of ' + date_text
    opening += " between " + vendor_name + " and the other party to the Agreement described below."

    parts = []
    parts.append(Paragraph(escape(title), styles["Title"]))
    parts.append(Paragraph(escape(opening), body_style))

    parts.append(Paragraph("1. Background", heading_style))
    background = 'The parties entered into an agreement (the "Agreement"). They now wish to amend it as set out below.'
    parts.append(Paragraph(escape(background), body_style))

    parts.append(Paragraph("2. Amendment", heading_style))
    parts.append(Paragraph(escape(intro_sentence), body_style))
    parts.append(Paragraph(escape(new_clause), clause_style))

    parts.append(Paragraph("3. Effect of Amendment", heading_style))
    effect = "Except as expressly amended by this Amendment, all terms of the Agreement remain in full force and effect. "
    effect += "If this Amendment conflicts with the Agreement, this Amendment controls."
    parts.append(Paragraph(escape(effect), body_style))

    parts.append(Paragraph("4. Effective Date", heading_style))
    parts.append(Paragraph(escape("This Amendment takes effect on " + date_text + "."), body_style))

    parts.append(Paragraph(escape(DISCLAIMER), body_style))

    document = SimpleDocTemplate(str(pdf_path), pagesize=letter, topMargin=72, bottomMargin=72)
    document.build(parts)


def clause_has_keyword(clause_text: str, keywords: list[str]) -> bool:
    """Check that the clause text contains at least one of the keywords."""
    lower_text = clause_text.lower()
    for keyword in keywords:
        if keyword in lower_text:
            return True
    return False


def find_base_row(plan: dict, rows: list[dict], labels_by_file: dict, used_files: set):
    """Find an unused base contract that fits the plan."""
    key = plan["category"].lower()

    for row in rows:
        file_name = row["file_name"]
        if file_name in used_files:
            continue

        labels = labels_by_file.get(file_name)
        if labels is None or key not in labels:
            continue

        has_clause = len(labels[key]) > 0

        if plan["kind"] == "add" and not has_clause:
            return row

        if plan["kind"] == "replace" and has_clause:
            # The CUAD label can point at the wrong text, so we check that the clause is about the topic
            clause_text = " ".join(labels[key])
            keywords = plan.get("base_keywords", [])
            if len(keywords) > 0 and not clause_has_keyword(clause_text, keywords):
                continue
            return row

    return None

def pick_unchanged_category(plan: dict, labels: dict):
    """Pick another clause of the base contract that the amendments do not touch."""
    for category in CATEGORY_QUESTIONS:
        if category == plan["category"]:
            continue
        if len(labels.get(category.lower(), [])) > 0:
            return category
    return None


async def build_family(plan: dict, row: dict, labels: dict):
    """Create the amendment PDFs for one family. Returns None if a clause could not be written."""
    vendor_name = row["vendor_name"]
    base_path = CUAD_FOLDER / row["file_name"]
    key = plan["category"].lower()
    old_clause = " ".join(labels[key])[:MAX_CLAUSE_CHARS]

    section_label = ""
    if plan["kind"] == "replace":
        section_label = find_section_label(str(base_path), old_clause)

    if plan["kind"] == "add":
        steps = [{"summary": plan["summary"], "checks": plan["checks"]}]
    else:
        steps = plan["steps"]

    amendments = []
    current_clause = old_clause

    for step_index, step in enumerate(steps):
        number = step_index + 1
        iso_date, date_text = AMENDMENT_DATES[step_index]

        if plan["kind"] == "add":
            new_clause = plan["clause_text"]
            intro_sentence = "The following new provision is added to the Agreement:"
        else:
            new_clause = await write_new_clause(current_clause, step)
            await asyncio.sleep(PAUSE_SECONDS)
            if new_clause == "":
                print("  could not get a correct clause from the LLM, family skipped:", plan["name"])
                return None
            intro_sentence = make_replace_sentence(section_label, plan["topic"], number)

        file_name = clean_file_name(vendor_name) + "_amendment_" + str(number) + ".pdf"
        write_amendment_pdf(AMENDMENTS_FOLDER / file_name, number, vendor_name, date_text, intro_sentence, new_clause)

        amendments.append(
            {
                "file_name": file_name,
                "number": number,
                "effective_date": iso_date,
                "category": plan["category"],
                "kind": plan["kind"],
                "section_label": section_label,
                "old_clause": current_clause,
                "new_clause": new_clause,
                "summary": step["summary"],
            }
        )
        # The next amendment in a chain replaces the clause that was just written
        current_clause = new_clause

    return amendments


def make_question_record(
    record_id: str, row: dict, plan: dict, question: str, expected: str, supporting: str, variant: str, amendments: list
) -> dict:
    """Build one level 5 question record."""
    amendment_files = []
    for amendment in amendments:
        amendment_files.append(amendment["file_name"])

    return {
        "id": record_id,
        "level": 5,
        "variant": variant,
        "vendor_name": row["vendor_name"],
        "file_name": row["file_name"],
        "amendment_files": amendment_files,
        "category": plan["category"],
        "question": question,
        "expected_answer": expected,
        "supporting_text": supporting,
        "must_mention": [],
        "answerable": True,
    }


async def main_async(args) -> None:
    """Build every planned family and write the manifest, sources and questions."""
    rows = read_sources()
    contracts_by_title = load_cuad_by_title(args.cuad_json)

    # The first contracts have level 1 and 2 questions, so they must not be amended
    candidate_rows = rows[args.skip_first :]

    labels_by_file = {}
    for row in candidate_rows:
        if row["cuad_title"] in contracts_by_title:
            labels_by_file[row["file_name"]] = read_contract_labels(contracts_by_title[row["cuad_title"]])

    AMENDMENTS_FOLDER.mkdir(parents=True, exist_ok=True)

    manifest = []
    source_rows = []
    question_records = []
    used_files = set()

    for family_number, plan in enumerate(FAMILY_PLANS, start=1):
        row = find_base_row(plan, candidate_rows, labels_by_file, used_files)
        if row is None:
            print("No fitting base contract for", plan["name"], "(try a bigger --count in step 1)")
            continue

        print("Family", family_number, plan["name"], "->", row["vendor_name"])
        labels = labels_by_file[row["file_name"]]
        amendments = await build_family(plan, row, labels)
        if amendments is None:
            continue
        used_files.add(row["file_name"])

        manifest.append({"family": family_number, "plan": plan["name"], "vendor_name": row["vendor_name"], "base_file": row["file_name"], "amendments": amendments})

        for amendment in amendments:
            source_rows.append(
                {
                    "file_name": "synthetic/amendments/" + amendment["file_name"],
                    "vendor_name": row["vendor_name"],
                    "document_type": "Amendment",
                    "cuad_title": row["cuad_title"],
                    "effective_date": amendment["effective_date"],
                    "parent_file_name": row["file_name"],
                }
            )

        # Question about the clause after all amendments
        final_amendment = amendments[-1]
        if plan["kind"] == "add":
            variant = "added"
        elif len(amendments) > 1:
            variant = "chain"
        else:
            variant = "changed"

        expected = "The current term is " + final_amendment["summary"]
        expected += ", as set by Amendment No. " + str(final_amendment["number"]) + "."
        record_id = "a" + str(len(question_records) + 1).zfill(3)
        record = make_question_record(record_id, row, plan, plan["question"], expected, final_amendment["new_clause"], variant, amendments)
        # The answer must contain one of these words, which we can check without an LLM
        if plan["kind"] == "add":
            record["must_mention"] = plan["checks"]
        else:
            record["must_mention"] = plan["steps"][-1]["checks"]
        question_records.append(record)

        # Question about a clause that no amendment touched. The answer must stay the same.
        if plan["kind"] == "replace":
            other_category = pick_unchanged_category(plan, labels)
            if other_category is not None:
                base_clause = " ".join(labels[other_category.lower()])[:MAX_CLAUSE_CHARS]
                direct_question = CATEGORY_QUESTIONS[other_category][0]
                record_id = "a" + str(len(question_records) + 1).zfill(3)
                other_plan = {"category": other_category}
                question_records.append(make_question_record(record_id, row, other_plan, direct_question, base_clause, base_clause, "unchanged", []))

    with open(AMENDMENTS_FOLDER / "manifest.json", "w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)

    field_names = ["file_name", "vendor_name", "document_type", "cuad_title", "effective_date", "parent_file_name"]
    with open(AMENDMENTS_FOLDER / "sources_amendments.csv", "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=field_names)
        writer.writeheader()
        writer.writerows(source_rows)

    with open(QUESTIONS_FILE, "w", encoding="utf-8") as file:
        for record in question_records:
            file.write(json.dumps(record) + "\n")

    print("Families built:", len(manifest))
    print("Amendment PDFs:", len(source_rows))
    print("Level 5 questions:", len(question_records))
    print("Now open the PDFs and manifest.json and check every new clause by hand.")


def main() -> None:
    """Read the command line arguments and run the builder."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--cuad-json", required=True, help="Path to CUAD_v1.json")
    parser.add_argument("--skip-first", type=int, default=8, help="Contracts at the top of sources.csv that must not be amended")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()