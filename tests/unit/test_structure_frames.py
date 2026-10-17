"""Structures that share a frame: one camera, one scale, one centre (flexo.structure_frames)."""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

import flexo
from flexo.compiler import compile_figure
from flexo.diagnostics import Severity

DATA = Path(__file__).parent / "data"


def _turns():
    np = pytest.importorskip("numpy")
    from flexo.structure_frames import turned

    def turn(seed: int):
        rng = np.random.default_rng(seed)
        return turned(*rng.uniform(-180, 180, size=3))

    return np, turn


def _draws(points, base, camera, box):
    """Where mol-sketch draws ``points`` (the file's coordinates) of a molecule along ``base``
    with ``camera``, in a ``box`` of points -- its computeFit and makeProjector, as written in
    its classic engine -- as points from the box's middle, x right and y down."""

    import numpy as np

    from flexo.structure_frames import _canvas, _points_per_pixel, turned

    scene = points @ base.T
    middle = (scene.min(axis=0) + scene.max(axis=0)) / 2
    seen = (scene - middle) @ turned(camera["yaw"], camera["pitch"], camera["roll"]).T
    low, high = seen.min(axis=0), seen.max(axis=0)
    rx, ry = (low[0] + high[0]) / 2, (low[1] + high[1]) / 2
    spans = np.maximum(high - low, 1)
    width, height = _canvas(box)
    opening = camera["fov"] * math.pi / 180
    reach = max(spans[0], spans[1]) / 2 + 1.5
    eye = reach / math.tan(opening / 2) if opening > 2e-3 else math.inf
    nearer = 1 if eye == math.inf else eye / max(eye - spans[2] / 2, eye * 0.3)
    pixels = min(width * 0.9 / (spans[0] + 2.6), (height - 24) / (spans[1] + 2.4)) * camera[
        "zoom"
    ] / nearer**0.7
    d = np.ones(len(seen)) if eye == math.inf else np.clip(eye / (eye - seen[:, 2]), 0.2, 4)
    x = (seen[:, 0] - rx) * pixels * d + camera["panX"] * width
    y = -(seen[:, 1] - ry) * pixels * d + camera["panY"] * height
    return np.stack([x, y], axis=1) * _points_per_pixel(box)


def _molecules(np, turn):
    """A protein (an ellipsoid of points) and the noise it was made from (a ball), around the
    same motif held fixed, each along axes of its own -- as mol-sketch starts each along its
    principal axes."""

    rng = np.random.default_rng(7)
    motif = rng.normal(size=(6, 3)) * 2.0 + [3.0, -2.0, 1.0]
    protein = np.concatenate([rng.normal(size=(400, 3)) * [15.0, 9.0, 6.0], motif])
    ball = np.concatenate([rng.normal(size=(400, 3)) * 5.0, motif])
    return motif, (protein, turn(1)), (ball, turn(2))


CAMERA = {"yaw": 20.0, "pitch": -10.0, "roll": 5.0, "zoom": 1.0, "panX": 0.0, "panY": 0.0}


def test_a_turn_is_read_back_as_the_angles_that_make_it() -> None:
    np, turn = _turns()
    from flexo.structure_frames import angles, turned

    for seed in range(20):
        matrix = turn(seed)
        assert np.allclose(turned(*angles(matrix)), matrix, atol=1e-9)
    # Looked at straight down, the yaw is the roll.
    assert np.allclose(turned(*angles(turned(30, 90, 0))), turned(30, 90, 0), atol=1e-9)


@pytest.mark.parametrize("fov", [0.0, 20.0])
def test_a_frame_of_one_is_drawn_as_it_is_alone(fov: float) -> None:
    np, turn = _turns()
    from flexo.structure_frames import angles, framing, member_camera, turned

    _, (protein, base), _ = _molecules(np, turn)
    camera = {**CAMERA, "zoom": 1.4, "panX": 0.05, "panY": -0.1, "fov": fov}
    box = (130.0, 100.0)
    own = member_camera(framing(camera, base, box, [(protein, base, box)]), protein, base, box)
    assert np.allclose(turned(own["yaw"], own["pitch"], own["roll"]),
                       turned(*angles(turned(20.0, -10.0, 5.0))))
    for key in ("zoom", "panX", "panY", "fov"):
        assert own[key] == pytest.approx(camera[key], abs=1e-9)


def test_a_frame_draws_its_members_with_one_camera_at_one_scale_about_one_centre() -> None:
    """The motif both hold lands in the same place in each, at the same scale, though each
    lies along axes of its own: mol-sketch, drawing each with the camera the frame gives it,
    puts it there."""

    np, turn = _turns()
    from flexo.structure_frames import framing, member_camera

    _, (protein, along), (ball, other) = _molecules(np, turn)
    box = (130.0, 130.0)
    camera = {**CAMERA, "fov": 0.0}
    members = [(ball, other, box), (protein, along, box)]
    frame = framing(camera, other, box, members)
    seen = []
    for points, base, size in members:
        drawn = member_camera(frame, points, base, size)
        seen.append(_draws(points, base, drawn, size))
    # (The motif is the last six points of each.)
    assert np.allclose(seen[0][-6:], seen[1][-6:], atol=1e-6)
    # Its noise drawn small: the protein fills its box, the ball does not.
    reach = [np.abs(points).max() for points in seen]
    assert 50 < reach[1] < 65
    assert reach[0] < 0.55 * reach[1]
    # Its owner -- the ball -- drawn as it is turned alone: its own turn kept.
    own = member_camera(frame, ball, other, box)
    assert (own["yaw"], own["pitch"], own["roll"]) == pytest.approx((20.0, -10.0, 5.0))


def test_a_frame_in_perspective_is_seen_from_one_eye() -> None:
    np, turn = _turns()
    from flexo.structure_frames import framing, member_camera

    _, (protein, along), (ball, other) = _molecules(np, turn)
    box = (130.0, 130.0)
    camera = {**CAMERA, "fov": 20.0}
    members = [(ball, other, box), (protein, along, box)]
    frame = framing(camera, other, box, members)
    drawn = [_draws(points, base, member_camera(frame, points, base, size), size)
             for points, base, size in members]
    # Off the frame's centre, by a share of the perspective at most: a hundredth of the box.
    assert np.abs(drawn[0][-6:] - drawn[1][-6:]).max() < 0.01 * 130


def _subset(tmp_path: Path, last: int) -> Path:
    """1A7G's chain up to residue ``last``, in a file of its own: along other axes than the
    whole (mol-sketch's start, its principal axes), its atoms where the whole has them."""

    gemmi = pytest.importorskip("gemmi")
    structure = gemmi.read_structure(str(DATA / "1a7g.cif"))
    structure.remove_ligands_and_waters()
    for chain in structure[0]:
        for index in reversed(range(len(chain))):
            if chain[index].seqid.num > last:
                del chain[index]
    out = tmp_path / f"upto{last}.pdb"
    structure.write_pdb(str(out))
    return out


def _framed_figure(tmp_path: Path, **properties: object):
    whole = tmp_path / "1a7g.cif"
    shutil.copy(DATA / "1a7g.cif", whole)
    part = _subset(tmp_path, 320)
    with flexo.Figure("framed") as figure:
        row = figure.root.row("row", gap=10)
        row.structure("part", part, look="flat", frame="fold", width=100, height=100,
                      sticks="none", yaw=30, pitch=10, **properties)
        row.structure("whole", whole, look="flat", frame="fold", width=100, height=100,
                      sticks="none")
    return figure.spec


def _mark(node, style, atom: str):
    """Where mol-sketch draws ``atom`` of the structure ``node`` (as the frame has it drawn): a
    mark pinned there, found on the drawing, in its pixels."""

    np = pytest.importorskip("numpy")
    from flexo.structure_frames import _box, _canvas
    from flexo.structures import _ask, _drawn, _one_at_a_time
    from flexo.style import Palette

    ask = _ask(node, style, Palette("marking", {"canvas": "#ffffff", "ink": "#000000"}))

    def draw():
        figure = _drawn(ask)
        figure.label("●", at=atom, offset=(0, 0), size=0.6)
        figure.set(palette={"label": "#ff00ff"})
        return figure.render(_canvas(_box(node, style)), scale=1.0).to_numpy()

    rgb = _one_at_a_time(draw)[..., :3].astype(int)
    found = (abs(rgb[..., 0] - 255) < 40) & (rgb[..., 1] < 60) & (abs(rgb[..., 2] - 255) < 40)
    ys, xs = np.nonzero(found)
    return float(xs.mean()), float(ys.mean())


def test_structures_in_a_frame_are_drawn_by_mol_sketch_with_their_atoms_where_it_puts_them(
    tmp_path: Path,
) -> None:
    """Part of a chain and the whole of it, each in a file of its own (so each along axes of its
    own, as mol-sketch starts them): in one frame, mol-sketch draws the atoms they share in the
    same places of their boxes -- turned as the first is, at one scale, about one centre."""

    pytest.importorskip("molsketch")
    from flexo.structure_frames import framed
    from flexo.themes import figure_style

    spec = _framed_figure(tmp_path)
    style = figure_style(spec)
    drawn = {node.id: node for node in framed(spec, style).nodes}
    # Each turned its own way to be seen the frame's way; the part, alone, as it was turned.
    assert drawn["row.part"].property("yaw") == pytest.approx(30)
    assert drawn["row.whole"].property("yaw") != pytest.approx(30)
    for atom in ("ILE295:CA", "TYR310:CA"):
        here, there = _mark(drawn["row.part"], style, atom), _mark(drawn["row.whole"], style, atom)
        assert math.dist(here, there) < 1.0, (atom, here, there)
    # Drawn as one, unchanged: the figure is drawn with them so.
    compiled = compile_figure(spec)
    assert 'id="row.part.molecule"' in compiled.document.text


def test_a_noised_series_in_a_frame_is_one_camera_in_the_files_coordinates(
    tmp_path: Path, monkeypatch
) -> None:
    """Copies of one file at noise 1, 0.3 and 0, a motif held: mol-sketch reads each noised
    molecule along its own axes and flexo turns it back to be seen as the file is -- in a
    frame, each is turned the frame's way the once, so the held atoms land in the same place
    of every box, and the studio turns them all from the frame's own turn."""

    pytest.importorskip("molsketch")
    np = pytest.importorskip("numpy")
    from flexo import structure_noise
    from flexo.serialization import figure_to_document
    from flexo.structure_frames import framed
    from flexo.studio.figure_kind import FigureKind
    from flexo.themes import figure_style

    monkeypatch.setattr(structure_noise, "_cache_folder", lambda: tmp_path / "noise")
    with flexo.Figure("noised") as figure:
        row = figure.root.row("row", gap=10)
        for name, noise in (("t100", 1.0), ("t30", 0.3), ("t0", None)):
            row.structure(name, DATA / "1a7g.cif", look="flat", frame="run", width=100,
                          height=100, sticks="none", noise=noise, fixed="resi 300+310",
                          seed=4, **({"yaw": 30, "pitch": 10} if name == "t100" else {}))
    spec = figure.spec
    style = figure_style(spec)
    drawn = {node.id: node for node in framed(spec, style).nodes}
    # One file, so one turn read against its axes for every copy: the frame's.
    for node in drawn.values():
        turn = [node.property(name) for name in ("yaw", "pitch", "roll")]
        assert turn == pytest.approx([30, 10, 0], abs=1e-4), node.id
    for atom in ("GLY300:CA", "TYR310:CA"):
        seen = [_mark(drawn[f"row.{name}"], style, atom) for name in ("t100", "t30", "t0")]
        assert max(math.dist(seen[0], other) for other in seen[1:]) < 1.0, (atom, seen)
    # The studio: the frame's turn, the file's axes, its points in the file's coordinates.
    text = json.dumps(figure_to_document(spec))
    views = {
        name: FigureKind().act({"text": text, "suffix": ".json"},
                               {"do": "structure-view", "id": f"row.{name}"}, tmp_path)["view"]
        for name in ("t30", "t0")
    }
    assert (views["t30"]["camera"]["yaw"], views["t30"]["camera"]["pitch"]) == (30, 10)
    assert views["t30"]["alone"] == {"yaw": 30, "pitch": 10, "roll": 0}
    assert np.allclose(views["t30"]["base"], views["t0"]["base"], atol=1e-5)
    assert np.allclose(views["t30"]["shared"]["base"], views["t0"]["base"], atol=1e-5)
    near = np.array([p for chain in views["t30"]["chains"] for p in chain])
    assert near.shape[1] == 3 and np.isfinite(near).all()


def test_a_frames_settings_are_its_firsts_and_anothers_own_are_said_unused(
    tmp_path: Path,
) -> None:
    from flexo.structure_frames import frame_problems, frames_of

    spec = _framed_figure(tmp_path)
    assert [node.id for node in frames_of(spec)["fold"]] == ["row.part", "row.whole"]
    assert frame_problems(spec) == []
    nodes = list(spec.nodes)
    nodes[1] = replace(nodes[1], properties=(*nodes[1].properties, ("zoom", 2.0), ("yaw", 30.0)))
    said = frame_problems(replace(spec, nodes=tuple(nodes)))
    assert [item.code for item in said] == ["structure.frame"]
    assert said[0].severity is Severity.WARNING and said[0].entity_id == "row.whole"
    assert "zoom is not used" in said[0].message and "row.part, the first" in said[0].message


def test_the_studio_turns_a_frame_from_any_of_its_structures(tmp_path: Path) -> None:
    """Asked what to turn while one is dragged round, the studio is told the frame's turn (its
    first's), the structure's points in the frame's coordinates, the frame's members, and the
    turn it would be drawn with alone to be seen as it is."""

    pytest.importorskip("molsketch")
    np = pytest.importorskip("numpy")
    from flexo.serialization import figure_to_document
    from flexo.structure_frames import turned
    from flexo.studio.figure_kind import FigureKind

    text = json.dumps(figure_to_document(_framed_figure(tmp_path)))
    view = FigureKind().act({"text": text, "suffix": ".json"},
                            {"do": "structure-view", "id": "row.whole"}, tmp_path)["view"]
    assert view["shared"]["name"] == "fold"
    assert view["shared"]["members"] == ["row.part", "row.whole"]
    assert view["shared"]["owner"] == "row.part"
    assert (view["camera"]["yaw"], view["camera"]["pitch"]) == (30, 10)
    base, frame = np.array(view["base"]), np.array(view["shared"]["base"])
    alone = view["alone"]
    # Alone, turned so: seen as the frame sees it.
    assert np.allclose(turned(alone["yaw"], alone["pitch"], alone["roll"]) @ base,
                       turned(30, 10, 0) @ frame, atol=2e-3)
    assert len(view["fit"]) >= 6 and view["chains"]
    part = FigureKind().act({"text": text, "suffix": ".json"},
                            {"do": "structure-view", "id": "row.part"}, tmp_path)["view"]
    assert part["alone"] == {"yaw": 30, "pitch": 10, "roll": 0}


def test_a_structures_name_can_stand_under_it() -> None:
    pytest.importorskip("molsketch")
    from flexo.ir.semantic import NodeSpec
    from flexo.structures import title_side_problem

    def placed(**options: object):
        with flexo.Figure("named") as figure:
            figure.root.structure("model", DATA / "1a7g.cif", label="[t]{italic} = 0", width=90,
                                  height=80, **options)
        compiled = compile_figure(figure.spec)
        node = compiled.routed.fitted.node("model")
        return compiled.document.text, node.bounds

    over, bounds = placed()
    under, same = placed(title_side="bottom")
    assert same.height == pytest.approx(bounds.height)

    def y_of(svg: str, identifier: str) -> float:
        import re

        found = re.search(rf'id="{re.escape(identifier)}"[^>]*?\sy="([-\d.]+)"', svg)
        assert found, identifier
        return float(found.group(1))

    assert y_of(over, "model.label") < y_of(over, "model.molecule")
    assert y_of(under, "model.label") > y_of(under, "model.molecule") + 80
    # Its t in italics, as a label's words are given a slant.
    assert 'font-style="italic">t</tspan>' in under
    wrong = NodeSpec("model", kind="structure", properties=(("title_side", "left"),))
    said = title_side_problem(wrong)
    assert said is not None and said.code == "structure.title-side"
    assert title_side_problem(replace(wrong, properties=(("title_side", "bottom"),))) is None


def test_python_names_a_structures_frame_and_where_its_name_stands() -> None:
    with flexo.Figure("named") as figure:
        figure.root.structure("model", "1ubq", frame="run", title_side="bottom")
    node = figure.spec.nodes[0]
    assert node.property("frame") == "run" and node.property("title_side") == "bottom"


# -- the studio's page (figure/structframes.js) --


def _page(code: str, **values: object) -> object:
    """``code`` run with the page's frames (``frames``) and figure parts (``parts``) at hand,
    each of ``values`` a constant of its name."""

    from test_pages import _studio

    given = "".join(f"const {name} = {json.dumps(value)};\n" for name, value in values.items())
    return _studio(
        "await (async () => {\n"
        'const frames = await import("/static/kinds/figure/structframes.js");\n'
        f"{given}{code}\n}})()"
    )


NODES = [
    {"id": "t100", "kind": "structure",
     "properties": {"source": "t100.pdb", "frame": "run", "yaw": 20}},
    {"id": "label", "kind": "text"},
    {"id": "t0", "kind": "structure", "properties": {"source": "t000.pdb", "frame": "run"}},
    {"id": "lone", "kind": "structure", "properties": {"source": "lone.pdb", "yaw": 5}},
]

TURNED = """
const [t0, lone] = [nodes[2], nodes[3]];
const turn = (id, values) =>
  frames.framedAction(nodes, { do: "update", target: { type: "node", id }, values });
return {
  turned: turn("t0", { "properties.yaw": 50 }),
  reset: turn("t0", { "properties.yaw": null, "properties.zoom": null }),
  words: turn("t0", { label: "x" }),
  alone: turn("lone", { "properties.yaw": 50 }),
  shown: frames.readFrom(nodes, t0, "properties.yaw").id,
  own: frames.readFrom(nodes, t0, "properties.source").id,
  lone: frames.readFrom(nodes, lone, "properties.yaw").id,
  members: frames.membersOf(nodes, "t0").map((node) => node.id),
};
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_page_turns_every_structure_of_a_frame_as_one_and_shows_the_frames_own() -> None:
    seen = _page(TURNED, nodes=NODES)
    # One edit of both, the one turned first (named for it); its words are its own.
    assert seen["turned"]["targets"] == [
        {"type": "node", "id": "t0"}, {"type": "node", "id": "t100"}
    ]
    assert seen["reset"]["targets"][1] == {"type": "node", "id": "t100"}
    assert "targets" not in seen["words"] and "targets" not in seen["alone"]
    # Its Camera tab shows the frame's turn: its first's.
    assert (seen["shown"], seen["own"], seen["lone"]) == ("t100", "t0", "lone")
    assert seen["members"] == ["t100", "t0"]


COLOURED_NODES = [
    {"id": "t100", "kind": "structure", "properties": {
        "source": "t100.pdb", "frame": "run", "ss_from": "end.pdb",
        "style": {"palette": {"helix": "#3f7fc0", "sheet": "#e08a2e"}},
        "colors": [{"group": "A", "color": "#dbebfd"}]}},
    {"id": "t30", "kind": "structure", "properties": {
        "source": "t030.pdb", "frame": "run", "ss_from": "end.pdb",
        "style": {"palette.helix": "#3f7fc0", "palette.sheet": "#d0607a"},
        "colors": [{"group": "A", "color": "#dbebfd"}]}},
    {"id": "t0", "kind": "structure", "properties": {
        "source": "t000.pdb", "frame": "run", "ss_from": "end.pdb",
        "style": {"palette": {"helix": "#3f7fc0", "sheet": "#e08a2e"}},
        "colors": [{"group": "A", "color": "#dbebfd"}]}},
    {"id": "lone", "kind": "structure", "properties": {"source": "lone.pdb"}},
]

COLOURED = """
const edit = (id, values) => {
  const action = frames.framedAction(nodes, { do: "update", target: { type: "node", id }, values });
  return (action.targets || [action.target]).map((target) => target.id);
};
return {
  helices: edit("t0", { "properties.style.palette.helix": "#1a5d9b" }),
  strands: edit("t0", { "properties.style.palette.sheet": "#246c2d" }),
  own: edit("t30", { "properties.style.palette.sheet": "#90394e" }),
  rows: edit("t100", { "properties.colors": [{ group: "A", color: "#246c2d" }] }),
  file: edit("t30", { "properties.ss_from": "other.pdb" }),
  scheme: edit("t0", { "properties.scheme": "figure" }),
  reset: edit("t0", {
    "properties.style.palette.helix": null, "properties.style.palette.loop": null }),
  cartoon: edit("t0", { "properties.style.cartoon_color": "rainbow" }),
  look: edit("t0", { "properties.look": "watercolour" }),
  mixed: edit("t0", { "properties.style.palette.helix": "#000000", "properties.yaw": 10 }),
  lone: edit("lone", { "properties.style.palette.helix": "#000000" }),
};
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_colour_the_structures_of_a_frame_share_is_changed_on_all_of_them() -> None:
    """A diffusion run's frames coloured alike: a colour changed on one is changed on each of
    the frame's that has it -- its style's palette (read nested or by a field's dotted name),
    its colour rows, the file it is coloured by, its scheme, how its cartoon is coloured --
    one step, the one edited first. A colour one of them has of its own (t30's strands) stays
    its own; and an edit of anything else (its look) is the one structure's alone."""

    seen = _page(COLOURED, nodes=COLOURED_NODES)
    assert seen["helices"] == ["t0", "t100", "t30"]
    # t30's strands are its own colour: changed on the two that share theirs, not on it.
    assert seen["strands"] == ["t0", "t100"]
    assert seen["own"] == ["t30"]
    assert seen["rows"] == ["t100", "t30", "t0"]
    assert seen["file"] == ["t30", "t100", "t0"]
    assert seen["scheme"] == ["t0", "t100", "t30"]
    assert seen["reset"] == ["t0", "t100", "t30"]
    assert seen["cartoon"] == ["t0", "t100", "t30"]
    assert seen["look"] == ["t0"]
    assert seen["mixed"] == ["t0"]
    assert seen["lone"] == ["lone"]


def _view(fit, *, zoom=1.0, pan=(0.0, 0.0), fov=0.0, yaw=0.0):
    return {
        "centre": [0, 0, 0], "fit": fit, "chains": [], "atoms": [],
        "frame": {"long_side": 1200, "foot": 0.0, "head": 0.0},
        "camera": {"yaw": yaw, "pitch": 0, "roll": 0, "zoom": zoom, "pan_x": pan[0],
                   "pan_y": pan[1], "fov": fov},
    }


PROJECTED = """
const alone = parts.moleculeProjector(one, angles, 1200, 900);
const [framed] = frames.framedProjectors([one], [{ width: 1200, height: 900 }], angles);
const square = { width: 600, height: 600 };
const pair = frames.framedProjectors(both, [square, square], angles);
return {
  alone: points.map((p) => alone.at(p)),
  framed: points.map((p) => framed.at(p)),
  per: [alone.perAngstrom, framed.perAngstrom],
  pair: pair.map((p) => [p.perAngstrom, p.at([4, 3, 1])]),
};
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_page_draws_a_frame_turning_as_the_frame_will_be_drawn() -> None:
    """Alone in its frame, a molecule turns as it does by itself (moleculeProjector); with a
    smaller one, both are drawn at the larger's scale about the middle of the two, a point they
    share in the same place of each."""

    corners = [[x, y, z] for x in (-10, 10) for y in (-5, 5) for z in (-2, 2)]
    small = [[x, y, z] for x in (-3, 5) for y in (-2, 2) for z in (-1, 1)]
    seen = _page(
        PROJECTED,
        one=_view(corners, zoom=1.5, pan=(0.1, -0.05)),
        both=[_view(small), _view(corners)],
        points=[[0, 0, 0], [10, 0, 0], [4, 3, 1]],
        angles={"yaw": 25, "pitch": -15, "roll": 10},
    )
    for mine, theirs in zip(seen["framed"], seen["alone"], strict=True):
        assert mine == pytest.approx(theirs)
    assert seen["per"][0] == pytest.approx(seen["per"][1])
    (small_scale, small_at), (large_scale, large_at) = seen["pair"]
    assert small_scale == pytest.approx(large_scale)
    assert small_at == pytest.approx(large_at)


MOVED = """
const view = async (id) => views[id];
const moves = (id, name, list = nodes) =>
  frames.frameMoves(list, list.find((node) => node.id === id), name, view);
return {
  left: await moves("t0", null),
  ownerLeft: await moves("t100", null),
  joined: await moves("lone", "run"),
  first: await moves("lone", "run", [nodes[3], ...nodes.slice(0, 3)]),
  named: frames.frameName(nodes[3], ["lone"]),
};
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_frame_field_keeps_how_each_structure_is_seen() -> None:
    """Out of a frame, a structure keeps the turn it was seen at; its first gone, the next is
    turned so that the frame is seen as it was; coming after a frame's first, one takes the
    frame's settings; coming first, it turns the frame about its own axes."""

    np = pytest.importorskip("numpy")
    from flexo.structure_frames import turned

    rng = np.random.default_rng(3)
    bases = {name: turned(*rng.uniform(-90, 90, size=3)).round(6).tolist()
             for name in ("t100", "t0", "lone")}
    framed = {"yaw": 20, "pitch": 0, "roll": 0}
    views = {
        "t100": {"base": bases["t100"], "camera": framed, "alone": framed},
        "t0": {"base": bases["t0"], "camera": framed,
               "alone": {"yaw": -61.5, "pitch": 12.25, "roll": 3}},
        "lone": {"base": bases["lone"], "camera": {"yaw": 5, "pitch": 0, "roll": 0}},
    }
    seen = _page(MOVED, nodes=NODES, views=views)

    def by(moves):
        return {move["id"]: move["values"] for move in moves}

    unframed = {"properties.zoom": None, "properties.pan_x": None, "properties.pan_y": None}
    t0_alone = {"properties.yaw": -61.5, "properties.pitch": 12.25, "properties.roll": 3}
    assert by(seen["left"]) == {"t0": {"properties.frame": None, **t0_alone, **unframed}}
    assert by(seen["ownerLeft"])["t0"] == t0_alone
    assert by(seen["joined"]) == {"lone": {
        "properties.frame": "run", "properties.yaw": 20, "properties.pitch": None,
        "properties.roll": None, **unframed,
    }}
    # Coming first: all of them turned about its axes, the frame seen as it was.
    first = by(seen["first"])
    assert set(first) == {"lone", "t100", "t0"}
    turn = first["t100"]
    now = turned(turn["properties.yaw"] or 0, turn["properties.pitch"] or 0,
                 turn["properties.roll"] or 0) @ np.array(bases["lone"])
    assert np.allclose(now, turned(20, 0, 0) @ np.array(bases["t100"]), atol=3e-3)
    assert first["lone"]["properties.frame"] == "run" and first["t0"] == turn
    assert seen["named"] == "lone-2"
