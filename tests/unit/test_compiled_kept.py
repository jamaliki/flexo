"""A figure laid out again for a box of another height -- a line of words added over it on a
slide -- is found compiled, not compiled again (flexo.boxfit.kept), and laid out as it would be
afresh; what its drawing remembered for its drafts is remembered again as it is found."""

from __future__ import annotations

import flexo
from flexo import boxfit, draft


def _flow(words: str = "Read") -> flexo.Figure:
    with flexo.Figure("flow") as figure:
        row = figure.root.row("row", gap=24)
        first = row.block("first", label=words)
        second = row.block("second", label="Write it all down")
        third = row.block("third", label="Check")
        figure.connect(first, second)
        figure.connect(second, third)
    return figure


def _same_fit(one: boxfit.BoxFit, other: boxfit.BoxFit) -> None:
    assert one.compilation.document.text == other.compilation.document.text
    assert (one.scale, one.ink, one.layout, one.words, one.errors, one.best) == (
        other.scale,
        other.ink,
        other.layout,
        other.words,
        other.errors,
        other.best,
    )


def test_a_figure_laid_out_again_for_a_box_of_another_height_is_compiled_once(
    monkeypatch,
) -> None:
    """Kept (``boxfit.kept``), a figure laid out in the layout it has for a box only as wide
    as before -- a line of words added over it -- is not compiled again, and is laid out as
    it would be afresh: its scale for the new box, whether it settles there."""

    store = boxfit.Kept()
    compiled: list[object] = []
    real = boxfit.compile_figure

    def counted(*args, **kwargs):
        compiled.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(boxfit, "compile_figure", counted)
    spec = _flow().spec
    for height in (160.0, 130.0, 100.0, 160.0):
        with boxfit.kept(store, "a slide"):
            kept = flexo.fit_in_box(spec, 520, height, keep="as written", whole=True)
        _same_fit(kept, flexo.fit_in_box(spec, 520, height, keep="as written", whole=True))
    # (Once kept; then once for each laid out afresh beside it, never kept.)
    assert len(compiled) == 1 + 4
    # Another width is another compilation; so is what else the figure is drawn from.
    with boxfit.kept(store, "a slide"):
        flexo.fit_in_box(spec, 400, 160.0, keep="as written", whole=True)
    with boxfit.kept(store, "another folder"):
        flexo.fit_in_box(spec, 520, 160.0, keep="as written", whole=True)
    assert len(compiled) == 1 + 4 + 2


def test_a_compilation_found_kept_is_remembered_for_drafts_as_if_drawn_again() -> None:
    """What a figure's drawing remembers for its drafts (``flexo.draft``) is remembered again,
    the same, in the same order, when the drawing is found kept: a draft drawn next starts
    from it as from the drawing made then."""

    spec = _flow("Remembered").spec
    store = boxfit.Kept()
    with boxfit.kept(store, "a slide"):
        flexo.fit_in_box(spec, 520, 160.0, keep="as written", whole=True)
    first = list(draft._REMEMBERED.items())[-2:]
    flexo.fit_in_box(_flow("Something else").spec, 520, 160.0)  # (remembered over it)
    with draft.recording() as remembered, boxfit.kept(store, "a slide"):
        flexo.fit_in_box(spec, 520, 120.0, keep="as written", whole=True)
    assert [(kind, key) for kind, key, _ in remembered] == [key for key, _ in first]
    assert list(draft._REMEMBERED.items())[-2:] == first


def test_a_draft_is_never_kept() -> None:
    spec = _flow("Drafted").spec
    store = boxfit.Kept()
    flexo.fit_in_box(spec, 520, 160.0)  # (a drawing for its drafts to follow)
    with draft.drafting(), boxfit.kept(store, "a slide"):
        flexo.fit_in_box(spec, 520, 160.0, keep="as written")
    assert not store.compiled


def test_drafts_remembered_within_a_recording_are_in_it_and_in_any_around_it() -> None:
    with draft.recording() as outer:
        draft.remember("layout", ("a",), 1)
        with draft.recording() as inner:
            draft.remember("routes", ("b",), 2)
    assert inner == [("routes", ("b",), 2)]
    assert outer == [("layout", ("a",), 1), ("routes", ("b",), 2)]
    draft.remember_again(outer)
    assert draft.recall("routes", ("b",)) == 2


def test_a_figure_drawn_ahead_is_remembered_only_once_it_is_found() -> None:
    """Drawn ahead of time (``draft.ahead``), what a figure's drawing remembers for its drafts is
    recorded but not remembered, and what it recalls leaves the memory as it was: remembered
    when the drawing is found kept, as though drawn then."""

    flexo.fit_in_box(_flow("Before").spec, 520, 160.0)
    before = list(draft._REMEMBERED.items())
    store = boxfit.Kept()
    spec = _flow("Ahead").spec
    with draft.ahead(), boxfit.kept(store, "a slide"):
        flexo.fit_in_box(spec, 520, 160.0, keep="as written", whole=True)
    assert list(draft._REMEMBERED.items()) == before
    with boxfit.kept(store, "a slide"):
        flexo.fit_in_box(spec, 520, 120.0, keep="as written", whole=True)
    kept_now = list(draft._REMEMBERED.items())
    flexo.fit_in_box(spec, 520, 120.0, keep="as written", whole=True)  # (drawn, not found)
    assert [key for key, _ in kept_now[-2:]] == [
        key for key, _ in list(draft._REMEMBERED.items())[-2:]
    ]
