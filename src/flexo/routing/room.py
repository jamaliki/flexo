"""Room a routing needs that the layout did not leave: the feedback half of layout.

Layout places components before any connector exists, so it can only guess how
much corridor a figure needs. The good routers do not guess (ELK widens a channel
to fit the lines it holds): they let routing say. Here that is one question asked
of a finished routing -- *did any connector, or its caption, have to leave the
container it belongs to?* -- and one answer: that container gets the missing room as padding
on the side the connector left by, and the figure is laid out and routed again.
The authored figure is never touched; only the compiled one is.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from itertools import pairwise

from flexo.components import TRANSPARENT_KINDS
from flexo.geometry import Point, Rect
from flexo.hierarchy import bounded_owner, parent_map
from flexo.ir.routed import RoutedFigure
from flexo.ir.semantic import FigureSpec, GroupSpec
from flexo.routing.labels import label_box
from flexo.style import LayoutStyle

_SIDES = ("top", "right", "bottom", "left")


def room_needed(routed: RoutedFigure, style: LayoutStyle) -> dict[str, dict[str, float]]:
    """Extra padding, per container and side, that would keep every route inside."""

    figure = routed.fitted.measured.semantic
    parents = parent_map(figure.groups)
    margin = style.route_clearance.points / 2.0
    lane = style.port_spacing.points
    needs: dict[str, dict[str, float]] = defaultdict(dict)

    def check(owner_id: str, points: tuple[Point, ...]) -> None:
        group = routed.fitted.group(owner_id)
        bounds = group.bounds
        overflow = {
            "top": max((bounds.top + margin - point.y for point in points), default=0.0),
            "right": max((point.x - (bounds.right - margin) for point in points), default=0.0),
            "bottom": max((point.y - (bounds.bottom - margin) for point in points), default=0.0),
            "left": max((bounds.left + margin - point.x for point in points), default=0.0),
        }
        for side, amount in overflow.items():
            if amount > 1e-6:
                needs[owner_id][side] = max(needs[owner_id].get(side, 0.0), amount + lane)

    clearance = style.route_clearance.points
    solid = [
        node
        for node in routed.fitted.nodes
        if node.measured.spec.kind not in TRANSPARENT_KINDS
    ]

    def squeezed(owner_id: str, ends: set[str], lines: tuple[tuple[Point, ...], ...]) -> None:
        """A run pressed against a box by its container's edge asks for that edge to move.

        Only the corridor between a box and the container's own boundary is the
        container's to widen; a run squeezed between two siblings is the gap's.
        """

        group = routed.fitted.group(owner_id)
        if group.measured.spec.role == "canvas":
            return
        bounds = group.bounds
        for line in lines:
            for start, end in pairwise(line):
                for node in solid:
                    if node.measured.spec.id in ends:
                        continue
                    for side, to_box, to_edge in _nearness(start, end, node.bounds, bounds):
                        if 0.0 < to_box < clearance and to_edge < 2.0 * clearance:
                            amount = clearance - to_box + lane
                            needs[owner_id][side] = max(needs[owner_id].get(side, 0.0), amount)

    def over_contents(owner_id: str, lines: tuple[tuple[Point, ...], ...]) -> None:
        """A run between a group's title and its contents asks for a corridor there.

        With too little air under the title, a route that has to pass over the
        contents goes round the title instead -- through the band that belongs
        to the words. The room this asks for opens the corridor it wanted.
        """

        group = routed.fitted.group(owner_id)
        if not group.measured.label.lines or group.measured.spec.role == "canvas":
            return
        children = [
            routed.fitted.group(child).bounds
            if child in groups
            else routed.fitted.node(child).bounds
            for child in group.measured.spec.children
        ]
        if not children:
            return
        contents_top = min(bounds.top for bounds in children)
        for line in lines:
            for start, end in pairwise(line):
                if abs(start.y - end.y) < 1e-6 and start.y < contents_top - 1e-6:
                    title_bottom = (
                        group.bounds.top
                        + group.measured.spec.layout.authored_padding(style.group_padding).top
                        + group.measured.label.height
                    )
                    gap = contents_top - title_bottom
                    amount = 2.0 * clearance + lane - gap
                    if amount > 1e-6:
                        needs[owner_id]["top"] = max(needs[owner_id].get("top", 0.0), amount)
                    return

    groups = {group.measured.spec.id for group in routed.fitted.groups}
    for edge in routed.edges:
        ids = (edge.spec.source.node_id, edge.spec.target.node_id)
        owner = bounded_owner(figure, parents, ids)
        over_contents(owner, (edge.centerline,))
        check(owner, edge.centerline)
        squeezed(owner, set(ids), (edge.centerline,))
        if edge.label_metrics is not None and edge.label_position is not None:
            # A caption is ink of its connector: it asks for room the same way.
            box = label_box(edge.label_position, edge.label_metrics)
            check(
                owner,
                (Point(box.left, box.top), Point(box.right, box.bottom)),
            )
    for net in routed.nets:
        ids = tuple(ref.node_id for ref in net.spec.sources + net.spec.targets)
        owner = bounded_owner(figure, parents, ids)
        check(owner, tuple(point for piece in net.pieces for point in piece))
        squeezed(owner, set(ids), net.pieces)
    return {owner: sides for owner, sides in needs.items() if sides}


def with_room(
    figure: FigureSpec,
    needs: dict[str, dict[str, float]],
    style: LayoutStyle,
) -> FigureSpec:
    """``figure`` with the padding ``needs`` asks for added to its containers."""

    groups: list[GroupSpec] = []
    for group in figure.groups:
        extra = needs.get(group.id)
        if not extra:
            groups.append(group)
            continue
        room = tuple(
            current + extra.get(side, 0.0)
            for current, side in zip(group.layout.room, _SIDES, strict=True)
        )
        layout = replace(group.layout, room=room)
        groups.append(replace(group, layout=layout))
    return replace(figure, groups=tuple(groups))


def _nearness(
    start: Point, end: Point, box: Rect, bounds: Rect
) -> tuple[tuple[str, float, float], ...]:
    """For a run beside ``box``: which side of it, how close, and how far to the wall."""

    if abs(start.y - end.y) < 1e-6:
        low, high = sorted((start.x, end.x))
        if min(high, box.right) - max(low, box.left) <= 1e-6:
            return ()
        y = start.y
        return (
            ("top", box.top - y, y - bounds.top),
            ("bottom", y - box.bottom, bounds.bottom - y),
        )
    low, high = sorted((start.y, end.y))
    if min(high, box.bottom) - max(low, box.top) <= 1e-6:
        return ()
    x = start.x
    return (
        ("left", box.left - x, x - bounds.left),
        ("right", x - box.right, bounds.right - x),
    )
