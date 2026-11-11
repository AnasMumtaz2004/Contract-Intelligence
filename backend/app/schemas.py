from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    """Data needed to create an account."""

    email: str = Field(min_length=3, max_length=255)
    # bcrypt cannot handle passwords longer than 72 bytes
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    """Data needed to log in."""

    email: str
    password: str


class TokenResponse(BaseModel):
    """The login token sent back to the frontend."""

    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    """Public user information."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str


class ContractCreate(BaseModel):
    """Data needed to create a contract."""

    vendor_name: str = Field(min_length=1, max_length=255)
    title: str | None = None


class ContractOut(BaseModel):
    """A contract sent to the frontend."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    vendor_name: str
    title: str | None
    created_at: datetime


class DocumentOut(BaseModel):
    """A document sent to the frontend."""

    id: int
    contract_id: int
    vendor_name: str
    file_name: str
    document_type: str
    status: str
    error_message: str | None
    page_count: int
    chunk_count: int
    effective_date: date | None
    parent_document_id: int | None
    parser_used: str
    parse_quality: float | None
    created_at: datetime


class ChunkOut(BaseModel):
    """A chunk sent to the frontend, used to check parsing quality."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_index: int
    section_path: str
    page_number: int
    content: str
    
class ConversationCreate(BaseModel):
    """Data needed to start a conversation."""

    title: str = Field(min_length=1, max_length=255)
    # None means "search all contracts"
    contract_id: int | None = None


class ConversationOut(BaseModel):
    """A conversation sent to the frontend."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    contract_id: int | None
    title: str
    created_at: datetime


class AskRequest(BaseModel):
    """A question from the user."""

    question: str = Field(min_length=3, max_length=2000)


class CitationOut(BaseModel):
    """One source used in an answer."""

    number: int
    chunk_id: int
    document_id: int
    file_name: str
    section_path: str
    page_number: int
    content: str
    claims: list[str] = []


class AnswerOut(BaseModel):
    """The answer contract. Status is "found" or "not_found" for now."""

    message_id: int
    answer: str
    status: str
    citations: list[CitationOut]
    warning: str = ""


class MessageOut(BaseModel):
    """A saved message with its citations."""

    id: int
    role: str
    content: str
    status: str | None
    warning: str | None = None
    feedback: int | None = None
    citations: list[CitationOut]
    created_at: datetime


class ChunkDetailOut(BaseModel):
    """A chunk with the full section around it, for the citation viewer."""

    chunk_id: int
    file_name: str
    section_path: str
    page_number: int
    content: str
    section_text: str

class MetadataSuggestion(BaseModel):
    """What the LLM thinks the vendor, type and date of a document are."""

    vendor_name: str
    document_type: str
    effective_date: date | None


class MetadataUpdate(BaseModel):
    """The metadata after the user has checked it."""

    vendor_name: str = Field(min_length=1, max_length=255)
    document_type: str
    effective_date: date | None = None
    parent_document_id: int | None = None
    
class FeedbackRequest(BaseModel):
    """A thumbs up (1) or thumbs down (-1)."""

    rating: int
    comment: str | None = Field(default=None, max_length=500)


class FocusOut(BaseModel):
    """The contract that follow-up questions of a conversation focus on."""

    contract_id: int | None
    vendor_name: str


class MemoryCreate(BaseModel):
    """A new memory: an alias or a preference."""

    kind: str
    key: str = Field(min_length=1, max_length=255)
    value: str = Field(min_length=1, max_length=500)


class MemoryOut(BaseModel):
    """A memory sent to the frontend."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    key: str
    value: str
    created_at: datetime