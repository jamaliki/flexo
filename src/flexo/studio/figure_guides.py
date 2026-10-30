"""A figure file taught to an agent a little at a time (``flexo.studio.agent_guides``): the brief
it is given first, the topics its guide (``figure_kind.GUIDE``) is cut into, and an example or
two of each that a test draws (``tests/unit/test_agent_guides.py``)."""

from __future__ import annotations

from flexo.studio.agent_guides import Snippet, Topic, topic_list, topics_from, written

BRIEF = """\
A flexo figure file: YAML that says what the figure is -- its parts (nodes), the lines between
them (edges), how parts are grouped (groups) -- never where things go. Flexo lays it out, routes
every line and draws it in a theme, the same in every export.

figure: {id: model, style: paper, width: double-column}   # style: a theme; width: 89mm, ...
nodes:
- {id: x, kind: text, label: "Input $x$"}
- {id: encoder, label: Encoder, properties: {tone: encoder}}
- {id: decoder, label: Decoder, properties: {tone: head}}
- {id: y, kind: text, label: "Output $y$"}
groups:
- {id: model, children: [encoder, decoder], layout: {kind: row}, label: Model}
- {id: root, children: [x, model, y], layout: {kind: row}}
edges:
- {from: x, to: encoder}
- {from: encoder, to: decoder, label: "$z$"}
- {from: decoder, to: y}
shapes:                                 # marks drawn over it, attached to its parts
- {kind: ring, around: [decoder]}

Parts at a glance
- nodes: {id, label, kind, properties}. Kinds: block (the default), text, op, circle, frame,
  image, structure, plot, mechanism, construct, protein, tree, cells and more (guide nodes).
- edges: {from, to, label, head, arrow: both|none, shape: orthogonal|straight|curved, line:
  dashed}. An end may be a group, or a node's port (node.port).
- groups: {id, children, layout: {kind: row|column|grid, gap}, label}. The root group holds the
  rest; a group with role: panel is a lettered panel.
- Labels are markup: $maths$, `code`, [words]{accent}, \\n for a new line.

How to work
1. {tool:outline} the figure: its parts as its groups hold them, its lines, its shapes, its
   warnings, and what the user has selected ("this" in a request).
2. {tool:read_document}, then {tool:edit_document} a few lines at a time, `old` copied exactly
   from what you read. The reply says what changed, warns of anything deleted, and says what
   to look at next.
3. {tool:look} at it once after a change. {arg:look.annotate}: true outlines each part, group and
   shape with its id, so you can name what you see.
4. Stop when the look shows no warnings and the figure reads as you mean; then tell the user.
5. {tool:guide} with a topic teaches the rest, with examples that draw (the topics are below).

Habits
- Name parts by what they are (encoder, not n3): lines, groups and shapes find them by id.
- Never place or size parts. Say what holds what -- rows, columns, grids, panels -- and flexo
  lays it out. Shapes drawn over the figure are placed from parts (on, around, {part: id}).
- One idea per figure, few words per part. Let tones (properties.tone) carry roles, and the
  theme carry colours.
- Mark up a part -- an arrow at it, a ring round it, a brace, a label -- with the figure's shapes,
  attached to it, rather than by changing the part.
- A figure for a deck is written in the deck's slide (the deck's guide figures), not as a file
  of its own, unless the user asks for a file.
- If valid YAML is laid out badly -- parts overlapping, a line through a part, words cut off --
  tell the user it looks like a Flexo bug, with the YAML. Don't nudge it to hide it.
- When an edit is refused (`old` does not occur), read again before retrying: the user may have
  changed it. Prefer {tool:edit_document} to {tool:write_document}, and never write the whole file
  from an old copy.
- When the user gives no style and there is no figure to match, ask one question about the look
  before drawing a large figure.
- Say what you are doing, in a few words, with {tool:status}.

Topics ({tool:guide} with topic: one of these and kind: figure; reference is the whole guide):
{topics}
"""

ABOUT = {
    "basics": "The figure's settings: theme, width, height, panel letters, spacing",
    "nodes": "Parts: their kinds, words, tones, outlines and label settings",
    "edges": "Lines between parts: heads, labels, routes, ends at groups",
    "groups": "Rows, columns and grids of parts, frames round parts, and panels",
    "shapes": "Marks drawn over the figure -- arrows, rings, braces, labels -- attached to parts",
    "insets": "A part shown magnified in a box, joined to it",
    "pictures": "Pictures (PNG, JPEG, SVG) as parts, and an SVG's words and colours",
    "structures": "Molecules from PDB or CIF files, and mol-sketch scenes",
    "mechanisms": "Reactions drawn with their curly arrows",
    "plots": "A matplotlib plot as a part",
    "biology": "Genetic constructs, plasmids, proteins, trees, plates and timelines",
    "grids": "Grids of cells with a key",
    "showing": "Parts hidden, dimmed or highlighted, nothing moved",
    "words": "Label markup: maths, code, colours, new lines",
}

ANCHORS = {
    "nodes": [
        r"^nodes: each",
        r"^A node, a group and a frame each take line",
        r"^A node's properties set its whole label",
    ],
    "biology": [r"^Genetics:", r"^Proteins:"],
    "grids": [r"^Grids:"],
    "edges": [r"^edges: each", r"^An edge may start or end at a group"],
    "groups": [r"^groups: each", r"^A frame round shapes", r"^A figure of several panels"],
    "pictures": [r"^A picture: \{id, kind: image"],
    "structures": [r"A molecule's\s+structure:"],
    "mechanisms": [r"^A reaction mechanism:"],
    "plots": [r"^A plot: \{id, kind: plot"],
    "showing": [r"^figure: \{hide:"],
    "shapes": [r"^shapes: drawn over the figure", r"E\.g\.\s+shapes: \[", r"A diagram pasted as"],
    "insets": [r"A zoom inset, kind: inset"],
    "words": [r"^Labels are markup"],
}

PNG = b"png"
"""A file a snippet names, written by the test as a small picture."""

SNIPPETS: dict[str, list[Snippet]] = {
    "basics": [
        Snippet(
            "a figure, its theme and width",
            """\
figure: {id: pipeline, style: paper, width: single-column, spacing: 0.8}
nodes:
- {id: data, label: Data}
- {id: model, label: Model, properties: {tone: encoder}}
edges:
- {from: data, to: model}
""",
        )
    ],
    "nodes": [
        Snippet(
            "kinds of part, and their tones",
            """\
figure: {id: kinds}
nodes:
- {id: x, kind: text, label: "Input $x$"}
- {id: sum, kind: op, label: "+"}
- {id: state, kind: circle, label: "$h_t$"}
- {id: encoder, label: Encoder, properties: {tone: encoder, bold: true}}
- {id: head, label: Head, line: dashed, properties: {tone: head}}
edges:
- {from: x, to: sum}
- {from: sum, to: state}
- {from: state, to: encoder}
- {from: encoder, to: head}
""",
        )
    ],
    "edges": [
        Snippet(
            "lines: heads, labels, routes",
            """\
figure: {id: lines}
nodes:
- {id: a, label: A}
- {id: b, label: B}
- {id: c, label: C}
groups:
- {id: root, children: [a, b, c], layout: {kind: row}}
edges:
- {from: a, to: b, label: "$f$", head: stealth}
- {from: b, to: c, arrow: both, line: dashed}
- {from: c, to: a, shape: curved, depart: south, arrive: south, label: feedback}
""",
        )
    ],
    "groups": [
        Snippet(
            "rows, a column, a frame and a title",
            """\
figure: {id: grouped}
nodes:
- {id: x, kind: text, label: Input}
- {id: enc, label: Encoder}
- {id: dec, label: Decoder}
- {id: y, kind: text, label: Output}
- {id: core, kind: frame, label: Core, properties: {around: "enc, dec"}}
groups:
- {id: model, children: [enc, dec], layout: {kind: column, gap: 12}, label: Model}
- {id: root, children: [x, model, y], layout: {kind: row}}
edges:
- {from: x, to: model}
- {from: model, to: y}
""",
        ),
        Snippet(
            "panels, lettered a and b",
            """\
figure: {id: panels}
nodes:
- {id: one, label: First}
- {id: two, label: Second}
groups:
- {id: left, role: panel, children: [one], layout: {kind: column}, label: Setup}
- {id: right, role: panel, children: [two], layout: {kind: column}, label: Result}
- {id: root, role: canvas, children: [left, right], layout: {kind: grid, columns: 2}}
""",
        ),
    ],
    "shapes": [
        Snippet(
            "a ring, an arrow, a label and a brace, attached to parts",
            """\
figure: {id: marked}
nodes:
- {id: encoder, label: Encoder}
- {id: decoder, label: Decoder}
- {id: note, kind: text, label: the bottleneck}
groups:
- {id: root, children: [encoder, decoder, note], layout: {kind: row, gap: 40}}
edges:
- {from: encoder, to: decoder}
shapes:
- {kind: ring, around: [decoder]}
- {kind: arrow, from: {part: note, side: left}, to: {part: decoder, side: right}}
- {kind: text, on: encoder, at: [0, -16], text: frozen}
- {kind: brace, around: [encoder, decoder], side: bottom, text: two steps}
""",
        )
    ],
    "insets": [
        Snippet(
            "a corner of a grid, magnified beside it",
            """\
figure: {id: zoomed}
nodes:
- id: board
  kind: cells
  properties: {grid: "1 2 3 4\\n5 6 7 8\\n8 7 6 5\\n4 3 2 1", values: true}
shapes:
- {kind: inset, of: board, on: board, region: [0.5, 0.5, 0.5, 0.5], at: [110, 0], size: [70, 70]}
""",
        )
    ],
    "pictures": [
        Snippet(
            "a picture as a part, labelled under it",
            """\
figure: {id: pictured}
nodes:
- {id: cell, kind: image, label: A cell, properties: {source: photo.png, title_side: bottom}}
- {id: model, label: Model}
groups:
- {id: root, children: [cell, model], layout: {kind: row}}
edges:
- {from: cell, to: model}
""",
            files={"photo.png": PNG},
        )
    ],
    "mechanisms": [
        Snippet(
            "a substitution, two steps",
            """\
figure: {id: sn2}
nodes:
- id: reaction
  kind: mechanism
  properties:
    steps:
    - {smiles: "[OH-:5].[CH3:1][Cl:4]", arrows: ["5 -> 1", "1-4 -> 4"], label: attack}
""",
        )
    ],
    "biology": [
        Snippet(
            "a construct, a protein and a plate",
            """\
figure: {id: bench}
nodes:
- id: construct
  kind: construct
  properties:
    parts:
    - {type: promoter, label: pT7}
    - {type: rbs}
    - {type: cds, label: GFP}
    - {type: terminator}
- id: protein
  kind: protein
  properties:
    length: 300
    features:
    - {type: domain, label: Kinase, start: 40, end: 200}
    - {type: phosphorylation, at: 250}
- id: plate
  kind: wellplate
  properties: {wells: 96, groups: [{wells: "A1-A12", label: Controls}]}
groups:
- {id: root, children: [construct, protein, plate], layout: {kind: column}}
""",
        )
    ],
    "grids": [
        Snippet(
            "a grid of cells with a key",
            """\
figure: {id: lattice}
nodes:
- id: board
  kind: cells
  properties:
    grid: "K . K\\n. Y R"
    key:
    - {symbol: K, color: accent, label: Kinase}
    - {symbol: Y, color: accent2, label: Yeast}
    - {symbol: R, color: muted, label: Rest}
""",
        )
    ],
    "showing": [
        Snippet(
            "one part dimmed, one hidden",
            """\
figure: {id: shown, dim: [b], hide: [c]}
nodes:
- {id: a, label: A}
- {id: b, label: B}
- {id: c, label: C}
groups:
- {id: root, children: [a, b, c], layout: {kind: row}}
""",
        )
    ],
    "words": [
        Snippet(
            "label markup",
            """\
figure: {id: worded}
nodes:
- {id: a, label: "Loss $\\\\mathcal{L}$ in [red]{accent}"}
- {id: b, label: "`code` and\\ntwo lines"}
edges:
- {from: a, to: b}
""",
        )
    ],
}


def topics() -> dict[str, Topic]:
    """A figure file's topics, cut from its guide."""

    from flexo.studio.figure_kind import GUIDE

    return topics_from(GUIDE, ABOUT, ANCHORS, SNIPPETS, first="basics")


def brief() -> str:
    """What an agent is told first about a figure file."""

    return written(BRIEF).replace("{topics}", topic_list(topics()))
