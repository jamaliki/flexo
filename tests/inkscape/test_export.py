from __future__ import annotations

from pathlib import Path

import pytest

from flexo.compiler import compile_figure
from flexo.export import export_outputs, find_inkscape, query_bounds
from flexo.gallery import vertical_slice

pytestmark = pytest.mark.skipif(find_inkscape() is None, reason="Inkscape is not installed")


def test_all_output_variants_and_bounds(tmp_path: Path) -> None:
    outputs = export_outputs(compile_figure(vertical_slice()), tmp_path, stem="slice")
    assert all(
        target_file.is_file() and target_file.stat().st_size > 0
        for target_file in outputs.existing()
    )
    bounds = query_bounds(outputs.editable_svg)
    assert "cryo.attention" in bounds
    assert "cryo.attention.label" in bounds
