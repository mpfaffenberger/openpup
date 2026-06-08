import time

from openpup.heartbeat.scheduler import Routine, Scheduler


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
