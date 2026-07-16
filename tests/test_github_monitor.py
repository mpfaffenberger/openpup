"""Tests for the github_monitor module."""



from openpup.github_monitor import RepoWatch, WatchStore


class TestRepoWatch:
    def test_key(self):
        w = RepoWatch(owner="mpfaffenberger", name="openpup")
        assert w.key == "mpfaffenberger/openpup"

    def test_round_trip(self):
        w = RepoWatch(owner="mpfaffenberger", name="openpup", last_issue_ts=1700000000.0)
        d = w.to_dict()
        restored = RepoWatch.from_dict(d)
        assert restored.owner == "mpfaffenberger"
        assert restored.last_issue_ts == 1700000000.0


class TestWatchStore:
    def test_watch_and_list(self, tmp_path):
        s = WatchStore(tmp_path / "w.json")
        s.watch("mpfaffenberger", "openpup")
        s.watch("mpfaffenberger", "openpup2")
        watches = s.list()
        keys = [w.key for w in watches]
        assert keys == ["mpfaffenberger/openpup", "mpfaffenberger/openpup2"]

    def test_unwatch(self, tmp_path):
        s = WatchStore(tmp_path / "w.json")
        s.watch("a", "b")
        assert s.unwatch("a", "b") is True
        # Second time false.
        assert s.unwatch("a", "b") is False

    def test_round_trip(self, tmp_path):
        s = WatchStore(tmp_path / "w.json")
        s.watch("a", "b")
        s2 = WatchStore(tmp_path / "w.json")
        watches = s2.list()
        assert len(watches) == 1
        assert watches[0].key == "a/b"
