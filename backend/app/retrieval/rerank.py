import asyncio

from sentence_transformers import CrossEncoder

from app.config import settings

# The model is loaded once, the first time it is needed
_model = None


def get_reranker() -> CrossEncoder:
    """Load the reranking model on first use and reuse it afterwards."""
    global _model
    if _model is None:
        _model = CrossEncoder(settings.reranker_model_name)
    return _model


def score_chunks(question: str, chunks: list[dict]) -> list[float]:
    """Give every chunk a score for how well it answers the question."""
    model = get_reranker()

    pairs = []
    for chunk in chunks:
        text = chunk["section_path"] + "\n" + chunk["content"]
        pairs.append([question, text])

    raw_scores = model.predict(pairs)

    scores = []
    for raw_score in raw_scores:
        scores.append(float(raw_score))
    return scores


async def rerank_chunks(question: str, chunks: list[dict], top_k: int) -> list[dict]:
    """Re-order the chunks by how well they answer the question and keep the best ones."""
    if len(chunks) == 0:
        return []

    # Scoring is slow, so it runs in a thread
    scores = await asyncio.to_thread(score_chunks, question, chunks)

    scored_chunks = []
    for chunk, score in zip(chunks, scores):
        item = dict(chunk)
        item["rerank_score"] = score
        scored_chunks.append(item)

    scored_chunks.sort(key=lambda item: item["rerank_score"], reverse=True)
    return scored_chunks[:top_k]