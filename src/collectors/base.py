"""Collector-layer Port and result DTO.

`filesystem.py`, `local.py`, `github.py`, and `gitlab.py` each implement `Collector` for one
`RepositoryProvider` value. Unlike `src.repository`'s Ports, which raise `GitCommandError` for
any failure, `Collector.collect` reports failure through the returned `CollectionResult` rather
than raising. A single `collect` call commonly represents a directory *scan* that may
legitimately encounter many invalid or missing sources; raising on the first one would abort
discovery of everything else, so failure is data here, not an exception. The one exception this
package's Port raises, `core.exceptions.ValidationError`, is reused rather than a new
package-specific class being introduced -- the same principle `domain` follows for its own
construction-time and state-transition checks -- and is reserved for a blank `source` argument: a
violation of `collect`'s basic contract, not a fact discovered about the source itself.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from src.core.exceptions import ValidationError
from src.domain.entities import RepositoryProvider, SourceRepository


@dataclass(frozen=True, slots=True)
class CollectionResult:
    """Outcome of a single `Collector.collect` call.

    Attributes:
        source: The source location that was collected from, exactly as passed to `collect`.
        succeeded: Whether the collection attempt completed successfully.
        repositories: `SourceRepository` entities discovered at `source`. Always empty when
            `succeeded` is False; may legitimately be empty when `succeeded` is True too (a
            valid source that simply contains no repositories).
        error_message: Explanation of the failure. Always `None` when `succeeded` is True,
            always set when `succeeded` is False.
    """

    source: str
    succeeded: bool
    repositories: tuple[SourceRepository, ...] = ()
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Validate that `succeeded`, `repositories`, and `error_message` are consistent.

        Raises:
            ValidationError: If a successful result carries an error message, or a failed
                result carries either repositories or no error message.
        """
        if self.succeeded and self.error_message is not None:
            raise ValidationError(
                "CollectionResult: error_message must be None when succeeded is True"
            )
        if not self.succeeded and self.repositories:
            raise ValidationError(
                "CollectionResult: repositories must be empty when succeeded is False"
            )
        if not self.succeeded and self.error_message is None:
            raise ValidationError(
                "CollectionResult: error_message is required when succeeded is False"
            )

    @classmethod
    def ok(cls, source: str, repositories: Sequence[SourceRepository]) -> "CollectionResult":
        """Build a successful result.

        Args:
            source: The source location that was collected from.
            repositories: Repositories discovered at `source`, possibly empty.

        Returns:
            A `CollectionResult` with `succeeded=True`.
        """
        return cls(source=source, succeeded=True, repositories=tuple(repositories))

    @classmethod
    def failed(cls, source: str, error_message: str) -> "CollectionResult":
        """Build a failed result.

        Args:
            source: The source location that collection was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            A `CollectionResult` with `succeeded=False`.
        """
        return cls(source=source, succeeded=False, error_message=error_message)


class Collector(ABC):
    """Discovers candidate repositories at a source location.

    A `Collector` decides *which* `SourceRepository` entities exist at a given source; it does
    not fetch their contents onto disk (see `src.repository.base.RepositoryClient`) nor persist
    them (see `src.domain.interfaces.SourceRepositoryStore`) -- both are separate, already-scoped
    concerns belonging to other layers.
    """

    @property
    @abstractmethod
    def provider(self) -> RepositoryProvider:
        """The `RepositoryProvider` this collector produces `SourceRepository` entities for."""
        ...

    @abstractmethod
    async def collect(self, source: str) -> CollectionResult:
        """Discover repositories located at or described by `source`.

        Args:
            source: Location to discover repositories from. Its exact meaning is
                provider-specific: a directory to scan for nested repositories, a single
                repository's own path, or a hosted-repository reference such as `"owner/repo"`.

        Returns:
            The outcome of the collection attempt.

        Raises:
            ValidationError: If `source` is blank.
        """
        ...


def require_source(source: str) -> str:
    """Validate that `source` is non-blank.

    Every `Collector.collect` implementation calls this first, so a caller error (an empty or
    whitespace-only `source`) is reported the same way -- as an immediate `ValidationError` --
    across every provider.

    Args:
        source: The raw `source` argument passed to `collect`.

    Returns:
        `source`, unchanged.

    Raises:
        ValidationError: If `source` is blank.
    """
    if not source.strip():
        raise ValidationError("source must not be empty")
    return source


def strip_git_suffix(reference: str) -> str:
    """Remove a trailing `.git` suffix from a repository reference, if present.

    Shared by `GitHubCollector` and `GitLabCollector`, which both accept clone-URL-style
    references that may or may not carry the conventional `.git` suffix.

    Args:
        reference: A repository reference, e.g. a clone URL or an `owner/repo` slug.

    Returns:
        `reference` without a trailing `.git`.
    """
    return reference.removesuffix(".git")
