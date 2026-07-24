from unittest.mock import AsyncMock

import pytest

from app import watchdog


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def fake_clock(monkeypatch):
    # Deterministic clock so cooldown assertions don't depend on wall time.
    clock = _FakeClock()
    monkeypatch.setattr(watchdog.time, "monotonic", clock)
    return clock


async def test_check_once_does_nothing_when_anki_is_responsive(monkeypatch):
    monkeypatch.setattr(watchdog.ankiconnect, "invoke", AsyncMock(return_value=6))
    restart_mock = AsyncMock()
    monkeypatch.setattr(watchdog.fly_api, "restart_anki_machines", restart_mock)

    await watchdog.Watchdog().check_once()

    restart_mock.assert_not_awaited()


async def test_check_once_restarts_when_anki_is_unresponsive(monkeypatch):
    monkeypatch.setattr(
        watchdog.ankiconnect, "invoke", AsyncMock(side_effect=Exception("timed out"))
    )
    restart_mock = AsyncMock()
    monkeypatch.setattr(watchdog.fly_api, "restart_anki_machines", restart_mock)

    await watchdog.Watchdog().check_once()

    restart_mock.assert_awaited_once()


async def test_check_once_respects_cooldown_between_restarts(monkeypatch, fake_clock):
    monkeypatch.setattr(
        watchdog.ankiconnect, "invoke", AsyncMock(side_effect=Exception("timed out"))
    )
    restart_mock = AsyncMock()
    monkeypatch.setattr(watchdog.fly_api, "restart_anki_machines", restart_mock)

    instance = watchdog.Watchdog()
    fake_clock.now = 0.0
    await instance.check_once()
    fake_clock.now = 1.0
    await instance.check_once()

    restart_mock.assert_awaited_once()


async def test_check_once_restarts_again_after_cooldown_elapses(monkeypatch, fake_clock):
    monkeypatch.setattr(
        watchdog.ankiconnect, "invoke", AsyncMock(side_effect=Exception("timed out"))
    )
    restart_mock = AsyncMock()
    monkeypatch.setattr(watchdog.fly_api, "restart_anki_machines", restart_mock)

    instance = watchdog.Watchdog()
    fake_clock.now = 0.0
    await instance.check_once()
    fake_clock.now = watchdog.RESTART_COOLDOWN_SECONDS + 1
    await instance.check_once()

    assert restart_mock.await_count == 2


async def test_check_once_swallows_restart_failures(monkeypatch):
    monkeypatch.setattr(
        watchdog.ankiconnect, "invoke", AsyncMock(side_effect=Exception("timed out"))
    )
    monkeypatch.setattr(
        watchdog.fly_api,
        "restart_anki_machines",
        AsyncMock(side_effect=Exception("fly API down too")),
    )

    await watchdog.Watchdog().check_once()  # must not raise
