import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict, total=False):
    """Everything the agent knows while it works on one question."""

    # The question. If it was a follow-up, this is the version that stands on its own.
    question: str

    # Memory and scope
    contract_id: int | None
    user_notes: str
    focus_contract_id: int | None
    focus_vendor: str

    # Cache
    cache_key: str
    cache_hit: bool
    # True if a step failed and the agent used a fallback. Such answers are not cached.
    degraded: bool

    # Analyze: the question split into sub-questions, each with a search text
    sub_questions: list[dict]

    # Retrieve and grade
    chunks: list[dict]
    attempt: int
    retry_queries: list[str]
    grade: dict

    # Generate and verify
    answer: str
    answer_not_found: bool
    partial_context: bool
    generate_attempts: int
    claims: list[dict]
    unsupported: list[str]
    conflict: bool
    verified: bool
    verify_feedback: str

    # The final result
    status: str
    cited_numbers: list[int]
    claim_map: dict
    warning: str

    # A short text for every step, shown to the user. New texts are added to the list.
    steps: Annotated[list[str], operator.add]