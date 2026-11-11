from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_db
from app.ingestion.metadata import DOCUMENT_TYPES, suggest_metadata
from app.ingestion.pipeline import compute_file_hash, run_ingestion, validate_pdf_file
from app.models import Chunk, Contract, Document, User
from app.routes.contracts import find_or_create_contract
from app.schemas import ChunkOut, DocumentOut, MetadataSuggestion, MetadataUpdate
from app.storage import delete_file, save_file

router = APIRouter(prefix="/documents", tags=["documents"])

# Documents uploaded without a vendor go here until the user confirms the metadata
UNASSIGNED_VENDOR = "Unassigned"


def make_document_out(document: Document, vendor_name: str) -> DocumentOut:
    """Build the response object for one document."""
    return DocumentOut(
        id=document.id,
        contract_id=document.contract_id,
        vendor_name=vendor_name,
        file_name=document.file_name,
        document_type=document.document_type,
        status=document.status,
        error_message=document.error_message,
        page_count=document.page_count,
        chunk_count=document.chunk_count,
        effective_date=document.effective_date,
        parent_document_id=document.parent_document_id,
        parser_used=document.parser_used,
        parse_quality=document.parse_quality,
        created_at=document.created_at,
    )


async def get_document_for_user(db: AsyncSession, document_id: int, user_id: int) -> Document:
    """Load a document, but only if it belongs to this user."""
    document = await db.get(Document, document_id)
    if document is None or document.user_id != user_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.post("/upload", response_model=DocumentOut)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    vendor_name: str = Form(""),
    document_type: str = Form("Other"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Save an uploaded PDF and start processing it in the background."""
    file_bytes = await file.read()

    # Check the file on the server, not only in the browser
    error_message = validate_pdf_file(file.filename or "", file_bytes)
    if error_message != "":
        raise HTTPException(status_code=400, detail=error_message)

    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Unknown document type")

    # The vendor can be left empty. The user confirms it after processing.
    vendor_name = vendor_name.strip()
    if vendor_name == "":
        vendor_name = UNASSIGNED_VENDOR

    # Stop the same file from being uploaded twice
    file_hash = compute_file_hash(file_bytes)
    query = select(Document).where(Document.user_id == user.id, Document.file_hash == file_hash)
    result = await db.execute(query)
    existing_document = result.scalars().first()
    if existing_document is not None:
        raise HTTPException(status_code=409, detail="You already uploaded this file")

    contract = await find_or_create_contract(db, user.id, vendor_name)
    file_path = save_file(file_bytes)

    document = Document(
        user_id=user.id,
        contract_id=contract.id,
        file_name=file.filename or "contract.pdf",
        file_path=file_path,
        file_hash=file_hash,
        document_type=document_type,
        status="uploaded",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    # The response returns now. Processing continues in the background.
    background_tasks.add_task(run_ingestion, document.id)

    return make_document_out(document, contract.vendor_name)


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all documents of the logged-in user, newest first."""
    query = (
        select(Document, Contract.vendor_name)
        .join(Contract, Document.contract_id == Contract.id)
        .where(Document.user_id == user.id)
        .order_by(Document.created_at.desc())
    )
    result = await db.execute(query)
    rows = result.all()

    documents = []
    for document, vendor_name in rows:
        documents.append(make_document_out(document, vendor_name))
    return documents


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return one document. The frontend uses this to check processing status."""
    document = await get_document_for_user(db, document_id, user.id)
    contract = await db.get(Contract, document.contract_id)
    return make_document_out(document, contract.vendor_name)


@router.get("/{document_id}/suggestions", response_model=MetadataSuggestion)
async def get_suggestions(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Ask the LLM to guess the vendor, type and effective date of a processed document."""
    document = await get_document_for_user(db, document_id, user.id)
    contract = await db.get(Contract, document.contract_id)

    current_vendor = contract.vendor_name
    if current_vendor == UNASSIGNED_VENDOR:
        current_vendor = ""

    # If the LLM cannot help, the form simply starts with the current values
    fallback = MetadataSuggestion(
        vendor_name=current_vendor,
        document_type=document.document_type,
        effective_date=document.effective_date,
    )
    if document.status != "ready":
        return fallback

    # An LLM call can fail (for example a rate limit), and that must not break the upload flow
    try:
        suggestion = await suggest_metadata(db, document.id)
    except Exception:
        return fallback

    # Keep what the user already entered
    if current_vendor != "":
        suggestion["vendor_name"] = current_vendor
    if document.document_type != "Other":
        suggestion["document_type"] = document.document_type
    if document.effective_date is not None:
        suggestion["effective_date"] = document.effective_date

    return MetadataSuggestion(**suggestion)


@router.patch("/{document_id}/metadata", response_model=DocumentOut)
async def update_metadata(
    document_id: int,
    data: MetadataUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Save the metadata that the user confirmed: vendor, type, effective date and parent document."""
    document = await get_document_for_user(db, document_id, user.id)

    if data.document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Unknown document type")

    contract = await find_or_create_contract(db, user.id, data.vendor_name)

    parent_id = data.parent_document_id
    if parent_id is not None:
        if parent_id == document.id:
            raise HTTPException(status_code=400, detail="A document cannot be its own parent")

        parent = await get_document_for_user(db, parent_id, user.id)
        if parent.contract_id != contract.id:
            raise HTTPException(status_code=400, detail="The parent document must belong to the same contract")
        if parent.parent_document_id == document.id:
            raise HTTPException(status_code=400, detail="The parent document points back to this document")

    # Moving a document to another contract also moves its chunks
    if contract.id != document.contract_id:
        await db.execute(update(Chunk).where(Chunk.document_id == document.id).values(contract_id=contract.id))
        document.contract_id = contract.id

    document.document_type = data.document_type
    document.effective_date = data.effective_date
    document.parent_document_id = parent_id

    await db.commit()
    await db.refresh(document)
    return make_document_out(document, contract.vendor_name)


@router.get("/{document_id}/chunks", response_model=list[ChunkOut])
async def get_document_chunks(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the chunks of one document so we can check them by eye."""
    document = await get_document_for_user(db, document_id, user.id)
    query = select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.chunk_index)
    result = await db.execute(query)
    return result.scalars().all()


@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a document, its file, and all its sections and chunks."""
    document = await get_document_for_user(db, document_id, user.id)
    delete_file(document.file_path)
    # The database removes the sections and chunks automatically (ON DELETE CASCADE)
    await db.delete(document)
    await db.commit()
    return {"message": "Document deleted"}

@router.post("/{document_id}/release", response_model=DocumentOut)
async def release_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Let a blocked document through. Its instruction-like sentences are still removed from the text."""
    document = await get_document_for_user(db, document_id, user.id)
    if document.status != "quarantined":
        raise HTTPException(status_code=400, detail="Only blocked documents can be released")

    document.status = "uploaded"
    document.error_message = None
    await db.commit()

    background_tasks.add_task(run_ingestion, document.id, True)

    contract = await db.get(Contract, document.contract_id)
    return make_document_out(document, contract.vendor_name)