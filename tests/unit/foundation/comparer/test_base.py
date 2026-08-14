"""Unit tests for `src.foundation.comparer.base`."""

from uuid import UUID

import pytest
from src.core.exceptions import ValidationError
from src.extractors.foundation.base import (
    FoundationCandidate,
    FoundationCandidateKind,
    FoundationExtractionResult,
)
from src.foundation.comparer.base import (
    FoundationComparer,
    FoundationComparisonOutcome,
    FoundationComparisonVerdict,
    FoundationSubject,
    build_subjects,
    compare_all,
    require_distinct_subjects,
    require_successful_foundation_extractions,
)

REPO_A = UUID("11111111-1111-1111-1111-111111111111")
REPO_B = UUID("22222222-2222-2222-2222-222222222222")


def _candidate(
    *,
    name: str = "retry",
    kind: FoundationCandidateKind = FoundationCandidateKind.FUNCTION,
    relative_path: str = "a.py",
    signals: tuple[str, ...] = (),
) -> FoundationCandidate:
    """Build a minimal `FoundationCandidate` for use in comparer tests."""
    return FoundationCandidate(
        name=name, kind=kind, relative_path=relative_path, signals=signals
    )


def _subject(
    *,
    repository_id: UUID = REPO_A,
    name: str = "retry",
    kind: FoundationCandidateKind = FoundationCandidateKind.FUNCTION,
    relative_path: str = "a.py",
    signals: tuple[str, ...] = (),
) -> FoundationSubject:
    """Build a minimal `FoundationSubject` for use in comparer tests."""
    return FoundationSubject(
        repository_id=repository_id,
        candidate=_candidate(name=name, kind=kind, relative_path=relative_path, signals=signals),
    )


class _FakeComparer(FoundationComparer):
    """A trivial `FoundationComparer` used only to exercise `compare_all`'s pairing logic."""

    def compare(
        self, left: FoundationSubject, right: FoundationSubject
    ) -> FoundationComparisonOutcome:
        """Always report `DISTINCT`, regardless of `left`/`right`'s actual signals."""
        require_distinct_subjects(left, right)
        return FoundationComparisonOutcome(
            left_subject_id=left.subject_id,
            right_subject_id=right.subject_id,
            verdict=FoundationComparisonVerdict.DISTINCT,
        )


def test_foundation_subject_subject_id_combines_repository_and_qualified_name() -> None:
    """`subject_id` should join `repository_id` to the candidate's qualified name."""
    subject = _subject(repository_id=REPO_A, name="retry", relative_path="a.py")
    assert subject.subject_id == f"{REPO_A}:a.py::retry"


def test_foundation_subject_is_frozen() -> None:
    """`FoundationSubject` should be immutable once constructed."""
    subject = _subject()
    with pytest.raises(AttributeError):
        subject.repository_id = REPO_B  # type: ignore[misc]


def test_foundation_subject_same_candidate_different_repository_differs() -> None:
    """Two subjects wrapping the same candidate but different repositories should differ."""
    left = _subject(repository_id=REPO_A)
    right = _subject(repository_id=REPO_B)
    assert left.subject_id != right.subject_id


def test_require_successful_foundation_extractions_returns_results_unchanged() -> None:
    """Given all-successful results, the sequence should pass through unchanged."""
    results = (
        FoundationExtractionResult.ok(relative_path="a.py", candidates=[_candidate()]),
        FoundationExtractionResult.ok(relative_path="b.py"),
    )
    assert require_successful_foundation_extractions(results) is results


def test_require_successful_foundation_extractions_rejects_any_failed_result() -> None:
    """A single failed entry anywhere in the sequence should raise."""
    results = (
        FoundationExtractionResult.ok(relative_path="a.py"),
        FoundationExtractionResult.failed(relative_path="b.py", error_message="bad"),
    )
    with pytest.raises(ValidationError):
        require_successful_foundation_extractions(results)


def test_build_subjects_flattens_candidates_across_files() -> None:
    """`build_subjects` should produce one subject per candidate across every extraction result."""
    results = (
        FoundationExtractionResult.ok(
            relative_path="a.py", candidates=[_candidate(name="retry", relative_path="a.py")]
        ),
        FoundationExtractionResult.ok(
            relative_path="b.py", candidates=[_candidate(name="fetch", relative_path="b.py")]
        ),
    )
    subjects = build_subjects(repository_id=REPO_A, extraction_results=results)
    assert len(subjects) == 2
    assert {subject.candidate.name for subject in subjects} == {"retry", "fetch"}


def test_build_subjects_sorts_by_subject_id() -> None:
    """`build_subjects` should return subjects sorted by `subject_id`, regardless of input order."""
    results = (
        FoundationExtractionResult.ok(
            relative_path="z.py", candidates=[_candidate(name="z_func", relative_path="z.py")]
        ),
        FoundationExtractionResult.ok(
            relative_path="a.py", candidates=[_candidate(name="a_func", relative_path="a.py")]
        ),
    )
    subjects = build_subjects(repository_id=REPO_A, extraction_results=results)
    assert [subject.subject_id for subject in subjects] == sorted(
        subject.subject_id for subject in subjects
    )
    assert subjects[0].candidate.name == "a_func"


def test_build_subjects_rejects_a_failed_extraction() -> None:
    """`build_subjects` should refuse to build from a failed `FoundationExtractionResult`."""
    results = (FoundationExtractionResult.failed(relative_path="a.py", error_message="bad"),)
    with pytest.raises(ValidationError):
        build_subjects(repository_id=REPO_A, extraction_results=results)


def test_build_subjects_rejects_duplicate_subject_ids() -> None:
    """`build_subjects` should refuse two candidates that resolve to the same `subject_id`."""
    duplicate = _candidate(name="retry", relative_path="a.py")
    results = (
        FoundationExtractionResult.ok(relative_path="a.py", candidates=[duplicate, duplicate]),
    )
    with pytest.raises(ValidationError):
        build_subjects(repository_id=REPO_A, extraction_results=results)


def test_build_subjects_empty_input_returns_empty_tuple() -> None:
    """`build_subjects` given no extraction results should return an empty tuple."""
    assert build_subjects(repository_id=REPO_A, extraction_results=()) == ()


def test_foundation_comparison_verdict_values() -> None:
    """`FoundationComparisonVerdict` members should stringify to their lower-cased names."""
    assert FoundationComparisonVerdict.EQUIVALENT.value == "equivalent"
    assert FoundationComparisonVerdict.COMPATIBLE.value == "compatible"
    assert FoundationComparisonVerdict.CONFLICTING.value == "conflicting"
    assert FoundationComparisonVerdict.DISTINCT.value == "distinct"


def test_foundation_comparison_outcome_accepts_a_valid_pair() -> None:
    """A well-formed outcome with sorted, deduplicated shared signals should construct cleanly."""
    outcome = FoundationComparisonOutcome(
        left_subject_id="a",
        right_subject_id="b",
        verdict=FoundationComparisonVerdict.COMPATIBLE,
        shared_signals=("decorated", "public"),
    )
    assert outcome.verdict is FoundationComparisonVerdict.COMPATIBLE


def test_foundation_comparison_outcome_rejects_blank_left_subject_id() -> None:
    """A blank `left_subject_id` should raise."""
    with pytest.raises(ValidationError):
        FoundationComparisonOutcome(
            left_subject_id="  ", right_subject_id="b", verdict=FoundationComparisonVerdict.DISTINCT
        )


def test_foundation_comparison_outcome_rejects_blank_right_subject_id() -> None:
    """A blank `right_subject_id` should raise."""
    with pytest.raises(ValidationError):
        FoundationComparisonOutcome(
            left_subject_id="a", right_subject_id=" ", verdict=FoundationComparisonVerdict.DISTINCT
        )


def test_foundation_comparison_outcome_rejects_equal_subject_ids() -> None:
    """A `left_subject_id` equal to `right_subject_id` should raise."""
    with pytest.raises(ValidationError):
        FoundationComparisonOutcome(
            left_subject_id="a", right_subject_id="a", verdict=FoundationComparisonVerdict.DISTINCT
        )


def test_foundation_comparison_outcome_rejects_unsorted_shared_signals() -> None:
    """Unsorted `shared_signals` should raise."""
    with pytest.raises(ValidationError):
        FoundationComparisonOutcome(
            left_subject_id="a",
            right_subject_id="b",
            verdict=FoundationComparisonVerdict.COMPATIBLE,
            shared_signals=("public", "decorated"),
        )


def test_foundation_comparison_outcome_rejects_duplicate_shared_signals() -> None:
    """Duplicate entries within `shared_signals` should raise."""
    with pytest.raises(ValidationError):
        FoundationComparisonOutcome(
            left_subject_id="a",
            right_subject_id="b",
            verdict=FoundationComparisonVerdict.COMPATIBLE,
            shared_signals=("public", "public"),
        )


def test_foundation_comparer_cannot_be_instantiated_directly() -> None:
    """The abstract `FoundationComparer` Port must not be instantiable."""
    with pytest.raises(TypeError):
        FoundationComparer()  # type: ignore[abstract]


def test_require_distinct_subjects_returns_the_pair_unchanged() -> None:
    """Given two different subjects, the pair should pass through unchanged."""
    left, right = _subject(name="retry"), _subject(name="fetch")
    assert require_distinct_subjects(left, right) == (left, right)


def test_require_distinct_subjects_rejects_a_subject_compared_to_itself() -> None:
    """Comparing a subject to an equal copy of itself should raise."""
    left = _subject(name="retry")
    right = _subject(name="retry")
    with pytest.raises(ValidationError):
        require_distinct_subjects(left, right)


def test_compare_all_covers_every_distinct_pair() -> None:
    """`compare_all` should produce one outcome per unordered pair of subjects."""
    subjects = [_subject(name="a"), _subject(name="b"), _subject(name="c")]
    outcomes = compare_all(_FakeComparer(), subjects)
    assert len(outcomes) == 3


def test_compare_all_is_deterministic_regardless_of_input_order() -> None:
    """`compare_all` should produce the same outcome order regardless of input order."""
    subjects = [_subject(name="a"), _subject(name="b"), _subject(name="c")]
    forward = compare_all(_FakeComparer(), subjects)
    backward = compare_all(_FakeComparer(), list(reversed(subjects)))
    assert [(o.left_subject_id, o.right_subject_id) for o in forward] == [
        (o.left_subject_id, o.right_subject_id) for o in backward
    ]


def test_compare_all_empty_input_returns_empty_tuple() -> None:
    """`compare_all` given zero or one subject should return an empty tuple."""
    assert compare_all(_FakeComparer(), []) == ()
    assert compare_all(_FakeComparer(), [_subject()]) == ()
