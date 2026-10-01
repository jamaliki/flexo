"""A grid of cells: a plate map, a heatmap, a board, a number square.

``cells`` draws a rectangle of cells from a ``grid`` written as text, one row per
line and one cell per word::

    K . K . K
    . Y R B .
    K R . B K

Each word is a symbol. The ``key`` says what a symbol is -- a ``color`` (one of
the figure's tones by name, or an exact ``#hex``), a small ``mark`` written in the
cell, a ``label`` for the legend -- and a symbol the key does not name takes a
tone by its own name, so "Control" is one colour on every grid of a figure. A
number is a value instead: the cell is shaded along ``ramp`` (two colours, low to
high) over ``range`` (the data's own, unless given), and ``values`` writes it in
the cell. ``.`` (or ``-``) leaves a cell empty, the paper showing.

The cells are painted a little inside their squares (``gap``, a fraction of a
cell) with rounded corners (``corner``); ``lines`` rules the grid (``ink``,
``muted``, or a ``#hex``); ``row_labels`` and ``column_labels`` number
(``numbers``), letter (``letters``), or name (a comma-separated list) the rows
and columns, on the ``row_side`` and ``column_side`` asked for.

Geometry only, like ``flexo.bench``: ``flexo.render_drawn`` paints it, and a
sketched theme paints it by hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from flexo.colour import is_dark, mix
from flexo.diagnostics import Diagnostic, FlexoError
from flexo.drawn import Picture, Shape, Words, path, units
from flexo.geometry import Side, Size
from flexo.ir.semantic import NodeSpec, PortSpec, Record, TextRun
from flexo.markup import parse_label
from flexo.style import LayoutStyle
from flexo.text import TextMeasurer
from flexo.units import pt

EMPTY = frozenset({".", "-", "_"})
"""Symbols that leave a cell empty."""

KEY_FIELDS = frozenset({"symbol", "color", "mark", "label"})

DEFAULT_RAMP = ("#f4f0e6", "#1f3a5f")
"""A value grid's shading, low to high, when the author gives none."""

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")


def _fail(node: NodeSpec, code: str, message: str, hint: str | None = None) -> FlexoError:
    return FlexoError(Diagnostic(f"cells.{code}", message, entity_id=node.id, hint=hint))


@dataclass(frozen=True, slots=True)
class Entry:
    """What one symbol means."""

    symbol: str
    color: str | None
    """An exact ``#hex``, or None when the cell takes a tone."""
    tone: str | None
    mark: tuple[TextRun, ...]
    label: tuple[TextRun, ...]
    empty: bool = False


def cell_grid(node: NodeSpec) -> tuple[tuple[str, ...], ...]:
    """The grid's rows of symbols, every row as long as the first."""

    text = node.property("grid")
    if not isinstance(text, str) or not text.strip():
        raise _fail(
            node,
            "grid",
            "A cell grid needs a grid: one row per line, one cell per word.",
            hint='For example grid: "K . K\\n. Y .\\nK . K".',
        )
    rows = tuple(
        tuple(word for word in re.split(r"[\s,]+", line.strip()) if word)
        for line in text.strip().splitlines()
        if line.strip()
    )
    width = len(rows[0])
    for index, row in enumerate(rows, 1):
        if len(row) != width:
            raise _fail(
                node,
                "grid",
                f"Row {index} has {len(row)} cells, and row 1 has {width}.",
                hint="Every row names every cell; write . for an empty one.",
            )
    return rows


def _value(symbol: str) -> float | None:
    try:
        return float(symbol)
    except ValueError:
        return None


def cell_key(node: NodeSpec) -> dict[str, Entry]:
    """Every symbol the grid uses, and what it means."""

    written: dict[str, Record] = {}
    value = node.property("key")
    if value is not None:
        if not isinstance(value, tuple):
            raise _fail(node, "key", '"key" is a list of mappings, each with a "symbol".')
        for index, record in enumerate(value, 1):
            extra = sorted(set(record.as_dict()) - KEY_FIELDS)
            if extra:
                raise _fail(
                    node,
                    "key",
                    f"key[{index}]: {', '.join(extra)} is not a field here.",
                    hint=f"Fields are: {', '.join(sorted(KEY_FIELDS))}.",
                )
            symbol = record.get("symbol")
            if symbol is None or not str(symbol).strip():
                raise _fail(node, "key", f"key[{index}] needs a symbol: the word it colours.")
            written[str(symbol).strip()] = record
    entries: dict[str, Entry] = {}
    for row in cell_grid(node):
        for symbol in row:
            if symbol in entries or symbol in EMPTY or _value(symbol) is not None:
                continue
            entries[symbol] = _entry(node, symbol, written.get(symbol))
    for symbol, record in written.items():  # keyed symbols the grid does not use yet
        entries.setdefault(symbol, _entry(node, symbol, record))
    return entries


def _entry(node: NodeSpec, symbol: str, record: Record | None) -> Entry:
    get = record.get if record is not None else (lambda _name, default=None: default)
    label = parse_label(str(get("label") or ""))
    mark = parse_label(str(get("mark") or ""))
    colour = get("color")
    if colour is not None:
        text = str(colour).strip()
        if text.lower() in {"none", "paper", "empty"}:
            return Entry(symbol, None, None, mark, label, empty=True)
        if _HEX.fullmatch(text):
            return Entry(symbol, text, None, mark, label)
        if not text:
            raise _fail(node, "key", f'The color of "{symbol}" is empty.')
        return Entry(symbol, None, text, mark, label)
    name = "".join(run.text for run in label) or symbol
    return Entry(symbol, None, name, mark, label)


def _ramp(node: NodeSpec) -> tuple[str, str]:
    value = node.property("ramp")
    if value is None:
        return DEFAULT_RAMP
    ends = [item.strip() for item in str(value).split(",")]
    if len(ends) != 2 or not all(_HEX.fullmatch(item) for item in ends):
        raise _fail(
            node, "ramp", f'ramp is two #hex colours, low then high, not "{value}".',
            hint='For example ramp: "#f7fbff, #08306b".',
        )
    return ends[0], ends[1]


def _range(node: NodeSpec, values: list[float]) -> tuple[float, float]:
    value = node.property("range")
    if value is None:
        return (min(values), max(values)) if values else (0.0, 1.0)
    try:
        low, high = (float(item) for item in str(value).split(","))
    except ValueError:
        raise _fail(node, "range", f'range is "low, high", not "{value}".') from None
    return low, high


def _labels(node: NodeSpec, name: str, count: int) -> tuple[str, ...] | None:
    value = node.property(name)
    if value is None or str(value).strip().lower() in {"", "none", "false"}:
        return None
    text = str(value).strip()
    if text.lower() == "numbers":
        return tuple(str(index + 1) for index in range(count))
    if text.lower() == "letters":
        return tuple(_letters(index) for index in range(count))
    names = tuple(item.strip() for item in text.split(","))
    if len(names) != count:
        raise _fail(
            node, name, f"{name} names {len(names)}, and the grid has {count}.",
            hint="Give one name each, separated by commas, or numbers or letters.",
        )
    return names


def _letters(index: int) -> str:
    text = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        text = chr(ord("A") + rest) + text
    return text


def _fraction(node: NodeSpec, name: str, default: float, high: float) -> float:
    value = node.property(name)
    if value is None:
        return default
    number = float(value)
    if not 0.0 <= number <= high:
        raise _fail(node, name, f"{name} is from 0 to {high}, not {value}.")
    return number


def _rounded(x: float, y: float, width: float, height: float, r: float) -> str:
    r = min(r, width / 2.0, height / 2.0)
    if r <= 0.01:
        return path(
            "M", x, y, "L", x + width, y, "L", x + width, y + height, "L", x, y + height, "Z"
        )  # fmt: skip
    return path(
        "M", x + r, y,
        "L", x + width - r, y, "A", r, r, 0, 0, 1, x + width, y + r,
        "L", x + width, y + height - r, "A", r, r, 0, 0, 1, x + width - r, y + height,
        "L", x + r, y + height, "A", r, r, 0, 0, 1, x, y + height - r,
        "L", x, y + r, "A", r, r, 0, 0, 1, x + r, y,
        "Z",
    )  # fmt: skip


def _measurer(style: LayoutStyle, size: float) -> TextMeasurer:
    return TextMeasurer(replace(style.typography, size=pt(size), minimum_size=pt(min(size, 5.0))))


def _format(value: float) -> str:
    return f"{value:g}" if value != 0 else "0"  # never "-0"


def cells_drawing(node: NodeSpec, style: LayoutStyle) -> Picture:
    measures = units(style)
    u, pen = measures.u, measures.pen
    rows = cell_grid(node)
    count_rows, count_columns = len(rows), len(rows[0])
    entries = cell_key(node)
    size = float(node.property("cell") or 1.4 * u)
    if size <= 0:
        raise _fail(node, "cell", f"cell is a size in points, above 0, not {size}.")
    gap = _fraction(node, "gap", 0.08, 0.45)
    corner = _fraction(node, "corner", 0.12, 0.5)
    lines = str(node.property("lines") or "none").strip()
    row_names = _labels(node, "row_labels", count_rows)
    column_names = _labels(node, "column_labels", count_columns)
    row_side = str(node.property("row_side") or "left").strip().lower()
    column_side = str(node.property("column_side") or "top").strip().lower()
    if row_side not in {"left", "right"}:
        raise _fail(node, "row_side", f'row_side is "left" or "right", not "{row_side}".')
    if column_side not in {"top", "bottom"}:
        raise _fail(node, "column_side", f'column_side is "top" or "bottom", not "{column_side}".')
    numbers = [value for row in rows for symbol in row if (value := _value(symbol)) is not None]
    low_colour, high_colour = _ramp(node)
    low, high = _range(node, numbers)
    show_values = bool(node.property("values"))

    small = measures.small_size
    small_measure = measures.small
    pad = 0.25 * u
    title = (
        measures.measure(node.label, weight=style.typography.title_weight) if node.label else None
    )
    top = pad + ((title.height + 0.4 * u) if title else 0.0)
    row_width = (
        max(small_measure.measure((TextRun(name),)).width for name in row_names)
        if row_names
        else 0.0
    )
    head = small_measure.measure((TextRun("0"),)).height if column_names else 0.0
    left = pad + (row_width + 0.4 * u if row_names and row_side == "left" else 0.0)
    grid_top = top + (head + 0.3 * u if column_names and column_side == "top" else 0.0)
    x1, y1 = left + count_columns * size, grid_top + count_rows * size

    shapes: list[Shape] = []
    words: list[Words] = []
    if lines.lower() not in {"none", "false", ""}:
        colour = lines if _HEX.fullmatch(lines) else None
        paint = "tick" if lines.lower() == "muted" else "line"
        ruled = [path("M", left, grid_top + i * size, "L", x1, grid_top + i * size)
                 for i in range(count_rows + 1)]  # fmt: skip
        ruled += [path("M", left + i * size, grid_top, "L", left + i * size, y1)
                  for i in range(count_columns + 1)]  # fmt: skip
        shapes.append(Shape(f"{node.id}.lines", " ".join(ruled), paint, None, pen * 0.6, colour))
    inset = size * gap
    side = size - 2 * inset
    mark_size = side * 0.62
    mark_measure = _measurer(style, mark_size)
    for r, row in enumerate(rows):
        for c, symbol in enumerate(row):
            if symbol in EMPTY:
                continue
            x, y = left + c * size + inset, grid_top + r * size + inset
            identifier = f"{node.id}.r{r + 1}c{c + 1}"
            value = _value(symbol)
            outline = _rounded(x, y, side, side, side * corner)
            if value is not None:
                share = 0.0 if high == low else min(1.0, max(0.0, (value - low) / (high - low)))
                colour = mix(low_colour, high_colour, share)
                shapes.append(Shape(identifier, outline, "solid", None, pen * 0.6, colour))
                if show_values:
                    runs = (TextRun(_format(value)),)
                    metrics = small_measure.measure(runs)
                    words.append(
                        Words(f"{identifier}.value", runs, metrics, x + side / 2.0,
                              y + side / 2.0 - metrics.height / 2.0 + metrics.baseline,
                              size=small, role="canvas" if is_dark(colour) else "ink")
                    )  # fmt: skip
                continue
            entry = entries[symbol]
            if entry.empty:
                continue
            shapes.append(Shape(identifier, outline, "solid", entry.tone, pen * 0.6, entry.color))
            if entry.mark:
                metrics = mark_measure.measure(entry.mark)
                dark = is_dark(entry.color) if entry.color else True
                words.append(
                    Words(f"{identifier}.mark", entry.mark, metrics, x + side / 2.0,
                          y + side / 2.0 - metrics.height / 2.0 + metrics.baseline,
                          size=mark_size, role="canvas" if dark else "ink")
                )  # fmt: skip
    if row_names:
        for r, name in enumerate(row_names):
            runs = (TextRun(name),)
            metrics = small_measure.measure(runs)
            at_left = row_side == "left"
            words.append(
                Words(f"{node.id}.row{r + 1}", runs, metrics,
                      left - 0.4 * u if at_left else x1 + 0.4 * u,
                      grid_top + (r + 0.5) * size - metrics.height / 2.0 + metrics.baseline,
                      anchor="end" if at_left else "start", size=small, role="muted-ink")
            )  # fmt: skip
    right = x1 + (0.4 * u + row_width if row_names and row_side == "right" else 0.0)
    bottom = y1
    if column_names:
        for c, name in enumerate(column_names):
            runs = (TextRun(name),)
            metrics = small_measure.measure(runs)
            baseline = (top + metrics.baseline if column_side == "top"
                        else y1 + 0.3 * u + metrics.baseline)  # fmt: skip
            words.append(
                Words(f"{node.id}.column{c + 1}", runs, metrics, left + (c + 0.5) * size,
                      baseline, size=small, role="muted-ink")
            )  # fmt: skip
        if column_side == "bottom":
            bottom = y1 + 0.3 * u + head
    # The legend: a swatch and a name for every symbol the key names, in rows.
    legend = [entry for entry in entries.values() if entry.label and not entry.empty]
    if legend and node.property("legend") is not False:
        y = bottom + 0.7 * u
        x = left
        line = 0.0
        swatch = min(side, 1.1 * u)
        for index, entry in enumerate(legend, 1):
            metrics = measures.measure(entry.label)
            entry_width = swatch + 0.4 * u + metrics.width
            if x > left and x + entry_width > max(x1, left + 20 * u):
                x, y = left, y + line + 0.35 * u
                line = 0.0
            line = max(line, metrics.height, swatch)
            middle = y + max(metrics.height, swatch) / 2.0
            shapes.append(
                Shape(f"{node.id}.legend{index}",
                      _rounded(x, middle - swatch / 2.0, swatch, swatch, swatch * corner),
                      "solid", entry.tone, pen * 0.6, entry.color)
            )  # fmt: skip
            words.append(
                Words(f"{node.id}.legend{index}.label", entry.label, metrics,
                      x + swatch + 0.3 * u, middle - metrics.height / 2.0 + metrics.baseline,
                      anchor="start")
            )  # fmt: skip
            right = max(right, x + entry_width)
            x += entry_width + 0.9 * u
        bottom = y + line
    if title is not None:
        words.append(
            Words(f"{node.id}.label", node.label, title, left, pad + title.baseline,
                  anchor="start", weight=style.typography.title_weight)
        )  # fmt: skip
        right = max(right, left + title.width)
    total = Size(right + pad, bottom + pad)
    middle = (grid_top + y1) / 2.0 / total.height
    return Picture(
        total,
        tuple(shapes),
        tuple(words),
        (PortSpec("input", Side.WEST, middle), PortSpec("output", Side.EAST, middle)),
    )


def cells_tones(node: NodeSpec) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            entry.tone for entry in cell_key(node).values() if entry.tone and not entry.empty
        )
    )
