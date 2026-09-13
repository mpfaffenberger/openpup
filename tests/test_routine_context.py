"""Scheduled prompt jobs must be grounded in recent memory + communications.

See #57: job prompts are authored blind (no live human in the conversation),
so run_due_routines prepends a context-grounding preamble to every PROMPT
job. Message jobs (plain reminders) never touch the agent and stay untouched.
"""

from types import SimpleNamespace

import pytest

from openpup import sessions as sessions_mod
from openpup import transcripts
from openpup.config import Settings
from openpup.heartbeat import routines
from openpup.messaging.registry import PlatformRegistry
from openpup.sessions import SessionStore


class _CapturingHost:
    """Drop-in agent host: canned reply, remembers every prompt sent."""

    def __init__(self, reply: str = "done"):
        self.reply = reply
        self.prompts: list[str] = []

    async def run(self, prompt, conversation="default", model=None, keep_history=True):
        self.prompts.append(prompt)
        return self.reply

    def has_history(self, conversation) -> bool:
        return False

    def reset_conversation(self, conversation) -> None:
        pass


@pytest.fixture
def store(tmp_path, monkeypatch) -> SessionStore:
    """A tmp-path store installed as the process singleton."""
    s = SessionStore(path=tmp_path / "sessions.db")
    monkeypatch.setattr(sessions_mod, "_store", s)
    return s


def _settings() -> Settings:
    # Pin the owner address so a host env var can't leak a delivery target.
    return Settings(_env_file=None, OPENPUP_OWNER_ADDRESS=None)


def _job(**kw) -> SimpleNamespace:
    defaults = dict(
        name="job",
        message=None,
        prompt="check the inbox and tell me what matters",
        deliver=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_prompt_job_gets_context_preamble(store):
    job = _job()
    scheduler = SimpleNamespace(due=lambda: [job])
    host = _CapturingHost()

    fired = await routines.run_due_routines(
        host, _settings(), PlatformRegistry(), scheduler
    )

    assert fired == ["job"]
    assert len(host.prompts) == 1
    sent = host.prompts[0]
    # grounding instructions: recent memory AND recent communications
    assert "kennel_recent" in sent
    assert "openpup_session_search" in sent
    assert "memories" in sent.lower()
    assert "incoming" in sent.lower() and "outgoing" in sent.lower()
    # preamble first, the job's own instructions intact after it
    assert sent.index("Ground first") < sent.index("check the inbox")
    assert "check the inbox and tell me what matters" in sent


@pytest.mark.asyncio
async def test_transcript_keeps_authors_prompt_verbatim(store):
    job = _job()
    scheduler = SimpleNamespace(due=lambda: [job])
    host = _CapturingHost()

    await routines.run_due_routines(
        host, _settings(), PlatformRegistry(), scheduler
    )

    dump = store.read_session(transcripts.heartbeat_session_id("routines"))
    user_turns = [m["content"] for m in dump["messages"] if m["role"] == "user"]
    # the author's prompt, not the runtime boilerplate preamble
    assert user_turns == ["check the inbox and tell me what matters"]


@pytest.mark.asyncio
async def test_preamble_stays_short(store):
    job = _job()
    scheduler = SimpleNamespace(due=lambda: [job])
    host = _CapturingHost()

    await routines.run_due_routines(
        host, Settings(_env_file=None), PlatformRegistry(), scheduler
    )

    sent = host.prompts[0]
    preamble = sent[: sent.index("---")]
    # it ships with every job, every day: keep it well under ~120 tokens
    assert len(preamble) < 900


@pytest.mark.asyncio
async def test_message_job_never_runs_agent(store):
    job = _job(message="wake up, human", prompt=None)
    scheduler = SimpleNamespace(due=lambda: [job])
    host = _CapturingHost()

    fired = await routines.run_due_routines(
        host, _settings(), PlatformRegistry(), scheduler
    )

    assert fired == ["job"]
    assert host.prompts == []
