"""Semantic, geometric, publication, and editability validation."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from flexo.components import component_names, normalize_node
from flexo.diagnostics import Diagnostic, FlexoError, Severity, raise_if_errors
from flexo.fonts import family_faces, require_family
from flexo.ir.semantic import FigureSpec, layout_connections
from flexo.themes import (
    DEFAULT_PALETTE_NAME,
    THEMES,
    parse_palette,
    unknown_palette,
    unknown_theme,
)


def normalize_and_validate(figure: FigureSpec) -> FigureSpec:
    normalized = replace(figure, nodes=tuple(normalize_node(node) for node in figure.nodes))
    raise_if_errors(semantic_diagnostics(normalized))
    return normalized


def resolve_alignment(figure: FigureSpec) -> FigureSpec:
    """Turn every ``align="auto"`` into the alignment its group actually needs.

    Arrows between siblings should run on one line, so a group whose children
    are wired to each other aligns their *port lines* (``ports``) -- which for a
    plain box is its centre, and for a captioned glyph is the glyph, not glyph
    plus caption. A group whose children are not connected to one another is a
    shelf: a shelf of stacks (columns in a row, rows in a column) is a set of
    parallel branches and aligns them at the start, so they begin level; any
    other shelf centres its children. Resolved once here, so every later pass and the
    serialized figure agree on one concrete value.
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
        stacks = bool(group.children) and all(
            child in groups and groups[child].layout.kind == across
            for child in group.children
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
    if figure.style not in THEMES:
        diagnostics.append(replace(unknown_theme(figure.style), entity_id=figure.id))
    elif figure.palette != DEFAULT_PALETTE_NAME and parse_palette(figure.palette) is None:
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
