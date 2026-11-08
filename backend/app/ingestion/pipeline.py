import asyncio
import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.ingestion.chunking import chunk_sections
from app.ingestion.indexing import save_chunks, save_sections
from app.ingestion.parsing import count_words, parse_pdf
from app.ingestion.structure import find_sections
from app.models import Document

# If a PDF has fewer words than this, it is probably a scan
MIN_WORDS_IN_DOCUMENT = 50


def validate_pdf_file(file_name: str, file_bytes: bytes) -> str:
    """Check the uploaded file and return an error message, or an empty string if it is fine."""
    if not file_name.lower().endswith(".pdf"):
        return "Only PDF files are allowed."

    if len(file_bytes) == 0:
        return "The file is empty."

    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        return "The file is larger than " + str(settings.max_upload_mb) + " MB."

    # Every real PDF starts with these bytes
    if not file_bytes.startswith(b"%PDF"):
        return "This file is not a real PDF."

    return ""


def compute_file_hash(file_bytes: bytes) -> str:
    """Return a SHA-256 fingerprint of the file, used to find duplicates."""
    return hashlib.sha256(file_bytes).hexdigest()


async def set_status(db: AsyncSession, document: Document, new_status: str) -> None:
    """Save a new status so the frontend can show the progress."""
    document.status = new_status
    await db.commit()


async def run_ingestion(document_id: int) -> None:
    """Background job: parse, chunk, embed and save one uploaded document."""
    # A background job needs its own database session
    async with AsyncSessionLocal() as db:
        document = await db.get(Document, document_id)
        if document is None:
            return

        try:
            await set_status(db, document, "parsing")
            # PyMuPDF is not async, so it runs in a thread
            pages = await asyncio.to_thread(parse_pdf, document.file_path)
            document.page_count = len(pages)

            if count_words(pages) < MIN_WORDS_IN_DOCUMENT:
                raise ValueError("No readable text found. Scanned PDFs are not supported yet.")

            await set_status(db, document, "chunking")
            sections = find_sections(pages)
            chunks = chunk_sections(sections)

            if len(chunks) == 0:
                raise ValueError("Could not create any chunks from this document.")

            await set_status(db, document, "embedding")
            section_ids = await save_sections(db, document, sections)
            chunk_count = await save_chunks(db, document, chunks, section_ids)

            document.chunk_count = chunk_count
            document.status = "ready"
            await db.commit()

        except Exception as error:
            # Undo any half-saved sections or chunks
            await db.rollback()

            # Load the document again, because rollback resets the session
            document = await db.get(Document, document_id)
            if document is None:
                return

            document.status = "failed"
            document.error_message = str(error)
            await db.commit()