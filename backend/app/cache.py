import asyncio
import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_redis
from app.embeddings import embed_query, embed_texts
from app.models import Chunk, Document


def hash_text(text: str) -> str:
    """Make a short fingerprint of a text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# A broken cache must never break an answer, so every Redis call below returns "nothing found" on an error.


async def get_value(key: str):
    """Read one value from Redis. Returns None if it is missing or Redis fails."""
    try:
        return await get_redis().get(key)
    except Exception:
        return None


async def get_many(keys: list[str]) -> list:
    """Read several values from Redis at once."""
    if len(keys) == 0:
        return []
    try:
        return await get_redis().mget(keys)
    except Exception:
        return [None] * len(keys)


async def set_value(key: str, value: str, ttl_seconds: int) -> None:
    """Save one value in Redis. It expires after the given time."""
    try:
        await get_redis().set(key, value, ex=ttl_seconds)
    except Exception:
        pass


async def delete_value(key: str) -> None:
    """Delete one value from Redis."""
    try:
        await get_redis().delete(key)
    except Exception:
        pass


# ---------- Embedding cache ----------


def make_embedding_key(text: str) -> str:
    """Make the Redis key of an embedding. It includes the model, so a new model never reuses old vectors."""
    return "emb:" + settings.embedding_model_name + ":" + hash_text(text)


async def get_query_embedding(question: str) -> list[float]:
    """Get the vector of a search question. Repeated questions skip the model."""
    key = make_embedding_key("query:" + question)

    cached = await get_value(key)
    if cached is not None:
        return json.loads(cached)

    # Embedding is slow, so it runs in a thread
    vector = await asyncio.to_thread(embed_query, question)
    await set_value(key, json.dumps(vector), settings.embedding_cache_ttl_seconds)
    return vector


async def get_text_embeddings(texts: list[str]) -> list[list[float]]:
    """Get the vectors of many chunk texts. Texts that were embedded before are not embedded again."""
    keys = []
    for text in texts:
        keys.append(make_embedding_key("passage:" + text))

    cached_values = await get_many(keys)

    vectors = [None] * len(texts)
    missing_positions = []
    for position, value in enumerate(cached_values):
        if value is None:
            missing_positions.append(position)
        else:
            vectors[position] = json.loads(value)

    if len(missing_positions) > 0:
        missing_texts = []
        for position in missing_positions:
            missing_texts.append(texts[position])

        new_vectors = await asyncio.to_thread(embed_texts, missing_texts)
        for position, vector in zip(missing_positions, new_vectors):
            vectors[position] = vector
            await set_value(keys[position], json.dumps(vector), settings.embedding_cache_ttl_seconds)

    return vectors


# ---------- Response cache ----------


async def make_scope_fingerprint(db: AsyncSession, user_id: int, contract_id) -> str:
    """Make a fingerprint of the documents that a question searches. It changes when a document changes."""
    query = select(
        Document.id,
        Document.file_hash,
        Document.document_type,
        Document.effective_date,
        func.max(Chunk.id),
    )
    query = query.select_from(Document)
    query = query.join(Chunk, Chunk.document_id == Document.id)
    query = query.where(Document.user_id == user_id)
    if contract_id is not None:
        query = query.where(Document.contract_id == contract_id)
    # The newest chunk id changes when a document is processed again, so old chunk ids are never served
    query = query.group_by(Document.id, Document.file_hash, Document.document_type, Document.effective_date)
    query = query.order_by(Document.id)

    result = await db.execute(query)

    parts = []
    for row in result.all():
        values = []
        for value in row:
            values.append(str(value))
        parts.append(":".join(values))

    return hash_text("|".join(parts))


def make_response_key(question: str, contract_id, fingerprint: str, notes: str, version: str) -> str:
    """Make the Redis key of a saved answer."""
    normalized_question = " ".join(question.lower().split()).rstrip("?. ")
    text = "|".join([version, normalized_question, str(contract_id), fingerprint, notes])
    return "resp:" + hash_text(text)


async def get_response(key: str):
    """Get a saved answer. Returns None if there is none."""
    value = await get_value(key)
    if value is None:
        return None

    try:
        entry = json.loads(value)
    except ValueError:
        return None

    # JSON turns the numbers of the claim map into text, so we turn them back
    claim_map = {}
    for number_text, claims in entry.get("claim_map", {}).items():
        claim_map[int(number_text)] = claims
    entry["claim_map"] = claim_map
    return entry


async def save_response(key: str, entry: dict) -> None:
    """Save an answer."""
    await set_value(key, json.dumps(entry), settings.response_cache_ttl_seconds)


async def remember_message_key(message_id: int, key: str) -> None:
    """Remember which saved answer belongs to a message, so a thumbs down can delete it."""
    await set_value("msgkey:" + str(message_id), key, settings.response_cache_ttl_seconds)


async def forget_message_answer(message_id: int) -> None:
    """Delete the saved answer of a message, so a bad answer is not served again."""
    key = await get_value("msgkey:" + str(message_id))
    if key is not None:
        await delete_value(key)
    await delete_value("msgkey:" + str(message_id))


# ---------- LLM call cache ----------


def make_llm_key(role: str, system_prompt: str, user_prompt: str) -> str:
    """Make the Redis key of an LLM call. It includes the model names."""
    models = [settings.gemini_model, settings.groq_model, settings.fast_provider, settings.smart_provider]
    text = "|".join(models) + "|" + role + "|" + system_prompt + "|" + user_prompt
    return "llm:" + hash_text(text)


async def get_llm_reply(key: str):
    """Get a saved LLM reply. Returns None if there is none."""
    return await get_value(key)


async def save_llm_reply(key: str, text: str) -> None:
    """Save an LLM reply."""
    await set_value(key, text, settings.llm_cache_ttl_seconds)