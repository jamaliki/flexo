from __future__ import annotations

import unicodedata

from flexo.ir.semantic import TextRun
from flexo.shifted import SHIFTED_CHARACTERS, shifted_runs
from flexo.text import drawable


def _nothing_is_drawable(character: str, italic: bool = False) -> bool:
    return False


def _everything_is_drawable(character: str, italic: bool = False) -> bool:
    return True


def _cut(text: str, drawable_test=_nothing_is_drawable, **run: object) -> list[tuple[str, str]]:
    runs = shifted_runs((TextRun(text, **run),), drawable_test)  # type: ignore[arg-type]
    return [(item.text, item.baseline_shift) for item in runs]


def test_the_table_says_what_unicode_says() -> None:
    """The table is frozen, so it has to be checked against its own source.

    Every entry claims a character *is* a shifted form of another, which is a
    fact Unicode records as a compatibility decomposition rather than an opinion
    this module is entitled to. Freezing the table keeps one label setting the
    same way under every Python; this test keeps the frozen copy honest.
    """

    for character, (base, shift) in SHIFTED_CHARACTERS.items():
        assert unicodedata.decomposition(character) == f"<{shift}> {ord(base):04X}", character
    assert len(set(SHIFTED_CHARACTERS)) == len(SHIFTED_CHARACTERS)


def test_the_table_avoids_the_ordinal_indicators() -> None:
    """``1ª`` is a Spanish abbreviation, not a raised ``a``."""

    assert "ª" not in SHIFTED_CHARACTERS
    assert "º" not in SHIFTED_CHARACTERS


def test_text_without_a_shifted_character_is_handed_back_untouched() -> None:
    """The common label pays nothing and cannot possibly change."""

    runs = (TextRun("softmax"), TextRun("QK", weight=700))
    assert shifted_runs(runs, _nothing_is_drawable) is runs


def test_a_superscript_becomes_its_own_run() -> None:
    assert _cut("softmax(QKᵀ)V") == [
        ("softmax(QK", "normal"),
        ("T", "super"),
        (")V", "normal"),
    ]


def test_a_subscript_becomes_its_own_run() -> None:
    assert _cut("Dₖ") == [("D", "normal"), ("k", "sub")]
    assert _cut("xₗ₊₁ + b") == [("x", "normal"), ("l+1", "sub"), (" + b", "normal")]


def test_neighbouring_shifts_of_different_kinds_stay_apart() -> None:
    assert _cut("Cᵀₖ") == [("C", "normal"), ("T", "super"), ("k", "sub")]


def test_a_run_the_face_can_draw_is_left_exactly_as_typed() -> None:
    """A designed inferior beats a shrunken one, so the font's version wins."""

    assert _cut("x₀", _everything_is_drawable) == [("x₀", "normal")]
    assert _cut("x₀", drawable) == [("x₀", "normal")]


def test_a_group_is_translated_all_together_or_not_at_all() -> None:
    """``A₀ₖ`` is one subscript, so it may not be drawn two different ways.

    IBM Plex has ``₀`` and no ``ₖ``. Deciding per character would set the zero
    as a designed inferior and the k as a shrunken letter, side by side at
    different sizes; deciding per group keeps the pair one subscript.
    """

    assert _cut("A₀ₖ", drawable) == [("A", "normal"), ("0k", "sub")]
    assert _cut("A₀", drawable) == [("A₀", "normal")]


def test_a_shifted_run_keeps_its_own_shift() -> None:
    """SVG has no superscript of a superscript, so the run's shift stands."""

    assert _cut("ᵀ", baseline_shift="super") == [("T", "super")]
    assert _cut("ₖ", baseline_shift="super") == [("k", "super")]


def test_translation_carries_weight_and_italics_across() -> None:
    runs = shifted_runs((TextRun("Aᵀ", weight=700, italic=True),), _nothing_is_drawable)
    assert [(run.text, run.weight, run.italic, run.baseline_shift) for run in runs] == [
        ("A", 700, True, "normal"),
        ("T", 700, True, "super"),
    ]


def test_every_translatable_character_has_a_glyph_to_translate_into() -> None:
    """A shifted run is only an improvement if the base character can be drawn.

    Trading ``ᵀ`` for a raised ``T`` is a fix; trading it for a second missing
    glyph is the same error with more steps. Both faces answer, because a run
    may be italic.
    """

    undrawable = {
        character
        for character, (base, _) in SHIFTED_CHARACTERS.items()
        if not (drawable(base) and drawable(base, italic=True))
    }
    assert not undrawable
