"""A compilation linted once (``flexo.lint.lint_compilation``): a figure laid out for a slide is
linted as its layout is chosen and again as its slide says what is wrong with it -- the same
report, worked out once, unless the style or how its pictures are drawn differs."""

from __future__ import annotations

from flexo import lint
from flexo.artwork import picture_link
from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.themes import figure_style


def _compiled():
    with Figure("linted") as figure, figure.column("steps") as steps:
        first = steps.block("a", label="Alpha")
        steps.block("b", label="Beta", input=first)
    return compile_figure(figure.spec)


def test_the_same_compilation_in_the_same_style_is_linted_once(monkeypatch) -> None:
    compiled = _compiled()
    style = figure_style(compiled.measured.semantic)
    gone_through: list[object] = []
    real = lint._fitted_diagnostics
    monkeypatch.setattr(lint, "_fitted_diagnostics", lambda c: gone_through.append(c) or real(c))
    first = lint.lint_compilation(compiled, style=style)
    assert lint.lint_compilation(compiled, style=style) is first
    assert len(gone_through) == 1
    # Another style, another compilation, or its pictures drawn otherwise: linted afresh.
    assert lint.lint_compilation(compiled) == first
    other = _compiled()
    assert lint.lint_compilation(other, style=style) == first
    token = picture_link.set(lambda artwork: "/picture")
    try:
        assert lint.lint_compilation(compiled, style=style) == first
    finally:
        picture_link.reset(token)
    assert len(gone_through) == 4


def test_only_the_last_few_are_kept() -> None:
    compiled = [_compiled() for _ in range(lint.LINTED + 2)]
    for item in compiled:
        lint.lint_compilation(item)
    assert len(lint._LINTED) <= lint.LINTED
    assert all(entry[0] is not compiled[0] for entry in lint._LINTED.values())
