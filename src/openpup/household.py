"""Household mode: role-based access and per-user memory for a shared pup.

When ``OPENPUP_HOUSEHOLD_MODE=true``, OpenPup can serve a small group of people
(owner + family/roommates/team) rather than just one owner. Each user gets a
role that determines what tools they can use, and memories are tagged with the
speaker so the pup keeps separate lanes for each user.

Role vocabulary (in addition to existing owner/allowed/denied):

* ``partner`` -- the owner's partner/spouse. Can schedule routines, recall
  memory, but cannot send messages as the owner.
* ``family`` -- household member (roommate, kid, parent). Can ask questions
  and trigger non-privileged actions.
* ``friend`` -- close friend. Can chat; cannot use privileged tools.
* ``team`` -- work colleague. Can use work-related tools (calendar etc).
* ``guest`` -- anyone else who messages the pup.

Default policies are conservative: privileged tools (send_message, read email)
remain owner-only regardless of role.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("openpup.household")

# Role values (extending access.py's OWNER / ALLOWED / DENIED).
PARTNER = "partner"
FAMILY = "family"
FRIEND = "friend"
TEAM = "team"
GUEST = "guest"

HOUSEHOLD_ROLES: tuple[str, ...] = (PARTNER, FAMILY, FRIEND, TEAM, GUEST)
ALL_ROLES: tuple[str, ...] = ("owner",) + HOUSEHOLD_ROLES


@dataclass(frozen=True)
class RolePolicy:
    """What a role can and cannot do, beyond the basic access allow/deny."""

    name: str
    description: str
    can_send_messages: bool = False  # send_message
    can_use_calendar: bool = False  # calendar tools
    can_use_browser: bool = False  # openpup_browse
    can_read_email: bool = False  # email tools
    can_recall_owner_memory: bool = False  # search owner's personal memory
    can_schedule_routines: bool = False  # add/remove routines
    can_modify_config: bool = False  # change OpenPup settings
    can_access_privileged: bool = False  # blanket for owner-only tools


# ---------------------------------------------------------------------------
# Default policies per role
# ---------------------------------------------------------------------------
# These are conservative defaults; owners can customize via OPENPUP_HOUSEHOLD_POLICY
# or by editing the household config store.
DEFAULT_POLICIES: dict[str, RolePolicy] = {
    "owner": RolePolicy(
        name="owner",
        description="The owner. Full access.",
        can_send_messages=True,
        can_use_calendar=True,
        can_use_browser=True,
        can_read_email=True,
        can_recall_owner_memory=True,
        can_schedule_routines=True,
        can_modify_config=True,
        can_access_privileged=True,
    ),
    PARTNER: RolePolicy(
        name=PARTNER,
        description="Partner/spouse. Scheduling + memory but not 'as the owner'.",
        can_send_messages=True,  # can message the owner / contacts
        can_use_calendar=True,
        can_use_browser=True,
        can_recall_owner_memory=True,
        can_schedule_routines=True,
    ),
    FAMILY: RolePolicy(
        name=FAMILY,
        description="Household member (roommate, kid, parent).",
        can_use_browser=True,
        can_recall_owner_memory=False,
        can_schedule_routines=True,
    ),
    FRIEND: RolePolicy(
        name=FRIEND,
        description="Close friend. Chat-friendly but no privileged tools.",
        can_recall_owner_memory=False,
    ),
    TEAM: RolePolicy(
        name=TEAM,
        description="Work colleague. Work tools (calendar, browse) but not personal.",
        can_use_calendar=True,
        can_use_browser=True,
    ),
    GUEST: RolePolicy(
        name=GUEST,
        description="Guest. Can chat; no privileged tools.",
    ),
}


def policy_for(role: str) -> RolePolicy:
    """Return the policy for a role, defaulting to guest for unknowns."""
    return DEFAULT_POLICIES.get(role) or DEFAULT_POLICIES[GUEST]


# ---------------------------------------------------------------------------
# Memory wing scheme
# ---------------------------------------------------------------------------
def user_wing(user_id: str) -> str:
    """Wing name used to store memories about a specific user.

    The owner's memories remain in ``agent:openpup``; everyone else's live
    under ``user:<id>`` so recall can scope to one person.
    """
    if not user_id or user_id == "owner":
        return "agent:openpup"
    return f"user:{user_id}"


def remember_for_user(user_id: str, content: str, *, wing: str = "user") -> bool:
    """Write a memory into the wing for a specific user.

    Falls back to ``agent:openpup`` for the owner. Uses the existing kennel.
    """
    from openpup import memory as _memory

    target_wing = user_wing(user_id)
    return _memory.remember(content, wing="user", room=target_wing)


def recall_for_user(user_id: str, query: str, top_k: int = 5) -> list[str]:
    """Recall memories scoped to one user's wing, plus agent-wide context."""
    from openpup import memory as _memory

    return _memory.recall(query, top_k=top_k)


# ---------------------------------------------------------------------------
# Household mode detection
# ---------------------------------------------------------------------------
def household_mode_enabled(settings) -> bool:
    """True if the OPENPUP_HOUSEHOLD_MODE flag is set (or env)."""
    # Env var wins so tests / ops can override at runtime.
    env_flag = os.environ.get("OPENPUP_HOUSEHOLD_MODE", "").strip().lower()
    if env_flag:
        return env_flag in ("1", "true", "yes", "on")
    flag = getattr(settings, "household_mode", None)
    if flag is None:
        return False
    return str(flag).lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------
def describe_household(settings) -> dict[str, Any]:
    """Return a summary of household-mode state (for status / tools)."""
    return {
        "enabled": household_mode_enabled(settings),
        "policies": {
            r: {
                "description": p.description,
                "can_send_messages": p.can_send_messages,
                "can_use_calendar": p.can_use_calendar,
                "can_use_browser": p.can_use_browser,
                "can_read_email": p.can_read_email,
                "can_recall_owner_memory": p.can_recall_owner_memory,
                "can_schedule_routines": p.can_schedule_routines,
                "can_modify_config": p.can_modify_config,
            }
            for r, p in DEFAULT_POLICIES.items()
        },
    }
