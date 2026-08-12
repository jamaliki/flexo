"""Kind-specific component rendering using shallow native SVG primitives."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from flexo.ir.fitted import FittedNode
from flexo.render_common import base_rect, paint_attributes
from flexo.render_scientific import render_scientific
from flexo.style import LayoutStyle, Palette
from flexo.svg import element, number


def render_node(
    parent: ET.Element,
    node: FittedNode,
    style: LayoutStyle,
    palette: Palette,
) -> ET.Element:
    spec = node.measured.spec
    group = element(
        parent,
        "g",
        id=spec.id,
        data__flexo__entity="component",
        data__flexo__kind=spec.kind,
        data__flexo__role=spec.role,
    )
    if spec.kind not in {"label", "spacer"}:
        _render_kind(group, node, style, palette)
    _render_label(group, node, style, palette)
    return group


def _render_kind(
    parent: ET.Element,
    node: FittedNode,
    style: LayoutStyle,
    palette: Palette,
) -> None:
    kind = node.measured.spec.kind
    if kind == "feature-strip":
        _feature_strip(parent, node, style, palette)
    elif kind == "sequence":
        _sequence(parent, node, style, palette)
    elif kind == "tensor":
        _tensor(parent, node, style, palette)
    elif kind == "junction":
        _junction(parent, node, style, palette)
    elif kind == "concat":
        _concat(parent, node, style, palette)
    elif kind == "channels":
        _channels(parent, node, style, palette)
    elif kind in {"matrix", "attention", "graph", "inset"}:
        render_scientific(parent, node, style, palette)
    else:
        _block(parent, node, style, palette)


def _block(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    kind = node.measured.spec.kind
    fill_role = "warm-fill" if kind in {"prediction", "loss"} else "block-fill"
    stroke_role = "warm-stroke" if kind in {"prediction", "loss"} else "block-stroke"
    base_rect(parent, node, style, palette, fill_role=fill_role, stroke_role=stroke_role)
    if kind in {"mlp", "cnn", "add-norm"}:
        motif = element(parent, "g", id=f"{node.measured.spec.id}.motif")
        bounds = node.bounds
        y = bounds.bottom - 6.0
        if kind == "mlp":
            for index, radius in enumerate((1.2, 1.6, 1.2)):
                element(
                    motif,
                    "circle",
                    cx=bounds.center.x + (index - 1) * 5.0,
                    cy=y,
                    r=radius,
                    **paint_attributes(palette=palette, fill_role="block-stroke"),
                )
        elif kind == "cnn":
            element(
                motif,
                "path",
                d=f"M {number(bounds.center.x - 9)} {number(y)} l 4 -3 l 4 3 l 4 -3 l 4 3",
                **paint_attributes(
                    palette=palette,
                    stroke_role="block-stroke",
                    stroke_width=style.stroke_width.points,
                ),
            )
        else:
            element(
                motif,
                "path",
                d=(
                    f"M {number(bounds.center.x - 5)} {number(y)} h 10 "
                    f"M {number(bounds.center.x)} {number(y - 5)} v 10"
                ),
                stroke__linecap="round",
                **paint_attributes(
                    palette=palette,
                    stroke_role="block-stroke",
                    stroke_width=style.stroke_width.points,
                ),
            )


def _feature_strip(
    parent: ET.Element,
    node: FittedNode,
    style: LayoutStyle,
    palette: Palette,
) -> None:
    base_rect(parent, node, style, palette, fill_role="accent-fill", stroke_role="accent-stroke")
    bounds = node.bounds
    cells = int(node.measured.spec.property("cells", 6))
    motif = element(parent, "g", id=f"{node.measured.spec.id}.cells")
    left = bounds.x + 6.0
    width = bounds.width - 12.0
    cell_width = width / cells
    y = bounds.bottom - 7.0
    for index in range(cells):
        element(
            motif,
            "rect",
            x=left + index * cell_width,
            y=y - 2.0,
            width=max(1.0, cell_width - 1.2),
            height=4.0,
            rx=0.7,
            opacity=0.35 + 0.55 * (index + 1) / cells,
            **paint_attributes(palette=palette, fill_role="accent-stroke"),
        )


def _sequence(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    base_rect(
        parent,
        node,
        style,
        palette,
        fill_role="container-fill",
        stroke_role="container-stroke",
    )
    bounds = node.bounds
    motif = element(parent, "g", id=f"{node.measured.spec.id}.tokens")
    count = int(node.measured.spec.property("tokens", 7))
    spacing = min(7.0, (bounds.width - 14.0) / max(1, count - 1))
    x0 = bounds.center.x - spacing * (count - 1) / 2.0
    for index in range(count):
        element(
            motif,
            "circle",
            cx=x0 + index * spacing,
            cy=bounds.bottom - 6.5,
            r=1.6,
            opacity=0.45 + 0.5 * index / max(1, count - 1),
            **paint_attributes(palette=palette, fill_role="block-stroke"),
        )


def _tensor(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    bounds = node.bounds
    for index in reversed(range(3)):
        inset = index * 2.0
        element(
            parent,
            "rect",
            id=f"{node.measured.spec.id}.slice.{index}",
            x=bounds.x + inset,
            y=bounds.y + 2.0 * (2 - index),
            width=bounds.width - 4.0,
            height=bounds.height - 4.0,
            rx=style.corner_radius.points,
            opacity=0.45 + 0.2 * index,
            **paint_attributes(
                palette=palette,
                fill_role="block-fill",
                stroke_role="block-stroke",
                stroke_width=style.stroke_width.points,
            ),
        )


def _junction(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    element(
        parent,
        "circle",
        id=f"{node.measured.spec.id}.body",
        cx=node.bounds.center.x,
        cy=node.bounds.center.y,
        r=min(node.bounds.width, node.bounds.height) / 2.0,
        **paint_attributes(
            palette=palette,
            fill_role="connector",
            stroke_role="canvas",
            stroke_width=style.stroke_width.points,
        ),
    )


def _concat(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    base_rect(
        parent,
        node,
        style,
        palette,
        fill_role="container-fill",
        stroke_role="block-stroke",
    )
    bounds = node.bounds
    motif = element(parent, "g", id=f"{node.measured.spec.id}.motif")
    for index, width in enumerate((14.0, 10.0, 6.0)):
        element(
            motif,
            "rect",
            x=bounds.center.x - width / 2.0,
            y=bounds.bottom - 11.0 + index * 3.0,
            width=width,
            height=1.5,
            rx=0.75,
            opacity=0.45 + index * 0.2,
            **paint_attributes(palette=palette, fill_role="block-stroke"),
        )


def _channels(parent: ET.Element, node: FittedNode, style: LayoutStyle, palette: Palette) -> None:
    bounds = node.bounds
    labels = str(node.measured.spec.property("labels", "K")).split(",")
    outputs = node.ports[1:]
    input_port = node.port("input")
    split_x = bounds.left + 4.0
    label_x = bounds.left + 10.0
    bar_left = bounds.right - 5.0
    motif = element(parent, "g", id=f"{node.measured.spec.id}.channels")
    path_commands = [
        f"M {number(bounds.left)} {number(input_port.position.y)} H {number(split_x)}"
    ]
    port_ys = (input_port.position.y, *(output.position.y for output in outputs))
    if min(port_ys) != max(port_ys):
        path_commands.append(
            f"M {number(split_x)} {number(min(port_ys))} V {number(max(port_ys))}"
        )
    for output in outputs:
        path_commands.append(
            f"M {number(split_x)} {number(output.position.y)} H {number(label_x - 2.0)}"
        )
    element(
        motif,
        "path",
        d=" ".join(path_commands),
        stroke__linecap="square",
        stroke__linejoin="miter",
        **paint_attributes(
            palette=palette,
            stroke_role="connector",
            stroke_width=style.connector_width.points,
        ),
    )
    for index, (label, output) in enumerate(zip(labels, outputs, strict=True)):
        text = element(
            motif,
            "text",
            id=f"{node.measured.spec.id}.channel.{index + 1}.label",
            x=label_x,
            y=output.position.y + style.typography.size.points * 0.32,
            font__family=style.typography.family,
            font__size=style.typography.minimum_size.points,
            font__weight=style.typography.label_weight,
            fill=palette.get("ink"),
            data__flexo__fill="ink",
        )
        text.text = label
        element(
            motif,
            "rect",
            id=f"{node.measured.spec.id}.channel.{index + 1}.bar",
            x=bar_left,
            y=output.position.y - 3.0,
            width=5.0,
            height=6.0,
            **paint_attributes(palette=palette, fill_role="accent-stroke"),
        )


def _render_label(
    parent: ET.Element,
    node: FittedNode,
    style: LayoutStyle,
    palette: Palette,
) -> None:
    metrics = node.measured.label
    if not metrics.lines:
        return
    bounds = node.bounds
    motif_kinds = {
        "attention",
        "channels",
        "concat",
        "feature-strip",
        "graph",
        "inset",
        "matrix",
        "sequence",
    }
    label_height = (
        bounds.height * 0.24
        if node.measured.spec.kind in motif_kinds
        else bounds.height / 2
    )
    center_y = bounds.y + label_height
    first_baseline = center_y - metrics.height / 2.0 + metrics.baseline
    text = element(
        parent,
        "text",
        id=f"{node.measured.spec.id}.label",
        x=bounds.center.x,
        y=first_baseline,
        text__anchor="middle",
        font__family=style.typography.family,
        font__size=style.typography.size.points,
        data__flexo__fill="ink",
        fill=palette.get("ink"),
    )
    for line_index, line in enumerate(metrics.lines):
        for run_index, run in enumerate(line.runs):
            tspan = element(
                text,
                "tspan",
                x=bounds.center.x if run_index == 0 else None,
                dy=metrics.line_height if line_index > 0 and run_index == 0 else None,
                font__weight=run.weight,
                font__style="italic" if run.italic else "normal",
                baseline__shift=run.baseline_shift if run.baseline_shift != "normal" else None,
                font__size=(
                    style.typography.size.points * 0.72
                    if run.baseline_shift != "normal"
                    else style.typography.size.points
                ),
            )
            tspan.text = run.text
