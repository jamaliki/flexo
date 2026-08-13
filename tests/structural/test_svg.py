from __future__ import annotations

import xml.etree.ElementTree as ET

from flexo.compiler import compile_figure
from flexo.emit import retheme_svg
from flexo.ir.semantic import (
    EdgeSpec,
    FigureSpec,
    GroupSpec,
    LayoutSpec,
    NodeSpec,
    PortRef,
    TextRun,
)
from flexo.lint import lint_compilation
from flexo.style import GRAYSCALE_PALETTE
from flexo.svg import INKSCAPE_NS, SVG_NS
from flexo.units import pt


def compilation():
    figure = FigureSpec(
        "editable",
        width=pt(180),
        nodes=(
            NodeSpec("features", "feature-strip", (TextRun("Features"),)),
            NodeSpec("projection", "mlp", (TextRun("Projection"),)),
        ),
        edges=(
            EdgeSpec(
                "features-to-projection",
                PortRef("features", "output"),
                PortRef("projection", "input"),
            ),
        ),
        groups=(
            GroupSpec(
                "root",
                ("features", "projection"),
                LayoutSpec("row", justify="space-between"),
                role="canvas",
            ),
        ),
    )
    return compile_figure(figure)


def test_editable_svg_has_named_layers_native_objects_and_live_text() -> None:
    built = compilation()
    root = ET.fromstring(built.document.text)
    by_id = {item.get("id"): item for item in root.iter() if item.get("id")}
    assert by_id["root"].get(f"{{{INKSCAPE_NS}}}groupmode") == "layer"
    assert by_id["features"].tag == f"{{{SVG_NS}}}g"
    assert by_id["features.body"].tag == f"{{{SVG_NS}}}rect"
    assert by_id["features.label"].tag == f"{{{SVG_NS}}}text"
    assert by_id["features-to-projection.shaft"].tag == f"{{{SVG_NS}}}path"
    assert by_id["features-to-projection.shaft"].get("marker-end") == "url(#arrow.flow)"
    assert not any(item.tag == f"{{{SVG_NS}}}foreignObject" for item in root.iter())
    assert lint_compilation(built).ok


def test_identical_inputs_emit_identical_svg() -> None:
    assert compilation().document.text == compilation().document.text


def test_palette_retheme_preserves_geometry_attributes() -> None:
    original = compilation().document.text
    themed = retheme_svg(original, GRAYSCALE_PALETTE)
    assert _geometry_signature(original) == _geometry_signature(themed)
    assert original != themed


def _geometry_signature(svg_text: str) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    root = ET.fromstring(svg_text)
    ignored = {
        "fill",
        "stroke",
        "data-flexo-fill",
        "data-flexo-stroke",
        "data-flexo-palette",
    }
    result = []
    for item in root.iter():
        if item.tag in {f"{{{SVG_NS}}}metadata", f"{{{SVG_NS}}}style"}:
            continue
        values = tuple(
            sorted(
                (name, value)
                for name, value in item.attrib.items()
                if name not in ignored
            )
        )
        result.append((item.tag, values))
    return tuple(result)
