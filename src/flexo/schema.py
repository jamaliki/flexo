"""JSON Schema loading and localized interchange-format diagnostics."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from flexo.diagnostics import Diagnostic, FlexoError


def load_schema() -> dict[str, Any]:
    schema_file = resources.files("flexo.resources").joinpath("figure.schema.json")
    return json.loads(schema_file.read_text(encoding="utf-8"))


def validate_document(document: object) -> None:
    validator = Draft202012Validator(load_schema())
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path))
    if not errors:
        return
    diagnostics = []
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path) or "document"
        entity_id = _entity_id(document, tuple(error.absolute_path))
        diagnostics.append(
            Diagnostic(
                "schema.invalid",
                f"{location}: {error.message}",
                entity_id=entity_id,
            )
        )
    raise FlexoError(diagnostics)


def _entity_id(document: object, location: tuple[object, ...]) -> str | None:
    value = document
    for part in location:
        try:
            value = value[part]  # type: ignore[index]
        except (KeyError, IndexError, TypeError):
            break
        if isinstance(value, dict) and isinstance(value.get("id"), str):
            return value["id"]
    return None
