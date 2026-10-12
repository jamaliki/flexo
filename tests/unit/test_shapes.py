"""The shapes of flowcharts and architecture diagrams: each sizes, wires, and draws.

A database, a server, a cloud, a queue, a document, a person, and the flowchart's
input/output are drawn from an outline (``flexo.shapes``). Each is still a
component -- sized round its words, painted in the theme's roles -- and the lines
it takes meet that outline, not the box round it.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from itertools import pairwise

import pytest

from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.drawing import read_drawing
from flexo.geometry import Point, Rect
from flexo.lint import lint_compilation
from flexo.shapes import (
    CLOUD_ROOM,
    SHAPE_KINDS,
    _cloud,
    _flatten,
    _hit_lines,
    ink_depth,
    label_area,
    lid_depth,
    outline,
)
from flexo.studio.figure_parts import CATEGORIES, catalogue
from flexo.themes import figure_style

KINDS = ("database", "server", "cloud", "queue", "document", "person", "io")
LABELS = {
    "database": "Postgres",
    "server": "Web server",
    "cloud": "Internet",
    "queue": "Jobs",
    "document": "Report",
    "person": "User",
    "io": "Read input",
}


def _alone(kind: str, label: str | None = None, **options: object):
    with Figure(kind) as figure, figure.module("m") as m:
        getattr(m, kind)("a", label=LABELS[kind] if label is None else label, **options)
    return compile_figure(figure.spec)


def _architecture(style: str = "paper", **options: object) -> Figure:
    """A web service's caching layer, every shape in it, and a flowchart beside it."""

    with Figure("architecture", style=style) as figure:
        with figure.module("m", label="Caching layer", layout="row") as m:
            user = m.person("user", "User", **options)
            web = m.cloud("net", "Internet", input=user, **options)
            app = m.server("app", "App server", input=web, **options)
            cache = m.database("cache", "Cache", input=app, **options)
            jobs = m.queue("jobs", "Jobs", input=app, **options)
            m.document("report", "Report", input=jobs, **options)
            m.connect(cache, jobs, arrow="none")
        with figure.module("f", label="Flowchart", layout="column") as f:
            start = f.terminal("start", "Start")
            read = f.io("read", "Read input", input=start, **options)
            step = f.block("step", label="Process", input=read)
            done = f.decision("done", "Done?", input=step)
            f.terminal("end", "End", input=done)
            f.connect(done, step, label="no")
    return figure


def _distance_to_outline(point: Point, node, style) -> float:
    lines = _hit_lines(node.measured.spec.kind, node.bounds, node.measured.label, style)
    best = math.inf
    for line in lines:
        for (ax, ay), (bx, by) in pairwise(line):
            dx, dy = bx - ax, by - ay
            length = dx * dx + dy * dy
            t = 0.0 if length == 0 else ((point.x - ax) * dx + (point.y - ay) * dy) / length
            t = min(1.0, max(0.0, t))
            best = min(best, math.hypot(point.x - (ax + t * dx), point.y - (ay + t * dy)))
    return best


@pytest.mark.parametrize("kind", KINDS)
def test_each_shape_is_sized_round_its_label_and_drawn_in_the_themes_roles(kind: str) -> None:
    compiled = _alone(kind)
    node = compiled.fitted.node("m.a")
    style = figure_style(compiled.measured.semantic)
    label = node.measured.label
    area = label_area(kind, node.bounds, label, style)
    # The words fit the room the outline leaves them, inside the shape's box.
    assert area.width >= label.width and area.height >= label.height - 1e-6
    assert node.bounds.contains_rect(area)
    root = ET.fromstring(compiled.document.text)
    body = next(item for item in root.iter() if item.get("id") == "m.a.body")
    assert body.tag.endswith("path")
    assert body.get("data-flexo-fill") == "block-fill"
    assert body.get("data-flexo-stroke") == "block-stroke"
    assert not lint_compilation(compiled).diagnostics


def test_a_long_name_wraps_and_an_authored_size_is_kept() -> None:
    long = _alone("database", "A rather long name for the primary database").fitted.node("m.a")
    assert len(long.measured.label.lines) == 2, "past 16 ems, a label wraps"
    style = figure_style(_architecture().spec)
    area = label_area("database", long.bounds, long.measured.label, style)
    assert area.height >= long.measured.label.height, "and the cylinder grows to hold it"
    cloud = _alone("cloud", "Content delivery network").fitted.node("m.a")
    assert len(cloud.measured.label.lines) == 2, "a cloud takes two lines, not a long lozenge"
    sized = _alone("server", width="90pt", height="50pt").fitted.node("m.a")
    assert (sized.bounds.width, sized.bounds.height) == pytest.approx((90.0, 50.0))


@pytest.mark.parametrize("kind", KINDS)
def test_a_size_too_small_for_its_words_grows_to_hold_them(kind: str) -> None:
    """A given size is a design, not a clip: the words wrap to its width and the shape is at
    least as tall as they need there, in the room its outline leaves them."""

    compiled = _alone(kind, "Every old result kept for later", width="50pt", height="20pt")
    node = compiled.fitted.node("m.a")
    style = figure_style(compiled.measured.semantic)
    label = node.measured.label
    area = label_area(kind, node.bounds, label, style)
    assert len(label.lines) > 1, "wrapped to the width it is given"
    assert area.width >= label.width - 1e-6 and area.height >= label.height - 1e-6
    assert node.bounds.contains_rect(area)


def test_a_circles_words_wrap_and_a_small_circle_grows_round_them() -> None:
    def circle(**options: object):
        with Figure("c") as figure, figure.row("r") as row:
            row.circle("a", label="Hub of every old result", **options)
        return compile_figure(figure.spec).fitted.node("r.a")

    for node in (circle(), circle(width="30pt", height="30pt")):
        label = node.measured.label
        assert len(label.lines) == 2, "not one line drawn across it from edge to edge"
        # Its words' box inscribed in it.
        assert math.hypot(label.width, label.height) <= node.bounds.width + 1e-6
        assert node.bounds.width == pytest.approx(node.bounds.height)
    assert circle(width="120pt").bounds.width == pytest.approx(120.0), "a size that holds them"


def test_a_shape_says_how_wide_its_words_run_before_they_wrap() -> None:
    compiled = _alone("cloud", width="80pt")
    root = ET.fromstring(compiled.document.text)
    group = next(item for item in root.iter() if item.get("id") == "m.a")
    style = figure_style(compiled.measured.semantic)
    room = 80.0 * CLOUD_ROOM[0] - style.padding_x.points
    assert float(group.get("data-flexo-room")) == pytest.approx(room, abs=0.01)


def test_a_database_is_a_cylinder_its_label_under_the_lid() -> None:
    compiled = _alone("database")
    node = compiled.fitted.node("m.a")
    root = ET.fromstring(compiled.document.text)
    data = {item.get("id"): item.get("d") for item in root.iter() if item.get("d")}
    assert data["m.a.body"].count("A") == 2  # the foot's curve and the lid's far side
    assert "A" in data["m.a.lines"]  # the lid's near rim
    style = figure_style(compiled.measured.semantic)
    lid = lid_depth(node.bounds)
    assert lid == pytest.approx(min(node.bounds.width, node.bounds.height) / 8.0)
    words = node.measured.label
    area = label_area("database", node.bounds, words, style)
    assert area.top == pytest.approx(node.bounds.top + 2.0 * lid), "below the whole lid"


def test_lines_meet_the_outline_not_the_box() -> None:
    """Three servers into one database: each arrowhead stops just short of the lid."""

    with Figure("lids") as figure, figure.module("m", layout="column") as m:
        with m.row("apps", role="layout") as row:
            apps = [row.server(f"a{index}", f"App {index}") for index in range(3)]
        db = m.database("db", "Primary database")
        for app in apps:
            m.connect(app, db)
        m.document("report", "Nightly report", input=db)
    compiled = compile_figure(figure.spec)
    assert not lint_compilation(compiled).diagnostics
    style = figure_style(compiled.measured.semantic)
    database = compiled.fitted.node("m.db")
    reached = []
    for edge in compiled.routed.edges:
        target = compiled.fitted.node(edge.spec.target.node_id)
        if target.measured.spec.kind not in SHAPE_KINDS:
            continue
        end, before = edge.centerline[-1], edge.centerline[-2]
        heading = Point(end.x - before.x, end.y - before.y)
        length = math.hypot(heading.x, heading.y)
        unit = Point(heading.x / length, heading.y / length)
        depth = edge.outline_depth[1]
        assert depth == pytest.approx(
            ink_depth(target.measured.spec.kind, target.bounds, target.measured.label, style, end,
                      (unit.x, unit.y))
        )
        # The arrowhead's tip: a standoff short of the outline, not of the box.
        tip = edge.shaft[-1].translated(
            unit.x * style.arrow_length.points, unit.y * style.arrow_length.points
        )
        meets = end.translated(unit.x * depth, unit.y * depth)
        assert tip.distance_to(meets) == pytest.approx(style.connector_standoff.points)
        assert _distance_to_outline(meets, target, style) < 0.05
        if target is database:
            reached.append(depth)
    # The middle one meets the top of the lid; the outer two come down to its curve.
    assert len(reached) == 3
    assert min(reached) < 0.5 * style.stroke_width.points + 0.05
    assert max(reached) > min(reached) + 0.3


def test_a_line_leaves_from_the_outline_too() -> None:
    """Out of a parallelogram's slanted side, under a document's wavy foot."""

    with Figure("leaving") as figure, figure.module("m", layout="row") as m:
        read = m.io("read", "Read input")
        m.block("step", label="Step", input=read)
    compiled = compile_figure(figure.spec)
    style = figure_style(compiled.measured.semantic)
    edge = compiled.routed.edges[0]
    start = edge.outline_depth[0]
    node = compiled.fitted.node("m.read")
    assert start == pytest.approx(node.bounds.height * 0.4 / 2.0, abs=0.6), "half the slant"
    # The shaft starts a standoff out from where the outline is.
    leaves = edge.centerline[0].translated(-start, 0.0)
    assert edge.shaft[0].distance_to(leaves) == pytest.approx(style.connector_standoff.points)
    assert not lint_compilation(compiled).diagnostics


def test_a_person_takes_lines_at_its_shoulders_and_under_its_name() -> None:
    with Figure("people") as figure, figure.module("m", layout="column") as m:
        user = m.person("user", "Mobile client")
        m.cloud("net", "Internet", input=user)
        with m.row("pair", role="layout") as row:
            left = row.person("left", "Admin")
            row.server("right", "Server", input=left)
    compiled = compile_figure(figure.spec)
    assert not lint_compilation(compiled).diagnostics
    style = figure_style(compiled.measured.semantic)
    down, across = compiled.routed.edges
    # From below a person, the line leaves under the name, not up through it.
    person = compiled.fitted.node("m.user")
    assert down.centerline[0].y == pytest.approx(person.bounds.bottom)
    assert down.outline_depth[0] == pytest.approx(0.0, abs=1e-6)
    # From its side, at the middle of the box: its shoulders, and the line reaches them.
    admin = compiled.fitted.node("m.pair.left")
    assert across.centerline[0].y == pytest.approx(admin.bounds.center.y)
    assert across.outline_depth[0] > 0.0
    meets = across.centerline[0].translated(-across.outline_depth[0], 0.0)
    assert _distance_to_outline(meets, admin, style) < 0.05
    area = label_area("person", admin.bounds, admin.measured.label, style)
    assert meets.y < area.top, "the shoulders are above the name"


def test_every_kind_of_line_reaches_the_outline_and_lints_clean() -> None:
    """Both ends, a reversible pair, an undirected link, and a merge into a cylinder."""

    with Figure("ends") as figure:
        with figure.module("m", layout="column") as m:
            with m.row("writers", role="layout") as row:
                writers = [row.server(f"w{index}", f"Writer {index}") for index in range(3)]
            store = m.database("store", "Store")
            with m.row("readers", role="layout") as row:
                report = row.document("report", "Report")
                read = row.io("read", "Read")
                person = row.person("person", "Analyst")
        figure.merge(sinks=writers, dst=store)
        m.connect(store, report, arrow="both")
        m.connect(store, read, arrow="reversible")
        m.connect(store, person, arrow="none")
    compiled = compile_figure(figure.spec)
    assert not lint_compilation(compiled).diagnostics
    by_target = {edge.spec.target.node_id: edge for edge in compiled.routed.edges}
    assert all(depth >= 0.0 for edge in by_target.values() for depth in edge.outline_depth)
    assert by_target["m.readers.read"].outline_depth[1] > 0.0, "the slanted top's far end"
    root = ET.fromstring(compiled.document.text)
    ids = {item.get("id") for item in root.iter()}
    reversible = by_target["m.readers.read"].spec.id
    assert {f"{reversible}.forward", f"{reversible}.back"} <= ids
    (net,) = compiled.routed.nets
    (into,) = net.target_stems
    style = figure_style(compiled.measured.semantic)
    end, before = into.centerline[-1], into.centerline[-2]
    depth = ink_depth(
        "database", compiled.fitted.node("m.store").bounds, compiled.fitted.node("m.store")
        .measured.label, style, end, (end.x - before.x, end.y - before.y)
    )
    reach = style.arrow_length.points + style.connector_standoff.points - depth
    assert into.shaft[-1].distance_to(end) == pytest.approx(reach)


def test_straight_lines_end_on_the_outline() -> None:
    with Figure("straight", conventions={"lines": "straight"}) as figure:
        with figure.module("m", layout="grid", columns=2) as m:
            net = m.cloud("net", "Internet")
            m.block("pad", label="Pad", motif=False)
            m.block("pad2", label="Pad", motif=False)
            db = m.database("db", "Store")
        m.connect(net, db)
    compiled = compile_figure(figure.spec)
    style = figure_style(compiled.measured.semantic)
    edge = compiled.routed.edges[0]
    assert edge.straight
    for point, node_id in zip(edge.centerline, ("m.net", "m.db"), strict=True):
        assert _distance_to_outline(point, compiled.fitted.node(node_id), style) < 0.05


def test_a_clouds_label_room_lies_inside_its_puffs() -> None:
    (start, arcs), (cx, cy) = _cloud()
    commands = [f"M {start[0] * 1000} {start[1] * 1000}"]
    for (rx, ry), large, (x, y) in arcs:
        commands.append(f"A {rx * 1000} {ry * 1000} 0 {int(large)} 1 {x * 1000} {y * 1000}")
    polygon = [(x / 1000, y / 1000) for x, y in _flatten(" ".join(commands) + " Z")[0]]
    xs = [x for x, _ in polygon]
    ys = [y for _, y in polygon]
    assert (min(xs), max(xs), min(ys), max(ys)) == pytest.approx((0, 1, 0, 1), abs=0.02)

    def inside(x: float, y: float) -> bool:
        crossings = 0
        for (x1, y1), (x2, y2) in pairwise([*polygon, polygon[0]]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                crossings += 1
        return crossings % 2 == 1

    room_x, room_y = CLOUD_ROOM
    for fx in (-0.5, 0.0, 0.5):
        for fy in (-0.5, 0.5):
            assert inside(cx + fx * room_x, cy + fy * room_y)
            assert inside(cx + fy * room_x, cy + fx * room_y)


def test_a_figure_of_every_shape_compiles_clean_in_every_kind_of_theme() -> None:
    for style in ("paper", "dark", "sketch", "tikz"):
        compiled = compile_figure(_architecture(style).spec)
        report = lint_compilation(compiled)
        assert not report.diagnostics, (style, report.format())
    shadowed = compile_figure(_architecture(shadow=True).spec)
    assert not lint_compilation(shadowed).diagnostics
    root = ET.fromstring(shadowed.document.text)
    shadow = next(item for item in root.iter() if item.get("id") == "m.cache.shadow")
    # A cylinder's shadow is a cylinder, not a box.
    assert all(part.tag.endswith("path") for part in shadow)


def test_every_shape_comes_through_the_exports_as_outlines() -> None:
    from flexo.pdf import pdf_bytes

    compiled = compile_figure(_architecture().spec)
    drawing = read_drawing(compiled.document.text)
    shapes = {}
    for item in drawing.walk():
        if getattr(item, "id", None) and getattr(item, "segments", None):
            shapes[item.id] = item
    for node_id in ("m.user", "m.net", "m.app", "m.cache", "m.jobs", "m.report", "f.read"):
        body = shapes[f"{node_id}.body"]
        assert body.kind == "path" and body.paint.fill and body.paint.stroke
        assert any(segment.kind == "C" for segment in body.segments) or node_id == "f.read"
    assert pdf_bytes([compiled.document.text]).startswith(b"%PDF")


def test_outlines_follow_their_bounds() -> None:
    style = figure_style(_architecture().spec)
    from flexo.ir.measured import TextMetrics

    label = TextMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, ())
    for kind in KINDS:
        bounds = Rect(10.0, 20.0, 80.0, 40.0)
        for data in (outline(kind, bounds, label, style).body,):
            points = [point for line in _flatten(data) for point in line]
            xs = [x for x, _ in points]
            ys = [y for _, y in points]
            inset = style.stroke_width.points / 2.0 - 0.01  # arcs drawn as cubics
            assert min(xs) >= bounds.left + inset and max(xs) <= bounds.right - inset, kind
            assert min(ys) >= bounds.top + inset and max(ys) <= bounds.bottom - inset, kind


@pytest.mark.parametrize(
    ("query", "kind"),
    [
        ("database", "database"),
        ("cylinder", "database"),
        ("storage", "database"),
        ("cache", "database"),
        ("db", "database"),
        ("server", "server"),
        ("computer", "server"),
        ("host", "server"),
        ("machine", "server"),
        ("cloud", "cloud"),
        ("internet", "cloud"),
        ("network", "cloud"),
        ("queue", "queue"),
        ("message queue", "queue"),
        ("buffer", "queue"),
        ("stream", "queue"),
        ("document", "document"),
        ("file", "document"),
        ("report", "document"),
        ("person", "person"),
        ("user", "person"),
        ("client", "person"),
        ("actor", "person"),
        ("process", "block"),
        ("decision", "decision"),
        ("terminal", "terminal"),
        ("start", "terminal"),
        ("end", "terminal"),
        ("input", "io"),
        ("output", "io"),
        ("data", "io"),
        ("i/o", "io"),
        ("parallelogram", "io"),
    ],
)
def test_the_shape_picker_finds_each_shape_by_the_words_people_use(query: str, kind: str) -> None:
    """The palette's search (``figure/parts.js``) reads a part's title, hint, kind and words."""

    parts = catalogue()["parts"]

    def matches(part: dict) -> bool:
        said = f"{part['title']} {part['hint']} {part['kind']} {' '.join(part.get('words', []))}"
        return query.lower() in said.lower()

    assert matches(parts[kind])


def test_the_software_shapes_have_a_category_of_their_own() -> None:
    parts = catalogue()["parts"]
    assert "Software" in CATEGORIES
    software = [kind for kind, part in parts.items() if part["category"] == "Software"]
    assert software == ["database", "server", "cloud", "queue", "document", "person"]
    assert parts["io"]["category"] == "Basics"
    for kind in (*software, "io"):
        assert parts[kind]["title"] and parts[kind]["hint"] and parts[kind]["words"]
