"""A figure laid out for a box: the way of drawing it whose words read largest there.

A figure compiled for a page and then scaled into a slide shrinks with it: a
tall stack in a wide box keeps only as much of its size as the box's height
allows. ``fit_in_box`` lays the figure out for the box instead. It compiles the
figure at a width where its words are ``words`` points once drawn, finds the
extent of its ink, and works out the scale that fits that ink in the box --
then tries the other ways the same figure can be drawn, and keeps the one whose
words come out largest:

- **as written**;
- **turned** (``flexo.orient.turned``): rows become columns, a stack that read
  upward reads left to right, a grid is transposed -- a tall figure made wide;
- **turned within**: the outermost parts stay as written, each turned inside;
- each of those with **tighter spacing**, which buys room without shrinking a
  single word;
- and, when none of those sets the words at their size, **folded**
  (``flexo.orient.wrapped``): a long row or column set on two lines, if that
  sets them clearly larger (``FOLD_GAIN``) and makes no lines cross.

It stops as soon as a layout lets the words reach ``largest``, so a figure that
already fits costs one compile. A turned or tightened layout is only chosen when
it is clearly better (``PREFERENCE``), and never when it lints worse than the
figure as written.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from flexo.compiler import Compilation, compile_figure
from flexo.draft import drafting, give_up_if_newer
from flexo.drawing import ink_bounds, read_drawing
from flexo.ir.semantic import FigureSpec
from flexo.lint import lint_compilation
from flexo.orient import turned, wrapped
from flexo.style import LayoutStyle
from flexo.themes import figure_style
from flexo.units import Length

if TYPE_CHECKING:  # pragma: no cover
    from flexo.builder import Figure

PREFERENCE = 1.12
"""How much larger another layout's words must be before it replaces the one written."""
FOLD_GAIN = 1.3
"""How much larger a fold must set the words before it replaces a layout that
keeps each row and column whole: folding changes how the figure reads, so it has
to buy more than turning does (``PREFERENCE``)."""
TIGHTER = 0.65
"""The spacing (gaps and group padding) of the tighter variants, as a share of the theme's."""


@dataclass(frozen=True, slots=True)
class BoxFit:
    """The layout ``fit_in_box`` chose, and how to place it."""

    compilation: Compilation
    scale: float
    """Figure points to box points: the drawing is drawn this much larger."""
    ink: tuple[float, float, float, float]
    """``left, top, width, height`` of what the figure draws, in its own points."""
    layout: str
    """``as written``, ``turned``, or ``turned within``, and ``tighter`` if spaced closer."""
    words: float
    """The size its words are drawn at in the box, in points."""
    errors: int
    style: LayoutStyle | None = None
    """The layout style it was compiled with (tighter spacing), for linting it again."""


def fit_in_box(
    figure: Figure | FigureSpec,
    width: float,
    height: float,
    *,
    words: float | None = None,
    largest: float | None = None,
    turn: bool = True,
    pad: float = 2.0,
    keep: str | None = None,
    fold: bool | None = None,
) -> BoxFit:
    """``figure`` laid out to fill a ``width`` by ``height`` box (points).

    ``words`` is the size the figure's words are laid out for (the theme's size
    by default): the figure is compiled at the width where they are that size
    once drawn across the box. ``largest`` caps how far it is scaled up (twice
    ``words`` by default). ``turn=False`` keeps the figure as written -- and unfolded,
    unless ``fold`` (which is ``turn`` unless given) says it may still be folded onto
    two lines: a figure kept the way it runs is not kept from folding.

    ``keep`` names a layout this returned before (its ``layout``): the figure is
    drawn that way alone, in one compile, rather than every way being tried -- as an
    editor draws a figure again and again while it is changed, its layout holding
    still, and finds the best one once the changes stop.
    """

    spec = figure if isinstance(figure, FigureSpec) else figure.spec
    style = figure_style(spec)
    base = style.typography.size.points
    least = (words or base) / base
    most = (largest / base) if largest else least * 2.0
    spec = replace(spec, width=f"{max(width / least, 40.0):.3f}pt", background=False)
    tight = replace(
        style,
        gap=Length(style.gap.points * TIGHTER),
        group_padding=Length(style.group_padding.points * TIGHTER),
        compact_gap=Length(style.compact_gap.points * TIGHTER),
    )
    variants = [("as written", spec)]
    # (A layout kept is drawn as it is named, turned though the figure is no longer free to
    # turn -- given another place, say: it is laid out afresh for it once the changes stop.)
    if turn or (keep or "").startswith("turned"):
        variants += [("turned", turned(spec)), ("turned within", turned(spec, keep_root=True))]
    every = [
        (name if spacing is None else f"{name}, {spacing}", variant, layout_style)
        for spacing, layout_style in ((None, None), ("tighter", tight))
        for name, variant in variants
    ]
    candidates = [item for item in every if turn or not item[0].startswith("turned")]
    if keep is not None:
        kept = _kept(keep, every, width, height, most, base, pad)
        if kept is not None:
            return kept
    # Laid out afresh, every way, a figure is drawn in full: a draft is only ever of the
    # layout kept (flexo.draft), never what is found best.
    with drafting(False):
        folding = turn if fold is None else fold
        return _afresh(spec, style, candidates, width, height, most, least, base, pad, folding)


def _afresh(spec, style, candidates, width, height, most, least, base, pad, fold) -> BoxFit:
    """The best of ``candidates`` for the box (see ``fit_in_box``)."""

    # Measuring is nearly free and routing is not: rank the layouts by the scale
    # their measured size allows (routing only adds to it, so this is an upper
    # bound), compile the written one first, and skip any that cannot win.
    first, *rest = candidates
    rest.sort(key=lambda item: -_estimate(item[1], item[2] or style, width, height, most))
    fits: list[BoxFit] = []
    for label, candidate, layout_style in (first, *rest):
        largest_so_far = max((fit.scale for fit in fits), default=0.0)
        if largest_so_far >= most - 1e-9:
            break
        if fits and _estimate(candidate, layout_style or style, width, height, most) <= (
            largest_so_far / PREFERENCE
        ):
            continue
        try:
            compiled = compile_figure(candidate, style=layout_style)
        except Exception:
            if not fits:
                raise
            continue
        give_up_if_newer()  # (a drawing given up for a newer one: flexo.draft)
        left, top, right, bottom = ink_bounds(read_drawing(compiled.document.text))
        ink = (left - pad, top - pad, right - left + 2 * pad, bottom - top + 2 * pad)
        scale = min(most, width / ink[2], height / ink[3])
        errors = len(lint_compilation(compiled, style=layout_style).errors)
        fits.append(BoxFit(compiled, scale, ink, label, base * scale, errors, layout_style))
    written_errors = fits[0].errors
    usable = [fit for fit in fits if fit.errors <= written_errors]
    top_scale = max(fit.scale for fit in usable)
    # The most natural layout among those nearly as large as the largest.
    order = [label for label, _, _ in candidates]
    best = min(
        (fit for fit in usable if fit.scale * PREFERENCE >= top_scale),
        key=lambda fit: order.index(fit.layout),
    )
    if fold and best.scale < least:
        # Smaller than the words were meant to be: fold long rows and columns onto
        # two lines, if that sets them clearly larger. Routing a folded figure is
        # costly, so only the most promising fold is tried -- and, should its lines
        # cross, the same fold with its second line run the other way.
        folds = [
            (label, candidate, layout_style)
            for label, candidate, layout_style in candidates
            if "within" not in label
        ]
        folds.sort(
            key=lambda item: -_estimate(wrapped(item[1]), item[2] or style, width, height, most)
        )
        label, unfolded, layout_style = folds[0]
        promise = _estimate(wrapped(unfolded), layout_style or style, width, height, most)
        if promise > best.scale * FOLD_GAIN:
            crossings = _crossings(best.compilation, best.style)
            tried: list[FigureSpec] = []
            for suffix, back in FOLDS:
                candidate = wrapped(unfolded, back=back)
                if candidate in tried:
                    continue
                tried.append(candidate)
                try:
                    compiled = compile_figure(candidate, style=layout_style)
                except Exception:
                    return best
                left, top, right, bottom = ink_bounds(read_drawing(compiled.document.text))
                ink = (left - pad, top - pad, right - left + 2 * pad, bottom - top + 2 * pad)
                scale = min(most, width / ink[2], height / ink[3])
                errors = len(lint_compilation(compiled, style=layout_style).errors)
                if errors > written_errors or scale <= best.scale * FOLD_GAIN:
                    break
                # A fold is the layout's doing, not its author's: one that makes lines cross
                # that did not is no fold to take, however much larger its words.
                if _crossings(compiled, layout_style) <= crossings:
                    return BoxFit(
                        compiled, scale, ink, f"{label}{suffix}", base * scale, errors, layout_style
                    )
    return best


FOLDS = ((", folded", None), (", folded back", True), (", folded on", False))
"""How a layout's name says it is folded (``flexo.orient.wrapped``): as the fold
itself has it, or with its second line made to run back, or on."""


def _crossings(compiled: Compilation, style: LayoutStyle | None) -> int:
    """How many pairs of lines cross in a compiled figure."""

    report = lint_compilation(compiled, style=style)
    return sum(item.code == "routing.connector.crossing" for item in report.diagnostics)


def _kept(keep: str, candidates, width: float, height: float, most: float, base: float, pad: float):
    """The figure drawn in the layout ``keep`` names, if it is one of ``candidates`` (or
    one folded), in one compile."""

    suffix, back = next(
        ((suffix, back) for suffix, back in FOLDS if keep.endswith(suffix)), ("", None)
    )
    for label, candidate, layout_style in candidates:
        if label != keep.removesuffix(suffix):
            continue
        try:
            compiled = compile_figure(
                wrapped(candidate, back=back) if suffix else candidate, style=layout_style
            )
        except Exception:
            return None
        left, top, right, bottom = ink_bounds(read_drawing(compiled.document.text))
        ink = (left - pad, top - pad, right - left + 2 * pad, bottom - top + 2 * pad)
        scale = min(most, width / ink[2], height / ink[3])
        errors = len(lint_compilation(compiled, style=layout_style).errors)
        return BoxFit(compiled, scale, ink, keep, base * scale, errors, layout_style)
    return None


def _estimate(spec: FigureSpec, style, width: float, height: float, most: float) -> float:
    """The scale a layout's measured size allows in the box: at least what it gets."""

    from flexo.layout.measure import measure_figure

    give_up_if_newer()
    try:
        measured = measure_figure(spec, style=style)
    except Exception:
        return 0.0
    root = next(group for group in measured.groups if group.spec.id == spec.root)
    size = root.intrinsic_size
    return min(most, width / max(size.width, 1.0), height / max(size.height, 1.0))
