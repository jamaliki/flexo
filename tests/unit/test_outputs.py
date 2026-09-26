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


def test_the_same_figure_compiles_to_the_same_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Embedded font subsets must not carry the time they were made."""

    import time

    from flexo.compiler import compile_figure

    first = compile_figure(_figure().spec).document.text
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 86_400.0)
    assert compile_figure(_figure().spec).document.text == first


def test_a_script_no_bundled_font_has_is_set_in_one_installed_font() -> None:
    """Characters outside every bundled font come from an installed font that has them all."""

    import re

    from flexo.compiler import compile_figure
    from flexo.fonts import family_covering

    word = "编码器"
    if family_covering(word) is None:
        pytest.skip("no installed font covers CJK")
    with Figure("cjk") as figure, figure.module("m", label=word) as m:
        m.block("b", label="注意力")
    compilation = compile_figure(figure.spec)
    families = {
        text: family
        for family, text in re.findall(
            r'<tspan font-family="([^"]+)">([^<]*)<', compilation.document.text
        )
    }
    assert word in families and "注意力" in families
