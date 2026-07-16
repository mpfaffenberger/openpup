"""Sub-agent delegation: spawn parallel child tasks.

A small facade for fan-out work. Given a list of prompts, runs them in
parallel via ``asyncio.gather``, each with a fresh conversation ID, and
returns the results.

For v1 each sub-agent is a lightweight call to the shared LLM with a
preamble (the parent context). Real per-subagent kennel + sessions
isolation is left for a follow-up so this commit stays focused on the
parallel-execution primitive.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Sequence

logger = logging.getLogger("openpup.subagents")


@dataclass
class SubAgentResult:
    """One sub-agent's output."""

    task_id: str
    prompt: str
    output: str
    elapsed_s: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "prompt": self.prompt[:120],
            "output": self.output,
            "elapsed_s": self.elapsed_s,
            "ok": self.ok,
            "error": self.error,
        }


async def fan_out(
    prompts: Sequence[str],
    runner: Callable[[str, str], Awaitable[str]],
    *,
    concurrency: int = 4,
) -> list[SubAgentResult]:
    """Run ``prompts`` via ``runner(prompt, task_id)`` in parallel.

    ``runner`` returns the assistant's text output. Limits concurrency via
    a semaphore. Failures in one task don't cancel the others.
    """
    sem = asyncio.Semaphore(concurrency)
    started_at = time.time()

    async def _one(prompt: str) -> SubAgentResult:
        task_id = uuid.uuid4().hex[:8]
        t0 = time.time()
        try:
            async with sem:
                output = await runner(prompt, task_id)
        except Exception as exc:
            return SubAgentResult(
                task_id=task_id,
                prompt=prompt,
                output="",
                elapsed_s=time.time() - t0,
                error=f"{exc!r}",
            )
        return SubAgentResult(
            task_id=task_id,
            prompt=prompt,
            output=output,
            elapsed_s=time.time() - t0,
        )

    coros = [_one(p) for p in prompts]
    return await asyncio.gather(*coros, return_exceptions=False)


async def _echo_runner(prompt: str, task_id: str) -> str:
    """Tiny stub runner used by tests + smoke checks.

    Real runners would invoke ``AgentHost.run`` (or similar) per task.
    """
    await asyncio.sleep(0)  # yield to the event loop
    return f"[{task_id}] {prompt}"
