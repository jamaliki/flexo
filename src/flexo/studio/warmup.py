"""The figure a studio is started on, drawn while its page loads.

The page asks for its first drawing only once it has loaded (about a second, in a browser or
the app's window), and a figure with a structure in it -- a ribosome, read and drawn by
mol-sketch -- takes seconds more to draw the first time. Drawn on a thread of its own as the
studio starts, its molecules are ready, or nearly, when the page asks: the page's drawing waits
its turn and finds them drawn. (Only a figure with a structure: anything else draws in the
blink the page would wait for it anyway.)
"""

from __future__ import annotations

import threading


def warm(workspace, name: str) -> None:
    """Draw the document ``name`` of ``workspace`` once, on a thread of its own, if it is a
    figure with a structure in it."""

    if not name:
        return
    try:
        text = workspace.path(name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return
    if "structure" not in text:
        return

    def draw() -> None:
        try:
            if workspace.open(name).kind.name == "figure":
                workspace.drawing_of(name)
        except Exception:  # (the page's own drawing says what went wrong)
            pass

    threading.Thread(target=draw, name="studio warm-up", daemon=True).start()
