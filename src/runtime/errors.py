"""Runtime-layer exception.

`Runtime.stop` -- including every rollback `stop()` call `Runtime.start` makes when startup
fails partway through -- never wraps a `stop()` failure: the exception a failing service's
`stop()` raises propagates completely unchanged, matching this layer's locked failure semantics
(see `runtime.py`'s own module docstring). `RuntimeLifecycleError` exists for the one failure
mode genuinely new to this layer: a registered service's `start()` raising partway through an
otherwise-successful startup sequence, after zero or more earlier services in the same sequence
already started and were therefore rolled back. It is never raised for a `stop()` failure, of any
kind, matching every earlier phase's own "a layer defines its own exception subclass only for a
failure mode genuinely new to that layer" convention (see `core.exceptions`,
`pipeline.base.StepExecutionError`, `bootstrap.errors.BootstrapError`).
"""

from src.core.exceptions import VAOSError


class RuntimeLifecycleError(VAOSError):
    """Raised by `Runtime.start` when a registered service's `start()` raises partway through
    startup.

    Attributes:
        message: Human-readable description of what went wrong.
        details: Structured context about the failure -- `"failed_index"` (the failing service's
            position in the `Runtime`'s own `services`) and `"rolled_back_indices"` (the
            positions of every already-started service that was rolled back, in the order
            rollback was attempted). `SupportsLifecycle` has no name/identity field (unlike
            `pipeline.base.Step.name`), so position is the only identifier available. The
            original exception itself is preserved as this error's `__cause__` via
            `raise ... from exc`, not re-described here, so it can still be inspected, matched on
            its own type, or re-raised by a caller that catches `RuntimeLifecycleError`. See
            `Runtime.start`'s own docstring for exactly when `"rolled_back_indices"` is present.
    """
