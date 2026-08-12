"""Semantic, geometric, publication, and editability validation."""

from __future__ import annotations

from collections import Counter

from flexo.components import component_names, normalize_node
from flexo.diagnostics import Diagnostic, FlexoError, Severity, raise_if_errors
from flexo.ir.semantic import FigureSpec
from flexo.style import PALETTES, STYLES


def normalize_and_validate(figure: FigureSpec) -> FigureSpec:
    normalized = FigureSpec(
        id=figure.id,
        width=figure.width,
        height=figure.height,
        root=figure.root,
        style=figure.style,
        palette=figure.palette,
        nodes=tuple(normalize_node(node) for node in figure.nodes),
        edges=figure.edges,
        groups=figure.groups,
        schema_version=figure.schema_version,
    )
    raise_if_errors(semantic_diagnostics(normalized))
    return normalized


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
    edge_ids = [edge.id for edge in figure.edges]
    for edge_id, count in Counter(edge_ids).items():
        if count > 1 or edge_id in entity_ids:
            diagnostics.append(
                Diagnostic("semantic.id.duplicate", "Semantic ID is not unique.", entity_id=edge_id)
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
    if figure.style not in STYLES:
        diagnostics.append(
            Diagnostic(
                "style.unknown",
                f'Unknown layout style "{figure.style}".',
                entity_id=figure.id,
                hint=f"Valid styles: {', '.join(STYLES)}.",
            )
        )
    if figure.palette not in PALETTES:
        diagnostics.append(
            Diagnostic(
                "palette.unknown",
                f'Unknown palette "{figure.palette}".',
                entity_id=figure.id,
                hint=f"Valid palettes: {', '.join(PALETTES)}.",
            )
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
