"""Foundation selector Port: constraint- and compatibility-aware candidate selection.

`FoundationSelector` turns a `foundation.ranking.base.FoundationRanking` into a
`FoundationSelectionResult` -- which subjects are actually selected, and why every other subject
was rejected -- honoring an explicit `FoundationSelectionPolicy` (score/capacity/kind
constraints) and the pairwise compatibility already established by `foundation.comparer.base.
FoundationComparisonOutcome`s (no two subjects compared as `CONFLICTING` may both be selected). It
does not itself score subjects (that is `foundation.ranking`'s concern, consumed here only via the
`FoundationRanking` it produces) and does not merge or export the selection -- those are
`foundation.merger` and `foundation.exporter`'s concerns.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum, auto

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.extractors.foundation.base import FoundationCandidateKind
from src.foundation.comparer.base import FoundationComparisonOutcome, FoundationSubject
from src.foundation.ranking.base import FoundationRanking

_logger = get_logger("foundation.selector")


@dataclass(frozen=True, slots=True)
class FoundationSelectionPolicy:
    """Explicit, deterministic constraints governing which subjects may be selected.

    Every field is a plain, serializable value -- no callback or predicate -- so a policy can be
    logged, stored, and compared for equality like any other DTO in this codebase, per the
    "serializable where applicable" and "free of hidden global state" requirements.

    Attributes:
        minimum_score: Minimum `FoundationScore.value` a subject must have to be eligible.
            Defaults to `0.0` (no minimum).
        maximum_selected: Maximum number of subjects that may be selected. `None` means no cap.
        required_kind: If set, restricts eligible subjects to this `FoundationCandidateKind`
            only. `None` means both `CLASS` and `FUNCTION` are eligible.
    """

    minimum_score: float = 0.0
    maximum_selected: int | None = None
    required_kind: FoundationCandidateKind | None = None

    def __post_init__(self) -> None:
        """Validate that `minimum_score` and `maximum_selected` are within range.

        Raises:
            ValidationError: If `minimum_score` falls outside `[0.0, 1.0]`, or `maximum_selected`
                is set to a non-positive value.
        """
        if not 0.0 <= self.minimum_score <= 1.0:
            raise ValidationError(
                "FoundationSelectionPolicy: minimum_score must be between 0.0 and 1.0"
            )
        if self.maximum_selected is not None and self.maximum_selected <= 0:
            raise ValidationError(
                "FoundationSelectionPolicy: maximum_selected must be positive when set"
            )


class FoundationRejectionReason(StrEnum):
    """Why a subject was not selected, per `FoundationSelectionResult.rejections`."""

    BELOW_MINIMUM_SCORE = auto()
    """The subject's `FoundationScore.value` was below `FoundationSelectionPolicy.
    minimum_score`."""

    KIND_MISMATCH = auto()
    """`FoundationSelectionPolicy.required_kind` was set and the subject's `FoundationCandidate.
    kind` did not match it."""

    CONFLICTING_WITH_SELECTED = auto()
    """The subject was compared as `CONFLICTING` (see `foundation.comparer.base.
    FoundationComparisonVerdict`) against a subject already selected."""

    CAPACITY_EXCEEDED = auto()
    """The subject was otherwise eligible, but `FoundationSelectionPolicy.maximum_selected` was
    already reached by higher-ranked subjects."""


@dataclass(frozen=True, slots=True)
class FoundationRejection:
    """A single subject's exclusion from selection, with its reason.

    Attributes:
        subject_id: `FoundationSubject.subject_id` of the rejected subject.
        reason: The category of constraint that excluded it.
        message: Human-readable detail, e.g. naming the conflicting subject or the policy value
            that was not met.
    """

    subject_id: str
    reason: FoundationRejectionReason
    message: str

    def __post_init__(self) -> None:
        """Validate that `subject_id` and `message` are non-blank.

        Raises:
            ValidationError: If `subject_id` or `message` is blank.
        """
        if not self.subject_id.strip():
            raise ValidationError("FoundationRejection: subject_id must not be empty")
        if not self.message.strip():
            raise ValidationError("FoundationRejection: message must not be empty")


@dataclass(frozen=True, slots=True)
class FoundationSelectionResult:
    """The outcome of one `FoundationSelector.select` call.

    Attributes:
        selected_subject_ids: `subject_id`s of every selected subject, lexicographically sorted
            and free of duplicates.
        rejections: One `FoundationRejection` per excluded subject, sorted by `subject_id` and
            free of duplicate `subject_id`s. A `subject_id` appears in exactly one of
            `selected_subject_ids` or `rejections`, never both.
    """

    selected_subject_ids: tuple[str, ...] = ()
    rejections: tuple[FoundationRejection, ...] = ()

    def __post_init__(self) -> None:
        """Validate sort order, uniqueness, and that selection and rejection do not overlap.

        Raises:
            ValidationError: If `selected_subject_ids` is not sorted or contains a duplicate, if
                `rejections` is not sorted by `subject_id` or contains a duplicate `subject_id`,
                or if any `subject_id` appears in both `selected_subject_ids` and `rejections`.
        """
        if list(self.selected_subject_ids) != sorted(set(self.selected_subject_ids)):
            raise ValidationError(
                "FoundationSelectionResult: selected_subject_ids must be sorted and free of "
                "duplicates"
            )
        rejection_ids = [rejection.subject_id for rejection in self.rejections]
        if rejection_ids != sorted(rejection_ids) or len(set(rejection_ids)) != len(
            rejection_ids
        ):
            raise ValidationError(
                "FoundationSelectionResult: rejections must be sorted by subject_id and free of "
                "duplicates"
            )
        overlap = set(self.selected_subject_ids) & set(rejection_ids)
        if overlap:
            raise ValidationError(
                "FoundationSelectionResult: a subject cannot be both selected and rejected",
                details={"subject_ids": sorted(overlap)},
            )

    @property
    def selected_count(self) -> int:
        """Total number of selected subjects."""
        return len(self.selected_subject_ids)

    def is_selected(self, subject_id: str) -> bool:
        """Check whether a given subject was selected.

        Args:
            subject_id: The `FoundationSubject.subject_id` to check.

        Returns:
            True if `subject_id` is in `selected_subject_ids`.
        """
        return subject_id in self.selected_subject_ids


class FoundationSelector(ABC):
    """Selects which ranked subjects to keep, honoring an explicit policy and known conflicts.

    A concrete implementation decides the exact selection algorithm (e.g. greedily walking
    `ranking` in score order); it does not score subjects or merge/export the result -- those are
    `foundation.ranking`, `foundation.merger`, and `foundation.exporter`'s concerns respectively.
    """

    @abstractmethod
    def select(
        self,
        subjects: Sequence[FoundationSubject],
        ranking: FoundationRanking,
        comparisons: Sequence[FoundationComparisonOutcome],
        policy: FoundationSelectionPolicy,
    ) -> FoundationSelectionResult:
        """Select which subjects to keep, from `subjects`, honoring `policy` and `comparisons`.

        Args:
            subjects: Every candidate under consideration.
            ranking: `subjects`' scores, used both to filter against `policy.minimum_score` and
                to break ties deterministically when `policy.maximum_selected` forces a choice
                among equally eligible subjects.
            comparisons: Pairwise comparisons among `subjects`, used to enforce that no two
                selected subjects were compared as `CONFLICTING`.
            policy: The constraints selection must honor.

        Returns:
            A `FoundationSelectionResult` covering every entry in `subjects` exactly once, either
            selected or rejected with a reason.

        Raises:
            ValidationError: If `ranking` or `comparisons` references a `subject_id` absent from
                `subjects` -- see `require_consistent_inputs`.
        """
        ...


def require_consistent_inputs(
    subjects: Sequence[FoundationSubject],
    ranking: FoundationRanking,
    comparisons: Sequence[FoundationComparisonOutcome],
) -> None:
    """Validate that `ranking` and `comparisons` reference only `subject_id`s present in
    `subjects`.

    Every `FoundationSelector.select` implementation calls this first, so a caller error (a
    ranking or comparison built from a different subject set than the one being selected from) is
    reported the same way -- as an immediate `ValidationError` -- across every implementation.

    Args:
        subjects: The raw `subjects` argument passed to `select`.
        ranking: The raw `ranking` argument passed to `select`.
        comparisons: The raw `comparisons` argument passed to `select`.

    Raises:
        ValidationError: If any `ranking.scores` or `comparisons` entry references a `subject_id`
            not present in `subjects`.
    """
    known = {subject.subject_id for subject in subjects}
    for score in ranking.scores:
        if score.subject_id not in known:
            _logger.debug(
                "Rejected selection: ranking references unknown subject '%s'", score.subject_id
            )
            raise ValidationError(
                "ranking references a subject_id absent from subjects",
                details={"subject_id": score.subject_id},
            )
    for outcome in comparisons:
        for subject_id in (outcome.left_subject_id, outcome.right_subject_id):
            if subject_id not in known:
                _logger.debug(
                    "Rejected selection: comparison references unknown subject '%s'", subject_id
                )
                raise ValidationError(
                    "a comparison references a subject_id absent from subjects",
                    details={"subject_id": subject_id},
                )
