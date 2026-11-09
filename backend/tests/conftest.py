import os

import pytest

# The tests import app code that reads settings, so we give it safe fake values.
# The unit tests never connect to a real database.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key")


class AgentEnv:
    """A fake LLM, a fake search and a fake amendment lookup for the agent tests."""

    def __init__(self):
        # The replies of the fake LLM, one for each call. An Exception in the list is raised.
        self.replies = []
        # What was asked: the role and the text of every LLM call
        self.roles = []
        self.prompts = []
        # The search texts of every search
        self.search_queries = []
        # The chunks that every search returns
        self.chunks = []

    def set_replies(self, replies: list) -> None:
        """Set the replies that the fake LLM gives, in order."""
        self.replies = list(replies)

    async def ask_llm(self, role, system_prompt, user_prompt):
        """Pretend to be the LLM."""
        self.roles.append(role)
        self.prompts.append(user_prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def search(self, db, user_id, contract_id, queries, question, top_k):
        """Pretend to search the contracts."""
        self.search_queries.append(list(queries))
        copies = []
        for chunk in self.chunks:
            copies.append(dict(chunk))
        return copies

    async def find_warning(self, db, chunks):
        """Pretend to look for amendments."""
        return ""


@pytest.fixture
def agent_env(monkeypatch):
    """Replace the LLM, the search and the amendment lookup of the agent with fakes."""
    from app.agent import nodes

    env = AgentEnv()
    monkeypatch.setattr(nodes, "ask_llm", env.ask_llm)
    monkeypatch.setattr(nodes, "retrieve_for_sub_question", env.search)
    monkeypatch.setattr(nodes, "find_amendment_warning", env.find_warning)
    return env