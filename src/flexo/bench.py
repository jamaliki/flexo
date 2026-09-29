"""The bench in a methods figure: a well plate by condition, and a protocol's timeline.

- ``wellplate`` draws a plate of 6 to 384 wells, rows lettered and columns
  numbered, with each group of ``wells`` ("A1-A12", "B1:D6", "E3") filled in the
  colour of its condition and a legend under the plate. A condition takes a colour
  by its name, so "Control" is one colour on every plate of a figure.
- ``timeline`` draws a protocol along a time axis: ``events`` at one time (a
  dot on the axis, named over it -- transfect, induce, harvest) and
  ``spans`` over a stretch of time (a bar under the axis -- a drug, a
  starvation), stacked where they overlap.

Geometry only, like ``flexo.genetics``: ``flexo.render_drawn`` paints it.
"""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.drawn import Picture, Shape, Words, path, units
from flexo.geometry import Side, Size
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import NodeSpec, PortSpec, Record, TextRun
from flexo.markup import parse_label
from flexo.style import LayoutStyle

PLATES = {6: (2, 3), 12: (3, 4), 24: (4, 6), 48: (6, 8), 96: (8, 12), 384: (16, 24)}
"""Rows and columns of every plate format."""


def _fail(node: NodeSpec, code: str, message: str, hint: str | None = None) -> FlexoError:
    return FlexoError(Diagnostic(f"{node.kind}.{code}", message, entity_id=node.id, hint=hint))


def _records(node: NodeSpec, name: str) -> tuple[Record, ...]:
    value = node.property(name)
    if value is None:
        return ()
    if not isinstance(value, tuple):
        raise _fail(node, "records", f'"{name}" is a list of mappings.')
    return value


def _check_fields(node: NodeSpec, record: Record, where: str, known: set[str]) -> None:
    extra = sorted(set(record.as_dict()) - known)
    if extra:
        raise _fail(
            node,
            "field",
            f"{where}: {', '.join(extra)} is not a field here.",
            hint=f"Fields are: {', '.join(sorted(known))}.",
        )


def _tone(label: tuple[TextRun, ...], tone: object) -> str | None:
    if tone is not None:
        text = str(tone).strip()
        return None if text.lower() in {"neutral", "none", ""} else text
    text = "".join(run.text for run in label)
    return text or None


# -- well plates ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Group:
    label: tuple[TextRun, ...]
    wells: frozenset[tuple[int, int]]
    tone: str | None


def _plate_format(node: NodeSpec) -> tuple[int, int]:
    value = node.property("wells")
    try:
        count = int(value if value is not None else 96)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        count = -1
    if count not in PLATES:
        raise _fail(
            node,
            "wells",
            f"{value!r} is not a plate format.",
            hint=f"Plates have {', '.join(str(size) for size in PLATES)} wells.",
        )
    return PLATES[count]


_WELL = re.compile(r"^\s*([A-Za-z])\s*0*(\d+)\s*$")


def _well(node: NodeSpec, text: str, rows: int, columns: int, where: str) -> tuple[int, int]:
    match = _WELL.match(text)
    if match is None:
        raise _fail(node, "well", f'{where}: "{text.strip()}" is not a well.', hint="Write A1.")
    row = ord(match.group(1).upper()) - ord("A")
    column = int(match.group(2)) - 1
    if not (0 <= row < rows and 0 <= column < columns):
        last = f"{chr(ord('A') + rows - 1)}{columns}"
        raise _fail(node, "well", f"{where}: {text.strip()} is not on this plate (A1 to {last}).")
    return row, column


def parse_wells(node: NodeSpec, text: str, rows: int, columns: int, where: str) -> frozenset:
    """The wells ``text`` names: ``A1``, a block ``B1-D6`` (or ``B1:D6``), a row ``C``
    or rows ``A-D``, a column ``7`` or columns ``1-3``; several separated by commas."""

    wells: set[tuple[int, int]] = set()
    for piece in text.split(","):
        piece = piece.strip()
        if not piece:
            continue
        if re.fullmatch(r"[A-Za-z]", piece):
            row = _well(node, f"{piece}1", rows, columns, where)[0]
            wells.update((row, column) for column in range(columns))
            continue
        if re.fullmatch(r"\d+", piece):
            column = _well(node, f"A{piece}", rows, columns, where)[1]
            wells.update((row, column) for row in range(rows))
            continue
        ends = re.split(r"\s*[-:]\s*", piece)
        if len(ends) == 2 and all(re.fullmatch(r"[A-Za-z]", end) for end in ends):
            first, last = (_well(node, f"{end}1", rows, columns, where)[0] for end in ends)
            wells.update(
                (row, column)
                for row in range(min(first, last), max(first, last) + 1)
                for column in range(columns)
            )
            continue
        if len(ends) == 2 and all(re.fullmatch(r"\d+", end) for end in ends):
            first, last = (_well(node, f"A{end}", rows, columns, where)[1] for end in ends)
            wells.update(
                (row, column)
                for row in range(rows)
                for column in range(min(first, last), max(first, last) + 1)
            )
            continue
        if len(ends) == 1:
            wells.add(_well(node, piece, rows, columns, where))
            continue
        if len(ends) != 2:
            raise _fail(node, "well", f'{where}: "{piece}" is not a block of wells.')
        (r1, c1), (r2, c2) = (_well(node, end, rows, columns, where) for end in ends)
        wells.update(
            (row, column)
            for row in range(min(r1, r2), max(r1, r2) + 1)
            for column in range(min(c1, c2), max(c1, c2) + 1)
        )
    return frozenset(wells)


def plate_groups(node: NodeSpec) -> tuple[_Group, ...]:
    rows, columns = _plate_format(node)
    groups = []
    for index, record in enumerate(_records(node, "groups")):
        where = f"group {index + 1}"
        _check_fields(node, record, where, {"wells", "label", "tone"})
        label = parse_label(str(record.get("label", "")))
        wells = parse_wells(node, str(record.get("wells", "")), rows, columns, where)
        if not wells:
            raise _fail(node, "well", f"{where} names no wells.", hint='Write wells: "A1-A12".')
        groups.append(_Group(label, wells, _tone(label, record.get("tone"))))
    return tuple(groups)


def wellplate_drawing(node: NodeSpec, style: LayoutStyle) -> Picture:
    measures = units(style)
    u, pen = measures.u, measures.pen
    rows, columns = _plate_format(node)
    groups = plate_groups(node)
    pitch = min(1.6 * u, 30.0 * u / columns)
    radius = pitch * 0.38
    small = measures.small_size
    pad = 0.25 * u
    title = (
        measures.measure(node.label, weight=style.typography.title_weight) if node.label else None
    )
    top = pad + ((title.height + 0.4 * u) if title else 0.0)
    shapes: list[Shape] = []
    words: list[Words] = []
    letters = [chr(ord("A") + row) for row in range(rows)]
    letter_width = max(measures.measure((TextRun(item),), small=True).width for item in letters)
    rim = 0.7 * pitch
    left = pad + letter_width + 0.5 * u
    head = measures.measure((TextRun(str(columns)),), small=True).height
    plate_top = top + head + 0.3 * u
    width = columns * pitch + 2 * rim
    height = rows * pitch + 2 * rim
    cut = rim * 1.1
    # The plate: a rounded frame with its A1 corner cut, as a real plate's is.
    r = 0.4 * rim
    x0, y0, x1, y1 = left, plate_top, left + width, plate_top + height
    shapes.append(
        Shape(
            f"{node.id}.plate",
            path(
                "M",
                x0 + cut,
                y0,
                "L",
                x1 - r,
                y0,
                "A",
                r,
                r,
                0,
                0,
                1,
                x1,
                y0 + r,
                "L",
                x1,
                y1 - r,
                "A",
                r,
                r,
                0,
                0,
                1,
                x1 - r,
                y1,
                "L",
                x0 + r,
                y1,
                "A",
                r,
                r,
                0,
                0,
                1,
                x0,
                y1 - r,
                "L",
                x0,
                y0 + cut,
                "Z",
            ),
            "body",
            None,
            pen,
        )
    )
    owner: dict[tuple[int, int], int] = {}
    for index, group in enumerate(groups):
        for well in group.wells:
            owner[well] = index
    for row, column in itertools.product(range(rows), range(columns)):
        cx = x0 + rim + (column + 0.5) * pitch
        cy = y0 + rim + (row + 0.5) * pitch
        index = owner.get((row, column))
        tone = groups[index].tone if index is not None else None
        paint = "hollow" if index is None else "body" if tone else "solid"
        shapes.append(
            Shape(
                f"{node.id}.{letters[row]}{column + 1}",
                _circle(cx, cy, radius),
                paint,
                tone,
                pen * 0.7,
            )
        )
    for column in range(columns):
        runs = (TextRun(str(column + 1)),)
        metrics = measures.measure(runs, small=True)
        words.append(
            Words(
                f"{node.id}.column{column + 1}",
                runs,
                metrics,
                x0 + rim + (column + 0.5) * pitch,
                top + metrics.baseline,
                size=small,
                role="muted-ink",
            )
        )
    for row, letter in enumerate(letters):
        runs = (TextRun(letter),)
        metrics = measures.measure(runs, small=True)
        words.append(
            Words(
                f"{node.id}.row{letter}",
                runs,
                metrics,
                left - 0.4 * u,
                y0 + rim + (row + 0.5) * pitch - metrics.height / 2.0 + metrics.baseline,
                anchor="end",
                size=small,
                role="muted-ink",
            )
        )
    # The legend: one swatch and name a condition, in rows as wide as the plate.
    y = y1 + 0.7 * u
    x = left
    line = 0.0
    right = x1
    for index, group in enumerate(groups):
        if not group.label:
            continue
        metrics = measures.measure(group.label)
        entry = 2 * radius + 0.4 * u + metrics.width
        if x > left and x + entry > x1:
            x, y = left, y + line + 0.35 * u
            line = 0.0
        line = max(line, metrics.height, 2 * radius)
        middle = y + max(metrics.height, 2 * radius) / 2.0
        shapes.append(
            Shape(
                f"{node.id}.legend{index + 1}",
                _circle(x + radius, middle, radius),
                "body" if group.tone else "solid",
                group.tone,
                pen * 0.7,
            )
        )
        words.append(
            Words(
                f"{node.id}.legend{index + 1}.label",
                group.label,
                metrics,
                x + 2 * radius + 0.3 * u,
                middle - metrics.height / 2.0 + metrics.baseline,
                anchor="start",
            )
        )
        right = max(right, x + entry)
        x += entry + 0.9 * u
    bottom = y + line + pad if line else y1 + pad
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
        right = max(right, left + title.width)
    size = Size(right + pad, bottom)
    middle = (y0 + y1) / 2.0 / size.height
    return Picture(
        size,
        tuple(shapes),
        tuple(words),
        (PortSpec("input", Side.WEST, middle), PortSpec("output", Side.EAST, middle)),
    )


def _circle(x: float, y: float, r: float) -> str:
    return path("M", x - r, y, "A", r, r, 0, 1, 1, x + r, y, "A", r, r, 0, 1, 1, x - r, y, "Z")


# -- timelines --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Moment:
    label: tuple[TextRun, ...]
    start: float
    end: float
    tone: str | None
    id: str | None = None

    @property
    def span(self) -> bool:
        return self.end > self.start


def _number(node: NodeSpec, value: object, where: str) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise _fail(node, "time", f"{where}: {value!r} is not a time.") from None


def timeline_moments(node: NodeSpec) -> tuple[tuple[_Moment, ...], tuple[_Moment, ...]]:
    events = []
    for index, record in enumerate(_records(node, "events")):
        where = f"event {index + 1}"
        _check_fields(node, record, where, {"at", "label", "tone", "id"})
        if record.get("at") is None:
            raise _fail(node, "time", f"{where} needs the time it happens (at:).")
        at = _number(node, record.get("at"), where)
        label = parse_label(str(record.get("label", "")))
        identifier = record.get("id")
        events.append(
            _Moment(
                label,
                at,
                at,
                _tone((), record.get("tone")),
                None if identifier is None else str(identifier),
            )
        )
    spans = []
    for index, record in enumerate(_records(node, "spans")):
        where = f"span {index + 1}"
        _check_fields(node, record, where, {"start", "end", "label", "tone"})
        if record.get("start") is None or record.get("end") is None:
            raise _fail(node, "time", f"{where} needs a start and an end.")
        start = _number(node, record.get("start"), where)
        end = _number(node, record.get("end"), where)
        if end <= start:
            raise _fail(node, "time", f"{where} ends ({end:g}) before it starts ({start:g}).")
        label = parse_label(str(record.get("label", "")))
        spans.append(_Moment(label, start, end, _tone(label, record.get("tone"))))
    if not events and not spans:
        raise _fail(
            node,
            "empty",
            "A timeline needs events or spans.",
            hint="Write events: [{at: 0, label: Transfect}, {at: 2, label: Induce}].",
        )
    return tuple(events), tuple(spans)


def _tick_step(extent: float) -> float:
    if extent <= 0:
        return 1.0
    raw = extent / 8.0
    power = 10 ** math.floor(math.log10(raw))
    for step in (1, 2, 5, 10):
        if step * power >= raw:
            return step * power
    return 10 * power


_SYMBOLS = frozenset({"s", "sec", "min", "h", "hr", "hrs", "ms", "µs", "ns", "d", "wk", "y", "yr"})
"""Units written after the number (2 h); a word is written before it (Day 2)."""


def _time_text(value: float, unit: str) -> str:
    number = f"{value:g}"
    if not unit:
        return number
    if unit.lower() in _SYMBOLS:
        return f"{number} {unit}"
    return f"{unit[:1].upper()}{unit[1:]} {number}"


@dataclass(slots=True)
class _Name:
    key: str
    runs: tuple[TextRun, ...]
    metrics: TextMetrics
    want: float
    x: float = 0.0


def _spread(names: list[_Name], gap: float) -> None:
    names.sort(key=lambda item: item.want)
    for item in names:
        item.x = item.want
    for _ in range(6):
        for before, after in itertools.pairwise(names):
            need = (before.metrics.width + after.metrics.width) / 2.0 + gap
            if after.x - before.x < need:
                push = (need - (after.x - before.x)) / 2.0
                before.x -= push
                after.x += push


def timeline_drawing(node: NodeSpec, style: LayoutStyle) -> Picture:
    measures = units(style)
    u, pen = measures.u, measures.pen
    events, spans = timeline_moments(node)
    unit = str(node.property("unit") or "").strip()
    times = [moment.start for moment in (*events, *spans)] + [m.end for m in spans]
    low, high = min(times), max(times)
    if high <= low:
        high = low + 1.0
    extent = high - low
    step = _tick_step(extent)
    first = math.floor(low / step) * step
    last = math.ceil(high / step) * step
    width = float(node.property("length") or 0) or max(
        24.0 * u, min(40.0 * u, 3.2 * u * (last - first) / step)
    )
    pad = 0.25 * u
    title = (
        measures.measure(node.label, weight=style.typography.title_weight) if node.label else None
    )
    top = pad + ((title.height + 0.4 * u) if title else 0.0)
    shapes: list[Shape] = []
    words: list[Words] = []

    # Event names over the axis, spread apart, each led down to its moment.
    names = [
        _Name(f"{node.id}.event{index}", item.label, measures.measure(item.label), 0.0)
        for index, item in enumerate(events, 1)
        if item.label
    ]
    left = pad + max([0.0] + [item.metrics.width / 2.0 for item in names]) + 0.3 * u

    def x_of(time: float) -> float:
        return left + (time - first) / (last - first) * width

    by_key = {}
    for index, item in enumerate(events, 1):
        by_key[f"{node.id}.event{index}"] = item
    for name in names:
        name.want = x_of(by_key[name.key].start)
    _spread(names, 0.6 * u)
    name_height = max((item.metrics.height for item in names), default=0.0)
    axis = top + (name_height + 1.2 * u if names else 0.4 * u)
    dot = 0.32 * u
    for name in names:
        moment = by_key[name.key]
        words.append(
            Words(
                f"{name.key}.label",
                name.runs,
                name.metrics,
                name.x,
                top + name.metrics.baseline,
                role="tone-ink" if moment.tone else "ink",
                tone=moment.tone,
            )
        )
        at = x_of(moment.start)
        shapes.append(
            Shape(
                f"{name.key}.leader",
                path("M", name.x, top + name_height + 0.2 * u, "L", at, axis - dot - 0.15 * u),
                "leader",
                None,
                pen * 0.7,
            )
        )
    # The axis, its ticks and times.
    shapes.append(
        Shape(
            f"{node.id}.axis",
            path("M", x_of(first), axis, "L", x_of(last), axis),
            "backbone",
            None,
            pen * 1.3,
        )
    )
    tick_values = []
    value = first
    while value <= last + step * 1e-6:
        tick_values.append(round(value, 10))
        value += step
    below_axis = axis + 0.3 * u
    for value in tick_values:
        x = x_of(value)
        shapes.append(
            Shape(
                f"{node.id}.tick{tick_values.index(value) + 1}",
                path("M", x, axis, "L", x, axis + 0.3 * u),
                "tick",
                None,
                pen * 0.8,
            )
        )
        runs = (TextRun(_time_text(value, unit)),)
        metrics = measures.measure(runs, small=True)
        words.append(
            Words(
                f"{node.id}.tick{tick_values.index(value) + 1}.label",
                runs,
                metrics,
                x,
                axis + 0.45 * u + metrics.baseline,
                size=measures.small_size,
                role="muted-ink",
            )
        )
        below_axis = max(below_axis, axis + 0.45 * u + metrics.height)
    ports: list[tuple[str, float]] = []
    for index, item in enumerate(events, 1):
        x = x_of(item.start)
        shapes.append(
            Shape(
                f"{node.id}.event{index}",
                _circle(x, axis, dot),
                "body" if item.tone else "solid",
                item.tone,
                pen,
            )
        )
        if item.id is not None:
            ports.append((item.id, x))
    # Spans under the times, in lanes where they overlap.
    lane_height = 1.5 * u
    lanes: list[float] = []
    y0 = below_axis + 0.5 * u
    bottom = below_axis
    for index, item in enumerate(sorted(spans, key=lambda moment: moment.start), 1):
        x1, x2 = x_of(item.start), x_of(item.end)
        metrics = measures.measure(item.label, small=True) if item.label else None
        inside = metrics is not None and metrics.width + 0.6 * u <= x2 - x1
        reach = x2 if inside or metrics is None else x2 + 0.3 * u + metrics.width
        lane = next((i for i, end in enumerate(lanes) if x1 >= end + 0.3 * u), None)
        if lane is None:
            lanes.append(reach)
            lane = len(lanes) - 1
        else:
            lanes[lane] = reach
        y = y0 + lane * lane_height
        bar = 1.05 * u
        shapes.append(
            Shape(
                f"{node.id}.span{index}",
                _bar(x1, y, x2 - x1, bar),
                "body" if item.tone else "solid",
                item.tone,
                pen,
            )
        )
        if metrics is not None:
            words.append(
                Words(
                    f"{node.id}.span{index}.label",
                    item.label,
                    metrics,
                    (x1 + x2) / 2.0 if inside else x2 + 0.3 * u,
                    y + bar / 2.0 - metrics.height / 2.0 + metrics.baseline,
                    anchor="middle" if inside else "start",
                    size=measures.small_size,
                    role="tone-ink" if inside and item.tone else "ink",
                    tone=item.tone if inside else None,
                )
            )
        bottom = max(bottom, y + bar)
    right = max([x_of(last) + 0.3 * u] + lanes + [n.x + n.metrics.width / 2.0 for n in names])
    if title is not None:
        words.append(
            Words(
                f"{node.id}.label",
                node.label,
                title,
                pad,
                pad + title.baseline,
                anchor="start",
                weight=style.typography.title_weight,
            )
        )
        right = max(right, pad + title.width)
    size = Size(right + pad + 0.4 * u, bottom + pad)
    placed = [
        PortSpec("input", Side.WEST, axis / size.height),
        PortSpec("output", Side.EAST, axis / size.height),
        *(
            PortSpec(name, Side.NORTH, min(max(x / size.width, 0.0), 1.0))
            for name, x in ports
        ),
    ]
    return Picture(size, tuple(shapes), tuple(words), tuple(placed))


def _bar(x: float, y: float, width: float, height: float) -> str:
    r = min(height * 0.3, width / 2.0)
    return path(
        "M", x + r, y, "L", x + width - r, y, "A", r, r, 0, 0, 1, x + width, y + r,
        "L", x + width, y + height - r, "A", r, r, 0, 0, 1, x + width - r, y + height,
        "L", x + r, y + height, "A", r, r, 0, 0, 1, x, y + height - r,
        "L", x, y + r, "A", r, r, 0, 0, 1, x + r, y, "Z",
    )  # fmt: skip


# -- shared -----------------------------------------------------------------------------


def bench_drawing(node: NodeSpec, style: LayoutStyle) -> Picture:
    if node.kind == "wellplate":
        return wellplate_drawing(node, style)
    return timeline_drawing(node, style)


def bench_tones(node: NodeSpec) -> tuple[str, ...]:
    if node.kind == "wellplate":
        tones = [group.tone for group in plate_groups(node)]
    else:
        events, spans = timeline_moments(node)
        tones = [moment.tone for moment in (*events, *spans)]
    return tuple(dict.fromkeys(tone for tone in tones if tone))
