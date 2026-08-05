"""The `FoundationService` Port: composition root for a full analysis run."""

from abc import ABC, abstractmethod

from domain.entities.artifact import Artifact
from foundation.models import FoundationReport


class FoundationService(ABC):
    """Coordinates collection, extraction, analysis and scoring for an artifact.

    `FoundationService` is the bounded-context entrypoint that later
    phases use to assemble the collector, extractor, analyzer and scorer
    Ports into a single end-to-end evaluation, without those individual
    Ports needing to know about one another.
    """

    @abstractmethod
    async def evaluate(self, artifact: Artifact) -> FoundationReport:
        """Run the full evaluation pipeline for a single artifact.

        Args:
            artifact: The artifact to evaluate.

        Returns:
            A report summarizing the evaluation outcome.
        """
        ...
