"""Figures in the studio: a figure file edited as its YAML, drawn as it changes.

The document the page edits is ``{"text": ...}``, the file's own words, so its
comments and order survive saving. The page shows the figure's parts (nodes,
groups, edges) beside the text, and selecting one marks it in the drawing.
"""

from __future__ import annotations

import json
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
edges: each {from: node or node.port, to: node or node.port, label, role, head: inhibition|
  catalysis|stimulation|necessary|modulation, arrow: reversible, back_label, cofactors: [ATP, ADP]}
groups: each {id, children: [ids], layout: {kind: row|column|grid, gap}, label}; the root group
  (figure.root, "root" by default) holds the rest. A file without groups stacks its nodes.
Labels are markup: $maths$, *emphasis*, **strong**. `flexo schema` prints the full schema.
"""


class FigureKind:
    name = "figure"
    title = "Figure"
    static = Path(__file__).parent / "static" / "figure"

    def claims(self, document: object) -> bool:
        return isinstance(document, dict) and ("nodes" in document or "figure" in document)

    def new(self, path: Path) -> dict[str, Any]:
        return {"text": NEW_FIGURE}

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
        import difflib

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

        result = apply(
            document["text"], action, suffix=document.get("suffix", ".yaml"), base=base
        )
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

        # The figure as written, for the page's inspector, whether or not it draws.
        info = {"model": model(document["text"], suffix=document.get("suffix", ".yaml"))}
        try:
            spec = parse(document["text"], base, suffix=document.get("suffix", ".yaml"))
        except (yaml.YAMLError, json.JSONDecodeError) as error:
            return Drawing([], [Message(_yaml_problem(error), "error", _yaml_line(error))],
                           info=info)
        except FlexoError as error:
            return Drawing([], [_message(item) for item in error.diagnostics], info=info)
        except (ValueError, TypeError, KeyError) as error:
            return Drawing([], [Message(str(error), "error")], info=info)
        try:
            compilation = compile_figure(spec)
        except FlexoError as error:
            return Drawing([], [_message(item) for item in error.diagnostics], info=info)
        report = lint_compilation(compilation)
        info["tones"] = _tones(spec)
        page = Page(
            spec.id, compilation.document.text, label=spec.id, extra={"outline": outline(spec)}
        )
        files = [base / value for value in (spec.style, spec.palette) if _is_file(value)]
        return Drawing([page], [_message(item) for item in report.diagnostics], files, info)

    def export(
        self, document: dict[str, Any], base: Path, stem: str, formats: list[str]
    ) -> list[Path]:
        from flexo.export import build

        spec = parse(document["text"], base)
        result = build(spec, base / "build", stem=stem, formats=tuple(formats))
        return list(result.outputs.existing())


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
    return {"colours": colours, "used": _tone_map(spec, figure_style(spec))}


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
        source = properties.get("source") if isinstance(properties, dict) else None
        if isinstance(source, str) and source and (base / source).is_file():
            properties["source"] = str((base / source).resolve())
    return parse_figure(document)


def _is_file(value: object) -> bool:
    return isinstance(value, str) and value.lower().endswith((".yaml", ".yml", ".json"))


def _message(diagnostic) -> Message:
    text = diagnostic.message + (f" ({diagnostic.hint})" if diagnostic.hint else "")
    severity = "note" if diagnostic.severity.value == "info" else diagnostic.severity.value
    return Message(text, severity, diagnostic.entity_id or "", code=diagnostic.code)


def _yaml_problem(error: Exception) -> str:
    problem = getattr(error, "problem", None)
    return f"the file does not read as YAML: {problem or error}"


def _yaml_line(error: Exception) -> str:
    mark = getattr(error, "problem_mark", None)
    return f"line {mark.line + 1}" if mark is not None else ""
