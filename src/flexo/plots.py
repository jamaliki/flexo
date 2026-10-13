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

The function is run in this process (``run``) unless someone runs it apart. ``RUNNER`` is
asked first: given what ``run`` is given, it answers as ``run`` does, or with ``None`` where
it has no process for it. flexo-talk sets it to its studio worker's (``flexo_talk.worker``),
so that in a studio a function that never returns is stopped and said, and one that ends its
Python ends the worker, not the app. Whichever process draws it sets the look it is sent
and registers flexo's faces; the drawing comes back as SVG and is made safe to place here.

A plot is drawn again when what it was drawn from changes: its Python file, its size, the
figure's look -- and the files its function read (``_Reading``: its data, the modules beside
it), which a studio watches as it does the Python file (``files``).
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import os
import sys
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
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


RUNNER: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None
"""Who runs a plot's function in a process of its own, if anyone does: asked as ``run`` is,
it answers as ``run`` does, or ``None`` to have it run here."""

_DRAWN: OrderedDict[tuple, tuple[PlotDrawing, tuple[str, ...], tuple]] = OrderedDict()
"""Plots drawn before, by what was asked for: each with the files it was drawn from (its
Python file, and those its function read) and what they were then (``_stamps``). A figure
is drawn at every edit, and its plots only when a file, their size or the figure's look
has changed."""
_READ: dict[tuple[str, str], tuple[str, ...]] = {}
"""The files each function read when last run, by its Python file and its name."""
_LOCK = threading.Lock()
"""Around what is kept of plots drawn."""
_HERE = threading.Lock()
"""One plot at a time is run in this process: matplotlib's pyplot keeps one state for the
whole of it. (One run apart is the runner's to order: another folder's does not wait.)"""
FILES_MOST = 200
"""How many files a plot is drawn again for, at most (a function that reads a folder of
thousands is not asked of each at every edit)."""


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
    from flexo.confine import folder_root, outside
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
        path.stat()
    except OSError as error:
        return PlotDrawing(
            said=f"Cannot read {path.name} ({error.strerror or error}).",
            code="plot.source.unreadable",
        )
    file = str(path.resolve())
    look = hashlib.sha256(repr((plot_style_key(style), sorted(palette.paints.items()))).encode())
    key = (file, function, node.id, round(width, 2), round(height, 2), look.hexdigest())
    made = _kept(key)
    if made is not None:
        return made
    was = _stamps((file,))
    try:
        asked = {
            "file": file, "function": function, "width": width, "height": height,
            "look": plot_style(style, palette),
            # (Where its data is looked for: the studio's folder, or its own.)
            "folder": str(folder_root.get() or Path(file).parent),
        }
    except ImportError:
        return PlotDrawing(said=_NO_MATPLOTLIB, code="plot.matplotlib.missing")
    answer = RUNNER(asked) if RUNNER is not None else None
    if answer is not None:
        return _keep(key, was, *_placed(node.id, path, asked, answer))
    with _HERE:
        # (Drawn meanwhile, perhaps, by another thread that was waiting its turn too.)
        made = _kept(key)
        if made is None:
            made = _keep(key, was, *_placed(node.id, path, asked, run(asked)))
        return made


def _kept(key: tuple) -> PlotDrawing | None:
    """The plot as drawn before, if the files it was drawn from are as they were then."""

    with _LOCK:
        known = _DRAWN.get(key)
        if known is None or known[2] != _stamps(known[1]):
            return None
        _DRAWN.move_to_end(key)
        return known[0]


def _keep(key: tuple, was: tuple, made: PlotDrawing, read: tuple[str, ...]) -> PlotDrawing:
    """``made`` kept as the plot ``key`` asks for: drawn from its Python file as it ``was``
    before it ran, and the files it ``read`` as they are now."""

    file, function = key[:2]
    with _LOCK:
        _DRAWN[key] = (made, (file, *read), (*was, *_stamps(read)))
        _DRAWN.move_to_end(key)
        _READ[(file, function)] = read
        while len(_DRAWN) > 48:
            _DRAWN.popitem(last=False)
    return made


def plot_style_key(style: LayoutStyle) -> tuple:
    typography = style.typography
    return (typography.family, typography.fallbacks, typography.size.points,
            style.connector_width.points)


def files(source: str | Path, function: str) -> list[Path]:
    """The files the plot of ``function`` in ``source`` is drawn from, for a studio to draw
    it again when one changes: the Python file, and those its function read when last run."""

    file = str(Path(source).expanduser().resolve())
    return [Path(file), *(Path(name) for name in _READ.get((file, str(function)), ()))]


def _stamps(names: Iterable[str]) -> tuple:
    """What each file is now: when it last changed and its size (``None``: not there)."""

    found: list[tuple[int, int] | None] = []
    for name in names:
        try:
            stat = os.stat(name)
        except OSError:
            found.append(None)
        else:
            found.append((stat.st_mtime_ns, stat.st_size))
    return tuple(found)


_NO_MATPLOTLIB = "Plots need matplotlib, which is not installed here."


def _placed(
    node_id: str, path: Path, asked: dict[str, Any], answer: Mapping[str, Any]
) -> tuple[PlotDrawing, tuple[str, ...]]:
    """What ``run`` (or a runner) answered for the plot ``asked`` for, as the figure places
    it: its drawing made safe, or what is said of it -- and the files its function read."""

    from flexo.artwork import _svg_artwork
    from flexo.diagnostics import FlexoError

    read = tuple(str(name) for name in answer.get("files") or ())[:FILES_MOST]
    if not answer.get("svg"):
        said = str(answer.get("said") or f"{asked['function']} in {path.name} was not drawn.")
        return PlotDrawing(said=said[:300], code=answer.get("code") or "plot.function.failed"), read
    try:
        artwork = _svg_artwork(node_id, path, answer["svg"])
    except FlexoError as error:
        said = "; ".join(item.message for item in error.diagnostics)
        unplaceable = PlotDrawing(
            said=f"The plot can\u2019t be placed: {said}", code="plot.unplaceable"
        )
        return unplaceable, read
    return PlotDrawing(markup=artwork.markup), read


def run(asked: Mapping[str, Any]) -> dict[str, Any]:
    """The plot ``asked`` for, drawn in this process: the function ``function`` of ``file``,
    called in the look ``look`` (``plot_style``) and laid out ``width`` by ``height`` points.

    The answer is plain values, to pass between processes: ``svg`` (bytes), or ``said`` and
    ``code`` for why there is none; and ``files``, those in ``folder`` the function read."""

    reading = _Reading(Path(asked["folder"]), Path(asked["file"]))
    return {**_run(asked, reading), "files": reading.files()}


def _run(asked: Mapping[str, Any], reading: _Reading) -> dict[str, Any]:
    path, function = Path(asked["file"]), str(asked["function"])
    width, height = float(asked["width"]), float(asked["height"])
    try:
        import matplotlib
    except ImportError:
        return {"said": _NO_MATPLOTLIB, "code": "plot.matplotlib.missing"}
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure

    from flexo.diagnostics import FlexoError

    _register_fonts()
    figure: Any = None
    # Drawn with no window: a studio draws off the main thread, where the Mac's own backend
    # makes no figure at all. (Put back after, on the main thread: a notebook's is its own.)
    backend = matplotlib.get_backend()
    windowed = backend.lower() != "agg"
    if windowed:
        plt.switch_backend("agg")
    # Its folder is on Python's path while it runs, so it finds the modules beside it -- which
    # are Python's only for that long (``_Reading.put_away``).
    folder, imported = str(path.resolve().parent), set(sys.modules)
    sys.path.insert(0, folder)
    try:
        with matplotlib.rc_context(dict(asked["look"])), reading:
            made = getattr(_module(path, reading), function, None)
            if not callable(made):
                return {
                    "said": f"{path.name} has no function {function}.",
                    "code": "plot.function.missing",
                }
            figure = made()
            if not isinstance(figure, Figure):
                return {
                    "said": f"{function} in {path.name} must return a matplotlib figure, not "
                    f"{type(figure).__name__}.",
                    "code": "plot.function.result",
                }
            # Laid out again at its shape's size: its words stay the figure's size.
            # (Not passed on to its window, which would round it to whole pixels.)
            figure.set_size_inches(width / 72.0, height / 72.0, forward=False)
            figure.set_layout_engine("constrained")
            held = io.BytesIO()
            figure.savefig(held, format="svg", transparent=True)
    except FlexoError:
        raise
    except (Exception, SystemExit) as error:
        # (``sys.exit()`` in a plot ends neither the figure's drawing nor a worker.)
        said = f"{function} in {path.name} failed: {type(error).__name__}: {error}"
        return {"said": said[:300], "code": "plot.function.failed"}
    finally:
        reading.put_away(imported)
        if folder in sys.path:
            sys.path.remove(folder)
        if figure is not None and isinstance(figure, Figure):
            plt.close(figure)
        if windowed and threading.current_thread() is threading.main_thread():
            with contextlib.suppress(Exception):
                plt.switch_backend(backend)
    return {"svg": held.getvalue()}


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


@dataclass(slots=True)
class _Imported:
    """A plot's Python file as last imported: the module, the files importing it read, what
    they and it were then (``_stamps``), and the modules it imported from beside it."""

    was: tuple
    module: Any
    read: tuple[str, ...]
    beside: dict[str, Any]


_MODULES: dict[str, _Imported] = {}


def _module(path: Path, reading: _Reading) -> Any:
    """``path`` imported as a module of its own -- again, with the modules beside it, when it
    or a file importing it read has changed. (Its folder is on Python's path: ``_run``.)"""

    resolved = str(path.resolve())
    known = _MODULES.get(resolved)
    if known is not None and known.was == _stamps((resolved, *known.read)):
        # (The modules beside it are Python's again while it runs, as when it imported them.)
        for name, beside in known.beside.items():
            sys.modules.setdefault(name, beside)
        reading.read.extend(known.read)
        return known.module
    was = _stamps((resolved,))
    name = f"flexo_plot_{hashlib.sha256(resolved.encode()).hexdigest()[:12]}"
    spec = importlib.util.spec_from_file_location(name, resolved)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {path.name}")
    module = importlib.util.module_from_spec(spec)
    start, imported = len(reading.read), set(sys.modules)
    spec.loader.exec_module(module)
    beside = reading.beside(imported)
    read = tuple(reading.files(start))
    _MODULES[resolved] = _Imported((*was, *_stamps(read)), module, read, beside)
    return module


_READING: _Reading | None = None
"""Whose files are being noted now, if anyone's (``_opened``)."""
_HOOKED = False
_WRITES = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_NEVER_DATA = frozenset(
    {".py", ".pyc", ".ttf", ".otf", ".ttc", ".dfont", ".afm", ".pfb", ".woff", ".woff2"}
)
"""Files Python and matplotlib open for themselves: modules, and fonts."""
_PYTHONS = frozenset({"site-packages", "__pycache__"})
"""Folders that are Python's own, whichever Python's."""


class _Reading:
    """The files in a folder that a plot's Python reads as it runs: the data it plots, and
    the modules beside it. The plot is drawn again when one of them changes.

    Data: Python's audit hook tells of each file opened, however it is (``open``,
    ``os.open``, numpy's and pandas' readers). Not counted are a file the Python also
    writes (a cache of its own, which would have it drawn again for ever), what Python and
    matplotlib open for themselves (``_NEVER_DATA``; anything in this Python's environment,
    should the folder hold it, or in a hidden folder), and what other threads open meanwhile
    (a studio reading its documents).

    Modules: those it imports from beside its file (``beside``)."""

    def __init__(self, folder: Path, source: Path) -> None:
        self.folder = os.path.realpath(folder) + os.sep
        self.source = os.path.realpath(source)
        self.python = tuple(
            {os.path.realpath(prefix) + os.sep for prefix in (sys.prefix, sys.base_prefix)}
        )
        self.thread = threading.get_ident()
        self.read: list[str] = []
        self.written: set[str] = set()
        self.before: _Reading | None = None

    def __enter__(self) -> _Reading:
        global _READING, _HOOKED
        if not _HOOKED:
            # (Once in a process: a hook is never taken away, and idle it only looks.)
            sys.addaudithook(_opened)
            _HOOKED = True
        self.thread = threading.get_ident()
        self.before, _READING = _READING, self
        return self

    def __exit__(self, *error: object) -> None:
        global _READING
        _READING = self.before

    def note(self, file: object, mode: object = None, flags: object = None) -> None:
        if isinstance(file, int):
            return  # (a descriptor: its file was opened, and noted, before)
        name = os.path.realpath(os.fsdecode(file))  # type: ignore[arg-type]
        if not name.startswith(self.folder) or name.startswith(self.python):
            return
        folders = name[len(self.folder):].split(os.sep)[:-1]
        if os.path.splitext(name)[1].lower() in _NEVER_DATA or any(
            part.startswith(".") or part in _PYTHONS for part in folders
        ):
            return
        writes = (
            bool(flags & _WRITES)
            if isinstance(flags, int)
            else any(letter in str(mode or "r") for letter in "wax+")
        )
        if writes:
            self.written.add(name)
        else:
            self.read.append(name)

    def beside(self, before: set[str]) -> dict[str, Any]:
        """The modules imported since ``before`` from beside the plot's file (found there
        because its folder is on Python's path), by name: their files are among what was
        read."""

        folder = os.path.dirname(self.source) + os.sep
        found: dict[str, Any] = {}
        for name in set(sys.modules) - before:
            module = sys.modules.get(name)
            file = getattr(module, "__file__", None)
            if not isinstance(file, str) or not file.endswith(".py"):
                continue
            file, top = os.path.realpath(file), folder + name.partition(".")[0]
            if file == top + ".py" or file.startswith(top + os.sep):
                found[name] = module
                self.read.append(file)
        return found

    def put_away(self, before: set[str]) -> None:
        """The modules beside the plot's file are Python's no longer, its Python having run:
        one edited is imported again with it, and a module of the same name beside another
        plot's file is that plot's own."""

        for name in self.beside(before):
            sys.modules.pop(name, None)

    def files(self, start: int = 0) -> list[str]:
        """The files read (from the ``start``-th noted on), each once, in the order read."""

        return [
            name
            for name in dict.fromkeys(self.read[start:])
            if name not in self.written and name != self.source and not os.path.isdir(name)
        ]


def _opened(event: str, args: tuple) -> None:
    reading = _READING
    if reading is None or event != "open" or threading.get_ident() != reading.thread:
        return
    try:
        reading.note(*args)
    except Exception:  # (a hook that fails would fail the opening it was told of)
        return


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
