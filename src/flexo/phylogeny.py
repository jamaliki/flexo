"""Trees: phylogenies and dendrograms, read from Newick and drawn to scale.

A ``tree`` component draws a tree written the way every tree program writes one,
Newick: ``((A:0.1,B:0.2)95:0.3,C:0.4);`` -- nested parentheses, a name after
each tip, an optional ``:length`` after anything, and an optional label (a
support value, say) after a closing parenthesis.

- ``layout="rectangular"`` (the default) runs the root on the left and the tips
  down the right, one a row; ``"circular"`` puts the root in the middle and the
  tips round a circle, named outside it.
- Branch lengths set how far each branch reaches (a phylogram) and a scale bar
  says how long a unit is; a tree without lengths, or ``lengths=False``, lines
  its tips up (a cladogram).
- ``clades`` colour a subtree -- the smallest one holding the ``tips`` named --
  and name it with a bracket beside its tips. A clade takes a colour by its
  name, like a gene or a domain.
- ``support=True`` writes the internal labels (support values) by their nodes.

Geometry only, like ``flexo.genetics``: ``flexo.render_drawn`` paints it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.drawn import Picture, Shape, Words, path, units
from flexo.geometry import Side, Size
from flexo.ir.semantic import NodeSpec, PortSpec, Record, TextRun
from flexo.markup import parse_label
from flexo.style import LayoutStyle


@dataclass(slots=True)
class Clade:
    """One node of a parsed tree."""

    name: str = ""
    length: float | None = None
    children: list[Clade] = field(default_factory=list)
    # Filled in by layout.
    x: float = 0.0
    y: float = 0.0
    depth: float = 0.0
    tone: str | None = None

    @property
    def tip(self) -> bool:
        return not self.children

    def tips(self) -> list[Clade]:
        if self.tip:
            return [self]
        return [leaf for child in self.children for leaf in child.tips()]

    def walk(self) -> list[Clade]:
        return [self, *(node for child in self.children for node in child.walk())]


class NewickError(ValueError):
    pass


_TOKEN = re.compile(r"\s*('(?:[^']|'')*'|[(),:;]|[^(),:;'\s][^(),:;']*)")


def parse_newick(text: str) -> Clade:
    """The tree ``text`` writes, in Newick. Comments in square brackets are dropped."""

    source = re.sub(r"\[[^\]]*\]", "", text).strip()
    if not source:
        raise NewickError("the tree is empty")
    if not source.endswith(";"):
        source += ";"
    tokens: list[str] = []
    position = 0
    while position < len(source):
        match = _TOKEN.match(source, position)
        if match is None or not match.group(1):
            if source[position:].strip() == "":
                break
            raise NewickError(f"cannot read {source[position : position + 12]!r}")
        tokens.append(match.group(1))
        position = match.end()
    index = 0

    def peek() -> str:
        return tokens[index] if index < len(tokens) else ""

    def take() -> str:
        nonlocal index
        token = peek()
        index += 1
        return token

    def name() -> str:
        token = peek()
        if token and token not in "(),:;":
            take()
            if token.startswith("'"):
                return token[1:-1].replace("''", "'")
            return token.strip().replace("_", " ")
        return ""

    def clade() -> Clade:
        node = Clade()
        if peek() == "(":
            take()
            node.children.append(clade())
            while peek() == ",":
                take()
                node.children.append(clade())
            if take() != ")":
                raise NewickError("a ( is never closed")
        node.name = name()
        if peek() == ":":
            take()
            value = take()
            try:
                node.length = float(value)
            except ValueError:
                raise NewickError(f"branch length {value!r} is not a number") from None
        return node

    root = clade()
    if peek() != ";":
        raise NewickError(f"unexpected {peek()!r} after the tree")
    if root.tip:
        raise NewickError("a tree needs at least two tips")
    return root


def _fail(node: NodeSpec, code: str, message: str, hint: str | None = None) -> FlexoError:
    return FlexoError(Diagnostic(f"tree.{code}", message, entity_id=node.id, hint=hint))


def _tree(node: NodeSpec) -> Clade:
    text = node.property("newick")
    if not isinstance(text, str) or not text.strip():
        raise _fail(
            node,
            "newick",
            "A tree needs its Newick text.",
            hint='Write newick: "((A:0.1,B:0.2):0.3,C:0.4);".',
        )
    try:
        return parse_newick(text)
    except NewickError as error:
        raise _fail(node, "newick", f"The tree's Newick does not read: {error}.") from None


@dataclass(frozen=True, slots=True)
class _CladeSpec:
    tips: tuple[str, ...]
    label: tuple[TextRun, ...]
    tone: str | None


def _clades(node: NodeSpec) -> tuple[_CladeSpec, ...]:
    value = node.property("clades")
    if value is None:
        return ()
    if not isinstance(value, tuple):
        raise _fail(node, "clades", '"clades" is a list of mappings.')
    clades = []
    for index, record in enumerate(value):
        assert isinstance(record, Record)
        extra = sorted(set(record.as_dict()) - {"tips", "label", "tone"})
        if extra:
            raise _fail(
                node,
                "clade.field",
                f"clade {index + 1}: {', '.join(extra)} is not a clade field.",
                hint="Fields are: label, tips, tone.",
            )
        tips = tuple(
            item.strip() for item in str(record.get("tips", "")).split(",") if item.strip()
        )
        if not tips:
            raise _fail(
                node, "clade.tips", f"clade {index + 1} names no tips.", hint='Write tips: "A, B".'
            )
        tone = record.get("tone")
        clades.append(
            _CladeSpec(
                tips, parse_label(str(record.get("label", ""))), None if tone is None else str(tone)
            )
        )
    return tuple(clades)


def _clade_tone(clade: _CladeSpec) -> str | None:
    if clade.tone is not None:
        text = clade.tone.strip()
        return None if text.lower() in {"neutral", "none", ""} else text
    text = "".join(run.text for run in clade.label)
    return text or ",".join(clade.tips)


def tree_tones(node: NodeSpec) -> tuple[str, ...]:
    return tuple(dict.fromkeys(tone for clade in _clades(node) if (tone := _clade_tone(clade))))


def _ancestor(root: Clade, names: tuple[str, ...], node: NodeSpec) -> Clade:
    """The smallest subtree holding every tip in ``names``."""

    tips = {tip.name: tip for tip in root.tips()}
    missing = [name for name in names if name not in tips]
    if missing:
        raise _fail(
            node,
            "clade.tips",
            f"no tip called {', '.join(repr(name) for name in missing)}.",
            hint=f"Tips are: {', '.join(sorted(tips))}.",
        )
    wanted = {id(tips[name]) for name in names}
    best = root
    for candidate in root.walk():
        held = {id(tip) for tip in candidate.tips()}
        if wanted <= held and len(held) < len({id(tip) for tip in best.tips()}):
            best = candidate
    return best


def _bool(node: NodeSpec, name: str, default: bool) -> bool:
    value = node.property(name)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "1", "on"}


def _nice(value: float) -> float:
    """A round length near a fifth of ``value``, for the scale bar."""

    if value <= 0:
        return 1.0
    target = value / 5.0
    power = 10 ** math.floor(math.log10(target))
    for step in (1, 2, 5, 10):
        if step * power >= target:
            return step * power
    return 10 * power


def _number(value: float) -> str:
    return f"{value:.4g}"


def tree_drawing(node: NodeSpec, style: LayoutStyle) -> Picture:
    measures = units(style)
    u, pen = measures.u, measures.pen
    root = _tree(node)
    layout = str(node.property("layout") or "rectangular").strip().lower()
    if layout not in {"rectangular", "circular"}:
        raise _fail(node, "layout", f'layout "{layout}" is neither rectangular nor circular.')
    use_lengths = _bool(node, "lengths", True) and any(
        clade.length is not None for clade in root.walk() if clade is not root
    )
    italic = _bool(node, "italic", False)
    show_support = _bool(node, "support", False)

    # Depth: along the branches from the root, by length or by count.
    def assign(clade: Clade, depth: float) -> None:
        clade.depth = depth
        for child in clade.children:
            step = (child.length or 0.0) if use_lengths else 1.0
            assign(child, depth + step)

    assign(root, 0.0)
    tips = root.tips()
    if not use_lengths:
        # A cladogram lines its tips up: each node as far out as its deepest path allows.
        def height(clade: Clade) -> int:
            return 0 if clade.tip else 1 + max(height(child) for child in clade.children)

        total = height(root)
        for clade in root.walk():
            clade.depth = total - height(clade)
    deepest = max(tip.depth for tip in tips) or 1.0

    # Tones: each clade's subtree, the smallest clade last so it wins.
    brackets = []
    for spec in _clades(node):
        ancestor = _ancestor(root, spec.tips, node)
        brackets.append((spec, ancestor))
    for spec, ancestor in sorted(brackets, key=lambda item: -len(item[1].tips())):
        tone = _clade_tone(spec)
        for clade in ancestor.walk():
            clade.tone = tone

    def label_runs(tip: Clade) -> tuple[TextRun, ...]:
        runs = parse_label(tip.name) if tip.name else ()
        return tuple(replace(run, italic=True) for run in runs) if italic else runs

    names = [label_runs(tip) for tip in tips]
    metrics = [measures.measure(runs) if runs else None for runs in names]
    widest = max((item.width for item in metrics if item), default=0.0)
    pad = 0.25 * u
    title = (
        measures.measure(node.label, weight=style.typography.title_weight) if node.label else None
    )
    top = pad + ((title.height + 0.5 * u) if title else 0.0)
    shapes: list[Shape] = []
    words: list[Words] = []
    lead = 0.8 * u

    if layout == "rectangular":
        row = max(1.35 * u, max((item.height for item in metrics if item), default=u) * 1.15)
        width = float(node.property("depth") or 0) or max(
            14.0 * u, min(34.0 * u, 4.0 * u * math.log2(len(tips) + 1) + 6 * u)
        )
        for index, tip in enumerate(tips):
            tip.y = top + row * (index + 0.5)

        def place(clade: Clade) -> None:
            clade.x = lead + clade.depth / deepest * width
            for child in clade.children:
                place(child)
            if clade.children:
                clade.y = (clade.children[0].y + clade.children[-1].y) / 2.0

        place(root)
        count = 0
        for clade in root.walk():
            if not clade.children:
                continue
            count += 1
            ys = [child.y for child in clade.children]
            shapes.append(
                Shape(
                    f"{node.id}.node{count}",
                    path("M", clade.x, min(ys), "L", clade.x, max(ys)),
                    "line",
                    clade.tone,
                    pen,
                )
            )
            for number, child in enumerate(clade.children, 1):
                shapes.append(
                    Shape(
                        f"{node.id}.node{count}.branch{number}",
                        path("M", clade.x, child.y, "L", child.x, child.y),
                        "line",
                        child.tone,
                        pen,
                    )
                )
            if show_support and clade is not root and clade.name:
                runs = (TextRun(clade.name),)
                small = measures.measure(runs, small=True)
                words.append(
                    Words(
                        f"{node.id}.node{count}.support",
                        runs,
                        small,
                        clade.x - 0.2 * u,
                        clade.y - 0.25 * u - small.height + small.baseline,
                        anchor="end",
                        size=measures.small_size,
                        role="muted-ink",
                    )
                )
        # A stub before the root, so the tree reads as rooted.
        shapes.append(
            Shape(
                f"{node.id}.root",
                path("M", root.x - lead * 0.6, root.y, "L", root.x, root.y),
                "line",
                root.tone,
                pen,
            )
        )
        for index, (tip, runs, item) in enumerate(zip(tips, names, metrics, strict=True), 1):
            if item is None:
                continue
            words.append(
                Words(
                    f"{node.id}.tip{index}",
                    runs,
                    item,
                    tip.x + 0.4 * u,
                    tip.y - item.height / 2.0 + item.baseline,
                    anchor="start",
                    role="tone-ink" if tip.tone else "ink",
                    tone=tip.tone,
                )
            )
        right = max(tip.x for tip in tips) + 0.4 * u + widest
        # Clade brackets beside their tips.
        bracket_x = right + 0.6 * u
        extent = right
        for number, (spec, ancestor) in enumerate(brackets, 1):
            held = ancestor.tips()
            y1, y2 = min(t.y for t in held) - row * 0.35, max(t.y for t in held) + row * 0.35
            tone = _clade_tone(spec)
            shapes.append(
                Shape(
                    f"{node.id}.clade{number}",
                    path("M", bracket_x, y1, "L", bracket_x, y2),
                    "line",
                    tone,
                    pen * 2.2,
                )
            )
            if spec.label:
                item = measures.measure(spec.label)
                words.append(
                    Words(
                        f"{node.id}.clade{number}.label",
                        spec.label,
                        item,
                        bracket_x + 0.5 * u,
                        (y1 + y2) / 2.0 - item.height / 2.0 + item.baseline,
                        anchor="start",
                        role="tone-ink" if tone else "ink",
                        tone=tone,
                    )
                )
                extent = max(extent, bracket_x + 0.5 * u + item.width)
        bottom = top + row * len(tips)
    else:
        gap = math.radians(18.0) if len(tips) > 2 else 0.0
        sweep = 2 * math.pi - gap
        radius = float(node.property("radius") or 0) or max(
            6.0 * u, len(tips) * 1.35 * u / sweep * 1.1
        )
        margin = widest + 0.9 * u
        centre = lead + margin + radius, top + margin + radius
        for index, tip in enumerate(tips):
            tip.y = -math.pi / 2 + gap / 2 + sweep * (index + 0.5) / len(tips)  # an angle

        def angle(clade: Clade) -> float:
            if clade.children:
                clade.y = (angle(clade.children[0]) + angle(clade.children[-1])) / 2.0
                for child in clade.children[1:-1]:
                    angle(child)
            return clade.y

        angle(root)

        def point(r: float, a: float) -> tuple[float, float]:
            return centre[0] + r * math.cos(a), centre[1] + r * math.sin(a)

        for clade in root.walk():
            clade.x = clade.depth / deepest * radius  # a radius
        count = 0
        for clade in root.walk():
            if not clade.children:
                continue
            count += 1
            first, last = clade.children[0].y, clade.children[-1].y
            r = clade.x
            if r > 1e-6:
                x1, y1 = point(r, first)
                x2, y2 = point(r, last)
                large = 1 if last - first > math.pi else 0
                shapes.append(
                    Shape(
                        f"{node.id}.node{count}",
                        path("M", x1, y1, "A", r, r, 0, large, 1, x2, y2),
                        "line",
                        clade.tone,
                        pen,
                    )
                )
            for number, child in enumerate(clade.children, 1):
                a = child.y
                x1, y1 = point(r, a)
                x2, y2 = point(child.x, a)
                shapes.append(
                    Shape(
                        f"{node.id}.node{count}.branch{number}",
                        path("M", x1, y1, "L", x2, y2),
                        "line",
                        child.tone,
                        pen,
                    )
                )
        for index, (tip, runs, item) in enumerate(zip(tips, names, metrics, strict=True), 1):
            if item is None:
                continue
            a = tip.y
            if tip.x < radius - 0.3 * u:
                # A short branch's name stays on the ring: a guide leads it there.
                x1, y1 = point(tip.x + 0.25 * u, a)
                x2, y2 = point(radius + 0.25 * u, a)
                shapes.append(
                    Shape(f"{node.id}.tip{index}.guide", path("M", x1, y1, "L", x2, y2), "guide")
                )
            x, y = point(radius + 0.5 * u, a)
            cos = math.cos(a)
            anchor = "start" if cos > 0.2 else "end" if cos < -0.2 else "middle"
            sin = math.sin(a)
            dy = item.height / 2.0 * sin
            words.append(
                Words(
                    f"{node.id}.tip{index}",
                    runs,
                    item,
                    x,
                    y + dy - item.height / 2.0 + item.baseline,
                    anchor=anchor,
                    role="tone-ink" if tip.tone else "ink",
                    tone=tip.tone,
                )
            )
        # A clade's name outside its tips, on an arc.
        for number, (spec, ancestor) in enumerate(brackets, 1):
            held = ancestor.tips()
            tone = _clade_tone(spec)
            a1, a2 = min(t.y for t in held), max(t.y for t in held)
            step = sweep / len(tips) * 0.4
            # Just past the clade's own names, however far each reaches out radially.
            reach = 0.0
            for tip in held:
                item = metrics[tips.index(tip)]
                if item is not None:
                    reach = max(
                        reach,
                        abs(math.cos(tip.y)) * item.width + abs(math.sin(tip.y)) * item.height,
                    )
            r = radius + 0.5 * u + reach + 0.6 * u
            x1, y1 = point(r, a1 - step)
            x2, y2 = point(r, a2 + step)
            shapes.append(
                Shape(
                    f"{node.id}.clade{number}",
                    path("M", x1, y1, "A", r, r, 0, 0, 1, x2, y2),
                    "line",
                    tone,
                    pen * 2.2,
                )
            )
            if spec.label:
                item = measures.measure(spec.label)
                middle = (a1 + a2) / 2.0
                x, y = point(r + 0.6 * u, middle)
                cos = math.cos(middle)
                anchor = "start" if cos > 0.2 else "end" if cos < -0.2 else "middle"
                words.append(
                    Words(
                        f"{node.id}.clade{number}.label",
                        spec.label,
                        item,
                        x,
                        y
                        + item.height / 2.0 * math.sin(middle)
                        - item.height / 2.0
                        + item.baseline,
                        anchor=anchor,
                        role="tone-ink" if tone else "ink",
                        tone=tone,
                    )
                )
        # Fit the frame to what is drawn: names reach out further on some sides.
        xs, ys = _reach(shapes, words, centre)
        dx, dy = lead - min(xs), top - min(ys)
        shapes = [_moved(shape, dx, dy) for shape in shapes]
        words = [replace(item, x=item.x + dx, y=item.y + dy) for item in words]
        extent = max(xs) + dx
        bottom = max(ys) + dy
        width = radius

    # The scale bar: a round length of branch, under the tree.
    if use_lengths and _bool(node, "scale_bar", True):
        span = _nice(deepest)
        length = span / deepest * width
        y = bottom + 0.6 * u
        shapes.append(
            Shape(f"{node.id}.scale", path("M", lead, y, "L", lead + length, y), "line", None, pen)
        )
        for end in (lead, lead + length):
            shapes.append(
                Shape(
                    f"{node.id}.scale.end{int(end > lead)}",
                    path("M", end, y - 0.2 * u, "L", end, y + 0.2 * u),
                    "line",
                    None,
                    pen,
                )
            )
        runs = (TextRun(_number(span)),)
        item = measures.measure(runs, small=True)
        words.append(
            Words(
                f"{node.id}.scale.label",
                runs,
                item,
                lead + length / 2.0,
                y + 0.35 * u + item.baseline,
                size=measures.small_size,
                role="muted-ink",
            )
        )
        bottom = y + 0.35 * u + item.height
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
        extent = max(extent, pad + title.width)
    size = Size(extent + pad, bottom + pad)
    middle = (root.y / size.height) if layout == "rectangular" else 0.5
    ports = (PortSpec("input", Side.WEST, middle), PortSpec("output", Side.EAST, 0.5))
    return Picture(size, tuple(shapes), tuple(words), ports)


def _reach(
    shapes: list[Shape], words: list[Words], centre: tuple[float, float]
) -> tuple[list[float], list[float]]:
    """Every x and y a circular tree's drawing reaches, its arcs (about ``centre``) and
    words included."""

    xs: list[float] = []
    ys: list[float] = []
    for shape in shapes:
        numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", shape.d)]
        points = [(numbers[i], numbers[i + 1]) for i in (0, len(numbers) - 2)]
        if " A " in f" {shape.d} ":
            (x1, y1), (x2, y2) = points
            r = math.hypot(x1 - centre[0], y1 - centre[1])
            a1 = math.atan2(y1 - centre[1], x1 - centre[0])
            a2 = math.atan2(y2 - centre[1], x2 - centre[0])
            while a2 < a1:
                a2 += 2 * math.pi
            points += [
                (
                    centre[0] + r * math.cos(a1 + (a2 - a1) * k / 24),
                    centre[1] + r * math.sin(a1 + (a2 - a1) * k / 24),
                )
                for k in range(25)
            ]
        xs += [x for x, _ in points]
        ys += [y for _, y in points]
    for item in words:
        left = {"start": item.x, "end": item.x - item.metrics.width}.get(
            item.anchor, item.x - item.metrics.width / 2.0
        )
        xs += [left, left + item.metrics.width]
        ys += [item.y - item.metrics.baseline, item.y - item.metrics.baseline + item.metrics.height]
    return xs, ys


def _moved(shape: Shape, dx: float, dy: float) -> Shape:
    from flexo.render_drawn import _moved as move

    return replace(shape, d=move(shape.d, dx, dy))
