"""Outputs that need nothing but Python: the notebook display and the PNG preview."""

from __future__ import annotations

from pathlib import Path

import pytest

import flexo
from flexo.builder import Figure


def _figure() -> Figure:
    with Figure("small") as figure, figure.module("m", label="Small") as m:
        m.block("b", label="$x_t$", input=m.text("a", "A"))
    return figure


def test_a_figure_displays_itself_in_a_notebook() -> None:
    svg = _figure()._repr_svg_()
    assert svg.lstrip().startswith("<?xml") and "<svg" in svg


def test_a_png_preview_needs_no_inkscape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLEXO_INKSCAPE", str(tmp_path / "no-inkscape-here"))
    result = flexo.build(_figure().spec, tmp_path, formats=("editable", "png"), dpi=96)
    assert result.outputs.png is not None
    assert result.outputs.png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(flexo.FlexoError, match="Inkscape is required"):
        flexo.build(_figure().spec, tmp_path, formats=("pdf",))
