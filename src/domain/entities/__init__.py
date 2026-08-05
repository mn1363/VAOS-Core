"""Domain entities: the core business objects of VAOS."""

from domain.entities.analysis import AnalysisResult
from domain.entities.artifact import Artifact
from domain.entities.base import Entity
from domain.entities.plugin import PluginDescriptor
from domain.entities.task import Task

__all__ = ["AnalysisResult", "Artifact", "Entity", "PluginDescriptor", "Task"]
