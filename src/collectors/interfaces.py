"""The `Collector` Port: discovers and retrieves artifacts from a source."""

from abc import ABC, abstractmethod

from collectors.models import CollectionResult


class Collector(ABC):
    """Discovers and retrieves artifacts from an external source."""

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Identifier of the kind of source this collector reads from.

        Returns:
            The source type identifier, e.g. a provider name.
        """
        ...

    @abstractmethod
    async def collect(self, source_uri: str) -> CollectionResult:
        """Retrieve artifacts from the given source location.

        Args:
            source_uri: Location to collect artifacts from.

        Returns:
            The outcome of the collection attempt.
        """
        ...
