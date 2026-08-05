"""Strongly-typed identifier wrappers used throughout the domain."""

from typing import NewType
from uuid import UUID

#: Identifier for an `Artifact` entity, distinguished at the type level
#: from other UUID-based identifiers to prevent accidental mixing.
ArtifactId = NewType("ArtifactId", UUID)

#: Identifier for an `AnalysisResult` entity.
AnalysisResultId = NewType("AnalysisResultId", UUID)

#: Identifier for a `Task` entity.
TaskId = NewType("TaskId", UUID)

#: Identifier for a `PluginDescriptor` entity.
PluginId = NewType("PluginId", UUID)
