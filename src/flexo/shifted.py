"""Superscript and subscript characters an author can type, set as runs.

An author writing an attention block writes ``softmax(QKᵀ)V``, because that is
what the formula looks like. The bundled face has no ``ᵀ`` -- almost no text
face does; the Unicode superscripts that exist as real glyphs are the digits and
little else -- so that spelling used to be a ``font.glyph.missing`` error, and
the only way to get the transpose onto the page was to know what a ``TextRun``
is and hand-build ``(TextRun("softmax(QK"), TextRun("T", baseline_shift="super"),
TextRun(")V"))``.

This module translates the typed spelling into exactly those runs. Unicode
already records the answer: every character here decomposes as ``<super>`` or
``<sub>`` onto a base character, so ``ᵀ`` is *defined* to be a raised ``T``, and
setting it as one is typesetting rather than guesswork.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Literal

from flexo.ir.semantic import TextRun

type Shift = Literal["super", "sub"]

SHIFTED_CHARACTERS: dict[str, tuple[str, Shift]] = {
    # Superscripts: the U+2070 block, the three Latin-1 digits, and the
    # modifier letters typed as superscripts. Frozen here rather than read from
    # ``unicodedata`` at import so that one label sets the same way under every
    # Python, whatever Unicode version it ships.
    "⁰": ("0", "super"),
    "¹": ("1", "super"),
    "²": ("2", "super"),
    "³": ("3", "super"),
    "⁴": ("4", "super"),
    "⁵": ("5", "super"),
    "⁶": ("6", "super"),
    "⁷": ("7", "super"),
    "⁸": ("8", "super"),
    "⁹": ("9", "super"),
    "⁺": ("+", "super"),
    "⁻": ("−", "super"),  # noqa: RUF001
    "⁼": ("=", "super"),
    "⁽": ("(", "super"),
    "⁾": (")", "super"),
    "ᴬ": ("A", "super"),
    "ᴮ": ("B", "super"),
    "ᴰ": ("D", "super"),
    "ᴱ": ("E", "super"),
    "ᴳ": ("G", "super"),
    "ᴴ": ("H", "super"),
    "ᴵ": ("I", "super"),
    "ᴶ": ("J", "super"),
    "ᴷ": ("K", "super"),
    "ᴸ": ("L", "super"),
    "ᴹ": ("M", "super"),
    "ᴺ": ("N", "super"),
    "ᴼ": ("O", "super"),
    "ᴾ": ("P", "super"),
    "ᴿ": ("R", "super"),
    "ᵀ": ("T", "super"),
    "ᵁ": ("U", "super"),
    "ⱽ": ("V", "super"),
    "ᵂ": ("W", "super"),
    "ᵃ": ("a", "super"),
    "ᵇ": ("b", "super"),
    "ᶜ": ("c", "super"),
    "ᵈ": ("d", "super"),
    "ᵉ": ("e", "super"),
    "ᶠ": ("f", "super"),
    "ᵍ": ("g", "super"),
    "ʰ": ("h", "super"),
    "ⁱ": ("i", "super"),
    "ʲ": ("j", "super"),
    "ᵏ": ("k", "super"),
    "ˡ": ("l", "super"),
    "ᵐ": ("m", "super"),
    "ⁿ": ("n", "super"),
    "ᵒ": ("o", "super"),
    "ᵖ": ("p", "super"),
    "ʳ": ("r", "super"),
    "ˢ": ("s", "super"),
    "ᵗ": ("t", "super"),
    "ᵘ": ("u", "super"),
    "ᵛ": ("v", "super"),
    "ʷ": ("w", "super"),
    "ˣ": ("x", "super"),
    "ʸ": ("y", "super"),
    "ᶻ": ("z", "super"),
    "ᵝ": ("β", "super"),
    "ᵞ": ("γ", "super"),  # noqa: RUF001
    "ᵟ": ("δ", "super"),
    "ᵠ": ("φ", "super"),
    "ᵡ": ("χ", "super"),
    # Subscripts: the U+2080 block plus the handful of Latin and Greek
    # subscript letters that live outside it.
    "₀": ("0", "sub"),
    "₁": ("1", "sub"),
    "₂": ("2", "sub"),
    "₃": ("3", "sub"),
    "₄": ("4", "sub"),
    "₅": ("5", "sub"),
    "₆": ("6", "sub"),
    "₇": ("7", "sub"),
    "₈": ("8", "sub"),
    "₉": ("9", "sub"),
    "₊": ("+", "sub"),
    "₋": ("−", "sub"),  # noqa: RUF001
    "₌": ("=", "sub"),
    "₍": ("(", "sub"),
    "₎": (")", "sub"),
    "ₐ": ("a", "sub"),
    "ₑ": ("e", "sub"),
    "ₕ": ("h", "sub"),
    "ᵢ": ("i", "sub"),
    "ⱼ": ("j", "sub"),
    "ₖ": ("k", "sub"),
    "ₗ": ("l", "sub"),
    "ₘ": ("m", "sub"),
    "ₙ": ("n", "sub"),
    "ₒ": ("o", "sub"),
    "ₚ": ("p", "sub"),
    "ᵣ": ("r", "sub"),
    "ₛ": ("s", "sub"),
    "ₜ": ("t", "sub"),
    "ᵤ": ("u", "sub"),
    "ᵥ": ("v", "sub"),
    "ₓ": ("x", "sub"),
    "ᵦ": ("β", "sub"),
    "ᵧ": ("γ", "sub"),  # noqa: RUF001
    "ᵨ": ("ρ", "sub"),  # noqa: RUF001
    "ᵩ": ("φ", "sub"),
    "ᵪ": ("χ", "sub"),
}
"""Every character that may be set as a shifted run, and what it is made of.

Two of Unicode's ``<super>`` characters are deliberately absent: ``ª`` and ``º``
are ordinal indicators, letters of Spanish and Portuguese orthography rather
than markup, and an author writing ``1ª`` means the word and not a raised ``a``.
Everything else omitted from the Unicode tables is phonetic notation (``ᶴ``,
``𐞥``) or CJK annotation, which a figure label is not written in.
"""


def shifted_runs(
    runs: tuple[TextRun, ...],
    drawable: Callable[[str, bool], bool],
) -> tuple[TextRun, ...]:
    """Re-cut ``runs`` so typed super/subscripts become baseline-shifted runs.

    A contiguous stretch of shifted characters is translated *as a unit* --
    all of it or none of it -- and only when the face cannot draw the stretch
    itself, which ``drawable`` answers for a character in a roman or italic
    face. The two halves of that rule are one idea: a shifted character should
    be set the best way available, and a group should be set one way.

    Where the face has a real glyph, that glyph wins. IBM Plex draws ``₀``-``₉``
    and ``⁰``-``⁹`` as designed inferiors and superiors, cut to sit against text
    of this weight; a ``0`` shrunk to 72% and dropped by the font's subscript
    offset is a mechanical imitation of exactly that, so ``x₀`` keeps the
    typographer's version and comes out byte-identical to what Flexo drew
    before this module existed. Where the face has nothing -- ``ᵀ``, ``ₖ``,
    ``⁻``, every letter -- a shifted run is the only version there is, and it
    beats the error that used to be the alternative.

    Translating by group is what keeps ``A₀ₖ`` from being drawn half one way
    and half the other: ``₀`` alone would stay a designed glyph, but standing
    next to a ``ₖ`` the face lacks, it joins it in a single ``0k`` subscript
    run, which reads as one subscript because it is one.

    A run that is *already* shifted takes the base characters and keeps its own
    shift -- SVG has no superscript of a superscript -- so ``TextRun("ᵀ",
    baseline_shift="super")`` sets as a raised ``T`` rather than failing.
    """

    if not any(character in SHIFTED_CHARACTERS for run in runs for character in run.text):
        return runs
    return tuple(part for run in runs for part in _expand(run, drawable))


def _expand(run: TextRun, drawable: Callable[[str, bool], bool]) -> Iterator[TextRun]:
    kept: list[str] = []
    for shift, text in _groups(run.text):
        if shift is None or all(drawable(character, run.italic) for character in text):
            # Text staying as typed is text the run already covers, whether or
            # not the character is a shifted one: ``A`` and ``₀`` came in as one
            # run and go out as one, so a label the face can draw is not merely
            # drawn the same, it is the same runs.
            kept.append(text)
            continue
        if kept:
            yield TextRun("".join(kept), run.weight, run.italic, run.baseline_shift)
            kept = []
        yield TextRun(
            "".join(SHIFTED_CHARACTERS[character][0] for character in text),
            run.weight,
            run.italic,
            shift if run.baseline_shift == "normal" else run.baseline_shift,
        )
    if kept:
        yield TextRun("".join(kept), run.weight, run.italic, run.baseline_shift)


def _groups(text: str) -> Iterator[tuple[Shift | None, str]]:
    """``text`` cut into maximal stretches of one shift class, in order."""

    start = 0
    current: Shift | None = None
    for index, character in enumerate(text):
        entry = SHIFTED_CHARACTERS.get(character)
        shift = entry[1] if entry else None
        if index and shift != current:
            yield current, text[start:index]
            start = index
        current = shift
    if text:
        yield current, text[start:]
