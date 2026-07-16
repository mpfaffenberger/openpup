"""Tests for the household mode module.

Covers default role policies, memory wing scheme, and the household-mode
detection helper.
"""

from openpup.household import (
    ALL_ROLES,
    DEFAULT_POLICIES,
    FAMILY,
    FRIEND,
    GUEST,
    HOUSEHOLD_ROLES,
    PARTNER,
    TEAM,
    describe_household,
    household_mode_enabled,
    policy_for,
    user_wing,
)


class TestRoleDefaults:
    def test_all_roles_have_policies(self):
        for r in ALL_ROLES:
            assert r in DEFAULT_POLICIES, f"missing policy for {r}"

    def test_household_roles_listed(self):
        assert HOUSEHOLD_ROLES == (PARTNER, FAMILY, FRIEND, TEAM, GUEST)

    def test_owner_can_do_everything(self):
        p = policy_for("owner")
        assert p.can_send_messages
        assert p.can_use_calendar
        assert p.can_use_browser
        assert p.can_read_email
        assert p.can_schedule_routines
        assert p.can_modify_config
        assert p.can_access_privileged

    def test_partner_can_send_and_schedule(self):
        p = policy_for(PARTNER)
        assert p.can_send_messages
        assert p.can_schedule_routines
        assert p.can_use_calendar
        # But cannot modify config.
        assert not p.can_modify_config

    def test_family_can_use_browser_and_routines(self):
        p = policy_for(FAMILY)
        assert p.can_use_browser
        assert p.can_schedule_routines
        # But not calendar (work tool).
        assert not p.can_use_calendar

    def test_friend_cannot_use_tools(self):
        p = policy_for(FRIEND)
        assert not p.can_send_messages
        assert not p.can_use_calendar
        assert not p.can_use_browser

    def test_team_can_use_calendar_browser(self):
        p = policy_for(TEAM)
        assert p.can_use_calendar
        assert p.can_use_browser
        # But not personal tools.
        assert not p.can_send_messages
        assert not p.can_read_email

    def test_guest_minimal(self):
        p = policy_for(GUEST)
        assert not p.can_send_messages
        assert not p.can_use_calendar
        assert not p.can_use_browser
        assert not p.can_read_email
        assert not p.can_schedule_routines
        assert not p.can_modify_config


class TestPolicyFor:
    def test_unknown_role_falls_back_to_guest(self):
        p = policy_for("random_string")
        assert p.name == GUEST

    def test_known_role_returns_its_own(self):
        p = policy_for(FAMILY)
        assert p.name == FAMILY


class TestUserWing:
    def test_owner_returns_agent_wing(self):
        assert user_wing("owner") == "agent:openpup"

    def test_empty_user_returns_agent_wing(self):
        assert user_wing("") == "agent:openpup"

    def test_other_user_gets_user_wing(self):
        assert user_wing("alice") == "user:alice"
        assert user_wing("bob") == "user:bob"


class TestHouseholdMode:
    def test_disabled_by_default(self):
        class S:
            household_mode = False

        assert household_mode_enabled(S()) is False

    def test_enabled_via_settings(self):
        class S:
            household_mode = True

        assert household_mode_enabled(S()) is True

    def test_enabled_via_env(self, monkeypatch):
        class S:
            household_mode = False

        monkeypatch.setenv("OPENPUP_HOUSEHOLD_MODE", "true")
        assert household_mode_enabled(S()) is True


class TestDescribeHousehold:
    def test_describe_when_off(self):
        class S:
            household_mode = False

        info = describe_household(S())
        assert info["enabled"] is False
        # Still describes policies (helpful for preview).
        assert "owner" in info["policies"]

    def test_describe_when_on(self):
        class S:
            household_mode = True

        info = describe_household(S())
        assert info["enabled"] is True
        for role in ALL_ROLES:
            assert role in info["policies"]
