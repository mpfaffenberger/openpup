"""Tests for peer registry."""

from openpup.peer import Peer, add, handoff, list_all, remove


def test_add_list_remove(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENPUP_PEERS_FILE", str(tmp_path / "p.json"))
    p = Peer(name="alice", endpoint="https://alice.example.com")
    add(p)
    assert len(list_all()) == 1
    assert remove("alice") is True
    assert list_all() == []


def test_handoff(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENPUP_PEERS_FILE", str(tmp_path / "p.json"))
    p = Peer(name="bob", endpoint="https://bob.example.com")
    r = handoff(p, "remind me tomorrow")
    assert r["ok"] is True
    assert r["peer"] == "bob"
