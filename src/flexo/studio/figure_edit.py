"""What the figure page does with the mouse, done to the figure file's own words.

The page draws the figure and shows its file. Adding a part, connecting two,
naming one, gathering some into a row: each arrives here as an *action* and is
made to the YAML itself, read and written back round-trip, so the file keeps its
comments, its order, and its quoting, and reads afterwards as if written by hand.

``apply(text, action)`` returns the file's new words and the ids the page should
choose next (the part just added). An action is a mapping with a ``do``:

- ``add``: ``kind`` (a part of ``figure_parts``), placed in ``parent`` or after
  ``after``, fed from ``source`` if given; ``node`` overrides its label and
  properties. A part put after ``source`` whose one line leads on to the part now
  after the new one goes into that line, as a step into a flow chart (``splice:
  false`` keeps the line, and the new part only fed from ``source``);
- ``connect``: ``source`` to ``target``, each a node or ``node.port``;
- ``update``: ``target`` (``{"type": "node" | "edge" | "group" | "figure", "id"}``)
  and ``values``, keys as the catalogue's fields name them (``properties.length``);
  an empty value removes its key; with ``name`` (the words a node had), a node's
  new label renames it too, if its id was made from those words or its kind's;
- ``rename``: ``id`` to ``to``, everywhere it is named;
- ``delete``: ``ids`` of nodes, groups (with what they hold), edges, and nets;
- ``gather``: ``ids`` held by one group, into a new ``layout`` (row, column,
  grid) group, a titled module if ``role`` is ``module``;
- ``ungroup``: ``id``'s children take its place;
- ``line_up``: ``ids``, whatever groups hold them, into one row or column (``kind``)
  of their own, in the order given, where the first of them stood;
- ``move``: ``id`` into ``parent`` at ``index``; or, with ``line`` (``below``,
  ``above``, ``right``, ``left``), on a line of its own beside the group ``of``
  (the root if not given), centred on it; ``step``: ``id`` by ``delta`` places
  among its siblings;
- ``align``: ``id``, on a line of its own, centred on the part or group ``with``;
- ``duplicate``: ``ids``, with the edges between them;
- ``paste``: parts copied from a figure (this one or another) -- ``nodes``,
  ``groups`` and ``edges`` as a file writes them, ``top`` the ones that hold the
  rest -- put after ``after`` or in ``parent``, each with an id of its own, the
  lines between them kept;
- ``join``: ``ids`` of lines into one shape (or out of one) made one line that
  branches (a net), with one caption; ``add``, a shape more on its branching side;
- ``separate``: the net ``id`` made lines again (with ``end``, that one branch);
- ``convert``: the shapes drawn over the figure at the places ``shapes`` made its parts --
  shapes, lines and groups, laid out as drawn (``flexo.studio.figure_convert``); ``placed``
  and ``boxes``, where the page has them drawn, spare drawing the figure to find them;
- ``shapes``: the shapes drawn over the figure (``flexo.figure_shapes``) made ``shapes``, a
  list as the file writes them: those unchanged kept as written, comments and all, one
  changed changed key by key -- and, with ``show`` (a ``show`` action's ``ids`` and ``as``),
  some of them hidden, dimmed or shown in the same step;
- ``read``: nothing; the page asks for the figure as it is.

A part renamed is renamed in the shapes drawn over the figure too (the part one is on, those
it goes round, what its ends are glued to); deleted, an end glued to it stays where it was
(its ``at``), a shape on it stays where it was drawn (given the part's top left, ``origins``,
by the page), and one round it goes round the rest -- or goes, round nothing.

A figure file that leaves its root group out stacks its parts in a column; the
first edit that needs the root written down (gathering, moving) writes it, as
the file already meant. So with a part a written root leaves out, which is drawn
at its end: the first edit that places a part among the others writes it there.
"""

from __future__ import annotations

import copy
import io
import json
import math
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.compat import ordereddict
from ruamel.yaml.scalarstring import (
    DoubleQuotedScalarString,
    LiteralScalarString,
    SingleQuotedScalarString,
)

from flexo.group_ends import PLAIN_PORTS
from flexo.ir.semantic import ID_PATTERN
from flexo.studio.group_lines import drop_gone, group_ids, outside_groups
from flexo.studio.group_lines import end_of as group_end
from flexo.studio.group_lines import named as group_named
from flexo.studio.merge import merge_text

SHOWN = {"hidden": "hide", "dimmed": "dim", "highlighted": "highlight"}
"""How a part is shown where not plainly, and the figure's setting that lists such parts."""

STRUCTURAL = frozenset(
    {
        "shapes",
        "add",
        "connect",
        "rename",
        "delete",
        "gather",
        "panels",
        "shift",
        "line_up",
        "frame",
        "ungroup",
        "move",
        "step",
        "duplicate",
        "paste",
        "arrange",
        "align",
        "join",
        "separate",
        "convert",
    }
)
"""Actions that change what the figure is made of: checked before they are kept."""

PLACING = STRUCTURAL - {"connect", "rename", "delete", "join", "separate", "shapes"}
"""Actions that put a part somewhere among the others: each part is held by a group the
file writes before one is made (``_Document.hold_all``)."""


class EditError(ValueError):
    """An edit that cannot be made; the page says why."""


NOUNS = {"node": "shape", "edge": "line", "net": "line"}
"""What the page calls each thing an edit targets, where it differs from the file."""

WORDS = frozenset({"label", "back_label", "cofactors"})
"""What a line says, as against how it looks: kept on one line when a part is put into it."""

ROUTE = frozenset({"waypoints", "lane", "via"})
"""How a line runs between its two ends (not where it leaves or meets them): not kept
when one of its ends changes."""


def _framed(node: Mapping[str, Any]) -> list[str]:
    """The ids a frame (a node of kind ``frame``) goes round, as its file names them; none
    for any other shape."""

    if node.get("kind") != "frame":
        return []
    written = str((node.get("properties") or {}).get("around") or "")
    return [item.strip() for item in written.split(",") if item.strip()]


def _frame_round(node: dict[str, Any], ids: list[str]) -> None:
    node.setdefault("properties", {})["around"] = ", ".join(ids)


def apply(
    text: str, action: Mapping[str, Any], *, suffix: str = ".yaml", base: Path | None = None
) -> dict[str, Any]:
    """The figure file's words after ``action``, and the ids to choose next."""

    return _applied(text, action, suffix=suffix, base=base)[0]


def _applied(
    text: str, action: Mapping[str, Any], *, suffix: str = ".yaml", base: Path | None = None
) -> tuple[dict[str, Any], _Document | None]:
    """``apply``'s answer, and the document the edit was made on (its words the answer's) --
    None for an edit that left the words as they were."""

    document = _Document(text, suffix)
    document.base = base
    verb = str(action.get("do", ""))
    handler = getattr(document, f"_{verb}", None)
    if verb not in STRUCTURAL | {"update", "read", "show"} or handler is None:
        raise EditError(f"Unknown figure edit “{verb}”.")
    # (Whether it read before the edit matters only to one that changes what it is made of.)
    was_valid = verb in STRUCTURAL and _reads(text, suffix, base)
    if verb in PLACING:
        document.hold_all()
    grouped = group_ids(document)
    select = handler(action) or []
    if document.unchanged:
        # Nothing to do: the file's words as they were, to the letter.
        return {"text": text, "select": list(select)}, None
    document.tidy_alignment()
    document.tidy_frames()
    drop_gone(document, grouped)  # (lines to a group gone go with it: flexo.group_ends)
    document.tidy_shown()
    result = document.dump()
    if verb in STRUCTURAL and was_valid:
        problem = _problem(result, suffix, base)
        if problem and document.spliced:
            # A part that cannot carry the line on (one with no output) is only fed.
            return _applied(text, {**action, "splice": False}, suffix=suffix, base=base)
        if problem:
            raise EditError(f"This change would break the figure: {problem}")
    # (What an edit made, in words, where it says: Convert to Figure Parts's.)
    said = {"said": document.summary} if document.summary else {}
    return {"text": result, "select": list(select), **said}, document


def astray(data: Any, ids: list[str] | None = None) -> list[str]:
    """Lines written to (or from) a shape the figure has none of -- ``to: nowhere``, a name
    mistyped -- taken out of ``data`` so the rest of it can be drawn: each said, as
    "A line to “nowhere” has no shape to go to.". ``ids``, given, gets the id the editor
    knows each by (``edge.2.b-to-nowhere``), to choose it by."""

    if not isinstance(data, dict) or not isinstance(data.get("edges"), list):
        return []
    nodes = {str(node.get("id")) for node in data.get("nodes") or [] if isinstance(node, dict)}
    # (A line may end at a group, as at a part: flexo.group_ends.)
    groups = {str(group.get("id")) for group in data.get("groups") or [] if isinstance(group, dict)}
    groups.add(str((data.get("figure") or {}).get("root", "root")))

    def there(reference: object) -> bool:
        reference = str(reference)
        head, _, port = reference.rpartition(".")
        return (
            reference in nodes
            or reference in groups
            or head in nodes
            or (head in groups and port in PLAIN_PORTS)
        )

    def node(reference: object) -> str:
        reference = str(reference)
        if reference in nodes or reference in groups:
            return reference
        return reference.rpartition(".")[0] or reference

    said, kept = [], []
    for index, edge in enumerate(data["edges"], start=1):
        if not isinstance(edge, dict) or ("from" not in edge or "to" not in edge):
            kept.append(edge)
            continue
        if not there(edge["to"]):
            said.append(f"A line to \u201c{edge['to']}\u201d has no shape to go to.")
        elif not there(edge["from"]):
            said.append(f"A line from \u201c{edge['from']}\u201d has no shape to start from.")
        else:
            kept.append(edge)
            continue
        if ids is not None:
            ids.append(
                str(edge.get("id") or f"edge.{index}.{node(edge['from'])}-to-{node(edge['to'])}")
            )
    if said:
        data["edges"] = kept
    return said


def apply_to_data(
    data: Mapping[str, Any], action: Mapping[str, Any], *, base: Path | None = None
) -> dict[str, Any]:
    """``action`` made to a figure written inline in another document (a deck's
    slide): the figure's data after it, the ids to choose, and its model."""

    import yaml

    # (Written as safe_dump writes it, by libyaml where there is one -- the very words, four
    # times sooner: an edit is made as the page waits.)
    text = yaml.dump(
        dict(data),
        Dumper=getattr(yaml, "CSafeDumper", yaml.SafeDumper),
        sort_keys=False,
        allow_unicode=True,
    )
    result, edited = _applied(text, action, base=base)
    # (Its model made from the document the edit was made on, as reading its words again would
    # make it -- not read again, which took as long as making the edit -- where its words read
    # back as it holds them: _reads_as_held.)
    shown = (
        _model(edited, base)
        if edited is not None and _reads_as_held(edited.data)
        else model(result["text"], base=base)
    )
    # (Read back as safe_load reads it, by libyaml where there is one: an edit is made as the
    # page waits.)
    return {
        "data": yaml.load(result["text"], getattr(yaml, "CSafeLoader", yaml.SafeLoader)),
        "select": result["select"],
        "model": shown,
    }


_BREAKS = ("\r", "\x85", "\u2028", "\u2029", "\ufeff")
"""What YAML may read otherwise than written in words: line breaks it takes as a new line, and
a byte order mark."""


def _reads_as_held(value: Any) -> bool:
    """Whether a figure's document, written as YAML (``_Document.dump``) and read again as a
    ``_Document`` reads it, would be what it holds now, for its model: a mapping of words to
    mappings, lists, words without breaks YAML reads otherwise (``_BREAKS``), numbers, true
    or false and nothing -- with its ``figure`` and its ``nodes``, as a document read is given."""

    if not isinstance(value, dict) or "figure" not in value or "nodes" not in value:
        return False
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or any(mark in key for mark in _BREAKS):
                    return False
                stack.append(child)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str):
            if any(mark in item for mark in _BREAKS):
                return False
        elif item is not None and not isinstance(item, bool | int | float):
            return False
    return True


def mend(data: Any, before: set[str] | None = None) -> bool:
    """A figure as two edits of it were merged may name what neither kept: a line to a
    shape one side deleted while the other drew it. Lines and nets to what is gone, and
    names of it in groups, go -- and a group left holding nothing with them, as a
    delete leaves none. Answers whether anything went.

    ``before``, the shapes there were before the edits: only a line to one of those is a
    line to a shape gone. One written to a shape there never was (``to: nowhere``) is the
    person's to put right, and stays: the drawing leaves it out and says so (``astray``)."""

    if not isinstance(data, dict):
        return False
    nodes = {str(node.get("id")) for node in data.get("nodes") or [] if isinstance(node, dict)}
    groups = [group for group in data.get("groups") or [] if isinstance(group, dict)]
    root = str((data.get("figure") or {}).get("root", "root"))
    known = nodes | {str(group.get("id")) for group in groups} | {root}

    def there(reference: object) -> bool:
        reference = str(reference)
        if reference in known or reference.rpartition(".")[0] in nodes:
            return True
        # (Never there at all: kept, for the drawing to say.)
        named = reference if "." not in reference else reference.rpartition(".")[0]
        return before is not None and reference not in before and named not in before

    changed = False
    for key in ("edges", "nets"):
        lines = data.get(key)
        if not isinstance(lines, list):
            continue
        kept = []
        for line in lines:
            if key == "edges":
                if not isinstance(line, dict) or (
                    there(line.get("from")) and there(line.get("to"))
                ):
                    kept.append(line)
                continue
            if not isinstance(line, dict):
                kept.append(line)
                continue
            for side in ("sources", "targets"):
                ends = line.get(side) or []
                if all(there(end) for end in ends):
                    continue
                line[side] = [end for end in ends if there(end)]
                changed = True
            sources, targets = line.get("sources") or [], line.get("targets") or []
            if not sources or not targets:
                continue
            # A fan-out left one target (a merge one source) is a line from one to the other.
            if (line.get("kind") == "fan-out" and len(targets) < 2) or (
                line.get("kind") == "merge" and len(sources) < 2
            ):
                edge = {"from": sources[0], "to": targets[0]}
                edge.update({k: line[k] for k in ("label", "line", "role") if k in line})
                data.setdefault("edges", []).append(edge)
                changed = True
                continue
            kept.append(line)
        if len(kept) != len(lines):
            data[key] = kept
            changed = True
    for key in ("edges", "nets"):
        if key in data and data[key] == []:
            del data[key]
    emptied = True
    while emptied:
        emptied = False
        known = nodes | {str(group.get("id")) for group in groups} | {root}
        for group in list(groups):
            children = group.get("children")
            if isinstance(children, list) and not all(str(child) in known for child in children):
                group["children"] = [child for child in children if str(child) in known]
                changed = True
            layout = group.get("layout")
            if isinstance(layout, dict) and isinstance(layout.get("placements"), list):
                placements = [
                    place
                    for place in layout["placements"]
                    if not isinstance(place, dict) or str(place.get("child")) in known
                ]
                if len(placements) != len(layout["placements"]):
                    layout["placements"] = placements
                    changed = True
            if "children" in group and not group.get("children") and str(group.get("id")) != root:
                groups.remove(group)
                data["groups"] = groups
                emptied = changed = True
    return changed


def model(
    text: str, *, suffix: str = ".yaml", base: Path | None = None
) -> dict[str, Any] | None:
    """The figure as its file writes it, for the page's inspector and outline: the
    figure's settings, nodes (with the ports each has), groups (the root among them,
    marked ``implied`` when the file leaves it out), edges under the ids the drawing
    gives them, and nets. ``None`` when the file does not read.

    With ``base``, the folder its files are named from: the functions each plot's Python
    file offers too (``functions``), for the page to choose among."""

    try:
        document = _Document(text, suffix)
    except Exception:
        return None
    return _model(document, base)


def _model(document: _Document, base: Path | None) -> dict[str, Any]:
    """``model`` of a document read."""

    data = json.loads(json.dumps(document.data, default=str))
    groups = list(data.get("groups") or [])
    root = next(
        (group for group in groups if isinstance(group, dict) and group.get("id") == document.root),
        None,
    )
    if root is not None:
        # What no group holds is drawn at the end of the root (see ``parse_figure``): listed so.
        held = {
            child
            for group in groups
            if isinstance(group, dict)
            for child in group.get("children") or []
        }
        loose = [
            item
            for item in [
                *(g.get("id") for g in groups if isinstance(g, dict)),
                *(n.get("id") for n in data.get("nodes") or [] if isinstance(n, dict)),
            ]
            if item is not None and item not in held and item != document.root
        ]
        if loose:
            groups[groups.index(root)] = {
                **root,
                "children": [*(root.get("children") or []), *loose],
            }
    if document.group(document.root) is None:
        groups.append(
            {
                "id": document.root,
                "children": document.top_level(),
                "layout": {"kind": "column"},
                "implied": True,
            }
        )
    nodes = []
    for item in data.get("nodes") or []:
        if not isinstance(item, dict) or "id" not in item:
            continue
        node = {"kind": "block", **item}
        node["ports"] = _ports(node)
        nodes.append(node)
    edges = [
        {**json.loads(json.dumps(item, default=str)), "id": identifier}
        for identifier, item in document.edge_ids()
        if isinstance(item, dict) and "from" in item and "to" in item
    ]
    return {
        "figure": data.get("figure") or {},
        "root": document.root,
        "nodes": nodes,
        "groups": groups,
        "edges": edges,
        "nets": data.get("nets") or [],
        # The shapes drawn over it (flexo.figure_shapes), as the file writes them.
        "shapes": data.get("shapes") if isinstance(data.get("shapes"), list) else [],
        # The sides of the ports that keep to one (a vector's four, ports written in the
        # file): where a line to one of them meets its shape.
        "sides": {
            node["id"]: fixed
            for node in nodes
            if (
                fixed := {
                    name: side
                    for name, (side, usual) in document.port_sides(str(node["id"])).items()
                    if not usual
                }
            )
        },
        # The functions each plot's file offers, read (never run) from the file as it is now:
        # none for a file that does not read, whose function is typed.
        "functions": {
            node["id"]: offered
            for node in nodes
            if node.get("kind") == "plot"
            and (offered := _offered(base, (node.get("properties") or {}).get("source")))
        },
    }


def _ports(node: Mapping[str, Any]) -> list[str]:
    written = [str(port.get("name")) for port in node.get("ports") or [] if isinstance(port, dict)]
    if written:
        return written
    from flexo.components import COMPONENTS

    definition = COMPONENTS.get(str(node.get("kind", "block")))
    names = [port.name for port in definition.ports] if definition else []
    properties = node.get("properties") or {}
    for key in ("parts", "features", "events", "tracks"):
        for record in properties.get(key) or []:
            if isinstance(record, dict) and record.get("id"):
                names.append(str(record["id"]))
    return names


def _reads(text: str, suffix: str, base: Path | None) -> bool:
    return _problem(text, suffix, base) is None


def _problem(text: str, suffix: str, base: Path | None) -> str | None:
    from flexo.diagnostics import FlexoError
    from flexo.studio.figure_kind import parse

    try:
        # (Read by libyaml where there is one: whether an edit breaks the figure is asked twice
        # as the page waits.)
        parse(text, base or Path.cwd(), suffix=suffix, libyaml=True)
    except FlexoError as error:
        return "; ".join(item.message for item in error.diagnostics) or str(error)
    except (ValueError, TypeError, KeyError) as error:
        return str(error)
    except Exception as error:  # a file that does not read at all
        return str(error)
    return None


def _parts() -> dict[str, Any]:
    from flexo.studio.figure_parts import catalogue

    return catalogue()["parts"]


MADE = {"block": frozenset({"step", "shape"}), "decision": frozenset({"check"})}
"""Ids the studio gave parts of its own beyond their words: the first flow chart's step
and its question, and a new figure's first shape, named for none of them."""

_SMALL = frozenset(
    {"a", "an", "and", "the", "of", "on", "in", "at", "to", "for", "with", "or", "by"}
)
"""Words an id cut short does not end on."""


def _slug(words: str) -> str:
    """An id made from words (a label, a kind): ``Encoder block`` is ``encoder-block``."""

    words = re.sub(r"\$|\\[A-Za-z]+|[*_`{}]", "", str(words))
    pieces = [piece for piece in re.split(r"[^A-Za-z0-9]+", words.lower()) if piece]
    # One that starts with a number reads with the number after: "3D refinement" is
    # refinement-3d, not part-3d-refinement.
    lead = next((at for at, piece in enumerate(pieces) if piece[0].isalpha()), None)
    if lead:
        pieces = pieces[lead:] + pieces[:lead]
    # Kept short, cut between words, not inside one -- nor after "and" or "the".
    kept: list[str] = []
    for piece in pieces:
        if len("-".join([*kept, piece])) > 24:
            while len(kept) > 1 and kept[-1] in _SMALL:
                kept.pop()
            break
        kept.append(piece)
    slug = "-".join(kept) or (pieces[0][:24] if pieces else "")
    if not slug or not slug[0].isalpha():
        slug = f"part-{slug}" if slug else "part"
    return slug


def _sequence_indent(text: str) -> int:
    """How far this file indents a list under a top-level key (``nodes:``)."""

    previous = ""
    for line in text.splitlines():
        stripped = line.lstrip(" ")
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and re.fullmatch(r"[A-Za-z_]+:\s*", previous):
            return len(line) - len(stripped)
        previous = line
    return 0


class _Document:
    base: Path | None = None
    """The folder the figure's files (pictures, structures) are found from."""

    def __init__(self, text: str, suffix: str) -> None:
        self.json = suffix.lower() == ".json"
        if self.json:
            self.data = json.loads(text) if text.strip() else {}
        else:
            self.yaml = YAML()
            self.yaml.preserve_quotes = True
            self.yaml.width = 4096
            indent = _sequence_indent(text)
            self.yaml.indent(mapping=2, sequence=indent + 2, offset=indent)
            self.data = self.yaml.load(text) if text.strip() else {}
        if not isinstance(self.data, dict):
            raise EditError("The file isn\u2019t a valid figure yet. Fix it in the source first.")
        self.data.setdefault("figure", {"id": "figure"})
        self.data.setdefault("nodes", [])
        self.spliced = False
        self.unchanged = False
        self.summary = ""
        """What the edit made, in words, where it says (Convert to Figure Parts)."""

    def dump(self) -> str:
        if self.json:
            return json.dumps(self.data, indent=2, ensure_ascii=False) + "\n"
        stream = io.StringIO()
        self.yaml.dump(_blocks(self.data), stream)
        return stream.getvalue()

    # -- what the file holds --

    @property
    def nodes(self) -> list[dict[str, Any]]:
        return self.data["nodes"]

    @property
    def groups(self) -> list[dict[str, Any]]:
        return self.data.get("groups") or []

    @property
    def edges(self) -> list[dict[str, Any]]:
        return self.data.get("edges") or []

    @property
    def nets(self) -> list[dict[str, Any]]:
        return self.data.get("nets") or []

    @property
    def root(self) -> str:
        figure = self.data.get("figure") or {}
        return str(figure.get("root", "root"))

    def node(self, identifier: str) -> dict[str, Any] | None:
        return next((item for item in self.nodes if item.get("id") == identifier), None)

    def group(self, identifier: str) -> dict[str, Any] | None:
        return next((item for item in self.groups if item.get("id") == identifier), None)

    def node_ids(self) -> set[str]:
        return {str(item.get("id")) for item in self.nodes}

    def taken(self) -> set[str]:
        ids = self.node_ids() | {str(item.get("id")) for item in self.groups}
        ids |= {str(item["id"]) for item in (*self.edges, *self.nets) if item.get("id")}
        ids |= set(self.shape_names())
        return ids | {self.root}

    @property
    def shapes(self) -> list[Any]:
        """The shapes drawn over the figure, as the file writes them."""

        found = self.data.get("shapes")
        return found if isinstance(found, list) else []

    def shape_names(self) -> list[str]:
        """The names of the shapes drawn over the figure: their own ids, else ``shapes.2``
        (and a group's shapes' own)."""

        from flexo.figure_shapes import name_of, shape_names

        found: list[str] = []
        for index, item in enumerate(self.shapes):
            if isinstance(item, dict):
                found += [name_of(item, index), *shape_names(item)[1:]]
        return list(dict.fromkeys(found))

    def node_of(self, reference: str) -> str:
        """The node a reference names: itself, or ``node.port``'s node."""

        if reference in self.node_ids() or group_end(self, reference) == reference:
            return reference
        head, _, _ = str(reference).rpartition(".")
        return head or reference

    def edge_ids(self) -> list[tuple[str, dict[str, Any]]]:
        """Each edge by the id the figure gives it (the builder's numbering when unnamed)."""

        return [
            (
                str(
                    item.get("id")
                    or f"edge.{index}.{self.node_of(item['from'])}-to-{self.node_of(item['to'])}"
                ),
                item,
            )
            for index, item in enumerate(self.edges, start=1)
        ]

    def edge_named(self, identifier: str) -> dict[str, Any] | None:
        """The edge ``identifier`` names: by its id -- or, for a line the figure numbers
        (unnamed: ``edge.3.check-to-end``), by the parts it joins, should lines have been
        added or taken away before it since: of the lines between them, the one nearest its
        number. (A line's number is where it is in the list; its ends are what it is.)"""

        named = dict(self.edge_ids())
        if identifier in named:
            return named[identifier]
        found = re.fullmatch(r"edge\.(\d+)\.(.+)", identifier)
        if not found:
            return None
        number, ends = int(found.group(1)), found.group(2)
        same = [
            (index, item)
            for index, item in enumerate(self.edges, start=1)
            if not item.get("id")
            and f"{self.node_of(item['from'])}-to-{self.node_of(item['to'])}" == ends
        ]
        return min(same, key=lambda pair: abs(pair[0] - number))[1] if same else None

    def edge_id(self, item: Mapping[str, Any]) -> str | None:
        """The id the figure gives the edge ``item`` now."""

        return next((name for name, edge in self.edge_ids() if edge is item), None)

    def line_said(self, identifier: str) -> str:
        """A line as a person knows it, by the parts it joins: the line from “Done?” to
        “End” -- not its id."""

        found = re.fullmatch(r"edge\.\d+\.(.+)", identifier)
        ends = found.group(1) if found else ""
        for node in self.nodes:
            start = f"{node.get('id')}-to-"
            other = self.node(ends.removeprefix(start)) if ends.startswith(start) else None
            if other is not None:
                return f"the line from “{self.said(node)}” to “{self.said(other)}”"
        # (Or a group at either end: flexo.group_ends.)
        either = [*self.nodes, *self.groups]
        for one in either:
            start = f"{one.get('id')}-to-"
            if not ends.startswith(start):
                continue
            rest = ends.removeprefix(start)
            other = self.node(rest) or self.group(rest)
            if other is not None:
                return f"the line from “{self.end_said(one)}” to “{self.end_said(other)}”"
        return "that line"

    def end_said(self, item: Mapping[str, Any]) -> str:
        """A line's end as a person knows it: a part by its words, a group by its title --
        else its id."""

        if self.node(str(item.get("id"))) is item:
            return self.said(item)
        return group_named(self, str(item.get("id")))

    def said(self, node: Mapping[str, Any]) -> str:
        """A part as a person knows it: by its words, else its id."""

        label = node.get("label")
        if isinstance(label, list):
            label = "".join(str(run.get("text", "")) for run in label)
        return str(label or node.get("id"))

    def holder(self, identifier: str) -> dict[str, Any] | None:
        return next(
            (group for group in self.groups if identifier in (group.get("children") or [])), None
        )

    def top_level(self) -> list[str]:
        """What the unwritten root holds: groups, then nodes, no group holds (as parsed)."""

        held = {child for group in self.groups for child in group.get("children") or []}
        order = [str(group["id"]) for group in self.groups] + [str(n["id"]) for n in self.nodes]
        return [item for item in order if item not in held]

    def written_root(self) -> dict[str, Any]:
        """The root group, written into the file if it was only implied."""

        found = self.group(self.root)
        if found is not None:
            return found
        root = {
            "id": self.root,
            "children": self.top_level(),
            "layout": {"kind": "column", "justify": "center"},
            "role": "canvas",
        }
        self.data.setdefault("groups", []).append(root)
        return root

    def parent_of(self, identifier: str) -> dict[str, Any]:
        """The group holding ``identifier``, the root written down if that is what holds it."""

        return self.holder(identifier) or self.written_root()

    def hold_all(self) -> None:
        """What a written root leaves out -- a part or group added to the file by hand, into
        none of its groups -- written into it, at its end, where it is drawn (see
        ``parse_figure``) and where the page lists it (``model``): a part moved among them,
        or beside one of them, finds each where it is seen."""

        root = self.group(self.root)
        if root is None:
            return
        loose = [item for item in self.top_level() if item != self.root]
        if loose:
            root.setdefault("children", []).extend(loose)

    def descendants(self, identifier: str) -> list[str]:
        group = self.group(identifier)
        if group is None:
            return []
        found = []
        for child in group.get("children") or []:
            found.append(child)
            found += self.descendants(child)
        return found

    def fresh(self, base: str, also: set[str] | frozenset[str] = frozenset()) -> str:
        """An unused id made from ``base`` (a label, a kind): ``encoder``, ``encoder-2``;
        none of ``also`` either (ids given out but not yet written)."""

        slug = _slug(base)
        taken = self.taken() | set(also)
        candidate, number = slug, 2
        while candidate in taken:
            candidate, number = f"{slug}-{number}", number + 1
        return candidate

    def fresh_copy(self, identifier: str, also: set[str] | frozenset[str] = frozenset()) -> str:
        """An unused id for a copy of ``identifier`` (duplicated, or pasted where it is taken):
        a copy of a copy numbered on from it, as the copies of one part are -- ``fix-3``
        after ``fix-2``, never ``fix-2-2``; none of ``also`` either."""

        taken = self.taken() | set(also)
        numbered = re.fullmatch(r"(.+)-(\d+)", identifier)
        if not numbered or identifier not in taken:
            return self.fresh(identifier, also)
        stem, number = _slug(numbered[1]), int(numbered[2]) + 1
        while f"{stem}-{number}" in taken:
            number += 1
        return f"{stem}-{number}"

    def detach(self, identifier: str) -> None:
        # (Lined up under a part where it was, it is placed afresh where it goes.)
        node = self.node(identifier)
        if node is not None:
            node.pop("align_with", None)
        for group in self.groups:
            children = group.get("children") or []
            while identifier in children:
                children.remove(identifier)
            layout = group.get("layout") or {}
            if layout.get("placements"):
                layout["placements"] = [
                    item for item in layout["placements"] if item.get("child") != identifier
                ]

    def place(self, identifier: str, parent: str | None, after: str | None) -> None:
        """Put ``identifier`` in ``parent`` (after ``after`` there), or after ``after``
        wherever that is, or at the end of the root."""

        if parent:
            group = self.group(parent)
            if group is None:
                raise EditError(f"There\u2019s no group named “{parent}”.")
        elif after and self.holder(after) is None and not self.groups:
            # A file of nodes alone stacks them in the order it lists them.
            node = self.node(identifier)
            anchor = self.node(after)
            if node is not None and anchor is not None:
                self.nodes.remove(node)
                self.nodes.insert(self.nodes.index(anchor) + 1, node)
            return
        elif not after and not self.groups:
            return  # listed last, so stacked last
        else:
            group = self.parent_of(after) if after else self.written_root()
        children = group.setdefault("children", [])
        index = children.index(after) + 1 if after in children else len(children)
        children.insert(index, identifier)

    # -- the actions --

    def _read(self, action: Mapping[str, Any]) -> list[str]:
        return []  # nothing changes: the page asked for the figure's model

    def _convert(self, action: Mapping[str, Any]) -> list[str]:
        """Shapes drawn over the figure (``shapes``, their places) made its parts: see
        ``flexo.studio.figure_convert``."""

        from flexo.studio.figure_convert import convert

        return convert(self, action)

    def _add(self, action: Mapping[str, Any]) -> list[str]:
        kind = str(action.get("kind", "block"))
        part = _parts().get(kind)
        if part is None:
            raise EditError(f"There\u2019s no shape type “{kind}”.")
        made = copy.deepcopy(part["node"])
        overrides = dict(action.get("node") or {})
        properties = {**made.get("properties", {}), **overrides.pop("properties", {})}
        made.update(overrides)
        # A shape starts with no words, but those it is given: the editor shows what it is,
        # faintly, until they are typed -- never a sample word that would be drawn.
        identifier = self.fresh(overrides.get("id") or overrides.get("label") or part["title"])
        item: dict[str, Any] = {"id": identifier}
        if kind != "block":
            item["kind"] = kind
        if overrides.get("label"):
            item["label"] = overrides["label"]
        # (And the size it is given: a picture dropped in, at a width the page has room for.)
        for side in ("width", "height"):
            if overrides.get(side):
                item[side] = overrides[side]
        # A structure named only for its file (1A7G) is named for what the file says it holds.
        if kind == "structure":
            item["label"] = self.structure_label(item.get("label"), properties.get("source"))
            if not item["label"]:
                item.pop("label")
        if kind == "plot":
            # A plot made of a file is that file's first function, till another is named.
            offered = _offered(self.base or Path.cwd(), properties.get("source"))
            if offered and not properties.get("function"):
                properties["function"] = offered[0]
            properties = {key: value for key, value in properties.items() if value != ""}
        if properties:
            item["properties"] = properties
        # Put into a line (``into``, chosen or let go on): between the parts it joins.
        into = self.line_named(str(action["into"])) if action.get("into") else None
        if into is not None and self.groups:
            self.written_root()  # (written before the part is: it would hold it twice)
        self.nodes.append(item)
        if into is not None:
            self.place_between(identifier, into, action.get("parent"))
            if action.get("splice", True):
                self.splice(into, identifier)
                self.spliced = True
            else:
                self.connect(str(into["from"]), identifier)
            return [identifier]
        if action.get("parent") and action.get("index") is not None:
            # Let go at a place in a group (a shape dragged from the palette): there.
            self.place_at(identifier, str(action["parent"]), int(action["index"]))
        else:
            self.place(identifier, action.get("parent"), action.get("after"))
        # A branch (``line``: a side, ``of``: the part or branch it goes beside) is put on a
        # line of its own there: a decision's other outcome under it, never into the line
        # between two parts.
        branch = str(action["line"]) if action.get("line") else None
        if action.get("source"):
            source = str(action["source"])
            spliced = action.get("splice", True) and not branch
            line = self.onward(source, identifier) if spliced else None
            if line is None:
                self.connect(source, identifier)
            else:
                # The line from source now ends at the new part (its words with it, as a
                # decision's "yes"), and a new line carries on to where it went.
                self.splice(line, identifier)
                self.spliced = True
        if branch:
            self.own_line(identifier, str(action.get("of") or action.get("after")), branch)
        return [identifier]

    def line_named(self, identifier: str) -> dict[str, Any]:
        """The line ``identifier`` names, or why there is none to put a part into."""

        line = self.edge_named(identifier)
        if line is None:
            said = self.line_said(identifier)
            raise EditError(f"{said[:1].upper()}{said[1:]} is gone.")
        return line

    def splice(self, line: dict[str, Any], identifier: str) -> None:
        """``identifier`` put into ``line``: the line now ends at it, its words, look and heads
        kept (a decision's "yes"), and a plain line of the same look carries on from it to
        where the line went -- arriving there as the line did. How the line ran between its
        ends (its waypoints, its lane) goes: it runs another way now. Two parts joined
        already are not joined twice."""

        source, target = self.node_of(str(line["from"])), self.node_of(str(line["to"]))
        if identifier in (source, target):
            raise EditError("A shape can\u2019t be put into its own line.")
        onward = line["to"]
        arrive = line.pop("arrive", None)
        for key in ROUTE:
            line.pop(key, None)
        look = {
            key: copy.deepcopy(value)
            for key, value in line.items()
            if key not in {"id", "from", "to", "depart"} | WORDS | ROUTE
        }
        if self.joined(source, identifier, but=line):
            self.edges.remove(line)
        else:
            line["to"] = self.free_input(identifier)
        if not self.joined(identifier, target):
            carried: dict[str, Any] = {"from": identifier, "to": onward, **look}
            if arrive:
                carried["arrive"] = arrive
            self.data.setdefault("edges", []).append(carried)

    def joined(self, source: str, target: str, but: object = None) -> bool:
        """Whether a line (other than ``but``) runs from ``source`` to ``target``."""

        return any(
            edge is not but
            and self.node_of(str(edge["from"])) == source
            and self.node_of(str(edge["to"])) == target
            for edge in self.edges
        )

    def place_between(
        self, identifier: str, line: Mapping[str, Any], parent: object = None
    ) -> None:
        """Put ``identifier``, going into ``line``, where it reads between the parts the line
        joins: in ``parent`` (the group it was let go in) -- else in the group that holds them
        both -- down to the smallest group there that holds them both: after what holds the
        part the line leaves, else before what holds the part it goes to (a part put into the
        line between two modules goes between them). Across the lines of a flow laid out on
        several (a long one folded to fit, written as it is seen), on the line the line
        arrives at, beside the part it goes to. Along a line run back (a fold's second), between
        the two all the same. In a file of parts alone, after the part the line leaves."""

        source, target = self.node_of(str(line["from"])), self.node_of(str(line["to"]))

        def holding(group: dict[str, Any], part: str) -> str | None:
            return next(
                (
                    child
                    for child in group.get("children") or []
                    if child != identifier
                    and (child == part or part in self.descendants(str(child)))
                ),
                None,
            )

        given = None
        if parent and (str(parent) != self.root or self.group(self.root) is not None):
            given = self.group(str(parent)) if str(parent) != self.root else self.written_root()
        for group in (given, self.both_in(source, target)):
            if group is None or group.get("id") == identifier:
                continue
            before, after = holding(group, source), holding(group, target)
            inner = self.group(str(before)) if before is not None and before == after else None
            while inner is not None and inner.get("id") != identifier:
                group = inner
                before, after = holding(group, source), holding(group, target)
                inner = self.group(str(before)) if before is not None and before == after else None
            if before is None and after is None:
                continue
            lines = before is not None and after is not None and before != after
            if lines and self.flow_line(group, before) and self.flow_line(group, after):
                group = self.group(str(after)) or group
                before, after = None, holding(group, target)
            children = group.setdefault("children", [])
            while identifier in children:
                children.remove(identifier)
            back = self.runs_back(group)
            if (
                before is not None
                and after is not None
                and back
                and children.index(after) < children.index(before)
            ):
                at = children.index(after) + 1
            elif before is not None:
                at = children.index(before) + 1
            else:
                # Beside the part it goes to, on the side the flow there comes from.
                at = children.index(after) + (1 if back else 0)
            # Should the part after the one the line leaves be another of its branches (a
            # decision's "yes", where this line is its "no"), it goes just before the one the
            # line goes to: never into another branch's way.
            if (
                before is not None
                and after is not None
                and children.index(after) > at
                and self.joined(source, self.node_of(str(children[at])))
            ):
                at = children.index(after)
            children.insert(at, identifier)
            return
        self.place(identifier, None, source)

    def flow_line(self, group: Mapping[str, Any], child: object) -> bool:
        """Whether ``child`` of ``group`` is one of its lines: a row (column) with no frame of
        its own in a column (row) -- as a long flow folded to fit is written as it is seen."""

        line = self.group(str(child))
        if line is None or line.get("role") != "layout" or line.get("label"):
            return False
        way = (group.get("layout") or {}).get("kind", "column")
        return {way, (line.get("layout") or {}).get("kind", "row")} == {"row", "column"}

    def runs_back(self, group: Mapping[str, Any]) -> bool:
        """Whether more of the lines between ``group``'s parts run from a later part to an
        earlier one than the other way: a line of a flow run back (a fold's second)."""

        children = [str(child) for child in group.get("children") or []]
        held = {
            node: index
            for index, child in enumerate(children)
            for node in ([child] if self.node(child) is not None else self.descendants(child))
        }
        forward = backward = 0
        for edge in self.edges:
            one = held.get(self.node_of(str(edge["from"])))
            two = held.get(self.node_of(str(edge["to"])))
            if one is None or two is None or one == two:
                continue
            forward += two > one
            backward += two < one
        return backward > forward

    def both_in(self, one: str, other: str) -> dict[str, Any] | None:
        """The smallest group written in the file that holds both ``one`` and ``other``."""

        def size(group: Mapping[str, Any]) -> int:
            return len(self.descendants(str(group.get("id"))))

        for group in sorted(self.groups, key=size):
            inside = self.descendants(str(group.get("id")))
            if one in inside and other in inside:
                return group
        return None

    def place_at(self, identifier: str, parent: str, index: int) -> None:
        """Put ``identifier`` at ``index`` among ``parent``'s parts (a file of parts alone, which
        lists them in the order it stacks them, at that place in its list)."""

        if parent == self.root and self.group(self.root) is None and not self.groups:
            node = self.node(identifier)
            if node is not None:
                self.nodes.remove(node)
                self.nodes.insert(max(0, min(index, len(self.nodes))), node)
            return
        group = self.written_root() if parent == self.root else self.group(parent)
        if group is None:
            raise EditError(f"There\u2019s no group named “{parent}”.")
        children = group.setdefault("children", [])
        while identifier in children:  # (a root written just now holds it already)
            children.remove(identifier)
        children.insert(max(0, min(index, len(children))), identifier)

    def structure_label(self, label: object, source: object) -> str | None:
        """A new structure's name: the one given, unless that is only its file's -- then what
        the file says it holds (``Regulatory protein E2 (1A7G)``), where it says."""

        from flexo.structures import structure_caption

        name = str(label or "").strip()
        stem = re.sub(r"\.(pdb|cif|mmcif|ent|json)$", "", Path(str(source or "")).name, flags=re.I)
        if not source or (name and name.lower() != stem.lower()):
            return name or None
        path = Path(str(source))
        path = path if path.is_absolute() else (self.base or Path.cwd()) / path
        return structure_caption(path) or name or None

    def onward(self, source: str, identifier: str) -> dict[str, Any] | None:
        """The line a part just put after ``source`` goes into: ``source``'s one line,
        when it leads to the part now right after the new one, in the same group."""

        node = self.node(identifier)
        if node is None or node.get("kind") == "attention" or self.node(source) is None:
            return None
        # A decision's lines are its branches: a part after it is a branch of its own.
        if self.node(source).get("kind") == "decision":
            return None
        if any(
            source in (self.node_of(str(end)) for end in net.get("sources") or [])
            for net in self.nets
        ):
            return None
        lines = [edge for edge in self.edges if self.node_of(str(edge["from"])) == source]
        if len(lines) != 1:
            return None
        holder = self.holder(identifier)
        order = list(holder.get("children") or []) if holder is not None else self.top_level()
        if identifier not in order or self.holder(source) is not holder:
            return None
        at = order.index(identifier)
        following = order[at + 1] if at + 1 < len(order) else None
        if at == 0 or order[at - 1] != source or following != self.node_of(str(lines[0]["to"])):
            return None
        return lines[0]

    def _connect(self, action: Mapping[str, Any]) -> list[str]:
        return [self.connect(str(action["source"]), str(action["target"]))]

    def connect(self, source: str, target: str) -> str:
        if self.node_of(source) == self.node_of(target):
            return self.loop(source)
        for end in (source, target):
            # (A group is an end as a shape is: flexo.group_ends.)
            if self.node(self.node_of(end)) is None and group_end(self, end) is None:
                raise EditError(f"There\u2019s no shape named “{end}” to connect.")
        ends = (self.node_of(source), self.node_of(target))
        if any(
            (self.node_of(str(e["from"])), self.node_of(str(e["to"]))) == ends for e in self.edges
        ):
            raise EditError(f"“{source}” and “{target}” are already connected.")
        self.outside_frames(*ends)
        outside_groups(self, *ends)
        node = self.node(target)
        target = self.free_input(target)
        if node is not None and node.get("kind") == "attention":
            # One value into attention is self-attention: query, key, and value alike.
            identifier = self.fresh(f"{self.node_of(source)}-to-{target}")
            self.data.setdefault("nets", []).append(
                {
                    "id": identifier,
                    "kind": "fan-out",
                    "sources": [source],
                    "targets": [f"{target}.q", f"{target}.k", f"{target}.v"],
                }
            )
            return identifier
        self.data.setdefault("edges", []).append({"from": source, "to": target})
        return self.edge_ids()[-1][0]

    def loop(self, source: str) -> str:
        """A line from a shape back into itself -- a step repeated, a model run on its own
        output -- drawn on the side nothing else uses (``flexo.routing``): its id."""

        node = self.node(self.node_of(source))
        if node is None:
            raise EditError(f"A line can\u2019t loop back to “{source}”: only a shape\u2019s can.")
        if any(
            self.node_of(str(e["from"])) == node["id"] and self.node_of(str(e["to"])) == node["id"]
            for e in self.edges
        ):
            raise EditError(f"“{self.said(node)}” loops back to itself already.")
        self.data.setdefault("edges", []).append({"from": node["id"], "to": node["id"]})
        return self.edge_ids()[-1][0]

    def held_by(self, frame: str) -> set[str]:
        """The shapes a frame goes round: those it names, and all the groups it names hold."""

        node = self.node(frame) or {}
        named = _framed(node)
        return {
            item
            for one in named
            for item in (one, *self.descendants(one))
            if self.node(item) is not None
        }

    def outside_frames(self, *ends: str) -> None:
        """A line between ``ends`` (shapes, by id) is one that can be drawn where an end is a
        frame: a line ends at a frame from outside it, never from a shape it goes round (nor
        from a frame all of whose shapes it goes round)."""

        for frame in ends:
            node = self.node(frame)
            if node is None or node.get("kind") != "frame":
                continue
            held = self.held_by(frame)
            for other in ends:
                if other == frame:
                    continue
                there = self.node(other) or {}
                within = self.held_by(other) if there.get("kind") == "frame" else None
                if other in held or (within and within <= held):
                    raise EditError(
                        f"A line can\u2019t end at “{self.said(node)}” from inside it: the "
                        f"frame goes round “{self.said(there) if there else other}”."
                    )

    def free_input(self, target: str) -> str:
        """Where a line into ``target`` lands: its ``input``, or, for a part whose inputs
        are numbered (concat), the first no line reaches yet."""

        node = self.node(target)
        if node is None:
            return target
        written = [str(port.get("name")) for port in node.get("ports") or []]
        if not written:
            from flexo.components import COMPONENTS

            definition = COMPONENTS.get(str(node.get("kind", "block")))
            written = [port.name for port in definition.ports] if definition else []
        if not written or "input" in written or node.get("kind") == "attention":
            return target
        numbered = [name for name in written if name.startswith("input")]
        if not numbered:
            return target
        used = {str(edge["to"]) for edge in self.edges}
        free = [name for name in numbered if f"{target}.{name}" not in used]
        return f"{target}.{(free or numbered)[0]}"

    def _update(self, action: Mapping[str, Any]) -> list[str]:
        many = action.get("targets")
        if many:
            # The same values for several things at once (parts coloured together): one edit --
            # or each its own (a style pasted on a shape and a group, as each takes it).
            chosen: list[str] = []
            for target in many:
                values = target.get("values", action.get("values"))
                chosen += self._update({"target": target, "values": values})
            return chosen
        target = action.get("target") or {}
        kind, identifier = target.get("type"), str(target.get("id", ""))
        values = dict(action.get("values") or {})
        if kind == "figure":
            item = self.data.setdefault("figure", {})
            values = {key.removeprefix("figure."): value for key, value in values.items()}
        elif kind == "node":
            item = self.node(identifier)
        elif kind == "group":
            item = self.group(identifier) or (
                self.written_root() if identifier == self.root else None
            )
        elif kind == "edge":
            item = self.edge_named(identifier)
            if item is None:
                said = self.line_said(identifier)
                raise EditError(f"{said[:1].upper()}{said[1:]} is gone.")
        elif kind == "net":
            item = next((net for net in self.nets if net.get("id") == identifier), None)
        else:
            raise EditError("Can\u2019t edit this item.")
        if item is None:
            raise EditError(f"There\u2019s no {NOUNS.get(kind, kind)} named “{identifier}”.")
        # (A line found by its ends is chosen by the name it has now.)
        now = self.edge_id(item) if kind == "edge" else None
        chosen = [now or identifier] if identifier else []
        typed_over = action.get("was")
        for words in ("label", "back_label"):
            if isinstance(typed_over, str) and isinstance(values.get(words), str):
                # Words typed over what a label said when the typing began, while someone
                # else changed it: both kept, merged as two people's words in one field are.
                now = item.get(words)
                if isinstance(now, str) and now != typed_over:
                    values[words] = merge_text(typed_over, values[words], now)
        if (
            kind == "node"
            and "name" in action
            and not str(action.get("name") or "").strip()
            and values.get("label")
            and "id" not in values
        ):
            # The first words typed on a part just added, done: its id follows them, as the
            # figure names a part it adds -- before anyone else can have seen it. An id a
            # shape already has is never changed by its words: others (a person, an agent,
            # a line, an export) may know it by that name.
            words = str(values["label"])
            named = self.named_for(identifier, item, "", words)
            if named != identifier:
                values["id"] = named
        for key, value in values.items():
            if key == "id" and kind in {"node", "group"}:
                if value and value != identifier:
                    self.rename(identifier, str(value))
                    chosen = [str(value)]
                continue
            if key == "kind" and kind == "node":
                self.retype(item, str(value or "block"))
                continue
            if key in {"depart", "arrive"} and kind == "edge":
                self.end_side(item, key, value)
                continue
            if key in {"from", "to"} and kind == "edge" and value:
                # (An end taken to a frame: from outside it, as a new line to it is.)
                other = item.get("to" if key == "from" else "from")
                self.outside_frames(self.node_of(str(value)), self.node_of(str(other)))
                outside_groups(self, self.node_of(str(value)), self.node_of(str(other)))
            if kind == "net" and key.startswith("side:"):
                self.net_side(item, key.removeprefix("side:"), value)
                continue
            if kind == "net" and key == "trunk":
                self.net_trunk(item, str(value or ""))
                continue
            _set(item, key.split("."), value)
            if kind == "edge" and key == "shape" and value != "curved":
                item.pop("bend", None)  # (only a curve bends, or leans)
                item.pop("lean", None)
            if kind == "edge" and key in {"arrow", "head"}:
                # A regulation head goes on an arrow with an end; a reversible step has none
                # (and only an arrow with heads at both ends has a head at its start).
                if key == "arrow" and value != "both":
                    item.pop("tail", None)
                if key == "arrow" and value in {"reversible", "none"}:
                    item.pop("head", None)
                elif (
                    key == "head"
                    and value not in (None, "", "arrow")
                    and item.get("arrow") in {"reversible", "none"}
                ):
                    item.pop("arrow", None)
            if kind == "net" and key in {"rail", "via"} and value:
                # A net's run is placed one way: along a side, by a share, or by a lean.
                for other in {"rail", "rail_at", "via"} - {key}:
                    item.pop(other, None)
            if kind == "node" and item.get("kind") == "vector" and value not in (None, ""):
                # A vector is shaded one way: from a colour (a tone) or along a ramp.
                other = {"properties.tone": "ramp", "properties.ramp": "tone"}.get(key)
                if other and isinstance(item.get("properties"), dict):
                    item["properties"].pop(other, None)
            if key == "layout.kind" and kind == "group":
                layout = item.setdefault("layout", {})
                if value == "grid" and not layout.get("columns"):
                    count = len(item.get("children") or [])
                    layout["columns"] = max(1, math.ceil(math.sqrt(count)))
                elif value != "grid":
                    layout.pop("columns", None)
        if (
            kind == "node"
            and item.get("kind") == "plot"
            and "properties.source" in values
            and "properties.function" not in values
        ):
            # A plot given another file keeps its function if that file has one of the name;
            # else it takes the file's first, as a new plot does. (A file that does not
            # read offers none: the name stays, to be typed.)
            properties = item.get("properties") or {}
            offered = _offered(self.base or Path.cwd(), properties.get("source"))
            if offered and properties.get("function") not in offered:
                _set(item, ["properties", "function"], offered[0])
        if kind == "edge":
            # (A line given another shape at an end is named by its new ends.)
            chosen = [self.edge_id(item) or identifier]
        return chosen

    def named_for(self, identifier: str, item: Mapping[str, Any], was: str, words: str) -> str:
        """The id for a node that had the words ``was`` and has ``words`` now: one made from
        them, if its id was made from ``was`` or from its kind's own (``block-3``); else
        the id it has."""

        kind = str(item.get("kind") or "block")
        part = _parts().get(kind) or {}
        given = (part.get("node") or {}).get("label") or kind
        made = {_slug(was) if was else "", kind, _slug(part.get("title") or kind), _slug(given)}
        made |= MADE.get(kind, frozenset())
        stem = re.sub(r"-\d+$", "", identifier)
        if identifier not in made and stem not in made:
            return identifier
        if _slug(words) in {identifier, stem}:
            return identifier
        return self.fresh(words)

    def retype(self, item: dict[str, Any], kind: str) -> None:
        """A node made another kind: it keeps its label and tone, takes the new kind's
        starting properties, and drops what only the old kind read."""

        part = _parts().get(kind)
        if part is None:
            raise EditError(f"There\u2019s no shape type “{kind}”.")
        if kind == "block":
            item.pop("kind", None)
        elif "kind" in item:
            item["kind"] = kind
        else:
            _insert_after_id(item, "kind", kind)
        known = {field["key"].removeprefix("properties.") for field in part["fields"]}
        properties = item.get("properties") or {}
        for name in list(properties):
            if name not in known:
                del properties[name]
        for name, value in part["node"].get("properties", {}).items():
            properties.setdefault(name, copy.deepcopy(value))
        if properties:
            item["properties"] = properties
        else:
            item.pop("properties", None)

    def _rename(self, action: Mapping[str, Any]) -> list[str]:
        self.rename(str(action["id"]), str(action["to"]))
        return [str(action["to"])]

    def rename(self, old: str, new: str) -> None:
        if not ID_PATTERN.fullmatch(new):
            raise EditError(
                f"“{new}” can\u2019t be used as a name. A name starts with a letter and "
                "has only letters, digits, dots, hyphens and underscores."
            )
        if new in self.taken():
            raise EditError(f"The name “{new}” is already in use.")
        node, group = self.node(old), self.group(old)
        if node is None and group is None and old != self.root:
            raise EditError(f"There\u2019s nothing named “{old}”.")
        if node is not None:
            node["id"] = new
        if group is not None:
            group["id"] = new
        if old == self.root:
            self.data.setdefault("figure", {})["root"] = new

        def moved(reference: str) -> str:
            if reference == old:
                return new
            if (
                node is not None
                and reference.startswith(f"{old}.")
                and "." not in reference[len(old) + 1 :]
            ):
                return new + reference[len(old) :]
            return reference

        for item in self.groups:
            children = item.get("children") or []
            for index, child in enumerate(children):
                if child == old:
                    children[index] = new
            if item.get("anchor") == old:
                item["anchor"] = new
            for placement in (item.get("layout") or {}).get("placements") or []:
                if placement.get("child") == old:
                    placement["child"] = new
        for part in self.nodes:
            if isinstance(part, dict) and part.get("align_with") == old:
                part["align_with"] = new
            # (A frame goes on round it, by its new name.)
            if isinstance(part, dict) and old in _framed(part):
                _frame_round(part, [new if item == old else item for item in _framed(part)])
        # (Shapes drawn over it stay on it, round it and glued to it -- to its pieces too.)
        def renamed(reference: object) -> object:
            reference = str(reference)
            if reference == old:
                return new
            if node is not None and reference.startswith(f"{old}."):
                return new + reference[len(old) :]
            return reference

        for shape in _every_shape(self.shapes):
            if shape.get("on") is not None and renamed(shape["on"]) != shape["on"]:
                shape["on"] = renamed(shape["on"])
            for index, item in enumerate(shape.get("around") or []):
                if renamed(item) != item:
                    shape["around"][index] = renamed(item)
            for key in ("from", "to"):
                end = shape.get(key)
                if isinstance(end, dict) and renamed(end.get("part")) != str(end.get("part")):
                    end["part"] = renamed(end["part"])
        # (And it stays hidden, dimmed or highlighted, by its new name.)
        settings = self.data.get("figure")
        for key in SHOWN.values():
            if isinstance(settings, dict) and old in (settings.get(key) or []):
                settings[key] = [new if item == old else item for item in settings[key]]
        for edge in self.edges:
            edge["from"], edge["to"] = moved(str(edge["from"])), moved(str(edge["to"]))
            for waypoint in edge.get("waypoints") or []:
                if waypoint.get("reference") == old:
                    waypoint["reference"] = new
        for net in self.nets:
            for side in ("sources", "targets"):
                values = net.get(side) or []
                for index, value in enumerate(values):
                    values[index] = moved(str(value))
            if isinstance(net.get("sides"), dict):
                net["sides"] = {moved(str(end)): side for end, side in net["sides"].items()}

    def _delete(self, action: Mapping[str, Any]) -> list[str]:
        ids = [str(item) for item in action.get("ids") or []]
        nodes: set[str] = set()
        for identifier in ids:
            if identifier == self.root:
                raise EditError("The figure itself can\u2019t be deleted.")
            if self.group(identifier) is not None:
                inside = self.descendants(identifier)
                nodes |= {item for item in inside if self.node(item) is not None}
                for item in [identifier, *inside]:
                    group = self.group(item)
                    if group is not None:
                        self.groups.remove(group)
                    self.detach(item)
            elif self.node(identifier) is not None:
                nodes.add(identifier)
            elif (edge := self.edge_named(identifier)) is not None:
                self.edges.remove(edge)
            else:
                net = next((item for item in self.nets if item.get("id") == identifier), None)
                if net is None:
                    raise EditError(f"There\u2019s nothing named “{identifier}” to delete.")
                self.nets.remove(net)
        # A part taken out of a chain leaves the chain joined round it. (A frame is no part
        # of one: the lines that end at it go with it.)
        self.rejoin({item for item in nodes if (self.node(item) or {}).get("kind") != "frame"})
        pair = None
        if action.get("rejoin") and len(nodes) == 1:
            # A part put beside another as a branch and taken out again at once (an Add Shape
            # left empty): the pair it made goes with it.
            (only,) = nodes
            pair = self.holder(only)
        for identifier in nodes:
            node = self.node(identifier)
            if node is not None:
                self.nodes.remove(node)
            self.detach(identifier)
        if pair is not None:
            self.unpair(pair)
        if nodes:
            for edge in list(self.edges):
                if {self.node_of(str(edge["from"])), self.node_of(str(edge["to"]))} & nodes:
                    self.edges.remove(edge)
            # Its nets lose it; one left with a single end each way becomes a line.
            mend(self.data)
        self.unattach({*ids, *nodes}, action.get("origins") or {})
        self._tidy()
        return []

    def unattach(self, gone: set[str], origins: Mapping[str, Any]) -> None:
        """The shapes drawn over the figure, its parts ``gone``: an end glued to one stays
        where it was (its ``at``); a shape on one stays where it was drawn, given the part's
        top left (``origins``) -- else it says it is on what is gone; one round some goes round
        the rest, and goes itself, round none."""

        from flexo.freeform import moved

        def lost(reference: object) -> bool:
            reference = str(reference)
            return reference in gone or any(reference.startswith(f"{part}.") for part in gone)

        kept = []
        for shape in self.shapes:
            if not isinstance(shape, dict):
                kept.append(shape)
                continue
            around = shape.get("around")
            if isinstance(around, list) and any(lost(item) for item in around):
                rest = [item for item in shape["around"] if not lost(item)]
                if not rest:
                    continue
                shape["around"][:] = rest
            on = shape.get("on")
            if on is not None and lost(on):
                origin = origins.get(str(on))
                if isinstance(origin, list | tuple) and len(origin) == 2:
                    places = moved(_plain(shape), float(origin[0]), float(origin[1]))
                    for key in ("at", "tail", "from", "to", "points", "d"):
                        if key in shape and places.get(key) != _plain(shape.get(key)):
                            shape[key] = self.written(key, places[key])
                    del shape["on"]
            for each in _every_shape([shape]):
                for key in ("from", "to"):
                    end = each.get(key)
                    if (
                        isinstance(end, dict)
                        and end.get("part") is not None
                        and lost(end["part"])
                        and isinstance(end.get("at"), list)
                    ):
                        each[key] = self.written("at", _plain(end["at"]))
            kept.append(shape)
        if len(kept) != len(self.shapes):
            self.shapes[:] = kept

    def _shapes(self, action: Mapping[str, Any]) -> list[str]:
        """The shapes drawn over the figure made ``shapes``: each the file has unchanged kept
        as it is written, comments and all; one changed, changed key by key; the rest
        written as a person writes them (points ``[x, y]``, an end ``{part: encoder}``)."""

        from flexo.figure_shapes import checked
        from flexo.freeform import ShapeError

        wanted = action.get("shapes")
        if not isinstance(wanted, list) or not all(isinstance(item, dict) for item in wanted):
            raise EditError("The shapes must be a list of shapes.")
        for index, item in enumerate(wanted):
            try:
                checked(item)
            except ShapeError as error:
                where = f"shapes[{index}]" + (f".{error.key}" if error.key else "")
                raise EditError(f"{where}: {error.message}") from None
        old = self.shapes
        plain = [_plain(item) for item in old]
        # (Shown apart in the same step -- a shape named to be hidden, dimmed: ``show``.)
        if isinstance(action.get("show"), Mapping):
            self._show(action["show"])
        if plain == wanted:
            self.unchanged = not isinstance(action.get("show"), Mapping)
            return []
        # Each wanted the same as one the file has is that one; one changed, the one at its
        # place, if that is not the same as another.
        places: list[int | None] = [None] * len(wanted)
        used: set[int] = set()
        for index, item in enumerate(wanted):
            found = next(
                (n for n, was in enumerate(plain) if n not in used and was == item), None
            )
            if found is not None:
                places[index] = found
                used.add(found)
        for index, _ in enumerate(wanted):
            if (
                places[index] is None
                and index < len(old)
                and index not in used
                and isinstance(old[index], dict)
            ):
                places[index] = index
                used.add(index)
        made = []
        for index, item in enumerate(wanted):
            at = places[index]
            if at is None:
                made.append(self.written_shape(item))
            elif plain[at] == item:
                made.append(old[at])
            else:
                made.append(self.rewritten(old[at], item))
        if not made:
            self.data.pop("shapes", None)
            return []
        if isinstance(self.data.get("shapes"), list):
            self.data["shapes"][:] = made
        else:
            self.data["shapes"] = made if self.json else CommentedSeq(made)
        return []

    def written_shape(self, item: Mapping[str, Any]) -> Any:
        """A shape as a person writes it: its kind, then its name, then the rest as given."""

        first = ["kind", *(["id"] if "id" in item else [])]
        keys = [*first, *(key for key in item if key not in first)]
        made = {} if self.json else CommentedMap()
        for key in keys:
            if key in item:
                made[self.key(key)] = self.written(key, item[key])
        return made

    def rewritten(self, old: dict[str, Any], item: Mapping[str, Any]) -> dict[str, Any]:
        """``old``, a shape as the file writes it, made ``item``: its keys kept in their
        places and as written where unchanged."""

        for key in list(old):
            if str(key) not in item:
                del old[key]
        for key, value in item.items():
            if key in old and _plain(old[key]) == value:
                continue
            old[self.key(key)] = self.written(key, value)
        return old

    def key(self, key: str) -> str:
        """A shape's key as written: ``on`` quoted in YAML, which reads a plain one as
        true."""

        return key if self.json or key != "on" else SingleQuotedScalarString(key)

    def written(self, key: str, value: Any) -> Any:
        """A shape's value as a person writes it: a point ``[x, y]`` on its line, a glued end
        ``{part: encoder, side: top, at: [x, y]}``, a group's shapes each as a shape."""

        if self.json:
            return value
        if key == "shapes" and isinstance(value, list):
            return CommentedSeq(
                [self.written_shape(child) for child in value if isinstance(child, dict)]
            )
        if isinstance(value, dict):
            made = CommentedMap((name, self.written(name, part)) for name, part in value.items())
            made.fa.set_flow_style()
            return made
        if isinstance(value, list) and key in FLOWED:
            made = CommentedSeq(
                self.written("at", part) if isinstance(part, list) else _number(part)
                for part in value
            )
            made.fa.set_flow_style()
            return made
        return value

    def rejoin(self, gone: set[str]) -> None:
        """The lines through parts about to be taken out, joined up round them: a part with
        lines in and one line out (or one in and lines out) has each line into it carried on to
        where the other went -- its words, look and heads kept (a chain's one line, else the
        words of the line out), leaving where it left and arriving as the other arrived. Never a
        second line between two parts already joined, nor a line from a part to itself. Parts
        taken out together that lines join are one run, joined round as one part."""

        def ends(edge: Mapping[str, Any]) -> tuple[str, str]:
            return self.node_of(str(edge["from"])), self.node_of(str(edge["to"]))

        runs: dict[str, set[str]] = {part: {part} for part in gone}
        for edge in self.edges:
            source, target = ends(edge)
            if source in gone and target in gone and runs[source] is not runs[target]:
                merged = runs[source] | runs[target]
                for part in merged:
                    runs[part] = merged
        for run in {id(each): each for each in runs.values()}.values():
            into = [e for e in self.edges if ends(e)[1] in run and ends(e)[0] not in run]
            out = [e for e in self.edges if ends(e)[0] in run and ends(e)[1] not in run]
            if not into or not out or (len(into) > 1 and len(out) > 1):
                continue
            chain = len(into) == 1 and len(out) == 1
            for inward in into:
                used = False
                for outward in out:
                    source, target = ends(inward)[0], ends(outward)[1]
                    if source == target or source in gone or target in gone:
                        continue
                    if self.joined(source, target):
                        continue
                    line = inward if not used else copy.deepcopy(dict(inward))
                    for key in {*ROUTE, "arrive"}:
                        line.pop(key, None)
                    line["to"] = outward["to"]
                    if outward.get("arrive"):
                        line["arrive"] = outward["arrive"]
                    if chain and not inward.get("label") and outward.get("label"):
                        line["label"] = copy.deepcopy(outward["label"])
                    if used:
                        line.pop("id", None)
                        self.data["edges"].append(line)
                    used = True

    def unpair(self, pair: dict[str, Any]) -> None:
        """A branch's pair (a part and what was put on a line of its own beside it, laid out
        only for that) left holding one: that one goes back where the pair was -- and a root
        written only to hold the pair goes back to being implied, as the file had it."""

        children = pair.get("children") or []
        layout = pair.get("layout") or {}
        made = layout.get("align") in ("center", "ports") and set(layout) <= {"kind", "align"}
        if pair.get("id") == self.root or pair.get("role") != "layout" or not made:
            return
        if len(children) != 1:
            return
        holder = self.holder(str(pair["id"]))
        if holder is None:
            return
        at = holder["children"].index(pair["id"])
        holder["children"][at] = children[0]
        self.groups.remove(pair)
        root = self.group(self.root)
        others = [group for group in self.groups if group is not root]
        implied = [str(node["id"]) for node in self.nodes]
        if (
            root is not None
            and not others
            and root.get("role") == "canvas"
            and dict(root.get("layout") or {}) == {"kind": "column", "justify": "center"}
            and [str(child) for child in root.get("children") or []] == implied
            and set(root) == {"id", "children", "layout", "role"}
        ):
            self.groups.remove(root)

    def _tidy(self) -> None:
        emptied = True
        while emptied:  # a group left holding nothing goes, and may empty its own parent
            emptied = False
            for group in list(self.groups):
                if not group.get("children") and group.get("id") != self.root:
                    self.groups.remove(group)
                    self.detach(str(group.get("id")))
                    emptied = True
        for key in ("edges", "nets", "groups"):
            if key in self.data and not self.data[key]:
                del self.data[key]

    def _gather(self, action: Mapping[str, Any]) -> list[str]:
        ids = [str(item) for item in action.get("ids") or []]
        layout = str(action.get("layout", "row"))
        role = action.get("role")
        if not ids:
            # Nothing chosen: a new group, holding a first block to build on.
            first = self._add(
                {"kind": "block", "parent": action.get("parent"), "after": action.get("after")}
            )
            ids = first
        holders = {id(self.parent_of(item)) for item in ids}
        if len(holders) != 1:
            raise EditError("Select shapes that are in the same row, column or group.")
        parent = self.parent_of(ids[0])
        children = parent["children"]
        ordered = sorted(ids, key=children.index)
        label = action.get("label") or ("Module" if role == "module" else "")
        # (A panel has its letter, not a title: named for what it is.)
        identifier = self.fresh(label or ("panel" if role == "panel" else layout))
        group: dict[str, Any] = {"id": identifier, "children": ordered, "layout": {"kind": layout}}
        if layout == "grid":
            group["layout"]["columns"] = max(1, math.ceil(math.sqrt(len(ordered))))
        if role == "module":
            group["layout"]["justify"] = "center"
            group["role"] = "module"
        if role == "panel":
            group["role"] = "panel"
        if label:
            group["label"] = label
        index = children.index(ordered[0])
        for item in ordered:
            children.remove(item)
        children.insert(index, identifier)
        self.data.setdefault("groups", []).append(group)
        return [identifier]

    def _panels(self, action: Mapping[str, Any]) -> list[str]:
        """The figure made one of ``count`` panels, ``columns`` across: a journal's figure
        of several parts, in one step. What it has that is in no panel becomes one, laid out
        as it was; the panels it lacks are added, each with a first shape to build on; and
        the figure lays them out -- in a row (as many columns as panels), a column (one), or
        a grid. Panels it has already are kept, however many. Answers the panels.

        ``rows`` (``[1, 2]``: one panel over two) or ``stacks`` (``[1, 2]``: one beside two,
        one over the other) lays them out in lines of different lengths instead: each line
        of more than one panel a row (or column) of its own in the figure's column (row)."""

        rows = [max(1, int(each)) for each in action.get("rows") or []]
        stacks = [max(1, int(each)) for each in action.get("stacks") or []]
        lines = rows or stacks
        count = max(1, min(sum(lines) or int(action.get("count") or 2), 26))
        columns = max(1, min(int(action.get("columns") or count), count))
        root = self.written_root()
        children: list[str] = root.setdefault("children", [])

        def panel(identifier: str) -> bool:
            return (self.group(identifier) or {}).get("role") == "panel"

        # Panels in lines of their own from the last time are the figure's own again first.
        for item in list(children):
            line = self.group(item)
            held = (line or {}).get("children") or []
            if line and line.get("role") == "layout" and held and all(panel(each) for each in held):
                at = children.index(item)
                children[at : at + 1] = held
                self.data["groups"].remove(line)
        frames = {str(node.get("id")) for node in self.nodes if node.get("kind") == "frame"}
        loose = [item for item in children if not panel(item) and item not in frames]
        if loose:
            identifier = self.fresh("panel")
            was = dict(root.get("layout") or {"kind": "column"})
            carried = ("kind", "columns", "gap", "align", "justify")
            layout = {key: was[key] for key in carried if key in was}
            at = children.index(loose[0])
            for item in loose:
                children.remove(item)
            children.insert(at, identifier)
            self.data.setdefault("groups", []).append(
                {"id": identifier, "role": "panel", "children": loose, "layout": layout}
            )
        while sum(1 for item in children if panel(item)) < count:
            first = self._add({"kind": "block", "parent": self.root})
            self._gather({"ids": first, "layout": "row", "role": "panel"})
        panels = [item for item in children if panel(item)]
        kept = {key: value for key, value in (root.get("layout") or {}).items() if key == "gap"}
        if lines:
            along, across_ = ("row", "column") if rows else ("column", "row")
            arranged: list[str] = []
            left = list(panels)
            for length in lines:
                part, left = left[:length], left[length:]
                if len(part) < 2:
                    arranged += part
                    continue
                identifier = self.fresh("panels")
                line = {"id": identifier, "role": "layout", "children": part}
                self.data["groups"].append({**line, "layout": {"kind": along}})
                arranged.append(identifier)
            others = [item for item in children if item not in panels]
            root["children"] = [*arranged, *left, *others]
            root["layout"] = {"kind": across_, **kept}
            return panels
        across = min(columns, len(panels))
        if across >= len(panels):
            root["layout"] = {"kind": "row", **kept}
        elif across == 1:
            root["layout"] = {"kind": "column", **kept}
        else:
            root["layout"] = {"kind": "grid", "columns": across, **kept}
        return panels

    def _frame(self, action: Mapping[str, Any]) -> list[str]:
        """A frame round the shapes and groups chosen (``ids``), wherever in the figure they
        are: behind them, or in front of them or over them as ``layer`` says. It is a shape
        of its own, which no group arranges (``flexo.frames``)."""

        chosen = [str(item) for item in action.get("ids") or []]
        round_ = [item for item in chosen if self.framable(item)]
        if not round_:
            raise EditError("Select the shapes or groups for the frame to go round.")
        identifier = self.fresh("frame")
        properties: dict[str, Any] = {"around": ", ".join(round_)}
        if action.get("layer") in {"front", "over"}:
            properties["layer"] = str(action["layer"])
        node: dict[str, Any] = {"id": identifier, "kind": "frame"}
        if action.get("label"):
            node["label"] = str(action["label"])
        node["properties"] = properties
        self.nodes.append(node)
        root = self.group(self.root)
        if root is not None:
            root.setdefault("children", []).append(identifier)
        return [identifier]

    def framable(self, identifier: str) -> bool:
        """Whether a frame can go round ``identifier``: a shape that is no frame itself, or
        a group other than the figure's own layout."""

        node = self.node(identifier)
        if node is not None:
            return node.get("kind") != "frame"
        return self.group(identifier) is not None and identifier != self.root

    def _show(self, action: Mapping[str, Any]) -> list[str]:
        """Shapes, groups or frames (``ids``) hidden, dimmed, highlighted or shown plainly
        again (``as``), where they stand: the figure's ``hide``, ``dim`` and ``highlight``
        (``flexo.showing``). ``all``: everything shown plainly."""

        settings = self.data.setdefault("figure", {})
        ids = [str(item) for item in action.get("ids") or []]
        how = str(action.get("as") or "shown")
        if how != "shown" and how not in SHOWN:
            raise EditError(f"A part can\u2019t be shown as “{how}”.")
        for key in SHOWN.values():
            kept = [] if action.get("all") else [
                item for item in settings.get(key) or [] if item not in ids
            ]
            if kept:
                settings[key] = kept
            else:
                settings.pop(key, None)
        if how in SHOWN and ids:
            settings[SHOWN[how]] = [*(settings.get(SHOWN[how]) or []), *ids]
        return ids

    def tidy_shown(self) -> None:
        """Nothing hidden, dimmed or highlighted that the figure no longer has."""

        settings = self.data.get("figure")
        if not isinstance(settings, dict) or not any(settings.get(key) for key in SHOWN.values()):
            return
        there = {str(node.get("id")) for node in self.nodes if isinstance(node, dict)}
        there |= {str(group.get("id")) for group in self.groups if isinstance(group, dict)}
        there |= {identifier for identifier, _ in self.edge_ids()}
        there |= {str(net.get("id")) for net in self.nets if isinstance(net, dict)}
        there |= set(self.shape_names())
        for key in SHOWN.values():
            kept = [item for item in settings.get(key) or [] if item in there]
            if kept:
                settings[key] = kept
            else:
                settings.pop(key, None)

    def tidy_frames(self) -> None:
        """No frame left round what the figure no longer has: one round nothing goes."""

        for node in list(self.nodes):
            if not isinstance(node, dict) or node.get("kind") != "frame":
                continue
            named = _framed(node)
            kept = [item for item in named if self.framable(item)]
            if kept == named:
                continue
            if kept:
                _frame_round(node, kept)
            else:
                self.nodes.remove(node)
                self.detach(str(node.get("id")))
                # Its lines go with it: there is no frame for them to end at.
                gone = str(node.get("id"))
                for edge in list(self.edges):
                    if gone in {self.node_of(str(edge["from"])), self.node_of(str(edge["to"]))}:
                        self.edges.remove(edge)
                mend(self.data)

    def _arrange(self, action: Mapping[str, Any]) -> list[str]:
        """A row (or column) written as it is seen folded onto lines to fit (``lines``, each
        its parts in the order they are seen): each line a group of its own laid out that way
        (``kind``), the group laying its lines out the other way, lined up as seen (``align``)
        -- made before a part is moved among them, so that only it moves. Answers the lines,
        in order."""

        identifier = str(action.get("id") or self.root)
        group = self.written_root() if identifier == self.root else self.group(identifier)
        if group is None:
            raise EditError(f"There\u2019s no group named “{identifier}”.")
        kind = str(action.get("kind", "row"))
        if kind not in {"row", "column"}:
            raise EditError(f"“{kind}” isn\u2019t a way to lay out a line.")
        lines = [[str(item) for item in line] for line in action.get("lines") or []]
        held = [str(child) for child in group.get("children") or []]
        seen = [item for line in lines for item in line]
        if len(lines) < 2 or any(not line for line in lines) or sorted(seen) != sorted(held):
            raise EditError("The figure changed while you dragged: drag again.")
        made = []
        for line in lines:
            name = self.fresh(kind, set(made))
            # Arrangement only: drawn with no frame of its own.
            self.data.setdefault("groups", []).append(
                {"id": name, "children": line, "layout": {"kind": kind}, "role": "layout"}
            )
            made.append(name)
        layout = {**(group.get("layout") or {}), "kind": "column" if kind == "row" else "row"}
        if action.get("align") in {"start", "center", "end"}:
            layout["align"] = action["align"]
        group["layout"] = layout
        group["children"] = made
        return made

    def _ungroup(self, action: Mapping[str, Any]) -> list[str]:
        identifier = str(action["id"])
        group = self.group(identifier)
        if group is None:
            raise EditError(f"There\u2019s no group named “{identifier}”.")
        if identifier == self.root:
            raise EditError("The figure\u2019s layout can\u2019t be ungrouped.")
        parent = self.parent_of(identifier)
        children = parent["children"]
        index = children.index(identifier)
        inside = list(group.get("children") or [])
        children[index : index + 1] = inside
        self.groups.remove(group)
        # A frame round the group goes round what it held.
        for node in self.nodes:
            if isinstance(node, dict) and identifier in _framed(node):
                held = [item for item in _framed(node) if item != identifier]
                _frame_round(node, [*held, *(item for item in inside if item not in held)])
        return inside

    def _shift(self, action: Mapping[str, Any]) -> list[str]:
        """Several parts of one row, column or group (``ids``) moved a place back or on
        together (``by``: -1 or 1), in the order they stand: what was before the first of
        them is after the last (or the other way), and nothing else moves."""

        ids = [str(item) for item in action.get("ids") or []]
        on = int(action.get("by") or 1) > 0
        if not ids:
            return []
        holders = {id(self.parent_of(item)) for item in ids}
        if len(holders) != 1:
            raise EditError("Select shapes that are in the same row, column or group.")
        children: list[str] = self.parent_of(ids[0])["children"]
        places = sorted(children.index(item) for item in ids)
        # (Each from the end they move toward, so one never jumps another of them.)
        for place in reversed(places) if on else places:
            other = place + (1 if on else -1)
            if 0 <= other < len(children) and children[other] not in ids:
                children[place], children[other] = children[other], children[place]
        return ids

    def _line_up(self, action: Mapping[str, Any]) -> list[str]:
        """Shapes and groups chosen anywhere in the figure (``ids``, in the order they are
        seen) put in one row or column (``kind``) of their own: a group that only arranges
        them, lined up by their lines, where the first of them stood. One chosen with the
        group that holds it goes with that group. What they leave is tidied (``tidy_left``);
        the lines between them are as they were. All in one row (column) already, nothing
        changes. Answers the parts lined up."""

        kind = str(action.get("kind", "row"))
        if kind not in {"row", "column"}:
            raise EditError(f"“{kind}” isn\u2019t a way to line shapes up.")
        # (Never a frame, which no group arranges, nor the figure's own layout.)
        named = [
            item
            for item in dict.fromkeys(str(each) for each in action.get("ids") or [])
            if self.framable(item)
        ]
        ids = [
            item for item in named if not any(item in self.descendants(other) for other in named)
        ]
        if len(ids) < 2:
            raise EditError(f"Select two or more shapes to align in a {kind}.")
        first = ids[0]
        outer = self.parent_of(first)
        if (
            all(self.parent_of(item) is outer for item in ids)
            and (outer.get("layout") or {}).get("kind", "row") == kind
        ):
            self.unchanged = True
            return ids
        stood = {str(group.get("id")): list(group.get("children") or []) for group in self.groups}
        left = [group for item in ids if (group := self.holder(item)) is not None]
        identifier = self.fresh(kind)
        children = outer.setdefault("children", [])
        if first in children:
            children[children.index(first)] = identifier
        else:
            children.append(identifier)  # held by no group: drawn at the end of the root
        # Where they go is lined up by its parts' lines too, should it run the other way and
        # have been arranged centred (as ``own_line``'s pair): the first of them keeps its
        # place, level with the parts beside it.
        layout = outer.get("layout")
        if (
            outer.get("role") == "layout"
            and isinstance(layout, dict)
            and layout.get("align") == "center"
            and layout.get("kind", "row") == ("column" if kind == "row" else "row")
        ):
            layout["align"] = "ports"
        for item in ids:
            self.detach(item)
        self.data.setdefault("groups", []).append(
            # Arrangement only: drawn with no frame of its own, its parts lined up by their
            # lines.
            {
                "id": identifier,
                "children": ids,
                "layout": {"kind": kind, "align": "ports"},
                "role": "layout",
            }
        )
        self.tidy_left(left, stood)
        return ids

    def tidy_left(self, groups: list[dict[str, Any]], stood: Mapping[str, list[str]]) -> None:
        """Groups that parts were taken out of: one left holding nothing goes, and the group
        that held it is looked at in its turn; one that only arranged its parts (no frame,
        no title), left holding a single part, gives that part its place. Never the
        figure's own layout. A frame round a group that goes is round what it held
        (``stood``: every group's parts as they were) or, of a group that gave its place,
        the part that took it -- as a shape lined up with that group is lined up with it."""

        gone: dict[str, list[str]] = {}
        left = list(groups)
        while left:
            group = left.pop(0)
            name = str(group.get("id"))
            if name == self.root or name in gone:
                continue
            held = group.get("children") or []
            holder = self.holder(name)
            if not held:
                self.groups.remove(group)
                self.detach(name)
                gone[name] = list(stood.get(name) or [])
                if holder is not None:
                    left.append(holder)
            elif (
                len(held) == 1
                and holder is not None
                and group.get("role") == "layout"
                and not group.get("label")
            ):
                (only,) = held
                holder["children"][holder["children"].index(name)] = only
                for place in (holder.get("layout") or {}).get("placements") or []:
                    if place.get("child") == name:
                        place["child"] = only
                self.groups.remove(group)
                gone[name] = [only]
                for node in self.nodes:
                    if isinstance(node, dict) and node.get("align_with") == name:
                        node["align_with"] = only

        def now(item: str) -> list[str]:
            return [each for inner in gone[item] for each in now(inner)] if item in gone else [item]

        for node in self.nodes:
            named = _framed(node) if isinstance(node, dict) else []
            if any(item in gone for item in named):
                round_ = [each for item in named for each in now(item)]
                _frame_round(node, list(dict.fromkeys(round_)))

    def _move(self, action: Mapping[str, Any]) -> list[str]:
        identifier = str(action["id"])
        if action.get("into"):
            moved = self.put_into(identifier, str(action["into"]), action.get("parent"))
            return [*moved, *self.carried(identifier, action.get("with"))]
        if action.get("line"):
            left = self.leaving([identifier])
            moved = self.own_line(
                identifier, str(action.get("of") or self.root), str(action["line"])
            )
            left()
            return moved
        parent_id = action.get("parent") or self.root
        if parent_id == identifier or parent_id in self.descendants(identifier):
            raise EditError("A group can\u2019t be moved inside itself.")
        self.parent_of(identifier)  # held somewhere written, before it moves
        target = self.group(parent_id) if parent_id != self.root else self.written_root()
        if target is None:
            raise EditError(f"There\u2019s no group named “{parent_id}”.")
        stood = self.reading_order()
        left = self.leaving([identifier, *(str(item) for item in action.get("with") or [])])
        self.detach(identifier)
        children = target.setdefault("children", [])
        index = action.get("index")
        index = len(children) if index is None else max(0, min(int(index), len(children)))
        children.insert(index, identifier)
        moved = [identifier, *self.carried(identifier, action.get("with"), stood)]
        left()
        return moved

    def leaving(self, parts: list[str]) -> Callable[[], None]:
        """The lines ``parts`` are about to be moved out of, to be tidied once they are (the
        answer, called then): a group that only arranged its parts -- a line of a row folded
        to fit, written as it was seen; a part and its branch -- left holding nothing goes,
        and left holding one part gives that part its place (``tidy_left``). A group with a
        frame or a title of its own stays, whatever it is left holding."""

        stood = {str(group.get("id")): list(group.get("children") or []) for group in self.groups}
        lines = [
            group
            for part in dict.fromkeys(parts)
            if (group := self.holder(part)) is not None
            and group.get("role") == "layout"
            and not group.get("label")
        ]

        def tidy() -> None:
            self.tidy_left([group for group in lines if group in self.groups], stood)

        return tidy

    def carried(
        self, identifier: str, others: object, stood: list[str] | None = None
    ) -> list[str]:
        """The other parts chosen with one that was moved (``others``: several chosen, one
        of them dragged) put where it now is, after it, in the order they stood (``stood``,
        as it was before the move). Never what holds it, nor what it holds. Answers them."""

        holder = self.parent_of(identifier)
        order = {part: place for place, part in enumerate(stood or self.reading_order())}
        also = [
            other
            for other in dict.fromkeys(str(item) for item in others or [])  # type: ignore[attr-defined]
            if other not in (identifier, self.root, holder.get("id"))
            and (self.node(other) is not None or self.group(other) is not None)
            and other not in self.descendants(identifier)
            and identifier not in self.descendants(other)
        ]
        also.sort(key=lambda other: order.get(other, len(order)))
        children: list[str] = holder["children"]
        for place, other in enumerate(also, 1):
            self.parent_of(other)
            self.detach(other)
            children.insert(children.index(identifier) + place, other)
        return also

    def reading_order(self) -> list[str]:
        """Every part and group in the order it is read: the root's children, each followed
        by what it holds."""

        found: list[str] = []
        left = [self.root]
        while left:
            one = left.pop(0)
            group = self.group(one)
            held = list((group or {}).get("children") or []) if one != self.root or group else []
            if one == self.root and group is None:
                held = list(self.written_root().get("children") or [])
            found += [item for item in held if item not in found]
            left = [*held, *left]
        return found

    def put_into(self, identifier: str, into: str, parent: object = None) -> list[str]:
        """A shape let go on a line (``into``) between two others: put into it, between them
        (``place_between``, in the group it was let go in), its own other lines kept."""

        if self.node(identifier) is None:
            raise EditError("Only a shape can be put into a line.")
        line = self.line_named(into)
        if identifier in (self.node_of(str(line["from"])), self.node_of(str(line["to"]))):
            raise EditError("A shape can\u2019t be put into its own line.")
        if self.groups:
            self.parent_of(identifier)  # held somewhere written, before it moves
        self.detach(identifier)
        self.place_between(identifier, line, parent)
        self.splice(line, identifier)
        self._tidy()
        return [identifier]

    def _align(self, action: Mapping[str, Any]) -> list[str]:
        """``id``, on a line of its own in a row or column, centred on the part or group
        ``with`` across the way its line runs (under one part of the row over it, or under
        the row itself); without ``with``, placed as its group places it. Alone on a line
        written for it (the last line of a row folded to fit, written as it was seen), it
        takes that line's place first: lined up across the lines, not along its own."""

        identifier = str(action["id"])
        node = self.node(identifier)
        if node is None:
            raise EditError(f"There\u2019s no shape named “{identifier}”.")
        line = self.parent_of(identifier)  # held somewhere written
        target = action.get("with")
        if target is None:
            node.pop("align_with", None)
            return [identifier]
        target = str(target)
        if target == identifier or (self.node(target) is None and self.group(target) is None):
            raise EditError(f"There\u2019s nothing named “{target}” to line it up with.")
        holder = self.holder(str(line.get("id")))
        if (
            holder is not None
            and line.get("children") == [identifier]
            and target != line.get("id")
            and self.flow_line(holder, line.get("id"))
        ):
            self.tidy_left([line], {})
        node["align_with"] = target
        return [identifier]

    def tidy_alignment(self) -> None:
        """No part left lined up with something the figure no longer has."""

        known = {
            str(item.get("id")) for item in [*self.nodes, *self.groups] if isinstance(item, dict)
        }
        for node in self.nodes:
            if (
                isinstance(node, dict)
                and "align_with" in node
                and str(node["align_with"]) not in known
            ):
                del node["align_with"]

    def own_line(self, identifier: str, of: str, side: str) -> list[str]:
        """``identifier`` on a line of its own ``side`` of the group ``of``, centred on it
        (a result under a row of steps, to compare them). Where ``of`` is held by a group
        running that way already, the part goes beside it there; else ``of`` keeps its
        place and its frame, its parts go into a new group laid out as it was, and it
        lays out that group and the part the other way, centred. Beside a part ``of`` (not
        a group) running the other way, the two go into a new group of their own, where
        ``of`` was, laid out that way."""

        if side not in {"below", "above", "right", "left"}:
            raise EditError(f"“{side}” isn\u2019t a valid position.")
        if identifier == of or of in self.descendants(identifier):
            raise EditError("A group can\u2019t be moved beside itself.")
        group = self.written_root() if of == self.root else self.group(of)
        if group is None and self.node(of) is None:
            raise EditError(f"There\u2019s no group or part named “{of}”.")
        self.parent_of(identifier)  # held somewhere written, before it moves
        way = "column" if side in {"below", "above"} else "row"
        first = side in {"above", "left"}
        holder = self.holder(of) if group is not None else self.parent_of(of)
        self.detach(identifier)
        if holder is not None and (holder.get("layout") or {}).get("kind", "row") == way:
            children = holder["children"]
            at = children.index(of)
            children.insert(at if first else at + 1, identifier)
            return [identifier]
        if group is None:
            pair = self.fresh(way)
            self.data.setdefault("groups", []).append(
                # Arrangement only: drawn with no frame of its own, the two lined up by their
                # lines (a part and what branches from it).
                {
                    "id": pair,
                    "children": [identifier, of] if first else [of, identifier],
                    "layout": {"kind": way, "align": "ports"},
                    "role": "layout",
                }
            )
            outer = self.parent_of(of)
            children = outer["children"]
            children[children.index(of)] = pair
            # Where the pair goes is lined up by its parts' lines too, should it have been
            # arranged so (centred): ``of`` keeps its place, level with the parts beside it,
            # not centred with what is now under it.
            layout = outer.get("layout")
            if (
                outer.get("role") == "layout"
                and isinstance(layout, dict)
                and layout.get("align") == "center"
            ):
                layout["align"] = "ports"
            return [identifier]
        children = list(group.get("children") or [])
        layout = dict(group.get("layout") or {})
        # The frame stays the group's own; how its parts were laid out goes with them.
        outer = {key: layout.pop(key) for key in list(layout) if key.startswith("padding")}
        outer.update({key: layout.pop(key) for key in ("width", "height") if key in layout})
        if len(children) == 1:
            inner = children[0]
        else:
            inner = self.fresh("row" if way == "column" else "column")
            self.data.setdefault("groups", []).append(
                # Arrangement only: drawn with no frame of its own.
                {
                    "id": inner,
                    "children": children,
                    "layout": layout or {"kind": "row"},
                    "role": "layout",
                }
            )
        group["children"] = [identifier, inner] if first else [inner, identifier]
        group["layout"] = {"kind": way, "align": "center", **outer}
        return [identifier]

    def _step(self, action: Mapping[str, Any]) -> list[str]:
        identifier = str(action["id"])
        parent = self.parent_of(identifier)
        children = parent["children"]
        index = children.index(identifier)
        to = max(0, min(index + int(action.get("delta", 1)), len(children) - 1))
        children.insert(to, children.pop(index))
        return [identifier]

    def _duplicate(self, action: Mapping[str, Any]) -> list[str]:
        made: list[str] = []
        renamed: dict[str, str] = {}
        for identifier in [str(item) for item in action.get("ids") or []]:
            copy_id = self.copy(identifier, renamed)
            if copy_id is None:
                continue
            if self.holder(identifier) is None and not self.groups:
                pass  # a file of nodes alone: the copy is listed after the original
            else:
                parent = self.parent_of(identifier)
                parent["children"].insert(parent["children"].index(identifier) + 1, copy_id)
            made.append(copy_id)
        for edge in list(self.edges):
            ends = [self.node_of(str(edge["from"])), self.node_of(str(edge["to"]))]
            if all(end in renamed for end in ends):
                twin = {key: copy.deepcopy(value) for key, value in edge.items() if key != "id"}
                for side, end in zip(("from", "to"), ends, strict=True):
                    twin[side] = renamed[end] + str(edge[side])[len(end) :]
                self.edges.append(twin)

        def moved(end: str) -> str | None:
            node = self.node_of(end)
            return renamed[node] + end[len(node) :] if node in renamed else None

        self.carry_nets(list(self.nets), moved)
        return made

    def _paste(self, action: Mapping[str, Any]) -> list[str]:
        def written(items: object) -> list[dict[str, Any]]:
            return [
                copy.deepcopy(dict(item))
                for item in items or []  # type: ignore[union-attr]
                if isinstance(item, Mapping) and item.get("id")
            ]

        nodes, groups = written(action.get("nodes")), written(action.get("groups"))
        top = [str(item) for item in action.get("top") or []]
        known = {str(item["id"]) for item in [*nodes, *groups]}
        if not top or not set(top) <= known:
            raise EditError("There\u2019s nothing to paste.")
        renamed: dict[str, str] = {}
        for item in [*nodes, *groups]:
            renamed[str(item["id"])] = self.fresh_copy(str(item["id"]), set(renamed.values()))
        for node in nodes:
            node["id"] = renamed[str(node["id"])]
            # The page's model lists port names where a file writes ports.
            if isinstance(node.get("ports"), list) and all(
                isinstance(p, str) for p in node["ports"]
            ):
                del node["ports"]
            self.nodes.append(node)
        for group in groups:
            group["id"] = renamed[str(group["id"])]
            group.pop("implied", None)
            group["children"] = [
                renamed.get(str(child), str(child)) for child in group.get("children") or []
            ]
            for placement in (group.get("layout") or {}).get("placements") or []:
                placement["child"] = renamed.get(placement["child"], placement["child"])
            self.data.setdefault("groups", []).append(group)
        after = action.get("after")
        for item in top:
            self.place(renamed[item], action.get("parent"), after)
            after = renamed[item]
        for edge in written(action.get("edges")):
            ends = [str(edge["from"]), str(edge["to"])]
            heads = [
                next((old for old in renamed if end == old or end.startswith(f"{old}.")), None)
                for end in ends
            ]
            if None in heads:
                continue  # a line to a part not copied
            edge.pop("id", None)
            for side, end, head in zip(("from", "to"), ends, heads, strict=True):
                edge[side] = renamed[head] + end[len(head) :]  # type: ignore[index]
            self.data.setdefault("edges", []).append(edge)

        def pasted(end: str) -> str | None:
            head = next((old for old in renamed if end == old or end.startswith(f"{old}.")), None)
            return renamed[head] + end[len(head) :] if head is not None else None

        self.carry_nets(written(action.get("nets")), pasted)
        return [renamed[item] for item in top]

    def carry_nets(self, nets: list[dict[str, Any]], moved: Callable[[str], str | None]) -> None:
        """The joined lines (nets) among parts copied, copied with them -- each end on the copy
        of its part (``moved``; ``None`` for a part not copied), their look kept: colour,
        dashes, words, where they run. Of one that reaches parts not copied too, what joins
        those copied: a joined line still, with two ends or more left on its branching side;
        a plain line of the same look, with one."""

        for net in nets:
            sources = [str(end) for end in net.get("sources") or []]
            targets = [str(end) for end in net.get("targets") or []]
            kind = net.get("kind")
            merge = kind == "merge" or (kind != "fan-out" and len(sources) > 1)
            hubs, branches = (targets, sources) if merge else (sources, targets)
            hub = moved(hubs[0]) if hubs else None
            ends = [new for end in branches if (new := moved(end)) is not None]
            if hub is None or not ends:
                continue
            look = {
                key: copy.deepcopy(value)
                for key, value in net.items()
                if key not in {"id", "kind", "sources", "targets", "sides"}
            }
            # (The sides its ends meet their shapes on, on the copies' ends.)
            given = net.get("sides") if isinstance(net.get("sides"), Mapping) else {}
            sides = {
                new: str(side)
                for end, side in given.items()
                if (new := moved(str(end))) is not None and new in {hub, *ends}
            }
            if len(ends) == 1:
                edge = {"from": ends[0], "to": hub} if merge else {"from": hub, "to": ends[0]}
                edge.update({key: look[key] for key in ("label", "tone", "line") if key in look})
                for key, end in (("depart", edge["from"]), ("arrive", edge["to"])):
                    if end in sides:
                        edge[key] = sides[end]
                self.data.setdefault("edges", []).append(edge)
                continue
            self.data.setdefault("nets", []).append(
                {
                    "id": self.fresh_copy(str(net.get("id") or "line")),
                    "kind": "merge" if merge else "fan-out",
                    "sources": ends if merge else [hub],
                    "targets": [hub] if merge else ends,
                    **look,
                    **({"sides": sides} if sides else {}),
                }
            )

    def copy(self, identifier: str, renamed: dict[str, str]) -> str | None:
        node, group = self.node(identifier), self.group(identifier)
        if node is None and group is None:
            return None
        new = self.fresh_copy(identifier)
        renamed[identifier] = new
        if node is not None:
            twin = copy.deepcopy(dict(node))
            twin["id"] = new
            self.nodes.insert(self.nodes.index(node) + 1, twin)
            return new
        assert group is not None
        twin = copy.deepcopy(dict(group))
        twin["id"] = new
        self.data["groups"].append(twin)
        twin["children"] = [self.copy(child, renamed) or child for child in group["children"]]
        for placement in (twin.get("layout") or {}).get("placements") or []:
            placement["child"] = renamed.get(placement["child"], placement["child"])
        return new

    # -- lines joined into one (a net) and parted again; where a line meets its shape --

    def line_or_net(self, identifier: str) -> tuple[str, dict[str, Any]]:
        """The line ``identifier`` names: ``("net", …)`` or ``("edge", …)``."""

        net = next((item for item in self.nets if item.get("id") == identifier), None)
        if net is not None:
            return "net", net
        edge = self.edge_named(identifier)
        if edge is None:
            said = self.line_said(identifier)
            raise EditError(f"{said[:1].upper()}{said[1:]} is gone.")
        return "edge", edge

    def end_of(self, reference: str, usual: str) -> tuple[str, str]:
        """A line's end as its shape and port: a shape named alone is at its ``usual`` port."""

        node = self.node_of(reference)
        return node, reference[len(node) + 1 :] if reference != node else usual

    def _join(self, action: Mapping[str, Any]) -> list[str]:
        """Lines into the same shape (or out of the same one) made one line that branches: a
        trunk they share, with one caption -- what they say, when they say the same or only
        one says anything; else the words ``label`` gives, the person having chosen them (a
        joined line has one caption, and no line's words are dropped unasked). ``add`` puts
        one more shape (or port) on the branching side of a line that branches already."""

        items = [self.line_or_net(str(identifier)) for identifier in action.get("ids") or []]
        if not items or (len(items) == 1 and items[0][0] == "edge" and not action.get("add")):
            raise EditError("Choose two lines or more to join.")
        sources = [str(end) for kind, item in items for end in self.ends(kind, item, "sources")]
        targets = [str(end) for kind, item in items for end in self.ends(kind, item, "targets")]
        into = {self.end_of(end, "input") for end in targets}
        out_of = {self.end_of(end, "output") for end in sources}
        added = str(action["add"]) if action.get("add") else None
        if len(into) == 1 and (len(out_of) > 1 or added):
            kind, hub, branches = "merge", targets[0], sources + ([added] if added else [])
            usual = "output"
        elif len(out_of) == 1 and (len(into) > 1 or added):
            kind, hub, branches = "fan-out", sources[0], targets + ([added] if added else [])
            usual = "input"
        elif len(into) == 1:
            raise EditError("These lines run between the same two shapes.")
        else:
            raise EditError(
                "Lines are joined where they meet: choose lines into the same shape, "
                "or out of the same one."
            )
        if added is not None and self.node(self.node_of(added)) is None:
            raise EditError(f"There\u2019s no shape named \u201c{added}\u201d to join.")
        kept: dict[tuple[str, str], str] = {}
        for end in branches:
            if self.node_of(end) == self.node_of(hub):
                raise EditError("A shape can\u2019t be joined to itself.")
            kept.setdefault(self.end_of(end, usual), end)
        if len(kept) < 2:
            raise EditError("A line that branches needs two ends or more on its branching side.")
        # What they say: a joined line has one caption, so lines saying different things are
        # joined only with the words it keeps chosen -- none dropped without a word.
        for kind_of, item in items:
            if kind_of == "edge" and (item.get("back_label") or item.get("cofactors")):
                called = (self.node(self.node_of(str(item[key]))) for key in ("from", "to"))
                ends = " to ".join(f"“{self.said(node or {})}”" for node in called)
                extra = [
                    what
                    for key, what in (("back_label", "a back label"), ("cofactors", "cofactors"))
                    if item.get(key)
                ]
                raise EditError(
                    f"The line from {ends} has {' and '.join(extra)}, which a joined line "
                    "can\u2019t carry. Remove them to join it."
                )
        said: list[Any] = []
        for _, item in items:
            if item.get("label") and item["label"] not in said:
                said.append(item["label"])
        if "label" not in action and len(said) > 1:
            words = [f"“{self.said({'label': label})}”" for label in said]
            raise EditError(
                f"These lines say {', '.join(words[:-1])} and {words[-1]}, but a joined line "
                "has one label. Choose the words it keeps."
            )
        nets = [item for kind, item in items if kind == "net"]
        net: dict[str, Any] = {
            "id": str(nets[0]["id"])
            if nets
            else self.fresh(f"{'into' if kind == 'merge' else 'from'}-{self.node_of(hub)}"),
            "kind": kind,
            "sources": list(kept.values()) if kind == "merge" else [hub],
            "targets": [hub] if kind == "merge" else list(kept.values()),
        }
        label = action.get("label") if "label" in action else (said[0] if said else None)
        if label:
            net["label"] = label
        for key in ("role", "line", "tone"):
            # How they all look, the one line looks: kept where they agree.
            values = {str(item.get(key)) for _, item in items}
            if len(values) == 1 and items[0][1].get(key) is not None:
                net[key] = items[0][1][key]
        for key in ("rail", "rail_at", "via", "joint"):
            if nets and key in nets[0]:
                net[key] = nets[0][key]
        # Where each end meets its shape, as it did: a line's leaving and arriving sides,
        # a joined line's ends'.
        joined = {*net["sources"], *net["targets"]}
        sides: dict[str, Any] = {}
        for kind_of, item in items:
            if kind_of == "net":
                given = item.get("sides") if isinstance(item.get("sides"), dict) else {}
                sides.update({str(end): side for end, side in given.items() if side})
            else:
                for key, end in (("depart", item["from"]), ("arrive", item["to"])):
                    if item.get(key):
                        sides.setdefault(str(end), item[key])
        sides = {end: side for end, side in sides.items() if end in joined}
        if sides:
            net["sides"] = sides
        at = len(self.nets)
        for kind_of, item in items:
            if kind_of == "edge":
                self.edges.remove(item)
            else:
                at = min(at, self.nets.index(item))
                self.nets.remove(item)
        self.data.setdefault("nets", []).insert(at, net)
        return [str(net["id"])]

    def net_side(self, net: dict[str, Any], end: str, side: Any) -> None:
        """The side of its shape one end of a joined line meets (``None``: where the figure
        puts it) -- a skip line made to leave its block's foot and come into the next one's
        head, down one straight trunk."""

        ends = [str(value) for value in (*(net.get("sources") or []), *(net.get("targets") or []))]
        if end not in ends:
            raise EditError("That end isn\u2019t on this line.")
        sides = net.get("sides") if isinstance(net.get("sides"), dict) else {}
        if side:
            if side not in {"north", "south", "east", "west"}:
                raise EditError(f"There\u2019s no side \u201c{side}\u201d.")
            sides[end] = side
        else:
            sides.pop(end, None)
        if sides:
            net["sides"] = sides
        else:
            net.pop("sides", None)

    def net_trunk(self, net: dict[str, Any], end: str) -> None:
        """The branch of a joined line that is its trunk: the one drawn straight into the
        shape the others join it at (or out of the one they leave), its caption above it --
        the net's first end on its branching side."""

        side = "sources" if net.get("kind") == "merge" else "targets"
        branches = [str(value) for value in net.get(side) or []]
        if end not in branches:
            raise EditError("That end isn\u2019t on this line.")
        written = list(net.get(side) or [])
        written.insert(0, written.pop(branches.index(end)))
        net[side] = written

    def ends(self, kind: str, item: Mapping[str, Any], side: str) -> list[Any]:
        """A line's ends on one ``side`` (``sources`` or ``targets``), a net's or an edge's."""

        if kind == "net":
            return list(item.get(side) or [])
        return [item["from" if side == "sources" else "to"]]

    def _separate(self, action: Mapping[str, Any]) -> list[str]:
        """A line that branches made lines of their own again, one per branch, the first
        with its caption; or, with ``end``, that one branch taken out as a line of its own
        (the rest branching still, while two are left)."""

        kind, net = self.line_or_net(str(action.get("id", "")))
        if kind != "net":
            raise EditError("Only a line that branches can be separated.")
        merge = net.get("kind") == "merge"
        hub = str((net.get("targets") if merge else net.get("sources"))[0])
        side = "sources" if merge else "targets"
        branches = [str(end) for end in net.get(side) or []]
        end = str(action["end"]) if action.get("end") else None
        if end is not None and end not in branches:
            raise EditError("That end isn\u2019t on this line.")
        parted = [end] if end is not None and len(branches) > 2 else branches
        look = {key: net[key] for key in ("role", "line", "tone") if key in net}
        sides = net.get("sides") if isinstance(net.get("sides"), dict) else {}
        made = []
        for index, branch in enumerate(parted):
            ends = (branch, hub) if merge else (hub, branch)
            edge: dict[str, Any] = {"from": ends[0], "to": ends[1]}
            if net.get("label") and len(parted) == len(branches) and index == 0:
                edge["label"] = net["label"]
            edge.update(copy.deepcopy(look))
            # Each end meets its shape where it did.
            for key, end in (("depart", ends[0]), ("arrive", ends[1])):
                if sides.get(end):
                    edge[key] = sides[end]
            self.data.setdefault("edges", []).append(edge)
            made.append(edge)
        if len(parted) == len(branches):
            self.nets.remove(net)
        else:
            net[side] = [branch for branch in branches if branch not in parted]
            for branch in parted:
                sides.pop(branch, None)
            if not sides:
                net.pop("sides", None)
        return [self.edge_id(edge) or "" for edge in made]

    def port_sides(self, identifier: str) -> dict[str, tuple[str, bool]]:
        """A shape's ports: each one's side, and whether that is only its kind's usual side
        (one it turns from, to face what it is joined to)."""

        node = self.node(identifier) or {}
        written = [port for port in node.get("ports") or [] if isinstance(port, dict)]
        if written:
            return {str(port.get("name")): (str(port.get("side")), False) for port in written}
        from flexo.components import default_ports

        ports = default_ports(str(node.get("kind") or "block"), labelled=bool(node.get("label")))
        return {port.name: (port.side.value, port.auto_side) for port in ports}

    def end_side(self, edge: dict[str, Any], key: str, side: object) -> None:
        """One end of ``edge`` (``depart``: where it leaves, ``arrive``: where it arrives)
        at ``side`` of its shape (``north``, ...; none, where the shape puts it). A port
        whose side is only its kind's usual one is asked to face it; a shape with a port
        of its own on that side (a vector's ``north``) has the line end there instead."""

        end, usual = ("from", "output") if key == "depart" else ("to", "input")
        node, port = self.end_of(str(edge[end]), usual)
        sides = self.port_sides(node)
        wanted = str(side or "").strip().lower()
        if not wanted:
            edge.pop(key, None)
            if port in sides and not sides[port][1] and port != usual and usual in sides:
                edge[end] = node  # (back at its usual port, where a line to it starts)
            return
        if wanted not in {"north", "east", "south", "west"}:
            raise EditError(f"\u201c{side}\u201d isn\u2019t a side.")
        if port not in sides or sides[port][1]:
            edge[key] = wanted
            return
        there = next((name for name, (at, _) in sides.items() if at == wanted), None)
        if there is None:
            raise EditError("This shape takes no line on that side.")
        edge.pop(key, None)
        edge[end] = node if there == usual else f"{node}.{there}"


FLOWED = frozenset({"at", "size", "tail", "from", "to", "around", "points", "region"})
"""A shape's lists written on one line: its points, ``[x, y]``, the parts it goes round, and
the region a zoom inset shows."""


def _number(value: Any) -> Any:
    """A number as a person writes it: ``120``, not ``120.0``; to a thousandth."""

    if isinstance(value, float) and math.isfinite(value):
        value = round(value, 3)
        return int(value) if value.is_integer() else value
    return value


def _plain(value: Any) -> Any:
    """``value`` as plain data, as the page sends it: what the file's own types hold."""

    return json.loads(json.dumps(value, default=str))


def _every_shape(shapes: list[Any]) -> list[dict[str, Any]]:
    """Each shape in ``shapes``, a group's own shapes too."""

    found: list[dict[str, Any]] = []
    for shape in shapes:
        if isinstance(shape, dict):
            found.append(shape)
            if shape.get("kind") == "group" and isinstance(shape.get("shapes"), list):
                found += _every_shape(shape["shapes"])
    return found


def _insert_after_id(item: dict[str, Any], key: str, value: object) -> None:
    """Write ``key`` second, under the id, as a person would."""

    if hasattr(item, "insert"):  # ruamel's round-trip mapping
        item.insert(1, key, value)
        return
    rest = {name: item.pop(name) for name in list(item) if name != "id"}
    item[key] = value
    item.update(rest)


def plot_functions(path: Path) -> list[str]:
    """The functions a plot's Python file offers -- those at its top, not named as its own
    (``_helper``) -- read without running it; none if it does not read."""

    import ast

    try:
        stat = path.stat()
        known = _FUNCTIONS.get(str(path))
        if known is not None and known[0] == (stat.st_mtime_ns, stat.st_size):
            return list(known[1])
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return []
    offered = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    ]
    # (Kept till the file changes: the page's model, read at every drawing, asks each time.)
    if len(_FUNCTIONS) > 64:
        _FUNCTIONS.clear()
    _FUNCTIONS[str(path)] = ((stat.st_mtime_ns, stat.st_size), offered)
    return list(offered)


_FUNCTIONS: dict[str, tuple[tuple[int, int], list[str]]] = {}
"""The functions a Python file offered when last read, and what the file was then."""


def _offered(base: Path | None, source: object) -> list[str]:
    """The functions of the Python file a plot names (``source``, from the folder ``base``):
    none with no folder to find it from, or for a file outside the folder a studio serves."""

    from flexo.confine import outside

    if base is None or not source or not isinstance(source, str):
        return []
    path = Path(source).expanduser()
    path = path if path.is_absolute() else base / path
    return [] if outside(path) else plot_functions(path)


def _set(item: dict[str, Any], path: list[str], value: object) -> None:
    """Set ``item[path]``, making the mappings on the way; an empty value removes the key,
    and a mapping left empty by that goes too."""

    empty = value is None or value == "" or value == [] or value == {}
    trail = [item]
    for key in path[:-1]:
        here = trail[-1]
        if key not in here or not isinstance(here[key], dict):
            if empty:
                return
            here[key] = {}
        trail.append(here[key])
    last = path[-1]
    if empty:
        trail[-1].pop(last, None)
        for parent, key in zip(reversed(trail[:-1]), reversed(path[:-1]), strict=True):
            if not parent[key] and key != "layout":
                del parent[key]
    elif isinstance(value, str) and isinstance(trail[-1], CommentedMap) and last in trail[-1]:
        # (Set as it is: ruamel would give new words the quotes of the old ones.)
        here = trail[-1]
        ordereddict.__setitem__(here, last, _requoted(here[last], value))
        here._ok.add(last)
    else:
        trail[-1][last] = value


def _requoted(old: object, words: str) -> str:
    """Words typed over words the file quoted: in the quotes the person chose for them --
    not in quotes YAML needed for what was there before (a "no", a '12'), which the new
    words may not need (``_blocks`` quotes them again if they do)."""

    import yaml

    quoted = (SingleQuotedScalarString, DoubleQuotedScalarString)
    plain = yaml.safe_dump(str(old), width=10**6).lstrip()[:1] not in ("'", '"')
    if isinstance(old, quoted) and "\n" not in words and plain:
        return type(old)(words)
    return words


def _misread(text: str) -> bool:
    """Whether ``text``, written plain, would read back as anything but itself."""

    import yaml

    return yaml.SafeLoader.resolve(yaml.SafeLoader, yaml.ScalarNode, text, (True, False)) != (
        "tag:yaml.org,2002:str"
    )


WORDS = frozenset({"label", "back_label", "caption", "title", "description", "text"})
"""Keys whose strings are words: written as typed, a new line in them no more (a block's
closing new line would be a line of their own)."""


def _blocks(value: Any, *, words: bool = False) -> Any:
    """``value`` with every new multi-line string written as a block (``|``), and every
    new string that would read back as something else (``Yes``, ``off``, ``12``) quoted.

    A grid of cells or a Newick tree typed into the page reads line by line in
    the file only as a block; a quoted string with ``\\n`` in it reads as noise. A block
    ends in a new line -- but words (``WORDS``) end where they were typed to end.
    The file is written as YAML 1.2 writes it but read as YAML 1.1 reads it, where a
    plain ``Yes`` or ``no`` is true or false: a label typed as "Yes" stays the word.
    Only plain strings change: what the file already held keeps the quoting it
    was written with.
    """

    if type(value) is str and "\n" in value:
        return LiteralScalarString(value if words or value.endswith("\n") else value + "\n")
    if type(value) is str and _misread(value):
        return SingleQuotedScalarString(value)
    if isinstance(value, dict):
        for key in list(value):
            value[key] = _blocks(value[key], words=key in WORDS)
    elif isinstance(value, list):
        # A part added among parts the file writes a line each ({id: a, label: A}) is
        # written so too, not as a block among them.
        flow = isinstance(value, CommentedSeq) and any(
            isinstance(item, CommentedMap) and item.fa.flow_style() for item in value
        )
        for index, item in enumerate(value):
            if flow and type(item) is dict:
                item = CommentedMap(item)
                item.fa.set_flow_style()
            value[index] = _blocks(item)
    return value
