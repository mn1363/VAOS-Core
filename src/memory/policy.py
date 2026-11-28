from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from src.memory.base import MemoryRecord

# Memory is advisory. A record is eligible only when its type has a known,
# analyzer-specific meaning and its metadata explicitly marks it active,
# sufficiently confident, and in scope for that analyzer.
_ANALYZER_MEMORY_TYPES: Final[dict[str, frozenset[str]]] = {
    "architecture": frozenset({"architecture_decision", "architecture_constraint"}),
    "complexity": frozenset({"complexity_budget", "complexity_constraint"}),
    "dependency": frozenset({"dependency_constraint", "approved_dependency"}),
    "documentation": frozenset({"documentation_standard", "documentation_requirement"}),
    "metrics": frozenset({"metric_baseline", "metric_target"}),
    "quality": frozenset({"quality_standard", "quality_constraint"}),
    "security": frozenset({"security_policy", "security_constraint"}),
    "tests": frozenset({"test_convention", "test_requirement"}),
}
_MIN_CONFIDENCE: Final[float] = 0.8


def memory_is_eligible(record: MemoryRecord, *, analyzer: str) -> bool:
    """Return True only for active, high-confidence memory with an explicit analyzer scope.

    Required metadata:
      - status: exactly ``active``
      - confidence: numeric value in [0.8, 1.0], excluding bool
      - analysis_scopes: list/tuple containing the requested analyzer

    Unknown memory types and malformed metadata are rejected. Memory never
    overrides source evidence; this function only controls advisory context.
    """
    allowed_types = _ANALYZER_MEMORY_TYPES.get(analyzer)
    if allowed_types is None or record.memory_type not in allowed_types:
        return False

    metadata: Mapping[str, object] = record.metadata
    confidence = metadata.get("confidence")
    scopes = metadata.get("analysis_scopes")
    return (
        metadata.get("status") == "active"
        and isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and _MIN_CONFIDENCE <= confidence <= 1.0
        and isinstance(scopes, (list, tuple))
        and analyzer in scopes
    )


def select_memory_for_analyzer(
    records: tuple[MemoryRecord, ...], *, analyzer: str
) -> tuple[MemoryRecord, ...]:
    """Return deterministically ordered, eligible memory for one analyzer."""
    eligible = (record for record in records if memory_is_eligible(record, analyzer=analyzer))
    return tuple(sorted(eligible, key=lambda record: (record.memory_type, str(record.id))))
