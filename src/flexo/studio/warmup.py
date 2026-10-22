"""The figure a studio is started on, drawn while its page loads.

The page asks for its first drawing only once it has loaded (about a second, in a browser or
the app's window), and a figure with a structure in it -- a ribosome, read and drawn by
mol-sketch -- takes seconds more to draw the first time. Drawn on a thread of its own as the
studio starts, its molecules are ready, or nearly, when the page asks: the page's drawing waits
its turn and finds them drawn. (Only a figure with a structure: anything else draws in the
blink the page would wait for it anyway.) A deck's first slide is drawn so too, with what its
page asks of its kind first (its catalogue): the drawing of a deck's slides waits on a second of
fonts read and code loaded the first time.

And the assistant's word on who can answer is asked for as the page loads (its first call):
knowing it imports the providers' SDKs, a second of Python and two thousand modules. The page
is answered with what was last found on this computer (flexo.studio.availability) while
nothing that decides it has changed, and the studio finds it out again on a thread of its own
once the first page is drawn and the pages have stopped asking for drawings a moment: the
modules read then are not read while a slide waits for them. (Never found here before, or
since changed, it is found out at once: the page waits for it.)
"""

from __future__ import annotations

import threading
import time

QUIET = 1.5
"""How long no page has asked for a drawing before the assistant's SDKs are read (seconds)."""
PATIENCE = 30.0
"""And the longest they wait for that (seconds)."""


def warm(workspace, name: str) -> threading.Thread | None:
    """Draw the document ``name`` of ``workspace`` once, on a thread of its own, if it is a
    figure with a structure in it; or, of another kind (a deck), its first page. The thread
    drawing it, if one is."""

    if not name:
        return None
    try:
        text = workspace.path(name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    try:
        figure = workspace.kind_of(workspace.path(name)).name == "figure"
    except Exception:
        return None
    if figure and "structure" not in text:
        return None

    def draw() -> None:
        try:
            doc = workspace.open(name)
            if doc.kind.name == "figure":
                workspace.drawing_of(name)
                return
            catalog = getattr(doc.kind, "catalog", None)
            if catalog is not None:
                catalog()
            workspace.draw(name, doc.document, 0, {}, {"focus": 0, "client": "warm-up"})
        except Exception:  # (the page's own drawing says what went wrong)
            pass

    drawing = threading.Thread(target=draw, name="studio warm-up", daemon=True)
    drawing.start()
    return drawing


def warm_assistant(workspace, after: threading.Thread | None = None) -> None:
    """Have ``workspace``'s assistant find out who can answer, on a thread of its own: at once
    if it was never found out here, else once the drawing ``after`` is done and the pages
    are quiet."""

    def ask() -> None:
        try:
            from flexo.studio import availability
            from flexo.studio.server import _assistant

            # (The answer a page may have been given meanwhile, as last found here: told again
            # should it be another now.)
            known = availability.remembered()
            if known is not None:
                _quiet(workspace, after)
            if workspace.assistant is not None:
                return  # (a page found out first)
            found = _assistant(workspace).availability()
            availability.remember(found)
            if known is not None and known != {key: found.get(key) for key in known}:
                workspace.broadcast({"type": "assistant", "event": "availability", **found})
        except Exception:  # (the page's own asking says what went wrong)
            pass

    threading.Thread(target=ask, name="studio assistant warm-up", daemon=True).start()


def _quiet(workspace, after: threading.Thread | None) -> None:
    """Wait for the drawing ``after`` and then for the pages to stop asking for drawings
    (``QUIET``), for ``PATIENCE`` at most."""

    until = time.monotonic() + PATIENCE
    if after is not None:
        after.join(PATIENCE)
    while not getattr(workspace, "_stop", threading.Event()).is_set():
        now = time.monotonic()
        waited = now - getattr(workspace, "drawn_at", 0.0)
        if waited >= QUIET or now >= until:
            return
        time.sleep(min(QUIET - waited, until - now) + 0.01)
