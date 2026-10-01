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
from dataclasses import dataclass, field

from flexo.chemistry.curly import draw_arrows, toward
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
ELECTRONS_TONE = "electrons"


@dataclass(slots=True)
class Step:
    smiles: str = ""
    arrows: list[str] = field(default_factory=list)
    label: str = ""
    reagents: str = ""
    conditions: str = ""
    arrow: str = "forward"


@dataclass(slots=True)
class Panel:
    """One structure as drawn, with its arrows and what is said under it."""

    molecule: Molecule
    arrows: list[Arrow]
    step: Step
    drawn: Drawn | None = None


def _fail(node: NodeSpec, code: str, message: str, hint: str | None = None) -> FlexoError:
    return FlexoError(
        Diagnostic(f"mechanism.{code}", message, entity_id=node.id, hint=hint or None)
    )


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
        }
        if unknown:
            raise _fail(
                node,
                "steps",
                f"Step {number} has {', '.join(sorted(unknown))}, which a step does not.",
                "A step has smiles, arrows, label, reagents, conditions and arrow.",
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


def mechanism_panels(node: NodeSpec) -> list[Panel]:
    """Each structure of the mechanism, laid out, its arrows read and checked."""

    steps = mechanism_steps(node)
    panels: list[Panel] = []
    made: Molecule | None = None
    for number, step in enumerate(steps, start=1):
        where = f"Step {number}"
        if step.smiles:
            try:
                molecule = read_smiles(step.smiles)
            except SmilesError as error:
                raise _fail(node, "smiles", f"{where}: {error}", error.hint) from None
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
                    raise _fail(
                        node,
                        "check",
                        f"{where} is not what step {number - 1}'s arrows make: " + " ".join(said),
                        f"Leave out step {number}'s smiles to draw what the arrows make.",
                    )
        elif made is None:
            raise _fail(
                node,
                "smiles",
                f"{where} has no structure, and the step before it no arrows to make one.",
                "Give it smiles, or give the step before it arrows.",
            )
        else:
            molecule = made
        try:
            arrows = [read_arrow(text, molecule) for text in step.arrows]
        except MechanismError as error:
            raise _fail(node, "arrows", f"{where}: {error}", error.hint) from None
        meetings = [pair for arrow in arrows if (pair := target_bond(arrow))]
        made = None
        if arrows:
            try:
                made = push(molecule, arrows, step=where)
            except MechanismError as error:
                raise _fail(node, "arrows", str(error), error.hint) from None
        if not panels:
            if made is None or not foresee(molecule, made.copy(), meetings):
                assemble(molecule, meetings)
        elif step.smiles:
            align(panels[-1].molecule, molecule)
            gather(molecule, meetings)
        else:
            gather(molecule, meetings)
        panels.append(Panel(molecule, arrows, step))
        if made is not None:
            follow(molecule, made)
    if made is not None:
        panels.append(Panel(made, [], Step()))
    return panels


def mechanism_tones(node: NodeSpec) -> tuple[str, ...]:
    steps = node.property("steps")
    if isinstance(steps, tuple) and any(
        isinstance(record, Record) and record.get("arrows") for record in steps
    ):
        return (ELECTRONS_TONE,)
    return ()


def mechanism_drawing(node: NodeSpec, style: LayoutStyle) -> Picture:
    measures = units(style)
    u = measures.u
    pen = Pen(u, lambda runs: measures.measure(runs))
    pairs = str(node.property("lone_pairs") or "used").strip().lower()
    if pairs not in {"used", "all", "none"}:
        raise _fail(node, "lone_pairs", f'lone_pairs "{pairs}" is not one of used, all, none.')
    charges = str(node.property("charges") or "circled").strip().lower()
    if charges not in {"circled", "plain"}:
        raise _fail(node, "charges", f'charges "{charges}" is neither circled nor plain.')
    panels = mechanism_panels(node)
    tone = ELECTRONS_TONE if any(panel.arrows for panel in panels) else None

    def drawing(index: int, panel: Panel, origin: tuple[float, float]) -> Drawn:
        used: dict[int, list[float]] = {}
        lone: dict[int, float] = {}
        for arrow in panel.arrows:
            angle = toward(panel.molecule, arrow)
            if angle is None:
                continue
            atom = arrow.source[0]
            if arrow.electrons == 1 and panel.molecule.atoms[atom].lone % 2:
                lone[atom] = angle
            else:
                used.setdefault(atom, []).append(angle)
        molecule, arrows, renumber = _shown(panel.molecule, panel.arrows)
        drawn = draw_molecule(
            molecule,
            pen,
            prefix=f"{node.id}.step{index + 1}",
            origin=origin,
            pairs=pairs,
            used={renumber[atom]: value for atom, value in used.items()},
            lone={renumber[atom]: value for atom, value in lone.items()},
            charges=charges,
            wedges=wedges(molecule),
        )
        draw_arrows(molecule, drawn, arrows, pen, prefix=f"{node.id}.step{index + 1}", tone=tone)
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
    return Picture(Size(width, y), tuple(shapes), tuple(words))


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
