"""Themes in the studio: a theme file edited through its settings, shown on samples.

The document is the theme file itself (``theme: {name, base, ...}``): only what
differs from its base is written, and the page shows every other setting as
the base has it. The samples are figures drawn in the theme, and whatever
other packages add through the ``flexo.studio.specimens`` entry-point group
(flexo-talk adds slides, and any deck in the folder).
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import fields
from pathlib import Path
from typing import Any

import yaml

from flexo.roundtrip import rewrite
from flexo.studio import Drawing, Message, Page

BUDGET = 0.5
SAMPLE = {
    "figure": {"id": "sample", "width": "single-column"},
    "nodes": [
        {"id": "request", "kind": "text", "label": "Request $r$"},
        {"id": "api", "label": "API", "properties": {"tone": "1"}},
        {"id": "queue", "kind": "queue", "label": "Queue", "properties": {"tone": "2"}},
        {"id": "worker", "label": "Worker", "properties": {"tone": "3"}},
        {"id": "store", "kind": "database", "label": "Store", "properties": {"tone": "4"}},
    ],
    "edges": [
        {"from": "request", "to": "api"},
        {"from": "api", "to": "queue"},
        {"from": "queue", "to": "worker"},
        {"from": "worker", "to": "store"},
    ],
}
"""A theme's first sample: a pipeline, its steps in the theme's first tones."""

SYSTEM = {
    "figure": {"id": "system", "width": "double-column"},
    "nodes": [
        {"id": "person", "kind": "person", "label": "Customer"},
        {"id": "web", "label": "Web app", "properties": {"tone": "1"}},
        {"id": "phone", "label": "Phone app", "properties": {"tone": "1"}},
        {"id": "api", "kind": "server", "label": "API", "properties": {"tone": "2"}},
        {"id": "queue", "kind": "queue", "label": "Orders", "properties": {"tone": "3"}},
        {"id": "worker", "label": "Worker", "properties": {"tone": "3"}},
        {"id": "db", "kind": "database", "label": "Database", "properties": {"tone": "4"}},
    ],
    "groups": [
        {
            "id": "root",
            "role": "canvas",
            "layout": {"kind": "row"},
            "children": ["person", "apps", "backend"],
        },
        {"id": "apps", "label": "Apps", "layout": {"kind": "column"}, "children": ["web", "phone"]},
        {
            "id": "backend",
            "label": "Backend",
            "layout": {"kind": "row"},
            "children": ["api", "queue", "worker", "db"],
        },
    ],
    "edges": [
        {"from": "person", "to": "web"},
        {"from": "person", "to": "phone"},
        {"from": "web", "to": "api", "label": "HTTPS"},
        {"from": "phone", "to": "api"},
        {"from": "api", "to": "queue"},
        {"from": "queue", "to": "worker"},
        {"from": "worker", "to": "db"},
    ],
}
"""Its second: a system, with groups, labelled lines and the software shapes."""


class ThemeKind:
    name = "theme"
    title = "Theme"
    static = Path(__file__).parent / "static" / "theme"

    def __init__(self) -> None:
        self._pages: OrderedDict[str, str] = OrderedDict()

    def claims(self, document: object) -> bool:
        return isinstance(document, dict) and isinstance(document.get("theme"), dict)

    def new(self, path: Path) -> dict[str, Any]:
        return {
            "theme": {
                "name": path.stem.removesuffix(".theme"),
                "base": "paper",
                "description": "Our own look.",
            }
        }

    def load(self, path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError(f"{path.name} is not a theme file")
        return data

    def save(self, path: Path, document: dict[str, Any], previous: str | None = None) -> None:
        if path.suffix.lower() == ".json":
            path.write_text(
                json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        else:
            # Over the file's words as they were (``previous``): its comments and quoting kept.
            text = rewrite(previous, document, self.dump, name=str(path.resolve()))
            path.write_text(text, encoding="utf-8")

    def dump(self, document: Any) -> str:
        return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100)

    def parse(self, text: str) -> Any:
        return yaml.safe_load(text)

    def guide(self) -> str:
        from flexo import theme_files

        return (
            "A flexo theme file.\n\n"
            + (theme_files.__doc__ or "")
            + (
                "\nWrite only what differs from `base`; "
                "`flexo theme <name>` shows every setting a theme has."
            )
        )

    def catalog(self) -> dict[str, Any]:
        from flexo.colour import design_palettes
        from flexo.conventions import CHOICES
        from flexo.fonts import available_families
        from flexo.style import LayoutStyle, TypographyStyle
        from flexo.themes import TONE_RULES, theme_names

        choices: dict[str, list[str]] = {}
        for owner in (LayoutStyle, TypographyStyle):
            for item in fields(owner):
                text = str(item.type)
                if text.startswith("Literal["):
                    choices[item.name] = [part.strip(" '\"") for part in text[8:-1].split(",")]
        return {
            "bases": list(theme_names()),
            "fonts": sorted(available_families()),
            "palettes": {name: list(colours) for name, colours in design_palettes().items()},
            "choices": choices,
            "conventions": {key: list(values) for key, values in CHOICES.items()},
            "tones": list(TONE_RULES),
            "specimens": [
                {"name": "figures", "title": "Figures"},
                *(
                    {"name": name, "title": provider.title}
                    for name, provider in _specimens().items()
                ),
            ],
        }

    def describe(self, before: Any, after: Any) -> list[dict[str, Any]]:
        old = (before or {}).get("theme") or {}
        new = (after or {}).get("theme") or {}
        names = {
            "palette": "the palette",
            "page": "the page colours",
            "type": "the type",
            "font": "the font",
            "style": "the lines and spacing",
            "tones": "the tones",
            "conventions": "the conventions",
            "sketch": "the hand-drawn look",
            "base": "the base theme",
            "name": "the name",
        }
        changed = [key for key in dict.fromkeys([*old, *new]) if old.get(key) != new.get(key)]
        return [
            {"text": f"changed {names.get(key, key)}", "where": {"label": key}}
            for key in changed[:4]
        ]

    def check(self, document: Any, base: Path) -> list[str]:
        try:
            _register(document, base)
        except Exception as error:
            return [str(error)]
        return []

    def draw(
        self, document: dict[str, Any], base: Path, hints: dict[str, Any] | None = None
    ) -> Drawing:
        from flexo.diagnostics import FlexoError

        hints = hints or {}
        try:
            name = _register(document, base)
        except FlexoError as error:
            return Drawing(
                [],
                [
                    Message(
                        item.message + (f" ({item.hint})" if item.hint else ""),
                        "error",
                        item.entity_id or "",
                        code=item.code,
                    )
                    for item in error.diagnostics
                ],
            )
        except Exception as error:
            from flexo.studio.plain import explain

            return Drawing([], [Message(explain(error), "error")])
        specimen = str(hints.get("specimen") or "figures")
        stamp = hashlib.sha256(
            json.dumps(
                [document, specimen, hints.get("deck")], sort_keys=True, default=str
            ).encode()
        ).hexdigest()
        info = {"effective": _effective(name), "tones": _tones(name)}
        messages: list[Message] = []
        if specimen == "figures":
            makers = [
                ("sample", "A pipeline", lambda: _sample(name, SAMPLE)),
                ("system", "A system", lambda: _sample(name, SYSTEM)),
            ]
        else:
            provider = _specimens().get(specimen)
            if provider is None:
                return Drawing([], [Message(f"No samples called {specimen}.", "error")], info=info)
            try:
                makers = provider.pages(name, base, hints)
            except Exception as error:
                # One that says it plainly (a deck that does not read) is said as it says it.
                said = str(error) if getattr(error, "plain", False) else (
                    f"The {provider.title.lower()} could not be drawn: {_explain(error)}"
                )
                return Drawing([], [Message(said, "error")], info=info)
        pages: list[Page] = []
        started = time.perf_counter()
        drew = False
        for identifier, label, make in makers:
            key = f"{stamp}:{identifier}"
            svg = self._pages.get(key)
            if svg is None and drew and time.perf_counter() - started > BUDGET:
                pages.append(Page(identifier, "", label, pending=True))
                continue
            if svg is None:
                try:
                    svg = make()
                except Exception as error:
                    from flexo.studio.plain import explain

                    messages.append(Message(f"{label}: {explain(error)}", "error", page=identifier))
                    continue
                drew = True
                self._pages[key] = svg
                while len(self._pages) > 120:
                    self._pages.popitem(last=False)
            pages.append(Page(identifier, svg, label))
        files = [path for path in _theme_files(document, base)]
        return Drawing(pages, messages, files, info)

    def export(
        self,
        document: dict[str, Any],
        base: Path,
        stem: str,
        formats: list[str],
        *,
        into: Path | None = None,
    ) -> list[Path]:
        # Never the theme's own name: exported beside it, it would replace it. Named plainly,
        # as a person would: "Order queue full theme.yaml", not "Order queue.theme (full).yaml".
        name = stem.removesuffix(".theme") or "theme"
        target = (into or base / "build") / f"{name} full theme.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        from flexo.theme_files import dump_theme

        target.write_text(dump_theme(_register(document, base)), encoding="utf-8")
        return [target]


def _register(document: Any, base: Path) -> str:
    from flexo.theme_files import register_theme

    if not isinstance(document, dict) or not isinstance(document.get("theme"), dict):
        raise ValueError("a theme file is a mapping with theme: {name, base, ...}")
    data = copy.deepcopy(document)
    if not data["theme"].get("name"):
        raise ValueError("the theme needs a name")
    return register_theme(data, folder=base)


def _theme_files(document: dict[str, Any], base: Path) -> list[Path]:
    value = (document.get("theme") or {}).get("base")
    if isinstance(value, str) and value.lower().endswith((".yaml", ".yml", ".json")):
        path = (base / value).resolve()
        return [path] if path.is_file() else []
    return []


def _effective(name: str) -> dict[str, Any]:
    from flexo.theme_files import theme_document

    return json.loads(json.dumps(theme_document(name)["theme"], default=str))


def _tones(name: str) -> list[dict[str, str]]:
    from flexo.themes import resolve_palette

    palette = resolve_palette(name)
    tones = []
    for index in range(1, 9):
        try:
            tones.append(
                {
                    "fill": palette.get(f"tone-{index}-fill"),
                    "stroke": palette.get(f"tone-{index}-stroke"),
                }
            )
        except (KeyError, ValueError):
            break
    return tones


def _sample(name: str, sample: dict[str, Any]) -> str:
    from dataclasses import replace

    from flexo.compiler import compile_figure
    from flexo.serialization import parse_figure

    spec = replace(parse_figure(copy.deepcopy(sample)), style=name)
    return compile_figure(spec).document.text


def _specimens() -> dict[str, Any]:
    from importlib.metadata import entry_points

    found = {}
    for entry in entry_points(group="flexo.studio.specimens"):
        try:
            provider = entry.load()
        except Exception:
            continue
        found[entry.name] = provider() if isinstance(provider, type) else provider
    return found


def _explain(error: BaseException) -> str:
    from flexo.studio.plain import explain

    return explain(error)
