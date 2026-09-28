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

    def catalog(self) -> dict[str, Any]:
        from flexo.colour import design_palettes
        from flexo.components import COMPONENTS
        from flexo.fonts import available_families
        from flexo.themes import theme_names

        return {
            "themes": list(theme_names()),
            "palettes": {name: list(colours) for name, colours in design_palettes().items()},
            "fonts": list(available_families()),
            "components": sorted(COMPONENTS),
        }

    def draw(
        self, document: dict[str, Any], base: Path, hints: dict[str, Any] | None = None
    ) -> Drawing:
        from flexo.compiler import compile_figure
        from flexo.diagnostics import FlexoError
        from flexo.lint import lint_compilation

        try:
            spec = parse(document["text"], base, suffix=document.get("suffix", ".yaml"))
        except (yaml.YAMLError, json.JSONDecodeError) as error:
            return Drawing([], [Message(_yaml_problem(error), "error", _yaml_line(error))])
        except FlexoError as error:
            return Drawing([], [_message(item) for item in error.diagnostics])
        except (ValueError, TypeError, KeyError) as error:
            return Drawing([], [Message(str(error), "error")])
        try:
            compilation = compile_figure(spec)
        except FlexoError as error:
            return Drawing([], [_message(item) for item in error.diagnostics])
        report = lint_compilation(compilation)
        page = Page(
            spec.id, compilation.document.text, label=spec.id, extra={"outline": outline(spec)}
        )
        files = [base / value for value in (spec.style, spec.palette) if _is_file(value)]
        return Drawing([page], [_message(item) for item in report.diagnostics], files)

    def export(
        self, document: dict[str, Any], base: Path, stem: str, formats: list[str]
    ) -> list[Path]:
        from flexo.export import build

        spec = parse(document["text"], base)
        result = build(spec, base / "build", stem=stem, formats=tuple(formats))
        return list(result.outputs.existing())


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
    """A figure from its file's words, theme and palette files found from ``base``."""

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
