import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import cache, memory
from app.agent.graph import stream_agent
from app.config import settings
from app.database import AsyncSessionLocal
from app.deps import get_current_user, get_db
from app.models import Chunk, Citation, Contract, Conversation, Document, Feedback, Message, Section, User
from app.rag import NOT_FOUND_TEXT
from app.schemas import (
    AnswerOut,
    AskRequest,
    ChunkDetailOut,
    CitationOut,
    ConversationCreate,
    ConversationOut,
    FeedbackRequest,
    FocusOut,
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
    """Return all messages of a conversation, with the citations and the feedback of each answer."""
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
        # Older answers have no claims
        claims = []
        if citation.claims_json:
            claims = json.loads(citation.claims_json)

        citation_out = CitationOut(
            number=citation.number,
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            file_name=file_name,
            section_path=chunk.section_path,
            page_number=chunk.page_number,
            content=chunk.content,
            claims=claims,
        )
        if citation.message_id not in citations_by_message:
            citations_by_message[citation.message_id] = []
        citations_by_message[citation.message_id].append(citation_out)

    # The thumbs of this user
    feedback_query = select(Feedback).where(Feedback.user_id == user.id, Feedback.message_id.in_(message_ids))
    feedback_result = await db.execute(feedback_query)
    ratings = {}
    for item in feedback_result.scalars().all():
        ratings[item.message_id] = item.rating

    output = []
    for message in messages:
        message_out = MessageOut(
            id=message.id,
            role=message.role,
            content=message.content,
            status=message.status,
            warning=message.warning,
            feedback=ratings.get(message.id),
            citations=citations_by_message.get(message.id, []),
            created_at=message.created_at,
        )
        output.append(message_out)
    return output


async def stream_answer(conversation_id: int, user_id: int, contract_id: int | None, question: str):
    """Run the agent, save the answer, and send every step and the final answer to the browser."""
    # The stream needs its own session, because the request session may close early
    async with AsyncSessionLocal() as db:
        try:
            user_message = Message(conversation_id=conversation_id, role="user", content=question)
            db.add(user_message)
            await db.commit()

            # These ids go into the LangSmith trace, so a run can be found from a message
            trace_info = {
                "message_id": user_message.id,
                "conversation_id": conversation_id,
                "pipeline": "chat",
            }

            final_state = {}
            steps_sent = 0
            async for state in stream_agent(
                db,
                user_id,
                contract_id,
                question,
                trace_info,
                conversation_id=conversation_id,
                use_cache=settings.response_cache_enabled,
            ):
                final_state = state

                # Every new step is sent to the browser as soon as it exists
                steps = state.get("steps", [])
                while steps_sent < len(steps):
                    yield sse_event("step", {"text": steps[steps_sent]})
                    steps_sent += 1

            chunks = final_state.get("chunks", [])
            cited_numbers = final_state.get("cited_numbers", [])
            claim_map = final_state.get("claim_map", {})
            status = final_state.get("status", "not_found")
            warning = final_state.get("warning", "")
            answer_text = final_state.get("answer", NOT_FOUND_TEXT)

            saved_warning = None
            if warning != "":
                saved_warning = warning

            assistant_message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=answer_text,
                status=status,
                warning=saved_warning,
            )
            db.add(assistant_message)
            # flush gives the message an id that the citations need
            await db.flush()

            citations_out = []
            for number in cited_numbers:
                # Source [1] is the first chunk, so the list index is number - 1
                chunk = chunks[number - 1]
                claims = claim_map.get(number, [])

                db.add(
                    Citation(
                        message_id=assistant_message.id,
                        chunk_id=chunk["chunk_id"],
                        number=number,
                        claims_json=json.dumps(claims),
                    )
                )
                citation_out = CitationOut(
                    number=number,
                    chunk_id=chunk["chunk_id"],
                    document_id=chunk["document_id"],
                    file_name=chunk["file_name"],
                    section_path=chunk["section_path"],
                    page_number=chunk["page_number"],
                    content=chunk["content"],
                    claims=claims,
                )
                citations_out.append(citation_out)

            await db.commit()

            # Short-term memory: this turn, and the contract that follow-up questions will use
            focus_vendor = final_state.get("focus_vendor", "")
            await memory.add_turn(
                conversation_id,
                final_state.get("question", question),
                answer_text,
                final_state.get("focus_contract_id"),
                focus_vendor,
            )

            # A thumbs down on this message can now delete the saved answer
            cache_key = final_state.get("cache_key", "")
            if cache_key != "":
                await cache.remember_message_key(assistant_message.id, cache_key)

            answer = AnswerOut(
                message_id=assistant_message.id,
                answer=answer_text,
                status=status,
                citations=citations_out,
                warning=warning,
            )
            yield sse_event("answer", answer.model_dump(mode="json"))

            if focus_vendor != "":
                yield sse_event(
                    "focus",
                    {"contract_id": final_state.get("focus_contract_id"), "vendor_name": focus_vendor},
                )

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
    """Answer a question with the agent and stream its steps (server-sent events)."""
    conversation = await get_conversation_for_user(db, conversation_id, user.id)

    generator = stream_answer(conversation.id, user.id, conversation.contract_id, data.question.strip())
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(generator, media_type="text/event-stream", headers=headers)


@router.get("/conversations/{conversation_id}/focus", response_model=FocusOut)
async def get_focus(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the contract that follow-up questions of this conversation focus on."""
    conversation = await get_conversation_for_user(db, conversation_id, user.id)
    stm = await memory.load_stm(conversation.id)
    return FocusOut(contract_id=stm["focus_contract_id"], vendor_name=stm["focus_vendor"])


@router.delete("/conversations/{conversation_id}/focus", response_model=FocusOut)
async def clear_focus(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Stop focusing on one contract. The next question searches all contracts again."""
    conversation = await get_conversation_for_user(db, conversation_id, user.id)
    await memory.clear_focus(conversation.id)
    return FocusOut(contract_id=None, vendor_name="")


@router.post("/messages/{message_id}/feedback")
async def send_feedback(
    message_id: int,
    data: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Save a thumbs up (1) or thumbs down (-1) for an answer. A thumbs down also deletes its saved answer."""
    if data.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="The rating must be 1 or -1")

    message = await db.get(Message, message_id)
    if message is None or message.role != "assistant":
        raise HTTPException(status_code=404, detail="Answer not found")

    conversation = await db.get(Conversation, message.conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Answer not found")

    query = select(Feedback).where(Feedback.user_id == user.id, Feedback.message_id == message_id)
    result = await db.execute(query)
    feedback = result.scalars().first()

    if feedback is None:
        feedback = Feedback(user_id=user.id, message_id=message_id, rating=data.rating, comment=data.comment)
        db.add(feedback)
    else:
        feedback.rating = data.rating
        feedback.comment = data.comment
    await db.commit()

    # A bad answer must not be served again from the cache
    if data.rating == -1:
        await cache.forget_message_answer(message_id)

    return {"rating": data.rating}


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