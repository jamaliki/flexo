# Flexo

Flexo is a Python-first compiler for editable scientific and neural-network
figures. Authors describe components, relationships, and editorial layout;
Flexo measures text, fits the composition, routes connectors, and emits
publication-ready SVG made from ordinary Inkscape-editable objects.

```text
semantic figure -> measured figure -> fitted figure -> routed figure -> SVG
```

Flexo is under active development. The first acceptance target is a compact
multi-module architecture figure with feature strips, attention, branches,
residual connections, and a scientific inset.

## Python authoring

```python
from flexo import Figure

with Figure("attention-flow", width="double-column") as figure:
    with figure.module("encoder", label="Encoder") as module:
        features = module.feature_strip("features", label="Node features")
        distances = module.feature_strip("distances", label="Distances")
        combined = module.concat("concat", inputs=[features, distances])
        projection = module.mlp("projection", input=combined)
        q, v = module.channels("query-value", labels=["Q", "V"], input=projection)
        keys = module.cnn("keys", input=features.branch)
        (k,) = module.channels("key", labels=["K"], input=keys)
        attended = module.attention("attention", q=q, k=k, v=v)
        prediction = module.prediction("prediction", input=attended)
        module.residual(features, prediction, lane="encoder-bottom")

figure.compile().document.write("attention-flow.editable.svg")
```

Shared values and true combinations are authored explicitly rather than inferred
from coincident lines:

```python
figure.net(src=add_norm.s, sinks=[mlp1.n, mlp2.n, mlp3.n])
figure.merge(
    sinks=[cryo_prediction.e, sequence_prediction.e, ipa_prediction.e],
    dst=average.n,
    rail="east",
    label="Average",
)
```

`net` emits one trunk with branches after the source; `merge` emits one rail and
combines before the destination. Only destination stems receive arrowheads, and
junction dots mark forks and merges only. Where a rail terminal serves a single
stem there is no fork, so rail and stem share one rounded corner instead of
meeting at a sharp one. The paper style turns every corner on a 6 pt elbow
fillet; set `elbow_radius=pt(0)` on a derived `LayoutStyle` for a sharp
technical-drawing treatment.

Two hints place and mark that joint. `rail_at=0.55` asks for the shared rail
partway along the trunk run — the fraction is measured from the trunk's start
toward the destination, so a merge that would otherwise join just before its
sink can join mid-run instead. It is a request: where clearances forbid it the
router moves to the nearest rail that fits and reports
`routing.net.rail-at.clamped` as a lint warning rather than silently obeying or
failing. `joint="arrow"` then ends the joining ink in an arrowhead one standoff
short of the run it points into, leaving the trunk unbroken and dropping the dot
that would otherwise mark the branch; `joint="dot"` insists on the dot even under
`junction_dots="never"`.

### Feature values as vector glyphs

A feature value is not a box. `vector()` composes a vertical stack of rounded
cells with its caption below, shaded along one palette ramp role, and returns the
cells so arrows attach to the glyph itself:

```python
nodes = module.vector("nodes", label="Node features", ramp="ramp-node")
q = module.vector("q", label="Q", ramp="ramp-q", input=module.mlp("mlp", input=nodes))
kv = module.vector("kv", label="K, V", ramp="ramp-kv", columns=2, input=encoder)
figure.merge(sinks=[q, kv], dst=attended, label=attention_formula)
```

The ramp is paint only: `ramp-node`, `ramp-embedding`, `ramp-q`, `ramp-kv`,
`ramp-attended`, and `ramp-output` are defined by every palette, so `flexo
retheme` re-colours a figure without moving a coordinate. A vector's four ports
are its four side centres — west and east on the *middle cell* — so the
counterpart port is the one that adapts, and a run into a vector comes out
straight.

When a panel needs its own colours instead, a `VectorPreset` carries one base
colour and a topology written columns-first, and derives the opaque shades of
each column for you:

```python
q = module.vector("q", label="Q", preset=VectorPreset("#e2703a", "1x3"))
kv = module.vector("kv", label="K, V", preset=VectorPreset(("#d0568c", "#7fae3f"), "2x3"))
```

Preset colour is author paint written literally into the SVG, so `flexo retheme`
— which rewrites role-tagged paint only — leaves it exactly as authored. Name a
ramp role instead when a figure has to survive retheming or a grayscale printing.

A ramp says *ordered*, which is a claim about the data. Real activations are not
ordered, so `order="shuffled"` permutes each column's shades and the glyph reads
as a feature vector rather than a gradient:

```python
q = module.vector("q", label="Q", preset=VectorPreset("#e2703a", "1x3", order="shuffled"))
kv = module.vector("kv", preset=VectorPreset(("#d0568c", "#7fae3f"), "2x3", order="shuffled"))
```

The permutation is deterministic: it is drawn from `seed` (default `0`), so one
preset always yields one figure and a rebuild is byte-for-byte the same. Each
column seeds separately, so the columns of one glyph differ from each other
rather than repeating a pattern sideways. A shuffle that came back in ramp order
would silently lie about what it depicts, so it is rejected and redrawn — a
`"shuffled"` glyph of two or more cells never reads as a ramp.

`tint` and `shade` set how far each column's light and dark ends travel from its
base colour — at least `0.0`, below `1.0` (`1.0` would end at pure white or
black, which is no longer a shade of anything). The defaults, `0.6` and `0.35`,
mix the light end further because a tint stays legible against a white canvas
long after an equal shade has gone to mud. On a *dark* panel that is backwards:
around `tint=0.35` keeps the pale cells saturated instead of washing them toward
the page. `shade_ramp(base, count, tint=..., shade=...)` takes the same two.

### Painting one component by hand

Palette roles are how a figure stays rethemeable, so change the palette when
every component of a kind should differ. When exactly one component must — a
caption that has to clear its own dark body, say — `paint` overrides the role for
that node alone:

```python
module.mlp("q-mlp", label="MLP", paint={"label": "#9fe1cb"})
module.block("panel", label="Panel", paint={"fill": "#085041", "stroke": "#56bb9a"})
```

The three parts are `fill` and `stroke` (the component body) and `label` (its
text); any other key is an error where it is written, as is a colour that is not
`#rgb` or `#rrggbb`. An overridden part carries **no** paint role into the SVG,
so `flexo retheme` leaves it exactly as authored — the same convention preset
vector cells follow. Parts left out keep their role and retheme normally.

### Titles and motifs

A group's title sits at the left of its top edge unless it asks otherwise:

```python
with figure.root.group("attention", label="Attention module", title_side="right") as module:
```

`title_side="right"` anchors it to the right end instead. The title band is the
same height either way, so nothing in the figure moves.

Component motifs — the MLP's three dots, the CNN's zigzag, the add-norm cross, a
matrix's or attention's cell grid, a sequence's tokens, a concat's bars, a
graph's little network, an inset's illustration — are ornament, and `motif=False`
drops one:

```python
module.mlp("q-mlp", input=nodes, motif=False)
```

Nothing else changes: same size, same body, same ports, same label. Reach for it
when a panel repeats a component often enough that its ornament becomes noise.

Attention then reads as a formula, not as a matrix: the merge above carries its
caption in styled runs (`TextRun("T", baseline_shift="super")`) and Flexo anchors
it above the horizontal run the arrow draws, with the second source rising into
that run just before the sink.

### Module interiors as grids

A module whose chains should line up is a `grid`: rows are the chains, columns
line them up, and `align="start"` puts each cell's content at the top of its row.
Give the boxes the height of a vector's cell stack and every run along a row is
straight by construction, with no port adaptation left to absorb.

Cells are addressed, not counted. A child names its cell with `at=(row, column)`,
0-indexed from the top left; the children that do not name one keep author order
and flow row-major into whatever cells are left. Nothing has to fill the holes —
a short last row, an empty column, or a gap in the middle of a row costs no
nodes at all:

```python
with module.grid("attention", columns=7, column_widths={3: pt(50)}) as grid:
    nodes = grid.vector("nodes", label="Node features", preset=node_preset)  # (0, 0)
    q_mlp = grid.mlp("q-mlp", input=nodes, height="cells:3")                 # (0, 1)
    q = grid.vector("q", label="Q", preset=q_preset, input=q_mlp)            # (0, 2)
    attended = grid.vector("attended", preset=attended_preset, at=(0, 4))    # past the lane
    embedding = grid.vector("embedding", label="Embedding", at=(1, 0))       # a short row
```

Column 3 above holds no child in either row: it is the corridor the attention
arrow runs down, and its formula has to fit above it. `column_widths={index:
length}` reserves a minimum width for a column even when every cell in it is
empty, so the lane needs no width-carrying `spacer` node to prop it open. Row 1
is three cells long and the four cells beside it simply do not exist.

Mixed mode is deterministic: addressed children claim their cells first, then
the unaddressed ones flow into the remainder. A child addressed at (0, 4) pushes
no sibling sideways — the flow steps over that cell when it reaches it. Two
children addressed to the same cell, or a column outside the grid, is an error
where it is written rather than a puzzle in the rendered figure.

### Spacing that is not square

`gap` spaces siblings on both axes at once, which is the wrong knob whenever a
panel wants vertical air: buying it out of a seven-column grid's gap spreads the
panel six times as far sideways. `row_gap` and `column_gap` override `gap` on one
axis each — a row reads `column_gap`, a column or stack reads `row_gap`, and a
grid reads both.

`padding` is one length for all four sides, an `(x, y)` pair, or a `(top, right,
bottom, left)` 4-tuple:

```python
figure.root.group(
    "attention",
    layout="grid",
    columns=7,
    row_gap=pt(19),
    column_gap=pt(19),
    padding=(pt(11.5), pt(11.5), pt(32.5), pt(11.5)),
)
```

The four sides are what let a panel's sides sit tighter than its top and bottom,
which is usually what a figure wants: captions hang below the bottom row, so the
floor needs more air than the flanks. Every one of these falls back to the value
it refines — `row_gap` to `gap` to the style token, each padding side to
`padding` — so a figure that asks for none of them keeps exactly the geometry it
had.

### Heights that match a vector stack

A box whose side ports must line up with a vector's is exactly as tall as that
vector's cell stack. `vector_stack_height(style, cells)` is that arithmetic, and
`"cells:N"` is the same thing written where a node's `width` or `height` goes:

```python
from flexo import vector_stack_height

module.mlp("q-mlp", input=nodes, height="cells:3")          # resolved at measure time
module.mlp("q-mlp", input=nodes, height=vector_stack_height(style, 3))
```

Prefer the string. It resolves against the style the figure is *compiled* with,
so a panel drawn at a larger `vector_cell` keeps its boxes and its vectors in
step; a length computed up front does not.

### Band rows and strip bands

Cross-container alignment is authored, not hoped for. When a residual spine runs
beside a stack of modules, make the root a column of **bands**: every band is a
row that starts with the same fixed-width spine cell, and *module bands alternate
with thin strip bands*. A module band carries the module; the strip band between
two modules carries the single spine block that joins them.

```python
def band(root, id):  # one band row, always starting with the spine column
    return root.row(id, gap="24pt", padding=0, align="start", role="layout")

with Figure("gnn", layout=LayoutSpec("column", gap=pt(20), align="start")) as figure:
    with band(figure.root, "band2") as module_band:            # module band
        module_band.node("spine", "spacer", width="72pt", height=0.0)
        module = _module(module_band, "sequence", "Sequence module")
    with band(figure.root, "strip2") as strip:                 # strip band
        add_norm = strip.node("addln2", "add-norm", label="Add LN", width="72pt", ports=...)
```

Why the alternation matters: a spine block level with the *top* of the module it
feeds has no reachable east side, so its feedback rail is forced up and over the
module. Give it its own strip and the same rail reads correctly -- east out of
the module's update MLP, south past the module, west along the strip, into the
east feedback port, always below the module. The strip is also where a fan-out
net from the last spine block lands its rail, between that block and the row it
feeds instead of below it.

Three uses of the zero-size `spacer` component hold that grid open without
padding anything:

- a `width`-only spacer in the spine cell of a module band, so every band's
  spine column shares one x;
- a zero-size spacer *after* the module, which carries the band's right edge one
  gutter past it -- `lane="<band>-right"` then names an empty column where a
  residual rail can drop south. Inside the module the container fill would
  paint over it.
- a `height`-only spacer row above a row of heads, reserving the fan-out
  corridor in one direction only. A single `padding` would reserve it on all
  four sides and leave a dead strip at the canvas edge; a one-sided
  `padding=(top, right, bottom, left)` now says the same thing without a node.

`flexo.gallery.modelangelo_gnn` is authored this way; its canvas ends at the
content plus the ordinary margin on every side.

### Which role paints what

An author overriding a palette needs to know which role reaches which ink before
writing the override, not after grepping the renderer. An `mlp` paints
`block-*`, not `accent-*`; a caption under an arrow paints `muted-ink` while a
caption inside a box paints `ink`.

| Role | Paints |
| --- | --- |
| `canvas` | the page background; the ring around a `junction` dot |
| `ink` | component labels, group titles, `channels` captions |
| `muted-ink` | connector and net captions — and nothing else |
| `container-fill` / `container-stroke` | a group's container rect; `sequence` body; `concat` body fill; the border of `graph` and `inset` |
| `block-fill` / `block-stroke` | `block`, `mlp`, `cnn`, `add-norm`, `tensor` bodies; `concat` body stroke. `block-stroke` also draws their motifs: MLP dots, CNN zigzag, add-norm cross, sequence tokens, concat bars |
| `accent-fill` / `accent-stroke` | `matrix`, `attention`, `feature-strip` bodies. `accent-stroke` also draws matrix and attention cell grids, feature-strip cells, `graph` nodes and edges, `inset` spokes, `channels` bars |
| `warm-fill` / `warm-stroke` | `prediction` and `loss` bodies; `warm-stroke` also the `inset` centre dot |
| `inset-fill` | `graph` and `inset` bodies, bordered in `container-stroke` |
| `connector` | edge shafts, net rails and stems, flow arrowheads, junction dots, the `junction` component's body, the `channels` split path |
| `residual` | the same ink for anything authored `role="residual"`, arrowheads included |
| `ramp-node`, `ramp-embedding`, `ramp-q`, `ramp-kv`, `ramp-attended`, `ramp-output` | `vector` cells — one role per glyph, fill and stroke, graded by `fill-opacity` |
| `grid` | defined by every palette, painted by nothing today |

Two kinds of ink sit outside the table on purpose, because they are literal
colour rather than a role: `VectorPreset` cells and any `paint=` override. Both
emit no `data-flexo-fill` or `data-flexo-stroke`, which is exactly what makes
`flexo retheme` walk past them.

The builder lowers to the same validated, versioned schema used by YAML and
JSON. See [`examples/vertical_slice.py`](examples/vertical_slice.py) and its
[`YAML equivalent`](examples/vertical_slice.yaml).

## Command line

```bash
uv run flexo build examples/vertical_slice.yaml --output examples/build
uv run flexo check examples/vertical_slice.yaml
uv run flexo inspect examples/vertical_slice.yaml
uv run flexo gallery --output examples/build
```

`build` emits an editable SVG master plus portable SVG, PDF, and PNG derivatives.
Derived exports require Inkscape on `PATH`, in the standard macOS application
location, or configured through `FLEXO_INKSCAPE`.

`build` and `gallery` always write their outputs so a flawed figure stays
inspectable: lint diagnostics go to stderr and the command exits `1` when any of
them is an error. Only a hard compile failure (exit `2`) produces no output.

## Development

```bash
uv sync --all-groups
uv run pytest
uv run flexo --help
```

See [the architecture](docs/architecture.md), [the implementation report](docs/implementation-report.md),
and [the improvement beam](docs/improvement-beam.md).

## Design principles

- semantic authoring instead of routine SVG coordinates;
- immutable, deterministic compiler passes;
- physical publication dimensions and measured typography;
- stable semantic IDs, named ports, and localized diagnostics;
- first-class fan-out nets and authored merge rails;
- orthogonal routing with a theme-controlled local elbow radius;
- connector ink painted after the components it joins, so no run is interrupted
  by a container fill;
- native SVG primitives, live text, and named Inkscape layers;
- explicit editorial layout with bounded local automation.

The repository is public but does not yet declare an open-source license.
