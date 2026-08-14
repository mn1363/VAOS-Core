"""Foundation ranking Port: deterministic candidate scoring and ranking.

`FoundationRanker` turns a sequence of `foundation.comparer.base.FoundationSubject`s into a
`FoundationRanking` -- one `FoundationScore` per subject, ordered deterministically from most to
least worth reusing. It does not compare candidates pairwise (that is `foundation.comparer`'s
concern, consumed here only via the `FoundationSubject`s it produces) and does not decide which
candidates are actually selected -- that is `foundation.selector`'s concern, which consumes a
`FoundationRanking` as one of its own inputs.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from src.core.exceptions import NotFoundError, ValidationError
from src.core.logging import get_logger
from src.foundation.comparer.base import FoundationSubject

_logger = get_logger("foundation.ranking")


@dataclass(frozen=True, slots=True)
class FoundationScore:
    """A single subject's deterministic reuse-worthiness score.

    Attributes:
        subject_id: `FoundationSubject.subject_id` this score is about.
        value: The subject's score, normalized to `[0.0, 1.0]` -- higher means more worth
            reusing. The exact scoring formula is a concrete `FoundationRanker`'s own decision;
            only the normalized range is fixed here, so every ranking is comparable regardless of
            which concrete formula produced it.
        rationale: Freeform, human-readable observations supporting this score (e.g. `"public
            with a docstring"`, `"no observed signals"`), for a consumer that wants to know *why*
            without re-deriving it -- the same role `FoundationCandidate.signals` plays one layer
            down.
    """

    subject_id: str
    value: float
    rationale: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate that `subject_id` is non-blank and `value` is within range.

        Raises:
            ValidationError: If `subject_id` is blank, or `value` falls outside `[0.0, 1.0]`.
        """
        if not self.subject_id.strip():
            raise ValidationError("FoundationScore: subject_id must not be empty")
        if not 0.0 <= self.value <= 1.0:
            raise ValidationError("FoundationScore: value must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class FoundationRanking:
    """A deterministically ordered set of `FoundationScore`s, one per ranked subject.

    Attributes:
        scores: Every subject's score, sorted by `(-value, subject_id)` -- highest score first,
            ties broken by ascending `subject_id` -- so the result is deterministic regardless of
            input order and independent of any particular sort's stability.
    """

    scores: tuple[FoundationScore, ...] = ()

    def __post_init__(self) -> None:
        """Validate that `scores` is sorted by `(-value, subject_id)` and free of duplicates.

        Raises:
            ValidationError: If `scores` is not in `(-value, subject_id)` order, or contains two
                entries with the same `subject_id`.
        """
        sort_keys = [(-score.value, score.subject_id) for score in self.scores]
        if sort_keys != sorted(sort_keys):
            raise ValidationError(
                "FoundationRanking: scores must be sorted by (-value, subject_id)"
            )
        subject_ids = [score.subject_id for score in self.scores]
        if len(set(subject_ids)) != len(subject_ids):
            raise ValidationError("FoundationRanking: scores must not contain duplicate subjects")

    @property
    def ranked_count(self) -> int:
        """Total number of subjects covered by this ranking."""
        return len(self.scores)

    def top(self, count: int) -> tuple[FoundationScore, ...]:
        """Retrieve the `count` highest-scoring entries.

        Args:
            count: How many entries to return. Values greater than `ranked_count` return every
                entry.

        Returns:
            The first `count` entries of `scores`, in existing order.

        Raises:
            ValidationError: If `count` is negative.
        """
        if count < 0:
            raise ValidationError("FoundationRanking.top: count must not be negative")
        return self.scores[:count]

    def score_for(self, subject_id: str) -> FoundationScore:
        """Retrieve a single subject's score by its `subject_id`.

        Args:
            subject_id: The `FoundationSubject.subject_id` to look up.

        Returns:
            The matching `FoundationScore`.

        Raises:
            NotFoundError: If no entry in `scores` has that `subject_id`.
        """
        for score in self.scores:
            if score.subject_id == subject_id:
                return score
        raise NotFoundError(f"no FoundationScore for subject_id '{subject_id}' in this ranking")


class FoundationRanker(ABC):
    """Scores and ranks every subject in a sequence of `FoundationSubject`s.

    A concrete implementation decides the exact deterministic formula combining each subject's
    `FoundationCandidate` fields (`is_public`, `has_docstring`, `signals`) into a `FoundationScore.
    value`; it does not compare subjects pairwise or select/merge/export any of them -- those are
    `foundation.comparer`, `foundation.selector`, `foundation.merger`, and `foundation.exporter`'s
    concerns respectively.
    """

    @abstractmethod
    def rank(self, subjects: Sequence[FoundationSubject]) -> FoundationRanking:
        """Score and rank every subject in `subjects`.

        Args:
            subjects: The subjects to rank, drawn from one or more repositories. Must not
                contain two subjects with the same `subject_id` -- see `require_unique_subjects`.

        Returns:
            A `FoundationRanking` with exactly one `FoundationScore` per entry in `subjects`,
            sorted per `FoundationRanking.__post_init__`.

        Raises:
            ValidationError: If `subjects` contains a duplicate `subject_id` -- see
                `require_unique_subjects`.
        """
        ...


def require_unique_subjects(subjects: Sequence[FoundationSubject]) -> Sequence[FoundationSubject]:
    """Validate that no two entries in `subjects` share a `subject_id`.

    Every `FoundationRanker.rank` implementation calls this first, so a caller error (the same
    subject appearing twice) is reported the same way -- as an immediate `ValidationError` --
    across every implementation.

    Args:
        subjects: The raw `subjects` argument passed to `rank`.

    Returns:
        `subjects`, unchanged.

    Raises:
        ValidationError: If any two entries in `subjects` share a `subject_id`.
    """
    subject_ids = [subject.subject_id for subject in subjects]
    if len(set(subject_ids)) != len(subject_ids):
        _logger.debug("Rejected ranking of subjects containing a duplicate subject_id")
        raise ValidationError("cannot rank subjects containing a duplicate subject_id")
    return subjects
