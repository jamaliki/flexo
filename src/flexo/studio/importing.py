"""A drawing pasted or dropped into the studio, made the page's own shapes.

The page sends what it was given -- a drawing's SVG (Inkscape's, from the clipboard), or a
file it saved beside the document (an ``.svg``, a PDF's or an Illustrator file's page) --
and where it goes: on a slide, centred where it is pasted and made small enough to fit; over
a figure, at the paste point. It gets back the shapes ``flexo.svgimport`` made of it, placed,
for it to add in one step; the pictures that keep what no shape draws are written into the
document's ``assets`` folder, as a file dropped there is, and taken away again when the
studio closes if nothing came to use them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flexo import svgimport

MOST_BYTES = 40_000_000
"""The largest drawing read as shapes: more is a picture's, not shapes'."""


def imported(workspace: Any, name: str, data: dict[str, Any]) -> dict[str, Any]:
    """The shapes of the drawing ``data`` brings (``svg``, its words, or ``path``, a file
    beside the document ``name``), placed as it says (``centre``, ``at``, ``fit``), its
    colours the theme's ``roles`` (``exact``: as drawn), its words in ``markup``."""

    document = workspace.path(name)
    folder = document.parent
    svg = data.get("svg")
    stem = Path(str(data.get("name") or "drawing")).stem or "drawing"
    if not svg and data.get("path"):
        source = workspace.path(_beside(name, str(data["path"])))
        workspace.relative(source)  # inside the folder, or PermissionError
        stem = source.stem
        svg = _drawing_of(source)
    if not isinstance(svg, str) or not svg.strip():
        raise ValueError("There is no drawing to make shapes of.")
    if len(svg) > MOST_BYTES:
        return {"whole": True, "why": "The drawing is too large to be made shapes of."}
    written: list[str] = []

    def keep(content: bytes, suffix: str) -> str:
        target = _unique(folder / "assets", f"{_clean(stem)}-part", suffix, content)
        workspace.relative(target)
        if not target.exists():
            workspace.uploads.add(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        made = target.relative_to(folder).as_posix()
        written.append(made)
        return made

    try:
        made = svgimport.shapes_of(
            svg,
            roles=data.get("roles") or None,
            exact=bool(data.get("exact")),
            markup="figure" if data.get("markup") == "figure" else "slide",
            centre=_pair(data.get("centre")),
            at=_pair(data.get("at")),
            fit=_pair(data.get("fit")),
            picture=keep,
            name=stem,
            taken=[str(item) for item in data.get("taken") or [] if isinstance(item, str | int)],
        )
    except svgimport.SvgImportError as error:
        return {"whole": True, "why": str(error)}
    return {
        "shapes": made.shapes,
        "box": list(made.box),
        "scale": made.scale,
        "count": made.count,
        "elements": made.elements,
        "kept": made.kept,
        "approximated": made.approximated,
        "pictures": written,
        "whole": made.count > svgimport.SHAPES_AT_MOST,
    }


def _beside(name: str, path: str) -> str:
    """A file the page names from its document's folder, as the workspace names it."""

    parent = Path(name).parent
    return (parent / path).as_posix() if str(parent) not in ("", ".") else path


def _drawing_of(source: Path) -> str:
    """A file's drawing as SVG: an SVG's own words, a PDF's (an Illustrator file's) page."""

    suffix = source.suffix.lower()
    if suffix == ".svg":
        return source.read_text(encoding="utf-8", errors="replace")
    if suffix in (".pdf", ".ai"):
        from flexo.pdfart import read_page

        return read_page(str(source), 1, source.stat().st_mtime_ns).markup
    raise ValueError(f"{source.name} is not a drawing: only SVG, PDF and Illustrator files are.")


def _pair(value: object) -> list[float] | None:
    if (
        isinstance(value, list | tuple)
        and len(value) == 2
        and all(isinstance(item, int | float) and not isinstance(item, bool) for item in value)
    ):
        return [float(value[0]), float(value[1])]
    return None


def _clean(stem: str) -> str:
    return "".join(ch for ch in stem if ch.isalnum() or ch in "._- ").strip() or "drawing"


def _unique(folder: Path, stem: str, suffix: str, content: bytes) -> Path:
    """A file's place in ``folder``: the first of ``stem-1``, ``stem-2``… free, or holding
    these very bytes already."""

    count = 1
    while True:
        target = folder / f"{stem}-{count}{suffix}"
        if not target.exists() or target.read_bytes() == content:
            return target
        count += 1


__all__ = ["imported"]
