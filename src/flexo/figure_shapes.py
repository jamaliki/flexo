"""Shapes drawn over a figure where they are put: what Inkscape was opened for.

A figure is laid out by flexo; a ring round part of it, an arrow pointing at a residue, a
brace and its words beside a stack, a highlight behind a word, "3.1 Å" between two atoms
were drawn afterwards, by hand, and drawn again each time the figure changed. A figure
file's ``shapes`` are those, written as a slide's are (``flexo.freeform``, the same words:
a shape copied from a slide pastes onto a figure, and back)::

    shapes:
    - kind: arrow
      from: [40, 12]
      to: {part: encoder, side: top}
    - kind: ring
      around: [encoder, decoder]
    - kind: text
      on: decoder
      at: [0, -18]
      text: "**the bottleneck**"

Places are the figure's own units (points), y down, from the top left of the figure as it
is laid out. The layout moves parts as the figure is edited, so a shape may be attached to
them by id -- a shape, a group, a frame, or any piece of one its drawing names (a protein's
feature ``spike.feature2``, a tree's tip ``tree.tip3``):

- a line's end glued to a part, ``{part: encoder, side: right}`` -- at a side's middle, its
  ``centre`` (stopping at its box), or, left out, the side facing the other end -- keeping
  ``at``, where it was, should the part go;
- a whole shape ``on`` a part: its places measured from the part's top left, so it moves
  with it;
- a shape ``around`` parts: drawn round them where they are, ``margin`` points out
  (``margin_of``: a highlight 2 unless said, a ring 3 -- through their box's corners -- a
  brace 4, the rest 6) -- a box's ``at`` and ``size``, a box of words' ``at`` and ``width``,
  a line's ``from`` and ``to`` along their ``side`` (a brace or a bracket on their
  ``right``, pointing away, unless said; any other line at their ``bottom``), lines through
  points stretched over them.

A part a shape names that the figure does not have is said, as a warning: an end glued to it
stays where it was, a shape on it is drawn from the figure's top left, and one round only
such parts is not drawn.

Shapes are drawn over everything (``behind``: under the figure's parts, over the box of the
innermost group that holds them -- a backdrop a part sits on), in the order listed, painted
by the figure's palette (``accent`` its first tone's colour, ``muted`` its muted ink, ...)
and their words set in its font, at its size unless they say.
None takes room: the layout never sees them (``flexo.compiler``), and the page grows to hold
one that reaches past it, on any side, moving nothing. Each is drawn as ``shapes.2`` (its
place in the list), or as its own ``id``, which the figure's ``hide``, ``dim`` and
``highlight`` may name as they name parts; a shape attached to parts is shown as they are,
unless it is named itself. ``locked`` keeps one where it is while the figure is edited.
"""

from __future__ import annotations

import copy
import math
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from flexo import freeform
from flexo.diagnostics import Diagnostic, Severity
from flexo.svg import element, layer, number

SHAPE_KEYS = ("on", "around", "margin", "side", "behind", "locked")
"""What a shape over a figure says besides how it is drawn (``flexo.freeform``): the part it
is ``on``; the parts it is drawn ``around``, ``margin`` points out, a line along their
``side``; whether it is ``behind`` the figure's parts; whether it is ``locked``."""

MARGIN = 6.0
"""How far, in points, a shape drawn round parts stands out from them when it says not."""
MARGINS = {"highlight": 2.0, "ring": 3.0, "ellipse": 3.0, "brace": 4.0, "bracket": 4.0}
"""The kinds that stand nearer what they go round: a highlight just past a word, a ring
just past the corners of what it rings, a brace beside what it gathers."""


def margin_of(spec: Mapping[str, Any]) -> float:
    """How far a shape drawn round parts stands out from them."""

    if spec.get("margin") is not None:
        return float(spec["margin"])
    return MARGINS.get(str(spec.get("kind")), MARGIN)


AROUND_SIDES = ("top", "right", "bottom", "left")

PIECE_ENDS = (".label", ".body", ".outline", ".shadow", ".hit")
"""Pieces of a drawing that are no part to point at of their own: a part's words, its box."""


# -- reading -------------------------------------------------------------------------------


def _ids(value: object, key: str) -> list[str]:
    if isinstance(value, str):
        value = [item.strip() for item in value.split(",")]
    if (
        isinstance(value, str | bytes)
        or not isinstance(value, Sequence)
        or not value
        or any(
            isinstance(item, bool) or not isinstance(item, str | int) or not str(item).strip()
            for item in value
        )
    ):
        raise freeform.ShapeError(
            key,
            f"{key} must be the parts it goes round, by id, such as [encoder, decoder], "
            f"not {value!r}.",
        )
    return [str(item).strip() for item in value]


_STAND_INS: dict[str, dict[str, object]] = {
    "line": {"from": [0.0, 0.0], "to": [1.0, 0.0]},
    "points": {"points": [[0.0, 0.0], [1.0, 1.0]]},
    "box": {"at": [0.0, 0.0], "size": [1.0, 1.0]},
    "text": {"at": [0.0, 0.0]},
}


def checked(data: object) -> dict[str, Any]:
    """A shape over a figure as written, checked (``flexo.freeform.checked``, with what a
    figure says of one besides: ``SHAPE_KEYS``): what is wrong said under its key
    (``freeform.ShapeError``). A shape ``around`` parts needs no places of its own."""

    if not isinstance(data, Mapping):
        return freeform.checked(data)
    if any(key is True for key in data):
        # (``on:`` read by a YAML 1.1 reader -- PyYAML's -- is the key ``true``: it is ``on``.)
        data = {("on" if key is True else key): value for key, value in data.items()}
    kind = data.get("kind")
    stand_in: dict[str, object] = {}
    if data.get("around") is not None:
        form = freeform.family(str(kind)) if kind in (*freeform.KINDS, "group") else None
        if form == "group":
            raise freeform.ShapeError(
                "around", "A group is not drawn round parts: its shapes are, each of its own."
            )
        stand_in = {
            key: value for key, value in _STAND_INS.get(form or "", {}).items() if key not in data
        }
    made = freeform.checked({**data, **stand_in}, extra=SHAPE_KEYS)
    for key in stand_in:
        made.pop(key, None)
    if made.get("on") is not None:
        on = made["on"]
        if isinstance(on, bool) or not isinstance(on, str | int) or not str(on).strip():
            raise freeform.ShapeError(
                "on", f"on must be the part it is on, by id, such as encoder, not {on!r}."
            )
        made["on"] = str(on).strip()
    if made.get("around") is not None:
        made["around"] = _ids(made["around"], "around")
        if made.get("on") is not None:
            raise freeform.ShapeError(
                "on", "A shape is on a part or drawn round parts, not both: say on or around."
            )
    for key in ("margin", "side"):
        if made.get(key) is not None and made.get("around") is None:
            raise freeform.ShapeError(
                key, f"{key} is for a shape drawn round parts: it needs around."
            )
    if made.get("margin") is not None:
        value = made["margin"]
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or not -500.0 <= value <= 500.0
        ):
            raise freeform.ShapeError(
                "margin",
                f"margin must be a number of points from -500 to 500, such as 6, not {value!r}.",
            )
        made["margin"] = float(value)
    if made.get("side") is not None and made["side"] not in AROUND_SIDES:
        raise freeform.ShapeError(
            "side", f"side must be one of {', '.join(AROUND_SIDES)}, not {made['side']!r}."
        )
    for key in ("behind", "locked"):
        if key in made and not isinstance(made[key], bool):
            raise freeform.ShapeError(key, f"{key} must be true or false, not {made[key]!r}.")
    return made


def read(written: object) -> tuple[list[dict[str, Any] | None], list[Diagnostic]]:
    """A figure's ``shapes`` as written: each checked, or ``None`` where it is wrong, said
    under its place (``shapes[2].fill``) -- and two shapes of one id said too."""

    if written is None:
        return [], []
    if isinstance(written, str | bytes | Mapping) or not isinstance(written, Sequence):
        return [], [
            Diagnostic(
                "shape.invalid",
                "shapes must be a list of shapes, each such as {kind: arrow, from: [10, 10], "
                "to: {part: encoder}}.",
                entity_id="shapes",
            )
        ]
    found: list[dict[str, Any] | None] = []
    said: list[Diagnostic] = []
    seen: set[str] = set()
    for index, item in enumerate(written):
        try:
            made = checked(item)
        except freeform.ShapeError as error:
            where = f"shapes[{index}]" + (f".{error.key}" if error.key else "")
            name = item.get("id") if isinstance(item, Mapping) else None
            said.append(
                Diagnostic(
                    "shape.invalid",
                    f"{where}: {error.message}",
                    entity_id=str(name) if name is not None else f"shapes.{index}",
                )
            )
            found.append(None)
            continue
        for named in shape_names(made):
            if named in seen:
                said.append(
                    Diagnostic(
                        "shape.id.duplicate",
                        f"shapes[{index}].id: two shapes are called {named}: each needs a name "
                        "of its own.",
                        entity_id=named,
                    )
                )
            seen.add(named)
        found.append(made)
    return found, said


def shape_names(spec: Mapping[str, Any]) -> list[str]:
    """The ids a shape is written with: its own, and its group's shapes'."""

    own = [str(spec["id"])] if spec.get("id") is not None else []
    if spec.get("kind") == "group":
        own += [name for child in spec.get("shapes") or [] for name in shape_names(child)]
    return own


def name_of(spec: Mapping[str, Any], index: int) -> str:
    """What a shape is drawn as, and named by in ``hide``: its own id, else ``shapes.2``."""

    return str(spec["id"]) if spec.get("id") is not None else f"shapes.{index}"


def attached(spec: Mapping[str, Any]) -> list[str]:
    """The parts a shape is attached to: the one it is on, those it is round, those its
    ends are glued to (its group's shapes' too)."""

    found: list[str] = []
    if spec.get("on") is not None:
        found.append(str(spec["on"]))
    found += [str(item) for item in spec.get("around") or []]
    for key in ("from", "to"):
        end = spec.get(key)
        if isinstance(end, Mapping) and end.get("part") is not None:
            found.append(str(end["part"]))
    for child in spec.get("shapes") or [] if spec.get("kind") == "group" else []:
        found += attached(child)
    return list(dict.fromkeys(found))


def free(spec: Mapping[str, Any]) -> bool:
    """Whether a shape is where it is written, attached to no part: it stays put however the
    figure is laid out."""

    return not attached(spec)


# -- placing -------------------------------------------------------------------------------

type Box = tuple[float, float, float, float]
"""x, y, width, height."""


ROUND = ("ellipse", "ring")
"""The shapes drawn round parts through their box's corners, not inside it: an oval round a
box that fits in the box would cut its corners off."""


def around_box(boxes: Sequence[Box], margin: float, kind: str = "rectangle") -> Box:
    """The box a shape of ``kind`` is drawn in round ``boxes``: theirs, ``margin`` out each
    way -- an oval's the box its outline passes through their box's corners in."""

    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    if kind in ROUND:
        grow = (math.sqrt(2.0) - 1.0) / 2.0
        across, down = (right - left) * grow, (bottom - top) * grow
        left, right, top, bottom = left - across, right + across, top - down, bottom + down
    left, top, right, bottom = left - margin, top - margin, right + margin, bottom + margin
    return (left, top, max(right - left, 0.0), max(bottom - top, 0.0))


def side_of(spec: Mapping[str, Any]) -> str:
    """The side of what it goes round a line drawn round parts runs along."""

    if spec.get("side"):
        return str(spec["side"])
    return "right" if spec.get("kind") in ("brace", "bracket") else "bottom"


def placed_round(spec: Mapping[str, Any], box: Box) -> dict[str, Any]:
    """``spec`` given the places that draw it round ``box``. A line runs along its side so
    that a brace or a bracket points away from what it goes round (it points to the left
    of the way it runs)."""

    made = dict(spec)
    x, y, w, h = box
    form = freeform.family(str(spec.get("kind")))
    if form == "box":
        made["at"], made["size"] = [x, y], [w, h]
    elif form == "text":
        made["at"], made["width"] = [x, y], max(w, 1.0)
    elif form == "line":
        side = side_of(spec)
        corners = {"tl": [x, y], "tr": [x + w, y], "br": [x + w, y + h], "bl": [x, y + h]}
        # A brace, a bracket and a dimension's words point away from what they go round (to
        # the left of the way they run); any other line runs as it is read, left to right,
        # down.
        away = spec.get("kind") in ("brace", "bracket", "dimension")
        ends = {
            "right": ("tr", "br"),
            "left": ("bl", "tl") if away else ("tl", "bl"),
            "top": ("tl", "tr"),
            "bottom": ("br", "bl") if away else ("bl", "br"),
        }[side]
        made["from"], made["to"] = corners[ends[0]], corners[ends[1]]
    elif form == "points":
        points = [list(map(float, point)) for point in spec.get("points") or []]
        if points:
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            left, top = min(xs), min(ys)
            across, down = (max(xs) - left) or 1.0, (max(ys) - top) or 1.0
            made["points"] = [
                [x + (px - left) / across * w, y + (py - top) / down * h] for px, py in points
            ]
    return made


@dataclass(slots=True)
class Placed:
    """A shape as it is drawn over the figure: where it is, absolutely."""

    index: int
    name: str
    spec: dict[str, Any]
    """As written, its places made the figure's: on a part, moved with it; round parts,
    their box."""
    behind: bool = False


@dataclass(slots=True)
class Overlay:
    """A figure's shapes, placed on it as it is laid out and drawn over it (``draw``).

    ``boxes``: each part's box by id (its shapes, groups and frames); ``piece`` finds one
    its drawing names besides, once it is drawn. What is placed and drawn is kept, for an
    editor: ``placed`` by the place each has in the list (``None`` where none is drawn),
    the boxes of the parts the shapes name, what was said of them, and how far they reach."""

    shapes: tuple[dict[str, Any] | None, ...]
    style: Any
    palette: Any
    boxes: dict[str, Box] = field(default_factory=dict)
    placed: list[Placed | None] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    reach: Box | None = None
    """``left, top, right, bottom`` of all the shapes draw, words and all."""
    named: dict[str, Box] = field(default_factory=dict)
    """The pieces of parts the shapes name, found in the drawing, by id."""
    groups: tuple[Any, ...] = ()
    """The figure's groups as laid out (``GroupSpec``): where a shape behind its parts is
    drawn among them."""
    root: str = "root"

    def box_of(self, name: str, piece: Callable[[str], Box | None] | None = None) -> Box | None:
        if name in self.boxes:
            return self.boxes[name]
        if name in self.named:
            return self.named[name]
        found = piece(name) if piece is not None else None
        if found is not None:
            self.named[name] = found
        return found

    # -- where each is --

    def place(self, piece: Callable[[str], Box | None] | None = None) -> None:
        """Each shape where it is drawn: on its part, round its parts, its ends glued."""

        self.placed = []
        for index, spec in enumerate(self.shapes):
            if spec is None:
                self.placed.append(None)
                continue
            name = name_of(spec, index)
            made = dict(spec)
            if spec.get("around"):
                found = [(part, self.box_of(part, piece)) for part in spec["around"]]
                missing = [part for part, box in found if box is None]
                there = [box for _, box in found if box is not None]
                if missing:
                    self._said(
                        name,
                        f"The {_called(spec)} goes round {_listed(missing)}, which "
                        f"{'is' if len(missing) == 1 else 'are'} not in the figure"
                        + ("." if there else ": it is not drawn."),
                    )
                if not there:
                    self.placed.append(None)
                    continue
                made = placed_round(made, around_box(there, margin_of(spec), str(spec["kind"])))
            elif spec.get("on") is not None:
                box = self.box_of(str(spec["on"]), piece)
                if box is None:
                    self._said(
                        name,
                        f"The {_called(spec)} is on “{spec['on']}”, which is not in the figure: "
                        "it is drawn from the figure's top left.",
                    )
                else:
                    made = freeform.moved(made, box[0], box[1])
            gone = self._unglued(made, name, piece)
            if gone:
                self.placed.append(None)
                continue
            self.placed.append(Placed(index, name, made, bool(spec.get("behind"))))

    def _unglued(
        self,
        spec: Mapping[str, Any],
        name: str,
        piece: Callable[[str], Box | None] | None,
    ) -> bool:
        """What is said of ends glued to parts the figure has none of; whether the shape
        is not drawn for it (such an end has no place of its own to stay at)."""

        lost = False
        for key in ("from", "to"):
            end = spec.get(key)
            if not isinstance(end, Mapping) or end.get("part") is None:
                continue
            if self.box_of(str(end["part"]), piece) is not None:
                continue
            stays = end.get("at") is not None
            lost |= not stays
            self._said(
                name,
                f"The {_called(spec)}'s {key} is glued to “{end['part']}”, which is not in the "
                "figure: " + ("it stays where it was." if stays else "it is not drawn."),
            )
        for child in spec.get("shapes") or [] if spec.get("kind") == "group" else []:
            lost |= self._unglued(child, name, piece)
        return lost

    def _said(self, name: str, message: str) -> None:
        self.diagnostics.append(
            Diagnostic(
                "shape.part.unknown",
                message,
                Severity.WARNING,
                entity_id=name,
                hint="Name a shape, group or frame the figure has (or a piece of one), or "
                "draw it where it is.",
            )
        )

    # -- drawing --

    def draw(self, root: ET.Element, under: ET.Element | None = None) -> None:
        """The shapes drawn into ``root`` (a figure's SVG, its parts drawn): those behind
        them in a layer of their own after ``under`` (its page), the rest over everything.
        Pieces of parts the shapes name are found in the drawing as it is."""

        named = self._wanted()
        piece = _pieces(root, named) if named else None
        self.place(piece)
        drawn = [one for one in self.placed if one is not None]
        if not drawn:
            return
        painter = _Painter(self)
        over: ET.Element | None = None
        backdrops: dict[str, ET.Element] = {}
        for one in drawn:
            if not one.behind:
                if over is None:
                    over = layer(root, "layer.shapes", "Shapes")
                painter.draw(over, one)
                continue
            home = self.home_of(one.spec)
            if home not in backdrops:
                backdrops[home] = self._backdrop(root, home, under)
            painter.draw(backdrops[home], one)
        self.reach = painter.reach

    def home_of(self, spec: Mapping[str, Any]) -> str:
        """The group a shape behind the figure's parts is drawn in: the innermost that holds
        all it is attached to (round a group, the one that holds that group); the figure's
        own, attached to nothing. It is drawn over that group's fill, under what it holds --
        a backdrop a part sits on, never one a group's box hides."""

        from flexo.hierarchy import ancestors

        parents = {child: group.id for group in self.groups for child in group.children}
        parts = []
        for part in attached(spec):
            if part not in parents:
                # (A piece of a part is its part's.)
                part = next((node for node in parents if part.startswith(f"{node}.")), part)
            if part in parents:
                parts.append(part)
        if not parts:
            return self.root
        chains = [ancestors(parents, part) for part in parts]
        common = next(group for group in chains[0] if all(group in chain for chain in chains))
        roles = {group.id: group.role for group in self.groups}
        # (A group that only arranges what it holds is drawn as nothing: the one round it.)
        while roles.get(common) == "layout" and common in parents:
            common = parents[common]
        return common

    def _backdrop(self, root: ET.Element, home: str, under: ET.Element | None) -> ET.Element:
        """Where the shapes behind the parts of the group ``home`` are drawn: in its layer,
        after its own box (and the frames behind its shapes), before what it holds -- else,
        should it draw no layer of its own, just over the figure's page."""

        from flexo.svg import inkscape_attr

        group = next(
            (
                item
                for item in root.iter()
                if item.get("id") == home and item.get(inkscape_attr("groupmode")) == "layer"
            ),
            None,
        )
        components = (
            next((item for item in group if item.get("id") == f"{home}.components"), None)
            if group is not None
            else None
        )
        if group is not None and components is not None:
            holder = ET.Element(
                components.tag,
                {"id": f"{home}.shapes-behind", inkscape_attr("label"): "Shapes Behind"},
            )
            group.insert(list(group).index(components), holder)
            return holder
        holder = layer(root, "layer.shapes-behind", "Shapes Behind")
        if under is not None:
            root.remove(holder)
            root.insert(list(root).index(under) + 1, holder)
        return holder

    def _wanted(self) -> set[str]:
        """The parts the shapes name that are not shapes, groups or frames: pieces of their
        drawing."""

        names = {part for spec in self.shapes if spec is not None for part in attached(spec)}
        return {name for name in names if name not in self.boxes}

    # -- how each is shown --

    def shown(self, states: Mapping[str, str], figure: Any) -> dict[str, str]:
        """How each shape is shown where not plainly (``flexo.showing``): as the figure's
        ``hide``, ``dim`` and ``highlight`` name it, else as the parts it is attached to
        are -- hidden with one hidden (one it goes round, with all of them), faint with
        one faint -- and, with parts highlighted, faint unless they are among them."""

        from flexo.showing import DIMMED, HIDDEN

        hidden, dimmed = set(figure.hidden), set(figure.dimmed)
        lit = set(figure.highlighted)
        found: dict[str, str] = {}
        for one in self.placed:
            if one is None:
                continue
            name = one.name
            if name in hidden:
                found[name] = HIDDEN
                continue
            if name in lit:
                continue
            if name in dimmed:
                found[name] = DIMMED
                continue
            spec = one.spec
            round_ = [str(part) for part in spec.get("around") or []]
            ends = [part for part in attached(spec) if part not in round_]
            how = [states.get(part) for part in ends]
            boxed = [states.get(part) for part in round_]
            if HIDDEN in how or (boxed and all(item == HIDDEN for item in boxed)):
                found[name] = HIDDEN
            elif any(item is not None for item in (*how, *boxed)) or (
                lit and not any(part in lit for part in (*ends, *round_))
            ):
                found[name] = DIMMED
        return found


def _called(spec: Mapping[str, Any]) -> str:
    return freeform.LABELS.get(str(spec.get("kind")), "shape").lower()


def _listed(names: Sequence[str]) -> str:
    quoted = [f"“{name}”" for name in names]
    return quoted[0] if len(quoted) == 1 else f"{', '.join(quoted[:-1])} and {quoted[-1]}"


def part_boxes(fitted: Any, frames: Sequence[Any] = ()) -> dict[str, Box]:
    """Each part of a laid-out figure a shape may name, by id: its shapes, its groups (the
    figure's own among them) and its frames, each its box."""

    boxes: dict[str, Box] = {}
    for group in fitted.groups:
        bounds = group.bounds
        boxes[group.measured.spec.id] = (bounds.x, bounds.y, bounds.width, bounds.height)
    for node in fitted.nodes:
        bounds = node.bounds
        boxes[node.measured.spec.id] = (bounds.x, bounds.y, bounds.width, bounds.height)
    for frame in frames:
        bounds = frame.bounds
        boxes[frame.spec.id] = (bounds.x, bounds.y, bounds.width, bounds.height)
    return boxes


def _pieces(root: ET.Element, wanted: set[str]) -> Callable[[str], Box | None]:
    """Where each piece of the drawing named in ``wanted`` is drawn (its ink), found once."""

    found: dict[str, Box] = {}
    present = {item.get("id") for item in root.iter() if item.get("id") in wanted}
    if present:
        from flexo.drawing import Drawing, Group, ink_bounds, read_drawing
        from flexo.svg import xml_document

        drawing = read_drawing(xml_document(copy.deepcopy(root)))

        def walk(group: Group) -> None:
            for item in group.items:
                ident = getattr(item, "id", None)
                if ident in present and ident not in found:
                    left, top, right, bottom = ink_bounds(Drawing(0.0, 0.0, Group(None, [item])))
                    if right >= left and bottom >= top and math.isfinite(left):
                        found[ident] = (left, top, right - left, bottom - top)
                if isinstance(item, Group):
                    walk(item)

        walk(drawing.root)
    return found.get


# -- painting ------------------------------------------------------------------------------


class _Painter:
    """Draws placed shapes and their words, and keeps how far they reach."""

    def __init__(self, overlay: Overlay) -> None:
        from flexo.text import TextMeasurer

        self.overlay = overlay
        self.style = overlay.style
        self.palette = overlay.palette
        self.typography = overlay.style.typography
        self.measurers: dict[tuple, Any] = {}
        self._measurer = TextMeasurer
        style = overlay.style
        self.shadow = freeform.Shadow(
            style.shadow_offset.points,
            style.shadow_spread.points,
            style.shadow_opacity,
            style.shadow_style,
        )
        self.sized: dict[str, tuple[float, float]] = {}
        self.targets: dict[str, freeform.Target] = {}
        self.ids: dict[str, str] = {}
        self.reach: Box | None = None
        self._prepare()

    # (Boxes of words are as large as their words: measured before anything is glued.)
    def _prepare(self) -> None:
        for one in self.overlay.placed:
            if one is None:
                continue
            for ident, spec in _every(one.name, one.spec):
                if spec.get("id") is not None:
                    self.ids.setdefault(str(spec["id"]), ident)
                form = freeform.family(str(spec["kind"]))
                if form in ("box", "text"):
                    if spec["kind"] == "text":
                        self.sized[ident] = self._text_size(freeform.normalised(spec))
                    made = freeform.geometry(spec, size=self.sized.get(ident))
                    self.targets[ident] = freeform.target_of(spec, made)

    def find(self, end: Mapping[str, Any]) -> freeform.Target | None:
        if end.get("shape") is not None:
            ident = self.ids.get(str(end["shape"]))
            return self.targets.get(ident) if ident else None
        if end.get("part") is not None:
            box = self.overlay.box_of(str(end["part"]))
            return freeform.Target(box) if box is not None else None
        return None

    def typography_of(self, spec: Mapping[str, Any]) -> Any:
        from flexo.units import Length

        typography = self.typography
        if spec.get("font"):
            typography = typography.with_family(str(spec["font"]))
        if spec.get("font_size"):
            typography = replace(typography, size=Length(float(spec["font_size"])))
        return typography

    def measurer(self, typography: Any) -> Any:
        key = (typography.family, typography.size.points)
        if key not in self.measurers:
            self.measurers[key] = self._measurer(typography)
        return self.measurers[key]

    def runs(self, spec: Mapping[str, Any]) -> tuple:
        from flexo.markup import parse_label

        text = str(spec.get("text") or "")
        if not text.strip():
            return ()
        runs = parse_label(text)
        if spec.get("bold") or spec.get("italic"):
            runs = tuple(
                replace(
                    run,
                    weight=700 if spec.get("bold") and not run.math else run.weight,
                    italic=run.italic or bool(spec.get("italic")),
                )
                for run in runs
            )
        return runs

    def _text_size(self, spec: Mapping[str, Any]) -> tuple[float, float]:
        from flexo.ir.semantic import TextRun

        runs = self.runs(spec) or (TextRun("Text"),)
        pad = float(spec.get("padding") or 0.0)
        width = spec.get("width")
        typography = self.typography_of(spec)
        metrics = self.measurer(typography).measure(
            runs, max_width=float(width) - 2 * pad if width else None, balance=False
        )
        return (float(width) if width else metrics.width + 2 * pad, metrics.height + 2 * pad)

    # -- one shape --

    def draw(self, parent: ET.Element, one: Placed) -> None:
        drawn = self._shape(parent, one.name, one.spec)
        drawn.set("data-flexo-index", str(one.index))
        if one.spec.get("locked"):
            drawn.set("data-flexo-locked", "")
        if one.spec.get("behind"):
            drawn.set("data-flexo-behind", "")

    def _shape(self, parent: ET.Element, ident: str, shape: Mapping[str, Any]) -> ET.Element:
        from flexo.svg import inkscape_attr

        spec = freeform.normalised(shape)
        kind = str(spec["kind"])
        if kind == "group":
            group = element(parent, "g", id=ident, data__flexo__shape="group")
            group.set(inkscape_attr("label"), "Group")
            if float(spec.get("opacity", 1.0)) < 1.0:
                group.set("opacity", number(float(spec["opacity"])))
            for n, child in enumerate(shape.get("shapes") or []):
                self._shape(group, f"{ident}.{n}", child)
            made = freeform.geometry(shape)
            group.set("data-flexo-box", " ".join(number(value) for value in made.box))
            return group
        form = freeform.family(kind)
        ends = freeform.glued(shape, self.find) if form == "line" else None
        made = freeform.geometry(shape, ends, self.sized.get(ident))
        drawn = freeform.draw(
            parent,
            spec,
            made,
            ident,
            self.palette,
            self.shadow if spec.get("shadow") else None,
        )
        drawn.set("data-flexo-shape", kind)
        drawn.set(inkscape_attr("label"), freeform.LABELS.get(kind, "Shape"))
        drawn.set("data-flexo-box", " ".join(number(value) for value in made.box))
        if made.turn:
            drawn.set("data-flexo-turn", number(made.turn))
        if made.ends:
            drawn.set(
                "data-flexo-ends", " ".join(number(value) for point in made.ends for value in point)
            )
        self._reached(spec, made)
        self._words(drawn, ident, spec, made)
        return drawn

    def _reached(self, spec: Mapping[str, Any], made: freeform.Geometry) -> None:
        left, top, right, bottom = freeform.bounds(spec, made)
        reach = float(spec.get("line_width") or 0.0) / 2.0 + 1.0
        if spec.get("shadow"):
            reach += self.shadow.offset + self.shadow.spread
        self._take((left - reach, top - reach, right + reach, bottom + reach))

    def _take(self, box: tuple[float, float, float, float]) -> None:
        if self.reach is None:
            self.reach = box
            return
        left, top, right, bottom = self.reach
        self.reach = (min(left, box[0]), min(top, box[1]), max(right, box[2]), max(bottom, box[3]))

    def _words(
        self, drawn: ET.Element, ident: str, spec: Mapping[str, Any], made: freeform.Geometry
    ) -> None:
        from flexo.colour import contrast
        from flexo.render_common import render_runs

        runs = self.runs(spec)
        if not runs:
            return
        typography = self.typography_of(spec)
        measurer = self.measurer(typography)
        pad = float(spec.get("padding") or 0.0)
        role, fill = "ink", None
        if spec.get("colour"):
            colour, named_role = freeform.paint(spec["colour"], self.palette)
            role, fill = (named_role, None) if named_role else ("ink", colour)
        elif (
            made.closed
            and spec.get("fill") not in (None, "none")
            and float(spec.get("fill_opacity", 1.0)) > 0.5
        ):
            # On a fill of its own, its words are the ink or the page's colour, whichever reads.
            ground = freeform.paint(spec["fill"], self.palette)[0]
            if ground:
                ink, page = self.palette.get("ink"), self.palette.get("canvas")
                role = "canvas" if contrast(page, ground) > contrast(ink, ground) else "ink"
        align = str(spec.get("align") or "middle")
        anchor = {"start": None, "middle": "middle", "end": "end"}[align]
        if made.area is not None:
            x, y, w, h = made.area
            inner = (x + pad, y + pad, max(w - 2 * pad, 1.0), max(h - 2 * pad, 1.0))
            metrics = measurer.measure(runs, max_width=inner[2], balance=False)
            valign = str(spec.get("valign") or "middle")
            top = (
                inner[1]
                + {
                    "top": 0.0,
                    "middle": (inner[3] - metrics.height) / 2.0,
                    "bottom": inner[3] - metrics.height,
                }[valign]
            )
            across = {"start": inner[0], "middle": inner[0] + inner[2] / 2.0}.get(
                align, inner[0] + inner[2]
            )
            render_runs(
                drawn,
                f"{ident}.text",
                metrics,
                x=across,
                y=top + metrics.baseline,
                typography=typography,
                palette=self.palette,
                fill_role=role,
                fill=fill,
                anchor=anchor,
                width=inner[2],
            )
            return
        label = made.label
        if label is None:
            return
        metrics = measurer.measure(runs, balance=False)
        w, h = metrics.width + 2 * pad, metrics.height + 2 * pad
        left = label.x - {"start": 0.0, "middle": w / 2.0, "end": w}[label.align]
        top = label.y - {"top": 0.0, "middle": h / 2.0, "bottom": h}[label.valign]
        holder = element(drawn, "g", id=f"{ident}.label")
        if label.angle:
            holder.set(
                "transform",
                f"rotate({number(label.angle)} {number(label.x)} {number(label.y)})",
            )
        across = {"start": left + pad, "middle": left + w / 2.0}.get(label.align, left + w - pad)
        render_runs(
            holder,
            f"{ident}.text",
            metrics,
            x=across,
            y=top + pad + metrics.baseline,
            typography=typography,
            palette=self.palette,
            fill_role=role,
            fill=fill,
            anchor={"start": None, "middle": "middle", "end": "end"}[label.align],
        )
        drawn.set(
            "data-flexo-label",
            " ".join(number(value) for value in (left, top, w, h, label.angle, label.x, label.y)),
        )
        corners = [(left, top), (left + w, top), (left + w, top + h), (left, top + h)]
        if label.angle:
            corners = [
                freeform._turned(point, (label.x, label.y), label.angle) for point in corners
            ]
        xs, ys = [point[0] for point in corners], [point[1] for point in corners]
        self._take((min(xs), min(ys), max(xs), max(ys)))


def _every(ident: str, spec: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    """A shape and, a group's, its shapes, each by the id it is drawn with."""

    found = [(ident, spec)]
    if spec.get("kind") == "group":
        for n, child in enumerate(spec.get("shapes") or []):
            found += _every(f"{ident}.{n}", child)
    return found


def grown(root: ET.Element, reach: Box | None, background: ET.Element | None = None) -> bool:
    """The figure's page (``root``, its SVG) made large enough to hold what its shapes reach
    (``left, top, right, bottom``), on any side, nothing moved: its view starts where they
    do. Its page's rectangle (``background``) is as large. Answers whether it grew."""

    from flexo.units import MILLIMETRES_PER_INCH, POINTS_PER_INCH

    if reach is None:
        return False
    view = [float(value) for value in (root.get("viewBox") or "0 0 0 0").split()]
    x, y, w, h = view
    left, top = min(x, reach[0]), min(y, reach[1])
    right, bottom = max(x + w, reach[2]), max(y + h, reach[3])
    if (left, top, right, bottom) == (x, y, x + w, y + h):
        return False
    width, height = right - left, bottom - top
    root.set("viewBox", " ".join(number(value) for value in (left, top, width, height)))
    root.set("width", f"{number(width / POINTS_PER_INCH * MILLIMETRES_PER_INCH)}mm")
    root.set("height", f"{number(height / POINTS_PER_INCH * MILLIMETRES_PER_INCH)}mm")
    if background is not None:
        for key, value in (("x", left), ("y", top), ("width", width), ("height", height)):
            background.set(key, number(value))
    return True


__all__ = [
    "MARGIN",
    "MARGINS",
    "ROUND",
    "SHAPE_KEYS",
    "Overlay",
    "Placed",
    "around_box",
    "attached",
    "checked",
    "free",
    "grown",
    "margin_of",
    "name_of",
    "part_boxes",
    "placed_round",
    "read",
    "shape_names",
]
