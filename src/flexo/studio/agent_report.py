"""What an edit's reply says besides "changed" (``edit_document``, ``write_document``): what the
change did to the document's structure -- slides or objects added, moved, deleted, as the
activity list says it -- a warning naming whatever it deleted, so a deletion nobody meant is
caught at once, and then what to do next and when to stop: the problems that block, the one
next thing to do, and what "done" is. An agent told this checks once and stops, rather than
looking again and again, or nudging what is laid out right.

A kind says what a change did with ``report(before, after)``: ``{"changes": [...],
"deleted": [...], "pages": [...], "noun": "slide"}``, the pages to look at numbered as after it
and what a page is called; a kind without it is described by its ``describe``.
"""

from __future__ import annotations

from typing import Any

NOTES = 8
"""Changes said at most; the rest counted."""


def found(kind: Any, before: Any, after: Any) -> dict[str, list]:
    """What a change did, as the kind says it."""

    hook = getattr(kind, "report", None)
    if hook is not None:
        said = hook(before, after)
        return {
            **{key: list(said.get(key) or []) for key in ("changes", "deleted", "pages")},
            "noun": str(said.get("noun") or "page"),
        }
    describe = getattr(kind, "describe", None)
    notes = describe(before, after) if describe is not None else []
    pages = sorted(
        {
            note["where"]["page"]
            for note in notes
            if isinstance(note.get("where"), dict) and isinstance(note["where"].get("page"), int)
        }
    )
    return {
        "changes": [note["text"] for note in notes],
        "deleted": [note["text"][8:] for note in notes if note["text"].startswith("deleted ")],
        "pages": pages,
        "noun": "page",
    }


def lines(kind: Any, before: Any, after: Any, problems: list[str]) -> list[str]:
    """The lines an edit's reply ends with: what changed, what it deleted, and what next."""

    try:
        said = found(kind, before, after)
    except Exception:  # (a document half written: said by its problems, if anything)
        said = {"changes": [], "deleted": [], "pages": [], "noun": "page"}
    out = []
    changes = said["changes"]
    if changes:
        more = f"; and {len(changes) - NOTES} more" if len(changes) > NOTES else ""
        out.append("What changed: " + "; ".join(changes[:NOTES]) + more + ".")
    if said["deleted"]:
        out.append(
            "Warning -- this deleted: " + "; ".join(said["deleted"]) + ". If that is not what you "
            "meant, put it back now, before anything else."
        )
    out.extend(policy(said["pages"], said["noun"], problems))
    return out


def policy(pages: list[int], noun: str, problems: list[str]) -> list[str]:
    """What to do next and when to stop: the problems first (they block), else one look at
    the ``pages`` changed (each a ``noun``); done when that look warns of nothing and it reads
    as meant."""

    if problems:
        return [
            "Blocking: the problems above. Next: fix them, then look at what you changed. "
            "Nothing else until they are gone."
        ]
    if pages:
        shown = ", ".join(str(page) for page in pages[:4])
        nouns = noun + ("s" if len(pages[:4]) > 1 else "")
        next_ = f"Next: look at {nouns} {shown} once (look, pages: [{shown}])."
    else:
        next_ = "Next: look at what you changed, once."
    return [
        next_ + " Done when that look shows no warnings and it reads as you mean: then stop. "
        "Where valid YAML lays out badly, report it as a Flexo bug; don't nudge places or sizes."
    ]
