"""Bootstrap-layer exception.

`wiring.py` never wraps or replaces an exception a lower-layer Port itself raises during
construction or connection (a `ConfigurationError`, `StorageConnectionError`,
`QdrantOperationError`, `ValidationError`, `StepExecutionError`, ...) -- each already-frozen
layer's own error type is preserved and propagates unchanged, matching every earlier phase's own
"a layer defines its own exception subclass only for a failure mode genuinely new to that layer"
convention (see `core.exceptions`, `pipeline.base.StepExecutionError`).

`BootstrapError` exists for the one failure mode genuinely new to this layer: a wiring decision
`wiring.py` itself makes -- which concrete backend a configuration value selects, or how a lower
layer's own "failure reported as data" result (e.g. `collectors.base.CollectionResult`) is
translated into `pipeline`'s "failure reported by raising" convention -- turning out to be
invalid. It is not raised for a failure any other layer's own error type already describes.
"""

from src.core.exceptions import VAOSError


class BootstrapError(VAOSError):
    """Raised for a wiring/composition failure specific to `bootstrap` itself.

    Examples: an unrecognized `storage.backend`/`collectors.backend` configuration value, a
    required configuration value missing for the backend selected (e.g. `storage.postgres.dsn`
    when `storage.backend` is `"postgres"`), or a configured `Collector` reporting a failed
    collection (`collectors.base.CollectionResult.succeeded` is False) for the one `source` this
    layer's own default flow collects from.
    """
