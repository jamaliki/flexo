from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from flexo.builder import Figure
from flexo.compiler import Compilation, compile_figure
from flexo.components import vector_grid
from flexo.geometry import Side
from flexo.ir.semantic import PortSpec
from flexo.style import DEFAULT_PALETTE, GRAYSCALE_PALETTE, STYLES, Palette, VectorPreset
from flexo.svg import SVG_NS, number
from flexo.theme import retheme_svg
from flexo.units import pt

_STYLE = STYLES["paper"]


def _figure(**vector_options: object) -> Figure:
    figure = Figure("vectors", width=pt(260.0))
    with figure.module("m", gap="24pt") as module:
        cells = module.vector("v", label="Node features", ramp="ramp-kv", **vector_options)
        module.mlp("mlp", label="MLP", input=cells)
    return figure


def _compiled(palette: Palette | None = None, **vector_options: object) -> Compilation:
    return compile_figure(_figure(**vector_options).spec, palette=palette)


def _cells(svg_text: str, node_id: str = "m.v.cells") -> list[ET.Element]:
    root = ET.fromstring(svg_text)
    return [
        item
        for item in root.iter(f"{{{SVG_NS}}}rect")
        if (item.get("id") or "").startswith(f"{node_id}.cell.")
    ]


def test_vector_draws_one_rounded_cell_per_grid_position() -> None:
    """R19: geometry is exactly the cell grid, at the style's tokens."""

    compiled = _compiled(cells=4, columns=2)
    node = compiled.fitted.node("m.v.cells")
    grid = vector_grid(node.measured.spec, _STYLE)
    assert grid.cells == 4 and grid.columns == 2
    assert node.bounds.size == grid.size
    cells = _cells(compiled.document.text)
    assert [cell.get("id") for cell in cells] == [
        f"m.v.cells.cell.{column}.{row}" for column in (1, 2) for row in (1, 2, 3, 4)
    ]
    for cell in cells:
        assert float(cell.get("width", "0")) == pytest.approx(_STYLE.vector_cell.points)
        assert float(cell.get("height", "0")) == pytest.approx(_STYLE.vector_cell.points)
        assert float(cell.get("rx", "0")) == pytest.approx(_STYLE.vector_cell_radius.points)


def test_vector_shades_cells_along_its_ramp_role() -> None:
    """R19: one palette role per ramp, graded by fill-opacity, per column."""

    cells = _cells(_compiled(cells=3, columns=2).document.text)
    for cell in cells:
        assert cell.get("data-flexo-fill") == "ramp-kv"
        assert cell.get("data-flexo-stroke") == "ramp-kv"
        assert cell.get("fill") == DEFAULT_PALETTE.get("ramp-kv")
    opacities = [float(cell.get("fill-opacity", "1")) for cell in cells]
    first_column, second_column = opacities[:3], opacities[3:]
    assert first_column == second_column, "columns of one vector share the ramp"
    assert first_column[0] < first_column[1] < first_column[2]


def test_vector_preset_paints_literal_shades_no_role_survives() -> None:
    """Preset colour is the author's, so retheme has no role to rewrite."""

    preset = VectorPreset(("#d0568c", "#7fae3f"), "2x3")
    figure = Figure("preset", width=pt(200.0))
    with figure.module("m") as module:
        module.vector("v", label="K, V", preset=preset)
    document = compile_figure(figure.spec).document.text
    cells = _cells(document, "m.v.cells")
    shades = preset.column_shades()
    assert [cell.get("fill") for cell in cells] == [*shades[0], *shades[1]]
    for cell in cells:
        assert cell.get("stroke") == cell.get("fill")
        assert cell.get("fill-opacity") is None, "preset cells are opaque"
        assert cell.get("data-flexo-fill") is None
        assert cell.get("data-flexo-stroke") is None
    root = ET.fromstring(document)
    stack = next(
        item for item in root.iter(f"{{{SVG_NS}}}g") if item.get("id") == "m.v.cells.grid"
    )
    assert stack.get("data-flexo-ramp") == "preset"
    assert retheme_svg(document, GRAYSCALE_PALETTE).count(shades[0][0]) == document.count(
        shades[0][0]
    )


def test_vector_ramp_is_paint_only_across_palettes() -> None:
    """The R19 invariant: swapping palettes may not move a single coordinate."""

    default = _compiled(DEFAULT_PALETTE, cells=4).document.text
    gray = _compiled(GRAYSCALE_PALETTE, cells=4).document.text
    assert default != gray
    assert _geometry(default) == _geometry(gray)
    assert [cell.get("fill") for cell in _cells(gray)] == [
        GRAYSCALE_PALETTE.get("ramp-kv")
    ] * 4


def test_retheme_repaints_vector_cells_and_keeps_the_ramp() -> None:
    """R19/theme: ``flexo retheme`` patches by role, so the shading survives."""

    original = _compiled().document.text
    themed = retheme_svg(original, GRAYSCALE_PALETTE)
    assert _geometry(original) == _geometry(themed)
    for cell in _cells(themed):
        assert cell.get("fill") == GRAYSCALE_PALETTE.get("ramp-kv")
        assert cell.get("stroke") == GRAYSCALE_PALETTE.get("ramp-kv")
    assert [cell.get("fill-opacity") for cell in _cells(themed)] == [
        cell.get("fill-opacity") for cell in _cells(original)
    ]


def test_vector_ports_sit_at_the_side_centres_of_the_stack() -> None:
    """R18/R19: west and east on the middle cell, north and south top/bottom centre."""

    compiled = _compiled(cells=3)
    node = compiled.fitted.node("m.v.cells")
    grid = vector_grid(node.measured.spec, _STYLE)
    middle = grid.cell_bounds(node.bounds, 0, 1).center
    ports = {port.name: port.position for port in node.ports}
    assert ports["input"].y == pytest.approx(middle.y)
    assert ports["output"].y == pytest.approx(middle.y)
    assert ports["input"].x == pytest.approx(node.bounds.left)
    assert ports["output"].x == pytest.approx(node.bounds.right)
    assert ports["north"] == node.bounds.point_on(Side.NORTH)
    assert ports["south"] == node.bounds.point_on(Side.SOUTH)


def test_vector_arrow_runs_straight_into_the_middle_cell() -> None:
    """The counterpart port adapts to the fixed centre, so the run is one segment."""

    compiled = _compiled(cells=3)
    node = compiled.fitted.node("m.v.cells")
    grid = vector_grid(node.measured.spec, _STYLE)
    middle = grid.cell_bounds(node.bounds, 0, 1).center
    edge = compiled.routed.edges[0]
    assert len(edge.centerline) == 2, "no jog between the middle cell and the MLP"
    assert edge.centerline[0].y == pytest.approx(middle.y)
    assert edge.centerline[-1].y == pytest.approx(middle.y)


def _geometry(svg_text: str) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    ignored = {"fill", "stroke", "data-flexo-fill", "data-flexo-stroke", "data-flexo-palette"}
    root = ET.fromstring(svg_text)
    return tuple(
        (
            item.tag,
            tuple(
                sorted(
                    (name, value)
                    for name, value in item.attrib.items()
                    if name not in ignored
                )
            ),
        )
        for item in root.iter()
        if item.tag not in {f"{{{SVG_NS}}}metadata", f"{{{SVG_NS}}}style"}
    )


def _merge_figure(**net_options: object) -> Figure:
    """Two sources into one sink: a rail whose terminals each serve one stem."""

    figure = Figure("merge", width=pt(320.0))
    with figure.root.row("row", gap="70pt", padding=0, align="center", role="layout") as row:
        with row.column("sources", gap="50pt", padding=0, role="layout") as sources:
            first = sources.block(
                "first",
                label="First",
                ports=(PortSpec("output", Side.EAST, adaptive=True),),
            )
            second = sources.block(
                "second",
                label="Second",
                ports=(PortSpec("output", Side.EAST, adaptive=True),),
            )
        sink = row.block(
            "sink",
            label="Sink",
            ports=(PortSpec("input", Side.WEST, adaptive=True),),
        )
    figure.merge(sinks=[first, second], dst=sink, id="combined", **net_options)  # type: ignore[arg-type]
    return figure


def _paths(svg_text: str) -> dict[str, str]:
    root = ET.fromstring(svg_text)
    return {
        item.get("id", ""): item.get("d", "")
        for item in root.iter(f"{{{SVG_NS}}}path")
    }


def test_single_stem_rail_terminals_turn_on_a_fillet() -> None:
    """R22: the rail hands its last two radii to the only stem it meets there."""

    compiled = compile_figure(_merge_figure().spec)
    net = compiled.routed.net("combined")
    radius = _STYLE.elbow_radius.points
    paths = _paths(compiled.document.text)
    rail = paths["combined.rail"]
    top, bottom = sorted(point.y for point in net.rail)
    assert rail.startswith(f"M {number(net.rail[0].x)} {number(top + 2.0 * radius)}")
    assert rail.endswith(f"V {number(bottom - 2.0 * radius)}")
    for stem_id in ("combined.source.1", "combined.source.2"):
        assert " Q " in paths[stem_id], "the stem owns the rounded corner"
        # The lead-in restores exactly what the rail gave up, so no ink is lost.
        assert f"{number(net.rail[0].x)}" in paths[stem_id]


def test_junction_dots_stay_on_the_emitted_rail() -> None:
    """R8/R22: a branch dot marks a fork, so it may never leave the rail path."""

    compiled = compile_figure(_merge_figure().spec)
    net = compiled.routed.net("combined")
    root = ET.fromstring(compiled.document.text)
    dots = [
        item
        for item in root.iter(f"{{{SVG_NS}}}circle")
        if (item.get("id") or "").startswith("combined.junction.")
    ]
    assert dots, "the arrival forks off the rail"
    low, high = sorted(point.y for point in net.rail)
    rail_start = low + 2.0 * _STYLE.elbow_radius.points
    rail_end = high - 2.0 * _STYLE.elbow_radius.points
    for dot in dots:
        assert float(dot.get("cx", "0")) == pytest.approx(net.rail[0].x)
        assert rail_start <= float(dot.get("cy", "0")) <= rail_end


def test_an_arrow_joint_marks_every_approach_and_drops_the_dot() -> None:
    """R8/R20: the branch points into the trunk; the trunk crosses it unbroken.

    This sink sits between its two sources, so the rail approaches the joint
    from both sides and each approach earns its own marker.
    """

    compiled = compile_figure(_merge_figure(joint="arrow").spec)
    net = compiled.routed.net("combined")
    joint = net.target_stems[0].centerline[0]
    root = ET.fromstring(compiled.document.text)
    assert not [
        item
        for item in root.iter(f"{{{SVG_NS}}}circle")
        if (item.get("id") or "").startswith("combined.junction.")
    ], "an arrowhead stands in for the dot it replaces"
    rails = {
        item.get("id", ""): item
        for item in root.iter(f"{{{SVG_NS}}}path")
        if (item.get("id") or "").startswith("combined.rail")
    }
    assert set(rails) == {"combined.rail.1", "combined.rail.2"}
    # Every piece is drawn toward the joint, so its marker points into the trunk.
    assert all(rail.get("marker-end") == "url(#arrow.flow)" for rail in rails.values())
    reach = _STYLE.arrow_length.points + _STYLE.connector_standoff.points
    tips = sorted(float(rail.get("d", "").rsplit(" ", 1)[-1]) for rail in rails.values())
    assert tips == [
        pytest.approx(joint.y - reach),
        pytest.approx(joint.y + reach),
    ], "each approach stops an arrow plus a standoff short of the trunk"
    arrival = _paths(compiled.document.text)["combined.target.1"]
    assert arrival.startswith(f"M {number(joint.x)} {number(joint.y)}")


def test_a_dot_joint_marks_the_branch_even_when_the_style_never_dots() -> None:
    """``joint="dot"`` is an authored mark, so it outranks the style token."""

    style = STYLES["paper"].with_updates(junction_dots="never")
    quiet = compile_figure(_merge_figure().spec, style=style)
    assert "combined.junction.1" not in quiet.document.text
    forced = compile_figure(_merge_figure(joint="dot").spec, style=style)
    assert 'id="combined.junction.1"' in forced.document.text


def test_connectors_paint_after_the_components_they_join() -> None:
    """A run entering a container must not vanish under the container fill."""

    root = ET.fromstring(_compiled().document.text)
    layers = {item.get("id"): item for item in root.iter() if item.get("id")}
    order = [child.get("id") for child in layers["m"]]
    assert order.index("m.components") < order.index("m.connectors")


def _element(document: str, element_id: str) -> ET.Element:
    root = ET.fromstring(document)
    return next(item for item in root.iter() if item.get("id") == element_id)


def _painted_figure(**paint_options: object) -> str:
    figure = Figure("painted", width=pt(240.0))
    with figure.module("m", label="Attention module", **paint_options) as module:
        module.mlp("mlp", label="MLP", paint={"label": "#9fe1cb"})
        module.block("body", label="Body", paint={"fill": "#085041", "stroke": "#56bb9a"})
    return compile_figure(figure.spec).document.text


def test_paint_overrides_a_body_with_literal_colour_and_no_role() -> None:
    """Author paint must survive retheme, as preset vector cells do."""

    document = _painted_figure()
    body = _element(document, "m.body.body")
    assert body.get("fill") == "#085041"
    assert body.get("stroke") == "#56bb9a"
    assert body.get("data-flexo-fill") is None
    assert body.get("data-flexo-stroke") is None
    themed = retheme_svg(document, GRAYSCALE_PALETTE)
    assert _element(themed, "m.body.body").get("fill") == "#085041"
    assert _element(themed, "m.body.body").get("stroke") == "#56bb9a"


def test_paint_overrides_label_text_only() -> None:
    """The reference panel's mint MLP caption on its dark teal body."""

    document = _painted_figure()
    label = _element(document, "m.mlp.label")
    assert label.get("fill") == "#9fe1cb"
    assert label.get("data-flexo-fill") is None
    body = _element(document, "m.mlp.body")
    assert body.get("data-flexo-fill") == "block-fill", "only the label was overridden"
    assert body.get("fill") == DEFAULT_PALETTE.get("block-fill")
    assert _element(document, "m.body.label").get("data-flexo-fill") == "ink"
    assert _element(retheme_svg(document, GRAYSCALE_PALETTE), "m.mlp.label").get(
        "fill"
    ) == "#9fe1cb"


def test_paint_normalizes_short_hex_and_rejects_the_rest() -> None:
    figure = Figure("painted", width=pt(240.0))
    with figure.module("m") as module:
        module.block("body", label="Body", paint={"fill": "#ABC"})
        with pytest.raises(ValueError, match="valid parts: fill, stroke, label"):
            module.block("bad", label="Bad", paint={"body": "#123456"})
        with pytest.raises(ValueError, match="invalid colour"):
            module.block("worse", label="Worse", paint={"fill": "teal"})
    assert _element(compile_figure(figure.spec).document.text, "m.body.body").get(
        "fill"
    ) == "#aabbcc"


def test_a_group_title_may_be_anchored_right() -> None:
    left = _painted_figure()
    right = _painted_figure(title_side="right")
    title = _element(right, "m.label")
    assert title.get("text-anchor") == "end"
    assert _element(left, "m.label").get("text-anchor") is None
    group = _element(right, "m.container")
    padding = STYLES["paper"].group_padding.points
    edge = float(group.get("x", "0")) + float(group.get("width", "0"))
    assert float(title.get("x", "0")) == pytest.approx(edge - padding)
    assert float(title.get("y", "0")) == pytest.approx(
        float(_element(left, "m.label").get("y", "0"))
    ), "the title stays on its own baseline; only the anchor end moves"
    # Paint, not layout: nothing but the title itself may move.
    for element_id in ("m.container", "m.mlp.body", "m.body.body", "canvas.background"):
        assert _element(left, element_id).attrib == _element(right, element_id).attrib


def test_a_motif_may_be_suppressed_without_moving_anything() -> None:
    def _document(**options: object) -> str:
        figure = Figure("motifs", width=pt(260.0))
        with figure.module("m", gap="24pt") as module:
            module.mlp("mlp", label="MLP", **options)
            module.matrix("grid", label="Attention", **options)
        return compile_figure(figure.spec).document.text

    drawn = _document()
    plain = _document(motif=False)
    assert _element(drawn, "m.mlp.motif") is not None
    for motif_id in ("m.mlp.motif", "m.grid.grid"):
        root = ET.fromstring(plain)
        assert not [item for item in root.iter() if item.get("id") == motif_id]
    assert _element(plain, "m.mlp.body").attrib == _element(drawn, "m.mlp.body").attrib
    assert _element(plain, "m.mlp.label").attrib == _element(drawn, "m.mlp.label").attrib
