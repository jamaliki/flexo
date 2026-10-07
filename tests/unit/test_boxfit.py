"""Figures laid out for a box: turned when that lets their words be larger."""

from __future__ import annotations

from itertools import pairwise

import flexo
from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.orient import turned


def _stack() -> Figure:
    """A stack that reads upward, as a transformer's does."""

    with Figure("stack") as figure, figure.column("layers", reverse=True) as layers:
        previous = layers.text("x", "$x$")
        for index in range(5):
            previous = layers.block(f"b{index}", label=f"Layer {index}", input=previous)
    return figure


def test_a_turned_stack_reads_left_to_right() -> None:
    spec = turned(_stack().spec)
    group = next(group for group in spec.groups if group.id == "layers")
    assert group.layout.kind == "row"
    # The bottom of the stack (its input) comes first once it lies down.
    assert group.children[0] == "layers.x"
    compiled = compile_figure(spec)
    boxes = {node.measured.spec.id: node.bounds for node in compiled.fitted.nodes}
    assert boxes["layers.x"].x < boxes["layers.b0"].x < boxes["layers.b4"].x


def test_a_tall_figure_in_a_wide_box_is_turned_and_reads_larger() -> None:
    fit = flexo.fit_in_box(_stack(), 800, 200, words=12, largest=18)
    kept = flexo.fit_in_box(_stack(), 800, 200, words=12, largest=18, turn=False)
    assert fit.layout.startswith("turned") and kept.layout == "as written"
    assert fit.words > kept.words * 1.5
    assert fit.ink[2] * fit.scale <= 800 + 1e-6 and fit.ink[3] * fit.scale <= 200 + 1e-6


def test_a_figure_that_already_fits_is_kept_as_written() -> None:
    fit = flexo.fit_in_box(_stack(), 300, 900, words=12, largest=18)
    assert fit.layout == "as written"


def test_turning_attention_lays_its_vectors_down() -> None:
    with Figure("attn") as figure:
        x = figure.text("x", "$x$")
        figure.attention("attn", label="Attention", input=x, vectors=True, width="110pt")
    spec = turned(figure.spec)
    vectors = [node for node in spec.nodes if node.kind == "vector"]
    assert vectors
    for node in vectors:
        values = dict(node.properties)
        assert values["cells"] == 1 and values["columns"] == 3
    compile_figure(spec)


def _boxes(spec) -> dict:
    compiled = compile_figure(spec)
    return compiled, {node.measured.spec.id: node.bounds for node in compiled.fitted.nodes}


def test_a_long_chain_folds_onto_two_evenly_spaced_lines() -> None:
    from flexo.orient import wrapped

    with Figure("chain") as figure, figure.row("steps") as steps:
        previous = steps.text("x", "$x$")
        for index in range(7):
            label = f"Step {index}" + " long" * index
            previous = steps.block(f"s{index}", label=label, input=previous)
    spec = wrapped(figure.spec)
    group = next(group for group in spec.groups if group.id == "steps")
    assert group.layout.kind == "column" and len(group.children) == 2
    lines = [next(item for item in spec.groups if item.id == child) for child in group.children]
    assert lines[0].children[-1] == "steps.s2" and lines[1].children[-1] == "steps.s3"
    _, boxes = _boxes(spec)
    # Each line keeps its own spacing: its arrows are as long as one another, not
    # stretched by the widths of the parts above or below them.
    for line in lines:
        gaps = [boxes[b].x - boxes[a].right for a, b in pairwise(line.children)]
        assert max(gaps) - min(gaps) < 1.0
    # Turned at the end of the first line, the second runs back under it: the line on
    # to it is a short step down, not one across the whole figure.
    assert boxes["steps.s4"].x < boxes["steps.s3"].x
    assert abs(boxes["steps.s3"].right - boxes["steps.s2"].right) < 1.0


def test_a_flow_that_loops_back_folds_with_nothing_crossing() -> None:
    from flexo.lint import lint_compilation
    from flexo.orient import wrapped

    with Figure("flow") as figure, figure.row("steps") as steps:
        start = steps.terminal("start", label="Start")
        first = steps.block("first", label="Collect movies", input=start)
        previous = first
        for index in range(3):
            previous = steps.block(f"s{index}", label=f"Step {index}", input=previous)
        check = steps.decision("check", label="Better than 3.5 Å?", input=previous)
        steps.terminal("end", label="Build the model", input=check)
        figure.connect(check, first, label="no")
    spec = wrapped(figure.spec)
    compiled, boxes = _boxes(spec)
    codes = [item.code for item in lint_compilation(compiled).diagnostics]
    assert "routing.connector.crossing" not in codes
    # The second line runs back under the first: the line between them is a short step down.
    assert boxes["steps.s2"].x > boxes["steps.check"].x > boxes["steps.end"].x
    turn = abs(boxes["steps.s2"].center.x - boxes["steps.s1"].center.x)
    assert turn < boxes["steps.s1"].width / 2


def test_a_line_drawn_in_or_taken_away_leaves_a_flow_folded_where_it_was() -> None:
    from flexo.orient import wrapped

    def folded(loops: bool):
        with Figure("assay") as figure, figure.row("steps") as steps:
            express = steps.terminal("express", label="Express sfGFP")
            pulse = steps.block("pulse", label="Pulse: induce 10 min", input=express)
            chase = steps.block("chase", label="Chase: add chloramphenicol", input=pulse)
            read = steps.block("read", label="Read fluorescence every 30 s", input=chase)
            plateau = steps.decision("plateau", label="Plateau reached?", input=read)
            fit = steps.block("fit", label="Fit two-step model to F(t)", input=plateau)
            steps.terminal("report", label="Report k1, k2", input=fit)
            if loops:
                figure.connect(plateau, read, label="no")
                figure.connect(fit, pulse, label="again")
        spec = wrapped(figure.spec)
        group = next(group for group in spec.groups if group.id == "steps")
        lines = [next(item for item in spec.groups if item.id == child) for child in group.children]
        return [line.children for line in lines], spec

    plain, _ = folded(False)
    looped, spec = folded(True)
    # The same parts on each line, in the same order, the loops back or not: the
    # fold is the parts', not their lines'. (The decision does not start the second
    # line: the fold comes a part earlier.)
    assert plain == looped
    assert plain[0][-1] == "steps.chase" and plain[1][-1] == "steps.read"
    compile_figure(spec)


def _sequencing(loop: bool, decision_last: bool = False) -> Figure:
    labels = [
        "Receive sample", "Extract DNA", "Amplify by PCR", "Purify product", "Sequence it",
        "Quality ok?", "Align reads", "Call variants", "Write report",
    ]
    order = [0, 1, 2, 3, 4, 6, 7, 8, 5] if decision_last else list(range(9))
    with Figure("sequencing") as figure, figure.row("steps") as steps:
        made = {}
        for index in order:
            add = steps.terminal if index in (0, 8) else steps.block
            made[index] = (steps.decision if index == 5 else add)(f"s{index}", label=labels[index])
        for index in range(8):
            figure.connect(made[index], made[index + 1], label="yes" if index == 5 else None)
        if loop:
            figure.connect(made[5], made[1], label="no")
    return figure


def test_a_flow_with_a_loop_back_runs_back_and_its_loop_crosses_nothing() -> None:
    from flexo.boxfit import _crossings
    from flexo.orient import wrapped

    spec = wrapped(_sequencing(loop=True).spec)
    lines = [group.children for group in spec.groups if group.id.startswith("steps.line")]
    # The decision is not where the line on comes down: its top is free for the "no".
    assert lines[0][-1] == "steps.s3" and lines[1][-1] == "steps.s4"
    assert not _crossings(compile_figure(spec), None)
    fit = flexo.fit_in_box(_sequencing(loop=True), 1100, 420, words=18, largest=24)
    assert fit.layout.endswith(", folded") and not _crossings(fit.compilation, fit.style)


def test_a_flow_listed_out_of_its_order_is_folded_along_its_lines() -> None:
    from flexo.boxfit import _crossings
    from flexo.orient import wrapped

    # The decision written last, its lines running back and forth along the row: folded,
    # it is set where its lines put it, as the flow written in order is.
    out = wrapped(_sequencing(loop=True, decision_last=True).spec)
    written = wrapped(_sequencing(loop=True).spec)
    def lines(spec):
        return [group.children for group in spec.groups if group.id.startswith("steps.line")]

    assert lines(out) == lines(written)
    assert not _crossings(compile_figure(out), None)
    figure = _sequencing(loop=True, decision_last=True)
    fit = flexo.fit_in_box(figure, 1100, 420, words=18, largest=24)
    assert "folded" in fit.layout and fit.words > 15


def test_parts_with_nothing_between_their_halves_fold_into_a_grid() -> None:
    from flexo.orient import wrapped

    with Figure("shelf") as figure, figure.row("panels") as panels:
        for index in range(6):
            panels.block(f"p{index}", label=f"Panel {index}")
    spec = wrapped(figure.spec)
    group = next(group for group in spec.groups if group.id == "panels")
    assert group.layout.kind == "grid" and group.layout.columns == 3
    cells = group.layout.placement_map()
    assert cells["panels.p2"] == (0, 2) and cells["panels.p3"] == (1, 0)
    compile_figure(spec)


def test_a_fold_runs_its_second_line_back_where_run_on_its_lines_would_cross() -> None:
    from flexo.boxfit import _crossings
    from flexo.orient import wrapped

    # A flow chart's first step moved to a line of its own below the rest: folded with
    # its second line run on, its lines cross; run back, as a fold runs, none do.
    with Figure("assay") as figure, figure.column("steps") as steps:
        with steps.row("row") as row:
            purify = row.terminal("purify", label="Purify CA")
            mix = row.block("mix", label="Mix CA with IP6", input=purify)
            check = row.decision("check", label="Tubes formed?")
            grids = row.terminal("grids", label="Cryo-EM grids")
            movies = row.block("movies", label="Collect movies", input=grids)
            motion = row.block("motion", label="Motion correction", input=movies)
            row.block("refine", label="3D refinement", input=motion)
        stain = steps.block("stain", label="Negative-stain EM", input=mix)
        figure.connect(stain, check)
        figure.connect(check, grids, label="yes")
        figure.connect(check, mix, label="no")
    assert _crossings(compile_figure(wrapped(figure.spec, back=False)), None)
    fit = flexo.fit_in_box(figure, 864, 380, words=18, largest=24)
    assert fit.layout.endswith(", folded") and fit.words > 15
    assert not _crossings(fit.compilation, fit.style)


def _model() -> Figure:
    """A tall column with a side input: too tall for a slide as written, not so tall
    that its words would be tiny."""

    with Figure("model") as figure, figure.column("model", gap=22) as column:
        patches = column.text("patches", "Image, cut into patches")
        projection = column.block(
            "projection", label="Linear projection of flattened patches", input=patches
        )
        tokens = column.block("tokens", label="Prepend a learned [class] token", input=projection)
        with column.row("positions", gap=18) as row:
            position = row.text("position", "Position embedding")
            total = row.add("sum", inputs=[tokens, position])
        encoder = column.block("encoder", label="Transformer encoder", input=total)
        head = column.block("head", label="MLP head", input=encoder)
        column.text("class", "Class", input=head)
    return figure


def test_a_fold_that_sets_the_words_clearly_larger_is_taken() -> None:
    kept = flexo.fit_in_box(_model(), 864, 361, words=13, largest=20, turn=False)
    fit = flexo.fit_in_box(_model(), 864, 361, words=13, largest=20)
    # As written it reaches most of the size it was meant to have; folded it reaches more.
    assert kept.words > 13 * 0.7
    assert "folded" in fit.layout and fit.words > kept.words * 1.3


def test_a_layout_kept_while_editing_is_drawn_alone_and_as_the_fit_drew_it(monkeypatch) -> None:
    import flexo.boxfit as boxfit

    fit = flexo.fit_in_box(_stack(), 800, 200, words=12, largest=18)
    compiles = []
    real = boxfit.compile_figure

    def counted(*args, **kwargs):
        compiles.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(boxfit, "compile_figure", counted)
    kept = flexo.fit_in_box(_stack(), 800, 200, words=12, largest=18, keep=fit.layout)
    assert len(compiles) == 1 and kept.layout == fit.layout
    assert kept.compilation.document.text == fit.compilation.document.text
    # A layout it does not know is no layout to keep: the best is found as ever.
    other = flexo.fit_in_box(_stack(), 800, 200, words=12, largest=18, keep="sideways")
    assert other.layout == fit.layout


def test_a_nets_end_sides_turn_with_the_figure() -> None:
    """A skip line asked to leave its block's foot and come into the next one's head
    leaves its right side and comes into the next one's left, turned."""

    from flexo.geometry import Side
    from flexo.serialization import parse_figure

    spec = parse_figure(
        {
            "figure": {"id": "spine"},
            "groups": [{"id": "root", "layout": {"kind": "column"}, "children": ["a", "b", "c"]}],
            "nodes": [{"id": name, "label": name.upper()} for name in ("a", "b", "c")],
            "nets": [
                {
                    "id": "skip",
                    "kind": "fan-out",
                    "sources": ["a"],
                    "targets": ["b", "c"],
                    "sides": {"a": "south", "c": "north"},
                }
            ],
        }
    )
    (net,) = turned(spec).nets
    assert dict(net.sides) == {"a.output": Side.EAST, "c.input": Side.WEST}
    compile_figure(turned(spec))
