"""A drawing holding molecules is written with each molecule's shapes written out once
(flexo.sealed), to the letter as it would be written element by element; and markup read once
is a copy of its own each time it is asked for (flexo.svg.read_markup)."""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

from flexo import sealed
from flexo.svg import SVG_NS, read_markup, xml_document

_MOLECULE = (
    f'<svg xmlns="{SVG_NS}" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
    'viewBox="0 0 10 10"><g id="chain" inkscape:label="Chain A"><path d="M0 0L1 1" '
    'fill="#123456"/><g id="res"><circle r="1"/><text xml:space="preserve">'
    '<tspan>C</tspan> <tspan>a</tspan></text></g></g><g id="other"><rect width="2"/></g></svg>'
)


def _drawing(depth: int) -> ET.Element:
    root = ET.Element(f"{{{SVG_NS}}}svg", {"id": "page"})
    holder = root
    for level in range(depth):
        holder = ET.SubElement(holder, f"{{{SVG_NS}}}g", {"id": f"g{level}"})
    words = ET.SubElement(holder, f"{{{SVG_NS}}}text")
    ET.SubElement(words, f"{{{SVG_NS}}}tspan").text = "Words"
    holder.append(read_markup(_MOLECULE))
    ET.SubElement(holder, f"{{{SVG_NS}}}rect", {"id": "after"})
    return root


def test_a_drawing_holding_sealed_parts_is_written_to_the_letter_as_it_would_be() -> None:
    """Written with its sealed parts (``flexo.sealed``) written out once, a drawing is the
    same, to the letter, as written element by element -- at any depth, its namespaces
    declared as they would be, again and again; and so it is with a sealed part changed."""

    for depth in (0, 1, 4):
        drawing = _drawing(depth)
        expected = xml_document(copy.deepcopy(drawing))  # (copied, nothing in it is sealed)
        assert sealed.sealed_in(drawing)
        assert xml_document(drawing) == expected
        assert xml_document(drawing) == expected  # (written again)
        assert 'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"' in expected
        changed = _drawing(depth)
        part = next(item for item in changed.iter() if item.get("id") == "res")
        part.set("opacity", "0.5")
        assert xml_document(changed) == xml_document(copy.deepcopy(changed))
        assert "opacity" in xml_document(changed)


def test_a_sealed_part_within_words_is_written_element_by_element() -> None:
    root = ET.Element(f"{{{SVG_NS}}}svg")
    words = ET.SubElement(root, f"{{{SVG_NS}}}text")
    holder = read_markup(_MOLECULE)
    words.append(holder)
    assert sealed.sealed_in(root) == []
    assert xml_document(root) == xml_document(copy.deepcopy(root))


def test_markup_read_once_is_a_copy_of_its_own_each_time() -> None:
    one, other = read_markup(_MOLECULE), read_markup(_MOLECULE)
    one[0].set("id", "changed")
    assert other[0].get("id") == "chain"
    assert ET.tostring(read_markup(_MOLECULE)) == ET.tostring(ET.fromstring(_MOLECULE))
