"""Secondary structure along a protein: helices, strands, and loops in one strip.

A ``protein`` given its secondary structure draws a strip under its chain (or
in its place, when nothing else is on it), on the protein's own residue scale:

- a **helix** as a ribbon wound round its axis, seen side on: the near half of
  each turn in the helix's colour over the far half, darker -- or, with
  ``helix="cylinder"``, a rounded bar, or with ``helix="spiral"`` a line;
- a **strand** as a broad arrow pointing to the C terminus;
- a **turn** as a small arch in the loop; everything else as a plain line;
- each helix and strand numbered over it (alpha 1, 2, ... then beta 1, 2, ...), unless
  ``numbered=False`` or it carries a label of its own;
- the one-letter ``sequence`` under the strip, when the scale leaves room for
  a letter a residue -- a close view of a segment, as ESPript draws one.

The structure is written either as a DSSP string, one letter a residue (``H``,
``G``, ``I`` helix; ``E`` strand; ``T`` turn; ``B``, ``S``, ``C``, ``-``, ``P``
and spaces loop), starting at residue ``secondary_start``; or as features of
type ``helix``, ``strand``, or ``turn`` with a ``start`` and ``end``; or both.
Helices and strands take the tones ``helix`` and ``strand``, one colour each
across the figure.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from flexo.drawn import Name, Shape, Units, Words, path, spread
from flexo.ir.semantic import NodeSpec, TextRun

SECONDARY_KINDS = frozenset({"helix", "strand", "turn"})
HELIX_STYLES = ("ribbon", "cylinder", "spiral")
HELIX_TONE = "helix"
STRAND_TONE = "strand"

_DSSP = {
    "H": "helix", "G": "helix", "I": "helix",
    "E": "strand",
    "T": "turn",
    "B": "loop", "S": "loop", "C": "loop", "-": "loop", "P": "loop", " ": "loop", ".": "loop",
    "L": "loop",
}  # fmt: skip


@dataclass(frozen=True, slots=True)
class Element:
    kind: str
    start: int
    end: int
    label: tuple[TextRun, ...] = ()


def dssp_elements(text: str, first: int) -> list[Element] | str:
    """The helices, strands, and turns a DSSP string writes; or the letter it cannot read."""

    elements: list[Element] = []
    run_kind, run_start = "loop", first
    for offset, letter in enumerate(text + "."):
        kind = _DSSP.get(letter.upper())
        if kind is None:
            return letter
        residue = first + offset
        if kind != run_kind:
            if run_kind != "loop":
                elements.append(Element(run_kind, run_start, residue - 1))
            run_kind, run_start = kind, residue
    return elements


def numbered(elements: list[Element], number: bool) -> list[Element]:
    """``elements`` in order, each unlabelled helix and strand numbered in Greek."""

    ordered = sorted(elements, key=lambda item: item.start)
    if not number:
        return ordered
    counts = {"helix": 0, "strand": 0}
    result = []
    for item in ordered:
        if item.kind in counts:
            counts[item.kind] += 1
            if not item.label:
                symbol = (
                    "\N{GREEK SMALL LETTER ALPHA}"
                    if item.kind == "helix"
                    else "\N{GREEK SMALL LETTER BETA}"
                )
                item = Element(
                    item.kind, item.start, item.end, (TextRun(f"{symbol}{counts[item.kind]}"),)
                )
        result.append(item)
    return result


@dataclass(frozen=True, slots=True)
class Lane:
    """One track's strip, ready to draw at any height."""

    elements: tuple[Element, ...]
    pieces: tuple[tuple[int, int], ...]
    sequence: str
    sequence_start: int
    helix: str
    """How a helix is drawn: ``ribbon``, ``cylinder``, or ``spiral``."""
    up: float
    """How far the strip's drawing reaches above its centre line (names included)."""
    down: float
    """How far below it (the sequence included)."""
    names: bool
    letters: bool

    def draw(
        self,
        key: str,
        centre: float,
        x_of,
        measures: Units,
        *,
        loop: bool = True,
    ) -> tuple[list[Shape], list[Words]]:
        u, pen = measures.u, measures.pen
        shapes: list[Shape] = []
        words: list[Words] = []
        if loop:
            # The loop runs between the elements, not under them: a turn's arch,
            # a helix's coil, and a strand's arrow each carry the chain themselves.
            for index, (low, high) in enumerate(_between(self.pieces, self.elements), 1):
                shapes.append(
                    Shape(
                        f"{key}.loop{index}",
                        path("M", x_of(low), centre, "L", x_of(high), centre),
                        "line",
                        None,
                        pen * 1.3,
                    )
                )
        labels: list[Name] = []
        for number, item in enumerate(self.elements, 1):
            name = f"{key}.ss{number}"
            for low, high in _clipped(item, self.pieces):
                x1, x2 = x_of(low), x_of(high + 1)
                if item.kind == "helix":
                    shapes.extend(_helix(name, x1, x2, centre, u, pen, self.helix, x_of))
                elif item.kind == "strand":
                    shapes.append(_strand(name, x1, x2, centre, u, pen))
                else:
                    # A turn: a low arch in the loop, no louder than the loop itself.
                    rise = min(0.4 * u, (x2 - x1) * 0.5)
                    radius = (x2 - x1) / 2.0
                    shapes.append(
                        Shape(
                            name,
                            path("M", x1, centre, "A", radius, rise, 0, 0, 1, x2, centre),
                            "line",
                            None,
                            pen * 1.3,
                        )
                    )
            if self.names and item.label and item.kind != "turn":
                kept = _clipped(item, self.pieces)
                if kept:
                    widest = max(kept, key=lambda piece: piece[1] - piece[0])
                    metrics = measures.measure(item.label, small=True)
                    labels.append(
                        Name(
                            f"{name}.label",
                            item.label,
                            metrics,
                            (x_of(widest[0]) + x_of(widest[1] + 1)) / 2.0,
                        )
                    )
        if labels:
            spread(labels, 0.3 * u)
            height = max(item.metrics.height for item in labels)
            bottom = centre - _REACH * u - 0.3 * u
            for label in labels:
                words.append(
                    Words(
                        label.key,
                        label.runs,
                        label.metrics,
                        label.x,
                        bottom - height + label.metrics.baseline,
                        size=measures.small_size,
                        role="muted-ink",
                    )
                )
                if abs(label.x - label.want) > 0.2 * u:
                    shapes.append(
                        Shape(
                            f"{label.key}.leader",
                            path("M", label.x, bottom, "L", label.want, centre - _REACH * u * 0.8),
                            "leader",
                            None,
                            pen * 0.7,
                        )
                    )
        if self.letters:
            for low, high in self.pieces:
                for residue in range(low, high + 1):
                    index = residue - self.sequence_start
                    if not 0 <= index < len(self.sequence) or self.sequence[index] in "-. ":
                        continue  # a residue the sequence (or the model) leaves out
                    runs = (TextRun(self.sequence[index], code=True),)
                    metrics = measures.measure(runs, small=True)
                    words.append(
                        Words(
                            f"{key}.residue{residue}",
                            runs,
                            metrics,
                            x_of(residue + 0.5),
                            centre + _REACH * u + 0.35 * u + metrics.baseline,
                            size=measures.small_size,
                        )
                    )
        return shapes, words


_REACH = 0.62
"""Half the strip's height, in label sizes: a strand's arrowhead, a helix's swing."""


def make_lane(
    node: NodeSpec,
    elements: list[Element],
    pieces: list[tuple[int, int]],
    scale: float,
    measures: Units,
) -> Lane | None:
    kept = tuple(item for item in elements if _clipped(item, pieces))
    sequence = str(node.property("sequence") or "").replace(" ", "").replace("\n", "")
    if not kept and not sequence:
        return None
    u = measures.u
    start = int(node.property("sequence_start") or 1)  # type: ignore[arg-type]
    names = any(item.label for item in kept if item.kind != "turn")
    probe = measures.measure((TextRun("W", code=True),), small=True)
    letters = bool(sequence) and scale >= probe.width * 1.05
    label_height = probe.height if names else 0.0
    up = _REACH * u + (0.3 * u + label_height if names else 0.0)
    down = _REACH * u + (0.35 * u + probe.height if letters else 0.0)
    style = str(node.property("helix") or "ribbon").strip().lower()
    if style not in HELIX_STYLES:
        raise ValueError(f'helix "{style}" is not one of {", ".join(HELIX_STYLES)}')
    return Lane(kept, tuple(pieces), sequence, start, style, up, down, names, letters)


def _between(pieces, elements) -> list[tuple[float, float]]:
    """The stretches of ``pieces`` (as residue edges) that no element covers."""

    covered = sorted((item.start, item.end + 1) for item in elements)
    gaps: list[tuple[float, float]] = []
    for low, high in pieces:
        at, stop = float(low), float(high + 1)
        for start, end in covered:
            if end <= at or start >= stop:
                continue
            if start > at:
                gaps.append((at, start))
            at = max(at, end)
        if at < stop:
            gaps.append((at, stop))
    return gaps


def _clipped(item: Element, pieces) -> list[tuple[int, int]]:
    kept = []
    for low, high in pieces:
        start, end = max(low, item.start), min(high, item.end)
        if start <= end:
            kept.append((start, end))
    return kept


def _helix(name, x1, x2, centre, u, pen, style, x_of) -> list[Shape]:
    """A helix seen side on, a turn every 3.6 residues where there is room for one."""

    width = x2 - x1
    amplitude = _REACH * u * 0.9
    if style == "cylinder":
        half = 0.5 * u
        r = min(half, width / 2.0)
        outline = path(
            "M", x1 + r, centre - half, "L", x2 - r, centre - half,
            "A", r, half, 0, 0, 1, x2 - r, centre + half,
            "L", x1 + r, centre + half,
            "A", r, half, 0, 0, 1, x1 + r, centre - half, "Z",
        )  # fmt: skip
        return [Shape(name, outline, "body", HELIX_TONE, pen)]
    period = max(abs(x_of(4.6) - x_of(1.0)), 0.8 * u)
    if style == "spiral":
        turns = max(1, round(width / period))
        samples = turns * 16
        commands: list[object] = ["M", x1, centre]
        for index in range(1, samples + 1):
            t = index / samples
            y = centre - amplitude * math.sin(2 * math.pi * turns * t)
            commands += ["L", x1 + width * t, y]
        return [Shape(name, path(*commands), "line", HELIX_TONE, pen * 2.4)]
    # A ribbon: two edges, the second the first moved along the axis by the
    # ribbon's breadth. Where the edges rise the ribbon faces the reader (a
    # right-handed helix's near side runs up to the right); where they fall it
    # is the far side, drawn first and paler, so the near side crosses over it.
    # A cartoon's proportions: a turn every 3.6 residues where that keeps it
    # between one and a half and two times as long as the helix is wide.
    period = min(max(period, 3.0 * amplitude), 4.0 * amplitude)
    breadth = min(0.42 * period, 0.3 * width)
    run = width - breadth
    halves = max(1, round(2.0 * run / period))
    end = math.pi * halves

    def edge(phase: float, shift: float) -> tuple[float, float]:
        return x1 + shift + run * phase / end, centre - amplitude * math.sin(phase)

    cuts = [
        0.0,
        *(math.pi / 2 + k * math.pi for k in range(halves) if math.pi / 2 + k * math.pi < end),
        end,
    ]
    far: list[Shape] = []
    near: list[Shape] = []
    for number, (a, b) in enumerate(itertools.pairwise(cuts), 1):
        steps = 10
        phases = [a + (b - a) * k / steps for k in range(steps + 1)]
        front = [edge(phase, 0.0) for phase in phases]
        back = [edge(phase, breadth) for phase in reversed(phases)]
        commands = ["M", *front[0]]
        for point in front[1:] + back:
            commands += ["L", *point]
        commands.append("Z")
        facing = math.cos((a + b) / 2.0) > 0.0
        shape = Shape(
            f"{name}.{'near' if facing else 'far'}{number}",
            path(*commands),
            "solid" if facing else "body",
            HELIX_TONE,
            pen * 0.8,
        )
        (near if facing else far).append(shape)
    # The first piece carries the helix's own id, so it is found by name.
    pieces = far + near
    first = pieces[0]
    pieces[0] = Shape(name, first.d, first.paint, first.tone, first.width)
    return pieces


def _strand(name, x1, x2, centre, u, pen) -> Shape:
    width = x2 - x1
    body = 0.3 * u
    head_half = _REACH * u
    head = min(0.9 * u, width * 0.6)
    neck = x2 - head
    return Shape(
        name,
        path(
            "M",
            x1,
            centre - body,
            "L",
            neck,
            centre - body,
            "L",
            neck,
            centre - head_half,
            "L",
            x2,
            centre,
            "L",
            neck,
            centre + head_half,
            "L",
            neck,
            centre + body,
            "L",
            x1,
            centre + body,
            "Z",
        ),
        "body",
        STRAND_TONE,
        pen,
    )


__all__ = ["SECONDARY_KINDS", "Element", "Lane", "dssp_elements", "make_lane", "numbered"]
