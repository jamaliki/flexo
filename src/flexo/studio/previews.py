"""A figure drawn in a design before it is chosen, for the figure editor's Design bar: its
theme gallery (the figure in each theme) and its live preview (the figure in the theme,
palette or font the pointer is over).

The page asks with ``{"do": "previews", "variants": [{"figure.style": "dark"}, ...]}``: each
variant is the figure's own settings as its inspector sets them (``None`` takes one away),
and the answer has one drawing for each, in order -- ``{"svg", "key"}``, or ``{"error"}``
where that design can't be drawn. Nothing is changed: the figure's file is drawn as it would
be, and kept a while by what it was drawn from, so a gallery shown again is drawn once.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

DESIGN = frozenset(
    {
        "figure.style",
        "figure.palette",
        "figure.font",
        "figure.width",
        "figure.height",
        "figure.panel_labels",
        "figure.spacing",
        "figure.shape_padding",
        "figure.line_width",
        "figure.head_size",
    }
)
"""What a variant may change: the figure's settings that are its design."""

MOST = 24
"""Variants drawn for one question: a gallery asks for those in sight, a few at a time."""

KEPT = 80
"""Drawings kept, the oldest let go first."""

_kept: OrderedDict[str, dict[str, Any]] = OrderedDict()
_lock = threading.Lock()


def previews(
    kind: Any, document: dict[str, Any], action: dict[str, Any], base: Path
) -> dict[str, Any]:
    """The figure ``document`` (a figure kind's: its file's words) drawn by ``kind`` in each of
    ``action["variants"]``."""

    variants = action.get("variants") or []
    return {"previews": [_drawn(kind, document, base, variant) for variant in variants[:MOST]]}


def _drawn(kind: Any, document: dict[str, Any], base: Path, variant: object) -> dict[str, Any]:
    from flexo.studio import code_allowed

    values = (
        {key: value for key, value in variant.items() if key in DESIGN}
        if isinstance(variant, dict)
        else {}
    )
    text = str(document.get("text") or "")
    said = json.dumps(
        [text, values, str(base), document.get("suffix", ".yaml"), code_allowed.get()],
        sort_keys=True,
        default=str,
    )
    key = hashlib.sha256(said.encode("utf-8")).hexdigest()
    with _lock:
        found = _kept.get(key)
        # (Kept while the files it draws are as they were: a picture changed draws it again.)
        if found is not None and all(_stamp(file) == at for file, at in found["files"]):
            _kept.move_to_end(key)
            return found["answer"]
    answer, files = _draw(kind, document, base, values)
    with _lock:
        _kept[key] = {"answer": answer, "files": [(file, _stamp(file)) for file in files]}
        while len(_kept) > KEPT:
            _kept.popitem(last=False)
    return answer


def _draw(
    kind: Any, document: dict[str, Any], base: Path, values: dict[str, Any]
) -> tuple[dict[str, Any], list[Path]]:
    from flexo.studio.figure_edit import apply
    from flexo.studio.plain import explain

    try:
        if values:
            action = {"do": "update", "target": {"type": "figure"}, "values": values}
            suffix = document.get("suffix", ".yaml")
            text = apply(document["text"], action, suffix=suffix, base=base)["text"]
            document = {**document, "text": text}
        drawing = kind.draw(document, base)
    except Exception as error:
        return {"error": explain(error)}, []
    files = [Path(file) for file in drawing.files]
    if not drawing.pages or not drawing.pages[0].svg:
        wrong = next((item.text for item in drawing.messages if item.severity == "error"), "")
        return {"error": wrong or "The figure can\u2019t be drawn so."}, files
    svg = drawing.pages[0].svg
    return {"svg": svg, "key": hashlib.sha256(svg.encode("utf-8")).hexdigest()[:16]}, files


def _stamp(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
