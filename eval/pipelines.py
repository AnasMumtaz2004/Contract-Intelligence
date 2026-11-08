import sys
from pathlib import Path

# The eval scripts reuse the backend code, so the backend folder is added to the import path
BACKEND_FOLDER = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_FOLDER))

from app.config import settings  # noqa: E402
from app.rag import generate_answer  # noqa: E402
from app.retrieval.search import hybrid_search, vector_search  # noqa: E402


async def finish_pipeline(question: str, chunks: list[dict]) -> dict:
    """Generate the answer from the chunks and return everything the evaluation needs."""
    result = await generate_answer(question, chunks)

    contexts = []
    for chunk in chunks:
        contexts.append(chunk["content"])

    return {"answer": result["answer"], "status": result["status"], "contexts": contexts}


async def run_naive(db, user_id: int, question: str, contract_id: int | None) -> dict:
    """Naive RAG: vector search only."""
    chunks = await vector_search(db, user_id, question, settings.top_k, contract_id=contract_id)
    return await finish_pipeline(question, chunks)


async def run_hybrid(db, user_id: int, question: str, contract_id: int | None) -> dict:
    """Hybrid RAG: vector search + keyword search merged with RRF."""
    chunks = await hybrid_search(db, user_id, question, contract_id=contract_id)
    return await finish_pipeline(question, chunks)


# Phase 3 and 4 will add more pipelines here
PIPELINES = {
    "naive": run_naive,
    "hybrid": run_hybrid,
}