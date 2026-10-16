"""mol-sketch's style, as a structure takes it, and how the studio lays it out.

A structure's ``style`` sets any field of mol-sketch's style over its look, nested as
mol-sketch writes them (``fill: ink colour``, ``line: {width: 2}``) -- every field in
mol-sketch's ``python/docs/style.md``. ``PANES`` are how the studio offers them, as
mol-sketch's own app does: a pane for the look, the molecule, a scene, the site, a
density map, the labels and the camera, each of sections, each setting with the choices or
range mol-sketch gives it. A section also holds the structure's own fields (its file, what
it draws, its site, its view) where they belong (``_own``: named by key, as the studio's
catalogue of parts has them).

Every field of mol-sketch's style is offered somewhere but those ``NOT_OFFERED`` says
why not: the figure's own (its paper, ``THE_FIGURES``), those the structure's own fields
set, and those that change nothing a figure draws.
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
    unit: str = "",
) -> dict[str, Any]:
    """A number; ``unit`` is shown beside it (Å, °, px, or TIMES, a multiple)."""

    field: dict[str, Any] = {"key": key, "label": label, "type": "number", "hint": hint}
    limits = (("min", low), ("max", high), ("step", step))
    field |= {name: value for name, value in limits if value is not None}
    if unit:
        field["unit"] = unit
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


def _colour(key: str, label: str, hint: str = "", *, group: str = "") -> dict[str, Any]:
    """A colour; ``group`` names the colours it is shown among (Elements)."""

    field = {"key": key, "label": label, "type": "colour", "hint": hint}
    return field | {"group": group} if group else field


def _words(key: str, label: str, hint: str = "", *, mono: bool = False) -> dict[str, Any]:
    """Words typed in; ``mono``, as code (a selection), in the studio's monospace."""

    field = {"key": key, "label": label, "type": "text", "hint": hint}
    return {**field, "mono": True} if mono else field


def _numbers(key: str, label: str, hint: str = "") -> dict[str, Any]:
    """Several numbers, typed with commas between them (``0.7, 1, 1.5``)."""

    return {"key": key, "label": label, "type": "numbers", "hint": hint}


def _own(key: str) -> dict[str, Any]:
    """One of the structure's own fields (``properties.site``), shown here: the studio's
    catalogue of parts says how it is edited."""

    return {"key": key, "own": True}


def _when(field: dict[str, Any], **drawn: object) -> dict[str, Any]:
    """``field``, shown only while the structure is drawn so (``cartoon_style="engraved"``;
    a list, any of them) -- or has a value of its own for it."""

    return field | {"show": {key.replace("__", "."): value for key, value in drawn.items()}}


def _section(
    title: str, fields: tuple[dict[str, Any], ...], *, open: bool = False, needs: str = ""
) -> dict[str, Any]:
    """Settings shown together, folded away unless ``open``; ``needs`` is a field of the
    structure's that the section is shown only once it has (a map's, once there is one)."""

    section: dict[str, Any] = {"title": title, "open": open, "fields": list(fields)}
    return section | {"needs": needs} if needs else section


def _pane(
    key: str, title: str, icon: str, hint: str, sections: tuple[dict[str, Any], ...],
    *, scene: bool | None = None,
) -> dict[str, Any]:
    """A pane, a tab away. ``scene``: shown only for a scene (True), or never for one (False)
    unless something in it is set."""

    pane: dict[str, Any] = {
        "key": key, "title": title, "icon": icon, "hint": hint, "sections": list(sections)
    }
    return pane if scene is None else pane | {"scene": scene}


TIMES = "\u00d7"
"""The unit of a multiple: the multiplication sign."""

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
ENGRAVED = {"cartoon_style": "engraved"}
ON = True

_LOOK = _pane(
    "look",
    "Look",
    "pen",
    "How the whole drawing is drawn: its look, its pen, its hatching and its colours",
    (
        _section(
            "Look",
            (
                _own("properties.look"),
                _own("properties.scheme"),
                _own("properties.palette"),
                _choice(
                    "fill",
                    "Fill",
                    FILLS,
                    "How shapes are filled. Outlines are always drawn in ink.",
                    labels=FILL_LABELS,
                ),
                _share("shading", "Shading", "How dark the shadow side is"),
                _number(
                    "line.width", "Line Width", low=0, step=0.1,
                    hint="On a drawing 1920 wide", unit="px",
                ),
            ),
            open=True,
        ),
        _section(
            "Pen",
            (
                _number("line.rough", "Roughness", low=0, step=0.1, hint="0 is perfectly straight"),
                _whole(
                    "line.passes", "Passes", low=1, high=6, hint="More passes look more sketched"
                ),
                _share(
                    "line.pressure", "Pressure", "How much the width swells and thins in a stroke"
                ),
                _share(
                    "line.hierarchy",
                    "Outline Weight",
                    "How much heavier outlines are than inner lines",
                ),
                _number(
                    "fill_wobble",
                    "Fill Wobble",
                    low=0,
                    step=0.1,
                    hint="How far fills stray from the outline",
                ),
                _when(
                    _share("pencil_fill", "Pencil Density", "How dense the scribbles are"),
                    fill=["pencil", "chalk"],
                ),
                _switch(
                    "construction", "Construction Lines", "Faint pencil lines under the drawing"
                ),
            ),
        ),
        _section(
            "Hatching",
            (
                _number(
                    "hatch.spacing", "Hatch Spacing", low=1, step=0.5,
                    hint="On a drawing 1920 wide", unit="px",
                ),
                _number("hatch.angle", "Hatch Angle", step=5, unit="°"),
                _number(
                    "hatch.density", "Hatch Density", low=0, step=0.1,
                    hint="How much of a shape the hatching covers",
                ),
            ),
        ),
        _section(
            "Colours",
            (
                _colour("palette.helix", "Helices", group="Ribbons and Surface"),
                _colour("palette.sheet", "Strands", group="Ribbons and Surface"),
                _colour("palette.loop", "Loops", group="Ribbons and Surface"),
                _colour("palette.nucleic", "Nucleic Acid", group="Ribbons and Surface"),
                _colour("palette.surface", "Surface", group="Ribbons and Surface"),
                _colour("palette.C", "Carbon", group="Elements"),
                _colour("palette.N", "Nitrogen", group="Elements"),
                _colour("palette.O", "Oxygen", group="Elements"),
                _colour("palette.H", "Hydrogen", group="Elements"),
                _colour("palette.S", "Sulphur", group="Elements"),
                _colour("palette.P", "Phosphorus", group="Elements"),
                _colour("palette.X", "Others", "Any other element", group="Elements"),
                _colour("palette.ink", "Ink", "Outlines and lines", group="Ink and Marks"),
                _colour("palette.hatch", "Hatching", "Hatching and shading", group="Ink and Marks"),
                _colour("palette.accent", "Accent", "Highlights", group="Ink and Marks"),
            ),
        ),
    ),
)

_MOLECULE = _pane(
    "molecule",
    "Molecule",
    "molecule",
    "What is drawn, as what, and in which colours",
    (
        _section(
            "Molecule",
            (
                _own("properties.source"),
                _own("properties.cartoon"),
                _own("properties.sticks"),
                _own("properties.surface"),
                _own("properties.solvent"),
            ),
            open=True,
        ),
        _section(
            "Colour",
            (
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
                _own("properties.colors"),
            ),
            open=True,
        ),
        _section(
            "Cartoon",
            (
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
                    unit=TIMES,
                ),
                _when(
                    _whole(
                        "engrave.lines", "Line Count", low=1, high=24, hint="Lines along each face"
                    ),
                    **ENGRAVED,
                ),
                _when(_number("engrave.width", "Line Weight", low=0, step=0.05), **ENGRAVED),
                _when(
                    _number(
                        "engrave.strand_thickness",
                        "Strand Thickness",
                        low=0,
                        step=0.1,
                        hint="How thick a strand seen side on is",
                        unit="Å",
                    ),
                    **ENGRAVED,
                ),
                _when(
                    _number(
                        "engrave.coil_width", "Coil Width", low=0, step=0.05,
                        hint="The width of coils and loops",
                    ),
                    **ENGRAVED,
                ),
            ),
        ),
        _section(
            "Sticks",
            (
                _choice(
                    "mode",
                    "Atom Style",
                    ("sticks", "ballstick"),
                    labels={"sticks": "Sticks", "ballstick": "Ball and Stick"},
                ),
                _choice(
                    "stick_style",
                    "Stick Style",
                    ("auto", "engraved", "sketch", "flat"),
                    "Automatic matches the ribbons. Flat is PyMOL's: solid colour, round joints",
                    labels={"auto": "Automatic", **STROKE_LABELS, "flat": "Flat"},
                ),
                _when(
                    _choice(
                        "stick_outline",
                        "Stick Outline",
                        ("auto", "on", "off"),
                        "Flat sticks inked round; Automatic when ribbons are drawn",
                        labels={"auto": "Automatic", "on": "On", "off": "Off"},
                    ),
                    stick_style="flat",
                ),
                _number(
                    "stick_radius", "Stick Radius", low=0.02, step=0.02, hint="In ångströms",
                    unit="Å",
                ),
                _number(
                    "stick_h_scale",
                    "Hydrogen Sticks",
                    low=0.1,
                    high=1,
                    step=0.05,
                    hint="A bond to a hydrogen, a share of a stick: a proton reads lighter",
                    unit=TIMES,
                ),
                _number(
                    "sphere_scale",
                    "Sphere Size",
                    low=0,
                    step=0.05,
                    hint="Balls on Cα atoms, a multiple of their size; 0 for none",  # noqa: RUF001
                    unit=TIMES,
                ),
                _switch(
                    "side_chain_helper", "Side Chains Only", "Leave backbone atoms to the ribbon"
                ),
                _switch("show.H", "Hydrogens"),
                _switch(
                    "show.valence",
                    "Double and Triple Bonds",
                    "Each drawn as such, in the sticks of a residue or a ligand",
                ),
                _switch("show.hbonds", "Hydrogen Bonds", "As dotted lines"),
                _colour("palette.hbond", "Hydrogen Bonds", "Their dots"),
            ),
        ),
        _section(
            "Surface",
            (
                _number(
                    "probe",
                    "Probe Radius",
                    low=0,
                    step=0.1,
                    hint="In ångströms; larger is smoother",
                    unit="Å",
                ),
                _share(
                    "surface_depth.edges",
                    "Depth Edges",
                    "Ink edges where one patch is in front of another",
                ),
                _share("surface_depth.pooling", "Pooling", "Grooves hold more shadow"),
                _share("surface_depth.fade", "Fade", "Far patches fade towards the paper"),
            ),
        ),
    ),
)

_SCENE = _pane(
    "scene",
    "Scene",
    "scene",
    "A scene's steps, and the chemistry drawn on it",
    (
        _section("Step", (_own("properties.step"),), open=True),
        _section(
            "Orbitals",
            (
                _switch("show.orbitals", "Orbitals", "A scene\u2019s orbitals, drawn as lobes"),
                _when(
                    _choice(
                        "orbital_style",
                        "Orbital Style",
                        ("auto", "engraved", "sketch"),
                        "Engraved: inked lobes with a ruled tint; Sketch: in the look\u2019s own "
                        "medium",
                        labels={"auto": "Automatic", "engraved": "Engraved", "sketch": "Sketch"},
                    ),
                    show__orbitals=ON,
                ),
                _colour("palette.filled", "Filled Orbitals", "Those holding electrons"),
                _colour("palette.empty", "Empty Orbitals", "Those holding none: σ*, π*"),  # noqa: RUF001
            ),
            open=True,
        ),
        _section(
            "Measures",
            (
                _switch(
                    "show.measures",
                    "Measures",
                    "A scene\u2019s distances, angles and torsions, with their windows",
                ),
                _colour("palette.measure", "Measure Lines", "Their lines and words"),
                _colour("palette.window", "Windows", "What a measure is set in"),
            ),
            open=True,
        ),
        _section(
            "Lone Pairs and Charges",
            (
                _switch("show.lone_pairs", "Lone Pairs"),
                _when(
                    _choice(
                        "lone_pair_style",
                        "Lone Pair Style",
                        ("dots", "bold", "lobes"),
                        "Dots beside the atom, bold dots set off from it, or a lobe holding each "
                        "pair",
                        labels={"dots": "Dots", "bold": "Bold", "lobes": "Lobes"},
                    ),
                    show__lone_pairs=ON,
                ),
                _switch("show.charges", "Charges"),
                _colour("palette.charge", "Charge Signs"),
            ),
            open=True,
        ),
        _section(
            "Arrows and Pocket",
            (
                _switch("show.arrows", "Curly Arrows"),
                _colour("palette.arrow", "Arrows"),
                _colour("palette.context", "Pocket", "The faint pocket behind a scene's site"),
            ),
            open=True,
        ),
    ),
    scene=True,
)

_SITE = _pane(
    "site",
    "Site",
    "site",
    "An active site, drawn out from the rest",
    (
        _section(
            "Site",
            (
                _own("properties.site"),
                _own("properties.site_within"),
                _own("properties.site_labels"),
            ),
            open=True,
        ),
        _section(
            "Emphasis",
            (
                _switch("site.cutaway", "Cutaway", "Open the ribbon in front of the site"),
                _share(
                    "site.quiet", "Fade Surroundings", "How much the rest of the protein fades"
                ),
                _number(
                    "site.scale",
                    "Stick Scale",
                    low=0.5,
                    step=0.1,
                    hint="How much thicker the site's sticks are",
                    unit=TIMES,
                ),
            ),
            open=True,
            needs="properties.site",
        ),
    ),
)

_MAP_STYLES = {"surface": "Surface", "layers": "Layers", "mesh": "Mesh", "slice": "Slice"}
_DENSITY = "properties.density"

_MAP = _pane(
    "map",
    "Map",
    "density",
    "A density map, drawn with the model or on its own",
    (
        _section("Map", (_own(_DENSITY),), open=True),
        _section(
            "Contour",
            (
                # Left empty, the level is the one the map's depositors recommend
                # (``placeholder``: what an empty field means, shown in it when the look gives
                # no value of its own).
                _number(
                    "map.sigma",
                    "Sigma Level",
                    low=0,
                    step=0.5,
                    hint="Standard deviations above the mean",
                    unit="σ",  # noqa: RUF001
                )
                | {"placeholder": "Recommended"},
                _number("map.level", "Absolute Level", step=0.01, hint="In the map's units")
                | {"placeholder": "Recommended"},
                _when(
                    _numbers(
                        "map.levels", "Layer Levels", "Multiples of the level, as 0.7, 1, 1.5"
                    ),
                    map__style="layers",
                ),
            ),
            open=True,
            needs=_DENSITY,
        ),
        _section(
            "Appearance",
            (
                _switch("map.visible", "Show Map", "Drawn, or kept but hidden"),
                _choice("map.style", "Style", tuple(_MAP_STYLES), labels=_MAP_STYLES),
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
                _choice(
                    "map.color",
                    "Colour",
                    ("single", "chain", "model"),
                    "By chain colours the cartoon by chain too",
                    labels={"single": "Single Colour", "chain": "By Chain", "model": "By Model"},
                ),
                _share("map.shade", "Shading", "0 is outline only"),
                _number("map.line_width", "Outline Weight", low=0, step=0.05),
                _when(
                    _share("map.opacity", "Opacity", "When drawn over the model"), map__layer="over"
                ),
                _switch("map.glass", "Glass", "A surface over the model, or alone, drawn as glass"),
                _when(
                    _number(
                        "map.mesh_spacing", "Mesh Spacing", low=0.1, step=0.1,
                        hint="Between the mesh's planes", unit="Å",
                    ),
                    map__style="mesh",
                ),
                _when(
                    _number(
                        "map.slice.offset", "Slice Depth", low=-0.5, high=0.5, step=0.01,
                        hint="A share of the depth, from -0.5 to 0.5",
                    ),
                    map__style="slice",
                ),
                _when(
                    _switch("map.slice.cut", "Cut Away the Front", "What is in front of the slice"),
                    map__style="slice",
                ),
                _colour("map.line", "Outline", "The look's ink unless given"),
            ),
            open=True,
            needs=_DENSITY,
        ),
        _section(
            "Close-Up",
            (
                _words("map.zone", "Close-Up", "A selection, such as resi 57+102", mono=True)
                | {"placeholder": "The whole map"},
                _number(
                    "map.carve",
                    "Carve Radius",
                    low=0,
                    step=0.5,
                    hint="In ångströms from the model; 0 is off",
                    unit="Å",
                ),
            ),
            needs=_DENSITY,
        ),
        _section(
            "Honesty Marks",
            (
                _switch(
                    "map.caption",
                    "Caption",
                    "A line under the drawing that says how the map is shown",
                ),
                _switch(
                    "map.unsupported",
                    "Unsupported Residues",
                    "A small circle on residues mostly outside the density",
                ),
                _switch(
                    "map.unexplained",
                    "Unexplained Density",
                    "Density the model does not explain, in the accent colour",
                ),
                _choice(
                    "map.local_resolution",
                    "Line Looseness",
                    ("none", "bfactor", "map"),
                    "Looser lines where the resolution is worse",
                    labels={"none": "Even", "bfactor": "From B-Factors", "map": "From a Map"},
                ),
            ),
            needs=_DENSITY,
        ),
        _section(
            "Processing",
            (
                _number(
                    "map.smooth", "Low-Pass", low=0, step=1,
                    hint="Smoothed to this many ångströms; 0 for none", unit="Å",
                )
                | {"words": {"auto": "Automatic"}},
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
                _when(
                    _whole(
                        "map.smoothing", "Smoothing Steps", low=0, high=20,
                        hint="Of the surface",
                    ),
                    map__finish=["drawn", "smooth"],
                ),
                _number(
                    "map.speck", "Smallest Speck", low=0, step=1,
                    hint="Smaller islands and holes are left out", unit="px",
                ),
                _number(
                    "map.crop", "Crop Margin", low=0, step=1,
                    hint="Round the model's box", unit="Å",
                ),
                _choice(
                    "map.context",
                    "Rest of Map",
                    ("hide", "show"),
                    "Density beyond the model",
                    labels={"hide": "Hide", "show": "Show"},
                ),
                _whole(
                    "map.max_voxels", "Largest Grid", low=16,
                    hint="Per side: larger maps are averaged down",
                ),
            ),
            needs=_DENSITY,
        ),
    ),
    scene=False,
)

_LABELS = _pane(
    "labels",
    "Labels",
    "tag",
    "The words drawn on the molecule, and how they are lettered",
    (
        _section(
            "Labels",
            (
                _switch("show.res_labels", "Residue Labels", "A label on every residue"),
                _when(
                    _switch(
                        "engrave.labels",
                        "Helix and Strand Labels",
                        "Name helices and strands α1, β1 …",  # noqa: RUF001
                    ),
                    **ENGRAVED,
                ),
                _switch(
                    "show.labels", "Atom Names", "Names a scene gives its atoms, such as His57"
                ),
                _switch(
                    "show.fig_labels", "Placed Labels", "Labels placed on it, such as the site's"
                ),
                _switch("show.no_labels", "Hide Every Label"),
            ),
            open=True,
        ),
        _section(
            "Lettering",
            (
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
                _number(
                    "label_size", "Label Size", low=4, step=1,
                    hint="On a drawing 1920 wide", unit="px",
                ),
                _number(
                    "annot",
                    "Mark Size",
                    low=0.2,
                    step=0.1,
                    hint="Dots, charge circles and arrowheads, a multiple of their size",
                    unit=TIMES,
                ),
                _colour("palette.label", "Labels", "Their words"),
            ),
            open=True,
        ),
    ),
)

_CAMERA = _pane(
    "camera",
    "Camera",
    "camera",
    "How the molecule is turned, framed, lit and drawn in depth",
    (
        _section(
            "View",
            (
                _own("properties.frame"),
                _own("properties"),
                _own("properties.yaw"),
                _own("properties.pitch"),
                _own("properties.roll"),
                _own("properties.zoom"),
                _own("properties.pan_x"),
                _own("properties.pan_y"),
            ),
            open=True,
        ),
        _section(
            "Depth and Light",
            (
                _number(
                    "view.fov",
                    "Field of View",
                    low=0,
                    high=90,
                    step=1,
                    hint="0 is flat",
                    unit="°",
                ),
                _number("view.light", "Light Angle", step=5, hint="-125 is top left", unit="°"),
                _share("view.fog", "Fog", "How much the far side fades"),
                _share("view.fog_start", "Fog Start", "As a fraction of the depth"),
            ),
            open=True,
        ),
        _section("Size", (_own("properties.width"), _own("properties.height"))),
        _section(
            "Detail",
            (
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
            ),
        ),
    ),
)

PANES: tuple[dict[str, Any], ...] = (_LOOK, _MOLECULE, _SCENE, _SITE, _MAP, _LABELS, _CAMERA)
"""How the studio lays out a structure's settings: its panes, each a tab away, of
sections."""

SECTIONS: tuple[dict[str, Any], ...] = tuple(
    {**section, "pane": pane["key"], "fields": [f for f in section["fields"] if not f.get("own")]}
    for pane in PANES
    for section in pane["sections"]
    if any(not field.get("own") for field in section["fields"])
)
"""Each section of mol-sketch's settings the studio offers, with its pane's key: its own
fields left out."""

CHOICES: dict[str, tuple[str, ...]] = {
    field["key"]: tuple(field["options"])
    for section in SECTIONS
    for field in section["fields"]
    if field["type"] == "choice"
}
"""The values a setting with choices takes."""

THE_FIGURES: dict[str, object] = {
    "paper.grain": 0,
    "paper.wash": 0,
    "show.caption": False,
    "show.step_label": False,
}
"""Settings the figure gives every structure it draws, over its look: the figure's page
is the paper, plain (its colour is ``palette.paper``, the figure's too), and the figure
names the panel itself -- a scene's own caption and step title are the app's."""

_FIGURE = "The figure's own: "
_SET = "Set by the structure's "
_PREVIEW = "Only mol-sketch's live preview draws with it: a drawing is the same either way"

NOT_OFFERED: dict[str, str] = {
    "palette.paper": _FIGURE + "its page is the paper, taken out round the molecule",
    "paper.grain": _FIGURE + "the paper is plain",
    "paper.wash": _FIGURE + "the paper is plain",
    "paper.wash_seed": _FIGURE + "the paper has no wash, whose pattern this picks",
    "paper.wash_life": _FIGURE + "the paper has no wash, which this changes as it moves",
    "palette.wash": _FIGURE + "the paper has no wash, which this colours",
    "paper.transparent": _FIGURE + "the paper is always taken out, its colour kept for the fog",
    "show.caption": _FIGURE + "it names the panel itself",
    "show.step_label": _FIGURE + "it names the panel itself",
    "caption_size": _FIGURE + "the scene's caption and step title it leaves out are its size",
    "reps.cartoon": _SET + "Cartoon",
    "reps.sticks": _SET + "Sticks",
    "reps.surface": _SET + "Surface",
    "site.sel": _SET + "Site",
    "group_palette": _SET + "Palette",
    "group_palette_name": _SET + "Palette",
    "water.layers": _PREVIEW,
    "water.wobble": _PREVIEW,
    "water.ring": _PREVIEW,
    "water.granulation": _PREVIEW,
    "water.tone": _PREVIEW,
    "line.alpha": _PREVIEW,
    "paper.wash_scale": _PREVIEW,
    "boil_every": _PREVIEW,
    "boil_hold": "An animation's: how many drawings keep one wobble, where a structure is one",
}
"""Every field of mol-sketch's style the studio does not offer, and why: the figure's own
(``THE_FIGURES``, its paper), those the structure's own fields set, and those that change
nothing a figure draws."""
