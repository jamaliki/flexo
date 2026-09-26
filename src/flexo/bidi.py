"""Right-to-left text among left-to-right: the order a line's characters are seen in.

Persian, Arabic, and Hebrew run right to left, and a line of them may hold
English words, numbers, and formulae that still run left to right. Unicode's
bidirectional algorithm (UAX #9) says where each character goes; this is that
algorithm for one paragraph without explicit embedding controls (rules P2-P3,
W1-W7, N1-N2, I1-I2, L1-L2), which is all a label or a slide line needs.

``levels`` gives each character its embedding level -- even runs left to right,
odd right to left -- and ``visual_order`` turns a line cut into pieces of one
level into the order they are laid out in, left to right on the page. A
renderer that shapes each piece in its own direction and sets the pieces in that
order draws the line as a browser or a word processor would.
"""

from __future__ import annotations

import unicodedata

_STRONG_RTL = frozenset({"R", "AL"})
_NEUTRAL = frozenset({"ON", "WS", "S", "B", "BN"})


def has_rtl(text: str) -> bool:
    """Whether ``text`` holds any right-to-left letter (or Arabic digits)."""

    return any(unicodedata.bidirectional(ch) in {"R", "AL", "AN"} for ch in text)


def base_level(text: str) -> int:
    """The paragraph's direction from its first strong letter: 0 left to right, 1 right to left."""

    for ch in text:
        kind = unicodedata.bidirectional(ch)
        if kind == "L":
            return 0
        if kind in _STRONG_RTL:
            return 1
    return 0


def levels(text: str, base: int | None = None) -> list[int]:
    """The embedding level of each character of ``text`` (one paragraph)."""

    if base is None:
        base = base_level(text)
    types = [unicodedata.bidirectional(ch) or "L" for ch in text]
    sos = "R" if base % 2 else "L"
    # W1: a combining mark takes the type of what it marks.
    for i, kind in enumerate(types):
        if kind == "NSM":
            types[i] = types[i - 1] if i else sos
    # W2: a European number after Arabic letters is an Arabic number.
    last = sos
    for i, kind in enumerate(types):
        if kind in {"L", "R", "AL"}:
            last = kind
        elif kind == "EN" and last == "AL":
            types[i] = "AN"
    # W3: Arabic letters are right to left.
    types = ["R" if kind == "AL" else kind for kind in types]
    # W4: one separator between two numbers of a kind joins them.
    for i in range(1, len(types) - 1):
        before, kind, after = types[i - 1], types[i], types[i + 1]
        if kind == "ES" and before == after == "EN":
            types[i] = "EN"
        elif kind == "CS" and before == after and before in {"EN", "AN"}:
            types[i] = before
    # W5: currency and percent signs beside a European number belong to it.
    for i, kind in enumerate(types):
        if kind == "EN":
            j = i - 1
            while j >= 0 and types[j] == "ET":
                types[j] = "EN"
                j -= 1
            j = i + 1
            while j < len(types) and types[j] == "ET":
                types[j] = "EN"
                j += 1
    # W6: any other separator is neutral.
    types = ["ON" if kind in {"ES", "ET", "CS"} else kind for kind in types]
    # W7: a European number after left-to-right letters is left to right.
    last = sos
    for i, kind in enumerate(types):
        if kind in {"L", "R"}:
            last = kind
        elif kind == "EN" and last == "L":
            types[i] = "L"
    # N0: a pair of brackets takes the direction of what it holds, so a formula's
    # closing parenthesis stays with the formula inside a right-to-left line.
    _bracket_pairs(text, types, base, sos)
    # N1-N2: neutrals between two of one direction take it; others, the paragraph's.
    i = 0
    while i < len(types):
        if types[i] not in _NEUTRAL:
            i += 1
            continue
        j = i
        while j < len(types) and types[j] in _NEUTRAL:
            j += 1
        before = _direction(types[i - 1]) if i else sos
        after = _direction(types[j]) if j < len(types) else sos
        fill = before if before == after else ("R" if base % 2 else "L")
        for k in range(i, j):
            types[k] = fill
        i = j
    # I1-I2: levels from the resolved types.
    result = []
    for kind in types:
        if base % 2 == 0:
            result.append(base + (1 if kind == "R" else 2 if kind in {"AN", "EN"} else 0))
        else:
            result.append(base + (1 if kind in {"L", "EN", "AN"} else 0))
    # L1: trailing white space takes the paragraph's level.
    for i in range(len(text) - 1, -1, -1):
        if not text[i].isspace():
            break
        result[i] = base
    return result


_STRONGISH = frozenset({"L", "R", "EN", "AN"})
_OPENING = {"(": ")", "[": "]", "{": "}", "⟨": "⟩", "«": "»"}


def _bracket_pairs(text: str, types: list[str], base: int, sos: str) -> None:
    embedding = "R" if base % 2 else "L"
    stack: list[tuple[str, int]] = []
    pairs: list[tuple[int, int]] = []
    for i, ch in enumerate(text):
        if types[i] != "ON":
            continue
        if ch in _OPENING:
            stack.append((_OPENING[ch], i))
        elif stack and ch in _OPENING.values():
            for depth in range(len(stack) - 1, -1, -1):
                if stack[depth][0] == ch:
                    pairs.append((stack[depth][1], i))
                    del stack[depth:]
                    break
    for opening, closing in sorted(pairs):
        held = types[opening + 1 : closing]
        inside = {_direction(kind) for kind in held if kind in _STRONGISH}
        if not inside:
            continue
        if embedding in inside:
            direction = embedding
        else:
            context = (kind for kind in reversed(types[:opening]) if kind in _STRONGISH)
            before = _direction(next(context, sos))
            direction = before if before != embedding else embedding
        types[opening] = types[closing] = direction


def _direction(kind: str) -> str:
    return "R" if kind in {"R", "AN", "EN"} else "L"


def visual_order(piece_levels: list[int]) -> list[int]:
    """Indices of a line's pieces (in logical order, each of one level) in the
    order they stand on the page, left to right (rule L2)."""

    order = list(range(len(piece_levels)))
    if not piece_levels:
        return order
    highest = max(piece_levels)
    lowest_odd = min((level for level in piece_levels if level % 2), default=highest + 1)
    for level in range(highest, lowest_odd - 1, -1):
        i = 0
        while i < len(order):
            if piece_levels[order[i]] >= level:
                j = i
                while j < len(order) and piece_levels[order[j]] >= level:
                    j += 1
                order[i:j] = reversed(order[i:j])
                i = j
            else:
                i += 1
    return order
