"""`Collector` that validates and normalizes a GitHub repository reference."""

import re

from src.domain.entities import RepositoryProvider, SourceRepository

from .base import CollectionResult, Collector, require_source, strip_git_suffix

#: GitHub username/organization rule: alphanumeric or single hyphens, 1-39 characters, and
#: never starting or ending with a hyphen.
_OWNER = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"

#: GitHub repository name rule: alphanumeric, `.`, `_`, and `-`, 1-100 characters.
_REPO = r"[A-Za-z0-9._-]{1,100}"

_SLUG_PATTERN = re.compile(rf"^(?P<owner>{_OWNER})/(?P<repo>{_REPO})$")
_HTTPS_PATTERN = re.compile(rf"^https://github\.com/(?P<owner>{_OWNER})/(?P<repo>{_REPO})$")
_SSH_PATTERN = re.compile(rf"^git@github\.com:(?P<owner>{_OWNER})/(?P<repo>{_REPO})$")


class GitHubCollector(Collector):
    """Validates and normalizes a GitHub repository reference into a `SourceRepository`.

    Accepts three equivalent forms of `source`: the `"owner/repo"` shorthand, an
    `https://github.com/owner/repo` URL, and a `git@github.com:owner/repo.git` SSH URL (each
    with or without a trailing `.git` and a trailing slash). This collector makes no network
    request -- it only recognizes and canonicalizes well-formed references. Whether the
    repository actually exists is discovered later, when `repository.RepositoryClient.clone` is
    attempted against it.
    """

    @property
    def provider(self) -> RepositoryProvider:
        """The provider this collector produces entities for.

        Returns:
            `RepositoryProvider.GITHUB`.
        """
        return RepositoryProvider.GITHUB

    async def collect(self, source: str) -> CollectionResult:
        """Parse `source` as a GitHub repository reference.

        Args:
            source: A `"owner/repo"` slug, an `https://github.com/...` URL, or a
                `git@github.com:...` SSH URL.

        Returns:
            A result containing exactly one repository if `source` is a recognized GitHub
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
                source, f"not a valid GitHub repository reference: '{source}'"
            )
        owner, repo = match["owner"], match["repo"]
        repository = SourceRepository(
            name=repo,
            source_uri=f"https://github.com/{owner}/{repo}.git",
            provider=RepositoryProvider.GITHUB,
        )
        return CollectionResult.ok(source, [repository])
