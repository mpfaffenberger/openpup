"""Headless harness around the code-puppy agent SDK.

This is the seam that lets OpenPup use code-puppy as a *library*: it boots the
plugin system (which brings in puppy_kennel memory), loads an agent, and runs
prompts programmatically — no TUI, no prompt-toolkit loop.

Per-conversation history is kept here, keyed by ``platform:channel`` address,
so each Discord channel / Telegram chat / email thread has its own context.
The underlying ``BaseAgent`` holds a single ``_message_history`` list, so we
swap histories in/out under a lock around each run.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("openpup.agent_host")

# Substrings / type names that indicate a transient network/streaming hiccup
# with the model API (worth retrying) rather than a real logic error.
_TRANSIENT_SIGNATURES = (
    "peer closed connection",
    "incomplete chunked read",
    "remoteprotocolerror",
    "readerror",
    "connecterror",
    "connectionerror",
    "readtimeout",
    "connecttimeout",
    "connection reset",
    "server disconnected",
    "serverdisconnected",
    "apiconnectionerror",
    "overloaded",
    "internalservererror",
    "502",
    "503",
    "529",
    "streamed response ended",
)


def _is_transient(exc: BaseException) -> bool:
    """True if any error in the cause/context/group chain looks transient."""
    seen: List[BaseException] = []

    def collect(e: Optional[BaseException]) -> None:
        if e is None or e in seen:
            return
        seen.append(e)
        collect(getattr(e, "__cause__", None))
        collect(getattr(e, "__context__", None))
        for sub in getattr(e, "exceptions", None) or []:  # ExceptionGroup
            collect(sub)

    collect(exc)
    for e in seen:
        blob = f"{type(e).__name__} {e}".lower()
        if any(sig in blob for sig in _TRANSIENT_SIGNATURES):
            return True
    return False


class AgentHost:
    """Boots and drives a code-puppy agent for OpenPup."""

    def __init__(
        self,
        agent_name: str = "auto",
        default_model: Optional[str] = None,
        universal_constructor: bool = True,
        max_retries: int = 3,
    ) -> None:
        self.agent_name = agent_name
        self.default_model = default_model
        self.universal_constructor = universal_constructor
        self.max_retries = max_retries
        self._agent: Any = None
        self._lock = asyncio.Lock()
        # address -> message history list
        self._histories: Dict[str, List[Any]] = {}

    # ---- lifecycle -------------------------------------------------------
    async def boot(self) -> None:
        """Load plugins (kennel et al.), fire startup hooks, load the agent."""
        from code_puppy.agents.agent_manager import load_agent
        from code_puppy.callbacks import register_callback
        from code_puppy.plugins import load_plugin_callbacks

        load_plugin_callbacks()

        # Give the agent OpenPup's own tools + a hermes-style layered identity
        # so it actually uses its integrations and works agentically instead of
        # acting like plain code-puppy. Same hook pattern the kennel uses.
        from openpup import agent_tools, agentic, browser_tools, prompting, schedule_tools

        prompting.ensure_templates()

        register_callback("register_tools", agent_tools.register_tools_callback)
        register_callback("register_agent_tools", agent_tools.advertise_tools)
        # Agentic task-list (todo) tool, ported from hermes.
        register_callback("register_tools", agentic.register_tools_callback)
        register_callback("register_agent_tools", agentic.advertise_tools)
        # Scheduling tools: reminders + cron-like jobs bound to the scheduler.
        register_callback("register_tools", schedule_tools.register_tools_callback)
        register_callback("register_agent_tools", schedule_tools.advertise_tools)
        # Stealth browser (CloakBrowser): owner-only, SSRF-guarded page fetches.
        register_callback("register_tools", browser_tools.register_tools_callback)
        register_callback("register_agent_tools", browser_tools.advertise_tools)
        # Layered system prompt (SOUL + agentic guidance + user/memory snapshots).
        register_callback("load_prompt", prompting.build_system_prompt)

        # Universal Constructor: let the agent forge its own tools at runtime.
        # This is a core code-puppy capability gated by its own config flag;
        # we flip it to match the OpenPup setting, and advertise the tool below.
        try:
            from code_puppy.config import set_universal_constructor_enabled

            set_universal_constructor_enabled(self.universal_constructor)
        except Exception:
            logger.debug("could not set universal_constructor flag", exc_info=True)

        try:
            from code_puppy import callbacks

            await callbacks.on_startup()
        except Exception:  # startup hooks must never block boot
            logger.debug("startup hooks raised (non-fatal)", exc_info=True)

        # "auto" generates a first-class agent named after the pup (hermes
        # style) instead of impersonating stock code-puppy; explicit names
        # pass straight through.
        from openpup.agent_def import resolve_agent_name

        effective_name = resolve_agent_name(self.agent_name)
        self._agent = load_agent(effective_name)
        logger.info("AgentHost booted agent '%s'", effective_name)

    async def shutdown(self) -> None:
        try:
            from code_puppy import callbacks

            await callbacks.on_shutdown()
        except Exception:
            logger.debug("shutdown hooks raised (non-fatal)", exc_info=True)

    # ---- running ---------------------------------------------------------
    async def run(
        self,
        prompt: str,
        *,
        conversation: str = "default",
        model: Optional[str] = None,
        keep_history: bool = True,
    ) -> str:
        """Run ``prompt`` in a named conversation and return the response text.

        ``conversation`` is typically an envelope address (``platform:channel``)
        so separate chats keep separate context. ``model`` overrides the model
        for just this run (used by cheap reflection ticks).
        """
        if self._agent is None:
            raise RuntimeError("AgentHost.boot() must be called before run()")

        # Tell the agentic todo tool which conversation's task list is active.
        from openpup import agentic

        agentic.set_conversation(conversation)

        async with self._lock:
            effective_model = model or self.default_model
            base_history = self._histories.get(conversation, [])

            try:
                result = await self._attempt_with_retries(
                    prompt, base_history, effective_model, conversation
                )
            except Exception as exc:
                # Self-heal: a conversation that keeps failing is almost always a
                # too-large or malformed message history (the streamed response
                # never completes). Drop that history and retry from a clean
                # slate so the user can keep chatting. Context is lost, but the
                # pup recovers instead of being wedged forever.
                if base_history:
                    logger.warning(
                        "Conversation '%s' failed (%s); resetting its history and "
                        "retrying from a clean slate.",
                        conversation,
                        exc,
                    )
                    self._histories.pop(conversation, None)
                    result = await self._attempt_with_retries(
                        prompt, [], effective_model, conversation
                    )
                else:
                    logger.exception("Agent run failed for conversation '%s'", conversation)
                    raise

            if keep_history:
                self._histories[conversation] = list(self._agent.get_message_history())

            return _extract_text(result)

    async def _attempt_with_retries(
        self,
        prompt: str,
        base_history: List[Any],
        effective_model: Optional[str],
        conversation: str,
    ) -> Any:
        """Run the agent with transient-error retries against a fixed base history."""
        attempts = max(1, self.max_retries)
        for attempt in range(1, attempts + 1):
            # Reset to the clean base history each attempt: a failed streaming
            # run can leave the agent's in-place history dirty.
            self._agent.set_message_history(list(base_history))
            try:
                if effective_model:
                    with self._agent.temporary_model_name_override(effective_model):
                        return await self._agent.run_with_mcp(prompt)
                return await self._agent.run_with_mcp(prompt)
            except Exception as exc:
                if attempt < attempts and _is_transient(exc):
                    delay = min(8.0, 1.5 * attempt)
                    logger.warning(
                        "Transient agent error (attempt %d/%d) for '%s': %s; retrying in %.1fs",
                        attempt,
                        attempts,
                        conversation,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

    def has_history(self, conversation: str) -> bool:
        """True if we already hold live in-memory turns for this conversation.

        False right after a (re)start -- the cue for the runtime to rehydrate
        recent turns from the persistent transcript instead.
        """
        return bool(self._histories.get(conversation))

    def reset_conversation(self, conversation: str) -> None:
        self._histories.pop(conversation, None)


def _extract_text(result: Any) -> str:
    """Pull the response string out of a pydantic-ai run result."""
    for attr in ("output", "data"):
        value = getattr(result, attr, None)
        if isinstance(value, str):
            return value
        if value is not None:
            return str(value)
    return str(result)
