"""Unit tests for `src.foundation.merger.base`."""

from uuid import UUID

import pytest
from src.core.exceptions import NotFoundError, ValidationError
from src.extractors.foundation.base import FoundationCandidate, FoundationCandidateKind
from src.foundation.comparer.base import (
    FoundationComparisonOutcome,
    FoundationComparisonVerdict,
    FoundationSubject,
)
from src.foundation.merger.base import (
    FoundationMember,
    FoundationMerger,
    FoundationResult,
    require_mergeable_selection,
    require_no_conflicting_selection,
)
from src.foundation.ranking.base import FoundationRanking, FoundationScore
from src.foundation.selector.base import FoundationSelectionResult

REPO_A = UUID("11111111-1111-1111-1111-111111111111")


def _member(subject_id: str = "a", score: float = 0.5) -> FoundationMember:
    """Build a minimal `FoundationMember` for use in merger tests."""
    return FoundationMember(
        subject_id=subject_id,
        repository_id=REPO_A,
        name="retry",
        kind=FoundationCandidateKind.FUNCTION,
        relative_path="a.py",
        score=score,
    )


def test_foundation_member_is_frozen() -> None:
    """`FoundationMember` should be immutable once constructed."""
    member = _member()
    with pytest.raises(AttributeError):
        member.score = 0.9  # type: ignore[misc]


def test_foundation_member_rejects_blank_subject_id() -> None:
    """A blank `subject_id` should raise."""
    with pytest.raises(ValidationError):
        FoundationMember(
            subject_id=" ",
            repository_id=REPO_A,
            name="retry",
            kind=FoundationCandidateKind.FUNCTION,
            relative_path="a.py",
            score=0.5,
        )


def test_foundation_member_rejects_blank_name() -> None:
    """A blank `name` should raise."""
    with pytest.raises(ValidationError):
        FoundationMember(
            subject_id="a",
            repository_id=REPO_A,
            name=" ",
            kind=FoundationCandidateKind.FUNCTION,
            relative_path="a.py",
            score=0.5,
        )


def test_foundation_member_rejects_blank_relative_path() -> None:
    """A blank `relative_path` should raise."""
    with pytest.raises(ValidationError):
        FoundationMember(
            subject_id="a",
            repository_id=REPO_A,
            name="retry",
            kind=FoundationCandidateKind.FUNCTION,
            relative_path=" ",
            score=0.5,
        )


def test_foundation_member_rejects_score_out_of_range() -> None:
    """A `score` outside `[0.0, 1.0]` should raise."""
    with pytest.raises(ValidationError):
        _member(score=-0.1)
    with pytest.raises(ValidationError):
        _member(score=1.1)


def test_foundation_result_defaults_to_empty() -> None:
    """A `FoundationResult` with no members should construct cleanly."""
    result = FoundationResult()
    assert result.member_count == 0


def test_foundation_result_accepts_correctly_ordered_members() -> None:
    """Members sorted by `(-score, subject_id)` should construct cleanly."""
    result = FoundationResult(
        members=(_member(subject_id="a", score=0.9), _member(subject_id="b", score=0.5))
    )
    assert result.member_count == 2


def test_foundation_result_rejects_members_out_of_score_order() -> None:
    """Members not sorted by descending `score` should raise."""
    with pytest.raises(ValidationError):
        FoundationResult(
            members=(_member(subject_id="a", score=0.5), _member(subject_id="b", score=0.9))
        )


def test_foundation_result_rejects_duplicate_members() -> None:
    """Two members sharing a `subject_id` should raise."""
    with pytest.raises(ValidationError):
        FoundationResult(
            members=(_member(subject_id="a", score=0.9), _member(subject_id="a", score=0.1))
        )


def test_foundation_result_get_member_returns_the_matching_member() -> None:
    """`get_member` should return the entry whose `subject_id` matches."""
    result = FoundationResult(members=(_member(subject_id="a"),))
    assert result.get_member("a").name == "retry"


def test_foundation_result_get_member_raises_for_an_unknown_subject() -> None:
    """`get_member` should raise `NotFoundError` for a `subject_id` absent from the result."""
    result = FoundationResult(members=(_member(subject_id="a"),))
    with pytest.raises(NotFoundError):
        result.get_member("does-not-exist")


def test_foundation_result_to_mapping_is_json_safe() -> None:
    """`to_mapping` should render members as plain dicts with primitive values."""
    result = FoundationResult(members=(_member(subject_id="a", score=0.75),))
    mapping = result.to_mapping()
    assert mapping == {
        "members": [
            {
                "subject_id": "a",
                "repository_id": str(REPO_A),
                "name": "retry",
                "kind": "function",
                "relative_path": "a.py",
                "score": 0.75,
            }
        ]
    }


def test_foundation_merger_cannot_be_instantiated_directly() -> None:
    """The abstract `FoundationMerger` Port must not be instantiable."""
    with pytest.raises(TypeError):
        FoundationMerger()  # type: ignore[abstract]


def test_require_mergeable_selection_accepts_known_subjects() -> None:
    """A selection whose selected ids are known to subjects and ranking should not raise."""
    subject = FoundationSubject(
        repository_id=REPO_A,
        candidate=FoundationCandidate(
            name="retry", kind=FoundationCandidateKind.FUNCTION, relative_path="a.py"
        ),
    )
    ranking = FoundationRanking(scores=(FoundationScore(subject_id=subject.subject_id, value=0.5),))
    selection = FoundationSelectionResult(selected_subject_ids=(subject.subject_id,))
    require_mergeable_selection([subject], ranking, selection)


def test_require_mergeable_selection_rejects_an_unknown_subject() -> None:
    """A selected id absent from `subjects` should raise."""
    selection = FoundationSelectionResult(selected_subject_ids=("unknown",))
    with pytest.raises(ValidationError):
        require_mergeable_selection([], FoundationRanking(), selection)


def test_require_mergeable_selection_rejects_a_selected_subject_missing_a_score() -> None:
    """A selected id present in `subjects` but absent from `ranking` should raise."""
    subject = FoundationSubject(
        repository_id=REPO_A,
        candidate=FoundationCandidate(
            name="retry", kind=FoundationCandidateKind.FUNCTION, relative_path="a.py"
        ),
    )
    selection = FoundationSelectionResult(selected_subject_ids=(subject.subject_id,))
    with pytest.raises(ValidationError):
        require_mergeable_selection([subject], FoundationRanking(), selection)


def test_require_no_conflicting_selection_passes_when_no_conflict_exists() -> None:
    """A selection with no `CONFLICTING` pair among it should not raise."""
    comparisons = (
        FoundationComparisonOutcome(
            left_subject_id="a", right_subject_id="b", verdict=FoundationComparisonVerdict.DISTINCT
        ),
    )
    require_no_conflicting_selection(["a", "b"], comparisons)


def test_require_no_conflicting_selection_rejects_a_conflicting_pair() -> None:
    """Two selected subjects compared as `CONFLICTING` should raise."""
    comparisons = (
        FoundationComparisonOutcome(
            left_subject_id="a",
            right_subject_id="b",
            verdict=FoundationComparisonVerdict.CONFLICTING,
        ),
    )
    with pytest.raises(ValidationError):
        require_no_conflicting_selection(["a", "b"], comparisons)


def test_require_no_conflicting_selection_ignores_a_conflict_outside_the_selection() -> None:
    """A `CONFLICTING` pair where only one side is selected should not raise."""
    comparisons = (
        FoundationComparisonOutcome(
            left_subject_id="a",
            right_subject_id="b",
            verdict=FoundationComparisonVerdict.CONFLICTING,
        ),
    )
    require_no_conflicting_selection(["a"], comparisons)
