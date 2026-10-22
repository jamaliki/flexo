"""Drawings read from SVG, kept: a slide read once for its PDF is not read again for its
PowerPoint, nor for the next export of the same deck. Reading a slide's SVG into a drawing
(``flexo.drawing.read_drawing``) is most of what writing it as a PDF takes, and much of what
writing it as a PowerPoint does: a slide with a molecule drawn as shapes has thousands.

A drawing is kept by its SVG's text. What is handed out is the drawing as read, its groups
its reader's own -- a writer may rearrange what a group holds (a PowerPoint takes a slide's
lists out of its drawing, to write them as its own) -- and its shapes, words and pictures,
which nothing changes, shared. The most recently read are kept, as long as all of them
together are no more than about ``SIZE`` bytes.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

from flexo.drawing import Drawing, Group, Image, Shape, Text, read_drawing

SIZE = 96 << 20
"""About how many bytes the drawings kept may take, all told."""

_KEPT: OrderedDict[bytes, tuple[Drawing, int]] = OrderedDict()
_LOCK = threading.Lock()


def drawing_of(svg_text: str) -> Drawing:
    """``read_drawing(svg_text)``: as read before, where it was; its groups yours."""

    key = hashlib.sha256(svg_text.encode("utf-8")).digest()
    with _LOCK:
        found = _KEPT.get(key)
        if found is not None:
            _KEPT.move_to_end(key)
    if found is None:
        drawing = read_drawing(svg_text)
        found = (drawing, _size(drawing.root))
        with _LOCK:
            _KEPT[key] = found
            _KEPT.move_to_end(key)
            total = sum(size for _, size in _KEPT.values())
            while total > SIZE and len(_KEPT) > 1:
                _, (_, size) = _KEPT.popitem(last=False)
                total -= size
    drawing = found[0]
    return Drawing(drawing.width, drawing.height, _groups(drawing.root))


def _groups(group: Group) -> Group:
    """``group`` with every group in it its own copy: what each holds may be rearranged."""

    return Group(
        group.id,
        [_groups(item) if isinstance(item, Group) else item for item in group.items],
        dict(group.data),
        group.label,
        group.clip,
    )


def _size(group: Group) -> int:
    """About how many bytes ``group`` and what it holds take: a shape's points most of all."""

    total = 200
    for item in group.items:
        if isinstance(item, Group):
            total += _size(item)
        elif isinstance(item, Shape):
            points = sum(len(segment.points) for segment in item.segments)
            heads = sum(len(segment.points) for head in item.arrowheads for segment in head.outline)
            total += 700 + 100 * len(item.segments) + 150 * (points + heads)
        elif isinstance(item, Text):
            total += 600 + sum(300 * len(line.runs) + 200 for line in item.lines)
        elif isinstance(item, Image):
            total += 400 + len(item.href)
        else:
            total += 200
    return total
