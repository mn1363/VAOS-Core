"""The `Analyzer` Port: inspects an artifact and produces findings."""

from abc import ABC, abstractmethod

from analyzers.models import AnalysisOutcome
from domain.entities.artifact import Artifact


class Analyzer(ABC):
    """Inspects an `Artifact` and produces structured findings."""

    @property
    @abstractmethod
    def analyzer_name(self) -> str:
        """Unique, human-readable name identifying this analyzer.

        Returns:
            The analyzer name.
        """
        ...

    @abstractmethod
    async def analyze(self, artifact: Artifact) -> AnalysisOutcome:
        """Analyze the given artifact.

        Args:
            artifact: The artifact to analyze.

        Returns:
            The outcome of the analysis attempt.
        """
        ...
