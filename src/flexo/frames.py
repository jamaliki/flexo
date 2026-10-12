"""Frames: a box round shapes wherever they are in the figure.

A group arranges what it holds, so it can only hold what stands together. A frame arranges
nothing: it names the shapes and groups it goes round (``around``, their ids), is drawn
round them where the layout put them -- taking no room of its own -- and lies behind them,
in front of them, or over them as a tint (``layer``).

    - id: stage
      kind: frame
      label: Stage 1
      properties: {around: "encoder, decoder", layer: behind}

It is written as a shape, so it has a shape's words and colours; the layout never sees it
(``split``), and it is placed once everything else has been (``place``).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace

from flexo.diagnostics import Diagnostic, Severity
from flexo.geometry import Rect
from flexo.ir.fitted import FittedFigure
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import FigureSpec, NodeSpec
from flexo.style import LayoutStyle, Palette

FRAME_KIND = "frame"
LAYERS = ("behind", "front", "over")
"""Where a frame lies: behind what it goes round, filled; in front, an outline alone; over
it, a tint the shapes show through."""
TINT = 0.22
"""How much of its colour a frame over its shapes lays on them."""


@dataclass(frozen=True, slots=True)
class PlacedFrame:
    spec: NodeSpec
    bounds: Rect
    label: TextMetrics | None
    layer: str
    inset: float
    """The room between the frame and what it goes round, which its title is set in from."""


def around(spec: NodeSpec) -> tuple[str, ...]:
    """The ids a frame goes round, as written: ``"encoder, decoder"``."""

    written = str(spec.property("around", "")).split(",")
    return tuple(part for part in (item.strip() for item in written) if part)


def layer_of(spec: NodeSpec) -> str:
    written = str(spec.property("layer", LAYERS[0])).strip().lower()
    return written if written in LAYERS else LAYERS[0]


def split(figure: FigureSpec) -> tuple[FigureSpec, tuple[NodeSpec, ...]]:
    """``figure`` as the layout sees it -- no frame among its shapes, in its groups or at
    the end of a line -- and its frames."""

    frames = tuple(node for node in figure.nodes if node.kind == FRAME_KIND)
    if not frames:
        return figure, ()
    ids = {frame.id for frame in frames}
    return (
        replace(
            figure,
            nodes=tuple(node for node in figure.nodes if node.id not in ids),
            groups=tuple(
                replace(group, children=tuple(c for c in group.children if c not in ids))
                for group in figure.groups
            ),
            edges=tuple(
                edge
                for edge in figure.edges
                if edge.source.node_id not in ids and edge.target.node_id not in ids
            ),
        ),
        frames,
    )


def place(
    frames: tuple[NodeSpec, ...], fitted: FittedFigure, style: LayoutStyle
) -> tuple[tuple[PlacedFrame, ...], tuple[Diagnostic, ...]]:
    """Each frame round what it names, where the layout put it; and what to say of a frame
    that names nothing there is."""

    if not frames:
        return (), ()
    from flexo.text import TextMeasurer, title_runs, title_typography

    boxes = {node.measured.spec.id: node.bounds for node in fitted.nodes}
    boxes |= {
        group.measured.spec.id: group.bounds
        for group in fitted.groups
        if group.measured.spec.id != fitted.measured.semantic.root
    }
    typography = style.typography
    measurer = TextMeasurer(title_typography(typography))
    inset = _inset(style)
    placed: list[PlacedFrame] = []
    said: list[Diagnostic] = []
    for spec in frames:
        named = around(spec)
        found = [boxes[item] for item in named if item in boxes]
        missing = [item for item in named if item not in boxes]
        if missing or not found:
            what = ", ".join(f"“{item}”" for item in missing) or "nothing"
            said.append(
                Diagnostic(
                    "frame.around.unknown",
                    f"The frame goes round {what}, which {'is' if len(missing) < 2 else 'are'} "
                    "not in the figure.",
                    Severity.WARNING,
                    entity_id=spec.id,
                    hint="Name the shapes or groups it goes round in its properties.around.",
                )
            )
        if not found:
            continue
        label = (
            measurer.measure(title_runs(spec.label, typography), weight=typography.title_weight)
            if spec.label
            else None
        )
        band = label.height + style.compact_gap.points if label is not None else 0.0
        left = min(box.x for box in found) - inset
        top = min(box.y for box in found) - inset - band
        right = max(box.right for box in found) + inset
        bottom = max(box.bottom for box in found) + inset
        if label is not None:
            right = max(right, left + label.width + 2.0 * inset)
        bounds = Rect(left, top, right - left, bottom - top)
        placed.append(PlacedFrame(spec, bounds, label, layer_of(spec), inset))
    return tuple(placed), tuple(said)


def room(frames: tuple[NodeSpec, ...], style: LayoutStyle) -> tuple[float, float]:
    """How far a frame stands out from what it goes round: at its sides and foot, and at its
    top, where its title is. (The page's margin is that much wider, so a frame round shapes
    at the page's edge is on the page.)"""

    if not frames:
        return 0.0, 0.0
    from flexo.text import TextMeasurer, title_runs, title_typography

    typography = style.typography
    measurer = TextMeasurer(title_typography(typography))
    inset = _inset(style)
    bands = [
        measurer.measure(title_runs(spec.label, typography), weight=typography.title_weight).height
        + style.compact_gap.points
        for spec in frames
        if spec.label
    ]
    return inset, inset + max(bands, default=0.0)


def _inset(style: LayoutStyle) -> float:
    return max(4.0, style.group_padding.points * 0.5)


def draw(
    parent: ET.Element,
    frame: PlacedFrame,
    style: LayoutStyle,
    palette: Palette,
    *,
    within: Rect | None = None,
    name: str = "",
) -> None:
    """One frame: its box and its title. ``within``: the part of it inside a container it
    shows through (``name``), drawn there again over the container's own fill -- only that
    part, and to an editor a part of the frame, not a shape of its own."""

    from flexo.components import node_tone
    from flexo.render import toned
    from flexo.render_common import paint_attributes, paint_override, render_runs
    from flexo.svg import element, inkscape_attr
    from flexo.text import title_typography

    spec, bounds = frame.spec, frame.bounds
    radius = (
        style.container_radius.points
        if style.container_radius is not None
        else style.corner_radius.points * 1.5
    )
    width = (
        style.container_stroke_width.points
        if style.container_stroke_width is not None
        else style.stroke_width.points
    )
    # In its own colour where it was given one; else as a container is.
    mine = toned(palette, spec, style)
    family = "block" if node_tone(spec, False) is not None else "container"
    filled = frame.layer != "front"
    attributes = paint_attributes(
        palette=mine,
        fill_role=f"{family}-fill" if filled else None,
        stroke_role=f"{family}-stroke",
        stroke_width=max(width, 0.75),
        fill=paint_override(spec, "fill") if filled else None,
        stroke=paint_override(spec, "stroke"),
    )
    if not filled:
        attributes["fill"] = "none"
    if frame.layer == "over":
        attributes["fill__opacity"] = TINT
    if within is None:
        group = element(
            parent,
            "g",
            id=spec.id,
            data__flexo__entity="component",
            data__flexo__kind=FRAME_KIND,
            data__flexo__role=spec.role,
            data__flexo__layer=frame.layer,
            **{inkscape_attr("label"): spec.text or spec.id},
        )
        part = spec.id
    else:
        part = f"{spec.id}.in.{name}"
        clip = element(parent, "clipPath", id=f"{part}.clip")
        element(clip, "rect", x=within.x, y=within.y, width=within.width, height=within.height)
        group = element(parent, "g", clip__path=f"url(#{part}.clip)", data__hit__for=spec.id)
    element(
        group,
        "rect",
        id=f"{part}.body",
        x=bounds.x,
        y=bounds.y,
        width=bounds.width,
        height=bounds.height,
        rx=radius,
        # (In front of its shapes, only its line is its own to press: they are under it.)
        pointer__events="stroke" if frame.layer != "behind" else None,
        **attributes,
    )
    if frame.label is not None:
        render_runs(
            group,
            f"{part}.label",
            frame.label,
            x=bounds.x + frame.inset,
            y=bounds.y + frame.inset + frame.label.baseline,
            typography=title_typography(style.typography),
            palette=mine,
            fill_role="ink",
            fill=paint_override(spec, "label"),
            weight=style.typography.title_weight,
        )
