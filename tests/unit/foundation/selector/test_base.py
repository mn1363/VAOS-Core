"""Unit tests for `src.foundation.selector.base`."""

from uuid import UUID

import pytest
from src.core.exceptions import ValidationError
from src.extractors.foundation.base import FoundationCandidate, FoundationCandidateKind
from src.foundation.comparer.base import (
    FoundationComparisonOutcome,
    FoundationComparisonVerdict,
    FoundationSubject,
)
from src.foundation.ranking.base import FoundationRanking, FoundationScore
from src.foundation.selector.base import (
    FoundationRejection,
    FoundationRejectionReason,
    FoundationSelectionPolicy,
    FoundationSelectionResult,
    FoundationSelector,
    require_consistent_inputs,
)

REPO_A = UUID("11111111-1111-1111-1111-111111111111")


def _subject(name: str = "retry", relative_path: str = "a.py") -> FoundationSubject:
    """Build a minimal `FoundationSubject` for use in selector tests."""
    return FoundationSubject(
        repository_id=REPO_A,
        candidate=FoundationCandidate(
            name=name, kind=FoundationCandidateKind.FUNCTION, relative_path=relative_path
        ),
    )


def test_foundation_selection_policy_defaults() -> None:
    """`FoundationSelectionPolicy` should default to no constraints."""
    policy = FoundationSelectionPolicy()
    assert policy.minimum_score == 0.0
    assert policy.maximum_selected is None
    assert policy.required_kind is None


def test_foundation_selection_policy_is_frozen() -> None:
    """`FoundationSelectionPolicy` should be immutable once constructed."""
    policy = FoundationSelectionPolicy()
    with pytest.raises(AttributeError):
        policy.minimum_score = 0.9  # type: ignore[misc]


def test_foundation_selection_policy_rejects_minimum_score_below_zero() -> None:
    """A `minimum_score` below `0.0` should raise."""
    with pytest.raises(ValidationError):
        FoundationSelectionPolicy(minimum_score=-0.1)


def test_foundation_selection_policy_rejects_minimum_score_above_one() -> None:
    """A `minimum_score` above `1.0` should raise."""
    with pytest.raises(ValidationError):
        FoundationSelectionPolicy(minimum_score=1.1)


def test_foundation_selection_policy_rejects_non_positive_maximum_selected() -> None:
    """A `maximum_selected` of zero or less should raise."""
    with pytest.raises(ValidationError):
        FoundationSelectionPolicy(maximum_selected=0)
    with pytest.raises(ValidationError):
        FoundationSelectionPolicy(maximum_selected=-1)


def test_foundation_selection_policy_accepts_a_positive_maximum_selected() -> None:
    """A positive `maximum_selected` should be accepted."""
    assert FoundationSelectionPolicy(maximum_selected=5).maximum_selected == 5


def test_foundation_rejection_rejects_blank_subject_id() -> None:
    """A blank `subject_id` should raise."""
    with pytest.raises(ValidationError):
        FoundationRejection(
            subject_id=" ", reason=FoundationRejectionReason.BELOW_MINIMUM_SCORE, message="too low"
        )


def test_foundation_rejection_rejects_blank_message() -> None:
    """A blank `message` should raise."""
    with pytest.raises(ValidationError):
        FoundationRejection(
            subject_id="a", reason=FoundationRejectionReason.BELOW_MINIMUM_SCORE, message=" "
        )


def test_foundation_selection_result_defaults_to_empty() -> None:
    """A `FoundationSelectionResult` with nothing selected or rejected should construct cleanly."""
    result = FoundationSelectionResult()
    assert result.selected_count == 0


def test_foundation_selection_result_accepts_a_valid_split() -> None:
    """A well-formed, sorted, non-overlapping selection/rejection split should construct cleanly."""
    result = FoundationSelectionResult(
        selected_subject_ids=("a", "c"),
        rejections=(
            FoundationRejection(
                subject_id="b",
                reason=FoundationRejectionReason.BELOW_MINIMUM_SCORE,
                message="too low",
            ),
        ),
    )
    assert result.selected_count == 2
    assert result.is_selected("a") is True
    assert result.is_selected("b") is False


def test_foundation_selection_result_rejects_unsorted_selected_ids() -> None:
    """`selected_subject_ids` out of sorted order should raise."""
    with pytest.raises(ValidationError):
        FoundationSelectionResult(selected_subject_ids=("b", "a"))


def test_foundation_selection_result_rejects_duplicate_selected_ids() -> None:
    """A duplicate entry in `selected_subject_ids` should raise."""
    with pytest.raises(ValidationError):
        FoundationSelectionResult(selected_subject_ids=("a", "a"))


def test_foundation_selection_result_rejects_unsorted_rejections() -> None:
    """`rejections` out of `subject_id` order should raise."""
    with pytest.raises(ValidationError):
        FoundationSelectionResult(
            rejections=(
                FoundationRejection(
                    subject_id="b",
                    reason=FoundationRejectionReason.BELOW_MINIMUM_SCORE,
                    message="x",
                ),
                FoundationRejection(
                    subject_id="a",
                    reason=FoundationRejectionReason.BELOW_MINIMUM_SCORE,
                    message="x",
                ),
            )
        )


def test_foundation_selection_result_rejects_duplicate_rejection_ids() -> None:
    """Two rejections sharing a `subject_id` should raise."""
    with pytest.raises(ValidationError):
        FoundationSelectionResult(
            rejections=(
                FoundationRejection(
                    subject_id="a",
                    reason=FoundationRejectionReason.BELOW_MINIMUM_SCORE,
                    message="x",
                ),
                FoundationRejection(
                    subject_id="a",
                    reason=FoundationRejectionReason.CAPACITY_EXCEEDED,
                    message="y",
                ),
            )
        )


def test_foundation_selection_result_rejects_overlap_between_selected_and_rejected() -> None:
    """A `subject_id` present in both `selected_subject_ids` and `rejections` should raise."""
    with pytest.raises(ValidationError):
        FoundationSelectionResult(
            selected_subject_ids=("a",),
            rejections=(
                FoundationRejection(
                    subject_id="a",
                    reason=FoundationRejectionReason.BELOW_MINIMUM_SCORE,
                    message="x",
                ),
            ),
        )


def test_foundation_selector_cannot_be_instantiated_directly() -> None:
    """The abstract `FoundationSelector` Port must not be instantiable."""
    with pytest.raises(TypeError):
        FoundationSelector()  # type: ignore[abstract]


def test_require_consistent_inputs_accepts_matching_data() -> None:
    """Ranking and comparisons referencing only known subjects should not raise."""
    subjects = [_subject(name="a"), _subject(name="b")]
    ranking = FoundationRanking(
        scores=(
            FoundationScore(subject_id=subjects[0].subject_id, value=0.9),
            FoundationScore(subject_id=subjects[1].subject_id, value=0.1),
        )
    )
    comparisons = (
        FoundationComparisonOutcome(
            left_subject_id=subjects[0].subject_id,
            right_subject_id=subjects[1].subject_id,
            verdict=FoundationComparisonVerdict.DISTINCT,
        ),
    )
    require_consistent_inputs(subjects, ranking, comparisons)


def test_require_consistent_inputs_rejects_an_unknown_ranking_subject() -> None:
    """A ranking entry naming a subject absent from `subjects` should raise."""
    subjects = [_subject(name="a")]
    ranking = FoundationRanking(scores=(FoundationScore(subject_id="unknown", value=0.5),))
    with pytest.raises(ValidationError):
        require_consistent_inputs(subjects, ranking, ())


def test_require_consistent_inputs_rejects_an_unknown_comparison_subject() -> None:
    """A comparison naming a subject absent from `subjects` should raise."""
    subjects = [_subject(name="a")]
    comparisons = (
        FoundationComparisonOutcome(
            left_subject_id=subjects[0].subject_id,
            right_subject_id="unknown",
            verdict=FoundationComparisonVerdict.DISTINCT,
        ),
    )
    with pytest.raises(ValidationError):
        require_consistent_inputs(subjects, FoundationRanking(), comparisons)
