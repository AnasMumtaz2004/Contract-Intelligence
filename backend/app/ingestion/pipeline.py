import asyncio
import hashlib

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.ingestion.chunking import chunk_sections
from app.ingestion.indexing import save_chunks, save_sections
from app.ingestion.parsing import count_words, parse_with_router
from app.ingestion.structure import find_sections
from app.models import Document, SecurityEvent
from app.security import make_quarantine_message, redact_chunks, scan_document

# If a PDF has fewer words than this, it has no readable text
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


def make_no_text_message(ocr_error: str) -> str:
    """Write the error message for a document without readable text."""
    message = "No readable text found."
    if ocr_error != "":
        message += " The PDF looks scanned, and OCR failed: " + ocr_error
    else:
        message += " The file may be empty or an unsupported scan."
    return message


def save_security_events(db: AsyncSession, document: Document, findings: list[dict]) -> None:
    """Add one security event for every finding of the scan."""
    for finding in findings:
        db.add(
            SecurityEvent(
                user_id=document.user_id,
                document_id=document.id,
                event_type=finding["kind"],
                severity=finding["severity"],
                rule=finding["rule"],
                page_number=finding["page"],
                snippet=finding["snippet"],
                action=finding["action"],
            )
        )


async def run_ingestion(document_id: int, allow_flagged: bool = False) -> None:
    """Background job: parse, scan, chunk, embed and save one uploaded document."""
    # A background job needs its own database session
    async with AsyncSessionLocal() as db:
        document = await db.get(Document, document_id)
        if document is None:
            return

        try:
            # A new run replaces the findings of an earlier run
            await db.execute(delete(SecurityEvent).where(SecurityEvent.document_id == document_id))

            await set_status(db, document, "parsing")
            # Parsing (and OCR) is slow and not async, so it runs in a thread
            parse_result = await asyncio.to_thread(parse_with_router, document.file_path)
            pages = parse_result["pages"]
            document.page_count = len(pages)
            document.parser_used = parse_result["parser_used"]
            document.parse_quality = parse_result["parse_quality"]

            if count_words(pages) < MIN_WORDS_IN_DOCUMENT:
                raise ValueError(make_no_text_message(parse_result["ocr_error"]))

            if settings.security_scan_enabled:
                await set_status(db, document, "scanning")
                scan = await asyncio.to_thread(scan_document, document.file_path, pages, allow_flagged)
                save_security_events(db, document, scan["findings"])

                if scan["quarantine"]:
                    # Nothing is indexed, so the document can never reach a prompt
                    document.status = "quarantined"
                    document.error_message = make_quarantine_message(scan["findings"])
                    await db.commit()
                    return

                # Hidden text is already taken out of these pages
                pages = scan["pages"]

            await set_status(db, document, "chunking")
            sections = find_sections(pages)
            chunks = chunk_sections(sections)

            if len(chunks) == 0:
                raise ValueError("Could not create any chunks from this document.")

            # Instruction-like sentences are cut out of the text before it is saved
            redact_chunks(chunks)

            await set_status(db, document, "embedding")
            section_ids = await save_sections(db, document, sections)
            chunk_count = await save_chunks(db, document, chunks, section_ids)

            document.chunk_count = chunk_count
            document.error_message = None
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