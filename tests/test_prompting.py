"""Tests for the layered system-prompt builder (ported from hermes)."""

import pytest

from openpup import prompting
from openpup.config import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Each test starts from a clean settings cache."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def prompt_env(monkeypatch, tmp_path):
    """Isolated OPENPUP_HOME so SOUL.md / USER.md / config.db are per-test.

    OPENPUP_LEAN_PROMPT is left unset -> the lean default is under test.
    """
    monkeypatch.setenv("OPENPUP_HOME", str(tmp_path))
    monkeypatch.delenv("OPENPUP_LEAN_PROMPT", raising=False)
    get_settings.cache_clear()
    return tmp_path


def _force_full_prompt(monkeypatch) -> None:
    monkeypatch.setenv("OPENPUP_LEAN_PROMPT", "false")
    get_settings.cache_clear()


def _write_profile(home, size_lines: int = 0) -> None:
    lines = ["# User Profile\n\n- Name: Mike\n- Timezone: US/Pacific\n"]
    lines += [f"- Durable fact {i} about the owner.\n" for i in range(size_lines)]
    (home / "USER.md").write_text("".join(lines))


def test_lean_prompt_is_default(prompt_env):
    prompt = prompting.build_system_prompt()
    assert prompt
    # identity + environment still present
    assert "always-on AI companion" in prompt
    assert "Current time:" in prompt
    # on-demand context instructions replace the baked-in layers
    assert "Fetch context on demand" in prompt
    assert "kennel_recent" in prompt
    assert "kennel_recall" in prompt
    assert "openpup_session_search" in prompt
    assert "around_message_id" in prompt
    assert str(prompt_env / "USER.md") in prompt
    # heavy layers are NOT baked in
    assert "# User profile" not in prompt
    assert "# Learning loop" not in prompt
    assert "# Recent memory" not in prompt
    # and the whole thing is small
    assert len(prompt) < 6000


def test_lean_prompt_omits_large_user_profile(prompt_env):
    _write_profile(prompt_env, size_lines=2000)
    prompt = prompting.build_system_prompt()
    assert "Mike" not in prompt
    assert len(prompt) < 6000


def test_lean_prompt_still_has_security_rules(prompt_env):
    prompt = prompting.build_system_prompt()
    assert "Owner-only" in prompt or "owner" in prompt.lower()
    assert "approval" in prompt


def test_full_prompt_still_available(prompt_env, monkeypatch):
    _write_profile(prompt_env)
    _force_full_prompt(monkeypatch)
    prompt = prompting.build_system_prompt()
    assert "# User profile" in prompt
    assert "Mike" in prompt
    assert "# Learning loop" in prompt
    assert "Finishing the job" in prompt


def test_lean_prompt_is_dramatically_smaller(prompt_env, monkeypatch):
    _write_profile(prompt_env, size_lines=3000)
    lean = prompting.build_lean_system_prompt()
    _force_full_prompt(monkeypatch)
    full = prompting.build_system_prompt()
    assert len(lean) < len(full) // 5


def test_build_system_prompt_has_layers(prompt_env, monkeypatch):
    _force_full_prompt(monkeypatch)
    prompt = prompting.build_system_prompt()
    assert prompt
    # identity (SOUL default)
    assert "always-on AI companion" in prompt
    # agentic guidance
    assert "Finishing the job" in prompt
    assert "Take action" in prompt
    assert "task list" in prompt.lower()
    # environment
    assert "Current time:" in prompt


def test_learning_loop_guidance_present(prompt_env, monkeypatch):
    _force_full_prompt(monkeypatch)
    prompt = prompting.build_system_prompt()
    assert "# Learning loop" in prompt
    assert "Persist durable knowledge the moment you learn it" in prompt
    assert 'openpup_skill(action="create"' in prompt
    assert 'openpup_skill(action="update"' in prompt
    assert "openpup_session_search for prior art" in prompt


def test_learning_loop_follows_skill_index(prompt_env, monkeypatch):
    # "check the skill index above" only makes sense if the index IS above.
    _force_full_prompt(monkeypatch)
    monkeypatch.setattr(prompting, "_skills_block", lambda: "# Skills\n- demo: a demo skill")
    prompt = prompting.build_system_prompt()
    assert prompt.index("# Skills") < prompt.index("# Learning loop")


def test_load_soul_from_file(tmp_path, monkeypatch):
    monkeypatch.setattr(prompting, "openpup_home", lambda: tmp_path)
    (tmp_path / "SOUL.md").write_text("You are Rex, a very good boy.")
    assert "Rex, a very good boy" in prompting.load_soul()


def test_default_soul_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(prompting, "openpup_home", lambda: tmp_path)
    assert "always-on AI companion" in prompting.load_soul("Buddy")


def test_ensure_templates_writes_files(tmp_path, monkeypatch):
    monkeypatch.setattr(prompting, "openpup_home", lambda: tmp_path)
    prompting.ensure_templates("Buddy")
    assert (tmp_path / "SOUL.md").exists()
    assert (tmp_path / "USER.md").exists()


def test_user_profile_template_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(prompting, "openpup_home", lambda: tmp_path)
    prompting.ensure_templates("Buddy")
    # untouched template (empty fields) should not be injected
    assert prompting.load_user_profile() is None


def test_user_profile_with_facts_is_loaded(tmp_path, monkeypatch):
    monkeypatch.setattr(prompting, "openpup_home", lambda: tmp_path)
    (tmp_path / "USER.md").write_text("# User Profile\n\n- Name: Mike\n- Timezone: US/Pacific\n")
    profile = prompting.load_user_profile()
    assert profile and "Mike" in profile
