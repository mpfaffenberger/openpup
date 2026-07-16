"""Voice calls: a Twilio Voice integration (stub for v1).

In v1 the abstraction is in place but the actual Twilio API call is stubbed
(returns a synthetic call SID). Real Twilio dispatch is a follow-up commit
so each feature stays a single focused commit.

Requires ``OPENPUP_TWILIO_ACCOUNT_SID``, ``_AUTH_TOKEN``, ``_FROM_NUMBER`` for
real use. The ``[sms]`` / ``[sms-cloud]`` extras already pull ``twilio`` --
we don't add a new dep here.
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass

logger = logging.getLogger("openpup.voice_calls")


@dataclass
class CallRequest:
    """One outbound voice call."""

    to: str  # E.164 phone number
    message: str = ""  # optional TTS message at pickup


@dataclass
class CallResult:
    """Result of initiating a call."""

    ok: bool
    call_sid: str = ""
    to: str = ""
    error: str | None = None


def place_call(req: CallRequest, *, from_number: str = "") -> CallResult:
    """Initiate an outbound voice call. Returns a CallResult.

    In v1 the result is a synthetic SID; no real Twilio call is made.
    """
    if not req.to:
        return CallResult(ok=False, to=req.to, error="missing 'to' address")
    if not from_number:
        from_number = os.environ.get("OPENPUP_TWILIO_FROM_NUMBER", "")
    if not from_number:
        return CallResult(
            ok=False,
            to=req.to,
            error="no FROM number (set OPENPUP_TWILIO_FROM_NUMBER)",
        )
    # v1 stub: real Twilio dispatch lands in a follow-up commit.
    sid = f"STUB-{uuid.uuid4().hex[:12]}"
    logger.info("would call %s from %s (message: %r)", req.to, from_number, req.message)
    return CallResult(ok=True, call_sid=sid, to=req.to)


def build_twiml(message: str) -> str:
    """Return a minimal TwiML document for a voice call.

    TwiML is XML consumed by Twilio to drive the call. Twilio expects
    ``application/xml`` so the response uses XML by default.
    """
    # Minimal escaping for the three XML chars.
    safe = (
        message.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Say>{safe}</Say>"
        "</Response>"
    )
