from __future__ import annotations

import pytest

from scripts.run_drug_target_traced import _close_async_stream


class _ClosableStream:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_close_async_stream_awaits_aclose() -> None:
    stream = _ClosableStream()

    await _close_async_stream(stream)

    assert stream.closed is True


@pytest.mark.asyncio
async def test_close_async_stream_ignores_non_closable_object() -> None:
    await _close_async_stream(object())
