"""`Collector` that validates and normalizes a GitLab repository reference."""

import re

from src.domain.entities import RepositoryProvider, SourceRepository

from .base import CollectionResult, Collector, require_source, strip_git_suffix

#: GitLab namespace/project path segment rule: alphanumeric, `.`, `_`, and `-`, 1-100 characters.
_SEGMENT = r"[A-Za-z0-9._-]{1,100}"

#: A GitLab project path: at least one namespace segment followed by a project segment. Unlike
#: GitHub's flat `owner/repo`, GitLab allows arbitrarily nested groups and subgroups.
_PATH = rf"{_SEGMENT}(?:/{_SEGMENT})+"

_SLUG_PATTERN = re.compile(rf"^(?P<path>{_PATH})$")
_HTTPS_PATTERN = re.compile(rf"^https://gitlab\.com/(?P<path>{_PATH})$")
_SSH_PATTERN = re.compile(rf"^git@gitlab\.com:(?P<path>{_PATH})$")


class GitLabCollector(Collector):
    """Validates and normalizes a GitLab repository reference into a `SourceRepository`.

    Accepts the same three forms as `GitHubCollector` -- a bare path, an
    `https://gitlab.com/...` URL, and a `git@gitlab.com:...` SSH URL -- except the path may
    contain any number of `/`-separated namespace segments (`group/subgroup/project`), since
    GitLab, unlike GitHub, allows arbitrarily nested groups. Like `GitHubCollector`, this makes
    no network request.
    """

    @property
    def provider(self) -> RepositoryProvider:
        """The provider this collector produces entities for.

        Returns:
            `RepositoryProvider.GITLAB`.
        """
        return RepositoryProvider.GITLAB

    async def collect(self, source: str) -> CollectionResult:
        """Parse `source` as a GitLab repository reference.

        Args:
            source: A `group[/subgroup...]/project` path, an `https://gitlab.com/...` URL, or a
                `git@gitlab.com:...` SSH URL.

        Returns:
            A result containing exactly one repository if `source` is a recognized GitLab
            reference, or a failed result otherwise.

        Raises:
            ValidationError: If `source` is blank.
        """
        require_source(source)
        candidate = strip_git_suffix(source.strip().rstrip("/"))
        match = (
            _HTTPS_PATTERN.match(candidate)
            or _SSH_PATTERN.match(candidate)
            or _SLUG_PATTERN.match(candidate)
        )
        if match is None:
            return CollectionResult.failed(
                source, f"not a valid GitLab repository reference: '{source}'"
            )
        path = match["path"]
        name = path.rsplit("/", maxsplit=1)[-1]
        repository = SourceRepository(
            name=name,
            source_uri=f"https://gitlab.com/{path}.git",
            provider=RepositoryProvider.GITLAB,
        )
        return CollectionResult.ok(source, [repository])
