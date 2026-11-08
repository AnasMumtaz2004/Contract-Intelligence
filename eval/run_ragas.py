import argparse
import asyncio
import json
import math
import re
import sys
from pathlib import Path

# The eval scripts reuse the backend code, so the backend folder is added to the import path
EVAL_FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_FOLDER.parent / "backend"))

from sqlalchemy import func, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import AsyncSessionLocal, engine  # noqa: E402
from app.llm import build_gemini, build_groq  # noqa: E402
from app.models import Contract, User  # noqa: E402
from pipelines import PIPELINES  # noqa: E402

QUESTIONS_FILE = EVAL_FOLDER / "questions.jsonl"
RESULTS_FOLDER = EVAL_FOLDER / "results"

# Pause between questions to stay under the free-tier request limits
PAUSE_SECONDS = 4

# A question counts as a "context hit" if this share of the expected clause appears in the retrieved text
HIT_THRESHOLD = 0.5
SHINGLE_SIZE = 5


def load_questions(limit: int) -> list[dict]:
    """Read questions.jsonl. A limit of 0 means all questions."""
    questions = []
    with open(QUESTIONS_FILE, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line == "":
                continue
            questions.append(json.loads(line))

    if limit > 0:
        questions = questions[:limit]
    return questions


def save_json(path: Path, data) -> None:
    """Save data as a readable JSON file."""
    RESULTS_FOLDER.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_json(path: Path):
    """Read a JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def get_shingles(text: str) -> set:
    """Split a text into overlapping groups of 5 words."""
    words = re.findall(r"[a-z0-9]+", text.lower())

    shingles = set()
    for start in range(0, len(words) - SHINGLE_SIZE + 1):
        shingle = " ".join(words[start : start + SHINGLE_SIZE])
        shingles.add(shingle)
    return shingles


def check_context_hit(supporting_text: str, contexts: list[str]) -> bool:
    """Check if the retrieved chunks contain (most of) the expected clause text."""
    support_shingles = get_shingles(supporting_text)
    if len(support_shingles) == 0:
        return False

    # The clause may be split across chunks, so all contexts are combined
    context_shingles = set()
    for context in contexts:
        context_shingles.update(get_shingles(context))

    shared = support_shingles & context_shingles
    share = len(shared) / len(support_shingles)
    return share >= HIT_THRESHOLD


async def find_contract_id(db, user_id: int, vendor_name: str):
    """Find the id of the user's contract for a vendor."""
    query = select(Contract).where(
        Contract.user_id == user_id,
        func.lower(Contract.vendor_name) == vendor_name.lower(),
    )
    result = await db.execute(query)
    contract = result.scalars().first()
    if contract is None:
        return None
    return contract.id


async def generate_answers(db, user_id: int, pipeline_name: str, questions: list[dict]) -> list[dict]:
    """Run one pipeline over all questions and return the answers."""
    pipeline = PIPELINES[pipeline_name]
    results = []

    for number, question in enumerate(questions, start=1):
        print(pipeline_name, number, "/", len(questions), question["id"])

        contract_id = await find_contract_id(db, user_id, question["vendor_name"])
        if contract_id is None:
            print("  vendor not found in the database, skipped:", question["vendor_name"])
            continue

        output = await pipeline(db, user_id, question["question"], contract_id)

        item = dict(question)
        item["answer"] = output["answer"]
        item["status"] = output["status"]
        item["contexts"] = output["contexts"]
        item["context_hit"] = check_context_hit(question["supporting_text"], output["contexts"])
        results.append(item)

        await asyncio.sleep(PAUSE_SECONDS)

    return results


async def generate_all(questions: list[dict], email: str, refresh: bool) -> dict:
    """Generate (or load saved) answers for every pipeline."""
    all_results = {}

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email.lower()))
        user = result.scalar_one_or_none()
        if user is None:
            sys.exit("User not found: " + email)

        for pipeline_name in PIPELINES:
            answers_file = RESULTS_FOLDER / ("answers_" + pipeline_name + ".json")

            # Saved answers save LLM quota. Use --refresh to generate them again.
            if answers_file.exists() and not refresh:
                print("Using saved answers for", pipeline_name)
                all_results[pipeline_name] = load_json(answers_file)
                continue

            results = await generate_answers(db, user.id, pipeline_name, questions)
            save_json(answers_file, results)
            all_results[pipeline_name] = results

    await engine.dispose()
    return all_results


def clean_score(value):
    """Return a normal number, or None if the score is missing or not a number."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    if math.isnan(value):
        return None
    return float(value)


def get_judge_model():
    """Pick the model that judges the answers."""
    # Ragas needs a plain chat model, so no fallback wrapper is used here
    if settings.google_api_key != "":
        return build_gemini()
    return build_groq()


def score_with_ragas(items: list[dict]) -> list[dict]:
    """Score the answered questions with Ragas. Returns one dictionary of scores per question."""
    # Ragas is imported here so runs without Ragas (--skip-ragas) stay fast
    from langchain_huggingface import HuggingFaceEmbeddings
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
        ResponseRelevancy,
    )
    from ragas.run_config import RunConfig

    samples = []
    for item in items:
        sample = SingleTurnSample(
            user_input=item["question"],
            response=item["answer"],
            retrieved_contexts=item["contexts"],
            reference=item["expected_answer"],
        )
        samples.append(sample)
    dataset = EvaluationDataset(samples=samples)

    judge = LangchainLLMWrapper(get_judge_model())
    embeddings = LangchainEmbeddingsWrapper(HuggingFaceEmbeddings(model_name=settings.embedding_model_name))
    metrics = [
        Faithfulness(llm=judge),
        ResponseRelevancy(llm=judge, embeddings=embeddings),
        LLMContextPrecisionWithReference(llm=judge),
        LLMContextRecall(llm=judge),
    ]

    # One worker at a time keeps us under the free-tier rate limits
    run_config = RunConfig(max_workers=1, timeout=180, max_retries=6)
    result = evaluate(dataset=dataset, metrics=metrics, run_config=run_config)

    scored = []
    for item, scores in zip(items, result.scores):
        clean_scores = {}
        for name, value in scores.items():
            clean_scores[name] = clean_score(value)
        scored.append({"id": item["id"], "scores": clean_scores})
    return scored


def main() -> None:
    """Generate answers for each pipeline, then score them."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, help="Email of the account that owns the contracts")
    parser.add_argument("--limit", type=int, default=0, help="Only use the first N questions (0 = all)")
    parser.add_argument("--refresh", action="store_true", help="Ignore saved answers and scores")
    parser.add_argument("--skip-ragas", action="store_true", help="Skip the Ragas scoring (saves LLM quota)")
    args = parser.parse_args()

    questions = load_questions(args.limit)
    print("Questions:", len(questions))

    # All database work happens inside one asyncio.run call.
    # Ragas runs afterwards, because it starts its own event loop.
    all_results = asyncio.run(generate_all(questions, args.email, args.refresh))

    if args.skip_ragas:
        print("Skipped Ragas. Run report.py to see the cheap metrics.")
        return

    for pipeline_name, results in all_results.items():
        scores_file = RESULTS_FOLDER / ("scores_" + pipeline_name + ".json")
        if scores_file.exists() and not args.refresh:
            print("Using saved scores for", pipeline_name)
            continue

        # Ragas only scores answers that were really given for answerable questions
        items_to_score = []
        for item in results:
            if item["answerable"] and item["status"] == "found" and len(item["contexts"]) > 0:
                items_to_score.append(item)

        print("Scoring", len(items_to_score), "answers for", pipeline_name)
        if len(items_to_score) == 0:
            save_json(scores_file, [])
            continue

        scored = score_with_ragas(items_to_score)
        save_json(scores_file, scored)

    print("Done. Run report.py to see the table.")


if __name__ == "__main__":
    main()