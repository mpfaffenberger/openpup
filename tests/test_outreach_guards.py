"""Tests for the outreach spam-guard logic (no agent / network needed)."""

from openpup.config import Settings
from openpup.heartbeat import outreach


def _settings(tmp_path, **overrides):
    base = dict(
        OPENPUP_OWNER_ADDRESS="telegram:1",
        PUPPY_KENNEL_ROOT=str(tmp_path / "kennel"),
        OPENPUP_OUTREACH_MAX_PER_DAY=2,
    )
    base.update(overrides)
    s = Settings(**base)
    # redirect state dir into tmp by monkeypatching kennel_root-derived dir
    return s


def test_quiet_hours_wrap_midnight(tmp_path, monkeypatch):
    s = _settings(tmp_path, OPENPUP_QUIET_HOURS="23-7")
    # 2am -> quiet
    monkeypatch.setattr(outreach.time, "time", lambda: _at_hour(2))
    assert outreach._in_quiet_hours(s) is True
    # noon -> not quiet
    monkeypatch.setattr(outreach.time, "time", lambda: _at_hour(12))
    assert outreach._in_quiet_hours(s) is False


def test_quiet_hours_same_day(tmp_path, monkeypatch):
    s = _settings(tmp_path, OPENPUP_QUIET_HOURS="9-17")
    monkeypatch.setattr(outreach.time, "time", lambda: _at_hour(10))
    assert outreach._in_quiet_hours(s) is True
    monkeypatch.setattr(outreach.time, "time", lambda: _at_hour(20))
    assert outreach._in_quiet_hours(s) is False


def test_daily_cap(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    # force state_dir into tmp
    monkeypatch.setattr(type(s), "state_dir", property(lambda self: tmp_path))
    assert outreach._remaining(s) == 2
    outreach._record_sent(s)
    assert outreach._remaining(s) == 1
    outreach._record_sent(s)
    assert outreach._remaining(s) == 0


def _at_hour(hour: int) -> float:
    """Return an epoch timestamp at a given local hour today."""
    from datetime import datetime

    now = datetime.now().replace(hour=hour, minute=30, second=0, microsecond=0)
    return now.timestamp()
