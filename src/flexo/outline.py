"""Text as glyphs: where each glyph of a run goes, and its outline.

Flexo lays text out by shaping it with HarfBuzz in the exact font file it will
be drawn in. A writer that must not depend on the reader having that font -- a
PDF embeds it, a portable SVG and a raster preview draw its outlines -- needs
the same shaping again, glyph by glyph. ``shape`` gives each glyph of a
``flexo.drawing.Run`` its id and page position; ``glyph_outline`` gives its
outline as drawing segments at that position, read through HarfBuzz so a
variable font is drawn at the run's own weight.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import uharfbuzz as hb

from flexo.drawing import Point, Run, Segment
from flexo.fonts import FontFace, hb_font, load_face


@dataclass(frozen=True, slots=True)
class Glyph:
    """One glyph of a run: its id in the face, where its origin sits, and its text."""

    gid: int
    x: float
    y: float
    advance: float
    text: str
    """The characters this glyph draws (a cluster; a ligature draws several)."""


def shape(run: Run) -> list[Glyph]:
    """The glyphs of ``run``, placed on the page as Flexo measured them."""

    font = hb_font(run.face, run.weight)
    upem = load_face(run.face).upem
    scale = run.size / upem
    buffer = hb.Buffer()
    buffer.add_str(run.text)
    buffer.guess_segment_properties()
    hb.shape(font, buffer, {"kern": True, "liga": True})
    infos, positions = buffer.glyph_infos, buffer.glyph_positions
    # uharfbuzz fills the buffer with code points, so clusters index the string.
    clusters = [*sorted({info.cluster for info in infos}), len(run.text)]
    glyphs = []
    pen = run.x
    for info, position in zip(infos, positions, strict=True):
        start = info.cluster
        end = clusters[clusters.index(start) + 1]
        glyphs.append(
            Glyph(
                info.codepoint,
                pen + position.x_offset * scale,
                run.baseline - position.y_offset * scale,
                position.x_advance * scale,
                run.text[start:end],
            )
        )
        pen += position.x_advance * scale
    # Glyphs sharing a cluster (a mark on its letter) own its text once.
    seen: set[int] = set()
    result = []
    for glyph, info in zip(glyphs, infos, strict=True):
        text = glyph.text if info.cluster not in seen else ""
        seen.add(info.cluster)
        result.append(Glyph(glyph.gid, glyph.x, glyph.y, glyph.advance, text))
    return result


class _Pen:
    """A fontTools-style pen collecting an outline as drawing segments."""

    def __init__(self) -> None:
        self.segments: list[Segment] = []
        self._here: Point = (0.0, 0.0)

    def moveTo(self, point: Point) -> None:
        self.segments.append(Segment("M", (point,)))
        self._here = point

    def lineTo(self, point: Point) -> None:
        self.segments.append(Segment("L", (point,)))
        self._here = point

    def curveTo(self, *points: Point) -> None:
        self.segments.append(Segment("C", tuple(points)))
        self._here = points[-1]

    def qCurveTo(self, *points: Point) -> None:
        # A quadratic spline with implied on-curve points between controls.
        controls, end = list(points[:-1]), points[-1]
        start = self._here
        for index, control in enumerate(controls):
            if index < len(controls) - 1:
                following = controls[index + 1]
                target = ((control[0] + following[0]) / 2.0, (control[1] + following[1]) / 2.0)
            else:
                target = end
            first = _towards(start, control)
            second = _towards(target, control)
            self.segments.append(Segment("C", (first, second, target)))
            start = target
        self._here = end

    def closePath(self) -> None:
        self.segments.append(Segment("Z"))

    def endPath(self) -> None:
        return None


def _towards(point: Point, control: Point) -> Point:
    """Two thirds of the way from ``point`` to ``control``: a quadratic's cubic control."""

    return (point[0] + 2 / 3 * (control[0] - point[0]), point[1] + 2 / 3 * (control[1] - point[1]))


@lru_cache(maxsize=4096)
def _outline(face: FontFace, weight: int, gid: int) -> tuple[Segment, ...]:
    pen = _Pen()
    hb_font(face, weight).draw_glyph_with_pen(gid, pen)
    return tuple(pen.segments)


def glyph_outline(run: Run, glyph: Glyph) -> tuple[Segment, ...]:
    """The outline of ``glyph`` on the page: font units scaled, y turned down."""

    scale = run.size / load_face(run.face).upem
    return tuple(
        Segment(
            segment.kind,
            tuple((glyph.x + x * scale, glyph.y - y * scale) for x, y in segment.points),
        )
        for segment in _outline(run.face, run.weight, glyph.gid)
    )
