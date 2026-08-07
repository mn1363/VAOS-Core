"""Collectors layer: discovers candidate `SourceRepository` entities from external sources.

`collectors` decides *which* repositories exist at a given source location -- a single local
directory, a directory tree to scan, or a hosted-repository reference -- and describes each one
as a `SourceRepository` domain entity. It does not fetch a repository's contents onto disk (that
is `repository`, already built) and does not persist entities to a store (that is `storage`, a
later phase); both are deliberately out of scope here, matching the frozen separation between
these packages.

It defines the abstract `Collector` Port and the `CollectionResult` outcome DTO in `base.py`, and
provides one concrete `Collector` per `RepositoryProvider` value: `FilesystemCollector`,
`LocalCollector`, `GitHubCollector`, and `GitLabCollector`.

Each module here is self-contained and imported directly by its full path (e.g. `from
src.collectors.local import LocalCollector`); this package intentionally does not re-export a
combined surface from `__init__.py`.
"""
