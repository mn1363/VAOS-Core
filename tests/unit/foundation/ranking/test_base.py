"""Unit tests for `src.foundation.ranking.base`."""

from uuid import UUID

import pytest
from src.core.exceptions import NotFoundError, ValidationError
from src.extractors.foundation.base import FoundationCandidate, FoundationCandidateKind
from src.foundation.comparer.base import FoundationSubject
from src.foundation.ranking.base import (
    FoundationRanker,
    FoundationRanking,
    FoundationScore,
    require_unique_subjects,
)

REPO_A = UUID("11111111-1111-1111-1111-111111111111")


def _subject(name: str = "retry", relative_path: str = "a.py") -> FoundationSubject:
    """Build a minimal `FoundationSubject` for use in ranking tests."""
    return FoundationSubject(
        repository_id=REPO_A,
        candidate=FoundationCandidate(
            name=name, kind=FoundationCandidateKind.FUNCTION, relative_path=relative_path
        ),
    )


def test_foundation_score_defaults_rationale_to_empty() -> None:
    """`FoundationScore` should default `rationale` to an empty tuple."""
    score = FoundationScore(subject_id="a", value=0.5)
    assert score.rationale == ()


def test_foundation_score_is_frozen() -> None:
    """`FoundationScore` should be immutable once constructed."""
    score = FoundationScore(subject_id="a", value=0.5)
    with pytest.raises(AttributeError):
        score.value = 0.9  # type: ignore[misc]


def test_foundation_score_rejects_blank_subject_id() -> None:
    """A blank `subject_id` should raise."""
    with pytest.raises(ValidationError):
        FoundationScore(subject_id="  ", value=0.5)


def test_foundation_score_rejects_value_below_zero() -> None:
    """A `value` below `0.0` should raise."""
    with pytest.raises(ValidationError):
        FoundationScore(subject_id="a", value=-0.1)


def test_foundation_score_rejects_value_above_one() -> None:
    """A `value` above `1.0` should raise."""
    with pytest.raises(ValidationError):
        FoundationScore(subject_id="a", value=1.1)


def test_foundation_score_accepts_boundary_values() -> None:
    """`value` of exactly `0.0` and `1.0` should both be accepted."""
    assert FoundationScore(subject_id="a", value=0.0).value == 0.0
    assert FoundationScore(subject_id="a", value=1.0).value == 1.0


def test_foundation_ranking_defaults_to_empty() -> None:
    """A `FoundationRanking` with no scores should construct cleanly."""
    ranking = FoundationRanking()
    assert ranking.ranked_count == 0


def test_foundation_ranking_accepts_correctly_ordered_scores() -> None:
    """Scores sorted by `(-value, subject_id)` should construct cleanly."""
    ranking = FoundationRanking(
        scores=(
            FoundationScore(subject_id="a", value=0.9),
            FoundationScore(subject_id="b", value=0.5),
            FoundationScore(subject_id="c", value=0.5),
        )
    )
    assert ranking.ranked_count == 3


def test_foundation_ranking_rejects_scores_out_of_value_order() -> None:
    """Scores not sorted by descending `value` should raise."""
    with pytest.raises(ValidationError):
        FoundationRanking(
            scores=(
                FoundationScore(subject_id="a", value=0.5),
                FoundationScore(subject_id="b", value=0.9),
            )
        )


def test_foundation_ranking_rejects_ties_out_of_subject_id_order() -> None:
    """Tied scores not tie-broken by ascending `subject_id` should raise."""
    with pytest.raises(ValidationError):
        FoundationRanking(
            scores=(
                FoundationScore(subject_id="b", value=0.5),
                FoundationScore(subject_id="a", value=0.5),
            )
        )


def test_foundation_ranking_rejects_duplicate_subject_ids() -> None:
    """Two scores sharing a `subject_id` should raise."""
    with pytest.raises(ValidationError):
        FoundationRanking(
            scores=(
                FoundationScore(subject_id="a", value=0.9),
                FoundationScore(subject_id="a", value=0.1),
            )
        )


def _sample_ranking() -> FoundationRanking:
    """Build a small, valid three-entry `FoundationRanking` for reuse across tests."""
    return FoundationRanking(
        scores=(
            FoundationScore(subject_id="a", value=0.9),
            FoundationScore(subject_id="b", value=0.5),
            FoundationScore(subject_id="c", value=0.1),
        )
    )


def test_foundation_ranking_top_returns_the_first_n_entries() -> None:
    """`top` should return the `count` highest-scoring entries, in order."""
    ranking = _sample_ranking()
    assert [score.subject_id for score in ranking.top(2)] == ["a", "b"]


def test_foundation_ranking_top_beyond_length_returns_everything() -> None:
    """`top` given a `count` larger than `ranked_count` should return every entry."""
    ranking = _sample_ranking()
    assert len(ranking.top(100)) == 3


def test_foundation_ranking_top_rejects_negative_count() -> None:
    """`top` given a negative `count` should raise."""
    with pytest.raises(ValidationError):
        _sample_ranking().top(-1)


def test_foundation_ranking_score_for_returns_the_matching_score() -> None:
    """`score_for` should return the entry whose `subject_id` matches."""
    ranking = _sample_ranking()
    assert ranking.score_for("b").value == 0.5


def test_foundation_ranking_score_for_raises_for_an_unknown_subject() -> None:
    """`score_for` should raise `NotFoundError` for a `subject_id` not present in the ranking."""
    ranking = _sample_ranking()
    with pytest.raises(NotFoundError):
        ranking.score_for("does-not-exist")


def test_foundation_ranker_cannot_be_instantiated_directly() -> None:
    """The abstract `FoundationRanker` Port must not be instantiable."""
    with pytest.raises(TypeError):
        FoundationRanker()  # type: ignore[abstract]


def test_require_unique_subjects_returns_subjects_unchanged() -> None:
    """Given subjects with distinct `subject_id`s, the sequence should pass through unchanged."""
    subjects = [_subject(name="a"), _subject(name="b")]
    assert require_unique_subjects(subjects) is subjects


def test_require_unique_subjects_rejects_a_duplicate_subject_id() -> None:
    """Two subjects sharing a `subject_id` should raise."""
    subjects = [_subject(name="a"), _subject(name="a")]
    with pytest.raises(ValidationError):
        require_unique_subjects(subjects)
