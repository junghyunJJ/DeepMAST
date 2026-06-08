import asyncio
import time

import pytest

from src.agents.deep_interpreter.tools.mcp_clients import run_async


def test_run_async_returns_result_without_running_loop():
    async def immediate():
        return "ok"

    assert run_async(immediate(), timeout=1) == "ok"


def test_run_async_applies_timeout_without_running_loop():
    async def slow():
        await asyncio.sleep(1)

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        run_async(slow(), timeout=0.01)

    assert time.monotonic() - started < 0.5
