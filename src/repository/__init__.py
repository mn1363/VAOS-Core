"""Repository layer: git repository access and local workspace management.

`repository` is an infrastructure-adjacent layer that may depend on `core`
and `domain`, but not on any other VAOS layer. It defines the abstract
`RepositoryClient` and `WorkspaceManager` Ports in `base.py`, and provides
one concrete implementation of each: `GitRepositoryClient` (shells out to
the system `git` executable) and `FilesystemWorkspaceManager` (allocates
one local directory per repository).

This package answers "how do I get a local, working copy of a
`SourceRepository` on disk, and where does it live" -- it does not decide
*which* repositories to collect (that is `collectors`, a later phase) nor
how to persist domain entities to a database (that is `storage`, also a
later phase). Each module here is self-contained and imported directly by
its full path (e.g. `from src.repository.git import GitRepositoryClient`);
this package intentionally does not re-export a combined surface from
`__init__.py`.
"""
