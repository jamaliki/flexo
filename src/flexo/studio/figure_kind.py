"""Figures in the studio: a figure file edited as its YAML, drawn as it changes.

The document the page edits is ``{"text": ...}``, the file's own words, so its
comments and order survive saving. The page shows the figure's parts (nodes,
groups, edges) beside the text, and selecting one marks it in the drawing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from flexo.studio import Drawing, Message, Page

NEW_FIGURE = """\
# A flexo figure: nodes, then the edges between them. See docs/guide.md.
figure:
  id: figure
  style: paper
nodes:
- id: shape
"""
"""A new figure file: one shape with no words yet, as a new figure on a slide starts. The
editor shows what it is, faintly, until its words are typed; nothing is drawn for it."""

SAMPLE_FIGURE = """\
# A flexo figure: nodes, then the edges between them. See docs/guide.md.
figure:
  id: figure
  style: paper
nodes:
- id: x
  kind: text
  label: Input $x$
- id: encoder
  label: Encoder
  properties:
    tone: encoder
- id: y
  kind: text
  label: Output $y$
edges:
- from: x
  to: encoder
- from: encoder
  to: y
"""
"""A small figure to try things on: an input, an encoder and an output."""


GUIDE = """\
A flexo figure file: YAML naming what the figure is, not where things go -- flexo lays it out
and routes every line.

figure: {id, style (a theme: paper, tikz, dark, sketch, ... or a theme file), palette, width}
nodes: each {id, label, kind (block by default; text, op, circle, feature-strip, mlp,
  attention, channels, inset, ...), properties: {tone: encoder|head|attention|..., badge, ...}}
Genetics: kind construct, properties {parts: [{type: promoter|rbs|cds|terminator|operator|origin|
  insulator|primer|site|region, label, id (makes a port), strand: + or -, tone}]}; kind plasmid,
  properties {length: bp, features: [{type, label, start, end, strand}]}.
Proteins: kind protein, properties {length, features: [{type: domain|region|motif|transmembrane|
  signal|mutation|phosphorylation|...|disulfide, label, start, end (or at, for a site)}],
  tracks: [{label, start, end, delete: "61-121"}], secondary: DSSP string (H helix, E strand,
  T turn), sequence: one-letter, helix: ribbon|cylinder|spiral}. Trees: kind tree,
  properties {newick,
  layout: rectangular|circular, clades: [{tips: "A, B", label}], support}. The bench: kind
  wellplate {wells: 96, groups: [{wells: "A1-A12", label}]}; kind timeline {unit: day,
  events: [{at, label}], spans: [{start, end, label}]}.
Grids: kind cells, properties {grid: "K . K\n. Y R" (one row per line, one symbol per word,
  . empty, numbers shaded on ramp), key: [{symbol, color: tone or #hex, mark, label}], cell,
  gap, corner, lines: ink|muted|#hex, row_labels / column_labels: numbers|letters|"a, b",
  row_side, column_side, ramp: "#lo, #hi", range: "lo, hi", values: true}.
edges: each {from: node or node.port, to: node or node.port, label, role, head: triangle|stealth|
  latex|open|hollow|dot|diamond|square, or SBGN's inhibition|catalysis|stimulation|necessary|
  modulation,
  arrow: none|both|reversible, tail (the start's head, with arrow: both), back_label, cofactors:
  [ATP, ADP], shape: orthogonal|straight|curved, line: dashed|dotted, tone, width (pt), head_size
  (1.5 = half as large again)}
groups: each {id, children: [ids], layout: {kind: row|column|grid, gap}, label}; the root group
  (figure.root, "root" by default) holds the rest. A file without groups stacks its nodes.
Labels are markup: $maths$, *emphasis*, **strong**. `flexo schema` prints the full schema.
"""


class FigureKind:
    name = "figure"
    title = "Figure"
    static = Path(__file__).parent / "static" / "figure"

    def mended(self, document: object, notes: list | None = None, base: object = None) -> object:
        """A figure two edits were merged into, with no line left naming a shape gone."""

        from flexo.studio.figure_edit import mend

        mend(document)
        return document

    def claims(self, document: object) -> bool:
        return isinstance(document, dict) and ("nodes" in document or "figure" in document)

    def new(self, path: Path) -> dict[str, Any]:
        # Named for its file, as a deck or a theme is: "Pipeline figure" is pipeline-figure.
        from flexo.studio.figure_edit import _slug

        return {"text": NEW_FIGURE.replace("  id: figure\n", f"  id: {_slug(path.stem)}\n", 1)}

    def adopt(self, data: dict[str, Any]) -> dict[str, Any]:
        """A parsed figure document (one written inline in a deck) as a file's words."""

        return {"text": yaml.safe_dump(data, sort_keys=False, allow_unicode=True)}

    def load(self, path: Path) -> dict[str, Any]:
        return {"text": path.read_text(encoding="utf-8")}

    def save(self, path: Path, document: dict[str, Any]) -> None:
        path.write_text(document["text"], encoding="utf-8")

    def dump(self, document: dict[str, Any]) -> str:
        return document["text"]

    def parse(self, text: str) -> dict[str, Any]:
        yaml.safe_load(text)  # refuse what does not read, before anyone sees it
        return {"text": text}

    def theme_of(self, document: dict[str, Any]) -> str | None:
        data = yaml.safe_load(document["text"])
        figure = data.get("figure") if isinstance(data, dict) else None
        style = figure.get("style") if isinstance(figure, dict) else None
        return str(style) if style else None

    def with_theme(self, document: dict[str, Any], theme: str, base: Path) -> dict[str, Any]:
        from flexo.studio.figure_edit import apply

        action = {"do": "update", "target": {"type": "figure"}, "values": {"figure.style": theme}}
        result = apply(document["text"], action, suffix=document.get("suffix", ".yaml"), base=base)
        return {**document, "text": result["text"]}

    def guide(self) -> str:
        return GUIDE

    def describe(self, before: Any, after: Any) -> list[dict[str, Any]]:
        """What an edit did, said as the figure has it ("added “Cache”", "connected “A” to
        “B”"), not as lines of its file -- but for a file that does not read as a figure."""

        import difflib

        said = _changes(_figure_of(before), _figure_of(after))
        if said is not None:
            return said
        old = (before or {}).get("text", "").splitlines()
        new = (after or {}).get("text", "").splitlines()
        changed = [
            (tag, start)
            for tag, start, _, _, _ in difflib.SequenceMatcher(None, old, new).get_opcodes()
            if tag != "equal"
        ]
        if not changed:
            return []
        first = changed[0][1] + 1
        return [
            {
                "text": f"edited line {first}"
                if len(changed) == 1
                else f"edited {len(changed)} places",
                "where": {"line": first, "label": f"line {first}"},
            }
        ]

    def act(self, document: dict[str, Any], action: dict[str, Any], base: Path) -> dict[str, Any]:
        """An edit made on the page (add, connect, rename, ...), made to the file's words."""

        from flexo.studio.figure_edit import apply

        if action.get("do") == "structure-view":
            return {"document": document, "view": _structure_view(document, action, base)}
        if action.get("do") == "structure-settings":
            spec = _as_drawn(document, base)
            return {"document": document, "settings": settings_of(spec, str(action.get("id")))}
        if action.get("do") == "structure-fetch":
            # One that can't be had is an answer, said in the dialog -- not a failed request
            # (which the browser would also log as an error).
            from flexo.studio.figure_edit import EditError
            from flexo.studio.plain import explain

            try:
                return {"document": document, "id": fetched(str(action.get("id") or ""))}
            except EditError as error:
                return {"document": document, "failed": explain(error)}
        result = apply(document["text"], action, suffix=document.get("suffix", ".yaml"), base=base)
        from flexo.studio.figure_edit import model

        suffix = document.get("suffix", ".yaml")
        return {
            "document": {**document, "text": result["text"]},
            "select": result["select"],
            "model": model(result["text"], suffix=suffix),
        }

    def check(self, document: dict[str, Any], base: Path) -> list[str]:
        drawing = self.draw(document, base)
        return [message.text for message in drawing.messages if message.severity == "error"]

    def catalog(self) -> dict[str, Any]:
        from flexo.colour import design_palettes
        from flexo.components import COMPONENTS
        from flexo.fonts import available_families
        from flexo.studio.figure_parts import catalogue
        from flexo.themes import theme_names

        found = {
            "themes": list(theme_names()),
            "palettes": {name: list(colours) for name, colours in design_palettes().items()},
            "fonts": list(available_families()),
            "components": sorted(COMPONENTS),
        }
        return {**found, "editor": catalogue(found)}

    def draw(
        self, document: dict[str, Any], base: Path, hints: dict[str, Any] | None = None
    ) -> Drawing:
        from flexo.compiler import compile_figure
        from flexo.diagnostics import FlexoError
        from flexo.lint import lint_compilation
        from flexo.studio.figure_edit import model
        from flexo.studio.plain import explain

        # The figure as written, for the page's inspector, whether or not it draws.
        try:
            info = {"model": model(document["text"], suffix=document.get("suffix", ".yaml"))}
        except Exception:  # not a shape the inspector can list: the drawing says why
            info = {}
        said_first: list[Message] = []
        wrong: set[str] = set()  # the shapes drawn as plain boxes
        # A line to a shape there is none of is left out, and said; the rest is drawn.
        document = _strays(document, said_first)
        try:
            spec = parse(document["text"], base, suffix=document.get("suffix", ".yaml"))
        except (yaml.YAMLError, json.JSONDecodeError) as error:
            return Drawing(
                [], [Message(_yaml_problem(error), "error", _yaml_line(error))], info=info
            )
        except FlexoError as error:
            # A shape that can't be drawn as it is (a protein with no length): said by its
            # name, plainly, the message leading to it -- and the rest of the figure drawn,
            # it a plain box with its words meanwhile.
            spec = _stand_in(document, base, error, info, said_first, wrong)
            if spec is None:
                return Drawing([], said_first, info=info)
        except Exception as error:
            return Drawing([], [Message(explain(error), "error")], info=info)
        # So too a shape found wanting as it is drawn (a plasmid of -5 bp, a tree whose
        # Newick does not read).
        try:
            drawn = _despite(document, base, spec, info, said_first, wrong, compile_figure)
        except Exception as error:
            return Drawing([], [Message(explain(error), "error")], info=info)
        if drawn is None:
            return Drawing([], said_first, info=info)
        spec, compilation = drawn
        report = lint_compilation(compilation)
        info["tones"] = _tones(spec)
        page = Page(
            spec.id, compilation.document.text, label=spec.id, extra={"outline": outline(spec)}
        )
        files = [base / value for value in (spec.style, spec.palette) if _is_file(value)]
        said = [*report.diagnostics, *structure_problems(spec)]
        return Drawing([page], [*said_first, *(_message(item) for item in said)], files, info)

    def export(
        self,
        document: dict[str, Any],
        base: Path,
        stem: str,
        formats: list[str],
        *,
        into: Path | None = None,
    ) -> list[Path]:
        from flexo.diagnostics import FlexoError
        from flexo.export import build
        from flexo.studio.figure_edit import model

        # Exported as it is drawn: lines to shapes it has none of left out, a shape that
        # can't be drawn as written (a protein with no length) a plain box of its words --
        # each said in a note with what was made.
        said: list[Message] = []
        wrong: set[str] = set()
        document = _strays(document, said)
        info = {"model": model(document["text"], suffix=document.get("suffix", ".yaml"))}
        try:
            spec = parse(document["text"], base, suffix=document.get("suffix", ".yaml"))
        except FlexoError as error:
            spec = _stand_in(document, base, error, info, said, wrong)
            if spec is None:
                raise ValueError(" ".join(message.text for message in said)) from None
        made = _despite(
            document,
            base,
            spec,
            info,
            said,
            wrong,
            lambda spec: build(spec, into or base / "build", stem=stem, formats=tuple(formats)),
        )
        if made is None:
            raise ValueError(" ".join(message.text for message in said))
        self.export_notes = [_exported_as(message.text) for message in said]
        result = made[1]
        written = list(result.outputs.existing())
        if into is not None and "editable" not in formats and len(written) > 1:
            # The editable SVG is written whatever is asked for: made aside, to be handed
            # over, only what was asked for is.
            result.outputs.editable_svg.unlink()
            written.remove(result.outputs.editable_svg)
        return written


def _tones(spec) -> dict[str, Any]:
    """The figure's tone colours, for the page's colour chips: the theme's, in order,
    and which of them each tone name the figure uses paints with."""

    from flexo.emit import _tone_map
    from flexo.themes import TONE_COUNT, figure_palette, figure_style, with_tone_roles

    palette = with_tone_roles(figure_palette(spec))
    colours = [
        {"fill": palette.get(f"tone-{index}-fill"), "stroke": palette.get(f"tone-{index}-stroke")}
        for index in range(1, TONE_COUNT + 1)
    ]
    # The theme's grey, as a shape toned ``neutral`` is painted (its block paint).
    neutral = {"fill": palette.get("block-fill"), "stroke": palette.get("block-stroke")}
    return {"colours": colours, "used": _tone_map(spec, figure_style(spec)), "neutral": neutral}


def outline(spec) -> dict[str, Any]:
    """The figure's parts as the page lists them: groups holding nodes, and edges."""

    def words(label) -> str:
        return "".join(run.text for run in label)

    nodes = {
        node.id: {"id": node.id, "type": "node", "kind": node.kind, "label": words(node.label)}
        for node in spec.nodes
    }
    groups = {group.id: group for group in spec.groups}

    def tree(identifier: str, seen: frozenset[str] = frozenset()) -> dict[str, Any]:
        if identifier in nodes:
            return nodes[identifier]
        group = groups.get(identifier)
        if group is None or identifier in seen:
            return {"id": identifier, "type": "missing", "label": ""}
        return {
            "id": identifier,
            "type": "group",
            "kind": group.layout.kind,
            "label": words(group.label),
            "children": [tree(child, seen | {identifier}) for child in group.children],
        }

    edges = [
        {
            "id": edge.id,
            "source": edge.source.node_id,
            "target": edge.target.node_id,
            "label": words(edge.label),
        }
        for edge in spec.edges
    ]
    return {"root": tree(spec.root), "edges": edges, "nets": [net.id for net in spec.nets]}


def parse(text: str, base: Path, *, suffix: str = ".yaml"):
    """A figure from its file's words, theme and palette files -- and the pictures and
    structures its parts draw -- found from ``base``."""

    from flexo.serialization import parse_figure

    document = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
    if not isinstance(document, dict):
        raise ValueError("a figure file is a mapping: figure, nodes, edges, groups")
    figure = document.get("figure")
    if isinstance(figure, dict):
        for key in ("theme", "style", "palette"):
            value = figure.get(key)
            if _is_file(value) and (base / value).is_file():
                figure[key] = str((base / value).resolve())
    for node in document.get("nodes") or []:
        properties = node.get("properties") if isinstance(node, dict) else None
        for key in ("source", "density"):
            value = properties.get(key) if isinstance(properties, dict) else None
            if isinstance(value, str) and value and (base / value).is_file():
                properties[key] = str((base / value).resolve())
    return parse_figure(document)


def _structure_view(document: dict[str, Any], action: dict[str, Any], base: Path) -> Any:
    """A structure's trace and turn, for the page to turn while it is dragged round."""

    return view_of(_as_drawn(document, base), str(action.get("id")))


def _as_drawn(document: dict[str, Any], base: Path) -> Any:
    """The figure as it is drawn -- a line to a shape it has none of left out, a shape that
    can't be drawn as written a plain box -- for what is asked of one of its parts (a
    structure's settings), which the rest being wrong does not change."""

    from flexo.diagnostics import FlexoError

    document = _strays(document, [])
    try:
        return parse(document["text"], base, suffix=document.get("suffix", ".yaml"))
    except FlexoError as error:
        spec = _stand_in(document, base, error, {}, [], set())
        if spec is None:
            raise
        return spec


def settings_of(spec, identifier: str) -> dict[str, Any]:
    """The mol-sketch settings the structure ``identifier`` in ``spec`` is drawn with --
    its look's, the figure's colours, and its own -- with mol-sketch's looks and palettes:
    what the studio shows beside the settings a structure may be given."""

    from flexo.structures import structure_settings
    from flexo.studio.figure_edit import EditError
    from flexo.themes import figure_palette, figure_style

    node = next((item for item in spec.nodes if item.id == identifier), None)
    if node is None or node.kind != "structure":
        raise EditError(f"“{identifier}” isn't a structure.")
    return structure_settings(node, figure_style(spec), figure_palette(spec))


def fetched(pdb_id: str) -> str:
    """A PDB entry downloaded before a structure is made of it: its ID, or an EditError
    saying why it couldn't be (for any kind that draws figures)."""

    from flexo.structures import fetch_structure
    from flexo.studio.figure_edit import EditError

    try:
        return fetch_structure(pdb_id)
    except ValueError as error:
        raise EditError(str(error)) from None


def structure_problems(spec) -> list[Any]:
    """What keeps each structure in ``spec`` from being drawn as written, as warnings: the
    figure is drawn all the same, a structure that can't be had as a panel saying why."""

    from flexo.structures import structure_problem
    from flexo.themes import figure_style

    style = figure_style(spec)
    found = [structure_problem(node, style) for node in spec.nodes if node.kind == "structure"]
    return [item for item in found if item is not None]


def view_of(spec, identifier: str) -> dict[str, Any]:
    """The trace and turn of the structure ``identifier`` in ``spec``, drawn as ``spec``
    says (its theme chooses the look): for any kind that draws figures."""

    from flexo.structures import structure_view
    from flexo.studio.figure_edit import EditError
    from flexo.themes import figure_palette, figure_style

    node = next((item for item in spec.nodes if item.id == identifier), None)
    if node is None or node.kind != "structure":
        raise EditError(f"“{identifier}” isn't a structure.")
    return structure_view(node, figure_style(spec), figure_palette(spec))


def _is_file(value: object) -> bool:
    return isinstance(value, str) and value.lower().endswith((".yaml", ".yml", ".json"))


_PLAIN = {
    "layout.width.grown": (
        "The figure is wider than its page. Choose a wider Width, or fewer shapes in a row."
    ),
}
"""Diagnostics said in the editor's words, not the file's (what to do there, not what to write)."""


def _message(diagnostic) -> Message:
    text = _PLAIN.get(diagnostic.code) or (
        diagnostic.message + (f" ({diagnostic.hint})" if diagnostic.hint else "")
    )
    severity = "note" if diagnostic.severity.value == "info" else diagnostic.severity.value
    return Message(text, severity, diagnostic.entity_id or "", code=diagnostic.code)


def _shape_problem(diagnostic, info: dict[str, Any]) -> Message:
    """What keeps a shape from being drawn, said of it by its name ("“Spike” can't be drawn
    yet: a protein needs its length in residues.") -- the editor's words: its panel is where
    it is put right, not a file to write in."""

    nodes = (info.get("model") or {}).get("nodes") or []
    node = next((item for item in nodes if item.get("id") == diagnostic.entity_id), None)
    if node is None:
        return _message(diagnostic)
    label = node.get("label")
    words = (
        label
        if isinstance(label, str)
        else " ".join(str(run.get("text", "")) for run in label or [] if isinstance(run, dict))
    )
    # (Its words as read: emphasis, code and maths marks left out.)
    name = re.sub(r"\]\{[^}]*\}|[*`$\[]", "", words).strip()
    message = diagnostic.message.strip()
    first = message.split(" ", 1)[0]
    lower = message if len(first) > 1 and first.isupper() else message[:1].lower() + message[1:]
    called = f"\u201c{name}\u201d" if name else f"This {node.get('kind') or 'shape'!s}"
    return Message(
        f"{called} can\u2019t be drawn yet: {lower} Choose it to set this in its panel.",
        "error",
        diagnostic.entity_id or "",
        code=diagnostic.code,
    )


def _exported_as(said: str) -> str:
    """What an export says of a shape it drew as a plain box, or a line it left out."""

    found = re.match(r"(\u201c[^\u201d]*\u201d|This \S+) can\u2019t be drawn yet: ", said)
    if found:
        why = said[found.end() :].split(" Choose it")[0]
        return f"{found.group(1)} is drawn as a plain box: {why}"
    return said


def _strays(document: dict[str, Any], said: list[Message]) -> dict[str, Any]:
    """The figure without its lines to (or from) shapes it has none of, each said in
    ``said`` -- or as it is, with none (or should it not read)."""

    from flexo.studio.figure_edit import astray

    json_file = document.get("suffix", ".yaml") == ".json"
    try:
        data = json.loads(document["text"]) if json_file else yaml.safe_load(document["text"])
    except (yaml.YAMLError, json.JSONDecodeError, TypeError):
        return document
    ids: list[str] = []
    lost = astray(data, ids)
    if not lost:
        return document
    # (Each at its line: chosen from the message, its panel says where it goes.)
    said += [Message(line, "warning", where) for line, where in zip(lost, ids, strict=True)]
    text = (
        json.dumps(data, indent=2, ensure_ascii=False)
        if json_file
        else yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    )
    return {**document, "text": text}


def _stand_in(
    document: dict[str, Any],
    base: Path,
    error,
    info: dict[str, Any],
    said: list[Message],
    wrong: set[str],
) -> Any:
    """The figure with each shape ``error`` names (and those in ``wrong``, found so
    before) a plain box of its words, each said in ``said`` by its name; None, said too,
    should ``error`` name no shape not found so already, or the figure not draw even so."""

    said += [_shape_problem(item, info) for item in error.diagnostics]
    named = {item.entity_id for item in error.diagnostics if item.entity_id} - wrong
    if not named:
        return None
    wrong |= named
    return _without(document, base, wrong)


def _despite(
    document: dict[str, Any],
    base: Path,
    spec,
    info: dict[str, Any],
    said: list[Message],
    wrong: set[str],
    attempt,
) -> tuple[Any, Any] | None:
    """``spec`` and what ``attempt(spec)`` makes of it -- a shape it fails at (a plasmid of
    -5 bp, a tree whose Newick does not read) a plain box of its words, and tried again, so
    one wrong shape does not blank the rest; each said in ``said``, and kept in ``wrong``
    with those found so before. None should it fail otherwise."""

    from flexo.diagnostics import FlexoError

    while True:
        try:
            return spec, attempt(spec)
        except FlexoError as error:
            spec = _stand_in(document, base, error, info, said, wrong)
            if spec is None:
                return None


def _without(document: dict[str, Any], base: Path, wrong: set[str]) -> Any:
    """The figure with each shape in ``wrong`` (that can't be drawn) a plain box of its
    words, so the rest is drawn: None should it name none of them, or not draw even so."""

    from flexo.diagnostics import FlexoError

    suffix = document.get("suffix", ".yaml")
    data = json.loads(document["text"]) if suffix == ".json" else yaml.safe_load(document["text"])
    if not isinstance(data, dict):
        return None
    nodes = [node for node in data.get("nodes") or [] if isinstance(node, dict)]
    if not any(node.get("id") in wrong for node in nodes):
        return None
    for node in nodes:
        if node.get("id") in wrong:
            node.pop("properties", None)
            node["kind"] = "block"
    try:
        return parse(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), base)
    except (FlexoError, ValueError, TypeError, yaml.YAMLError):
        return None


def _yaml_problem(error: Exception) -> str:
    problem = getattr(error, "problem", None)
    return f"the file does not read as YAML: {problem or error}"


def _yaml_line(error: Exception) -> str:
    mark = getattr(error, "problem_mark", None)
    return f"line {mark.line + 1}" if mark is not None else ""


def _figure_of(document: Any) -> dict[str, Any] | None:
    """A figure file's nodes, lines, groups and settings, as written; None if it does not
    read as one."""

    try:
        data = yaml.safe_load((document or {}).get("text", "") or "") or {}
    except yaml.YAMLError:
        return None
    return _read_figure(data)


def figure_changes(old: Any, new: Any) -> list[str]:
    """What an edit did to a figure written in another document (a deck's slide), as its
    data before and after: a few notes ("added “Cache”", "moved “Encoder”"); none when it
    does not read as a figure."""

    return [note["text"] for note in _changes(_read_figure(old), _read_figure(new)) or []]


def _read_figure(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict) or not isinstance(data.get("nodes", []), list):
        return None
    nodes = {
        str(node["id"]): node
        for node in data.get("nodes") or []
        if isinstance(node, dict) and "id" in node
    }

    def end(value: Any) -> str:
        value = str(value)
        return value if value in nodes else value.rsplit(".", 1)[0]

    edges = {}
    for edge in data.get("edges") or []:
        if isinstance(edge, dict) and "from" in edge and "to" in edge:
            edges[(end(edge["from"]), end(edge["to"]))] = edge
    groups = {
        str(group["id"]): group
        for group in data.get("groups") or []
        if isinstance(group, dict) and "id" in group
    }
    # A line that branches, by its id: the pairs of parts its branches join, and its hub.
    nets = {}
    for net in data.get("nets") or []:
        if isinstance(net, dict) and net.get("id") and net.get("sources") and net.get("targets"):
            merge = net.get("kind") == "merge"
            sources = [end(item) for item in net["sources"]]
            targets = [end(item) for item in net["targets"]]
            hub = targets[0] if merge else sources[0]
            branches = sources if merge else targets
            pairs = {(item, hub) if merge else (hub, item) for item in branches}
            nets[str(net["id"])] = {"net": net, "hub": hub, "merge": merge, "pairs": pairs}
    rest = {
        key: value for key, value in data.items() if key not in {"nodes", "edges", "groups", "nets"}
    }
    return {"nodes": nodes, "edges": edges, "groups": groups, "nets": nets, "rest": rest}


def _changes(old: dict[str, Any] | None, new: dict[str, Any] | None) -> list[dict] | None:
    """What changed between two readings of a figure file, a few notes at most."""

    if old is None or new is None:
        return None

    def name(node: dict[str, Any]) -> str:
        words = re.sub(r"\s+", " ", str(node.get("label") or "")).strip()
        if words:
            return f"\u201c{words}\u201d"
        kind = str(node.get("kind") or "block")
        return "a shape" if kind == "block" else f"a {kind.replace('-', ' ')}"

    def called(identifier: str) -> str:
        node = new["nodes"].get(identifier) or old["nodes"].get(identifier) or {}
        return name(node)

    notes: list[dict[str, Any]] = []
    added = [key for key in new["nodes"] if key not in old["nodes"]]
    gone = [key for key in old["nodes"] if key not in new["nodes"]]
    if len(added) > 2:
        notes.append({"text": f"added {len(added)} shapes", "where": None})
    else:
        notes += [{"text": f"added {called(key)}", "where": {"id": key}} for key in added]
    if len(gone) > 2:
        notes.append({"text": f"deleted {len(gone)} shapes", "where": None})
    else:
        notes += [{"text": f"deleted {called(key)}", "where": None} for key in gone]
    for key, node in new["nodes"].items():
        was = old["nodes"].get(key)
        if was is None or was == node:
            continue
        before, after = str(was.get("label") or "").strip(), str(node.get("label") or "").strip()
        if before != after:
            text = (
                f"named {name(was)} \u201c{after}\u201d"
                if not before
                else f"emptied {name(was)}"
                if not after
                else f"renamed {name(was)} to {name(node)}"
            )
        elif was.get("kind") != node.get("kind"):
            kind = str(node.get("kind") or "block").replace("-", " ")
            text = f"made {name(was)} a {kind}"
        else:
            text = f"changed {name(node)}"
        notes.append({"text": text, "where": {"id": key}})
    # A part there before put into a line (let go on it): said as that, not as the lines.
    kept = [key for key in new["nodes"] if key in old["nodes"]]
    spliced = [
        (pair, key)
        for pair in old["edges"]
        if pair not in new["edges"]
        for key in kept
        if key not in pair
        and (pair[0], key) in new["edges"]
        and (key, pair[1]) in new["edges"]
        and ((pair[0], key) not in old["edges"] or (key, pair[1]) not in old["edges"])
    ]
    for pair, key in spliced:
        notes.append(
            {
                "text": f"put {called(key)} between {called(pair[0])} and {called(pair[1])}",
                "where": {"id": key},
            }
        )
    told = {(pair[0], key) for pair, key in spliced} | {(key, pair[1]) for pair, key in spliced}
    # Lines joined into one (a net), or one parted into lines: said as that, not line by line.
    for key, net in new["nets"].items():
        was = old["nets"].get(key)
        joined = net["pairs"] & set(old["edges"])
        way = "into" if net["merge"] else "out of"
        if was is None and joined:
            notes.append({"text": f"joined the lines {way} {called(net['hub'])}", "where": None})
            told |= joined
        elif was is None:
            notes.append({"text": f"added a line {way} {called(net['hub'])}", "where": None})
        elif was["net"] != net["net"]:
            notes.append({"text": f"changed the line {way} {called(net['hub'])}", "where": None})
            told |= (net["pairs"] ^ was["pairs"])
    for key, net in old["nets"].items():
        if key in new["nets"]:
            continue
        parted = net["pairs"] & set(new["edges"])
        way = "into" if net["merge"] else "out of"
        verb = "separated" if parted else "removed"
        notes.append({"text": f"{verb} the line {way} {called(net['hub'])}", "where": None})
        told |= parted
    # Lines: a line between two parts made or taken away (not those that went with a part,
    # nor one joined up round a part taken out of it).
    for pair, edge in new["edges"].items():
        rejoined = any(
            (pair[0], key) in old["edges"] and (key, pair[1]) in old["edges"] for key in gone
        )
        if pair not in old["edges"] and not set(pair) & set(added) and not rejoined:
            if pair in told:
                continue
            notes.append(
                {"text": f"connected {called(pair[0])} to {called(pair[1])}", "where": None}
            )
        elif pair in old["edges"] and old["edges"][pair] != edge:
            notes.append(
                {
                    "text": f"changed the line from {called(pair[0])} to {called(pair[1])}",
                    "where": None,
                }
            )
    for pair in old["edges"]:
        # (A line a new part was put into runs on through it: nothing was taken away.)
        through = any(
            (pair[0], key) in new["edges"] and (key, pair[1]) in new["edges"] for key in added
        )
        if pair not in new["edges"] and not set(pair) & set(gone) and not through:
            if any(pair == each for each, _ in spliced) or pair in told:
                continue
            notes.append(
                {
                    "text": f"removed the line from {called(pair[0])} to {called(pair[1])}",
                    "where": None,
                }
            )
    if spliced:
        pass  # (its place among the parts is the line's: said already)
    elif not added and not gone and _order(old) != _order(new):
        moved = [
            key
            for key in new["nodes"]
            if [item for item in _order(old) if item != key]
            == [item for item in _order(new) if item != key]
        ]
        if len(moved) == 1:
            notes.append({"text": f"moved {called(moved[0])}", "where": {"id": moved[0]}})
        else:
            notes.append({"text": "rearranged the figure", "where": None})
    elif old["groups"] != new["groups"] and not added and not gone:
        notes.append({"text": "rearranged the figure", "where": None})
    if old["rest"] != new["rest"]:
        notes.append({"text": "changed the figure's settings", "where": None})
    return notes[:4] if notes else None


def _order(figure: dict[str, Any]) -> list[str]:
    """The parts as the figure lays them out, in turn: through its groups from the root (or,
    with none written, as the file lists them)."""

    groups, nodes = figure["groups"], figure["nodes"]
    root = str((figure["rest"].get("figure") or {}).get("root") or "root")
    held = {str(child) for group in groups.values() for child in group.get("children") or []}
    top = (
        [str(child) for child in groups[root].get("children") or []]
        if root in groups
        else [key for key in [*groups, *nodes] if key not in held]
    )
    found: list[str] = []

    def walk(items: list[str], seen: set[str]) -> None:
        for item in items:
            if item in nodes:
                found.append(item)
            elif item in groups and item not in seen:
                walk([str(child) for child in groups[item].get("children") or []], seen | {item})

    walk(top, {root})
    return found
