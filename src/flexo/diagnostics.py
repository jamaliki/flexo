"""Structured diagnostics shared by compiler passes and the CLI."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    severity: Severity = Severity.ERROR
    entity_id: str | None = None
    hint: str | None = None

    def format(self) -> str:
        location = f' [{self.entity_id}]' if self.entity_id else ""
        rendered = f"{self.severity.value}: {self.code}{location}: {self.message}"
        return f"{rendered}\n  hint: {self.hint}" if self.hint else rendered


class FlexoError(Exception):
    """A compiler failure carrying one or more actionable diagnostics."""

    def __init__(self, diagnostics: Diagnostic | Iterable[Diagnostic]) -> None:
        values = (diagnostics,) if isinstance(diagnostics, Diagnostic) else tuple(diagnostics)
        if not values:
            raise ValueError("FlexoError requires at least one diagnostic")
        self.diagnostics = values
        super().__init__("\n".join(item.format() for item in values))


def raise_if_errors(diagnostics: Iterable[Diagnostic]) -> tuple[Diagnostic, ...]:
    values = tuple(diagnostics)
    errors = tuple(item for item in values if item.severity is Severity.ERROR)
    if errors:
        raise FlexoError(errors)
    return values
