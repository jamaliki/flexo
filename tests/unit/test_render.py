from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from flexo.builder import Figure
from flexo.compiler import Compilation, compile_figure
from flexo.components import INSET_INK, motif_area, vector_grid
from flexo.geometry import Side
from flexo.ir.semantic import PortSpec, TextRun
from flexo.lint import lint_compilation
from flexo.render_common import SHADOW_LAYERS
from flexo.style import DEFAULT_PALETTE, GRAYSCALE_PALETTE, STYLES, Palette, VectorPreset
from flexo.svg import SVG_NS, number
from flexo.text import SHIFTED_SIZE, TextMeasurer
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


_TITLE = (
    TextRun("QK"),
    TextRun("T", baseline_shift="super"),
    TextRun("-attention", weight=700),
)
"""A group title that exercises every axis a run has: shift, weight, plain."""


def _titled_figure(title: tuple[TextRun, ...] = _TITLE, **options: object) -> str:
    figure = Figure("titled", width=pt(240.0))
    with figure.module("m", label=title, **options) as module:
        module.mlp("mlp", label="MLP")
    return compile_figure(figure.spec).document.text


def test_a_group_title_keeps_its_styled_runs() -> None:
    """A title is styled text: a superscript must reach the SVG, not flatten.

    Group titles used to be joined into one plain string, so ``QK^T`` came out as
    ``QKT`` -- the one text object in the figure that silently dropped what its
    author wrote.
    """

    title = _element(_titled_figure(), "m.label")
    spans = list(title)
    assert [span.text for span in spans] == ["QK", "T", "-attention"]
    assert [span.get("baseline-shift") for span in spans] == [None, "super", None]
    shifted = STYLES["paper"].typography.size.points * SHIFTED_SIZE
    assert [span.get("font-size") for span in spans] == [None, number(shifted), None]


def test_a_title_run_inherits_the_title_weight_unless_it_asks() -> None:
    """The weight is declared once on the text object, so runs may inherit it.

    Spelling ``font-weight="400"`` onto every run would unbold every title in
    every figure -- which is why a run emits a weight only where its author
    asked for one.
    """

    title = _element(_titled_figure(), "m.label")
    assert title.get("font-weight") == str(STYLES["paper"].typography.title_weight)
    weights = [span.get("font-weight") for span in title]
    assert weights == [None, None, "700"], "only the bold run overrides the title"
    # A component label declares no weight, so its plain runs stay unadorned.
    plain = _element(_titled_figure(), "m.mlp.label")
    assert plain.get("font-weight") is None
    assert [span.get("font-weight") for span in plain] == [None]
    assert [span.get("font-style") for span in plain] == [None]


def test_a_group_takes_paint_the_way_a_component_does() -> None:
    """``paint=`` has to reach the container body and its title, not just nodes."""

    document = _titled_figure(paint={"fill": "#085041", "stroke": "#56bb9a", "label": "#9fe1cb"})
    container = _element(document, "m.container")
    assert container.get("fill") == "#085041"
    assert container.get("stroke") == "#56bb9a"
    assert container.get("data-flexo-fill") is None
    assert container.get("data-flexo-stroke") is None
    title = _element(document, "m.label")
    assert title.get("fill") == "#9fe1cb"
    assert title.get("data-flexo-fill") is None
    # An overridden part carries no role, so retheme walks straight past it.
    themed = retheme_svg(document, GRAYSCALE_PALETTE)
    assert _element(themed, "m.container").get("fill") == "#085041"
    assert _element(themed, "m.container").get("stroke") == "#56bb9a"
    assert _element(themed, "m.label").get("fill") == "#9fe1cb"


def test_a_group_part_left_out_keeps_its_role() -> None:
    document = _titled_figure(paint={"fill": "#085041"})
    container = _element(document, "m.container")
    assert container.get("data-flexo-fill") is None
    assert container.get("data-flexo-stroke") == "container-stroke"
    assert container.get("stroke") == DEFAULT_PALETTE.get("container-stroke")
    title = _element(document, "m.label")
    assert title.get("data-flexo-fill") == "ink"
    assert title.get("fill") == DEFAULT_PALETTE.get("ink")


def test_group_paint_is_paint_only() -> None:
    """Recolouring a container may not move it, or anything inside it."""

    plain = _titled_figure()
    painted = _titled_figure(paint={"fill": "#085041", "label": "#9fe1cb"})
    for element_id in ("m.mlp.body", "m.mlp.label", "canvas.background"):
        assert _element(plain, element_id).attrib == _element(painted, element_id).attrib
    for name in ("x", "y", "width", "height", "rx"):
        assert _element(plain, "m.container").get(name) == _element(
            painted, "m.container"
        ).get(name)


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


def _add_norm_figure(label: str = "Add LN", **options: object) -> Figure:
    figure = Figure("norms", width=pt(260.0))
    with figure.module("m", gap="24pt") as module:
        module.add_norm("norm", label=label, **options)
    return figure


def _norm_motifs(document: str) -> list[ET.Element]:
    root = ET.fromstring(document)
    return [item for item in root.iter() if item.get("id") == "m.norm.motif"]


def test_an_add_norm_draws_its_label_and_nothing_else() -> None:
    """R24: an add-norm is a named box.

    The circled plus of R23 was ornament the figure never asked for -- the words
    already say what the box does -- so add-norm draws no motif at all, and its
    label sits on the box's own centre like every other block's.
    """

    compilation = compile_figure(_add_norm_figure().spec)
    document = compilation.document.text
    assert _norm_motifs(document) == []
    body = _element(document, "m.norm.body")
    centre = float(body.get("x", "0")) + float(body.get("width", "0")) / 2.0
    assert float(_element(document, "m.norm.label").get("x", "0")) == pytest.approx(centre)


def test_an_add_norm_reserves_no_width_beside_its_label() -> None:
    """Nothing is set beside the words, so nothing widens the box for it."""

    label = "Add + norm"
    drawn = compile_figure(_add_norm_figure(label).spec).fitted.node("m.norm").bounds
    plain = compile_figure(
        _add_norm_figure(label, motif=False).spec
    ).fitted.node("m.norm").bounds
    assert drawn.width == pytest.approx(plain.width)
    assert drawn.height == pytest.approx(plain.height)


def _shadow_figure(*, shadow: bool) -> Figure:
    figure = Figure("shadows", width=pt(220.0))
    with figure.module("m", gap="18pt", shadow=shadow) as module:
        module.block("box", label="Box", shadow=shadow)
    return figure


def _shadow_rects(document: str, entity_id: str) -> list[ET.Element]:
    root = ET.fromstring(document)
    group = next(
        (item for item in root.iter() if item.get("id") == f"{entity_id}.shadow"),
        None,
    )
    return list(group) if group is not None else []


def test_a_shadow_is_pure_vector_geometry_and_no_filter() -> None:
    """R24: Inkscape rasterizes filtered regions on PDF export, so no filter is used."""

    document = compile_figure(_shadow_figure(shadow=True).spec).document.text
    assert "filter" not in document and "feDropShadow" not in document
    layers = _shadow_rects(document, "m")
    assert len(layers) == SHADOW_LAYERS
    assert {layer.tag for layer in layers} == {f"{{{SVG_NS}}}rect"}
    assert {layer.get("data-flexo-fill") for layer in layers} == {"shadow"}


def test_a_shadow_nests_its_layers_and_offsets_them_below_the_box() -> None:
    """Each layer reaches less far than the last, which is what grades the falloff."""

    compilation = compile_figure(_shadow_figure(shadow=True).spec)
    bounds = compilation.fitted.group("m").bounds
    layers = _shadow_rects(compilation.document.text, "m")
    widths = [float(layer.get("width", "0")) for layer in layers]
    assert widths == sorted(widths, reverse=True), "outermost first, tightest last"
    assert widths[0] == pytest.approx(bounds.width + 2.0 * _STYLE.shadow_spread.points)
    top = float(layers[-1].get("y", "0")) + float(layers[-1].get("height", "0")) / 2.0
    assert top > bounds.center.y, "offset below the box, never centred on it"
    # Subtle: every layer is faint, and the stack composites to the authored value.
    opacities = [float(layer.get("opacity", "1")) for layer in layers]
    composed = 1.0
    for opacity in opacities:
        composed *= 1.0 - opacity
    # Rounded to the SVG's own precision, so compare at that precision.
    assert 1.0 - composed == pytest.approx(_STYLE.shadow_opacity, rel=1e-3)
    assert max(opacities) < _STYLE.shadow_opacity


def test_a_shadow_shows_along_the_bottom_and_right_edges_only() -> None:
    """R24: the light comes from the top left, so a shadow is not a halo.

    Geometry, not clipping: the widest layer starts on the box's own top-left
    corner and every tighter one starts further in, so no layer can put ink above
    the top edge or left of the left edge whatever the corner radius is.
    """

    compilation = compile_figure(_shadow_figure(shadow=True).spec)
    for entity_id in ("m", "m.box"):
        bounds = (
            compilation.fitted.group("m").bounds
            if entity_id == "m"
            else compilation.fitted.node("m.box").bounds
        )
        layers = _shadow_rects(compilation.document.text, entity_id)
        assert layers, entity_id
        for layer in layers:
            x = float(layer.get("x", "0"))
            y = float(layer.get("y", "0"))
            assert x >= bounds.x - 1e-6, f"{entity_id}: shadow ink left of the box"
            assert y >= bounds.y - 1e-6, f"{entity_id}: shadow ink above the box"
            assert x + float(layer.get("width", "0")) > bounds.right, "reaches right"
            assert y + float(layer.get("height", "0")) > bounds.bottom, "reaches below"


def test_nothing_casts_a_shadow_unless_it_asks_to() -> None:
    document = compile_figure(_shadow_figure(shadow=False).spec).document.text
    assert _shadow_rects(document, "m") == []
    assert _shadow_rects(document, "m.box") == []


def test_a_shadow_rethemes_by_role_like_every_other_paint() -> None:
    document = compile_figure(_shadow_figure(shadow=True).spec).document.text
    assert DEFAULT_PALETTE.get("shadow") in document
    assert GRAYSCALE_PALETTE.get("shadow") in retheme_svg(document, GRAYSCALE_PALETTE)


def _inset_figure(label: str, **options: object) -> Figure:
    figure = Figure("insets", width=pt(260.0))
    with figure.module("m", gap="18pt") as module:
        module.inset("i", label=label, **options)
    return figure


def _ink_box(document: str, element_id: str) -> tuple[float, float, float, float]:
    """The extent of one motif group, as (left, top, right, bottom).

    Read off the primitives rather than off a renderer, so the assertion is about
    the geometry Flexo emitted and not about how something rasterizes it.
    """

    root = ET.fromstring(document)
    group = next(item for item in root.iter() if item.get("id") == element_id)
    left = top = float("inf")
    right = bottom = float("-inf")
    for item in group.iter():
        tag = item.tag.rsplit("}", 1)[-1]
        if tag == "circle":
            cx, cy = float(item.get("cx", "0")), float(item.get("cy", "0"))
            radius = float(item.get("r", "0"))
            box = (cx - radius, cy - radius, cx + radius, cy + radius)
        elif tag == "rect":
            x, y = float(item.get("x", "0")), float(item.get("y", "0"))
            box = (x, y, x + float(item.get("width", "0")), y + float(item.get("height", "0")))
        else:
            continue
        left, top = min(left, box[0]), min(top, box[1])
        right, bottom = max(right, box[2]), max(bottom, box[3])
    return left, top, right, bottom


@pytest.mark.parametrize("label", ["Centre cube", "Edge\nrectangles"])
def test_an_inset_keeps_its_label_out_of_its_illustration(label: str) -> None:
    """R24: the caption owns a band at the top and the molecule what is left.

    The defect this replaces: "Edge rectangles" was centred at a fraction of the
    box height and the molecule at another, so a two-line label was drawn through
    the drawing it named.
    """

    compilation = compile_figure(_inset_figure(label).spec)
    node = compilation.fitted.node("m.i")
    metrics = node.measured.label
    _, top, _, _ = _ink_box(compilation.document.text, "m.i.illustration")
    band_bottom = node.bounds.y + _STYLE.padding_y.points + metrics.height
    assert top >= band_bottom + _STYLE.motif_label_gap.points - 1e-6
    assert top > node.bounds.y + metrics.height, "clear of the words by any reading"
    assert lint_compilation(compilation).ok


def test_a_squeezed_inset_shrinks_its_illustration_instead_of_colliding() -> None:
    """An authored height too small for both is the drawing's problem, not the words'."""

    compilation = compile_figure(_inset_figure("Edge\nrectangles", height="40pt").spec)
    node = compilation.fitted.node("m.i")
    left, top, right, bottom = _ink_box(compilation.document.text, "m.i.illustration")
    assert bottom - top < INSET_INK.height, "scaled down to the room it has"
    assert right - left < INSET_INK.width, "and scaled, not cropped"
    assert (right - left) / (bottom - top) == pytest.approx(
        INSET_INK.width / INSET_INK.height
    ), "aspect preserved"
    band = node.bounds.y + _STYLE.padding_y.points + node.measured.label.height
    assert top >= band + _STYLE.motif_label_gap.points - 1e-6, "still under the band"
    assert bottom <= node.bounds.bottom, "and still inside the box"


def test_every_motif_label_kind_draws_below_its_label_band() -> None:
    """One band model, so no kind can grow a collision of its own.

    ``sequence`` is the near miss that proves it: its dots sat a fixed distance
    off the bottom edge, which happened to clear a one-line label in a box of the
    default height and nothing else.
    """

    figure = Figure("motifs", width=pt(420.0))
    with figure.module("m", gap="16pt") as module:
        sequence = module.sequence("seq", label="Sequence\nof residues", tokens=6)
        graph = module.graph("g", label="Distances to\nQ points")
        module.concat("cat", label="Concat\ntwo ways", inputs=[sequence, graph])
        module.feature_strip("strip", label="Feature\nstrip", cells=5)
    compilation = compile_figure(figure.spec)
    for node_id, motif_id in (
        ("m.seq", "m.seq.tokens"),
        ("m.g", "m.g.network"),
        ("m.cat", "m.cat.motif"),
        ("m.strip", "m.strip.cells"),
    ):
        node = compilation.fitted.node(node_id)
        area = motif_area(node.measured.spec.kind, node.bounds, node.measured.label, _STYLE)
        left, top, right, bottom = _ink_box(compilation.document.text, motif_id)
        assert top >= area.y - 1e-6, f"{motif_id} rises into the label band"
        assert bottom <= area.bottom + 1e-6, f"{motif_id} spills past its area"
        assert left >= area.x - 1e-6 and right <= area.right + 1e-6, f"{motif_id} too wide"
    assert lint_compilation(compilation).ok


def test_a_title_band_is_measured_at_the_weight_the_title_draws_at() -> None:
    """R27: measured at 400 and drawn at 600 reserved a band too narrow.

    The title is the one text object whose weight comes from the style rather
    than from its runs, so it was the one measured at a weight it never used.
    """

    title = (TextRun("Sequence module"),)
    figure = Figure("band", width=pt(240.0))
    with figure.module("m", label=title) as module:
        module.block("tiny", label="x", width="20pt")
    compilation = compile_figure(figure.spec)
    metrics = compilation.measured.group("m").label
    measurer = TextMeasurer(_STYLE.typography)
    assert metrics.width == pytest.approx(
        measurer.measure(title, weight=_STYLE.typography.title_weight).width
    )
    assert metrics.width > measurer.measure(title).width
    # And the band that measurement reserves holds the words it is measured for.
    module_bounds = compilation.fitted.group("m").bounds
    padding = compilation.measured.group("m").spec.layout.resolved_padding(
        _STYLE.group_padding
    )
    assert module_bounds.width >= metrics.width + padding.horizontal
    report = lint_compilation(compilation)
    assert not report.errors, report.format()


def test_a_run_that_begins_with_a_space_still_sets_one() -> None:
    """XML strips a tspan's leading whitespace, so the run that owns it says preserve."""

    space = "{http://www.w3.org/XML/1998/namespace}space"
    title = (TextRun("QK", weight=700), TextRun(" module"))
    spans = list(_element(_titled_figure(title), "m.label"))
    assert [span.text for span in spans] == ["QK", " module"]
    assert [span.get(space) for span in spans] == [None, "preserve"]
    # Nothing else gains the attribute: a run with no edge whitespace is unchanged.
    plain = list(_element(_titled_figure(), "m.label"))
    assert [span.get(space) for span in plain] == [None, None, None]


def test_a_caption_role_paints_muted_ink_and_still_rethemes() -> None:
    """R28: the Q/K/V captions a composite grows are notes, not statements."""

    with (
        Figure("captions", width=pt(320.0)) as figure,
        figure.root.column("m", role="layout") as column,
    ):
        column.attention("mha", label="Attention", width=pt(120.0), vectors=True)
    document = compile_figure(figure.spec).document.text
    caption = _element(document, "m.mha.qkv.q.label.label")
    assert caption.get("fill") == DEFAULT_PALETTE.get("muted-ink")
    assert caption.get("data-flexo-fill") == "muted-ink", "a role, so retheme reaches it"
    assert _element(document, "m.mha.block.label").get("data-flexo-fill") == "ink"
    themed = retheme_svg(document, GRAYSCALE_PALETTE)
    assert _element(themed, "m.mha.qkv.q.label.label").get("fill") == GRAYSCALE_PALETTE.get(
        "muted-ink"
    )


def test_motif_less_attention_centres_its_label() -> None:
    """With no motif in the interior, the words centre in the box."""

    def label_y(motif: bool) -> tuple[float, float, float]:
        with Figure("t") as figure:
            figure.root.node(
                "att",
                "attention",
                label="Multi-Head Attention",
                width="120pt",
                motif=motif,
            )
        compilation = compile_figure(figure.spec)
        fitted = compilation.routed.fitted
        node = next(n for n in fitted.nodes if n.measured.spec.id == "att")
        svg = compilation.document.text
        match = re.search(r'<text[^>]*id="att.label"[^>]*y="([-0-9.]+)"', svg)
        assert match is not None
        return node.bounds.y, node.bounds.height, float(match.group(1))

    top, height, banded = label_y(True)
    top2, height2, centred = label_y(False)
    assert (top, height) == (top2, height2)  # motif=False changes no geometry
    assert banded < centred  # the banded label sits higher than the centred one
    mid = top + height / 2.0
    assert abs(centred - mid) < height / 4.0  # centred label straddles the middle
