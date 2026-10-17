"""A structure's part the size of its molecule as drawn (flexo.structure_fit)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import flexo
from flexo.compiler import compile_figure

DATA = Path(__file__).parent / "data"


def _group(drawing, identifier: str):
    from flexo.drawing import Group

    stack = [drawing.root]
    while stack:
        group = stack.pop()
        if group.id == identifier:
            return group
        stack += [item for item in group.items if isinstance(item, Group)]
    raise AssertionError(identifier)


def _ink(svg: str, identifier: str) -> tuple[float, float, float, float]:
    """Where what ``identifier`` paints lies on the page: left, top, right, bottom."""

    from flexo.drawing import Drawing, ink_bounds, read_drawing

    drawing = read_drawing(svg)
    return ink_bounds(Drawing(drawing.width, drawing.height, _group(drawing, identifier)))


def _nested(svg: str, identifier: str) -> dict[str, str]:
    """The attributes of the drawing nested in a flat molecule's group."""

    held = rf'<g [^>]*id="{re.escape(identifier)}"[^>]*>\s*<rect [^>]*/>\s*<svg ([^>]*)>'
    found = re.search(held, svg)
    assert found, identifier
    return dict(re.findall(r'([\w:-]+)="([^"]*)"', found.group(1)))


def test_lines_meet_a_molecule_whose_box_is_much_wider_than_it() -> None:
    """A molecule given a box three times as wide as it is drawn: its part is the molecule
    as drawn, at the scale the box draws it, so the lines on either side end at it -- a few
    points short, not at the box's sides a hundred points away."""

    pytest.importorskip("molsketch")
    with flexo.Figure("wide") as figure:
        row = figure.root.row("row", gap=30)
        before = row.block("before", label="Substrate")
        model = row.structure("model", DATA / "1a7g.cif", look="flat", width=360, height=90)
        after = row.block("after", label="Product")
        figure.connect(before, model)
        figure.connect(model, after)
    compiled = compile_figure(figure.spec)
    svg = compiled.document.text
    left, top, right, bottom = _ink(svg, "row.model.molecule")
    box = compiled.routed.fitted.node("row.model").bounds
    assert box.width < 200  # (drawn in 360 by 90, it is no wider than it is drawn)
    arriving = compiled.routed.edges[0].centerline[-1]
    leaving = compiled.routed.edges[1].centerline[0]
    assert 0 <= left - arriving.x < 4, (arriving, left)
    assert 0 <= leaving.x - right < 4, (leaving, right)
    assert top <= arriving.y <= bottom and top <= leaving.y <= bottom
    # Drawn as it was: in a canvas of 360 by 90, cut to the part that shows -- which the
    # studio is told of, to turn it and to size it by.
    nested = _nested(svg, "row.model.molecule")
    view = [float(value) for value in nested["viewBox"].split()]
    assert view[2] < 0.6 * 1200 and view[3] <= 300
    canvas = re.search(r'id="row.model.molecule"[^>]*data-flexo-canvas="([^"]+)"', svg)
    assert canvas and [round(float(value)) for value in canvas.group(1).split()][2:] == [360, 90]


def test_a_molecule_keeps_the_size_its_box_draws_it_at() -> None:
    """Laid out round its molecule, a structure is not drawn any larger or smaller: the
    molecule's ink is where, and as large as, it is in the box it was given."""

    pytest.importorskip("molsketch")
    from flexo.structure_fit import drawn_in

    with flexo.Figure("same") as figure:
        figure.root.row("row").structure("model", DATA / "1a7g.cif", look="flat", width=200,
                                         height=150)
    compiled = compile_figure(figure.spec)
    node = next(node for node in compiled.measured.semantic.nodes if node.id == "row.model")
    (width, height), (left, top, right, bottom) = drawn_in(node)
    assert (width, height) == (200, 150)
    nested = _nested(compiled.document.text, "row.model.molecule")
    view = [float(value) for value in nested["viewBox"].split()]
    # 1200 by 900 pixels in 200 by 150 points: six to the point, cut or not.
    assert float(nested["width"]) / view[2] == pytest.approx(1 / 6, rel=1e-3)
    assert view[0] == pytest.approx(left * 1200, abs=0.01)
    assert view[1] == pytest.approx(top * 900, abs=0.01)
    assert right - left < 1 or bottom - top < 1


def test_a_molecule_drawn_as_a_picture_is_cut_to_what_it_draws() -> None:
    pytest.importorskip("molsketch")
    import base64
    import struct

    with flexo.Figure("picture") as figure:
        figure.root.row("row").structure("model", DATA / "1a7g.cif", look="engraved-colour",
                                         width=300, height=90)
    compiled = compile_figure(figure.spec)
    svg = compiled.document.text
    found = re.search(r'<image [^>]*id="row.model.molecule"[^>]*>', svg)
    assert found
    attributes = dict(re.findall(r'([\w:-]+)="([^"]*)"', found.group(0)))
    png = base64.b64decode(attributes["href"].split(",", 1)[1])
    pixels_w, pixels_h = struct.unpack(">II", png[16:24])
    width, height = float(attributes["width"]), float(attributes["height"])
    assert width < 200 and height <= 90
    # The picture is the part shown: as many pixels as the canvas has to its points.
    assert pixels_w < 1200 and pixels_w / width == pytest.approx(1200 / 300, rel=0.02)
    assert pixels_h / height == pytest.approx(1200 / 300, rel=0.02)


def test_structures_sharing_a_frame_are_cut_alike_about_its_centre(tmp_path: Path) -> None:
    """A chain and a part of it, in one frame: each is drawn at the frame's scale about its
    centre, and cut to what they draw together -- boxes the same size, the same part of each
    canvas, so the atoms they share stay in the same place of each."""

    pytest.importorskip("molsketch")
    from flexo.structure_fit import drawn_in

    with flexo.Figure("framed") as figure:
        row = figure.root.row("row", gap=10)
        row.structure("whole", DATA / "1a7g.cif", look="flat", frame="f", width=160,
                      height=120, yaw=30, sticks="none")
        row.structure("part", DATA / "1a7g.cif", look="flat", frame="f", width=160,
                      height=120, yaw=30, sticks="none", cartoon="resi 300-320")
    compiled = compile_figure(figure.spec)
    nodes = {node.id: node for node in compiled.measured.semantic.nodes}
    whole, part = drawn_in(nodes["row.whole"]), drawn_in(nodes["row.part"])
    assert whole == part
    assert whole[1][2] - whole[1][0] < 0.95 or whole[1][3] - whole[1][1] < 0.95
    boxes = [compiled.routed.fitted.node(f"row.{name}").bounds for name in ("whole", "part")]
    assert boxes[0].width == pytest.approx(boxes[1].width)
    assert boxes[0].height == pytest.approx(boxes[1].height)
    # The part is drawn small, inside what the whole draws: one scale, not its own fit.
    svg = compiled.document.text
    inks = [_ink(svg, f"row.{name}.molecule") for name in ("whole", "part")]
    assert inks[1][2] - inks[1][0] < 0.8 * (inks[0][2] - inks[0][0])
    for name, ink in zip(("whole", "part"), inks, strict=True):
        box = compiled.routed.fitted.node(f"row.{name}").bounds
        assert box.x - 0.5 <= ink[0] and ink[2] <= box.x + box.width + 0.5


def test_given_one_size_a_molecule_takes_its_own_proportions() -> None:
    """Only a width: the molecule is drawn as large as that width lets it be -- as large as in
    a taller box of that width, and larger than in a shorter one -- in a canvas of its own
    proportions as it is seen, not the usual four by three; so for only a height."""

    pytest.importorskip("molsketch")
    from flexo.structure_fit import drawn_in

    def drawn(**size):
        with flexo.Figure("one") as figure:
            figure.root.row("row").structure("model", DATA / "1a7g.cif", look="flat", **size)
        compiled = compile_figure(figure.spec)
        node = next(node for node in compiled.measured.semantic.nodes if node.id == "row.model")
        bounds = compiled.routed.fitted.node("row.model").bounds
        return drawn_in(node)[0], (bounds.width, bounds.height)

    for given, view in (("width", {}), ("height", {}), ("width", {"yaw": 90, "pitch": 40})):
        at = 0 if given == "width" else 1
        free = "height" if given == "width" else "width"
        canvas, box = drawn(**{given: 150}, **view)
        assert canvas[at] == pytest.approx(150) and canvas[1 - at] != pytest.approx(150 * 3 / 4)
        _, roomier = drawn(**{given: 150, free: canvas[1 - at] * 1.3}, **view)
        _, tighter = drawn(**{given: 150, free: canvas[1 - at] * 0.8}, **view)
        assert box[at] == pytest.approx(roomier[at], abs=1.5), (given, view)
        assert tighter[at] < box[at] - 5, (given, view)
