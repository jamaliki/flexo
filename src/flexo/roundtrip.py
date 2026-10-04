"""A YAML document written over the file it was read from, keeping what its person wrote there.

A deck or a theme is edited as data (a keystroke in the studio changes a title) and written
back as a whole. Dumped afresh, the file would lose all that is not data: the comments a
person or an agent left in it (``# agent: tighten this``), its blank lines, its quoting
(``"The pipeline"``) and its order of keys. ``rewrite`` instead reads the file as it is on
disk (ruamel's round trip), puts the new document into it in place -- mappings key by key,
lists item by item, paired by likeness so an item that did not change keeps its comments --
and writes that: every part the edit did not touch is written as it was.

What cannot be kept so (a file that does not read, or one whose top is not a mapping) is
written afresh by ``fresh``, as is anything that would not read back as the document.
"""

from __future__ import annotations

import datetime
import difflib
import io
import json
from collections.abc import Callable
from pathlib import PurePath
from typing import Any

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import (
    DoubleQuotedScalarString,
    LiteralScalarString,
    SingleQuotedScalarString,
)
from ruamel.yaml.util import load_yaml_guess_indent

_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def rewrite(previous: str | None, document: Any, fresh: Callable[[Any], str]) -> str:
    """``document`` as YAML text, written over ``previous`` (the file's text as it is on
    disk): its comments, blank lines, quoting, flow style and key order kept wherever the
    document did not change. Without a ``previous`` that reads as a mapping, ``fresh``."""

    if not previous or not previous.strip() or not isinstance(document, dict):
        return fresh(document)
    reader = _yaml()
    try:
        old, indent, offset = load_yaml_guess_indent(previous, yaml=reader)
    except Exception:  # a file that does not read: nothing of it to keep
        return fresh(document)
    if not isinstance(old, CommentedMap):
        return fresh(document)
    lines = previous.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    was = _parts(old, lines)
    root = _merge(old, document)
    writer = _yaml()
    if indent:
        writer.indent(mapping=indent, sequence=indent, offset=offset or 0)
    if previous.lstrip().startswith("---"):
        writer.explicit_start = True
    out = io.StringIO()
    try:
        writer.dump(root, out)
    except Exception:
        return fresh(document)
    text = out.getvalue()
    # The parts that did not change are their lines as the file had them, word for word:
    # written again, a long line would be wrapped otherwise than it was.
    try:
        spliced = _splice(lines, was, text, reader)
    except Exception:
        spliced = None
    want = _plain(document)
    for candidate in (spliced, text):
        # Written so, it must read as the document does, or it is written afresh: what is
        # kept of the person's file is never kept at the cost of what the document says.
        try:
            if candidate is not None and _plain(yaml.load(candidate, _LOADER)) == want:
                return candidate
        except Exception:
            continue
    return fresh(document)


def _parts(root: CommentedMap, lines: list[str]) -> dict[Any, dict[str, Any]]:
    """Where each of a mapping's keys is in its text (its lines, from its key -- and the
    comments right over it, which speak of it -- to the next key's), what it says, and -- a
    list's -- where each of its items is, so."""

    def begin(line: int, floor: int) -> int:
        while line - 1 > floor and lines[line - 1].lstrip().startswith("#"):
            line -= 1
        return line

    keys = list(root)
    starts: list[int] = []
    for key in keys:
        starts.append(begin(root.lc.key(key)[0], starts[-1] if starts else -1))
    parts = {}
    for at, key in enumerate(keys):
        end = starts[at + 1] if at + 1 < len(keys) else len(lines)
        value = root[key]
        items = None
        listed = isinstance(value, CommentedSeq) and value
        if listed and all(isinstance(item, (dict, list)) for item in value):
            begins: list[int] = []
            for k in range(len(value)):
                begins.append(begin(value.lc.item(k)[0], begins[-1] if begins else starts[at]))
            ends = [*begins[1:], end]
            items = [
                {"start": first, "end": ends[k], "key": _key(value[k])}
                for k, first in enumerate(begins)
            ]
        parts[key] = {"start": starts[at], "end": end, "key": _key(value), "items": items}
    return parts


def _splice(lines: list[str], was: dict[Any, dict[str, Any]], text: str, reader: YAML) -> str:
    """``text`` (the round trip's), each top-level part of it -- and each item of a top-level
    list -- that did not change taken word for word from the file's ``lines``."""

    written = text.splitlines(keepends=True)
    now = _parts(reader.load(text), written)
    if not now:
        return text
    first_now = min(part["start"] for part in now.values())
    first_was = min((part["start"] for part in was.values()), default=0)
    out = lines[:first_was] if was else written[:first_now]
    for key, part in now.items():
        old = was.get(key)
        if old and old["key"] == part["key"]:
            out += lines[old["start"]:old["end"]]
            continue
        if old and old["items"] and part["items"]:
            # Its own lines (the key, what comes before its first item) as written now, then
            # each item: an unchanged one as the file had it, a changed one as written now.
            out += written[part["start"]:part["items"][0]["start"]]
            olds = old["items"]
            keys_old = [item["key"] for item in olds]
            keys_now = [item["key"] for item in part["items"]]
            matcher = difflib.SequenceMatcher(None, keys_old, keys_now, autojunk=False)
            for tag, i1, _i2, j1, j2 in matcher.get_opcodes():
                for k in range(j2 - j1):
                    item = part["items"][j1 + k]
                    if tag == "equal":
                        source = olds[i1 + k]
                        out += lines[source["start"]:source["end"]]
                    else:
                        out += written[item["start"]:item["end"]]
            continue
        out += written[part["start"]:part["end"]]
    return "".join(out)


def _yaml() -> YAML:
    made = YAML()
    made.preserve_quotes = True
    made.width = 100
    made.allow_unicode = True
    return made


def _merge(old: Any, new: Any) -> Any:
    """``new``, put into ``old`` (a node read from the file) where they are alike: the node
    itself, changed in place, when it is kept; else a node made afresh."""

    if isinstance(new, dict):
        return _merge_map(old, new) if isinstance(old, CommentedMap) else _fresh(new)
    if isinstance(new, (list, tuple)):
        return _merge_seq(old, list(new)) if isinstance(old, CommentedSeq) else _fresh(new)
    if _same_scalar(old, new):
        return old
    # Changed words in the quotes the person wrote them in; else as YAML writes them.
    quoted = (SingleQuotedScalarString, DoubleQuotedScalarString)
    if isinstance(new, str) and "\n" not in new and isinstance(old, quoted):
        return type(old)(new)
    return _fresh(new)


def _merge_map(old: CommentedMap, new: dict) -> CommentedMap:
    for key in [key for key in old if key not in new]:
        _drop_key(old, key)
    before = None
    for key, value in new.items():
        if key in old:
            merged = _merge(old[key], value)
            if merged is not old[key]:
                old[key] = merged
        else:
            # A key the file did not have goes after the one the document has before it.
            keys = list(old)
            old.insert(keys.index(before) + 1 if before in keys else 0, key, _fresh(value))
        before = key
    return old


def _drop_key(old: CommentedMap, key: Any) -> None:
    """A key gone; comments on the lines after it (written down there for what follows)
    stay, with the key before it."""

    keys = list(old)
    at = keys.index(key)
    notes = old.ca.items.pop(key, None)
    del old[key]
    after = notes[2] if notes and len(notes) > 2 else None
    if after is not None and at > 0:
        previous = keys[at - 1]
        held = old.ca.items.setdefault(previous, [None, None, None, None])
        while len(held) < 3:
            held.append(None)
        if held[2] is None:
            held[2] = after


def _merge_seq(old: CommentedSeq, new: list) -> CommentedSeq:
    items = list(old)
    # Items paired by likeness: those unchanged kept as they are (with their comments); a
    # run changed, item for item, put into the ones it took the place of.
    keys_old, keys_new = [_key(item) for item in items], [_key(item) for item in new]
    result: list[Any] = []
    sources: list[int | None] = []
    matcher = difflib.SequenceMatcher(None, keys_old, keys_new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            result.extend(items[i1:i2])
            sources.extend(range(i1, i2))
            continue
        paired = min(i2 - i1, j2 - j1) if tag == "replace" else 0
        for k in range(j2 - j1):
            if k < paired:
                result.append(_merge(items[i1 + k], new[j1 + k]))
                sources.append(i1 + k)
            else:
                result.append(_fresh(new[j1 + k]))
                sources.append(None)
    kept = sources == list(range(len(items)))
    if kept and all(a is b for a, b in zip(result, items, strict=True)):
        return old
    notes = dict(old.ca.items)
    old.ca.items.clear()
    del old[:]
    old.extend(result)
    for at, source in enumerate(sources):
        if source is not None and source in notes:
            old.ca.items[at] = notes[source]
    return old


def _fresh(value: Any) -> Any:
    """A value as the round trip writes what is new: block mappings and lists, words over
    several lines as a literal block."""

    if isinstance(value, dict):
        made = CommentedMap()
        for key, item in value.items():
            made[key] = _fresh(item)
        return made
    if isinstance(value, (list, tuple)):
        return CommentedSeq(_fresh(item) for item in value)
    if isinstance(value, PurePath):
        value = str(value)
    if isinstance(value, str) and "\n" in value:
        return LiteralScalarString(value)
    return value


def _same_scalar(old: Any, new: Any) -> bool:
    """Whether a value read from the file is the document's: the same, as YAML reads it (a
    date written bare is the document's words for it)."""

    if isinstance(old, (dict, list)) or isinstance(new, (dict, list, tuple)):
        return False
    if isinstance(old, bool) != isinstance(new, bool):
        return False
    if isinstance(new, PurePath):
        new = str(new)
    if isinstance(old, datetime.date) and isinstance(new, str):
        return old.isoformat() == new
    if isinstance(old, str) != isinstance(new, str):
        return False
    try:
        return bool(old == new)
    except Exception:
        return False


def _key(value: Any) -> str:
    return json.dumps(_plain(value), sort_keys=True, ensure_ascii=False)


def _plain(value: Any) -> Any:
    """``value`` as plain data, to compare: what a file reads as and what a document is."""

    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value) if isinstance(value, float) else int(value)
    if isinstance(value, (datetime.date, PurePath)):
        return str(value)
    if isinstance(value, str):
        return str(value)
    return str(value)
