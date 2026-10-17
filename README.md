# Flexo

Flexo is a Python-first compiler for editable scientific and neural-network
figures. Authors describe components, relationships, and editorial layout; Flexo
measures text, fits the composition, routes connectors, and emits
publication-ready SVG made from ordinary Inkscape-editable objects.

```text
semantic figure -> measured figure -> fitted figure -> routed figure -> SVG
```

No coordinates, and no post-hoc nudging: the figure you author is the figure
that compiles, and it compiles the same way every time.

| `theme="paper"` | `theme="sketch"` |
| --- | --- |
| ![The Transformer (examples/transformer.py)](examples/build/transformer.preview.png) | ![The same code, drawn by hand](examples/build/transformer-sketch.preview.png) |

New to Flexo? The [tutorial](docs/tutorial.md) builds figures step by step,
from a first box to a themed, hand-drawn panel, with every picture made from
the code beside it.

## Quick start

```bash
uv sync --all-groups
```

```python
import flexo

with flexo.Figure("block", width="single-column") as figure:
    with figure.module("residual", label="Residual block", layout="column") as m:
        x = m.block("x", label="x")
        conv = m.block("conv", label="3x3 conv", input=x)
        norm = m.block("bn", label="BatchNorm", input=conv)
        total = m.add("sum", inputs=[norm, x])
        m.block("out", label="ReLU", input=total)

result = flexo.build(figure, "build", formats=("editable", "pdf", "png"))
print(result.summary())
```

That is the whole figure: no coordinates, no port tables, no colours, no
routing hints. `flexo.build` compiles, writes the formats you asked for, and
lints; outputs are written even when the report has errors, so a flawed figure
stays inspectable. Every format is written in Python, with nothing else to
install: the editable SVG (live text), a portable SVG (words as outlines), a PDF
(real, selectable text in embedded fonts), and a PNG preview. In a Jupyter
notebook, a figure displays itself: end a cell with `figure`.

Components can also be written flat, in any order, and laid out from their
wiring alone:

```python
with flexo.Figure("heads", layout="flow") as figure:
    x = figure.root.text("x", "Input $x$")
    shared = figure.root.block("shared", label="Shared encoder", input=x)
    heads = [figure.root.block(name, label=name, input=shared) for name in ("Depth", "Normals")]
    figure.root.add("total", inputs=heads)
```

## Figures from the literature

[`examples/literature.py`](examples/literature.py) draws sixty-nine figures from
papers and textbooks -- Inception, LSTM, Mamba, ViT, U-Net, a GPT block, the
agent–environment loop, a multilayer perceptron, graphical models, and more --
each in about fifteen lines, with no coordinates, colours, or port tables. See
the [gallery](examples/README.md#literaturepy).

| | | |
| --- | --- | --- |
| ![Inception module](examples/build/literature/inception.preview.png) | ![LSTM cell](examples/build/literature/lstm.preview.png) | ![Mamba block](examples/build/literature/mamba.preview.png) |
| ![Agent-environment loop](examples/build/literature/agent-environment.preview.png) | ![Multilayer perceptron](examples/build/literature/multilayer-perceptron.preview.png) | ![LSTM cell in the tikz theme](examples/build/literature/lstm-tikz.preview.png) |

## What you can draw

### Components and wiring

A figure is groups of components. `figure.module(...)` opens a titled
container; inside any group, `row`, `column`, and `grid` arrange their children
and, unless given a label, draw nothing. Every component is a method on the group it goes in:

| Kind | Methods |
| --- | --- |
| Boxes | `block`, `mlp`, `cnn`, `attention`, `add_norm`, `prediction`, `loss`, `tensor`, `matrix`, `sequence`, `feature_strip`, `concat`, `channels` |
| Shapes | `circle`, `decision`, `terminal`, `io`, `volume`, `op` (and `add`, `multiply`) |
| Software | `database`, `server`, `cloud`, `queue`, `document`, `person` (see [Flowcharts and architecture diagrams](#flowcharts-and-architecture-diagrams)) |
| Words and art | `text`, `vector`, `image`, `graph`, `inset`, `legend` |
| Genetics | `construct`, `plasmid` (see [Genetic designs](#genetic-designs-constructs-and-plasmids)) |
| Proteins, trees, the bench | `protein`, `tree`, `wellplate`, `timeline` (see [Proteins, trees, plates, and timelines](#proteins-trees-plates-and-timelines)) |
| Grids | `cells`: plate maps, heatmaps, boards, number squares (see [Grids of cells](#grids-of-cells)) |
| Chemistry | `mechanism`: structures from SMILES and the curly arrows between them (see [Reaction mechanisms](#reaction-mechanisms)) |

A label longer than 16 ems wraps into balanced lines, and a component with an
authored `width=` wraps its label to fit; `"\n"` breaks a line where you want.

`input=` connects one upstream component as the new one is created, and
`inputs=` connects several. `connect(a, b)` draws an edge later,
`net(src=a, sinks=[b, c])` draws one value going to several places, and
`merge(sinks=[a, b], dst=c)` draws several values joining before one place.
Edges and nets belong to the figure, not to a group: `figure.connect(a, b)`
and `m.connect(a, b)` are the same edge, so an edge between groups is written
wherever both ends are in hand. The [authoring guide](docs/guide.md) covers
each component and option.

### Genetic designs: constructs and plasmids

A genetic construct is drawn in [SBOL Visual](https://sbolstandard.org/visual-about/)
glyphs on a backbone, and a plasmid as a circular map. Both are components like any
other: they sit in a figure, take its theme (type, palette, hand), and are wired to
other components.

```python
with flexo.Figure("reporter") as figure:
    circuit = figure.root.construct("circuit", label="pTet–GFP reporter", parts=[
        {"type": "promoter", "label": "pTet"},
        {"type": "rbs", "label": "B0034"},
        {"type": "cds", "label": "GFP", "id": "gfp"},   # an id makes the part a port
        {"type": "terminator", "label": "B0015"},
        {"type": "cds", "label": "TetR", "strand": "-"},
    ])
    figure.root.plasmid("vector", 5421, label="pTet-GFP", features=[
        {"type": "promoter", "label": "pTet", "start": 120, "end": 180},
        {"type": "cds", "label": "GFP", "start": 220, "end": 940},
        {"type": "cds", "label": "AmpR", "start": 3300, "end": 4160, "strand": "-"},
        {"type": "origin", "label": "ColE1", "start": 2500, "end": 3090},
        {"type": "site", "label": "EcoRI", "start": 5},
    ])
    protein = figure.root.block("protein", label="Fluorescence", tone="GFP")
    figure.connect(circuit.port("gfp"), protein)
```

| Part | Construct glyph | On a plasmid |
| --- | --- | --- |
| `promoter` | a bent arrow | a short arrow along the circle |
| `rbs` | a half circle on the backbone | -- |
| `cds` (`gene`) | an arrow with the gene's name in it | an arrow arc |
| `terminator` | a T | a T standing out from the circle |
| `operator`, `insulator` | a square; a square in a square | -- |
| `origin` (`ori`) | a circle on the backbone | an arc |
| `primer`, `site`, `region`, `spacer` | a half arrow; a tick; a box; a gap | a thin arrow; a tick named with its position; an arc |

A part on the `-` strand is turned over: it points left and hangs below the
backbone, or runs anticlockwise round the plasmid. A gene takes a colour by its
name, so `GFP` is one colour in every construct and plasmid of a figure, and a
component given `tone="GFP"` matches it; any part can name a `tone` of its own,
and the other parts are drawn in ink. A construct's part with an `id` is a port
under its glyph (`input` and `output` are the backbone's ends), so an arrow can
leave a gene for what it makes. On a plasmid, features are placed by their base
pairs (`start`, `end`; a feature may run across the origin), overlapping features
stack outward, every named feature is labelled outside the circle with a leader
line, and ticks mark every round number of base pairs (`ticks=False` drops them).
`scale=0.1` draws a construct to scale, that many points a base pair: give each
part its length (`"bp": 720`). Genes, regions, and spacers are then as long as
they are, the smaller glyphs keep their size centred on their stretch, the names
sit in one row clear of every glyph and are spread apart where they crowd, and a
base-pair ruler runs underneath (`ticks=False` drops it).
In a figure file the same are `kind: construct` with `properties: {parts: [...]}`
and `kind: plasmid` with `properties: {length: 5421, features: [...]}`.

### Pathways, regulation, and reactions

![A pathway and a gene circuit (examples/biology.py)](examples/build/pathway.preview.png)

```python
figure.connect(glucose, g6p, label="hexokinase", cofactors=("ATP", "ADP"))
figure.connect(g6p, f6p, arrow="reversible", label="$k_1$", back_label="$k_{-1}$")
figure.connect(tetr, ptet, head="inhibition")      # a repressor on its promoter
figure.connect(ptet, gfp, head="stimulation")
```

`head=` says what a connector does to its target, in
[SBGN](https://sbgn.github.io/)'s arrowheads: `"inhibition"` (a bar, ⊣),
`"catalysis"` (an open circle), `"stimulation"` (an open triangle),
`"necessary"` (a bar and an open triangle), or `"modulation"` (an open
diamond). These heads touch what they act on, where an arrow stops just short.
`arrow="reversible"` draws a reversible step as two half-headed lines (⇌),
with `label` over them and `back_label` under them. `cofactors=("ATP", "ADP")`
writes what a step takes in and gives off as a curved arrow touching the line,
across it from the label; either may be `""` (water taken in, nothing given
off). Layout makes room for both sides of the line, as it does for a caption.
In a figure file these are the edge fields `head`, `arrow: reversible`,
`back_label`, and `cofactors: [ATP, ADP]`.

### Proteins, trees, plates, and timelines

![Protein domain maps (examples/biology.py)](examples/build/proteins.preview.png)

```python
figure.root.protein("abl1", 1130, label="ABL1", features=[
    {"type": "domain", "label": "SH3", "start": 61, "end": 121},
    {"type": "domain", "label": "Kinase", "start": 242, "end": 493},
    {"type": "region", "label": "Disordered", "start": 540, "end": 960},
    {"type": "transmembrane", "start": 1000, "end": 1022},
    {"type": "mutation", "label": "T315I", "at": 315},
    {"type": "phosphorylation", "label": "Y412", "at": 412},
    {"type": "disulfide", "start": 600, "end": 700},
])
figure.root.protein("constructs", 1130, features=domains, tracks=[
    {"label": "Full length"},
    {"label": "ΔSH3", "delete": "61-121"},
    {"label": "Kinase domain", "start": 229, "end": 500},
])
```

`protein` draws a chain to scale by residue: domains, regions, and motifs as
boxes (named inside when the name fits, under the box when not), transmembrane
helices as tall dark bars, a signal peptide as a short box, sites (`mutation`,
`phosphorylation`, `glycosylation`, ... at one residue, `at:`) as lollipops
with their names spread apart, and disulfides as brackets under the chain, over
a residue axis. `tracks` draws the protein several times on one scale -- a
truncation keeps `start` to `end`, a `delete` breaks the chain with a hinge.
A domain takes a colour by its name, as a gene does; every mutation shares one
colour, every kind of modification another. `scale=` (points a residue) and
`gutter=` (room for track names) line up separate proteins. A feature with an
`id` is a port over it; a track with an `id` is a port at each end of its chain
(`"short"` on the left, `"short.end"` on the right), so an arrow can point at one
construct of a stack. Sites closer than their heads are fanned out sideways, each
stem bending from its own residue to a head of its own.

![Secondary structure (examples/biology.py)](examples/build/structure.preview.png)

```python
figure.root.protein("ubiquitin", 76, secondary=dssp, sequence=sequence, scale=6.2)
figure.root.protein("close", 76, secondary=dssp, sequence=sequence, scale=12,
                    helix="cylinder", tracks=[{"start": 18, "end": 42}])
```

`secondary=` draws the secondary structure along the chain, on its scale: a
DSSP string, one letter a residue (`H`, `G`, `I` helix; `E` strand; `T` turn;
anything else loop), or features of type `helix`, `strand`, and `turn`.
Helices are ribbons seen side on, the near half of each turn over the darker far
half (`helix="cylinder"` for bars, `"spiral"` for a line), strands arrows, turns low
arches, numbered α1, β1, ... over them (`numbered=False` to leave them bare). The
strip takes the chain's place when nothing else is on it, and runs under the
domains when they are. `sequence=` writes the one-letter sequence under it
wherever the scale leaves room for a letter a residue, and a track's `start`
and `end` make a close view of a segment.

#### From a structure or a UniProt entry

```python
figure.root.protein("ubq", **flexo.from_structure("1ubq.cif"))           # sequence, helices, strands
figure.root.protein("abl1", **flexo.from_uniprot("P00519"))              # domains, motifs, bonds
figure.root.protein("abl1", **flexo.from_uniprot("P00519.json", sites=True, variants=True))
```

`from_structure` reads a PDB or mmCIF file (install the `structures` extra, which
brings [gemmi](https://gemmi.readthedocs.io)): the chain's sequence and its
secondary structure, from the file's helix and sheet records or -- for a model
without them, a design or a prediction, or with `assign=True` -- from the
backbone's hydrogen bonds after DSSP. `from_uniprot` reads an entry from the
UniProt REST service, or a saved entry's JSON: domains, regions, motifs,
transmembrane and signal segments, and disulfides; modified residues and
glycosylations with `sites=True`, variants with `variants=True`, and the entry's
helices and strands with `structure=True`. Each returns the arguments `protein()`
takes, as a plain dict to edit or merge before drawing.

#### A molecule beside its map

![A structure by mol-sketch beside its secondary structure (examples/biology.py)](examples/build/molecule.preview.png)

```python
row.structure("model", "1a7g.cif", label="E2 DNA-binding domain", yaw=30, width=150, height=120)
row.protein("map", **flexo.from_structure("1a7g.cif"), scale=3.2)
```

`structure` draws a PDB or mmCIF file (or a PDB ID) by hand with
[mol-sketch](https://github.com/jamaliki/mol-sketch), as a component of the
figure: its look follows the theme (watercolour in `sketch`, dark paper on a dark
page, engraved colour otherwise) unless `look=` names one; it is drawn on the
figure's page colour and that colour taken out, so it sits on the page with no
box; its ink is the figure's, and its helices and strands take the colours a
protein map in the figure gives them. `colors={"A": "Kinase"}` colours a chain
(or a residue such as `SER195` or a ligand such as `6V0401`, a subunit, an entity,
or a selection such as `resi 10-24` or `not polymer`) with a hex colour or one of
the figure's tones, a later one over an earlier one where they overlap; a group
the molecule has none of is said. `ss_from="end.pdb"` colours each residue by its
secondary structure in another file, in the look's helix, strand and loop colours,
while it is drawn with its own -- a diffusion run's frames coloured by the
structure they end as; `yaw`, `pitch`, `roll`, `zoom` turn and frame it; `cartoon`, `sticks`,
`surface`, and `site` are mol-sketch selections (`site="ligand"` picks out the
largest ligand's pocket). The rest of mol-sketch is there too: `palette=` names
one of its group palettes, `density=` draws a density map with the model
(`"auto"`, an EMDB ID, or a map file), and `style=` sets any field of its style
over the look, nested as mol-sketch writes them --
`style={"fill": "ink colour", "line": {"width": 2}}`, or in a figure file
`style: {fill: ink colour, line: {width: 2}}`; a field it does not have, or a
choice it does not offer, is said with what was meant. In the studio, a chosen
structure's panel shows these settings in mol-sketch's own sections, each with
what the look gives it until it is given its own. Install the `molecules` extra
(or `pip install path/to/mol-sketch/python`).

`look="flat"` draws it as PyMOL's flat, outlined figures are drawn -- solid colours,
a darker shade on a ribbon's far side, thin even outlines, round sticks -- and in the
figure's own colours: helices in the accent's fill, strands in the warm fill, loops in
the neutral fill, a chain or residue in its tone's fill, outlines, words, charges and
arrows in ink. It
is nested as shapes rather than a picture, so it stays sharp at any size, the PDF
carries it as vectors, and each shape records the role it was painted in, so `flexo
retheme` recolours it with the rest of the figure. In a sketched theme it keeps its
own clean line.

#### Structures that share a frame

A run of structures -- a diffusion model's steps from noise to the folded protein, a motif
scaffolded five ways, the states of a motor -- reads as one only when each is seen the same
way. Drawn alone, each is fitted to its own box (`zoom` 1 fits what is drawn), so the small
ball of noise is drawn as large as the protein it becomes; and each starts along its own
principal axes, so the same `yaw` turns two of them differently. Structures that name the
same `frame` are drawn as one:

```yaml
nodes:
  - id: t100
    kind: structure
    label: "[t]{italic} = 100"
    properties: {source: frames/t100.pdb, frame: diffusion, yaw: 20, pitch: -10, title_side: bottom}
  - id: t0
    kind: structure
    label: "[t]{italic} = 0"
    properties: {source: frames/t000.pdb, frame: diffusion, title_side: bottom}
```

- **One camera**: each is turned as the first of them (in the figure's `nodes`) is turned by
  its `yaw`, `pitch` and `roll` -- the same way in space, their coordinates read in one frame.
  The first is drawn as it would be alone; the others are seen from where it is seen.
- **One scale**: the same ångströms to the point, the scale at which each of them fits its
  own box -- the largest's -- times the first's `zoom`. The noise is drawn small, and grows.
- **One centre**: the middle of all they draw together, moved by the first's `pan_x` and
  `pan_y`. A motif held fixed, or a trajectory aligned, stays where it is in every panel.

Each keeps its own box, look, colours and what it draws. A row of structures wider than its page -- five frames at their usual size are, in a double column -- is drawn with the structures that have no size of their own smaller, all alike, until it fits; one given a `width` or `height` keeps it. The first one's `yaw`, `pitch`,
`roll`, `zoom`, `pan_x` and `pan_y` are the frame's; another's own are not used (and said,
where they differ). With a flat projection (the engraved, textbook and flat looks) each atom
is drawn exactly where the frame's camera puts it; in perspective each is seen from the
frame's eye, exact at the frame's centre and within a share of the perspective elsewhere. In
Python: `row.structure("t0", "frames/t000.pdb", frame="diffusion", title_side="bottom")`.

In the studio, turning any of them by its rotate handle turns them all as it is dragged, and
setting the yaw, pitch or roll (or the zoom, or the offset) in its panel's **Camera** tab sets
them for the frame -- one step to undo. So too its colours: a colour changed in its **Look** tab's
Colours (helices, strands, loops, ink...), its **Molecule** tab's colour rows, Secondary Structure
From, or how it is coloured, is changed on each structure of the frame that had the same -- one
step -- while a colour one of them was given of its own stays its own. The Camera tab's **Frame** puts a structure in one of
the figure's frames (each with how many structures it has), in a new frame of its own, or in
none: out of a frame, it keeps the turn it was seen at.

A structure's name stands over the molecule, or under it with `title_side: bottom`; its words
take a slant as any label's do, `[t]{italic} = 100` setting the *t* in italics (asterisks are
drawn as typed).

#### A diffusion run, frame by frame

![A diffusion run of one structure, five copies at five noise levels (examples/biology.py)](examples/build/diffusion.preview.png)

```yaml
nodes:
  - {id: t100, kind: structure, label: "t = 100", properties: {source: 5KKA.pdb, look: flat, noise: 1}}
  - {id: t30, kind: structure, label: "t = 30", properties: {source: 5KKA.pdb, look: flat, noise: 0.3}}
  - {id: t20, kind: structure, label: "t = 20", properties: {source: 5KKA.pdb, look: flat, noise: 0.16}}
  - {id: t10, kind: structure, label: "t = 10", properties: {source: 5KKA.pdb, look: flat, noise: 0.06}}
  - {id: t0, kind: structure, label: "t = 0", properties: {source: 5KKA.pdb, look: flat}}
groups:
  - {id: run, role: layout, layout: {kind: row, gap: 16}, children: [t100, t30, t20, t10, t0]}
edges:
  - {from: t100, to: t30}
  - {from: t30, to: t20}
  - {from: t20, to: t10}
  - {from: t10, to: t0}
```

A structure's `noise` draws it as a diffusion model does on its way, from 0 (the
file itself) to 1 (a random coil): it is the share of the run still to go, t over its
steps, so `noise: 0.3` is t = 30 of a hundred steps, or t = 15 of fifty. Copies of one
structure alike but for their noise are moments of one trajectory, so a series is five
copies of one part, with no frames made elsewhere. `fixed:` holds a mol-sketch selection
where the file has it -- a residue whole when any of its atoms is selected -- for a
motif-scaffolding run (`fixed: resi 34+94+119+177 or resn 6V0`), or a target a binder is
made for (`fixed: chain B`); `seed:` picks another run (0 unless given). In the studio,
a structure's Molecule tab has them under Noise.

The prior is a random coil with a protein's own local geometry (its C-alphas 3.8 Å apart,
each angle between 85° and 135°), wandering in a ball about the size of the chain folded,
and through a motif's C-alphas. Stretches of the chain then fold to the file's shape, the
short ones first, so helices form, right-handed, before their packing: at noise 0.3 the
chain is 70% as far from the file as its prior (RMS) and its helices forming, at 0.16 a
quarter (its shape is there), at 0.06 a twelfth (nearly the file). Throughout, each bond
keeps the file's length and each angle stays within a protein's, so the trace is never
broken where the file's is not, and a helix is never squashed into a rod; the file's
helices and strands are drawn where they have formed. Every residue moves rigidly with
its C-alpha, turned as the chain is turned there, so side chains and sticks stay
chemically sane; a ligand, ion or water not held moves with the residue nearest it. Each
chain folds on its own, round where it ends up, and is seen as the file is: `yaw` and
`pitch` turn every copy alike. A trajectory is worked out once for each file, chain,
seed and what is held -- in about a second for 300 residues -- and kept in memory and in
flexo's cache folder; any noise after that is drawn at once.

![Trees (examples/biology.py)](examples/build/trees.preview.png)

```python
figure.root.tree("mammals", "((Human:0.08,Chimp:0.09)100:0.37,(Mouse:0.35,Rat:0.33):0.3);",
                 support=True, italic=True,
                 clades=[{"tips": "Human, Chimp", "label": "Primates"}])
figure.root.tree("ring", newick, layout="circular")
```

`tree` reads [Newick](https://en.wikipedia.org/wiki/Newick_format): branch
lengths make a phylogram with a scale bar, a tree without them (or
`lengths=False`) a cladogram with its tips lined up. `layout="circular"` puts
the root in the middle, names on the ring. A clade -- the smallest subtree
holding the `tips` named -- is coloured by its name and bracketed beside its
tips; `support=True` writes support values by their nodes.

![A plate and a protocol (examples/biology.py)](examples/build/bench.preview.png)

```python
figure.root.wellplate("plate", [
    {"wells": "A1-A12", "label": "Control"},
    {"wells": "B-D", "label": "Drug, 1 µM"},
], wells=96)
figure.root.timeline("protocol", unit="day",
    events=[{"at": 0, "label": "Seed"}, {"at": 2, "label": "Induce"}],
    spans=[{"start": 2, "end": 5, "label": "Doxycycline"}])
```

`wellplate` draws 6, 12, 24, 48, 96, or 384 wells, each group's wells (a well
`A1`, a block `B1-D6`, rows `A-D`, columns `1-3`) filled in its condition's
colour, with a legend. `timeline` sets events as dots on a time axis, named
over it, and spans as bars under it, stacked where they overlap; `unit="day"`
writes "Day 2", `unit="h"` "2 h".

In a figure file each is a node kind -- `protein`, `tree`, `wellplate`,
`timeline` -- with the same names under `properties`.

### Reaction mechanisms

```python
figure.root.mechanism("hydrolysis", [
    {"smiles": "[OH-:5].[CH3:1][C:2](=[O:3])[Cl:4]", "arrows": ["5 -> 2", "2=3 -> 3"],
     "label": "acid chloride", "reagents": "NaOH", "conditions": "H$_2$O"},
    {"arrows": ["3 -> 2", "2-4 -> 4"], "label": "tetrahedral intermediate"},
])
```

A `mechanism` draws structures as chemists draw them and the curly arrows that join
them. Each step is SMILES -- the molecules apart with `.`, the atoms its arrows name
mapped (`[O-:5]`) -- and its arrows: from a lone pair (`"5 -> 2"`: atom 5's pair
makes a bond to 2), from a bond to an atom (`"2=3 -> 3"`: the π bond becomes a lone
pair on 3), a bond moved (`"1=2 -> 2-6"`), a fishhook for one electron (`"~>"`).

A mechanism may be schematic. A bracket atom whose symbol is no element is a
placeholder, drawn as it is written -- `[X]`, `[Nu-]`, `[E]`, `[LG]`, `[EWG]`, `[R']`,
`[R1]` (its digits raised: R¹), or `[*Ar]`, `[*B]` for a symbol that is also an
element's -- with any number of bonds and no hydrogens of its own. Its valence is
unknown, so it has a pair to give wherever an arrow starts from it and nothing is
refused on its account; its charge is kept all the same (X attacking ends X⁺, Z
taking a bond's pair Z⁻), and the real atoms beside it are checked as ever.

```python
figure.root.mechanism("sigma", [
    {"smiles": "[X:1].[Y:2][Z:3]", "arrows": ["1 -> 2", "2-3 -> 3"]},
])
figure.root.mechanism("pi", [
    {"smiles": "[Nu-:1].[E:2]=[Z:3]", "arrows": ["1 -> 2", "2=3 -> 3"]},
])
```

The arrows are not decoration: each moves electrons, and the next structure is what
they make -- a step with no SMILES is drawn from them, its atoms where they were, the
attacking molecule brought in beside the atom it bonds to, a leaving group set apart.
A step written out is checked against them. An arrow that cannot be is said in words:
carbon given ten electrons ("as a bond to it forms, another must break"), a lone pair
that is not there, a fishhook left without its partner, a hydrogen with two bonds.
A symbol that is no element is no longer refused, being a placeholder: check the
letters of what is drawn, since an element mistyped into none (`[Xx]` for `[Xe]`) is
drawn as it is written. Capitals where an element has a small letter (`[CL]`, `[BR]`)
are still refused, with what was meant, as are a small first letter (`[cl]`), a `*`
with no name, and hydrogens counted on a placeholder (`[XH2]`: write `[X]([H])[H]`).
After the last step with arrows comes what they make. With `partial=True` a step that
cannot be is drawn as far as it goes, its arrows on it, instead of refused (as it is
between one arrow and the next while a step is drawn); `flexo.mechanism.mechanism_states`
says what is wrong. In a figure file it is the node kind `mechanism`, its steps under
`properties.steps`, written as in Python: arrows a list or words apart with `;`, a
step's `place` a mapping or words (`"5 move -1 0.5 turn 30"`).

Structures are laid out flat as a chemist would: rings as regular polygons, fused rings
side by side, chains in a horizontal zigzag, every bond on the 30-degree grid, furan
and pyrrole standing on their heteroatom, a double bond keeping the side its SMILES
gives (`F/C=C/F`), a stereocentre drawn with the wedge or hash its `@`/`@@` means. A
cycloaddition is drawn in the shape of its product, so a diene curls s-cis. The
proportions are the ACS document settings: bonds 1.44 label heights long, double
bonds inside their rings, labels clipping the bonds that meet them, hydrogens on the
side the bonds leave free (`OH`, `HO`, `H₂N`), charges circled. Reaction arrows carry
their `reagents` over them and `conditions` under them; `arrow` is `forward`,
`equilibrium`, `resonance` or `none`; steps fold into rows when there are many
(`per_row=`).

The curly arrows are drawn by rule, in one ink: magenta, unless `arrow_colour=` gives
another -- a colour, or the theme's `ink`, `muted` or `accent` (`accent2`...), which
follow the theme.
An arrow carries its electrons: the lone pair (or radical) it starts from is drawn at
its tail, in its ink, out from the atom where its bonds leave room; an arrow from a
bond leaves square to it, a little off its middle. It goes into a bond square to it,
and into an atom along a radius -- on the side with room, facing the electrons, never
back down the bond they leave; a pair re-forming its own atom's double bond curls
from beside the bond down onto it, and two half arrows making a bond meet in its
middle from either side. Of the curves that would do, the smoothest is drawn that
crosses no bond, no other arrow and no charge, and bends one way only; charges move
out of the arrows' way. Other lone pairs are drawn with `lone_pairs="all"` (on a
placeholder, those arrows have left on it; as written it has none to show); a radical
is a dot. A step's `place` puts its molecules where you want them, each named by one of
its atoms: `{5: {"move": [-1, 0.5], "turn": 30, "flip": True}}` takes the molecule with
atom 5 a bond left and half a bond down from where it is laid out, turned 30 degrees
clockwise and flipped left for right.

### Grids of cells

![A plate map and a contact map (examples/cells.py)](examples/build/cells.preview.png)

```python
figure.root.cells("plate", """
    C C D1 D1
    C C D2 D2
    V V .  .
""", {"C": {"label": "Control"}, "V": {"label": "Vehicle", "mark": "v"},
      "D1": {"label": "1 µM"}, "D2": {"label": "10 µM"}},
    row_labels="letters", column_labels="numbers", lines="muted")
figure.root.cells("contacts", matrix, ramp=("#fbf6ee", "#7a1f1f"), values=True)
```

`cells` draws a grid written as text, one row per line and one symbol per word
(`.` leaves a cell empty), or given as rows of values. The key says what a
symbol is: a `color` (a tone by name, or an exact `#hex`, painted as written and
left alone by `flexo retheme`), a `mark` written small in the cell, and a
`label` for the legend; a symbol the key does not name takes a tone by its
name. Numbers are values: shaded along `ramp` (two colours, low to high) over
`range`, and written in their cells with `values=True`. `cell` sets a cell's
side in points, `gap` and `corner` how far inside its square it is painted and
how round; `lines` rules the grid; `row_labels` and `column_labels` number,
letter, or name the rows and columns, on the `row_side` and `column_side`
asked for. In a figure file it is the node kind `cells`, the grid under
`properties.grid` as text.

![After Alfred Jensen: two number squares, painted by hand (examples/jensen.py)](examples/build/jensen.preview.png)

[`examples/jensen.py`](examples/jensen.py) generates a page after Alfred
Jensen's number squares -- rings of colour around a centre, their counts
written around them and computed from the same rings -- and paints it with the
sketch theme's `gouache` fill.

### Operators and words

```python
m.add("sum", inputs=[a, b])              # a circle with a plus in it
m.multiply("gate", inputs=[value, gate]) # a circle with a times sign
m.op("pe", "~")                          # a sine: a positional encoding
m.op("z", "Σ", inputs=[mu, sigma])      # any other symbol, set as text
m.text("in", "Inputs")                   # words an arrow can start or end at
```

Each value arriving at an operator gets its own arrow into the circle, on the
side that faces where the value comes from. Three or more values from one
direction join on a bus and enter as one arrow. The symbols `+`, `x`, `-`, `.`
and `~` are drawn as strokes, so they sit exactly in the centre in any
typeface.

A value that enters an operator from the side -- a position embedding added to
a stream of tokens -- goes in a row with the operator. The row is aligned on
the operator, so the stream stays straight:

```python
with m.row("pe") as row:
    pos = row.text("pos", "Position embedding")
    total = row.add("sum", inputs=[projection, pos])
```

### Math in labels

Text between dollar signs is math, in a small subset of TeX:

```python
m.text("c", "$c_{t-1}$")               # subscript: one character, or {a group}
m.block("attn", label="softmax($QK^T$)V")
m.text("eps", r"$\epsilon \sim N(0, I)$")
m.text("out", r"$\hat{x}$")            # \hat, \bar, \tilde, \dot
m.text("h", r"$\vec{h}_1$")            # \vec, \overrightarrow, \overleftarrow
m.block("w", label=r"$W_{\text{out}}$")  # \text{} and \mathrm{} are upright
```

Latin letters in math are italic and digits are upright, as in TeX. `-` is a
minus sign. `\alpha` to `\omega`, `\Gamma` to `\Omega`, and common operators
and relations (`\times`, `\cdot`, `\sim`, `\in`, `\nabla`, `\to`, `\le`,
`\sum`, ...) become their symbols; `\log`, `\exp`, `\max` and the other named
functions are upright; `\mathcal{L}`, `\mathbb{E}` and `\mathfrak{g}` give
script, blackboard, and fraktur capitals. A superscript and a subscript on one
letter (`$\sigma^2_B$`) are stacked, as in TeX. `\sqrt{d}` is `√d`, and
`\frac{a}{b}` is set inline as `a/b`. `\vec`, `\overrightarrow` and
`\overleftarrow` draw an arrow centred over their whole argument
(`$\overleftarrow{h}$`, the backward state of a bidirectional network); Flexo
draws that arrow itself, because no bundled text face can place one.

Spacing follows TeX. A binary operator or a relation gets one space on each
side, whatever was typed: `$B=0$` and `$B = 0$` both give *B* = 0, and
`$d\times d$` gives *d* × *d*. There is no such space inside a sub- or
superscript (`$\mathbb{R}^{d\times d}$`), or around a sign that opens a formula
or follows `(`, `,` or another operator (`$-y$`). The space that ends a command
name is dropped (`$\alpha x$` is *αx*), and a named function is set apart from
its operand (`$\log p$`). Every other space is kept as typed. Write `\$`
for a literal dollar sign; a single `$` with no closing partner is also
literal. A script cannot contain another script.

A character that the figure's font does not have is set in the next font of the
fallback stack that does; the stack ends in IBM Plex Sans, Liberation Sans, and
Latin Modern Math, which together cover Greek and mathematical symbols. A
character no bundled font has (Chinese, Japanese, Arabic, ...) is taken from an
installed font that has it, and a run of such characters stays in that one
font. Colour emoji fonts are never used, because a figure is drawn from
outlines. A character that no usable font has is an error that names it. An
accent is kept with its letter: if the primary font has the accent but cannot
position it on that letter, the letter and the accent are both set in a
fallback font that can.

### Captions on connectors

`connect(a, b, label="action $A_t$")` puts a caption beside the line, and
`net(..., label=...)` beside a net. A caption names the value its edge carries,
so a captioned edge gets pins of its own and is drawn as its own line, even
next to another edge between the same two ports (unless the side is too short
for a pin each, when the edges share a stem).

Captions are placed after routing. The candidate places are above and below
each horizontal run and on either side of each vertical run, at the middle and
then toward either end; a branch out of a decision tries the places nearest the
decision first, so "yes" and "no" sit by the question. The caption with the
fewest clear places chooses first. A place is clear when it overlaps no
component, title, other caption, or line, and is not within a lane of another
connector, where it would read as that connector's caption. When no place is
clear the cheapest is taken: close beside another line, then outside the
canvas (which then grows), then over a line, then over a box. A caption left
with no clear place takes one from a caption that can move elsewhere.

Room for captions is made before they are placed: a line running over a
captioned edge keeps a caption's height from it, not just a lane, and a grid
leaves a caption's height in the row gap between diagonal neighbours joined by
a captioned edge. A caption that still finds no clear place asks for room --
on the side of its container's contents it sits above or below, or in the gap
between the two children it sits between -- and the figure is laid out again. Lint warns about any caption that overlaps a component, another
caption, or a line (`routing.caption.overlap`, `routing.caption.covers-line`).

### Node-link figures: circles and straight lines

```python
import flexo

with flexo.Figure("mlp", conventions={"lines": "straight"}) as figure:
    with figure.module("m", label="Multilayer perceptron") as m:
        with m.column("in") as column:
            inputs = [column.circle(f"x{i}", f"$x_{i}$", tone="input") for i in (1, 2, 3)]
        with m.column("hidden") as column:
            hidden = [column.circle(f"h{i}", f"$h_{i}$", tone="hidden") for i in (1, 2, 3, 4)]
        m.connect_all(inputs, hidden)
```

`circle` is a labelled circle. All circles in a figure without an authored
`width=` share one size, the size the longest label needs, so a reader does not
compare variables by the length of their names. `shaded=True` fills it grey,
the graphical-model mark for an observed variable. A straight edge is one
segment from outline to outline on the line between the two centres. In a
figure whose convention is straight lines, an edge whose straight line would
run through another component is routed round it instead. An edge made
straight on its own (`shape="straight"`) in a routed figure stays straight
wherever it goes, and lint reports what it crosses as
`routing.obstacle.intersection`. Two straight edges between the same pair run
side by side. Choose straight lines for a whole figure with
`conventions={"lines": "straight"}`, or for one edge with
`connect(a, b, shape="straight")`. `connect_all(sources, targets)` connects
every source to every target.

### Feature maps

```python
image = m.volume("input", (3, 224, 224), label="224×224×3")
conv = m.volume("conv1", (64, 112, 112), label="conv1", input=image, tone="conv")
```

`volume` draws a feature map as a box in oblique projection: the front face
is as tall as the map's height, the box as deep as its width, and as thick as
its channel count, each on a log scale so a whole network fits on a page.
`shape` is `(channels, height, width)`, or `(height, width)` for one channel.
The label is set under the box; arrows attach to the box.

### Flowcharts and architecture diagrams

```python
start = m.terminal("start", label="Start")          # a pill: start or end
data = m.io("data", label="Read batch", input=start)  # a parallelogram: input/output
step = m.block("step", label="Update weights", input=data)
done = m.decision("done", label="Converged?", input=step)  # a diamond
m.connect(done, start, label="no")
```

A process is a `block`, a start or end a `terminal`, a question a `decision`, and
data read or written an `io` parallelogram. A decision's diamond is sized round its
words; given a `width=` (or `height=`), it is that, and the other way as small as its
words let it be. In the studio, drag a shape's corner to size it: it snaps to the size
that fits its words (for a diamond, one that hugs them), and a double-click fits it. Text
has a handle at each side instead, as a Keynote text box has: drag one to set where its
words wrap (`width=`); it snaps back to the width they take of themselves, and stops at the
longest word. The shapes of a software diagram are
components too, each sized round its label and painted in the theme's roles, so a
palette, a tone, or a dark theme recolours them with the rest:

```python
user = m.person("user", "User")                # a head and shoulders, the name under them
web = m.cloud("web", "Internet", input=user)   # a cloud of round puffs
app = m.server("app", "App server", input=web)  # a box over two rack units
cache = m.database("cache", "Cache", input=app)  # a cylinder: a database, any store
jobs = m.queue("jobs", "Jobs", input=app)      # a box whose end is divided into slots
m.document("report", "Nightly report", input=jobs)  # a page with a wavy foot
```

A line meets each of these at its drawn outline, not at the box round it: arrows
into a database from above stop just short of its lid wherever they land on it,
a line leaves an `io` from its slanted side and arrives under a document's wavy
foot, and a straight line ends on a cloud's puffs. A person takes lines at its
shoulders from either side, over its head from above, and under its name from
below. Each draws as plain paths, so the editable SVG, the PDF, and a slide's
PowerPoint keep them as shapes.

A line meets a circle or a diamond only at the middle of a side of its box,
which for a diamond is a corner. Each line gets a corner of its own while
corners last. A line in line with the diamond chooses first, then the line to
the nearest neighbour, so the flow keeps its corners: the "no" of a loop leaves
by a side corner, not by the top corner its input came in by, and a loop back
from far down the chart comes in by a corner the flow does not use.

### Line styles and arrowheads

```python
m.connect(x, z, line="dashed")                  # or "dotted"
m.block("cache", label="Cache", line="dashed")  # a shape's outline takes one too,
m.group("later", label="Later", line="dotted")  # and a group's, and a frame's
m.connect(top, bottom, arrow="none", label="shared weights")  # undirected
m.connect(a, b, arrow="both")
m.connect(a, b, shape="curved")                 # one smooth curve
m.connect(a, b, width=2, head_size=1.5)         # 2pt wide, heads larger again
```

`line=` changes only the stroke. `arrow=` says where the arrowheads go:
`"end"` (the default, at the target), `"none"` for an undirected link, which
then meets both components, or `"both"`. Nets take `line=` too.

`shape="curved"` draws one smooth curve from the side of the source that faces
the target to the side of the target that faces back. It bows away from the
middle of the figure (round a cycle, outwards), else to the left of its travel,
so two curves between one pair, one each way, bow apart; `via="south"` bows it
that way instead, and `depart=` and `arrive=` sides make it leave and meet those
sides square, as a hand-drawn arrow does. `bend=` says how far it bows: its
middle stood off the straight line between its ends by that share of the line's
length, to the left of its travel (`0.3`) or the right (`-0.3`); `lean=` moves that
middle along the line, toward its target (`0.25`) or its source (`-0.25`). In the
studio, drag the handle on a curved or straight line's middle anywhere: the curve
passes through it, and it snaps half way between the ends, to straight, to where
the line bows of itself, and level with either end (hold ⌘ to place it freely -- or, with
snapping turned off by Snap (the magnet) in the toolbar, to snap it;
double-click it to let the line bow of itself again). Where a curve bows out of its
container, the container makes room for it, as it does for any line.

`width=` draws a line wider or thinner than the theme's, in points, and its
arrowheads grow and shrink with it, as a drawing program's do; `head_size=`
scales the heads on top of that (`1.5`, half as large again). In the studio
they are a line's **Routing**, **Line Width** and **Arrowhead Size**.

`head=` draws a line's head in a shape of its own: one of the theme's arrow
shapes by name, whatever the theme (`"triangle"`, `"stealth"`, `"latex"`,
`"open"`), an outline triangle (`"hollow"`), or a filled `"dot"`, `"diamond"` or
`"square"`; the SBGN heads (above)
say what a line does. With `arrow="both"`, `tail=` gives its start a head of
its own (`connect(a, b, arrow="both", head="triangle", tail="dot")`). In the
studio they are **Arrowhead** and **Start Arrowhead**, each shown as it looks.

`connect(a, a)` draws a loop: a recurrent cell's state fed back to itself, a
state that can stay where it is. It goes on the component's emptiest side.

### Layout groups

A `row`, `column`, or `grid` without a label is a layout group
(`role="layout"`): it arranges its children and draws nothing. Give it a
`label` and it is a titled container instead. Layout adds a few rules of its
own:

- A layout group has no padding unless you give it one, so the space between
  its children and its neighbours is exactly its `gap`.
- `layout="flow"` (top to bottom) or `layout="flow-right"` (left to right)
  arranges a group's children from their wiring, so they can be written flat,
  with no rows or columns: each goes one layer after whatever feeds it, and
  each layer is ordered to avoid crossings. A loop back, or a link with no
  arrowhead, does not reorder the layers. `Figure(..., layout="flow")` does
  the same for what sits directly on the figure.
- `layout="cycle"` places a group's children clockwise, in the order written,
  round the border of the squarest grid that holds them: the steps of a
  lifecycle or a metabolic cycle, each beside the next.
- `reverse=True` places a row's or column's children last-first. A stream that
  flows upward is written in the order its values flow -- image, encoder,
  projection -- and drawn from the bottom up.
- Columns side by side that are not wired to each other are parallel branches,
  and are aligned at the top.
- Two rows stacked in a column, with the same number of children and child *i*
  of one wired to child *i* of the other (and to nothing else in the pair),
  are laid out as one grid, so each child sits over its partner. The same holds
  for two columns side by side.
- A figure wider than its page first gets tighter gaps and group padding (down
  to half), and only then a wider page, with a `layout.width.grown` warning.
  A figure compiled with an explicit `style=` keeps its spacing exactly.
  A figure taller than a page with a `height` is treated the same way
  (`layout.height.grown`).

### Lines to a group

A line may start or end at a group, as at a shape -- everything going in, the cell,
everything coming out, where an arrow from one of the molecules would read as though it
came from that one alone:

```yaml
groups:
- {id: substrates, role: layout, layout: {kind: grid, columns: 3}, children: [acv, plus, oxygen]}
- {id: products, role: layout, layout: {kind: grid, columns: 4}, children: [ipn, plus2, two, water]}
edges:
- {from: substrates, to: cell}
- {from: cell, to: products}
```

It meets a group drawn with an outline (a module, a titled box) at that outline, and a
group that draws none (a layout group, a panel) at the box round what it holds, its
arrowhead as far short of those parts as it would stop short of one of them -- at the
middle of the side that faces its other end, or of the side `depart` or `arrive` names.
Such a line moves nothing: the figure is laid out without it and the line routed to the
group where the layout put it, never in among the group's parts on its way. In Python,
`connect()` takes a group (the `module`/`group` you made, or its id) as it takes a shape.

A line between a group and a part or group it holds has no way to it from outside, and is
refused (`group.line.inside`); so is one to the figure's own root, and one to a port of a
group, which has none (`substrates.top`: write `substrates` with `depart: north`). A line
naming neither a part nor a group of the figure is said in plain words, with the ids it
may have meant. A line to a group is hidden or dimmed with the group, turned and folded
with the figure on a slide, and in a deck's builds appears with the last of what the group
holds. In the studio, choose a group and **Connect** draws a line from it to what you
click next (a click between a group's parts is the group's); the line is listed by its
ends -- **Substrates → Cell**, a group or part with no words of its own called by its name
in the file -- and its **From** and **To** offer the groups beside the shapes.

### Pages and panels

A figure's page is its `width` and, for a page of a fixed size, its `height`;
without a height the page is as tall as the figure. `page=` names a size
instead: a journal's column (`"nature-1"` is 89 mm, `"nature-2"` 183 mm,
`"science-1"`, `"science-1.5"`, `"science-2"`, `"cell-1"`, `"cell-1.5"`, `"cell-2"`,
`"pnas-1"`, `"pnas-1.5"`, `"pnas-2"`), a
journal's whole page (`"nature-page"`, 183 × 247 mm), or a sheet of paper
(`"a3"`, `"a4"`, `"a5"`, `"letter"`); `flexo.PAGE_SIZES` lists them. In a file
the size is written as its lengths (`width: 183mm`, `height: 247mm`).

A figure of several panels, as a journal prints one, is made of `panel`s: a
panel is a group with no frame, lettered where a title goes. The letters run in
the order the panels are read, so none is written, and a panel moved takes the
letter of where it is now.

```python
with flexo.Figure("study", page="nature-2", layout="row") as figure:
    with figure.panel("model") as model:  # a
        x = model.text("x", "Input $x$")
        model.block("encoder", label="Encoder", input=x)
    with figure.panel("readout", "Read-out") as readout:  # b, with a title after it
        readout.block("head", label="Head")
```

`Figure(panel_labels="A")` letters them A, B, C, and `"(a)"` or `"(A)"` in
brackets. Panels in rows and columns are a grid:
`layout=flexo.LayoutSpec("grid", columns=2)`. In a file a panel is a group with
`role: panel`, and the root group lays the panels out
(`layout: {kind: grid, columns: 2}`).

### Frames: a box round shapes anywhere

A group holds what stands together, and arranges it. A **frame** arranges nothing: it
names the shapes and groups it goes round, wherever in the figure they are, and is drawn
round them where the layout put them -- behind them, as an outline in front of them, or
over them as a tint they show through.

```yaml
nodes:
- {id: shared, kind: frame, label: Shared weights, properties: {around: "encoder, decoder"}}
- {id: frozen, kind: frame, properties: {around: "left", layer: over, tone: 4}}
```

`around` lists ids of shapes or groups; `layer` is `behind` (the default), `front` or
`over`; a frame takes a `label`, a `tone`, `paint` and a `line` (`dashed`, `dotted`) as
a shape does. It is centred on what it holds and takes no room, but for its title: a
band is kept clear over the shape at the frame's top, and room beside the frame where a
long title widens it, so the title lies on nothing -- where an arrow comes down into the
frame, it ends short of the arrow. Behind shapes that stand in filled groups, a frame is
drawn over those groups' own fills, so it shows.

The title stands at the frame's top left. `title_side` in its properties names another
corner, in the words a group's `title_side` takes: `right` (the top right), `bottom-left`
or `bottom-right` -- for a frame whose top shape has a line going up from it, say, where
no title along the top would be clear of the line:

```yaml
nodes:
- id: stage
  kind: frame
  label: Generation
  properties: {around: "sample, refine", title_side: bottom-left}
```

At the bottom its band is under the shape at the frame's bottom, so what is below makes
way and nothing above does; at the right it ends at the frame's right, and starts past a
line through its band. Any other word is said, and the title drawn at the top left.

A line may start or end at a frame, as at a shape -- from a shape the frame does not go
round:

```yaml
edges:
- {from: restraints, to: stage, arrive: south}
```

It meets the frame's outline, its arrowhead on it, at the middle of the side that faces
its other end, or of the side `arrive` names (`depart`, where it leaves a frame):
`north`, `south`, `east` or `west`. Several lines on one side each have a place along it,
as on a box's, clear of any line that goes through that side to a shape inside; and a
line that ends at the frame never runs inside it. Such a line moves nothing: the figure
is laid out without it, and every other line goes through the frame as before. Between a
frame and a shape it goes round there is no way from outside, and the line is refused
(`frame.line.inside`). A line that branches (a net) may end at a frame too; a line to a
frame that is hidden or dimmed is hidden or dimmed with it.

### Shapes drawn over a figure: arrows, rings, braces, labels

What used to be drawn on a finished figure in Inkscape -- an arrow pointing at a part, a
ring round some, a brace and its words beside a stack, a highlight behind a word, a
dimension line, a box of words -- is the figure's own `shapes`, drawn over it where they are
put and taking no room in its layout. Each is written as a slide's shape is
(`flexo.freeform`: the same kinds and settings, so a shape copied from a slide pastes onto a
figure, and back):

```yaml
shapes:
- {kind: ring, around: [encoder]}                          # round a part, as it is laid out
- kind: arrow
  from: [20, 10]
  to: {part: decoder, side: top}                           # glued to a part's side
  text: here
- {kind: text, on: decoder, at: [0, -16], text: bottleneck} # on a part: moves with it
- {kind: brace, around: [x, encoder], text: front end}     # a brace beside them, on their right
- {kind: highlight, around: [latent], behind: true}       # a backdrop the part stands on
```

Places are the figure's points, y down, from its top left as it is laid out. Since the
layout moves parts as a figure is edited, a shape is best attached to them, by id -- a shape,
a group, a frame, or a piece of one its drawing names (a protein's feature `spike.feature2`,
a tree's tip `tree.tip3`): a line's end glued to a part, `{part: id, side: top}` (a side's
middle, `centre` to stop at its box, or, left out, the side facing the other end; `at` keeps
where it was, should the part go); a whole shape `on` a part, its places from that part's top
left; or a shape `around` parts, sized round them `margin` points out -- a ring through the
corners of their box, a brace, a bracket or a dimension along their `side` (`right` for a
brace unless said). A part named that the figure does not have is a warning, not an error:
an end stays where it was, a shape on it is drawn from the figure's top left.

Shapes are painted by the figure's palette (`accent` is its first tone, `accent2-fill` its
second's tint, `muted`, `ink`, `paper`, `grey`, or `#rrggbb`) and their words are set in its
font, at its size unless they say; they are drawn over everything, in the order listed (or,
`behind: true`, under the parts, over the box of the group that holds them: a backdrop they
stand on), and the page grows to hold one that reaches past it, on any side, moving nothing. The figure's `hide`, `dim` and `highlight` name a shape by its `id`, as
they name parts; a shape attached to parts is shown as they are unless it is named itself.
In Python, `figure.shape("ring", around=["encoder"])`, `figure.shape("arrow", from_=[20, 10],
to={"part": "decoder"})`.

In the studio, Draw in the figure's toolbar offers every kind: drag on the figure to draw
one (a click makes it its usual size -- or, for a ring, a highlight, a box or a brace, a click
on a part draws it round that part, a filled one behind it so that it hides nothing), and it
is moved, sized, turned, bent, glued, styled, grouped, stacked and copied as on a slide,
catching at the parts' edges and middles as it goes -- unless Snap (the magnet) in the toolbar
(or %) has turned snapping off, when nothing catches, a line's end is glued only with ⌘ held,
and a part's handles snap only with ⌘ too. **#** (or Grid in the toolbar, or View ›
Show Grid) draws graph paper over the figure, its squares sized to it; snapping to the grid
(the magnet's next turn after guides, or View › Snap to Grid), a shape catches at its lines
instead. A shape drawn on a part is put on it, and moves
with it; its panel's **Moves With** chooses
another part, or none, and **Drawn** puts it in front of the parts or behind them.

The figure's parts and the shapes drawn over it are one choice, as Keynote's objects are:
⇧-click (or ⌘-click) a part with shapes chosen, or a shape with parts chosen, and both are
chosen ("2 Shapes, 1 Drawn Shape"); a band across both chooses what it touches of each.
Together they are deleted (⌫), cut, copied and pasted (⌘X, ⌘C, ⌘V: the parts pasted as
parts, the shapes as shapes), and duplicated (⌘D) -- each one step, named for both, both
chosen again by its undo -- and the inspector offers that, with Align and Distribute for the
shapes, the parts among what they line up with. The arrows nudge the shapes; the parts are
laid out, and move as they do alone. On a slide, a figure being edited is the same with the
slide's shapes over it.

A group of shapes -- one made with ⌘G, or a drawing pasted from Inkscape, with its groups
inside it -- is entered as Inkscape enters one: double-click it (or choose it and press
Return, or Enter Group in its right-click menu and the palette). Its shapes are then the
figure's to click, drag, size, turn, restyle, retype, copy, nudge, lock and delete one by
one, each change written back into the group as one step; a group in it is entered by another
double-click, and ⌥-click chooses the shape under the pointer however deep in groups it is. A
dotted frame shows the group, and a chip over the page names where one is (Figure › Group
› Group): each level a way back to it, ✕ out a level. Esc steps out a level once nothing in
it is chosen, the group then chosen; a click on empty space, or a double-click, leaves it,
and a click on a shape outside it chooses that one instead. Undo and redo stay inside.
**Ungroup All** (the right-click menu, the palette, the Mac app's Arrange menu) takes the
groups chosen apart at every level at once; a shape in a group may be written
`locked: true`, as one on the figure may.

### A shape's words, and a picture's crop

A shape says how the whole of its label is set, in its properties: `bold: true`,
`italic: true`, `size: 6pt` and `align: left` (or `right`). The size is what the
label is measured at, so the shape is the size for it. In the studio a shape (or
several chosen) has a **Text** section -- Bold, Italic, the side its lines stand at,
and Size -- and ⌘B and ⌘I work on shapes chosen. Single words are bold or italic as
coloured words are written: `[word]{bold}`, `[lacZ]{italic}` (a label's asterisks are
drawn as typed); ⌘B and ⌘I do it to the words chosen while a label is typed.

A picture in a figure is cropped by how much is cut off each side, in hundredths:
`crop_left: 10`, `crop_top`, `crop_right`, `crop_bottom`. It is as large as the part
kept.

An SVG picture's words -- a drawing pasted from Inkscape, say -- are set in the figure's
font, so the studio, the PNG, the PDF and every viewer draw the same face, and the picture
grows to hold them should they reach past its page. Its properties may say otherwise, and
change its words and colours without touching its file:

```yaml
- id: sketch
  kind: image
  properties:
    source: assets/sketch.svg
    font: drawn                 # the faces the file names (as found); or a family
    texts:                      # by the text's id in the file (with none: text: 3)
    - {id: text1, words: "Encoder\nblock", size: 20, bold: true, colour: "#c0392b"}
    colours: {"#4a90d9": "#2e7d32"}   # every use of a colour, drawn in another
```

A text's size is in points at the drawing's own size. The file stays as its program wrote
it, to be opened there again; a change to a text it no longer has is passed over. In the
studio its panel has **Words** -- the font, and each text's words, size, bold, italic and
colour, in the order they are read -- and **Colours**, a well for each colour it is painted
in.

### Plots in a figure

A paper's figure has plots among its diagrams. A `plot` names a Python file and a
function in it that returns a matplotlib figure (`pip install "flexo[plots]"`):

```yaml
- id: loss
  kind: plot
  properties: {source: plots.py, function: loss}
  width: 60mm
  height: 40mm
```

```python
panel.plot("loss", "plots.py", "loss", width="60mm", height="40mm")
```

The function is called with matplotlib set to the figure's look -- its font and
size, its inks, the palette's tones as the colour cycle (`flexo.plots.plot_style`)
-- and what it returns is laid out again at the shape's own size, so its words
are the size of the figure's words whatever the panel's size. It is drawn as
vectors, its words kept as words. Name data from the file's own folder
(`Path(__file__).parent / "loss.csv"`), so it is found wherever the figure is
drawn.

A plot is drawn again only when its size, the figure's look or something it is
drawn from changes:

- its Python file, and the modules it imports from beside it;
- the files its function read, however they are opened (`open`, numpy, pandas),
  in a thread it starts too;
- the folders it listed (`glob`, `os.listdir`, `os.scandir`, `Path.iterdir`):
  one more file where it looks is a change;
- the files its Python names in so many words -- `"loss.h5"`,
  `HERE / "runs" / "a.parquet"`, a pattern `"runs/*.h5"` -- which is how a file
  read by a library that opens files for itself (HDF5, Parquet) is seen at all.

What none of these shows -- a name put together as the function runs -- the plot
names as its `data`: files, folders (all that is in them) or patterns, from the
figure's folder.

```yaml
- id: loss
  kind: plot
  properties: {source: plots.py, function: loss, data: [loss.h5, "runs/*.parquet"]}
```

```python
panel.plot("loss", "plots.py", "loss", data=["loss.h5", "runs/*.parquet"])
```

Only files in the folder count -- the studio's, or outside a studio the Python
file's -- and never Python's own, a font, or anything in a hidden folder.

In the studio, **Shape › Plot** asks for the file and takes its first function.
**Function** is a pop-up of the functions the file offers, and a plot given
another file keeps its function's name if that file has it. **Data** (under
More) is its `data`, the names with commas between them. A corner dragged sets
its width and height, in the unit they are written in (⇧ keeps its proportions;
double-click for the size a plot has of itself). The figure redraws when the
Python file, or data it read, is saved, and when a file is put where it looks.

A figure that names Python runs it when it is drawn: in a studio, only in a folder
you have trusted. Not run -- or with matplotlib missing, or the function failing
-- the plot is an empty box and a warning that says why, and the rest of the
figure is drawn. In Flexo Studio (and any studio with flexo-talk installed) the
function runs in a process of its own, as a deck's Python does: one that takes
longer than 30 seconds is stopped, one that crashes takes only that process with
it, and the plot says which. The 30 seconds are the function's own, counted once
Python and matplotlib have started. A plot that was stopped is not run again
until its Python file changes, at whatever size or in whichever figure; and
while it runs it holds up nothing else: the folder's other plots, and its other
documents, are drawn meanwhile.

### Hiding, dimming and highlighting parts

A talk shows one figure many times: all of it, then one part with the rest faint, then
that part alone. Each is the same figure, laid out the same way -- nothing moves --
drawn with some of it left out:

```yaml
figure:
  id: pipeline
  hide: [store]            # not drawn, and its place kept
  dim: [queue, worker]     # drawn faint
  highlight: [api]         # these at full strength, and the rest faint
```

Each lists shapes, groups (all they hold), lines or frames by id; in Python,
`Figure("pipeline", hide=[...], dim=[...], highlight=[...])`. A line is shown as the
less shown of its two ends is. What is faint is drawn in colours nearer the page's
(not see-through), so it is the same in a PDF and a PowerPoint as on the page; what
is hidden is in no export. In the studio a shape's **Show** is Shown, Highlight,
Dimmed or Hidden (a hidden part is a ghost while its figure is edited), and
**Show All** brings everything back.

### Laying a figure out for a box (slides, posters)

A figure is written for a page, which is taller than it is wide. To place one
in a box of another shape -- a 16:9 slide, a poster panel -- let flexo lay it out
for that box rather than shrinking the page layout into it:

```python
fit = flexo.fit_in_box(figure, 864, 380, words=13, largest=20)   # points
fit.layout      # "as written", "turned", "turned within", each maybe ", tighter"
fit.words       # the size its words are drawn at in the box
fit.compilation, fit.scale, fit.ink              # what to draw, and where
```

It compiles the figure where its words are `words` points once drawn, measures
its ink, and tries it as written, **turned** (`flexo.turned(spec)`: rows become
columns, a stack that reads upward reads left to right, grids transpose, ports
and hints turn with it, vector glyphs lie down), and with tighter spacing --
keeping the most natural layout whose words come within 12% of the largest.
When none sets the words at their size, long rows and columns are **folded**
onto two lines (`flexo.orient.wrapped`) -- if that sets them at least 30% larger,
since a fold changes how the figure reads.
Measured sizes rank the candidates, so only layouts that could win are routed.
[flexo-talk](https://github.com/jamaliki/flexo-talk) lays every slide figure out
this way.

## Themes, palettes, and fonts

A **theme** is one name for a whole look -- typeface, line weights, corners,
arrowheads, how a module draws its boundary, and the rules that turn colours
into paint. A **palette** is the colours. They compose: every theme takes every
palette.

```python
flexo.Figure("f", theme="paper")                               # the default
flexo.Figure("f", theme="tikz")                                # a LaTeX/TikZ figure
flexo.Figure("f", theme="dark", background=True)               # slides, on navy
flexo.Figure("f", theme="swiss", font="Helvetica")             # any installed font
flexo.Figure("f", palette=["#2a6f97", "#e76f51", "#2a9d8f"])   # your own colours
```

| Theme | Look |
| --- | --- |
| `paper` | Journal default: Figtree, pastel boxes with same-hue outlines, Stealth arrows |
| `tikz` | A TikZ figure in a LaTeX paper: Latin Modern, hairlines, 10% tints, dashed module boxes |
| `slides`, `dark` | Projection scale: 12 pt type, heavier lines, 16:9 widths; `dark` on navy |
| `archive` | A 1970s technical report: cream page, Helvetica, hairlines, one accent, greys |
| `print` | Bertin: ink only, kinds told apart by lightness, never by hue |
| `swiss` | International Typographic Style: red and black, section rules instead of boxes |
| `bauhaus` | Primary colours as solid fills, heavy outlines, capitals |
| `midcentury` | Brick, teal and mustard on warm paper, hard offset shadows |
| `sketch` | Drawn by hand: wandering ink lines, watercolour washes on cream paper, Kalam lettering |
| `rams`, `economist` | Quiet greys and one signal colour; a news graphic with red section bands |
| `classic` | Flexo's original look, kept exactly |

Every figure's SVG is **transparent**: the theme's page colour is used to
choose fills and contrast, but the page itself is left unpainted, so the figure
sits on whatever it is placed on. `Figure(background=True)` paints the theme's
page colour (the cream of `archive` or `sketch`, the navy of `dark`), and
`background="#ffffff"` paints any colour.

The themes follow the modes of [labviz](https://github.com/jamaliki/labviz), and
the palettes are design-corner's, the same ones labviz plots with, so a diagram
and the plots beside it read as one figure. `flexo themes` lists them all;
`flexo build figure.yaml --theme tikz --palette "Deep Sea Harvest"` overrides a
figure's own choice from the command line.

### Your own theme, in a file

A look of your own -- a lab's, a journal's -- is a YAML file that starts from
any theme and changes what it likes:

```yaml
theme:
  name: lab
  base: paper
  font: Helvetica
  type: {size: 7.5pt}
  palette: ["#1d4e89", "#f26419", "#2a9d8f"]
  style: {corner_radius: 1.5pt, arrow_shape: latex}
  conventions: {branch: dot}
palettes:
  Lab warm: ["#9b2226", "#ca6702", "#ee9b00"]
```

A theme set in faces Flexo does not ship brings them with `fonts: [fonts/]`
beside `theme:` (files or folders, found from the theme file), and its palette
is used in the order written: the first colour is the accent.

`Figure(theme="lab.yaml")` uses it (so does `theme: lab.yaml` in a figure file,
and `flexo build ... --theme lab.yaml`), `flexo.register_theme("lab.yaml")`
makes it `theme="lab"`, and a directory named by `FLEXO_THEME_PATH` makes every
theme and palette in it available everywhere. `uv run flexo theme paper -o
lab.yaml` writes out every setting a theme has, as a file to start from.
Palettes can be registered on their own: `flexo.register_palette("Lab",
["#..", ...])`, or a file of `palettes:`. A setting a theme does not have is
refused with the nearest one it does (`extends:` → `base:`), never ignored.
Right-to-left text (Persian, Arabic, Hebrew) is ordered by Unicode's bidirectional
algorithm (`flexo.bidi`), English words and formulae inside it included, and set
in one face per script (Vazirmatn, Noto Sans Arabic, or Geeza Pro, whichever is
installed first).
`[words]{accent}` paints words in a colour (`accent2`..., `muted`, a palette role, or
`#rrggbb`). `[words](https://...)` in a label is a link -- clickable in the SVG, the PDF, and
flexo-talk's PowerPoint -- set in the accent colour.
Code between backticks in a label (`` `fit()` ``) is set in `type: {mono_family: ...}`,
or the first installed of JetBrains Mono, Menlo, Consolas, DejaVu Sans Mono, ....
`type: {math_family: Latin Modern Math}` sets maths symbols and italic Greek
in a maths font, as TeX does (the `tikz` theme does this).
`type: {figure_family: IBM Plex Mono}` sets the words of figures in a family of
their own -- a deck's figures in a monospace face, its slides in the theme's
`font` -- and `type: {title_family: ...}` a deck's slide titles and headings; a
figure with a `font` of its own keeps it. In the studio a theme's settings are in
tabs -- **Colour**, **Type** (a font for the text, and for titles, figures, code
and maths apart from it), **Shapes** and **Layout**. The
[tutorial](docs/tutorial.md#12-your-own-theme-and-palette) lists every key.

### Drawing by hand

`theme="sketch"` draws a figure the way an illustrator would, after
[mol-sketch](https://github.com/jamaliki/mol-sketch): every line in two
wandering strokes, every box coloured in with a watercolour wash, on cream paper,
lettered in Kalam. Any other theme can be drawn by hand too, keeping its own
type and colours:

```python
flexo.Figure("f", theme="sketch")                                  # the illustrated look
flexo.Figure("f", theme="paper", sketch=True)                      # paper, drawn by hand
flexo.Figure("f", theme="sketch", sketch={"fill": "hatch"})        # pencil hatching
flexo.Figure("f", theme="sketch", sketch={"fill": "gouache"})      # opaque paint, brushed
flexo.Figure("f", theme="sketch", sketch={"roughness": 0.2})       # a careful hand
```

The drawing is done after layout, so a sketched figure has exactly the clean
figure's geometry: boxes stay where they were, arrows still end on them, text
stays live and editable. Each line is seeded from its element's id, so a figure
draws the same way every time. The settings (`flexo.Sketch`) are:

| Setting | Default | Meaning |
| --- | --- | --- |
| `roughness` | `0.5` | How loose the hand is: 0 is a ruled line, 1 a quick sketch |
| `passes` | `2` | Strokes per line: the line, then lighter strokes going back over it |
| `fill` | `"wash"` | `"wash"` (watercolour), `"hatch"` (pencil lines), `"solid"`, `"gouache"` (opaque paint with the brush's streaks and uneven density), or `"none"` |
| `paper` | `true` | A few faint stains over the page, as on worked paper |
| `seed` | `0` | Another number draws the same figure with a different hand |

In YAML the same settings go under `sketch:` on the figure (`sketch: true`
for the default hand).

**Fonts** resolve by family name, and whatever Flexo measures with is what the
SVG, the PDF and the PNG are drawn in. IBM Plex Sans, Figtree, Liberation Sans
(metric-compatible with Arial and Helvetica), Latin Modern Roman, Latin
Modern Math, and the handwriting faces Kalam and Caveat (Latin only) ship with
Flexo and work everywhere; any installed family works by
name, and `flexo.register_font("path/to/Face.ttf")` (or `FLEXO_FONT_PATH`) adds
a file. Characters a family lacks -- Greek in Figtree, say -- fall back to the
next family that has them, measured in the face that will draw them. Bundled
faces are embedded in the SVG, cut down to the characters the figure uses, so
an editable SVG is tens of kilobytes rather than a megabyte and a half; the PDF
embeds its own subsets and the portable SVG and PNG draw the glyphs' outlines,
so no output ever falls back to a substitute face.

### Colour by kind

Each kind of component takes a colour of its own -- the next palette colour for
each kind a figure uses -- so every attention block is one colour, every
add-norm another, and they match wherever they appear. A plain `block` is
neutral until you give it a tone:

```python
tower.block("ff", label="Feed Forward", tone="ffn")   # every "ffn" block matches
tower.block("lin", label="Linear", tone=3)            # the palette's third colour
tower.attention("mha", tone="neutral")                # take a kind's colour away
```

Tones are paint roles (`tone-1-fill`, `tone-1-stroke`, ...), so `flexo retheme`
recolours a finished SVG without touching its geometry.

**Badges** mark what is frozen, trained, or fine-tuned, as papers do: a small
snowflake, flame, or lightning bolt drawn on the box's top-right corner.

```python
m.block("encoder", label="Vision encoder", badge="frozen")    # a snowflake
m.block("projection", label="Projection", badge="trained")    # a flame
m.block("llm", label="Language model", badge="tuned")         # a lightning bolt
m.legend(badges={"frozen": "frozen", "trained": "trained", "tuned": "fine-tuned"})
```

The marks are vector paths, not emoji, so they look the same in every
renderer, in print, and drawn by hand in the `sketch` theme.

`m.legend()` keys the colours: a swatch and a name for every tone the
components created so far are painted in. Pass `entries={"encoder": "Encoder
blocks", ...}` to choose the tones and their words, and `layout="column"` to
stack the entries.

## Conventions: branches, merges, arrivals, lines, and pins

Papers draw lines by different conventions, and Flexo lets a figure choose.
Lines meet in three ways; the defaults are:

- **Branch.** A value read by several components is drawn as one tree that
  forks with a plain T. There is no dot.
- **Merge.** Where two lines join into one (`merge(...)`), the joining line
  ends in an arrowhead that points into the line it joins. A merge of three or
  more lines is a bus: the lines meet it with plain Ts, and the only arrowhead
  is the one into the destination.
- **Arrivals.** Several connectors that end at the same port each get their
  own arrow, spread along the side of the box. They are not joined.

If the lines combine by an operation, author the operation with `add`,
`multiply` or `op`. It is then drawn as a circle, and the arrows point into
it. A fourth convention, `lines`, chooses between routed right-angled lines
(the default) and straight ones. A fifth, `pin_spread`, sets where arrows meet
a side: the central `pin_spread` of the side (0.8 by default) is cut into
equal shares, one per arrow, and each arrow meets the side at the middle of its
share. One arrow meets the middle of the side; two meet it at 30% and 70%. An
arrow still moves off its place when that lets it run straight to the box it
faces.

Change a convention for a whole figure with `conventions=`, or in YAML with a
`conventions:` mapping on the figure:

```python
flexo.Figure("f", conventions={"branch": "dot"})     # a dot on every fork
flexo.Figure("f", conventions={"merge": "plain"})    # no arrowheads at joins
flexo.Figure("f", conventions={"arrivals": "joined"})  # join before the port
flexo.Figure("f", conventions={"lines": "straight"})     # diagonals, not routes
flexo.Figure("f", conventions={"pin_spread": 0.5})       # arrows nearer the middle
```

| Convention | Values (default first) |
| --- | --- |
| `branch` | `"plain"`, `"dot"` |
| `merge` | `"auto"`, `"arrow"`, `"plain"`, `"dot"` |
| `arrivals` | `"separate"`, `"joined"` |
| `lines` | `"orthogonal"`, `"straight"` |
| `pin_spread` | `0.8`, or any number from 0 to 1 |

A theme can carry its own conventions (`LayoutStyle.conventions`). A net's
`joint="arrow"` or `joint="dot"` overrides the conventions for that one net.

## How connectors are routed

Routing follows the routers that draw connectors well (libavoid, ELK, yFiles).
It never fails for lack of a path: if a figure is too tight for its
connectors, it is laid out again with the room they need. A hint that cannot
be honoured is reported as a warning, not an error. (A `lane=` or waypoint
that names nothing in the figure is still an error.)

The steps -- pins, search, rip-up and reroute, separation, uncrossing, and
room -- and the hints that steer them (`via=`, `rail=`, `rail_at=`, `lane=`) are
described in [docs/routing.md](docs/routing.md).

## Documentation

- [Tutorial](docs/tutorial.md): figures step by step, from a first box to a
  themed, hand-drawn panel, and a table of where each choice lives.
- [SKILL.md](SKILL.md): the whole of it on one page -- the loop, the calls, the
  habits that make figures read well -- for a person or an assistant.
- [Authoring guide](docs/guide.md): every component, grids and alignment,
  vector glyphs, band rows, paint and retheming, artwork, shadows, export
  formats, and which palette role paints what.
- [Routing](docs/routing.md): how connectors are routed, and nets, rails, and `via=`.
- [Architecture](docs/architecture.md): the compiler's passes and modules.
- [Examples](examples/README.md): the scripts in `examples/` and what each shows.

## Command line

```bash
uv run flexo build examples/vertical_slice.yaml --output examples/build
uv run flexo build examples/vertical_slice.yaml --theme tikz --palette "Okabe-Ito"
uv run flexo build examples/vertical_slice.yaml --font "Helvetica"
uv run flexo check examples/vertical_slice.yaml
uv run flexo inspect examples/vertical_slice.yaml
uv run flexo gallery --output examples/build
uv run flexo themes                      # themes, palettes, and bundled fonts
uv run flexo retheme build/slice.editable.svg "Deep Sea Harvest" -o build/slice.recoloured.svg
uv run flexo schema
uv run flexo studio                      # edit this folder's figures and themes in the browser
uv run flexo studio mcp                  # the studio's tools for an agent (MCP over stdio)
uv run flexo bundle figure.yaml -o figure.flexo   # the figure and every file it names, as one file
uv run flexo unbundle figure.flexo -o figure/     # a bundle written out as a plain folder
uv run flexo build figure.flexo          # built straight from a bundle (--trust to run its Python)
uv run flexo studio figure.flexo         # edited as a folder, saved back into the bundle
```

### Bundles: one file to send

A figure (or a deck, with flexo-talk) is a folder: its document, pictures, data, plots'
Python, structures, maps and theme files. A **bundle** (`.flexo`) is all of that as one
file -- to email, AirDrop or Slack, open on another computer, edit, save and send back, as
Keynote's `.key` is one file. It is a zip:

```text
manifest.json              {"format": "flexo-bundle", "version": 1, "document": "talk.yaml",
                            "kind": "deck", "app": "Flexo Studio 0.3.0", "created": ...,
                            "modified": ..., "files": 14, "missing": [...], "outside": [...]}
talk.yaml                  the document, at its root
figures/model.yaml         every file it names, under the name it names it by --
data/loss.csv              and every file those name: a figure file's pictures, a theme's
plots.py, helpers.py       fonts, the modules a plot imports from beside it, the files its
assets/drawing-part-1.svg  words name, a plot's data
.flexo/pdb/1UBQ.cif        a PDB entry a structure names by its ID, as it was fetched
```

Nothing the document says is rewritten. A file it names that is missing, or outside its
folder (`../logo.png`, a whole path), is left out and said, in the manifest and as it is
bundled. A bundle someone sends is read as one from a stranger: no name out of it, no
link, nothing larger than 3 GB however small it is packed -- and its Python runs only once
its person trusts it. The studio opens a bundle into a working folder of its own (in
`~/Library/Application Support/flexo/bundles`, or the XDG data folder) and writes it back,
whole, a moment after each change; a bundle saved on another computer meanwhile is taken
in, as a file changed on disk is.

### The studio: edit with people and agents, live

`flexo studio` (in a folder, or on a file) opens an editor in the browser, served
from this machine, for every document in the folder: figures, themes, and --
with flexo-talk -- decks, each in a tab. It is made for working *with* an
agent: what anyone changes -- you, Claude in the studio's side panel, an agent
such as Claude Code working through MCP, or any program writing the files --
is merged with everyone else's edits, saved, and shown at once. Slides and parts
an agent touches flash in its colour, its avatar and what it is doing ("Tightening
slide 4") show where it works, the activity list says who changed what, and
**Follow** keeps the view on whatever an agent is changing. Undo takes back your
own last change and leaves others' alone; the history beside it (⌥⌘Z) lists your
changes in words, to go back or forward to any of them.

- **Design** in a figure's toolbar (⇧⌘D, View › Show Design in the Mac app) shows its
  Design bar, as a deck's: one low row of pop-up buttons naming what is in use -- **Theme** (a
  grid of the figure drawn in each theme), **Colours**, **Font**, **Page Size** (with its width
  and height), **Sizes** (spacing, shapes' padding, lines' width, arrowheads' size) and
  **More** (panel letters, Customise…). While the Theme or Colours menu is open, the theme or
  palette the pointer is over shows on the figure; chosen, it is one step to undo. The
  inspector keeps what is the figure's parts' own.
- **Figures**, made without writing YAML: **Add** offers every kind of part --
  blocks and operators, the machine-learning components, constructs, plasmids,
  proteins, trees, plates, timelines, structures -- and a part added while another
  is chosen comes after it, a line between them; when the chosen part's single line
  runs on to the part after it, the new one goes into that line, as a step into a
  flow chart. A **+** beside the part chosen adds the next step there at once (a
  block after a start or a decision, another structure after a structure), and the
  words of a part just added are typed on it as soon as it is drawn, in place, in
  the part's own face and size; with a part chosen, typing types over its words, as on a
  Keynote shape, and ⌘G groups the parts chosen (⇧⌘G ungroups). A chosen structure
  turns by its rotate handle (or by
  the buttons in its panel), with every structure that shares its frame, and a structure or
  picture is sized by its corners;
  a shape's **Type** may be made either, its file asked for. Right-click a part
  for what can be done with it. **Connect**
  draws a line from one part to the next (or drag from a part's **+** to another); double-click a part or a line to
  type its words on the drawing; ⇧-click several and **Group** (⌘G) gathers them
  into a row, column, grid, titled module, or lettered **panel** (a, b, c, as a
  journal prints a figure of several; **Panel Letters**, in the Design bar's More,
  letters them A, B, C or in brackets; **Panel** in the toolbar adds one, or lays the
  whole figure out as panels -- 2 across, 2 × 2, 3 × 2, one over two, one beside two --
  in one step; several shapes of one row move a place together with ⌥ and an arrow) -- or puts a **frame** round them where they
  are, in whatever groups: behind them, in front of them or over them as a tint (its
  **Layer**), its title at whichever corner is chosen (its **Title Position**, as a
  group's). A line is drawn to a frame as to a shape: a shape's **+** dragged and let go
  on the frame's outline or its title (inside it, on none of its shapes, is nowhere), or
  the frame's own **+** dragged to a shape -- clicked, it asks for the shape, as
  **Connect to…** in its panel does; a chosen line's end dragged round the frame takes
  another side of it. Shapes chosen anywhere in the figure, in whatever groups, go in one row or
  column of their own with **Align in a Row** or **Align in a Column** (in their panel,
  their right-click menu and the palette), in the order they are seen, where the first of
  them stood: boxes of a flow chart that have ended up in two columns side by side are put
  back on one line. A shape, a group and a frame each have an **Outline**: solid, dashed or
  dotted, as a line has its Line Style. Pictures and drawings (PNG, JPEG, SVG, PDF) and structure files dropped on
  the figure are added to it, beside the shape they are let go on; pasted (⌘V), after the shape
  chosen -- a drawing copied in Inkscape as the SVG it is (in the Mac app), not a picture of
  it. With nothing chosen the figure's **Page
  Size** is chosen by name -- a column or a page of Nature's, Cell's or PNAS's, A4,
  US Letter -- or typed as a **Width** and **Height** of your own (Custom…); a
  page with no height is as tall as the figure. A part (or a whole group) dragged on the drawing goes to another
  place in its row or column, or into another group: it follows the pointer, a line
  shows where it would go, and once it is let go the figure is laid out again and
  every part slides to where it now is (Esc, or letting go off the figure, takes it
  back). A part dragged out under (or over) a figure laid out in a row goes on a line
  of its own there, centred under the rest -- a score under the steps it compares --
  as **Below** and **Above** in a part's panel do; beside a figure laid out in a
  column, it takes a column of its own. The inspector on the right has each part's settings, down to
  a plasmid's features or a plate's groups as a table; the list on the left holds
  the parts as they nest, dragged to move them. Every edit is made to the figure's
  file, which the **Source** tab shows and edits too: comments and order stay, and
  what the page has no control for can be written there. Lint messages sit under
  the drawing; clicking one chooses the part it is about. flexo-talk edits the
  figures on a deck's slides the same way, where they are drawn.
- **Find and replace**: ⌘F opens a bar over the document (a figure, or with flexo-talk
  a deck) that finds a word in all of it as it is typed -- a figure's labels, its lines'
  and modules' words, the words of the shapes drawn over it -- marking each where it is
  drawn and saying "2 of 5". Return and ⇧Return in its field go from one to the next, and
  so do n and ⇧N, as vim's, while it is open and no words are typed (a shape chosen is not
  typed over); **Match Case** and **Whole Words** narrow it, ⌥⌘F shows **Replace** and **Replace
  All** (each one step in the history), and Esc closes it, the last match's shape
  chosen. The top bar's **Search** (⌘K) finds the same words, listed above the
  commands and documents it finds. One engine does both (`static/studio/finding.js`).
- **TODOs**: the word `TODO` in capitals, as a word of its own, in a figure's words is
  work left: marked amber where it is drawn, counted in the zoom bar ("2 TODOs", which
  goes to the next), and gone through by Next TODO (⌘') and Previous TODO (⇧⌘'), its
  shape chosen. Only in the studio: nothing exported has the marks. Found by the same
  engine with Match Case and Whole Words (`static/studio/todos.js`; a deck's, with
  flexo-talk).
- **Themes**: a theme's colours (palette, tones, page), type, lines and shapes,
  and spacing, each shown as the base theme has it until changed, with samples
  drawn as you go -- figures, slides, or any deck in the folder.
- **Assistant**: ⌘J opens a conversation that works on the open documents, told
  what you are looking at, answered by Claude, ChatGPT or another model (chosen,
  with its model, at the top of the panel; the conversation goes with a change).
  It needs `pip install 'flexo[assistant]'`, then: for Claude, credentials the
  Anthropic SDK finds (`ANTHROPIC_API_KEY`, or `ant auth login`); for ChatGPT,
  `OPENAI_API_KEY`; for another model served as OpenAI's API serves them (Ollama,
  LM Studio, OpenRouter), `FLEXO_STUDIO_OTHER_URL` (Ollama's is
  `http://localhost:11434/v1`), with `FLEXO_STUDIO_OTHER_MODEL`,
  `FLEXO_STUDIO_OTHER_KEY` if it asks for one, and `FLEXO_STUDIO_OTHER_NAME` to call
  it by. `FLEXO_STUDIO_PROVIDER` (`claude`, `chatgpt` or `other`) says which answers
  first.
- **Agents**: `claude mcp add flexo-studio -- flexo studio mcp` (once, in the
  folder) gives Claude Code the studio's tools: list, open, read, and edit
  documents (as their YAML), *look* at pages as pictures with their warnings,
  see what you are looking at, and say what it is doing. It joins the studio open
  on the folder, or starts one. For Codex, `codex mcp add flexo-studio -- flexo
  studio mcp`; any MCP client can run `flexo studio mcp` the same way.
- **Shared folders**: a folder kept by Dropbox, Google Drive, iCloud Drive,
  OneDrive or Box can be open in studios on several computers at once. Each
  studio takes in what the others save as the service brings it, merged with
  what is being typed there. When two computers save a file at once, the copy
  the service keeps beside it ("talk (Ben's conflicted copy).yaml", "talk
  [Conflict].yaml") is merged back in and moved out of the folder, to
  `~/Library/Application Support/flexo/merged`. In such a folder a document is
  saved after 1.5 s without typing (at most every 8 s), not 0.35 s, so the
  service carries fewer versions and two computers save at once less often.
- ⌘K searches every command, slide, and file; `?` lists the keys.
- The **help bar**, one row along the window's foot, names the keys for what is being done
  now, a keycap and a word or two each: while a shape is dragged, what ⇧, ⌥ and ⌘ do to the
  drag (each lit while it is held) and Esc; while the find bar is open, ↩ and ⇧↩ in its field
  and N and ⇧N once the keys are elsewhere; while words are typed, theirs; else those of what
  is chosen, or of the page (a deck's slides overlaid: O to stop, ⇞⇟ among them, a click on
  one's object, and snapping's). **View › Hide Help Bar** (the palette, the Mac app, its own
  right-click) hides it, kept in the browser; it says the keys as the Keyboard Shortcuts
  sheet does (`studio/helpkeys.js`).

Other packages add kinds of document through the `flexo.studio` entry-point
group (`flexo.studio.Kind` says what one provides) and samples for the theme
editor through `flexo.studio.specimens`. The studio reads and writes only inside
its folder, answers on `127.0.0.1` alone, and needs the token its page is given
(agents find it in a session file only its owner can read). A document that names
Python -- a deck's plots -- runs it when drawn.

The builder lowers to the same validated, versioned schema that YAML and JSON
parse into, so a figure is one thing written two ways -- see
[`examples/vertical_slice.py`](examples/vertical_slice.py) and its
[YAML equivalent](examples/vertical_slice.yaml). A figure's `style` (or
`theme`), `palette`, `font`, `conventions` and `sketch` are fields of that
document too. A hand-written file may be short: nodes are blocks unless they
say otherwise, `from: encoder` means the node's output (and `to:` its input),
edges are numbered for you, and a file with no `groups` stacks its nodes in a
column (see [the tutorial](docs/tutorial.md#13-the-same-figure-as-a-file)).

`build` and `gallery` always write their outputs so a flawed figure stays
inspectable: lint diagnostics go to stderr and the command exits `1` when any of
them is an error. Only a hard compile failure (exit `2`) produces no output.

## Development

```bash
uv sync --all-groups
uv run pytest
uv run ruff check
uv run flexo --help
```

See [the architecture](docs/architecture.md). The
[implementation report](docs/implementation-report.md) and
[improvement beam](docs/improvement-beam.md) are the history of the first
version.

## Design principles

- semantic authoring instead of routine SVG coordinates;
- immutable, deterministic compiler passes;
- physical publication dimensions and measured typography;
- stable semantic IDs, named ports, and localized diagnostics;
- connectors routed as a whole, never failing: pins on the facing side, trees for
  shared values, crossings priced, lanes solved, and room asked of the layout;
- first-class fan-out nets and merges: branches are plain Ts, a merge of two ends
  in an arrow, and an operation is an operator node;
- defaults that read the figure they are in, and authored values that always win;
- orthogonal routing with a theme-controlled local elbow radius, and straight
  lines where a figure asks for them;
- themes that change the whole look -- type, line work, colour rules -- and move
  nothing a reader relies on;
- connector ink painted after the components it joins, so no run is interrupted
  by a container fill;
- native SVG primitives, live text, and named Inkscape layers;
- explicit editorial layout with bounded local automation;
- linting that reads the finished figure and never feeds back into it.

## License

Flexo is licensed under the [Apache License 2.0](LICENSE). The fonts in
`src/flexo/resources/fonts` keep their own licenses, which sit beside them: the SIL
Open Font License for Caveat, Figtree, IBM Plex Sans and Kalam, the GUST Font License
for Latin Modern, and Liberation's license for Liberation Sans.
