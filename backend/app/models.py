from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.database import Base


class User(Base):
    """A person who can log in."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Contract(Base):
    """One vendor relationship. It can hold many documents later (MSA, amendments)."""

    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    vendor_name: Mapped[str] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    """One uploaded PDF file."""

    __tablename__ = "documents"
    # The same user cannot upload the same file twice
    __table_args__ = (UniqueConstraint("user_id", "file_hash", name="uq_documents_user_file_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"))
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))
    file_hash: Mapped[str] = mapped_column(String(64))
    document_type: Mapped[str] = mapped_column(String(50))
    # uploaded, parsing, chunking, embedding, ready, failed
    status: Mapped[str] = mapped_column(String(30), default="uploaded", server_default="uploaded")
    error_message: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # The date the document takes effect. It tells us which amendment is the newest.
    effective_date: Mapped[date | None] = mapped_column(Date)
    # For an amendment or exhibit: the document it belongs to
    parent_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    # Which parsing paths were used: pymupdf, pymupdf+tables, pymupdf+ocr
    parser_used: Mapped[str] = mapped_column(String(50), default="pymupdf", server_default="pymupdf")
    # Share of pages that gave readable text (0 to 1)
    parse_quality: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Section(Base):
    """A numbered part of a contract, like 12.3 Limitation of Liability."""

    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    parent_section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id", ondelete="SET NULL"))
    section_number: Mapped[str | None] = mapped_column(String(50))
    heading: Mapped[str] = mapped_column(String(255))
    level: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    full_text: Mapped[str] = mapped_column(Text)


class Chunk(Base):
    """A small piece of a section. This is the unit we search."""

    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    section_path: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    # deferred=True means these big columns are only loaded when we ask for them
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dimension), deferred=True)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
        deferred=True,
    )

class Conversation(Base):
    """One chat session. It can be limited to one contract."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    """One question from the user or one answer from the assistant."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    # "user" or "assistant"
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    # Only assistant messages have a status: found or not_found
    status: Mapped[str | None] = mapped_column(String(30))
    # A note shown under the answer, for example "this contract has amendments"
    warning: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Citation(Base):
    """Links an assistant message to a chunk that it used as a source."""

    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"))
    # The number shown in the answer text, like [1]
    number: Mapped[int] = mapped_column(Integer)
     # The claims of the answer that this source supports, as a JSON list
    claims_json: Mapped[str | None] = mapped_column(Text)
    
    
class SecurityEvent(Base):
    """One thing that the security scan found in a document."""

    __tablename__ = "security_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # The document id becomes empty when the document is deleted, so the audit trail stays
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    # injection_text, hidden_text or metadata
    event_type: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10))
    rule: Mapped[str] = mapped_column(String(50))
    page_number: Mapped[int | None] = mapped_column(Integer)
    snippet: Mapped[str] = mapped_column(Text)
    # quarantined, removed, redacted or ignored
    action: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Memory(Base):
    """Long-term memory of a user: vendor aliases and preferences."""

    __tablename__ = "memories"
    __table_args__ = (UniqueConstraint("user_id", "kind", "key", name="uq_memories_user_kind_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # "alias" or "preference"
    kind: Mapped[str] = mapped_column(String(20))
    # For an alias: the nickname. For a preference: a short label.
    key: Mapped[str] = mapped_column(String(255))
    # For an alias: the vendor name. For a preference: the note.
    value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Feedback(Base):
    """A thumbs up (1) or thumbs down (-1) on an answer."""

    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("user_id", "message_id", name="uq_feedback_user_message"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())