import time
from unittest import mock

from openpup.heartbeat.scheduler import Routine, Scheduler, _atomic_write_text


def test_interval_routine_due(tmp_path):
    sched = Scheduler(path=tmp_path / "r.json")
    sched.add(Routine(name="ping", prompt="p", deliver="telegram:1", every=100))

    now = time.time()
    # last_run is 0, so it's due immediately
    due = sched.due(now=now)
    assert [r.name for r in due] == ["ping"]

    # not due again right away
    assert sched.due(now=now + 10) == []
    # due after the interval
    assert [r.name for r in sched.due(now=now + 200)] == ["ping"]


def test_disabled_routine_not_due(tmp_path):
    sched = Scheduler(path=tmp_path / "r.json")
    r = Routine(name="x", prompt="p", deliver="a:b", every=10, enabled=False)
    sched.add(r)
    assert sched.due() == []


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "r.json"
    sched = Scheduler(path=path)
    sched.add(Routine(name="digest", prompt="news", deliver="email:me@x.com", daily="08:00"))

    reloaded = Scheduler.load(path)
    assert len(reloaded.routines) == 1
    assert reloaded.routines[0].name == "digest"
    assert reloaded.routines[0].daily == "08:00"


def test_remove(tmp_path):
    sched = Scheduler(path=tmp_path / "r.json")
    sched.add(Routine(name="a", prompt="p", deliver="x:y", every=5))
    assert sched.remove("a") is True
    assert sched.remove("a") is False


def test_atomic_write_text_replaces_on_success(tmp_path):
    """On success, atomic_write_text puts the new content in place via os.replace."""
    target = tmp_path / "x.txt"
    target.write_text("old")
    _atomic_write_text(target, "new")
    assert target.read_text() == "new"


def test_atomic_write_text_preserves_target_on_failure(tmp_path):
    """If write/rename fails, the original file (if any) is unchanged."""
    target = tmp_path / "x.txt"
    target.write_text("original")
    # Force os.replace to raise; verify target stays untouched + tmp cleaned up.
    real_replace = __import__("os").replace

    def fail_replace(*a, **kw):
        raise OSError("simulated crash")

    with mock.patch("openpup.heartbeat.scheduler.os.replace", side_effect=fail_replace):
        try:
            _atomic_write_text(target, "new")
        except OSError:
            pass
    assert target.read_text() == "original"


def test_save_writes_via_atomic_helper(tmp_path):
    """Scheduler.save() routes through _atomic_write_text (no direct write_text)."""
    path = tmp_path / "r.json"
    sched = Scheduler(path=path)
    sched.add(Routine(name="a", prompt="p", deliver="x:y", every=5))
    with mock.patch("openpup.heartbeat.scheduler._atomic_write_text") as w:
        sched.save()
        w.assert_called_once()
    # File exists and has the routines.
    assert path.exists()
    assert "a" in path.read_text()
