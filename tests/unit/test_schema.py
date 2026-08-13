from __future__ import annotations

import pytest

from flexo.diagnostics import FlexoError
from flexo.schema import validate_document


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
