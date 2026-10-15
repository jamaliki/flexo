"""Convert to Figure Parts: shapes drawn over a figure made its parts, in its file's words.

A diagram pasted from Inkscape, or drawn over a figure with the Draw tools, is shapes: they
are drawn where they are put, in no theme and no layout. ``convert`` reads the shapes chosen
as the diagram they draw (``flexo.recognise``) and makes them the figure's own parts -- its
shapes, lines and groups, laid out as they were drawn -- so the figure's theme, spacing and
layout take them, and they are edited as anything built in flexo is. The shapes go; those
that were no part of the diagram (a highlight, a brace, a free curve) stay, attached to the
parts they were drawn at; and a shape elsewhere glued to one made a part is glued to the part.

The parts go into a new group where the shapes were: into the innermost group the drawing's
middle is in, among what that group holds by where the drawing was (in a row by its left, a
column by its top). One part, or one group, goes in as it is, with no group of its own round
it; and a figure with nothing of its own yet (none, or its one shape with no words that a new
figure starts with) is made the diagram, its root laid out as the drawing was.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from flexo.figure_shapes import shape_names
from flexo.recognise import Recognised, recognise

OWN = ("on", "around", "margin", "side")
"""What a shape over a figure says of where it is that a shape placed has no more need of."""


def convert(document: Any, action: Mapping[str, Any]) -> list[str]:
    """``action``'s shapes (``shapes``: their places in the figure's list) made the figure's
    parts, made to ``document`` (a ``figure_edit._Document``); the ids of what was made.

    The page may say where each shape and part is drawn -- ``placed``, each chosen shape as
    it is placed (as many as ``shapes``), and ``boxes``, each part's ``[x, y, w, h]`` -- else
    the figure is drawn here to find out."""

    from flexo.studio.figure_edit import EditError

    shapes = document.shapes
    picks = sorted({int(index) for index in action.get("shapes") or []})
    if not picks or any(not 0 <= index < len(shapes) for index in picks):
        raise EditError("Choose the shapes drawn over the figure to make its parts.")
    look = _look(document)
    placed, boxes = action.get("placed"), action.get("boxes")
    if not isinstance(placed, list) or len(placed) != len(picks) or not isinstance(boxes, dict):
        placed, boxes = _drawn(document, picks, look)
    placed = [_free(item) for item in placed]
    empty = _empty(document)
    bare = bool(empty) or not any(isinstance(node, dict) for node in document.nodes)
    holder = document.root if bare else document.fresh("diagram")
    nodes = document.node_ids() - set(empty)
    chosen = {name for item in placed for name in shape_names(item)}
    found = _recognised(placed, chosen, look, document, boxes, nodes, holder)
    for gone in empty:
        document.nodes.remove(document.node(gone))
        document.detach(gone)
    # Where it goes, found before it is there (a root written now holds what the figure had).
    where = None if bare else _where(document, found, boxes)
    document.nodes.extend(found.nodes)
    if found.edges:
        document.data.setdefault("edges", []).extend(found.edges)
    made = _bare(document, found) if where is None else _place(document, found, holder, where)
    _reshape(document, picks, found, {*made, holder})
    document.summary = found.said
    return made


def _look(document: Any) -> dict[str, Any]:
    """The figure's colours and its words' size, which a drawing's are matched to."""

    from flexo.studio.figure_kind import parse
    from flexo.themes import figure_palette, figure_style, with_tone_roles

    try:
        spec = parse(document.dump(), document.base or Path.cwd(), suffix=_suffix(document))
    except Exception:  # (one that does not read is matched to the paper theme's)
        from flexo.themes import resolve_palette

        return {
            "palette": with_tone_roles(resolve_palette("paper", "default")),
            "words": 8.0,
            "style": "paper",
            "spec": None,
        }
    return {
        "palette": with_tone_roles(figure_palette(spec)),
        "words": figure_style(spec).typography.size.points,
        "style": spec.style,
        "spec": spec,
    }


def _suffix(document: Any) -> str:
    return ".json" if document.json else ".yaml"


def _drawn(
    document: Any, picks: list[int], look: Mapping[str, Any]
) -> tuple[list[Any], dict[str, Any]]:
    """Each chosen shape as the figure places it, and each part's box: the figure drawn."""

    from flexo.compiler import compile_figure
    from flexo.studio.figure_edit import EditError
    from flexo.studio.figure_kind import _drawn_over

    spec = look.get("spec")
    if spec is None:
        raise EditError("The figure must read before its shapes can be made its parts.")
    if not spec.nodes:
        return [_plain(document.shapes[index]) for index in picks], {}
    try:
        compilation = compile_figure(spec)
    except Exception as error:
        raise EditError(
            f"The figure must draw before its shapes can be made parts: {error}"
        ) from None
    said = _drawn_over(compilation, spec, [_plain(item) for item in document.shapes])
    placed = said["shapes"]
    found = [
        placed[index]
        if index < len(placed) and placed[index] is not None
        else _plain(document.shapes[index])
        for index in picks
    ]
    return found, said["boxes"]


def _free(spec: Any) -> dict[str, Any]:
    """A shape as placed, where it is drawn: no more on or round a part."""

    made = {key: value for key, value in dict(spec).items() if key not in OWN}
    if made.get("kind") == "group":
        made["shapes"] = [_free(child) for child in made.get("shapes") or []]
    return made


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _empty(document: Any) -> list[str]:
    """The figure's parts, if it has nothing of its own yet: none, or the one shape a new figure
    starts with, with no words, joined to nothing and with nothing drawn on it."""

    nodes = [node for node in document.nodes if isinstance(node, dict)]
    if not nodes:
        return []
    if len(nodes) > 1 or document.edges or document.nets:
        return []
    (node,) = nodes
    label = node.get("label")
    if label or node.get("kind", "block") != "block" or node.get("properties"):
        return []
    from flexo.figure_shapes import attached

    identifier = str(node.get("id"))
    if any(
        identifier in attached(_plain(shape))
        for shape in document.shapes
        if isinstance(shape, dict)
    ):
        return []
    others = [group for group in document.groups if str(group.get("id")) != document.root]
    return [] if others else [identifier]


def _recognised(
    placed: list[dict[str, Any]],
    chosen: set[str],
    look: Mapping[str, Any],
    document: Any,
    boxes: Mapping[str, Any],
    nodes: set[str],
    holder: str,
) -> Recognised:
    from flexo.studio.figure_edit import EditError

    try:
        return recognise(
            placed,
            palette=look["palette"],
            # (The names of the shapes chosen are free: those that stay keep theirs.)
            taken=(document.taken() - chosen) | {holder},
            parts={key: value for key, value in boxes.items() if isinstance(value, list | tuple)},
            nodes=nodes,
            holder=holder,
            word_size=float(look["words"]),
            style=str(look["style"]),
        )
    except ValueError as error:
        raise EditError(str(error)) from None


def _bare(document: Any, found: Recognised) -> list[str]:
    """The diagram made the figure, which had nothing of its own: its root holds it, laid out
    as it was drawn."""

    groups = document.data.setdefault("groups", [])
    groups.extend(found.groups)
    only = found.groups[0] if found.groups else None
    if only is not None and found.top == [only["id"]] and only.get("role") == "layout":
        # (One arrangement: the root is it.)
        groups.remove(only)
        children, layout = list(only["children"]), dict(only["layout"])
        for shape in found.shapes:
            if shape.get("on") == only["id"]:
                shape["on"] = document.root
    else:
        children, layout = list(found.top), dict(found.layout or {"kind": "row"})
    root = document.group(document.root)
    if root is None:
        groups.insert(
            0, {"id": document.root, "children": children, "layout": layout, "role": "canvas"}
        )
    else:
        root["children"] = children
        kept = {
            key: value
            for key, value in (root.get("layout") or {}).items()
            if key not in ("kind", "columns", "placements", "equal_size", "align")
        }
        root["layout"] = {**layout, **kept}
    return children


def _place(
    document: Any, found: Recognised, holder: str, where: tuple[dict[str, Any], int]
) -> list[str]:
    """The diagram put into the figure where it was drawn: one part or group as it is, else a
    group (``holder``) of what it holds, laid out as drawn."""

    groups = document.data.setdefault("groups", [])
    if len(found.top) == 1:
        made = found.top[0]
    else:
        made = holder
        groups.append(
            {"id": holder, "children": list(found.top), "layout": found.layout, "role": "layout"}
        )
    groups.extend(found.groups)
    target, index = where
    target.setdefault("children", []).insert(index, made)
    return [made]


def _where(document: Any, found: Recognised, boxes: Mapping[str, Any]) -> tuple[dict, int]:
    """The group the diagram goes into -- the innermost the drawing's middle is in -- and its
    place there, by where it was drawn among what that group holds."""

    x0, y0, x1, y1 = found.box
    middle = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
    new = {group["id"] for group in found.groups}

    def holds(identifier: str) -> bool:
        box = boxes.get(identifier)
        return (
            bool(box)
            and box[0] <= middle[0] <= box[0] + box[2]
            and box[1] <= middle[1] <= box[1] + box[3]
        )

    inside = [
        group
        for group in document.groups
        if group.get("id") not in new
        and group.get("id") != document.root
        and group.get("role") != "layout"
        and holds(str(group.get("id")))
    ]
    target = (
        min(inside, key=lambda group: boxes[group["id"]][2] * boxes[group["id"]][3])
        if inside
        else document.written_root()
    )
    children = [str(child) for child in target.get("children") or []]
    layout = target.get("layout") or {}
    kind = layout.get("kind", "column") if isinstance(layout, Mapping) else "column"
    if layout.get("placements") if isinstance(layout, Mapping) else False:
        return target, len(children)

    def before(child: str) -> bool:
        box = boxes.get(child)
        if not box:
            return True
        if kind == "row":
            return box[0] + box[2] / 2.0 < middle[0]
        if kind == "grid":
            return (box[1] + box[3] < middle[1]) or (
                box[1] <= middle[1] and box[0] + box[2] / 2.0 < middle[0]
            )
        if kind in ("column", "stack"):
            return box[1] + box[3] / 2.0 < middle[1]
        return True

    index = 0
    for at, child in enumerate(children):
        if before(child):
            index = at + 1
    return target, index


def _reshape(document: Any, picks: list[int], found: Recognised, made: set[str]) -> None:
    """The figure's shapes after: those made parts gone, those kept attached to the parts,
    and an end glued to a shape made a part glued to the part."""

    old = document.shapes
    kept = dict(zip(found.kept, found.shapes, strict=True))
    new = {*made, *(node["id"] for node in found.nodes), *(group["id"] for group in found.groups)}
    shapes: list[Any] = []
    for index, item in enumerate(old):
        if index in picks:
            if index in kept:
                shapes.append(document.written_shape(_kept(item, kept[index], new, found.parts)))
            continue
        _reglue(document, item, found.parts)
        shapes.append(item)
    if not shapes:
        document.data.pop("shapes", None)
    else:
        document.data["shapes"][:] = shapes
    # Shown apart under its old name: under its part's.
    settings = document.data.get("figure")
    if isinstance(settings, dict):
        for key in ("hide", "dim", "highlight"):
            if isinstance(settings.get(key), list):
                settings[key][:] = list(
                    dict.fromkeys(found.parts.get(str(name), str(name)) for name in settings[key])
                )


def _kept(
    written: Any, attached: dict[str, Any], new: set[str], parts: Mapping[str, str]
) -> dict[str, Any]:
    """A shape kept: attached to the parts made, if it was drawn at them; else as it was
    written, where it was attached to the figure's own parts."""

    plain = _plain(written) if isinstance(written, Mapping) else {}
    tied = bool(attached.get("around")) or (
        attached.get("on") in new and attached.get("on") not in plain.get("around", [])
    )
    glued = any(
        isinstance(attached.get(key), dict) and attached[key].get("part") in new
        for key in ("from", "to")
    )
    if not (tied or glued) and any(plain.get(key) is not None for key in ("on", "around")):
        return _reglued(plain, parts)
    return attached


def _reglued(spec: dict[str, Any], parts: Mapping[str, str]) -> dict[str, Any]:
    for key in ("from", "to"):
        end = spec.get(key)
        if isinstance(end, dict) and end.get("shape") is not None and str(end["shape"]) in parts:
            spec[key] = {
                "part": parts[str(end["shape"])],
                **{name: end[name] for name in ("side", "at") if name in end},
            }
    if spec.get("kind") == "group":
        spec["shapes"] = [_reglued(dict(child), parts) for child in spec.get("shapes") or []]
    return spec


def _reglue(document: Any, item: Any, parts: Mapping[str, str]) -> None:
    """``item``, a shape the file has, its ends glued to shapes made parts glued to the parts,
    the rest of it as written."""

    if not isinstance(item, dict):
        return
    for key in ("from", "to"):
        end = item.get(key)
        if isinstance(end, dict) and end.get("shape") is not None and str(end["shape"]) in parts:
            glue = {"part": parts[str(end["shape"])]}
            glue.update({name: _plain(end[name]) for name in ("side", "at") if name in end})
            item[key] = document.written(key, glue)
    if item.get("kind") == "group":
        for child in item.get("shapes") or []:
            _reglue(document, child, parts)
