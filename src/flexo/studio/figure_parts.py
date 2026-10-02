"""What the figure editor offers: every kind of part, what it starts as, and its fields.

The studio's figure page builds its insert palette and its inspector from this
catalogue, so a kind added to flexo is offered by adding an entry here -- the
page has no form of its own for any kind. A field names the key it edits in the
figure file (``label``, ``properties.length``, ``layout.gap``) and how it is
edited:

- ``text``, ``markup`` (flexo's inline markup), ``code`` (monospace, several lines);
- ``integer``, ``number``, ``length`` (``12pt``, ``4mm``), ``bool``;
- ``choice`` (one of ``options``, each shown as ``labels`` names it) and ``combo``
  (usually one of ``options``);
- ``records``: a table of rows, each a mapping with the given ``columns`` -- a
  plasmid's features, a plate's groups, a timeline's events;
- ``pair``: two words kept as a list of two (a reaction's cofactors);
- ``file``: a file beside the figure, of the given ``types`` (the studio's: ``image``,
  ``structure``);
- ``view``: a molecule's ``properties.yaw``, ``pitch``, and ``zoom``, changed a step
  at a time by buttons, as one turns a molecule in a viewer.

A field may carry a ``default`` (what the kind does when the key is absent),
``more`` (shown folded away, under the rest, for those who look for it),
``show`` (``{"key": value}`` or ``{"key": [values]}``: shown only while another key
has that value), and ``hint``. A ``records`` field's ``row`` is what a new row
starts as; ``"+N"`` is the last row's value and N more.
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib.util import find_spec
from typing import Any

TONES = (
    "encoder",
    "decoder",
    "embedding",
    "attention",
    "norm",
    "mlp",
    "cnn",
    "data",
    "model",
    "head",
    "output",
    "frozen",
    "neutral",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
)
"""Tones people reach for; any name works, and each new name takes the next colour."""

BADGES = ("frozen", "trained", "tuned")


SMALL_WORDS = frozenset(
    {"a", "an", "the", "and", "or", "but", "nor", "as", "at", "by", "for", "from", "in", "into"}
    | {"like", "near", "of", "on", "onto", "over", "per", "to", "upon", "via", "with"}
)
"""Words title-style leaves lowercase, unless they come first or last."""

WORDS = {
    "": "None",
    "auto": "Automatic",
    "cds": "CDS",
    "rbs": "RBS",
    "tm": "TM",
    "310-helix": "3-10 Helix",
    "center": "Centre",
}
"""Values shown otherwise than title-cased."""


def _labels(options: list[Any], special: Mapping[str, str] | None = None) -> dict[str, str]:
    """What the studio shows for each of a choice's ``options`` (the values written to the
    file): ``special``'s word for it, else the value in title-style (``active-site``:
    Active Site)."""

    def titled(value: str) -> str:
        words = value.replace("-", " ").replace("_", " ").split()
        last = len(words) - 1
        return " ".join(
            word if 0 < index < last and word in SMALL_WORDS else word[:1].upper() + word[1:]
            for index, word in enumerate(words)
        )

    said = {**WORDS, **(special or {})}
    return {str(option): said.get(str(option)) or titled(str(option)) for option in options}


def _field(key: str, label: str, type: str, **options: Any) -> dict[str, Any]:
    """A field; a ``choice`` field also carries ``labels``, what is shown for each option
    (given ``labels`` say it for some)."""

    if type == "choice":
        options["labels"] = _labels(options["options"], options.get("labels"))
    return {"key": key, "label": label, "type": type, **options}


def _column(name: str, label: str, type: str = "text", **options: Any) -> dict[str, Any]:
    if type == "choice":
        options["labels"] = _labels(options["options"], options.get("labels"))
    return {"name": name, "label": label, "type": type, **options}


LABEL = _field("label", "Label", "markup")
TONE = _field(
    "properties.tone",
    "Tone",
    "combo",
    options=list(TONES),
    hint="Shapes with the same tone share a colour",
)
BADGE = _field("properties.badge", "Badge", "choice", options=["", *BADGES])
SHADOW = _field("shadow", "Shadow", "bool", default=False)
SIZE = [
    _field("width", "Width", "length", hint="Leave empty to fit the label"),
    _field("height", "Height", "length"),
]
MOTIF = _field(
    "properties.motif",
    "Motif",
    "bool",
    default=True,
    hint="The drawing behind the label",
)
COMMON = [LABEL, TONE, BADGE, SHADOW]


def _part(
    kind: str,
    title: str,
    category: str,
    hint: str,
    node: dict[str, Any] | None = None,
    fields: list[dict[str, Any]] | None = None,
    *,
    common: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "title": title,
        "category": category,
        "hint": hint,
        "node": {"kind": kind, **(node or {})},
        "fields": [*(COMMON if common is None else common), *(fields or [])],
        **extra,
    }


def _genetics() -> list[dict[str, Any]]:
    from flexo.genetics import _PLASMID_PARTS, PART_TYPES

    glyphs = sorted(set(PART_TYPES.values()))
    strand = _column(
        "strand",
        "Strand",
        "choice",
        options=["", "+", "-"],
        labels={"": "Default", "+": "Forward", "-": "Reverse"},
    )
    tone = _column("tone", "Tone", "combo", options=list(TONES))
    return [
        _part(
            "construct",
            "Construct",
            "Biology",
            "Genetic parts on a DNA backbone, drawn as SBOL glyphs",
            {
                "label": "Reporter",
                "properties": {
                    "parts": [
                        {"type": "promoter", "label": "pTet"},
                        {"type": "rbs", "label": "RBS"},
                        {"type": "cds", "label": "GFP"},
                        {"type": "terminator", "label": "T1"},
                    ]
                },
            },
            [
                _field(
                    "properties.parts",
                    "Parts",
                    "records",
                    row={"type": "cds", "label": "Gene"},
                    columns=[
                        _column("type", "Type", "choice", options=glyphs),
                        _column("label", "Label"),
                        strand,
                        tone,
                        _column("bp", "Length", "integer", hint="In base pairs"),
                        _column("id", "Port", hint="Name to connect lines to"),
                    ],
                ),
                _field(
                    "properties.scale",
                    "Base Pairs per Point",
                    "number",
                    hint="Draws parts to scale by their length",
                ),
                _field("properties.ticks", "Show ticks", "bool", default=True),
            ],
        ),
        _part(
            "plasmid",
            "Plasmid",
            "Biology",
            "A circular plasmid map with features placed by base pair",
            {
                "label": "pExample",
                "properties": {
                    "length": 3000,
                    "features": [
                        {"type": "promoter", "label": "pLac", "start": 120, "end": 200},
                        {"type": "cds", "label": "GFP", "start": 220, "end": 940},
                        {"type": "origin", "label": "ColE1", "start": 1400, "end": 1990},
                        {"type": "cds", "label": "AmpR", "start": 2100, "end": 2960, "strand": "-"},
                    ],
                },
            },
            [
                _field("properties.length", "Length (bp)", "integer", min=1),
                _field(
                    "properties.features",
                    "Features",
                    "records",
                    row={"type": "cds", "label": "Gene", "start": "+300", "end": "+300"},
                    columns=[
                        _column("type", "Type", "choice", options=sorted(_PLASMID_PARTS)),
                        _column("label", "Label"),
                        _column("start", "Start", "integer"),
                        _column("end", "End", "integer"),
                        strand,
                        tone,
                    ],
                ),
                _field("properties.radius", "Radius", "number"),
                _field("properties.ticks", "Show ticks", "bool", default=True),
            ],
        ),
    ]


def _proteins() -> list[dict[str, Any]]:
    from flexo.proteins import FEATURE_TYPES
    from flexo.secondary import HELIX_STYLES

    kinds = [
        "domain",
        "region",
        "motif",
        "transmembrane",
        "signal",
        "helix",
        "strand",
        "turn",
        "mutation",
        "phosphorylation",
        "glycosylation",
        "active-site",
        "binding-site",
        "site",
        "disulfide",
    ]
    kinds += sorted(set(FEATURE_TYPES) - set(kinds))
    return [
        _part(
            "protein",
            "Protein",
            "Biology",
            "Domains, sites and secondary structure along a protein",
            {
                "label": "Kinase",
                "properties": {
                    "length": 420,
                    "features": [
                        {"type": "domain", "label": "SH3", "start": 20, "end": 80},
                        {"type": "domain", "label": "SH2", "start": 95, "end": 185},
                        {"type": "domain", "label": "Kinase", "start": 220, "end": 400},
                        {"type": "mutation", "label": "T315I", "at": 315},
                    ],
                },
            },
            [
                _field("properties.length", "Length (Residues)", "integer", min=1),
                _field(
                    "properties.features",
                    "Features",
                    "records",
                    row={"type": "domain", "label": "Domain", "start": "+60", "end": "+60"},
                    columns=[
                        _column("type", "Type", "choice", options=kinds),
                        _column("label", "Label"),
                        _column("start", "Start", "integer"),
                        _column("end", "End", "integer"),
                        _column("at", "At", "integer", hint="The residue of a single site"),
                        _column("tone", "Tone", "combo", options=list(TONES)),
                        _column("id", "Port"),
                    ],
                ),
                _field(
                    "properties.tracks",
                    "Tracks",
                    "records",
                    row={"label": "Construct"},
                    hint="One line per construct of the protein",
                    columns=[
                        _column("label", "Label"),
                        _column("start", "Start", "integer"),
                        _column("end", "End", "integer"),
                        _column("delete", "Deleted", hint="61-121"),
                        _column("id", "Port"),
                    ],
                ),
                _field(
                    "properties.secondary",
                    "Secondary Structure",
                    "code",
                    hint="DSSP letters: H helix, E strand, T turn",
                ),
                _field("properties.secondary_start", "First Residue", "integer", default=1),
                _field("properties.sequence", "Sequence", "code", hint="One-letter codes"),
                _field("properties.sequence_start", "First Residue", "integer", default=1),
                _field(
                    "properties.helix",
                    "Helix Style",
                    "choice",
                    options=list(HELIX_STYLES),
                    default="ribbon",
                ),
                _field("properties.numbered", "Show residue numbers", "bool", default=True),
                _field("properties.scale", "Points per Residue", "number"),
                _field("properties.gutter", "Track Name Width", "number"),
            ],
        ),
    ]


def _bench() -> list[dict[str, Any]]:
    from flexo.bench import PLATES

    tone = _column("tone", "Tone", "combo", options=list(TONES))
    return [
        _part(
            "tree",
            "Tree",
            "Biology",
            "A phylogenetic tree from Newick, with coloured, labelled clades",
            {
                "label": "Primates",
                "properties": {
                    "newick": "(((Human:0.08,Chimpanzee:0.09):0.12,Gorilla:0.21):0.25,"
                    "Orangutan:0.45);",
                },
            },
            [
                _field("properties.newick", "Newick", "code"),
                _field(
                    "properties.layout",
                    "Layout",
                    "choice",
                    options=["rectangular", "circular"],
                    default="rectangular",
                ),
                _field(
                    "properties.clades",
                    "Clades",
                    "records",
                    row={"label": "Clade"},
                    columns=[
                        _column("tips", "Tips", hint="Two tips spanning the clade: A, B"),
                        _column("label", "Label"),
                        tone,
                    ],
                ),
                _field("properties.lengths", "Show branch lengths", "bool", default=True),
                _field("properties.support", "Show support values", "bool", default=False),
                _field("properties.italic", "Italic tip names", "bool", default=False),
                _field("properties.scale_bar", "Show scale bar", "bool", default=True),
                _field("properties.depth", "Depth", "number"),
            ],
        ),
        _part(
            "wellplate",
            "Plate",
            "Biology",
            "A multiwell plate with wells grouped by condition",
            {
                "label": "Plate layout",
                "properties": {
                    "wells": 96,
                    "groups": [
                        {"wells": "A1-A12", "label": "Control"},
                        {"wells": "B-D", "label": "Treated"},
                    ],
                },
            },
            [
                _field("properties.wells", "Wells", "choice", options=sorted(PLATES)),
                _field(
                    "properties.groups",
                    "Groups",
                    "records",
                    row={"wells": "", "label": "Group"},
                    columns=[
                        _column("wells", "Wells", hint="A1, B1-D6, C, 7"),
                        _column("label", "Label"),
                        tone,
                    ],
                ),
            ],
        ),
        _part(
            "timeline",
            "Timeline",
            "Biology",
            "Protocol events on an axis, with spans below",
            {
                "label": "Protocol",
                "properties": {
                    "events": [
                        {"at": 0, "label": "Seed"},
                        {"at": 1, "label": "Treat"},
                        {"at": 3, "label": "Harvest"},
                    ],
                    "spans": [{"start": 1, "end": 3, "label": "Drug"}],
                    "unit": "day",
                },
            },
            [
                _field(
                    "properties.events",
                    "Events",
                    "records",
                    row={"at": "+1", "label": "Event"},
                    columns=[
                        _column("at", "At", "number"),
                        _column("label", "Label"),
                        tone,
                        _column("id", "Port"),
                    ],
                ),
                _field(
                    "properties.spans",
                    "Spans",
                    "records",
                    row={"start": "+1", "end": "+1", "label": "Span"},
                    columns=[
                        _column("start", "Start", "number"),
                        _column("end", "End", "number"),
                        _column("label", "Label"),
                        tone,
                    ],
                ),
                _field(
                    "properties.unit",
                    "Unit",
                    "combo",
                    options=["", "s", "min", "h", "day", "week", "month", "year"],
                ),
                _field("properties.length", "Length", "number"),
            ],
        ),
    ]


def _structure() -> dict[str, Any]:
    from flexo.structure_style import SECTIONS
    from flexo.structures import LOOKS

    ready = find_spec("molsketch") is not None and find_spec("gemmi") is not None
    return _part(
        "structure",
        "Structure",
        "Biology",
        "A PDB or mmCIF structure drawn by mol-sketch",
        {"label": "Structure", "properties": {"source": ""}},
        [
            _field("properties.source", "File", "file", types=["structure"]),
            _field("properties", "View", "view", hint="Or drag the molecule to rotate it"),
            _field(
                "properties.look",
                "Look",
                "choice",
                options=["", *LOOKS],
                labels={"": "Default"},
                hint="Default uses the figure's theme",
            ),
            # mol-sketch's own settings: its palettes, colours of one's own, what is
            # drawn, the site, a density map, and every field of its style.
            _field(
                "properties.palette",
                "Palette",
                "molpalette",
                hint="Colours given to residues and chains in turn",
            ),
            _field(
                "properties.colors",
                "Colours",
                "records",
                row={"group": "A", "color": "#e69f00"},
                columns=[
                    _column("group", "Chain or Residue", hint="A, SER195, entity:1, subunit:L"),
                    _column(
                        "color", "Colour", "combo", options=list(TONES), hint="#e69f00 or a tone"
                    ),
                ],
                hint="These override the palette and the look",
            ),
            _field(
                "properties.cartoon", "Cartoon", "text", hint="Drawn as ribbons: polymer", more=True
            ),
            _field(
                "properties.sticks",
                "Sticks",
                "text",
                hint="Drawn as sticks: resi 57+102+195",
                more=True,
            ),
            _field(
                "properties.surface",
                "Surface",
                "text",
                hint="Drawn as a surface: chain A",
                more=True,
            ),
            _field(
                "properties.site",
                "Site",
                "text",
                hint="Highlighted: resi 57+102, or ligand for its pocket",
                more=True,
            ),
            _field(
                "properties.site_within",
                "Pocket Radius",
                "number",
                hint="In ångströms around the ligand (default 5)",
                more=True,
                show={"properties.site": "ligand"},
            ),
            _field("properties.site_labels", "Label site residues", "bool", more=True),
            _field(
                "properties.density",
                "Density Map",
                "text",
                hint="auto for the entry's own map, an EMDB ID, or a map file",
                more=True,
            ),
            _field("properties.width", "Width", "number", more=True),
            _field("properties.height", "Height", "number", more=True),
            _field("properties.yaw", "Yaw", "number", hint="In degrees", more=True),
            _field("properties.pitch", "Pitch", "number", hint="In degrees", more=True),
            _field("properties.roll", "Roll", "number", hint="In degrees", more=True),
            _field("properties.zoom", "Zoom", "number", more=True),
            _field(
                "properties.pan_x", "Offset X", "number", hint="A fraction of the frame", more=True
            ),
            _field(
                "properties.pan_y", "Offset Y", "number", hint="A fraction of the frame", more=True
            ),
            _field("properties.style", "Rendering", "molsketch", sections=list(SECTIONS)),
        ],
        needs_file=True,
        unavailable="" if ready else "Requires flexo[structures,molecules]",
    )


def _learning() -> list[dict[str, Any]]:
    simple = [
        ("mlp", "MLP", "A multilayer perceptron", "MLP", [MOTIF]),
        ("cnn", "CNN", "A convolutional network", "CNN", [MOTIF]),
        (
            "attention",
            "Attention",
            "Attention with query, key and value ports",
            "Attention",
            [MOTIF],
        ),
        ("add-norm", "Add & Norm", "A residual sum followed by normalisation", "Add + norm", []),
        ("concat", "Concat", "Values concatenated side by side", "Concat", []),
        ("tensor", "Tensor", "A tensor drawn as a slab", "Tensor", []),
        ("matrix", "Matrix", "A grid of cells", "Matrix", [MOTIF]),
        ("graph", "Graph", "A small graph of nodes and edges", "Graph", [MOTIF]),
        ("inset", "Inset", "A molecule inset", "Molecule", [MOTIF]),
        ("prediction", "Prediction", "The output of a model", "Prediction", []),
        ("loss", "Loss", "A loss term", "Loss", []),
    ]
    parts = [
        _part(kind, title, "Machine Learning", hint, {"label": label}, fields)
        for kind, title, hint, label, fields in simple
    ]
    parts += [
        _part(
            "feature-strip",
            "Features",
            "Machine Learning",
            "A strip of feature cells",
            {"label": "Features", "properties": {"cells": 6}},
            [_field("properties.cells", "Cells", "integer", min=1)],
        ),
        _part(
            "sequence",
            "Sequence",
            "Machine Learning",
            "A row of tokens",
            {"label": "Tokens", "properties": {"tokens": 7}},
            [_field("properties.tokens", "Tokens", "integer", min=1)],
        ),
        _part(
            "volume",
            "Volume",
            "Machine Learning",
            "A feature map drawn as a 3D block",
            {"properties": {"channels": 16, "height": 32, "width": 32}},
            [
                _field("properties.channels", "Channels", "integer", min=1),
                _field("properties.height", "Height", "integer", min=1),
                _field("properties.width", "Width", "integer", min=1),
            ],
            common=[TONE, SHADOW],
        ),
    ]
    return parts


def _basics() -> list[dict[str, Any]]:
    return [
        _part("block", "Block", "Basics", "A labelled box", {"label": "Block"}, SIZE),
        _part(
            "text",
            "Text",
            "Basics",
            "Text without a box, such as an input, output or note",
            {"label": "Text"},
            common=[LABEL],
        ),
        _part(
            "op",
            "Operator",
            "Basics",
            "A sum, product or other operator in a circle",
            {"properties": {"symbol": "+"}},
            [
                _field(
                    "properties.symbol",
                    "Symbol",
                    "combo",
                    options=[
                        "+",
                        "\N{MULTIPLICATION SIGN}",
                        "\N{MIDDLE DOT}",
                        "\N{MINUS SIGN}",
                        "~",
                        "\N{GREEK SMALL LETTER SIGMA}",
                    ],
                )
            ],
            common=[TONE],
        ),
        _part(
            "circle",
            "Circle",
            "Basics",
            "A variable in a circle, as in a graphical model",
            {"label": "$z$"},
            [_field("properties.shaded", "Shaded", "bool", default=False)],
        ),
        _part(
            "terminal",
            "Start/End",
            "Basics",
            "A rounded start or end of a flowchart",
            {"label": "Start"},
        ),
        _part("decision", "Decision", "Basics", "A diamond for a decision", {"label": "Decision?"}),
        _part(
            "image",
            "Picture",
            "Basics",
            "An image or drawing from a file",
            {"properties": {"source": ""}},
            [_field("properties.source", "File", "file", types=["image"]), *SIZE],
            common=[LABEL],
            needs_file=True,
        ),
        _part("junction", "Junction", "Basics", "A point where lines meet", common=[]),
        _cells(),
    ]


def _cells() -> dict[str, Any]:
    """A grid of cells: a board, a plate map, a heatmap, a number square."""

    labels = ["", "numbers", "letters"]
    return _part(
        "cells",
        "Cells",
        "Basics",
        "A grid of coloured cells, such as a plate map, heatmap or board",
        {
            "label": "Grid",
            "properties": {
                "grid": "A B A B\nB A B A\nA B A B",
                "key": [{"symbol": "A", "label": "First"}, {"symbol": "B", "label": "Second"}],
            },
        },
        [
            _field(
                "properties.grid",
                "Grid",
                "code",
                hint="One row per line and one cell per word. A dot leaves a cell empty; "
                "numbers are shaded on the ramp.",
            ),
            _field(
                "properties.key",
                "Key",
                "records",
                row={"symbol": "", "label": ""},
                columns=[
                    _column("symbol", "Symbol", hint="As written in the grid"),
                    _column("color", "Colour", "combo", options=list(TONES), hint="A tone or #hex"),
                    _column("mark", "Mark", hint="Short text in the cell"),
                    _column("label", "Label", hint="Name in the legend"),
                ],
            ),
            _field("properties.cell", "Cell Size", "number", hint="In points"),
            _field("properties.gap", "Gap", "number", hint="A fraction of a cell, 0 to 0.45"),
            _field(
                "properties.corner",
                "Corner Radius",
                "number",
                hint="A fraction of a cell, 0 to 0.5",
            ),
            _field(
                "properties.lines",
                "Grid Lines",
                "combo",
                options=["none", "ink", "muted"],
                hint="none, ink, muted, or a hex colour",
            ),
            _field("properties.row_labels", "Row Labels", "combo", options=labels),
            _field(
                "properties.row_side",
                "Row Label Position",
                "choice",
                options=["left", "right"],
                default="left",
            ),
            _field("properties.column_labels", "Column Labels", "combo", options=labels),
            _field(
                "properties.column_side",
                "Column Label Position",
                "choice",
                options=["top", "bottom"],
                default="top",
            ),
            _field("properties.ramp", "Ramp", "text", hint="Two hex colours, low then high"),
            _field("properties.range", "Range", "text", hint="Low, high"),
            _field("properties.values", "Show values", "bool", default=False),
            _field("properties.legend", "Show legend", "bool", default=True),
        ],
    )


GROUPS = [
    {"kind": "row", "title": "Row", "hint": "Shapes side by side", "layout": "row"},
    {"kind": "column", "title": "Column", "hint": "Shapes stacked vertically", "layout": "column"},
    {"kind": "grid", "title": "Grid", "hint": "Shapes in rows and columns", "layout": "grid"},
    {
        "kind": "module",
        "title": "Module",
        "hint": "A titled frame around shapes",
        "layout": "row",
        "role": "module",
    },
]
"""What parts can be gathered into; each takes the parts chosen, or a first block."""

GROUP_FIELDS = [
    LABEL,
    _field(
        "layout.kind",
        "Layout",
        "choice",
        options=["row", "column", "grid", "flow", "flow-right", "stack", "overlay", "cycle"],
    ),
    _field("layout.columns", "Columns", "integer", min=1, show={"layout.kind": "grid"}),
    _field("layout.gap", "Gap", "length"),
    _field(
        "layout.align",
        "Align",
        "choice",
        options=["auto", "start", "center", "end", "stretch", "ports"],
        labels={"ports": "To Ports"},
        default="auto",
    ),
    _field(
        "layout.justify",
        "Justify",
        "choice",
        options=["start", "center", "end", "space-between"],
        default="start",
    ),
    _field(
        "role",
        "Frame",
        "choice",
        options=["container", "module"],
        default="container",
        hint="A module draws a titled frame around its shapes",
    ),
    SHADOW,
]

EDGE_FIELDS = [
    LABEL,
    _field(
        "arrow",
        "Arrow",
        "choice",
        options=["end", "both", "none", "reversible"],
        labels={"both": "Both Ends"},
        default="end",
    ),
    _field(
        "back_label",
        "Back Label",
        "markup",
        show={"arrow": "reversible"},
        hint="The rate shown under a reversible step",
    ),
    _field(
        "head",
        "Arrowhead",
        "choice",
        options=["arrow", "inhibition", "catalysis", "stimulation", "necessary", "modulation"],
        labels={"necessary": "Necessary Stimulation"},
        default="arrow",
        hint="What the arrowhead means, as in SBGN",
        show={"arrow": ["end", "both"]},
    ),
    _field("line", "Line Style", "choice", options=["solid", "dashed", "dotted"], default="solid"),
    _field(
        "shape", "Routing", "choice", options=["auto", "orthogonal", "straight"], default="auto"
    ),
    _field(
        "cofactors",
        "Cofactors",
        "pair",
        labels=["Consumed", "Produced"],
        hint="Shown on an arc beside the reaction: ATP, ADP",
    ),
]


def figure_fields(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _field("figure.id", "Name", "text"),
        _field(
            "figure.style", "Theme", "theme", options=catalog.get("themes", []), default="paper"
        ),
        _field(
            "figure.palette",
            "Palette",
            "palette",
            options=["default", *sorted(catalog.get("palettes", {}))],
            colours=catalog.get("palettes", {}),
            default="default",
        ),
        _field(
            "figure.width",
            "Width",
            "combo",
            options=["single-column", "double-column", "120mm", "180mm"],
            default="double-column",
        ),
        _field("figure.font", "Font", "combo", options=catalog.get("fonts", [])),
    ]


CATEGORIES = ("Basics", "Machine Learning", "Biology")


def catalogue(catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """The editor's catalogue: parts by category, groups, and the fields of each thing."""

    parts = [*_basics(), *_learning(), *_genetics(), *_proteins(), *_bench(), _structure()]
    return {
        "categories": list(CATEGORIES),
        "parts": {part["kind"]: part for part in parts},
        "groups": GROUPS,
        "group_fields": GROUP_FIELDS,
        "edge_fields": EDGE_FIELDS,
        "figure_fields": figure_fields(catalog or {}),
    }
