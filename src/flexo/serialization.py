"""YAML/JSON interchange parsing into the immutable semantic IR."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from flexo.components import COMPONENTS
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
)
from flexo.schema import validate_document
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
    return parse_figure(document)


def parse_figure(document: object) -> FigureSpec:
    validate_document(document)
    assert isinstance(document, dict)
    figure_data = document["figure"]
    assert isinstance(figure_data, dict)
    figure = FigureSpec(
        id=figure_data["id"],
        width=_length_or_preset(figure_data["width"]),
        height=_optional_length(figure_data.get("height")),
        root=figure_data["root"],
        style=figure_data.get("style", "paper"),
        palette=figure_data.get("palette", "default"),
        nodes=tuple(_node(item) for item in document["nodes"]),
        edges=tuple(_edge(item) for item in document["edges"]),
        nets=tuple(_net(item) for item in document.get("nets", [])),
        groups=tuple(_group(item) for item in document["groups"]),
        schema_version=document["schema_version"],
    )
    return normalize_and_validate(figure)


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
    return result


def _node_data(node: NodeSpec) -> dict[str, object]:
    result: dict[str, object] = {"id": node.id, "kind": node.kind}
    _put_label(result, node.label)
    if node.role != "block":
        result["role"] = node.role
    default_ports = COMPONENTS.get(node.kind)
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
    if node.properties:
        result["properties"] = dict(node.properties)
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
    if net.joint != "auto":
        result["joint"] = net.joint
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
    if layout.align != "center":
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


def _put_label(result: dict[str, object], label: tuple[TextRun, ...]) -> None:
    if not label:
        return
    if len(label) == 1 and label[0] == TextRun(label[0].text):
        result["label"] = label[0].text
        return
    result["label"] = [
        {
            "text": run.text,
            "weight": run.weight,
            "italic": run.italic,
            "baseline_shift": run.baseline_shift,
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
        return (TextRun(value),) if value else ()
    assert isinstance(value, list)
    return tuple(
        TextRun(
            text=item["text"],
            weight=item.get("weight", 400),
            italic=item.get("italic", False),
            baseline_shift=item.get("baseline_shift", "normal"),
        )
        for item in value
    )


def _node(data: dict[str, Any]) -> NodeSpec:
    return NodeSpec(
        id=data["id"],
        kind=data["kind"],
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
        properties=tuple(sorted(data.get("properties", {}).items())),
    )


def _edge(data: dict[str, Any]) -> EdgeSpec:
    return EdgeSpec(
        id=data["id"],
        source=PortRef.parse(data["from"]),
        target=PortRef.parse(data["to"]),
        role=data.get("role", "flow"),
        label=_label(data.get("label", "")),
        lane_hint=data.get("lane"),
        waypoints=tuple(_waypoint(item) for item in data.get("waypoints", [])),
        depart=Side(data["depart"]) if data.get("depart") else None,
        arrive=Side(data["arrive"]) if data.get("arrive") else None,
    )


def _net(data: dict[str, Any]) -> NetSpec:
    return NetSpec(
        id=data["id"],
        kind=data["kind"],
        sources=tuple(PortRef.parse(value) for value in data["sources"]),
        targets=tuple(PortRef.parse(value) for value in data["targets"]),
        role=data.get("role", "flow"),
        label=_label(data.get("label", "")),
        rail_hint=Side(data["rail"]) if data.get("rail") else None,
        rail_at=data.get("rail_at"),
        joint=data.get("joint", "auto"),
    )


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
            align=layout.get("align", "center"),
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
    )


def _optional_length(value: object) -> Length | None:
    return None if value is None else Length.parse(value)  # type: ignore[arg-type]


def _optional_extent(value: object) -> Extent | None:
    return None if value is None else parse_extent(value)  # type: ignore[arg-type]


def _length_or_preset(value: object) -> str | Length:
    if isinstance(value, str) and value in {"single-column", "double-column", "presentation"}:
        return value
    return Length.parse(value)  # type: ignore[arg-type]
