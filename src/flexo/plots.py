"""Plots in a figure: a matplotlib figure drawn at its panel's size, in the figure's type.

A paper's figure of several panels has plots among its diagrams. A ``plot`` shape names a
Python file and a function in it that returns a matplotlib figure:

    - id: loss
      kind: plot
      properties: {source: plots.py, function: loss}
      width: 60mm
      height: 40mm

The function is called with matplotlib set to the figure's look (``plot_style``: its font
and size, its inks, the palette's tones as the colour cycle), and what it returns is laid
out again at the shape's own size -- so its words are the size of the figure's words, not
scaled with the panel -- and drawn as vectors, its words kept as words.

Python a figure names is run when the figure is drawn, as a deck's is: in a studio only
in a folder its person trusts (``flexo.studio.code_allowed``). Where it is not run -- or
matplotlib is not installed, or the function fails -- the shape is drawn as an empty box
that says why, and the figure is drawn all the same.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import sys
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flexo.diagnostics import Diagnostic, Severity
from flexo.geometry import Size
from flexo.ir.semantic import NodeSpec
from flexo.style import LayoutStyle, Palette

PLOT_KIND = "plot"
WIDTH = 170.08
"""How wide a plot is with no width of its own: 60 mm."""
ASPECT = 1.5
"""Its width to its height, with only one of them given."""


@dataclass(frozen=True, slots=True)
class PlotDrawing:
    """A plot as drawn: its SVG (sanitized, its ids its shape's own), or why there is none."""

    markup: str = ""
    said: str = ""
    code: str = ""


def plot_size(node: NodeSpec, style: LayoutStyle) -> Size:
    """How large a plot is: as wide and tall as it says; with one given, the other in
    proportion (3:2); with neither, 60 mm wide."""

    width = style.resolve_extent(node.width).points if node.width is not None else None
    height = style.resolve_extent(node.height).points if node.height is not None else None
    if width is None and height is None:
        width = WIDTH
    if width is None:
        width = height * ASPECT  # type: ignore[operator]
    if height is None:
        height = width / ASPECT
    return Size(max(width, 24.0), max(height, 24.0))


def plot_style(style: LayoutStyle, palette: Palette) -> dict[str, object]:
    """matplotlib's settings for a plot in a figure's look: its family and size, its inks,
    the palette's tones as the colour cycle, and the lines as heavy as the figure's own."""

    from cycler import cycler

    typography = style.typography
    family, size = typography.family, typography.size.points
    ink, muted = palette.get("ink"), palette.get("muted-ink")
    tones = [palette.paints.get(palette.role(f"tone-{index}-stroke")) for index in range(1, 9)]
    colours = list(dict.fromkeys(tone for tone in tones if tone)) or [ink]
    line = max(style.connector_width.points, 0.5)
    return {
        "font.family": [family, *typography.fallbacks],
        "font.size": size,
        "axes.titlesize": size,
        "axes.labelsize": size,
        "xtick.labelsize": size * 0.9,
        "ytick.labelsize": size * 0.9,
        "legend.fontsize": size * 0.9,
        "text.color": ink,
        "axes.labelcolor": ink,
        "axes.titlecolor": ink,
        "axes.edgecolor": muted,
        "xtick.color": muted,
        "ytick.color": muted,
        "xtick.labelcolor": ink,
        "ytick.labelcolor": ink,
        "grid.color": muted,
        "grid.alpha": 0.25,
        "axes.prop_cycle": cycler(color=colours),
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.facecolor": "none",
        "figure.facecolor": "none",
        "savefig.facecolor": "none",
        "legend.frameon": False,
        "axes.linewidth": line,
        "xtick.major.width": line,
        "ytick.major.width": line,
        "xtick.major.size": 2.5,
        "ytick.major.size": 2.5,
        "lines.linewidth": line * 1.6,
        "lines.markersize": 3.0,
        "patch.edgecolor": "none",
        "mathtext.fontset": "custom",
        "mathtext.rm": family,
        "mathtext.it": f"{family}:italic",
        "mathtext.bf": f"{family}:bold",
        # (Not matplotlib's "cursive", which is whatever script face a computer has.)
        "mathtext.cal": f"{family}:italic",
        "mathtext.sf": family,
        "mathtext.fallback": "stix",
        # Its words stay words, in the figure's face, not outlines of matplotlib's own.
        "svg.fonttype": "none",
    }


_DRAWN: OrderedDict[tuple, PlotDrawing] = OrderedDict()
"""Plots drawn before, by what they were drawn from: a figure is drawn at every edit, and
its plots only when their file, their size or the figure's look has changed."""
_LOCK = threading.Lock()
"""One plot at a time: matplotlib's pyplot keeps one state for the whole process."""


def drawn(
    node: NodeSpec, width: float, height: float, style: LayoutStyle, palette: Palette
) -> PlotDrawing:
    """The plot ``node`` names, drawn ``width`` by ``height`` points in ``style``."""

    source = str(node.property("source", "") or "").strip()
    function = str(node.property("function", "") or "").strip()
    if not source or not function:
        return PlotDrawing(
            said="A plot needs a Python file and a function in it that returns a matplotlib "
            "figure.",
            code="plot.source.missing",
        )
    from flexo.confine import outside
    from flexo.studio import code_allowed

    path = Path(source).expanduser()
    if outside(path):
        return PlotDrawing(said=f"{path.name} is outside the folder.", code="plot.source.outside")
    if not code_allowed.get():
        return PlotDrawing(
            said=f"{path.name} hasn\u2019t been run: Python in this folder runs once you trust "
            "the folder.",
            code="code.untrusted",
        )
    try:
        stat = path.stat()
    except OSError as error:
        return PlotDrawing(
            said=f"Cannot read {path.name} ({error.strerror or error}).",
            code="plot.source.unreadable",
        )
    look = hashlib.sha256(repr((plot_style_key(style), sorted(palette.paints.items()))).encode())
    key = (
        str(path.resolve()), stat.st_mtime_ns, stat.st_size, function, node.id,
        round(width, 2), round(height, 2), look.hexdigest(),
    )
    with _LOCK:
        if key in _DRAWN:
            _DRAWN.move_to_end(key)
            return _DRAWN[key]
        made = _made(node.id, path, function, width, height, style, palette)
        _DRAWN[key] = made
        while len(_DRAWN) > 48:
            _DRAWN.popitem(last=False)
        return made


def plot_style_key(style: LayoutStyle) -> tuple:
    typography = style.typography
    return (typography.family, typography.fallbacks, typography.size.points,
            style.connector_width.points)


def _made(
    node_id: str, path: Path, function: str, width: float, height: float,
    style: LayoutStyle, palette: Palette,
) -> PlotDrawing:
    try:
        import matplotlib
    except ImportError:
        return PlotDrawing(
            said="Plots need matplotlib, which is not installed here.",
            code="plot.matplotlib.missing",
        )
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure

    from flexo.artwork import _svg_artwork
    from flexo.diagnostics import FlexoError

    _register_fonts()
    figure: Any = None
    # Drawn with no window: a studio draws off the main thread, where the Mac's own backend
    # makes no figure at all. (Put back after, on the main thread: a notebook's is its own.)
    backend = matplotlib.get_backend()
    windowed = backend.lower() != "agg"
    if windowed:
        plt.switch_backend("agg")
    try:
        with matplotlib.rc_context(plot_style(style, palette)):
            made = getattr(_module(path), function, None)
            if not callable(made):
                return PlotDrawing(
                    said=f"{path.name} has no function {function}.", code="plot.function.missing"
                )
            figure = made()
            if not isinstance(figure, Figure):
                return PlotDrawing(
                    said=f"{function} in {path.name} must return a matplotlib figure, not "
                    f"{type(figure).__name__}.",
                    code="plot.function.result",
                )
            # Laid out again at its shape's size: its words stay the figure's size.
            # (Not passed on to its window, which would round it to whole pixels.)
            figure.set_size_inches(width / 72.0, height / 72.0, forward=False)
            figure.set_layout_engine("constrained")
            held = io.BytesIO()
            figure.savefig(held, format="svg", transparent=True)
    except FlexoError:
        raise
    except Exception as error:
        said = f"{function} in {path.name} failed: {type(error).__name__}: {error}"
        return PlotDrawing(said=said[:300], code="plot.function.failed")
    finally:
        if figure is not None and isinstance(figure, Figure):
            plt.close(figure)
        if windowed and threading.current_thread() is threading.main_thread():
            with contextlib.suppress(Exception):
                plt.switch_backend(backend)
    try:
        artwork = _svg_artwork(node_id, path, held.getvalue())
    except FlexoError as error:
        said = "; ".join(item.message for item in error.diagnostics)
        return PlotDrawing(said=f"The plot can\u2019t be placed: {said}", code="plot.unplaceable")
    return PlotDrawing(markup=artwork.markup)


_FONTS_KNOWN = False


def _register_fonts() -> None:
    """Let matplotlib measure words in flexo's own faces (once in a process)."""

    global _FONTS_KNOWN
    if _FONTS_KNOWN:
        return
    from matplotlib import font_manager

    from flexo.fonts import bundled_font_directory

    for path in sorted(bundled_font_directory().iterdir()):
        if path.suffix.lower() in {".ttf", ".otf"}:
            try:
                font_manager.fontManager.addfont(str(path))
            except Exception:
                continue
    _FONTS_KNOWN = True


_MODULES: dict[str, tuple[int, Any]] = {}
"""A plot's Python file as last imported, and when the file had last changed."""


def _module(path: Path) -> Any:
    """``path`` imported as a module of its own (again, when the file has changed), its
    folder on Python's path while it is, so it finds the files beside it."""

    resolved = str(path.resolve())
    stamp = path.stat().st_mtime_ns
    known = _MODULES.get(resolved)
    if known is not None and known[0] == stamp:
        return known[1]
    name = f"flexo_plot_{hashlib.sha256(resolved.encode()).hexdigest()[:12]}"
    spec = importlib.util.spec_from_file_location(name, resolved)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {path.name}")
    module = importlib.util.module_from_spec(spec)
    folder = str(path.resolve().parent)
    sys.path.insert(0, folder)
    try:
        spec.loader.exec_module(module)
    finally:
        if folder in sys.path:
            sys.path.remove(folder)
    _MODULES[resolved] = (stamp, module)
    return module


def said(nodes: Any, style: LayoutStyle, palette: Palette) -> tuple[Diagnostic, ...]:
    """What to say of the figure's plots that were not drawn (``nodes``: its shapes as
    fitted): each is drawn here, once, and kept for the drawing of the figure itself."""

    found: list[Diagnostic] = []
    for node in nodes:
        spec = node.measured.spec
        if spec.kind != PLOT_KIND:
            continue
        made = drawn(spec, node.bounds.width, node.bounds.height, style, palette)
        if not made.markup:
            found.append(Diagnostic(made.code, made.said, Severity.WARNING, entity_id=spec.id))
    return tuple(found)
