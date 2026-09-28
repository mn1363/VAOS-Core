"""Structural architecture graph builder: the first concrete `ArchitectureGraphBuilder`
implementation.

`StructuralArchitectureGraphBuilder` assembles many files' already-extracted `PackageUnit`s
(carried by `ArchitectureExtractionResult`s) into one repository-wide `ArchitectureGraph`, using
nothing but each unit's own `package_path`, `relative_path`, and `is_package_root`: packages are
grouped by `package_path`, every ancestor package implied by nesting is added so the tree is
connected back to the repository root, and each non-root package is linked to its immediate
parent. It performs no path normalization, no module resolution, no interpretation of
`declared_modules`, no scoring, and no cross-file analysis beyond that grouping; see
`ArchitectureGraphBuilder`'s own docstring in `base.py` for what is deliberately out of scope.
"""

from collections.abc import Sequence

from src.extractors.architecture.base import ArchitectureExtractionResult
from src.graph.architecture.base import (
    ArchitectureGraph,
    ArchitectureGraphBuilder,
    PackageContainmentEdge,
    PackageNode,
    ancestor_package_paths,
    require_successful_extractions,
)


class StructuralArchitectureGraphBuilder(ArchitectureGraphBuilder):
    """Assembles `PackageUnit`s into a package containment tree, one node per package.

    Stateless and dependency-free: no `__init__` override, and a single instance may be reused
    across any number of `build` calls. The builder is separator-agnostic -- it trusts each
    `PackageUnit`'s `package_path` and `relative_path` exactly as supplied, and never splits,
    joins, or rewrites either of them.
    """

    def build(
        self, extraction_results: Sequence[ArchitectureExtractionResult]
    ) -> ArchitectureGraph:
        """Assemble an `ArchitectureGraph` from many files' architectural placements.

        Args:
            extraction_results: The outcomes of extracting architectural placement for every
                file under consideration, as produced by `src.extractors.architecture`. Every
                entry must be successful.

        Returns:
            An empty `ArchitectureGraph` for empty input. Otherwise a graph with one
            `PackageNode` per distinct `unit.package_path` -- plus one for every ancestor of
            each (including the repository root, `()`) -- sorted by `package_path` tuple. A
            node's `file_paths` is the sorted, deduplicated `unit.relative_path`s of the units
            placed directly in it (empty for an ancestor no unit belongs to), and its
            `has_package_root_file` is True if any of those units has `is_package_root` set.
            `edges` holds exactly one `PackageContainmentEdge` per non-root node, from its
            immediate parent, sorted by `(parent_path, child_path)`.
            `PackageUnit.declared_modules` plays no part in the result.

        Raises:
            ValidationError: If any entry in `extraction_results` is itself a failed extraction.
        """
        require_successful_extractions(extraction_results)

        if not extraction_results:
            return ArchitectureGraph()

        # A successful `ArchitectureExtractionResult` always carries a unit (enforced by its own
        # `__post_init__`), so this filter never drops anything; it only lets the type checker
        # see that `unit` is present.
        units = [result.unit for result in extraction_results if result.unit is not None]

        files_by_package: dict[tuple[str, ...], set[str]] = {}
        packages_with_root_file: set[tuple[str, ...]] = set()
        for unit in units:
            files_by_package.setdefault(unit.package_path, set()).add(unit.relative_path)
            if unit.is_package_root:
                packages_with_root_file.add(unit.package_path)

        node_paths: set[tuple[str, ...]] = set(files_by_package)
        for package_path in files_by_package:
            node_paths.update(ancestor_package_paths(package_path))

        nodes = tuple(
            PackageNode(
                package_path=package_path,
                file_paths=tuple(sorted(files_by_package.get(package_path, ()))),
                has_package_root_file=package_path in packages_with_root_file,
            )
            for package_path in sorted(node_paths)
        )

        edges = tuple(
            sorted(
                (
                    PackageContainmentEdge(parent_path=package_path[:-1], child_path=package_path)
                    for package_path in node_paths
                    if package_path
                ),
                key=lambda edge: (edge.parent_path, edge.child_path),
            )
        )

        return ArchitectureGraph(nodes=nodes, edges=edges)
