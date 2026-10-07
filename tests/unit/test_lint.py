"""What lint says of a figure's SVG file: about the drawing, never about how its author
chose to group it."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from flexo.compiler import compile_figure
from flexo.lint import _tree_depth, lint_compilation, lint_svg
from flexo.serialization import parse_figure


def _grouped(depth: int) -> dict:
    """Two insets and their CNNs in rows framed in a module, framed in a row, ``depth``
    frames deep -- as Group, then Module, then rows made inside it build one."""

    groups = [
        {"id": "r1", "children": ["i1", "c1"], "layout": {"kind": "row"}, "role": "container"},
        {"id": "r2", "children": ["i2", "c2"], "layout": {"kind": "row"}, "role": "container"},
    ]
    inner = ["grid", "r1", "r2"]
    for level in range(depth):
        layout = {"kind": "column"}
        groups.append(
            {"id": f"g{level}", "children": inner, "layout": layout, "role": "module", "label": "M"}
        )
        inner = [f"g{level}"]
    groups.append({"id": "root", "children": inner, "layout": {"kind": "column"}, "role": "canvas"})
    return {
        "figure": {"id": "deep"},
        "nodes": [
            {"id": "grid", "kind": "cells", "label": "Grid", "properties": {"grid": "A B\nB A"}},
            {"id": "i1", "kind": "inset", "label": "Edge"},
            {"id": "c1", "kind": "cnn", "label": "CNN"},
            {"id": "i2", "kind": "inset", "label": "Cube"},
            {"id": "c2", "kind": "cnn", "label": "CNN"},
        ],
        "groups": groups,
        "edges": [{"from": "i1", "to": "c1"}, {"from": "i2", "to": "c2"}],
    }


def test_a_figure_grouped_deeply_by_its_author_is_not_a_drawing_problem() -> None:
    """Each frame is a layer holding its parts' sublayer, two levels by design: a figure
    framed in frames in frames nests as deep as it was made, and that is not said."""

    for depth in (1, 3, 5):
        compiled = compile_figure(parse_figure(_grouped(depth)))
        root = ET.fromstring(compiled.document.text)
        raw = _depth_of(root)
        assert raw > 10 or depth == 1
        codes = [item.code for item in lint_compilation(compiled).diagnostics]
        assert "svg.hierarchy.deep" not in codes, depth
        assert _tree_depth(root) <= 8


def test_a_drawing_whose_own_pieces_nest_too_deep_is_still_said() -> None:
    nested = "<g>" * 12 + "<path d='M0 0'/>" + "</g>" * 12
    svg = f'<svg xmlns="http://www.w3.org/2000/svg">{nested}</svg>'
    codes = [item.code for item in lint_svg(svg).diagnostics]
    assert "svg.hierarchy.deep" in codes


def _depth_of(element: ET.Element) -> int:
    return 1 + max((_depth_of(child) for child in element), default=0)
