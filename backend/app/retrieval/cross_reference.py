import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Chunk, Document, Section
from app.retrieval.search import make_result

# Matches "Section 12.3", "Sections 4" or "Article 7"
REFERENCE_PATTERN = re.compile(r"\b(?:Sections?|Articles?)\s+(\d+(?:\.\d+)*)", re.IGNORECASE)


def find_referenced_numbers(text: str) -> list[str]:
    """Find the section numbers that a text points to, like ['12.3', '4']."""
    numbers = []
    for match in REFERENCE_PATTERN.finditer(text):
        number = match.group(1)
        if number not in numbers:
            numbers.append(number)
    return numbers


async def load_section_chunk(db: AsyncSession, user_id: int, document_id: int, section_number: str):
    """Load the first chunk of a numbered section of one document. Returns None if there is none."""
    query = select(Chunk, Document.file_name, Document.document_type, Document.effective_date)
    query = query.join(Document, Chunk.document_id == Document.id)
    query = query.join(Section, Chunk.section_id == Section.id)
    query = query.where(Chunk.user_id == user_id)
    query = query.where(Chunk.document_id == document_id)
    query = query.where(Section.section_number == section_number)
    query = query.order_by(Chunk.chunk_index)
    query = query.limit(1)

    result = await db.execute(query)
    row = result.first()
    if row is None:
        return None

    chunk, file_name, document_type, effective_date = row
    return make_result(chunk, file_name, document_type, effective_date)


async def add_cross_references(db: AsyncSession, user_id: int, chunks: list[dict]) -> list[dict]:
    """Add the sections that the chunks point to ('subject to Section 12.3') to the list."""
    known_ids = set()
    for chunk in chunks:
        known_ids.add(chunk["chunk_id"])

    extra_chunks = []
    max_extra = settings.max_cross_reference_chunks

    for chunk in chunks:
        for number in find_referenced_numbers(chunk["content"]):
            if len(extra_chunks) >= max_extra:
                break

            extra = await load_section_chunk(db, user_id, chunk["document_id"], number)
            if extra is None:
                continue
            # The chunk may already be in the list
            if extra["chunk_id"] in known_ids:
                continue

            known_ids.add(extra["chunk_id"])
            extra["via_cross_reference"] = True
            extra_chunks.append(extra)

    return chunks + extra_chunks