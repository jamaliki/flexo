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
  an empty value removes its key;
- ``rename``: ``id`` to ``to``, everywhere it is named;
- ``delete``: ``ids`` of nodes, groups (with what they hold), edges, and nets;
- ``gather``: ``ids`` held by one group, into a new ``layout`` (row, column,
  grid) group, a titled module if ``role`` is ``module``;
- ``ungroup``: ``id``'s children take its place;
- ``move``: ``id`` into ``parent`` at ``index``; or, with ``line`` (``below``,
  ``above``, ``right``, ``left``), on a line of its own beside the group ``of``
  (the root if not given), centred on it; ``step``: ``id`` by ``delta`` places
  among its siblings;
- ``duplicate``: ``ids``, with the edges between them;
- ``read``: nothing; the page asks for the figure as it is.

A figure file that leaves its root group out stacks its parts in a column; the
first edit that needs the root written down (gathering, moving) writes it, as
the file already meant.
"""

from __future__ import annotations

import copy
import io
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

from flexo.ir.semantic import ID_PATTERN

STRUCTURAL = frozenset(
    {"add", "connect", "rename", "delete", "gather", "ungroup", "move", "step", "duplicate"}
)
"""Actions that change what the figure is made of: checked before they are kept."""


class EditError(ValueError):
    """An edit that cannot be made; the page says why."""


def apply(
    text: str, action: Mapping[str, Any], *, suffix: str = ".yaml", base: Path | None = None
) -> dict[str, Any]:
    """The figure file's words after ``action``, and the ids to choose next."""

    document = _Document(text, suffix)
    verb = str(action.get("do", ""))
    handler = getattr(document, f"_{verb}", None)
    if verb not in STRUCTURAL | {"update", "read"} or handler is None:
        raise EditError(f'unknown figure edit "{verb}"')
    was_valid = _reads(text, suffix, base)
    select = handler(action) or []
    result = document.dump()
    if verb in STRUCTURAL and was_valid:
        problem = _problem(result, suffix, base)
        if problem and document.spliced:
            # A part that cannot carry the line on (one with no output) is only fed.
            return apply(text, {**action, "splice": False}, suffix=suffix, base=base)
        if problem:
            raise EditError(f"that would break the figure: {problem}")
    return {"text": result, "select": list(select)}


def apply_to_data(
    data: Mapping[str, Any], action: Mapping[str, Any], *, base: Path | None = None
) -> dict[str, Any]:
    """``action`` made to a figure written inline in another document (a deck's
    slide): the figure's data after it, the ids to choose, and its model."""

    import yaml

    text = yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True)
    result = apply(text, action, base=base)
    return {
        "data": yaml.safe_load(result["text"]),
        "select": result["select"],
        "model": model(result["text"]),
    }


def model(text: str, *, suffix: str = ".yaml") -> dict[str, Any] | None:
    """The figure as its file writes it, for the page's inspector and outline: the
    figure's settings, nodes (with the ports each has), groups (the root among them,
    marked ``implied`` when the file leaves it out), edges under the ids the drawing
    gives them, and nets. ``None`` when the file does not read."""

    try:
        document = _Document(text, suffix)
    except Exception:
        return None
    data = json.loads(json.dumps(document.data, default=str))
    groups = list(data.get("groups") or [])
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
        parse(text, base or Path.cwd(), suffix=suffix)
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
            raise EditError("the file is not a figure yet: fix it in the source first")
        self.data.setdefault("figure", {"id": "figure"})
        self.data.setdefault("nodes", [])
        self.spliced = False

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
        return ids | {self.root}

    def node_of(self, reference: str) -> str:
        """The node a reference names: itself, or ``node.port``'s node."""

        if reference in self.node_ids():
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

    def descendants(self, identifier: str) -> list[str]:
        group = self.group(identifier)
        if group is None:
            return []
        found = []
        for child in group.get("children") or []:
            found.append(child)
            found += self.descendants(child)
        return found

    def fresh(self, base: str) -> str:
        """An unused id made from ``base`` (a label, a kind): ``encoder``, ``encoder-2``."""

        words = re.sub(r"\$|\\[A-Za-z]+|[*_`{}]", "", str(base))
        slug = re.sub(r"[^A-Za-z0-9]+", "-", words).strip("-").lower()[:24].strip("-")
        if not slug or not slug[0].isalpha():
            slug = f"part-{slug}" if slug else "part"
        taken = self.taken()
        candidate, number = slug, 2
        while candidate in taken:
            candidate, number = f"{slug}-{number}", number + 1
        return candidate

    def detach(self, identifier: str) -> None:
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
                raise EditError(f'no group "{parent}"')
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

    def _add(self, action: Mapping[str, Any]) -> list[str]:
        kind = str(action.get("kind", "block"))
        part = _parts().get(kind)
        if part is None:
            raise EditError(f'no part "{kind}" to add')
        made = copy.deepcopy(part["node"])
        overrides = dict(action.get("node") or {})
        properties = {**made.get("properties", {}), **overrides.pop("properties", {})}
        made.update(overrides)
        identifier = self.fresh(overrides.get("id") or made.get("label") or part["title"])
        item: dict[str, Any] = {"id": identifier}
        if kind != "block":
            item["kind"] = kind
        if made.get("label"):
            item["label"] = made["label"]
        if properties:
            item["properties"] = properties
        self.nodes.append(item)
        self.place(identifier, action.get("parent"), action.get("after"))
        if action.get("source"):
            source = str(action["source"])
            line = self.onward(source, identifier) if action.get("splice", True) else None
            if line is None:
                self.connect(source, identifier)
            else:
                # The line from source now ends at the new part (its words with it, as a
                # decision's "yes"), and a new line carries on to where it went.
                onward = line["to"]
                line["to"] = self.free_input(identifier)
                self.data["edges"].append({"from": identifier, "to": onward})
                self.spliced = True
        return [identifier]

    def onward(self, source: str, identifier: str) -> dict[str, Any] | None:
        """The line a part just put after ``source`` goes into: ``source``'s one line,
        when it leads to the part now right after the new one, in the same group."""

        node = self.node(identifier)
        if node is None or node.get("kind") == "attention" or self.node(source) is None:
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
            raise EditError("a part cannot be connected to itself")
        for end in (source, target):
            if self.node(self.node_of(end)) is None:
                raise EditError(f'no part "{end}" to connect')
        ends = (self.node_of(source), self.node_of(target))
        if any(
            (self.node_of(str(e["from"])), self.node_of(str(e["to"]))) == ends for e in self.edges
        ):
            raise EditError(f'"{source}" and "{target}" are connected already')
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
            # The same values for several things at once (parts coloured together): one edit.
            chosen: list[str] = []
            for target in many:
                chosen += self._update({"target": target, "values": action.get("values")})
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
            item = dict(self.edge_ids()).get(identifier)
        elif kind == "net":
            item = next((net for net in self.nets if net.get("id") == identifier), None)
        else:
            raise EditError(f'cannot edit a "{kind}"')
        if item is None:
            raise EditError(f'no {kind} "{identifier}"')
        chosen = [identifier] if identifier else []
        for key, value in values.items():
            if key == "id" and kind in {"node", "group"}:
                if value and value != identifier:
                    self.rename(identifier, str(value))
                    chosen = [str(value)]
                continue
            if key == "kind" and kind == "node":
                self.retype(item, str(value or "block"))
                continue
            _set(item, key.split("."), value)
            if kind == "edge" and key in {"arrow", "head"}:
                # A regulation head goes on an arrow with an end; a reversible step has none.
                if key == "arrow" and value in {"reversible", "none"}:
                    item.pop("head", None)
                elif (
                    key == "head"
                    and value not in (None, "", "arrow")
                    and item.get("arrow") in {"reversible", "none"}
                ):
                    item.pop("arrow", None)
            if key == "layout.kind" and kind == "group":
                layout = item.setdefault("layout", {})
                if value == "grid" and not layout.get("columns"):
                    count = len(item.get("children") or [])
                    layout["columns"] = max(1, math.ceil(math.sqrt(count)))
                elif value != "grid":
                    layout.pop("columns", None)
        return chosen

    def retype(self, item: dict[str, Any], kind: str) -> None:
        """A node made another kind: it keeps its label and tone, takes the new kind's
        starting properties, and drops what only the old kind read."""

        part = _parts().get(kind)
        if part is None:
            raise EditError(f'no part "{kind}"')
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
                f'"{new}" cannot name a part: start with a letter; letters, '
                "digits, dots, dashes and underscores after"
            )
        if new in self.taken():
            raise EditError(f'"{new}" names another part already')
        node, group = self.node(old), self.group(old)
        if node is None and group is None and old != self.root:
            raise EditError(f'no part "{old}"')
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

    def _delete(self, action: Mapping[str, Any]) -> list[str]:
        ids = [str(item) for item in action.get("ids") or []]
        edges = dict(self.edge_ids())
        nodes: set[str] = set()
        for identifier in ids:
            if identifier == self.root:
                raise EditError("the figure itself cannot be deleted")
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
            elif identifier in edges:
                if edges[identifier] in self.edges:
                    self.edges.remove(edges[identifier])
            else:
                net = next((item for item in self.nets if item.get("id") == identifier), None)
                if net is None:
                    raise EditError(f'no part "{identifier}" to delete')
                self.nets.remove(net)
        for identifier in nodes:
            node = self.node(identifier)
            if node is not None:
                self.nodes.remove(node)
            self.detach(identifier)
        if nodes:
            for edge in list(self.edges):
                if {self.node_of(str(edge["from"])), self.node_of(str(edge["to"]))} & nodes:
                    self.edges.remove(edge)
            for net in list(self.nets):
                for side in ("sources", "targets"):
                    kept = net.get(side) or []
                    net[side] = [value for value in kept if self.node_of(str(value)) not in nodes]
                if not net["sources"] or not net["targets"]:
                    self.nets.remove(net)
        self._tidy()
        return []

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
            raise EditError("choose parts that sit side by side in one row, column, or group")
        parent = self.parent_of(ids[0])
        children = parent["children"]
        ordered = sorted(ids, key=children.index)
        label = action.get("label") or ("Module" if role == "module" else "")
        identifier = self.fresh(label or layout)
        group: dict[str, Any] = {"id": identifier, "children": ordered, "layout": {"kind": layout}}
        if layout == "grid":
            group["layout"]["columns"] = max(1, math.ceil(math.sqrt(len(ordered))))
        if role == "module":
            group["layout"]["justify"] = "center"
            group["role"] = "module"
        if label:
            group["label"] = label
        index = children.index(ordered[0])
        for item in ordered:
            children.remove(item)
        children.insert(index, identifier)
        self.data.setdefault("groups", []).append(group)
        return [identifier]

    def _ungroup(self, action: Mapping[str, Any]) -> list[str]:
        identifier = str(action["id"])
        group = self.group(identifier)
        if group is None:
            raise EditError(f'no group "{identifier}"')
        if identifier == self.root:
            raise EditError("the figure's own layout cannot be taken apart")
        parent = self.parent_of(identifier)
        children = parent["children"]
        index = children.index(identifier)
        inside = list(group.get("children") or [])
        children[index : index + 1] = inside
        self.groups.remove(group)
        return inside

    def _move(self, action: Mapping[str, Any]) -> list[str]:
        identifier = str(action["id"])
        if action.get("line"):
            return self.own_line(
                identifier, str(action.get("of") or self.root), str(action["line"])
            )
        parent_id = action.get("parent") or self.root
        if parent_id == identifier or parent_id in self.descendants(identifier):
            raise EditError("a group cannot go inside itself")
        self.parent_of(identifier)  # held somewhere written, before it moves
        target = self.group(parent_id) if parent_id != self.root else self.written_root()
        if target is None:
            raise EditError(f'no group "{parent_id}"')
        self.detach(identifier)
        children = target.setdefault("children", [])
        index = action.get("index")
        index = len(children) if index is None else max(0, min(int(index), len(children)))
        children.insert(index, identifier)
        return [identifier]

    def own_line(self, identifier: str, of: str, side: str) -> list[str]:
        """``identifier`` on a line of its own ``side`` of the group ``of``, centred on it
        (a result under a row of steps, to compare them). Where ``of`` is held by a group
        running that way already, the part goes beside it there; else ``of`` keeps its
        place and its frame, its parts go into a new group laid out as it was, and it
        lays out that group and the part the other way, centred."""

        if side not in {"below", "above", "right", "left"}:
            raise EditError(f'no side "{side}" to put a part on')
        if identifier == of or of in self.descendants(identifier):
            raise EditError("a group cannot go beside itself")
        group = self.written_root() if of == self.root else self.group(of)
        if group is None:
            raise EditError(f'no group "{of}"')
        self.parent_of(identifier)  # held somewhere written, before it moves
        way = "column" if side in {"below", "above"} else "row"
        first = side in {"above", "left"}
        holder = self.holder(of)
        self.detach(identifier)
        if holder is not None and (holder.get("layout") or {}).get("kind", "row") == way:
            children = holder["children"]
            at = children.index(of)
            children.insert(at if first else at + 1, identifier)
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
        return made

    def copy(self, identifier: str, renamed: dict[str, str]) -> str | None:
        node, group = self.node(identifier), self.group(identifier)
        if node is None and group is None:
            return None
        new = self.fresh(identifier)
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


def _insert_after_id(item: dict[str, Any], key: str, value: object) -> None:
    """Write ``key`` second, under the id, as a person would."""

    if hasattr(item, "insert"):  # ruamel's round-trip mapping
        item.insert(1, key, value)
        return
    rest = {name: item.pop(name) for name in list(item) if name != "id"}
    item[key] = value
    item.update(rest)


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
    else:
        trail[-1][last] = value


def _blocks(value: Any) -> Any:
    """``value`` with every new multi-line string written as a block (``|``).

    A grid of cells or a Newick tree typed into the page reads line by line in
    the file only as a block; a quoted string with ``\\n`` in it reads as noise.
    Only plain strings change: what the file already held keeps the quoting it
    was written with.
    """

    if type(value) is str and "\n" in value:
        return LiteralScalarString(value if value.endswith("\n") else value + "\n")
    if isinstance(value, dict):
        for key in list(value):
            value[key] = _blocks(value[key])
    elif isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _blocks(item)
    return value
