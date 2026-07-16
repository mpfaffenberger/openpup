"""Tests for the sub-agent delegation module."""

import asyncio


from openpup.subagents import SubAgentResult, _echo_runner, fan_out


class TestFanOut:
    def test_empty_prompts(self):
        results = asyncio.run(fan_out([], _echo_runner))
        assert results == []

    def test_single_prompt(self):
        async def go():
            return await fan_out(["only one"], _echo_runner)

        results = asyncio.run(go())
        assert len(results) == 1
        assert results[0].prompt == "only one"
        assert "only one" in results[0].output
        assert results[0].ok

    def test_multiple_prompts_run_in_parallel(self):
        async def slow_runner(prompt, task_id):
            await asyncio.sleep(0.05)
            return f"done {prompt}"

        async def go():
            t0 = asyncio.get_event_loop().time()
            results = await fan_out(["a", "b", "c", "d"], slow_runner)
            elapsed = asyncio.get_event_loop().time() - t0
            return results, elapsed

        results, elapsed = asyncio.run(go())
        # 4 parallel @ 50ms each should finish in well under 200ms.
        assert len(results) == 4
        assert elapsed < 0.2

    def test_failure_does_not_cancel_others(self):
        async def flaky(prompt, task_id):
            if "fail" in prompt:
                raise RuntimeError("boom")
            await asyncio.sleep(0)
            return f"ok {prompt}"

        async def go():
            return await fan_out(["good", "fail-me", "also-good"], flaky)

        results = asyncio.run(go())
        assert len(results) == 3
        # 2 succeed, 1 fails.
        succeeded = [r for r in results if r.ok]
        failed = [r for r in results if not r.ok]
        assert len(succeeded) == 2
        assert len(failed) == 1
        assert "boom" in failed[0].error

    def test_concurrency_limit(self):
        max_seen = 0
        current = 0
        lock = asyncio.Lock()

        async def counter(prompt, task_id):
            nonlocal max_seen, current
            async with lock:
                current += 1
                max_seen = max(max_seen, current)
            await asyncio.sleep(0.02)
            async with lock:
                current -= 1
            return "ok"

        async def go():
            return await fan_out(
                ["a", "b", "c", "d", "e", "f"], counter, concurrency=2
            )

        results = asyncio.run(go())
        # With concurrency=2, we never see 3 or more at once.
        assert max_seen <= 2
        assert len(results) == 6


class TestResult:
    def test_ok_property(self):
        r = SubAgentResult(task_id="x", prompt="p", output="o")
        assert r.ok is True
        assert r.to_dict()["ok"] is True

    def test_error_property(self):
        r = SubAgentResult(task_id="x", prompt="p", output="", error="boom")
        assert r.ok is False
        d = r.to_dict()
        assert d["ok"] is False
        assert d["error"] == "boom"
