"""Reaction mechanisms: structures drawn from SMILES, and the curly arrows that join them.

A ``mechanism`` component draws a run of steps, left to right and in rows when they
are many, a reaction arrow between each and the next -- its reagents over it, its
conditions under it -- and each structure's name under it. A step is

- ``smiles``: its structure, the molecules apart with ``.`` (``[OH-:5].C[C:2](=O)Cl``);
  atom maps (``:5``) name the atoms its arrows and the steps after it talk of;
- ``arrows``: its curly arrows (``"5 -> 2; 2=3 -> 3"``, see ``flexo.chemistry.electrons``);
- ``label``, ``reagents``, ``conditions``, and ``arrow``: ``forward`` (the default),
  ``equilibrium``, ``resonance``, or ``none``.

A step with no ``smiles`` is what the arrows before it make: drawn from them, its
atoms where they were. One written out is checked against them, and anything they do
not make -- a charge, a bond, a hydrogen -- is said, as is an arrow that cannot be
(carbon given ten electrons, a lone pair that is not there). After a last step with
arrows comes what they make. Lone pairs are drawn where arrows leave them
(``lone_pairs: all`` for every one, ``none`` for none), charges circled (``charges:
plain`` for superscripts).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from flexo.chemistry.curly import INK, draw_arrows, tail_ways
from flexo.chemistry.draw import Drawn, Pen, draw_molecule
from flexo.chemistry.electrons import Arrow, MechanismError, compare, push, read_arrow, target_bond
from flexo.chemistry.layout import align, assemble, follow, foresee, gather
from flexo.chemistry.molecule import Molecule, SmilesError, read_smiles
from flexo.chemistry.stereo import wedges
from flexo.diagnostics import Diagnostic, FlexoError
from flexo.drawn import Picture, Shape, Words, path, units
from flexo.geometry import Size
from flexo.ir.semantic import NodeSpec, Record, TextRun
from flexo.markup import parse_label
from flexo.style import LayoutStyle

ARROWS = ("forward", "equilibrium", "resonance", "none")


@dataclass(slots=True)
class Placement:
    """Where a molecule goes from where it is laid out: flipped (left for right) and
    turned (degrees, clockwise) about its middle, then moved (bond lengths, y down)."""

    move: tuple[float, float] = (0.0, 0.0)
    turn: float = 0.0
    flip: bool = False


@dataclass(slots=True)
class Step:
    smiles: str = ""
    arrows: list[str] = field(default_factory=list)
    label: str = ""
    reagents: str = ""
    conditions: str = ""
    arrow: str = "forward"
    place: dict[int, Placement] = field(default_factory=dict)
    """Molecules put where the author wants them, each named by one of its atoms."""


@dataclass(slots=True)
class Panel:
    """One structure as drawn, with its arrows and what is said under it."""

    molecule: Molecule
    arrows: list[Arrow]
    step: Step
    drawn: Drawn | None = None


def _fail(node: NodeSpec, code: str, message: str, hint: str | None = None) -> FlexoError:
    return FlexoError(_said(node, code, message, hint))


def mechanism_steps(node: NodeSpec) -> list[Step]:
    value = node.property("steps")
    if value is None or value == ():
        raise _fail(
            node,
            "steps",
            "A mechanism needs at least one step.",
            'Give steps, each {"smiles": ..., "arrows": ...}.',
        )
    if isinstance(value, str):
        return [Step(smiles=value)]
    if not isinstance(value, tuple):
        raise _fail(node, "steps", '"steps" is a list of steps.')
    steps = []
    for number, record in enumerate(value, start=1):
        if not isinstance(record, Record):
            raise _fail(node, "steps", f"Step {number} is not a step.")
        unknown = set(record.as_dict()) - {
            "smiles",
            "arrows",
            "label",
            "reagents",
            "conditions",
            "arrow",
            "place",
        }
        if unknown:
            raise _fail(
                node,
                "steps",
                f"Step {number} has {', '.join(sorted(unknown))}, which a step does not.",
                "A step has smiles, arrows, label, reagents, conditions, arrow and place.",
            )
        arrow = str(record.get("arrow") or "forward").strip().lower()
        if arrow not in ARROWS:
            raise _fail(
                node, "arrow", f'Step {number}: arrow "{arrow}" is not one of {", ".join(ARROWS)}.'
            )
        arrows_text = record.get("arrows") or ""
        if not isinstance(arrows_text, str):
            raise _fail(
                node,
                "arrows",
                f'Step {number}: arrows are written as words, such as "5 -> 2; 2=3 -> 3".',
            )
        steps.append(
            Step(
                smiles=str(record.get("smiles") or "").strip(),
                arrows=[
                    part.strip()
                    for part in arrows_text.replace("\n", ";").split(";")
                    if part.strip()
                ],
                label=str(record.get("label") or ""),
                reagents=str(record.get("reagents") or ""),
                conditions=str(record.get("conditions") or ""),
                arrow=arrow,
                place=_placements(node, number, record.get("place")),
            )
        )
    if not steps[0].smiles:
        raise _fail(
            node,
            "smiles",
            "The first step needs its structure, as SMILES.",
            'For example {"smiles": "[OH-:5].[CH3:1][C:2](=[O:3])[Cl:4]", '
            '"arrows": "5 -> 2; 2=3 -> 3"}.',
        )
    return steps


def place_words(value: object) -> str:
    """A step's ``place`` as the mechanism keeps it: ``{5: {"move": [-1, 0.5], "turn": 30,
    "flip": True}}`` (or ``{5: [-1, 0.5]}``, only moved) written ``"5 move -1 0.5 turn 30
    flip"``, several apart with ``;``. Words are kept as they are."""

    if isinstance(value, str):
        return value
    parts = []
    for atom, how in dict(value or {}).items():  # type: ignore[call-overload]
        if isinstance(how, list | tuple):
            how = {"move": how}
        words = [str(atom).strip()]
        move = how.get("move") if isinstance(how, dict) else None
        if move:
            words += ["move", f"{float(move[0]):g}", f"{float(move[1]):g}"]
        if isinstance(how, dict) and how.get("turn"):
            words += ["turn", f"{float(how['turn']):g}"]
        if isinstance(how, dict) and how.get("flip"):
            words.append("flip")
        parts.append(" ".join(words))
    return "; ".join(parts)


def place_record(value: object) -> dict[str, dict[str, object]]:
    """A step's ``place``, words or mapping, as a mapping a document keeps: each atom (as
    words) to its ``move``, ``turn`` and ``flip``, the ones not used left out."""

    out: dict[str, dict[str, object]] = {}
    for part in place_words(value).replace("\n", ";").split(";"):
        atom, how = _placement(part)
        if atom is None:
            continue
        entry: dict[str, object] = {}
        if how.move != (0.0, 0.0):
            entry["move"] = [how.move[0], how.move[1]]
        if how.turn:
            entry["turn"] = how.turn
        if how.flip:
            entry["flip"] = True
        out[str(atom)] = entry
    return out


def _placement(part: str) -> tuple[int | None, Placement]:
    words = part.split()
    if not words:
        return None, Placement()
    atom, rest, how = int(words[0]), words[1:], Placement()
    while rest:
        word = rest.pop(0).lower()
        if word == "move":
            how.move = (float(rest.pop(0)), float(rest.pop(0)))
        elif word == "turn":
            how.turn = float(rest.pop(0))
        elif word == "flip":
            how.flip = True
        else:
            raise ValueError(word)
    return atom, how


def _placements(node: NodeSpec, number: int, value: object) -> dict[int, Placement]:
    if value is None or value == "":
        return {}
    if not isinstance(value, str):
        raise _fail(
            node,
            "place",
            f'Step {number}: place is written as words, such as "5 move -1 0.5 turn 30 flip".',
        )
    out: dict[int, Placement] = {}
    for part in value.replace("\n", ";").split(";"):
        try:
            atom, how = _placement(part)
        except (ValueError, IndexError):
            raise _fail(
                node,
                "place",
                f'Step {number}: "{part.strip()}" does not say where a molecule goes.',
                'Write "5 move -1 0.5 turn 30 flip": the molecule with atom 5 moved a bond '
                "left and half a bond down, turned 30 degrees clockwise, and flipped.",
            ) from None
        if atom is not None:
            out[atom] = how
    return out


def _arrange(molecule: Molecule, place: dict[int, Placement]) -> int | None:
    """Each molecule ``place`` names put where it says; the first atom it names that the
    molecule does not have, if any."""

    missing = None
    fragments = molecule.fragments()
    for number, how in place.items():
        index = molecule.index_of(number)
        if index is None:
            missing = missing if missing is not None else number
            continue
        atoms = [molecule.atoms[i] for i in next(f for f in fragments if index in f)]
        cx = sum(atom.x for atom in atoms) / len(atoms)
        cy = sum(atom.y for atom in atoms) / len(atoms)
        cos, sin = math.cos(math.radians(how.turn)), math.sin(math.radians(how.turn))
        for atom in atoms:
            x, y = atom.x - cx, atom.y - cy
            if how.flip:
                x = -x
            atom.x = cx + x * cos - y * sin + how.move[0]
            atom.y = cy + x * sin + y * cos + how.move[1]
    return missing


def mechanism_panels(node: NodeSpec) -> list[Panel]:
    """Each structure of the mechanism, laid out, its arrows read and checked; a step
    that cannot be is refused, in words."""

    panels, problem = mechanism_states(node)
    if problem is not None:
        raise FlexoError(problem)
    return panels


def mechanism_states(node: NodeSpec) -> tuple[list[Panel], Diagnostic | None]:
    """Each structure of the mechanism as far as it goes, and what stops it. A step is
    wrong between one arrow and the next while it is drawn -- a carbon has five bonds
    until the leaving group's arrow comes -- so the step that cannot be is kept, with
    the arrows that read, the structures after it are not, and why is said.

    A step ``holding`` names (``{"step": 2, "arrows": "..."}``) is laid out for those
    arrows rather than its own, so that drawing on it does not move it."""

    steps = mechanism_steps(node)
    held = _holding(node)
    panels: list[Panel] = []
    made: Molecule | None = None
    noted: Diagnostic | None = None
    for number, step in enumerate(steps, start=1):
        where = f"Step {number}"
        if step.smiles:
            try:
                molecule = read_smiles(step.smiles)
            except SmilesError as error:
                problem = _said(node, "smiles", f"{where}: {error}", error.hint)
                if not panels:
                    raise FlexoError(problem) from None
                return _ending(panels, made), problem
            if made is not None and panels and panels[-1].arrows:
                # A step drawn by hand may leave out what takes no part, and bring in what
                # joins: only what it says of the atoms it shares must agree.
                said = [
                    line
                    for line in compare(
                        made, molecule, step=where.lower(), before=f"step {number - 1}"
                    )
                    if "does not draw atom" not in line and "that step" not in line
                ]
                if said:
                    return _ending(panels, made), _said(
                        node,
                        "check",
                        f"{where} is not what step {number - 1}'s arrows make: " + " ".join(said),
                        f"Leave out step {number}'s smiles to draw what the arrows make.",
                    )
        elif made is None:
            return panels, _said(
                node,
                "smiles",
                f"{where} has no structure, and the step before it no arrows to make one.",
                "Give it smiles, or give the step before it arrows.",
            )
        else:
            molecule = made
        problem = None
        arrows = []
        for text in step.arrows:
            try:
                arrows.append(read_arrow(text, molecule))
            except MechanismError as error:
                if problem is None:
                    problem = _said(node, "arrows", f"{where}: {error}", error.hint)
        made = None
        if arrows and problem is None:
            try:
                made = push(molecule, arrows, step=where)
            except MechanismError as error:
                problem = _said(node, "arrows", str(error), error.hint)
        # Laid out for what the arrows do -- or, held, for the arrows it was opened with.
        laid, layout = arrows, made
        if number in held:
            laid = [arrow for text in held[number] if (arrow := _quietly(text, molecule))]
            layout = _pushed(molecule, laid)
        meetings = [pair for arrow in laid if (pair := target_bond(arrow))]
        if not panels:
            if layout is None or not foresee(molecule, layout.copy(), meetings):
                assemble(molecule, meetings)
        elif step.smiles:
            align(panels[-1].molecule, molecule)
            gather(molecule, meetings)
        else:
            gather(molecule, meetings)
        missing = _arrange(molecule, step.place)
        if missing is not None and noted is None:
            noted = _said(
                node,
                "place",
                f"{where} places the molecule with atom {missing}, which it does not have.",
                f"Name the molecule by an atom it has, or leave atom {missing} out of place.",
            )
        panels.append(Panel(molecule, arrows, step))
        if problem is not None:
            return panels, problem
        if made is not None:
            follow(molecule, made)
    if made is not None:
        panels.append(Panel(made, [], Step()))
    return panels, noted


def _said(node: NodeSpec, code: str, message: str, hint: str | None = None) -> Diagnostic:
    return Diagnostic(f"mechanism.{code}", message, entity_id=node.id, hint=hint or None)


def _ending(panels: list[Panel], made: Molecule | None) -> list[Panel]:
    """The panels so far, and what the last arrows make, when the next step is wrong."""

    if made is None or not panels or not panels[-1].arrows:
        return panels
    return [*panels, Panel(made, [], Step())]


def _holding(node: NodeSpec) -> dict[int, list[str]]:
    value = node.property("holding")
    held: dict[int, list[str]] = {}
    for record in value if isinstance(value, tuple) else ():
        step, arrows = record.get("step"), record.get("arrows")
        if isinstance(step, int) and isinstance(arrows, str):
            held[step] = [part.strip() for part in arrows.split(";") if part.strip()]
    return held


def _quietly(text: str, molecule: Molecule) -> Arrow | None:
    try:
        return read_arrow(text, molecule)
    except MechanismError:
        return None


def _pushed(molecule: Molecule, arrows: list[Arrow]) -> Molecule | None:
    if not arrows:
        return None
    try:
        return push(molecule, arrows)
    except MechanismError:
        return None


def mechanism_tones(node: NodeSpec) -> tuple[str, ...]:
    """A mechanism takes no tones: its arrows have their one ink."""

    del node
    return ()


def mechanism_drawing(node: NodeSpec, style: LayoutStyle) -> Picture:
    return mechanism_composed(node, style).picture


@dataclass(slots=True)
class Composed:
    """A mechanism drawn: the picture, and each structure in it as drawn -- the molecule
    (hydrogens no arrow moves folded into their labels), where its atoms went, and how
    the step's atoms are numbered in it."""

    picture: Picture
    drawn: dict[int, tuple[Drawn, Molecule, dict[int, int]]]
    pen: Pen
    panels: list[Panel]
    problem: Diagnostic | None


def mechanism_composed(node: NodeSpec, style: LayoutStyle) -> Composed:
    """The mechanism's picture, and what is in it. With ``partial`` a step that cannot be
    is drawn and the rest left out (``problem`` says why) rather than refused; with
    ``only`` (a structure's number, from 1) that one structure is drawn alone, as an
    editor draws on it."""

    measures = units(style)
    u = measures.u
    pen = Pen(u, lambda runs: measures.measure(runs))
    pairs = str(node.property("lone_pairs") or "used").strip().lower()
    if pairs not in {"used", "all", "none"}:
        raise _fail(node, "lone_pairs", f'lone_pairs "{pairs}" is not one of used, all, none.')
    charges = str(node.property("charges") or "circled").strip().lower()
    if charges not in {"circled", "plain"}:
        raise _fail(node, "charges", f'charges "{charges}" is neither circled nor plain.')
    panels, problem = mechanism_states(node)
    if problem is not None and (not node.property("partial") or not panels):
        raise FlexoError(problem)
    colour = _arrow_colour(node)
    kept: dict[int, tuple[Drawn, Molecule, dict[int, int]]] = {}
    only = node.property("only")
    if isinstance(only, int) and not isinstance(only, bool):
        chosen = min(max(only, 1), len(panels)) - 1
        drawn, molecule, renumber = draw_panel(
            panels[chosen],
            pen,
            prefix=f"{node.id}.step{chosen + 1}",
            pairs=pairs,
            charges=charges,
            colour=colour,
        )
        x0, y0, x1, y1 = drawn.bounds()
        drawn, molecule, renumber = draw_panel(
            panels[chosen],
            pen,
            prefix=f"{node.id}.step{chosen + 1}",
            origin=(-x0, -y0),
            pairs=pairs,
            charges=charges,
            colour=colour,
        )
        kept[chosen] = (drawn, molecule, renumber)
        picture = Picture(Size(x1 - x0, y1 - y0), tuple(drawn.shapes), tuple(drawn.words))
        return Composed(picture, kept, pen, panels, problem)

    def drawing(index: int, panel: Panel, origin: tuple[float, float]) -> Drawn:
        drawn, molecule, renumber = draw_panel(
            panel,
            pen,
            prefix=f"{node.id}.step{index + 1}",
            origin=origin,
            pairs=pairs,
            charges=charges,
            colour=colour,
        )
        kept[index] = (drawn, molecule, renumber)
        return drawn

    # Each structure drawn once where it falls, to measure it, then where it goes.
    sizes = []
    for index, panel in enumerate(panels):
        x0, y0, x1, y1 = drawing(index, panel, (0.0, 0.0)).bounds()
        if panel.step.label:
            # A name wider than its structure widens its room, centred under it.
            wide = measures.measure(parse_label(panel.step.label), small=True).width + u * 0.6
            if wide > x1 - x0:
                spare = (wide - (x1 - x0)) / 2.0
                x0, x1 = x0 - spare, x1 + spare
        sizes.append((x0, y0, x1, y1))
    small = u * 0.82
    joins = []
    for panel in panels[:-1]:
        step = panel.step
        above = _words(step.reagents, measures, small) if step.reagents else None
        below = _words(step.conditions, measures, small) if step.conditions else None
        widest = max([0.0] + [item.width for item in (above, below) if item is not None])
        length = 0.0 if step.arrow == "none" else max(u * 2.6, widest + u * 1.2)
        joins.append((step.arrow, length, above, below))
    per_row = _per_row(node, sizes, joins, u)
    gap = u * 0.7
    shapes: list[Shape] = []
    words: list[Words] = []
    y = 0.0
    width = 0.0
    labels_room = u * 1.5 if any(panel.step.label for panel in panels) else 0.0
    rows = [
        list(range(start, min(start + per_row, len(panels))))
        for start in range(0, len(panels), per_row)
    ]
    for row_number, row in enumerate(rows):
        heights = [sizes[index][3] - sizes[index][1] for index in row]
        row_height = max(heights)
        middle = y + row_height / 2.0
        x = 0.0
        for place, index in enumerate(row):
            if index > 0 and (place > 0 or row_number > 0):
                # The arrow into this structure (at a row's start, the arrow that carries on).
                kind, length, above, below = joins[index - 1]
                if kind != "none":
                    x += gap
                    _reaction_arrow(
                        shapes,
                        words,
                        kind,
                        x,
                        middle,
                        length,
                        above,
                        below,
                        measures,
                        small,
                        f"{node.id}.arrow{index}",
                        u,
                    )
                    x += length + gap
                else:
                    x += gap * 2
            x0, y0, x1, y1 = sizes[index]
            origin = (x - x0, middle - (y0 + y1) / 2.0)
            drawn = drawing(index, panels[index], origin)
            shapes += drawn.shapes
            words += drawn.words
            label = panels[index].step.label
            if label:
                runs = parse_label(label)
                metrics = measures.measure(runs, small=True)
                words.append(
                    Words(
                        f"{node.id}.label{index + 1}",
                        runs,
                        metrics,
                        x + (x1 - x0) / 2.0,
                        middle + row_height / 2.0 + u * 1.1,
                        anchor="middle",
                        role="muted-ink",
                        size=measures.small_size,
                    )
                )
            x += x1 - x0
        width = max(width, x)
        y += row_height + labels_room + (u * 1.4 if row_number < len(rows) - 1 else 0.0)
    return Composed(
        Picture(Size(width, y), tuple(shapes), tuple(words)), kept, pen, panels, problem
    )


def draw_panel(
    panel: Panel,
    pen: Pen,
    *,
    prefix: str,
    origin: tuple[float, float] = (0.0, 0.0),
    pairs: str = "used",
    charges: str = "circled",
    colour: str = INK,
) -> tuple[Drawn, Molecule, dict[int, int]]:
    """One structure and its arrows: the molecule drawn once to see where everything
    falls, which way its arrows leave their atoms and where they would go, then again
    keeping those clear, the arrows over it. Also the molecule as drawn (hydrogens no arrow moves
    folded back into their labels) and how its atoms are numbered in it."""

    molecule, arrows, renumber = _shown(panel.molecule, panel.arrows)
    marks = wedges(molecule)
    first = draw_molecule(
        molecule, pen, prefix=prefix, origin=origin, pairs=pairs, charges=charges, wedges=marks
    )
    used = tail_ways(molecule, first, arrows, pen)
    # Where the arrows would go with the charges out of their way, for the charges to keep off.
    first.marks.clear()
    tried = draw_arrows(molecule, first, arrows, pen, prefix=prefix)
    radicals = {
        arrow.source[0]: 0.0
        for arrow in arrows
        if arrow.electrons == 1
        and len(arrow.source) == 1
        and molecule.atoms[arrow.source[0]].lone % 2
    }
    drawn = draw_molecule(
        molecule,
        pen,
        prefix=prefix,
        origin=origin,
        pairs=pairs,
        used=used,
        lone=radicals,
        charges=charges,
        wedges=marks,
        avoid=tried,
    )
    draw_arrows(molecule, drawn, arrows, pen, prefix=prefix, colour=colour)
    return drawn, molecule, renumber


def _arrow_colour(node: NodeSpec) -> str:
    """The one ink a mechanism's curly arrows are drawn in: magenta, or ``arrow_colour`` --
    a colour (``#c0392b``), or the theme's ``ink``, ``muted`` ink or ``accent``
    (``accent2``...), which follow the theme."""

    value = node.property("arrow_colour")
    if value is None or value == "":
        return INK
    text = str(value).strip().lower()
    if re.fullmatch(r"#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})", text):
        return text
    if text in {"ink", "muted"}:
        return {"ink": "ink", "muted": "muted-ink"}[text]
    accent = re.fullmatch(r"accent(\d*)", text)
    if accent:
        return f"tone-{accent.group(1) or 1}-stroke"
    raise _fail(
        node,
        "arrow_colour",
        f'arrow_colour "{value}" is not a colour.',
        "Give a colour such as #c0392b, or ink, muted, accent (accent2, ...) for the theme's.",
    )


def _shown(molecule: Molecule, arrows: list[Arrow]) -> tuple[Molecule, list[Arrow], dict[int, int]]:
    """The molecule as drawn: a hydrogen written as an atom (to be moved by an arrow) that no
    arrow here moves goes back into its neighbour's label -- ``H₂O``, not ``H-O-H``."""

    moving = {atom for arrow in arrows for atom in (*arrow.source, *arrow.target)}
    folded = [
        index
        for index, atom in enumerate(molecule.atoms)
        if atom.element == "H"
        and index not in moving
        and len(molecule.neighbours(index)) == 1
        and molecule.atoms[molecule.neighbours(index)[0]].element != "H"
        and not atom.lone
        and molecule.charge_of(index) == 0
    ]
    if not folded:
        return molecule, arrows, {index: index for index in range(len(molecule.atoms))}
    shown = molecule.copy()
    for index in folded:
        (holder,) = molecule.neighbours(index)
        shown.atoms[holder].hydrogens += 1
    keep = [index for index in range(len(molecule.atoms)) if index not in set(folded)]
    renumber = {old: new for new, old in enumerate(keep)}
    shown.atoms = [shown.atoms[index] for index in keep]
    shown.bonds = [
        type(bond)(renumber[bond.a], renumber[bond.b], bond.order, bond.aromatic, bond.stereo)
        for bond in shown.bonds
        if bond.a in renumber and bond.b in renumber
    ]
    for atom in shown.atoms:
        atom.order = [renumber.get(item, item) if item >= 0 else item for item in atom.order]
    moved = [
        Arrow(
            tuple(renumber[a] for a in arrow.source),
            tuple(renumber[a] for a in arrow.target),
            arrow.electrons,
            arrow.written,
        )
        for arrow in arrows
    ]
    return shown, moved, renumber


def _words(text: str, measures, size: float):
    runs = parse_label(text)
    return _Said(runs, measures.measure(runs, small=True))


@dataclass(slots=True)
class _Said:
    runs: tuple[TextRun, ...]
    metrics: object

    @property
    def width(self) -> float:
        return self.metrics.width  # type: ignore[attr-defined]


def _per_row(node: NodeSpec, sizes, joins, u: float) -> int:
    """How many structures a row holds: as asked, or as many as keep the whole about
    twice as wide as it is tall."""

    asked = node.property("per_row")
    count = len(sizes)
    if asked is not None:
        try:
            value = int(asked)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise _fail(node, "per_row", f'per_row "{asked}" is not a whole number.') from None
        if value < 1:
            raise _fail(node, "per_row", "per_row is at least 1.")
        return min(value, count)
    best, best_score = count, None
    for per_row in range(1, count + 1):
        rows = [range(start, min(start + per_row, count)) for start in range(0, count, per_row)]
        width = max(
            sum(sizes[i][2] - sizes[i][0] for i in row)
            + sum(joins[i - 1][1] + u * 1.4 for i in row if i > 0)
            for row in rows
        )
        height = sum(max(sizes[i][3] - sizes[i][1] for i in row) for row in rows) + u * 2.4 * (
            len(rows) - 1
        )
        # Mechanisms read along a row: up to four times as wide as tall before folding.
        score = max(0.0, math.log((width / max(height, 1e-6)) / 5.0)) + 0.5 * (len(rows) - 1)
        if best_score is None or score < best_score - 1e-9:
            best, best_score = per_row, score
    return best


def _reaction_arrow(
    shapes: list[Shape],
    words: list[Words],
    kind: str,
    x: float,
    y: float,
    length: float,
    above,
    below,
    measures,
    size: float,
    identifier: str,
    u: float,
) -> None:
    """A reaction arrow from ``x`` along ``length`` at height ``y``: forward, equilibrium
    (two half-headed arrows) or resonance (headed at both ends), its words over and under."""

    line = u * 0.075
    head, wide = u * 0.55, u * 0.38
    end = x + length

    def arrowhead(tip_x: float, tip_y: float, pointing: float, half: str = "") -> str:
        back = tip_x - pointing * head
        notch = tip_x - pointing * head * 0.75
        upper, lower = (back, tip_y - wide / 2), (back, tip_y + wide / 2)
        if half == "upper":
            return path("M", tip_x, tip_y, "L", *upper, "L", notch, tip_y, "Z")
        if half == "lower":
            return path("M", tip_x, tip_y, "L", *lower, "L", notch, tip_y, "Z")
        return path("M", tip_x, tip_y, "L", *upper, "L", notch, tip_y, "L", *lower, "Z")

    if kind == "equilibrium":
        apart = u * 0.18
        shapes.append(
            Shape(
                identifier,
                path(
                    "M",
                    x,
                    y - apart,
                    "L",
                    end - head * 0.7,
                    y - apart,
                    "M",
                    x + head * 0.7,
                    y + apart,
                    "L",
                    end,
                    y + apart,
                ),
                "line",
                width=line,
            )
        )
        shapes.append(
            Shape(
                f"{identifier}.heads",
                arrowhead(end, y - apart, 1.0, "upper")
                + " "
                + arrowhead(x, y + apart, -1.0, "lower"),
                "solid",
                width=line * 0.5,
            )
        )
    elif kind == "resonance":
        shapes.append(
            Shape(
                identifier,
                path("M", x + head * 0.7, y, "L", end - head * 0.7, y),
                "line",
                width=line,
            )
        )
        shapes.append(
            Shape(
                f"{identifier}.heads",
                arrowhead(end, y, 1.0) + " " + arrowhead(x, y, -1.0),
                "solid",
                width=line * 0.5,
            )
        )
    else:
        shapes.append(
            Shape(identifier, path("M", x, y, "L", end - head * 0.7, y), "line", width=line)
        )
        shapes.append(
            Shape(f"{identifier}.head", arrowhead(end, y, 1.0), "solid", width=line * 0.5)
        )
    middle = x + length / 2.0
    if above is not None:
        words.append(
            Words(
                f"{identifier}.reagents",
                above.runs,
                above.metrics,
                middle,
                y - u * 0.45,
                anchor="middle",
                size=measures.small_size,
            )
        )
    if below is not None:
        cap = above.metrics.cap_height if above is not None else below.metrics.cap_height
        words.append(
            Words(
                f"{identifier}.conditions",
                below.runs,
                below.metrics,
                middle,
                y + u * 0.45 + (cap or size * 0.7),
                anchor="middle",
                size=measures.small_size,
            )
        )
