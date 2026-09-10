"""Unit tests for `src.health.health`, covering every item in the locked Phase 20 contract.

`_RecordingService` is a minimal, concrete `SupportsHealthCheck` double that records every
`health_check()` call it receives (and can be configured to return `False` or raise) so ordering,
no-short-circuit, and failure-handling behavior can all be asserted directly against the recorded
event sequence. `_ServiceFailure` is a distinct exception type, used to prove that a raising
service's own exception never escapes `Health.health_check()`.
"""

import pytest
from src.core.protocols import SupportsHealthCheck
from src.health.health import Health


class _ServiceFailure(Exception):
    """A distinct exception type raised by `_RecordingService`, to prove failure identity."""


class _RecordingService:
    """A minimal, concrete `SupportsHealthCheck`, recording every `health_check()` call it
    receives.

    Args:
        events: Shared list every `_RecordingService` instance in a test appends its own
            `"<name>.health_check"` (or `".fail"`-suffixed) event to, in call order.
        name: This service's own label, used only to build its event strings.
        result: `True` or `False` to return from `health_check()`, or the literal string
            `"raise"` to raise `_ServiceFailure` instead. Defaults to `True`.
    """

    def __init__(self, events: list[str], name: str, *, result: bool | str = True) -> None:
        self._events = events
        self._name = name
        self._result = result

    async def health_check(self) -> bool:
        """Record a health-check event, then return `result` or raise `_ServiceFailure`."""
        if self._result == "raise":
            self._events.append(f"{self._name}.health_check.fail")
            raise _ServiceFailure(f"{self._name} failed to report health")
        self._events.append(f"{self._name}.health_check")
        assert isinstance(self._result, bool)
        return self._result


def test_recording_service_satisfies_supports_health_check() -> None:
    """The test double used throughout this file is a genuine `SupportsHealthCheck`."""
    assert isinstance(_RecordingService([], "a"), SupportsHealthCheck)


def test_services_property_returns_exact_construction_order() -> None:
    """`Health.services` returns exactly what was constructed, in order, immutably -- proving
    `Health` uses the exact objects it was given rather than constructing any service itself."""
    events: list[str] = []
    a, b, c = (
        _RecordingService(events, "a"),
        _RecordingService(events, "b"),
        _RecordingService(events, "c"),
    )
    health = Health([a, b, c])
    assert health.services == (a, b, c)
    assert health.services[0] is a
    assert health.services[1] is b
    assert health.services[2] is c
    assert isinstance(health.services, tuple)


@pytest.mark.asyncio
async def test_health_check_returns_true_for_empty_services() -> None:
    """`health_check()` on a `Health` with no registered services returns `True`."""
    health = Health([])
    assert await health.health_check() is True


@pytest.mark.asyncio
async def test_health_check_returns_true_when_all_healthy() -> None:
    """`health_check()` returns `True` when every registered service reports healthy."""
    events: list[str] = []
    services = [_RecordingService(events, name) for name in ("a", "b", "c")]
    health = Health(services)
    assert await health.health_check() is True


@pytest.mark.asyncio
async def test_health_check_returns_false_when_one_unhealthy() -> None:
    """`health_check()` returns `False` when any registered service reports unhealthy."""
    events: list[str] = []
    services = [
        _RecordingService(events, "a"),
        _RecordingService(events, "b", result=False),
        _RecordingService(events, "c"),
    ]
    health = Health(services)
    assert await health.health_check() is False


@pytest.mark.asyncio
async def test_health_check_does_not_short_circuit_on_false() -> None:
    """Every registered service is still checked after an earlier one reports unhealthy."""
    events: list[str] = []
    services = [
        _RecordingService(events, "a", result=False),
        _RecordingService(events, "b"),
        _RecordingService(events, "c"),
    ]
    health = Health(services)
    await health.health_check()
    assert events == ["a.health_check", "b.health_check", "c.health_check"]


@pytest.mark.asyncio
async def test_health_check_treats_raising_service_as_unhealthy() -> None:
    """A service whose `health_check()` raises makes the overall result `False`."""
    events: list[str] = []
    services = [_RecordingService(events, "a", result="raise")]
    health = Health(services)
    assert await health.health_check() is False


@pytest.mark.asyncio
async def test_health_check_does_not_propagate_service_exception() -> None:
    """`Health.health_check()` itself never raises, even when a registered service's own
    `health_check()` does -- the exception is caught, not left to propagate."""
    events: list[str] = []
    services = [_RecordingService(events, "a", result="raise")]
    health = Health(services)
    # No pytest.raises: reaching this assertion at all is the proof the exception was contained.
    result = await health.health_check()
    assert result is False


@pytest.mark.asyncio
async def test_health_check_continues_checking_remaining_services_after_exception() -> None:
    """Every registered service is still checked after an earlier one raises."""
    events: list[str] = []
    services = [
        _RecordingService(events, "a", result="raise"),
        _RecordingService(events, "b"),
        _RecordingService(events, "c"),
    ]
    health = Health(services)
    await health.health_check()
    assert events == ["a.health_check.fail", "b.health_check", "c.health_check"]


@pytest.mark.asyncio
async def test_health_check_calls_services_in_registration_order() -> None:
    """`health_check()` checks every service in exactly the order it was registered."""
    events: list[str] = []
    services = [_RecordingService(events, name) for name in ("a", "b", "c")]
    health = Health(services)
    await health.health_check()
    assert events == ["a.health_check", "b.health_check", "c.health_check"]


@pytest.mark.asyncio
async def test_health_check_mixed_results_still_returns_false_and_checks_all() -> None:
    """A mix of healthy, unhealthy, and raising services still checks every one, in order, and
    reports an overall `False`."""
    events: list[str] = []
    services = [
        _RecordingService(events, "a"),
        _RecordingService(events, "b", result=False),
        _RecordingService(events, "c", result="raise"),
        _RecordingService(events, "d"),
    ]
    health = Health(services)
    result = await health.health_check()
    assert result is False
    assert events == [
        "a.health_check",
        "b.health_check",
        "c.health_check.fail",
        "d.health_check",
    ]
