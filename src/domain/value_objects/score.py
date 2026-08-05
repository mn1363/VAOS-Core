"""The `Score` value object: an immutable, dimensioned numeric outcome."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Score:
    """An immutable score with an optional per-dimension breakdown.

    Attributes:
        value: The overall score value.
        max_value: The maximum possible value the score could take.
        breakdown: Optional mapping of named sub-scores that compose the
            overall value.
    """

    value: float
    max_value: float
    breakdown: dict[str, float] = field(default_factory=dict)
