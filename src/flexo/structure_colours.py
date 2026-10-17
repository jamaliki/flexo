"""A structure's colours: what each of its rows colours, which row wins where they overlap,
and a molecule coloured by another's secondary structure.

A row of ``colors`` gives its ``color`` to its ``group``, which is any of:

- a chain of the molecule's: ``A``;
- a residue: ``SER195`` (in each chain that has one), ``SER195.A`` (in chain A alone), or a
  ligand, whose code may start with a digit as many do: ``6V0401`` (6V0, at 401);
- an entity or a subunit: ``entity:1``, ``subunit:L``;
- a mol-sketch selection: ``resi 10-24``, ``resi 34+94+119``, ``resn HIS``,
  ``chain A and resi 1-50``, ``ss H``, ``not polymer`` (read as
  ``flexo.structures._selection`` reads them).

Each is looked for among the chains, residues and entities the file has -- never told
apart by its shape -- and a row that names nothing it has, or a selection that selects none
of it, is said (``structure_problem``) and colours nothing. A selection colours each
residue it selects an atom of, the whole residue: mol-sketch colours residues, not atoms.

Where rows overlap, **a later row wins over an earlier one**, as the last colour given is
the one PyMOL draws: chain ``A`` teal and then ``resi 34`` dark is A teal but for 34; the
other way round, the whole of A is teal.

``ss_from`` colours each residue by its secondary structure in another file (or PDB entry),
matched by chain and number, in the look's helix, strand and loop colours (the figure's,
with ``scheme: figure``), as a cartoon is coloured by its own: each frame of a diffusion run
drawn with its own shape, coloured by the structure it ends as. Its secondary structure is
as mol-sketch has it -- from the file's HELIX and SHEET records (an mmCIF's struct_conf and
struct_sheet_range) where it has them, else worked out from its alpha carbons, as its
cartoon is drawn -- so a structure coloured by its own file is coloured as its cartoon is.
A residue whose own drawing is what ``ss_from`` has there (a helix drawn where the end has a
helix) is left to mol-sketch, which colours a cartoon by the helix, strand or loop it draws:
a strand's arrowhead, drawn on the first residue after it, in the strand's colour, and the
loop that leaves from that residue in the loop's. Only a residue drawn otherwise than
``ss_from`` has it is handed a colour of its own. The rows are laid over it.

mol-sketch is handed each residue's colour by its own name for it (``SER195.A``) -- and a
chain all one colour but for a few residues, as most are, by the chain's, the few by theirs.
"""

from __future__ import annotations

import functools
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from flexo.structures import (
    _NUCLEIC,
    _atoms,
    _BadSelection,
    _called,
    _residues,
    _residues_of,
    _selection,
)

SHADES = {"H": "helix", "E": "sheet", "L": "loop"}
"""The colour of mol-sketch's palette each secondary structure is coloured in."""

_SHAPED = re.compile(r"[A-Za-z0-9]{1,3}-?\d+[A-Za-z]?(\.\w+)?")
"""What a residue's name looks like (``SER195``, ``6V0401.A``): used only to say what a
group that names nothing was taken for, never to tell what a group is."""


class Unseen(ValueError):
    """A colour that would show nowhere: a row naming nothing the molecule has, a selection
    that selects none of it, a file to colour by that can't be read or that has none of its
    residues. The molecule is drawn without it."""

    def __init__(self, message: str, hint: str = "", *, code: str = "colors", title: str = ""):
        super().__init__(message)
        self.hint = hint or None
        self.code = code
        self.title = title


class Residue(NamedTuple):
    """A residue of the molecule, as it is coloured (a tuple: a ribosome's 18 000 are made at
    once)."""

    key: str
    """mol-sketch's name for it, what it is coloured by: ``SER195.A``."""
    resn: str
    resi: int
    chain: str
    entity: str
    subunit: str
    het: bool
    ss: str


class Molecule:
    """A molecule's residues, in its file's order, and its atoms (each with the place of its
    residue), as its colours are worked out on them. Its atoms are read only when asked
    for -- by a selection, tested on each -- as most rows (a chain, a residue, a subunit)
    need its residues alone, and a large molecule's atoms take seconds to read."""

    def __init__(self, residues: tuple[Residue, ...], source: str, stamp: float):
        self.residues = residues
        self.source = source
        self.stamp = stamp
        self.chains: dict[str, tuple[int, ...]] = _index(residues, lambda residue: residue.chain)

    # (Each worked out when first asked for: a row names one kind of group.)
    @functools.cached_property
    def entities(self) -> dict[str, tuple[int, ...]]:
        return _index(self.residues, lambda residue: residue.entity)

    @functools.cached_property
    def subunits(self) -> dict[str, tuple[int, ...]]:
        return _index(self.residues, lambda residue: residue.subunit.upper())

    @functools.cached_property
    def named(self) -> dict[str, tuple[int, ...]]:
        return _index(self.residues, lambda residue: f"{residue.resn.upper()}{residue.resi}")

    @functools.cached_property
    def keyed(self) -> dict[str, int]:
        return {
            f"{residue.resn.upper()}{residue.resi}.{residue.chain}": place
            for place, residue in enumerate(self.residues)
        }

    @functools.cached_property
    def atoms(self) -> tuple:
        return _atoms(self.source, self.stamp)

    @functools.cached_property
    def owners(self) -> tuple[int, ...]:
        """The place of each atom's residue."""

        places = {residue.key: place for place, residue in enumerate(self.residues)}
        return tuple(
            places[atom.group or f"{atom.resn}{atom.resi}{'.' + atom.chain if atom.chain else ''}"]
            for atom in self.atoms
        )

    def residue(self, text: str) -> tuple[int, ...]:
        """The residues ``SER195`` (in any chain) or ``SER195.A`` names: none, for a name
        that is no residue of the molecule's."""

        head, dot, chain = text.partition(".")
        if dot:
            place = self.keyed.get(f"{head.upper()}.{chain}")
            return () if place is None else (place,)
        return self.named.get(head.upper(), ())

    def numbered(self) -> str:
        """How its residues are numbered, as a hint says it ("1 to 300"), or ""."""

        numbers = [residue.resi for residue in self.residues if not residue.het]
        return f"{min(numbers)} to {max(numbers)}" if numbers else ""

    def ligands(self) -> list[Residue]:
        """Its ligands: residues not of the polymer, waters aside, each named once."""

        seen: dict[str, Residue] = {}
        for residue in self.residues:
            if residue.het and residue.resn.upper() not in {"HOH", "WAT"}:
                seen.setdefault(f"{residue.resn}{residue.resi}", residue)
        return list(seen.values())


def _index(residues: tuple[Residue, ...], key) -> dict[str, tuple[int, ...]]:
    found: dict[str, list[int]] = {}
    for place, residue in enumerate(residues):
        found.setdefault(key(residue), []).append(place)
    return {name: tuple(places) for name, places in found.items()}


@functools.lru_cache(maxsize=8)
def molecule(source: str, stamp: float) -> Molecule:
    """The molecule ``source`` holds, by residue (``flexo.structures._residues``)."""

    seen: set[str] = set()
    residues: list[Residue] = []
    for held in _residues(source, stamp):
        if held.group in seen:
            continue
        seen.add(held.group)
        residues.append(Residue(held.group, held.resn, held.resi, held.chain, held.entity,
                                held.subunit or "X", held.het, held.ss or "L"))
    return Molecule(tuple(residues), source, stamp)


@dataclass(frozen=True, slots=True)
class Row:
    """What a row of colours colours: the places of its residues, in the molecule's order --
    or, for a row that colours nothing, why (``problem``, and a ``hint``)."""

    places: tuple[int, ...]
    problem: str = ""
    hint: str = ""


@functools.lru_cache(maxsize=64)
def rows(source: str, stamp: float, groups: tuple[str, ...], name: str) -> tuple[Row, ...]:
    """What each of ``groups`` colours of the molecule ``source`` holds (called ``name``)."""

    found = molecule(source, stamp)
    return tuple(_row(found, group.strip(), name) for group in groups)


def _row(found: Molecule, text: str, name: str) -> Row:
    if text in found.chains:
        return Row(found.chains[text])
    for kind, index in (("entity", found.entities), ("subunit", found.subunits)):
        if text.lower().startswith(f"{kind}:"):
            wanted = text[len(kind) + 1:].strip()
            places = index.get(wanted.upper() if kind == "subunit" else wanted)
            if places:
                return Row(places)
            have = [each for each in index if each and each != "X"]
            hint = (f"Its {'entities' if kind == 'entity' else 'subunits'} are {', '.join(have)}."
                    if have else f"It names no {'entities' if kind == 'entity' else 'subunits'}.")
            return Row((), f'"{text}" names no {kind} of {name}, so its colour would show '
                           "nowhere.", hint)
    places = found.residue(text)
    if places:
        return Row(places)
    try:
        test = _selection(text)
    except _BadSelection as error:
        if " " in text or "(" in text:
            return Row((), f'"{text}" colours nothing: {error}')
        return _named_nothing(found, text, name)
    places = tuple(sorted({found.owners[at] for at, atom in enumerate(found.atoms) if test(atom)}))
    if places:
        return Row(places)
    words = {token.lower() for token in re.findall(r"[^\s()+]+", text)}
    hints = []
    if words & {"chain", "c."}:
        hints.append(f"Its chains are {', '.join(chain for chain in found.chains if chain)}.")
    if words & {"resi", "i."} and found.numbered():
        hints.append(f"Its residues are numbered {found.numbered()}.")
    if words & {"resn", "r."} and found.ligands():
        hints.append(_ligands(found))
    return Row((), f'"{text}" selects nothing in {name}, so its colour would show nowhere.',
               " ".join(hints))


def _named_nothing(found: Molecule, text: str, name: str) -> Row:
    """A group of one word that names nothing the molecule has: a residue, by the look of
    it, or else a chain."""

    if _SHAPED.fullmatch(text) and not text.isdigit():
        hints = [f"Its residues are numbered {found.numbered()}."] if found.numbered() else []
        if found.ligands():
            hints.append(_ligands(found))
        return Row((), f'"{text}" names no residue of {name}, so its colour would show nowhere.',
                   " ".join(hints))
    chains = ", ".join(chain for chain in found.chains if chain)
    return Row(
        (), f'"{text}" names no chain of {name}, so its colour would show nowhere.',
        f"Its chains are {chains} (the author's chain names, as the file gives them)."
        if chains else "",
    )


def _ligands(found: Molecule) -> str:
    named = [f"{residue.resn}{residue.resi}" for residue in found.ligands()]
    more = f" and {len(named) - 6} more" if len(named) > 6 else ""
    return f"Its ligands are {', '.join(named[:6])}{more}."


def plan(found: Molecule, rows: tuple[Row, ...], colours: tuple[str, ...],
         under: dict[int, str]) -> dict[str, str]:
    """mol-sketch's colours for the molecule, by its names for groups: each residue's, from
    ``under`` (by its place) and then each row in turn, a later row over an earlier one --
    a chain coloured throughout handed over as its most common colour, with its residues of
    another colour by theirs (in mol-sketch, the narrowest wins)."""

    final = dict(under)
    for row, colour in zip(rows, colours, strict=True):
        final.update(dict.fromkeys(row.places, colour))
    handed: dict[str, str] = {}
    whole: set[int] = set()
    for chain, places in found.chains.items():
        if not chain or any(place not in final for place in places):
            continue
        common = Counter(final[place] for place in places).most_common(1)[0][0]
        handed[chain] = common
        for place in places:
            if final[place] != common:
                handed[found.residues[place].key] = final[place]
        whole.update(places)
    for place in sorted(final.keys() - whole):
        handed[found.residues[place].key] = final[place]
    return handed


@functools.lru_cache(maxsize=16)
def _secondary(source: str, stamp: float) -> dict[tuple[str, int], str]:
    """Each residue of a polymer's secondary structure in ``source`` (H, E or L), by chain and
    number, as mol-sketch assigns it."""

    found: dict[tuple[str, int], str] = {}
    for residue in _residues(source, stamp):
        if not residue.het and residue.resn.upper() not in _NUCLEIC:
            found.setdefault((residue.chain, residue.resi), residue.ss or "L")
    return found


def secondary(found: Molecule, source: str, stamp: float,
              palette: dict[str, str],
              drawn: dict[tuple[str, int], str] | None = None) -> dict[int, str]:
    """Each of the molecule's polymer residues coloured by its secondary structure in
    ``source`` -- the residue there of its chain and number -- in ``palette``'s helix, sheet
    and loop colours, by its place: none that ``source`` lacks, and none ``drawn`` (what the
    molecule draws each as: ``drawn_as``) draws as ``source`` has it -- mol-sketch colours
    those itself, by the element it draws them in."""

    taken = _taken(source, stamp)
    shades = {code: palette.get(role) for code, role in SHADES.items()}
    coloured: dict[int, str] = {}
    for place, residue in enumerate(found.residues):
        code = None if residue.het else taken.get((residue.chain, residue.resi))
        if code is not None and code not in ("H", "E"):
            code = "L"
        if code is not None and drawn and drawn.get((residue.chain, residue.resi)) == code:
            continue
        shade = None if code is None else shades.get(code) or shades["L"]
        if shade and residue.resn.upper() not in _NUCLEIC:
            coloured[place] = shade
    return coloured


def drawn_as(figure) -> dict[tuple[str, int], str]:
    """What mol-sketch draws each polymer residue of ``figure`` in -- H, E or L, by chain and
    number -- as its cartoon is cut into helices and strands: its own secondary structure, a
    helix of fewer than three residues and a strand of one drawn as loop."""

    ss: dict[tuple[str, int], str] = {}
    for residue in _drawn_residues(figure):
        if residue.het or residue.resn.upper() in _NUCLEIC:
            continue
        code = residue.ss or "L"
        ss.setdefault((residue.chain, residue.resi), code if code in ("H", "E") else "L")
    drawn: dict[tuple[str, int], str] = {}
    keys = sorted(ss)
    start = 0
    for k in range(1, len(keys) + 1):
        broken = k == len(keys) or keys[k][0] != keys[k - 1][0] or keys[k][1] - keys[k - 1][1] > 2
        if not broken and ss[keys[k]] == ss[keys[start]]:
            continue
        code = ss[keys[start]]
        if (code == "H" and k - start < 3) or (code == "E" and k - start < 2):
            code = "L"
        for key in keys[start:k]:
            drawn[key] = code
        start = k
    return drawn


def _drawn_residues(figure) -> tuple:
    """The residues of mol-sketch's ``figure`` (``flexo.structures._residues_of``), or for a
    mol-sketch that can't list them, its scene's atoms (each has what its residue has)."""

    found = _residues_of(figure)
    if found is not None:
        return found
    from molsketch._engine import engine

    atoms = engine().call("sceneJson", figure._spec())["keyframes"][0]["atoms"]
    return tuple(
        Residue("", str(atom.get("resn") or ""), int(atom.get("resi") or 0),
                str(atom.get("chain") or ""), "", "", bool(atom.get("het")),
                str(atom.get("ss") or ""))
        for atom in atoms.values()
    )


_unread: dict[tuple[str, float], Exception] = {}
"""Why a file to colour by could not be read, by its name and when it was saved: not read
again until it is saved again (a PDB entry that could not be had, not again this session) --
never at every drawing."""


def _taken(source: str, stamp: float) -> dict[tuple[str, int], str]:
    if not Path(source).exists() and _FILE.search(source):
        raise FileNotFoundError(source)  # (not looked for in the PDB)
    if (source, stamp) in _unread:
        raise _unread[(source, stamp)]
    try:
        return _secondary(source, stamp)
    except Exception as error:
        _unread[(source, stamp)] = error
        raise


_FILE = re.compile(r"[/\\]|\.(pdb|cif|mmcif|ent|json)$", re.IGNORECASE)
"""A name that is a file's, not a PDB ID's."""


def _about(figure) -> tuple[list[str], str, dict]:
    """The molecule's chains and name, and the colours of the palette it is drawn with."""

    info = figure._info()
    structure = info.get("structure") or {}
    chains = [str(chain) for chain in structure.get("chains") or ()]
    return chains, _called(structure.get("name")), (info.get("style") or {}).get("palette") or {}


def paint(figure, ask) -> None:
    """Hand ``figure`` (mol-sketch's, its look and style set) the colours ``ask`` gives it:
    by the secondary structure of its ``ss_from``, its rows over that -- but for what would
    show nowhere (said by ``check``)."""

    groups = tuple(group for group, _ in ask.colours)
    colours = tuple(colour for _, colour in ask.colours)
    if not groups and not ask.ss_from:
        return
    chains, name, palette = _about(figure)
    if not ask.ss_from and all(group in chains for group in groups):
        # Chains alone never overlap: a later row for a chain is over an earlier one, as
        # they are handed over (and no residue need be looked at).
        _hand(figure, dict(zip(groups, colours, strict=True)))
        return
    try:
        found = molecule(ask.source, ask.stamp)
    except Exception:  # (its residues unread: its rows handed over as they are written)
        _hand(figure, dict(zip(groups, colours, strict=True)))
        return
    under: dict[int, str] = {}
    if ask.ss_from:
        # (A cartoon coloured by secondary structure, as it is unless its style says
        # otherwise: what it draws as ss_from has it is left to it.)
        own = (getattr(figure, "style", None) or {}).get("cartoon_color", "ss") in (None, "", "ss")
        try:
            drawn = drawn_as(figure) if own else None
            under = secondary(found, ask.ss_from, ask.ss_stamp, palette, drawn)
        except Exception:  # (said by check: coloured by its own meanwhile)
            under = {}
    _hand(figure, plan(found, rows(ask.source, ask.stamp, groups, name), colours, under))


def _hand(figure, handed: dict[str, str]) -> None:
    """``handed`` given to mol-sketch: the first as its ``color`` gives one (a scene's own
    colours kept), the rest all at once -- given one at a time, each would copy all those
    given before it, and a large molecule's thousands of residues take seconds."""

    if not handed:
        return
    (first, colour), *rest = handed.items()
    figure.color(first, colour)
    kept = getattr(figure, "_colors", None)
    if isinstance(kept, dict):
        kept.update(rest)
        return
    for group, each in rest:
        figure.color(group, each)


def check(figure, ask) -> None:
    """Say (``Unseen``) the first of ``ask``'s colours that would show nowhere: a row that
    colours nothing, or a file to colour by that can't be read or has none of the
    molecule's residues."""

    groups = tuple(group for group, _ in ask.colours)
    chains, name, _ = _about(figure)
    if any(group not in chains for group in groups):
        try:
            found = rows(ask.source, ask.stamp, groups, name)
        except Exception:  # (its residues unread: nothing said of its rows)
            found = ()
        for row in found:
            if row.problem:
                raise Unseen(row.problem, row.hint)
    if ask.ss_from:
        _check_secondary(ask, name)


def _check_secondary(ask, name: str) -> None:
    source = ask.ss_from
    called = Path(source).name if _FILE.search(source) else _called(source)
    own = f"{name} is coloured by its own secondary structure."
    try:
        taken = _taken(source, ask.ss_stamp)
    except FileNotFoundError:
        raise Unseen(f"There is no such file in the folder, so {own}", code="ss_from",
                     title=f"Couldn't find {called}") from None
    except ConnectionError:
        raise Unseen(f"The Protein Data Bank can't be reached, so {own}", code="ss_from",
                     title=f"Couldn't download {called}") from None
    except Exception as error:  # whatever it is, said
        first = str(error).split("\n")[0].strip().rstrip(".")
        said = f"{first[:1].upper()}{first[1:]}, so {own}" if first else own[:1].upper() + own[1:]
        raise Unseen(said, code="ss_from", title=f"Couldn't read {called}") from None
    try:
        residues = molecule(ask.source, ask.stamp).residues
    except Exception:  # (its own residues unread: nothing said of them)
        return
    if not any((residue.chain, residue.resi) in taken for residue in residues
               if not residue.het):
        raise Unseen(
            f"{called} has none of {name}'s residues (by chain and number), so its secondary "
            "structure colours nothing.", code="ss_from", title=name,
        )


def said(figure, ask) -> dict[str, object]:
    """What the studio shows beside a structure's rows of colours: what each group colours
    (how many residues; or why nothing, and a hint), and the molecule's ligands to choose."""

    groups = tuple(dict.fromkeys(group for group, _ in ask.colours))
    _, name, _ = _about(figure)
    try:
        found = molecule(ask.source, ask.stamp)
        each = rows(ask.source, ask.stamp, groups, name)
    except Exception:  # (its residues unread: nothing said of its rows)
        return {"groups": {}, "ligands": []}
    return {
        "groups": {
            group: {"residues": len(row.places), "problem": row.problem, "hint": row.hint}
            for group, row in zip(groups, each, strict=True)
        },
        "ligands": [
            {"group": f"{residue.resn}{residue.resi}", "label": f"{residue.resn} {residue.resi}"}
            for residue in found.ligands()
        ],
    }
