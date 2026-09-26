"""The tutorial's code is run as written: every step must compile clean."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from flexo.compiler import compile_figure
from flexo.lint import lint_compilation

_PATH = Path(__file__).resolve().parents[2] / "examples" / "tutorial.py"


def _tutorial():
    spec = importlib.util.spec_from_file_location("tutorial", _PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STEPS = _tutorial().steps()


def test_the_tutorial_has_its_steps() -> None:
    assert len(STEPS) >= 12


@pytest.mark.parametrize(
    ("step", "look"), [(step, look) for step, figures in STEPS.items() for look in figures]
)
def test_every_tutorial_step_compiles_without_a_diagnostic(step: str, look: str) -> None:
    figure = STEPS[step][look]
    spec = getattr(figure, "spec", figure)
    report = lint_compilation(compile_figure(spec))
    assert not report.diagnostics, report.format()
