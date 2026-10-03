"""A figure turned a quarter: the same parts and wiring, read across instead of down.

A figure is written for a page, and a page is taller than it is wide; a slide
is the other way round. A tall stack of layers can only be shrunk to fit a
slide, and its words shrink with it. ``turned`` says the same thing laid the
other way: every row becomes a column and every column a row, a grid is
transposed, a flow placed downward is placed rightward, and every side a hint
or a port names turns with it (north becomes west, east becomes south). A figure
that reads downward is transposed (down becomes right); one whose stacks read
upward, as a transformer's do, is turned so up becomes right -- its stacks'
bottoms come first -- so arrows still run with the reading direction. A
column of vector cells lies down as a row.

Hints that name coordinates (waypoints, lanes) are dropped: they were given for
the figure as written. ``fit_in_box`` (``flexo.fit``) uses this to choose the
way a figure is laid out for a box of a given shape.
"""

from __future__ import annotations

from dataclasses import replace

from flexo.geometry import Side
from flexo.ir.semantic import FigureSpec, GroupSpec, LayoutSpec, NodeSpec, layout_connections
from flexo.units import Length

_ACROSS = {
    Side.NORTH: Side.WEST, Side.WEST: Side.NORTH, Side.SOUTH: Side.EAST, Side.EAST: Side.SOUTH
}
"""A figure that reads downward is turned by transposing it: down becomes right."""
_UPWARD = {
    Side.NORTH: Side.EAST, Side.SOUTH: Side.WEST, Side.EAST: Side.SOUTH, Side.WEST: Side.NORTH
}
"""A figure that reads upward is turned so that up becomes right, not left."""
_KIND = {"row": "column", "column": "row", "flow": "flow-right", "flow-right": "flow"}


def turned(figure: FigureSpec, *, keep_root: bool = False) -> FigureSpec:
    """``figure`` laid out the other way (see the module docs).

    ``keep_root=True`` turns everything but the outermost group that holds more
    than one part: its parts stay side by side (or stacked), each turned within.
    """

    under = _nodes_under(figure)
    upward = _reads_upward(figure, under)
    sides = _UPWARD if upward else _ACROSS
    kept = _outermost(figure) if keep_root else set()
    groups = tuple(
        group if group.id in kept else _turned_group(group, upward)
        for group in figure.groups
    )
    nodes = tuple(_turned_node(node, sides) for node in figure.nodes)

    def side(value):
        return sides.get(Side(value), value) if value is not None else None

    edges = tuple(
        replace(
            edge,
            depart=side(edge.depart),
            arrive=side(edge.arrive),
            via=side(edge.via),
            waypoints=(),
            lane_hint=None,
        )
        for edge in figure.edges
    )
    nets = tuple(replace(net, rail_hint=side(net.rail_hint)) for net in figure.nets)
    return replace(figure, groups=groups, nodes=nodes, edges=edges, nets=nets)


def _outermost(figure: FigureSpec) -> set[str]:
    """The root and the single-child groups under it, down to the first that branches."""

    groups = {group.id: group for group in figure.groups}
    kept: set[str] = set()
    current = groups.get(figure.root)
    while current is not None:
        kept.add(current.id)
        if len(current.children) != 1:
            break
        current = groups.get(current.children[0])
    return kept


def _turned_node(node: NodeSpec, sides: dict[Side, Side]) -> NodeSpec:
    ports = tuple(
        port if port.auto_side else replace(port, side=sides[Side(port.side)])
        for port in node.ports
    )
    properties = node.properties
    values = dict(properties)
    if node.kind == "vector" and "cells" in values:
        # A column of cells lies down as a row: cells per column and columns
        # swap, and the shades (column by column) are transposed with them.
        cells, columns = int(values["cells"]), int(values.get("columns", 1) or 1)
        changed = {"cells": columns, "columns": cells}
        if "shades" in values:
            grid = [column.split(",") for column in str(values["shades"]).split(";")]
            changed["shades"] = ";".join(
                ",".join(grid[column][row] for column in range(columns)) for row in range(cells)
            )
        properties = tuple((name, changed.get(name, value)) for name, value in properties)
        properties += tuple((name, value) for name, value in changed.items() if name not in values)
    if ports == node.ports and properties == node.properties:
        return node
    return replace(node, ports=ports, properties=properties)


def _turned_group(group: GroupSpec, upward: bool) -> GroupSpec:
    layout = group.layout
    if layout.kind in _KIND:
        children = group.children
        if upward and layout.kind == "column":
            # Up becomes right: the bottom of a stack comes first in a row.
            children = tuple(reversed(children))
        turned_layout = replace(
            layout, kind=_KIND[layout.kind], reflow=_KIND.get(layout.reflow or "")
        )
        return replace(group, children=children, layout=_swapped_padding(turned_layout))
    if layout.kind == "grid":
        from flexo.layout.grid import grid_plan

        plan = grid_plan(layout, group.children)
        placements = tuple(
            (child, column, plan.rows - 1 - row if upward else row)
            for child, (row, column) in zip(group.children, plan.cells, strict=True)
        )
        return replace(
            group,
            layout=_swapped_padding(
                replace(
                    layout,
                    columns=max(plan.rows, 1),
                    placements=placements,
                    column_widths=(),
                    row_gap=layout.column_gap,
                    column_gap=layout.row_gap,
                )
            ),
        )
    return group


def _swapped_padding(layout: LayoutSpec) -> LayoutSpec:
    return replace(
        layout,
        padding_top=layout.padding_left,
        padding_left=layout.padding_top,
        padding_bottom=layout.padding_right,
        padding_right=layout.padding_bottom,
        # A size fixed for one reading (a glyph row as wide as its block) does
        # not carry over to the other: a turned group sizes itself.
        width=None,
        height=None,
    )


def _nodes_under(figure: FigureSpec) -> dict[str, set[str]]:
    """Every group's and node's id, mapped to the node ids inside it."""

    groups = {group.id: group for group in figure.groups}
    found: dict[str, set[str]] = {}

    def collect(identifier: str) -> set[str]:
        if identifier in found:
            return found[identifier]
        group = groups.get(identifier)
        if group is None:
            nodes = {identifier}
        else:
            nodes = set().union(*(collect(child) for child in group.children))
        found[identifier] = nodes
        return nodes

    for group in figure.groups:
        collect(group.id)
    return found


def _reads_upward(figure: FigureSpec, under: dict[str, set[str]]) -> bool:
    """Whether the figure's stacks read upward: more wiring between the parts
    of its columns runs from a lower part to a higher one than the other way."""

    pairs = [(edge.source.node_id, edge.target.node_id) for edge in figure.edges]
    for net in figure.nets:
        pairs += [(s.node_id, t.node_id) for s in net.sources for t in net.targets]
    score = 0
    for group in figure.groups:
        if group.layout.kind != "column":
            continue
        position: dict[str, int] = {}
        for index, child in enumerate(group.children):
            for node in under.get(child, {child}):
                position[node] = index
        for source, target in pairs:
            a, b = position.get(source), position.get(target)
            if a is not None and b is not None and a != b:
                score += 1 if a > b else -1
    return score > 0


def wrapped(figure: FigureSpec, *, longest: int = 5, back: bool | None = None) -> FigureSpec:
    """``figure`` with each long row or column folded onto two lines.

    A row of ``longest`` or more parts is set on two rows, read left to right
    and then on to the next row, as a long pipeline is set across a page; a
    column on two columns, read down and then on. The parts and their wiring are
    unchanged; only where they sit.

    Parts wired across the fold make it a flow: it is folded, near the middle,
    where the fewest lines cross from one line to the other, and each line keeps
    its own spacing, so its arrows are even. One whose fold is crossed by more
    than the line that carries it on (a loop back, as a flow chart's "no") turns
    at the end of the first line and runs back along the second, a snake, so that
    line is a short step down and nothing crosses it. Parts with nothing between
    the two halves (a shelf of panels) keep the columns of a grid. ``back`` says
    whether a flow's second line runs back (``True``) or on (``False``) whatever
    the fold: for a figure whose lines cross the one way and not the other.
    """

    import math

    under = _nodes_under(figure)
    pairs = [(link.source.node_id, link.target.node_id) for link in layout_connections(figure)]
    taken = {group.id for group in figure.groups} | {node.id for node in figure.nodes}
    groups: list[GroupSpec] = []
    for group in figure.groups:
        kind, count = group.layout.kind, len(group.children)
        if kind not in {"row", "column"} or count < longest:
            groups.append(group)
            continue
        half = math.ceil(count / 2)
        if not _crossing(group.children, half, under, pairs):
            groups.append(_gridded(group, half))
            continue
        # Folded where the fewest lines cross between the two lines, as near the middle as
        # that allows (the earlier, of two as near): a part added at the end of a row does
        # not move the fold, and the parts before it, unless it must.
        at = min(
            (at for at in (half - 1, half, half + 1) if 2 <= at <= count - 2),
            key=lambda at: (len(_crossing(group.children, at, under, pairs)), abs(at - half), at),
            default=half,
        )
        first, second = group.children[:at], group.children[at:]
        across = _crossing(group.children, at, under, pairs)
        last, then = _held(first[-1:], under), _held(second[:1], under)
        on = [(source, target) for source, target in across if source in last and target in then]
        snake = (bool(on) and len(across) > len(on)) if back is None else back
        lines = []
        for children in (first, tuple(reversed(second)) if snake else second):
            line = _fresh(f"{group.id}.line", taken)
            taken.add(line)
            lines.append(
                GroupSpec(
                    line,
                    tuple(children),
                    LayoutSpec(
                        kind=kind, gap=group.layout.gap, align=group.layout.align,
                        padding=Length(0.0),
                    ),
                    role="layout",
                )
            )
        # The second line starts under the first (or, run back, ends under its end).
        groups.append(
            replace(
                group,
                children=tuple(line.id for line in lines),
                layout=replace(
                    group.layout, kind="column" if kind == "row" else "row",
                    align="end" if snake else "start", justify="start", gap=None,
                    row_gap=None, column_gap=None, width=None, height=None, reflow=None,
                ),
            )
        )
        groups.extend(lines)
    return replace(figure, groups=tuple(groups))


def _held(children: tuple[str, ...], under: dict[str, set[str]]) -> set[str]:
    return set().union(*(under.get(child, {child}) for child in children))


def _crossing(
    children: tuple[str, ...], at: int, under: dict[str, set[str]], pairs: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """The connections between the parts before ``at`` and those from it on."""

    ahead, behind = _held(children[:at], under), _held(children[at:], under)
    return [
        (source, target)
        for source, target in pairs
        if {source, target} & ahead and {source, target} & behind and source != target
    ]


def _gridded(group: GroupSpec, half: int) -> GroupSpec:
    """A long row or column as a grid of two rows (or columns), in reading order."""

    children = enumerate(group.children)
    if group.layout.kind == "row":
        placements = tuple((child, n // half, n % half) for n, child in children)
        columns = half
    else:
        placements = tuple((child, n % half, n // half) for n, child in children)
        columns = 2
    return replace(
        group,
        layout=replace(
            group.layout, kind="grid", columns=columns, placements=placements,
            width=None, height=None, reflow=None,
        ),
    )


def _fresh(candidate: str, taken: set[str]) -> str:
    name, suffix = candidate, 1
    while name in taken:
        suffix += 1
        name = f"{candidate}-{suffix}"
    return name


__all__ = ["turned", "wrapped"]
