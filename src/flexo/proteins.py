"""Protein domain maps: a chain drawn to scale by residue, its domains on it.

A ``protein`` component draws the domain map that opens many structure papers: the
chain as a thin bar, one residue a fixed width, and on it

- **domains**, regions, and motifs as boxes, named inside when the name fits and
  under the box when it does not; a domain takes a colour by its name, so the
  kinase domain is one colour in every protein of a figure;
- **transmembrane helices** as tall dark bars and a **signal peptide** as a
  short box at the N terminus;
- **sites** -- mutations, modifications, anything at one residue -- as
  lollipops standing on the chain, their names spread apart over them;
- **disulfides** as brackets under the chain, stacked where they overlap;
- a residue **axis** under it all.

``tracks`` draws the same protein several times, one over the other on one
scale -- the constructs of a study: full length, a truncation (``start``,
``end``), a deletion (``delete: "61-121"``). The scale is ``scale`` points a
residue, or whatever fits the chain in a comfortable width; two proteins given
one ``scale`` line up residue for residue.

Geometry only, like ``flexo.genetics``: ``flexo.render_drawn`` paints it.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.drawn import Picture, Shape, Words, nice_step, path, units
from flexo.geometry import Side, Size
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import NodeSpec, PortSpec, Record, TextRun
from flexo.markup import parse_label
from flexo.secondary import (
    HELIX_TONE,
    SECONDARY_KINDS,
    STRAND_TONE,
    Element,
    dssp_elements,
    make_lane,
    numbered,
)
from flexo.style import LayoutStyle

FEATURE_TYPES: dict[str, str] = {
    "domain": "domain",
    "family": "domain",
    "repeat": "domain",
    "region": "region",
    "disordered": "region",
    "low-complexity": "region",
    "coiled-coil": "region",
    "motif": "motif",
    "transmembrane": "transmembrane",
    "tm": "transmembrane",
    "helix": "helix",
    "alpha-helix": "helix",
    "310-helix": "helix",
    "strand": "strand",
    "beta-strand": "strand",
    "sheet": "strand",
    "turn": "turn",
    "signal": "signal",
    "signal-peptide": "signal",
    "transit-peptide": "signal",
    "propeptide": "signal",
    "site": "site",
    "mutation": "site",
    "variant": "site",
    "modification": "site",
    "phosphorylation": "site",
    "glycosylation": "site",
    "acetylation": "site",
    "methylation": "site",
    "ubiquitination": "site",
    "active-site": "site",
    "binding-site": "site",
    "disulfide": "disulfide",
    "crosslink": "disulfide",
    "bond": "disulfide",
}
"""Every feature a protein knows, by the names people write, to how it is drawn."""

_SPANS = frozenset({"domain", "region", "motif", "transmembrane", "signal"})


@dataclass(frozen=True, slots=True)
class Feature:
    """One feature of a protein, as written."""

    kind: str
    written: str
    label: tuple[TextRun, ...]
    start: int
    end: int
    tone: str | None = None
    id: str | None = None

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.label)


@dataclass(frozen=True, slots=True)
class Track:
    """One drawing of the protein: which residues it keeps, and its name."""

    label: tuple[TextRun, ...]
    start: int
    end: int
    deleted: tuple[tuple[int, int], ...] = ()

    def keeps(self, residue: float) -> bool:
        return self.start <= residue <= self.end and not any(
            low <= residue <= high for low, high in self.deleted
        )

    def pieces(self) -> list[tuple[int, int]]:
        """The stretches of chain this track draws, N to C."""

        pieces, at = [], self.start
        for low, high in sorted(self.deleted):
            if low > at:
                pieces.append((at, min(low - 1, self.end)))
            at = max(at, high + 1)
        if at <= self.end:
            pieces.append((at, self.end))
        return pieces


def _fail(node: NodeSpec, code: str, message: str, hint: str | None = None) -> FlexoError:
    return FlexoError(Diagnostic(f"protein.{code}", message, entity_id=node.id, hint=hint))


def _records(node: NodeSpec, name: str) -> tuple[Record, ...]:
    value = node.property(name)
    if value is None:
        return ()
    if not isinstance(value, tuple):
        raise _fail(node, "records", f'"{name}" is a list of mappings.')
    return value


def _residue(node: NodeSpec, value: object, where: str, length: int) -> int:
    try:
        residue = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise _fail(node, "position", f"{where}: {value!r} is not a residue number.") from None
    if not 1 <= residue <= length:
        raise _fail(
            node, "position", f"{where}: residue {residue} is outside the protein (1 to {length})."
        )
    return residue


def protein_length(node: NodeSpec) -> int:
    value = node.property("length")
    try:
        length = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise _fail(
            node, "length", "A protein needs its length in residues.", hint="Write length: 1130."
        ) from None
    if length < 2:
        raise _fail(node, "length", f"A protein of {length} residues is too short to draw.")
    return length


def protein_features(node: NodeSpec) -> tuple[Feature, ...]:
    length = protein_length(node)
    features = []
    for index, record in enumerate(_records(node, "features")):
        where = f"feature {index + 1}"
        written = str(record.get("type", "domain")).strip().lower()
        kind = FEATURE_TYPES.get(written)
        if kind is None:
            raise _fail(
                node,
                "feature.unknown",
                f'{where}: no feature called "{written}".',
                hint=f"Features are: {', '.join(sorted(FEATURE_TYPES))}.",
            )
        known = {"type", "label", "start", "end", "at", "tone", "id"}
        extra = sorted(set(record.as_dict()) - known)
        if extra:
            raise _fail(
                node,
                "feature.field",
                f"{where}: {', '.join(extra)} is not a feature field.",
                hint=f"Fields are: {', '.join(sorted(known))}.",
            )
        if kind == "site":
            at = record.get("at", record.get("start"))
            if at is None:
                raise _fail(node, "position", f"{where}: a site needs the residue it is at (at:).")
            start = end = _residue(node, at, where, length)
        else:
            if record.get("start") is None or record.get("end") is None:
                raise _fail(node, "position", f"{where}: a {written} needs a start and an end.")
            start = _residue(node, record.get("start"), where, length)
            end = _residue(node, record.get("end"), where, length)
            if end < start:
                raise _fail(
                    node, "position", f"{where}: it ends ({end}) before it starts ({start})."
                )
        tone = record.get("tone")
        identifier = record.get("id")
        features.append(
            Feature(
                kind,
                written,
                parse_label(str(record.get("label", ""))),
                start,
                end,
                None if tone is None else str(tone),
                None if identifier is None else str(identifier),
            )
        )
    return tuple(features)


_RANGE = re.compile(r"^\s*(\d+)\s*[-\u2013:]\s*(\d+)\s*$|^\s*(\d+)\s*$")


def protein_tracks(node: NodeSpec) -> tuple[Track, ...]:
    length = protein_length(node)
    records = _records(node, "tracks")
    if not records:
        return (Track((), 1, length),)
    tracks = []
    for index, record in enumerate(records):
        where = f"track {index + 1}"
        extra = sorted(set(record.as_dict()) - {"label", "start", "end", "delete"})
        if extra:
            raise _fail(
                node,
                "track.field",
                f"{where}: {', '.join(extra)} is not a track field.",
                hint="Fields are: label, start, end, delete.",
            )
        start = _residue(node, record.get("start", 1), where, length)
        end = _residue(node, record.get("end", length), where, length)
        deleted = []
        for piece in str(record.get("delete", "") or "").split(","):
            if not piece.strip():
                continue
            match = _RANGE.match(piece)
            if match is None:
                raise _fail(
                    node,
                    "track.delete",
                    f'{where}: "{piece.strip()}" is not a stretch of residues.',
                    hint='Write delete: "61-121" (several: "61-121, 300-310").',
                )
            low = int(match.group(1) or match.group(3))
            high = int(match.group(2) or match.group(3))
            deleted.append(
                (
                    _residue(node, min(low, high), where, length),
                    _residue(node, max(low, high), where, length),
                )
            )
        tracks.append(
            Track(parse_label(str(record.get("label", ""))), start, end, tuple(sorted(deleted)))
        )
    return tuple(tracks)


def feature_tone(feature: Feature) -> str | None:
    """A feature's colour: its own tone; a domain's, region's, or motif's name; a
    site's kind (every mutation one colour); or none, for ink."""

    if feature.tone is not None:
        text = feature.tone.strip()
        return None if text.lower() in {"neutral", "none", ""} else text
    if feature.kind in {"domain", "motif", "region"}:
        return feature.text or feature.written
    if feature.kind == "site" and feature.written not in {"site"}:
        return feature.written
    if feature.kind == "signal":
        return "signal"
    return None


def protein_tones(node: NodeSpec) -> tuple[str, ...]:
    tones = [tone for feature in protein_features(node) if (tone := feature_tone(feature))]
    kinds = {element.kind for element in protein_secondary(node)}
    tones += [
        tone for kind, tone in (("helix", HELIX_TONE), ("strand", STRAND_TONE)) if kind in kinds
    ]
    return tuple(dict.fromkeys(tones))


def protein_secondary(node: NodeSpec) -> list[Element]:
    """The protein's helices, strands, and turns: its DSSP string's, and its features'."""

    length = protein_length(node)
    elements: list[Element] = []
    text = node.property("secondary")
    if text:
        first = int(node.property("secondary_start") or 1)  # type: ignore[arg-type]
        read = dssp_elements(str(text), first)
        if isinstance(read, str):
            raise _fail(
                node,
                "secondary",
                f'"{read}" is not a DSSP letter.',
                hint="Write H, G, I (helix), E (strand), T (turn), or C, S, B, - (loop).",
            )
        last = first + len(str(text)) - 1
        if first < 1 or last > length:
            raise _fail(
                node,
                "secondary",
                f"the secondary structure runs from residue {first} to {last}, "
                f"outside the protein (1 to {length}).",
            )
        elements.extend(read)
    for feature in protein_features(node):
        if feature.kind in SECONDARY_KINDS:
            elements.append(Element(feature.kind, feature.start, feature.end, feature.label))
    return numbered(elements, node.property("numbered") is not False)


# -- layout ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Label:
    """A name to set over (or under) a point of the chain, pushed apart from its neighbours."""

    key: str
    runs: tuple[TextRun, ...]
    metrics: TextMetrics
    want: float
    x: float = 0.0


def _spread(labels: list[_Label], gap: float, low: float, high: float) -> None:
    """Centre each label over the x it wants, pushing neighbours apart, within [low, high]."""

    labels.sort(key=lambda item: item.want)
    for item in labels:
        item.x = item.want
    for _ in range(4):
        for before, after in itertools.pairwise(labels):
            need = (before.metrics.width + after.metrics.width) / 2.0 + gap
            if after.x - before.x < need:
                push = (need - (after.x - before.x)) / 2.0
                before.x -= push
                after.x += push
        for item in labels:
            item.x = min(
                max(item.x, low + item.metrics.width / 2.0), high - item.metrics.width / 2.0
            )
        # A last sweep left to right, so what the edges pushed back never overlaps.
        for before, after in itertools.pairwise(labels):
            need = (before.metrics.width + after.metrics.width) / 2.0 + gap
            after.x = max(after.x, before.x + need)


def _lanes(spans: list[tuple[float, float]], clearance: float) -> list[int]:
    ends: list[float] = []
    lanes = []
    for start, end in spans:
        for lane, last in enumerate(ends):
            if start > last + clearance:
                ends[lane] = end
                lanes.append(lane)
                break
        else:
            ends.append(end)
            lanes.append(len(ends) - 1)
    return lanes


def _scale(node: NodeSpec, length: int, u: float) -> float:
    value = node.property("scale")
    if value is not None:
        try:
            scale = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise _fail(node, "scale", f"scale {value!r} is not points a residue.") from None
        if scale <= 0:
            raise _fail(node, "scale", "scale is points a residue, more than 0.")
        return scale
    width = min(max(length * 0.3, 22.0 * u), 40.0 * u)
    return width / length


def protein_drawing(node: NodeSpec, style: LayoutStyle) -> Picture:
    measures = units(style)
    u, pen = measures.u, measures.pen
    length = protein_length(node)
    features = protein_features(node)
    tracks = protein_tracks(node)
    scale = _scale(node, length, u)
    shapes: list[Shape] = []
    words: list[Words] = []
    ports: list[tuple[str, Side, float]] = []

    pad = 0.25 * u
    gutter = 0.0
    names = [measures.measure(track.label) if track.label else None for track in tracks]
    if any(names):
        gutter = max(metrics.width for metrics in names if metrics) + 0.8 * u
    authored = node.property("gutter")
    if authored is not None:
        # A gutter for track names as wide as another protein's, so the two line up.
        gutter = max(gutter, float(authored))  # type: ignore[arg-type]
    left = pad + gutter + 0.3 * u
    # The stretch any track shows: a close view of a segment starts at its first residue.
    first = min(track.start for track in tracks)
    last = max(track.end for track in tracks)
    right = left + (last - first + 1) * scale
    secondary = protein_secondary(node)

    def x_of(residue: float) -> float:
        # Residue r fills [x_of(r), x_of(r + 1)] of the chain; its centre is x_of(r + 0.5).
        return left + (residue - first) * scale

    title = (
        measures.measure(node.label, weight=style.typography.title_weight) if node.label else None
    )
    y = pad + ((title.height + 0.5 * u) if title else 0.0)
    chain, box, tall = 0.55 * u, 1.9 * u, 2.5 * u
    first_base = None
    for number, (track, heading) in enumerate(zip(tracks, names, strict=True), 1):
        key = f"{node.id}.track{number}" if len(tracks) > 1 else node.id
        kept = [item for item in features if _kept(item, track)]
        sites = [item for item in kept if item.kind == "site"]
        spans = [item for item in kept if item.kind in _SPANS]
        bonds = [item for item in kept if item.kind == "disulfide"]

        def reach_at(residue: float, spans: list[Feature] = spans) -> float:
            """How far the chain's drawing reaches above (and below) it at ``residue``."""

            return max(
                [chain / 2.0]
                + [
                    (tall if item.kind == "transmembrane" else _height(item.kind, box)) / 2.0
                    for item in spans
                    if item.start - 0.5 <= residue <= item.end + 0.5
                ]
            )

        top_reach = max(
            [chain / 2.0]
            + [(tall if item.kind == "transmembrane" else box) / 2.0 for item in spans]
        )
        # Secondary structure: in the chain's place when nothing else is on it,
        # else in a strip of its own under the chain.
        lane = make_lane(node, secondary, track.pieces(), scale, measures)
        replacing = lane is not None and not spans
        if replacing:
            top_reach = max(top_reach, lane.up)

        # Sites: lollipops over the chain, names spread over them.
        site_labels = [
            _Label(
                f"{key}.site{index}",
                item.label,
                measures.measure(item.label, small=True),
                x_of(item.start + 0.5),
            )
            for index, item in enumerate(sites, 1)
            if item.label
        ]
        stem = 1.5 * u
        head = 0.32 * u
        labels_up = (
            (max(item.metrics.height for item in site_labels) + 0.9 * u) if site_labels else 0.0
        )
        # Heads closer than a head apart stand at two heights, so both show.
        levels: list[int] = []
        last_at: dict[int, float] = {}
        for item in sites:
            x = x_of(item.start + 0.5)
            level = 0
            while level in last_at and x - last_at[level] < 2.6 * head:
                level += 1
            last_at[level] = x
            levels.append(level)
        rise = 2.4 * head
        raised = max(levels, default=0) * rise
        above = top_reach + (stem + raised + head + labels_up if sites else 0.0)
        base = y + above
        first_base = first_base if first_base is not None else base

        # Under the chain: outside names of spans, then disulfide brackets.
        outside = []
        for item in spans:
            if not item.label:
                continue
            metrics = measures.measure(item.label, small=item.kind != "domain")
            width = (min(item.end, track.end) - max(item.start, track.start) + 1) * scale
            if item.kind == "transmembrane" or metrics.width + 0.6 * u > width:
                outside.append(
                    _Label(
                        f"{key}.feature{features.index(item) + 1}.label",
                        item.label,
                        measures.measure(item.label, small=True),
                        (x_of(max(item.start, track.start)) + x_of(min(item.end, track.end) + 1))
                        / 2.0,
                    )
                )
        below = top_reach
        if outside:
            below += 0.35 * u + max(item.metrics.height for item in outside)
        bond_top = (
            base
            + top_reach
            + (0.35 * u + max(i.metrics.height for i in outside) + 0.3 * u if outside else 0.3 * u)
        )
        bond_lanes = _lanes([(x_of(b.start), x_of(b.end)) for b in bonds], 0.4 * u)
        if bonds:
            below = bond_top - base + (max(bond_lanes) + 1) * 0.6 * u
        if lane is not None:
            if replacing and not bonds:
                below = max(below, lane.down)
                strip = base
            else:
                strip = base + below + 0.6 * u + lane.up
                below = strip - base + lane.down
            lane_shapes, lane_words = lane.draw(f"{key}.secondary", strip, x_of, measures)
            shapes.extend(lane_shapes)
            words.extend(lane_words)
        # The chain, piece by piece; a deletion is a hinge between two pieces.
        pieces = track.pieces()
        for index, (low, high) in enumerate(pieces, 1):
            x1, x2 = x_of(low), x_of(high + 1)
            if index > 1:
                previous = x_of(pieces[index - 2][1] + 1)
                middle = (previous + x1) / 2.0
                shapes.append(
                    Shape(
                        f"{key}.deletion{index - 1}",
                        path("M", previous, base, "L", middle, base + chain * 1.6, "L", x1, base),
                        "leader",
                        None,
                        pen,
                    )
                )
            if replacing and not bonds:
                continue
            # The chain shows between the boxes on it, not under them, so a
            # translucent wash (a sketch, a print) never shows it through a domain.
            shown = _uncovered(low, high, spans)
            for part, (start, end) in enumerate(shown, 1):
                name = f"{key}.chain{index}" if len(pieces) > 1 else f"{key}.chain"
                shapes.append(
                    Shape(
                        name if part == 1 else f"{name}.{part}",
                        _box(
                            x_of(start),
                            base - chain / 2.0,
                            x_of(end) - x_of(start),
                            chain,
                            chain * 0.3,
                        ),
                        "body",
                        None,
                        pen,
                    )
                )
        # Spans, the widest first, so a motif inside a domain is drawn over it.
        for item in sorted(spans, key=lambda item: -(item.end - item.start)):
            index = features.index(item) + 1
            tone = feature_tone(item)
            for low, high in _clip(item, track):
                x1, x2 = x_of(low), x_of(high + 1)
                if item.kind == "transmembrane":
                    height, paint = tall, "solid"
                else:
                    height, paint = _height(item.kind, box), "body"
                shapes.append(
                    Shape(
                        f"{key}.feature{index}",
                        _box(
                            x1, base - height / 2.0, x2 - x1, height, min(0.35 * u, (x2 - x1) / 3)
                        ),
                        paint,
                        tone,
                        pen,
                    )
                )
            if not item.label:
                continue
            metrics = measures.measure(item.label, small=item.kind != "domain")
            pieces_in = _clip(item, track)
            widest = max(pieces_in, key=lambda piece: piece[1] - piece[0])
            x1, x2 = x_of(widest[0]), x_of(widest[1] + 1)
            if item.kind != "transmembrane" and metrics.width + 0.6 * u <= x2 - x1:
                words.append(
                    Words(
                        f"{key}.feature{index}.label",
                        item.label,
                        metrics,
                        (x1 + x2) / 2.0,
                        base - metrics.height / 2.0 + metrics.baseline,
                        role="tone-ink" if tone else "ink",
                        tone=tone,
                        size=None if item.kind == "domain" else measures.small_size,
                    )
                )
            if item.id is not None and number == 1:
                ports.append((item.id, Side.NORTH, (x1 + x2) / 2.0))
        if outside:
            _spread(outside, 0.4 * u, left, right)
            top = base + top_reach + 0.35 * u
            for label in outside:
                words.append(
                    Words(
                        label.key,
                        label.runs,
                        label.metrics,
                        label.x,
                        top + label.metrics.baseline,
                        size=measures.small_size,
                        role="muted-ink",
                    )
                )
                if abs(label.x - label.want) > 0.2 * u:
                    shapes.append(
                        Shape(
                            f"{label.key}.leader",
                            path("M", label.want, base + top_reach, "L", label.x, top),
                            "leader",
                            None,
                            pen * 0.7,
                        )
                    )
        # Disulfides: brackets under the chain.
        for item, lane in zip(bonds, bond_lanes, strict=True):
            index = features.index(item) + 1
            x1, x2 = x_of(item.start + 0.5), x_of(item.end + 0.5)
            depth = bond_top + lane * 0.6 * u + 0.35 * u
            shapes.append(
                Shape(
                    f"{key}.feature{index}",
                    path(
                        "M",
                        x1,
                        base + reach_at(item.start),
                        "L",
                        x1,
                        depth,
                        "L",
                        x2,
                        depth,
                        "L",
                        x2,
                        base + reach_at(item.end),
                    ),
                    "line",
                    feature_tone(item),
                    pen,
                )
            )
        # Sites last: lollipops on top of the boxes.
        if sites:
            _spread(site_labels, 0.35 * u, left - 2.0 * u, right + 2.0 * u)
            placed = {label.key: label for label in site_labels}
            top_head = base - top_reach - stem - raised
            for index, item in enumerate(sites, 1):
                x = x_of(item.start + 0.5)
                head_y = base - top_reach - stem - levels[index - 1] * rise
                tone = feature_tone(item)
                name = f"{key}.site{index}"
                shapes.append(
                    Shape(
                        f"{name}.stem",
                        path("M", x, base - reach_at(item.start), "L", x, head_y + head),
                        "line",
                        None,
                        pen * 0.8,
                    )
                )
                shapes.append(
                    Shape(name, _circle(x, head_y, head), "solid" if tone else "hollow", tone, pen)
                )
                label = placed.get(name)
                if label is None:
                    continue
                bottom = top_head - head - 0.7 * u
                words.append(
                    Words(
                        name + ".label",
                        label.runs,
                        label.metrics,
                        label.x,
                        bottom - label.metrics.height + label.metrics.baseline,
                        size=measures.small_size,
                    )
                )
                shapes.append(
                    Shape(
                        f"{name}.leader",
                        path("M", x, head_y - head - 0.15 * u, "L", label.x, bottom - 0.1 * u),
                        "leader",
                        None,
                        pen * 0.7,
                    )
                )
                if item.id is not None and number == 1:
                    ports.append((item.id, Side.NORTH, x))
        if heading is not None:
            words.append(
                Words(
                    f"{key}.label",
                    track.label,
                    heading,
                    pad + gutter - 0.8 * u,
                    base - heading.height / 2.0 + heading.baseline,
                    anchor="end",
                )
            )
        y = base + below + 0.9 * u

    # The residue axis, under the last track.
    step = nice_step(last - first + 1)
    ticks = sorted({first, *range((first // step + 1) * step, last, step), last})
    if len(ticks) > 2 and last - ticks[-2] < step * 0.35:
        ticks.remove(ticks[-2])
    if len(ticks) > 2 and ticks[1] - first < step * 0.35:
        ticks.remove(ticks[1])
    axis = y - 0.3 * u
    shapes.append(
        Shape(
            f"{node.id}.axis",
            path("M", x_of(first), axis, "L", x_of(last + 1), axis),
            "tick",
            None,
            pen * 0.8,
        )
    )
    numbers = []
    for value in ticks:
        x = (
            x_of(value + 0.5)
            if value not in {first, last}
            else (x_of(first) if value == first else x_of(last + 1))
        )
        shapes.append(
            Shape(
                f"{node.id}.tick{value}",
                path("M", x, axis, "L", x, axis + 0.3 * u),
                "tick",
                None,
                pen * 0.8,
            )
        )
        runs = (TextRun(f"{value:,}"),)
        metrics = measures.measure(runs, small=True)
        numbers.append(
            Words(
                f"{node.id}.tick{value}.label",
                runs,
                metrics,
                x,
                axis + 0.45 * u + metrics.baseline,
                size=measures.small_size,
                role="muted-ink",
            )
        )
    words.extend(numbers)
    bottom = axis + 0.45 * u + max(item.metrics.height for item in numbers) + pad
    if title is not None:
        words.append(
            Words(
                f"{node.id}.label",
                node.label,
                title,
                left,
                pad + title.baseline,
                anchor="start",
                weight=style.typography.title_weight,
            )
        )
    width = right + pad + 0.3 * u
    # Words that spread past either end widen the drawing.
    reach_left = min([0.0] + [_left(item) for item in words])
    reach_right = max([width] + [_right(item) for item in words])
    shift = -reach_left + (pad if reach_left < 0 else 0.0)
    if shift:
        shapes = [_moved(shape, shift) for shape in shapes]
        words = [_shifted(item, shift) for item in words]
        ports = [(name, side, offset + shift) for name, side, offset in ports]
        reach_right += shift
    width = max(width + shift, reach_right + pad)
    base_at = (first_base or 0.0) / bottom
    placed = [
        PortSpec("input", Side.WEST, base_at),
        PortSpec("output", Side.EAST, base_at),
        *(PortSpec(name, side, min(max(offset / width, 0.0), 1.0)) for name, side, offset in ports),
    ]
    return Picture(Size(width, bottom), tuple(shapes), tuple(words), tuple(placed))


def _uncovered(low: int, high: int, spans: list[Feature]) -> list[tuple[float, float]]:
    """The stretches of residues ``low`` to ``high`` (as edges) that no span covers."""

    covered = sorted((item.start, item.end + 1) for item in spans)
    shown: list[tuple[float, float]] = []
    at, stop = float(low), float(high + 1)
    for start, end in covered:
        if end <= at or start >= stop:
            continue
        if start > at:
            shown.append((at, start))
        at = max(at, end)
    if at < stop:
        shown.append((at, stop))
    # Each stretch runs a little under its neighbours, so the chain meets them.
    tuck = 0.3
    return [(max(low, a - tuck), min(high + 1, b + tuck)) for a, b in shown]


def _height(kind: str, box: float) -> float:
    """How tall a span's box is: a domain's full height, a region or signal less."""

    return box * 0.62 if kind in {"region", "signal"} else box


def _kept(feature: Feature, track: Track) -> bool:
    return bool(_clip(feature, track))


def _clip(feature: Feature, track: Track) -> list[tuple[int, int]]:
    """The stretches of ``feature`` that ``track`` keeps."""

    kept = []
    for low, high in track.pieces():
        start, end = max(low, feature.start), min(high, feature.end)
        if start <= end:
            kept.append((start, end))
    if feature.kind == "disulfide":
        # A bond needs both its cysteines.
        return kept if track.keeps(feature.start) and track.keeps(feature.end) else []
    return kept


def _box(x: float, y: float, width: float, height: float, radius: float) -> str:
    r = max(0.0, min(radius, width / 2.0, height / 2.0))
    if r <= 0.01:
        return path(
            "M", x, y, "L", x + width, y, "L", x + width, y + height, "L", x, y + height, "Z"
        )
    return path(
        "M", x + r, y,
        "L", x + width - r, y,
        "A", r, r, 0, 0, 1, x + width, y + r,
        "L", x + width, y + height - r,
        "A", r, r, 0, 0, 1, x + width - r, y + height,
        "L", x + r, y + height,
        "A", r, r, 0, 0, 1, x, y + height - r,
        "L", x, y + r,
        "A", r, r, 0, 0, 1, x + r, y,
        "Z",
    )  # fmt: skip


def _circle(x: float, y: float, r: float) -> str:
    return path("M", x - r, y, "A", r, r, 0, 1, 1, x + r, y, "A", r, r, 0, 1, 1, x - r, y, "Z")


def _left(words: Words) -> float:
    if words.anchor == "start":
        return words.x
    if words.anchor == "end":
        return words.x - words.metrics.width
    return words.x - words.metrics.width / 2.0


def _right(words: Words) -> float:
    return _left(words) + words.metrics.width


def _moved(shape: Shape, dx: float) -> Shape:
    from flexo.render_drawn import _moved as move

    return Shape(shape.id, move(shape.d, dx, 0.0), shape.paint, shape.tone, shape.width)


def _shifted(words: Words, dx: float) -> Words:
    from dataclasses import replace

    return replace(words, x=words.x + dx)
