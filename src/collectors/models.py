"""Data structures produced by `Collector` implementations."""

from dataclasses import dataclass, field

from domain.entities.artifact import Artifact


@dataclass(frozen=True, slots=True)
class CollectionResult:
    """Outcome of a single collection attempt.

    Attributes:
        source_uri: Location that was collected from.
        succeeded: Whether the collection attempt completed successfully.
        artifacts: Artifacts discovered during collection.
        error_message: Explanation of the failure, when `succeeded` is False.
    """

    source_uri: str
    succeeded: bool
    artifacts: list[Artifact] = field(default_factory=list)
    error_message: str | None = None
