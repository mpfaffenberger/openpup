"""Per-platform group-chat policies.

A "group" here means anything that isn't a 1:1 DM: Telegram groups / channels,
Discord servers, Slack channels, etc. Each platform has a :class:`GroupPolicy`
that decides whether OpenPup should respond to a message in that context.

Three orthogonal settings (combined into one decision):

* **require_mention**: if True, only reply when the message ``@mentions`` the
  bot or contains the bot's ``require_keyword``. Default False (always reply).
* **require_keyword**: a literal substring the message must contain (e.g. the
  bot's name). When set, counts as a "mention" even without a true @mention.
* **mode**: ``open`` (always reply), ``silent`` (never reply), or ``smart``
  (default; obeys require_mention + require_keyword).

State lives in ``~/.openpup/group_policies.json`` (separate from access.json
so we can change group policy without touching owner / allowlist settings).
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("openpup.group_policy")

# Mode values
MODE_SMART = "smart"  # obey require_mention/require_keyword
MODE_OPEN = "open"  # always reply (legacy default)
MODE_SILENT = "silent"  # never reply to groups

MODES = (MODE_SMART, MODE_OPEN, MODE_SILENT)


@dataclass
class GroupPolicy:
    platform: str
    mode: str = MODE_SMART
    require_mention: bool = True
    require_keyword: str = ""  # empty = no keyword required
    bot_user_ids: list[str] = field(default_factory=list)  # bot's user IDs on this platform

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "GroupPolicy":
        return cls(
            platform=str(raw["platform"]),
            mode=str(raw.get("mode", MODE_SMART)),
            require_mention=bool(raw.get("require_mention", True)),
            require_keyword=str(raw.get("require_keyword", "")),
            bot_user_ids=list(raw.get("bot_user_ids", []) or []),
        )


@dataclass
class GroupDecision:
    allowed: bool
    reason: str = ""

    @classmethod
    def allow(cls, reason: str = "") -> "GroupDecision":
        return cls(allowed=True, reason=reason)

    @classmethod
    def deny(cls, reason: str) -> "GroupDecision":
        return cls(allowed=False, reason=reason)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
class GroupPolicyStore:
    """Persists per-platform GroupPolicy to JSON."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, GroupPolicy]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text())
        except Exception:
            logger.exception("could not parse group policy file %s", self.path)
            return {}
        return {p: GroupPolicy.from_dict(d) for p, d in raw.get("policies", {}).items()}

    def save(self, policies: dict[str, GroupPolicy]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"policies": {p: pol.to_dict() for p, pol in policies.items()}}
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True))

    def get(self, platform: str, default: Optional[GroupPolicy] = None) -> GroupPolicy:
        policies = self.load()
        return policies.get(platform, default or GroupPolicy(platform=platform))

    def upsert(self, policy: GroupPolicy) -> None:
        policies = self.load()
        policies[policy.platform] = policy
        self.save(policies)

    def remove(self, platform: str) -> bool:
        policies = self.load()
        if platform in policies:
            del policies[platform]
            self.save(policies)
            return True
        return False


def default_store_path() -> Path:
    from openpup.config import config_home

    return config_home() / "group_policies.json"


def get_store() -> GroupPolicyStore:
    """Shared store; honors OPENPUP_HOME via config_home()."""
    return GroupPolicyStore(default_store_path())


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------
def should_reply(
    env,  # Envelope (avoid circular import)
    policy: GroupPolicy,
    bot_user_id: Optional[str] = None,
) -> GroupDecision:
    """Decide whether the agent should respond to this envelope.

    Inputs come from the envelope's chat_type / mentions / text. The bot's own
    user id is optional — when the platform adapter doesn't provide one we
    fall back to require_keyword only.
    """
    # DMs always allowed.
    if getattr(env, "chat_type", "dm") != "group":
        return GroupDecision.allow("dm_or_unknown")

    if policy.mode == MODE_SILENT:
        return GroupDecision.deny("group policy is 'silent' for this platform")
    if policy.mode == MODE_OPEN:
        return GroupDecision.allow("group policy is 'open' (always reply)")

    # MODE_SMART: apply mention / keyword gates.
    mentions = set(getattr(env, "mentions", []) or [])
    if bot_user_id:
        mentions.add(str(bot_user_id))
    if policy.bot_user_ids:
        mentions.update(str(x) for x in policy.bot_user_ids)

    text = (env.text or "").strip()
    if policy.require_mention and mentions:
        if any(m in mentions for m in (getattr(env, "mentions", []) or []) if m):
            return GroupDecision.allow("explicit @mention")
        # bot id was the only "mention"
        if bot_user_id and any(m == str(bot_user_id) for m in (getattr(env, "mentions", []) or [])):
            return GroupDecision.allow("bot user mentioned")
    if policy.require_keyword and policy.require_keyword.lower() in text.lower():
        return GroupDecision.allow(f"keyword {policy.require_keyword!r} present")
    if policy.require_mention:
        return GroupDecision.deny("no mention / keyword in group; require_mention=true")
    # No require_mention + no keyword required -> allow by default.
    return GroupDecision.allow("no gate failed")
