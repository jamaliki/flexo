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
    # (A net's ends asked onto sides turn with it, as an edge's do: a spine's skip line
    # leaving its block's foot leaves its right side, turned.)
    nets = tuple(
        replace(
            net,
            rail_hint=side(net.rail_hint),
            sides=tuple((end, side(value)) for end, value in net.sides),
        )
        for net in figure.nets
    )
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

    A row of ``longest`` or more parts is set on two rows, a column on two
    columns. The parts and their wiring are unchanged; only where they sit.

    Parts wired across the fold make it a flow. It is folded at the middle, by
    its parts alone, and turns at the end of its first line to run back along
    the second, a snake: the line on to the second is a short step, and a loop
    back across the fold (a flow chart's "no") crosses nothing. So a line drawn
    in or taken away leaves every part where it was. Each line keeps its own
    spacing, so its arrows are even. Parts with nothing between the two halves
    (a shelf of panels) keep the columns of a grid, read left to right and then
    on. ``back`` says whether a flow's second line runs back (``True``) or on
    (``False``), read as a page is: for a figure whose lines cross run back.
    """

    import math

    under = _nodes_under(figure)
    pairs = [(link.source.node_id, link.target.node_id) for link in layout_connections(figure)]
    taken = {group.id for group in figure.groups} | {node.id for node in figure.nodes}
    kinds = {node.id: node.kind for node in figure.nodes}
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
        # Laid along its lines, should its parts be listed out of the order they run in.
        children = _along(group.children, under, pairs)
        # Folded at the middle (the first line the longer) by its parts alone, never by its
        # lines: a line drawn in or taken away (a loop back) leaves the fold where it was. A
        # part met only at its corners (a decision) does not start the second line, where the
        # line on to it takes its top and a loop back up would have no way out: the fold
        # comes a part earlier, else a part later.
        at = half
        if kinds.get(children[at]) in _CORNERED:
            at = next(
                (
                    place for place in (half - 1, half + 1)
                    if 2 <= place <= count - 2 and kinds.get(children[place]) not in _CORNERED
                ),
                half,
            )
        first, second = children[:at], children[at:]
        snake = True if back is None else back
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


_CORNERED = frozenset({"decision", "circle"})
"""Parts that lines meet only at their corners, or the middles of their sides: one a side."""


def _along(
    children: tuple[str, ...], under: dict[str, set[str]], pairs: list[tuple[str, str]]
) -> tuple[str, ...]:
    """``children`` in the order their lines run, should they be listed out of it.

    From the first listed, each part is followed by those its lines go on to, in the
    order listed; a part no line reaches keeps its place in the list. Taken only when
    fewer lines then run backward than as listed: a loop back (a flow chart's "no")
    changes nothing, nor does a stack listed from its top that reads up.
    """

    holder = {node: child for child in children for node in under.get(child, {child})}
    place = {child: index for index, child in enumerate(children)}
    onward: dict[str, list[str]] = {child: [] for child in children}
    links = []
    for source, target in pairs:
        one, two = holder.get(source), holder.get(target)
        if one is None or two is None or one == two:
            continue
        links.append((one, two))
        if two not in onward[one]:
            onward[one].append(two)
    order: list[str] = []
    seen: set[str] = set()
    for start in children:
        stack = [start]
        while stack:
            child = stack.pop()
            if child in seen:
                continue
            seen.add(child)
            order.append(child)
            stack.extend(sorted(onward[child], key=place.__getitem__, reverse=True))

    def backward(sequence) -> int:
        at = {child: index for index, child in enumerate(sequence)}
        return sum(at[one] > at[two] for one, two in links)

    return tuple(order) if backward(order) < backward(children) else children


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
