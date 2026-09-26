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
from flexo.geometry import Point, Rect, segment_crosses_rect
from flexo.hierarchy import bounded_owner, parent_map
from flexo.ir.routed import RoutedFigure
from flexo.ir.semantic import FigureSpec, GroupSpec
from flexo.layout.grid import grid_plan
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

    lines = [(edge.spec.id, edge.centerline) for edge in routed.edges] + [
        (net.spec.id, piece) for net in routed.nets for piece in net.pieces
    ]

    def cramped(owner_id: str, edge_id: str, line: tuple[Point, ...], box: Rect) -> None:
        """A caption that found no clear place over or under the contents asks for its height.

        Clear means off every component and every other line, and not so close
        beside another line that it reads as that line's caption.

        Lines running over a row of boxes are packed a lane apart, which leaves
        no room for a caption between them; more room on that side lets them,
        and the caption, spread out.
        """

        inner = box.inflated(-0.5)
        reach = box.inflated(style.port_spacing.points)
        blocked = any(
            node.bounds.intersects(inner, strict=True) for node in solid
        ) or any(
            # Crossed, or close enough to read as that line's caption.
            segment_crosses_rect(start, end, reach)
            for line_id, line in lines
            if line_id != edge_id
            for start, end in pairwise(line)
        )
        if not blocked:
            return
        contents = [
            node.bounds
            for node in solid
            if routed.fitted.group(owner_id).bounds.contains_rect(node.bounds)
        ]
        if not contents:
            return
        # Where the caption wants to be: over the edge's longest horizontal run,
        # or right of its longest vertical one when it has no horizontal run.
        runs = [(start, end) for start, end in pairwise(line) if abs(start.y - end.y) < 1e-6]
        clearance = style.caption_clearance.points
        if not runs:
            upright = [(start, end) for start, end in pairwise(line) if start.x == end.x]
            if not upright:
                # A straight line at an angle (a graph's edge): the gap it
                # spans grows along its longer axis, which spreads the lines
                # that converge on one node and opens room between them.
                # Only a caption drawn over another line asks: one merely near
                # a line where lines converge is the placer's to move.
                if not any(
                    segment_crosses_rect(a, b, inner)
                    for line_id, other in lines
                    if line_id != edge_id
                    for a, b in pairwise(other)
                ):
                    return
                start, end = line[0], line[-1]
                across_x = abs(end.x - start.x) >= abs(end.y - start.y)
                middle = Point((start.x + end.x) / 2.0, (start.y + end.y) / 2.0)
                size = (box.width if across_x else box.height) + clearance
                widen(middle, across_x, size, reach=size)
                return
            start, end = max(upright, key=lambda run: abs(run[1].y - run[0].y))
            # From the line out to the caption's far edge, it runs into the
            # next child: the gap it runs across grows.
            spot = Point(start.x, (start.y + end.y) / 2.0)
            widen(spot, True, box.width + clearance, reach=box.width + clearance)
            return
        start, end = max(runs, key=lambda run: abs(run[1].x - run[0].x))
        level = start.y
        amount = box.height + clearance
        if level < min(bounds.top for bounds in contents):
            needs[owner_id]["top"] = max(needs[owner_id].get("top", 0.0), amount)
        elif level > max(bounds.bottom for bounds in contents):
            needs[owner_id]["bottom"] = max(needs[owner_id].get("bottom", 0.0), amount)
        else:
            # Between two rows of the contents: the gap it spans grows. A
            # caption sits above its line, so the span runs from its top down;
            # failing that, the gap under the line, where it may go instead.
            # A run between two neighbours of a row lies in no column, so the
            # columns its ends stand in are asked too.
            for x in ((start.x + end.x) / 2.0, start.x, end.x):
                if widen(Point(x, level - amount), False, amount, reach=amount) or widen(
                    Point(x, level), False, amount, reach=amount
                ):
                    break

    def widen(spot: Point, across_x: bool, amount: float, reach: float = 0.0) -> bool:
        """Ask the gap at ``spot`` (or within ``reach`` past it) to grow by ``amount``."""

        found = _gutter(routed, spot, across_x, reach)
        if found is None:
            return False
        group_id, boundary = found
        key = f"gap:{boundary}"
        needs[group_id][key] = max(needs[group_id].get(key, 0.0), amount)
        return True

    above: dict[str, int] = defaultdict(int)

    def over_contents(owner_id: str, lines: tuple[tuple[Point, ...], ...]) -> None:
        """Count a connector that runs between a group's title and its contents.

        With too little air under the title, a route that has to pass over the
        contents goes round the title instead -- through the band that belongs
        to the words -- or squeezes against another. Each such connector asks
        for a lane there (see below).
        """

        group = routed.fitted.group(owner_id)
        spec = group.measured.spec
        if not group.measured.label.lines or spec.role == "canvas" or spec.title_below:
            return
        top = _contents_top(owner_id)
        if top is None:
            return
        if any(
            abs(start.y - end.y) < 1e-6 and start.y < top - 1e-6
            for line in lines
            for start, end in pairwise(line)
        ):
            above[owner_id] += 1

    def _contents_top(owner_id: str) -> float | None:
        group = routed.fitted.group(owner_id)
        children = [
            routed.fitted.group(child).bounds
            if child in groups
            else routed.fitted.node(child).bounds
            for child in group.measured.spec.children
        ]
        return min((bounds.top for bounds in children), default=None)

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
            cramped(owner, edge.spec.id, edge.centerline, box)
    for net in routed.nets:
        ids = tuple(ref.node_id for ref in net.spec.sources + net.spec.targets)
        owner = bounded_owner(figure, parents, ids)
        over_contents(owner, net.pieces)
        check(owner, tuple(point for piece in net.pieces for point in piece))
        squeezed(owner, set(ids), net.pieces)
    # Two lines laid closer than a lane in the gap between two neighbours had
    # no room to spread: that gap grows by a lane.
    for spot, across_x in _crowded(routed, style.port_spacing.points):
        widen(spot, across_x, style.port_spacing.points)
    for owner_id, count in above.items():
        # A lane per connector over the contents, with clearance either side.
        group = routed.fitted.group(owner_id)
        title_bottom = (
            group.bounds.top
            + group.measured.spec.layout.authored_padding(style.group_padding).top
            + group.measured.label.height
        )
        gap = (_contents_top(owner_id) or title_bottom) - title_bottom
        amount = 2.0 * clearance + count * lane - gap
        if amount > 1e-6:
            needs[owner_id]["top"] = max(needs[owner_id].get("top", 0.0), amount)
    return {owner: sides for owner, sides in needs.items() if sides}


def crossings(routed: RoutedFigure) -> list[tuple[str, str]]:
    """Pairs of connectors whose routed lines cross, as lint counts them."""

    routes: list[tuple[str, str | None, tuple[Point, ...]]] = [
        (edge.spec.id, edge.bundle, edge.centerline)
        for edge in routed.edges
        if not edge.straight
    ]
    for net in routed.nets:
        routes.extend((net.spec.id, net.bundle, piece) for piece in net.pieces or ())
    result = []
    seen: set[tuple[str, str]] = set()
    for index, (first_id, first_bundle, first) in enumerate(routes):
        for second_id, second_bundle, second in routes[index + 1 :]:
            if first_id == second_id or (first_bundle and first_bundle == second_bundle):
                continue
            key = (first_id, second_id)
            if key in seen:
                continue
            if any(
                _crosses(a, b, c, d) for a, b in pairwise(first) for c, d in pairwise(second)
            ):
                seen.add(key)
                result.append(key)
    return result


def crossing_room(routed: RoutedFigure, style: LayoutStyle) -> list[dict[str, dict[str, float]]]:
    """Room worth trying for each crossing: a lane along the top or bottom of its container."""

    figure = routed.fitted.measured.semantic
    parents = parent_map(figure.groups)
    lane = 2.0 * style.route_clearance.points + style.port_spacing.points
    edges = {edge.spec.id: edge for edge in routed.edges}
    offers: list[dict[str, dict[str, float]]] = []
    for pair in crossings(routed):
        for connector in pair:
            edge = edges.get(connector)
            if edge is None:
                continue
            ends = (edge.spec.source.node_id, edge.spec.target.node_id)
            owner = bounded_owner(figure, parents, ends)
            for side in _open_sides(routed, owner, ends, lane):
                offer = {owner: {side: lane}}
                if offer not in offers:
                    offers.append(offer)
    return offers


def _open_sides(
    routed: RoutedFigure, owner_id: str, ends: tuple[str, str], lane: float
) -> tuple[str, ...]:
    """The container edges a route between ``ends`` could run along: top when
    both ends sit in the top row of the contents, bottom when both sit in the
    bottom row. Only there would a lane of room open a way round."""

    boxes = [routed.fitted.node(node_id).bounds for node_id in ends]
    contents = [
        node.bounds
        for node in routed.fitted.nodes
        if routed.fitted.group(owner_id).bounds.contains_rect(node.bounds)
    ]
    if not contents:
        return ()
    top = min(bounds.top for bounds in contents)
    bottom = max(bounds.bottom for bounds in contents)
    sides = []
    if all(bounds.top <= top + lane for bounds in boxes):
        sides.append("top")
    if all(bounds.bottom >= bottom - lane for bounds in boxes):
        sides.append("bottom")
    return tuple(sides)


def _crosses(a: Point, b: Point, c: Point, d: Point) -> bool:
    first_horizontal = abs(a.y - b.y) < 1e-9
    second_horizontal = abs(c.y - d.y) < 1e-9
    if first_horizontal == second_horizontal:
        return False
    (h1, h2), (v1, v2) = ((a, b), (c, d)) if first_horizontal else ((c, d), (a, b))
    x_low, x_high = sorted((h1.x, h2.x))
    y_low, y_high = sorted((v1.y, v2.y))
    return x_low + 1e-7 < v1.x < x_high - 1e-7 and y_low + 1e-7 < h1.y < y_high - 1e-7


def with_room(
    figure: FigureSpec,
    needs: dict[str, dict[str, float]],
    style: LayoutStyle,
) -> FigureSpec:
    """``figure`` with the padding and gaps ``needs`` asks for added to its groups."""

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
        gaps = list(group.layout.gap_room)
        for key, amount in extra.items():
            if key.startswith("gap:"):
                index = int(key[4:])
                gaps.extend([0.0] * (index + 1 - len(gaps)))
                gaps[index] += amount
        layout = replace(group.layout, room=room, gap_room=tuple(gaps))
        groups.append(replace(group, layout=layout))
    return replace(figure, groups=tuple(groups))


def _gutter(
    routed: RoutedFigure, spot: Point, across_x: bool, reach: float = 0.0
) -> tuple[str, int] | None:
    """The innermost row (``across_x``) or column holding ``spot`` with a gap
    between two neighbouring children within ``reach`` past it: its id and the
    gap's index. ``spot`` is where the squeezed thing starts, ``reach`` how far
    it extends along the axis."""

    fitted = routed.fitted
    wanted = "row" if across_x else "column"
    at = spot.x if across_x else spot.y
    best: tuple[float, float, str, int] | None = None
    for group in fitted.groups:
        spec = group.measured.spec
        if spec.layout.kind not in {wanted, "grid"} or not group.bounds.contains_point(spot):
            continue
        rects = []
        for child in spec.children:
            try:
                rects.append(fitted.node(child).bounds)
            except StopIteration:
                rects.append(fitted.group(child).bounds)
        for index, low, high in _gaps_of(spec, rects, across_x):
            if high + 1e-6 < at or low - 1e-6 > at + reach:
                continue
            area = group.bounds.width * group.bounds.height
            candidate = (area, max(0.0, low - at), spec.id, index)
            if best is None or candidate[:2] < best[:2]:
                best = candidate
    return None if best is None else (best[2], best[3])


def _gaps_of(
    spec: GroupSpec, rects: list[Rect], across_x: bool
) -> list[tuple[int, float, float]]:
    """``(gap index, start, end)`` of each gap between a group's children along x
    (``across_x``) or y, indexed the way layout indexes them."""

    if spec.layout.kind != "grid":
        return [
            (index, first.right, second.left) if across_x else (index, first.bottom, second.top)
            for index, (first, second) in enumerate(pairwise(rects))
        ]
    plan = grid_plan(spec.layout, spec.children)
    tracks: dict[int, list[Rect]] = defaultdict(list)
    for (row, column), rect in zip(plan.cells, rects, strict=True):
        tracks[column if across_x else row].append(rect)
    count = plan.columns if across_x else plan.rows
    result = []
    for track in range(count - 1):
        before, after = tracks.get(track), tracks.get(track + 1)
        if not before or not after:
            continue
        low = max(rect.right if across_x else rect.bottom for rect in before)
        high = min(rect.left if across_x else rect.top for rect in after)
        # A grid lists its column gaps, then its row gaps.
        index = track if across_x else max(0, plan.columns - 1) + track
        result.append((index, low, high))
    return result


def _crowded(routed: RoutedFigure, lane: float) -> list[tuple[Point, bool]]:
    """Where two different lines run parallel closer than a lane: the middle of
    the stretch they share, and whether they are apart along x."""

    routes: list[tuple[str, str | None, tuple[Point, ...]]] = [
        (edge.spec.id, edge.bundle, edge.centerline) for edge in routed.edges if not edge.straight
    ]
    routes.extend((net.spec.id, net.bundle, piece) for net in routed.nets for piece in net.pieces)
    runs = [
        (route_id, bundle, start, end)
        for route_id, bundle, line in routes
        for start, end in pairwise(line)
        if (start.x == end.x) != (start.y == end.y)
    ]
    spots: list[tuple[Point, bool]] = []
    for index, (first_id, first_bundle, a, b) in enumerate(runs):
        upright = a.x == b.x
        for second_id, second_bundle, c, d in runs[index + 1 :]:
            if second_id == first_id or (first_bundle and first_bundle == second_bundle):
                continue
            if (c.x == d.x) != upright:
                continue
            if upright:
                apart = abs(a.x - c.x)
                low = max(min(a.y, b.y), min(c.y, d.y))
                high = min(max(a.y, b.y), max(c.y, d.y))
            else:
                apart = abs(a.y - c.y)
                low = max(min(a.x, b.x), min(c.x, d.x))
                high = min(max(a.x, b.x), max(c.x, d.x))
            if apart >= lane - 1e-3 or high - low <= lane:
                continue
            middle = (low + high) / 2.0
            if upright:
                spots.append((Point((a.x + c.x) / 2.0, middle), True))
            else:
                spots.append((Point(middle, (a.y + c.y) / 2.0), False))
    return spots


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
