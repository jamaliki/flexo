"""Paint-only SVG re-theming through stable role metadata."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from flexo.style import Palette
from flexo.svg import SVG_NS, xml_document


def retheme_svg(svg_text: str, palette: Palette) -> str:
    from flexo.themes import with_tone_roles

    palette = with_tone_roles(palette)
    root = ET.fromstring(svg_text)
    for item in root.iter():
        for part in ("fill", "stroke"):
            role = item.get(f"data-flexo-{part}")
            if role:
                item.set(part, _painted(palette, role, item.get(f"data-flexo-{part}-shade")))
    root.set("data-flexo-palette", palette.name)
    metadata = root.find(f"{{{SVG_NS}}}metadata")
    if metadata is not None and metadata.text:
        try:
            value = json.loads(metadata.text)
            value["palette"] = palette.name
            metadata.text = json.dumps(value, sort_keys=True, separators=(",", ":"))
        except json.JSONDecodeError:
            pass
    return xml_document(root)


def _painted(palette: Palette, role: str, shade: str | None) -> str:
    """What ``role`` paints in ``palette``; with a ``shade``, that colour so far toward the
    ink (a flat ribbon's far side, as mol-sketch shades it)."""

    colour = palette.get(role)
    if not shade:
        return colour
    from flexo.colour import srgb_mix

    return srgb_mix(colour, palette.get("ink"), float(shade))
