import asyncio
import re

from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.embeddings import embed_query
from app.models import Chunk, Document

# Words shorter than this are ignored in keyword search
MIN_WORD_LENGTH = 3


def build_keyword_query(question: str) -> str:
    """Turn a question into an OR query for PostgreSQL, like 'liability | cap'."""
    # Only letters and digits are kept, so the query can never contain search syntax
    words = re.findall(r"[a-z0-9]+", question.lower())

    unique_words = []
    for word in words:
        if len(word) < MIN_WORD_LENGTH:
            continue
        if word in unique_words:
            continue
        unique_words.append(word)

    return " | ".join(unique_words)


def add_filters(query, user_id: int, contract_id: int | None, document_type: str | None):
    """Limit a search to one user, and optionally to one contract or document type."""
    # The user filter is always applied, so nobody sees another user's contracts
    query = query.where(Chunk.user_id == user_id)

    if contract_id is not None:
        query = query.where(Chunk.contract_id == contract_id)
    if document_type is not None:
        query = query.where(Document.document_type == document_type)

    return query


def make_result(chunk: Chunk, file_name: str, document_type: str, effective_date) -> dict:
    """Turn a chunk row into a simple dictionary."""
    effective_text = ""
    if effective_date is not None:
        effective_text = effective_date.isoformat()

    return {
        "chunk_id": chunk.id,
        "document_id": chunk.document_id,
        "contract_id": chunk.contract_id,
        "file_name": file_name,
        "document_type": document_type,
        "effective_date": effective_text,
        "section_path": chunk.section_path,
        "page_number": chunk.page_number,
        "content": chunk.content,
    }


async def vector_search(
    db: AsyncSession,
    user_id: int,
    question: str,
    limit: int,
    contract_id: int | None = None,
    document_type: str | None = None,
) -> list[dict]:
    """Find the chunks whose meaning is closest to the question."""
    # Embedding is slow, so it runs in a thread
    question_vector = await asyncio.to_thread(embed_query, question)
    distance = Chunk.embedding.cosine_distance(question_vector)

    query = select(
        Chunk,
        Document.file_name,
        Document.document_type,
        Document.effective_date,
        distance.label("distance"),
    )
    query = query.join(Document, Chunk.document_id == Document.id)
    query = add_filters(query, user_id, contract_id, document_type)
    # The smallest distance means the closest meaning
    query = query.order_by(distance)
    query = query.limit(limit)

    result = await db.execute(query)

    results = []
    for chunk, file_name, doc_type, effective_date, _distance in result.all():
        results.append(make_result(chunk, file_name, doc_type, effective_date))
    return results


async def keyword_search(
    db: AsyncSession,
    user_id: int,
    question: str,
    limit: int,
    contract_id: int | None = None,
    document_type: str | None = None,
) -> list[dict]:
    """Find the chunks that contain the words of the question."""
    keyword_query = build_keyword_query(question)
    if keyword_query == "":
        return []

    # 'english' is written directly in the SQL, because asyncpg cannot pass it as a parameter
    tsquery = func.to_tsquery(literal_column("'english'"), keyword_query)
    rank = func.ts_rank(Chunk.search_vector, tsquery)

    query = select(
        Chunk,
        Document.file_name,
        Document.document_type,
        Document.effective_date,
        rank.label("rank"),
    )
    query = query.join(Document, Chunk.document_id == Document.id)
    # "@@" means: this chunk matches the search query
    query = query.where(Chunk.search_vector.op("@@")(tsquery))
    query = add_filters(query, user_id, contract_id, document_type)
    query = query.order_by(rank.desc())
    query = query.limit(limit)

    result = await db.execute(query)

    results = []
    for chunk, file_name, doc_type, effective_date, _rank in result.all():
        results.append(make_result(chunk, file_name, doc_type, effective_date))
    return results


def merge_with_rrf(result_lists: list[list[dict]], rrf_k: int) -> list[dict]:
    """Merge several ranked lists into one list using Reciprocal Rank Fusion."""
    scores = {}
    items = {}

    for results in result_lists:
        for position, item in enumerate(results):
            chunk_id = item["chunk_id"]
            rank = position + 1
            # A chunk found by both searches collects points twice
            points = 1.0 / (rrf_k + rank)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + points
            items[chunk_id] = item

    chunk_ids = list(scores.keys())
    chunk_ids.sort(key=lambda chunk_id: scores[chunk_id], reverse=True)

    merged = []
    for chunk_id in chunk_ids:
        item = dict(items[chunk_id])
        item["score"] = scores[chunk_id]
        merged.append(item)
    return merged


async def hybrid_search(
    db: AsyncSession,
    user_id: int,
    question: str,
    contract_id: int | None = None,
    document_type: str | None = None,
    top_k: int | None = None,
) -> list[dict]:
    """Run vector search and keyword search, then merge them into the best chunks."""
    if top_k is None:
        top_k = settings.top_k

    pool_size = settings.candidate_pool
    vector_results = await vector_search(db, user_id, question, pool_size, contract_id, document_type)
    keyword_results = await keyword_search(db, user_id, question, pool_size, contract_id, document_type)

    merged = merge_with_rrf([vector_results, keyword_results], settings.rrf_k)
    return merged[:top_k]


async def find_amendment_warning(db: AsyncSession, chunks: list[dict]) -> str:
    """Return a warning if a chunk comes from a contract that has amendments. Otherwise an empty text."""
    contract_ids = set()
    for chunk in chunks:
        if chunk["document_type"] != "Amendment":
            contract_ids.add(chunk["contract_id"])

    if len(contract_ids) == 0:
        return ""

    query = select(Document)
    query = query.where(Document.contract_id.in_(contract_ids))
    query = query.where(Document.document_type == "Amendment")
    query = query.order_by(Document.effective_date, Document.id)
    result = await db.execute(query)
    amendments = result.scalars().all()

    if len(amendments) == 0:
        return ""

    labels = []
    for amendment in amendments:
        label = amendment.file_name.split("/")[-1]
        if amendment.effective_date is not None:
            label += " (effective " + amendment.effective_date.isoformat() + ")"
        labels.append(label)

    warning = "This contract has amendments: " + ", ".join(labels) + ". "
    warning += "A clause used in this answer may have been changed by them. Please check the amendments."
    return warning