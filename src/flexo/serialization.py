"""YAML/JSON interchange parsing into the immutable semantic IR."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from flexo.components import COMPONENTS, normalize_node
from flexo.conventions import parse_conventions
from flexo.geometry import Side
from flexo.ir.semantic import (
    EdgeSpec,
    FigureSpec,
    GroupSpec,
    LayoutSpec,
    NetSpec,
    NodeSpec,
    PortRef,
    PortSpec,
    TextRun,
    Waypoint,
    freeze_property,
    thaw_property,
)
from flexo.markup import has_markup, parse_label
from flexo.schema import validate_document
from flexo.sketch import parse_sketch
from flexo.units import CellSpan, Extent, Length, parse_extent
from flexo.validate import normalize_and_validate


def load_figure(source_file: str | Path) -> FigureSpec:
    target_file = Path(source_file)
    text = target_file.read_text(encoding="utf-8")
    if target_file.suffix.lower() == ".json":
        document = json.loads(text)
    elif target_file.suffix.lower() in {".yaml", ".yml"}:
        document = yaml.safe_load(text)
    else:
        raise ValueError("figure specifications must use .yaml, .yml, or .json")
    # A theme or palette file named in a figure file is found next to it.
    figure_data = document.get("figure") if isinstance(document, dict) else None
    if isinstance(figure_data, dict):
        for key in ("theme", "style", "palette"):
            value = figure_data.get(key)
            if isinstance(value, str) and value.lower().endswith((".yaml", ".yml", ".json")):
                beside = (target_file.parent / value).resolve()
                if not Path(value).is_absolute() and beside.is_file():
                    figure_data[key] = str(beside)
    return parse_figure(document)


def parse_figure(document: object) -> FigureSpec:
    """A figure from its document (parsed YAML or JSON), validated.

    A hand-written file may leave out what Python would not make you write:
    ``schema_version``, ``width`` (double-column), ``root``, a node's
    ``kind`` (a block), an edge's ``id`` (numbered as the builder numbers them),
    and ``groups`` (the nodes are stacked in a column, as on a new ``Figure``).
    An edge end may name a node alone -- ``from: encoder`` -- for its usual port,
    ``output`` where a value leaves and ``input`` where it arrives; ``theme`` is
    the same as ``style``.
    """

    document = _written_steps(document)
    validate_document(document)
    assert isinstance(document, dict)
    figure_data = document["figure"]
    assert isinstance(figure_data, dict)
    root = figure_data.get("root", "root")
    node_ids = {item["id"] for item in document["nodes"]}

    def reference(value: str, port: str) -> PortRef:
        return PortRef(value, port) if value in node_ids else PortRef.parse(value)

    edges = []
    for index, item in enumerate(document.get("edges", []), start=1):
        source, target = reference(item["from"], "output"), reference(item["to"], "input")
        edge_id = item.get("id") or f"edge.{index}.{source.node_id}-to-{target.node_id}"
        edges.append(_edge(item, edge_id, source, target))
    groups = [_group(item) for item in document.get("groups", [])]
    held = {child for group in groups for child in group.children}
    unplaced = tuple(
        item_id
        for item_id in [*(group.id for group in groups), *(n["id"] for n in document["nodes"])]
        if item_id not in held and item_id != root
    )
    if unplaced and any(group.id == root for group in groups):
        # A node (or group) written into the file but into none of its groups -- added by
        # hand -- is drawn at the end of the root, not left out of the layout it would break.
        groups = [
            replace(group, children=(*group.children, *unplaced)) if group.id == root else group
            for group in groups
        ]
    if not any(group.id == root for group in groups):
        # No root written: everything no group holds is stacked on the canvas.
        held = {child for group in groups for child in group.children}
        top = tuple(
            item_id
            for item_id in [*(group.id for group in groups), *(n["id"] for n in document["nodes"])]
            if item_id not in held
        )
        groups.append(
            GroupSpec(
                id=root,
                children=top,
                layout=LayoutSpec("column", align="auto", justify="center"),
                role="canvas",
            )
        )
    from flexo.theme_files import is_file_reference, register_palette, register_theme

    style = str(figure_data.get("theme", figure_data.get("style", "paper")))
    if is_file_reference(style):
        style = register_theme(style)
    palette = str(figure_data.get("palette", "default"))
    if is_file_reference(palette):
        palette = register_palette(palette)[0]
    figure = FigureSpec(
        id=figure_data["id"],
        width=_length_or_preset(figure_data.get("width", "double-column")),
        height=_optional_length(figure_data.get("height")),
        root=root,
        style=style,
        palette=palette,
        font=figure_data.get("font"),
        conventions=parse_conventions(figure_data.get("conventions")),
        sketch=parse_sketch(figure_data.get("sketch")),
        background=figure_data.get("background"),
        nodes=tuple(_node(item) for item in document["nodes"]),
        edges=tuple(edges),
        nets=tuple(_net(item, reference) for item in document.get("nets", [])),
        groups=tuple(groups),
        schema_version=document.get("schema_version", 1),
    )
    return normalize_and_validate(figure)


def _written_steps(document: object) -> object:
    """The document with each mechanism's steps as the figure holds them: a file may write
    a step's arrows as a list and its place as a mapping, as Python does."""

    if not isinstance(document, dict) or not isinstance(document.get("nodes"), list):
        return document
    from flexo.mechanism import step_records

    nodes = []
    for node in document["nodes"]:
        properties = node.get("properties") if isinstance(node, dict) else None
        if (
            node_kind(node) == "mechanism"
            and isinstance(properties, dict)
            and "steps" in properties
        ):
            node = {
                **node,
                "properties": {**properties, "steps": step_records(properties["steps"])},
            }
        nodes.append(node)
    return {**document, "nodes": nodes}


def node_kind(node: object) -> object:
    return node.get("kind") if isinstance(node, dict) else None


def figure_to_document(figure: FigureSpec) -> dict[str, Any]:
    semantic = normalize_and_validate(figure)
    document = {
        "schema_version": semantic.schema_version,
        "figure": _figure_data(semantic),
        "nodes": [_node_data(node) for node in semantic.nodes],
        "edges": [_edge_data(edge) for edge in semantic.edges],
        "groups": [_group_data(group) for group in semantic.groups],
    }
    if semantic.nets:
        document["nets"] = [_net_data(net) for net in semantic.nets]
    validate_document(document)
    return document


def dump_figure(figure: FigureSpec, *, format: str = "yaml") -> str:
    document = figure_to_document(figure)
    if format == "json":
        return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if format != "yaml":
        raise ValueError("format must be yaml or json")
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def save_figure(figure: FigureSpec, destination: str | Path) -> Path:
    target_file = Path(destination)
    format = "json" if target_file.suffix.lower() == ".json" else "yaml"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(dump_figure(figure, format=format), encoding="utf-8")
    return target_file


def _figure_data(figure: FigureSpec) -> dict[str, object]:
    result: dict[str, object] = {
        "id": figure.id,
        "width": figure.width if isinstance(figure.width, str) else _length_data(figure.width),
        "root": figure.root,
        "style": figure.style,
        "palette": figure.palette,
    }
    if figure.height is not None:
        result["height"] = _length_data(figure.height)
    if figure.font is not None:
        result["font"] = figure.font
    if figure.conventions is not None and figure.conventions.changes():
        result["conventions"] = figure.conventions.changes()
    if figure.sketch is not None:
        result["sketch"] = figure.sketch.changes() or True
    if figure.background is not None:
        result["background"] = figure.background
    return result


def _node_data(node: NodeSpec) -> dict[str, object]:
    result: dict[str, object] = {"id": node.id, "kind": node.kind}
    _put_label(result, node.label)
    if node.role != "block":
        result["role"] = node.role
    # The ports a node's kind gives it (a construct's include one per part) are not written.
    default_ports = normalize_node(replace(node, ports=())) if node.kind in COMPONENTS else None
    if default_ports is None or node.ports != default_ports.ports:
        result["ports"] = [
            {
                "name": port.name,
                "side": port.side.value,
                "offset": port.offset,
                **({"adaptive": True} if port.adaptive else {}),
            }
            for port in node.ports
        ]
    if node.width is not None:
        result["width"] = _extent_data(node.width)
    if node.height is not None:
        result["height"] = _extent_data(node.height)
    if node.shadow:
        result["shadow"] = True
    if node.align_with is not None:
        result["align_with"] = node.align_with
    if node.properties:
        result["properties"] = {name: thaw_property(value) for name, value in node.properties}
    return result


def _edge_data(edge: EdgeSpec) -> dict[str, object]:
    result: dict[str, object] = {
        "id": edge.id,
        "from": str(edge.source),
        "to": str(edge.target),
    }
    if edge.role != "flow":
        result["role"] = edge.role
    _put_label(result, edge.label)
    if edge.lane_hint:
        result["lane"] = edge.lane_hint
    if edge.depart:
        result["depart"] = edge.depart.value
    if edge.arrive:
        result["arrive"] = edge.arrive.value
    if edge.via:
        result["via"] = edge.via.value
    if edge.shape != "auto":
        result["shape"] = edge.shape
    if edge.line != "solid":
        result["line"] = edge.line
    if edge.tone is not None:
        result["tone"] = edge.tone
    if edge.arrow != "end":
        result["arrow"] = edge.arrow
    if edge.head != "arrow":
        result["head"] = edge.head
    if edge.back_label:
        back: dict[str, object] = {}
        _put_label(back, edge.back_label)
        result["back_label"] = back["label"]
    if edge.cofactors:
        cofactors = []
        for runs in edge.cofactors:
            item: dict[str, object] = {}
            _put_label(item, runs)
            cofactors.append(item.get("label", ""))
        result["cofactors"] = cofactors
    if edge.waypoints:
        result["waypoints"] = [_waypoint_data(waypoint) for waypoint in edge.waypoints]
    return result


def _net_data(net: NetSpec) -> dict[str, object]:
    result: dict[str, object] = {
        "id": net.id,
        "kind": net.kind,
        "sources": [str(source) for source in net.sources],
        "targets": [str(target) for target in net.targets],
    }
    if net.role != "flow":
        result["role"] = net.role
    _put_label(result, net.label)
    if net.rail_hint is not None:
        result["rail"] = net.rail_hint.value
    if net.rail_at is not None:
        result["rail_at"] = net.rail_at
    if net.via is not None:
        result["via"] = net.via.value
    if net.joint != "auto":
        result["joint"] = net.joint
    if net.line != "solid":
        result["line"] = net.line
    if net.tone is not None:
        result["tone"] = net.tone
    return result


def _group_data(group: GroupSpec) -> dict[str, object]:
    result: dict[str, object] = {
        "id": group.id,
        "children": list(group.children),
        "layout": _layout_data(group.layout),
    }
    if group.collision_policy != "disjoint":
        result["collision_policy"] = group.collision_policy
    _put_label(result, group.label)
    if group.role != "container":
        result["role"] = group.role
    if group.title_side != "left":
        result["title_side"] = group.title_side
    if group.anchor is not None:
        result["anchor"] = group.anchor
    if group.shadow:
        result["shadow"] = True
    if group.paint:
        result["paint"] = dict(group.paint)
    return result


def _layout_data(layout: LayoutSpec) -> dict[str, object]:
    result: dict[str, object] = {"kind": layout.kind}
    for name in (
        "gap",
        "row_gap",
        "column_gap",
        "padding",
        "padding_top",
        "padding_right",
        "padding_bottom",
        "padding_left",
        "width",
        "height",
    ):
        value = getattr(layout, name)
        if value is not None:
            result[name] = _length_data(value)
    if layout.align != "auto":
        result["align"] = layout.align
    if layout.justify != "start":
        result["justify"] = layout.justify
    if layout.columns is not None:
        result["columns"] = layout.columns
    if layout.reflow is not None:
        result["reflow"] = layout.reflow
    if layout.equal_size:
        result["equal_size"] = True
    if layout.placements:
        result["placements"] = [
            {"child": child_id, "row": row, "column": column}
            for child_id, row, column in layout.placements
        ]
    if layout.column_widths:
        result["column_widths"] = [
            {"column": column, "width": _length_data(width)}
            for column, width in layout.column_widths
        ]
    return result


def _waypoint_data(waypoint: Waypoint) -> dict[str, object]:
    result: dict[str, object] = {}
    if waypoint.reference:
        result["reference"] = waypoint.reference
    if waypoint.side:
        result["side"] = waypoint.side.value
    if waypoint.offset != 0.5:
        result["offset"] = waypoint.offset
    for name in ("dx", "dy"):
        value = getattr(waypoint, name)
        if value.points:
            result[name] = _length_data(value)
    for name in ("x", "y"):
        value = getattr(waypoint, name)
        if value is not None:
            result[name] = _length_data(value)
    return result


_RUN_EXTRAS = ("accent", "code", "link", "color", "math", "maths")


def _put_label(result: dict[str, object], label: tuple[TextRun, ...]) -> None:
    if not label:
        return
    if len(label) == 1 and label[0] == TextRun(label[0].text) and not has_markup(label[0].text):
        result["label"] = label[0].text
        return
    result["label"] = [
        {
            "text": run.text,
            "weight": run.weight,
            "italic": run.italic,
            "baseline_shift": run.baseline_shift,
            # A run's formula, colour, link and code are kept: a label read back is the one written.
            **{key: getattr(run, key) for key in _RUN_EXTRAS if getattr(run, key)},
        }
        for run in label
    ]


def _length_data(value: Length) -> str:
    rendered = f"{value.points:.5f}".rstrip("0").rstrip(".")
    return f"{rendered}pt"


def _extent_data(value: Extent) -> str:
    return str(value) if isinstance(value, CellSpan) else _length_data(value)


def _label(value: object = "") -> tuple[TextRun, ...]:
    if isinstance(value, str):
        return parse_label(value)
    assert isinstance(value, list)
    return tuple(
        TextRun(
            text=item["text"],
            weight=item.get("weight", 400),
            italic=item.get("italic", False),
            baseline_shift=item.get("baseline_shift", "normal"),
            accent=item.get("accent", ""),
            code=bool(item.get("code", False)),
            link=item.get("link", ""),
            color=item.get("color", ""),
            math=item.get("math", ""),
            maths=bool(item.get("maths", False)),
        )
        for item in value
    )


def _node(data: dict[str, Any]) -> NodeSpec:
    return NodeSpec(
        id=data["id"],
        kind=data.get("kind", "block"),
        label=_label(data.get("label", "")),
        role=data.get("role", "block"),
        ports=tuple(
            PortSpec(
                port["name"],
                Side(port["side"]),
                port.get("offset", 0.5),
                port.get("adaptive", False),
            )
            for port in data.get("ports", [])
        ),
        width=_optional_extent(data.get("width")),
        height=_optional_extent(data.get("height")),
        properties=tuple(
            sorted(
                (name, freeze_property(name, value))
                for name, value in {
                    **data.get("properties", {}),
                    **({"badge": data["badge"]} if data.get("badge") else {}),
                }.items()
            )
        ),
        shadow=data.get("shadow", False),
        align_with=data.get("align_with"),
    )


def _edge(data: dict[str, Any], edge_id: str, source: PortRef, target: PortRef) -> EdgeSpec:
    return EdgeSpec(
        id=edge_id,
        source=source,
        target=target,
        role=data.get("role", "flow"),
        label=_label(data.get("label", "")),
        lane_hint=data.get("lane"),
        waypoints=tuple(_waypoint(item) for item in data.get("waypoints", [])),
        depart=Side(data["depart"]) if data.get("depart") else None,
        arrive=Side(data["arrive"]) if data.get("arrive") else None,
        via=Side(data["via"]) if data.get("via") else None,
        shape=data.get("shape", "auto"),
        line=data.get("line", "solid"),
        tone=_tone(data.get("tone")),
        arrow=data.get("arrow", "end"),
        head=data.get("head", "arrow"),
        back_label=_label(data.get("back_label", "")),
        cofactors=tuple(_label(item) for item in data.get("cofactors", ())),
    )


def _net(data: dict[str, Any], reference: Callable[[str, str], PortRef]) -> NetSpec:
    return NetSpec(
        id=data["id"],
        kind=data["kind"],
        sources=tuple(reference(value, "output") for value in data["sources"]),
        targets=tuple(reference(value, "input") for value in data["targets"]),
        role=data.get("role", "flow"),
        label=_label(data.get("label", "")),
        rail_hint=Side(data["rail"]) if data.get("rail") else None,
        rail_at=data.get("rail_at"),
        joint=data.get("joint", "auto"),
        line=data.get("line", "solid"),
        tone=_tone(data.get("tone")),
        via=Side(data["via"]) if data.get("via") else None,
    )


def _tone(value: object) -> str | None:
    """A line's tone as written: a number (``tone: 3``) is read as the tone it names."""

    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def _waypoint(data: dict[str, Any]) -> Waypoint:
    return Waypoint(
        reference=data.get("reference"),
        side=Side(data["side"]) if data.get("side") else None,
        offset=data.get("offset", 0.5),
        dx=_optional_length(data.get("dx")) or Length(0.0),
        dy=_optional_length(data.get("dy")) or Length(0.0),
        x=_optional_length(data.get("x")),
        y=_optional_length(data.get("y")),
    )


def _group(data: dict[str, Any]) -> GroupSpec:
    layout = data["layout"]
    return GroupSpec(
        id=data["id"],
        children=tuple(data["children"]),
        layout=LayoutSpec(
            kind=layout["kind"],
            gap=_optional_length(layout.get("gap")),
            padding=_optional_length(layout.get("padding")),
            align=layout.get("align", "auto"),
            justify=layout.get("justify", "start"),
            columns=layout.get("columns"),
            width=_optional_length(layout.get("width")),
            height=_optional_length(layout.get("height")),
            reflow=layout.get("reflow"),
            equal_size=layout.get("equal_size", False),
            row_gap=_optional_length(layout.get("row_gap")),
            column_gap=_optional_length(layout.get("column_gap")),
            padding_top=_optional_length(layout.get("padding_top")),
            padding_right=_optional_length(layout.get("padding_right")),
            padding_bottom=_optional_length(layout.get("padding_bottom")),
            padding_left=_optional_length(layout.get("padding_left")),
            placements=tuple(
                (item["child"], item["row"], item["column"])
                for item in layout.get("placements", [])
            ),
            column_widths=tuple(
                (item["column"], Length.parse(item["width"]))
                for item in layout.get("column_widths", [])
            ),
        ),
        collision_policy=data.get("collision_policy", "disjoint"),
        label=_label(data.get("label", "")),
        role=data.get("role", "container"),
        title_side=data.get("title_side", "left"),
        anchor=data.get("anchor"),
        shadow=data.get("shadow", False),
        paint=tuple(sorted(data.get("paint", {}).items())),
    )


def _optional_length(value: object) -> Length | None:
    return None if value is None else Length.parse(value)  # type: ignore[arg-type]


def _optional_extent(value: object) -> Extent | None:
    return None if value is None else parse_extent(value)  # type: ignore[arg-type]


def _length_or_preset(value: object) -> str | Length:
    if isinstance(value, str) and value in {"single-column", "double-column", "presentation"}:
        return value
    return Length.parse(value)  # type: ignore[arg-type]
