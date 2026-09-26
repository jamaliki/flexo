"""Deterministic text shaping, wrapping, and baseline measurement."""

from __future__ import annotations

import itertools
import re
import unicodedata
from dataclasses import dataclass
from functools import cache

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

_TOKEN_PATTERN = re.compile(r"\S+|\s+")

SHIFTED_SIZE = 0.72
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


DEFAULT_FALLBACKS = ("IBM Plex Sans", "Liberation Sans", "Latin Modern Math")
"""Bundled families every stack ends in, for the glyphs its own families lack.

Figtree has no Greek and Latin Modern has no subscripts; Plex covers Greek and
most of the mathematical letters a caption reaches for, Liberation Sans the
modifier letters (``ᵀ``) Plex does not, and Latin Modern Math the rest of
mathematics: script, blackboard and fraktur capitals, and symbols such as
``∇`` and ``∈``. All three always resolve, so a glyph missing from the
author's family is still measured in the face that will draw it rather than
rejected.
"""


class FontStack:
    """The families one typography draws with, in fallback order.

    Each character is set in the first family that has it -- which is what a
    browser and Inkscape do with a ``font-family`` list -- so a width is always
    the width of the glyphs that will actually be drawn. The first family is the
    one whose vertical metrics (ascent, descent, subscript drop) set the line.
    """

    def __init__(self, typography: TypographyStyle) -> None:
        self.typography = typography
        names =(typography.family, *typography.fallbacks, *DEFAULT_FALLBACKS)
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

        family = family_covering(characters)
        if family is None:
            return False
        faces = family_faces(family)
        if not faces or any(existing[0].family == faces[0].family for existing in self.families):
            return False
        self.families = (*self.families, faces)
        return True

    def face(self, weight: int, italic: bool, family: int = 0) -> FontFace:
        return select_face(self.families[family], weight, italic)

    def primary(self, italic: bool = False, weight: int = 400) -> LoadedFace:
        return load_face(self.face(weight, italic))

    def segments(self, text: str, weight: int, italic: bool) -> list[tuple[FontFace, str]]:
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
        for cluster in _clusters(text):
            if cluster.isspace():
                if pieces:
                    pieces[-1] = (pieces[-1][0], pieces[-1][1] + cluster)
                    continue
                choice = 0
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
                if choice > 0 and previous > 0 and previous in covering:
                    # Outside the primary face, stay in the fallback already in
                    # use: a word in another script is set in one font, not a
                    # mixture of every font that happens to have each glyph.
                    choice = previous
            face = faces[choice]
            if pieces and pieces[-1][0] == face:
                pieces[-1] = (face, pieces[-1][1] + cluster)
            else:
                pieces.append((face, cluster))
        return pieces

    def missing(self, text: str, italic: bool) -> set[str]:
        loaded = [load_face(self.face(400, italic, index)) for index in range(len(self.families))]
        return {
            character
            for character in text
            if not character.isspace() and not any(item.has(character) for item in loaded)
        }


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


@cache
def font_stack(typography: TypographyStyle) -> FontStack:
    return FontStack(typography)


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
    ) -> TextMetrics:
        """Shape ``runs`` at the weights they will actually be drawn at.

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
            for line in self._balanced(hard_line, max_width, weight)
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
        return TextMetrics(
            width=max((line.width for line in measured_lines), default=0.0),
            height=line_height * len(measured_lines),
            ascent=ascent,
            descent=descent,
            baseline=baseline,
            line_height=line_height,
            lines=measured_lines,
            cap_height=cap,
        )

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
        if not run.text:
            return 0.0
        weight = drawn_weight(run, inherited)
        advance = 0.0
        for face, text in self.stack.segments(run.text, weight, run.italic):
            font = hb_font(face, weight)
            buffer = hb.Buffer()
            buffer.add_str(text)
            buffer.guess_segment_properties()
            hb.shape(font, buffer, {"kern": True, "liga": True})
            upem = load_face(face).upem
            advance += sum(position.x_advance for position in buffer.glyph_positions) / upem
        scale = SHIFTED_SIZE if run.baseline_shift != "normal" else 1.0
        tracking = self.typography.tracking * len(run.text)
        return (advance + tracking) * self.typography.size.points * scale

    def _balanced(
        self,
        line: tuple[TextRun, ...],
        max_width: float | None,
        weight: int | None,
    ) -> tuple[tuple[TextRun, ...], ...]:
        """``line`` wrapped at ``max_width`` into lines of similar length.

        Greedy wrapping fills each line and leaves the last one short -- "Multi-
        head self-attention with rotary / embeddings". The narrowest width that
        still needs no more lines than greedy wrapping does spreads the words
        evenly instead, which is how a label is set by hand.
        """

        wrapped = self._wrap_line(line, max_width, weight)
        if len(wrapped) < 2 or max_width is None:
            return wrapped
        low, high = 0.0, max_width
        for _ in range(12):
            middle = (low + high) / 2.0
            if len(self._wrap_line(line, middle, weight)) <= len(wrapped):
                high = middle
            else:
                low = middle
        return self._wrap_line(line, high, weight)

    def _wrap_line(
        self,
        line: tuple[TextRun, ...],
        max_width: float | None,
        weight: int | None = None,
    ) -> tuple[tuple[TextRun, ...], ...]:
        if max_width is None or max_width <= 0.0:
            return (line,)
        wrapped: list[tuple[TextRun, ...]] = []
        current: list[TextRun] = []
        current_width = 0.0
        for run in line:
            for token in _TOKEN_PATTERN.findall(run.text):
                token_run = TextRun(token, run.weight, run.italic, run.baseline_shift)
                token_width = self._shape_run(token_run, weight)
                is_space = token.isspace()
                if current and not is_space and current_width + token_width > max_width:
                    wrapped.append(_trim_and_merge(current))
                    current = []
                    current_width = 0.0
                if not current and is_space:
                    continue
                current.append(token_run)
                current_width += token_width
        wrapped.append(_trim_and_merge(current))
        return tuple(wrapped)

    def _validate_glyphs(self, runs: tuple[TextRun, ...]) -> None:
        missing: set[str] = set()
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
                lines[-1].append(TextRun(part, run.weight, run.italic, run.baseline_shift))
            if index < len(parts) - 1:
                lines.append([])
    return tuple(_trim_and_merge(line) for line in lines)


def _trim_and_merge(runs: list[TextRun]) -> tuple[TextRun, ...]:
    while runs and runs[-1].text.isspace():
        runs.pop()
    merged: list[TextRun] = []
    for run in runs:
        if merged and (
            merged[-1].weight,
            merged[-1].italic,
            merged[-1].baseline_shift,
        ) == (run.weight, run.italic, run.baseline_shift):
            previous = merged[-1]
            merged[-1] = TextRun(
                previous.text + run.text,
                previous.weight,
                previous.italic,
                previous.baseline_shift,
            )
        else:
            merged.append(run)
    return tuple(merged)


def title_runs(runs: tuple[TextRun, ...], typography: TypographyStyle) -> tuple[TextRun, ...]:
    """A group title's runs as they are set: in capitals when the style says so."""

    if typography.title_transform != "upper":
        return runs
    return tuple(
        TextRun(run.text.upper(), run.weight, run.italic, run.baseline_shift) for run in runs
    )


def title_typography(typography: TypographyStyle) -> TypographyStyle:
    """The typography a group title is set in: the body's, scaled by ``title_size``."""

    if typography.title_size == 1.0:
        return typography
    from dataclasses import replace

    from flexo.units import Length

    return replace(typography, size=Length(typography.size.points * typography.title_size))
