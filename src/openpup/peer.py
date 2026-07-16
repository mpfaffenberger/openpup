"""Multi-pup collaboration: peer registry for OpenPup-to-OpenPup handoffs.

v1 keeps a JSON-backed registry of trusted peers. Real handoff over the
network (HMAC-signed payload, peer URL, etc.) is a follow-up commit so
v1 stays focused on the framework.

Storage: ``~/.openpup/peers.json``.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openpup.peer")


@dataclass
class Peer:
    """One trusted peer pup."""

    name: str  # human-readable name (e.g. 'alice-pup')
    endpoint: str = ""  # base URL of the peer's OpenPup
    public_key: str = ""  # HMAC verification key

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "Peer":
        return cls(**raw)


def _file() -> Path:
    from openpup.config import config_home

    return Path(os.environ.get("OPENPUP_PEERS_FILE", config_home() / "peers.json"))


def _load() -> dict[str, Peer]:
    p = _file()
    if not p.exists():
        return {}
    try:
        return {pe["name"]: Peer.from_dict(pe) for pe in json.loads(p.read_text()).get("peers", [])}
    except Exception:
        return {}


def _save(peers: dict[str, Peer]) -> None:
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"peers": [pe.to_dict() for pe in peers.values()]}, indent=2))


def add(peer: Peer) -> Peer:
    peers = _load()
    peers[peer.name] = peer
    _save(peers)
    return peer


def list_all() -> list[Peer]:
    return sorted(_load().values(), key=lambda p: p.name)


def remove(name: str) -> bool:
    peers = _load()
    if name not in peers:
        return False
    del peers[name]
    _save(peers)
    return True


def handoff(peer: Peer, task: str) -> dict:
    """Pretend to hand off a task. v1 returns a synthetic ack.

    A real implementation would HMAC-sign the payload and POST to
    ``peer.endpoint``.
    """
    logger.info("would hand off %r to %r (%d chars)", peer.name, peer.endpoint, len(task))
    return {"ok": True, "peer": peer.name, "ack": "received", "chars": len(task)}
