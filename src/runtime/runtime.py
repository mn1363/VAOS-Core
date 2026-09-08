"""`Runtime`: orchestrates a fixed, constructor-injected sequence of `SupportsLifecycle` services.

A `Runtime` coordinates already-existing `SupportsLifecycle` services -- it never constructs one
itself. Every service it starts and stops is supplied at construction time; see `__init__`'s own
docstring, and this package's own module docstring (`src/runtime/__init__.py`) for the fuller
architectural picture, including why this layer imports `core` only.

Startup is fail-fast and self-healing: the first service whose `start()` raises stops startup
immediately, and every service that had already started is then stopped, in reverse order,
before the original failure is re-raised, wrapped, as `RuntimeLifecycleError`. Shutdown is
fail-fast and unforgiving: the first service whose `stop()` raises -- whether during ordinary
shutdown or during this startup rollback -- propagates that exception completely unwrapped, and
no further service is attempted. See `errors.py`'s own module docstring for exactly why stop
failures are never wrapped, aggregated, or suppressed.
"""

from collections.abc import Sequence

from src.core.logging import get_logger
from src.core.protocols import SupportsLifecycle

from .errors import RuntimeLifecycleError

_logger = get_logger("runtime")


class Runtime:
    """Orchestrates an ordered, fixed sequence of `SupportsLifecycle` services.

    Every service a `Runtime` starts and stops is supplied at construction time (dependency
    injection) -- a `Runtime` never constructs a service itself, and holds no hidden service
    locator or global registry through which one could be looked up instead.

    A single `Runtime` instance is reusable in the same sense `pipeline.pipeline.Pipeline` is:
    `start`/`stop` read only `self._services`, fixed at construction, so calling `start` and
    `stop` again after a prior `start`/`stop` pair walks the same services in the same order
    every time. Neither method tracks whether the other has already run, or whether it has
    itself already run -- there is no internal started/stopped state -- so that bookkeeping is a
    caller concern, not this class's.
    """

    def __init__(self, services: Sequence[SupportsLifecycle]) -> None:
        """Construct a runtime from an already-assembled, ordered sequence of services.

        Args:
            services: The services this runtime starts and stops, in the exact order given. May
                be empty -- see `start`/`stop`'s own docstrings for empty-runtime behavior. No
                uniqueness constraint is enforced: `SupportsLifecycle` has no identity field
                (unlike `pipeline.base.Step.name`) for one to be checked against.
        """
        self._services: tuple[SupportsLifecycle, ...] = tuple(services)

    @property
    def services(self) -> tuple[SupportsLifecycle, ...]:
        """The services this runtime orchestrates, in registration order, exactly as
        constructed."""
        return self._services

    async def start(self) -> None:
        """Start every registered service, in registration order.

        An empty `services` sequence is not an error: `start` simply returns immediately having
        started nothing.

        Raises:
            RuntimeLifecycleError: If any service's `start()` raises. Every service that had
                already started successfully is stopped, in reverse order, before this error is
                raised; the original exception is preserved as this error's `__cause__` via
                `raise ... from exc`. `details` records `"failed_index"` (this service's
                position in `services`) and `"rolled_back_indices"` (the positions of every
                service rolled back, in the order rollback was attempted) -- present only when
                every rollback attempt itself succeeds; see the next entry for when one does not.
            Exception: If a rollback `stop()` call itself raises, that exception propagates
                completely unwrapped in place of `RuntimeLifecycleError` -- matching `stop`'s own
                unwrapped-failure behavior exactly -- and any remaining rollback stops are not
                attempted.
        """
        started: list[int] = []
        for index, service in enumerate(self._services):
            _logger.debug("runtime starting service at index %d", index)
            try:
                await service.start()
            except Exception as exc:
                _logger.debug("runtime failed starting service at index %d: %s", index, exc)
                rolled_back = list(reversed(started))
                for rollback_index in rolled_back:
                    _logger.debug("runtime rolling back service at index %d", rollback_index)
                    await self._services[rollback_index].stop()
                raise RuntimeLifecycleError(
                    f"runtime failed to start service at index {index}: {exc}",
                    details={"failed_index": index, "rolled_back_indices": rolled_back},
                ) from exc
            started.append(index)
            _logger.debug("runtime started service at index %d", index)

    async def stop(self) -> None:
        """Stop every registered service, in reverse registration order.

        An empty `services` sequence is not an error: `stop` simply returns immediately having
        stopped nothing.

        Raises:
            Exception: Whatever the first failing service's `stop()` call itself raises,
                propagated completely unwrapped -- this layer's `RuntimeLifecycleError` is never
                used for a `stop()` failure. Remaining services, earlier in reverse order, are
                not attempted; no exception is aggregated or suppressed. See this module's own
                docstring for why.
        """
        for index in reversed(range(len(self._services))):
            _logger.debug("runtime stopping service at index %d", index)
            await self._services[index].stop()
            _logger.debug("runtime stopped service at index %d", index)
