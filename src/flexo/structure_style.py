"""mol-sketch's style, as a structure takes it, and the part of it the studio offers.

A structure's ``style`` sets any field of mol-sketch's style over its look, nested as
mol-sketch writes them (``fill: ink colour``, ``line: {width: 2}``) -- every field in
mol-sketch's ``python/docs/style.md``. ``SECTIONS`` are those the studio shows, grouped
as that page groups them, each with the choices or range mol-sketch gives it.
"""

from __future__ import annotations

from typing import Any


def _choice(key: str, label: str, options: tuple[str, ...], hint: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "type": "choice", "options": list(options), "hint": hint}


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

SECTIONS: tuple[dict[str, Any], ...] = (
    {
        "title": "Fill and colour",
        "fields": [
            _choice("fill", "Fill", FILLS, "How shapes are filled; outlines are always ink"),
            _choice("color_by", "Carbons by", ("element", *GROUPS), "Other elements keep theirs"),
            _choice("cartoon_color", "Cartoon by", ("ss", "carbon", "rainbow"), "ss: by structure"),
            _choice("surface_color", "Surface by", ("single", *GROUPS)),
            _colour("palette.helix", "Helices"),
            _colour("palette.sheet", "Strands"),
            _colour("palette.loop", "Loops"),
            _colour("palette.nucleic", "Nucleic acid"),
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
        "title": "How it is drawn",
        "fields": [
            _choice("cartoon_style", "Ribbons", ("engraved", "sketch"), "Engraved, or in the fill"),
            _number("cartoon_scale", "Ribbon width", low=0.1, step=0.1, hint="× normal"),  # noqa: RUF001
            _choice("mode", "Sticks as", ("sticks", "ballstick")),
            _choice("stick_style", "Stick lines", ("auto", "engraved", "sketch")),
            _number("stick_radius", "Stick radius", low=0.02, step=0.02, hint="Å"),
            _number("sphere_scale", "Spheres", low=0, step=0.05, hint="Cα balls; 0 for none"),  # noqa: RUF001
            _number("probe", "Surface probe", low=0, step=0.1, hint="Å: larger is smoother"),
            _switch("side_chain_helper", "Side chains only", "Backbone left to the ribbon"),
            _switch("show.H", "Hydrogens"),
            _switch("show.hbonds", "H-bonds"),
            _switch("show.valence", "Double bonds"),
            _switch("construction", "Construction", "Faint pencil lines underneath"),
        ],
    },
    {
        "title": "The pen",
        "fields": [
            _number("line.width", "Ink width", low=0, step=0.1),
            _number("line.rough", "Roughness", low=0, step=0.1, hint="0 is ruler-straight"),
            _whole("line.passes", "Passes", low=1, high=6, hint="More look more sketched"),
            _share("line.pressure", "Pressure"),
            _share("line.hierarchy", "Outline weight", "How much heavier outlines are"),
            _number("fill_wobble", "Fill wobble", low=0, step=0.1),
        ],
    },
    {
        "title": "Shading and hatching",
        "fields": [
            _share("shading", "Shading", "How dark the shadow side is"),
            _number("view.light", "Light from", step=5, hint="Degrees round it; -125 is top left"),
            _number("hatch.spacing", "Hatch spacing", low=1, step=0.5),
            _number("hatch.angle", "Hatch angle", step=5, hint="Degrees"),
            _number("hatch.density", "Hatch density", low=0, step=0.1),
            _share("pencil_fill", "Pencil density", "With the pencil fill"),
        ],
    },
    {
        "title": "Surface depth",
        "fields": [
            _share("surface_depth.edges", "Edges", "Ink where a patch stands in front"),
            _share("surface_depth.pooling", "Pooling", "Grooves hold more shadow"),
            _share("surface_depth.fade", "Fade", "Far patches fade to the paper"),
        ],
    },
    {
        "title": "Engraved ribbons",
        "fields": [
            _whole("engrave.lines", "Lines", low=1, high=24, hint="Along each face"),
            _number("engrave.width", "Line weight", low=0, step=0.05),
            _number("engrave.strand_thickness", "Strand edge", low=0, step=0.1, hint="Å"),
            _number("engrave.coil_width", "Coil width", low=0, step=0.05),
            _switch("engrave.labels", "α1, β1 …", "Helices and strands named"),  # noqa: RUF001
        ],
    },
    {
        "title": "Active site",
        "fields": [
            _switch("site.cutaway", "Cut away", "Open the ribbon in front of it"),
            _share("site.quiet", "Quiet the rest", "How much the rest fades"),
            _number("site.scale", "Site sticks", low=0.5, step=0.1, hint="× thicker"),  # noqa: RUF001
        ],
    },
    {
        "title": "View and depth",
        "fields": [
            _number("view.fov", "Field of view", low=0, high=90, step=1, hint="Degrees; 0 is flat"),
            _share("view.fog", "Fog", "How much the far side fades"),
            _share("view.fog_start", "Fog starts", "As a share of the depth"),
        ],
    },
    {
        "title": "Labels and lettering",
        "fields": [
            _choice("font", "Lettering", ("Caveat", "Patrick Hand", "Kalam", "Plain sans")),
            _number("label_size", "Label size", low=4, step=1),
            _switch("show.res_labels", "Every residue", "A label on each"),
            _number("annot", "Marks", low=0.2, step=0.1, hint="Dots, rings, arrow heads"),
        ],
    },
    {
        "title": "Density map",
        "fields": [
            _choice("map.style", "Drawn as", ("surface", "layers", "mesh", "slice")),
            _number("map.sigma", "Level (σ)", low=0, step=0.5, hint="Above the mean"),  # noqa: RUF001
            _number("map.level", "Level", step=0.01, hint="In the map's units"),
            _choice("map.finish", "Finish", ("drawn", "smooth", "sketch")),
            _choice("map.marks", "Marks", ("ink", "look")),
            _choice("map.layer", "Layer", ("auto", "behind", "over", "lines")),
            _share("map.shade", "Shade"),
            _share("map.opacity", "Opacity", "Over the model"),
            _number("map.carve", "Carve to", low=0, step=0.5, hint="Å from the model; 0 off"),
            _words("map.zone", "Close up on", "A selection: resi 57+102"),
            _choice("map.context", "The rest", ("hide", "show")),
            _switch("map.caption", "Caption", "How the map is shown, under it"),
        ],
    },
    {
        "title": "Detail",
        "fields": [
            _choice("detail", "Detail", ("auto", "full"), "Auto: lighter for large structures"),
            _choice(
                "texture_scale", "Texture", ("screen", "object"), "Object: scales with the drawing"
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
