"""Deterministic text shaping, wrapping, and baseline measurement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from importlib import resources
from io import BytesIO

import uharfbuzz as hb
from fontTools.ttLib import TTFont

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.ir.measured import MeasuredLine, TextMetrics
from flexo.ir.semantic import TextRun
from flexo.style import TypographyStyle

_TOKEN_PATTERN = re.compile(r"\S+|\s+")

SHIFTED_SIZE = 0.72
"""Font-size factor of a superscript or subscript run.

One number shared by shaping, component labels, and connector captions, so the
width a run is measured at is the width it is drawn at.
"""


@dataclass(frozen=True, slots=True)
class FontData:
    raw: bytes
    upem: int
    ascent: int
    descent: int
    subscript_drop: int
    codepoints: frozenset[int]


@cache
def font_data(italic: bool = False) -> FontData:
    filename = (
        "IBMPlexSans-Italic-Variable.ttf" if italic else "IBMPlexSans-Variable.ttf"
    )
    raw = resources.files("flexo.resources.fonts").joinpath(filename).read_bytes()
    font = TTFont(BytesIO(raw), lazy=True)
    return FontData(
        raw=raw,
        upem=font["head"].unitsPerEm,
        ascent=font["hhea"].ascent,
        descent=abs(font["hhea"].descent),
        # How far below the running baseline `baseline-shift="sub"` drops one.
        # The renderers Flexo targets read it from OS/2, so the depth of a
        # subscript is knowable at measure time rather than a guess.
        subscript_drop=font["OS/2"].ySubscriptYOffset,
        codepoints=frozenset((font.getBestCmap() or {}).keys()),
    )


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
            font = font_data(run.italic)
            drop = font.subscript_drop / font.upem * size
            depth = max(depth, drop + SHIFTED_SIZE * font.descent / font.upem * size)
    return depth


@cache
def font_bytes(italic: bool = False) -> bytes:
    return font_data(italic).raw


class TextMeasurer:
    """Shape text with HarfBuzz using the exact bundled output font."""

    def __init__(self, typography: TypographyStyle) -> None:
        self.typography = typography

    def measure(
        self,
        runs: tuple[TextRun, ...],
        *,
        max_width: float | None = None,
    ) -> TextMetrics:
        if not runs or not any(run.text for run in runs):
            return TextMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, ())
        self._validate_glyphs(runs)
        hard_lines = _split_hard_lines(runs)
        lines = tuple(
            line
            for hard_line in hard_lines
            for line in self._wrap_line(hard_line, max_width)
        )
        measured_lines = tuple(
            MeasuredLine(line, sum(self._shape_run(run) for run in line)) for line in lines
        )
        font = font_data()
        size = self.typography.size.points
        ascent = font.ascent / font.upem * size
        descent = font.descent / font.upem * size
        line_height = size * self.typography.line_height
        leading = max(0.0, line_height - ascent - descent)
        baseline = leading / 2.0 + ascent
        return TextMetrics(
            width=max((line.width for line in measured_lines), default=0.0),
            height=line_height * len(measured_lines),
            ascent=ascent,
            descent=descent,
            baseline=baseline,
            line_height=line_height,
            lines=measured_lines,
        )

    def _shape_run(self, run: TextRun) -> float:
        if not run.text:
            return 0.0
        data = font_data(run.italic)
        font = hb.Font(hb.Face(data.raw))
        font.scale = (data.upem, data.upem)
        font.set_variations({"wght": float(run.weight)})
        buffer = hb.Buffer()
        buffer.add_str(run.text)
        buffer.guess_segment_properties()
        hb.shape(font, buffer, {"kern": True, "liga": True})
        scale = SHIFTED_SIZE if run.baseline_shift != "normal" else 1.0
        return sum(position.x_advance for position in buffer.glyph_positions) / data.upem * (
            self.typography.size.points * scale
        )

    def _wrap_line(
        self,
        line: tuple[TextRun, ...],
        max_width: float | None,
    ) -> tuple[tuple[TextRun, ...], ...]:
        if max_width is None or max_width <= 0.0:
            return (line,)
        wrapped: list[tuple[TextRun, ...]] = []
        current: list[TextRun] = []
        current_width = 0.0
        for run in line:
            for token in _TOKEN_PATTERN.findall(run.text):
                token_run = TextRun(token, run.weight, run.italic, run.baseline_shift)
                token_width = self._shape_run(token_run)
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
        missing = {
            character
            for run in runs
            for character in run.text
            if not character.isspace() and ord(character) not in font_data(run.italic).codepoints
        }
        if missing:
            rendered = ", ".join(repr(character) for character in sorted(missing))
            raise FlexoError(
                Diagnostic(
                    "font.glyph.missing",
                    f"IBM Plex Sans does not contain: {rendered}.",
                    hint="Use supported Unicode text or supply an imported math/vector group.",
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
