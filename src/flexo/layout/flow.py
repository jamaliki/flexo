"""Flow groups: children laid out in layers by how they are wired.

A group with ``layout="flow"`` (top to bottom) or ``layout="flow-right"`` (left
to right) does not keep its children in the order they were written. It reads
the wiring between them instead, the way a layered graph drawing does:

1. **Layers.** Each child goes one layer after the latest of the children that
   feed it, so every arrow points down the flow. An arrow that closes a loop
   (found by walking the children in authoring order) is left out of this, so
   a cycle still has a first step, and so is a link with no arrowhead. A child
   that nothing feeds goes one layer before the first child it feeds.
2. **Order.** An arrow that skips layers holds a place in each layer it passes
   -- a spacer, in the compiled figure -- so nothing is set down in its way.
   Within a layer, children are sorted by the mean position of their
   neighbours in the layers around them, a few sweeps down and up, which
   takes out most crossings; ties keep authoring order.
3. **Places.** A layer that holds one child is a row of its own, centred. A run
   of wider layers is one grid in which each place takes the column nearest
   the mean column of the components feeding it -- components first, the
   places of passing arrows around them -- so a branch runs straight down its
   column.

The compiled flow group is a column (a row, for ``flow-right``) of those rows
and grids, centred on one another unless the group names an ``align``. The
authored figure keeps its flow group; only the compiled figure changes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from flexo.components import normalize_node
from flexo.ir.semantic import FigureSpec, GroupSpec, LayoutSpec, NodeSpec
from flexo.units import Length

FLOW_KINDS = {"flow": "column", "flow-right": "row"}
"""Each flow kind and the kind of stack it becomes."""

SWEEPS = 4
"""Down-and-up passes of the ordering heuristic."""

_PASSING = "\0"
"""Marks the place an arrow holds in a layer it passes through."""


def lower_cycles(figure: FigureSpec) -> FigureSpec:
    """``figure`` with every cycle group laid round the border of a grid.

    A cycle's children go clockwise from the top left in the order they were
    written, round the border of the squarest grid that holds them, so each
    sits beside the next and the arrow closing the cycle is as short as the
    others. Two children are a row; three take three corners of a square.
    """

    if not any(group.layout.kind == "cycle" for group in figure.groups):
        return figure
    groups = []
    for group in figure.groups:
        if group.layout.kind != "cycle":
            groups.append(group)
            continue
        count = len(group.children)
        if count <= 2:
            groups.append(replace(group, layout=replace(group.layout, kind="row")))
            continue
        rows, columns = _ring(count)
        cells = _perimeter(rows, columns)[:count]
        groups.append(
            replace(
                group,
                layout=replace(
                    group.layout,
                    kind="grid",
                    columns=columns,
                    placements=tuple(
                        (child, row, column)
                        for child, (row, column) in zip(group.children, cells, strict=True)
                    ),
                ),
            )
        )
    return replace(figure, groups=tuple(groups))


def _ring(count: int) -> tuple[int, int]:
    """The ``(rows, columns)`` whose border holds ``count`` cells with fewest to
    spare, and of those the squarest; never taller than wide."""

    fits = [
        (rows, columns)
        for rows in range(2, count + 1)
        for columns in range(rows, count + 1)
        if 2 * (rows + columns) - 4 >= count
    ]
    return min(fits, key=lambda size: (2 * (size[0] + size[1]) - 4 - count, size[1] - size[0]))


def _perimeter(rows: int, columns: int) -> list[tuple[int, int]]:
    """The border cells of a grid, clockwise from the top left."""

    top = [(0, column) for column in range(columns)]
    right = [(row, columns - 1) for row in range(1, rows)]
    bottom = [(rows - 1, column) for column in range(columns - 2, -1, -1)]
    left = [(row, 0) for row in range(rows - 2, 0, -1)]
    return top + right + bottom + left


def lower_flows(figure: FigureSpec) -> FigureSpec:
    """``figure`` with every flow group replaced by a stack of rows and grids."""

    figure = lower_cycles(figure)
    if not any(group.layout.kind in FLOW_KINDS for group in figure.groups):
        return figure
    groups = {group.id: group for group in figure.groups}
    taken = set(groups) | {node.id for node in figure.nodes}
    # An undirected link -- shared weights between twins -- says nothing about
    # which comes first: it only pulls its ends together within a layer.
    connections = [
        (edge.source.node_id, edge.target.node_id)
        for edge in figure.edges
        if edge.arrow != "none"
    ] + [
        (source.node_id, target.node_id)
        for net in figure.nets
        for source in net.sources
        for target in net.targets
    ]
    links = [
        (edge.source.node_id, edge.target.node_id)
        for edge in figure.edges
        if edge.arrow == "none"
    ]
    result: list[GroupSpec] = []
    spacers: list[NodeSpec] = []
    for group in figure.groups:
        if group.layout.kind not in FLOW_KINDS:
            result.append(group)
            continue
        across = group.layout.kind == "flow-right"
        stack = FLOW_KINDS[group.layout.kind]
        if not group.children:
            result.append(replace(group, layout=replace(group.layout, kind=stack)))  # type: ignore[arg-type]
            continue
        layers, chain = _layers(group, groups, connections, links)
        children: list[str] = []
        for band in _bands(layers):
            if len(band) == 1 and len(band[0]) == 1:
                children.append(band[0][0])
                continue
            band_id = _fresh(f"{group.id}.layers", taken)
            taken.add(band_id)
            children.append(band_id)
            columns = _columns(band, chain)
            width = max(columns.values()) + 1
            placed = []
            for level, layer in enumerate(band):
                for child in layer:
                    name = child
                    if child.startswith(_PASSING):
                        # An empty place would let the grid close up the lane
                        # the arrow runs in: a spacer holds it open.
                        name = _fresh(f"{group.id}.passing", taken)
                        taken.add(name)
                        spacers.append(normalize_node(NodeSpec(name, "spacer")))
                    placed.append((name, level, columns[child]))
            result.append(
                GroupSpec(
                    band_id,
                    tuple(child for child, _, _ in placed),
                    LayoutSpec(
                        kind="grid",
                        columns=len(band) if across else width,
                        gap=group.layout.gap,
                        padding=Length(0.0),
                        placements=tuple(
                            (child, column, level) if across else (child, level, column)
                            for child, level, column in placed
                        ),
                    ),
                    role="layout",
                )
            )
        # Layers are centred on one another, as a layered drawing is.
        align = "center" if group.layout.align == "auto" else group.layout.align
        result.append(
            replace(
                group,
                children=tuple(children),
                layout=replace(group.layout, kind=stack, align=align),  # type: ignore[arg-type]
            )
        )
    return replace(figure, nodes=(*figure.nodes, *spacers), groups=tuple(result))


def _layers(
    group: GroupSpec,
    groups: dict[str, GroupSpec],
    connections: list[tuple[str, str]],
    links: list[tuple[str, str]],
) -> tuple[list[list[str]], dict[str, list[str]]]:
    """The group's children in ordered layers, with the places arrows pass through,
    and what feeds what between adjacent layers."""

    owner: dict[str, str] = {}

    def claim(entity: str, child: str) -> None:
        owner[entity] = child
        for item in groups[entity].children if entity in groups else ():
            claim(item, child)

    for child in group.children:
        claim(child, child)
    feeds: dict[str, list[str]] = defaultdict(list)
    for source, target in connections:
        first, second = owner.get(source), owner.get(target)
        if None not in (first, second) and first != second and second not in feeds[first]:
            feeds[first].append(second)  # type: ignore[index, arg-type]
    # Walk in authoring order; an arrow back to a child still on the walk
    # closes a loop and does not decide layers.
    forward: dict[str, list[str]] = defaultdict(list)
    state: dict[str, int] = {}

    def walk(child: str) -> None:
        state[child] = 1
        for successor in feeds[child]:
            if state.get(successor) == 1:
                continue
            forward[child].append(successor)
            if successor not in state:
                walk(successor)
        state[child] = 2

    for child in group.children:
        if child not in state:
            walk(child)
    rank = {child: 0 for child in group.children}
    order = {child: float(index) for index, child in enumerate(group.children)}
    changed = True
    while changed:
        changed = False
        for child in group.children:
            for successor in forward[child]:
                if rank[successor] < rank[child] + 1:
                    rank[successor] = rank[child] + 1
                    changed = True
    # A value that nothing feeds -- real data beside a generator, noise beside
    # the mean and variance it perturbs -- enters one layer before the first
    # step that reads it, not at the very top.
    fed = {successor for successors in forward.values() for successor in successors}
    for child in group.children:
        if child not in fed and forward[child]:
            rank[child] = max(0, min(rank[successor] for successor in forward[child]) - 1)
    # An arrow over several layers holds a place in each layer between.
    chain: dict[str, list[str]] = defaultdict(list)
    for child in group.children:
        for successor in forward[child]:
            previous = child
            for level in range(rank[child] + 1, rank[successor]):
                passing = f"{_PASSING}{child}\0{successor}\0{level}"
                rank[passing] = level
                order[passing] = order[child]
                chain[previous].append(passing)
                previous = passing
            chain[previous].append(successor)
    depth = max(rank.values()) + 1
    layers = [[child for child in rank if rank[child] == level] for level in range(depth)]
    # Every arrow pulls its ends together when ordering; a loop, and a link
    # with no arrowhead, break ties -- the step a loop leaves from sits on the
    # side nearest where it goes back to.
    neighbours: dict[str, set[str]] = defaultdict(set)
    for child, successors in chain.items():
        for successor in successors:
            neighbours[child].add(successor)
            neighbours[successor].add(child)
    extra: dict[str, set[str]] = defaultdict(set)
    for child in feeds:
        for successor in feeds[child]:
            if successor not in forward[child]:
                extra[child].add(successor)
                extra[successor].add(child)
    for first, second in links:
        one, two = owner.get(first), owner.get(second)
        if one is not None and two is not None and one != two:
            extra[one].add(two)
            extra[two].add(one)

    def place() -> dict[str, float]:
        return {
            child: (index + 0.5) / len(layer)
            for layer in layers
            for index, child in enumerate(layer)
        }

    for sweep in range(SWEEPS):
        levels = range(1, depth) if sweep % 2 == 0 else range(depth - 2, -1, -1)
        for level in levels:
            position = place()
            side = level - 1 if sweep % 2 == 0 else level + 1

            def key(child: str, side: int = side, position: dict = position) -> tuple:
                near = [position[other] for other in neighbours[child] if rank[other] == side]
                every = [
                    position[other]
                    for other in neighbours[child] | extra[child]
                    if other in position and other != child
                ]
                return (
                    sum(near) / len(near) if near else position[child],
                    sum(every) / len(every) if every else position[child],
                    order[child],
                )

            layers[level].sort(key=key)
    return layers, chain


def _bands(layers: list[list[str]]) -> list[list[list[str]]]:
    """Consecutive layers grouped: each one-child layer alone, wider ones in runs."""

    bands: list[list[list[str]]] = []
    for layer in layers:
        if len(layer) > 1 and bands and len(bands[-1][-1]) > 1:
            bands[-1].append(layer)
        else:
            bands.append([layer])
    return bands


PRIORITY = 10.0
"""How much more a component resists leaving its column than an arrow's place."""


def _columns(band: list[list[str]], chain: dict[str, list[str]]) -> dict[str, int]:
    """A grid column for each place in the band, kept in each layer's order.

    Each place wants the mean column of what feeds it from the layer before
    -- the middle column, if that is a centred row above the band -- and the
    columns are chosen, in order, to keep components where they want to be
    first and arrows' passing places second, so a chain runs straight down
    and the arrows that skip past it move aside.
    """

    width = max(len(layer) for layer in band)
    fed_by: dict[str, list[str]] = defaultdict(list)
    for child, successors in chain.items():
        for successor in successors:
            fed_by[successor].append(child)
    column: dict[str, int] = {}
    middle = (width - 1) / 2.0
    for level, layer in enumerate(band):
        offset = (width - len(layer)) / 2.0
        wanted = []
        for index, child in enumerate(layer):
            sources = [column[other] for other in fed_by[child] if other in column]
            # A component follows the components feeding it, not the arrows
            # that merely pass: a chain runs straight on.
            solid = [
                column[other]
                for other in fed_by[child]
                if other in column and not other.startswith(_PASSING)
            ]
            if solid and not child.startswith(_PASSING):
                sources = solid
            if sources:
                wanted.append(sum(sources) / len(sources))
            elif fed_by[child] and level == 0:
                wanted.append(middle)  # fed from the centred row above
            else:
                wanted.append(offset + index)
        weights = [1.0 if child.startswith(_PASSING) else PRIORITY for child in layer]
        for child, value in zip(layer, _cheapest(wanted, weights, width), strict=True):
            column[child] = value
    return column


def _cheapest(wanted: list[float], weights: list[float], width: int) -> list[int]:
    """Increasing columns in ``0..width-1`` closest to ``wanted``, by weight."""

    count = len(wanted)
    infinity = float("inf")
    # cost[i][c]: the best cost of the first i + 1 places with place i at c.
    cost = [[infinity] * width for _ in range(count)]
    back = [[-1] * width for _ in range(count)]
    for column in range(width):
        cost[0][column] = weights[0] * abs(column - wanted[0])
    for index in range(1, count):
        best, best_at = infinity, -1
        for column in range(width):
            if column >= 1 and cost[index - 1][column - 1] < best:
                best, best_at = cost[index - 1][column - 1], column - 1
            if best < infinity:
                cost[index][column] = best + weights[index] * abs(column - wanted[index])
                back[index][column] = best_at
    column = min(range(width), key=lambda value: cost[count - 1][value])
    result = [column]
    for index in range(count - 1, 0, -1):
        column = back[index][column]
        result.append(column)
    return result[::-1]


def _fresh(candidate: str, taken: set[str]) -> str:
    name, suffix = candidate, 1
    while name in taken:
        suffix += 1
        name = f"{candidate}-{suffix}"
    return name
