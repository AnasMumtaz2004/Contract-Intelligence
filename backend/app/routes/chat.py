import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.deps import get_current_user, get_db
from app.models import Chunk, Citation, Contract, Conversation, Document, Message, Section, User
from app.rag import generate_answer
from app.retrieval.search import hybrid_search
from app.schemas import (
    AnswerOut,
    AskRequest,
    ChunkDetailOut,
    CitationOut,
    ConversationCreate,
    ConversationOut,
    MessageOut,
)

router = APIRouter(prefix="/chat", tags=["chat"])


def sse_event(event_name: str, data: dict) -> str:
    """Format one server-sent event. Every event ends with a blank line."""
    return "event: " + event_name + "\ndata: " + json.dumps(data) + "\n\n"


async def get_conversation_for_user(db: AsyncSession, conversation_id: int, user_id: int) -> Conversation:
    """Load a conversation, but only if it belongs to this user."""
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.post("/conversations", response_model=ConversationOut)
async def create_conversation(
    data: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start a new conversation, for one contract or for all contracts."""
    if data.contract_id is not None:
        contract = await db.get(Contract, data.contract_id)
        if contract is None or contract.user_id != user.id:
            raise HTTPException(status_code=404, detail="Contract not found")

    conversation = Conversation(user_id=user.id, contract_id=data.contract_id, title=data.title)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List the conversations of the logged-in user, newest first."""
    query = select(Conversation).where(Conversation.user_id == user.id)
    query = query.order_by(Conversation.id.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return all messages of a conversation, with the citations of each answer."""
    conversation = await get_conversation_for_user(db, conversation_id, user.id)

    query = select(Message).where(Message.conversation_id == conversation.id)
    query = query.order_by(Message.id)
    result = await db.execute(query)
    messages = result.scalars().all()

    if len(messages) == 0:
        return []

    message_ids = []
    for message in messages:
        message_ids.append(message.id)

    # Load all citations of this conversation in one query
    citation_query = select(Citation, Chunk, Document.file_name)
    citation_query = citation_query.join(Chunk, Citation.chunk_id == Chunk.id)
    citation_query = citation_query.join(Document, Chunk.document_id == Document.id)
    citation_query = citation_query.where(Citation.message_id.in_(message_ids))
    citation_query = citation_query.order_by(Citation.number)
    citation_result = await db.execute(citation_query)

    citations_by_message = {}
    for citation, chunk, file_name in citation_result.all():
        citation_out = CitationOut(
            number=citation.number,
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            file_name=file_name,
            section_path=chunk.section_path,
            page_number=chunk.page_number,
            content=chunk.content,
        )
        if citation.message_id not in citations_by_message:
            citations_by_message[citation.message_id] = []
        citations_by_message[citation.message_id].append(citation_out)

    output = []
    for message in messages:
        message_out = MessageOut(
            id=message.id,
            role=message.role,
            content=message.content,
            status=message.status,
            citations=citations_by_message.get(message.id, []),
            created_at=message.created_at,
        )
        output.append(message_out)
    return output


async def stream_answer(conversation_id: int, user_id: int, contract_id: int | None, question: str):
    """Search, ask the LLM, save everything, and send progress events to the browser."""
    # The stream needs its own session, because the request session may close early
    async with AsyncSessionLocal() as db:
        try:
            user_message = Message(conversation_id=conversation_id, role="user", content=question)
            db.add(user_message)
            await db.commit()

            yield sse_event("status", {"text": "Searching the contracts..."})
            chunks = await hybrid_search(db, user_id, question, contract_id=contract_id)

            yield sse_event("status", {"text": "Writing the answer..."})
            result = await generate_answer(question, chunks)

            assistant_message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=result["answer"],
                status=result["status"],
            )
            db.add(assistant_message)
            # flush gives the message an id that the citations need
            await db.flush()

            citations_out = []
            for number in result["cited_numbers"]:
                # Source [1] is the first chunk, so the list index is number - 1
                chunk = chunks[number - 1]
                db.add(Citation(message_id=assistant_message.id, chunk_id=chunk["chunk_id"], number=number))
                citation_out = CitationOut(
                    number=number,
                    chunk_id=chunk["chunk_id"],
                    document_id=chunk["document_id"],
                    file_name=chunk["file_name"],
                    section_path=chunk["section_path"],
                    page_number=chunk["page_number"],
                    content=chunk["content"],
                )
                citations_out.append(citation_out)

            await db.commit()

            answer = AnswerOut(
                message_id=assistant_message.id,
                answer=result["answer"],
                status=result["status"],
                citations=citations_out,
            )
            yield sse_event("answer", answer.model_dump(mode="json"))

        except Exception as error:
            # LLM calls can fail (for example a rate limit), so the user must see a message
            await db.rollback()
            yield sse_event("error", {"message": str(error)[:300]})

    yield sse_event("done", {})


@router.post("/conversations/{conversation_id}/ask")
async def ask_question(
    conversation_id: int,
    data: AskRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Answer a question and stream progress events (server-sent events)."""
    conversation = await get_conversation_for_user(db, conversation_id, user.id)

    generator = stream_answer(conversation.id, user.id, conversation.contract_id, data.question.strip())
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(generator, media_type="text/event-stream", headers=headers)


@router.get("/chunks/{chunk_id}", response_model=ChunkDetailOut)
async def get_chunk_detail(
    chunk_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return a chunk and its full section, so the user can read the clause in context."""
    chunk = await db.get(Chunk, chunk_id)
    if chunk is None or chunk.user_id != user.id:
        raise HTTPException(status_code=404, detail="Chunk not found")

    document = await db.get(Document, chunk.document_id)
    section = await db.get(Section, chunk.section_id)

    return ChunkDetailOut(
        chunk_id=chunk.id,
        file_name=document.file_name,
        section_path=chunk.section_path,
        page_number=chunk.page_number,
        content=chunk.content,
        section_text=section.full_text,
    )