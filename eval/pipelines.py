import sys
from pathlib import Path
from app.agent.graph import run_agent  

# The eval scripts reuse the backend code, so the backend folder is added to the import path
BACKEND_FOLDER = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_FOLDER))

from app.config import settings  # noqa: E402
from app.rag import generate_answer, retrieve_best_chunks  # noqa: E402
from app.retrieval.rerank import rerank_chunks  # noqa: E402
from app.retrieval.search import hybrid_search, vector_search  # noqa: E402


async def retrieve_naive(db, user_id: int, question: str, contract_id: int | None) -> list[dict]:
    """Naive RAG: vector search only."""
    return await vector_search(db, user_id, question, settings.top_k, contract_id=contract_id)


async def retrieve_hybrid(db, user_id: int, question: str, contract_id: int | None) -> list[dict]:
    """Hybrid RAG: vector search + keyword search merged with RRF."""
    return await hybrid_search(db, user_id, question, contract_id=contract_id)


async def retrieve_hybrid_rerank(db, user_id: int, question: str, contract_id: int | None) -> list[dict]:
    """Hybrid search, then a reranker picks the best chunks."""
    candidates = await hybrid_search(db, user_id, question, contract_id=contract_id, top_k=settings.rerank_pool)
    return await rerank_chunks(question, candidates, settings.top_k)


async def retrieve_hybrid_rerank_xref(db, user_id: int, question: str, contract_id: int | None) -> list[dict]:
    """Hybrid search, reranking, and cross-reference lookup. This is what the chat page uses."""
    return await retrieve_best_chunks(db, user_id, question, contract_id)


# These only find chunks. They never call an LLM.
RETRIEVERS = {
    "naive": retrieve_naive,
    "hybrid": retrieve_hybrid,
    "hybrid_rerank": retrieve_hybrid_rerank,
    "hybrid_rerank_xref": retrieve_hybrid_rerank_xref,
}


async def finish_pipeline(question: str, chunks: list[dict]) -> dict:
    """Generate the answer from the chunks and return everything the evaluation needs."""
    result = await generate_answer(question, chunks)

    contexts = []
    sources = []
    for chunk in chunks:
        contexts.append(chunk["content"])
        sources.append(chunk["file_name"])

    return {
        "answer": result["answer"],
        "status": result["status"],
        "contexts": contexts,
        "sources": sources,
    }


async def run_naive(db, user_id: int, question: str, contract_id: int | None) -> dict:
    """Naive RAG, including the LLM answer."""
    chunks = await retrieve_naive(db, user_id, question, contract_id)
    return await finish_pipeline(question, chunks)


async def run_hybrid(db, user_id: int, question: str, contract_id: int | None) -> dict:
    """Hybrid RAG, including the LLM answer."""
    chunks = await retrieve_hybrid(db, user_id, question, contract_id)
    return await finish_pipeline(question, chunks)


async def run_hybrid_rerank(db, user_id: int, question: str, contract_id: int | None) -> dict:
    """Hybrid + rerank, including the LLM answer."""
    chunks = await retrieve_hybrid_rerank(db, user_id, question, contract_id)
    return await finish_pipeline(question, chunks)


async def run_hybrid_rerank_xref(db, user_id: int, question: str, contract_id: int | None) -> dict:
    """Hybrid + rerank + cross-references, including the LLM answer."""
    chunks = await retrieve_hybrid_rerank_xref(db, user_id, question, contract_id)
    return await finish_pipeline(question, chunks)



async def run_agentic(db, user_id: int, question: str, contract_id: int | None) -> dict:
    """The agent: analyze, search, grade, answer and verify."""
    state = await run_agent(db, user_id, contract_id, question, {"pipeline": "agentic", "source": "eval"})

    chunks = state.get("chunks", [])
    contexts = []
    sources = []
    for chunk in chunks:
        contexts.append(chunk["content"])
        sources.append(chunk["file_name"])

    return {
        "answer": state.get("answer", ""),
        "status": state.get("status", "not_found"),
        "contexts": contexts,
        "sources": sources,
        "steps": state.get("steps", []),
    }


PIPELINES = {
    "naive": run_naive,
    "hybrid": run_hybrid,
    "hybrid_rerank": run_hybrid_rerank,
    "hybrid_rerank_xref": run_hybrid_rerank_xref,
    "agentic": run_agentic,
}