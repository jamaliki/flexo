"""Themes as the studio offers them: every built-in theme and every theme file in the
folder, each with what a card of it shows, and one theme file put to use in many
documents at once."""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

from flexo.studio.workspace import Workspace

THEME_FILES = (".yaml", ".yml", ".json")
TONES_SHOWN = 6


def cards(workspace: Workspace, name: str) -> list[dict[str, Any]]:
    """The themes the document ``name`` may use: the folder's theme files, then
    flexo's own. A file's ``value`` is how the document names it, from its folder."""

    from flexo.theme_files import register_theme
    from flexo.themes import BUILT_IN

    here = workspace.path(name).parent
    found = []
    for entry in _theme_files(workspace):
        path = workspace.path(entry)
        card: dict[str, Any] = {"value": _reference(path, here), "file": entry, "source": "folder"}
        try:
            card.update(_card(register_theme(path)))
        except Exception as error:  # a theme file half-written, or wrong: offered, with why
            card.update({"title": path.name.split(".")[0], "problem": str(error)})
        found.append(card)
    found += [{"value": theme, "source": "built-in", **_built_in(theme)} for theme in BUILT_IN]
    return found


def uses(workspace: Workspace, name: str) -> list[dict[str, Any]]:
    """Every document in the folder that takes a theme, and whether it uses the theme
    file ``name``."""

    target = workspace.path(name).resolve()
    found = []
    for entry in workspace.documents():
        kind = workspace.kinds[entry["kind"]]
        theme_of = getattr(kind, "theme_of", None)
        if theme_of is None:
            continue
        path = workspace.path(entry["file"])
        open_doc = workspace.docs.get(entry["file"])
        try:
            document = open_doc.document if open_doc is not None else kind.load(path)
            current = theme_of(document)
        except Exception:  # a document that does not read: listed, using nothing
            current = None
        found.append(
            {
                "file": entry["file"],
                "kind": entry["kind"],
                "title": entry["title"],
                "theme": current or "",
                "uses": _names(current, path.parent, target),
            }
        )
    return found


def use(
    workspace: Workspace, name: str, targets: list[str], who: dict[str, Any]
) -> list[dict[str, Any]]:
    """Draw each of ``targets`` in the theme file ``name``, as an edit ``who`` made:
    every page open on them sees it, and each is saved."""

    theme = workspace.path(name)
    if theme.suffix.lower() not in THEME_FILES or not theme.is_file():
        raise FileNotFoundError(f"no theme file {name}")
    for target in targets:
        doc = workspace.open(target)
        with_theme = getattr(doc.kind, "with_theme", None)
        if with_theme is None:
            raise ValueError(f"a {doc.kind.title.lower()} is not drawn in a theme")
        with doc.lock:
            changed = with_theme(doc.document, _reference(theme, doc.path.parent), doc.path.parent)
            doc.update(changed, doc.version, who, str(who.get("id", "")))
        if doc.write():
            workspace.broadcast({"type": "saved", "file": doc.name, "version": doc.saved})
    return uses(workspace, name)


def _theme_files(workspace: Workspace) -> list[str]:
    return [entry["file"] for entry in workspace.documents() if entry["kind"] == "theme"]


def _reference(path: Path, folder: Path) -> str:
    return Path(os.path.relpath(path, folder)).as_posix()


def _names(current: str | None, folder: Path, target: Path) -> bool:
    if not current or not current.lower().endswith(THEME_FILES):
        return False
    return (folder / current).resolve() == target


@functools.cache
def _built_in(name: str) -> dict[str, Any]:
    return _card(name)


def _card(name: str) -> dict[str, Any]:
    from flexo.themes import resolve_palette, theme

    found = theme(name)
    palette = resolve_palette(name)
    return {
        "title": found.name,
        "description": found.description,
        "font": found.style.typography.family,
        "canvas": found.page.canvas,
        "ink": found.page.ink,
        "tones": [
            {"fill": palette.get(f"tone-{i}-fill"), "stroke": palette.get(f"tone-{i}-stroke")}
            for i in range(1, TONES_SHOWN + 1)
        ],
        "sketch": found.style.sketch is not None,
    }
