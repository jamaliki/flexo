from __future__ import annotations

import pytest

from flexo.diagnostics import FlexoError
from flexo.serialization import parse_figure


def document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "figure": {"id": "pipeline", "width": "single-column", "root": "root"},
        "nodes": [
            {"id": "input", "kind": "feature-strip", "label": "Features"},
            {"id": "projection", "kind": "mlp", "label": "Projection"},
        ],
        "edges": [
            {"id": "input-to-projection", "from": "input.output", "to": "projection.input"}
        ],
        "groups": [
            {
                "id": "root",
                "children": ["input", "projection"],
                "layout": {"kind": "row", "justify": "center"},
            }
        ],
    }


def test_parse_normalizes_component_ports() -> None:
    figure = parse_figure(document())
    assert {port.name for port in figure.node("projection").ports} == {"input", "output"}


def test_unknown_port_lists_valid_alternatives() -> None:
    value = document()
    value["edges"][0]["to"] = "projection.in"  # type: ignore[index]
    with pytest.raises(
        FlexoError,
        match=r"Valid ports: projection\.input, projection\.output",
    ):
        parse_figure(value)
