"""Parts of a drawing written out once, however often the drawing is.

A molecule drawn as shapes is a few hundred elements nested in its figure (``flexo.render_drawn``),
most of what the figure is -- and of the slide it is placed on. ElementTree writes a drawing in
Python, element by element (``flexo.svg.xml_document``): a slide with four proteins on it was
written whole at every letter typed on it, the proteins' shapes as they were the letter before,
seven milliseconds of the slide's twenty.

So a tree of elements copied from one kept unchanged (``copied``: a molecule read once,
``flexo.svg.read_markup``; a figure placed on a slide, flexo-talk's) has each child of it
*sealed*: known to be a copy of the kept one's (``seal``). ``xml_document`` writes a sealed child
it finds still as it was copied -- element for element, word for word: what it is checked by
before it is written -- as the kept one is written at that depth, worked out once and kept
(``_written``), and the rest of the drawing as it would be. A child changed since it was copied
(a part hidden in it, its ids made the slide's) is written as any other. What is written is the
same, to the letter, either way: only sooner.
"""

from __future__ import annotations

import copy
import re
import secrets
import threading
import weakref
import xml.etree.ElementTree as ET
from collections import OrderedDict
from collections.abc import Callable
from io import StringIO

XML_NS = "http://www.w3.org/XML/1998/namespace"
"""The namespace of ``xml:space``: never declared."""

WRITTEN = 512
"""How many sealed children, each at a depth, are kept written."""

_KEPT: weakref.WeakKeyDictionary[ET.Element, ET.Element] = weakref.WeakKeyDictionary()
"""Each sealed child: what it is a copy of."""
_WRITTEN: OrderedDict[tuple[int, int, tuple], tuple[ET.Element, str]] = OrderedDict()
"""Each kept child, written at a depth (by its identity, held, and its namespaces' prefixes)."""
_USES: OrderedDict[int, tuple[ET.Element, tuple[str, ...] | None]] = OrderedDict()
"""The namespaces each kept child names -- None should one not be registered."""
_LOCK = threading.Lock()

_MARK = f"flexo-sealed-{secrets.token_hex(6)}-"
_MARKED = re.compile(rf"<{_MARK}(\d+)\b[^>]*/>")


def seal(made: ET.Element, kept: ET.Element) -> None:
    """``made`` known to be a copy of ``kept``, which is never changed."""

    _KEPT[made] = kept


def copied(kept: ET.Element) -> ET.Element:
    """A copy of ``kept`` (``copy.deepcopy``), each of its children sealed (``seal``): ``kept``
    must never be changed."""

    made = copy.deepcopy(kept)
    for child, original in zip(made, kept, strict=True):
        _KEPT[child] = original
    return made


def sealed_in(root: ET.Element) -> list[tuple[ET.Element, int, ET.Element, int]]:
    """The sealed children in ``root`` still as they were copied, none within a ``<text>``:
    each with its parent, where it is among the parent's children, and its depth -- found
    without going into them."""

    if not _KEPT:
        return []
    found = []
    stack = [(root, 0, False)]
    while stack:
        parent, depth, worded = stack.pop()
        worded = worded or _local(parent.tag) == "text"
        for index, child in enumerate(parent):
            kept = _KEPT.get(child)
            if kept is not None and not worded and _uses(kept) is not None and _same(child, kept):
                found.append((parent, index, kept, depth + 1))
            elif len(child):
                stack.append((child, depth + 1, worded))
    return found


def written_with(
    root: ET.Element,
    found: list[tuple[ET.Element, int, ET.Element, int]],
    write: Callable[[ET.Element], str],
) -> str:
    """``write(root)`` -- the drawing indented and written -- with each of the sealed children
    ``found`` (``sealed_in``) written as kept: each stood in for, as it is written, by a mark
    naming the namespaces it names (for them to be declared as they would be), and the mark
    replaced by it, as written at its depth (``_written``)."""

    marks = []
    for number, (parent, index, kept, _) in enumerate(found):
        child = parent[index]
        mark = ET.Element(f"{_MARK}{number}")
        for uri in _uses(kept) or ():
            mark.set(f"{{{uri}}}s", "")
        mark.tail = child.tail
        parent[index] = mark
        marks.append(child)
    try:
        text = write(root)
    finally:
        for (parent, index, _, _), child in zip(found, marks, strict=True):
            child.tail = parent[index].tail
            parent[index] = child
    pieces = {
        str(number): _written(kept, depth) for number, (_, _, kept, depth) in enumerate(found)
    }
    return _MARKED.sub(lambda match: pieces[match.group(1)], text)


def _same(made: ET.Element, kept: ET.Element) -> bool:
    """Whether ``made`` is still as ``kept``, element for element (its own tail aside): the two
    gone through side by side, each element's tag, words, attributes and how many children it
    has alike -- and so the same elements, in the same places."""

    for one, other in zip(made.iter(), kept.iter(), strict=False):
        if (
            one.tag != other.tag
            or one.text != other.text
            or len(one) != len(other)
            or one.attrib != other.attrib
            or (one.tail != other.tail and one is not made)
        ):
            return False
    return True


def _uses(kept: ET.Element) -> tuple[str, ...] | None:
    """The namespaces ``kept`` names in its tags and its attributes' names, but ``xml``'s;
    None should one of them not be registered (``ET.register_namespace``) -- its prefix would
    be the drawing's to choose -- or anything in it not be an element or a name in words."""

    with _LOCK:
        known = _USES.get(id(kept))
        if known is not None and known[0] is kept:
            _USES.move_to_end(id(kept))
            return known[1]
    found: set[str] | None = set()
    registered = ET._namespace_map  # type: ignore[attr-defined]
    for item in kept.iter():
        if not isinstance(item.tag, str):
            found = None
            break
        for name in (item.tag, *item.keys()):
            if not isinstance(name, str):
                found = None
                break
            if name[:1] == "{":
                uri = name[1:].rsplit("}", 1)[0]
                if uri != XML_NS:
                    found.add(uri)
        if found is None:
            break
    if found is not None and any(uri not in registered for uri in found):
        found = None
    uses = None if found is None else tuple(sorted(found))
    with _LOCK:
        _USES[id(kept)] = (kept, uses)
        while len(_USES) > WRITTEN:
            _USES.popitem(last=False)
    return uses


def _written(kept: ET.Element, depth: int) -> str:
    """``kept`` as ``flexo.svg.xml_document`` writes it at ``depth`` in a drawing -- indented
    from there, the space in its words taken out where it would be -- but for its tail."""

    from flexo.svg import unspaced

    # (By the prefixes its namespaces are written with too: registered since, they would be
    # written so.)
    registered = ET._namespace_map  # type: ignore[attr-defined]
    key = (id(kept), depth, tuple(registered.get(uri) for uri in _uses(kept) or ()))
    with _LOCK:
        known = _WRITTEN.get(key)
        if known is not None and known[0] is kept:
            _WRITTEN.move_to_end(key)
            return known[1]
    made = copy.deepcopy(kept)
    ET.indent(made, space="  ", level=depth)
    unspaced(made)
    made.tail = None
    qnames, _ = ET._namespaces(made)  # type: ignore[attr-defined]
    out = StringIO()
    ET._serialize_xml(out.write, made, qnames, None, short_empty_elements=True)  # type: ignore[attr-defined]
    text = out.getvalue()
    with _LOCK:
        _WRITTEN[key] = (kept, text)
        while len(_WRITTEN) > WRITTEN:
            _WRITTEN.popitem(last=False)
    return text


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""
