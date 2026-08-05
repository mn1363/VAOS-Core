"""The `Metadata` value object: immutable, structured key-value data."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Metadata:
    """Immutable collection of freeform, structured metadata.

    Attributes:
        values: Underlying key-value mapping. Treated as opaque by the
            domain layer; interpretation is left to collectors, analyzers,
            extractors and scorers.
    """

    values: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def empty() -> "Metadata":
        """Create an empty `Metadata` instance.

        Returns:
            A `Metadata` value object with no entries.
        """
        return Metadata(values={})
