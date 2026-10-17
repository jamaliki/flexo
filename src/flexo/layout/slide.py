"""Slide a group across its parent's axis so the arrows leaving it can run straight.

A column centres what it holds, and a row of inputs above a block is centred like
anything else. When those inputs feed ports near one end of the block, or feed two
blocks, the centred row leaves an input outside the stretch its port can slide
to, and its arrow jogs sideways. Port adaptation cannot mend that: it moves ports,
not boxes.

This pass moves boxes, within limits. A group whose parent stacks the other way
(a row in a column, a column in a row) may slide along its own axis, as far as
its parent's content box allows; siblings sit above and below it, so nothing can
collide. It slides only when that lets more of its arrows reach their ports
straight, and then by the least distance that does, so a figure that already
reads straight is left exactly as it was.

So does a box joined by one line to one other (a store under the queue that feeds
it), in a parent that centres what it holds -- before the groups, and again after:
it goes centred on that other box, as far as its parent's room allows, so its line
runs straight from the middle of one side to the middle of the other. A line that is
the only one on its side meets it at its middle (``flexo.routing.pins``), so that is
the one way it runs straight. A group still slides as it did, for its lines as the
ports could meet them: a row over a box several lines come into stays centred over it.

And a box at the end of its row or column, joined by one line to a box standing beside
that row or column (the last step of one branch, fed from the branch beside it), goes
level with that box, further from the rest of its own line -- two branches side by side
whose steps are of different heights, or have a line between them in one and none in the
other, still end on one line. It goes only where the room of what holds its line allows,
so nothing else moves.

No group lined up by one of its parts (its anchor: ``flexo.layout.measure``) slides
while a line of that part's runs between the middles of two faces it has to itself: it
stays where its parent lined it up rather than set that line off them to straighten
another. (A row of parts that speak for it together still slides, as it did.)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from itertools import pairwise

from flexo.components import centred_port
from flexo.geometry import Point, Rect, Side
from flexo.hierarchy import lined_up
from flexo.ir.fitted import FittedGroup, FittedNode, ResolvedPort
from flexo.ir.semantic import FigureSpec, LayoutKind, layout_connections
from flexo.layout.measure import anchor_children, outward_connections
from flexo.style import LayoutStyle
from flexo.title_sides import drawn_span, middle_y

_CENTER_BAND_FRACTION = 0.3
"""How far port adaptation may slide a port, as a fraction of its side (see ``ports``)."""

_SLIDING_ALIGNMENTS = frozenset({"center", "ports"})
"""Parents whose cross placement is a default, not a request to sit at one edge."""

_EPSILON = 1e-6

_CENTRED = 0.5
"""How near level the middles of two boxes are, in points, for a line to run between them."""


def slide_groups(
    figure: FigureSpec,
    nodes: tuple[FittedNode, ...],
    groups: tuple[FittedGroup, ...],
    kinds: dict[str, LayoutKind],
    style: LayoutStyle,
) -> tuple[tuple[FittedNode, ...], tuple[FittedGroup, ...]]:
    """Nodes and groups, with each slidable group moved to straighten its arrows.

    Parents go first: a group slides with everything in it, and its children then
    judge their own slides from where it ended up.
    """

    parent = {
        child: group.measured.spec.id for group in groups for child in group.measured.spec.children
    }
    order = {group.measured.spec.id: index for index, group in enumerate(groups)}
    by_node = {node.measured.spec.id: node for node in nodes}
    written = {node.id: index for index, node in enumerate(figure.nodes)}
    by_group = {group.measured.spec.id: group for group in groups}
    every = layout_connections(figure)
    served = Counter(
        (end.node_id, end.port_name)
        for connection in every
        for end in (connection.source, connection.target)
    )
    # A straight-drawn or lane-routed line goes where it is told, whatever the
    # ports do, and a net meets its taps with a shared rail, not a straight run. A
    # fixed port that serves several arrows (a diamond's vertex) can send only one
    # of them straight, and the router picks which, so none of them can vouch for
    # a slide.
    connections = tuple(
        connection
        for connection in every
        if connection.source.node_id != connection.target.node_id
        and not connection.externally_routed
        and not connection.from_net
        and not any(
            served[(end.node_id, end.port_name)] > 1
            and not _adaptive(by_node[end.node_id], end.port_name)
            for end in (connection.source, connection.target)
        )
    )
    # A box joined by one line to one other, in a parent that centres what it holds: centred
    # on that other box, its line straight -- it moves, not the row it goes under.
    joined = Counter(
        end.node_id
        for connection in every
        if connection.source.node_id != connection.target.node_id
        for end in (connection.source, connection.target)
    )

    def lone_boxes() -> None:
        for node in figure.nodes:
            owner = parent.get(node.id)
            # (One its person lined up with a part of their choosing stays there: aligned_with.)
            if owner is None or joined[node.id] != 1 or owner not in by_group or node.align_with:
                continue
            holder = by_group[owner].measured.spec.layout
            across = (
                _slide_axis(kinds.get(owner), holder.align) if holder.align == "center" else None
            )
            if across is None:
                continue
            shift = _best_shift(
                by_node[node.id].bounds,
                _beside_room(owner, node.id, by_node, by_group, across),
                across,
                {node.id},
                connections,
                by_node,
                style,
                written,
                every,
                figure,
                parent,
            )
            if abs(shift) > _EPSILON:
                dx, dy = (shift, 0.0) if across == "x" else (0.0, shift)
                by_node[node.id] = _moved_node(by_node[node.id], dx, dy)

    outward = outward_connections(figure)
    node_kinds = {node.id: node.kind for node in figure.nodes}

    def voice(group_id: str) -> str | None:
        """The one part a group's port line is taken from (``anchor_children``, down through
        the groups it holds), or None where several speak for it together: the part its
        parent lined up with what stands beside the group."""

        while group_id in by_group:
            spec = by_group[group_id].measured.spec
            speakers = anchor_children(spec, node_kinds, outward.get(group_id, {}))
            if len(speakers) != 1:
                return None
            group_id = speakers[0]
        return group_id if group_id in by_node else None

    def branch_ends() -> None:
        for node in figure.nodes:
            owner = parent.get(node.id)
            if owner is None or joined[node.id] != 1 or owner not in by_group or node.align_with:
                continue
            along = {"row": "x", "column": "y"}.get(kinds.get(owner) or "")
            holder = parent.get(owner)
            if along is None or holder is None or holder not in by_group:
                continue
            other = next(
                (
                    end.node_id
                    for connection in every
                    if node.id in (connection.source.node_id, connection.target.node_id)
                    for end in (connection.source, connection.target)
                    if end.node_id != node.id
                ),
                None,
            )
            within = _nodes_within(owner, by_group)
            if other is None or other in within or other not in by_node:
                continue
            shift, over = _level_shift(
                by_node[node.id].bounds,
                by_node[other].bounds,
                by_group[owner],
                by_group[holder].content_bounds,
                [by_node[each].bounds for each in within if each != node.id],
                [by_node[each].bounds for each in by_node if each not in within],
                along,
                style.gap.points,
                # (Level by what they draw: a named molecule's middle is its molecule's.)
                lift=(middle_y(by_node[other]) - by_node[other].bounds.center.y)
                - (middle_y(by_node[node.id]) - by_node[node.id].bounds.center.y),
            )
            if abs(shift) <= _EPSILON:
                continue
            outer = _holders(owner, parent)
            if over > _EPSILON and not _room_beyond(
                outer, over, along, by_node, by_group, parent, style.gap.points
            ):
                continue
            dx, dy = (shift, 0.0) if along == "x" else (0.0, shift)
            by_node[node.id] = _moved_node(by_node[node.id], dx, dy)
            # Its line reaches as far as it now does: a frame round it is round it still --
            # and every group round that, the page too, where it reaches past their end.
            by_group[owner] = _reaching(by_group[owner], by_node[node.id].bounds)
            for inner, group_id in pairwise((owner, *outer)):
                by_group[group_id] = _reaching(by_group[group_id], by_group[inner].bounds)

    lone_boxes()
    branch_ends()
    for group_id in sorted(by_group, key=lambda name: (_depth(name, parent), order[name])):
        owner = parent.get(group_id)
        if owner is None:
            continue
        across = _slide_axis(kinds.get(owner), by_group[owner].measured.spec.layout.align)
        if across is None:
            continue
        members = _nodes_within(group_id, by_group)
        shift = _best_shift(
            by_group[group_id].bounds,
            by_group[owner].content_bounds,
            across,
            members,
            connections,
            by_node,
            style,
            written,
            settled=every,
            voice=voice(group_id),
        )
        if abs(shift) <= _EPSILON:
            continue
        dx, dy = (shift, 0.0) if across == "x" else (0.0, shift)
        for node_id in members:
            by_node[node_id] = _moved_node(by_node[node_id], dx, dy)
        for inner in _groups_within(group_id, by_group):
            by_group[inner] = _moved_group(by_group[inner], dx, dy)
    # (Again, should the groups it sits among have slid since.)
    lone_boxes()
    branch_ends()
    return (
        tuple(by_node[node.measured.spec.id] for node in nodes),
        tuple(by_group[group.measured.spec.id] for group in groups),
    )


def aligned_with(
    figure: FigureSpec,
    nodes: tuple[FittedNode, ...],
    groups: tuple[FittedGroup, ...],
    kinds: dict[str, LayoutKind],
) -> tuple[FittedNode, ...]:
    """Nodes, each one that names a part or group to line up with (``align_with``) centred
    on it across the way its row or column runs -- as far as its group's room allows, so
    nothing else moves, and the row it goes under neither spreads nor shifts."""

    asked = {node.id: node.align_with for node in figure.nodes if node.align_with}
    if not asked:
        return nodes
    parent = {
        child: group.measured.spec.id for group in groups for child in group.measured.spec.children
    }
    by_node = {node.measured.spec.id: node for node in nodes}
    by_group = {group.measured.spec.id: group for group in groups}
    for node_id, target in asked.items():
        owner = parent.get(node_id)
        box = by_node[target].bounds if target in by_node else by_group.get(target)
        if owner is None or box is None or node_id not in by_node or target == node_id:
            continue
        box = box if isinstance(box, Rect) else box.bounds
        own = by_node[node_id].bounds
        across = {"column": "x", "stack": "x", "row": "y"}.get(kinds.get(owner, ""))
        if kinds.get(owner) == "grid":
            # In a grid, across its column (or row) -- the one the two share: a spine of
            # blocks down a figure's side, each centred under the last; along it, turned.
            above = abs(box.center.x - own.center.x) <= abs(box.center.y - own.center.y)
            across = "x" if above else "y"
            room = _track_room(owner, node_id, by_node, by_group, across)
        elif across is None:
            continue
        else:
            room = _beside_room(owner, node_id, by_node, by_group, across)
        if across == "x":
            want = box.center.x - own.width / 2.0
            at = max(room.left, min(want, room.right - own.width))
            shift = (at - own.x, 0.0)
        else:
            want = box.center.y - own.height / 2.0
            at = max(room.top, min(want, room.bottom - own.height))
            shift = (0.0, at - own.y)
        if abs(shift[0]) > _EPSILON or abs(shift[1]) > _EPSILON:
            by_node[node_id] = _moved_node(by_node[node_id], *shift)
        short = want - at
        if (
            kinds.get(owner) == "grid"
            and abs(short) > _EPSILON
            and target in by_node
            and target not in asked
            and parent.get(target) == owner
        ):
            # Too large to move all the way within its track (the tallest of its row), it
            # is met by the part it lines up with, as far as that part's room allows: a
            # spine turned to fit a slide stays one straight line.
            theirs = by_node[target].bounds
            room = _track_room(owner, target, by_node, by_group, across)
            if across == "x":
                to = max(room.left, min(theirs.x - short, room.right - theirs.width))
                moved = (to - theirs.x, 0.0)
            else:
                to = max(room.top, min(theirs.y - short, room.bottom - theirs.height))
                moved = (0.0, to - theirs.y)
            if abs(moved[0]) > _EPSILON or abs(moved[1]) > _EPSILON:
                by_node[target] = _moved_node(by_node[target], *moved)
    return tuple(by_node[node.measured.spec.id] for node in nodes)


def _track_room(
    owner: str,
    node_id: str,
    nodes: dict[str, FittedNode],
    groups: dict[str, FittedGroup],
    across: str,
) -> Rect:
    """Where a part in a grid may go across its column (``across="x"``) or its row: as far
    as the parts of that track reach, so it never leaves its own cell for a neighbour's."""

    own = nodes[node_id].bounds
    boxes = [
        nodes[child].bounds if child in nodes else groups[child].bounds
        for child in groups[owner].measured.spec.children
        if child in nodes or child in groups
    ]
    if across == "x":
        track = [box for box in boxes if box.left < own.right and box.right > own.left]
        low, high = min(box.left for box in track), max(box.right for box in track)
        return Rect(low, own.y, high - low, own.height)
    track = [box for box in boxes if box.top < own.bottom and box.bottom > own.top]
    low, high = min(box.top for box in track), max(box.bottom for box in track)
    return Rect(own.x, low, own.width, high - low)


def _beside_room(
    owner: str,
    node_id: str,
    nodes: dict[str, FittedNode],
    groups: dict[str, FittedGroup],
    across: str,
) -> Rect:
    """Where a part on a line of its own may go across its group: as far as the lines
    beside it reach (a row over it), so it never makes the figure wider -- nor the figure
    on a slide smaller, its other parts moving -- or its group's room, should it be wider
    than they are already."""

    room = groups[owner].content_bounds
    others = [
        (nodes[child].bounds if child in nodes else groups[child].content_bounds)
        for child in groups[owner].measured.spec.children
        if child != node_id and (child in nodes or child in groups)
    ]
    own = nodes[node_id].bounds
    if not others:
        return room
    if across == "x":
        low, high = min(box.left for box in others), max(box.right for box in others)
        if high - low < own.width:
            return room
        return Rect(
            max(low, room.left), room.y, min(high, room.right) - max(low, room.left), room.height
        )
    low, high = min(box.top for box in others), max(box.bottom for box in others)
    if high - low < own.height:
        return room
    return Rect(room.x, max(low, room.top), room.width, min(high, room.bottom) - max(low, room.top))


def _level_shift(
    own: Rect,
    other: Rect,
    line: FittedGroup,
    room: Rect,
    beside: list[Rect],
    others: list[Rect],
    along: str,
    gap: float,
    lift: float = 0.0,
) -> tuple[float, float]:
    """How far a box at the end of its row or column (``line``, running ``along`` x or y)
    goes along it to stand level with the box its one line joins it to (``other``) -- down a
    column, ``lift`` further, where the middles of what they draw are not their boxes' -- or 0:
    only away from the parts ``beside`` it on its line, only if ``other`` stands beside the
    line rather than before or after it, and never onto (or within half a gap of) one of the
    ``others`` -- and how far past the end of ``room`` the line (its frame, should it have
    one) then reaches. Going on past its end -- down a column, right along a row -- the room
    grows that far, if nothing stands in the way (``branch_ends``); before its start it may
    not go, as what is there would have to move."""

    frame, parts = line.bounds, line.content_bounds
    if along == "y":
        aside = other.right <= frame.left + _EPSILON or other.left >= frame.right - _EPSILON
        shift = other.center.y - own.center.y + lift
        last = all(box.bottom <= own.top + _EPSILON for box in beside)
        first = all(box.top >= own.bottom - _EPSILON for box in beside)
        moved = Rect(own.x, own.y + shift, own.width, own.height)
        before = room.top - _EPSILON <= moved.top - (parts.top - frame.top)
        over = moved.bottom + (frame.bottom - parts.bottom) - room.bottom
    else:
        aside = other.bottom <= frame.top + _EPSILON or other.top >= frame.bottom - _EPSILON
        shift = other.center.x - own.center.x
        last = all(box.right <= own.left + _EPSILON for box in beside)
        first = all(box.left >= own.right - _EPSILON for box in beside)
        moved = Rect(own.x + shift, own.y, own.width, own.height)
        before = room.left - _EPSILON <= moved.left - (parts.left - frame.left)
        over = moved.right + (frame.right - parts.right) - room.right
    if not beside or not aside or not before or (over > _EPSILON and shift <= 0.0):
        return 0.0, 0.0
    if not ((last and shift > _EPSILON) or (first and shift < -_EPSILON)):
        return 0.0, 0.0
    near = moved.inflated(gap / 2.0)
    if any(_overlap(box, near) for box in others):
        return 0.0, 0.0
    return shift, max(over, 0.0)


def _holders(group_id: str, parent: dict[str, str]) -> list[str]:
    """The groups ``group_id`` is in, from its own holder out to the figure's root."""

    found = []
    while group_id in parent:
        group_id = parent[group_id]
        found.append(group_id)
    return found


def _room_beyond(
    holders: list[str],
    over: float,
    along: str,
    nodes: dict[str, FittedNode],
    groups: dict[str, FittedGroup],
    parent: dict[str, str],
    gap: float,
) -> bool:
    """Whether each of ``holders`` -- the groups round a line that is to reach ``over``
    past the end of the first of them -- may grow that far ``along`` its end: nothing of
    another group's is there, nor a ``gap`` past it. (The figure's root may always: its
    page grows.)"""

    reach = over + gap - _EPSILON
    for group_id in holders[:-1]:
        box = groups[group_id].bounds
        grown = (
            Rect(box.x, box.bottom, box.width, reach)
            if along == "y"
            else Rect(box.right, box.y, reach, box.height)
        )
        mine = _nodes_within(group_id, groups)
        if any(_overlap(node.bounds, grown) for name, node in nodes.items() if name not in mine):
            return False
        around = {group_id, *_holders(group_id, parent)}
        if any(
            _overlap(other.bounds, grown)
            for name, other in groups.items()
            if name not in around and name not in _groups_within(group_id, groups)
        ):
            return False
    return True


def _overlap(a: Rect, b: Rect) -> bool:
    return a.left < b.right and a.right > b.left and a.top < b.bottom and a.bottom > b.top


def _reaching(group: FittedGroup, box: Rect) -> FittedGroup:
    """``group`` with its bounds, and the room of its parts, reaching as far as ``box``."""

    def reached(rect: Rect) -> Rect:
        left, top = min(rect.left, box.left), min(rect.top, box.top)
        right, bottom = max(rect.right, box.right), max(rect.bottom, box.bottom)
        return Rect(left, top, right - left, bottom - top)

    content = reached(group.content_bounds)
    if content == group.content_bounds:
        return group
    grown = Rect(
        group.bounds.x + (content.x - group.content_bounds.x),
        group.bounds.y + (content.y - group.content_bounds.y),
        group.bounds.width + (content.width - group.content_bounds.width),
        group.bounds.height + (content.height - group.content_bounds.height),
    )
    return replace(group, bounds=grown, content_bounds=content)


def _depth(group_id: str, parent: dict[str, str]) -> int:
    depth = 0
    while group_id in parent:
        group_id = parent[group_id]
        depth += 1
    return depth


def _slide_axis(kind: LayoutKind | None, align: str) -> str | None:
    """The axis a child of this parent may slide along, or None when it may not."""

    if align not in _SLIDING_ALIGNMENTS:
        return None
    if kind in {"column", "stack"}:
        return "x"
    if kind == "row":
        return "y"
    return None


def _nodes_within(group_id: str, groups: dict[str, FittedGroup]) -> set[str]:
    found: set[str] = set()
    for child in groups[group_id].measured.spec.children:
        if child in groups:
            found |= _nodes_within(child, groups)
        else:
            found.add(child)
    return found


def _groups_within(group_id: str, groups: dict[str, FittedGroup]) -> list[str]:
    found = [group_id]
    for child in groups[group_id].measured.spec.children:
        if child in groups:
            found += _groups_within(child, groups)
    return found


def _best_shift(
    bounds: Rect,
    room: Rect,
    across: str,
    members: set[str],
    connections: tuple,
    nodes: dict[str, FittedNode],
    style: LayoutStyle,
    written: dict[str, int] | None = None,
    every: tuple = (),
    figure: FigureSpec | None = None,
    parents: dict[str, str] | None = None,
    settled: tuple = (),
    voice: str | None = None,
) -> float:
    """The slide that lets the most arrows run straight, centred among them, or 0.

    Of slides that straighten as many, one that straightens an arrow running on, from
    a part written earlier to one written later, beats one that straightens a loop back:
    a part stays where its flow put it when a line back to it is drawn.

    Given all the figure's connections (``settled``) and the one part that speaks for
    what slides (``voice``: a group's anchor), no slide at all while an arrow of that
    part's runs between the middles of two faces it has to itself (``_settled``).
    """

    if across == "x":
        low, high = room.left - bounds.left, room.right - bounds.right
    else:
        low, high = room.top - bounds.top, room.bottom - bounds.bottom
    if high - low <= _EPSILON:
        return 0.0
    low, high = min(low, 0.0), max(high, 0.0)
    pairs = []
    forward: set[int] = set()
    # Lines from several of these into one port of a box beyond are a fan: straight only
    # all together (Q and K over the product they feed) -- one of a row of four over the
    # box they all feed is no reason to slide the rest aside.
    fans: list[tuple[str, str]] = []
    for connection in connections:
        ends = (connection.source, connection.target)
        inside = [end for end in ends if end.node_id in members]
        if len(inside) != 1:
            continue
        mine = inside[0]
        other = connection.target if mine is connection.source else connection.source
        pair = _reaches(
            nodes[mine.node_id],
            mine.port_name,
            nodes[other.node_id],
            other.port_name,
            across,
            style,
            every,
            nodes,
            figure is not None and lined_up(figure, parents or {}, mine.node_id, other.node_id),
        )
        if pair is not None and not _blocked(
            nodes, members, other.node_id, bounds, pair[1], across
        ):
            if mine.node_id == voice and _settled(
                nodes[mine.node_id], nodes[other.node_id], across, settled, nodes
            ):
                # The group was lined up by this part, and its line runs between the
                # middles of two faces it has to itself: no slide that straightens another
                # is worth setting it off them.
                return 0.0
            pairs.append(pair)
            # (Lines coming into the one port; lines it sends out to several are each their own.)
            fans.append(
                (other.node_id, other.port_name)
                if other is connection.target
                else (str(len(pairs)), "")
            )
            onward = (written or {}).get(connection.source.node_id, 0) <= (written or {}).get(
                connection.target.node_id, 0
            )
            if onward:
                forward.add(len(pairs) - 1)
    if not pairs:
        return 0.0
    # Each arrow runs straight over a window of slides; the best slide lies at a
    # window's edge, or where one arrow's two ends sit exactly opposite each other.
    candidates = {0.0, low, high}
    for (mine_low, mine_high), (other_low, other_high) in pairs:
        candidates |= {
            other_high - mine_low,
            other_low - mine_high,
            (other_low + other_high - mine_low - mine_high) / 2.0,
        }
    choices = [value for value in candidates if low - _EPSILON <= value <= high + _EPSILON]

    def straight(shift: float) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        return [pairs[index] for index in straightened(shift)]

    def straightened(shift: float) -> list[int]:
        straight = {
            index
            for index, pair in enumerate(pairs)
            if pair[0][0] + shift <= pair[1][1] + _EPSILON
            and pair[1][0] <= pair[0][1] + shift + _EPSILON
        }
        return [
            index
            for index in sorted(straight)
            if all(other in straight for other, fan in enumerate(fans) if fan == fans[index])
        ]

    def off_centre(shift: float) -> float:
        return sum(
            abs((mine_low + mine_high) / 2.0 + shift - (other_low + other_high) / 2.0)
            for (mine_low, mine_high), (other_low, other_high) in straight(shift)
        )

    # Only more straight arrows justify a slide: a bend that stays a bend is no
    # better for being shorter, and a nudge of a point or two is port adaptation's job.
    best = min(
        choices,
        key=lambda value: (
            -len(straight(value)),
            -len(forward.intersection(straightened(value))),
            round(off_centre(value), 3),
            abs(value),
        ),
    )
    return best if len(straight(best)) > len(straight(0.0)) else 0.0


def _reaches(
    mine: FittedNode,
    mine_port: str,
    other: FittedNode,
    other_port: str,
    across: str,
    style: LayoutStyle,
    every: tuple = (),
    nodes: dict[str, FittedNode] | None = None,
    lined: bool = False,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Where each end of an arrow can sit along the slide axis, if the arrow runs
    across it: from one box to a box beyond it along the parent's stacking axis.

    Judged from where the boxes sit, not from the sides the ports are on yet: a
    port several arrows share takes the side most of them want, and the router
    still brings an odd one in on the face it arrives at. An end that is the only
    one on the face it arrives at sits at that face's middle (``every``: all the
    figure's connections, to tell) -- but on a line between parts ``lined`` up
    otherwise than centred (``flexo.hierarchy.lined_up``), which slides as it can.
    """

    if across == "x":
        beyond = other.bounds.bottom <= mine.bounds.top or other.bounds.top >= mine.bounds.bottom
    else:
        beyond = other.bounds.right <= mine.bounds.left or other.bounds.left >= mine.bounds.right
    if not beyond:
        return None
    faces = {Side.NORTH, Side.SOUTH} if across == "x" else {Side.EAST, Side.WEST}
    first, second = mine.port(mine_port), other.port(other_port)
    if first.side in faces and first.side is second.side:
        return None
    lone = nodes is not None and bool(every) and not lined
    return (
        _reach(
            mine, first, across, faces, style, lone and _alone(mine, other, across, every, nodes)
        ),
        _reach(
            other, second, across, faces, style, lone and _alone(other, mine, across, every, nodes)
        ),
    )


def _settled(
    mine: FittedNode, other: FittedNode, across: str, every: tuple, nodes: dict[str, FittedNode]
) -> bool:
    """Whether the line between two boxes already runs from the middle of one's face to
    the middle of the other's, each face that line's alone: where lining them up put it."""

    if across == "x":
        apart = abs(mine.bounds.center.x - other.bounds.center.x)
    else:
        # (A named molecule's middle is its drawing's: flexo.title_sides.)
        apart = abs(middle_y(mine) - middle_y(other))
    return (
        apart <= _CENTRED
        and _alone(mine, other, across, every, nodes)
        and _alone(other, mine, across, every, nodes)
    )


def _alone(
    node: FittedNode, other: FittedNode, across: str, every: tuple, nodes: dict[str, FittedNode]
) -> bool:
    """Whether ``node``'s end of its line to ``other`` is the only end on the face of it
    that faces ``other`` (its top or bottom, for a slide ``across`` x): no other line of
    its goes that way."""

    me = node.measured.spec.id

    def beyond(box: Rect) -> int:
        mine = node.bounds
        if across == "x":
            return (box.top >= mine.bottom) - (box.bottom <= mine.top)
        return (box.left >= mine.right) - (box.right <= mine.left)

    way = beyond(other.bounds)
    count = 0
    for connection in every:
        ends = (connection.source.node_id, connection.target.node_id)
        if me not in ends or ends[0] == ends[1]:
            continue
        far = ends[1] if ends[0] == me else ends[0]
        if far in nodes and beyond(nodes[far].bounds) == way:
            count += 1
    return count == 1


def _blocked(
    nodes: dict[str, FittedNode],
    members: set[str],
    other_id: str,
    bounds: Rect,
    reach: tuple[float, float],
    across: str,
) -> bool:
    """True when some box stands between the group and the arrow's far end, across
    every place that end could be: the arrow bends around it wherever the group sits,
    so it has no say in where the group goes."""

    other = nodes[other_id].bounds
    if across == "x":
        near, far = (
            (bounds.bottom, other.top) if other.top >= bounds.bottom else (other.bottom, bounds.top)
        )
    else:
        near, far = (
            (bounds.right, other.left) if other.left >= bounds.right else (other.right, bounds.left)
        )
    for node_id, node in nodes.items():
        if node_id in members or node_id == other_id:
            continue
        box = node.bounds
        along = (box.top, box.bottom) if across == "x" else (box.left, box.right)
        side = (box.left, box.right) if across == "x" else (box.top, box.bottom)
        if (
            along[0] < far - _EPSILON
            and along[1] > near + _EPSILON
            and (side[0] <= reach[0] + _EPSILON and side[1] >= reach[1] - _EPSILON)
        ):
            return True
    return False


def _reach(
    node: FittedNode,
    port: ResolvedPort,
    across: str,
    faces: set[Side],
    style: LayoutStyle,
    alone: bool = False,
) -> tuple[float, float]:
    """The stretch of its face a port may slide to (a point, if it does not adapt).

    A port on another face for now is taken from the middle of the facing one; an end
    ``alone`` on its face at a port the grammar gave the box, from its middle exactly.
    """

    bounds = node.bounds
    start, length = (bounds.left, bounds.width) if across == "x" else (bounds.top, bounds.height)
    spec = next(item for item in node.measured.spec.ports if item.name == port.name)
    if alone and centred_port(node.measured.spec.kind, spec):
        at = start + length / 2.0
        # (A named structure's, picture's or mechanism's at the middle of its drawing.)
        drawn = drawn_span(node) if across == "y" and port.side in faces else None
        if drawn is not None:
            at = (drawn[0] + drawn[1]) / 2.0
        return at, at
    if port.side in faces:
        at = port.position.x if across == "x" else port.position.y
    else:
        at = start + length / 2.0
    if not _adaptive(node, port.name):
        return at, at
    margin = min(style.corner_radius.points, length / 2.0)
    reach = _CENTER_BAND_FRACTION * length
    return max(start + margin, at - reach), min(start + length - margin, at + reach)


def _adaptive(node: FittedNode, name: str) -> bool:
    return next(port for port in node.measured.spec.ports if port.name == name).adaptive


def _moved_node(node: FittedNode, dx: float, dy: float) -> FittedNode:
    return replace(
        node,
        bounds=Rect(node.bounds.x + dx, node.bounds.y + dy, node.bounds.width, node.bounds.height),
        ports=tuple(
            ResolvedPort(port.name, port.side, Point(port.position.x + dx, port.position.y + dy))
            for port in node.ports
        ),
    )


def _moved_group(group: FittedGroup, dx: float, dy: float) -> FittedGroup:
    def moved(rect: Rect) -> Rect:
        return Rect(rect.x + dx, rect.y + dy, rect.width, rect.height)

    return replace(group, bounds=moved(group.bounds), content_bounds=moved(group.content_bounds))
