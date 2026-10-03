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
    assert lines[0].children[-1] == "steps.s2" and lines[1].children[0] == "steps.s3"
    _, boxes = _boxes(spec)
    # Each line keeps its own spacing: its arrows are as long as one another, not
    # stretched by the widths of the parts above or below them.
    for line in lines:
        gaps = [boxes[b].x - boxes[a].right for a, b in pairwise(line.children)]
        assert max(gaps) - min(gaps) < 1.0
    # Read left to right, and then on, from the start of the next line.
    assert boxes["steps.s3"].x < boxes["steps.s4"].x and boxes["steps.s3"].x < boxes["steps.s1"].x


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


def test_a_flow_folds_where_the_fewest_lines_cross_between_its_lines() -> None:
    from flexo.orient import wrapped

    with Figure("consumer") as figure, figure.row("steps") as steps:
        arrives = steps.terminal("arrives", label="Message arrives")
        seen = steps.decision("seen", label="Seen this ID?", input=arrives)
        steps.terminal("skip", label="Skip it", input=seen)
        update = steps.block("update", label="Update the order")
        figure.connect(seen, update, label="no")
        worked = steps.decision("worked", label="Worked?", input=update)
        figure.connect(worked, update, label="no")
        done = steps.terminal("done", label="Acknowledge", input=worked)
        steps.block("log", label="Log it", input=done)
    spec = wrapped(figure.spec)
    group = next(group for group in spec.groups if group.id == "steps")
    second = next(item for item in spec.groups if item.id == group.children[1])
    # One line between the two lines ("no" to the update) rather than two (on to
    # "Worked?" and its "no" back): the update starts the second line, as it did
    # before the last part was added.
    assert second.children[0] == "steps.update"
    compile_figure(spec)


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
