import json
from pathlib import Path

from langchain_core.runnables import RunnableConfig

from app import cache, memory, security
from app.agent.state import AgentState
from app.config import settings
from app.llm import ask_llm
from app.rag import NOT_FOUND_MARKER, NOT_FOUND_TEXT, build_context, describe_document, find_cited_numbers
from app.retrieval.cross_reference import add_cross_references
from app.retrieval.rerank import rerank_chunks
from app.retrieval.search import find_amendment_warning, hybrid_search, merge_with_rrf

PROMPTS_FOLDER = Path(__file__).resolve().parent / "prompts"

# Written into every LangSmith run and into every cache key.
# Change it whenever you change a prompt, so old saved answers are not reused.
PROMPT_VERSION = "phase5-v1"


def load_prompt(name: str) -> str:
    """Read one prompt file from the prompts folder."""
    return (PROMPTS_FOLDER / (name + ".md")).read_text(encoding="utf-8")


def shorten(text: str, max_chars: int) -> str:
    """Cut a text to a maximum length."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def read_json_reply(reply: str):
    """Read the JSON object from an LLM reply. Returns None if there is none."""
    text = reply.strip()
    text = text.replace("```json", "").replace("```", "").strip()

    # The model may add words around the JSON, so we cut from the first { to the last }
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None

    # LLMs sometimes send broken JSON, so this try/catch is needed
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None
    return data


def read_number_list(values, max_number: int) -> list[int]:
    """Turn a list from the LLM into a clean list of numbers between 1 and max_number."""
    numbers = []
    if not isinstance(values, list):
        return numbers

    for value in values:
        # The LLM may send text or other things instead of numbers
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number < 1 or number > max_number:
            continue
        if number in numbers:
            continue
        numbers.append(number)
    return numbers


def read_analysis(reply: str, question: str) -> list[dict]:
    """Read the plan of the analyze step. If the reply is unusable, search with the question itself."""
    fallback = [{"question": question, "search_query": question}]

    data = read_json_reply(reply)
    if data is None:
        return fallback

    raw_items = data.get("sub_questions")
    if not isinstance(raw_items, list):
        return fallback

    sub_questions = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        sub_question = str(item.get("question", "")).strip()
        search_query = str(item.get("search_query", "")).strip()
        if sub_question == "":
            continue
        if search_query == "":
            search_query = sub_question

        sub_questions.append({"question": sub_question, "search_query": search_query})
        if len(sub_questions) >= settings.agent_max_sub_questions:
            break

    if len(sub_questions) == 0:
        return fallback
    return sub_questions


def read_grade(reply: str, chunk_count: int):
    """Read the answer of the grade step. Returns None if the reply is unusable."""
    data = read_json_reply(reply)
    if data is None:
        return None

    relevant = read_number_list(data.get("relevant"), chunk_count)
    sufficient = data.get("sufficient") is True

    # The model said "enough" but forgot the list, so we trust it and keep every passage
    if sufficient and len(relevant) == 0:
        relevant = list(range(1, chunk_count + 1))

    return {
        "relevant": relevant,
        "sufficient": sufficient,
        "missing": str(data.get("missing", "")).strip(),
        "better_query": str(data.get("better_query", "")).strip(),
    }


def read_verification(reply: str, chunk_count: int):
    """Read the answer of the verify step. Returns None if the reply is unusable."""
    data = read_json_reply(reply)
    if data is None:
        return None

    raw_claims = data.get("claims")
    if not isinstance(raw_claims, list):
        return None

    claims = []
    for item in raw_claims:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if text == "":
            continue
        claims.append(
            {
                "text": text,
                "supported": item.get("supported") is True,
                "sources": read_number_list(item.get("sources"), chunk_count),
            }
        )

    return {"claims": claims, "conflict": data.get("conflict") is True}


def build_claim_map(claims: list[dict]) -> dict:
    """Make {source number: the claims that this source supports}."""
    claim_map = {}
    for claim in claims:
        if not claim["supported"]:
            continue
        for number in claim["sources"]:
            if number not in claim_map:
                claim_map[number] = []
            claim_map[number].append(claim["text"])
    return claim_map


def pick_chunks(chunks: list[dict], numbers: list[int]) -> list[dict]:
    """Pick the chunks with the given numbers (1 is the first chunk)."""
    picked = []
    for number in numbers:
        picked.append(chunks[number - 1])
    return picked


def sort_by_date(chunks: list[dict]) -> list[dict]:
    """Put the oldest documents first. The original contract has no date, so it comes first."""
    sorted_chunks = list(chunks)
    # sort keeps the old order for chunks with the same date
    sorted_chunks.sort(key=lambda chunk: chunk.get("effective_date", ""))
    return sorted_chunks


def interleave(lists: list[list[dict]]) -> list[dict]:
    """Take one chunk from each list in turn, so every sub-question stays represented."""
    merged = []
    seen_ids = set()

    longest = 0
    for items in lists:
        longest = max(longest, len(items))

    for position in range(longest):
        for items in lists:
            if position >= len(items):
                continue
            chunk = items[position]
            if chunk["chunk_id"] in seen_ids:
                continue
            seen_ids.add(chunk["chunk_id"])
            merged.append(chunk)
    return merged


def build_grade_prompt(question: str, sub_questions: list[dict], chunks: list[dict]) -> str:
    """Write the text that the grader reads: the question and short numbered excerpts."""
    lines = ["QUESTION: " + question]

    if len(sub_questions) > 1:
        lines.append("SUB-QUESTIONS:")
        for sub_question in sub_questions:
            lines.append("- " + sub_question["question"])

    lines.append("")
    lines.append("EXCERPTS:")
    for number, chunk in enumerate(chunks, start=1):
        header = "[" + str(number) + "] " + describe_document(chunk)
        header += " | " + security.clean_for_prompt(chunk["section_path"])
        lines.append(header)
        # The excerpt is contract text, so it is cleaned before it goes into a prompt
        lines.append(security.clean_for_prompt(shorten(chunk["content"], settings.grade_chunk_chars)))
        lines.append("")

    return "\n".join(lines)


def get_run_context(config: RunnableConfig) -> tuple:
    """Get the database session, the user id and the contract id that were given to this run."""
    values = config["configurable"]
    return values["db"], values["user_id"], values["contract_id"]


async def retrieve_for_sub_question(
    db,
    user_id: int,
    contract_id,
    queries: list[str],
    question: str,
    top_k: int,
) -> list[dict]:
    """Search with several wordings, merge the results, rerank them and follow cross-references."""
    unique_queries = []
    for query in queries:
        if query != "" and query not in unique_queries:
            unique_queries.append(query)

    result_lists = []
    for query in unique_queries:
        candidates = await hybrid_search(db, user_id, query, contract_id=contract_id, top_k=settings.rerank_pool)
        result_lists.append(candidates)

    merged = merge_with_rrf(result_lists, settings.rrf_k)
    merged = merged[: settings.rerank_pool]

    # The reranker judges the passages against the sub-question, not against the rewritten search text
    best = await rerank_chunks(question, merged, top_k)
    return await add_cross_references(db, user_id, best)


async def load_context_node(state: AgentState, config: RunnableConfig) -> dict:
    """Use the memory: find the contract in focus, and rewrite a follow-up question so it stands on its own."""
    values = config["configurable"]
    contract_id = values["contract_id"]
    conversation_id = values.get("conversation_id")

    # Without a conversation there is no memory (for example in the evaluation scripts)
    if conversation_id is None:
        return {"contract_id": contract_id, "steps": []}

    db = values["db"]
    user_id = values["user_id"]
    question = state["question"]
    steps = []

    # Memory is a help, not a need. If it fails, the question is answered without it.
    try:
        stm = await memory.load_stm(conversation_id)
        ltm = await memory.load_ltm(db, user_id)
        contracts = await memory.load_contract_list(db, user_id)
    except Exception:
        if db is not None:
            await db.rollback()
        return {"contract_id": contract_id, "steps": []}

    # A conversation that is limited to one contract keeps its contract. Otherwise we look for a vendor.
    focus_contract_id = None
    focus_vendor = ""
    if contract_id is None:
        known_ids = []
        for contract in contracts:
            known_ids.append(contract["id"])

        mentioned = memory.find_vendor_in_text(question, contracts, ltm["aliases"])
        if mentioned is not None:
            focus_contract_id = mentioned["id"]
            focus_vendor = mentioned["vendor_name"]
        elif stm["focus_contract_id"] in known_ids:
            focus_contract_id = stm["focus_contract_id"]
            focus_vendor = stm["focus_vendor"]

        if focus_contract_id is not None:
            contract_id = focus_contract_id
            steps.append("Focusing on " + focus_vendor)

    # A short question may depend on the earlier ones, so the LLM writes it so that it stands on its own
    if memory.looks_like_follow_up(question, len(stm["turns"]) > 0):
        vendor_text = focus_vendor
        if vendor_text == "":
            vendor_text = "none"

        prompt = "CONVERSATION:\n" + memory.format_history(stm["turns"])
        prompt += "\n\nVENDOR IN FOCUS: " + vendor_text
        prompt += "\n\nLATEST QUESTION: " + question

        # If the rewrite fails, we keep the question as the user wrote it
        try:
            reply = await ask_llm("fast", load_prompt("followup"), prompt)
            rewritten = memory.read_rewritten_question(reply, question)
            if rewritten != question:
                steps.append("Understood your question as: " + shorten(rewritten, 120))
                question = rewritten
        except Exception:
            pass

    return {
        "question": question,
        "contract_id": contract_id,
        "focus_contract_id": focus_contract_id,
        "focus_vendor": focus_vendor,
        "user_notes": memory.format_preferences(ltm["preferences"]),
        "steps": steps,
    }


async def cache_check_node(state: AgentState, config: RunnableConfig) -> dict:
    """Look for a saved answer to the same question about the same documents."""
    values = config["configurable"]
    if not values.get("use_cache", False):
        return {"steps": []}

    db, user_id, _contract_id = get_run_context(config)
    contract_id = state.get("contract_id")

    # A cache problem must never stop a question
    try:
        fingerprint = await cache.make_scope_fingerprint(db, user_id, contract_id)
        key = cache.make_response_key(
            state["question"],
            contract_id,
            fingerprint,
            state.get("user_notes", ""),
            PROMPT_VERSION,
        )
        entry = await cache.get_response(key)
    except Exception:
        if db is not None:
            await db.rollback()
        return {"steps": []}

    if entry is None:
        return {"cache_key": key, "cache_hit": False, "steps": []}

    return {
        "cache_key": key,
        "cache_hit": True,
        "answer": entry["answer"],
        "status": entry["status"],
        "chunks": entry["chunks"],
        "cited_numbers": entry["cited_numbers"],
        "claim_map": entry["claim_map"],
        "warning": entry["warning"],
        "steps": ["Found a saved answer for this question"],
    }


async def analyze_node(state: AgentState) -> dict:
    """Split the question into sub-questions and write a search text for each one."""
    question = state["question"]
    degraded = False

    # If the planning call fails, we still search with the original question
    try:
        reply = await ask_llm("fast", load_prompt("analyze"), "Question: " + question)
        sub_questions = read_analysis(reply, question)
        step = "Planned " + str(len(sub_questions)) + " search(es): "
        step += "; ".join(shorten(item["search_query"], 70) for item in sub_questions)
    except Exception:
        sub_questions = [{"question": question, "search_query": question}]
        step = "Could not plan the search, using the question as it is"
        degraded = True

    result = {
        "sub_questions": sub_questions,
        "attempt": 1,
        "retry_queries": [],
        "generate_attempts": 0,
        "steps": [step],
    }
    if degraded:
        result["degraded"] = True
    return result


async def retrieve_node(state: AgentState, config: RunnableConfig) -> dict:
    """Search the contracts for every sub-question and merge the results."""
    db, user_id, config_contract_id = get_run_context(config)
    # The memory step may have narrowed the search to one contract
    contract_id = state.get("contract_id", config_contract_id)
    retry_queries = state.get("retry_queries", [])

    lists = []
    # On a second try, the useful passages from the first try are kept
    if state["attempt"] > 1:
        lists.append(state.get("chunks", []))

    for sub_question in state["sub_questions"]:
        queries = [sub_question["search_query"], sub_question["question"]]
        for query in retry_queries:
            queries.append(query)

        chunks = await retrieve_for_sub_question(
            db,
            user_id,
            contract_id,
            queries,
            sub_question["question"],
            settings.agent_chunks_per_sub_question,
        )
        lists.append(chunks)

    merged = interleave(lists)
    merged = merged[: settings.agent_max_chunks]

    step = "Searched the contracts: " + str(len(merged)) + " passages found"
    return {"chunks": merged, "steps": [step]}


async def grade_node(state: AgentState) -> dict:
    """Check which passages help, and whether they are enough to answer."""
    chunks = state["chunks"]

    if len(chunks) == 0:
        grade = {"relevant": [], "sufficient": False, "missing": "Nothing was found.", "better_query": ""}
        return {"grade": grade, "steps": ["Found no passages to check"]}

    # If the grading call fails, we keep all passages and go on
    try:
        prompt = build_grade_prompt(state["question"], state["sub_questions"], chunks)
        reply = await ask_llm("fast", load_prompt("grade"), prompt)
        grade = read_grade(reply, len(chunks))
    except Exception:
        grade = None

    if grade is None:
        everything = {"relevant": [], "sufficient": True, "missing": "", "better_query": ""}
        return {
            "grade": everything,
            "degraded": True,
            "steps": ["Could not check the passages, using all of them"],
        }

    relevant_chunks = sort_by_date(pick_chunks(chunks, grade["relevant"]))

    step = "Checked the passages: " + str(len(relevant_chunks)) + " of " + str(len(chunks)) + " are useful"
    if not grade["sufficient"]:
        step += ". Not enough yet"
        if grade["missing"] != "":
            step += ": " + shorten(grade["missing"], 100)

    return {"grade": grade, "chunks": relevant_chunks, "steps": [step]}


async def correct_node(state: AgentState) -> dict:
    """Prepare a second search with new words."""
    grade = state["grade"]

    new_query = grade["better_query"]
    if new_query == "":
        new_query = grade["missing"]
    if new_query == "":
        new_query = state["question"]

    return {
        "attempt": state["attempt"] + 1,
        "retry_queries": [new_query],
        "steps": ["Searching again with: " + shorten(new_query, 80)],
    }


async def generate_node(state: AgentState) -> dict:
    """Write the answer from the passages that were found."""
    chunks = state["chunks"]
    context = build_context(chunks)

    user_prompt = "<context>\n" + context + "\n</context>\n\nQuestion: " + state["question"]

    # Notes that the user saved (long-term memory). They are background, not facts about the contract.
    user_notes = state.get("user_notes", "")
    if user_notes != "":
        user_prompt += "\n\nNotes from the user about how they work (background only, not facts about the contract):\n"
        user_prompt += user_notes

    # After a failed check, the model sees what was wrong and writes the answer again
    feedback = state.get("verify_feedback", "")
    if feedback != "":
        user_prompt += "\n\nYour previous answer had problems. " + feedback
        user_prompt += " Write the answer again. Only state what the excerpts say."

    answer = await ask_llm("smart", load_prompt("generate"), user_prompt)
    answer = answer.strip()
    attempts = state.get("generate_attempts", 0) + 1

    # If the passages were only partly enough, the answer can only be partly complete
    partial_context = not state["grade"]["sufficient"]

    if answer.startswith(NOT_FOUND_MARKER):
        return {
            "answer": NOT_FOUND_TEXT,
            "answer_not_found": True,
            "generate_attempts": attempts,
            "steps": ["The passages do not contain the answer"],
        }

    if attempts > 1:
        step = "Wrote the answer again after checking it"
    else:
        step = "Wrote an answer from " + str(len(chunks)) + " source(s)"

    return {
        "answer": answer,
        "answer_not_found": False,
        "partial_context": partial_context,
        "generate_attempts": attempts,
        "steps": [step],
    }


async def verify_node(state: AgentState) -> dict:
    """Check every claim of the answer against the passages."""
    chunks = state["chunks"]
    prompt = "SOURCES:\n" + build_context(chunks) + "\n\nANSWER:\n" + state["answer"]

    # If the check fails, we keep the answer, but we tell the user that it was not checked
    try:
        reply = await ask_llm("smart", load_prompt("verify"), prompt)
        result = read_verification(reply, len(chunks))
    except Exception:
        result = None

    if result is None:
        return {
            "claims": [],
            "unsupported": [],
            "conflict": False,
            "verified": False,
            "verify_feedback": "",
            "steps": ["Could not check the answer against the sources"],
        }

    unsupported = []
    for claim in result["claims"]:
        if not claim["supported"]:
            unsupported.append(claim["text"])

    feedback = ""
    if len(unsupported) > 0:
        feedback = "These statements are not supported by the excerpts: " + "; ".join(unsupported) + "."

    if len(unsupported) > 0:
        step = "Checked the answer: " + str(len(unsupported)) + " claim(s) could not be verified"
    else:
        step = "Checked every claim against the sources: all supported"

    return {
        "claims": result["claims"],
        "unsupported": unsupported,
        "conflict": result["conflict"],
        "verified": True,
        "verify_feedback": feedback,
        "steps": [step],
    }


async def finalize_node(state: AgentState, config: RunnableConfig) -> dict:
    """Decide the final status, find the cited sources, write the warnings, and save the answer in the cache."""
    db, _user_id, _contract_id = get_run_context(config)
    values = config["configurable"]
    chunks = state["chunks"]

    cited_numbers = find_cited_numbers(state["answer"], len(chunks))
    claim_map = build_claim_map(state.get("claims", []))
    # If the model forgot the [1] marks, the verified claims still tell us which sources were used
    if len(cited_numbers) == 0:
        cited_numbers = sorted(claim_map.keys())

    unsupported = state.get("unsupported", [])
    if state.get("conflict", False):
        status = "conflicting"
    elif len(unsupported) > 0 or state.get("partial_context", False):
        status = "partial"
    else:
        status = "found"

    notes = []

    chunks_to_check = []
    for number in cited_numbers:
        chunks_to_check.append(chunks[number - 1])
    if len(chunks_to_check) == 0:
        chunks_to_check = chunks
    amendment_warning = await find_amendment_warning(db, chunks_to_check)
    if amendment_warning != "":
        notes.append(amendment_warning)

    if security.count_flagged_chunks(chunks) > 0:
        notes.append("Some text in the contracts looked like instructions to an AI system. It was ignored.")
    if status == "conflicting":
        notes.append("The documents disagree and nothing shows which one applies.")
    if len(unsupported) > 0:
        notes.append("Could not verify: " + "; ".join(unsupported) + ".")
    if state.get("partial_context", False):
        notes.append("Only part of the question could be answered from the contract.")
    if not state.get("verified", True):
        notes.append("This answer could not be checked automatically.")

    warning = " ".join(notes)

    # An answer that was made with a fallback (a failed step) is not saved
    is_degraded = state.get("degraded", False) or not state.get("verified", True)
    cache_key = state.get("cache_key", "")
    if values.get("use_cache", False) and cache_key != "" and not is_degraded:
        entry = {
            "answer": state["answer"],
            "status": status,
            "chunks": chunks,
            "cited_numbers": cited_numbers,
            "claim_map": claim_map,
            "warning": warning,
        }
        await cache.save_response(cache_key, entry)

    return {
        "status": status,
        "cited_numbers": cited_numbers,
        "claim_map": claim_map,
        "warning": warning,
        "steps": ["Done"],
    }


async def abstain_node(state: AgentState) -> dict:
    """Say that the answer is not in the contracts."""
    return {
        "answer": NOT_FOUND_TEXT,
        "status": "not_found",
        "cited_numbers": [],
        "claim_map": {},
        "warning": "",
        "steps": ["Could not find this in the contracts"],
    }