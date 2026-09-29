"""Figures laid out for a box: turned when that lets their words be larger."""

from __future__ import annotations

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


def test_a_long_row_folds_onto_two_lines() -> None:
    from flexo.orient import wrapped

    with Figure("chain") as figure, figure.row("steps") as steps:
        previous = steps.text("x", "$x$")
        for index in range(7):
            previous = steps.block(f"s{index}", label=f"Step {index}", input=previous)
    spec = wrapped(figure.spec)
    group = next(group for group in spec.groups if group.id == "steps")
    assert group.layout.kind == "grid" and group.layout.columns == 4
    cells = group.layout.placement_map()
    assert cells["steps.s2"] == (0, 3) and cells["steps.s3"] == (1, 0)
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
