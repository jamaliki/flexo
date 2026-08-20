"""Shared paint metadata, text setting, and component-body primitives."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from flexo.geometry import Rect
from flexo.ir.fitted import FittedNode
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import GroupSpec, NodeSpec
from flexo.style import PAINT_PROPERTY_PREFIX, LayoutStyle, Palette, TypographyStyle
from flexo.svg import element
from flexo.text import DEFAULT_RUN_WEIGHT, SHIFTED_SIZE


def paint_override(spec: NodeSpec | GroupSpec, part: str) -> str | None:
    """The author's literal colour for one part of ``spec``, if any.

    A component carries its parts as ``paint-<part>`` properties -- a node
    property holds a scalar and never a mapping -- while a group, which has no
    property bag, carries them as its own typed ``paint`` pairs. Both answer the
    same question, so both answer it here.
    """

    if isinstance(spec, GroupSpec):
        return dict(spec.paint).get(part)
    value = spec.property(f"{PAINT_PROPERTY_PREFIX}{part}")
    return None if value is None else str(value)


def paint_attributes(
    *,
    palette: Palette,
    fill_role: str | None = None,
    stroke_role: str | None = None,
    stroke_width: float | None = None,
    fill: str | None = None,
    stroke: str | None = None,
) -> dict[str, object]:
    """Paint one element by role, or literally where the author overrode it.

    An overridden part emits its colour and *no* ``data-flexo-fill`` or
    ``data-flexo-stroke``, so ``flexo retheme`` -- which rewrites paint by role
    -- leaves author paint exactly as written, the same convention preset vector
    cells follow.
    """

    values: dict[str, object] = {}
    if fill is not None:
        values["fill"] = fill
    elif fill_role:
        values["fill"] = palette.get(fill_role)
        values["data__flexo__fill"] = fill_role
    else:
        values["fill"] = "none"
    if stroke is not None:
        values["stroke"] = stroke
    elif stroke_role:
        values["stroke"] = palette.get(stroke_role)
        values["data__flexo__stroke"] = stroke_role
    if stroke_width is not None:
        values["stroke__width"] = stroke_width
    return values


_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
"""The attribute that stops SVG from throwing away a run's own leading space.

XML whitespace processing strips the leading and trailing whitespace of every
``tspan`` chunk, so ``(TextRun("QK"), TextRun(" module", italic=True))`` -- two
runs because their styles differ -- sets as ``QKmodule``: a space the author
wrote, measured into the width, and then not drawn. Marking *that* run
``xml:space="preserve"`` is the whole fix, and it goes on the run rather than on
the text object because the document is indented: preserving whitespace around
the tspans would turn the indentation itself into ink.
"""


def render_runs(
    parent: ET.Element,
    element_id: str,
    metrics: TextMetrics,
    *,
    x: float,
    y: float,
    typography: TypographyStyle,
    palette: Palette,
    fill_role: str,
    fill: str | None = None,
    anchor: str | None = None,
    weight: int | None = None,
) -> ET.Element | None:
    """One text object, one ``tspan`` per styled run -- wherever Flexo sets text.

    Component labels, connector captions, and group titles are the same object:
    measured runs set on a baseline. They differ only in where they sit and what
    the text object itself declares -- a title carries the style's
    ``title_weight``, a caption paints ``muted-ink`` -- so one helper draws all
    three, and a superscript survives into every one of them rather than into
    whichever call site remembered to loop over the runs.

    A run emits only what its author actually asked for: a weight other than the
    ``TextRun`` default, ``font-style`` where it is italic,
    ``baseline-shift`` with the reduced ``font-size`` where it is shifted, and
    ``xml:space="preserve"`` where its own text begins or ends in a space that
    XML would otherwise discard. Inheritance is the point rather than economy: a
    group title declares ``title_weight`` once on the text object, so a run
    spelling out ``font-weight="400"`` on top of it would silently unbold the
    title it belongs to -- and it is why ``TextMeasurer.measure`` takes the same
    weight, so the words are measured at the weight they inherit.
    """

    if not metrics.lines:
        return None
    size = typography.size.points
    text = element(
        parent,
        "text",
        id=element_id,
        x=x,
        y=y,
        text__anchor=anchor,
        font__family=typography.family,
        font__size=size,
        font__weight=weight,
        **paint_attributes(palette=palette, fill_role=fill_role, fill=fill),
    )
    for line_index, line in enumerate(metrics.lines):
        for run_index, run in enumerate(line.runs):
            shifted = run.baseline_shift != "normal"
            span = element(
                text,
                "tspan",
                x=x if run_index == 0 else None,
                dy=metrics.line_height if line_index > 0 and run_index == 0 else None,
                font__weight=run.weight if run.weight != DEFAULT_RUN_WEIGHT else None,
                font__style="italic" if run.italic else None,
                baseline__shift=run.baseline_shift if shifted else None,
                font__size=size * SHIFTED_SIZE if shifted else None,
            )
            span.text = run.text
            if run.text != run.text.strip():
                span.set(_XML_SPACE, "preserve")
    return text


SHADOW_LAYERS = 5
"""Nested rectangles one drop shadow is built from.

Enough that the steps between them fall below what a 300 dpi press can resolve
across a 2.5 pt band -- three were still visible as rings under magnification --
and few enough that a figure of shadowed modules stays a handful of rectangles
rather than a gradient mesh.
"""


def soft_shadow(
    parent: ET.Element,
    entity_id: str,
    bounds: Rect,
    radius: float,
    style: LayoutStyle,
    palette: Palette,
) -> ET.Element | None:
    """A soft drop shadow drawn as pure vector geometry, never as a filter.

    Flexo's figures leave as editable SVG and arrive as PDF through Inkscape,
    and Inkscape rasterizes any region it has to filter -- ``feDropShadow`` is
    not even a shape it knows, and ``feGaussianBlur`` turns its whole subtree
    into a 96 dpi bitmap. Either would put a raster patch behind every module in
    a vector figure, so the shadow is made of the only thing that survives the
    trip: rounded rectangles.

    Five of them, nested and equally faint, offset together *down and to the
    right*. Each reaches a fifth less far than the last, so one layer covers the
    outer band and five the ring against the box -- a stepped falloff that
    composites to ``style.shadow_opacity`` where they all overlap. Everything
    under the box itself is hidden by its own fill.

    The light comes from the top left, so the shadow shows along the bottom and
    right edges and nowhere else. That is geometry rather than clipping: with the
    stack offset by at least its own spread, the widest layer's top-left corner
    lands on the box's own top-left corner and every narrower layer starts
    further in, so no layer can put ink above the top edge or left of the left
    edge -- true at any corner radius, and still five plain rectangles.
    """

    spread = style.shadow_spread.points
    if spread <= 0.0 or style.shadow_opacity <= 0.0:
        return None
    # A shorter offset than the spread would let the outer layers ring the top
    # and left edges, which is the halo this shadow exists not to be.
    offset = max(style.shadow_offset.points, spread)
    # Alpha per layer, chosen so all of them together reach the authored opacity.
    layer_opacity = 1.0 - (1.0 - style.shadow_opacity) ** (1.0 / SHADOW_LAYERS)
    group = element(parent, "g", id=f"{entity_id}.shadow")
    for index in range(SHADOW_LAYERS):
        reach = spread * (SHADOW_LAYERS - index) / SHADOW_LAYERS
        element(
            group,
            "rect",
            x=bounds.x + offset - reach,
            y=bounds.y + offset - reach,
            width=bounds.width + 2.0 * reach,
            height=bounds.height + 2.0 * reach,
            rx=radius + reach,
            opacity=layer_opacity,
            **paint_attributes(palette=palette, fill_role="shadow"),
        )
    return group


def base_rect(
    parent: ET.Element,
    node: FittedNode,
    style: LayoutStyle,
    palette: Palette,
    *,
    fill_role: str = "block-fill",
    stroke_role: str = "block-stroke",
) -> ET.Element:
    bounds = node.bounds
    spec = node.measured.spec
    return element(
        parent,
        "rect",
        id=f"{spec.id}.body",
        x=bounds.x,
        y=bounds.y,
        width=bounds.width,
        height=bounds.height,
        rx=style.corner_radius.points,
        **paint_attributes(
            palette=palette,
            fill_role=fill_role,
            stroke_role=stroke_role,
            stroke_width=style.stroke_width.points,
            fill=paint_override(spec, "fill"),
            stroke=paint_override(spec, "stroke"),
        ),
    )
