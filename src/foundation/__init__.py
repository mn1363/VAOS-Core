"""Foundation bounded context: composes the analysis pipeline end-to-end."""

from foundation.interfaces import FoundationService
from foundation.models import FoundationReport

__all__ = ["FoundationReport", "FoundationService"]
