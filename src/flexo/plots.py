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
figure's look -- and what its function read (``_Reading``), which a studio watches as it
does the Python file (``files``): the files it opened, the folders it listed (one more file
in a folder it globbed is a change), the files its Python names in so many words, and the
data its shape names, for whatever cannot be seen (``data: [loss.h5, "runs/*.parquet"]``).

One that a runner stopped -- it never returned, or took its process down -- is not run again
until its Python file changes, at whatever size or in whichever figure it is asked for; one
a runner could not run yet (``WAITING``) is asked for again at the next drawing.
"""

from __future__ import annotations

import ast
import contextlib
import glob
import hashlib
import importlib.util
import io
import os
import re
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator, Mapping
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

STOPPED = "plot.function.stopped"
"""What a runner says of a plot it stopped: one that never returned, or ended its process."""
WAITING = "plot.function.waiting"
"""What a runner says of a plot it could not run yet, for no fault of the plot's (its
process was still starting): not kept, so the next drawing asks for it again."""

_DRAWN: OrderedDict[tuple, tuple[PlotDrawing, tuple[str, ...], tuple]] = OrderedDict()
"""Plots drawn before, by what was asked for: each with the files it was drawn from (its
Python file, and those its function read) and what they were then (``_stamps``). A figure
is drawn at every edit, and its plots only when a file, their size or the figure's look
has changed."""
_READ: dict[tuple[str, str, tuple[str, ...]], tuple[str, ...]] = {}
"""What each function read when last run, by its Python file, its name and the data its
shape names (``_whole``)."""
_WAS_STOPPED: dict[tuple[str, str], tuple[tuple[str, ...], tuple, PlotDrawing]] = {}
"""The functions a runner stopped, by Python file and name: the files each was drawn from
(its Python file: one stopped has told of no other), what they were then, and what was
said. Asked for at another size, or in another figure, one is not run again -- each would
wait out its time anew -- until a file changes."""
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
    data = _whole(node.property("data"))
    look = hashlib.sha256(repr((plot_style_key(style), sorted(palette.paints.items()))).encode())
    key = (file, function, node.id, round(width, 2), round(height, 2), look.hexdigest(), data)
    made = _kept(key) or _WAITED.__dict__.setdefault("plots", {}).pop(key, None)
    if made is not None:
        return made
    was = _stamps((file,))
    made = _stopped(file, function)
    if made is not None:
        return made
    try:
        asked = {
            "file": file, "function": function, "width": width, "height": height,
            "look": plot_style(style, palette),
            # (Where its data is looked for: the studio's folder, or its own.)
            "folder": str(folder_root.get() or Path(file).parent),
            "data": list(data),
        }
    except ImportError:
        return PlotDrawing(said=_NO_MATPLOTLIB, code="plot.matplotlib.missing")
    if RUNNER is not None:
        from flexo.studio import waiting

        # Run apart, a function is run once at a time: asked for meanwhile -- at another
        # size, in another figure -- it waits for that run, and is not run again if that
        # one is stopped (each would take a process, and wait out its time). And while
        # this waits, the folder's turn to draw is another document's.
        with waiting(), _turn(file, function):
            made = _kept(key) or _stopped(file, function)
            if made is not None:
                return made
            answer = RUNNER(asked)
            if answer is not None:
                made, read = _placed(node.id, path, asked, answer)
                if made.code == WAITING:
                    _WAITED.plots[key] = made
                    return made
                with _LOCK:
                    if made.code == STOPPED:
                        stamps = (*was, *_stamps(read))
                        _WAS_STOPPED[(file, function)] = ((file, *read), stamps, made)
                    else:
                        _WAS_STOPPED.pop((file, function), None)
                return _keep(key, was, made, read)
    with _HERE:
        # (Drawn meanwhile, perhaps, by another thread that was waiting its turn too.)
        made = _kept(key)
        if made is None:
            made = _keep(key, was, *_placed(node.id, path, asked, run(asked)))
        return made


def _stopped(file: str, function: str) -> PlotDrawing | None:
    """What was said of the function when a runner stopped it, if the files it was drawn
    from are as they were then."""

    with _LOCK:
        stopped = _WAS_STOPPED.get((file, function))
    if stopped is None or stopped[1] != _stamps(stopped[0]):
        return None
    return stopped[2]


_WAITED = threading.local()
"""In each thread, the ``plots`` just said not to have been run yet (``WAITING``), by what
was asked for: told once more as they were. A figure's drawing asks for each of its plots
twice -- to say what there is to say of it, then to draw it -- and the second is not a
new asking: its runner would be waited on all over again."""
_TURNS: dict[tuple[str, str], threading.Lock] = {}
"""Whose turn it is to run each function apart, by Python file and name."""


def _turn(file: str, function: str) -> threading.Lock:
    with _LOCK:
        return _TURNS.setdefault((file, function), threading.Lock())


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
        _READ[(file, function, key[-1])] = read
        while len(_DRAWN) > 48:
            _DRAWN.popitem(last=False)
    return made


def plot_style_key(style: LayoutStyle) -> tuple:
    typography = style.typography
    return (typography.family, typography.fallbacks, typography.size.points,
            style.connector_width.points)


def named(data: object) -> tuple[str, ...]:
    """The names a plot's ``data`` gives, as written: one, several with commas between
    them, or a list of them -- each a file, a folder, or a pattern (``runs/*.h5``)."""

    if isinstance(data, str):
        data = data.split(",")
    if not isinstance(data, list | tuple):
        return ()
    names = (name.strip() for name in data if isinstance(name, str))
    return tuple(dict.fromkeys(name for name in names if name))


def beside(base: Path, data: object) -> list[str]:
    """A plot's ``data`` with each name found from ``base``, its figure's folder (whose own
    name is taken as it is written, whatever marks of a pattern are in it)."""

    return [
        name
        if os.path.isabs(os.path.expanduser(name))
        else os.path.join(glob.escape(str(base)), name)
        for name in named(data)
    ]


def _whole(data: object) -> tuple[str, ...]:
    """The names a plot's ``data`` gives, each whole and as the computer has it: what a
    plot is kept by, however its figure came to be read."""

    names = (os.path.realpath(os.path.expanduser(name)) for name in named(data))
    return tuple(dict.fromkeys(names))


def _from(source: str | Path, function: str, data: object) -> tuple[str, ...]:
    file = str(Path(source).expanduser().resolve())
    return (file, *_READ.get((file, str(function), _whole(data)), ()))


def files(source: str | Path, function: str, data: object = None) -> list[Path]:
    """What the plot of ``function`` in ``source`` is drawn from, for a studio to draw it
    again when one changes: the Python file, and what its function read when last run --
    files, and folders it listed. ``data``: what its shape names, as its figure holds it
    (each name from the figure's folder: ``beside``)."""

    return [Path(name) for name in _from(source, function, data)]


def state(source: str | Path, function: str, data: object = None) -> tuple:
    """What ``files`` are now, to keep something drawn from the plot by: each one's name,
    with when it last changed and its size -- or, of a folder, what is in it."""

    names = _from(source, function, data)
    return (names, _stamps(names))


def _stamps(names: Iterable[str]) -> tuple:
    """What each file is now: when it last changed and its size (``None``: not there). Of a
    folder that was listed (its name ends as a folder's does): what is in it."""

    found: list[tuple[int, int] | str | None] = []
    for name in names:
        try:
            stat = os.stat(name)
        except OSError:
            found.append(None)
        else:
            changed, listed = stat.st_mtime_ns, name.endswith(os.sep)
            found.append(_listing(name, changed) if listed else (changed, stat.st_size))
    return tuple(found)


_LISTED: dict[str, tuple[int, str]] = {}
"""What was in each folder when last looked at, and when the folder had last changed."""


def _listing(folder: str, changed: int) -> str:
    """What is in ``folder``, as one word: the names there, whatever each holds (but not
    the hidden ones, nor Python's own). Read again only when the folder says it has
    changed -- which a file saved in place of itself does too, and changes nothing here."""

    known = _LISTED.get(folder)
    if known is not None and known[0] == changed:
        return known[1]
    try:
        names = sorted(
            name for name in os.listdir(folder) if not name.startswith(".") and name not in _PYTHONS
        )
    except OSError:
        names = []
    word = hashlib.sha256("\0".join(names).encode("utf-8", "surrogateescape")).hexdigest()
    # (Not kept of a folder changed this moment: a clock that counts in seconds would not
    # tell of what changes next.)
    if time.time_ns() - changed > 2_000_000_000:
        if len(_LISTED) > 512:
            _LISTED.clear()
        _LISTED[folder] = (changed, word)
    return word


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
    ``code`` for why there is none; and ``files``, what in ``folder`` the function read --
    with the ``data`` its shape names, and the files its Python spells (``_Reading``)."""

    reading = _Reading(Path(asked["folder"]), Path(asked["file"]))
    answer = _run(asked, reading)
    # (Whatever a name does to the looking, the plot is drawn: only less is watched.)
    with contextlib.suppress(Exception):
        reading.named(asked.get("data") or ())
    with contextlib.suppress(Exception):
        reading.spelt(str(asked["function"]))
    return {**answer, "files": reading.files()}


def warm() -> None:
    """What ``run`` needs, made ready before any plot is asked for: matplotlib imported
    (which may first list the computer's fonts, for many seconds) and flexo's faces known
    to it. A process that runs plots apart does this before it takes one, so that none of
    it is counted as a plot's own time."""

    try:
        import matplotlib
    except ImportError:
        return
    with contextlib.suppress(Exception):
        _unlocked(Path(matplotlib.get_cachedir()))
    import matplotlib.pyplot

    _register_fonts()


LOCK_HELD = 60.0
"""Seconds past which a lock matplotlib left on a file it keeps is no one's: it holds one
for the moment it takes to write the file."""


def _unlocked(kept: Path) -> None:
    """Take from the folder matplotlib keeps its files in (``kept``) the locks no process
    holds any more. One ended as it wrote the list of the computer's fonts leaves its lock
    there, and every Python after lists the fonts anew (many seconds), waits five more on
    the lock, and keeps nothing: each start as slow as the first, for good."""

    for lock in kept.glob("*.matplotlib-lock"):
        with contextlib.suppress(OSError):
            if time.time() - lock.stat().st_mtime > LOCK_HELD:
                lock.unlink()


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
"""Whose files are being noted now, if anyone's (``_audited``)."""
_HOOKED = False
_WRITES = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_NEVER_DATA = frozenset(
    {".py", ".pyc", ".ttf", ".otf", ".ttc", ".dfont", ".afm", ".pfb", ".woff", ".woff2"}
)
"""Files Python and matplotlib open for themselves: modules, and fonts."""
_PYTHONS = frozenset({"site-packages", "__pycache__"})
"""Folders that are Python's own, whichever Python's."""
_LISTINGS = frozenset({"os.listdir", "os.scandir"})
"""What Python says as a folder is listed, however it is: ``glob``, ``Path.iterdir`` and
``os.walk`` list through these."""
_STARTS = frozenset({"_thread.start_new_thread", "_thread.start_joinable_thread"})
"""What Python says as a thread is started."""
_IMPORTERS = frozenset({"importlib", "_frozen_importlib", "_frozen_importlib_external", "pkgutil"})
"""Whose code lists a folder to find a module in it, not to read what is there."""
SPELT_MOST = 400
"""How many of the words a Python file spells are tried as names of files, at most."""


class _Reading:
    """What in a folder a plot's Python reads as it runs: the data it plots, and the
    modules beside it. The plot is drawn again when any of it changes.

    Files opened: Python's audit hook tells of each, however it is opened (``open``,
    ``os.open``, numpy's and pandas' readers), by the plot's thread or one it started.
    Folders listed (``_LISTINGS``): kept by what is in them, so a file put where the plot
    globs is a change -- but not the listing Python does itself to find a module.

    What Python is not told of -- a file a library opens for itself (HDF5, Parquet) -- is
    found in the plot's own words (``spelt``: a file its Python names counts as read), and
    is named for it by its shape, where the words do not say (``named``: its ``data``).

    Not counted: a file the Python also writes (a cache of its own, which would have it
    drawn again for ever), what Python and matplotlib open for themselves (``_NEVER_DATA``;
    anything in this Python's environment, should the folder hold it, or in a hidden
    folder), and what threads not the plot's open meanwhile (a studio reading its documents).

    Modules: those it imports from beside its file (``beside``)."""

    def __init__(self, folder: Path, source: Path) -> None:
        self.folder = os.path.realpath(folder) + os.sep
        self.source = os.path.realpath(source)
        self.python = tuple(
            {os.path.realpath(prefix) + os.sep for prefix in (sys.prefix, sys.base_prefix)}
        )
        self.thread = threading.get_ident()
        self.threads: set[threading.Thread] = set()
        self.read: list[str] = []
        """Each file read and (its name ending as a folder's does) each folder listed."""
        self.written: set[str] = set()
        self.before: _Reading | None = None

    def __enter__(self) -> _Reading:
        global _READING, _HOOKED
        if not _HOOKED:
            # (Once in a process: a hook is never taken away, and idle it only looks.)
            sys.addaudithook(_audited)
            _HOOKED = True
        self.thread = threading.get_ident()
        self.before, _READING = _READING, self
        return self

    def __exit__(self, *error: object) -> None:
        global _READING
        _READING = self.before

    def mine(self) -> bool:
        """Whether the thread running now is the plot's: its own, or one it started."""

        thread = threading.get_ident()
        return thread == self.thread or any(own.ident == thread for own in self.threads)

    def started(self, function: object) -> None:
        """A thread the plot's Python starts (as ``threading`` does, and a pool of them)
        is the plot's: what it opens is read by the plot."""

        thread = getattr(function, "__self__", None)
        if isinstance(thread, threading.Thread):
            self.threads.add(thread)

    def _data(self, name: str, folder: bool = False) -> bool:
        """Whether ``name`` -- a file's whole name, or a ``folder``'s -- may be the plot's
        to read: in its folder, and not Python's or matplotlib's own."""

        inside = name + os.sep if folder else name
        if not inside.startswith(self.folder) or inside.startswith(self.python):
            return False
        folders = inside[len(self.folder):].split(os.sep)[:-1]
        if any(part.startswith(".") or part in _PYTHONS for part in folders):
            return False
        return folder or os.path.splitext(name)[1].lower() not in _NEVER_DATA

    def note(self, file: object, mode: object = None, flags: object = None) -> None:
        if isinstance(file, int):
            return  # (a descriptor: its file was opened, and noted, before)
        name = os.path.realpath(os.fsdecode(file))  # type: ignore[arg-type]
        if not self._data(name):
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

    def look(self, folder: object, by: str = "") -> None:
        """A folder listed (by code of the module ``by``): there or not yet, what is in it
        is read. (Not when Python lists it for itself, looking for a module to import.)"""

        if isinstance(folder, int) or by.partition(".")[0] in _IMPORTERS:
            return
        name = os.path.realpath(os.fsdecode(folder if folder is not None else os.curdir))  # type: ignore[arg-type]
        if self._data(name, folder=True):
            self.read.append(name + os.sep)

    def named(self, data: Iterable[str]) -> None:
        """The data the plot's shape names (its ``data``), each by its whole name: a file,
        there or not yet; a folder, for all that is in it; a pattern, for the files it
        finds -- and the folders looked in, for one more to be found there."""

        for name in data:
            found = [name]
            if glob.has_magic(name):
                # (Where the pattern starts, there or not: watched for what it will find.)
                self.look(_fixed(name))
                found = self._found(name)
            for file in found:
                if not os.path.isdir(file):
                    self.note(file)
                    continue
                for inside in self._found(os.path.join(glob.escape(file), "**")):
                    if os.path.isfile(inside):
                        self.note(inside)

    def _found(self, pattern: str) -> list[str]:
        """What ``pattern`` finds now, the folders it looks in noted as it lists them."""

        with self:
            return sorted(glob.glob(pattern, recursive=True))

    def spelt(self, function: str) -> None:
        """The files the plot's Python names in so many words -- ``"loss.h5"``,
        ``HERE / "runs" / "a.parquet"``, ``"runs/*.h5"`` -- count as read, when they are
        there: of a file a library opens for itself, Python is told nothing. The words are
        the function's own, those of what it uses in its file, and those of the modules
        beside it (``_spelt``); a name is looked for from its Python file's folder and
        from the plot's, a pattern from its Python file's alone."""

        modules = [name for name in self.read if name.endswith(".py")]
        for source in dict.fromkeys((self.source, *modules)):
            own = os.path.dirname(source)
            for name in _spelt(source, function if source == self.source else ""):
                if _pattern(name):
                    found = glob.glob(name, root_dir=own, recursive=True)[:FILES_MOST]
                    found = [os.path.join(own, file) for file in found]
                else:
                    name = os.path.expanduser(name)
                    found = [os.path.join(own, name), os.path.join(self.folder, name)]
                for file in found:
                    if os.path.isfile(file):
                        self.note(file)

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
        """What was read (from the ``start``-th noted on), each once: the folders listed,
        then the files in the order read. (The folders first: where only so many are kept
        (``FILES_MOST``), a file more in one is still seen.)"""

        found = [
            name
            for name in dict.fromkeys(self.read[start:])
            if name not in self.written
            and name != self.source
            and (name.endswith(os.sep) or not os.path.isdir(name))
        ]
        return sorted(found, key=lambda name: not name.endswith(os.sep))


def _audited(event: str, args: tuple) -> None:
    reading = _READING
    if reading is None or not (event == "open" or event in _LISTINGS or event in _STARTS):
        return
    try:
        if not reading.mine():
            return
        if event == "open":
            reading.note(*args)
        elif event in _STARTS:
            reading.started(args[0])
        else:
            # (Who lists it: the code that called ``os.listdir``, one frame out from here.)
            reading.look(args[0], str(sys._getframe(1).f_globals.get("__name__") or ""))
    except Exception:  # (a hook that fails would fail what it was told of)
        return


def _fixed(pattern: str) -> str:
    """The folder a pattern starts in: its whole name as far as it is written out."""

    parts = pattern.split(os.sep)
    fixed: list[str] = []
    for part in parts[:-1]:
        # (A part written out may yet be written as a pattern of itself: ``glob.escape``.)
        plain = re.sub(r"\[([*?\[])\]", r"\1", part)
        if glob.has_magic(part) and glob.escape(plain) != part:
            break
        fixed.append(plain)
    return os.sep.join(fixed) or os.sep


def _pattern(name: str) -> bool:
    """Whether a word a plot's Python spells reads as a pattern of files' names
    (``runs/*.h5``, ``*.csv``) -- not as a mark that only looks like one (a marker ``*``)."""

    return glob.has_magic(name) and (os.sep in name or re.search(r"\.\w+$", name) is not None)


_SPELT: dict[tuple[str, str], tuple[tuple, tuple[str, ...]]] = {}
"""The words each Python file spells for a function, and what the file was then."""


def _spelt(source: str, function: str = "") -> tuple[str, ...]:
    """The words the Python file ``source`` spells that may name a file: each text, and
    texts it joins into a path (``HERE / "runs" / "a.csv"``, ``join(HERE, "runs", "a.csv")``).
    For a ``function`` of it: its own words, those of what it uses in the file (a helper
    that reads for several plots), and those outside any function -- not another plot's.
    Read again when the file changes."""

    was = _stamps((source,))
    known = _SPELT.get((source, function))
    if known is not None and known[0] == was:
        return known[1]
    try:
        tree = ast.parse(Path(source).read_bytes())
    except (OSError, SyntaxError, ValueError):
        tree = ast.Module(body=[], type_ignores=[])
    parts: list[ast.AST] = list(tree.body)
    named_here = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    made = {part.name: part for part in parts if isinstance(part, named_here)}
    if function in made:
        parts = [part for part in parts if not isinstance(part, named_here)]
        used, wanted = set(), [function]
        while wanted:
            name = wanted.pop()
            if name in used or name not in made:
                continue
            used.add(name)
            parts.append(made[name])
            wanted += [node.id for node in ast.walk(made[name]) if isinstance(node, ast.Name)]
    found: dict[str, None] = {}
    taken: set[int] = set()
    for part in parts:
        # (Each part is come to after what holds it: a text joined into a path is taken.)
        for node in ast.walk(part):
            if id(node) in taken:
                continue
            for name in _joined(node, taken):
                if 0 < len(name) < 256 and "\n" not in name and "\0" not in name:
                    found[name] = None
    words = tuple(found)[:SPELT_MOST]
    if len(_SPELT) > 256:
        _SPELT.clear()
    _SPELT[(source, function)] = (was, words)
    return words


def _joined(node: ast.AST, taken: set[int]) -> Iterator[str]:
    """The text ``node`` is, or the path it joins texts into -- whose parts are ``taken``,
    not names by themselves: those ``/`` joins, and a pattern among a call's (``"*.h5"``
    alone would find every such file beside the Python)."""

    def text(part: ast.AST | None) -> str | None:
        written = isinstance(part, ast.Constant) and isinstance(part.value, str)
        return part.value if written else None  # type: ignore[union-attr]

    if text(node) is not None:
        yield text(node)  # type: ignore[misc]
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        parts: list[ast.AST] = []
        while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and text(node.right):
            parts.append(node.right)
            node = node.left
        if text(node):
            parts.append(node)
        if len(parts) > 1:
            taken.update(id(part) for part in parts)
            yield "/".join(text(part) for part in reversed(parts))  # type: ignore[misc]
    elif isinstance(node, ast.Call):
        run: list[ast.AST] = []
        for argument in (*node.args, None):
            if text(argument):
                run.append(argument)  # type: ignore[arg-type]
                continue
            if len(run) > 1:
                taken.update(id(part) for part in run if glob.has_magic(text(part) or ""))
                yield "/".join(text(part) for part in run)  # type: ignore[misc]
            run = []


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
