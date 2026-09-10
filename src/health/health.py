"""`Health`: orchestrates a fixed, constructor-injected sequence of `SupportsHealthCheck`
services.

A `Health` coordinates already-existing `SupportsHealthCheck` services -- it never constructs one
itself. Every service it checks is supplied at construction time; see `__init__`'s own docstring,
and this package's own module docstring (`src/health/__init__.py`) for the fuller architectural
picture, including why this layer imports `core` only.

`health_check()` is a scan, not an all-or-nothing action: every registered service is checked, in
registration order, regardless of any earlier result. A service that returns `False`, or whose own
`health_check()` raises, is treated as unhealthy -- contributing to an overall `False` result --
without stopping the scan or propagating out of this method. This deliberately does not mirror
`runtime.runtime.Runtime.start`'s fail-fast, propagate-and-roll-back behavior: `pipeline.base`'s
own module docstring distinguishes a single, ordered, all-or-nothing execution (`Pipeline.run`,
`Runtime.start`/`stop`) from "a per-item scan that may legitimately encounter many independent
failures" (`collectors.base.CollectionResult`, `parsers.base.ParseResult`, every
extractor/analyzer/graph/foundation Port) -- checking the health of several independent services
is the latter shape, not the former.
"""

from collections.abc import Sequence

from src.core.logging import get_logger
from src.core.protocols import SupportsHealthCheck

_logger = get_logger("health")


class Health:
    """Orchestrates an ordered, fixed sequence of `SupportsHealthCheck` services.

    Every service a `Health` checks is supplied at construction time (dependency injection) -- a
    `Health` never constructs a service itself, and holds no hidden service locator or global
    registry through which one could be looked up instead.

    A single `Health` instance is reusable in the same sense `runtime.runtime.Runtime` is:
    `health_check` reads only `self._services`, fixed at construction, so calling it more than
    once walks the same services, in the same order, every time. It tracks no internal state
    between calls.
    """

    def __init__(self, services: Sequence[SupportsHealthCheck]) -> None:
        """Construct a health orchestrator from an already-assembled, ordered sequence of
        services.

        Args:
            services: The services this orchestrator checks, in the exact order given. May be
                empty -- see `health_check`'s own docstring for empty behavior. No uniqueness
                constraint is enforced: `SupportsHealthCheck` has no identity field (unlike
                `pipeline.base.Step.name`) for one to be checked against.
        """
        self._services: tuple[SupportsHealthCheck, ...] = tuple(services)

    @property
    def services(self) -> tuple[SupportsHealthCheck, ...]:
        """The services this orchestrator checks, in registration order, exactly as
        constructed."""
        return self._services

    async def health_check(self) -> bool:
        """Check every registered service, in registration order, and report whether every one
        is healthy.

        An empty `services` sequence is not a special case: with nothing to check, every
        registered service (zero of them) is healthy, so this returns `True`.

        Every service is checked -- there is no short-circuit on the first unhealthy result, and
        no short-circuit on a raised exception. A service whose `health_check()` raises is
        treated exactly like one that returns `False`: the exception is caught at the point of
        that single call, never propagates out of this method, and the scan continues with the
        next service.

        Returns:
            `True` if every registered service reported healthy (or there were none to check);
            `False` if any registered service reported unhealthy or raised.
        """
        all_healthy = True
        for index, service in enumerate(self._services):
            try:
                healthy = await service.health_check()
            except Exception as exc:  # noqa: BLE001 -- see this method's own docstring: any
                # exception a service's own `health_check()` raises is treated as that service
                # being unhealthy, not as a failure of this scan itself, so it is deliberately
                # caught broadly here rather than re-raised.
                _logger.debug("health check raised for service at index %d: %s", index, exc)
                healthy = False
            else:
                _logger.debug(
                    "health check for service at index %d: %s",
                    index,
                    "healthy" if healthy else "unhealthy",
                )
            if not healthy:
                all_healthy = False
        return all_healthy
