"""Genetic designs: linear constructs drawn in SBOL Visual glyphs, and plasmid maps.

Two components carry them, each a node like any other -- it sits in a figure, is
wired to other nodes, takes the theme's type, palette, and hand:

- ``construct`` sets its ``parts`` left to right on a backbone, each in its SBOL
  Visual glyph: a promoter's bent arrow, a ribosome binding site's half circle, a
  coding sequence's arrow with the gene's name in it, a terminator's T. A part on
  the reverse strand is turned over and hangs below the backbone. A part with an
  ``id`` is a port, so an arrow can leave a gene for the protein it makes.
- ``plasmid`` draws a circular map: the backbone as a circle, each of its
  ``features`` an arc placed by its base pairs (an arrow where it has a
  direction), stacked in lanes where features overlap, named outside the circle
  with leader lines, the plasmid's name and length in the middle.

A gene takes a colour by its name, so ``GFP`` is one colour in every construct
and plasmid of a figure; any part or feature can name a ``tone`` of its own.

This module is geometry only: where every glyph, arc, and word goes, in the
component's own coordinates, from the style and the measured words. Measurement
sizes the component from it; ``render_drawn`` draws it.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.drawn import Picture, Shape, Words, nice_step, path, units
from flexo.geometry import Side, Size
from flexo.ir.semantic import NodeSpec, PortSpec, Record, TextRun
from flexo.markup import parse_label
from flexo.style import LayoutStyle

GENETIC_KINDS = frozenset({"construct", "plasmid"})

PART_TYPES: dict[str, str] = {
    "promoter": "promoter",
    "rbs": "rbs",
    "ribosome-binding-site": "rbs",
    "ribosome-entry-site": "rbs",
    "cds": "cds",
    "gene": "cds",
    "coding-sequence": "cds",
    "terminator": "terminator",
    "operator": "operator",
    "origin": "origin",
    "ori": "origin",
    "origin-of-replication": "origin",
    "insulator": "insulator",
    "primer": "primer",
    "primer-binding-site": "primer",
    "site": "site",
    "restriction-site": "site",
    "region": "region",
    "part": "region",
    "spacer": "spacer",
}
"""Every part a construct or plasmid knows, by the names people write, to its glyph."""

DIRECTED = frozenset({"promoter", "cds", "primer"})
"""Parts that read one way along the DNA, drawn with an arrow on a plasmid."""

_CONSTRUCT_PARTS = frozenset(PART_TYPES.values())
_PLASMID_PARTS = frozenset({"cds", "promoter", "origin", "region", "primer", "site", "terminator"})


# -- what the author wrote ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Part:
    """One part of a construct, or one feature of a plasmid, as written."""

    type: str
    label: tuple[TextRun, ...]
    id: str | None = None
    tone: str | None = None
    reverse: bool = False
    start: int = 0
    end: int = 0
    bp: int = 0
    """A construct part's length in base pairs, for a construct drawn to scale."""

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.label)


def _fail(node: NodeSpec, code: str, message: str, hint: str | None = None) -> FlexoError:
    return FlexoError(Diagnostic(f"genetics.{code}", message, entity_id=node.id, hint=hint))


def _records(node: NodeSpec, name: str) -> tuple[Record, ...]:
    value = node.property(name)
    if value is None:
        return ()
    if not isinstance(value, tuple):
        raise _fail(
            node,
            "records",
            f'"{name}" is a list of mappings, one for each part.',
            hint=f'Write "{name}: [{{type: promoter, label: pTet}}, {{type: cds, label: GFP}}]".',
        )
    return value


def _strand(node: NodeSpec, record: Record) -> bool:
    value = str(record.get("strand", "+")).strip().lower()
    if value in {"+", "1", "forward", "fwd", "top"}:
        return False
    if value in {"-", "-1", "reverse", "rev", "bottom"}:
        return True
    raise _fail(node, "strand", f'strand "{value}" is neither + nor -.')


def _part(node: NodeSpec, record: Record, where: str, allowed: frozenset[str]) -> Part:
    written = str(record.get("type", "")).strip().lower()
    kind = PART_TYPES.get(written)
    if kind is None or kind not in allowed:
        names = sorted(name for name, glyph in PART_TYPES.items() if glyph in allowed)
        raise _fail(
            node,
            "part.unknown",
            f'{where}: no part called "{written}".',
            hint=f"Parts are: {', '.join(names)}.",
        )
    known = {"type", "label", "id", "tone", "strand", "start", "end", "bp"}
    extra = sorted(set(record.as_dict()) - known)
    if extra:
        raise _fail(
            node,
            "part.field",
            f"{where}: {', '.join(extra)} is not a part field.",
            hint=f"Fields are: {', '.join(sorted(known))}.",
        )
    identifier = record.get("id")
    if identifier is not None and not _port_name(str(identifier)):
        raise _fail(
            node,
            "part.id",
            f'{where}: "{identifier}" is not a usable id.',
            hint="Ids start with a letter and use letters, digits, '.', '_' and '-'.",
        )
    tone = record.get("tone")
    label = parse_label(str(record.get("label", "")))
    try:
        bp = int(record.get("bp", 0) or 0)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise _fail(node, "part.bp", f"{where}: bp is a length in base pairs.") from None
    return Part(
        kind,
        label,
        None if identifier is None else str(identifier),
        None if tone is None else str(tone),
        _strand(node, record),
        bp=bp,
    )


def _port_name(text: str) -> bool:
    from flexo.ir.semantic import ID_PATTERN

    return bool(ID_PATTERN.match(text)) and text not in {"input", "output"}


def construct_parts(node: NodeSpec) -> tuple[Part, ...]:
    return tuple(
        _part(node, record, f"part {index + 1}", _CONSTRUCT_PARTS)
        for index, record in enumerate(_records(node, "parts"))
    )


def plasmid_length(node: NodeSpec) -> int:
    value = node.property("length")
    try:
        length = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise _fail(
            node,
            "plasmid.length",
            "A plasmid needs its length in base pairs.",
            hint="Write length: 5421.",
        ) from None
    if length < 10:
        raise _fail(node, "plasmid.length", f"A plasmid of {length} bp is too short to draw.")
    return length


def plasmid_features(node: NodeSpec) -> tuple[Part, ...]:
    length = plasmid_length(node)
    features = []
    for index, record in enumerate(_records(node, "features")):
        where = f"feature {index + 1}"
        part = _part(node, record, where, _PLASMID_PARTS)
        try:
            start = int(record.get("start", 0))  # type: ignore[arg-type]
            end = int(record.get("end", start))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise _fail(
                node, "feature.position", f"{where}: start and end are base pairs."
            ) from None
        for value in (start, end):
            if not 1 <= value <= length:
                raise _fail(
                    node,
                    "feature.position",
                    f"{where}: {value} is outside the plasmid (1 to {length} bp).",
                )
        features.append(replace(part, start=start, end=end))
    return tuple(features)


def part_tone(part: Part) -> str | None:
    """The colour a part takes: its own tone, a gene's name, or none (drawn in ink)."""

    if part.tone is not None:
        text = part.tone.strip()
        return None if text.lower() in {"neutral", "none", ""} else text
    if part.type == "cds":
        return part.text or part.id or "gene"
    return None


def genetic_tones(node: NodeSpec) -> tuple[str, ...]:
    """The tones a construct or plasmid paints with, in order, for the figure's tone map."""

    if node.kind == "construct":
        parts = construct_parts(node)
    elif node.kind == "plasmid":
        parts = plasmid_features(node)
    else:
        return ()
    return tuple(dict.fromkeys(tone for part in parts if (tone := part_tone(part)) is not None))


# -- constructs ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Glyph:
    width: float
    up: float
    down: float
    inside: bool = False
    """Whether the part's name is written inside the glyph (a gene, a region)."""


def _glyph(kind: str, u: float, label_width: float) -> _Glyph:
    if kind == "promoter":
        return _Glyph(1.9 * u, 2.3 * u, 0.0)
    if kind == "rbs":
        return _Glyph(1.4 * u, 0.7 * u, 0.0)
    if kind == "cds":
        return _Glyph(max(4.6 * u, label_width + 2.4 * u), 0.95 * u, 0.95 * u, inside=True)
    if kind == "region":
        return _Glyph(max(3.2 * u, label_width + 1.6 * u), 0.8 * u, 0.8 * u, inside=True)
    if kind == "terminator":
        return _Glyph(1.5 * u, 1.9 * u, 0.0)
    if kind in {"operator", "insulator"}:
        return _Glyph(1.3 * u, 0.65 * u, 0.65 * u)
    if kind == "origin":
        return _Glyph(1.5 * u, 0.75 * u, 0.75 * u)
    if kind == "primer":
        return _Glyph(2.6 * u, 1.3 * u, 0.0)
    if kind == "site":
        return _Glyph(0.8 * u, 1.3 * u, 0.5 * u)
    return _Glyph(1.4 * u, 0.0, 0.0)  # a spacer: backbone only


def _glyph_shapes(
    kind: str,
    x: float,
    width: float,
    u: float,
    pen: float,
    flip: bool,
    base: float,
    name: str,
    tone: str | None,
) -> list[Shape]:
    """A glyph in ``[x, x + width]`` on the backbone at ``base``; ``flip`` turns it over
    (a reverse part: pointing left, hanging below)."""

    centre = x + width / 2.0

    def at(dx: float, dy: float) -> tuple[float, float]:
        # dx from the glyph's centre, dy up from the backbone, both read forward.
        return (centre - dx, base + dy) if flip else (centre + dx, base - dy)

    def line(*points: tuple[float, float]) -> str:
        first, *rest = [at(*point) for point in points]
        return path("M", *first, *[item for point in rest for item in ("L", *point)])

    half = width / 2.0
    heavy = pen * 1.6
    if kind == "promoter":
        stem, top, tip = -half + 0.15 * u, 2.0 * u, half - 0.05 * u
        head = 0.62 * u
        return [
            Shape(
                f"{name}.stem",
                line((stem, 0.0), (stem, top), (tip - head * 0.6, top)),
                "line",
                tone,
                heavy,
            ),
            Shape(
                f"{name}.head",
                line((tip - head, top + head * 0.55), (tip, top), (tip - head, top - head * 0.55))
                + " Z",
                "solid",
                tone,
                pen,
            ),
        ]
    if kind == "rbs":
        r = 0.68 * u
        (x1, y1), (x2, y2) = at(-r, 0.0), at(r, 0.0)
        return [Shape(name, path("M", x1, y1, "A", r, r, 0, 0, 1, x2, y2, "Z"), "body", tone, pen)]
    if kind == "cds":
        h = 0.9 * u
        tip = min(1.1 * u, width / 3.0)
        return [
            Shape(
                name,
                line((-half, -h), (half - tip, -h), (half, 0.0), (half - tip, h), (-half, h))
                + " Z",
                "body",
                tone,
                pen,
            )
        ]
    if kind == "region":
        h = 0.75 * u
        return [
            Shape(
                name, line((-half, -h), (half, -h), (half, h), (-half, h)) + " Z", "body", tone, pen
            )
        ]
    if kind == "terminator":
        top, bar = 1.8 * u, 0.62 * u
        return [
            Shape(
                name,
                line((0.0, 0.0), (0.0, top)) + " " + line((-bar, top), (bar, top)),
                "line",
                tone,
                heavy,
            )
        ]
    if kind == "operator":
        s = 0.6 * u
        return [Shape(name, line((-s, -s), (s, -s), (s, s), (-s, s)) + " Z", "hollow", tone, pen)]
    if kind == "insulator":
        s, t = 0.6 * u, 0.3 * u
        outer = line((-s, -s), (s, -s), (s, s), (-s, s)) + " Z"
        inner = line((-t, -t), (t, -t), (t, t), (-t, t)) + " Z"
        return [
            Shape(name, outer, "hollow", tone, pen),
            Shape(f"{name}.inner", inner, "hollow", tone, pen),
        ]
    if kind == "origin":
        r = 0.7 * u
        cx, cy = at(0.0, 0.0)
        return [
            Shape(
                name,
                path(
                    "M",
                    cx - r,
                    cy,
                    "A",
                    r,
                    r,
                    0,
                    1,
                    1,
                    cx + r,
                    cy,
                    "A",
                    r,
                    r,
                    0,
                    1,
                    1,
                    cx - r,
                    cy,
                    "Z",
                ),
                "hollow",
                tone,
                pen,
            )
        ]
    if kind == "primer":
        y, barb = 0.75 * u, 0.5 * u
        return [
            Shape(name, line((-half, y), (half, y), (half - barb, y + barb)), "line", tone, heavy)
        ]
    if kind == "site":
        return [Shape(name, line((0.0, -0.45 * u), (0.0, 1.25 * u)), "line", tone, heavy)]
    return []


def construct_drawing(node: NodeSpec, style: LayoutStyle) -> Picture:
    """A construct laid out: parts left to right on the backbone, names under them
    (over them for reverse parts, inside for genes), the construct's name over all."""

    measures = units(style)
    u, pen = measures.u, measures.pen
    parts = construct_parts(node)
    if not parts:
        raise _fail(
            node,
            "construct.empty",
            "A construct needs parts.",
            hint="Write parts: [{type: promoter}, {type: rbs}, {type: cds, label: GFP}].",
        )
    lead, gap, word_gap = 1.1 * u, 0.45 * u, 0.35 * u
    slots = []
    x = lead
    for part in parts:
        metrics = measures.measure(part.label) if part.label else None
        width = metrics.width if metrics else 0.0
        glyph = _glyph(part.type, u, width)
        slot = max(glyph.width, 0.0 if glyph.inside or metrics is None else width)
        slots.append((part, glyph, metrics, x, slot))
        x += slot + gap
    length = x - gap + lead
    scale = _construct_scale(node)
    if scale is not None:
        slots, length = _scaled_slots(node, parts, measures, scale, lead)

    # How far the drawing reaches above and below the backbone, words included.
    above = below = 0.0
    for part, glyph, metrics, _, _ in slots:
        up, down = (glyph.down, glyph.up) if part.reverse else (glyph.up, glyph.down)
        words = 0.0 if metrics is None or glyph.inside else word_gap + metrics.height
        if part.reverse:
            above, below = max(above, up + words), max(below, down)
        else:
            above, below = max(above, up), max(below, down + words)
    above, below = max(above, 0.9 * u), max(below, 0.9 * u)
    # Drawn to scale, a name sits in one row clear of every glyph on its side,
    # not just its own: a long gene's box runs under its small neighbours.
    reach_down = max((glyph.up if part.reverse else glyph.down) for part, glyph, *_ in slots)
    reach_up = max((glyph.down if part.reverse else glyph.up) for part, glyph, *_ in slots)
    if scale is not None:
        heights_down = [m.height for p, g, m, *_ in slots if m and not g.inside and not p.reverse]
        heights_up = [m.height for p, g, m, *_ in slots if m and not g.inside and p.reverse]
        if heights_down:
            below = max(below, reach_down + word_gap + max(heights_down))
        if heights_up:
            above = max(above, reach_up + word_gap + max(heights_up))
    title = (
        measures.measure(node.label, weight=style.typography.title_weight) if node.label else None
    )
    top = (title.height + 0.6 * u) if title else 0.0
    if title is not None and title.width + 2 * lead > length:
        # A name longer than the parts: the backbone runs under all of it, with
        # the parts in the middle of it.
        extra = title.width + 2 * lead - length
        slots = [
            (part, glyph, metrics, x + extra / 2.0, slot) for part, glyph, metrics, x, slot in slots
        ]
        length += extra
    pad = 0.25 * u
    base = pad + top + above
    axis_room = 0.0
    if scale is not None and node.property("ticks") is not False:
        axis_room = 0.9 * u + measures.small.measure((TextRun("0"),)).height
    height = base + below + axis_room + pad

    shapes = [
        Shape(
            f"{node.id}.backbone",
            path("M", 0.0, base, "L", length, base),
            "backbone",
            None,
            pen * 1.4,
        )
    ]
    words: list[Words] = []
    ports = [
        PortSpec("input", Side.WEST, base / height),
        PortSpec("output", Side.EAST, base / height),
    ]
    # Long parts first, so the small glyphs drawn to scale over them show.
    order = sorted(
        enumerate(slots),
        key=lambda item: 0 if scale is not None and item[1][0].type in _SCALED else 1,
    )
    for index, (part, glyph, metrics, left, slot) in order:
        name = f"{node.id}.part{index + 1}"
        tone = part_tone(part)
        glyph_left = left + (slot - glyph.width) / 2.0
        shapes.extend(
            _glyph_shapes(
                part.type, glyph_left, glyph.width, u, pen, part.reverse, base, name, tone
            )
        )
        centre = left + slot / 2.0
        if metrics is not None:
            if glyph.inside:
                y = base - metrics.height / 2.0 + metrics.baseline
                words.append(
                    Words(
                        f"{name}.label", part.label, metrics, centre, y, role="tone-ink", tone=tone
                    )
                )
            elif part.reverse:
                reach = reach_up if scale is not None else glyph.down
                y = base - reach - word_gap - metrics.height + metrics.baseline
                words.append(Words(f"{name}.label", part.label, metrics, centre, y))
            else:
                reach = reach_down if scale is not None else glyph.down
                y = base + reach + word_gap + metrics.baseline
                words.append(Words(f"{name}.label", part.label, metrics, centre, y))
        if part.id is not None:
            side = Side.NORTH if part.reverse else Side.SOUTH
            ports.append(PortSpec(part.id, side, min(max(centre / length, 0.0), 1.0)))
    if scale is not None:
        # Drawn to scale, small parts sit close: their names are spread apart
        # (under the backbone and over it separately), each led to its part.
        words, leaders = _spread_part_names(words, slots, node.id, u, pen, base, length)
        shapes.extend(leaders)
        if axis_room:
            shapes_axis, words_axis = _bp_axis(
                node.id, parts, scale, lead, base + below + 0.4 * u, measures, pen
            )
            shapes.extend(shapes_axis)
            words.extend(words_axis)
    if title is not None:
        words.append(
            Words(
                f"{node.id}.label",
                node.label,
                title,
                lead,
                pad + title.baseline,
                anchor="start",
                weight=style.typography.title_weight,
            )
        )
    return Picture(Size(length, height), tuple(shapes), tuple(words), tuple(ports))


_SCALED = frozenset({"cds", "region", "spacer", "primer"})
"""Parts drawn as long as they are, on a construct drawn to scale; the rest are
glyphs of their own size, centred on their stretch of backbone."""


def _construct_scale(node: NodeSpec) -> float | None:
    value = node.property("scale")
    if value is None:
        return None
    try:
        scale = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise _fail(
            node, "construct.scale", f"scale {value!r} is not points a base pair."
        ) from None
    if scale <= 0:
        raise _fail(node, "construct.scale", "scale is points a base pair, more than 0.")
    return scale


def _scaled_slots(node: NodeSpec, parts, measures, scale: float, lead: float):
    """Each part's stretch of backbone, ``bp`` times ``scale`` long, end to end."""

    u = measures.u
    slots = []
    x = lead
    for index, part in enumerate(parts, 1):
        if part.bp <= 0:
            raise _fail(
                node,
                "part.bp",
                f"part {index}: a construct drawn to scale needs each part's length.",
                hint="Write bp: 720 on every part, or leave out scale.",
            )
        metrics = measures.measure(part.label) if part.label else None
        glyph = _glyph(part.type, u, metrics.width if metrics else 0.0)
        slot = part.bp * scale
        if part.type in _SCALED:
            margin = 2.4 * u if part.type == "cds" else 1.6 * u
            fits = glyph.inside and metrics is not None and metrics.width + margin <= slot
            glyph = replace(glyph, width=max(slot, 0.8 * u), inside=fits)
        slots.append((part, glyph, metrics, x, slot))
        x += slot
    return slots, x + lead


def _spread_part_names(
    words, slots, node_id: str, u: float, pen: float, base: float, length: float
):
    from flexo.drawn import Name, spread

    by_id = {item.id: item for item in words}
    leaders: list[Shape] = []
    for below in (True, False):
        names = []
        for index, (part, glyph, _, left, slot) in enumerate(slots, 1):
            key = f"{node_id}.part{index}.label"
            item = by_id.get(key)
            if item is None or glyph.inside or part.reverse == below:
                continue
            names.append(Name(key, item.runs, item.metrics, left + slot / 2.0))
        spread(names, 0.4 * u, 0.0, length)
        for name in names:
            item = by_id[name.key]
            by_id[name.key] = replace(item, x=name.x)
            if abs(name.x - name.want) > 0.2 * u:
                edge = (
                    item.y - item.metrics.baseline
                    if below
                    else item.y - item.metrics.baseline + item.metrics.height
                )
                start = base + (0.95 * u if below else -0.95 * u)
                leaders.append(
                    Shape(
                        f"{name.key}.leader",
                        path("M", name.want, start, "L", name.x, edge),
                        "leader",
                        None,
                        pen * 0.7,
                    )
                )
    return [by_id[item.id] for item in words], leaders


def _bp_axis(node_id: str, parts, scale: float, lead: float, y: float, measures, pen: float):
    """A base-pair ruler under a construct drawn to scale."""

    total = sum(part.bp for part in parts)
    step = nice_step(total)
    u = measures.u
    shapes = [
        Shape(
            f"{node_id}.axis",
            path("M", lead, y, "L", lead + total * scale, y),
            "tick",
            None,
            pen * 0.8,
        )
    ]
    words = []
    values = [*range(0, total, step), total]
    if len(values) > 2 and total - values[-2] < step * 0.35:
        values.pop(-2)
    for value in values:
        x = lead + value * scale
        shapes.append(
            Shape(
                f"{node_id}.tick{value}",
                path("M", x, y, "L", x, y + 0.3 * u),
                "tick",
                None,
                pen * 0.8,
            )
        )
        runs = (TextRun(f"{value:,} bp" if value == total else f"{value:,}"),)
        metrics = measures.measure(runs, small=True)
        words.append(
            Words(
                f"{node_id}.tick{value}.label",
                runs,
                metrics,
                x,
                y + 0.45 * u + metrics.baseline,
                size=measures.small_size,
                role="muted-ink",
            )
        )
    return shapes, words


# -- plasmids -----------------------------------------------------------------------------


@dataclass(slots=True)
class _Label:
    words: Words
    angle: float
    right: bool
    ideal: float
    y: float = 0.0
    reach: float = 0.0
    """How far out the feature it names reaches, where its leader line starts."""
    height: float = 0.0
    anchor_x: float = 0.0


def _span(part: Part, length: int) -> tuple[float, float]:
    """A feature's start and end as angles, clockwise from the top; the end past the
    start even where the feature runs across the origin."""

    start = (part.start - 1) / length * 2.0 * math.pi
    end = part.end / length * 2.0 * math.pi
    if part.end < part.start:
        end += 2.0 * math.pi
    if end - start < 1e-6:
        end = start + 2.0 * math.pi / length
    return start, end


def _lanes(spans: list[tuple[float, float]], clearance: float) -> list[int]:
    """Stack overlapping arcs outward: each takes the innermost lane it fits in."""

    taken: list[list[tuple[float, float]]] = []
    lanes = []
    for start, end in spans:
        for lane, arcs in enumerate(taken):
            if all(not _overlap(start, end, a, b, clearance) for a, b in arcs):
                arcs.append((start, end))
                lanes.append(lane)
                break
        else:
            taken.append([(start, end)])
            lanes.append(len(taken) - 1)
    return lanes


def _overlap(a1: float, a2: float, b1: float, b2: float, clearance: float) -> bool:
    for shift in (-2.0 * math.pi, 0.0, 2.0 * math.pi):
        if a1 < b2 + shift + clearance and b1 + shift < a2 + clearance:
            return True
    return False


def plasmid_drawing(node: NodeSpec, style: LayoutStyle) -> Picture:
    """A plasmid map: the backbone a circle, features arcs by their base pairs (stacked
    where they overlap), sites ticks, every feature named outside with a leader line."""

    measures = units(style)
    u, pen = measures.u, measures.pen
    length = plasmid_length(node)
    features = plasmid_features(node)
    radius = float(node.property("radius", 0) or 0) or 7.5 * u
    band, lane_gap = 1.15 * u, 0.3 * u

    arcs = [(index, part) for index, part in enumerate(features) if part.type != "site"]
    spans = [_span(part, length) for _, part in arcs]
    lanes = _lanes(spans, 0.9 * u / radius)
    lane_of = {index: lane for (index, _), lane in zip(arcs, lanes, strict=True)}
    outer_lane = max(lanes, default=0)

    def lane_radius(lane: int) -> float:
        return radius + lane * (band + lane_gap)

    # Words: the name and length in the middle, a label for every named feature.
    name_metrics = (
        measures.measure(node.label, weight=style.typography.title_weight) if node.label else None
    )
    size_runs = (TextRun(f"{length:,} bp"),)
    size_metrics = measures.measure(size_runs, small=True)
    ring = lane_radius(outer_lane) + band / 2.0
    label_radius = ring + 1.1 * u
    labels: list[_Label] = []
    for index, part in enumerate(features):
        if not part.label:
            continue
        runs = part.label
        if part.type == "site":
            runs = (*runs, TextRun(f" ({part.start:,})", weight=400))
        metrics = measures.measure(runs, small=part.type == "site")
        if part.type == "site":
            angle = (part.start - 0.5) / length * 2.0 * math.pi
            reach = radius + 0.9 * u
        else:
            start, end = _span(part, length)
            angle = (start + end) / 2.0
            reach = lane_radius(lane_of[index]) + (
                band * 0.5 if part.type != "primer" else band * 0.2
            )
        sine, cosine = math.sin(angle), math.cos(angle)
        right = sine >= -1e-9 if abs(sine) > 0.02 else cosine > 0
        words = Words(
            f"{node.id}.feature{index + 1}.label",
            runs,
            metrics,
            0.0,
            0.0,
            anchor="start" if right else "end",
            size=measures.small_size if part.type == "site" else None,
        )
        ideal = -label_radius * cosine
        labels.append(_Label(words, angle, right, ideal, ideal, reach, metrics.height))

    # Labels on each side keep their order round the circle and never overlap.
    spacing = 0.15 * u
    for right in (True, False):
        side = sorted(
            (label for label in labels if label.right == right), key=lambda item: item.ideal
        )
        for _ in range(60):
            moved = False
            for first, second in itertools.pairwise(side):
                need = (first.height + second.height) / 2.0 + spacing
                if second.y - first.y < need:
                    push = (need - (second.y - first.y)) / 2.0
                    first.y -= push
                    second.y += push
                    moved = True
            if not moved:
                break
        for label in side:
            # Across: on the circle's own curve at that height, so leaders stay short, but
            # never inside the elbow of its own leader, so leaders do not cross.
            level = max(-1.0, min(1.0, label.y / label_radius))
            across = label_radius * math.sqrt(max(0.0, 1.0 - level * level))
            elbow = abs(max(label.reach, ring + 0.45 * u) * math.sin(label.angle))
            across = max(across, elbow + 0.3 * u)
            label.anchor_x = (across + 0.35 * u) if right else -(across + 0.35 * u)

    # The drawing's extent, centred on the circle; then everything moves by the margin.
    left = min(
        [-ring]
        + [label.anchor_x - label.words.metrics.width for label in labels if not label.right]
    )
    right_edge = max(
        [ring] + [label.anchor_x + label.words.metrics.width for label in labels if label.right]
    )
    top = min([-ring] + [label.y - label.height / 2.0 for label in labels])
    bottom = max([ring] + [label.y + label.height / 2.0 for label in labels])
    pad = 0.4 * u
    cx, cy = pad - left, pad - top
    size = Size(right_edge - left + 2.0 * pad, bottom - top + 2.0 * pad)

    def point(r: float, angle: float) -> tuple[float, float]:
        return cx + r * math.sin(angle), cy - r * math.cos(angle)

    shapes = [
        Shape(
            f"{node.id}.backbone",
            path(
                "M",
                cx - radius,
                cy,
                "A",
                radius,
                radius,
                0,
                1,
                1,
                cx + radius,
                cy,
                "A",
                radius,
                radius,
                0,
                1,
                1,
                cx - radius,
                cy,
                "Z",
            ),
            "backbone",
            None,
            pen * 1.4,
        )
    ]
    # Ticks inside the backbone, every round number of base pairs, each numbered.
    words: list[Words] = []
    if node.property("ticks", True) not in (False, "false", "no"):
        step = nice_step(length)
        ticks = []
        for position in range(step, length, step):
            angle = position / length * 2.0 * math.pi
            x1, y1 = point(radius - band / 2.0 - 0.15 * u, angle)
            x2, y2 = point(radius - band / 2.0 - 0.55 * u, angle)
            ticks.extend(["M", x1, y1, "L", x2, y2])
            runs = (TextRun(f"{position:,}"),)
            metrics = measures.measure(runs, small=True)
            # Set just inside the tick, pulled in by half its own extent along the radius.
            inward = radius - band / 2.0 - 0.8 * u
            half = abs(math.sin(angle)) * metrics.width + abs(math.cos(angle)) * metrics.height
            inward -= half / 2.0
            tx, ty = point(inward, angle)
            words.append(
                Words(
                    f"{node.id}.tick{position}",
                    runs,
                    metrics,
                    tx,
                    ty - metrics.height / 2.0 + metrics.baseline,
                    role="muted-ink",
                    size=measures.small_size,
                )
            )
        if ticks:
            shapes.append(Shape(f"{node.id}.ticks", path(*ticks), "tick", None, pen * 0.8))

    for index, part in enumerate(features):
        name = f"{node.id}.feature{index + 1}"
        tone = part_tone(part)
        if part.type == "site":
            angle = (part.start - 0.5) / length * 2.0 * math.pi
            x1, y1 = point(radius - 0.35 * u, angle)
            x2, y2 = point(radius + 0.9 * u, angle)
            shapes.append(Shape(name, path("M", x1, y1, "L", x2, y2), "line", tone, pen * 1.2))
            continue
        if part.type == "terminator":
            angle = (part.start + part.end - 1) / 2.0 / length * 2.0 * math.pi
            r = lane_radius(lane_of[index])
            stem_in, stem_out = point(r - band * 0.3, angle), point(r + band * 0.55, angle)
            # A T standing out from the backbone: its bar across the radius.
            bar = 0.5 * u / (r + band * 0.55)
            bar1, bar2 = point(r + band * 0.55, angle - bar), point(r + band * 0.55, angle + bar)
            shapes.append(
                Shape(
                    name,
                    path("M", *stem_in, "L", *stem_out, "M", *bar1, "L", *bar2),
                    "line",
                    tone,
                    pen * 1.6,
                )
            )
            continue
        start, end = _span(part, length)
        r = lane_radius(lane_of[index])
        thick = band * (0.6 if part.type in {"promoter", "primer"} else 1.0)
        if part.type == "primer":
            r = r + band * 0.2
        arrow = part.type in DIRECTED
        shapes.append(
            Shape(
                name,
                _arc(cx, cy, r, thick, start, end, arrow, part.reverse, u),
                "body" if part.type != "primer" else "solid",
                tone,
                pen,
            )
        )

    for label in labels:
        metrics = label.words.metrics
        x = cx + label.anchor_x
        y = cy + label.y - metrics.height / 2.0 + metrics.baseline
        words.append(replace(label.words, x=x, y=y, role="ink"))
        # A leader from the feature to its name: straight out from the circle past every
        # lane, then across to the name, so leaders keep the order of what they name.
        fx, fy = point(label.reach, label.angle)
        ex, ey = point(max(label.reach, ring + 0.45 * u), label.angle)
        tx = x - 0.2 * u if label.right else x + 0.2 * u
        ty = cy + label.y
        shapes.append(
            Shape(
                f"{label.words.id.removesuffix('.label')}.leader",
                path("M", fx, fy, "L", ex, ey, "L", tx, ty),
                "leader",
                None,
                pen * 0.7,
            )
        )

    if name_metrics is not None:
        total = name_metrics.height + 0.15 * u + size_metrics.height
        top_y = cy - total / 2.0
        words.append(
            Words(
                f"{node.id}.label",
                node.label,
                name_metrics,
                cx,
                top_y + name_metrics.baseline,
                weight=style.typography.title_weight,
            )
        )
        words.append(
            Words(
                f"{node.id}.length",
                size_runs,
                size_metrics,
                cx,
                top_y + name_metrics.height + 0.15 * u + size_metrics.baseline,
                role="muted-ink",
                size=measures.small_size,
            )
        )
    else:
        words.append(
            Words(
                f"{node.id}.length",
                size_runs,
                size_metrics,
                cx,
                cy - size_metrics.height / 2.0 + size_metrics.baseline,
                role="muted-ink",
                size=measures.small_size,
            )
        )
    return Picture(size, tuple(shapes), tuple(words), ())


def _arc(
    cx: float,
    cy: float,
    r: float,
    thick: float,
    start: float,
    end: float,
    arrow: bool,
    reverse: bool,
    u: float,
) -> str:
    """A band along the circle from ``start`` to ``end`` (angles clockwise from the
    top), with an arrowhead at its end -- or its start, on the reverse strand."""

    outer, inner = r + thick / 2.0, r - thick / 2.0
    if end - start >= 2 * math.pi - 1e-6:
        if not arrow:
            # All the way round: a ring. An arc's ends cannot meet (SVG drops an
            # arc that starts where it ends), so each circle is two half arcs,
            # the inner one run the other way to leave the middle open.
            top, bottom = cy - outer, cy + outer
            inside_top, inside_bottom = cy - inner, cy + inner
            return path(
                "M", cx, top, "A", outer, outer, 0, 1, 1, cx, bottom,
                "A", outer, outer, 0, 1, 1, cx, top, "Z",
                "M", cx, inside_top, "A", inner, inner, 0, 1, 0, cx, inside_bottom,
                "A", inner, inner, 0, 1, 0, cx, inside_top, "Z",
            )  # fmt: skip
        end = start + 2 * math.pi - 1e-3
    head = min(0.9 * u / r, (end - start) * 0.45) if arrow else 0.0
    a1, a2 = (start + head, end) if reverse else (start, end - head)

    def point(radius: float, angle: float) -> tuple[float, float]:
        return cx + radius * math.sin(angle), cy - radius * math.cos(angle)

    large = 1 if a2 - a1 > math.pi else 0
    o1, o2 = point(outer, a1), point(outer, a2)
    i1, i2 = point(inner, a1), point(inner, a2)
    commands: list[object] = ["M", *o1, "A", outer, outer, 0, large, 1, *o2]
    if arrow and not reverse:
        wide = thick * 0.5
        commands += [
            "L",
            *point(outer + wide * 0.5, a2),
            "L",
            *point(r, end),
            "L",
            *point(inner - wide * 0.5, a2),
            "L",
            *i2,
        ]
    else:
        commands += ["L", *i2]
    commands += ["A", inner, inner, 0, large, 0, *i1]
    if arrow and reverse:
        wide = thick * 0.5
        commands += [
            "L",
            *point(inner - wide * 0.5, a1),
            "L",
            *point(r, start),
            "L",
            *point(outer + wide * 0.5, a1),
        ]
    commands.append("Z")
    return path(*commands)


def genetic_drawing(node: NodeSpec, style: LayoutStyle) -> Picture:
    if node.kind == "construct":
        return construct_drawing(node, style)
    return plasmid_drawing(node, style)


GeneticDrawing = Picture
