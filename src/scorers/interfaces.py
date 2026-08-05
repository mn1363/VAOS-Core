"""The `Scorer` Port: computes a `Score` for an artifact."""

from abc import ABC, abstractmethod

from domain.entities.artifact import Artifact
from scorers.models import ScoringOutcome


class Scorer(ABC):
    """Computes a `Score` for an `Artifact` based on prior findings."""

    @property
    @abstractmethod
    def scorer_name(self) -> str:
        """Unique, human-readable name identifying this scorer.

        Returns:
            The scorer name.
        """
        ...

    @abstractmethod
    async def score(self, artifact: Artifact) -> ScoringOutcome:
        """Compute a score for the given artifact.

        Args:
            artifact: The artifact to score.

        Returns:
            The outcome of the scoring attempt.
        """
        ...
