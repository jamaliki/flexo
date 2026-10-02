"""mol-sketch's style, as a structure takes it, and the part of it the studio offers.

A structure's ``style`` sets any field of mol-sketch's style over its look, nested as
mol-sketch writes them (``fill: ink colour``, ``line: {width: 2}``) -- every field in
mol-sketch's ``python/docs/style.md``. ``SECTIONS`` are those the studio shows, grouped
as that page groups them, each with the choices or range mol-sketch gives it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _choice(
    key: str,
    label: str,
    options: tuple[str, ...],
    hint: str = "",
    *,
    labels: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """A setting with choices: ``options`` are the values mol-sketch takes (what the file
    keeps), ``labels`` what the studio shows for each."""

    field: dict[str, Any] = {
        "key": key,
        "label": label,
        "type": "choice",
        "options": list(options),
        "hint": hint,
    }
    if labels is not None:
        field["labels"] = {option: labels.get(option, option) for option in options}
    return field


def _number(
    key: str,
    label: str,
    *,
    low: float | None = None,
    high: float | None = None,
    step: float | None = None,
    hint: str = "",
) -> dict[str, Any]:
    field: dict[str, Any] = {"key": key, "label": label, "type": "number", "hint": hint}
    limits = (("min", low), ("max", high), ("step", step))
    field |= {name: value for name, value in limits if value is not None}
    return field


def _whole(
    key: str, label: str, *, low: int = 0, high: int | None = None, hint: str = ""
) -> dict[str, Any]:
    return {**_number(key, label, low=low, high=high, step=1, hint=hint), "type": "integer"}


def _share(key: str, label: str, hint: str = "") -> dict[str, Any]:
    """A strength from 0 to 1."""

    return _number(key, label, low=0, high=1, step=0.05, hint=hint)


def _switch(key: str, label: str, hint: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "type": "bool", "hint": hint}


def _colour(key: str, label: str) -> dict[str, Any]:
    return {"key": key, "label": label, "type": "colour", "hint": ""}


def _words(key: str, label: str, hint: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "type": "text", "hint": hint}


FILLS = ("flat", "wash", "pencil", "watercolour", "ink", "ink colour", "chalk")
GROUPS = ("residue", "chain", "subunit", "entity")

FILL_LABELS = {
    "flat": "Flat",
    "wash": "Wash",
    "pencil": "Pencil",
    "watercolour": "Watercolour",
    "ink": "Ink",
    "ink colour": "Ink Colour",
    "chalk": "Chalk",
}
GROUP_LABELS = {"residue": "Residue", "chain": "Chain", "subunit": "Subunit", "entity": "Entity"}
STROKE_LABELS = {"engraved": "Engraved", "sketch": "Sketch"}

SECTIONS: tuple[dict[str, Any], ...] = (
    {
        "title": "Fill and Colour",
        "fields": [
            _choice(
                "fill",
                "Fill",
                FILLS,
                "How shapes are filled. Outlines are always drawn in ink.",
                labels=FILL_LABELS,
            ),
            _choice(
                "color_by",
                "Colour Carbons By",
                ("element", *GROUPS),
                "Other elements keep their element colours",
                labels={"element": "Element", **GROUP_LABELS},
            ),
            _choice(
                "cartoon_color",
                "Colour Cartoon By",
                ("ss", "carbon", "rainbow"),
                "Carbon matches the carbons. Rainbow runs blue to red along each chain.",
                labels={"ss": "Secondary Structure", "carbon": "Carbon", "rainbow": "Rainbow"},
            ),
            _choice(
                "surface_color",
                "Colour Surface By",
                ("single", *GROUPS),
                "Single Colour uses the Surface colour",
                labels={"single": "Single Colour", **GROUP_LABELS},
            ),
            _colour("palette.helix", "Helices"),
            _colour("palette.sheet", "Strands"),
            _colour("palette.loop", "Loops"),
            _colour("palette.nucleic", "Nucleic Acid"),
            _colour("palette.surface", "Surface"),
            _colour("palette.C", "Carbon"),
            _colour("palette.N", "Nitrogen"),
            _colour("palette.O", "Oxygen"),
            _colour("palette.S", "Sulphur"),
            _colour("palette.ink", "Ink"),
            _colour("palette.hatch", "Hatching"),
            _colour("palette.accent", "Accent"),
        ],
    },
    {
        "title": "Representation",
        "fields": [
            _choice(
                "cartoon_style",
                "Ribbon Style",
                ("engraved", "sketch"),
                "Engraved ribbons are shaded with lines; sketched ones use the fill",
                labels=STROKE_LABELS,
            ),
            _number(
                "cartoon_scale",
                "Ribbon Width",
                low=0.1,
                step=0.1,
                hint="A multiple of the normal width",
            ),
            _choice(
                "mode",
                "Atom Style",
                ("sticks", "ballstick"),
                labels={"sticks": "Sticks", "ballstick": "Ball and Stick"},
            ),
            _choice(
                "stick_style",
                "Stick Style",
                ("auto", "engraved", "sketch"),
                "Automatic matches the ribbons",
                labels={"auto": "Automatic", **STROKE_LABELS},
            ),
            _number("stick_radius", "Stick Radius", low=0.02, step=0.02, hint="In ångströms"),
            _number(
                "sphere_scale",
                "Sphere Size",
                low=0,
                step=0.05,
                hint="Balls on Cα atoms; 0 for none",  # noqa: RUF001
            ),
            _number(
                "probe",
                "Probe Radius",
                low=0,
                step=0.1,
                hint="In ångströms; larger is smoother",
            ),
            _switch("side_chain_helper", "Side Chains Only", "Leave backbone atoms to the ribbon"),
            _switch("show.H", "Hydrogens"),
            _switch("show.hbonds", "Hydrogen Bonds"),
            _switch("show.valence", "Double Bonds", "Draw double and triple bonds as such"),
            _switch("construction", "Construction Lines", "Faint pencil lines under the drawing"),
        ],
    },
    {
        "title": "Lines",
        "fields": [
            _number("line.width", "Line Width", low=0, step=0.1),
            _number("line.rough", "Roughness", low=0, step=0.1, hint="0 is perfectly straight"),
            _whole("line.passes", "Passes", low=1, high=6, hint="More passes look more sketched"),
            _share("line.pressure", "Pressure", "How much the width swells and thins in a stroke"),
            _share(
                "line.hierarchy", "Outline Weight", "How much heavier outlines are than inner lines"
            ),
            _number(
                "fill_wobble",
                "Fill Wobble",
                low=0,
                step=0.1,
                hint="How far fills stray from the outline",
            ),
        ],
    },
    {
        "title": "Shading and Hatching",
        "fields": [
            _share("shading", "Shading", "How dark the shadow side is"),
            _number("view.light", "Light Angle", step=5, hint="In degrees; -125 is top left"),
            _number("hatch.spacing", "Hatch Spacing", low=1, step=0.5),
            _number("hatch.angle", "Hatch Angle", step=5, hint="In degrees"),
            _number("hatch.density", "Hatch Density", low=0, step=0.1),
            _share("pencil_fill", "Pencil Density", "For the Pencil fill"),
        ],
    },
    {
        "title": "Surface Depth",
        "fields": [
            _share(
                "surface_depth.edges", "Edges", "Ink edges where one patch is in front of another"
            ),
            _share("surface_depth.pooling", "Pooling", "Grooves hold more shadow"),
            _share("surface_depth.fade", "Fade", "Far patches fade towards the paper"),
        ],
    },
    {
        "title": "Engraved Ribbons",
        "fields": [
            _whole("engrave.lines", "Line Count", low=1, high=24, hint="Lines along each face"),
            _number("engrave.width", "Line Weight", low=0, step=0.05),
            _number(
                "engrave.strand_thickness",
                "Strand Thickness",
                low=0,
                step=0.1,
                hint="In ångströms",
            ),
            _number("engrave.coil_width", "Coil Width", low=0, step=0.05),
            _switch(
                "engrave.labels",
                "Helix and Strand Labels",
                "Name helices and strands α1, β1 …",  # noqa: RUF001
            ),
        ],
    },
    {
        "title": "Active Site",
        "fields": [
            _switch("site.cutaway", "Cutaway", "Open the ribbon in front of the site"),
            _share("site.quiet", "Fade Surroundings", "How much the rest of the protein fades"),
            _number(
                "site.scale",
                "Stick Scale",
                low=0.5,
                step=0.1,
                hint="How much thicker the site's sticks are",
            ),
        ],
    },
    {
        "title": "View and Depth",
        "fields": [
            _number(
                "view.fov",
                "Field of View",
                low=0,
                high=90,
                step=1,
                hint="In degrees; 0 is flat",
            ),
            _share("view.fog", "Fog", "How much the far side fades"),
            _share("view.fog_start", "Fog Start", "As a fraction of the depth"),
        ],
    },
    {
        "title": "Labels",
        "fields": [
            _choice(
                "font",
                "Font",
                ("Caveat", "Patrick Hand", "Kalam", "Plain sans"),
                labels={
                    "Caveat": "Caveat",
                    "Patrick Hand": "Patrick Hand",
                    "Kalam": "Kalam",
                    "Plain sans": "Plain sans",
                },
            ),
            _number("label_size", "Label Size", low=4, step=1),
            _switch("show.res_labels", "Residue Labels", "A label on every residue"),
            _number(
                "annot",
                "Mark Size",
                low=0.2,
                step=0.1,
                hint="Dots, charge circles and arrowheads",
            ),
        ],
    },
    {
        "title": "Density Map",
        "fields": [
            _choice(
                "map.style",
                "Style",
                ("surface", "layers", "mesh", "slice"),
                labels={"surface": "Surface", "layers": "Layers", "mesh": "Mesh", "slice": "Slice"},
            ),
            _number("map.sigma", "Level (σ)", low=0, step=0.5, hint="Above the mean"),  # noqa: RUF001
            _number("map.level", "Level", step=0.01, hint="In the map's units"),
            _choice(
                "map.finish",
                "Finish",
                ("drawn", "smooth", "sketch"),
                labels={"drawn": "Drawn", "smooth": "Smooth", "sketch": "Sketch"},
            ),
            _choice(
                "map.marks",
                "Marks",
                ("ink", "look"),
                "Ink outlines and hatching, or the marks of the look",
                labels={"ink": "Ink", "look": "Look"},
            ),
            _choice(
                "map.layer",
                "Layer",
                ("auto", "behind", "over", "lines"),
                "Where the map is drawn relative to the model",
                labels={
                    "auto": "Automatic",
                    "behind": "Behind",
                    "over": "Over",
                    "lines": "Outline Only",
                },
            ),
            _share("map.shade", "Shading", "0 is outline only"),
            _share("map.opacity", "Opacity", "When drawn over the model"),
            _number(
                "map.carve",
                "Carve Radius",
                low=0,
                step=0.5,
                hint="In ångströms from the model; 0 is off",
            ),
            _words("map.zone", "Close-Up", "A selection, such as resi 57+102"),
            _choice(
                "map.context",
                "Rest of Map",
                ("hide", "show"),
                "Density beyond the model",
                labels={"hide": "Hide", "show": "Show"},
            ),
            _switch(
                "map.caption", "Caption", "A line under the drawing that says how the map is shown"
            ),
        ],
    },
    {
        "title": "Detail",
        "fields": [
            _choice(
                "detail",
                "Detail",
                ("auto", "full"),
                "Automatic simplifies large structures",
                labels={"auto": "Automatic", "full": "Full"},
            ),
            _choice(
                "texture_scale",
                "Texture Scale",
                ("screen", "object"),
                "Object scales the texture with the drawing",
                labels={"screen": "Screen", "object": "Object"},
            ),
        ],
    },
)
"""The settings the studio offers for a structure, grouped as mol-sketch groups them."""

CHOICES: dict[str, tuple[str, ...]] = {
    field["key"]: tuple(field["options"])
    for section in SECTIONS
    for field in section["fields"]
    if field["type"] == "choice"
}
"""The values a setting with choices takes."""
