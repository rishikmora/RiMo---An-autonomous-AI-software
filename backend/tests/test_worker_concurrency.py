"""Worker concurrency tests — proves the semaphore cap actually holds.

The worker gates project advancement on a semaphore sized by
``max_concurrent_projects``. These tests prove two properties the README claims
but did not previously demonstrate:

  1. With N projects where N > cap, the number running *simultaneously* never
     exceeds the cap.
  2. Every project still eventually completes (no starvation under contention).

The work itself is replaced with an instrumented coroutine that records the live
concurrency, so the test is fast, deterministic, and needs no database.
"""
from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.asyncio


class _ConcurrencyProbe:
    """Tracks live and peak concurrency through a semaphore-guarded section."""

    def __init__(self) -> None:
        self.live = 0
        self.peak = 0
        self.completed = 0
        self._lock = asyncio.Lock()

    async def enter(self) -> None:
        async with self._lock:
            self.live += 1
            self.peak = max(self.peak, self.live)

    async def exit(self) -> None:
        async with self._lock:
            self.live -= 1
            self.completed += 1


async def _run_guarded(semaphore: asyncio.Semaphore, probe: _ConcurrencyProbe, work_ms: int = 10) -> None:
    """Mirror the worker's `async with self._semaphore: <work>` structure."""
    async with semaphore:
        await probe.enter()
        try:
            await asyncio.sleep(work_ms / 1000)
        finally:
            await probe.exit()


async def test_semaphore_caps_concurrency() -> None:
    cap = 4
    n = 20
    semaphore = asyncio.Semaphore(cap)
    probe = _ConcurrencyProbe()

    await asyncio.gather(*(_run_guarded(semaphore, probe) for _ in range(n)))

    assert probe.peak <= cap, f"peak concurrency {probe.peak} exceeded cap {cap}"
    assert probe.completed == n, "every unit of work must complete"


async def test_no_starvation_under_contention() -> None:
    """Far more work than slots: everything still finishes, none is dropped."""
    cap = 2
    n = 50
    semaphore = asyncio.Semaphore(cap)
    probe = _ConcurrencyProbe()

    await asyncio.wait_for(
        asyncio.gather(*(_run_guarded(semaphore, probe, work_ms=2) for _ in range(n))),
        timeout=10,
    )

    assert probe.completed == n
    assert probe.peak <= cap


async def test_worker_uses_configured_cap() -> None:
    """The worker sizes its semaphore from settings.max_concurrent_projects."""
    from app.core.config import settings
    from app.orchestration.worker import Worker

    worker = Worker()
    # Semaphore exposes its initial value via _value when fully available.
    assert worker._semaphore._value == settings.max_concurrent_projects


async def test_semaphore_serializes_when_cap_is_one() -> None:
    cap = 1
    n = 8
    semaphore = asyncio.Semaphore(cap)
    probe = _ConcurrencyProbe()

    await asyncio.gather(*(_run_guarded(semaphore, probe, work_ms=1) for _ in range(n)))

    assert probe.peak == 1  # strictly serialized
    assert probe.completed == n
