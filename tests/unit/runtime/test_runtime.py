"""Unit tests for `src.runtime.runtime`, covering every item in the locked Phase 19 contract.

`_RecordingService` is a minimal, concrete `SupportsLifecycle` double that records every
start/stop call it receives (and optionally fails one of them) so ordering, rollback, and
failure-propagation behavior can all be asserted directly against the recorded event sequence.
`_ServiceFailure` is a distinct exception type, used to prove exactly which exception -- the raw
service failure, or `RuntimeLifecycleError` wrapping it -- a given call actually propagates.
"""

import pytest
from src.core.protocols import SupportsLifecycle
from src.runtime.errors import RuntimeLifecycleError
from src.runtime.runtime import Runtime


class _ServiceFailure(Exception):
    """A distinct exception type raised by `_RecordingService`, to prove failure identity."""


class _RecordingService:
    """A minimal, concrete `SupportsLifecycle`, recording every start/stop call it receives.

    Args:
        events: Shared list every `_RecordingService` instance in a test appends its own
            `"<name>.start"`/`"<name>.stop"` (or `".fail"`-suffixed) events to, in call order.
        name: This service's own label, used only to build its event strings.
        fail_on: `"start"` or `"stop"` to make that method raise `_ServiceFailure` instead of
            recording success; `None` (the default) to always succeed.
    """

    def __init__(self, events: list[str], name: str, *, fail_on: str | None = None) -> None:
        self._events = events
        self._name = name
        self._fail_on = fail_on

    async def start(self) -> None:
        """Record a start event, or raise `_ServiceFailure` if constructed with `fail_on="start"`."""
        if self._fail_on == "start":
            self._events.append(f"{self._name}.start.fail")
            raise _ServiceFailure(f"{self._name} failed to start")
        self._events.append(f"{self._name}.start")

    async def stop(self) -> None:
        """Record a stop event, or raise `_ServiceFailure` if constructed with `fail_on="stop"`."""
        if self._fail_on == "stop":
            self._events.append(f"{self._name}.stop.fail")
            raise _ServiceFailure(f"{self._name} failed to stop")
        self._events.append(f"{self._name}.stop")


def test_recording_service_satisfies_supports_lifecycle() -> None:
    """The test double used throughout this file is a genuine `SupportsLifecycle`."""
    assert isinstance(_RecordingService([], "a"), SupportsLifecycle)


def test_services_property_returns_exact_construction_order() -> None:
    """`Runtime.services` returns exactly what was constructed, in order, immutably."""
    events: list[str] = []
    a, b, c = (
        _RecordingService(events, "a"),
        _RecordingService(events, "b"),
        _RecordingService(events, "c"),
    )
    runtime = Runtime([a, b, c])
    assert runtime.services == (a, b, c)
    assert isinstance(runtime.services, tuple)


@pytest.mark.asyncio
async def test_start_is_a_noop_for_empty_services() -> None:
    """`start()` on an empty `Runtime` returns immediately, without raising."""
    runtime = Runtime([])
    await runtime.start()


@pytest.mark.asyncio
async def test_stop_is_a_noop_for_empty_services() -> None:
    """`stop()` on an empty `Runtime` returns immediately, without raising."""
    runtime = Runtime([])
    await runtime.stop()


@pytest.mark.asyncio
async def test_start_calls_services_in_registration_order() -> None:
    """`start()` starts every service in exactly the order it was registered."""
    events: list[str] = []
    services = [_RecordingService(events, name) for name in ("a", "b", "c")]
    runtime = Runtime(services)
    await runtime.start()
    assert events == ["a.start", "b.start", "c.start"]


@pytest.mark.asyncio
async def test_stop_calls_services_in_reverse_registration_order() -> None:
    """`stop()` stops every service in exactly the reverse of its registration order."""
    events: list[str] = []
    services = [_RecordingService(events, name) for name in ("a", "b", "c")]
    runtime = Runtime(services)
    await runtime.stop()
    assert events == ["c.stop", "b.stop", "a.stop"]


@pytest.mark.asyncio
async def test_start_failure_stops_further_startup() -> None:
    """The first `start()` failure stops the startup loop -- no later service starts."""
    events: list[str] = []
    services = [
        _RecordingService(events, "a"),
        _RecordingService(events, "b", fail_on="start"),
        _RecordingService(events, "c"),
    ]
    runtime = Runtime(services)
    with pytest.raises(RuntimeLifecycleError):
        await runtime.start()
    assert "c.start" not in events


@pytest.mark.asyncio
async def test_start_failure_rolls_back_already_started_services_in_reverse_order() -> None:
    """Already-started services are stopped, in reverse order, before the error is raised."""
    events: list[str] = []
    services = [
        _RecordingService(events, "a"),
        _RecordingService(events, "b"),
        _RecordingService(events, "c", fail_on="start"),
    ]
    runtime = Runtime(services)
    with pytest.raises(RuntimeLifecycleError):
        await runtime.start()
    assert events == ["a.start", "b.start", "c.start.fail", "b.stop", "a.stop"]


@pytest.mark.asyncio
async def test_start_failure_preserves_original_exception_as_cause() -> None:
    """`RuntimeLifecycleError.__cause__` is the original exception, via `raise ... from exc`."""
    events: list[str] = []
    services = [_RecordingService(events, "a", fail_on="start")]
    runtime = Runtime(services)
    with pytest.raises(RuntimeLifecycleError) as exc_info:
        await runtime.start()
    assert isinstance(exc_info.value.__cause__, _ServiceFailure)


@pytest.mark.asyncio
async def test_start_failure_details_identify_failed_and_rolled_back_indices() -> None:
    """`details` names the failed service's index and every rolled-back index, in rollback order."""
    events: list[str] = []
    services = [
        _RecordingService(events, "a"),
        _RecordingService(events, "b"),
        _RecordingService(events, "c", fail_on="start"),
    ]
    runtime = Runtime(services)
    with pytest.raises(RuntimeLifecycleError) as exc_info:
        await runtime.start()
    assert exc_info.value.details["failed_index"] == 2
    assert exc_info.value.details["rolled_back_indices"] == [1, 0]


@pytest.mark.asyncio
async def test_rollback_stop_failure_propagates_unwrapped_and_halts_remaining_rollback() -> None:
    """A rollback `stop()` failure propagates unwrapped, and halts any remaining rollback."""
    events: list[str] = []
    services = [
        _RecordingService(events, "a"),
        _RecordingService(events, "b", fail_on="stop"),
        _RecordingService(events, "c", fail_on="start"),
    ]
    runtime = Runtime(services)
    with pytest.raises(_ServiceFailure):
        await runtime.start()
    assert events == ["a.start", "b.start", "c.start.fail", "b.stop.fail"]
    assert "a.stop" not in events


@pytest.mark.asyncio
async def test_stop_failure_propagates_unwrapped_and_leaves_remaining_services_unstopped() -> None:
    """A `stop()` failure propagates unwrapped, and remaining (earlier, reverse-order) services
    are not attempted -- no aggregation, no suppression, no best-effort shutdown."""
    events: list[str] = []
    services = [
        _RecordingService(events, "a"),
        _RecordingService(events, "b", fail_on="stop"),
        _RecordingService(events, "c"),
    ]
    runtime = Runtime(services)
    with pytest.raises(_ServiceFailure):
        await runtime.stop()
    assert events == ["c.stop", "b.stop.fail"]
    assert "a.stop" not in events
