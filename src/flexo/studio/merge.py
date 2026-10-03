"""Three-way merge of JSON documents: two people's changes to one document, together.

``merge3(base, ours, theirs)`` keeps what either side changed from ``base``.
Mappings merge key by key; lists merge like lines of text (each side's
insertions, removals, and edits kept where they do not touch, both sides'
insertions at one place kept in order, an item both edited merged in turn);
words merge line by line, and within a line both changed, word by word. Where
both sides changed the same thing differently, ``theirs`` wins: the studio
passes the newest change as ``theirs``. ``static/studio/merge.js`` is the same
algorithm for the page.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

_MISSING = object()
_LINES = re.compile(r"[^\n]*\n|[^\n]+")
_WORDS = re.compile(r"\w+|\s+|[^\w\s]")
_SPACE = re.compile(r"\s")


def merge3(base: Any, ours: Any, theirs: Any) -> Any:
    if _same(ours, theirs) or _same(base, theirs):
        return ours
    if _same(base, ours):
        return theirs
    if isinstance(ours, dict) and isinstance(theirs, dict):
        return _merge_dicts(base if isinstance(base, dict) else {}, ours, theirs)
    if isinstance(ours, list) and isinstance(theirs, list):
        return merge_lists(base if isinstance(base, list) else [], ours, theirs)
    if isinstance(ours, str) and isinstance(theirs, str) and isinstance(base, str):
        return merge_text(base, ours, theirs)
    return theirs


def merge_text(base: str, ours: str, theirs: str) -> str:
    """Two edits of words, merged as diff3 merges two edits of a file: line by line,
    and lines both changed word by word, so two people typing in one field keep both
    their words. Where both changed the same words differently, ``theirs`` wins; a
    single word (a name, a colour, a file) is not taken apart."""

    if ours == theirs or base == theirs:
        return ours
    if base == ours:
        return theirs
    if "\n" in base or "\n" in ours or "\n" in theirs:
        lines = [_LINES.findall(text) for text in (base, ours, theirs)]
        return "".join(_diff3(*lines, _lines_chunk))
    return _merge_words(base, ours, theirs)


def _merge_words(base: str, ours: str, theirs: str) -> str:
    if not any(_SPACE.search(text) for text in (base, ours, theirs)):
        return theirs
    words = [_WORDS.findall(text) for text in (base, ours, theirs)]
    return "".join(_diff3(*words, _words_chunk))


def _lines_chunk(base: list, ours: list, theirs: list) -> list:
    if not base:
        return [*ours, *theirs]
    return [_merge_words("".join(base), "".join(ours), "".join(theirs))]


def _words_chunk(base: list, ours: list, theirs: list) -> list:
    return [*ours, *theirs] if not base else list(theirs)


def _merge_dicts(base: dict, ours: dict, theirs: dict) -> dict:
    result: dict = {}
    for key in [*ours, *(key for key in theirs if key not in ours)]:
        was = base.get(key, _MISSING)
        mine = ours.get(key, _MISSING)
        other = theirs.get(key, _MISSING)
        if mine is not _MISSING and other is not _MISSING:
            result[key] = merge3(None if was is _MISSING else was, mine, other)
        elif mine is not _MISSING:
            # Theirs lacks it: kept if we added it; gone if they removed it (even
            # if we changed it: theirs wins).
            if was is _MISSING:
                result[key] = mine
        elif was is _MISSING or not _same(was, other):
            # Ours lacks it: kept if they added or changed it, gone if we removed it.
            result[key] = other
    return result


def merge_lists(base: list, ours: list, theirs: list) -> list:
    """Merge two edits of a list, as diff3 merges two edits of a file."""

    return _diff3(base, ours, theirs, _chunk)


def _diff3(base: list, ours: list, theirs: list, both: Callable[[list, list, list], list]) -> list:
    """The items of ``base`` both sides kept hold the merge together; between them, the
    side that changed something has it, and ``both`` settles what both sides changed."""

    keys_base = [_key(item) for item in base]
    to_ours = _matches(keys_base, [_key(item) for item in ours])
    to_theirs = _matches(keys_base, [_key(item) for item in theirs])
    result: list = []
    b = o = t = 0
    anchors = [
        (i, to_ours[i], to_theirs[i]) for i in range(len(base)) if i in to_ours and i in to_theirs
    ]
    for ab, ao, at in [*anchors, (len(base), len(ours), len(theirs))]:
        was, mine, other = base[b:ab], ours[o:ao], theirs[t:at]
        if _same(mine, was):
            result.extend(other)
        elif _same(other, was) or _same(mine, other):
            result.extend(mine)
        else:
            result.extend(both(was, mine, other))
        if ab < len(base):
            result.append(ours[ao])
        b, o, t = ab + 1, ao + 1, at + 1
    return result


def _chunk(base: list, ours: list, theirs: list) -> list:
    if not base:
        # Both inserted here: keep both.
        return [*ours, *theirs]
    if len(base) == len(ours) == len(theirs):
        return [
            merge3(was, mine, other) for was, mine, other in zip(base, ours, theirs, strict=True)
        ]
    return list(theirs)


def _matches(first: list[str], second: list[str]) -> dict[int, int]:
    """Where each item of ``first`` sits in ``second``, by a longest common subsequence."""

    start = 0
    while start < len(first) and start < len(second) and first[start] == second[start]:
        start += 1
    end_a, end_b = len(first), len(second)
    while end_a > start and end_b > start and first[end_a - 1] == second[end_b - 1]:
        end_a -= 1
        end_b -= 1
    matched = {i: i for i in range(start)}
    middle_a, middle_b = first[start:end_a], second[start:end_b]
    if middle_a and middle_b:
        rows, cols = len(middle_a), len(middle_b)
        table = [[0] * (cols + 1) for _ in range(rows + 1)]
        for i in range(rows - 1, -1, -1):
            row, below = table[i], table[i + 1]
            for j in range(cols - 1, -1, -1):
                row[j] = (
                    below[j + 1] + 1 if middle_a[i] == middle_b[j] else max(below[j], row[j + 1])
                )
        i = j = 0
        while i < rows and j < cols:
            if middle_a[i] == middle_b[j]:
                matched[start + i] = start + j
                i += 1
                j += 1
            elif table[i + 1][j] >= table[i][j + 1]:
                i += 1
            else:
                j += 1
    for offset in range(len(first) - end_a):
        matched[end_a + offset] = end_b + offset
    return matched


def _key(item: Any) -> str:
    return item if isinstance(item, str) else json.dumps(item, sort_keys=True, ensure_ascii=False)


def _same(first: Any, second: Any) -> bool:
    if first is second:
        return True
    if type(first) is not type(second) and not (
        isinstance(first, int | float) and isinstance(second, int | float)
    ):
        return False
    return first == second
