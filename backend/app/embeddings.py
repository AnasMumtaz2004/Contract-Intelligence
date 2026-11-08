from sentence_transformers import SentenceTransformer

from app.config import settings

# BGE models work best when the search question starts with this sentence.
# The stored chunks do NOT get a prefix.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# The model is loaded once, the first time it is needed
_model = None


def get_model() -> SentenceTransformer:
    """Load the embedding model on first use and reuse it afterwards."""
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.embedding_model_name)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Turn a list of texts into a list of vectors."""
    model = get_model()
    # normalize_embeddings makes cosine search work well
    vectors = model.encode(texts, normalize_embeddings=True, batch_size=32)
    return vectors.tolist()


def embed_query(question: str) -> list[float]:
    """Turn one search question into a vector."""
    model = get_model()
    vector = model.encode(QUERY_PREFIX + question, normalize_embeddings=True)
    return vector.tolist()