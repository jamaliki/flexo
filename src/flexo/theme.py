"""Paint-only SVG re-theming through stable role metadata."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from flexo.style import Palette
from flexo.svg import SVG_NS


def retheme_svg(svg_text: str, palette: Palette) -> str:
    root = ET.fromstring(svg_text)
    for item in root.iter():
        fill_role = item.get("data-flexo-fill")
        stroke_role = item.get("data-flexo-stroke")
        if fill_role:
            item.set("fill", palette.get(fill_role))
        if stroke_role:
            item.set("stroke", palette.get(stroke_role))
    root.set("data-flexo-palette", palette.name)
    metadata = root.find(f"{{{SVG_NS}}}metadata")
    if metadata is not None and metadata.text:
        try:
            value = json.loads(metadata.text)
            value["palette"] = palette.name
            metadata.text = json.dumps(value, sort_keys=True, separators=(",", ":"))
        except json.JSONDecodeError:
            pass
    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml}\n'
