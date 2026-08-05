"""Vector subsystem: Port and data structures for embedding storage."""

from vector.interfaces import VectorStore
from vector.models import VectorMatch, VectorRecord

__all__ = ["VectorMatch", "VectorRecord", "VectorStore"]
