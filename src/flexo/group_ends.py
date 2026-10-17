"""Lines to groups: a line may start or end at a group, as it may at one of its parts.

    groups:
      - {id: substrates, role: layout, layout: {kind: row}, children: [acv, plus, oxygen]}
      - {id: products, role: layout, layout: {kind: row}, children: [ipn, plus2, water]}
    edges:
      - {from: substrates, to: cell}
      - {from: cell, to: products, arrive: west}

Everything that goes in, the cell, everything that comes out: an arrow from one of the
molecules would read as though it came from that one alone. A line to a group meets it
where a reader sees the group end (``reach``): the outline of a group drawn with one (a
module, a box), or, round a group that only arranges what it holds (a layout group, a
panel), the box round what it holds -- so the arrow stops as far short of those parts as it
would of one of them. It meets that at the middle of the side that faces its other end, or
of the side ``depart`` or ``arrive`` names.

As a line to a frame does (``flexo.frames``), it moves nothing: the layout never sees it
(``split``). Routing is given each group such lines end at as a part of the figure, where
the group is (``stood_in``): one every other line goes through as before, and that its own
lines keep out of, so none of them runs through the group's own parts on its way in.

A line between a group and what it holds has no way to it from outside, nor one that starts
and ends at one group: each is refused, in words (``refused``).
"""

from __future__ import annotations

from dataclasses import replace

from flexo.components import TRANSPARENT_ROLES, normalize_node
from flexo.diagnostics import Diagnostic, Severity
from flexo.frames import FRAME_KIND, around
from flexo.geometry import Point, Rect, Size
from flexo.ir.fitted import FittedFigure, FittedGroup, FittedNode, ResolvedPort
from flexo.ir.measured import MeasuredNode, TextMetrics
from flexo.ir.routed import RoutedFigure
from flexo.ir.semantic import EdgeSpec, FigureSpec, GroupSpec, NetSpec, NodeSpec
from flexo.style import LayoutStyle

PLAIN_PORTS = ("input", "output")
"""The ways a group is gone into and out of: a group has no ports of its own, so a line to
one is written with its id alone (``from: substrates``), or with these, as a file the
figure wrote itself has them (``substrates.output``)."""

DRAWN_ROUND = frozenset({"filled", "outline", "dashed"})
"""The ways a theme draws a container (``LayoutStyle.container_style``) that put a line round
it: a line to such a group meets that outline. (A rule or a band marks only its top.)"""

UNMET = frozenset({"spacer", FRAME_KIND})
"""Parts a group holds that a line to it does not stop short of: they draw nothing there."""


def _ends(line: EdgeSpec | NetSpec) -> set[str]:
    """The ids a line starts and ends at."""

    if isinstance(line, EdgeSpec):
        return {line.source.node_id, line.target.node_id}
    return {reference.node_id for reference in (*line.sources, *line.targets)}


def grouped(figure: FigureSpec) -> set[str]:
    """The ids of ``figure``'s groups that a line of it starts or ends at."""

    groups = {group.id for group in figure.groups}
    if not groups:
        return set()
    return {end for line in (*figure.edges, *figure.nets) for end in _ends(line)} & groups


def split(
    figure: FigureSpec,
) -> tuple[FigureSpec, tuple[tuple[EdgeSpec, ...], tuple[NetSpec, ...]]]:
    """``figure`` as the layout sees it -- without the lines that start or end at a group --
    and those lines: its edges, and its lines that branch."""

    ids = grouped(figure)
    if not ids:
        return figure, ((), ())
    edges = tuple(edge for edge in figure.edges if _ends(edge) & ids)
    nets = tuple(net for net in figure.nets if _ends(net) & ids)
    return (
        replace(
            figure,
            edges=tuple(edge for edge in figure.edges if not _ends(edge) & ids),
            nets=tuple(net for net in figure.nets if not _ends(net) & ids),
        ),
        (edges, nets),
    )


def drawn_round(spec: GroupSpec, style: LayoutStyle) -> bool:
    """Whether ``spec`` is drawn with a line round it (``flexo.emit``'s container): a line to
    it meets that line."""

    if spec.role in TRANSPARENT_ROLES:
        return False
    return spec.role == "plate" or spec.line != "solid" or style.container_style in DRAWN_ROUND


def reach(fitted: FittedFigure, group_id: str, style: LayoutStyle) -> Rect | None:
    """Where a line to the group ``group_id`` meets it: its outline, if it is drawn with
    one; else the box round what it holds (and its title, where it writes one) -- the parts
    a line keeps its gap from, as it does from any part. None: it holds nothing to meet."""

    groups = {group.measured.spec.id: group for group in fitted.groups}
    nodes = {node.measured.spec.id: node for node in fitted.nodes}

    def boxes(item: str) -> list[Rect]:
        group = groups.get(item)
        if group is None:
            node = nodes.get(item)
            if node is None or node.measured.spec.kind in UNMET:
                return []
            return [node.bounds]
        spec = group.measured.spec
        if drawn_round(spec, style):
            return [group.bounds]
        found = [box for child in spec.children for box in boxes(child)]
        title = _title(group, style)
        return [*found, title] if title is not None and found else found

    if group_id not in groups:
        return None
    found = [box for box in boxes(group_id) if box.width > 0.0 or box.height > 0.0]
    return Rect.union(found) if found else None


def _title(group: FittedGroup, style: LayoutStyle) -> Rect | None:
    """Where a group that draws no outline writes its title, if it writes one: a panel's,
    a container's in a theme that only marks its top."""

    if group.measured.spec.role in {"layout", "canvas"}:
        return None
    from flexo.routing.pins import title_rect

    return title_rect(group, style)


def _level(group: FittedGroup, bounds: Rect) -> tuple[float, float] | None:
    """Where a line beside a group meets it, as a named part's drawing is met
    (``MeasuredNode.drawn``, down from the top of ``bounds``, where the group stands in):
    about the line its centred parts stand on (``MeasuredGroup.middle``) -- level with a
    row of named molecules, not their names -- so a line from beside them runs straight on
    to the next part lined up there. ``None``: at the middle of its side."""

    middle = group.measured.middle
    if middle is None:
        return None
    line = group.bounds.y + middle
    reach = min(line - bounds.top, bounds.bottom - line)
    if reach <= 0.0:
        return None
    return line - reach - bounds.top, line + reach - bounds.top


def stood_in(
    fitted: FittedFigure,
    lines: tuple[tuple[EdgeSpec, ...], tuple[NetSpec, ...]],
    style: LayoutStyle,
    *,
    also: tuple[tuple[EdgeSpec, ...], tuple[NetSpec, ...]] = ((), ()),
) -> FittedFigure:
    """``fitted`` as routing sees it where ``lines`` start or end at groups: each group they
    name a part of the figure where the group is (``reach``), and those lines among the
    figure's. ``also``: other lines routed with them (those to frames, ``flexo.frames``),
    whose groups stand in too but which are not added here.

    A stand-in is the group's own id, as a frame (``flexo.frames.FRAME_KIND``): in no
    other line's way, and kept out of by its own lines, as out of a box. It is held by the
    groups that hold the group, and drawn by none: the group is drawn as it is. A line meets
    its left or right side on the line the group's centred parts stand on (``_level``).

    A line to a group that holds nothing to meet is left out (``undrawn``)."""

    edges, nets = lines
    named = {end for line in (*edges, *nets, *also[0], *also[1]) for end in _ends(line)}
    named &= {group.measured.spec.id for group in fitted.groups}
    named -= {node.measured.spec.id for node in fitted.nodes}
    if not named:
        return fitted
    from flexo.routing.aside import writing_room
    from flexo.text import TextMeasurer

    semantic = fitted.measured.semantic
    stand_ins: list[FittedNode] = []
    for group in fitted.groups:
        name = group.measured.spec.id
        if name not in named:
            continue
        bounds = reach(fitted, name, style)
        if bounds is None:
            continue
        spec = normalize_node(NodeSpec(id=name, kind=FRAME_KIND, properties=(("around", name),)))
        measured = MeasuredNode(
            spec,
            TextMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, ()),
            Size(bounds.width, bounds.height),
            Point(bounds.width / 2.0, bounds.height / 2.0),
            drawn=_level(group, bounds),
        )
        ports = tuple(
            ResolvedPort(port.name, port.side, bounds.point_on(port.side, port.offset))
            for port in spec.ports
        )
        stand_ins.append(FittedNode(measured, bounds, ports))
    there = {node.measured.spec.id for node in (*fitted.nodes, *stand_ins)}
    edges = tuple(edge for edge in edges if _ends(edge) <= there)
    nets = tuple(net for net in nets if _ends(net) <= there)
    if not stand_ins:
        return fitted
    measurer = TextMeasurer(style.typography)
    measured = replace(
        fitted.measured,
        semantic=replace(
            semantic,
            nodes=semantic.nodes + tuple(node.measured.spec for node in stand_ins),
            edges=semantic.edges + edges,
            nets=semantic.nets + nets,
        ),
        nodes=fitted.measured.nodes + tuple(node.measured for node in stand_ins),
        edge_labels=fitted.measured.edge_labels
        + tuple(
            writing_room(edge, measurer.measure(edge.label), measurer.measure, style)
            for edge in edges
        ),
        net_labels=fitted.measured.net_labels + tuple(measurer.measure(net.label) for net in nets),
    )
    return replace(fitted, measured=measured, nodes=fitted.nodes + tuple(stand_ins))


def standing(
    fitted: FittedFigure, held: tuple, style: LayoutStyle, *, among: RoutedFigure | None = None
) -> FittedFigure:
    """``fitted`` as routing sees it, ``held`` its lines kept from the layout -- its frames
    and the lines to them, and the lines to its groups (``flexo.compiler``): each group they
    end at standing in it, then each frame (``flexo.frames.stood_in``)."""

    from flexo.frames import stood_in as frames_stood_in

    frames, lines, *rest = held
    grouped_lines = rest[0] if rest else ((), ())
    base = stood_in(fitted, grouped_lines, style, also=lines)
    if not frames or not any(lines):
        return base
    return frames_stood_in(base, frames, lines, style, among=among)


def undrawn(
    lines: tuple[tuple[EdgeSpec, ...], tuple[NetSpec, ...]], routed: RoutedFigure
) -> tuple[Diagnostic, ...]:
    """What to say of each of ``lines`` (to groups) that is not drawn: its group holds
    nothing there is to meet."""

    drawn = {edge.spec.id for edge in routed.edges} | {net.spec.id for net in routed.nets}
    groups = {group.id for group in routed.fitted.measured.semantic.groups}
    return tuple(
        Diagnostic(
            "group.line.undrawn",
            f"The line to the group “{sorted(_ends(line) & groups)[0]}” is not drawn: the "
            "group holds nothing for it to meet.",
            Severity.WARNING,
            entity_id=line.id,
            hint="Put a part in the group, or join the line to a part.",
        )
        for line in (*lines[0], *lines[1])
        if line.id not in drawn and _ends(line) & groups
    )


def refused(figure: FigureSpec) -> tuple[Diagnostic, ...]:
    """What to say of a line that starts or ends at a group and cannot: one between a group
    and a part or group it holds (there is no way to it from outside), one that starts and
    ends at one group, one between a group and a frame round it or inside it -- and one
    that names a port of a group, which has none."""

    groups = {group.id: group for group in figure.groups}
    named = grouped(figure)
    if not named:
        return ()
    frames = {node.id: node for node in figure.nodes if node.kind == FRAME_KIND}
    memo: dict[str, set[str]] = {}

    def within(item: str) -> set[str]:
        """Everything ``item`` holds, however deep: its parts and groups."""

        if item not in memo:
            memo[item] = set()
            found: set[str] = set()
            for child in groups[item].children if item in groups else ():
                found |= {child, *within(child)}
            memo[item] = found
        return memo[item]

    def parts(item: str) -> set[str]:
        return {one for one in (item, *within(item)) if one not in groups}

    def round_frame(frame: str) -> set[str]:
        return {one for item in around(frames[frame]) for one in parts(item)}

    said: list[Diagnostic] = []
    for line in (*figure.edges, *figure.nets):
        ends = (
            [line.source, line.target]
            if isinstance(line, EdgeSpec)
            else [*line.sources, *line.targets]
        )
        ported = next(
            (end for end in ends if end.node_id in named and end.port_name not in PLAIN_PORTS),
            None,
        )
        if ported is not None:
            said.append(
                Diagnostic(
                    "group.line.port",
                    f"A line can\u2019t end at a port of the group “{ported.node_id}”: a group "
                    f"has none, and “{ported}” names one.",
                    entity_id=line.id,
                    hint=f"Write the group alone (“{ported.node_id}”), with depart or arrive "
                    "for the side the line meets.",
                )
            )
            continue
        names = sorted({end.node_id for end in ends})
        alone = isinstance(line, EdgeSpec) and line.source.node_id == line.target.node_id
        for group in (name for name in names if name in named):
            if group == figure.root:
                what = "holds the whole figure"
            elif alone:
                what = "starts and ends at it"
            else:
                what = _inside(group, names, within, parts, frames, round_frame)
                if what is None:
                    continue
            said.append(
                Diagnostic(
                    "group.line.inside",
                    (
                        f"A line can\u2019t end at “{group}”, the group that holds the whole "
                        "figure."
                        if group == figure.root
                        else f"A line can\u2019t end at the group “{group}” from inside it: "
                        f"this one {what}."
                    ),
                    entity_id=line.id,
                    hint="Join the group to a part it does not hold, or the line to a part "
                    "inside it.",
                )
            )
            break
    return tuple(said)


def _inside(group, names, within, parts, frames, round_frame) -> str | None:
    """How a line between ``group`` and its other ends ``names`` is one from inside it, in
    words; None, if it is not."""

    held = within(group)
    for other in names:
        if other == group:
            continue
        if other in frames:
            round_ = round_frame(other)
            mine = parts(group)
            if round_ and mine and mine <= round_:
                return f"joins it to the frame “{other}”, which goes round it"
            if round_ and round_ <= mine:
                return f"joins it to the frame “{other}”, round parts it holds"
        elif other in held:
            return f"joins it to “{other}”, which it holds"
    return None


__all__ = [
    "PLAIN_PORTS",
    "drawn_round",
    "grouped",
    "reach",
    "refused",
    "split",
    "standing",
    "stood_in",
    "undrawn",
]
