import argparse
import asyncio
import sys
from pathlib import Path

# The eval scripts reuse the backend code, so the backend folder is added to the import path
EVAL_FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_FOLDER.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app.database import AsyncSessionLocal, engine  # noqa: E402
from app.models import User  # noqa: E402
from pipelines import RETRIEVERS  # noqa: E402
from run_ragas import (  # noqa: E402
    RESULTS_FOLDER,
    check_amendment_retrieved,
    check_context_hit,
    find_contract_id,
    load_questions,
    save_json,
)


async def retrieve_for_pipeline(db, user_id: int, pipeline_name: str, questions: list[dict]) -> list[dict]:
    """Run only the retrieval part of a pipeline for every question. No LLM is used."""
    retriever = RETRIEVERS[pipeline_name]
    results = []

    for question in questions:
        contract_id = await find_contract_id(db, user_id, question["vendor_name"])
        if contract_id is None:
            print("  vendor not found in the database, skipped:", question["vendor_name"])
            continue

        chunks = await retriever(db, user_id, question["question"], contract_id)

        contexts = []
        sources = []
        for chunk in chunks:
            contexts.append(chunk["content"])
            sources.append(chunk["file_name"])

        results.append(
            {
                "id": question["id"],
                "level": question["level"],
                "vendor_name": question["vendor_name"],
                "answerable": question["answerable"],
                "context_hit": check_context_hit(question["supporting_text"], contexts),
                "amendment_retrieved": check_amendment_retrieved(sources, question.get("amendment_files", [])),
            }
        )

    return results


def average_hit(results: list[dict]) -> float:
    """Average context hit of the answerable questions."""
    hits = []
    for item in results:
        if item["answerable"]:
            hits.append(1.0 if item["context_hit"] else 0.0)
    if len(hits) == 0:
        return 0.0
    return sum(hits) / len(hits)


async def main_async(args) -> None:
    """Run the retrieval of every chosen pipeline and save the results."""
    questions = load_questions(args.limit, args.levels)

    pipeline_names = args.pipelines
    if len(pipeline_names) == 0:
        pipeline_names = list(RETRIEVERS.keys())

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == args.email.lower()))
        user = result.scalar_one_or_none()
        if user is None:
            sys.exit("User not found: " + args.email)

        for pipeline_name in pipeline_names:
            print("Retrieving with", pipeline_name, "for", len(questions), "questions...")
            results = await retrieve_for_pipeline(db, user.id, pipeline_name, questions)
            save_json(RESULTS_FOLDER / ("retrieval_" + pipeline_name + ".json"), results)
            print("  context hit (answerable questions):", round(average_hit(results), 2))

    await engine.dispose()


def main() -> None:
    """Read the command line arguments and run the retrieval."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, help="Email of the account that owns the contracts")
    parser.add_argument("--limit", type=int, default=0, help="Only use the first N questions (0 = all)")
    parser.add_argument("--levels", type=int, nargs="*", default=[], help="Only these levels, like: --levels 5")
    parser.add_argument("--pipelines", nargs="*", default=[], help="Only these pipelines (default: all)")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()