"""A YAML document written over the file it was read from, keeping what its person wrote there.

A deck or a theme is edited as data (a keystroke in the studio changes a title) and written
back as a whole. Dumped afresh, the file would lose all that is not data: the comments a
person or an agent left in it (``# agent: tighten this``), its blank lines, its quoting
(``"The pipeline"``), its flow-style rows and its order of keys. ``rewrite`` instead reads
the file as it is on disk (ruamel's round trip, read as YAML 1.1 reads it, as the studio
does), puts the new document into it in place and writes that:

- mappings key by key, a new key after the one before it in the document;
- lists item by item, paired by likeness: an item unchanged is kept as it is, one moved
  (a slide moved up, an undo putting it back) is found where it was and keeps all that is
  its own, one changed is put into the one it took the place of;
- a comment over an item (``# --- the middle ---``) is that item's, and goes where it goes;
- every top-level part, and every item of a top-level list (a deck's slides), that did not
  change is its lines as the file had them, word for word.

What cannot be kept so (a file that does not read, or one whose top is not a mapping) is
written afresh by ``fresh``, as is anything that would not read back as the document --
said in the log, never in silence.
"""

from __future__ import annotations

import contextlib
import datetime
import difflib
import io
import itertools
import json
import logging
import re
from collections import OrderedDict
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import PurePath
from typing import Any

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.compat import ordereddict
from ruamel.yaml.error import CommentMark
from ruamel.yaml.scalarstring import (
    DoubleQuotedScalarString,
    LiteralScalarString,
    SingleQuotedScalarString,
)
from ruamel.yaml.tokens import CommentToken
from ruamel.yaml.util import load_yaml_guess_indent

_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_LOG = logging.getLogger(__name__)
_VERSION = (1, 1)
"""YAML as the studio reads it (PyYAML's 1.1): ``yes`` is true, so a word "yes" is quoted."""

_GONE_BY_FILE: OrderedDict[str, tuple[OrderedDict, OrderedDict]] = OrderedDict()
"""Items taken out of a file's lists (a slide deleted) as it had them, nodes and lines, for
a while -- by what they say and what was either side of them: put back where they were
(the deletion undone), one is written as it was, its comments too. A file's own, never
another's, and never for an item new and empty (a Text just added brings no comments)."""
_GONE: ContextVar[tuple[OrderedDict, OrderedDict] | None] = ContextVar("gone", default=None)
_FILE: ContextVar[str | None] = ContextVar("file", default=None)
_LOOSE: ContextVar[dict[str, Any] | None] = ContextVar("loose", default=None)
"""In one writing, the items taken out of a list and those new in one: an object moved to
another list (a slide's other column) is the one taken out, its comments with it."""


def _keep(kept: OrderedDict, key: str, value: Any) -> None:
    kept[key] = value
    kept.move_to_end(key)
    while len(kept) > 64:
        kept.popitem(last=False)


def _gone(which: int) -> OrderedDict | None:
    """The file being written's items taken out (0: nodes, 1: lines); None for no file."""

    found = _GONE.get()
    return found[which] if found is not None else None


def _placed(keys: list[str], at: int) -> str:
    """An item by what it says and what is either side of it in its list."""

    before = keys[at - 1] if at > 0 else ""
    after = keys[at + 1] if at + 1 < len(keys) else ""
    return "\x00".join((before, keys[at], after))


def _empty(value: Any) -> bool:
    """Whether a value says nothing: no words, no numbers (a Text just added)."""

    if isinstance(value, dict):
        return all(_empty(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_empty(item) for item in value)
    return value is None or (isinstance(value, str) and not value.strip())


def _first_of_runs(sources: list[int | None], keys: list[str]) -> None:
    """Of items alike side by side in the file (a slide and its copy), those kept are the
    first: a copy undone leaves the one there before, the comment over it with it."""

    run = 0
    for end in range(1, len(keys) + 1):
        if end < len(keys) and keys[end] == keys[run]:
            continue
        if end - run > 1:
            places = [j for j, at in enumerate(sources) if at is not None and run <= at < end]
            for k, j in enumerate(places):
                sources[j] = run + k
        run = end


def _earliest(sources: list[int | None], keys: list[str], free: list[bool]) -> None:
    """Of items alike side by side (a slide and its copy just made), the first is the one
    there before, with all that is its own (the comment over it): the copy is the later.
    ``free``: an item kept as it was, or new -- not one changed in another's place."""

    run = 0
    for end in range(1, len(keys) + 1):
        if end < len(keys) and keys[end] == keys[run]:
            continue
        places = [j for j in range(run, end) if free[j]]
        mine = [sources[j] for j in places if sources[j] is not None]
        for k, j in enumerate(places):
            sources[j] = mine[k] if k < len(mine) else None
        run = end


@contextlib.contextmanager
def writing(name: str):
    """While a file is written by way of another (a file beside it, moved over it once whole),
    the file it is: what was deleted from it comes back as it was, as when it is written
    itself."""

    token = _FILE.set(name)
    try:
        yield
    finally:
        _FILE.reset(token)


def rewrite(
    previous: str | None, document: Any, fresh: Callable[[Any], str], *, name: str | None = None
) -> str:
    """``document`` as YAML text, written over ``previous`` (the file's text as it is on
    disk): its comments, blank lines, quoting, flow style and key order kept wherever the
    document did not change. Without a ``previous`` that reads as a mapping, ``fresh``.
    ``name`` is the file's: what was deleted from it is put back as it was (an undo)."""

    if not previous or not previous.strip() or not isinstance(document, dict):
        return fresh(document)
    name = _FILE.get() or name
    if name is None:
        token = _GONE.set(None)
    else:
        kept = _GONE_BY_FILE.setdefault(name, (OrderedDict(), OrderedDict()))
        _GONE_BY_FILE.move_to_end(name)
        while len(_GONE_BY_FILE) > 32:
            _GONE_BY_FILE.popitem(last=False)
        token = _GONE.set(kept)
    try:
        return _rewrite(previous, document, fresh)
    finally:
        _GONE.reset(token)


def _rewrite(previous: str, document: Any, fresh: Callable[[Any], str]) -> str:
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
    gaps = _gaps(lines)
    _comments_to_items(old)
    # The comments at the file's end are its end's, whatever comes last in it now: never
    # carried off by the item they follow (a quote moved down, past them).
    ending = _cut_tail(old, list(old)[-1]) if old else None
    loose: dict[str, Any] = {"out": {}, "new": []}
    token = _LOOSE.set(loose)
    try:
        root = _merge(old, document)
        _rehome(loose)
    finally:
        _LOOSE.reset(token)
    writer = _yaml()
    if indent:
        writer.indent(mapping=indent, sequence=indent, offset=offset or 0)
    out = io.StringIO()
    try:
        writer.dump(root, out)
    except Exception:
        _LOG.warning("a YAML file could not be written over its words", exc_info=True)
        return fresh(document)
    text = _trimmed(_undeclared(out.getvalue(), previous)) + (ending or "")
    # The parts that did not change are their lines as the file had them, word for word:
    # written again, a long line would be wrapped otherwise than it was.
    try:
        spliced = _splice(lines, was, text, reader, gaps)
    except Exception:
        _LOG.warning("a YAML file's unchanged parts could not be kept word for word", exc_info=True)
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
        _LOG.warning("a YAML file written over its words did not read back as its document")
    _LOG.warning("a YAML file is written afresh: its comments and quoting are not kept")
    return fresh(document)


def _yaml() -> YAML:
    made = YAML()
    made.preserve_quotes = True
    made.width = 100
    made.allow_unicode = True
    made.version = _VERSION
    return made


def _trimmed(text: str) -> str:
    """The text without the space the round trip leaves at the end of a line where it folds
    a long value (a block's own lines, whose spaces are its words, as they are)."""

    out, block = [], None
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\n")
        depth = len(body) - len(body.lstrip(" "))
        if block is not None and (not body.strip() or depth > block):
            out.append(line)
            continue
        block = depth if re.search(r"(^|[\s:])[|>][-+]?\d?$", body.rstrip()) else None
        out.append(body.rstrip(" ") + ("\n" if line.endswith("\n") else ""))
    return "".join(out)


def _undeclared(text: str, previous: str) -> str:
    """The text without the ``%YAML 1.1`` the round trip puts at its head, unless the file
    had one (and its ``---`` only if it had one)."""

    if previous.lstrip().startswith("%YAML"):
        return text
    text = re.sub(r"\A%YAML [\d.]+\n", "", text)
    if not previous.lstrip().startswith("---"):
        text = re.sub(r"\A---\n", "", text)
    return text


# -- where each part of the file is --


def _parts(root: CommentedMap, lines: list[str]) -> dict[Any, dict[str, Any]]:
    """Where each of a mapping's keys is in its text, what it says, and -- a list of
    mappings or lists (a deck's slides) -- where each of its items is. A part is its lines
    from the comments right over it (which speak of it) to the next part's; an item's
    ``line`` is where it starts itself; a list's ``tail`` the comments after its last item
    (``# end of deck``), which stay at its end."""

    def begin(line: int, floor: int) -> int:
        while line - 1 > floor and lines[line - 1].lstrip().startswith("#"):
            line -= 1
        return line

    def tail(start: int, end: int) -> int:
        while end - 1 > start and (not lines[end - 1].strip() or _remark(lines[end - 1])):
            end -= 1
        return end

    keys = list(root)
    starts: list[int] = []
    for key in keys:
        starts.append(begin(root.lc.key(key)[0], starts[-1] if starts else -1))
    parts = {}
    for at, key in enumerate(keys):
        end = starts[at + 1] if at + 1 < len(keys) else len(lines)
        value = root[key]
        items, rest = None, None
        listed = isinstance(value, CommentedSeq) and value and value.fa.flow_style() is False
        if listed and all(isinstance(item, (dict, list)) for item in value):
            heads = [value.lc.item(k)[0] for k in range(len(value))]
            begins: list[int] = []
            for head in heads:
                begins.append(begin(head, begins[-1] if begins else starts[at]))
            last = tail(heads[-1], end)
            ends = [*begins[1:], last]
            items = [
                {"start": first, "line": heads[k], "end": ends[k], "key": _key(value[k]),
                 "empty": _empty(value[k])}
                for k, first in enumerate(begins)
            ]
            rest = (last, end)
        parts[key] = {
            "start": starts[at],
            "end": end,
            "key": _key(value),
            "items": items,
            "tail": rest,
        }
    return parts


def _remark(line: str) -> bool:
    return line.lstrip().startswith("#")


def _gaps(lines: list[str]) -> dict[str, str]:
    """The room before each comment written after something on its line, by the comment."""

    found = {}
    for line in lines:
        match = re.search(r"\S(\s+)(#.*)$", line.rstrip("\n"))
        if match and not line.lstrip().startswith("#"):
            found.setdefault(match.group(2), match.group(1))
    return found


def _splice(
    lines: list[str], was: dict[Any, dict[str, Any]], text: str, reader: YAML, gaps: dict[str, str]
) -> str:
    """``text`` (the round trip's), each top-level part of it -- and each item of a top-level
    list -- that did not change taken word for word from the file's ``lines``; an item moved
    is its lines too, wherever it went, and one changed keeps the comments over it."""

    written = text.splitlines(keepends=True)
    now = _parts(reader.load(text), written)
    if not now:
        return text
    first_was = min((part["start"] for part in was.values()), default=0)
    out = lines[:first_was]
    for key, part in now.items():
        old = was.get(key)
        if old and old["key"] == part["key"]:
            out += lines[old["start"] : old["end"]]
            continue
        if old and old["items"] and part["items"]:
            out += _spaced(written[part["start"] : part["items"][0]["start"]], gaps)
            olds, news = old["items"], part["items"]
            keys_old = [item["key"] for item in olds]
            used: set[int] = set()
            source: list[int | None] = [None] * len(news)
            changed: list[int | None] = [None] * len(news)
            matcher = difflib.SequenceMatcher(
                None, keys_old, [item["key"] for item in news], autojunk=False
            )
            for tag, i1, _i2, j1, j2 in matcher.get_opcodes():
                if tag == "equal":
                    for k in range(j2 - j1):
                        source[j1 + k] = i1 + k
                        used.add(i1 + k)
            # An item moved is found where it was; one changed in place, by its place.
            for j, item in enumerate(news):
                if source[j] is None:
                    found = next(
                        (
                            i
                            for i, key_old in enumerate(keys_old)
                            if key_old == item["key"] and i not in used
                        ),
                        None,
                    )
                    if found is not None:
                        source[j] = found
                        used.add(found)
            keys_new = [item["key"] for item in news]
            _earliest(source, keys_new, [True] * len(news))
            _first_of_runs(source, keys_old)
            used = {mine for mine in source if mine is not None}
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == "replace":
                    free = [i for i in range(i1, i2) if i not in used]
                    for j in range(j1, j2):
                        if source[j] is None and free:
                            changed[j] = free.pop(0)
                            used.add(changed[j])
            gone = _gone(1)
            for i, item in enumerate(olds):
                if i not in used and gone is not None:
                    _keep(gone, _placed(keys_old, i), lines[item["start"] : item["end"]])
            for j, item in enumerate(news):
                placed = _placed(keys_new, j)
                if source[j] is not None:
                    mine = olds[source[j]]
                    out += lines[mine["start"] : mine["end"]]
                elif changed[j] is not None:
                    mine = olds[changed[j]]
                    out += lines[mine["start"] : mine["line"]]
                    out += _spaced(written[item["line"] : item["end"]], gaps)
                elif gone is not None and placed in gone and not item["empty"]:
                    out += gone.pop(placed)
                else:
                    out += _spaced(written[item["line"] : item["end"]], gaps)
            out += (
                lines[old["tail"][0] : old["tail"][1]]
                if old["tail"]
                else written[part["tail"][0] : part["tail"][1]]
            )
            continue
        out += _spaced(written[part["start"] : part["end"]], gaps)
    return "".join(out)


def _spaced(written: list[str], gaps: dict[str, str]) -> list[str]:
    """Lines written again with each comment after their words at the room it had."""

    out = []
    for line in written:
        match = re.search(r"(\S)(\s+)(#.*)$", line.rstrip("\n"))
        if match and match.group(3) in gaps and not line.lstrip().startswith("#"):
            line = line[: match.start(2)] + gaps[match.group(3)] + match.group(3) + "\n"
        out.append(line)
    return out


# -- comments, as their items' --


def _comments_to_items(node: Any) -> None:
    """The comments on the lines over an item (or a key) made that item's, as written over
    it: ruamel keeps them with what comes before, at the end of its last line, where an
    item moved or a key added after it would carry them off."""

    if isinstance(node, CommentedMap):
        keys = list(node)
        for key in keys:
            _comments_to_items(node[key])
            _first_over(node, key)
        for before, key in itertools.pairwise(keys):
            _over(node, key, _cut_tail(node, before))
    elif isinstance(node, CommentedSeq):
        for item in node:
            _comments_to_items(item)
        for k in range(1, len(node)):
            _over(node, k, _cut_tail(node, k - 1))


def _first_over(holder: CommentedMap, key: Any) -> None:
    """The comments between a key and the first item of its list (``body:``, then ``#
    Callout: say this slowly``, then ``- callout:``) made that item's: ruamel keeps them with
    the list, where they would stay over whichever item came first."""

    value = holder[key]
    if not isinstance(value, CommentedSeq) or not value or value.fa.flow_style():
        return
    tokens = value.ca.comment[1] if value.ca.comment and len(value.ca.comment) > 1 else None
    if not tokens:
        return
    said = [token for token in tokens if isinstance(token, CommentToken)]
    words = "".join(" " * (token.column or 0) + token.value for token in said)
    value.ca.comment[1] = []
    entry = holder.ca.items.get(key)
    if entry and len(entry) > 3:
        entry[3] = None
    _over(value, 0, words)


def _over(holder: Any, slot: Any, words: str | None) -> None:
    if not words:
        return
    entry = holder.ca.items.setdefault(slot, [None, None, None, None])
    entry[1] = [CommentToken(words, CommentMark(0), None), *(entry[1] or [])]


def _cut_tail(holder: Any, slot: Any) -> str | None:
    """The comment lines after what ``holder[slot]`` writes last (not one on its own line),
    taken from it."""

    value = holder[slot]
    if isinstance(value, (CommentedMap, CommentedSeq)) and value and not value.fa.flow_style():
        last = list(value)[-1] if isinstance(value, CommentedMap) else len(value) - 1
        cut = _cut_tail(value, last)
        if cut is not None:
            return cut
    entry = holder.ca.items.get(slot)
    at = 2 if isinstance(holder, CommentedMap) else 0
    token = entry[at] if entry and len(entry) > at else None
    if not isinstance(token, CommentToken) or "\n" not in token.value:
        return None
    end = token.value.index("\n") + 1
    head, rest = token.value[:end], token.value[end:]
    if not rest.strip():
        return None
    if head.strip():
        token.value = head
    else:
        entry[at] = None
    return rest


# -- the document put into the file --


def _merge(old: Any, new: Any) -> Any:
    """``new``, put into ``old`` (a node read from the file) where they are alike: the node
    itself, changed in place, when it is kept; else a node made afresh."""

    if isinstance(new, dict):
        return _merge_map(old, new) if isinstance(old, CommentedMap) else _fresh(new)
    if isinstance(new, (list, tuple)):
        return _merge_seq(old, list(new)) if isinstance(old, CommentedSeq) else _fresh(new)
    if _same_scalar(old, new):
        return old
    # Changed words in the quotes the person chose for them -- not quotes YAML needed for
    # what was there before (an empty '', a '**bold**' start), which the words may not.
    quoted = (SingleQuotedScalarString, DoubleQuotedScalarString)
    if (
        isinstance(new, str)
        and "\n" not in new
        and isinstance(old, quoted)
        and not _needs_quotes(str(old))
    ):
        return type(old)(new)
    return _fresh(new)


def _needs_quotes(words: str) -> bool:
    return yaml.safe_dump(words, width=10**6).lstrip()[:1] in ("'", '"')


def _merge_map(old: CommentedMap, new: dict) -> CommentedMap:
    for key in [key for key in old if key not in new]:
        _drop_key(old, key)
    before = None
    for key, value in new.items():
        if key in old:
            merged = _merge(old[key], value)
            if merged is not old[key]:
                # (Set as it is: ruamel would give new words the quotes of the old ones.)
                ordereddict.__setitem__(old, key, merged)
                old._ok.add(key)
        else:
            # A key the file did not have goes after the one the document has before it (a
            # list of it put together as one would be: an object moved there is itself).
            keys = list(old)
            listed = isinstance(value, (list, tuple))
            made = _merge_seq(CommentedSeq(), list(value)) if listed else _fresh(value)
            old.insert(keys.index(before) + 1 if before in keys else 0, key, made)
        before = key
    return old


def _drop_key(old: CommentedMap, key: Any) -> None:
    """A key gone, and the comments that are its own (on its lines, over it) with it."""

    old.ca.items.pop(key, None)
    # The items of a list gone with it (a slide's column emptied) may be in another now.
    loose, value = _LOOSE.get(), old[key]
    if loose is not None and isinstance(value, CommentedSeq):
        for at, item in enumerate(value):
            if isinstance(item, (CommentedMap, CommentedSeq)):
                loose["out"].setdefault(_key(item), []).append((item, value.ca.items.get(at)))
    del old[key]


def _merge_seq(old: CommentedSeq, new: list) -> CommentedSeq:
    items = list(old)
    keys_old, keys_new = [_key(item) for item in items], [_key(item) for item in new]
    result: list[Any] = [None] * len(new)
    sources: list[int | None] = [None] * len(new)
    used: set[int] = set()
    matcher = difflib.SequenceMatcher(None, keys_old, keys_new, autojunk=False)
    opcodes = matcher.get_opcodes()
    # Items unchanged and where they were: kept as they are, with their comments.
    for tag, i1, _i2, j1, j2 in opcodes:
        if tag == "equal":
            for k in range(j2 - j1):
                sources[j1 + k] = i1 + k
                used.add(i1 + k)
    # Items moved (a slide moved up; an undo putting it back): found where they were.
    for j, key in enumerate(keys_new):
        if sources[j] is None:
            found = next(
                (i for i, key_old in enumerate(keys_old) if key_old == key and i not in used), None
            )
            if found is not None:
                sources[j] = found
                used.add(found)
    _earliest(sources, keys_new, [True] * len(new))
    _first_of_runs(sources, keys_old)
    used = {source for source in sources if source is not None}
    for j, source in enumerate(sources):
        if source is not None:
            result[j] = items[source]
    # Items changed: put into the ones they took the place of, item for item.
    for tag, i1, i2, j1, j2 in opcodes:
        if tag != "replace":
            continue
        free = [i for i in range(i1, i2) if i not in used]
        for j in range(j1, j2):
            if sources[j] is None and free:
                at = free.pop(0)
                result[j], sources[j] = _merge(items[at], new[j]), at
                used.add(at)
    notes = dict(old.ca.items)
    gone, loose = _gone(0), _LOOSE.get()
    for i, item in enumerate(items):
        if i not in used and isinstance(item, (CommentedMap, CommentedSeq)):
            if gone is not None:
                _keep(gone, _placed(keys_old, i), (item, notes.get(i)))
            if loose is not None:
                loose["out"].setdefault(keys_old[i], []).append((item, notes.get(i)))
    # The rest is new -- one taken out a moment ago put back where it was (by an undo) as it
    # was; a copy of one there (a slide duplicated, a figure in it given a new id) as that one
    # is written, comments in it and all (not the one over it, which is the first's); else
    # written as YAML does.
    back: dict[int, Any] = {}
    for j, key in enumerate(keys_new):
        if sources[j] is None and result[j] is None:
            placed = _placed(keys_new, j)
            if gone is not None and placed in gone and not _empty(new[j]):
                result[j], back[j] = gone.pop(placed)
            elif (twin := _twin(items, keys_old, key, new[j])) is not None:
                copied = _copy(items[twin])
                result[j] = copied if keys_old[twin] == key else _merge(copied, new[j])
            else:
                result[j] = _fresh(new[j])
                # (One new and empty, a Text just added, is no object moved.)
                if loose is not None and isinstance(new[j], (dict, list)) and not _empty(new[j]):
                    loose["new"].append((old, j, key))
    if sources == list(range(len(items))) and all(
        a is b for a, b in zip(result, items, strict=True)
    ):
        return old
    old.ca.items.clear()
    del old[:]
    old.extend(result)
    for at, source in enumerate(sources):
        if source is not None and source in notes:
            old.ca.items[at] = notes[source]
        elif back.get(at) is not None:
            old.ca.items[at] = back[at]
    return old


def _rehome(loose: dict[str, Any]) -> None:
    """Each item new in a list that is one taken out of another (a table moved to the left
    column) put there as it was read, the comments over it and in it with it."""

    for holder, at, key in loose["new"]:
        taken = loose["out"].get(key)
        if not taken:
            continue
        item, notes = taken.pop(0)
        list.__setitem__(holder, at, item)
        holder.ca.items.pop(at, None)
        if notes is not None:
            holder.ca.items[at] = notes


def _twin(items: list, keys: list[str], key: str, value: Any) -> int | None:
    """The item a new one is a copy of: the same, or -- a mapping or list -- all but the
    same (a slide duplicated, its figure given an id of its own). None for one empty."""

    if _empty(value):
        return None
    same = next((i for i, other in enumerate(keys) if other == key), None)
    if same is not None or not isinstance(value, (dict, list)):
        return same
    best, found = 0.9, None
    for i, other in enumerate(keys):
        if not isinstance(items[i], (CommentedMap, CommentedSeq)):
            continue
        matcher = difflib.SequenceMatcher(None, other, key, autojunk=False)
        if matcher.real_quick_ratio() > best and matcher.quick_ratio() > best:
            ratio = matcher.ratio()
            if ratio > best:
                best, found = ratio, i
    return found


def _copy(node: Any) -> Any:
    import copy

    return copy.deepcopy(node)


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
    return str(value)
