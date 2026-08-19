from __future__ import annotations

import json
from pathlib import Path

import pytest

from flexo.diagnostics import FlexoError
from flexo.schema import load_schema, validate_document


def minimal_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "figure": {"id": "minimal", "width": "single-column", "root": "root"},
        "nodes": [{"id": "input", "kind": "block", "label": "Input"}],
        "edges": [],
        "groups": [
            {"id": "root", "children": ["input"], "layout": {"kind": "row"}}
        ],
    }


def test_minimal_document_is_valid() -> None:
    validate_document(minimal_document())


def test_schema_reports_entity_and_location() -> None:
    document = minimal_document()
    document["nodes"][0]["unexpected"] = True  # type: ignore[index]
    with pytest.raises(FlexoError) as error:
        validate_document(document)
    assert error.value.diagnostics[0].entity_id == "input"
    assert "nodes.0" in error.value.diagnostics[0].message


def test_published_schema_matches_the_one_the_compiler_loads() -> None:
    """The repository copy and the packaged copy have to stay in lockstep."""

    published = Path(__file__).resolve().parents[2] / "schemas" / "figure.schema.json"
    assert json.loads(published.read_text(encoding="utf-8")) == load_schema()


def test_layout_accepts_asymmetric_spacing_and_grid_placement() -> None:
    document = minimal_document()
    document["groups"][0]["layout"] = {  # type: ignore[index]
        "kind": "grid",
        "columns": 2,
        "row_gap": "9pt",
        "column_gap": "4pt",
        "padding_top": "12pt",
        "padding_left": "3pt",
        "placements": [{"child": "input", "row": 1, "column": 0}],
        "column_widths": [{"column": 1, "width": "50pt"}],
    }
    document["nodes"][0]["height"] = "cells:3"  # type: ignore[index]
    validate_document(document)
