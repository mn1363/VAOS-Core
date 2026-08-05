"""Concrete pipeline orchestration built on top of application Ports."""

from application.pipeline.sequential import SequentialPipeline
from application.pipeline.stage import BasePipelineStage

__all__ = ["BasePipelineStage", "SequentialPipeline"]
