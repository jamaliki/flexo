"""A mechanism drawn on by pointing, as mechazyme's editor draws on one.

The structure a step acts on is drawn alone, every atom and bond of it something to
click, and two clicks -- where the electrons come from, where they go -- write an
arrow. The page draws and points; this decides:

- ``sheet`` gives the structure as SVG, with where its atoms, bonds and lone pairs
  are, what its arrows say in words, and what is wrong, if anything;
- ``add_arrow`` writes the arrow two clicks make -- numbering an atom in the SMILES
  that wrote it, if it has no number yet -- or asks which end of a bond makes the
  new one;
- ``remove_arrow`` takes one away;
- ``place_molecule`` moves, turns or flips one of a step's molecules from where it is
  laid out, or puts it back.

A step that cannot be is drawn all the same, its problem said: between one arrow and
the next it usually is (the nucleophile's arrow gives carbon five bonds until the
leaving group's comes). A step being drawn on is laid out for the arrows it had when
it was opened (``holding``), so that drawing on it does not move it.
"""

from __future__ import annotations

import copy
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

import flexo
from flexo.chemistry.curly import lone_pair_spots
from flexo.chemistry.draw import _edge, _free_angle
from flexo.chemistry.electrons import Arrow, MechanismError, read_arrow
from flexo.chemistry.molecule import Molecule, mapped_smiles
from flexo.compiler import compile_figure
from flexo.diagnostics import FlexoError
from flexo.ir.semantic import FigureSpec
from flexo.mechanism import mechanism_composed, mechanism_states, place_record
from flexo.studio.figure_edit import EditError
from flexo.themes import figure_palette, figure_style

OPTIONS = ("lone_pairs", "charges", "arrow_colour")
"""The mechanism's own settings a sheet is drawn with."""

_BOND = {1: "-", 2: "=", 3: "#"}


def normal_steps(steps: object) -> list[dict[str, Any]]:
    """A mechanism's steps as the editor keeps them: each a mapping, its arrows a list,
    its ``place`` a mapping."""

    written = [steps] if isinstance(steps, str) else list(steps or [])  # type: ignore[call-overload]
    out = []
    for step in written:
        item = {"smiles": step} if isinstance(step, str) else dict(step or {})
        arrows = item.get("arrows")
        if isinstance(arrows, str):
            item["arrows"] = [
                part.strip() for part in arrows.replace("\n", ";").split(";") if part.strip()
            ]
        elif arrows is None:
            item["arrows"] = []
        else:
            item["arrows"] = [str(part).strip() for part in arrows if str(part).strip()]
        if "place" in item:
            try:
                item["place"] = place_record(item["place"])
            except (ValueError, IndexError, TypeError, AttributeError) as error:
                raise EditError("This step\u2019s placement can\u2019t be read.") from error
            if not item["place"]:
                del item["place"]
        out.append(item)
    if not out:
        raise EditError("A mechanism needs at least one step.")
    return out


def sheet(
    steps: object,
    *,
    step: int,
    holding: Sequence[str] | None = None,
    options: Mapping[str, Any] | None = None,
    look: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The structure ``step`` (from 0) acts on, drawn to be drawn on -- in ``look`` (a
    figure's ``theme``, ``palette``, ``font``...), on its ``paper`` colour: ``svg``, its
    ``view`` (x, y, width, height, in the SVG's units), the ``bond`` length in them, its
    ``atoms`` (``index`` in the step, ``name``, ``number`` as arrows call it, ``x``,
    ``y``, its lone ``pairs`` as two dots each), its ``bonds`` (``atoms``, ``order``,
    ``x``, ``y`` of the middle), its ``molecules`` (their ``atoms``, the ``ids`` of what
    is drawn of them, whether they are ``placed`` by hand), its ``arrows`` in words, the
    atoms they ``name``, how many structures there are (``states``), and the
    ``problem``, if there is one."""

    written = normal_steps(steps)
    figure = _figure(written, options, only=step, holding=holding, look=look)
    node = figure.nodes[0]
    style = figure_style(figure)
    try:
        composed = mechanism_composed(node, style)
    except FlexoError as error:
        # Nothing to draw on: the first structure itself cannot be read.
        return {
            "svg": "",
            "states": 0,
            "steps": len(written),
            "step": 0,
            "atoms": [],
            "bonds": [],
            "arrows": [],
            "named": [],
            "molecules": [],
            "problem": _problem(error.diagnostics[0]),
        }
    panels = composed.panels
    chosen = min(max(step, 0), len(panels) - 1)
    drawn, shown, renumber = composed.drawn[chosen]
    panel = panels[chosen]
    compilation = compile_figure(figure, style=style)
    fitted = next(item for item in compilation.fitted.nodes if item.measured.spec.id == node.id)
    size = composed.picture.size
    dx = fitted.bounds.x + (fitted.bounds.width - size.width) / 2.0
    dy = fitted.bounds.y + (fitted.bounds.height - size.height) / 2.0
    # The page cut down to the structure, with room round it for arrows and pairs: by its
    # atoms, not its arrows, so that an arrow drawn does not move it.
    xs, ys = [], []
    for place in drawn.atoms.values():
        xs.append(place.point[0])
        ys.append(place.point[1])
        if place.label is not None:
            xs += [place.label[0], place.label[2]]
            ys += [place.label[1], place.label[3]]
    room = composed.pen.bond * 1.25
    view = (
        min(xs) + dx - room,
        min(ys) + dy - room,
        max(xs) - min(xs) + 2 * room,
        max(ys) - min(ys) + 2 * room,
    )
    back = {new: old for old, new in renumber.items()}
    molecule = panel.molecule
    # The pairs this step's arrows take are drawn at their tails; the rest are offered.
    given = Counter(
        renumber[arrow.source[0]]
        for arrow in panel.arrows
        if len(arrow.source) == 1 and arrow.electrons == 2
    )
    ink = _arrow_points(drawn)
    atoms = []
    for index, place in drawn.atoms.items():
        original = back[index]
        spots = lone_pair_spots(shown, drawn, composed.pen, index, given[index])
        # Its number keeps off the pairs shown under the pointer, as off what is drawn.
        middles = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in spots]
        atoms.append(
            {
                "index": original,
                "element": molecule.atoms[original].element,
                "name": molecule.name(original),
                "number": _number(molecule, original),
                "x": round(place.point[0] + dx, 2),
                "y": round(place.point[1] + dy, 2),
                "pairs": [
                    [
                        round(a[0] + dx, 2),
                        round(a[1] + dy, 2),
                        round(b[0] + dx, 2),
                        round(b[1] + dy, 2),
                    ]
                    for a, b in spots
                ],
                "radical": bool(molecule.atoms[original].lone % 2),
                "tag": _tag(place, composed.pen, dx, dy, ink + middles),
            }
        )
    bonds = []
    for bond in shown.bonds:
        (ax, ay), (bx, by) = drawn.atoms[bond.a].point, drawn.atoms[bond.b].point
        bonds.append(
            {
                "atoms": [back[bond.a], back[bond.b]],
                "order": bond.order,
                "x": round((ax + bx) / 2 + dx, 2),
                "y": round((ay + by) / 2 + dy, 2),
            }
        )
    arrows = []
    for text in panel.step.arrows if chosen < len(written) else []:
        try:
            arrows.append({"text": text, "said": said(read_arrow(text, molecule), molecule)})
        except MechanismError as error:
            arrows.append({"text": text, "said": "", "problem": str(error)})
    named = sorted({atom for arrow in panel.arrows for atom in (*arrow.source, *arrow.target)})
    prefix = f"{node.id}.step{chosen + 1}"
    placed = {molecule.index_of(number) for number in panel.step.place}
    molecules = []
    for fragment in shown.fragments():
        members = set(fragment)
        ids = [
            f"{prefix}.{part}{index}"
            for index in fragment
            for part in ("atom", "charge", "pair", "radical")
        ]
        ids += [
            f"{prefix}.bond{number}" for number, bond in enumerate(shown.bonds) if bond.a in members
        ]
        originals = [back[index] for index in fragment]
        molecules.append({"atoms": originals, "ids": ids, "placed": bool(placed & set(originals))})
    return {
        "svg": _cropped(compilation.document.text, view),
        "view": [round(value, 2) for value in view],
        "bond": round(composed.pen.bond, 3),
        "dot": round(composed.pen.dot, 3),
        "paper": figure_palette(figure).get("canvas"),
        "molecules": molecules,
        "states": len(panels),
        "steps": len(written),
        "step": chosen,
        "atoms": atoms,
        "bonds": bonds,
        "arrows": arrows,
        "named": named,
        "problem": _problem(composed.problem) if composed.problem is not None else None,
    }


def add_arrow(
    steps: object,
    *,
    step: int,
    tail: Mapping[str, Any],
    head: Mapping[str, Any],
    half: bool = False,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The arrow from ``tail`` to ``head`` -- each ``{"atom": index}`` (a lone pair, or
    the atom electrons settle on or bond to) or ``{"bond": [index, index]}`` -- written
    into ``step``: ``{"steps", "arrow"}``. A bond's electrons sent to an atom outside it
    make a bond from one of its ends, and which is asked: ``{"ends": [{index, name}]}``.
    The structure after the last step takes arrows as a new step."""

    written = normal_steps(steps)
    panels, _ = mechanism_states(_figure(written, options).nodes[0])
    if not 0 <= step < len(panels):
        raise EditError("This structure can\u2019t be drawn because an earlier step has a problem.")
    molecule = panels[step].molecule.copy()
    count = len(molecule.atoms)
    ends = [_atoms(tail, count), _atoms(head, count)]
    source, target = ends
    if len(source) == 2 and molecule.bond(*source) is None:
        raise EditError("Those two atoms aren\u2019t bonded.")
    if len(source) == 2 and len(target) == 1 and target[0] not in source:
        return {"ends": [{"index": atom, "name": molecule.name(atom)} for atom in source]}
    if len(source) == 1 and len(target) == 2:
        if source[0] not in target:
            raise EditError(
                f"A lone pair on {molecule.name(source[0])} forms a bond to an atom. "
                "Click the atom."
            )
        target = [atom for atom in target if atom != source[0]]
    if len(source) == 1 and target == source:
        raise EditError("The electrons must go somewhere else. Click where they go.")
    origin = max(
        index for index in range(min(step, len(written) - 1) + 1) if written[index].get("smiles")
    )
    numbers = {atom: _numbered(written, origin, molecule, atom) for atom in {*source, *target}}

    def end(atoms: list[int], first: bool) -> str:
        if len(atoms) == 1:
            return str(numbers[atoms[0]])
        bond = molecule.bond(*atoms)
        mark = _BOND[bond.order] if first and bond is not None else "-"
        return f"{numbers[atoms[0]]}{mark}{numbers[atoms[1]]}"

    text = f"{end(source, True)} {'~>' if half else '->'} {end(target, False)}"
    try:
        read_arrow(text, molecule)
    except MechanismError as error:
        raise EditError(str(error)) from None
    if step >= len(written):
        written.append({"arrows": [text]})
    else:
        if any(_same(text, other, molecule) for other in written[step]["arrows"]):
            raise EditError("That arrow already exists.")
        written[step]["arrows"].append(text)
    return {"steps": written, "arrow": text}


def place_molecule(
    steps: object,
    *,
    step: int,
    atom: int,
    move: Sequence[float] | None = None,
    turn: float = 0.0,
    flip: bool = False,
    reset: bool = False,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The molecule of structure ``step`` that has ``atom`` (its index there) moved by
    ``move`` (bond lengths, y down), turned by ``turn`` (degrees, clockwise) or flipped
    left for right, as it is seen -- or, with ``reset``, put back where it is laid out:
    ``{"steps"}``. The structure after the last step is placed as a new step with no
    arrows, which draws the same."""

    written = normal_steps(steps)
    panels, _ = mechanism_states(_figure(written, options).nodes[0])
    if not 0 <= step < len(panels):
        raise EditError("This structure can\u2019t be drawn because an earlier step has a problem.")
    molecule = panels[step].molecule.copy()
    if not 0 <= atom < len(molecule.atoms):
        raise EditError("That atom no longer exists. Someone else may have changed the structure.")
    fragment = next(group for group in molecule.fragments() if atom in group)
    origin = max(
        index for index in range(min(step, len(written) - 1) + 1) if written[index].get("smiles")
    )
    if step >= len(written):
        written.append({"arrows": []})
    place = place_record(written[step].get("place"))
    key = next((name for name in place if molecule.index_of(int(name)) in fragment), None)
    if key is None:
        named = next(
            (index for index in sorted(fragment) if _number(molecule, index) is not None), None
        )
        key = str(
            _number(molecule, named)
            if named is not None
            else _numbered(written, origin, molecule, atom)
        )
    how = {} if reset else dict(place.get(key, {}))
    if move is not None:
        x, y = how.get("move", [0.0, 0.0])
        how["move"] = [round(float(x) + float(move[0]), 2), round(float(y) + float(move[1]), 2)]
        if how["move"] == [0.0, 0.0]:
            del how["move"]
    if flip:
        # Mirrored as it is seen: a turn already made turns the other way.
        how["flip"] = not how.get("flip")
        if how.get("turn"):
            how["turn"] = -float(how["turn"])
    if turn:
        angle = (float(how.get("turn", 0.0)) + float(turn)) % 360.0
        how["turn"] = round(angle - 360.0 if angle > 180.0 else angle, 1)
    how = {name: value for name, value in how.items() if value}
    if how:
        place[key] = how
    else:
        place.pop(key, None)
    if place:
        written[step]["place"] = place
    else:
        written[step].pop("place", None)
    return {"steps": written}


def remove_arrow(steps: object, *, step: int, index: int) -> dict[str, Any]:
    """``step`` without its arrow ``index``: ``{"steps"}``."""

    written = normal_steps(steps)
    try:
        written[step]["arrows"].pop(index)
    except (IndexError, KeyError) as error:
        raise EditError(
            "That arrow no longer exists. Someone else may have changed the step."
        ) from error
    return {"steps": written}


def said(arrow: Arrow, molecule: Molecule) -> str:
    """An arrow in words: "lone pair on O5 → C2", "C2=O3 bond → O3"."""

    def end(atoms: tuple[int, ...], first: bool) -> str:
        if len(atoms) == 2:
            bond = molecule.bond(*atoms)
            mark = _BOND.get(bond.order, "-") if bond is not None else "-"
            return f"{molecule.name(atoms[0])}{mark}{molecule.name(atoms[1])} bond"
        if first:
            what = (
                "radical"
                if arrow.electrons == 1 and molecule.atoms[atoms[0]].lone % 2
                else "lone pair"
            )
            return f"{what} on {molecule.name(atoms[0])}"
        return molecule.name(atoms[0])

    pointer = "⇀" if arrow.electrons == 1 else "→"
    return f"{end(arrow.source, True)} {pointer} {end(arrow.target, False)}"


def _figure(
    steps: list[dict[str, Any]],
    options: Mapping[str, Any] | None,
    *,
    only: int | None = None,
    holding: Sequence[str] | None = None,
    look: Mapping[str, Any] | None = None,
) -> FigureSpec:
    properties: dict[str, object] = {"partial": True}
    if only is not None:
        properties["only"] = int(only) + 1
        # Every hydrogen written as an atom is there to be pointed at, moved by an arrow
        # or not yet: none is folded back into its neighbour's label.
        properties["hydrogens"] = "kept"
        if holding is not None:
            properties["holding"] = [{"step": int(only) + 1, "arrows": "; ".join(holding)}]
    chosen = {
        key: value for key, value in (options or {}).items() if key in OPTIONS and value is not None
    }
    settings = {key: value for key, value in (look or {}).items() if value is not None}
    try:
        figure = flexo.Figure("sheet", background=True, **settings)
    except (ValueError, TypeError, OSError):
        figure = flexo.Figure("sheet", background=True)  # a look flexo cannot read: its own
    with figure:
        figure.root.mechanism("m", copy.deepcopy(steps), properties=properties, **chosen)
    return figure.spec


def _atoms(end: Mapping[str, Any], count: int) -> list[int]:
    value = end.get("bond") if "bond" in end else [end.get("atom")]
    try:
        atoms = [int(atom) for atom in value]  # type: ignore[union-attr]
    except (TypeError, ValueError) as error:
        raise EditError("An arrow must start and end at an atom or a bond.") from error
    if (
        not 1 <= len(atoms) <= 2
        or len(set(atoms)) != len(atoms)
        or not all(0 <= a < count for a in atoms)
    ):
        raise EditError("That atom no longer exists. Someone else may have changed the structure.")
    return atoms


def _number(molecule: Molecule, atom: int) -> int | None:
    """What an arrow calls an atom: its map, or its place in a molecule with no maps."""

    if molecule.atoms[atom].map is not None:
        return molecule.atoms[atom].map
    if not any(item.map is not None for item in molecule.atoms):
        return atom + 1
    return None


def _numbered(steps: list[dict[str, Any]], origin: int, molecule: Molecule, atom: int) -> int:
    """An atom's number for an arrow -- given one, in the SMILES that wrote it, if it has
    none while others do."""

    number = _number(molecule, atom)
    if number is not None:
        return number
    used = [
        int(found)
        for step in steps
        for found in re.findall(r":(\d+)\]", str(step.get("smiles") or ""))
    ]
    number = max(used, default=0) + 1
    steps[origin]["smiles"] = mapped_smiles(str(steps[origin]["smiles"]), atom, number)
    molecule.atoms[atom].map = number
    return number


def _same(text: str, other: str, molecule: Molecule) -> bool:
    try:
        first, second = read_arrow(text, molecule), read_arrow(other, molecule)
    except MechanismError:
        return False
    return (first.source, first.target, first.electrons) == (
        second.source,
        second.target,
        second.electrons,
    )


def _arrow_points(drawn) -> list[tuple[float, float]]:
    """Points along the arrows drawn (their ends, and their curves' handles)."""

    points = []
    for shape in drawn.shapes:
        if ".arrow" in shape.id:
            numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", shape.d)]
            points += list(zip(numbers[0::2], numbers[1::2], strict=False))
    return points


def _tag(place, pen, dx: float, dy: float, ink: list[tuple[float, float]]) -> list[float]:
    """Where an atom's number is written in the editor: beside it, on its freest side --
    clear of its bonds, its marks, and the arrows near it."""

    x, y = place.point
    near = [
        math.atan2(py - y, px - x)
        for px, py in ink
        if 0 < math.dist((px, py), (x, y)) < pen.bond * 0.9
    ]
    angle = _free_angle([*place.taken, *near], -math.pi / 4)
    reach = _edge(place, angle, pen) + pen.bond * 0.2
    return [
        round(place.point[0] + math.cos(angle) * reach + dx, 2),
        round(place.point[1] + math.sin(angle) * reach + dy, 2),
    ]


def _cropped(svg: str, view: tuple[float, float, float, float]) -> str:
    """The SVG showing only ``view`` of its page."""

    x, y, width, height = (f"{value:.2f}" for value in view)

    def root(match: re.Match[str]) -> str:
        tag = re.sub(r'\sviewBox="[^"]*"', f' viewBox="{x} {y} {width} {height}"', match.group(0))
        tag = re.sub(r'\swidth="[^"]*"', f' width="{width}pt"', tag)
        return re.sub(r'\sheight="[^"]*"', f' height="{height}pt"', tag)

    return re.sub(r"<svg\b[^>]*>", root, svg, count=1)


def _problem(diagnostic) -> dict[str, Any]:
    return {"message": diagnostic.message, "hint": diagnostic.hint, "code": diagnostic.code}
