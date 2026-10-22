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
knowing it imports the providers' SDKs, seconds of Python on a Mac busy opening a deck. Asked
on a thread of its own as the studio starts, it is known by the time the page asks.
"""

from __future__ import annotations

import threading


def warm(workspace, name: str) -> None:
    """Draw the document ``name`` of ``workspace`` once, on a thread of its own, if it is a
    figure with a structure in it; or, of another kind (a deck), its first page."""

    if not name:
        return
    try:
        text = workspace.path(name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return
    try:
        figure = workspace.kind_of(workspace.path(name)).name == "figure"
    except Exception:
        return
    if figure and "structure" not in text:
        return

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

    threading.Thread(target=draw, name="studio warm-up", daemon=True).start()


def warm_assistant(workspace) -> None:
    """Have ``workspace``'s assistant find out who can answer, on a thread of its own."""

    def ask() -> None:
        try:
            from flexo.studio.server import _assistant

            _assistant(workspace).state()
        except Exception:  # (the page's own asking says what went wrong)
            pass

    threading.Thread(target=ask, name="studio assistant warm-up", daemon=True).start()
