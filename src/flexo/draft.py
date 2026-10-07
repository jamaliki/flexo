"""Drawing a figure as a draft: fast enough to draw again while it is changed.

An editor draws a figure again and again as its person drags parts about, renames
them and adds to them -- a slide's figure many times a second, the studio waiting on
each before it can draw the next. The best drawing of a large figure takes far longer
than that: its lines are routed several times over, each repair (pins swapped, ends
turned, a lane of room tried) a routing of the whole figure again.

While ``DRAFT`` is set, a figure is drawn as a draft instead (``drafting``):

- each line is drawn as it was the last time the figure was drawn, moved with its
  ends, wherever nothing beside it has changed; only the lines that did are routed
  again, once each, near where they ran and in some haste, not in view of the rest
  (``flexo.routing.router``);
- the repairs the last full drawing chose (pin orders, the sides of ends) are kept,
  and none is tried anew; nor is a lane of room to take a crossing out
  (``flexo.compiler``);
- the room the last drawing gave its lines, and whether it slid its groups, are kept
  too, and no more asked for, so the draft is laid out as that drawing was.

Once the changes stop the figure is drawn in full, as ever: a draft is never what a
figure is exported as. A full drawing of a large figure takes a while, and the changes may
start again meanwhile: one drawn ``given_up_when`` a newer drawing is wanted stops, its
searches raising ``GivenUp``, rather than keep the newer -- a draft -- waiting.
"""

from __future__ import annotations

import contextvars
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

DRAFT = contextvars.ContextVar("flexo_draft", default=False)
"""Whether figures are drawn as drafts (see the module)."""

MEMORY = 48
"""How many figures' last drawings are remembered, for their drafts to start from."""

_NEWER: contextvars.ContextVar[Callable[[], bool] | None] = contextvars.ContextVar(
    "flexo_newer", default=None
)

_REMEMBERED: OrderedDict[tuple[str, str, Any], Any] = OrderedDict()
_LOCK = threading.Lock()


@contextmanager
def drafting(on: bool = True) -> Iterator[None]:
    """Figures drawn within are drafts (``on``), or drawn in full."""

    token = DRAFT.set(on)
    try:
        yield
    finally:
        DRAFT.reset(token)


def recall(kind: str, key: Any) -> Any:
    """What was last remembered of a figure (``key``) for ``kind`` of work, or None."""

    with _LOCK:
        found = _REMEMBERED.get((kind, key))
        if found is not None:
            _REMEMBERED.move_to_end((kind, key))
        return found


def remember(kind: str, key: Any, value: Any) -> None:
    """Keep ``value`` of a figure (``key``) for ``kind`` of work, for its next draft."""

    with _LOCK:
        _REMEMBERED[(kind, key)] = value
        _REMEMBERED.move_to_end((kind, key))
        while len(_REMEMBERED) > MEMORY * 3:
            _REMEMBERED.popitem(last=False)


class GivenUp(BaseException):
    """A drawing given up for a newer one (``given_up_when``). Not an ``Exception``: it is
    no fault of the figure's, and nothing that says a figure's faults takes it for one."""


@contextmanager
def given_up_when(newer: Callable[[], bool]) -> Iterator[None]:
    """Figures drawn within stop with ``GivenUp`` once ``newer()`` says a newer drawing is
    wanted (asked every so often as their lines are routed)."""

    token = _NEWER.set(newer)
    try:
        yield
    finally:
        _NEWER.reset(token)


def newer_wanted() -> Callable[[], bool] | None:
    """What says a newer drawing is wanted, while a drawing may be given up for one."""

    return _NEWER.get()


def give_up_if_newer() -> None:
    """Stop the drawing (``GivenUp``) if a newer one is wanted."""

    newer = _NEWER.get()
    if newer is not None and newer():
        raise GivenUp
