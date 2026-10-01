"""Deterministic text shaping, wrapping, and baseline measurement."""

from __future__ import annotations

import itertools
import re
import unicodedata
from dataclasses import dataclass, replace
from functools import cache, lru_cache

import uharfbuzz as hb

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.fonts import (
    FontFace,
    LoadedFace,
    family_covering,
    family_faces,
    hb_font,
    load_face,
    require_family,
    select_face,
)
from flexo.ir.measured import MeasuredLine, TextMetrics
from flexo.ir.semantic import TextRun
from flexo.style import TypographyStyle

NO_BREAK = "\u00a0\u2007\u202f\u2060"
_NOT_FIRST = set(
    "、。，．・：；？！‐゠–〜～…‥ー」』）］｝〕〉》〙〛ぁぃぅぇ"  # noqa: RUF001 -- the marks themselves
    "ぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶ々〻.,!?:;)]}%"
)
"""What a line of Chinese or Japanese never starts with (kinsoku): closing marks, small kana."""
_NOT_LAST = set("「『（［｛〔〈《〘〚([{")  # noqa: RUF001 -- the marks themselves
"""What it never ends with: opening marks."""


def _cjk(character: str) -> bool:
    code = ord(character)
    return (
        0x3000 <= code <= 0x30FF or 0x3400 <= code <= 0x4DBF or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF or 0xFF00 <= code <= 0xFFEF or 0x20000 <= code <= 0x2FA1F
    )


def _cjk_units(token: str) -> list[str]:
    """``token`` cut where a line of Chinese or Japanese may break: between two
    characters, either of them Han or kana -- never before a closing mark or a small
    kana, nor after an opening mark. Words in other scripts in it stay whole."""

    if not any(_cjk(character) for character in token):
        return [token]
    units = [token[0]]
    for previous, character in itertools.pairwise(token):
        if (
            (_cjk(previous) or _cjk(character))
            and character not in _NOT_FIRST and previous not in _NOT_LAST
            and not unicodedata.category(character).startswith("M")
        ):
            units.append(character)
        else:
            units[-1] += character
    return units
"""Spaces a line is never broken at (a no-break space, ~ in a label; maths' thin space)."""
_TOKEN_PATTERN = re.compile(r"(?:[\u00a0\u2007\u202f\u2060]|\S)+|\s+")
_BREAK_AFTER = re.compile(r"[^/\-_.?&=]+[/\-_.?&=]*|[/\-_.?&=]+")

SHIFTED_SIZE = 0.72
ACCENT_SIZE = 0.78
"""An accent mark's size, as a fraction of the text it sits over."""

_TALL = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789bdfhklt"
    "\u0394\u0398\u039b\u03a3\u03a6\u03a8\u03a9\u03b2\u03b4\u03b6\u03b8\u03bb\u03be"
)
"""Letters that reach the ascender, so a mark over them sits higher."""


def accent_rise(run: TextRun, typography: TypographyStyle) -> float:
    """How far up an accent mark's baseline sits over ``run``, in points.

    A mark over a letter with an ascender (``h``, ``A``) clears the ascender;
    over one without (``x``, ``a``) it clears the x-height; over a script it
    rides the script's own shift.
    """

    size = typography.size.points
    scale = SHIFTED_SIZE if run.baseline_shift != "normal" else 1.0
    tall = any(character in _TALL for character in run.text)
    return script_shift(run.baseline_shift, run.italic, typography) + (
        0.62 if tall else 0.42
    ) * size * scale
"""Font-size factor of a superscript or subscript run.

One number shared by shaping, component labels, and connector captions, so the
width a run is measured at is the width it is drawn at.
"""

DEFAULT_RUN_WEIGHT = 400
"""The weight a ``TextRun`` carries when its author did not ask for one.

A run at this weight asked for nothing, so it inherits whatever the text object
it sits in declares -- ``title_weight`` for a group title, the text default for a
component label. Measurement and emission read the same constant, which is what
makes ``TextMeasurer.measure(runs, weight=...)`` the exact counterpart of the
``font-weight`` a ``<text>`` element carries.
"""


@dataclass(frozen=True, slots=True)
class FontData:
    raw: bytes
    upem: int
    ascent: int
    descent: int
    subscript_drop: int
    codepoints: frozenset[int]


DEFAULT_FALLBACKS = ("IBM Plex Sans", "Liberation Sans", "Latin Modern Math", "Fira Math")
"""Bundled families every stack ends in, for the glyphs its own families lack.

Figtree has no Greek and Latin Modern has no subscripts; Plex covers Greek and
most of the mathematical letters a caption reaches for, Liberation Sans the
modifier letters (``ᵀ``) Plex does not, and the two maths fonts the rest of
mathematics: its italic letters, script, blackboard and fraktur capitals, and
symbols such as ``∇`` and ``∈`` -- the one that suits the typography first (see
``maths_family``). All always resolve, so a glyph missing from the author's
family is still measured in the face that will draw it rather than rejected.
"""

SERIF_MATHS = "Latin Modern Math"
SANS_MATHS = "Fira Math"


def maths_family(typography: TypographyStyle) -> str:
    """The maths font a typography sets its formulas in: its own (``math_family``),
    else Latin Modern Math beside a serif face and Fira Math beside any other, so a
    formula's Greek, signs and brackets are drawn in the manner of its words."""

    if typography.math_family:
        return typography.math_family
    return SERIF_MATHS if typography.generic == "serif" else SANS_MATHS


MONO_FAMILIES = (
    "IBM Plex Mono", "JetBrains Mono", "Fira Code", "SF Mono", "Menlo", "Consolas",
    "DejaVu Sans Mono", "Liberation Mono", "Courier New",
)
"""Monospace families tried, in order, for code when a typography names none. The
first is bundled, so code is set alike on every machine, in the sibling of the Plex
Sans that sets what the words' face lacks."""


class FontStack:
    """The families one typography draws with, in fallback order.

    Each character is set in the first family that has it -- which is what a
    browser and Inkscape do with a ``font-family`` list -- so a width is always
    the width of the glyphs that will actually be drawn. The first family is the
    one whose vertical metrics (ascent, descent, subscript drop) set the line.
    """

    def __init__(self, typography: TypographyStyle) -> None:
        self.typography = typography
        maths = (typography.math_family,) if typography.math_family else ()
        # The maths font that suits the words comes before the other one.
        chosen = maths_family(typography)
        other = SERIF_MATHS if chosen != SERIF_MATHS else SANS_MATHS
        tail = (*DEFAULT_FALLBACKS[:2], chosen, other)
        names = (typography.family, *maths, *typography.fallbacks, *tail)
        primary = require_family(typography.family)
        families: list[tuple[FontFace, ...]] = [primary]
        seen = {primary[0].family.casefold()}
        for name in names[1:]:
            faces = family_faces(name)
            if faces and faces[0].family.casefold() not in seen:
                seen.add(faces[0].family.casefold())
                families.append(faces)
        self.families = tuple(families)

    def adopt(self, characters: set[str]) -> bool:
        """Add an installed family that has ``characters`` to the end of the stack.

        Used when no family in the stack has a glyph a label needs; the family
        found is then named on the ``tspan`` that uses it, like any fallback.
        """

        # A family for each script missing, not one for them all: Persian and Chinese
        # missing together found Arial Unicode MS, which then set every later Chinese,
        # Korean and Thai word in the deck, without bold.
        adopted = False
        for group in _by_script(characters):
            family = family_covering(group) or family_covering(characters)
            if family is None:
                continue
            faces = family_faces(family)
            known = {existing[0].family for existing in self.families}
            if not faces or faces[0].family in known:
                continue
            self.families = (*self.families, faces)
            adopted = True
        return adopted

    def face(self, weight: int, italic: bool, family: int = 0) -> FontFace:
        return select_face(self.families[family], weight, italic)

    def primary(self, italic: bool = False, weight: int = 400) -> LoadedFace:
        return load_face(self.face(weight, italic))

    def mono(self) -> tuple[FontFace, ...] | None:
        """The faces code is set in: the typography's monospace family, or the first
        installed of ``MONO_FAMILIES``."""

        names = (self.typography.mono_family,) if self.typography.mono_family else MONO_FAMILIES
        return next((faces for name in names if (faces := family_faces(name))), None)

    def segments(
        self, text: str, weight: int, italic: bool, *, code: bool = False
    ) -> list[tuple[FontFace, str]]:
        if code and (mono := self.mono()) is not None:
            # Code in the monospace face wherever it has the character, and in
            # the stack's faces where it does not.
            face = select_face(mono, weight, italic)
            loaded = load_face(face)
            pieces: list[tuple[FontFace, str]] = []
            for character in text:
                if loaded.has(character) or character.isspace():
                    if pieces and pieces[-1][0] == face:
                        pieces[-1] = (face, pieces[-1][1] + character)
                    else:
                        pieces.append((face, character))
                else:
                    pieces.extend(self.segments(character, weight, italic))
            return pieces
        return self._segments(text, weight, italic)

    def _segments(self, text: str, weight: int, italic: bool) -> list[tuple[FontFace, str]]:
        """``text`` split into runs of one face each.

        Each cluster -- a character and the combining marks after it -- is set
        in the first face that has all of its characters and, when it carries a
        mark, places that mark on the letter (a face with the glyphs but no
        anchor for that letter would draw the accent beside it). A cluster the
        primary face lacks stays in the fallback face of the cluster before it
        when that face has it.
        """

        faces = [self.face(weight, italic, index) for index in range(len(self.families))]
        loaded = [load_face(face) for face in faces]
        pieces: list[tuple[FontFace, str]] = []
        # Italic Greek the words' face lacks is TeX's, from the maths font -- a
        # fallback's italic θ may be drawn as ϑ, which is another letter in maths.
        maths = self.maths_index()
        if maths is not None and italic:
            # TeX's italic Greek is the mathematical italic alphabet of the maths font.
            text = "".join(
                _MATH_ITALIC.get(ch, ch)
                if not loaded[0].has(ch) and loaded[maths].has(_MATH_ITALIC.get(ch, ch))
                else ch
                for ch in text
            )
        clusters = _clusters(text)
        whole = self._whole_words(clusters, faces, loaded)
        for position, cluster in enumerate(clusters):
            if cluster.isspace():
                if pieces:
                    pieces[-1] = (pieces[-1][0], pieces[-1][1] + cluster)
                    continue
                choice = 0
            elif position in whole:
                choice = whole[position]
            else:
                covering = [
                    index
                    for index, item in enumerate(loaded)
                    if all(item.has(character) for character in cluster)
                ]
                choice = next(
                    (index for index in covering if _places_marks(faces[index], cluster)),
                    covering[0] if covering else 0,
                )
                previous = faces.index(pieces[-1][0]) if pieces else 0
                lettered = unicodedata.category(cluster[0])[0] in "LMNP"
                if choice > 0 and previous > 0 and previous in covering and lettered:
                    # Outside the primary face, stay in the fallback already in
                    # use: a word in another script is set in one font, not a
                    # mixture of every font that happens to have each glyph. A
                    # symbol (a check mark) takes the first face that has it.
                    choice = previous
            face = faces[choice]
            if pieces and pieces[-1][0] == face:
                pieces[-1] = (face, pieces[-1][1] + cluster)
            else:
                pieces.append((face, cluster))
        return pieces

    def _whole_words(
        self, clusters: list[str], faces: list[FontFace], loaded: list[LoadedFace]
    ) -> dict[int, int]:
        """The face for each cluster of a word the primary face has only part of, in one
        script (Vietnamese, which Figtree has some letters of): the first face that has
        all of the word, so a word is set in one face rather than letter by letter."""

        chosen: dict[int, int] = {}
        start = 0
        for end in range(len(clusters) + 1):
            if end < len(clusters) and not clusters[end].isspace():
                continue
            word = clusters[start:end]
            start = end + 1
            if not word or all(all(loaded[0].has(ch) for ch in cluster) for cluster in word):
                continue
            scripts = {
                unicodedata.name(cluster[0], "?").split()[0]
                for cluster in word if unicodedata.category(cluster[0]).startswith("L")
            }
            if len(scripts) != 1:
                continue
            for index in range(1, len(loaded)):
                if all(all(loaded[index].has(ch) for ch in cluster) for cluster in word) and all(
                    _places_marks(faces[index], cluster) for cluster in word
                ):
                    for offset in range(len(word)):
                        chosen[end - len(word) + offset] = index
                    break
        return chosen

    def maths_index(self, name: str | None = None) -> int | None:
        """Where the typography's maths family (or ``name``) sits in the stack, if it has one."""

        name = name or self.typography.math_family
        if not name:
            return None
        return next(
            (
                index
                for index, faces in enumerate(self.families)
                if faces[0].family.casefold() == name.casefold()
            ),
            None,
        )

    def missing(self, text: str, italic: bool) -> set[str]:
        """The characters of ``text`` no family here draws. Invisible format characters
        (a variation selector after ❤, a joiner) are never missing: they draw nothing."""

        loaded = [load_face(self.face(400, italic, index)) for index in range(len(self.families))]
        return {
            character
            for character in text
            if not character.isspace() and not _ignorable(character)
            and not any(item.has(character) for item in loaded)
        }


_IGNORABLE = (
    # Unicode's default ignorable code points: drawn as nothing when a face lacks them.
    (0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C), (0x115F, 0x1160), (0x17B4, 0x17B5),
    (0x180B, 0x180F), (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F), (0x3164, 0x3164),
    (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF), (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF),
)


def _ignorable(character: str) -> bool:
    code = ord(character)
    return any(low <= code <= high for low, high in _IGNORABLE)


_MATH_ITALIC = {
    # alpha to omega, final sigma included, then the variant forms and the partial.
    **{chr(0x03B1 + index): chr(0x1D6FC + index) for index in range(25)},
    **{
        chr(code): chr(0x1D716 + index)
        for index, code in enumerate((0x3F5, 0x3D1, 0x3F0, 0x3D5, 0x3F1, 0x3D6))
    },
    "\u2202": "\U0001D715",
}
"""Greek letters and their mathematical italic forms (U+1D6FC on)."""


def is_math_italic(character: str) -> bool:
    """Whether ``character`` is a mathematical italic Greek letter (already slanted)."""

    return 0x1D6FC <= ord(character[:1] or "\0") <= 0x1D71B


def _clusters(text: str) -> list[str]:
    """``text`` as characters, each with the combining marks that follow it."""

    clusters: list[str] = []
    for character in text:
        if clusters and unicodedata.combining(character):
            clusters[-1] += character
        else:
            clusters.append(character)
    return clusters


@cache
def _places_marks(face: FontFace, cluster: str) -> bool:
    """Whether ``face`` draws every mark of ``cluster`` on its letter, not beside it."""

    if len(cluster) < 2:
        return True
    font = hb_font(face, 400)
    buffer = hb.Buffer()
    buffer.add_str(cluster)
    buffer.guess_segment_properties()
    hb.shape(font, buffer, {})
    positions = buffer.glyph_positions
    if len(positions) == 1:
        return True  # composed into one glyph
    return all(
        position.x_offset != 0 or position.y_offset != 0 for position in positions[1:]
    )


def _by_script(characters: set[str]) -> list[set[str]]:
    """``characters`` grouped by the script their Unicode names begin with (CJK, ARABIC,
    HANGUL, THAI...); symbols with no script, each a group with what precedes it."""

    import unicodedata

    groups: dict[str, set[str]] = {}
    for character in sorted(characters):
        try:
            script = unicodedata.name(character).split()[0]
        except ValueError:
            script = "?"
        groups.setdefault(script, set()).add(character)
    return list(groups.values())


@cache
def font_stack(typography: TypographyStyle) -> FontStack:
    return FontStack(typography)


@lru_cache(maxsize=200_000)
def _advance(
    typography: TypographyStyle, text: str, weight: int, italic: bool, code: bool
) -> float:
    """How far ``text`` advances, in ems, shaped as ``font_stack(typography)`` sets it.

    Wrapping and balancing a paragraph measures each word many times over; a
    word measured once is not shaped again.
    """

    advance = 0.0
    for face, piece in font_stack(typography).segments(text, weight, italic, code=code):
        font = hb_font(face, weight)
        buffer = hb.Buffer()
        buffer.add_str(piece)
        buffer.guess_segment_properties()
        hb.shape(font, buffer, {"kern": True, "liga": True})
        upem = load_face(face).upem
        advance += sum(position.x_advance for position in buffer.glyph_positions) / upem
    return advance


def font_data(italic: bool = False, typography: TypographyStyle | None = None) -> FontData:
    """The primary face's metrics for ``typography`` (default: the paper style)."""

    loaded = font_stack(typography or TypographyStyle()).primary(italic)
    return FontData(
        raw=loaded.raw,
        upem=loaded.upem,
        ascent=loaded.ascent,
        descent=loaded.descent,
        subscript_drop=loaded.subscript_drop,
        codepoints=loaded.codepoints,
    )


def drawn_weight(run: TextRun, inherited: int | None) -> int:
    """The weight ``run`` will be set at: its own, or the one it inherits.

    The rule is the emission rule read backwards. A run whose weight is the
    ``TextRun`` default emits no ``font-weight``, so it comes out at whatever the
    ``<text>`` element around it declares; one that names a weight overrides it.
    Measuring through the same rule is what keeps a reserved band the width of
    the words that land in it.
    """

    if inherited is None or run.weight != DEFAULT_RUN_WEIGHT:
        return run.weight
    return inherited


def formula_of(run: TextRun, typography: TypographyStyle, inherited: int | None = None):
    """The formula a maths run (``TextRun.math``) is set as, at the size its words would be."""

    from flexo.texmath import typeset

    scale = SHIFTED_SIZE if run.baseline_shift != "normal" else 1.0
    return typeset(
        run.math, typography, typography.size.points * scale, weight=drawn_weight(run, inherited)
    )


def script_shift(shift: str, italic: bool, typography: TypographyStyle) -> float:
    """How far a sub- or superscript run's baseline moves, in points, up positive.

    Read from the primary face's own OS/2 offsets -- the numbers its designer
    chose -- and emitted as a length, so every renderer lowers a subscript by
    the same amount instead of interpreting the ``sub`` keyword its own way.
    """

    if shift == "normal":
        return 0.0
    face = font_stack(typography).primary(italic)
    size = typography.size.points
    # Clamped to typographic ranges: some faces ship a tool's default instead
    # of a designed offset (Figtree says 0.075 em), which barely drops a script.
    if shift == "sub":
        drop = min(max(face.subscript_drop / face.upem, 0.15), 0.25)
        return -drop * size
    rise = min(max(face.superscript_rise / face.upem, 0.3), 0.45)
    return rise * size


def stacked_scripts(line: tuple[TextRun, ...]) -> list[tuple[range, range]]:
    """Pairs of script groups set one over the other, as ``(first, second)`` run ranges.

    ``x^2_B`` is a superscript and a subscript on one letter; TeX stacks them
    at the same place, the pair as wide as the wider, rather than setting the
    subscript after the superscript. A group is a run of consecutive runs at
    one shift -- ``^{(i)}`` may be three runs -- and a group stacks on the group
    of the other kind just before it, unless that one already stacks.
    """

    groups: list[range] = []
    start = 0
    for index in range(1, len(line) + 1):
        if index == len(line) or line[index].baseline_shift != line[start].baseline_shift:
            if line[start].baseline_shift != "normal":
                groups.append(range(start, index))
            start = index
    pairs: list[tuple[range, range]] = []
    for first, second in itertools.pairwise(groups):
        if (
            first.stop == second.start
            and line[first.start].baseline_shift != line[second.start].baseline_shift
            and not (pairs and pairs[-1][1] == first)
        ):
            pairs.append((first, second))
    return pairs


def ink_descent(metrics: TextMetrics, typography: TypographyStyle) -> float:
    """How far the lowest ink of measured text falls below its last baseline.

    ``TextMetrics.descent`` is the font's descender for text on one baseline. A
    subscript run sits on a *dropped* baseline and takes its own descender from
    there, so ``softmax(-ΣD_q)V`` reaches lower than its metrics claim -- which
    is exactly the amount that decides whether a caption grazes the arrow it
    labels.
    """

    size = typography.size.points
    depth = metrics.descent
    for line in metrics.lines:
        for run in line.runs:
            if run.math:
                depth = max(depth, formula_of(run, typography).depth)
                continue
            if run.baseline_shift != "sub":
                continue
            font = font_data(run.italic, typography)
            drop = -script_shift("sub", run.italic, typography)
            depth = max(depth, drop + SHIFTED_SIZE * font.descent / font.upem * size)
    return depth


class TextMeasurer:
    """Shape text with HarfBuzz using the exact bundled output font."""

    def __init__(self, typography: TypographyStyle) -> None:
        self.typography = typography
        self.stack = font_stack(typography)

    def measure(
        self,
        runs: tuple[TextRun, ...],
        *,
        max_width: float | None = None,
        weight: int | None = None,
        balance: bool = True,
        break_words: bool = False,
    ) -> TextMetrics:
        """Shape ``runs`` at the weights they will actually be drawn at.

        Wrapped lines are balanced to similar lengths, as a label is set by
        hand; ``balance=False`` fills each line in turn instead, as a word
        processor or slide program wraps a paragraph. ``break_words=True`` breaks
        a word wider than the line (a URL) after a ``/``, ``-``, ``_``, or ``.``,
        or between letters if it must, instead of letting it overrun.

        ``weight`` is what the text object these runs will sit in declares, and a
        run that named no weight of its own is measured at it -- because that is
        the weight it will inherit. A group title is the case that matters: its
        runs carry the ``TextRun`` default and its ``<text>`` element carries
        ``title_weight``, so measuring at 400 and drawing at 600 reserved a band
        narrower than the words it holds. Left out, every run is measured at the
        weight it declares, which is right for a component label or a caption.
        """

        if not runs or not any(run.text for run in runs):
            return TextMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, ())
        self._validate_glyphs(runs)
        hard_lines = _split_hard_lines(runs)
        lines = tuple(
            line
            for hard_line in hard_lines
            for line in (
                self._balanced(hard_line, max_width, weight, break_words)
                if balance
                else self._wrap_line(hard_line, max_width, weight, break_words)
            )
        )
        measured_lines = tuple(
            MeasuredLine(line, self.line_width(line, weight)) for line in lines
        )
        font = self.stack.primary()
        size = self.typography.size.points
        ascent = font.ascent / font.upem * size
        descent = font.descent / font.upem * size
        line_height = size * self.typography.line_height
        leading = max(0.0, line_height - ascent - descent)
        baseline = leading / 2.0 + ascent
        cap = font.cap_height / font.upem * size if font.cap_height else 0.7 * size
        # A formula taller than the line (a fraction, a matrix) opens the lines up
        # enough to hold it; every line keeps the same step, so they stay even.
        rise = fall = 0.0
        for measured in measured_lines:
            for run in measured.runs:
                if run.math:
                    formula = formula_of(run, self.typography, weight)
                    rise = max(rise, formula.height - (ascent + leading / 2.0))
                    fall = max(fall, formula.depth - (descent + leading / 2.0))
        line_height += rise + fall
        baseline += rise
        return TextMetrics(
            width=max((line.width for line in measured_lines), default=0.0),
            height=line_height * len(measured_lines),
            ascent=ascent,
            descent=descent,
            baseline=baseline,
            line_height=line_height,
            lines=measured_lines,
            cap_height=cap,
            rise=rise,
            fall=fall,
        )

    def mark_width(self, mark: str, italic: bool = False) -> float:
        """How wide an accent mark (``TextRun.accent``) is drawn, at ``ACCENT_SIZE``."""

        return self._shape_run(TextRun(mark, 400, italic)) * ACCENT_SIZE

    def run_widths(self, line: tuple[TextRun, ...], weight: int | None = None) -> list[float]:
        """The advance of each run of ``line``, as it would be set on its own."""

        return [self._shape_run(run, weight) for run in line]

    def line_width(self, line: tuple[TextRun, ...], weight: int | None = None) -> float:
        """How wide ``line`` is set: a stacked pair of scripts is as wide as the wider."""

        widths = self.run_widths(line, weight)
        width = sum(widths)
        for first, second in stacked_scripts(line):
            width -= min(sum(widths[i] for i in first), sum(widths[i] for i in second))
        return width

    def _shape_run(self, run: TextRun, inherited: int | None = None) -> float:
        if run.math:
            return formula_of(run, self.typography, inherited).width
        if not run.text:
            return 0.0
        weight = drawn_weight(run, inherited)
        advance = _advance(self.typography, run.text, weight, run.italic, run.code)
        scale = SHIFTED_SIZE if run.baseline_shift != "normal" else 1.0
        tracking = self.typography.tracking * len(run.text)
        return (advance + tracking) * self.typography.size.points * scale

    def _balanced(
        self,
        line: tuple[TextRun, ...],
        max_width: float | None,
        weight: int | None,
        break_words: bool = False,
    ) -> tuple[tuple[TextRun, ...], ...]:
        """``line`` wrapped at ``max_width`` into lines of similar length.

        Greedy wrapping fills each line and leaves the last one short -- "Multi-
        head self-attention with rotary / embeddings". The narrowest width that
        still needs no more lines than greedy wrapping does spreads the words
        evenly instead, which is how a label is set by hand.
        """

        wrapped = self._wrap_line(line, max_width, weight, break_words)
        if len(wrapped) < 2 or max_width is None:
            return wrapped
        # Never narrower than its widest word: evened out, a line would break a word
        # ("Colum / n") that fits whole.
        low, high = min(self._widest_word(line, weight), max_width), max_width
        for _ in range(12):
            middle = (low + high) / 2.0
            if len(self._wrap_line(line, middle, weight, break_words)) <= len(wrapped):
                high = middle
            else:
                low = middle
        return self._wrap_line(line, high, weight, break_words)

    def _widest_word(self, line: tuple[TextRun, ...], weight: int | None) -> float:
        """The widest stretch of the line between spaces (runs that touch are one word)."""

        widest, word = 0.0, []
        for run in line:
            if run.math:
                word.append(run)
                continue
            for token in _TOKEN_PATTERN.findall(run.text):
                if token.isspace() and not any(ch in NO_BREAK for ch in token):
                    if word:
                        widest = max(widest, self.line_width(tuple(word), weight))
                    word = []
                elif len(units := _cjk_units(token)) > 1:
                    # Each unit of Chinese or Japanese is a word of its own.
                    for unit in units[:-1]:
                        word.append(replace(run, text=unit))
                        widest = max(widest, self.line_width(tuple(word), weight))
                        word = []
                    word.append(replace(run, text=units[-1]))
                else:
                    word.append(replace(run, text=token))
        if word:
            widest = max(widest, self.line_width(tuple(word), weight))
        return widest

    def _wrap_line(
        self,
        line: tuple[TextRun, ...],
        max_width: float | None,
        weight: int | None = None,
        break_words: bool = False,
    ) -> tuple[tuple[TextRun, ...], ...]:
        if max_width is None or max_width <= 0.0:
            return (line,)
        # Each token with its width, whether it is a space, and whether a line may break
        # before it: after a space, between the pieces of a formula TeX breaks, or inside
        # a word too long for any line -- never where two runs touch (a subscript, a
        # comma after a formula, a bold word's last letter), which read as one word.
        items: list[tuple[TextRun, float, bool, bool]] = []
        after_space = True
        for run in line:
            if run.math:
                # A formula wider than the line breaks where TeX would break it, after a
                # relation or an operator at its top level; else it is one piece.
                pieces = (run.math,)
                inline = not run.math.startswith("\\displaystyle")
                if inline and self._shape_run(run, weight) > max_width:
                    from flexo.texmath import breakable

                    pieces = breakable(run.math)
                for index, piece in enumerate(pieces):
                    token_run = replace(run, math=piece)
                    width = self._shape_run(token_run, weight)
                    items.append((token_run, width, False, after_space or index > 0))
                after_space = False
                continue
            for token in _TOKEN_PATTERN.findall(run.text):
                if token.isspace():
                    token_run = replace(run, text=token)
                    items.append((token_run, self._shape_run(token_run, weight), True, True))
                    after_space = True
                    continue
                word = replace(run, text=token)
                units = _cjk_units(token)
                if len(units) > 1:
                    pieces = units  # Chinese and Japanese break between characters
                else:
                    pieces = self._pieces(word, max_width, weight) if break_words else [token]
                for index, piece in enumerate(pieces):
                    token_run = replace(run, text=piece)
                    width = self._shape_run(token_run, weight)
                    items.append((token_run, width, False, after_space or index > 0))
                after_space = False
        units: list[list[tuple[TextRun, float, bool, bool]]] = []
        for item in items:
            if item[2] or item[3] or not units or units[-1][0][2]:
                units.append([item])
            else:
                units[-1].append(item)
        wrapped: list[tuple[TextRun, ...]] = []
        current: list[TextRun] = []
        current_width = 0.0
        for unit in units:
            width = sum(item[1] for item in unit)
            if unit[0][2]:  # a space: kept between words, dropped at the start of a line
                if current:
                    current.append(unit[0][0])
                    current_width += width
                continue
            if current and current_width + width > max_width:
                wrapped.append(_trim_and_merge(current))
                current, current_width = [], 0.0
            if width > max_width and len(unit) > 1:
                # Runs glued into one word wider than any line: broken between them.
                for token_run, token_width, _, _ in unit:
                    if current and current_width + token_width > max_width:
                        wrapped.append(_trim_and_merge(current))
                        current, current_width = [], 0.0
                    current.append(token_run)
                    current_width += token_width
                continue
            current.extend(item[0] for item in unit)
            current_width += width
        wrapped.append(_trim_and_merge(current))
        return tuple(wrapped)

    def _pieces(self, run: TextRun, max_width: float, weight: int | None) -> list[str]:
        """A word, as pieces no wider than a line: split after URL punctuation, then letters."""

        if run.text.isspace() or self._shape_run(run, weight) <= max_width:
            return [run.text]
        pieces: list[str] = []
        for part in _BREAK_AFTER.findall(run.text):
            if self._shape_run(replace(run, text=part), weight) <= max_width:
                pieces.append(part)
                continue
            start = 0
            while start < len(part):
                # The longest piece from here that fits (a character at least): found by
                # doubling, then halving, so a word of a million letters is not shaped
                # a letter longer at a time.
                def fits(count: int, start: int = start, part: str = part) -> bool:
                    piece = replace(run, text=part[start : start + count])
                    return self._shape_run(piece, weight) <= max_width

                remaining = len(part) - start
                good, probe = 1, 2
                while probe <= remaining and fits(probe):
                    good, probe = probe, probe * 2
                bad = min(probe, remaining + 1)
                while bad - good > 1:
                    middle = (good + bad) // 2
                    good, bad = (middle, bad) if fits(middle) else (good, middle)
                pieces.append(part[start : start + good])
                start += good
        return pieces

    def _validate_glyphs(self, runs: tuple[TextRun, ...]) -> None:
        missing: set[str] = set()
        runs = tuple(run for run in runs if not run.math)  # a formula brings its own glyphs
        for run in runs:
            missing |= self.stack.missing(run.text, run.italic)
        if missing and self.stack.adopt(missing):
            missing = set()
            for run in runs:
                missing |= self.stack.missing(run.text, run.italic)
        if missing:
            rendered = ", ".join(repr(character) for character in sorted(missing))
            families = ", ".join(faces[0].family for faces in self.stack.families)
            raise FlexoError(
                Diagnostic(
                    "font.glyph.missing",
                    f"No font in the stack ({families}) contains: {rendered}.",
                    hint=(
                        "No installed font has them either. Install or register "
                        "(flexo.register_font) a font that does, or draw the symbol "
                        "(flexo's op() component draws \u2295 and \u2297 as shapes)."
                    ),
                )
            )


def _split_hard_lines(runs: tuple[TextRun, ...]) -> tuple[tuple[TextRun, ...], ...]:
    lines: list[list[TextRun]] = [[]]
    for run in runs:
        parts = run.text.split("\n")
        for index, part in enumerate(parts):
            if part:
                lines[-1].append(replace(run, text=part))
            if index < len(parts) - 1:
                lines.append([])
    return tuple(_trim_and_merge(line) for line in lines)


def _trim_and_merge(runs: list[TextRun]) -> tuple[TextRun, ...]:
    while runs and runs[-1].text.isspace():
        runs.pop()
    merged: list[TextRun] = []
    for run in runs:
        if merged and not run.accent and not merged[-1].accent and not run.math \
                and not merged[-1].math and (
            merged[-1].weight,
            merged[-1].italic,
            merged[-1].baseline_shift,
            merged[-1].code,
            merged[-1].link,
            merged[-1].color,
        ) == (run.weight, run.italic, run.baseline_shift, run.code, run.link, run.color):
            merged[-1] = replace(merged[-1], text=merged[-1].text + run.text)
        else:
            merged.append(run)
    return tuple(merged)


def title_runs(runs: tuple[TextRun, ...], typography: TypographyStyle) -> tuple[TextRun, ...]:
    """A group title's runs as they are set: in capitals when the style says so."""

    if typography.title_transform != "upper":
        return runs
    return tuple(
        run if run.math else replace(run, text=run.text.upper()) for run in runs
    )


def title_typography(typography: TypographyStyle) -> TypographyStyle:
    """The typography a group title is set in: the body's, scaled by ``title_size``."""

    if typography.title_size == 1.0:
        return typography
    from dataclasses import replace

    from flexo.units import Length

    return replace(typography, size=Length(typography.size.points * typography.title_size))
