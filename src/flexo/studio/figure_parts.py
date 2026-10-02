"""What the figure editor offers: every kind of part, what it starts as, and its fields.

The studio's figure page builds its insert palette and its inspector from this
catalogue, so a kind added to flexo is offered by adding an entry here -- the
page has no form of its own for any kind. A field names the key it edits in the
figure file (``label``, ``properties.length``, ``layout.gap``) and how it is
edited:

- ``text``, ``markup`` (flexo's inline markup), ``code`` (monospace, several lines);
- ``integer``, ``number``, ``length`` (``12pt``, ``4mm``), ``bool``;
- ``choice`` (one of ``options``) and ``combo`` (usually one of ``options``);
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


def _field(key: str, label: str, type: str, **options: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "type": type, **options}


def _column(name: str, label: str, type: str = "text", **options: Any) -> dict[str, Any]:
    return {"name": name, "label": label, "type": type, **options}


LABEL = _field("label", "Label", "markup")
TONE = _field(
    "properties.tone",
    "Tone",
    "combo",
    options=list(TONES),
    hint="Parts with the same tone share a colour",
)
BADGE = _field("properties.badge", "Badge", "choice", options=["", *BADGES])
SHADOW = _field("shadow", "Shadow", "bool", default=False)
SIZE = [
    _field("width", "Width", "length", hint="Leave empty to fit the words"),
    _field("height", "Height", "length"),
]
MOTIF = _field(
    "properties.motif",
    "Motif",
    "bool",
    default=True,
    hint="The drawing a kind puts under its words",
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
    strand = _column("strand", "Strand", "choice", options=["", "+", "-"])
    tone = _column("tone", "Tone", "combo", options=list(TONES))
    return [
        _part(
            "construct",
            "Construct",
            "Biology",
            "Parts on a DNA backbone, in SBOL glyphs",
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
                        _column("bp", "bp", "integer"),
                        _column("id", "Port", hint="Name it to connect to this part"),
                    ],
                ),
                _field(
                    "properties.scale",
                    "bp per point",
                    "number",
                    hint="Draw parts to their length in base pairs",
                ),
                _field("properties.ticks", "Ticks", "bool", default=True),
            ],
        ),
        _part(
            "plasmid",
            "Plasmid",
            "Biology",
            "A circular map, features placed by base pair",
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
                _field("properties.ticks", "Ticks", "bool", default=True),
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
            "A protein's domains, sites, and secondary structure along its length",
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
                _field("properties.length", "Length (residues)", "integer", min=1),
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
                        _column("at", "At", "integer", hint="A site's residue"),
                        _column("tone", "Tone", "combo", options=list(TONES)),
                        _column("id", "Port"),
                    ],
                ),
                _field(
                    "properties.tracks",
                    "Tracks",
                    "records",
                    row={"label": "Construct"},
                    hint="Constructs of the protein, one line each",
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
                    "Secondary structure",
                    "code",
                    hint="DSSP letters: H helix, E strand, T turn",
                ),
                _field("properties.secondary_start", "It starts at", "integer", default=1),
                _field("properties.sequence", "Sequence", "code", hint="One-letter codes"),
                _field("properties.sequence_start", "It starts at", "integer", default=1),
                _field(
                    "properties.helix",
                    "Helices",
                    "choice",
                    options=list(HELIX_STYLES),
                    default="ribbon",
                ),
                _field("properties.numbered", "Residue numbers", "bool", default=True),
                _field("properties.scale", "Points per residue", "number"),
                _field("properties.gutter", "Room for track names", "number"),
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
            "A phylogeny from Newick, clades coloured and named",
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
                        _column("tips", "Tips", hint="Two tips that span the clade: A, B"),
                        _column("label", "Label"),
                        tone,
                    ],
                ),
                _field("properties.lengths", "Branch lengths", "bool", default=True),
                _field("properties.support", "Support values", "bool", default=False),
                _field("properties.italic", "Italic names", "bool", default=False),
                _field("properties.scale_bar", "Scale bar", "bool", default=True),
                _field("properties.depth", "Depth", "number"),
            ],
        ),
        _part(
            "wellplate",
            "Plate",
            "Biology",
            "A multiwell plate, its wells grouped by condition",
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
            "A protocol: events on an axis, spans under it",
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
            _field("properties", "View", "view", hint="Or drag the molecule round"),
            _field(
                "properties.look",
                "Look",
                "choice",
                options=["", *LOOKS],
                hint="Empty: the figure's theme chooses",
            ),
            # mol-sketch's own settings: its palettes, colours of one's own, what is
            # drawn, the site, a density map, and every field of its style.
            _field(
                "properties.palette",
                "Palette",
                "molpalette",
                hint="Colours handed to residues and chains in turn",
            ),
            _field(
                "properties.colors",
                "Colours",
                "records",
                row={"group": "A", "color": "#e69f00"},
                columns=[
                    _column("group", "Chain or residue", hint="A, SER195, entity:1, subunit:L"),
                    _column(
                        "color", "Colour", "combo", options=list(TONES), hint="#e69f00 or a tone"
                    ),
                ],
                hint="Win over the palette and the look",
            ),
            _field("properties.cartoon", "Cartoon", "text", hint="As ribbons: polymer", more=True),
            _field(
                "properties.sticks", "Sticks", "text", hint="As sticks: resi 57+102+195", more=True
            ),
            _field(
                "properties.surface", "Surface", "text", hint="A surface over: chain A", more=True
            ),
            _field(
                "properties.site",
                "Site",
                "text",
                hint="Picked out: resi 57+102, or ligand for its pocket",
                more=True,
            ),
            _field(
                "properties.site_within",
                "Pocket reach",
                "number",
                hint="Å round the ligand (5)",
                more=True,
                show={"properties.site": "ligand"},
            ),
            _field("properties.site_labels", "Label the site", "bool", more=True),
            _field(
                "properties.density",
                "Density map",
                "text",
                hint="auto (the entry's), an EMDB ID, or a map file",
                more=True,
            ),
            _field("properties.width", "Width", "number", more=True),
            _field("properties.height", "Height", "number", more=True),
            _field("properties.yaw", "Yaw", "number", hint="Degrees", more=True),
            _field("properties.pitch", "Pitch", "number", hint="Degrees", more=True),
            _field("properties.roll", "Roll", "number", hint="Degrees", more=True),
            _field("properties.zoom", "Zoom", "number", more=True),
            _field("properties.pan_x", "Shift across", "number", hint="Of its box", more=True),
            _field("properties.pan_y", "Shift down", "number", hint="Of its box", more=True),
            _field("properties.style", "Drawing", "molsketch", sections=list(SECTIONS)),
        ],
        needs_file=True,
        unavailable="" if ready else "needs flexo[structures,molecules]",
    )


def _learning() -> list[dict[str, Any]]:
    simple = [
        ("mlp", "MLP", "A multilayer perceptron", "MLP", [MOTIF]),
        ("cnn", "CNN", "A convolutional network", "CNN", [MOTIF]),
        (
            "attention",
            "Attention",
            "Attention, with query, key, and value ports",
            "Attention",
            [MOTIF],
        ),
        ("add-norm", "Add & norm", "A residual sum and a normalisation", "Add + norm", []),
        ("concat", "Concat", "Values joined side by side", "Concat", []),
        ("tensor", "Tensor", "A tensor as a slab", "Tensor", []),
        ("matrix", "Matrix", "A grid of cells", "Matrix", [MOTIF]),
        ("graph", "Graph", "A small graph of nodes and edges", "Graph", [MOTIF]),
        ("inset", "Inset", "A molecule inset", "Molecule", [MOTIF]),
        ("prediction", "Prediction", "What the model outputs", "Prediction", []),
        ("loss", "Loss", "A loss term", "Loss", []),
    ]
    parts = [
        _part(kind, title, "Machine learning", hint, {"label": label}, fields)
        for kind, title, hint, label, fields in simple
    ]
    parts += [
        _part(
            "feature-strip",
            "Features",
            "Machine learning",
            "A strip of feature cells",
            {"label": "Features", "properties": {"cells": 6}},
            [_field("properties.cells", "Cells", "integer", min=1)],
        ),
        _part(
            "sequence",
            "Sequence",
            "Machine learning",
            "Tokens in a row",
            {"label": "Tokens", "properties": {"tokens": 7}},
            [_field("properties.tokens", "Tokens", "integer", min=1)],
        ),
        _part(
            "volume",
            "Volume",
            "Machine learning",
            "A feature map as a block in depth",
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
            "Words on their own: an input, an output, a note",
            {"label": "Text"},
            common=[LABEL],
        ),
        _part(
            "op",
            "Operator",
            "Basics",
            "A sum, product, or other operator in a circle",
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
            "Start / end",
            "Basics",
            "A rounded terminal of a flowchart",
            {"label": "Start"},
        ),
        _part(
            "decision", "Decision", "Basics", "A diamond with a question", {"label": "Decision?"}
        ),
        _part(
            "image",
            "Picture",
            "Basics",
            "A picture or drawing from a file",
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
        "A grid of coloured cells: a map, a heatmap, a board",
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
                hint="One row per line, one cell per word; . leaves a cell empty; "
                "numbers are shaded on the ramp",
            ),
            _field(
                "properties.key",
                "Key",
                "records",
                row={"symbol": "", "label": ""},
                columns=[
                    _column("symbol", "Symbol", hint="The word in the grid"),
                    _column("color", "Colour", "combo", options=list(TONES), hint="A tone or #hex"),
                    _column("mark", "Mark", hint="A small word written in the cell"),
                    _column("label", "Label", hint="Its name in the legend"),
                ],
            ),
            _field("properties.cell", "Cell size", "number", hint="Points"),
            _field("properties.gap", "Gap", "number", hint="A fraction of a cell, 0 to 0.45"),
            _field("properties.corner", "Corners", "number", hint="A fraction of a cell, 0 to 0.5"),
            _field(
                "properties.lines",
                "Lines",
                "combo",
                options=["none", "ink", "muted"],
                hint="none, ink, muted, or a #hex",
            ),
            _field("properties.row_labels", "Row labels", "combo", options=labels),
            _field(
                "properties.row_side",
                "Row labels at",
                "choice",
                options=["left", "right"],
                default="left",
            ),
            _field("properties.column_labels", "Column labels", "combo", options=labels),
            _field(
                "properties.column_side",
                "Column labels at",
                "choice",
                options=["top", "bottom"],
                default="top",
            ),
            _field("properties.ramp", "Ramp", "text", hint="Two #hex, low then high"),
            _field("properties.range", "Range", "text", hint="low, high"),
            _field("properties.values", "Write values", "bool", default=False),
            _field("properties.legend", "Legend", "bool", default=True),
        ],
    )


GROUPS = [
    {"kind": "row", "title": "Row", "hint": "Parts side by side", "layout": "row"},
    {"kind": "column", "title": "Column", "hint": "Parts one under another", "layout": "column"},
    {"kind": "grid", "title": "Grid", "hint": "Parts in rows and columns", "layout": "grid"},
    {
        "kind": "module",
        "title": "Module",
        "hint": "A titled frame around parts",
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
        hint="A module draws a titled frame",
    ),
    SHADOW,
]

EDGE_FIELDS = [
    LABEL,
    _field(
        "arrow", "Arrow", "choice", options=["end", "both", "none", "reversible"], default="end"
    ),
    _field(
        "back_label",
        "Back label",
        "markup",
        show={"arrow": "reversible"},
        hint="The rate written under a reversible step",
    ),
    _field(
        "head",
        "Head",
        "choice",
        options=["arrow", "inhibition", "catalysis", "stimulation", "necessary", "modulation"],
        default="arrow",
        hint="What the head means, after SBGN",
        show={"arrow": ["end", "both"]},
    ),
    _field("line", "Line", "choice", options=["solid", "dashed", "dotted"], default="solid"),
    _field("shape", "Route", "choice", options=["auto", "orthogonal", "straight"], default="auto"),
    _field(
        "cofactors",
        "Cofactors",
        "pair",
        labels=["Taken", "Given"],
        hint="Written on an arc beside the reaction: ATP, ADP",
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


CATEGORIES = ("Basics", "Machine learning", "Biology")


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
