"""A molecule drawn by hand: a structure rendered by mol-sketch, in the figure's colours.

A ``structure`` component draws a PDB or mmCIF file (or a PDB ID, fetched) with
`mol-sketch <https://github.com/jamaliki/mol-sketch>`_ -- engraved ribbons,
watercolour, pen and ink -- as a panel of the figure:

- its **look** follows the theme unless one is named: watercolour in a sketched
  theme, dark paper on a dark page, engraved colour otherwise;
- it is drawn on the figure's own page colour, which is then taken out, so the
  molecule sits on whatever is behind it with no box round it;
- ``colors`` names a colour for a chain (``"A"``), a residue (``"SER195"``), a
  subunit or an entity -- a hex colour, or one of the figure's **tones**, so the
  kinase domain on the protein map and the chain in the structure are one colour;
- ``yaw``, ``pitch``, ``roll``, and ``zoom`` turn and frame it, and ``pan_x`` and
  ``pan_y`` shift it (fractions of its box); ``cartoon``, ``sticks``, and ``surface``
  say what to draw (mol-sketch selections), and ``site`` marks an active site -- a
  selection, or ``ligand`` for the largest ligand and what lies within ``site_within``
  Å of it -- its residues labelled with ``site_labels``;
- ``palette`` names one of mol-sketch's group palettes, ``density`` draws a density
  map with it (``auto``: the map the entry was built into; an EMDB ID; or a map file),
  and ``style`` sets any field of mol-sketch's style over the look, nested as
  mol-sketch writes them -- ``style: {fill: ink colour, line: {width: 2}}`` (see
  ``flexo.structure_style``).

mol-sketch is an optional dependency (``pip install "flexo[molecules]"``, or the
``python`` folder of a mol-sketch clone). The picture is drawn at print
resolution and embedded, so the editable SVG, the PDF, and the slides carry it.
"""

from __future__ import annotations

import atexit
import difflib
import functools
import re
import struct
import threading
import zlib
from dataclasses import dataclass
from pathlib import Path

from flexo.confine import outside
from flexo.diagnostics import Diagnostic, FlexoError, Severity
from flexo.drawn import Picture, Shape, Words, path, units
from flexo.geometry import Side, Size
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import NodeSpec, PortSpec, Record, Settings, TextRun
from flexo.style import LayoutStyle, Palette

LOOKS = (
    "engraved-colour",
    "engraved",
    "watercolour",
    "ink-colour",
    "ink",
    "dark-paper",
    "chalkboard",
    "assembly-cartoon",
    "assembly-surface",
)


@atexit.register
def _close_engine() -> None:
    """mol-sketch's engine, if it was started, closed as Python exits: left to be collected
    while the interpreter shuts down, its V8 waits for ever on a thread already gone, and
    the process never ends."""

    import sys

    engine_module = sys.modules.get("molsketch._engine")
    engine = getattr(engine_module, "_engine", None)
    if engine is None:
        return
    try:
        engine.v8.close()
    finally:
        engine_module._engine = None  # type: ignore[union-attr]


def _fail(node: NodeSpec, code: str, message: str, hint: str | None = None) -> FlexoError:
    return FlexoError(Diagnostic(f"structure.{code}", message, entity_id=node.id, hint=hint))


def _colours(node: NodeSpec) -> tuple[tuple[str, str], ...]:
    value = node.property("colors")
    if value is None:
        return ()
    if not isinstance(value, tuple):
        raise _fail(node, "colors", '"colors" is a list of {group, color} mappings.')
    pairs = []
    for record in value:
        assert isinstance(record, Record)
        group, colour = record.get("group"), record.get("color")
        # A row still being filled in (a chain with no colour yet) colours nothing.
        if group is None or colour is None or not str(group).strip() or not str(colour).strip():
            continue
        pairs.append((str(group).strip(), str(colour).strip()))
    return tuple(pairs)


def structure_tones(node: NodeSpec) -> tuple[str, ...]:
    """The figure tones a structure's colours name (a colour written ``#rrggbb`` is none)."""

    return tuple(
        dict.fromkeys(colour for _, colour in _colours(node) if not colour.startswith("#"))
    )


def structure_title(node: NodeSpec, style: LayoutStyle) -> TextMetrics:
    """A structure's name as it is set over its panel: in the title's weight, wrapped to the
    panel's width."""

    u = units(style).u
    width = float(node.property("width") or 20.0 * u)  # type: ignore[arg-type]
    return units(style).measurer.measure(
        node.label, weight=style.typography.title_weight, max_width=width
    )


def structure_drawing(node: NodeSpec, style: LayoutStyle) -> Picture:
    """The panel: the molecule's box, under the component's name if it has one. A molecule
    that can't be had (a PDB entry not downloaded, a file that does not read) is a dashed
    panel the same size saying why, so the rest of the figure is drawn all the same."""

    measures = units(style)
    u = measures.u
    width = float(node.property("width") or 20.0 * u)  # type: ignore[arg-type]
    height = float(node.property("height") or 15.0 * u)  # type: ignore[arg-type]
    words = []
    top = 0.0
    if node.label:
        # A long name is set on as many lines as the panel is wide, not over its edges.
        title = structure_title(node, style)
        words.append(
            Words(
                f"{node.id}.label",
                node.label,
                title,
                width / 2.0,
                title.baseline,
                weight=style.typography.title_weight,
            )
        )
        top = title.height + 0.3 * u
    size = Size(width, top + height)
    middle = (top + height / 2.0) / size.height
    ports = (PortSpec("input", Side.WEST, middle), PortSpec("output", Side.EAST, middle))
    problem = _problem(node, style)
    if problem is None or problem.drawn:
        return Picture(
            size, (), tuple(words), ports,
            images=((f"{node.id}.molecule", 0.0, top, width, height),),
        )
    shapes, said = _placeholder(node, measures, problem, top, width, height)
    return Picture(size, shapes, (*words, *said), ports)


def _placeholder(node: NodeSpec, measures, problem: _Problem, top: float, width: float,
                 height: float) -> tuple[tuple[Shape, ...], tuple[Words, ...]]:
    """A dashed panel where the molecule goes, a warning sign, and what went wrong."""

    u = measures.u
    inset = 0.4 * measures.pen
    corner = min(0.6 * u, width / 4.0, height / 4.0)
    x0, y0, x1, y1 = inset, top + inset, width - inset, top + height - inset
    frame = path(
        "M", x0 + corner, y0, "L", x1 - corner, y0, "A", corner, corner, 0, 0, 1, x1, y0 + corner,
        "L", x1, y1 - corner, "A", corner, corner, 0, 0, 1, x1 - corner, y1,
        "L", x0 + corner, y1, "A", corner, corner, 0, 0, 1, x0, y1 - corner,
        "L", x0, y0 + corner, "A", corner, corner, 0, 0, 1, x0 + corner, y0, "Z",
    )
    room = max(width - 1.6 * u, 4.0 * u)
    heading = (TextRun(problem.title, weight=600),)
    reason = (TextRun(problem.reason),)
    first = measures.measurer.measure(heading, max_width=room)
    second = measures.small.measure(reason, max_width=room)
    sign = 1.1 * u
    gap = 0.35 * u
    total = sign + gap + first.height + 0.2 * u + second.height
    y = top + max((height - total) / 2.0, 0.3 * u)
    mid = width / 2.0
    warning = path(
        "M", mid, y, "L", mid + sign * 0.58, y + sign, "L", mid - sign * 0.58, y + sign, "Z",
        "M", mid, y + sign * 0.36, "L", mid, y + sign * 0.66,
        "M", mid, y + sign * 0.82, "L", mid, y + sign * 0.84,
    )
    shapes = (
        Shape(f"{node.id}.placeholder", frame, "guide", width=measures.pen),
        Shape(f"{node.id}.warning", warning, "line", width=measures.pen, color="muted-ink"),
    )
    y += sign + gap
    said = (
        Words(f"{node.id}.problem", heading, first, mid, y + first.baseline, weight=600),
        Words(
            f"{node.id}.reason", reason, second, mid, y + first.height + 0.2 * u + second.baseline,
            role="muted-ink", size=measures.small_size,
        ),
    )
    return shapes, said


@dataclass(frozen=True, slots=True)
class _Problem:
    """What keeps a structure from being drawn as written: ``title`` and ``reason`` as its
    panel says them. ``drawn``: the molecule is drawn all the same, without what it can't
    show (a colour for a chain it does not have)."""

    code: str
    title: str
    reason: str
    hint: str | None = None
    drawn: bool = False


def structure_problem(node: NodeSpec, style: LayoutStyle) -> Diagnostic | None:
    """What keeps the structure ``node`` from being drawn as written, as a warning on it --
    the figure is drawn all the same, the structure as a panel saying why (or, for a colour
    it can't show, without that colour) -- or None."""

    problem = _problem(node, style)
    if problem is None:
        return None
    said = problem.title.startswith("Couldn't")
    message = f"{problem.title}. {problem.reason}" if said else problem.reason
    return Diagnostic(
        f"structure.{problem.code}", message, Severity.WARNING, entity_id=node.id,
        hint=problem.hint,
    )


def _problem(node: NodeSpec, style: LayoutStyle) -> _Problem | None:
    """The molecule set up as it will be drawn -- read, or fetched, its settings checked --
    without drawing it: what goes wrong, if anything."""

    name = _name(node)
    try:
        # Colours are checked here, not painted: any tone will do.
        tones = Palette("checking", {}, tuple((tone, 1) for tone in structure_tones(node)))
        ask = _ask(node, style, tones)
    except FlexoError as error:
        said = error.diagnostics[0]
        return _Problem(said.code.removeprefix("structure."), f"Couldn't draw {name}",
                        _sentence(said.message), said.hint)
    found = _checked(ask, name)
    failed = None if found else _failed.get(_failing(ask))
    return _Problem("draw", f"Couldn't draw {name}", failed, drawn=True) if failed else found


@functools.lru_cache(maxsize=64)
def _checked(ask: _Ask, name: str) -> _Problem | None:
    if not Path(ask.source).exists() and re.search(r"[/\\]|\.(pdb|cif|mmcif|ent|json)$", ask.source,
                                                   re.IGNORECASE):
        return _Problem("source", f"Couldn't find {name}", "There is no such file in the folder.")
    fetched = not Path(ask.source).exists()
    try:
        figure = _one_at_a_time(_drawn, ask)
    except ImportError:
        return _Problem(
            "molsketch", f"Couldn't draw {name}", "Drawing a structure needs mol-sketch.",
            'pip install "flexo[molecules]", or pip install path/to/mol-sketch/python.',
        )
    except _Unknown as error:
        return _Problem(error.code, f"Couldn't draw {name}", _sentence(str(error)), error.hint)
    except ConnectionError:
        return _Problem("fetch", f"Couldn't download {name}",
                        "The Protein Data Bank can't be reached. Check the network connection.")
    except FileNotFoundError:
        return _Problem("source", f"Couldn't find {name}", "There is no such file in the folder.")
    except Exception as error:  # whatever it is, the panel says it, not the slide
        first = str(error).split("\n")[0]
        said = _sentence(first) if first else "It can't be read as a structure."
        if fetched and "not in the PDB" in first:
            return _Problem("fetch", f"Couldn't download {name}", f"{name} isn't in the PDB.")
        if fetched and "not a PDB ID" in first:
            return _Problem("source", f"Couldn't draw {name}",
                            f"“{ask.source}” isn't a PDB ID or a file in the folder.")
        return _Problem("source", f"Couldn't read {name}", said)
    try:
        _one_at_a_time(_check_chains, figure, ask.colours)
    except _NoSuchChain as error:
        return _Problem("colors", name, _sentence(str(error)), error.hint, drawn=True)
    return None


def fetch_structure(pdb_id: str) -> str:
    """The PDB entry ``pdb_id`` downloaded and read, ready to draw (mol-sketch keeps the file,
    so it is fetched once): its ID, in capitals. A ValueError says why it couldn't be, in a
    sentence."""

    pid = pdb_id.strip().upper()
    if not re.fullmatch(r"[0-9][A-Z0-9]{3}", pid):
        raise ValueError(
            f"“{pdb_id.strip()}” isn't a PDB ID. An ID is four characters, starting with a "
            "digit, like 1UBQ."
        )
    try:
        _one_at_a_time(_loaded, pid, 0.0)
    except ImportError:
        raise ValueError("Drawing a structure needs mol-sketch.") from None
    except ConnectionError:
        raise ValueError(
            f"Couldn't download {pid}: the Protein Data Bank can't be reached. Check the network "
            "connection."
        ) from None
    except Exception as error:
        said = str(error).split("\n")[0] or "it can't be read"
        if "not in the PDB" in said:
            said = "there is no such entry in the PDB"
        raise ValueError(f"Couldn't download {pid}: {said.rstrip('.')}.") from None
    return pid


_PLAIN = frozenset(
    {"A", "AN", "AND", "AS", "AT", "BY", "FOR", "FROM", "IN", "INTO", "OF", "ON", "OR", "THE",
     "TO", "WITH"}
)
"""Short words a name in capitals has that are English, not an acronym like DNA or HIV."""

NAMED = 32
"""How long (characters) a structure's name from its file may be before it is cut short."""


def structure_caption(path: Path) -> str | None:
    """What a structure file says it holds, as a person would write it, with its PDB ID:
    ``Regulatory protein E2 (1A7G)`` for a file that names its molecule REGULATORY PROTEIN
    E2. None for a file that names nothing."""

    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:400_000]
    except OSError:
        return None
    name = entry = None
    if path.suffix.lower() in (".cif", ".mmcif"):
        for key in ("_struct.pdbx_descriptor", "_struct.title"):
            found = re.search(rf"^{re.escape(key)}\s+(.+?)\s*$", text, re.MULTILINE)
            value = found.group(1).strip().strip("'\"").strip() if found else ""
            if value and value not in ("?", "."):
                name = value
                break
        found = re.search(r"^_entry\.id\s+(\S+)", text, re.MULTILINE)
        entry = found.group(1) if found else None
    else:
        found = re.search(r"^COMPND.{4}.*?MOLECULE:\s*([^;\n]+)", text, re.MULTILINE)
        if not found:
            found = re.search(r"^TITLE\s+(.+?)\s*$", text, re.MULTILINE)
        name = found.group(1).strip() if found else None
        found = re.match(r"HEADER.{56}([0-9][A-Za-z0-9]{3})", text)
        entry = found.group(1) if found else None
    stem = re.sub(r"\.(pdb|cif|mmcif|ent)$", "", path.name, flags=re.IGNORECASE)
    if entry is None and re.fullmatch(r"[0-9][A-Za-z0-9]{3}", stem):
        entry = stem
    if not name:
        return None
    # The first of the molecules it names, cut short between words.
    name = name.split(",")[0].strip()
    if len(name) > NAMED:
        words = name[:NAMED + 1].split()[:-1] or [name[:NAMED]]
        while len(words) > 1 and words[-1].upper() in _PLAIN:
            words.pop()
        name = " ".join(words)
    if name.isupper():
        def readable(piece: str) -> str:
            letters = re.sub(r"[^A-Z]", "", piece)
            short = len(letters) <= 4 and letters not in _PLAIN
            return piece if short or any(ch.isdigit() for ch in piece) else piece.lower()

        words = ("-".join(readable(piece) for piece in word.split("-")) for word in name.split())
        name = " ".join(words)
        name = name[:1].upper() + name[1:]
    return f"{name} ({entry.upper()})" if entry else name


def _name(node: NodeSpec) -> str:
    """A structure as its panel names it: a PDB ID in capitals, a file by its name."""

    source = str(node.property("source") or "").strip()
    stem = re.sub(r"\.(pdb|cif|mmcif|ent)$", "", Path(source).name, flags=re.IGNORECASE)
    if re.fullmatch(r"[0-9][A-Za-z0-9]{3}", stem):
        return stem.upper()
    return Path(source).name or "the structure"


def _called(name: object) -> str:
    """A molecule by the name mol-sketch reads it as: a PDB ID in capitals."""

    text = str(name or "").strip()
    if re.fullmatch(r"[0-9][A-Za-z0-9]{3}", text):
        return text.upper()
    return text or "the structure"


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text.endswith((".", "?", "!")) else f"{text}."


def structure_png(
    node: NodeSpec, style: LayoutStyle, palette: Palette, width: float, height: float
) -> bytes:
    """The molecule, drawn by mol-sketch at ``width`` by ``height`` points, as a PNG with
    the page taken out. Should mol-sketch fail to draw it, the panel is left hatched and
    the failure is said on the structure (structure_problem): the figure is drawn all the
    same."""

    ask = _ask(node, style, palette)
    if _failed.get(_failing(ask)):
        return _hatched(width / height)
    try:
        return _one_at_a_time(_render, ask, width / height)
    except Exception as error:
        # What mol-sketch said, without where in its code it said it.
        said = re.sub(r"^.*?\b[A-Za-z]*Error: ", "", str(error).split("\n")[0]).strip()
        _failed[_failing(ask)] = (
            f"mol-sketch couldn't draw it with these settings ({said})." if said
            else "mol-sketch couldn't draw it with these settings."
        )
        return _hatched(width / height)


_failed: dict[tuple, str] = {}
"""Why mol-sketch failed to draw a structure, by what it was drawn from (its colours aside)."""


def _failing(ask: _Ask) -> tuple:
    """What a structure is drawn from, but its colours and look: one failure said whatever
    the page it is drawn on."""

    return (ask.source, ask.stamp, ask.view, ask.show, ask.site, ask.group_palette, ask.style,
            ask.pan, ask.density, ask.site_within, ask.site_labels, ask.solvent)


def _hatched(aspect: float) -> bytes:
    """A panel faintly hatched, where a molecule mol-sketch could not draw would be."""

    import numpy as np

    width = 240
    height = max(1, round(width / aspect))
    rows, columns = np.indices((height, width))
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    pixels[..., :3] = 128
    pixels[..., 3] = np.where((rows + columns) % 16 < 2, 70, 0)
    return _png(pixels)


def structure_settings(node: NodeSpec, style: LayoutStyle, palette: Palette) -> dict[str, object]:
    """What the studio shows of a structure's mol-sketch settings: the style it is drawn
    with -- its look's, the figure's colours, and its own settings over them -- by dotted
    name, mol-sketch's looks and group palettes to choose from, and the molecule's chains.
    A structure that can't be drawn as written says why (``problem``, ``reason``), with
    what can still be read."""

    problem = _problem(node, style)
    # A colour for a chain it lacks is said on its row of colours; the rest, on the structure.
    said = (
        {} if problem is None or problem.code == "colors"
        else {"problem": problem.title, "reason": problem.reason}
    )
    if problem is not None and not problem.drawn:
        return {"style": {}, "looks": list(LOOKS), "palettes": {}, "chains": [], **said}
    ask = _ask(node, style, palette)
    try:
        return {**_one_at_a_time(_settings, ask), **said}
    except _Unknown as error:
        raise _fail(node, error.code, str(error), hint=error.hint) from None


@dataclass(frozen=True, slots=True)
class _Ask:
    """Everything a structure is drawn from, checked: what its drawing is kept by."""

    source: str
    stamp: float
    look: str
    paper: str
    colours: tuple[tuple[str, str], ...]
    view: tuple[tuple[str, float], ...]
    show: tuple[tuple[str, str], ...]
    site: str | None
    roles: tuple[tuple[str, str], ...]
    group_palette: str | None = None
    style: tuple[tuple[str, object], ...] = ()
    pan: tuple[float, float] | None = None
    density: str | None = None
    site_within: float | None = None
    site_labels: bool = False
    solvent: bool = False
    """Whether its waters and lone ions are drawn (as small dots, floating free)."""


def _ask(node: NodeSpec, style: LayoutStyle, palette: Palette) -> _Ask:
    source = node.property("source")
    if not isinstance(source, str) or not source.strip():
        raise _fail(node, "source", "A structure needs a file or a PDB ID (source:).")
    look = str(node.property("look") or _theme_look(style, palette)).strip().lower()
    if look not in LOOKS:
        raise _fail(node, "look", f'look "{look}" is not a mol-sketch look.', hint=", ".join(LOOKS))
    paper = palette.get("canvas", "#ffffff")
    colours = []
    for group, colour in _colours(node):
        if not colour.startswith("#"):
            index = palette.tone_index(colour)
            if index is None:
                raise _fail(
                    node, "colors", f'"{colour}" is neither a colour nor a tone of the figure.'
                )
            colour = palette.get(f"tone-{index}-stroke")
        colours.append((group, colour))
    view = tuple(
        (name, float(value))  # type: ignore[arg-type]
        for name in ("yaw", "pitch", "roll", "zoom")
        if (value := node.property(name)) is not None
    )
    show = tuple(
        (name, str(value))
        for name in ("cartoon", "sticks", "surface")
        if (value := node.property(name)) is not None
    )
    site = node.property("site")
    # The figure's own colours where it has them: its ink, and -- when a protein map
    # in the figure draws helices and strands -- theirs, so the two agree.
    roles = [("ink", palette.get("ink", "#000000"))]
    for tone, key in (("helix", "helix"), ("strand", "sheet")):
        index = palette.tone_index(tone)
        if index is not None:
            roles.append((key, palette.get(f"tone-{index}-stroke")))
    path = Path(source).expanduser()
    if path.exists() and outside(path):
        raise _fail(node, "source", "The structure file is outside the folder.")
    density = node.property("density")
    if density is not None:
        density = str(density).strip()
        if Path(density).expanduser().exists() and outside(Path(density).expanduser()):
            raise _fail(node, "density", "The map file is outside the folder.")
    pan = (node.property("pan_x"), node.property("pan_y"))
    within = node.property("site_within")
    group_palette = node.property("palette")
    return _Ask(
        str(path) if path.exists() else source.strip(),
        path.stat().st_mtime if path.exists() else 0.0,
        look,
        paper,
        tuple(colours),
        view,
        show,
        None if site is None else str(site),
        tuple(roles),
        None if group_palette in (None, "") else str(group_palette),
        _style(node),
        None if pan == (None, None) else (float(pan[0] or 0.0), float(pan[1] or 0.0)),  # type: ignore[arg-type]
        density or None,
        None if within is None else float(within),  # type: ignore[arg-type]
        bool(node.property("site_labels")),
        bool(node.property("solvent")),
    )


def _style(node: NodeSpec) -> tuple[tuple[str, object], ...]:
    """The node's own mol-sketch settings, by dotted name, their choices checked."""

    from flexo.structure_style import CHOICES

    value = node.property("style")
    if value is None:
        return ()
    if not isinstance(value, Settings):
        raise _fail(
            node,
            "style",
            '"style" is a set of mol-sketch settings.',
            hint="Write style: {fill: ink colour, line: {width: 2}}.",
        )
    for key, item in value.items:
        choices = CHOICES.get(key)
        if choices and item not in choices:
            raise _fail(
                node,
                "style",
                f'{key} "{item}" is not one of mol-sketch\'s.',
                hint=", ".join(choices),
            )
    return value.items


class _Unknown(ValueError):
    """Something named that mol-sketch does not have: a setting, a palette, a map."""

    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint


_MOLSKETCH = threading.RLock()
"""mol-sketch's engine is one V8 for the process, made the first time it is asked for with
no lock of its own: two structures drawn at once (the studio serves each request on a thread)
would each make one, and a molecule read into the engine let go would be asked of the other
-- "unknown input in1", for as long as it is kept. Whatever reads or draws a molecule holds
this, one at a time."""


def _one_at_a_time(work, *args):
    """``work(*args)`` with mol-sketch to itself. A molecule kept from an engine since let go
    (one made elsewhere, before this lock) is read again, once."""

    with _MOLSKETCH:
        try:
            return work(*args)
        except Exception as error:
            if "unknown input" not in str(error):
                raise
            _loaded.cache_clear()
            return work(*args)


@functools.lru_cache(maxsize=8)
def _loaded(source: str, stamp: float):
    """The molecule, read once (or fetched) and copied for each way it is drawn."""

    import molsketch as ms

    del stamp  # part of the cache key: an edited file is read again
    return ms.load(source) if Path(source).exists() else ms.fetch(source)


@functools.lru_cache(maxsize=1)
def _fields() -> frozenset[str]:
    """Every field of mol-sketch's style, by dotted name."""

    import molsketch as ms

    def walk(value: dict, prefix: str) -> list[str]:
        names = []
        for key, item in value.items():
            names += walk(item, f"{prefix}{key}.") if isinstance(item, dict) else [f"{prefix}{key}"]
        return names

    return frozenset(walk(ms.default_style(), ""))


def _drawn(ask: _Ask):
    """A mol-sketch figure set up as ``ask`` says, ready to draw or to read."""

    import molsketch as ms

    figure = _loaded(ask.source, ask.stamp).copy()
    # A colour for a chain the molecule lacks would show nowhere: it is left out, and said
    # (structure_problem).
    _, missing = _chains(figure, ask.colours)
    figure = figure.look(ask.look)
    figure.set(
        palette={"paper": ask.paper, **dict(ask.roles)},
        # A scene's own captions and step labels are the app's; the figure names
        # the panel itself.
        **{"paper.grain": 0, "paper.wash": 0, "show.caption": False, "show.step_label": False},
    )
    if ask.group_palette:
        if ask.group_palette not in ms.palettes():
            raise _Unknown(
                "palette",
                f'"{ask.group_palette}" is not one of mol-sketch\'s palettes.',
                ", ".join(ms.palettes()),
            )
        figure.palette(ask.group_palette)
    if ask.style:
        fields = _fields()
        for key, _ in ask.style:
            if key not in fields:
                near = difflib.get_close_matches(key, fields, n=3)
                raise _Unknown(
                    "style",
                    f'"{key}" is not a field of mol-sketch\'s style.',
                    f"Did you mean {' or '.join(near)}?" if near else "See its docs/style.md.",
                )
        figure.set(
            **{key: list(value) if isinstance(value, tuple) else value for key, value in ask.style}
        )
        # The paper is taken out after: it stays the figure's own.
        figure.set(**{"palette.paper": ask.paper})
    for group, colour in ask.colours:
        if group not in missing:
            figure.color(group, colour)
    if ask.show:
        figure.show(**dict(ask.show))
    if "sticks" not in dict(ask.show):
        _solvent(figure, ask)
    if ask.view or ask.pan:
        figure.view(**dict(ask.view), **({"pan": ask.pan} if ask.pan else {}))
    if ask.site == "ligand":
        try:
            figure.site(ligand=True, within=ask.site_within or 5.0)
        except ValueError as error:
            raise _Unknown("site", str(error)) from None
    elif ask.site:
        figure.site(ask.site)
    if ask.density:
        try:
            figure.map(ask.density)
        except (OSError, ValueError) as error:
            raise _Unknown(
                "density",
                f"No map {ask.density}: {error}",
                "auto (the map the entry was built into), an EMDB ID as EMD-11638, or a map file",
            ) from None
    return figure


def _solvent(figure, ask: _Ask) -> None:
    """Waters and lone ions (a calcium, a chloride) left out of what the look draws as
    sticks -- they float free of the molecule as stray dots -- unless asked for."""

    sticks = (figure.style.get("reps") or {}).get("sticks") or ""
    if ask.solvent:
        figure.show(sticks=f"({sticks}) or water" if sticks else "water")
        return
    ions = _ions(ask.source, ask.stamp)
    if sticks and ions:
        figure.show(sticks=f"({sticks}) and not resn {'+'.join(ions)}")


@functools.lru_cache(maxsize=8)
def _ions(source: str, stamp: float) -> tuple[str, ...]:
    """The residues of a structure that are one atom, but for waters: its ions."""

    atoms: dict[tuple[str, int, str], list[_Atom]] = {}
    for atom in _atoms(source, stamp):
        if atom.het and atom.element.upper() != "H" and atom.resn not in {"HOH", "WAT"}:
            atoms.setdefault((atom.chain, atom.resi, atom.resn), []).append(atom)
    lone = {resn for (_, _, resn), held in atoms.items() if len(held) == 1}
    # A residue name that is one atom somewhere and more elsewhere is not an ion.
    more = {resn for (_, _, resn), held in atoms.items() if len(held) > 1}
    return tuple(sorted(lone - more))


@functools.lru_cache(maxsize=32)
def _render(ask: _Ask, aspect: float) -> bytes:
    figure = _drawn(ask)
    # mol-sketch's pen is sized for its own canvas (1920 wide): drawn at that
    # scale and shrunk into the box, the lines keep their weight against the molecule.
    long_side = 1200
    size = (
        (long_side, round(long_side / aspect))
        if aspect >= 1
        else (round(long_side * aspect), long_side)
    )
    if ask.site_labels and ask.site:
        figure.label_site(size)
    image = figure.render(size, scale=1.0)
    pixels = image.to_numpy()
    return _png(_without_paper(pixels, ask.paper))


@functools.lru_cache(maxsize=16)
def _settings(ask: _Ask) -> dict[str, object]:
    import molsketch as ms

    figure = _drawn(ask)

    def flat(value: dict, prefix: str) -> dict[str, object]:
        out: dict[str, object] = {}
        for key, item in value.items():
            if isinstance(item, dict):
                out |= flat(item, f"{prefix}{key}.")
            else:
                out[f"{prefix}{key}"] = item
        return out

    chains = _chains(figure, ())[0]
    selected = [(f"properties.{name}", text) for name, text in ask.show]
    if ask.site and ask.site != "ligand":
        selected.append(("properties.site", ask.site))
    atoms = _atoms(ask.source, ask.stamp) if selected else ()
    name = _called((figure._info().get("structure") or {}).get("name"))
    found = ((key, _selection_problem(text, atoms, name, chains)) for key, text in selected)
    return {
        "style": flat(figure.style, ""),
        "look": ask.look,
        "looks": ms.looks(),
        "palettes": ms.palettes(),
        "chains": chains,
        "selections": {key: said for key, said in found if said},
    }


# -- selections, checked as mol-sketch reads them --


@dataclass(frozen=True, slots=True)
class _Atom:
    element: str
    resn: str
    resi: int
    chain: str
    name: str
    het: bool
    ss: str
    entity: str
    subunit: str


@functools.lru_cache(maxsize=8)
def _atoms(source: str, stamp: float) -> tuple[_Atom, ...]:
    """The molecule's atoms, as a selection is tested on them."""

    from molsketch._engine import engine

    figure = _loaded(source, stamp)
    atoms = engine().call("sceneJson", figure._spec())["keyframes"][0]["atoms"]
    return tuple(
        _Atom(
            str(atom.get("el") or ""), str(atom.get("resn") or ""), int(atom.get("resi") or 0),
            str(atom.get("chain") or ""), str(atom.get("name") or ""), bool(atom.get("het")),
            str(atom.get("ss") or ""), str(atom.get("entity") or ""),
            str(atom.get("subunit") or ""),
        )
        for atom in atoms.values()
    )


_NUCLEIC = frozenset({
    "A", "C", "G", "U", "I", "DA", "DC", "DG", "DT", "DI", "N", "PSU", "5MC", "7MG", "OMG", "OMC",
    "1MA", "2MG", "M2G", "4SU", "H2U", "5MU", "YG", "UR3", "MA6", "6MZ", "A2M", "CM0", "G7M", "QUO",
})
_BACKBONE = frozenset({"N", "CA", "C", "O", "OXT"})
_LISTED = {
    "chain": "chain", "c.": "chain", "resn": "resn", "r.": "resn", "name": "name", "n.": "name",
    "elem": "element", "e.": "element", "ss": "ss", "subunit": "subunit",
}


class _BadSelection(ValueError):
    """A selection mol-sketch would read as nothing: a word it does not know, a number that
    is not one."""


def _selection(text: str):
    """A mol-sketch selection (``resi 57+102``, ``chain A and polymer``) as a test of one
    atom, read as mol-sketch reads it -- or _BadSelection, where it would quietly select
    nothing."""

    tokens = re.findall(r"\(|\)|[^\s()]+", text.strip())
    place = 0

    def peek() -> str | None:
        return tokens[place] if place < len(tokens) else None

    def take() -> str | None:
        nonlocal place
        place += 1
        return tokens[place - 1] if place - 1 < len(tokens) else None

    def listed(word: str) -> list[str]:
        token = take()
        if token is None:
            example = {"resi": "57", "i.": "57", "resn": "SER", "r.": "SER", "name": "CA",
                       "n.": "CA", "elem": "C", "e.": "C", "ss": "H", "entity": "1"}.get(word, "A")
            raise _BadSelection(f"“{word}” needs what to select after it, as in {word} {example}.")
        return token.split("+")

    def factor():
        token = take()
        if token is None:
            return lambda atom: False
        word = token.lower()
        if word == "(":
            test = expression()
            if peek() == ")":
                take()
            return test
        if word in {"not", "!"}:
            inner = factor()
            return lambda atom: not inner(atom)
        simple = {
            "all": lambda atom: True, "*": lambda atom: True, "none": lambda atom: False,
            "hetatm": lambda atom: atom.het, "het": lambda atom: atom.het,
            "polymer": lambda atom: not atom.het, "poly": lambda atom: not atom.het,
            "backbone": lambda atom: atom.name in _BACKBONE,
            "bb": lambda atom: atom.name in _BACKBONE,
            "sidechain": lambda atom: not atom.het and atom.name not in _BACKBONE,
            "nucleic": lambda atom: atom.resn in _NUCLEIC,
            "protein": lambda atom: not atom.het and atom.resn not in _NUCLEIC,
            "water": lambda atom: atom.resn in {"HOH", "WAT"},
            "hydrogens": lambda atom: atom.element == "H",
        }
        aliases = {"sc": "sidechain", "na": "nucleic", "prot": "protein", "solvent": "water",
                   "hydro": "hydrogens", "h.": "hydrogens"}
        word = aliases.get(word, word)
        if word in simple:
            return simple[word]
        if word in _LISTED:
            wanted = {value.upper() for value in listed(word)}
            field = _LISTED[word]
            return lambda atom: getattr(atom, field).upper() in wanted
        if word == "entity":
            entities = set(listed(word))
            return lambda atom: atom.entity in entities
        if word in {"resi", "i."}:
            ranges = []
            for value in listed(word):
                match = re.fullmatch(r"(-?\d+)(?:-(-?\d+))?", value)
                if not match:
                    raise _BadSelection(
                        f"“{value}” isn't a residue number. Write resi 57+102, or resi 50-60."
                    )
                ranges.append((int(match[1]), int(match[2] or match[1])))
            return lambda atom: any(low <= atom.resi <= high for low, high in ranges)
        raise _BadSelection(
            f"“{token}” isn't a word selections use, such as chain, resi, resn or polymer."
        )

    def term():
        test = factor()
        while (peek() or "").lower() in {"and", "&"}:
            take()
            left, right = test, factor()
            test = lambda atom, left=left, right=right: left(atom) and right(atom)  # noqa: E731
        return test

    def expression():
        test = term()
        while (peek() or "").lower() in {"or", "|"}:
            take()
            left, right = test, term()
            test = lambda atom, left=left, right=right: left(atom) or right(atom)  # noqa: E731
        return test

    return expression()


def _selection_problem(text: str, atoms: tuple[_Atom, ...], name: str, chains: list[str]) -> str:
    """Why ``text`` selects nothing of the molecule, in a sentence -- or nothing."""

    if not text.strip():
        return ""
    try:
        test = _selection(text)
    except _BadSelection as error:
        return str(error)
    if any(test(atom) for atom in atoms):
        return ""
    said = f"Selects nothing in {name}."
    words = {token.lower() for token in re.findall(r"[^\s()+]+", text)}
    if words & {"chain", "c."} and chains:
        said += f" Its chains are {', '.join(chains)}."
    numbers = [atom.resi for atom in atoms if not atom.het]
    if words & {"resi", "i."} and numbers:
        said += f" Its residues are numbered {min(numbers)} to {max(numbers)}."
    return said


class _NoSuchChain(ValueError):
    """A colour for a chain the structure does not have (it would colour nothing)."""

    def __init__(self, message: str, hint: str) -> None:
        super().__init__(message)
        self.hint = hint


_RESIDUE = re.compile(r"[A-Za-z]{1,3}-?\d+[A-Za-z]?(\.\w+)?")


def _chains(figure, colours: tuple[tuple[str, str], ...]) -> tuple[list[str], list[str]]:
    """The chains the molecule has, and the groups of ``colours`` that name a chain it does
    not (a residue, an entity or a chain's residue is not checked here)."""

    structure = figure._info().get("structure") or {}
    chains = [str(chain) for chain in structure.get("chains") or ()]
    if not chains:
        return chains, []
    missing = [
        group for group, _ in colours
        if not (":" in group or _RESIDUE.fullmatch(group) or group in chains)
    ]
    return chains, missing


def _check_chains(figure, colours: tuple[tuple[str, str], ...]) -> None:
    """Say a colour given to a chain the structure does not have -- mol-sketch would
    quietly colour nothing -- naming the chains it has."""

    chains, missing = _chains(figure, colours)
    for group in missing[:1]:
        name = _called((figure._info().get("structure") or {}).get("name"))
        raise _NoSuchChain(
            f'"{group}" names no chain of {name}, so its colour would show nowhere.',
            f"Its chains are {', '.join(chains)} "
            "(the author's chain names, as the file gives them).",
        )


def _theme_look(style: LayoutStyle, palette: Palette) -> str:
    if style.sketch is not None:
        return "watercolour"
    if _lightness(palette.get("canvas", "#ffffff")) < 0.4:
        return "dark-paper"
    return "engraved-colour"


def _lightness(colour: str) -> float:
    text = colour.lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    try:
        r, g, b = (int(text[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return 1.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def structure_view(node: NodeSpec, style: LayoutStyle, palette: Palette) -> dict[str, object]:
    """What the studio turns while a structure is dragged round: each chain's trace (its
    alpha carbons, or P for nucleic acids) in mol-sketch's own frame -- its scene's, where
    the structure already lies in its base orientation -- centred, and the turn it is drawn
    at now (``yaw``, ``pitch``, ``roll``). Turned as mol-sketch turns it (about y by yaw,
    then x by pitch, then z by roll; y up), the trace lies as the molecule will be drawn."""

    source = node.property("source")
    if not isinstance(source, str) or not source.strip():
        raise _fail(node, "source", "A structure needs a file or a PDB ID (source:).")
    look = str(node.property("look") or _theme_look(style, palette)).strip().lower()
    if look not in LOOKS:
        raise _fail(node, "look", f'look "{look}" is not a mol-sketch look.', hint=", ".join(LOOKS))
    path = Path(source).expanduser()
    if path.exists() and outside(path):
        raise _fail(node, "source", "The structure file is outside the folder.")
    view = tuple(
        (name, float(value))  # type: ignore[arg-type]
        for name in ("yaw", "pitch", "roll")
        if (value := node.property(name)) is not None
    )
    stamp = path.stat().st_mtime if path.exists() else 0.0
    return _one_at_a_time(_view, str(path) if path.exists() else source.strip(), stamp, look, view)


@functools.lru_cache(maxsize=16)
def _view(
    source: str, stamp: float, look: str, view: tuple[tuple[str, float], ...]
) -> dict[str, object]:
    import molsketch as ms
    from molsketch._engine import engine

    del stamp  # part of the cache key: an edited file is read again
    figure = ms.load(source) if Path(source).exists() else ms.fetch(source)
    figure = figure.look(look)
    if view:
        figure.view(**dict(view))
    spec = figure._spec()
    camera = engine().call("engineConfig", spec)["camera"]
    # The scene's atoms are where the camera's base orientation has put them already.
    atoms = engine().call("sceneJson", spec)["keyframes"][0]["atoms"]
    chains: dict[str, list[tuple[int, list[float]]]] = {}
    for atom in atoms.values():
        if atom.get("het") or atom.get("name") not in {"CA", "P"}:
            continue
        chains.setdefault(str(atom.get("chain")), []).append(
            (int(atom.get("resi", 0)), atom["pos"])
        )
    points = [pos for trace in chains.values() for _, pos in trace]
    if not points:
        return {"chains": [], "camera": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}}
    low = [min(p[k] for p in points) for k in range(3)]
    high = [max(p[k] for p in points) for k in range(3)]
    centre = [(low[k] + high[k]) / 2.0 for k in range(3)]
    step = max(1, len(points) // 900)
    traces = [
        [
            [round(pos[k] - centre[k], 2) for k in range(3)]
            for _, pos in sorted(trace, key=lambda item: item[0])[::step]
        ]
        for trace in chains.values()
    ]
    return {
        "chains": traces,
        "camera": {name: float(camera.get(name) or 0.0) for name in ("yaw", "pitch", "roll")},
    }


def _without_paper(pixels, paper: str):
    """``pixels`` (RGBA) with the paper colour taken out, as GIMP's colour to alpha does:
    each pixel keeps the least opacity that, laid over the paper, gives it back."""

    import numpy as np

    text = paper.lstrip("#")
    ground = np.array([int(text[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255.0
    # A channel's share of opacity depends on its value alone: looked up from a table of
    # its 256, and in single precision, not worked out pixel by pixel in double -- ten
    # times as fast on a molecule's picture (a second and more) and the same to the eye.
    values = np.arange(256, dtype=np.float32) / 255.0
    alpha = np.zeros(pixels.shape[:2], dtype=np.float32)
    for channel, level in enumerate(ground):
        lighter = (values - level) / max(1.0 - level, 1e-6)
        darker = (level - values) / max(level, 1e-6)
        table = np.where(values > level, lighter, np.where(values < level, darker, 0.0))
        np.maximum(alpha, table.astype(np.float32)[pixels[..., channel]], out=alpha)
    np.clip(alpha, 0.0, 1.0, out=alpha)
    restored = pixels[..., :3].astype(np.float32) * np.float32(1.0 / 255.0)
    restored -= ground
    restored /= np.maximum(alpha, 1e-6)[..., None]
    restored += ground
    np.clip(restored, 0.0, 1.0, out=restored)
    alpha *= pixels[..., 3].astype(np.float32) * np.float32(1.0 / 255.0)
    out = np.empty(pixels.shape, dtype=np.uint8)
    out[..., :3] = np.rint(restored * 255.0)
    out[..., 3] = np.rint(alpha * 255.0)
    return out


def _png(pixels) -> bytes:
    """An RGBA array as PNG bytes."""

    height, width = pixels.shape[:2]
    rows = b"".join(b"\x00" + pixels[row].tobytes() for row in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    )
