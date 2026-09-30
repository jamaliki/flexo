"""JSON Schema loading and localized interchange-format diagnostics."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from flexo.diagnostics import Diagnostic, FlexoError, described


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
                f"{location}: {_said(error)}",
                entity_id=entity_id,
            )
        )
    raise FlexoError(diagnostics)


TYPES = {
    "object": "a set of settings",
    "array": "a list",
    "string": "words",
    "number": "a number",
    "integer": "a whole number",
    "boolean": "yes or no",
    "null": "nothing",
}


def _said(error: Any) -> str:
    """What the schema found wrong, in words rather than the checker's own (which shows
    the value as Python writes it)."""

    kind, expected, value = error.validator, error.validator_value, error.instance
    if kind == "type":
        wanted = [expected] if isinstance(expected, str) else list(expected)
        names = " or ".join(TYPES.get(item, item) for item in wanted)
        return f"should be {names}, not {described(value)}"
    if kind == "required":
        missing = [name for name in expected if isinstance(value, dict) and name not in value]
        return f"needs {', '.join(missing) or 'more'}"
    if kind == "additionalProperties" and isinstance(value, dict):
        allowed = set((error.schema.get("properties") or {}).keys())
        extra = [str(name) for name in value if name not in allowed]
        return f"takes no {', '.join(extra)}" if extra else error.message
    if kind == "enum":
        choices = ", ".join(str(item) for item in expected)
        return f"should be one of {choices}, not {described(value)}"
    if kind in {"minimum", "exclusiveMinimum"}:
        return f"should be at least {expected}, not {described(value)}"
    if kind in {"maximum", "exclusiveMaximum"}:
        return f"should be at most {expected}, not {described(value)}"
    if kind == "minItems":
        return f"needs at least {expected} item{'s' if expected != 1 else ''}"
    if kind == "pattern":
        return f"is not written as expected ({described(value)})"
    if kind in {"oneOf", "anyOf"}:
        return f"is not written as expected ({described(value)})"
    if len(error.message) < 120:
        return error.message
    return f"is not written as expected ({described(value)})"


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
