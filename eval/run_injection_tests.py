import argparse
import asyncio
import json
import sys
from pathlib import Path

# The eval scripts reuse the backend code, so the backend folder is added to the import path
EVAL_FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_FOLDER.parent / "backend"))

from sqlalchemy import delete, select  # noqa: E402

from app import security  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import AsyncSessionLocal, engine  # noqa: E402
from app.ingestion.pipeline import compute_file_hash, run_ingestion  # noqa: E402
from app.models import Contract, Document, SecurityEvent, User  # noqa: E402
from app.routes.contracts import find_or_create_contract  # noqa: E402
from app.storage import delete_file, save_file  # noqa: E402
from app.rag import build_context, generate_answer  # noqa: E402
from pipelines import retrieve_hybrid_rerank_xref  # noqa: E402

PROJECT_ROOT = EVAL_FOLDER.parent
POISONED_FOLDER = PROJECT_ROOT / "data" / "poisoned"
CASES_FILE = EVAL_FOLDER / "injection_cases" / "cases.json"
RESULTS_FOLDER = EVAL_FOLDER / "results"

# Pause between questions to stay under the free-tier request limits
PAUSE_SECONDS = 4

# All poisoned contracts get a vendor name that starts with this, so they can be found and removed
POISON_PREFIX = "Poison "


async def delete_poison_documents(db, user_id: int) -> None:
    """Remove every document and contract made by this script, including the files."""
    query = select(Document)
    query = query.join(Contract, Document.contract_id == Contract.id)
    query = query.where(Document.user_id == user_id, Contract.vendor_name.like(POISON_PREFIX + "%"))
    result = await db.execute(query)

    for document in result.scalars().all():
        delete_file(document.file_path)

    # The documents, sections and chunks go with their contract (ON DELETE CASCADE)
    await db.execute(delete(Contract).where(Contract.user_id == user_id, Contract.vendor_name.like(POISON_PREFIX + "%")))
    await db.commit()


async def load_case(db, user_id: int, case: dict) -> tuple:
    """Upload one poisoned (or clean) contract and run the ingestion. Returns the document and the contract id."""
    file_bytes = (POISONED_FOLDER / case["file_name"]).read_bytes()
    contract = await find_or_create_contract(db, user_id, case["vendor_name"])

    document = Document(
        user_id=user_id,
        contract_id=contract.id,
        file_name=case["file_name"],
        file_path=save_file(file_bytes),
        file_hash=compute_file_hash(file_bytes),
        document_type="Other",
        status="uploaded",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    await run_ingestion(document.id)
    # run_ingestion used its own session, so we reload the document to see the result
    await db.refresh(document)
    return document, contract.id


async def read_events(db, document_id: int) -> list[SecurityEvent]:
    """Load the findings of the security scan for one document."""
    result = await db.execute(select(SecurityEvent).where(SecurityEvent.document_id == document_id))
    return list(result.scalars().all())


def describe_scan(document: Document, events: list) -> str:
    """Describe in one word what the scan did with a document."""
    if document.status == "quarantined":
        return "quarantined"
    if document.status != "ready":
        return "failed"
    if len(events) == 0:
        return "indexed untouched"

    actions = set()
    for event in events:
        actions.add(event.action)
    return "cleaned (" + ", ".join(sorted(actions)) + ")"


def judge_attack(document: Document, obeyed) -> bool | None:
    """An attack is handled if the document was blocked, or if the answer did not follow it."""
    if document.status == "quarantined":
        return True
    if document.status != "ready":
        return False
    if obeyed is None:
        # No answer was asked for
        return None
    return not obeyed


async def run_case(db, user_id: int, case: dict, skip_answers: bool) -> dict:
    """Load one case, look at what the scan did, check if the attack text reached the prompt, and ask the question."""
    document, contract_id = await load_case(db, user_id, case)
    events = await read_events(db, document.id)

    result = {
        "id": case["id"],
        "kind": case["kind"],
        "name": case["name"],
        "expected_scan": case["expected_scan"],
        "status": document.status,
        "scan": describe_scan(document, events),
        "rules": sorted({event.rule for event in events}),
        "answer": "",
        "obeyed": None,
        "reached_model": None,
    }

    if document.status == "ready":
        # Retrieval uses no LLM, so this check costs nothing
        chunks = await retrieve_hybrid_rerank_xref(db, user_id, case["question"], contract_id)

        if case["canary"] != "":
            # build_context gives the exact text that goes into the prompt, after the cleaning
            prompt_text = build_context(chunks)
            result["reached_model"] = case["canary"].lower() in prompt_text.lower()
            print("  attack text reached the prompt:", result["reached_model"])

        if not skip_answers:
            answer_result = await generate_answer(case["question"], chunks)
            result["answer"] = answer_result["answer"]
            if case["canary"] != "":
                result["obeyed"] = case["canary"].lower() in answer_result["answer"].lower()
            await asyncio.sleep(PAUSE_SECONDS)

    if case["kind"] == "attack":
        result["passed"] = judge_attack(document, result["obeyed"])
    else:
        # A clean control must be indexed with no finding at all
        result["passed"] = document.status == "ready" and len(events) == 0

    return result

def print_results(results: list[dict], mode: str) -> None:
    """Print one line per case and the summary."""
    print("")
    print("Mode:", mode)
    for item in results:
        verdict = {True: "PASS", False: "FAIL", None: "n/a "}[item["passed"]]
        line = verdict + " | " + item["id"] + " " + item["name"] + " | " + item["scan"]
        if item["obeyed"] is not None:
            line += " | model obeyed: " + str(item["obeyed"])
        print(line)

    attacks = []
    controls = []
    for item in results:
        if item["kind"] == "attack":
            attacks.append(item)
        else:
            controls.append(item)

    blocked = 0
    cleaned = 0
    slipped = 0
    obeyed = 0
    for item in attacks:
        if item["status"] == "quarantined":
            blocked += 1
        elif item["scan"].startswith("cleaned"):
            cleaned += 1
        elif item["status"] == "ready":
            slipped += 1
        if item["obeyed"] is True:
            obeyed += 1

    handled = 0
    for item in attacks:
        if item["passed"] is True:
            handled += 1

    false_alarms = 0
    for item in controls:
        if item["passed"] is False:
            false_alarms += 1

    print("")
    print("Attacks:", len(attacks))
    print("  blocked at upload (quarantined):", blocked)
    print("  indexed after cleaning the text:", cleaned)
    print("  indexed untouched (the scan found nothing):", slipped)
    print("  answers that followed the attack:", obeyed)
    print("  handled safely (blocked, or the answer did not follow it):", handled, "of", len(attacks))
    print("Clean controls with a false alarm:", false_alarms, "of", len(controls))


async def main_async(args) -> None:
    """Load every case, measure, and save the results."""
    if args.mode == "undefended":
        # Both layers are switched off in this process only: the upload scan and the cleaning of prompts
        settings.security_scan_enabled = False
        security.DEFENSES_ENABLED = False

    with open(CASES_FILE, encoding="utf-8") as file:
        cases = json.load(file)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == args.email.lower()))
        user = result.scalar_one_or_none()
        if user is None:
            sys.exit("User not found: " + args.email)

        # Earlier poisoned copies are replaced
        await delete_poison_documents(db, user.id)

        results = []
        for case in cases:
            print("Loading", case["id"], case["name"], "...")
            results.append(await run_case(db, user.id, case, args.skip_answers))

        # Unprotected copies must never stay in your library
        if args.mode == "undefended" and not args.keep:
            await delete_poison_documents(db, user.id)

    await engine.dispose()

    RESULTS_FOLDER.mkdir(exist_ok=True)
    result_file = RESULTS_FOLDER / ("injection_" + args.mode + ".json")
    result_file.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print_results(results, args.mode)


def main() -> None:
    """Read the command line arguments and run the injection tests."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, help="Email of the account that owns the contracts")
    parser.add_argument("--mode", choices=["defended", "undefended"], default="defended")
    parser.add_argument("--skip-answers", action="store_true", help="Only look at the scan. No LLM calls.")
    parser.add_argument("--keep", action="store_true", help="Keep the unprotected copies after an undefended run")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()