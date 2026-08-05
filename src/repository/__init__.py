"""Repository subsystem: Ports and scaffolding for persistence adapters.

`Repository` is re-exported directly from `domain.repositories` (the single
source of truth for this Port) so storage-adapter implementers can depend
on `repository` alone without reaching into `domain` themselves.
"""

from domain.repositories.interfaces import Repository
from repository.base import AbstractRepository

__all__ = ["AbstractRepository", "Repository"]
