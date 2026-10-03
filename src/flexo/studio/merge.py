"""Three-way merge of JSON documents: two people's changes to one document, together.

``merge3(base, ours, theirs)`` keeps what either side changed from ``base``.
Mappings merge key by key. Lists merge item by item, each item known by what it
was: a slide one side edited and the other moved is the edited slide, moved; one
side's new slide beside a slide the other edited is kept, and so is the edit; an
item both edited is merged in turn; both sides' insertions at one place are kept,
ours first; an item one side removed and the other edited is kept, edited. Words
merge line by line, and within a line both changed, word by word. Where both sides
changed the same thing differently, ``theirs`` wins: the studio passes the newest
change as ``theirs``. ``static/studio/merge.js`` is the same algorithm for the page.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from itertools import pairwise
from typing import Any

_MISSING = object()
_LINES = re.compile(r"[^\n]*\n|[^\n]+")
_WORDS = re.compile(r"\w+|\s+|[^\w\s]")
_SPACE = re.compile(r"\s")
_WORDS_ONLY = re.compile(r"\w+")


def merge3(base: Any, ours: Any, theirs: Any) -> Any:
    if _same(ours, theirs) or _same(base, theirs):
        return ours
    if _same(base, ours):
        return theirs
    if isinstance(ours, dict) and isinstance(theirs, dict):
        return _merge_dicts(base if isinstance(base, dict) else {}, ours, theirs)
    if isinstance(ours, list) and isinstance(theirs, list):
        return merge_items(base if isinstance(base, list) else [], ours, theirs)
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


def merge_items(base: list, ours: list, theirs: list) -> list:
    """Merge two edits of a list of items by the items' identities (see the module's
    words): each side's items are paired with the items of ``base`` they were."""

    to_ours, to_theirs = _pairs(base, ours), _pairs(base, theirs)
    from_ours = {j: i for i, j in to_ours.items()}
    from_theirs = {k: i for i, k in to_theirs.items()}
    # Items both sides added alike are one item.
    twins: dict[int, int] = {}
    added: dict[str, list[int]] = {}
    for j, item in enumerate(ours):
        if j not in from_ours:
            added.setdefault(_key(item), []).append(j)
    for k, item in enumerate(theirs):
        if k not in from_theirs and added.get(_key(item)):
            twins[k] = added[_key(item)].pop(0)
    seq_ours = [("b", from_ours[j]) if j in from_ours else ("o", j) for j in range(len(ours))]
    seq_theirs = [
        ("b", from_theirs[k]) if k in from_theirs else ("o", twins[k]) if k in twins else ("t", k)
        for k in range(len(theirs))
    ]
    content: dict[tuple[str, int], Any] = {}
    for i, was in enumerate(base):
        j, k = to_ours.get(i), to_theirs.get(i)
        if j is not None and k is not None:
            content[("b", i)] = merge3(was, ours[j], theirs[k])
        elif j is not None and not _same(ours[j], was):
            content[("b", i)] = ours[j]  # removed by them, edited by us: kept, edited
        elif k is not None and not _same(theirs[k], was):
            content[("b", i)] = theirs[k]
    for name, j in seq_ours:
        if name == "o":
            content[("o", j)] = ours[j]
    for name, k in seq_theirs:
        if name == "t":
            content[("t", k)] = theirs[k]

    # The order: the side that moved items has its order (theirs, if both did); the other
    # side's items not in it go after the item they followed there, after the first
    # side's own additions at that place.
    def moved(seq: list[tuple[str, int]]) -> bool:
        kept = [i for name, i in seq if name == "b"]
        return kept != sorted(kept)

    first, second = (seq_theirs, seq_ours) if moved(seq_theirs) else (seq_ours, seq_theirs)
    order = [item for item in first if item in content]
    placed = set(order)
    own = {item for item in first if item[0] != "b"}
    previous = None
    for item in second:
        if item in placed:
            previous = item
            continue
        if item not in content:
            continue
        at = order.index(previous) + 1 if previous is not None else 0
        while at < len(order) and order[at] in own:
            at += 1
        order.insert(at, item)
        placed.add(item)
        previous = item
    return [content[item] for item in order]


_ALIKE = 0.4
"""How alike an item must be to an item of base to be taken for it (see ``_alike``)."""


def _pairs(base: list, side: list) -> dict[int, int]:
    """Which item of ``side`` each item of ``base`` became: the same item where it is in
    order (a longest common subsequence), or moved; else, between items kept, the most
    alike of the items changed; else, as many changed as there were, each in turn."""

    keys_base, keys_side = [_key(item) for item in base], [_key(item) for item in side]
    pairs = _matches(keys_base, keys_side)
    anchors = sorted(pairs.items())
    used = set(pairs.values())
    # Moved: the same item elsewhere (a word, a slide), never a number or a flag.
    free: dict[str, list[int]] = {}
    for j, item in enumerate(side):
        if j not in used and isinstance(item, str | dict | list):
            free.setdefault(keys_side[j], []).append(j)
    for i, item in enumerate(base):
        if i not in pairs and isinstance(item, str | dict | list) and free.get(keys_base[i]):
            j = free[keys_base[i]].pop(0)
            pairs[i] = j
            used.add(j)
    # Changed: between two items kept in order, the most alike first, then the rest in turn.
    bounds = [(-1, -1), *anchors, (len(base), len(side))]
    for (low_b, low_s), (high_b, high_s) in pairwise(bounds):
        gone = [i for i in range(low_b + 1, high_b) if i not in pairs]
        come = [j for j in range(low_s + 1, high_s) if j not in used]
        if not gone or not come:
            continue
        scored = sorted(
            (-score, abs((i - low_b) / (high_b - low_b) - (j - low_s) / (high_s - low_s)), i, j)
            for i in gone
            for j in come
            if (score := _alike(base[i], side[j])) >= _ALIKE
        )
        for _, _, i, j in scored:
            if i not in pairs and j not in used:
                pairs[i] = j
                used.add(j)
        gone = [i for i in gone if i not in pairs]
        come = [j for j in come if j not in used]
        if len(gone) == len(come):
            for i, j in zip(gone, come, strict=True):
                if _kin(base[i], side[j]):
                    pairs[i] = j
                    used.add(j)
    return pairs


def _kind(item: Any) -> str:
    if isinstance(item, bool):
        return "flag"
    if isinstance(item, int | float):
        return "number"
    return type(item).__name__


def _kin(first: Any, second: Any) -> bool:
    """Whether one item could have become the other: of one kind, and a mapping with a
    key of the other's (with an id, the same id)."""

    if _kind(first) != _kind(second):
        return False
    if isinstance(first, dict):
        if "id" in first and "id" in second:
            return _same(first["id"], second["id"])
        return bool(first.keys() & second.keys()) or not first or not second
    return True


def _alike(first: Any, second: Any) -> float:
    """How alike two items are, from 0 to 1: words by the letters they share at their
    ends and the words they share; mappings by their values, key by key (with an id,
    by it alone); lists by their items, place by place."""

    if _same(first, second):
        return 1.0
    if not _kin(first, second):
        return 0.0
    if isinstance(first, str):
        if not first or not second:
            return 0.5
        start = 0
        most = min(len(first), len(second))
        while start < most and first[start] == second[start]:
            start += 1
        end = 0
        while end < most - start and first[-1 - end] == second[-1 - end]:
            end += 1
        ends = (start + end) / ((len(first) + len(second)) / 2)
        words_a = set(_WORDS_ONLY.findall(first.lower()))
        words_b = set(_WORDS_ONLY.findall(second.lower()))
        shared = len(words_a & words_b) / len(words_a | words_b) if words_a | words_b else 0.0
        return max(ends, shared)
    if isinstance(first, dict):
        if "id" in first and "id" in second:
            return 1.0
        keys = sorted(first.keys() | second.keys())  # in one order, as the page adds them
        total = 0.0
        for key in keys:
            if key in first and key in second:
                same = _same(first[key], second[key])
                total += 1.0 if same else 0.25 + 0.75 * _alike(first[key], second[key])
        return total / len(keys)
    if isinstance(first, list):
        longest = max(len(first), len(second))
        if not longest:
            return 1.0
        places = zip(first, second, strict=False)
        return sum(1.0 if _same(a, b) else 0.5 * _alike(a, b) for a, b in places) / longest
    return 0.0


def merge_lists(base: list, ours: list, theirs: list) -> list:
    """Merge two edits of a list of lines, as diff3 merges two edits of a file."""

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
