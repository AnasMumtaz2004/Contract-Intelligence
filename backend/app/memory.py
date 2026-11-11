import json
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_redis
from app.models import Contract, Memory
from app.security import clean_for_prompt

# Alias keys shorter than this are ignored
MIN_ALIAS_LENGTH = 3
# A vendor name with its company ending removed ("Adams Golf Inc" -> "adamsgolf") must be at least this long.
# Shorter ones, like "ability", are common words and would match normal questions.
MIN_AUTO_KEY_LENGTH = 8
# A vendor name can be up to this many words in a question
MAX_WINDOW_WORDS = 4

COMPANY_ENDINGS = ["inc", "corp", "corporation", "ltd", "llc", "co", "company", "holdings", "group", "plc"]

# Questions that start like this usually depend on an earlier question
FOLLOW_UP_OPENERS = ["what about", "and ", "how about", "also", "what if", "same ", "why ", "so "]
# Words that point back to something said before
FOLLOW_UP_WORDS = ["it", "its", "they", "them", "their", "those"]
# Questions with this many words or fewer are checked as possible follow-ups
SHORT_QUESTION_WORDS = 6


# ---------- Short-term memory (Redis) ----------


def stm_key(conversation_id: int) -> str:
    """The Redis key of the short-term memory of a conversation."""
    return "stm:" + str(conversation_id)


async def load_stm(conversation_id: int) -> dict:
    """Load the recent turns and the focus of a conversation. Returns an empty memory if there is none."""
    empty = {"turns": [], "focus_contract_id": None, "focus_vendor": ""}

    try:
        value = await get_redis().get(stm_key(conversation_id))
    except Exception:
        return empty
    if value is None:
        return empty

    try:
        stm = json.loads(value)
    except ValueError:
        return empty

    for key, default in empty.items():
        if key not in stm:
            stm[key] = default
    return stm


async def save_stm(conversation_id: int, stm: dict) -> None:
    """Save the short-term memory. It expires after a while without use."""
    try:
        await get_redis().set(stm_key(conversation_id), json.dumps(stm), ex=settings.stm_ttl_seconds)
    except Exception:
        pass


async def add_turn(conversation_id: int, question: str, answer: str, focus_contract_id, focus_vendor: str) -> None:
    """Remember a question and its answer, and the contract that the conversation focuses on."""
    stm = await load_stm(conversation_id)

    stm["turns"].append({"question": question, "answer": answer[: settings.stm_answer_chars]})
    stm["turns"] = stm["turns"][-settings.stm_max_turns :]
    stm["focus_contract_id"] = focus_contract_id
    stm["focus_vendor"] = focus_vendor

    await save_stm(conversation_id, stm)


async def clear_focus(conversation_id: int) -> None:
    """Forget which contract the conversation focuses on."""
    stm = await load_stm(conversation_id)
    stm["focus_contract_id"] = None
    stm["focus_vendor"] = ""
    await save_stm(conversation_id, stm)


# ---------- Long-term memory (PostgreSQL) ----------


async def load_ltm(db: AsyncSession, user_id: int) -> dict:
    """Load the aliases and preferences of a user."""
    query = select(Memory).where(Memory.user_id == user_id).order_by(Memory.id)
    result = await db.execute(query)

    aliases = {}
    preferences = []
    for memory in result.scalars().all():
        if memory.kind == "alias":
            aliases[memory.key] = memory.value
        elif memory.kind == "preference":
            preferences.append({"key": memory.key, "value": memory.value})

    return {"aliases": aliases, "preferences": preferences}


async def load_contract_list(db: AsyncSession, user_id: int) -> list[dict]:
    """Load the id and vendor name of every contract of a user."""
    query = select(Contract).where(Contract.user_id == user_id).order_by(Contract.id)
    result = await db.execute(query)

    contracts = []
    for contract in result.scalars().all():
        contracts.append({"id": contract.id, "vendor_name": contract.vendor_name})
    return contracts


async def save_memory(db: AsyncSession, user_id: int, kind: str, key: str, value: str) -> Memory:
    """Create a memory, or change the value if the same kind and key already exist."""
    query = select(Memory).where(Memory.user_id == user_id, Memory.kind == kind, Memory.key == key)
    result = await db.execute(query)
    memory = result.scalars().first()

    if memory is None:
        memory = Memory(user_id=user_id, kind=kind, key=key, value=value)
        db.add(memory)
    else:
        memory.value = value

    await db.commit()
    await db.refresh(memory)
    return memory


# ---------- Helpers ----------


def normalize_name(text: str) -> str:
    """Keep only lowercase letters and digits, so 'Adams Golf, Inc.' becomes 'adamsgolfinc'."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def vendor_keys(vendor_name: str) -> list[str]:
    """Make the names that a user may use for a vendor: the full name, and the name without company endings."""
    full_name = normalize_name(vendor_name)

    keys = []
    if len(full_name) >= MIN_ALIAS_LENGTH:
        keys.append(full_name)

    current = full_name
    changed = True
    while changed:
        changed = False
        for ending in COMPANY_ENDINGS:
            if current.endswith(ending) and len(current) - len(ending) >= MIN_AUTO_KEY_LENGTH:
                current = current[: -len(ending)]
                if current not in keys:
                    keys.append(current)
                changed = True
                break

    return keys


def find_vendor_in_text(text: str, contracts: list[dict], aliases: dict):
    """Find the contract that a text talks about. Returns None if no vendor or alias is named."""
    words = re.findall(r"[a-z0-9]+", text.lower())

    # Every group of up to four neighbouring words, joined together
    windows = set()
    for start in range(len(words)):
        for size in range(1, MAX_WINDOW_WORDS + 1):
            if start + size > len(words):
                break
            windows.add("".join(words[start : start + size]))

    best_contract = None
    best_length = 0
    for contract in contracts:
        keys = vendor_keys(contract["vendor_name"])

        vendor_full_name = normalize_name(contract["vendor_name"])
        for alias, vendor_name in aliases.items():
            alias_key = normalize_name(alias)
            if normalize_name(vendor_name) == vendor_full_name and len(alias_key) >= MIN_ALIAS_LENGTH:
                keys.append(alias_key)

        for key in keys:
            # The longest match wins, so "adamsgolfinc" beats "adams"
            if key in windows and len(key) > best_length:
                best_contract = contract
                best_length = len(key)

    return best_contract


def looks_like_follow_up(question: str, has_history: bool) -> bool:
    """Guess whether a question depends on the earlier conversation."""
    if not has_history:
        return False

    lower_question = question.lower().strip()
    words = lower_question.split()

    if len(words) <= SHORT_QUESTION_WORDS:
        return True
    for opener in FOLLOW_UP_OPENERS:
        if lower_question.startswith(opener):
            return True
    for word in words:
        if word.strip("?,.!") in FOLLOW_UP_WORDS:
            return True
    return False


def format_history(turns: list[dict]) -> str:
    """Write the recent turns as text for a prompt."""
    lines = []
    for turn in turns:
        lines.append("User: " + turn["question"])
        # An old answer was made from contract text, so it is cleaned like any other contract text
        lines.append("Assistant: " + clean_for_prompt(turn["answer"]))
    return "\n".join(lines)


def format_preferences(preferences: list[dict]) -> str:
    """Write the preferences of the user as text for a prompt."""
    lines = []
    for preference in preferences:
        lines.append("- " + preference["key"] + ": " + preference["value"])
    return "\n".join(lines)


def read_rewritten_question(reply: str, fallback: str) -> str:
    """Read the rewritten question from an LLM reply. Returns the fallback if the reply is unusable."""
    for line in reply.strip().split("\n"):
        line = line.strip().strip('"').strip("'").strip()
        if line == "":
            continue
        if len(line) > 300:
            return fallback
        return line
    return fallback