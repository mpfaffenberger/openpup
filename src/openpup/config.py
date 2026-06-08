"""OpenPup configuration.

A single pydantic-settings model that reads from environment variables (and a
``.env`` file if present). Every platform/feature is opt-in via an ``*_ENABLED``
flag so OpenPup runs with whatever subset you configure.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env once at import so plain os.environ readers (e.g. the kennel) see it.
load_dotenv()


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(path))).resolve()


class Settings(BaseSettings):
    """Runtime configuration for an OpenPup instance."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ---- Identity & agent ------------------------------------------------
    name: str = Field("OpenPup", alias="OPENPUP_NAME")
    agent: str = Field("code-puppy", alias="OPENPUP_AGENT")
    model: Optional[str] = Field(None, alias="OPENPUP_MODEL")
    reflection_model: Optional[str] = Field(None, alias="OPENPUP_REFLECTION_MODEL")

    # ---- Owner -----------------------------------------------------------
    owner_address: Optional[str] = Field(None, alias="OPENPUP_OWNER_ADDRESS")

    # ---- Memory ----------------------------------------------------------
    kennel_root: str = Field("~/.openpup/kennel", alias="PUPPY_KENNEL_ROOT")

    # ---- Heartbeat -------------------------------------------------------
    heartbeat_enabled: bool = Field(True, alias="OPENPUP_HEARTBEAT_ENABLED")
    heartbeat_interval: int = Field(900, alias="OPENPUP_HEARTBEAT_INTERVAL")
    heartbeat_jitter: int = Field(120, alias="OPENPUP_HEARTBEAT_JITTER")
    heartbeat_behaviors: str = Field(
        "reflect,outreach,routines,inbound", alias="OPENPUP_HEARTBEAT_BEHAVIORS"
    )
    quiet_hours: Optional[str] = Field("23-7", alias="OPENPUP_QUIET_HOURS")
    outreach_max_per_day: int = Field(4, alias="OPENPUP_OUTREACH_MAX_PER_DAY")

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
    email_poll_seconds: int = Field(60, alias="EMAIL_POLL_SECONDS")

    # ---- SMS -------------------------------------------------------------
    sms_enabled: bool = Field(False, alias="SMS_ENABLED")
    twilio_account_sid: Optional[str] = Field(None, alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: Optional[str] = Field(None, alias="TWILIO_AUTH_TOKEN")
    twilio_from_number: Optional[str] = Field(None, alias="TWILIO_FROM_NUMBER")

    # ---- Derived helpers -------------------------------------------------
    @property
    def kennel_path(self) -> Path:
        return _expand(self.kennel_root)

    @property
    def state_dir(self) -> Path:
        d = _expand("~/.openpup")
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
        """Return (platform, channel) the owner can be reached at, or None."""
        if not self.owner_address or ":" not in self.owner_address:
            return None
        platform, channel = self.owner_address.split(":", 1)
        return platform.strip(), channel.strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    # Point the kennel at OpenPup's root before any code-puppy import reads it.
    settings = Settings()
    os.environ.setdefault("PUPPY_KENNEL_ROOT", str(settings.kennel_path))
    return settings
