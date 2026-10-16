"""Structures that share a frame: one camera, one scale, one centre, for a series of molecules.

A run of structures -- a diffusion model's trajectory from noise to the folded protein, the
states of a motor, a motif scaffolded five ways -- reads as one only when each is seen the same
way. Drawn alone, each is fitted to its own box (mol-sketch's ``zoom`` 1 fits what is drawn), so
a small ball of noise is drawn as large as the protein it becomes; and each is turned about its
own axes (mol-sketch starts every molecule along its principal axes), so the same ``yaw`` turns
two of them differently. Structures that name the same frame are drawn as one::

  nodes:
    - {id: t100, kind: structure, label: "[t]{italic} = 100",
       properties: {source: frames/t100.pdb, frame: diffusion, yaw: 20, pitch: -10}}
    - {id: t0, kind: structure, label: "[t]{italic} = 0",
       properties: {source: frames/t000.pdb, frame: diffusion}}

- **One camera.** Each is turned as the frame's first (its **owner**: the first of them in the
  figure's ``nodes``) is turned by its ``yaw``, ``pitch`` and ``roll`` -- the same way in space,
  their coordinates read in one frame, whatever axes mol-sketch would start each along. So the
  owner is drawn as it would be alone, and the others are seen from where it is seen. A noised
  structure (``flexo.structure_noise``) is framed as mol-sketch draws it -- the noised
  molecule's atoms -- and its turn read against the file's axes, as it is alone: copies of one
  file at several noises are one camera in the file's own coordinates, what they hold fixed
  in one place in every box.
- **One scale.** Each is drawn at the same ångströms to the point: the scale at which every one
  of them, drawn about the frame's centre, fits its own box -- the largest's -- times the owner's
  ``zoom``. The ball of noise is drawn small, and grows.
- **One centre.** Each is drawn about the middle of what they all draw together (the box round
  all their drawn atoms, turned, as mol-sketch frames one molecule), moved by the owner's
  ``pan_x`` and ``pan_y`` (shares of the owner's box): a motif held fixed, or a trajectory
  aligned, stays where it is from one to the next.

Each keeps its own box (``width``, ``height``), look, colours and what it draws; the frame's
settings (``FRAME_KEYS``) are the owner's, and another's own are not used (said, where they
differ: ``frame_problems``). The studio writes them on every member alike, so that whichever
comes first is the owner with the same settings.

The frame is worked out against mol-sketch's own camera (its ``computeFit`` and
``makeProjector``): each member is drawn by mol-sketch with a turn, zoom and pan of its own
(``framed``) that put its atoms where the frame's camera puts them. With a flat projection (the
engraved, textbook and flat looks) they are exactly there. With perspective (a field of view),
each is seen from the frame's eye, the same distance away; exact at the frame's centre, and off
by a share of the perspective elsewhere for a member far off that centre.
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass, replace

from flexo.diagnostics import Diagnostic, Severity
from flexo.ir.semantic import FigureSpec, NodeSpec, Settings
from flexo.style import LayoutStyle, Palette

FRAME_KEYS = ("yaw", "pitch", "roll", "zoom", "pan_x", "pan_y")
"""A structure's settings that are its frame's: the owner's are used for every member."""

LONG_SIDE = 1200
"""The long side of the drawing mol-sketch makes of a structure (``flexo.structures._render``)."""


def frame_of(node: NodeSpec) -> str | None:
    """The frame a structure names, or None."""

    if node.kind != "structure":
        return None
    name = node.property("frame")
    if isinstance(name, bool) or not isinstance(name, str | int | float):
        return None
    return str(name).strip() or None


def frames_of(spec: FigureSpec) -> dict[str, tuple[NodeSpec, ...]]:
    """Each frame the figure's structures name, with those that name it, in the order of the
    figure's ``nodes``: the first is its owner."""

    found: dict[str, list[NodeSpec]] = {}
    for node in spec.nodes:
        name = frame_of(node)
        if name is not None:
            found.setdefault(name, []).append(node)
    return {name: tuple(members) for name, members in found.items()}


def framed(spec: FigureSpec, style: LayoutStyle) -> FigureSpec:
    """``spec`` with the structures of each frame of two or more drawn as the frame says: each
    given the turn, zoom and pan (and, in perspective, the field of view) mol-sketch draws it
    at for its atoms to be where the frame's camera puts them. A member that can't be drawn is
    left as it is, and out of the frame's reckoning."""

    frames = {name: members for name, members in frames_of(spec).items() if len(members) > 1}
    if not frames:
        return spec
    cameras: dict[str, dict[str, float]] = {}
    for members in frames.values():
        cameras |= _cameras(members, style)
    if not cameras:
        return spec
    return replace(
        spec, nodes=tuple(_with_camera(node, cameras[node.id]) if node.id in cameras else node
                          for node in spec.nodes),
    )


def frame_problems(spec: FigureSpec) -> list[Diagnostic]:
    """A member's own frame settings that differ from the owner's, which are used instead, as
    warnings: each says which is used."""

    said = []
    for name, members in frames_of(spec).items():
        owner = members[0]
        for node in members[1:]:
            differ = [
                key for key in FRAME_KEYS
                if node.property(key) is not None and node.property(key) != owner.property(key)
            ]
            if not differ:
                continue
            listed = ", ".join(differ[:-1]) + (" and " if len(differ) > 1 else "") + differ[-1]
            said.append(Diagnostic(
                "structure.frame",
                f"{node.id}\u2019s {listed} {'is' if len(differ) == 1 else 'are'} not used: the "
                f"structures in frame {name} are turned and framed as {owner.id}, the first "
                "of them, is.",
                Severity.WARNING,
                entity_id=node.id,
                hint=f"Turn, zoom or move {owner.id}, or any of them in the studio.",
            ))
    return said


# -- the frame worked out --


@dataclass(frozen=True, slots=True)
class _Geometry:
    """What a member is framed by, as mol-sketch draws it: the atoms its framing is fitted to
    (``fitPoints``, in the file's coordinates: of the molecule drawn, noised or not), the axes
    mol-sketch starts it along (``base``: its scene's coordinates are ``base @ p``), the axes
    its ``yaw``, ``pitch`` and ``roll`` are read against (``seen``: its own, ``base`` -- but a
    noised structure's are the file's, as ``flexo.structure_noise`` turns it to be seen as
    the file is), and the camera it is drawn with unturned (its turn, as it is read)."""

    points: object  # (n, 3) numpy array
    base: object  # (3, 3) numpy array
    camera: tuple[tuple[str, float], ...]
    seen: object  # (3, 3) numpy array


def _box(node: NodeSpec, style: LayoutStyle) -> tuple[float, float]:
    """A structure's box, in points, as ``flexo.structures.structure_drawing`` sizes it."""

    from flexo.drawn import units

    u = units(style).u
    width = float(node.property("width") or 20.0 * u)  # type: ignore[arg-type]
    height = float(node.property("height") or 15.0 * u)  # type: ignore[arg-type]
    return width, height


def _canvas(box: tuple[float, float]) -> tuple[int, int]:
    """The drawing mol-sketch makes for a box (as ``flexo.structures._render`` sizes it)."""

    aspect = box[0] / box[1]
    if aspect >= 1:
        return LONG_SIDE, round(LONG_SIDE / aspect)
    return round(LONG_SIDE * aspect), LONG_SIDE


def _unpainted(node: NodeSpec, style: LayoutStyle):
    """What the structure is drawn from, but its colours and its camera: what its framing is
    fitted to does not change with them. None, for one that can't be had."""

    from flexo.diagnostics import FlexoError
    from flexo.structures import _ask

    # (Its colours, tones among them, are checked and said where it is drawn.)
    bare = replace(node, properties=tuple(
        (key, value) for key, value in node.properties if key != "colors"
    ))
    try:
        return _ask(bare, style, Palette("framing", {}, ()))
    except FlexoError:
        return None


def _geometry_of(node: NodeSpec, style: LayoutStyle) -> tuple[object, _Geometry] | None:
    """What ``node`` is drawn from and what it is framed by -- or None, for one that can't be
    had (drawn as a panel saying why, outside the frame: not asked of again)."""

    from flexo.structures import _one_at_a_time, _problem

    problem = _problem(node, style)
    if problem is not None and not problem.drawn:
        return None
    ask = _unpainted(node, style)
    if ask is None:
        return None
    plain = replace(ask, colours=(), roles=(), paints=(), paper="#ffffff", view=(), pan=None)
    try:
        return ask, _one_at_a_time(_geometry, plain)
    except Exception:  # mol-sketch failing it: said where it is drawn
        return None


@functools.lru_cache(maxsize=64)
def _geometry(ask) -> _Geometry:
    import numpy as np

    from flexo.structures import _drawn, _noised

    spec = _drawn(ask)._spec()
    # (A density map is not what it is framed on here: left out of what is asked.)
    spec.pop("map", None)
    settled = _settled(spec)
    camera = settled["camera"]
    base = settled["base"] or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    # (Column by column, as mol-sketch keeps a matrix: row r of the turn is base[r], [r+4], [r+8].)
    turn = np.array([[base[r + 4 * c] for c in range(3)] for r in range(3)], dtype=float)
    # A scene is framed on the atoms of all its steps, in its own coordinates.
    points = settled["points"] or settled["scene"]
    held = np.asarray(points or [0.0, 0.0, 0.0], dtype=float).reshape(-1, 3)
    unturned = {
        key: float(camera.get(key) or (1.0 if key == "zoom" else 0.0))
        for key in ("yaw", "pitch", "roll", "zoom", "panX", "panY", "fov")
    }
    noised = _noised(ask)
    if noised is None:
        return _Geometry(held, turn, tuple(unturned.items()), turn)
    # Noised, mol-sketch reads the molecule along its own axes, and flexo turns it back to be
    # seen as the file is (``noised.turn``, from its scene to the file's): its turn is read
    # against the file's axes, unturned the file's.
    unturned |= {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}
    return _Geometry(held, turn, tuple(unturned.items()), np.array(noised.turn) @ turn)


_FIT = """MolSketchCore.flexoFit = (spec) => {
  const f = MolSketchCore.settle(spec), c = f.camera;
  const steps = f.scene ? (f.scene.keyframes || [])
    .map((k) => Object.values(k.atoms || {}).map((a) => a.pos)) : [];
  return {
    points: Array.from(f.fitPoints || []), base: Array.from(c.base || []), scene: steps.flat(2),
    camera: { yaw: c.yaw, pitch: c.pitch, roll: c.roll, zoom: c.zoom, panX: c.panX, panY: c.panY,
              fov: c.fov },
  };
};"""
"""What a structure is framed by, asked of mol-sketch's engine (its ``settle``): only that, not
the whole molecule ``settle`` hands back -- a tenth of the time for a large one."""


def _settled(spec: dict) -> dict:
    from molsketch._engine import engine

    running = engine()
    taught = getattr(running, "_flexo_fit", None)
    if taught is None:
        try:
            running.v8.eval(_FIT)
            taught = True
        except Exception:  # an engine of another make: asked for all of it
            taught = False
        running._flexo_fit = taught
    if taught:
        return running.call("flexoFit", spec)
    settled = running.call("settle", spec)
    steps = (settled.get("scene") or {}).get("keyframes") or ()
    return {
        "points": _listed(settled.get("fitPoints"), None),
        "base": _listed(settled["camera"].get("base"), 16),
        "scene": [value for step in steps for atom in (step.get("atoms") or {}).values()
                  for value in atom["pos"]],
        "camera": settled["camera"],
    }


def _listed(value: object, count: int | None) -> list[float]:
    """A typed array as mol-sketch's engine hands it over: a list, or ``{"0": x, ...}``."""

    if isinstance(value, list):
        return [float(item) for item in value]
    if isinstance(value, dict):
        return [float(value[str(index)]) for index in range(count or len(value))]
    return []


def turned(yaw: float, pitch: float, roll: float):
    """mol-sketch's turn (its ``rot3``): about y by ``yaw``, then x by ``pitch``, then z by
    ``roll``, in degrees; y up."""

    import numpy as np

    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
    about_y = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    about_x = np.array([[1.0, 0.0, 0.0], [0.0, cp, -sp], [0.0, sp, cp]])
    about_z = np.array([[cr, -sr, 0.0], [sr, cr, 0.0], [0.0, 0.0, 1.0]])
    return about_z @ about_x @ about_y


def angles(turn) -> tuple[float, float, float]:
    """The ``yaw``, ``pitch`` and ``roll`` that make the turn ``turn`` (``turned``'s inverse):
    pitch between -90 and 90 degrees."""

    pitch = math.degrees(math.asin(max(-1.0, min(1.0, float(turn[2][1])))))
    if abs(float(turn[2][1])) < 1 - 1e-9:
        yaw = math.degrees(math.atan2(-float(turn[2][0]), float(turn[2][2])))
        roll = math.degrees(math.atan2(-float(turn[0][1]), float(turn[1][1])))
    else:  # looked at straight down: the yaw is the roll
        yaw = 0.0
        roll = math.degrees(math.atan2(float(turn[1][0]), float(turn[0][0])))
    return yaw, pitch, roll


@dataclass(frozen=True, slots=True)
class Framing:
    """A frame worked out: its turn (``turn @ p``, of a point in the file's coordinates, is it
    in the frame's view: x right, y up, z towards the eye), its centre in that view
    (``centre``, x and y; ``depth``, z), the scale every member is drawn at (``scale``, points
    to the ångström, at the centre's depth), the eye's distance (``eye``, in ångströms;
    infinite, a flat projection), and the shift of the centre in points (``shift``, x right,
    y down)."""

    turn: object
    centre: tuple[float, float]
    depth: float
    scale: float
    eye: float
    shift: tuple[float, float]


def framing(owner_camera: dict[str, float], owner_base, owner_box, members) -> Framing:
    """The frame of ``members`` -- each ``(points, base, box)``, its fit points in the file's
    coordinates and its box in points -- seen with the owner's camera (mol-sketch's names:
    ``yaw``, ``pitch``, ``roll``, ``zoom``, ``panX``, ``panY``, ``fov``) from its axes."""

    import numpy as np

    turn = turned(owner_camera["yaw"], owner_camera["pitch"], owner_camera["roll"]) @ owner_base
    views = [points @ turn.T for points, _, _ in members]
    every = np.concatenate(views)
    low, high = every.min(axis=0), every.max(axis=0)
    centre = ((low[0] + high[0]) / 2.0, (low[1] + high[1]) / 2.0)
    spans = np.maximum(high - low, 1.0)
    # (The depth it is seen at, as mol-sketch has it: the middle of the box round them along
    # the owner's axes, turned.)
    along = np.concatenate([points @ owner_base.T for points, _, _ in members])
    middle = (along.min(axis=0) + along.max(axis=0)) / 2.0
    depth = float((turned(owner_camera["yaw"], owner_camera["pitch"], owner_camera["roll"])
                   @ middle)[2])
    opening = math.radians(owner_camera["fov"])
    eye = (max(spans[0], spans[1]) / 2.0 + 1.5) / math.tan(opening / 2.0) if opening > 2e-3 \
        else math.inf
    nearer = 1.0 if eye == math.inf else eye / max(eye - spans[2] / 2.0, eye * 0.3)
    fits = []
    for view, (_, _, box) in zip(views, members, strict=True):
        width, height = _canvas(box)
        across = max(2.0 * float(np.abs(view[:, 0] - centre[0]).max()), 1.0)
        up = max(2.0 * float(np.abs(view[:, 1] - centre[1]).max()), 1.0)
        pixels = min(width * 0.9 / (across + 2.6), (height - 24) / (up + 2.4)) / nearer**0.7
        fits.append(pixels * _points_per_pixel(box))
    scale = min(fits) * owner_camera["zoom"]
    width, height = _canvas(owner_box)
    shift = (owner_camera["panX"] * width * _points_per_pixel(owner_box),
             owner_camera["panY"] * height * _points_per_pixel(owner_box))
    return Framing(turn, (float(centre[0]), float(centre[1])), depth, scale, eye, shift)


def _points_per_pixel(box: tuple[float, float]) -> float:
    """How large a pixel of mol-sketch's drawing is in the box it is drawn into (centred, as
    large as fits)."""

    width, height = _canvas(box)
    return min(box[0] / width, box[1] / height)


def member_camera(frame: Framing, points, base, box, seen=None) -> dict[str, float]:
    """The camera a member is drawn with (``points``, ``base``, ``box`` as for ``framing``)
    for mol-sketch to draw its atoms where ``frame`` puts them: its own turn, zoom, pan and
    field of view, in mol-sketch's names. Its turn is read against ``seen`` (its own axes,
    ``base``, unless said): a noised structure's against the file's, as flexo turns a noised
    molecule (``flexo.structures._drawn``), so that it is drawn at the turn mol-sketch is to
    draw it at -- turned the once."""

    import numpy as np

    own = frame.turn @ base.T  # its scene's coordinates turned into the frame's view
    view = points @ frame.turn.T
    low, high = view.min(axis=0), view.max(axis=0)
    middle = ((low[0] + high[0]) / 2.0, (low[1] + high[1]) / 2.0)
    spans = np.maximum(high - low, 1.0)
    scened = points @ base.T
    depth = float((own @ ((scened.min(axis=0) + scened.max(axis=0)) / 2.0))[2])
    width, height = _canvas(box)
    per_pixel = _points_per_pixel(box)
    pixels = frame.scale / per_pixel  # pixels to the ångström, as the frame draws it
    fitted = min(width * 0.9 / (spans[0] + 2.6), (height - 24) / (spans[1] + 2.4))
    yaw, pitch, roll = angles(own if seen is None else frame.turn @ seen.T)
    if frame.eye == math.inf:
        zoom, fov = pixels / fitted, 0.0
    else:
        # Seen from the frame's eye: as far from its own middle as the eye is from it.
        reach = max(spans[0], spans[1]) / 2.0 + 1.5
        eye = max(frame.eye + frame.depth - depth, spans[2] / 2.0 + 1.5)
        nearer = eye / max(eye - spans[2] / 2.0, eye * 0.3)
        zoom = pixels * frame.eye / eye / (fitted / nearer**0.7)
        fov = math.degrees(2.0 * math.atan(reach / eye))
    pan_x = ((middle[0] - frame.centre[0]) * pixels + frame.shift[0] / per_pixel) / width
    pan_y = ((frame.centre[1] - middle[1]) * pixels + frame.shift[1] / per_pixel) / height
    return {"yaw": yaw, "pitch": pitch, "roll": roll, "zoom": float(zoom),
            "panX": float(pan_x), "panY": float(pan_y), "fov": fov}


def _owner_camera(ask, geometry: _Geometry) -> dict[str, float]:
    """The owner's camera: what it is drawn with unturned, its own view and pan over it."""

    camera = dict(geometry.camera)
    camera |= dict(ask.view)
    if ask.pan is not None:
        camera["panX"], camera["panY"] = ask.pan
    return camera


def _cameras(members: tuple[NodeSpec, ...], style: LayoutStyle) -> dict[str, dict[str, float]]:
    found = [(node, _geometry_of(node, style)) for node in members]
    known = [(node, held) for node, held in found if held is not None]
    if len(known) < 2:
        return {}
    (_, (owner_ask, owner)), owner_node = known[0], known[0][0]
    camera = _owner_camera(owner_ask, owner)
    boxes = {node.id: _box(node, style) for node, _ in known}
    frame = framing(camera, owner.seen, boxes[owner_node.id],
                    [(held.points, held.base, boxes[node.id]) for node, (_, held) in known])
    return {
        node.id: member_camera(frame, held.points, held.base, boxes[node.id], held.seen)
        for node, (_, held) in known
    }


def _with_camera(node: NodeSpec, camera: dict[str, float]) -> NodeSpec:
    """``node`` drawn with ``camera``: its turn, zoom and pan, and its field of view among its
    mol-sketch settings (``view.fov``)."""

    written = {
        "yaw": camera["yaw"], "pitch": camera["pitch"], "roll": camera["roll"],
        "zoom": camera["zoom"], "pan_x": camera["panX"], "pan_y": camera["panY"],
    }
    rounded = {key: round(value, 7) for key, value in written.items()}
    properties = [(key, value) for key, value in node.properties if key not in rounded]
    properties += list(rounded.items())
    style = node.property("style")
    items = list(style.items) if isinstance(style, Settings) else []
    items = [(key, value) for key, value in items if key != "view.fov"]
    items.append(("view.fov", round(camera["fov"], 7)))
    properties = [(key, value) for key, value in properties if key != "style"]
    properties.append(("style", Settings(tuple(items))))
    return replace(node, properties=tuple(properties))


# -- for the studio --


def framed_view(spec: FigureSpec, identifier: str, style: LayoutStyle,
                palette: Palette) -> dict[str, object]:
    """What the studio turns while a structure is dragged round (``structure_view``), framed:
    for a structure in a frame of two or more, its points in the frame's coordinates (the
    owner's scene's: turned by the frame's ``yaw``, ``pitch`` and ``roll`` they are where the
    frame's camera puts them), the frame's camera, and the frame (``shared``: its ``name``,
    ``owner`` and ``members``). Every structure also says the axes its turn is read against
    (``base``, rows, of the file's coordinates: its scene's, a noised one's file's) and -- in
    a frame -- the turn it would be drawn alone with to be seen as it is now (``alone``)."""

    import numpy as np

    from flexo.structures import structure_view

    node = next(item for item in spec.nodes if item.id == identifier)
    view = dict(structure_view(node, style, palette))
    held = _geometry_of(node, style)
    if held is None:
        return view
    view["base"] = _rows(held[1].seen)
    name = frame_of(node)
    members = frames_of(spec).get(name or "", ())
    if len(members) < 2:
        return view
    found = [(member, _geometry_of(member, style)) for member in members]
    known = [(member, geometry) for member, geometry in found if geometry is not None]
    if len(known) < 2 or not any(member.id == identifier for member, _ in known):
        return view
    owner_node, (owner_ask, owner) = known[0]
    camera = _owner_camera(owner_ask, owner)
    own = held[1]
    # This one's scene's coordinates (as the studio is told them: a noised one's, the file's)
    # into the owner's.
    into = owner.seen @ own.seen.T

    def moved(point):
        return [round(float(value), 2) for value in into @ np.asarray(point[:3], dtype=float)]

    view["centre"] = [round(float(value), 3) for value in into @ np.asarray(view["centre"])]
    view["chains"] = [[moved(point) for point in chain] for chain in view["chains"]]
    view["atoms"] = [[*moved(atom), *atom[3:]] for atom in view["atoms"]]
    view["fit"] = _outermost(own.points @ owner.seen.T)
    view["camera"] = {
        "yaw": camera["yaw"], "pitch": camera["pitch"], "roll": camera["roll"],
        "zoom": camera["zoom"], "pan_x": camera["panX"], "pan_y": camera["panY"],
        "fov": camera["fov"],
    }
    alone = angles(turned(camera["yaw"], camera["pitch"], camera["roll"]) @ into)
    # (In tenths of a degree, as the studio turns it.)
    view["alone"] = dict(zip(("yaw", "pitch", "roll"), (round(value, 1) for value in alone),
                             strict=True))
    view["shared"] = {
        "name": name, "owner": owner_node.id, "members": [member.id for member, _ in known],
        "base": _rows(owner.seen),
    }
    return view


def _rows(matrix) -> list[list[float]]:
    return [[round(float(value), 6) for value in row] for row in matrix]


_SIDES = 160
"""How many ways the outermost of a member's points are looked for (``structures._SIDES``)."""


def _outermost(points) -> list[list[float]]:
    """The points of ``points`` outermost one way or another: the box round them, turned any
    way, is within a hundredth of their reach of the box round them all."""

    import numpy as np

    if not len(points):
        return []
    turn = np.arange(_SIDES) + 0.5
    rise = 1 - 2 * turn / _SIDES
    around = np.pi * (1 + 5**0.5) * turn
    sides = np.concatenate([
        np.eye(3), -np.eye(3),
        np.stack([np.sqrt(1 - rise**2) * np.cos(around), np.sqrt(1 - rise**2) * np.sin(around),
                  rise], axis=1),
    ])
    chosen = sorted(set(np.argmax(points @ sides.T, axis=0).tolist()))
    return [[round(float(value), 2) for value in points[index]] for index in chosen]
