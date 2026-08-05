"""The `Extractor` Port: pulls structured data out of an artifact."""

from abc import ABC, abstractmethod

from domain.entities.artifact import Artifact
from extractors.models import ExtractionOutcome


class Extractor(ABC):
    """Extracts structured data from an `Artifact`."""

    @property
    @abstractmethod
    def extractor_name(self) -> str:
        """Unique, human-readable name identifying this extractor.

        Returns:
            The extractor name.
        """
        ...

    @abstractmethod
    async def extract(self, artifact: Artifact) -> ExtractionOutcome:
        """Extract structured data from the given artifact.

        Args:
            artifact: The artifact to extract data from.

        Returns:
            The outcome of the extraction attempt.
        """
        ...
