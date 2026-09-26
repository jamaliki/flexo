"""Semantic, geometric, publication, and editability validation."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from flexo.components import component_names, normalize_node
from flexo.diagnostics import Diagnostic, FlexoError, Severity, raise_if_errors
from flexo.fonts import family_faces, require_family
from flexo.ir.semantic import FigureSpec, GroupSpec, layout_connections
from flexo.themes import (
    DEFAULT_PALETTE_NAME,
    parse_palette,
    theme,
    unknown_palette,
)


def normalize_and_validate(figure: FigureSpec) -> FigureSpec:
    normalized = replace(figure, nodes=tuple(normalize_node(node) for node in figure.nodes))
    raise_if_errors(semantic_diagnostics(normalized))
    return normalized


def _suggestion(name: str, nodes) -> str | None:
    """A "did you mean" for an unknown node id, from the ids that exist."""

    from difflib import get_close_matches

    ids = [node_id for node_id in nodes]
    close = get_close_matches(name, ids, n=3, cutoff=0.6) or [
        node_id for node_id in ids if node_id.rsplit(".", 1)[-1] == name.rsplit(".", 1)[-1]
    ][:3]
    if not close:
        return "Ids are scoped by their group: a node made in module m as \"x\" is \"m.x\"."
    return "Did you mean " + " or ".join(f'"{item}"' for item in close) + "?"


def merge_matched_stacks(figure: FigureSpec) -> FigureSpec:
    """Lay rows wired one-to-one on shared columns (and columns on shared rows).

    Two rows stacked in a column, with the same number of children and child
    *i* of one wired to child *i* of the other -- inputs over their
    projections, say -- are one table: each child should sit over its partner.
    As separate rows each centres its own children, and a row of narrow words
    over a row of wide boxes leaves every arrow between them jogging sideways.
    Such rows (and, across a row, such columns) are merged into one grid, so
    partners share a column. Consecutive matched stacks merge into one grid.
    The authored figure keeps its rows; only the compiled one is a grid.
    """

    groups = {group.id: group for group in figure.groups}
    nodes = {node.id for node in figure.nodes}
    wired = {
        frozenset((connection.source.node_id, connection.target.node_id))
        for connection in layout_connections(figure)
    }
    across = {"column": "row", "row": "column"}

    def stack(child_id: str, kind: str) -> GroupSpec | None:
        child = groups.get(child_id)
        if (
            child is None
            or child.role != "layout"
            or child.label
            or child.layout.kind != kind
            or not child.children
            or not all(item in nodes for item in child.children)
        ):
            return None
        return child

    def matched(first: GroupSpec, second: GroupSpec) -> bool:
        """Child *i* wired to child *i*, and to no other child of the pair."""

        if len(first.children) != len(second.children):
            return False
        return all(
            (frozenset((a, b)) in wired) == (i == j)
            for i, a in enumerate(first.children)
            for j, b in enumerate(second.children)
        )

    replaced: dict[str, GroupSpec] = {}
    removed: set[str] = set()
    for parent in figure.groups:
        kind = across.get(parent.layout.kind)
        if kind is None:
            continue
        runs: list[list[GroupSpec]] = []
        for child_id in parent.children:
            candidate = stack(child_id, kind)
            if candidate is not None and runs and runs[-1] and matched(runs[-1][-1], candidate):
                runs[-1].append(candidate)
            elif candidate is not None:
                runs.append([candidate])
            else:
                runs.append([])
        children = list(parent.children)
        for run in runs:
            if len(run) < 2:
                continue
            first = run[0]
            size = len(first.children)
            if parent.layout.kind == "column":
                cells = tuple(item for row in run for item in row.children)
                columns = size
                row_gap = parent.layout.row_gap or parent.layout.gap
                column_gap = first.layout.column_gap or first.layout.gap
            else:
                cells = tuple(
                    item
                    for index in range(size)
                    for column in run
                    for item in (column.children[index],)
                )
                columns = len(run)
                row_gap = first.layout.row_gap or first.layout.gap
                column_gap = parent.layout.column_gap or parent.layout.gap
            grid = replace(
                first,
                children=cells,
                layout=replace(
                    first.layout,
                    kind="grid",
                    columns=columns,
                    align="center",
                    justify="center",
                    row_gap=row_gap,
                    column_gap=column_gap,
                    gap=None,
                    placements=(),
                ),
            )
            replaced[first.id] = grid
            for other in run[1:]:
                removed.add(other.id)
                children.remove(other.id)
        if len(children) != len(parent.children):
            replaced[parent.id] = replace(replaced.get(parent.id, parent), children=tuple(children))
    if not replaced:
        return figure
    return replace(
        figure,
        groups=tuple(
            replaced.get(group.id, group) for group in figure.groups if group.id not in removed
        ),
    )


def resolve_alignment(figure: FigureSpec) -> FigureSpec:
    """Turn every ``align="auto"`` into the alignment its group actually needs.

    Arrows between siblings should run on one line, so a group whose children
    are wired to each other aligns their *port lines* (``ports``) -- which for a
    plain box is its centre, and for a captioned glyph is the glyph, not glyph
    plus caption. A group whose children are not connected to one another is a
    shelf: a shelf of two or more stacks (columns in a row, rows in a column)
    is a set of parallel branches and aligns them at the start, so they begin
    level; any other shelf -- and the canvas -- centres its children. Resolved
    once here, so every later pass and the serialized figure agree on one
    concrete value.
    """

    if not any(group.layout.align == "auto" for group in figure.groups):
        return figure
    groups = {group.id: group for group in figure.groups}
    node_ids = {node.id for node in figure.nodes}
    memo: dict[str, frozenset[str]] = {}

    def descendants(entity_id: str) -> frozenset[str]:
        if entity_id not in memo:
            if entity_id in node_ids:
                memo[entity_id] = frozenset((entity_id,))
            elif entity_id in groups:
                memo[entity_id] = frozenset().union(
                    *(descendants(child) for child in groups[entity_id].children)
                )
            else:
                memo[entity_id] = frozenset()
        return memo[entity_id]

    pairs = tuple(
        (connection.source.node_id, connection.target.node_id)
        for connection in layout_connections(figure)
    )
    resolved = []
    for group in figure.groups:
        if group.layout.align != "auto":
            resolved.append(group)
            continue
        owner = {
            node_id: index
            for index, child in enumerate(group.children)
            for node_id in descendants(child)
        }
        wired = any(
            source in owner and target in owner and owner[source] != owner[target]
            for source, target in pairs
        )
        # A shelf of stacks -- columns side by side, rows one over another -- is
        # parallel branches: they start together, the way a fork reads.
        across = {"row": "column", "column": "row"}.get(group.layout.kind)
        stacks = (
            len(group.children) > 1
            and group.role != "canvas"
            and all(
                child in groups and groups[child].layout.kind == across
                for child in group.children
            )
        )
        layout = replace(
            group.layout, align="ports" if wired else ("start" if stacks else "center")
        )
        resolved.append(replace(group, layout=layout))
    return replace(figure, groups=tuple(resolved))


def semantic_diagnostics(figure: FigureSpec) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    entity_ids = [node.id for node in figure.nodes] + [group.id for group in figure.groups]
    for entity_id, count in Counter(entity_ids).items():
        if count > 1:
            diagnostics.append(
                Diagnostic(
                    "semantic.id.duplicate",
                    "Semantic ID is not unique.",
                    entity_id=entity_id,
                )
            )
    connection_ids = [edge.id for edge in figure.edges] + [net.id for net in figure.nets]
    for connection_id, count in Counter(connection_ids).items():
        if count > 1 or connection_id in entity_ids:
            diagnostics.append(
                Diagnostic(
                    "semantic.id.duplicate",
                    "Semantic ID is not unique.",
                    entity_id=connection_id,
                )
            )

    nodes = {node.id: node for node in figure.nodes}
    groups = {group.id: group for group in figure.groups}
    valid_components = component_names()
    for node in figure.nodes:
        if node.kind not in valid_components:
            diagnostics.append(
                Diagnostic(
                    "component.kind.unknown",
                    f'Unknown component kind "{node.kind}".',
                    entity_id=node.id,
                    hint=f"Valid kinds: {', '.join(valid_components)}.",
                )
            )

    if figure.root not in groups:
        diagnostics.append(
            Diagnostic(
                "figure.root.unknown",
                f'Root group "{figure.root}" does not exist.',
                entity_id=figure.id,
            )
        )
    try:
        # A theme file is read here, so a mistake in it is reported with the figure.
        theme(figure.style)
    except FlexoError as error:
        diagnostics.extend(replace(item, entity_id=figure.id) for item in error.diagnostics)
    else:
        try:
            known = figure.palette == DEFAULT_PALETTE_NAME or parse_palette(figure.palette)
        except FlexoError as error:
            diagnostics.extend(replace(item, entity_id=figure.id) for item in error.diagnostics)
        else:
            if not known:
                diagnostics.append(replace(unknown_palette(figure.palette), entity_id=figure.id))
    if figure.font is not None and not family_faces(figure.font):
        try:
            require_family(figure.font)
        except FlexoError as error:
            diagnostics.extend(
                replace(diagnostic, entity_id=figure.id) for diagnostic in error.diagnostics
            )

    child_counts: Counter[str] = Counter()
    known_children = set(nodes) | set(groups)
    for group in figure.groups:
        for child in group.children:
            child_counts[child] += 1
            if child not in known_children:
                diagnostics.append(
                    Diagnostic(
                        "group.child.unknown",
                        f'Child "{child}" does not exist.',
                        entity_id=group.id,
                    )
                )
            elif child == group.id:
                diagnostics.append(
                    Diagnostic("group.cycle", "Group contains itself.", entity_id=group.id)
                )
        placeable = set(group.children)
        for placed, row, column in group.layout.placements:
            if placed not in placeable:
                diagnostics.append(
                    Diagnostic(
                        "layout.grid.placement.unknown-child",
                        f'Cell (row {row}, column {column}) is given to "{placed}", '
                        "which is not a child of this group.",
                        entity_id=group.id,
                        hint=f"Children: {', '.join(group.children) or 'none'}.",
                    )
                )
    for entity_id in known_children - {figure.root}:
        count = child_counts[entity_id]
        if count == 0:
            diagnostics.append(
                Diagnostic(
                    "semantic.orphan",
                    "Entity is not reachable from a layout group.",
                    Severity.WARNING,
                    entity_id,
                )
            )
        elif count > 1:
            diagnostics.append(
                Diagnostic(
                    "group.child.multiple-parents",
                    "Entity appears in more than one layout group.",
                    entity_id=entity_id,
                )
            )
    diagnostics.extend(_cycle_diagnostics(groups, figure.root))

    for edge in figure.edges:
        for label, reference in (("source", edge.source), ("target", edge.target)):
            node = nodes.get(reference.node_id)
            if node is None:
                diagnostics.append(
                    Diagnostic(
                        f"edge.{label}.unknown-node",
                        f'{label.title()} node "{reference.node_id}" does not exist.',
                        entity_id=edge.id,
                        hint=_suggestion(reference.node_id, nodes),
                    )
                )
                continue
            names = tuple(port.name for port in node.ports)
            if reference.port_name not in names:
                diagnostics.append(
                    Diagnostic(
                        f"edge.{label}.unknown-port",
                        f'{label.title()} port "{reference}" does not exist.',
                        entity_id=edge.id,
                        hint=f"Valid ports: {', '.join(f'{node.id}.{name}' for name in names)}.",
                    )
                )
        for waypoint in edge.waypoints:
            if waypoint.reference and waypoint.reference not in known_children:
                diagnostics.append(
                    Diagnostic(
                        "edge.waypoint.unknown-reference",
                        f'Waypoint reference "{waypoint.reference}" does not exist.',
                        entity_id=edge.id,
                    )
                )
    for net in figure.nets:
        for label, references in (("source", net.sources), ("target", net.targets)):
            for reference in references:
                node = nodes.get(reference.node_id)
                if node is None:
                    diagnostics.append(
                        Diagnostic(
                            f"net.{label}.unknown-node",
                            f'{label.title()} node "{reference.node_id}" does not exist.',
                            entity_id=net.id,
                            hint=_suggestion(reference.node_id, nodes),
                        )
                    )
                    continue
                names = tuple(port.name for port in node.ports)
                if reference.port_name not in names:
                    diagnostics.append(
                        Diagnostic(
                            f"net.{label}.unknown-port",
                            f'{label.title()} port "{reference}" does not exist.',
                            entity_id=net.id,
                            hint=(
                                "Valid ports: "
                                + ", ".join(f"{node.id}.{name}" for name in names)
                                + "."
                            ),
                        )
                    )
    return tuple(diagnostics)


def _cycle_diagnostics(groups: dict[str, object], root: str) -> tuple[Diagnostic, ...]:
    if root not in groups:
        return ()
    diagnostics: list[Diagnostic] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(group_id: str) -> None:
        if group_id in visiting:
            diagnostics.append(
                Diagnostic("group.cycle", "Layout group cycle detected.", entity_id=group_id)
            )
            return
        if group_id in visited:
            return
        visiting.add(group_id)
        group = groups[group_id]
        for child in group.children:  # type: ignore[attr-defined]
            if child in groups:
                visit(child)
        visiting.remove(group_id)
        visited.add(group_id)

    visit(root)
    return tuple(diagnostics)


def require_valid(figure: FigureSpec) -> None:
    diagnostics = semantic_diagnostics(figure)
    errors = tuple(item for item in diagnostics if item.severity is Severity.ERROR)
    if errors:
        raise FlexoError(errors)
