"""A new line in a shape's words: ⇧Return in the studio, a new line in the file, or
``\\n`` typed (as Graphviz reads it) -- but not in maths or code, where ``\\nu`` and
``\\n`` are their own. A new line after the last words is no line of its own."""

from __future__ import annotations

import yaml

from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.markup import parse_label, parse_words


def _texts(label: str) -> list[str]:
    return [run.text for run in parse_label(label)]


def test_a_typed_backslash_n_starts_a_new_line_but_not_in_maths_or_code() -> None:
    assert _texts("Structure\\ndesign model") == ["Structure\ndesign model"]
    assert _texts("rate\\nper $\\nu$") == ["rate\nper ", "\N{MATHEMATICAL ITALIC SMALL NU}"]
    runs = parse_label("`a\\nb` then\\nnext")
    assert [(run.text, run.code) for run in runs] == [("a\\nb", True), (" then\nnext", False)]


def test_a_new_line_after_the_last_words_is_no_line_of_its_own() -> None:
    def height(label: str) -> float:
        figure = Figure("d")
        with figure, figure.row("r") as row:
            row.block("b", label=label)
        return compile_figure(figure.spec).fitted.node("r.b").bounds.height

    assert _texts("A\nB\n") == ["A\nB"] and _texts("A\\nB\\n") == ["A\nB"]
    assert parse_label("\n") == ()
    assert height("Generated\nbackbones\n") == height("Generated\nbackbones")


def test_words_given_a_new_line_in_the_studio_are_written_as_typed() -> None:
    from flexo.studio.figure_edit import apply

    action = {"do": "update", "target": {"type": "node", "id": "gen"}, "values": {"label": "A\nB"}}
    for text in (
        "figure: {id: p}\nnodes:\n  - {id: gen, label: A B}\n",
        "figure: {id: p}\nnodes:\n- id: gen\n  label: A B\n",
    ):
        written = apply(text, action)["text"]
        assert yaml.safe_load(written)["nodes"][0]["label"] == "A\nB", written


def test_running_text_keeps_its_words_as_written() -> None:
    # A slide's words, between their emphasis: a line that ends before bold words is kept,
    # and a backslash and n are only that.
    assert [run.text for run in parse_words("one\n")] == ["one\n"]
    assert [run.text for run in parse_words("a \\n b")] == ["a \\n b"]
    assert [run.text for run in parse_words("one\n[two]{accent}")] == ["one\n", "two"]
