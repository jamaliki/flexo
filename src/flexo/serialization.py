"""YAML/JSON interchange parsing into the immutable semantic IR."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from flexo.geometry import Side
from flexo.ir.semantic import (
    EdgeSpec,
    FigureSpec,
    GroupSpec,
    LayoutSpec,
    NodeSpec,
    PortRef,
    PortSpec,
    TextRun,
    Waypoint,
)
from flexo.schema import validate_document
from flexo.units import Length
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
        groups=tuple(_group(item) for item in document["groups"]),
        schema_version=document["schema_version"],
    )
    return normalize_and_validate(figure)


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
            PortSpec(port["name"], Side(port["side"]), port.get("offset", 0.5))
            for port in data.get("ports", [])
        ),
        width=_optional_length(data.get("width")),
        height=_optional_length(data.get("height")),
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
        ),
        collision_policy=data.get("collision_policy", "disjoint"),
        label=_label(data.get("label", "")),
        role=data.get("role", "container"),
    )


def _optional_length(value: object) -> Length | None:
    return None if value is None else Length.parse(value)  # type: ignore[arg-type]


def _length_or_preset(value: object) -> str | Length:
    if isinstance(value, str) and value in {"single-column", "double-column", "presentation"}:
        return value
    return Length.parse(value)  # type: ignore[arg-type]
