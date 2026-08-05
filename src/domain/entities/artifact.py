"""The `Artifact` entity: a generic analyzable unit within VAOS."""

from dataclasses import dataclass, field

from domain.entities.base import Entity
from domain.enums.status import ArtifactStatus
from domain.value_objects.metadata import Metadata


@dataclass(eq=False, kw_only=True)
class Artifact(Entity):
    """A unit of content that can flow through collection and analysis.

    An `Artifact` is intentionally generic: it may represent a source
    repository, a module within a repository, a document, or any other
    unit that collectors discover and that analyzers, extractors and
    scorers subsequently process.

    Attributes:
        name: Human-readable name of the artifact.
        source_uri: Location the artifact was collected from.
        status: Current lifecycle status of the artifact.
        metadata: Freeform, structured metadata describing the artifact.
    """

    name: str
    source_uri: str
    status: ArtifactStatus = ArtifactStatus.PENDING
    metadata: Metadata = field(default_factory=Metadata.empty)
