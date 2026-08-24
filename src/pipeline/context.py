"""Pipeline execution context: the explicit, in-memory data carried between `Step`s.

`PipelineContext` is deliberately a single, mutable, named-key container rather than a chain of
per-step return values or a frozen, replace-on-write dataclass: a `Pipeline` may run any number of
heterogeneous `Step`s in sequence -- a `Collector.collect` call producing `SourceRepository`
entities, a `Parser.parse` call producing a `ParseResult`, a graph `Builder.build` call producing
a whole `DependencyGraph` -- and no single fixed set of typed fields could name all of them without
this module importing (and thus coupling itself to) every layer it might ever coordinate, which
`__init__.py`'s own module docstring already rules out. A single `dict[str, Any]`, addressed by
explicit `get`/`require`/`set` calls rather than implicit attribute or global lookup, keeps every
read and write visible at the call site -- "no hidden global state", per this phase's own brief --
while staying agnostic to which layers a particular `Pipeline` happens to coordinate.

`PipelineContext` performs no serialization and enforces no schema of its own: a stored value is
whatever a `Step` chose to write, unchanged, including domain entities, dataclass DTOs, or plain
Python collections. Determinism is a property of how a `Pipeline` and its `Step`s use a context
(see `pipeline.py`), not of the context's own storage, which is intentionally as simple as
possible.
"""

from dataclasses import dataclass, field
from typing import Any

from src.core.exceptions import NotFoundError, ValidationError


@dataclass(slots=True)
class PipelineContext:
    """Explicit, typed, in-memory data carried between `Step`s during one `Pipeline.run` call.

    Attributes:
        values: The context's own backing store, keyed by the explicit, caller-chosen names each
            `Step` reads from and writes to. Exposed as a plain, mutable dict rather than hidden
            behind a private name so a caller assembling a `Pipeline`'s initial context can also
            construct one directly (`PipelineContext(values={...})`) without going through `set`
            for every seed value.
    """

    values: dict[str, Any] = field(default_factory=dict)

    def has(self, key: str) -> bool:
        """Report whether a value is currently stored under `key`.

        Args:
            key: The key to check.

        Returns:
            True if `key` currently has a stored value.
        """
        return key in self.values

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve the value stored under `key`, or `default` if none exists.

        Args:
            key: The key to look up.
            default: Value returned if `key` is not currently present. Defaults to None.

        Returns:
            The stored value, or `default`.
        """
        return self.values.get(key, default)

    def require(self, key: str) -> Any:
        """Retrieve the value stored under `key`, treating its absence as an error.

        Args:
            key: The key to look up.

        Returns:
            The stored value.

        Raises:
            NotFoundError: If no value is currently stored under `key`.
        """
        if key not in self.values:
            raise NotFoundError(
                f"pipeline context has no value for key '{key}'", details={"key": key}
            )
        return self.values[key]

    def set(self, key: str, value: Any) -> None:
        """Store `value` under `key`, overwriting any existing value stored there.

        Args:
            key: The key to store `value` under. Must not be blank.
            value: The value to store.

        Raises:
            ValidationError: If `key` is blank.
        """
        if not key.strip():
            raise ValidationError("PipelineContext.set: key must not be empty")
        self.values[key] = value

    def to_mapping(self) -> dict[str, Any]:
        """Render this context's current contents as a plain dict.

        Returns:
            A shallow copy of `values`. Mutating the returned dict does not affect this context.
        """
        return dict(self.values)
