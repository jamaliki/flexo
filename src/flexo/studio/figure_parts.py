"""What the figure editor offers: every kind of part, what it starts as, and its fields.

The studio's figure page builds its insert palette and its inspector from this
catalogue, so a kind added to flexo is offered by adding an entry here -- the
page has no form of its own for any kind. A part's ``words`` are what else people
call it ("cylinder", "storage" and "DB" for a database), which the palette's search
finds it by as well as by its title and hint. A field names the key it edits in the
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

A ``records`` column is edited as a field of the same type is, or as a ``chain`` (one of
the structure's chains, offered from a menu; residues and the like typed) or a ``colour``
(a colour well, or one of ``options``, a tone, typed).

A field may carry a ``default`` (what the kind does when the key is absent),
``more`` (shown folded away, under the rest, for those who look for it),
``show`` (``{"key": value}`` or ``{"key": [values]}``: shown only while another key
has that value), and ``hint``. A ``records`` field's ``row`` is what a new row
starts as; ``"+N"`` is the last row's value and N more, and ``"@chain"`` a chain of the
structure's that no row names yet.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from importlib.util import find_spec
from typing import Any

from flexo.ir.semantic import EDGE_HEADS

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


def _attach() -> dict[str, Any]:
    """A row's name for lines to end at (a feature's, a part's): said as what it does."""

    title = "A name lines are drawn to, to end at this one"
    return _column("id", "Attach At", hint="a name", title=title)


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
            # One part with no name to start from (a construct of none can't be drawn), the
            # rest its own to add: no example's drawn into a figure.
            {"label": "Construct", "properties": {"parts": [{"type": "cds"}]}},
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
                        _attach(),
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
            # Its own features to be added: no example's drawn into a figure.
            {"label": "Plasmid", "properties": {"length": 3000}},
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
    # Each kind once: another name for one offered already (TM, alpha helix) is read in a
    # file, not offered again.
    same = {"tm", "alpha-helix", "beta-strand", "signal-peptide"}
    kinds += sorted(set(FEATURE_TYPES) - set(kinds) - same)
    return [
        _part(
            "protein",
            "Protein",
            "Biology",
            "Domains, sites and secondary structure along a protein",
            # Its own domains and sites to be added: no example's drawn into a figure.
            {"label": "Protein", "properties": {"length": 300}},
            [
                _field("properties.length", "Length (Residues)", "integer", min=1),
                _field(
                    "properties.features",
                    "Features",
                    "records",
                    row={"type": "domain", "label": "Domain", "start": "+60", "end": "+60"},
                    columns=[
                        # A site is at one residue (At); the rest run from Start to End.
                        _column(
                            "type",
                            "Type",
                            "choice",
                            options=kinds,
                            points=sorted(
                                kind for kind, drawn in FEATURE_TYPES.items() if drawn == "site"
                            ),
                        ),
                        _column("label", "Label"),
                        _column("start", "Start", "integer"),
                        _column("end", "End", "integer"),
                        _column("at", "At", "integer", hint="The residue of a single site"),
                        _column("tone", "Tone", "combo", options=list(TONES)),
                        _attach(),
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
                        _attach(),
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
            # Its own groups of wells to be added: no example's drawn into a figure.
            {"label": "Plate", "properties": {"wells": 96}},
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
            # Its first and next day with nothing named on them, an axis to name its own events
            # on: no example's drawn into a figure.
            {"label": "Timeline", "properties": {"events": [{"at": 0}, {"at": 1}], "unit": "day"}},
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
                        _attach(),
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
                # (The axis's width on the page, not how long the protocol runs: never so
                # short that its times overprint.)
                _field(
                    "properties.length",
                    "Axis Width (pt)",
                    "number",
                    hint="Auto: as wide as its times need",
                ),
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
            _field(
                "properties", "View", "view", hint="Or drag its rotate handle, or ⌥-drag it"
            ),
            # (The theme's look, named so: not "Default", which reads as a look of its own
            # beside the one it is -- Engraved Colour, on a light theme.)
            _field(
                "properties.look",
                "Look",
                "choice",
                options=["", *LOOKS],
                labels={"": "Theme\u2019s Look"},
                hint="The look the figure's theme gives structures",
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
                # A new row colours a chain the structure has that no row colours yet.
                row={"group": "@chain", "color": "#e69f00"},
                columns=[
                    _column("group", "Chain or Residue", "chain",
                            hint="A, SER195, entity:1, subunit:L"),
                    _column(
                        "color", "Colour", "colour", options=list(TONES), hint="#e69f00 or a tone"
                    ),
                ],
                hint="These override the palette, the look and its colours (such as Helices)",
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
            # Off, the waters and lone ions a crystal holds are left out: they float free of
            # the molecule, as stray dots.
            _field(
                "properties.solvent",
                "Waters and Ions",
                "bool",
                hint="Draw the waters and lone ions where they lie",
                more=True,
            ),
            _field(
                "properties.density",
                "Map File",
                "text",
                hint="auto for the entry's own map, an EMDB ID, or a map file",
                more=True,
            ),
            _field("properties.width", "Width", "number", more=True),
            _field("properties.height", "Height", "number", more=True),
            _field("properties.yaw", "Yaw", "number", unit="°", more=True),
            _field("properties.pitch", "Pitch", "number", unit="°", more=True),
            _field("properties.roll", "Roll", "number", unit="°", more=True),
            _field("properties.zoom", "Zoom", "number", more=True),
            _field(
                "properties.pan_x", "Offset X", "number", hint="A fraction of the frame", more=True
            ),
            _field(
                "properties.pan_y", "Offset Y", "number", hint="A fraction of the frame", more=True
            ),
            _field("properties.style", "Rendering", "molsketch", sections=list(SECTIONS)),
        ],
        # (Its words, but no tone, badge or shadow: mol-sketch draws it in colours of its own,
        # and nothing round it.)
        common=[LABEL],
        needs_file=True,
        unavailable="" if ready else "Requires flexo[structures,molecules]",
    )


def _learning() -> list[dict[str, Any]]:
    simple = [
        # (Boxes can be sized: a spine's blocks as wide as the block they hang from, so
        # its skip lines run straight down their middle.)
        ("mlp", "MLP", "A multilayer perceptron", "MLP", [MOTIF, *SIZE]),
        ("cnn", "CNN", "A convolutional network", "CNN", [MOTIF, *SIZE]),
        (
            "attention",
            "Attention",
            "Attention with query, key and value ports",
            "Attention",
            [MOTIF, *SIZE],
        ),
        (
            "add-norm",
            "Add & Norm",
            "A residual sum followed by normalisation",
            "Add + norm",
            SIZE,
        ),
        ("concat", "Concat", "Values concatenated side by side", "Concat", SIZE),
        ("tensor", "Tensor", "A tensor drawn as a slab", "Tensor", []),
        ("matrix", "Matrix", "A grid of cells", "Matrix", [MOTIF]),
        ("graph", "Graph", "A small graph of nodes and edges", "Graph", [MOTIF]),
        ("inset", "Inset", "A molecule inset", "Molecule", [MOTIF]),
        ("prediction", "Prediction", "The output of a model", "Prediction", SIZE),
        ("loss", "Loss", "A loss term", "Loss", SIZE),
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
        _vector(),
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


RAMPS = {
    "ramp-node": "Node Features",
    "ramp-embedding": "Embedding",
    "ramp-q": "Query",
    "ramp-kv": "Key and Value",
    "ramp-attended": "Attended Value",
    "ramp-output": "Output",
}
"""The theme's ramps for a vector, by the value each is made for (``flexo.style.RAMP_ROLES``)."""


def _vector() -> dict[str, Any]:
    """A feature vector: a stack of cells shaded light to dark, its words under it. Its
    colour is a tone, chosen as any shape's is (its cells shaded from that colour), or
    one of the theme's ramps."""

    return _part(
        "vector",
        "Vector",
        "Machine Learning",
        "A stack of cells shaded light to dark, its name under it: a feature value, Q, K or V",
        {"label": "Vector", "properties": {"cells": 3}},
        [
            _field("properties.cells", "Cells", "integer", min=1, max=12, default=3),
            _field("properties.columns", "Columns", "integer", min=1, max=6, default=1),
            _field(
                "properties.ramp",
                "Ramp",
                "choice",
                options=["", *RAMPS],
                labels={"": "Automatic", **RAMPS},
                hint="The theme's shading for this kind of value; a colour above replaces it",
                more=True,
            ),
        ],
        common=[LABEL, TONE],
        words=["cells", "stack", "glyph", "feature", "embedding", "query", "key", "value",
               "q", "k", "v", "activation", "token"],
    )


def _basics() -> list[dict[str, Any]]:
    return [
        _part(
            "block",
            "Block",
            "Basics",
            "A labelled box, such as a step of a process",
            {"label": "Block"},
            SIZE,
            words=["process", "step", "task", "action", "activity", "rectangle", "box"],
        ),
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
            words=["start", "end", "begin", "stop", "terminator", "terminal", "pill", "flowchart"],
        ),
        _part(
            "decision",
            "Decision",
            "Basics",
            "A diamond for a decision",
            {"label": "Decision?"},
            words=["if", "branch", "condition", "choice", "question", "yes/no", "diamond"],
        ),
        _part(
            "io",
            "Input/Output",
            "Basics",
            "A parallelogram for data a flowchart reads or writes",
            {"label": "Input"},
            words=["input", "output", "i/o", "io", "data", "read", "write", "parallelogram"],
        ),
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
            # Every row of the legend shown, or none: one switch, not a row at a time.
            _field(
                "properties.legend",
                "Legend",
                "bool",
                default=True,
                hint="Shows the symbols named in the key",
            ),
            _field("properties.cell", "Cell Size", "number", unit="pt"),
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
            _field(
                "properties.ramp",
                "Ramp",
                "text",
                hint="Two colours, low then high, with a space or comma between: #f7fbff #08306b",
            ),
            _field("properties.range", "Range", "text", hint="Low then high: 0 1"),
            _field("properties.values", "Show values", "bool", default=False),
        ],
    )


def _software() -> list[dict[str, Any]]:
    """The shapes of an architecture diagram (``flexo.shapes``), each found by the
    words people search for it by."""

    return [
        _part(
            "database",
            "Database",
            "Software",
            "A cylinder for a database, cache or other store",
            {"label": "Database"},
            words=["cylinder", "storage", "store", "cache", "db", "sql", "table", "disk", "data"],
        ),
        _part(
            "server",
            "Server",
            "Software",
            "A server: a host, machine or computer",
            {"label": "Server"},
            words=["computer", "host", "machine", "rack", "node", "service", "instance", "vm"],
        ),
        _part(
            "cloud",
            "Cloud",
            "Software",
            "A cloud for the internet or a network",
            {"label": "Internet"},
            words=["internet", "network", "web", "online", "provider"],
        ),
        _part(
            "queue",
            "Queue",
            "Software",
            "A message queue, buffer or stream",
            {"label": "Queue"},
            words=["message queue", "buffer", "stream", "topic", "bus", "pipe", "fifo", "jobs"],
        ),
        _part(
            "document",
            "Document",
            "Software",
            "A page with a wavy foot: a file or report",
            {"label": "Document"},
            words=["file", "report", "page", "paper", "log", "flowchart"],
        ),
        _part(
            "person",
            "Person",
            "Software",
            "A person with the label under it: a user, client or actor",
            {"label": "User"},
            words=["user", "client", "actor", "people", "customer", "human", "account", "role"],
        ),
    ]


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
        options=["layout", "container", "module"],
        labels={"layout": "None", "container": "Frame", "module": "Module"},
        default="container",
        hint="Whether a frame is drawn round the shapes; a module's is named for them",
    ),
    SHADOW,
]

HEAD_NAMES = {
    "arrow": "Theme\u2019s Arrow",
    "latex": "LaTeX",
    "open": "Open Arrow",
    "hollow": "Hollow Triangle",
    "inhibition": "Bar (Inhibits)",
    "catalysis": "Open Circle (Catalysis)",
    "stimulation": "Open Triangle (Stimulates)",
    "necessary": "Bar and Open Triangle (Necessary)",
    "modulation": "Open Diamond (Modulates)",
}
"""What each arrowhead is called in the inspector: by its look, and an SBGN head by what it
says too."""

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
        options=list(EDGE_HEADS),
        labels=HEAD_NAMES,
        icons={head: f"head-{head}" for head in EDGE_HEADS},
        default="arrow",
        hint="The open ones and the bar say what the line does, as in SBGN",
        show={"arrow": ["end", "both"]},
    ),
    _field(
        "tail",
        "Start Arrowhead",
        "choice",
        options=["", *EDGE_HEADS],
        labels={"": "Same as End", **HEAD_NAMES},
        icons={head: f"head-{head}" for head in EDGE_HEADS},
        default="",
        show={"arrow": "both"},
    ),
    _field("line", "Line Style", "choice", options=["solid", "dashed", "dotted"], default="solid"),
    _field(
        "shape",
        "Routing",
        "choice",
        options=["auto", "orthogonal", "straight", "curved"],
        default="auto",
        hint="Curved bows away from the figure's middle, or leaves the sides chosen square",
    ),
    _field(
        "bend",
        "Bend",
        "number",
        min=-1,
        max=1,
        step=0.05,
        show={"shape": "curved"},
        hint="Drag the handle on its middle; a share of its length, to the left of its travel",
    ),
    _field(
        "lean",
        "Lean",
        "number",
        min=-0.5,
        max=0.5,
        step=0.05,
        show={"shape": "curved"},
        hint="Where along it the curve peaks: toward its end (+) or its start (-)",
    ),
    _field(
        "width",
        "Line Width",
        "number",
        min=0.1,
        max=20,
        step=0.25,
        unit="pt",
        hint="Unset, the theme's; its arrowheads grow with it",
    ),
    _field(
        "head_size",
        "Arrowhead Size",
        "number",
        min=0.1,
        max=10,
        step=0.25,
        unit="\u00d7",  # times as large
        default=1,
        show={"arrow": ["end", "both", "reversible"]},
    ),
    _field(
        "cofactors",
        "Cofactors",
        "pair",
        labels=["Consumed", "Produced"],
        hint="Shown on an arc beside the reaction: ATP, ADP",
        more=True,
        # A reaction's: offered on a figure of biology or chemistry, not a flow chart.
        science=True,
    ),
]


SIDES = {"": "Automatic", "north": "Top", "east": "Right", "south": "Bottom", "west": "Left"}
"""The sides of a shape, as a person says them."""

NET_FIELDS = [
    LABEL,
    _field(
        "via",
        "Side",
        "choice",
        options=list(SIDES),
        labels=SIDES,
        hint="Where it meets its shape",
        show={"kind": "merge"},
    ),
    _field("line", "Line Style", "choice", options=["solid", "dashed", "dotted"], default="solid"),
    _field(
        "rail",
        "Shared Run",
        "choice",
        options=list(SIDES),
        labels=SIDES,
        hint="The side the branches meet along",
    ),
]
"""A line that branches: its words, how it is drawn, and where its branches meet."""


def figure_fields(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        # The figure's name is its file's; what the file calls it is kept under More.
        _field(
            "figure.id", "Name in File", "text", hint="What the file calls the figure", more=True
        ),
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
            labels={"single-column": "Single Column", "double-column": "Double Column"},
            default="double-column",
        ),
        _field("figure.font", "Font", "combo", options=catalog.get("fonts", [])),
    ]


CATEGORIES = ("Basics", "Software", "Machine Learning", "Biology")


def catalogue(catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """The editor's catalogue: parts by category, groups, and the fields of each thing."""

    parts = [
        *_basics(),
        *_software(),
        *_learning(),
        *_genetics(),
        *_proteins(),
        *_bench(),
        _structure(),
    ]
    sizes = _sizes()
    return {
        "categories": list(CATEGORIES),
        "parts": {
            part["kind"]: {**part, "size": sizes[part["kind"]]} if part["kind"] in sizes else part
            for part in parts
        },
        "groups": GROUPS,
        "group_fields": GROUP_FIELDS,
        "edge_fields": EDGE_FIELDS,
        "net_fields": NET_FIELDS,
        "figure_fields": figure_fields(catalog or {}),
    }


@functools.cache
def _sizes() -> dict[str, list[float]]:
    """How large each part is drawn as it is added (with the words it starts with), in ems
    of the figure's words: so the page can stand it in where it goes at the size it will be,
    before it is drawn there -- a circle a circle's size, not its neighbour's."""

    from flexo.layout.measure import measure_figure
    from flexo.serialization import parse_figure
    from flexo.themes import figure_style

    sizes = {}
    for part in [*_basics(), *_software(), *_learning(), *_genetics(), *_proteins(), *_bench()]:
        try:
            spec = parse_figure({"figure": {"id": "x"}, "nodes": [{"id": "n", **part["node"]}]})
            style = figure_style(spec)
            size = measure_figure(spec, style=style).nodes[0].intrinsic_size
        except Exception:  # (one that can't be drawn bare is stood in as its neighbour's size)
            continue
        em = style.typography.size.points
        sizes[part["kind"]] = [round(size.width / em, 2), round(size.height / em, 2)]
    return sizes
