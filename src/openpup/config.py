"""OpenPup configuration.

A single pydantic-settings model that reads from environment variables (and a
``.env`` file if present). Every platform/feature is opt-in via an ``*_ENABLED``
flag so OpenPup runs with whatever subset you configure.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env once at import so plain os.environ readers (e.g. the kennel) see it.
# override=True ensures .env values win over inherited-but-empty env vars
# (e.g. a parent process exporting OPENPUP_OWNER_ADDRESS="").
load_dotenv(override=True)

def _expand(path: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(path))).resolve()


#: Default home for ALL OpenPup state. Override with the OPENPUP_HOME env var.
DEFAULT_HOME = "~/.openpup"


def config_home() -> Path:
    """OpenPup's config/state directory (single source of truth).

    Resolution order: ``OPENPUP_HOME`` env var, then :data:`DEFAULT_HOME`.
    Tests can monkeypatch this function; anything computed lazily (state_dir,
    SOUL.md, skills, ...) follows. Import-time wiring (the kennel root and
    code-puppy's own dirs below) is snapshotted once, so to move *those* set
    ``OPENPUP_HOME`` before importing openpup.
    """
    return _expand(os.environ.get("OPENPUP_HOME") or DEFAULT_HOME)


# IMPORTANT: code-puppy's puppy_kennel reads PUPPY_KENNEL_ROOT at *import time*
# and does NOT expand ``~``. ``load_dotenv`` leaves a literal "~/.openpup/kennel"
# in the environment, which would resolve to a broken relative path -- or, if
# read before we set it, fall back to code-puppy's OWN kennel (~/.code_puppy/
# kennel), silently sharing memory. So we normalize it to an absolute path here,
# at OpenPup-config import (which happens before the kennel is ever imported),
# defaulting to OpenPup's own kennel so the two stay separate.
_kennel_root = os.environ.get("PUPPY_KENNEL_ROOT") or str(config_home() / "kennel")
os.environ["PUPPY_KENNEL_ROOT"] = str(_expand(_kennel_root))


def _redirect_code_puppy_dirs() -> None:
    """Point the code-puppy SDK's dirs at OpenPup's home, not ~/.code_puppy.

    code_puppy.config snapshots CONFIG_DIR/DATA_DIR/CACHE_DIR/STATE_DIR from
    the XDG_* env vars at *import time* (appending "code_puppy"). We import it
    eagerly inside a temporary XDG override so its files land under
    ``<config_home>/code_puppy/`` -- then restore the env, so agent-spawned
    subprocesses never inherit hijacked XDG vars.
    """
    home = str(config_home())
    xdg_vars = ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME")
    saved = {v: os.environ.get(v) for v in xdg_vars}
    try:
        for v in xdg_vars:
            os.environ[v] = home
        import code_puppy.config  # noqa: F401  (snapshots dirs at import)
    finally:
        for v, old in saved.items():
            if old is None:
                os.environ.pop(v, None)
            else:
                os.environ[v] = old


_redirect_code_puppy_dirs()


class Settings(BaseSettings):
    """Runtime configuration for an OpenPup instance."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ---- Identity & agent ------------------------------------------------
    name: str = Field("OpenPup", alias="OPENPUP_NAME")
    # "auto" = generate a first-class agent named after the pup (OPENPUP_NAME),
    # carrying the full code-puppy toolset. Set an explicit code-puppy agent
    # name to drive that instead.
    agent: str = Field("auto", alias="OPENPUP_AGENT")
    model: Optional[str] = Field(None, alias="OPENPUP_MODEL")
    reflection_model: Optional[str] = Field(None, alias="OPENPUP_REFLECTION_MODEL")
    # Universal Constructor: let the agent build its own tools at runtime.
    universal_constructor: bool = Field(True, alias="OPENPUP_UNIVERSAL_CONSTRUCTOR")
    # Persona presets used to generate SOUL.md (the editable identity).
    personality: str = Field("warm_loyal_sassy", alias="OPENPUP_PERSONALITY")
    proactivity: str = Field("relentless", alias="OPENPUP_PROACTIVITY")

    # ---- Owner -----------------------------------------------------------
    # Primary owner address (default destination for proactive outreach).
    owner_address: Optional[str] = Field(None, alias="OPENPUP_OWNER_ADDRESS")
    # Additional owner addresses across platforms, comma-separated. The owner is
    # recognized (and reachable) at ANY of these, e.g. "telegram:123,sms:+1555".
    owner_addresses_raw: str = Field("", alias="OPENPUP_OWNER_ADDRESSES")

    @field_validator("owner_address", mode="before")
    @classmethod
    def _empty_owner_is_none(cls, v: object) -> object:
        """Treat blank strings as None so an inherited empty env var doesn't
        silently disable owner features."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    # ---- Outbound comms governance --------------------------------------
    # open | contacts | owner_only -- who the agent may message.
    send_policy: str = Field("open", alias="OPENPUP_SEND_POLICY")
    # Per-platform outbound message cap per minute (runaway/spam guard).
    send_rate_per_min: int = Field(10, alias="OPENPUP_SEND_RATE_PER_MIN")

    # ---- Inbound security --------------------------------------------------
    # Scan NON-owner messages for prompt-injection patterns and append an
    # advisory to the agent's per-message context. Advisory only, never blocks;
    # owner messages are never scanned.
    threat_guard: bool = Field(True, alias="OPENPUP_THREAT_GUARD")
    # Seconds to wait for the owner to answer an approval request
    # (security.approval). Expired requests are denied by default.
    approval_timeout_s: int = Field(300, alias="OPENPUP_APPROVAL_TIMEOUT_S")

    # ---- Memory ----------------------------------------------------------
    # Default is config_home()/kennel; the import-time normalization above
    # always sets the env var, so this fallback rarely fires.
    kennel_root: str = Field("", alias="PUPPY_KENNEL_ROOT")

    # ---- Heartbeat -------------------------------------------------------
    heartbeat_enabled: bool = Field(True, alias="OPENPUP_HEARTBEAT_ENABLED")
    heartbeat_interval: int = Field(900, alias="OPENPUP_HEARTBEAT_INTERVAL")
    heartbeat_jitter: int = Field(120, alias="OPENPUP_HEARTBEAT_JITTER")
    # How often to check the scheduler + poll inbound adapters. This is
    # decoupled from the (slow) reflect/outreach heartbeat so reminders fire
    # promptly instead of waiting up to a full heartbeat interval.
    scheduler_interval: int = Field(30, alias="OPENPUP_SCHEDULER_INTERVAL")
    heartbeat_behaviors: str = Field(
        "reflect,outreach,routines,inbound", alias="OPENPUP_HEARTBEAT_BEHAVIORS"
    )
    quiet_hours: Optional[str] = Field("23-7", alias="OPENPUP_QUIET_HOURS")
    outreach_max_per_day: int = Field(4, alias="OPENPUP_OUTREACH_MAX_PER_DAY")
    # Briefings: RSS / Atom news digest delivered via the heartbeat.
    briefing_feeds: str = Field("", alias="OPENPUP_BRIEFING_FEEDS")
    briefing_interval_hours: int = Field(12, alias="OPENPUP_BRIEFING_INTERVAL_HOURS")
    # Household mode: serve a small group instead of just the owner.
    household_mode: bool = Field(False, alias="OPENPUP_HOUSEHOLD_MODE")
    # Curator: skill-shelf maintenance (opt-in via OPENPUP_HEARTBEAT_BEHAVIORS).
    curator_interval_hours: int = Field(168, alias="OPENPUP_CURATOR_INTERVAL_HOURS")
    curator_stale_after_days: int = Field(30, alias="OPENPUP_CURATOR_STALE_AFTER_DAYS")
    curator_archive_after_days: int = Field(90, alias="OPENPUP_CURATOR_ARCHIVE_AFTER_DAYS")

    # ---- Webhook server --------------------------------------------------
    web_enabled: bool = Field(False, alias="OPENPUP_WEB_ENABLED")
    web_host: str = Field("0.0.0.0", alias="OPENPUP_WEB_HOST")
    web_port: int = Field(8080, alias="OPENPUP_WEB_PORT")
    webhook_secret: Optional[str] = Field(None, alias="OPENPUP_WEBHOOK_SECRET")

    # ---- Discord ---------------------------------------------------------
    discord_enabled: bool = Field(False, alias="DISCORD_ENABLED")
    discord_bot_token: Optional[str] = Field(None, alias="DISCORD_BOT_TOKEN")

    # ---- Telegram --------------------------------------------------------
    telegram_enabled: bool = Field(False, alias="TELEGRAM_ENABLED")
    telegram_bot_token: Optional[str] = Field(None, alias="TELEGRAM_BOT_TOKEN")

    # ---- WhatsApp --------------------------------------------------------
    whatsapp_enabled: bool = Field(False, alias="WHATSAPP_ENABLED")
    whatsapp_phone_number_id: Optional[str] = Field(None, alias="WHATSAPP_PHONE_NUMBER_ID")
    whatsapp_access_token: Optional[str] = Field(None, alias="WHATSAPP_ACCESS_TOKEN")
    whatsapp_verify_token: Optional[str] = Field(None, alias="WHATSAPP_VERIFY_TOKEN")

    # ---- Email -----------------------------------------------------------
    email_enabled: bool = Field(False, alias="EMAIL_ENABLED")
    email_imap_host: Optional[str] = Field(None, alias="EMAIL_IMAP_HOST")
    email_imap_port: int = Field(993, alias="EMAIL_IMAP_PORT")
    email_smtp_host: Optional[str] = Field(None, alias="EMAIL_SMTP_HOST")
    email_smtp_port: int = Field(587, alias="EMAIL_SMTP_PORT")
    email_username: Optional[str] = Field(None, alias="EMAIL_USERNAME")
    email_password: Optional[str] = Field(None, alias="EMAIL_PASSWORD")
    # Where openpup_delete_email moves mail by default (reversible). When set
    # (the default), deletes are a MOVE to this folder; pass permanent=True at
    # the tool to expunge instead. Set to "" to make plain deletes permanent.
    # Folder names vary by provider (e.g. Gmail uses "[Gmail]/Trash").
    email_trash_folder: Optional[str] = Field("Trash", alias="EMAIL_TRASH_FOLDER")
    # Email is a read-only sensor (no inbound polling); there is no poll
    # interval. Use a scheduled openpup_check_email job to watch the inbox.

    # ---- iMessage (macOS native) ----------------------------------------
    imessage_enabled: bool = Field(False, alias="IMESSAGE_ENABLED")
    imessage_poll_seconds: int = Field(5, alias="IMESSAGE_POLL_SECONDS")
    imessage_db_path: str = Field("~/Library/Messages/chat.db", alias="IMESSAGE_DB_PATH")

    # ---- SMS -------------------------------------------------------------
    sms_enabled: bool = Field(False, alias="SMS_ENABLED")
    twilio_account_sid: Optional[str] = Field(None, alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: Optional[str] = Field(None, alias="TWILIO_AUTH_TOKEN")
    twilio_from_number: Optional[str] = Field(None, alias="TWILIO_FROM_NUMBER")

    # ---- Derived helpers -------------------------------------------------
    @property
    def kennel_path(self) -> Path:
        if self.kennel_root:
            return _expand(self.kennel_root)
        return config_home() / "kennel"

    @property
    def state_dir(self) -> Path:
        d = config_home()
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def behaviors(self) -> List[str]:
        return [b.strip() for b in self.heartbeat_behaviors.split(",") if b.strip()]

    @property
    def quiet_window(self) -> Optional[Tuple[int, int]]:
        """Return (start_hour, end_hour) or None."""
        if not self.quiet_hours:
            return None
        try:
            start, end = self.quiet_hours.split("-")
            return int(start), int(end)
        except (ValueError, AttributeError):
            return None

    def owner(self) -> Optional[Tuple[str, str]]:
        """Return (platform, channel) of the PRIMARY owner address, or None."""
        if not self.owner_address or ":" not in self.owner_address:
            return None
        platform, channel = self.owner_address.split(":", 1)
        return platform.strip(), channel.strip()

    @property
    def owner_addresses(self) -> List[str]:
        """All addresses that count as the owner (primary + extras), deduped."""
        out: List[str] = []
        if self.owner_address:
            out.append(self.owner_address.strip())
        for a in self.owner_addresses_raw.split(","):
            a = a.strip()
            if a and a not in out:
                out.append(a)
        return out

    def owner_for_platform(self, platform: str) -> Optional[str]:
        """Return the owner address on a given platform, if known."""
        for a in self.owner_addresses:
            if ":" in a and a.split(":", 1)[0].strip() == platform:
                return a
        return None


logger = logging.getLogger("openpup.config")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Config lives in a SQLite store (``config_home()/config.db``). We run a
    one-time ``.env`` migration, then inject the stored values into
    ``os.environ`` so Settings reads the DB as the source of truth. The store
    is best-effort: any failure falls back to plain env/.env loading so the
    pup always boots.
    """
    try:
        from openpup.config_store import get_config_store

        store = get_config_store()
        store.bootstrap()
        store.apply_to_environ()
    except Exception:
        logger.exception("config store unavailable; using env/.env only")
    settings = Settings()
    # Force the kennel at OpenPup's (expanded, absolute) root. Force-set rather
    # than setdefault so a literal-tilde value from .env can't win.
    os.environ["PUPPY_KENNEL_ROOT"] = str(settings.kennel_path)
    return settings
