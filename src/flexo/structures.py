"""A molecule drawn by hand: a structure rendered by mol-sketch, in the figure's colours.

A ``structure`` component draws a PDB or mmCIF file (or a PDB ID, fetched) with
`mol-sketch <https://github.com/jamaliki/mol-sketch>`_ -- engraved ribbons,
watercolour, pen and ink -- as a panel of the figure:

- its **look** follows the theme unless one is named: watercolour in a sketched
  theme, dark paper on a dark page, engraved colour otherwise;
- it is drawn on the figure's own page colour, which is then taken out, so the
  molecule sits on whatever is behind it with no box round it;
- ``colors`` names a colour for a chain (``"A"``), a residue (``"SER195"``, a ligand
  ``"6V0401"``), a subunit, an entity or a selection (``"resi 10-24"``, ``"not polymer"``)
  -- a hex colour, or one of the figure's **tones**, so the kinase domain on the protein
  map and the chain in the structure are one colour -- a later row over an earlier one
  where they overlap (see ``flexo.structure_colours``);
- ``ss_from`` colours it by another file's secondary structure, in the look's helix,
  strand and loop colours, while it is drawn with its own: frames of a diffusion run
  coloured by the structure they end as;
- ``yaw``, ``pitch``, ``roll``, and ``zoom`` turn and frame it, and ``pan_x`` and
  ``pan_y`` shift it (fractions of its box); ``frame`` names a frame it shares with other
  structures of the figure, all drawn with one camera, at one scale, about one centre -- a
  diffusion trajectory, a motif held fixed -- as the first of them is turned and framed
  (``flexo.structure_frames``); ``cartoon``, ``sticks``, and ``surface``
  say what to draw (mol-sketch selections), and ``site`` marks an active site -- a
  selection, or ``ligand`` for the largest ligand and what lies within ``site_within``
  Å of it -- its residues labelled with ``site_labels``;
- ``palette`` names one of mol-sketch's group palettes, ``density`` draws a density
  map with it (``auto``: the map the entry was built into; an EMDB ID; or a map file),
  and ``style`` sets any field of mol-sketch's style over the look, nested as
  mol-sketch writes them -- ``style: {fill: ink colour, line: {width: 2}}`` (see
  ``flexo.structure_style``);
- its name is set over the molecule, or under it with ``title_side: bottom``; inline
  markup gives a word of it a slant: ``[t]{italic} = 100``.

mol-sketch is an optional dependency (``pip install "flexo[molecules]"``, or the
``python`` folder of a mol-sketch clone). The picture is drawn at print
resolution and embedded, so the editable SVG, the PDF, and the slides carry it.

In the **flat** look (PyMOL's flat, outlined figures) the molecule is shapes instead:
mol-sketch's SVG nested in the figure's, so it stays sharp at any size and the PDF
carries it as vectors. It is in the look's own colours -- coral helices, amber strands,
near-white loops, teal hydrogen bonds -- or, with ``scheme: figure``, painted in the
figure's own roles -- helices in the accent's fill, strands in the warm fill, loops in
the neutral fill, a chain or a tone in that tone's fill, outlines in ink -- and every
shape records the role it was painted in (and, for a ribbon's darker side, how far
toward the ink), so ``flexo retheme`` recolours the molecule with the rest of the
figure.

A **scene** -- a mol-sketch ``.json`` of steps, such as a reaction drawn with its
orbitals, lone pairs, curly arrows and the distances and angles it is posed at -- is drawn
as a structure too: at the end of the step ``step`` names (1, its first, by default),
where its arrows are drawn in full.
"""

from __future__ import annotations

import atexit
import difflib
import functools
import math
import re
import struct
import threading
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, replace
from pathlib import Path

from flexo.confine import outside
from flexo.diagnostics import Diagnostic, FlexoError, Severity
from flexo.drawn import Picture, Shape, Words, path, units
from flexo.geometry import Side, Size
from flexo.ir.measured import TextMetrics
from flexo.ir.semantic import NodeSpec, PortSpec, Record, Settings, TextRun
from flexo.structure_style import THE_FIGURES
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
    "textbook",
    "flat",
)

SCHEMES = ("look", "figure")
"""Whose colours a flat structure is in: its look's own (mol-sketch's Flat: coral helices,
amber strands, near-white loops, teal hydrogen bonds), or the figure's tones."""

VECTOR_LOOKS = frozenset({"flat"})
"""Looks whose molecule is nested as shapes, not embedded as a picture. (Its drawing is
checked all the same: anything a picture holds better is drawn as one; see ``_PICTURED``.)"""


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


TITLE_SIDES = ("top", "bottom")
"""Where a structure's name is set: over its molecule (``title_side: top``, as it is unless
written) or under it (``bottom``)."""


def structure_title_side(node: NodeSpec) -> str:
    """Where the structure's name is set (``TITLE_SIDES``): over it, unless it says under."""

    written = str(node.property("title_side") or TITLE_SIDES[0]).strip().lower()
    return written if written in TITLE_SIDES else TITLE_SIDES[0]


def title_side_problem(node: NodeSpec) -> Diagnostic | None:
    """A title side written that is neither, as a warning: the name is set over it."""

    written = str(node.property("title_side") or TITLE_SIDES[0]).strip().lower()
    if node.kind != "structure" or written in TITLE_SIDES:
        return None
    return Diagnostic(
        "structure.title-side",
        f"A structure\u2019s name can\u2019t stand at “{written}”: it is set over the molecule.",
        Severity.WARNING, entity_id=node.id,
        hint="Its properties.title_side is top (over the molecule) or bottom (under it).",
    )


def structure_drawing(node: NodeSpec, style: LayoutStyle) -> Picture:
    """The panel: the molecule's box, under the component's name if it has one -- or the name
    under the box, ``title_side: bottom``. A molecule that can't be had (a PDB entry not
    downloaded, a file that does not read) is a dashed panel the same size saying why, so the
    rest of the figure is drawn all the same."""

    measures = units(style)
    u = measures.u
    width = float(node.property("width") or 20.0 * u)  # type: ignore[arg-type]
    height = float(node.property("height") or 15.0 * u)  # type: ignore[arg-type]
    words = []
    top = 0.0
    named = 0.0
    if node.label:
        # A long name is set on as many lines as the panel is wide, not over its edges.
        title = structure_title(node, style)
        named = title.height + 0.3 * u
        below = structure_title_side(node) == "bottom"
        words.append(
            Words(
                f"{node.id}.label",
                node.label,
                title,
                width / 2.0,
                height + 0.3 * u + title.baseline if below else title.baseline,
                weight=style.typography.title_weight,
            )
        )
        top = 0.0 if below else named
    size = Size(width, named + height)
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
    from flexo.structure_colours import Unseen, check

    try:
        _one_at_a_time(check, figure, ask)
    except Unseen as error:
        return _Problem(error.code, error.title or name, _sentence(str(error)), error.hint,
                        drawn=True)
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

_JOINS = _PLAIN | frozenset(
    {"ABOUT", "AFTER", "AGAINST", "AMONG", "BEFORE", "BETWEEN", "BOUND", "COMPLEXED", "DURING",
     "ITS", "OVER", "THAT", "THEIR", "THROUGH", "UNDER", "UPON", "VERSUS", "VIA", "VS", "WHICH",
     "WITHIN", "WITHOUT"}
)
"""Words a phrase of a name begins with (or that leave it hanging): a name cut short ends
before the phrase the cut fell in, never on one of these."""

ACRONYMS = frozenset(
    {"DNA", "RNA", "MRNA", "TRNA", "RRNA", "SSDNA", "DSDNA", "HIV", "SIV", "GFP", "YFP", "CFP",
     "RFP", "ATP", "ADP", "AMP", "GTP", "GDP", "NAD", "NADH", "NADP", "NADPH", "FAD", "FMN",
     "MHC", "HLA", "TCR", "BCR", "IGG", "IGE", "IGM", "TNF", "EGF", "VEGF", "FGF", "PDGF", "SARS",
     "COV", "MERS", "CRISPR", "PCR", "LDL", "HDL", "ABC", "PDZ", "SUMO", "HSP", "GPCR", "ERK",
     "MAP", "JAK", "STAT", "CAP", "TATA", "EGFR", "HER", "PKA", "PKC", "CDK", "ATPASE", "TBP"}
)
"""Names in a title in capitals that stay in capitals: acronyms, not words (``LAC`` is a word)."""

NAMED = 32
"""How long (characters) a structure's name from its file may be before it is cut short."""


def is_scene(path: Path) -> bool:
    """Whether a ``.json`` file is a mol-sketch scene (it has steps: ``keyframes``), not a
    figure, a deck or a theme written in JSON."""

    if path.suffix.lower() != ".json":
        return False
    try:
        with path.open(encoding="utf-8", errors="replace") as file:
            return '"keyframes"' in file.read(4_000_000)
    except OSError:
        return False


def _scene_name(path: Path) -> str | None:
    """A scene's own name for what it draws ("Proton transfer"), if it gives one."""

    import json

    try:
        name = json.loads(path.read_text(encoding="utf-8")).get("name")
    except (OSError, ValueError, AttributeError):
        return None
    return name.strip() if isinstance(name, str) and name.strip() else None


def scene_steps(path: Path) -> list[str]:
    """A scene's steps, by the names it gives them ("π* attack: precursor"; "" for one it
    names not): none for a file that is not a scene, or does not read."""

    import json

    if not is_scene(path):
        return []
    try:
        steps = json.loads(path.read_text(encoding="utf-8")).get("keyframes") or []
    except (OSError, ValueError, AttributeError):
        return []
    named = (step.get("name") if isinstance(step, dict) else None for step in steps)
    return [name.strip() if isinstance(name, str) else "" for name in named]


def structure_caption(path: Path) -> str | None:
    """What a structure file says it holds, as a person would write it, with its PDB ID:
    ``E2 DNA-binding domain (1A7G)`` for a file titled THE CRYSTAL STRUCTURE OF THE E2
    DNA-BINDING DOMAIN FROM HUMAN PAPILLOMAVIRUS AT 2.4 ANGSTROMS. Its title, without how
    it was solved and from what, at what resolution -- else the first protein it names
    (never a bare DNA or RNA). A scene, the name it gives itself. None for a file that names
    nothing."""

    if is_scene(path):
        return _scene_name(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:400_000]
    except OSError:
        return None
    titles: list[str] = []
    molecules: list[str] = []
    entry = None
    if path.suffix.lower() in (".cif", ".mmcif"):
        def value(key: str) -> str:
            found = re.search(rf"^{re.escape(key)}\s+(.+?)\s*$", text, re.MULTILINE)
            said = found.group(1).strip().strip("'\"").strip() if found else ""
            return "" if said in ("?", ".") else said

        titles += [value("_struct.title")]
        molecules += [part.strip() for part in value("_struct.pdbx_descriptor").split(",")]
        found = re.search(r"^_entry\.id\s+(\S+)", text, re.MULTILINE)
        entry = found.group(1) if found else None
    else:
        title = " ".join(
            line[10:].strip() for line in text.splitlines() if line.startswith("TITLE ")
        )
        if title:
            titles.append(re.sub(r"\s+", " ", title))
        compound = re.findall(r"^COMPND.{4}.*?MOLECULE:\s*([^;\n]+)", text, re.MULTILINE)
        molecules += [found.strip() for found in compound]
        found = re.match(r"HEADER.{56}([0-9][A-Za-z0-9]{3})", text)
        entry = found.group(1) if found else None
    names = [_plain_title(title) for title in titles] + [
        molecule for molecule in molecules if not re.fullmatch(r"(?i)(5'-)?[DR]NA\b.*", molecule)
    ]
    name = next((name for name in names if name), None)
    stem = re.sub(r"\.(pdb|cif|mmcif|ent)$", "", path.name, flags=re.IGNORECASE)
    if entry is None and re.fullmatch(r"[0-9][A-Za-z0-9]{3}", stem):
        entry = stem
    if not name:
        return None
    # Cut short between words -- and before the phrase the cut fell in ("Acyl-enzyme
    # intermediate", not "Acyl-enzyme intermediate during").
    if len(name) > NAMED:
        words = name[:NAMED + 1].split()[:-1] or [name[:NAMED]]
        joins = [
            at for at, word in enumerate(words) if at > 0 and word.upper().strip(",;") in _JOINS
        ]
        if joins:
            words = words[: joins[-1]]
        while len(words) > 1 and words[-1].upper().strip(",;") in _JOINS:
            words.pop()
        name = " ".join(words).rstrip(",;")
    if name.isupper():
        # In sentence case: a word in lower case, an acronym (DNA, HIV), a name with a digit
        # (E2, P53) or a Roman numeral (II) as written.
        def readable(piece: str) -> str:
            letters = re.sub(r"[^A-Z]", "", piece)
            kept = letters in ACRONYMS or re.fullmatch(r"[IVX]{2,4}", letters) is not None
            return piece if kept or any(ch.isdigit() for ch in piece) else piece.lower()

        words = ("-".join(readable(piece) for piece in word.split("-")) for word in name.split())
        name = " ".join(words)
        name = name[:1].upper() + name[1:]
    return f"{name} ({entry.upper()})" if entry else name


def _plain_title(title: str) -> str:
    """A structure's title without how it was solved, what it was taken from or at what
    resolution: THE CRYSTAL STRUCTURE OF THE E2 DNA-BINDING DOMAIN FROM HUMAN
    PAPILLOMAVIRUS AT 2.4 ANGSTROMS is E2 DNA-BINDING DOMAIN."""

    title = re.sub(
        r"(?i)^(the\s+)?((crystal|solution|nmr|x-ray|cryo-?em|refined|high[- ]resolution)\s+)*"
        r"(structures?|model)\s+(of|for)\s+(the\s+|a\s+|an\s+)?",
        "",
        title.strip(),
    )
    title = re.sub(r"(?i)\s+(at|to)\s+[0-9.]+\s*(a|angstroms?|\u00c5)\b.*$", "", title)
    source = r"(human|mouse|yeast|bovine|bacteri|escherichia|e\.)"
    title = re.sub(rf"(?i)\s+(from|in|of)\s+{source}.*$", "", title)
    return title.strip(" ,.;")


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


def structure_svg(
    node: NodeSpec, style: LayoutStyle, palette: Palette, width: float, height: float
) -> str | None:
    """The molecule as shapes: mol-sketch's drawing at ``width`` by ``height`` points, as
    an ``<svg>`` to nest in the figure's, every shape painted in a colour of the figure's
    marked with the role it was painted by -- or None, for a look drawn as a picture
    (``VECTOR_LOOKS``), a drawing a picture holds better, or one mol-sketch failed to draw
    (``structure_png`` then draws it, or says why)."""

    ask = _ask(node, style, palette)
    if ask.look not in VECTOR_LOOKS or _failed.get(_failing(ask)):
        return None
    try:
        markup = _one_at_a_time(_render_svg, ask, width / height)
    except Exception:
        return None  # structure_png meets the same failure, and says it
    return None if markup is None else _own_ids(markup, f"{node.id}.molecule")


_PICTURED = ("<image", "mix-blend-mode", "<filter", "<pattern", "<mask", "Gradient", "<clipPath")
"""What a drawing as shapes would hold that the figure's other readers (the PDF, the
slides) only approximate -- pictures, blends, blurs, fills of a picture, clips other than
a rectangle: a drawing with any of them is embedded as a picture instead."""


@functools.lru_cache(maxsize=32)
def _render_svg(ask: _Ask, aspect: float) -> str | None:
    figure = _drawn(ask)
    long_side = 1200  # as _render draws it: the same pen weight against the molecule
    size = (
        (long_side, round(long_side / aspect))
        if aspect >= 1
        else (round(long_side * aspect), long_side)
    )
    if ask.site_labels and ask.site:
        figure.label_site(size)
    # No paper laid down: the figure's page is under it (its colour is still the paper's).
    figure.set(**{"paper.transparent": True})
    text = figure.svg(size, scale=1.0)
    if any(mark in text for mark in _PICTURED):
        return None
    shading = float(figure.style.get("shading") or 0.0)
    return _painted_by_role(text, ask, min(max(0.3 * shading, 0.0), 1.0))


def _painted_by_role(text: str, ask: _Ask, shade: float) -> str:
    """mol-sketch's SVG with every fill and line in a colour the figure handed it marked
    with that colour's role -- and the one darker shade a flat ribbon takes of its colour
    on its far side, with the role and how far toward the ink -- so ``flexo retheme``
    paints it again."""

    from flexo.colour import srgb_mix

    ink = _hex(dict(ask.paints).get("ink", "#000000"))
    found: dict[str, tuple[str, float]] = {}
    for role, colour in ask.paints:
        found.setdefault(_hex(colour), (role, 0.0))
    for role, colour in ask.paints:
        if shade > 0 and role not in {"ink", "canvas"}:
            found.setdefault(srgb_mix(_hex(colour), ink, shade), (role, shade))
    root = ET.fromstring(text)
    for item in root.iter():
        for part in ("fill", "stroke"):
            value = item.get(part)
            if value is None or not value.startswith("#"):
                continue
            hit = found.get(_hex(value))
            if hit is None:
                continue
            role, amount = hit
            item.set(f"data-flexo-{part}", role)
            if amount:
                item.set(f"data-flexo-{part}-shade", f"{amount:.4g}")
    return ET.tostring(root, encoding="unicode")


def _hex(colour: str) -> str:
    """A colour as ``#rrggbb`` in lower case, as mol-sketch writes it."""

    text = colour.strip().lower()
    if len(text) == 4 and text.startswith("#"):
        text = "#" + "".join(digit * 2 for digit in text[1:])
    return text


def _own_ids(markup: str, prefix: str) -> str:
    """mol-sketch's SVG with its ids (clip paths and the like, numbered from 1 in every
    drawing) made the molecule's own, so two molecules in a figure never share one."""

    if ' id="' not in markup:
        return markup
    root = ET.fromstring(markup)
    renamed = {}
    for item in root.iter():
        identifier = item.get("id")
        if identifier:
            renamed[identifier] = f"{prefix}.{identifier}"
            item.set("id", renamed[identifier])
    for item in root.iter():
        for name, value in item.attrib.items():
            if "#" in value:
                item.set(name, re.sub(r"(url\(#|^#)([^)\s]+)",
                                      lambda m: m.group(1) + renamed.get(m.group(2), m.group(2)),
                                      value))
    return ET.tostring(root, encoding="unicode")


_failed: dict[tuple, str] = {}
"""Why mol-sketch failed to draw a structure, by what it was drawn from (its colours aside)."""


def _failing(ask: _Ask) -> tuple:
    """What a structure is drawn from, but its colours and look: one failure said whatever
    the page it is drawn on."""

    return (ask.source, ask.stamp, ask.view, ask.show, ask.site, ask.group_palette, ask.style,
            ask.pan, ask.density, ask.site_within, ask.site_labels, ask.solvent, ask.noise,
            ask.fixed, ask.seed)


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
    # A scene's steps, by name, even when the one it asks for is not among them.
    source = node.property("source")
    steps = scene_steps(Path(source).expanduser()) if isinstance(source, str) else []
    if problem is not None and not problem.drawn:
        return {"style": {}, "looks": list(LOOKS), "palettes": {}, "chains": [], "steps": steps,
                **said}
    ask = _ask(node, style, palette)
    try:
        return {**_one_at_a_time(_settings, ask), "steps": steps, **said}
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
    paints: tuple[tuple[str, str], ...] = ()
    """Each colour handed to mol-sketch by a role of the figure's, as (role, colour), the
    roles that matter most first: what a molecule drawn as shapes is painted by."""
    step: int = 1
    """Which of a scene's steps is drawn (1, its first), once its arrows are in: ``_frame``."""
    ss_from: str | None = None
    """The file (or PDB entry) whose secondary structure it is coloured by, and when it was
    saved: ``flexo.structure_colours``."""
    ss_stamp: float = 0.0
    noise: float = 0.0
    """How far along its way from the file to a random coil it is drawn (``flexo.structure_noise``):
    0, the file itself."""
    fixed: str = ""
    """What of it is held where the file has it, noised: a selection."""
    seed: int = 0
    """Which run of noise it is a moment of."""


def _ask(node: NodeSpec, style: LayoutStyle, palette: Palette) -> _Ask:
    source = node.property("source")
    if not isinstance(source, str) or not source.strip():
        raise _fail(node, "source", "A structure needs a file or a PDB ID (source:).")
    look = str(node.property("look") or _theme_look(style, palette)).strip().lower()
    if look not in LOOKS:
        raise _fail(node, "look", f'look "{look}" is not a mol-sketch look.', hint=", ".join(LOOKS))
    paper = palette.get("canvas", "#ffffff")
    ink = palette.get("ink", "#000000")
    # A flat molecule is filled with its tones, as the figure's shapes are; the other looks
    # draw in lines, and take a tone's line colour. Flat, it is in the look's own colours
    # (mol-sketch's: coral helices, amber strands) unless it asks for the figure's.
    scheme = str(node.property("scheme") or "look").strip().lower()
    if scheme not in SCHEMES:
        said = f'scheme "{scheme}" is neither of a structure\'s.'
        raise _fail(node, "scheme", said, hint=", ".join(SCHEMES))
    flat = look == "flat"
    figured = flat and scheme == "figure"
    part = "fill" if flat else "stroke"
    paints = [("ink", ink)]  # outlines first: a tone of the same colour is not what they are
    colours = []
    for group, colour in _colours(node):
        if not colour.startswith("#"):
            index = palette.tone_index(colour)
            if index is None:
                raise _fail(
                    node, "colors", f'"{colour}" is neither a colour nor a tone of the figure.'
                )
            colour = palette.get(f"tone-{index}-{part}")
            paints.append((f"tone-{index}-{part}", colour))
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
    roles = [("ink", ink)]
    if figured:
        # Flat in the figure's colours, the whole molecule is: helices in the accent's fill,
        # strands in the warm one, loops in the neutral fill (a protein map's tones win,
        # below), words, charges, a mechanism's arrows and its measures in ink, hydrogen
        # bonds in the accent's line -- and a scene's orbitals, filled in the warm fill and
        # empty in the accent's, the window they are measured against in the neutral fill.
        for key, role in (("helix", "accent-fill"), ("sheet", "warm-fill"), ("loop", "block-fill"),
                          ("label", "ink"), ("charge", "ink"), ("arrow", "ink"),
                          ("hbond", "accent-stroke"), ("filled", "warm-fill"),
                          ("empty", "accent-fill"), ("measure", "ink"), ("window", "block-fill")):
            roles.append((key, palette.get(role)))
    for tone, key in (("helix", "helix"), ("strand", "sheet")):
        index = palette.tone_index(tone)
        if index is not None:
            roles.append((key, palette.get(f"tone-{index}-{part}")))
            paints.append((f"tone-{index}-{part}", palette.get(f"tone-{index}-{part}")))
    if figured:
        paints += [(role, palette.get(role)) for role in ("accent-fill", "warm-fill", "block-fill",
                                                          "accent-stroke")]
    paints.append(("canvas", paper))  # last: a fill as white as the page is still a fill
    path = Path(source).expanduser()
    if path.exists() and outside(path):
        raise _fail(node, "source", "The structure file is outside the folder.")
    density = node.property("density")
    if density is not None:
        density = str(density).strip()
        if Path(density).expanduser().exists() and outside(Path(density).expanduser()):
            raise _fail(node, "density", "The map file is outside the folder.")
    ss_from = str(node.property("ss_from") or "").strip() or None
    ss_path = Path(ss_from).expanduser() if ss_from else None
    if ss_path is not None and ss_path.exists():
        if outside(ss_path):
            raise _fail(node, "ss_from", "The file its secondary structure is from is outside "
                        "the folder.")
        ss_from = str(ss_path)
    pan = (node.property("pan_x"), node.property("pan_y"))
    within = node.property("site_within")
    group_palette = node.property("palette")
    step = node.property("step")
    if step is not None and (isinstance(step, bool) or not isinstance(step, int | float) or step < 1
                             or step != int(step)):
        raise _fail(node, "step", "A scene's step is a whole number, from 1 for its first.")
    noise, fixed, seed = _noise(node)
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
        tuple(paints),
        1 if step is None else int(step),
        ss_from,
        ss_path.stat().st_mtime if ss_path is not None and ss_path.exists() else 0.0,
        noise,
        fixed,
        seed,
    )


def _noise(node: NodeSpec) -> tuple[float, str, int]:
    """A structure's ``noise`` (0 to 1), ``fixed`` (a selection) and ``seed``, checked."""

    noise, fixed, seed = (node.property(name) for name in ("noise", "fixed", "seed"))
    if noise is not None and (isinstance(noise, bool) or not isinstance(noise, int | float)
                              or not 0 <= noise <= 1):
        raise _fail(node, "noise", "A structure's noise is a number from 0 (the file) to 1.",
                    hint="0.3 is t = 30 of a run of a hundred steps.")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int | float)
                             or seed != int(seed) or seed < 0):
        raise _fail(node, "seed", "A structure's seed is a whole number, from 0.")
    return (0.0 if noise is None else float(noise), str(fixed or "").strip(),
            0 if seed is None else int(seed))


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


def _loaded(source: str, stamp: float):
    """The molecule, read once (or fetched) and copied for each way it is drawn. A PDB ID a
    bundle keeps the entry of (``flexo.bundle``) is read from the bundle's: no network."""

    from flexo.bundle import kept_entry
    from flexo.confine import folder_root

    kept = None if Path(source).exists() else kept_entry(source, folder_root.get())
    if kept is not None:
        return _read_kept(str(kept), kept.stat().st_mtime_ns, source.strip().upper())
    return _read(source, stamp)


@functools.lru_cache(maxsize=8)
def _read(source: str, stamp: float):
    import molsketch as ms

    del stamp  # part of the cache key: an edited file is read again
    return ms.load(source) if Path(source).exists() else ms.fetch(source)


@functools.lru_cache(maxsize=8)
def _read_kept(path: str, stamp: int, pid: str):
    import molsketch as ms

    del stamp
    return ms.load(Path(path), name=pid)


def _forget_loaded() -> None:
    import sys

    _read.cache_clear()
    _read_kept.cache_clear()
    noise = sys.modules.get("flexo.structure_noise")
    if noise is not None:
        noise.forget()  # (its molecules were read into the engine let go, too)


_loaded.cache_clear = _forget_loaded  # type: ignore[attr-defined]


HOLD = 24
"""The frames a scene's step is held for where it does not say (mol-sketch's own default)."""


def _frame(figure, ask: _Ask) -> int | None:
    """The frame a scene (a mol-sketch ``.json`` of steps) is drawn at: the last drawing of
    its step's hold, where its arrows are drawn in full -- they grow over the end of the hold,
    and are not there at its start -- as mol-sketch draws a reaction's figure. None for a
    molecule read from its coordinates, whose frame is only which wobble its lines take."""

    if Path(ask.source).suffix.lower() != ".json":
        return None
    steps = figure.scene().get("keyframes") or []
    if ask.step > max(len(steps), 1):
        said = f"{len(steps)} step{'s' if len(steps) != 1 else ''}"
        raise _Unknown("step", f"This scene has {said}: step {ask.step} is not one of them.",
                       f"A step from 1 to {len(steps)}.")
    if not steps:
        return None
    start = figure.frames("keyframes")[ask.step - 1]
    hold = int(steps[ask.step - 1].get("hold") or HOLD)
    # (Drawn on twos: the last drawing of the hold is two frames before its end.)
    return start + max(hold - 2, 0)


@functools.lru_cache(maxsize=1)
def _fields() -> frozenset[str]:
    """Every field of mol-sketch's style, by dotted name."""

    import molsketch as ms

    def walk(value: dict, prefix: str) -> list[str]:
        names = []
        for key, item in value.items():
            names += walk(item, f"{prefix}{key}.") if isinstance(item, dict) else [f"{prefix}{key}"]
        return names

    return frozenset(walk(ms.default_style(), "")) | UNSET


UNSET = frozenset(
    f"palette.{key}" for key in ("filled", "empty", "window", "measure", "hbond")
)
"""Colours of mol-sketch's style that it leaves out until given, choosing them from the
paper, the ink and the hatching meanwhile: a scene's orbitals, its measures and their
windows, and hydrogen bonds."""


def _drawn(ask: _Ask):
    """A mol-sketch figure set up as ``ask`` says, ready to draw or to read."""

    import molsketch as ms

    from flexo.structure_colours import paint

    noised = _noised(ask)
    figure = (_loaded(ask.source, ask.stamp) if noised is None else noised.figure).copy()
    frame = _frame(figure, ask)
    if frame is not None:
        figure.frame(frame)
    figure = figure.look(ask.look)
    figure.set(palette={"paper": ask.paper, **dict(ask.roles)}, **THE_FIGURES)
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
    # Its colours, a later row over an earlier one -- but those that would show nowhere,
    # left out and said (structure_problem).
    paint(figure, ask)
    if ask.show:
        figure.show(**dict(ask.show))
    if "sticks" not in dict(ask.show):
        _solvent(figure, ask)
    if ask.view or ask.pan or noised is not None:
        view = dict(ask.view)
        if noised is not None:
            # (Seen as the file is: mol-sketch turns what it reads to its own axes.)
            view |= noised.view(*(view.get(name, 0.0) for name in ("yaw", "pitch", "roll")))
        figure.view(**view, **({"pan": ask.pan} if ask.pan else {}))
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


def _noised(ask: _Ask):
    """The molecule at its noise, read into mol-sketch (``flexo.structure_noise``) -- or
    None, drawn as the file has it."""

    if not ask.noise:
        return None
    from flexo import structure_noise

    try:
        fixed = structure_noise.fixed_residues(ask.source, ask.stamp, ask.fixed)
    except _BadSelection as error:
        raise _Unknown("fixed", str(error)) from None
    try:
        return structure_noise.drawn(_loaded(ask.source, ask.stamp), ask.noise, ask.seed, fixed)
    except ValueError as error:
        raise _Unknown("noise", str(error)) from None


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

    from flexo.structure_colours import said as colours_said

    chains = _chains(figure)
    selected = [(f"properties.{name}", text) for name, text in ask.show]
    if ask.site and ask.site != "ligand":
        selected.append(("properties.site", ask.site))
    if ask.fixed:
        selected.append(("properties.fixed", ask.fixed))
    atoms = _atoms(ask.source, ask.stamp) if selected else ()
    name = _called((figure._info().get("structure") or {}).get("name"))
    found = ((key, _selection_problem(text, atoms, name, chains)) for key, text in selected)
    style = flat(figure.style, "")
    # What each setting is without the structure's own: its look's, and the figure's
    # colours. (Its map and its site are left out: neither sets a field it offers.)
    inherited = (
        flat(_drawn(replace(ask, style=(), density=None, site=None)).style, "")
        if ask.style else style
    )
    return {
        "style": style,
        "inherited": inherited,
        "look": ask.look,
        "looks": ms.looks(),
        "palettes": ms.palettes(),
        "chains": chains,
        "selections": {key: said for key, said in found if said},
        # What each row of its colours colours, and the ligands a row may name.
        "colours": colours_said(figure, ask),
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
    group: str = ""
    """Its residue by mol-sketch's name, which it is coloured by: ``SER195.A``."""


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
            str(atom.get("subunit") or ""), str(atom.get("group") or ""),
        )
        for atom in atoms.values()
    )


_NUCLEIC = frozenset({
    "A", "C", "G", "U", "I", "DA", "DC", "DG", "DT", "DI", "N", "PSU", "5MC", "7MG", "OMG", "OMC",
    "1MA", "2MG", "M2G", "4SU", "H2U", "5MU", "YG", "UR3", "MA6", "6MZ", "A2M", "CM0", "G7M", "QUO",
})
_BACKBONE = frozenset({"N", "CA", "C", "O", "OXT"})
_LISTED = {
    "resn": "resn", "r.": "resn", "name": "name", "n.": "name",
    "elem": "element", "e.": "element", "ss": "ss", "subunit": "subunit",
}
"""What a selection's words match in any case: a residue's name, an atom's, an element. A
chain is matched as the file writes it, in its case (a ribosome's Le is not its LE), as
mol-sketch matches it."""


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
        if word in {"chain", "c."}:
            chains = set(listed(word))
            return lambda atom: atom.chain in chains
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

    # (None is nothing, as meant: what a structure draws none of is said so.)
    if not text.strip() or text.strip().lower() == "none":
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


def _chains(figure) -> list[str]:
    """The chains the molecule has, by the author's names, as the file gives them."""

    structure = figure._info().get("structure") or {}
    return [str(chain) for chain in structure.get("chains") or ()]


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
    """What the studio draws while a structure is dragged round, as it will be drawn: the
    turn it is at now (``yaw``, ``pitch``, ``roll``) and how mol-sketch frames it (``zoom``,
    ``pan_x``, ``pan_y``, its field of view), the points that framing is fitted to
    (``fit``, the outermost of what it draws, round their ``centre``), each chain's trace
    where its ribbon is drawn (its alpha carbons, or P for nucleic acids), and its atoms
    drawn as sticks -- an active site's flagged, drawn thicker -- with the bonds between
    them. All in mol-sketch's own frame, its scene's, where the structure already lies in
    its base orientation: turned as mol-sketch turns it (about the centre, y by yaw, then x
    by pitch, then z by roll; y up) and framed as it frames it, they lie where the molecule
    will be drawn -- a site zoomed into stays where it is in the box, not the whole
    protein fitted to it."""

    return _one_at_a_time(_view, _ask(node, style, palette))


_SIDES = 160
"""How many ways the outermost points of a framing are looked for: the box mol-sketch fits
round them, turned any way, is then within a hundredth of their reach of its own."""


@functools.lru_cache(maxsize=16)
def _view(ask: _Ask) -> dict[str, object]:
    import numpy as np
    from molsketch._engine import engine

    figure = _drawn(ask)
    spec = figure._spec()
    config = engine().call("engineConfig", spec)
    cfg, reps, camera = config["cfg"], config["reps"] or {}, config["camera"]
    rep, shown = cfg.get("rep") or {}, cfg.get("show") or {}
    keyframes = engine().call("sceneJson", spec)["keyframes"]
    # The scene's atoms are where the camera's base orientation has put them already.
    keyframe = keyframes[min(ask.step, len(keyframes)) - 1]
    atoms = [
        (
            key,
            _Atom(
                str(atom.get("el") or ""), str(atom.get("resn") or ""),
                int(atom.get("resi") or 0), str(atom.get("chain") or ""),
                str(atom.get("name") or ""), bool(atom.get("het")), str(atom.get("ss") or ""),
                str(atom.get("entity") or ""), str(atom.get("subunit") or ""),
            ),
            atom["pos"],
        )
        for key, atom in keyframe["atoms"].items()
    ]

    def test(text: object):
        text = str(text or "").strip()
        if not text:
            return None
        try:
            return _selection(text)
        except _BadSelection:
            return None

    sticks, cartoon, surface, site = (
        test(reps.get("sticks")), test(reps.get("cartoon")), test(reps.get("surface")),
        test(rep.get("siteSel")),
    )
    drawn = [test for test in (sticks, cartoon, surface, site) if test is not None]
    # What it is framed on: everything it draws (all of it, drawing nothing), as mol-sketch
    # fits its view.
    framed = [pos for _, atom, pos in atoms if any(each(atom) for each in drawn)] or [
        pos for *_, pos in atoms
    ]
    points = np.asarray(framed, dtype=float).reshape(-1, 3)
    centre = (points.min(axis=0) + points.max(axis=0)) / 2 if len(points) else np.zeros(3)
    turn = np.arange(_SIDES) + 0.5
    rise = 1 - 2 * turn / _SIDES
    around = np.pi * (1 + 5**0.5) * turn
    sides = np.concatenate([
        np.eye(3), -np.eye(3),
        np.stack([np.sqrt(1 - rise**2) * np.cos(around), np.sqrt(1 - rise**2) * np.sin(around),
                  rise], axis=1),
    ])
    outermost = sorted(set(np.argmax(points @ sides.T, axis=0).tolist())) if len(points) else []
    # A residue drawn as ribbon: its trace, and -- the side chain helper on -- its backbone
    # left out of the sticks (but its alpha carbon).
    ribbon = {
        (atom.chain, atom.resi) for _, atom, _ in atoms
        if cartoon is not None and cartoon(atom) and atom.name == "CA" and not atom.het
    }
    traces: dict[str, list[tuple[int, list[float]]]] = {}
    for _, atom, pos in atoms:
        if atom.name in {"CA", "P"} and not atom.het and cartoon is not None and cartoon(atom):
            traces.setdefault(atom.chain, []).append((atom.resi, pos))
    chains: list[list[list[float]]] = []
    for trace in traces.values():
        piece: list[list[float]] = []
        last: tuple[int, list[float]] | None = None
        for resi, pos in sorted(trace, key=lambda item: item[0]):
            # A gap in the chain (residues not in the file) is not drawn across.
            if last is not None and (resi - last[0] > 1 or math.dist(pos, last[1]) > 7.5):
                if len(piece) > 1:
                    chains.append(piece)
                piece = []
            piece.append([round(value, 2) for value in pos])
            last = (resi, pos)
        if len(piece) > 1:
            chains.append(piece)
    helper = bool(rep.get("sideChainHelper"))
    hydrogens = bool(shown.get("H"))
    held: dict[str, int] = {}
    stuck: list[list[object]] = []
    for key, atom, pos in atoms:
        in_site = site is not None and site(atom)
        if not (in_site or (sticks is not None and sticks(atom))):
            continue
        if atom.element.upper() == "H" and not hydrogens:
            continue
        if helper and (atom.chain, atom.resi) in ribbon and atom.name in {"N", "C", "O", "OXT"}:
            continue
        held[key] = len(stuck)
        stuck.append([*(round(value, 2) for value in pos), atom.element, int(in_site)])
    bonds = [
        [held[a], held[b]]
        for a, b, *order in keyframe.get("bonds") or ()
        if a in held and b in held and (not order or order[0] != 0)
    ]
    shown = {
        "camera": {
            "yaw": float(camera.get("yaw") or 0.0),
            "pitch": float(camera.get("pitch") or 0.0),
            "roll": float(camera.get("roll") or 0.0),
            "zoom": float(camera.get("zoom") or 1.0),
            "pan_x": float(camera.get("panX") or 0.0),
            "pan_y": float(camera.get("panY") or 0.0),
            "fov": float(camera.get("fov") or 0.0),
        },
        # As _render draws it: its long side 1200 pixels, a caption's band at the foot and a
        # step's at the head where it has them -- mol-sketch's framing keeps clear of them.
        "frame": {
            "long_side": 1200,
            "foot": 0.13 if shown.get("caption") else 0.0,
            "head": 0.05 if shown.get("stepLabel") else 0.0,
        },
        "centre": [round(float(value), 3) for value in centre],
        "fit": [[round(float(value), 2) for value in points[index]] for index in outermost],
        "chains": chains,
        "atoms": stuck,
        "bonds": bonds,
        "sticks": {
            "radius": float(rep.get("stickRadius") or 0.2),
            "site": float(rep.get("siteScale") or 1.9),
        },
    }
    # Noised, it is shown as the file is seen: in the file's turn, at its own yaw and pitch.
    noised = _noised(ask)
    return shown if noised is None else noised.as_seen(shown, dict(ask.view))


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
