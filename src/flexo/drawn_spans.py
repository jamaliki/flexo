"""Where a compiled figure's molecules are drawn, in its words.

A molecule drawn as shapes (``flexo.render_drawn``: a structure in a look drawn as shapes) is
nested in its figure as an ``<svg>`` of its own -- a few hundred shapes, most of the figure's
words: a figure of four proteins is three quarters of a megabyte, of which a few kilobytes are
the figure's own boxes, words and lines. What reads a figure for its own parts -- the extent
of its ink (``flexo.structure_fit.figure_ink``), its ids prefixed for a slide (flexo-talk) --
need not read every one of those shapes each time: ``spans`` says where each molecule's shapes
are in the words, for them to be left out, or read once and kept. What reads it whole (lint)
reads it so too (``read``): each molecule's shapes read once, and put in a copy of their own.

The words are as ``flexo.svg.xml_document`` writes them (ElementTree's): every ``<`` begins a
tag -- in words and in attribute values it is written ``&lt;``, ``>`` in a value ``&gt;`` and
``"`` there ``&quot;`` -- and nothing is a comment, a CDATA section or an instruction. Words
written otherwise (any of those found) are not told apart: ``spans`` says None, and they are
read whole, as ever.
"""

from __future__ import annotations

import copy
import functools
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

MARK = 'data-flexo-drawn="mol-sketch"'
"""How the group holding a molecule drawn as shapes is marked (``flexo.render_drawn``)."""

_ODD = re.compile(r"<[!?]")
_TAG = re.compile(r"<(/?)([A-Za-z_][\w:.-]*)(?:\s[^>]*?)?(/?)>")
_SVG = re.compile(r"<(/?)svg(?=[\s/>])")
_ID = re.compile(r'\sid="([^"&]*)"')


@dataclass(frozen=True, slots=True)
class Span:
    """A molecule's ``<svg>`` in a figure's words: its group's id, where the ``<svg>`` begins
    (``start``), where its shapes begin (``inside``: after the words before the first of them,
    which stay the ``<svg>``'s own) and where its closing tag begins (``end``) -- its shapes
    are ``words[inside:end]``, the last one's trailing words with them. ``inside == end`` for
    one that holds no shapes."""

    holder: str
    start: int
    inside: int
    end: int


@functools.lru_cache(maxsize=16)
def spans(words: str) -> tuple[Span, ...] | None:
    """Each molecule nested in ``words`` -- the ``<svg>`` children of each group marked as
    holding one (``MARK``), in the order they are written -- or None when the words are not
    plainly as ElementTree writes them, or a group marked so is not as ``flexo.render_drawn``
    writes one (another group's ``<svg>`` within it). (Kept for the last few words asked of:
    a figure's are asked of for its ink, and again as it is placed on a slide.)"""

    if MARK not in words:
        return ()
    declared = words.find("?>") + 2 if words.startswith("<?") else 0
    if _ODD.search(words, declared) is not None:
        return None
    found: list[Span] = []
    at = 0
    while True:
        mark = words.find(MARK, at)
        if mark < 0:
            return tuple(found)
        start = words.rfind("<", 0, mark)
        close = words.find(">", mark)
        if start < 0 or close < 0 or ">" in words[start:mark]:
            return None
        head = words[start : close + 1]
        named = _ID.search(head)
        if not head.startswith("<g ") or head.endswith("/>") or named is None:
            return None
        held = _children(words, close + 1, named.group(1))
        if held is None:
            return None
        made, at = held
        # (One within another, it is not told apart: read whole.)
        if words.find(MARK, close + 1, at) >= 0:
            return None
        found += made


def _children(words: str, at: int, holder: str) -> tuple[list[Span], int] | None:
    """The ``<svg>`` children of the group whose own words begin at ``at`` -- and where its
    closing tag ends -- or None."""

    made: list[Span] = []
    depth = 0
    while True:
        tag = _TAG.search(words, at)
        if tag is None:
            return None
        closing, name, empty = tag.group(1), tag.group(2), tag.group(3)
        if name.endswith(":svg"):
            return None
        if closing:
            if depth == 0:
                return (made, tag.end()) if name == "g" else None
            depth -= 1
        elif name == "svg" and depth == 0:
            if empty:
                made.append(Span(holder, tag.start(), tag.end(), tag.end()))
            else:
                end = _svg_end(words, tag.end())
                if end is None:
                    return None
                first = words.find("<", tag.end(), end)
                inside = end if first < 0 else first
                made.append(Span(holder, tag.start(), inside, end))
                at = end + len("</svg>")
                continue
        elif not empty:
            depth += 1
        at = tag.end()


def _svg_end(words: str, at: int) -> int | None:
    """Where the closing tag of the ``<svg>`` whose shapes begin at ``at`` begins."""

    depth = 0
    while True:
        tag = _SVG.search(words, at)
        if tag is None:
            return None
        if tag.group(1):
            if depth == 0:
                return tag.start() if words.startswith("</svg>", tag.start()) else None
            depth -= 1
            at = tag.end()
            continue
        close = words.find(">", tag.end())
        if close < 0:
            return None
        if words[close - 1] != "/":
            depth += 1
        at = close + 1


def without(words: str, left_out: list[Span] | tuple[Span, ...]) -> str:
    """``words`` without the shapes of each of ``left_out`` (spans of ``words``)."""

    pieces = []
    at = 0
    for span in left_out:
        pieces.append(words[at : span.inside])
        at = span.end
    pieces.append(words[at:])
    return "".join(pieces)


_DECLARED = re.compile(r'\sxmlns(?::[\w.-]+)?="[^"]*"')


def read(words: str) -> ET.Element:
    """``words`` read (``ET.fromstring``) -- the very tree reading them whole makes, each
    molecule's shapes read once, kept (``_shapes``), and put in a copy of their own."""

    every = spans(words)
    found = [span for span in every or () if span.inside < span.end]
    head = re.match(r"(?:<\?[^>]*\?>\s*)?<[^>]*>", words) if found else None
    if not every or not found or head is None:
        return ET.fromstring(words)
    declared = " ".join(_DECLARED.findall(head.group(0)))
    if any("xmlns" in words[span.start : span.end] for span in found):
        return ET.fromstring(words)
    try:
        shapes = [_shapes(words[span.inside : span.end], declared) for span in found]
        root = ET.fromstring(without(words, found))
    except ET.ParseError:
        return ET.fromstring(words)  # (said as reading them whole says it)
    holders = [
        child
        for item in root.iter()
        if item.get("data-flexo-drawn") == "mol-sketch"
        for child in item
        if isinstance(child.tag, str) and child.tag.rsplit("}", 1)[-1] == "svg"
    ]
    if len(holders) != len(every):
        return ET.fromstring(words)
    order = {span.start: index for index, span in enumerate(every)}
    for span, kept in zip(found, shapes, strict=True):
        holders[order[span.start]].extend(copy.deepcopy(shape) for shape in kept)
    return root


@functools.lru_cache(maxsize=64)
def _shapes(held: str, declared: str) -> tuple[ET.Element, ...]:
    """A molecule's shapes (``held``: its words) read, in the namespaces its figure declares:
    kept, and never changed."""

    return tuple(ET.fromstring(f"<svg {declared}>{held}</svg>"))
