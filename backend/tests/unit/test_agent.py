import asyncio

from app.agent.graph import run_agent
from app.agent.nodes import read_analysis, read_grade
from app.rag import NOT_FOUND_TEXT

QUESTION = "What law governs this agreement?"

ANALYZE = '{"sub_questions": [{"question": "What law governs this agreement?", "search_query": "governing law jurisdiction"}]}'
GRADE_OK = '{"relevant": [1], "sufficient": true, "missing": "", "better_query": ""}'
GRADE_NOT_ENOUGH = '{"relevant": [], "sufficient": false, "missing": "no rule found", "better_query": "choice of law clause"}'
GRADE_PARTLY = '{"relevant": [1], "sufficient": false, "missing": "only part", "better_query": "choice of law clause"}'
ANSWER = "The agreement is governed by Delaware law [1]."
VERIFY_OK = '{"claims": [{"text": "governed by Delaware law", "supported": true, "sources": [1]}], "conflict": false}'
VERIFY_BAD = '{"claims": [{"text": "governed by Delaware law", "supported": false, "sources": []}], "conflict": false}'
VERIFY_CONFLICT = '{"claims": [{"text": "governed by Delaware law", "supported": true, "sources": [1]}], "conflict": true}'


def make_chunk(chunk_id: int = 1) -> dict:
    """Make a fake chunk."""
    return {
        "chunk_id": chunk_id,
        "document_id": 1,
        "contract_id": 1,
        "file_name": "a.pdf",
        "document_type": "Other",
        "effective_date": "",
        "section_path": "5 Governing Law",
        "page_number": 3,
        "content": "This Agreement is governed by the laws of the State of Delaware.",
    }


def run(question: str = QUESTION) -> dict:
    """Run the agent on a question and return the final state."""
    return asyncio.run(run_agent(None, 1, None, question, {}))


def test_normal_question_goes_through_all_steps(agent_env):
    """Analyze, grade, generate and verify each call the LLM once, and the answer is found."""
    agent_env.chunks = [make_chunk()]
    agent_env.set_replies([ANALYZE, GRADE_OK, ANSWER, VERIFY_OK])

    state = run()

    assert state["status"] == "found"
    assert state["cited_numbers"] == [1]
    assert state["claim_map"] == {1: ["governed by Delaware law"]}
    assert agent_env.roles == ["fast", "fast", "smart", "smart"]


def test_not_enough_passages_triggers_a_second_search(agent_env):
    """If the grader says 'not enough', the agent searches again with the new words."""
    agent_env.chunks = [make_chunk()]
    agent_env.set_replies([ANALYZE, GRADE_NOT_ENOUGH, GRADE_OK, ANSWER, VERIFY_OK])

    state = run()

    assert len(agent_env.search_queries) == 2
    assert "choice of law clause" in agent_env.search_queries[1]
    assert state["status"] == "found"


def test_agent_gives_up_when_nothing_useful_is_found(agent_env):
    """After the last try with nothing useful, the agent says not found and never writes an answer."""
    agent_env.chunks = [make_chunk()]
    agent_env.set_replies([ANALYZE, GRADE_NOT_ENOUGH, GRADE_NOT_ENOUGH])

    state = run()

    assert state["status"] == "not_found"
    assert state["answer"] == NOT_FOUND_TEXT
    assert "smart" not in agent_env.roles


def test_generator_saying_not_found_skips_the_check(agent_env):
    """If the generator says NOT_FOUND, the answer is not checked."""
    agent_env.chunks = [make_chunk()]
    agent_env.set_replies([ANALYZE, GRADE_OK, "NOT_FOUND"])

    state = run()

    assert state["status"] == "not_found"
    assert agent_env.roles == ["fast", "fast", "smart"]


def test_failed_check_writes_the_answer_again_once(agent_env):
    """An unsupported claim sends the agent back to generate, with the problem in the prompt."""
    agent_env.chunks = [make_chunk()]
    agent_env.set_replies([ANALYZE, GRADE_OK, "Wrong answer [1].", VERIFY_BAD, ANSWER, VERIFY_OK])

    state = run()

    assert state["status"] == "found"
    assert state["answer"] == ANSWER
    assert agent_env.roles == ["fast", "fast", "smart", "smart", "smart", "smart"]
    # The second generate prompt tells the model what was wrong
    assert "previous answer had problems" in agent_env.prompts[4]


def test_answer_that_fails_the_check_twice_is_partial(agent_env):
    """If the claim is still unsupported after the rewrite, the status is partial with a warning."""
    agent_env.chunks = [make_chunk()]
    agent_env.set_replies([ANALYZE, GRADE_OK, ANSWER, VERIFY_BAD, ANSWER, VERIFY_BAD])

    state = run()

    assert state["status"] == "partial"
    assert "Could not verify" in state["warning"]


def test_conflicting_sources_give_the_conflicting_status(agent_env):
    """If the checker finds a conflict, the status is conflicting."""
    agent_env.chunks = [make_chunk()]
    agent_env.set_replies([ANALYZE, GRADE_OK, ANSWER, VERIFY_CONFLICT])

    state = run()

    assert state["status"] == "conflicting"


def test_partly_useful_passages_give_a_partial_answer(agent_env):
    """If the passages only partly answer the question, the answer is still written but marked partial."""
    agent_env.chunks = [make_chunk()]
    agent_env.set_replies([ANALYZE, GRADE_PARTLY, GRADE_PARTLY, ANSWER, VERIFY_OK])

    state = run()

    assert state["status"] == "partial"
    assert "Only part of the question" in state["warning"]


def test_failed_planning_call_falls_back_to_the_question(agent_env):
    """If the analyze call fails, the agent searches with the original question and goes on."""
    agent_env.chunks = [make_chunk()]
    agent_env.set_replies([RuntimeError("quota"), GRADE_OK, ANSWER, VERIFY_OK])

    state = run()

    assert agent_env.search_queries[0] == [QUESTION, QUESTION]
    assert state["status"] == "found"
    assert "Could not plan the search" in state["steps"][0]


def test_read_analysis_falls_back_when_the_reply_is_not_json():
    """A reply without JSON gives one sub-question: the question itself."""
    plan = read_analysis("Sorry, I cannot do that.", QUESTION)
    assert plan == [{"question": QUESTION, "search_query": QUESTION}]


def test_read_analysis_limits_the_number_of_sub_questions():
    """At most three sub-questions are kept."""
    reply = '{"sub_questions": ['
    reply += '{"question": "a", "search_query": "a"}, {"question": "b", "search_query": "b"},'
    reply += '{"question": "c", "search_query": "c"}, {"question": "d", "search_query": "d"}]}'
    plan = read_analysis(reply, QUESTION)
    assert len(plan) == 3


def test_read_grade_ignores_numbers_that_do_not_exist():
    """Excerpt numbers outside the list are dropped."""
    grade = read_grade('{"relevant": [1, 7, "x", 2], "sufficient": true}', 3)
    assert grade["relevant"] == [1, 2]
    assert grade["sufficient"] is True


def test_read_grade_trusts_sufficient_when_the_list_is_missing():
    """If the grader says enough but gives no list, every passage is kept."""
    grade = read_grade('{"relevant": [], "sufficient": true}', 3)
    assert grade["relevant"] == [1, 2, 3]