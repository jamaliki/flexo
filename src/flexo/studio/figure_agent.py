"""A figure file as an agent reads it in brief, names what it sees on it, finds what is selected
in it, and hears what its edit did (``outline``, ``marks``, ``selected``, ``report``: the
figure kind's, for ``flexo.studio.agent``)."""

from __future__ import annotations

from typing import Any

import yaml

from flexo.studio.agent_look import Mark
from flexo.studio.agent_read import todos, warnings

LISTED = 120
"""Parts an outline lists at most, before saying how many more."""


def read(document: Any) -> dict[str, Any]:
    """A figure file's YAML as it reads (empty where it does not)."""

    try:
        data = yaml.safe_load((document or {}).get("text", "") or "")
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _listed(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    items = data.get(key)
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _words(value: Any, limit: int = 40) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def outline(document: Any, drawing: Any) -> list[str]:
    """A figure in brief: its settings, its parts as its groups hold them, its lines, its
    shapes, its TODOs and warnings."""

    data = read(document)
    if not data:
        return ["It does not read as a figure: read_document shows it as written."]
    figure = data.get("figure") if isinstance(data.get("figure"), dict) else {}
    settings = ", ".join(
        f"{key} {figure[key]}" for key in ("style", "width", "height", "palette") if key in figure
    )
    lines = [f"Figure {figure.get('id', '')}{f': {settings}' if settings else ''}."]
    nodes = {str(node.get("id")): node for node in _listed(data, "nodes") if "id" in node}
    groups = {str(group.get("id")): group for group in _listed(data, "groups") if "id" in group}
    root = str(figure.get("root") or "root")
    count = [0]

    def said(identifier: str) -> str:
        node = nodes.get(identifier)
        if node is not None:
            label = f" “{_words(node.get('label'))}”" if node.get("label") else ""
            return f"{identifier}: {node.get('kind') or 'block'}{label}"
        group = groups[identifier]
        layout = (
            (group.get("layout") or {}).get("kind")
            if isinstance(group.get("layout"), dict)
            else None
        )
        role = f", {group['role']}" if group.get("role") else ""
        label = f" “{_words(group.get('label'))}”" if group.get("label") else ""
        return f"{identifier} (group: {layout or 'stack'}{role}){label}"

    def tree(identifier: str, depth: int, seen: frozenset[str]) -> list[str]:
        count[0] += 1
        if count[0] > LISTED:
            return []
        out = [f"{'  ' * depth}- {said(identifier)}"]
        if identifier in groups and identifier not in seen:
            for child in groups[identifier].get("children") or []:
                child = str(child)
                if child in nodes or child in groups:
                    out += tree(child, depth + 1, seen | {identifier})
        return out

    lines.append("Parts:")
    if root in groups:
        lines += tree(root, 0, frozenset())
    held = {str(child) for group in groups.values() for child in group.get("children") or []}
    # (What no group holds: the figure's own, stacked, where it has no root group.)
    for identifier in [*groups, *nodes]:
        if identifier != root and identifier not in held:
            lines += tree(identifier, 0, frozenset())
    if count[0] > LISTED:
        lines.append(f"- and {count[0] - LISTED} more parts")
    edges = _listed(data, "edges")
    if edges:
        said_edges = [
            f"{edge.get('from')} → {edge.get('to')}"
            + (f" “{_words(edge.get('label'), 20)}”" if edge.get("label") else "")
            for edge in edges[:LISTED]
        ]
        lines.append(f"Lines ({len(edges)}): " + "; ".join(said_edges))
    shapes = _listed(data, "shapes")
    if shapes:
        lines.append(f"Shapes ({len(shapes)}):")
        for index, shape in enumerate(shapes[:LISTED]):
            name = f" {shape['id']}" if shape.get("id") else ""
            words = f" “{_words(shape.get('text'), 30)}”" if shape.get("text") else ""
            on = shape.get("on") or shape.get("around") or shape.get("of")
            at = f", on {on}" if on else ""
            lines.append(f"- shapes[{index}]{name}: {shape.get('kind', 'shape')}{words}{at}")
    found = todos(data)
    if found:
        lines.append(f"TODOs: {found}.")
    pages = {page.id: number for number, page in enumerate(drawing.pages, start=1)}
    lines += warnings(drawing.messages, pages)
    return lines


def marks(document: Any, number: int, page: Any) -> list[Mark]:
    """What to outline on a figure: its groups, its parts and its shapes, each by its id (as
    the figure's drawing names them)."""

    data = read(document)
    figure = data.get("figure") if isinstance(data.get("figure"), dict) else {}
    root = str(figure.get("root") or "root")
    found: list[Mark] = []
    for index, group in enumerate(_listed(data, "groups")):
        identifier = str(group.get("id", ""))
        if identifier and identifier != root:
            found.append(Mark(identifier, f"groups[{index}]", identifier, "group", "object"))
    for index, node in enumerate(_listed(data, "nodes")):
        identifier = str(node.get("id", ""))
        if identifier:
            what = str(node.get("kind") or "block")
            found.append(Mark(identifier, f"nodes[{index}]", identifier, what, "part"))
    for index, shape in enumerate(_listed(data, "shapes")):
        drawn = str(shape["id"]) if shape.get("id") else f"shapes.{index}"
        label = f"shapes[{index}]" + (f" {shape['id']}" if shape.get("id") else "")
        found.append(Mark(drawn, f"shapes[{index}]", label, str(shape.get("kind", "")), "shape"))
    return found


def selected(document: Any, where: dict[str, Any]) -> str | None:
    """The part a person has chosen in a figure (their ``where``'s ``id``), as a path in its
    YAML: "nodes[1] (encoder)"."""

    identifier = where.get("id")
    if identifier is None:
        return None
    data = read(document)
    for key in ("nodes", "groups", "shapes"):
        for index, item in enumerate(_listed(data, key)):
            if str(item.get("id")) == str(identifier):
                return f"{key}[{index}] ({identifier})"
    return f"the part {identifier}"


def report(before: Any, after: Any) -> dict[str, Any]:
    """What an edit did to a figure: its changes as the activity list says them, and every
    part, group, line and shape it deleted."""

    from flexo.studio.figure_kind import FigureKind

    changes = [note["text"] for note in FigureKind().describe(before, after)]
    old, new = read(before), read(after)
    deleted = []
    for key, noun in (("nodes", "part"), ("groups", "group")):
        kept = {str(item.get("id")) for item in _listed(new, key)}
        for item in _listed(old, key):
            if str(item.get("id")) not in kept:
                label = f" “{_words(item.get('label'))}”" if item.get("label") else ""
                deleted.append(f"the {noun} {item.get('id')}{label}")
    lines = {(str(edge.get("from")), str(edge.get("to"))) for edge in _listed(new, "edges")}
    for edge in _listed(old, "edges"):
        if (str(edge.get("from")), str(edge.get("to"))) not in lines:
            deleted.append(f"the line from {edge.get('from')} to {edge.get('to')}")
    was, now = _listed(old, "shapes"), _listed(new, "shapes")
    named = {str(shape.get("id")) for shape in now if shape.get("id")}
    gone = [shape for shape in was if shape.get("id") and str(shape["id"]) not in named]
    deleted += [f"the shape {shape['id']} ({shape.get('kind', 'shape')})" for shape in gone]
    unnamed = len([s for s in was if not s.get("id")]) - len([s for s in now if not s.get("id")])
    if unnamed > 0:
        deleted.append(f"{unnamed} shape{'s' if unnamed > 1 else ''}")
    return {"changes": changes, "deleted": deleted, "pages": [1], "noun": "page"}
