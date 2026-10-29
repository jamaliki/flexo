"""How near two versions of a document are, and which of several a changed one was made from.

Something that writes a document's file whole -- an agent writing back what it read with its
change, a script, an editor holding the file open, another computer -- may have read it a while
ago. Its change is then a change from what it read, not from what the file held just before:
merged from that, the edits saved since it read the file are kept, and its own change is taken
in. What it read is not said, so it is the version the studio had that its words are nearest
(``nearest``): the one it differs from the least -- for a change made from the latest, the
latest itself.

How far apart two versions are (``apart``) is told by their words, in pieces: each value and
each item, as ``json.dumps`` writes them, and each line of words. Each piece is counted, and
each together with the piece after it, so a slide moved is apart from where it was; the pieces
and pairs one version has and the other has not are how far apart they are. Only what lies
between where two versions begin to differ and where they last differ is read -- and the
versions a studio kept, each its last saving edited a little, are compared each with the one
before it, the difference from the changed one carried along: the forty versions of a 70 kB
deck in a few milliseconds.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from itertools import pairwise

_SEPARATORS = (", ", "\\n", "\n")
"""What separates the pieces of a document's words: values and items as ``json.dumps`` writes them
(and a YAML flow list), the lines of words in a value (``\\n`` there), and lines."""
_NEARBY = 2048
"""Characters a separator is looked for in, around what differs, before looking further."""


def apart(one: str, other: str) -> int:
    """How far apart two versions of a document are, in their words (as ``json.dumps`` writes
    them, or as their file has them): of their pieces (see the module), and each with the
    piece after it, how many one has and the other has not."""

    return sum(map(abs, _difference(one, other).values()))


def nearest(texts: Iterable[str], aim: str) -> str | None:
    """Of ``texts``, the one nearest ``aim`` (``apart``): the first of those as near. Each is
    compared with the one before it -- quickly, where each is the one before it edited a little
    (the versions a studio kept, newest or oldest first) -- and ``aim`` with the first."""

    best: str | None = None
    least = far = 0
    difference: dict[str | tuple[str, str], int] = {}
    last: str | None = None
    for text in texts:
        # (``aim`` less this one: ``aim`` less the one before, and the one before less this.)
        for piece, count in _difference(last if last is not None else aim, text).items():
            was = difference.get(piece, 0)
            difference[piece] = was + count
            far += abs(was + count) - abs(was)
        if best is None or far < least:
            best, least = text, far
            if not far:
                break
        last = text
    return best


def _difference(one: str, other: str) -> Counter:
    """The pieces of ``one`` (see the module), and each with the next, less those of
    ``other``: a count for each, negative for those ``other`` has more of."""

    if one == other:
        return Counter()
    start, end = _alike(one, other)
    # Out to the pieces around what differs, and one more each side: a piece is counted with
    # its neighbour, as it is in the rest, which both share.
    for _ in range(2):
        start = _before(one, start)
    until = len(one) - end
    for step in range(2):
        until = _after(one, until + step)
    end = len(one) - until
    difference = _pieces(one[start:until])
    difference.subtract(_pieces(other[start : len(other) - end]))
    return difference


def _alike(one: str, other: str) -> tuple[int, int]:
    """How long a start, and then an end, two texts share (the two never overlapping)."""

    most = min(len(one), len(other))
    low, high = 0, most
    while low < high:
        middle = (low + high + 1) // 2
        if one[low:middle] == other[low:middle]:
            low = middle
        else:
            high = middle - 1
    start = low
    low, high = 0, most - start
    while low < high:
        middle = (low + high + 1) // 2
        if one[len(one) - middle : len(one) - low] == other[len(other) - middle : len(other) - low]:
            low = middle
        else:
            high = middle - 1
    return start, low


def _before(text: str, at: int) -> int:
    """Where the separator before ``at`` is (0 if none is), looked for nearby first."""

    for since in (max(at - _NEARBY, 0), 0):
        found = max(text.rfind(separator, since, at) for separator in _SEPARATORS)
        if found >= 0 or not since:
            return max(found, 0)
    return 0


def _after(text: str, at: int) -> int:
    """Where the separator from ``at`` on is (the end if none is), looked for nearby first."""

    for until in (min(at + _NEARBY, len(text)), len(text)):
        found = [
            where for separator in _SEPARATORS if (where := text.find(separator, at, until)) >= 0
        ]
        if found or until == len(text):
            return min(found, default=len(text))
    return len(text)


def _pieces(text: str) -> Counter:
    """The pieces of words (see the module), and each with the next, counted."""

    pieces = text.replace("\\n", "\n").replace(", ", "\n").split("\n")
    counted: Counter = Counter(pieces)
    counted.update(pairwise(pieces))
    return counted
