"""Flow groups: children laid out in layers by how they are wired.

A group with ``layout="flow"`` (top to bottom) or ``layout="flow-right"`` (left
to right) does not keep its children in the order they were written. It reads
the wiring between them instead, the way a layered graph drawing does:

1. **Layers.** Each child goes one layer after the latest of the children that
   feed it, so every arrow points down the flow. An arrow that closes a loop
   (found by walking the children in authoring order) is left out of this, so
   a cycle still has a first step, and so is a link with no arrowhead. A child
   that nothing feeds goes one layer before the first child it feeds.
2. **Order.** Within a layer, children are sorted by the mean position of their
   neighbours in the layers around them, a few sweeps down and up, which takes
   out most crossings; ties keep authoring order.
3. **Groups.** Each layer of two or more children becomes an unlabelled row
   (a column, for ``flow-right``), and the flow group becomes a column (a row)
   of layers, centred on one another unless the group names an ``align``.
   From there it is laid out and routed like any other group.

The authored figure keeps its flow group; only the compiled figure has layers.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from flexo.ir.semantic import FigureSpec, GroupSpec, LayoutSpec
from flexo.units import Length

FLOW_KINDS = {"flow": ("column", "row"), "flow-right": ("row", "column")}
"""Each flow kind: the kind the group becomes, and the kind of each layer."""

SWEEPS = 4
"""Down-and-up passes of the ordering heuristic."""


def lower_flows(figure: FigureSpec) -> FigureSpec:
    """``figure`` with every flow group replaced by a stack of layer groups."""

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
    for group in figure.groups:
        if group.layout.kind not in FLOW_KINDS:
            result.append(group)
            continue
        outer, inner = FLOW_KINDS[group.layout.kind]
        layers = _layers(group, groups, connections, links)
        children: list[str] = []
        for index, layer in enumerate(layers):
            if len(layer) == 1:
                children.append(layer[0])
                continue
            layer_id = _fresh(f"{group.id}.layer{index}", taken)
            taken.add(layer_id)
            children.append(layer_id)
            result.append(
                GroupSpec(
                    layer_id,
                    tuple(layer),
                    LayoutSpec(kind=inner, gap=group.layout.gap, padding=Length(0.0)),
                    role="layout",
                )
            )
        # Layers are centred on one another, as a layered drawing is; a row
        # would otherwise present its first child to a ports-aligned stack.
        align = "center" if group.layout.align == "auto" else group.layout.align
        result.append(
            replace(
                group,
                children=tuple(children),
                layout=replace(group.layout, kind=outer, align=align),  # type: ignore[arg-type]
            )
        )
    return replace(figure, groups=tuple(result))


def _layers(
    group: GroupSpec,
    groups: dict[str, GroupSpec],
    connections: list[tuple[str, str]],
    links: list[tuple[str, str]],
) -> list[list[str]]:
    """The group's children in layers, each layer in crossing-reducing order."""

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
    order = {child: index for index, child in enumerate(group.children)}
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
    depth = max(rank.values()) + 1
    layers = [
        [child for child in group.children if rank[child] == level] for level in range(depth)
    ]
    # Every arrow, loops included, pulls its ends together when ordering: a
    # step that feeds back to an earlier one sits on the side nearest it.
    neighbours: dict[str, set[str]] = defaultdict(set)
    for child, successors in feeds.items():
        for successor in successors:
            neighbours[child].add(successor)
            neighbours[successor].add(child)
    for first, second in links:
        one, two = owner.get(first), owner.get(second)
        if one is not None and two is not None and one != two:
            neighbours[one].add(two)
            neighbours[two].add(one)

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
                # Ties -- two heads fed by one box -- go by every neighbour,
                # so the one a loop leaves from sits on the loop's side.
                every = [
                    position[other] for other in neighbours[child] if rank[other] != rank[child]
                ]
                return (
                    sum(near) / len(near) if near else position[child],
                    sum(every) / len(every) if every else position[child],
                    order[child],
                )

            layers[level].sort(key=key)
    return layers


def _fresh(candidate: str, taken: set[str]) -> str:
    name, suffix = candidate, 1
    while name in taken:
        suffix += 1
        name = f"{candidate}-{suffix}"
    return name
