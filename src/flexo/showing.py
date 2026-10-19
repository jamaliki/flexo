"""Parts of a figure hidden, dimmed or highlighted, where they stand.

A talk shows one figure many times: all of it, then one part with the rest faint, then
that part alone. Each is the same figure laid out the same way -- nothing moves -- drawn
with some of it left out:

    figure:
      id: pipeline
      hide: [store]            # not drawn, and its place kept
      dim: [queue, worker]     # drawn faint
      highlight: [api]         # these at full strength, and the rest faint

Each names shapes, groups (all they hold), lines or frames by id. A line is shown as the
less shown of its two ends is: hidden with a hidden shape, faint with a faint one. A
group's own box and title are faint when everything in it is, and hidden when everything
in it is hidden. ``highlight`` is the other way to say ``dim``: what it does not name is
faint -- the box and title of a group too, unless the group is named or all that is shown
in it is highlighted. A name the figure has nothing of is passed over (a shape since
deleted).

The layout never sees any of it; what is hidden is drawn all the same, marked
``visibility="hidden"`` (a renderer leaves it out; an editor shows it as a ghost, to bring
it back), and what is faint is drawn in colours nearer the page's.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable

from flexo.ir.semantic import FigureSpec, NodeSpec

HIDDEN, DIMMED = "hidden", "dimmed"
DIM = 0.28
"""How much of its strength a dimmed part is drawn at."""
MARK = "data-flexo-show"
"""On each element drawn hidden or dimmed: which."""


def states(figure: FigureSpec, frames: Iterable[NodeSpec] = ()) -> dict[str, str]:
    """How each shape, group, line and frame of ``figure`` is shown, where not plainly:
    ``"hidden"`` or ``"dimmed"``, by id. ``frames``: its frames, where the figure is the
    one the layout sees (which has none: ``flexo.frames.split``)."""

    if not (figure.hidden or figure.dimmed or figure.highlighted):
        return {}
    from flexo.frames import FRAME_KIND, around

    groups = {group.id: group for group in figure.groups}
    frames = [*frames, *(node for node in figure.nodes if node.kind == FRAME_KIND)]
    held = {frame.id: around(frame) for frame in frames}
    shapes = [node.id for node in figure.nodes if node.kind != FRAME_KIND]

    def within(ids: Iterable[str]) -> set[str]:
        """Each of ``ids``, and all that a group among them holds."""

        found: set[str] = set()
        left = list(ids)
        while left:
            one = left.pop()
            if one not in found:
                found.add(one)
                left += groups[one].children if one in groups else ()
        return found

    hidden = within(figure.hidden)
    lit = within(figure.highlighted) - hidden
    dimmed = within(figure.dimmed) - hidden
    shown: dict[str, str] = {}

    def of(entity: str, ends: Iterable[str], *, every: bool = False) -> None:
        """A line (``ends``, its shapes) or a box (``every``: all it holds) shown as they
        are: hidden with one of them hidden (a box: with all), else faint with one faint
        (a box: with all) -- unless highlighted itself."""

        ends = list(ends)
        how = [shown.get(end) for end in ends]
        some = all if every else any
        if entity in hidden or (ends and some(one == HIDDEN for one in how)):
            shown[entity] = HIDDEN
        elif entity not in lit:
            if every and lit:
                # Among highlights a box is faint with anything faint in it: only what is
                # highlighted stands out, not the box and the title it happens to be in.
                lesser = any(one == DIMMED for one in how)
            else:
                lesser = bool(ends) and some(one is not None for one in how)
            if entity in dimmed or (lit and not ends) or lesser:
                shown[entity] = DIMMED

    for shape in shapes:
        if shape in hidden:
            shown[shape] = HIDDEN
        elif shape in dimmed or (lit and shape not in lit):
            shown[shape] = DIMMED
    # A line that ends at a frame is shown as its frame is, as one to a shape is: those
    # frames first.
    joined = {end for edge in figure.edges for end in (edge.source.node_id, edge.target.node_id)}
    joined |= {port.node_id for net in figure.nets for port in (*net.sources, *net.targets)}
    for frame, round_ in held.items():
        if frame in joined:
            of(frame, [one for one in within(round_) if one in set(shapes)], every=True)
    for edge in figure.edges:
        of(edge.id, (edge.source.node_id, edge.target.node_id))
    for net in figure.nets:
        # A line that branches is gone with what it comes from, or with all it goes to, and
        # faint likewise; a branch of it to one shape is that shape's (``branches``).
        sources = [shown.get(port.node_id) for port in net.sources]
        targets = [shown.get(port.node_id) for port in net.targets]
        if net.id in hidden or HIDDEN in sources or all(how == HIDDEN for how in targets):
            shown[net.id] = HIDDEN
        elif net.id in lit:
            continue
        elif net.id in dimmed or DIMMED in sources or all(how is not None for how in targets):
            shown[net.id] = DIMMED
    for group in figure.groups:
        if group.id != figure.root:
            of(group.id, [one for one in within([group.id]) if one in set(shapes)], every=True)
    for frame, round_ in held.items():
        of(frame, [one for one in within(round_) if one in set(shapes)], every=True)
    return shown


def branches(shown: dict[str, str], nets: Iterable[object]) -> dict[str, str]:
    """``shown`` with the branches of each line that branches (``nets``, as routed) shown as
    the shape each goes to or comes from is: a branch to a hidden shape is hidden, and to a
    faint one faint, where the line as a whole is not. (Its trunk stays, for the others.)"""

    if not shown:
        return shown
    found = dict(shown)
    for net in nets:
        whole = shown.get(net.spec.id)  # type: ignore[attr-defined]
        if whole == HIDDEN:
            continue
        ends = (("source", net.source_stems), ("target", net.target_stems))  # type: ignore[attr-defined]
        for side, stems in ends:
            for index, stem in enumerate(stems, 1):
                how = shown.get(stem.port.node_id)
                if how == HIDDEN or (how == DIMMED and whole is None):
                    found[f"{net.spec.id}.{side}.{index}"] = how  # type: ignore[attr-defined]
    return found


def mark(
    root: ET.Element, shown: dict[str, str], groups: Iterable[str] = (), canvas: str = "#ffffff"
) -> None:
    """Draw ``root`` (a figure's SVG) as ``shown`` says: each part named there hidden or
    faint. A shape, a line and a frame are one element each (and a frame's pieces inside
    other boxes); a group (``groups``, their ids) is its box and its title, not what it
    holds. ``canvas``: the page's colour, which what is faint is drawn nearer to."""

    if not shown:
        return
    boxes = set(groups)
    markers = {
        element.get("id"): (parent, element)
        for parent in root.iter()
        for element in parent
        if _local(element.tag) == "marker" and element.get("id")
    }

    def how_of(element: ET.Element) -> str | None:
        name = element.get("id") or ""
        owner = element.get("data-hit-for") or ""
        how = shown.get(owner) if owner else None
        if how is None and name in shown and name not in boxes:
            how = shown[name]
        if how is None and "." in name:
            # A group's own pieces: its box, its title, its shadow.
            stem, piece = name.rsplit(".", 1)
            if stem in boxes and piece in {"container", "label", "shadow"}:
                how = shown.get(stem)
        return how

    # What is in something faint already -- faint here, or drawn so before (a figure's part,
    # its figure then dimmed on a slide) -- is faint once: never twice as faint.
    stack = [(root, False)]
    while stack:
        element, faint = stack.pop()
        how = how_of(element)
        if how == HIDDEN:
            element.set("visibility", "hidden")
            element.set(MARK, HIDDEN)
        elif element.get(MARK) == DIMMED:
            faint = True
        elif how == DIMMED and not faint:
            element.set(MARK, DIMMED)
            _faded(element, canvas, markers)
            faint = True
        stack.extend((child, faint) for child in reversed(list(element)))


_PAINTS = ("fill", "stroke", "stop-color", "flood-color")
_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_ENDS = ("marker-start", "marker-mid", "marker-end")


def _faded(element: ET.Element, canvas: str, markers: dict) -> None:
    """``element`` and all in it drawn faint: every colour brought most of the way to the
    page's, rather than made see-through -- a faint shape hides the line behind it as it
    did, and is the same in a PDF and a PowerPoint as on the page. A colour so changed is
    the figure's own no longer (it carries no paint role). An arrowhead is a marker shared
    with other lines: a faint line ends in a faint copy of it. A picture's pixels are
    made see-through, there being no other way."""

    for one in _unfaded(element):
        for key in _PAINTS:
            value = one.get(key)
            if value and _HEX.fullmatch(value.strip()):
                one.set(key, faint(value.strip(), canvas))
                one.attrib.pop(f"data-flexo-{key}", None)
        if one.get("style"):
            styled = _HEX.sub(lambda found: faint(found.group(0), canvas), one.get("style"))
            one.set("style", styled)
        if _local(one.tag) == "image":
            one.set("opacity", f"{DIM * _opacity(one.get('opacity')):.4g}")
        for key in _ENDS:
            found = re.fullmatch(r"url\(#(.+)\)", one.get(key) or "")
            if found is None or found.group(1) not in markers:
                continue
            name = f"{found.group(1)}.dimmed"
            if name not in markers:
                parent, marker = markers[found.group(1)]
                copy = _copied(marker)
                copy.set("id", name)
                parent.insert(list(parent).index(marker) + 1, copy)
                markers[name] = (parent, copy)
                _faded(copy, canvas, {})
            one.set(key, f"url(#{name})")


def _unfaded(element: ET.Element):
    """``element`` and all in it but what is drawn faint already (marked so)."""

    yield element
    for child in element:
        if child.get(MARK) != DIMMED:
            yield from _unfaded(child)


def _opacity(value: str | None) -> float:
    try:
        return min(1.0, max(0.0, float(value))) if value else 1.0
    except ValueError:
        return 1.0


def faint(colour: str, canvas: str) -> str:
    """``colour`` (``#rgb`` or ``#rrggbb``) as it is drawn dimmed on a page of ``canvas``:
    ``DIM`` of it, the rest the page's."""

    def parts(value: str) -> tuple[int, int, int]:
        value = value.lstrip("#")
        if len(value) == 3:
            value = "".join(letter * 2 for letter in value)
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)

    try:
        page = parts(canvas)
    except ValueError:
        page = (255, 255, 255)
    mixed = (
        round(DIM * own + (1.0 - DIM) * of_page)
        for own, of_page in zip(parts(colour), page, strict=True)
    )
    return "#" + "".join(f"{value:02x}" for value in mixed)


def _copied(element: ET.Element) -> ET.Element:
    import copy

    return copy.deepcopy(element)


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""
