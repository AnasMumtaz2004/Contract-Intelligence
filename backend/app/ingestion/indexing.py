import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings import embed_texts
from app.ingestion.structure import get_section_text
from app.models import Chunk, Document, Section


async def save_sections(db: AsyncSession, document: Document, sections: list[dict]) -> list[int]:
    """Save the sections and return their database ids in the same order."""
    section_ids = []
    id_by_number = {}

    for section in sections:
        # Parents come before children in the document, so the parent id is already known
        parent_id = None
        if section["parent_number"] is not None:
            parent_id = id_by_number.get(section["parent_number"])

        new_section = Section(
            document_id=document.id,
            parent_section_id=parent_id,
            section_number=section["number"],
            heading=section["heading"],
            level=section["level"],
            page_start=section["page_start"],
            page_end=section["page_end"],
            full_text=get_section_text(section),
        )
        db.add(new_section)
        # flush gives the new section an id, which children and chunks need
        await db.flush()

        section_ids.append(new_section.id)
        if section["number"] is not None:
            id_by_number[section["number"]] = new_section.id

    return section_ids


async def save_chunks(
    db: AsyncSession,
    document: Document,
    chunks: list[dict],
    section_ids: list[int],
) -> int:
    """Embed the chunks, save them, and return how many were saved."""
    # The section path in front of the text helps the model understand the clause
    texts_to_embed = []
    for chunk in chunks:
        texts_to_embed.append(chunk["section_path"] + "\n" + chunk["content"])

    # Embedding is slow, so it runs in a thread and does not block the server
    vectors = await asyncio.to_thread(embed_texts, texts_to_embed)

    for position, chunk in enumerate(chunks):
        new_chunk = Chunk(
            user_id=document.user_id,
            contract_id=document.contract_id,
            document_id=document.id,
            section_id=section_ids[chunk["section_index"]],
            chunk_index=position,
            section_path=chunk["section_path"],
            page_number=chunk["page_number"],
            content=chunk["content"],
            embedding=vectors[position],
        )
        db.add(new_chunk)

    await db.flush()
    return len(chunks)