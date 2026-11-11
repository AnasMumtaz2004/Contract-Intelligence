from langgraph.graph import END, START, StateGraph
from app.agent import nodes
from app.agent.state import AgentState
from app.config import settings
from app.logging import get_request_id

# The graph is built once and reused
_graph = None


def route_after_cache(state: AgentState) -> str:
    """After the cache check: stop if a saved answer was found, otherwise start working."""
    if state.get("cache_hit", False):
        return "hit"
    return "miss"


def route_after_grade(state: AgentState) -> str:
    """After grading: write the answer, search again, or give up."""
    if state["grade"]["sufficient"]:
        return "generate"

    # Not enough yet, but there are tries left
    if state["attempt"] < settings.agent_max_attempts:
        return "correct"

    # No tries left. If something useful was found, we answer what we can.
    if len(state["chunks"]) > 0:
        return "generate"
    return "abstain"


def route_after_generate(state: AgentState) -> str:
    """After writing: stop if the model said NOT_FOUND, otherwise check the answer."""
    if state.get("answer_not_found", False):
        return "abstain"
    return "verify"


def route_after_verify(state: AgentState) -> str:
    """After checking: write the answer again once if a claim was unsupported, otherwise finish."""
    has_problem = len(state.get("unsupported", [])) > 0
    can_try_again = state.get("generate_attempts", 0) < settings.agent_max_generate_attempts
    if has_problem and can_try_again:
        return "generate"
    return "finalize"


def build_graph():
    """Connect the steps of the agent into a graph."""
    builder = StateGraph(AgentState)

    builder.add_node("load_context", nodes.load_context_node)
    builder.add_node("cache_check", nodes.cache_check_node)
    builder.add_node("analyze", nodes.analyze_node)
    builder.add_node("retrieve", nodes.retrieve_node)
    builder.add_node("grade", nodes.grade_node)
    builder.add_node("correct", nodes.correct_node)
    builder.add_node("generate", nodes.generate_node)
    builder.add_node("verify", nodes.verify_node)
    builder.add_node("finalize", nodes.finalize_node)
    builder.add_node("abstain", nodes.abstain_node)

    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "cache_check")
    builder.add_conditional_edges("cache_check", route_after_cache, {"hit": END, "miss": "analyze"})
    builder.add_edge("analyze", "retrieve")
    builder.add_edge("retrieve", "grade")
    builder.add_conditional_edges(
        "grade",
        route_after_grade,
        {"generate": "generate", "correct": "correct", "abstain": "abstain"},
    )
    builder.add_edge("correct", "retrieve")
    builder.add_conditional_edges(
        "generate",
        route_after_generate,
        {"verify": "verify", "abstain": "abstain"},
    )
    builder.add_conditional_edges(
        "verify",
        route_after_verify,
        {"generate": "generate", "finalize": "finalize"},
    )
    builder.add_edge("finalize", END)
    builder.add_edge("abstain", END)

    return builder.compile()


def get_graph():
    """Return the compiled graph. It is built the first time it is needed."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def make_run_config(db, user_id: int, contract_id, metadata: dict, conversation_id=None, use_cache=False) -> dict:
    """Make the settings of one run: who asks, and the tags that appear in LangSmith."""
    run_metadata = dict(metadata)
    run_metadata["prompt_version"] = nodes.PROMPT_VERSION
    run_metadata["request_id"] = get_request_id()

    return {
        # The database session is given to the steps here, so it is never part of the saved state
        "configurable": {
            "db": db,
            "user_id": user_id,
            "contract_id": contract_id,
            # Memory and the cache are only used when a conversation is given
            "conversation_id": conversation_id,
            "use_cache": use_cache,
        },
        "tags": ["agent", "prompt:" + nodes.PROMPT_VERSION],
        "metadata": run_metadata,
        "run_name": "contract_agent",
        "recursion_limit": 40,
    }


async def stream_agent(db, user_id: int, contract_id, question: str, metadata: dict, conversation_id=None, use_cache=False):
    """Run the agent and give the full state after every step."""
    graph = get_graph()
    input_state = {"question": question, "steps": []}
    config = make_run_config(db, user_id, contract_id, metadata, conversation_id, use_cache)

    async for state in graph.astream(input_state, config, stream_mode="values"):
        yield state


async def run_agent(db, user_id: int, contract_id, question: str, metadata: dict, conversation_id=None, use_cache=False) -> dict:
    """Run the agent and return the final state."""
    final_state = {}
    async for state in stream_agent(db, user_id, contract_id, question, metadata, conversation_id, use_cache):
        final_state = state
    return final_state