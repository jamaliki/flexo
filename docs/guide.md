# Authoring guide

This guide covers Flexo's components, layout, paint, artwork, and export in
detail. The [README](../README.md) covers the essentials. Connector routing is
described in [routing.md](routing.md), and the compiler's structure in
[architecture.md](architecture.md).

## Components and wiring

```python
import flexo

with flexo.Figure("attention-flow", width="double-column") as figure:
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
```

Component factories share two wiring keywords: `input=` takes one upstream
value and `inputs=` takes several. They work on `node` and on `block`, `circle`,
`image`, `inset`, `graph`, `matrix`, `sequence`, `tensor`, `feature_strip`,
`vector`, `channels`, `add_norm`, `mlp`, `cnn`, `prediction`, and `loss`.

- One source connects to the component's `input` port.
- Several sources connect to `input1`, `input2`, ... when the component has
  those ports. Otherwise they all connect to `input`.
- `concat` gives each source its own west port, `input1`, `input2`, ....
  Created before its sources exist, it takes `count=` ports (two by default).
- `attention` maps sources by name. `input=x` is self-attention: `x` feeds `q`,
  `k`, and `v`. `inputs=[x, memory]` is cross-attention: `x` feeds `q` and
  `memory` feeds `k` and `v`. Three sources feed `q`, `k`, and `v` in order.
  `q=`, `k=`, and `v=` connect each port directly; passing them together with
  `input=`/`inputs=` raises `ValueError`.

`mlp`, `cnn`, `concat`, and `channels` build their own port tables from their
arguments. If you pass `ports=`, your table replaces the computed one, and the
sources are wired to the `input` or `input1`, `input2`, ... ports it declares.

Ids are scoped by the group that owns them: `module.mlp("head")` inside
`encoder` has the id `encoder.head`. The same component name can therefore
appear in every module of a figure.

### Components you can create before their inputs exist

Wiring at creation is optional. Every factory creates its component without
sources. An `attention` block has its `q`, `k`, and `v` ports
whether or not sources were given, so a later `connect` or `net` can reach them:

```python
import flexo

with flexo.Figure("transformer", width="double-column") as figure:
    with figure.module("decoder", layout="column") as decoder:
        cross = decoder.attention("xmha", label="Multi-Head\nAttention")
    with figure.module("encoder", layout="column") as encoder:
        top = encoder.add_norm("an", label="Add & Norm")
    figure.net(src=top, sinks=[cross.k, cross.v], id="cross-kv")
```

This lets you write a figure out of flow order. Here the decoder's
cross-attention is created before the encoder that supplies its keys and
values.

### Attention that grows its own Q, K, V

`vectors=` draws an attention block's three inputs as vector glyphs below it:
one cell stack per port, each centred under the port it feeds, with a caption
beside it.

```python
import flexo

QKV = {
    "q": flexo.VectorPreset("#9a6fb8", "1x3"),
    "k": flexo.VectorPreset("#c9853d", "1x3"),
    "v": flexo.VectorPreset("#4f9b8f", "1x3"),
}

with flexo.Figure("grown", width="double-column") as figure:
    with figure.module("encoder", layout="column", gap="14pt") as tower:
        norm = tower.add_norm("an", label="Add & Norm", width="120pt")
        mha = tower.attention(
            "mha", label="Multi-Head\nAttention", width="120pt", vectors=QKV
        )
    figure.connect(mha, norm)
```

`vectors=` accepts:

- `True`: the palette's `ramp-q` role for Q and `ramp-kv` for both K and V.
- One `VectorPreset` or one ramp role name: all three glyphs painted alike.
- A mapping with the keys `q`, `k`, and `v`: each glyph painted its own way.
  Keys are case-insensitive, so `Q`, `K`, `V` also work. All three keys are
  required.
- `None` (the default) or `False`: the plain attention block, with no glyphs.

The composite requires `width=`; without it `attention` raises `ValueError`.
The builder divides that width into a one-row grid: a pad, then a lane and a
pad for each port. Every lane has the same width and is centred on its port's
offset. A glyph centred in its lane is therefore centred under its port, and
the connector between them is a straight vertical. If the lanes are too narrow
to hold a stack with its caption, the builder widens the block until they fit.

The returned handle still names the block, so `output` is the attention
output. Its `q`, `k`, and `v` resolve to the glyphs' `input` ports, so a value
wired to `mha.k` enters the K glyph:

```python
import flexo

with flexo.Figure("grown-wired", width="double-column") as figure:
    with figure.module("encoder", layout="column", gap="14pt") as tower:
        norm = tower.add_norm("an", label="Add & Norm", width="120pt")
        mha = tower.attention(
            "mha", label="Multi-Head\nAttention", width="120pt", vectors=True
        )
        embedding = tower.block("embedding", label="Embedding", width="120pt")
    figure.net(src=embedding, sinks=[mha.q, mha.k, mha.v], id="qkv")  # into the glyphs
    figure.connect(mha, norm)                                         # out of the block
```

A glyph's two ports are pinned: `input` on its south side and `output` on its
north side, which feeds the attention port above. A value that comes from one
side routes to below its glyph and enters from underneath.

Each caption stands to the left of its stack, one `caption_clearance` from the
cells. The glyph reserves the same width as padding on the right of the stack,
so the stack stays centred in its lane and the space below it stays clear for
the incoming connector. A standalone `vector()` keeps its caption below the
stack.

Lanes are assigned in port-offset order, not in q/k/v order. A `ports=` table
that puts `v` on the left therefore puts the V glyph on the left. This is how
the Transformer paper draws cross-attention:

```python
import flexo

CROSS_PORTS = (
    flexo.PortSpec("v", flexo.Side.SOUTH, 0.24, adaptive=True, auto_side=True),
    flexo.PortSpec("k", flexo.Side.SOUTH, 0.5, adaptive=True, auto_side=True),
    flexo.PortSpec("q", flexo.Side.SOUTH, 0.76, adaptive=True, auto_side=True),
    flexo.PortSpec("output", flexo.Side.NORTH, 0.5, adaptive=True, auto_side=True),
)

with flexo.Figure("cross", width="double-column") as figure:
    with figure.module("decoder", layout="column") as decoder:
        cross = decoder.attention(
            "xmha",
            label="Multi-Head\nAttention",
            width="120pt",
            vectors=True,
            ports=CROSS_PORTS,
        )
```

In a ports-aligned parent the composite aligns on the attention block, not on
the glyph row below it. A row of towers therefore lines up on the attention
boxes. [`examples/transformer.py`](../examples/transformer.py) builds all three
attention blocks of a Transformer this way.

### Residual blocks name both of their wires

`add_norm` is a residual join. It has a separate port for each incoming wire:

```python
import flexo

with flexo.Figure("residual", width="double-column") as figure:
    with figure.module("m", layout="column", gap="18pt") as module:
        norm = module.add_norm("an", label="Add & Norm")
        sublayer = module.block("ff", label="Feed Forward")
        fork = module.node("fork", "junction")
        module.connect(fork, sublayer)
        module.connect(sublayer, norm)                            # -> an.input
        module.connect(fork.branch, norm, target_port="skip")     # -> an.skip
```

Its four ports are:

| Port | Carries | Side |
| --- | --- | --- |
| `input` | the sublayer's output | auto-sided |
| `skip` | the value that bypassed the sublayer | east |
| `output` | the sum, to the next sublayer | auto-sided |
| `branch` | the sum, to the next block's `skip` | east |

A port's declared offset only orders it among its neighbours. Where an arrow
meets the side is set when routing: one arrow at the middle, several spread
evenly (see [How connectors are routed](routing.md)).

`add_norm(input=..., skip=...)` wires both at creation, and `residual()` uses a
`residual` or `skip` port when the target has one. Two values sent to the same
`input` port are drawn as two arrows side by side (see `arrivals` under
[Conventions](../README.md#conventions-branches-merges-arrivals-lines-and-pins)).

`skip` and `branch` are pinned to the east side, so every residual in a figure
runs on the same side. Both are adaptive and slide along the east edge toward
their counterparts. Because the bypass runs outside the block, the enclosing
container needs side padding for it; the router adds that padding when it is
missing (see [How connectors are routed](../README.md#how-connectors-are-routed)).
For residuals on the west, pass a `ports=` table.

### Ports pick the side they face

Each component's default ports declare a side: inputs west and outputs east.
Ports marked `auto_side` (most component defaults) can move. Flexo attaches
each end of each connection on the side of the box that faces the other end.
The choice is made per connection, not per port: a value that goes both down
and sideways leaves from two sides.

The rules:

- **An authored `PortSpec` is pinned.** So is a port named by an edge's
  `depart`/`arrive` hint (fields of `EdgeSpec`), and the arriving end of an
  edge with `via=` (a route that comes round the west arrives from the west).
- **A default port without `auto_side` is pinned.** Examples: `add_norm`'s
  `skip` and `branch`, and the four ports of `vector` and `image`.
- **Ends of one port that leave on the same side share one pin** and are drawn
  as a tree from it. Pins on one side are ordered by where their lines go, so
  lines leaving one box do not cross each other.
- **An arrival and a departure of different values do not share a side** when
  one of them can move. A departure with nowhere else to face leaves by its
  port's own side, next to the same value leaving there (a feedback loop taps
  the output); an arrival comes in over the top or under the bottom.
- **A side whose straight approach would hit another box is skipped** in
  favour of the next side that faces the counterpart.
- **A side holds only as many pins as have room**; the rest go round the corner
  to the next side that faces their lines.
- **Each input of an operator takes its own side**, so values meeting at a `+`
  arrive from different directions: the step in line with it keeps the top,
  and values from off to one side come in by the side facing them. Three or
  more inputs from one direction (the experts of a mixture, summed below them)
  join on a bus and enter as one arrow.
- **A circle or a diamond takes one line per corner**, the line in line with it
  first, then the nearest.
- **A loop (`connect(a, a)`) goes on the emptiest side.**
- **Two pins facing each other across a gap are aligned** when both boxes allow
  it and the straight line between them is clear, so the arrow is straight.

Ports with no connection keep their declared side. Side selection happens at
compile time: the figure serializes with the sides it was written with, and
re-compiles to the same picture.

## Feature values as vector glyphs

`vector()` draws a feature value as a vertical stack of rounded cells with its
caption below. It returns the handle of the cells, so connectors attach to the
glyph:

```python
import flexo

with flexo.Figure("vectors", width="double-column") as figure:
    with figure.module("m", label="Attention") as module:
        nodes = module.vector("nodes", label="Node features", ramp="ramp-node")
        mlp = module.mlp("mlp", input=nodes)
        q = module.vector("q", label="Q", ramp="ramp-q", input=mlp)
        kv = module.vector("kv", label="K, V", ramp="ramp-kv", columns=2)
        attended = module.vector("attended", label="Attended", ramp="ramp-attended")
        module.merge(sinks=[q, kv], dst=attended, label="softmax(QKᵀ)V")
```

A vector has four pinned ports at its side centres: `input` (west), `output`
(east), `north`, and `south`. A connector into a side port meets the middle of
the stack. The caption is a separate node placed directly below the `south`
port, and routes avoid it. A route that leaves through `south` needs room
between the stack and the caption; use `north` when the route can go up
instead.

`ramp` selects a paint role only: `ramp-node`, `ramp-embedding`, `ramp-q`,
`ramp-kv`, `ramp-attended`, or `ramp-output`. Every palette defines all six, so
`flexo retheme` recolours a figure without moving anything.

For colours outside the palette, a `VectorPreset` takes one base colour and a
topology written columns first (`"1x3"` is one column of three cells). It
derives the shades of each column from the base colour:

```python
import flexo

with flexo.Figure("presets", width="double-column") as figure:
    with figure.module("m", label="Attention") as module:
        module.vector("q", label="Q", preset=flexo.VectorPreset("#e2703a", "1x3"))
        module.vector(
            "kv",
            label="K, V",
            preset=flexo.VectorPreset(("#d0568c", "#7fae3f"), "2x3"),
        )
```

A preset shuffles its shades by default (`order="shuffled"`), so the glyph
reads as a feature vector rather than an ordered ramp. Pass `order="ramp"` for
a light-to-dark gradient:

```python
import flexo

with flexo.Figure("ordered", width="double-column") as figure:
    with figure.module("m", label="Attention") as module:
        module.vector("q", label="Q", preset=flexo.VectorPreset("#e2703a", "1x3"))
        ramped = flexo.VectorPreset("#e2703a", "1x3", order="ramp")
        module.vector("scale", label="Scale", preset=ramped)
```

The shuffle is deterministic. It is seeded from `seed` (default `0`), so the
same preset always produces the same figure. Each column is shuffled with its
own stream. A shuffle that returns the shades in ramp order is discarded and
redrawn, so a `"shuffled"` column of two or more distinct shades never appears
in ramp order.

`tint` and `shade` set how far each column's light and dark ends move from the
base colour. Both must be at least `0.0` and below `1.0`; the defaults are
`tint=0.6` and `shade=0.35`. On a dark background, a lower `tint` (around
`0.35`) keeps the light cells saturated. `shade_ramp(base, count, tint=...,
shade=...)` takes the same two parameters.

## Grids, spacing, and alignment

A `grid` lines up rows and columns. A child names its cell with
`at=(row, column)`, counted from 0 at the top left. Children without `at=` keep
author order and fill the remaining cells row by row. Cells can stay empty: a
short last row, an empty column, or a gap in a row needs no placeholder node.

```python
import flexo

with flexo.Figure("grid", width="double-column") as figure:
    with figure.module("m", label="Attention") as outer:
        with outer.grid("attention", columns=7, column_widths={3: flexo.pt(50)}) as grid:
            nodes = grid.vector("nodes", label="Node features", ramp="ramp-node")
            q_mlp = grid.mlp("q-mlp", input=nodes, height="cells:3")
            grid.vector("q", label="Q", ramp="ramp-q", input=q_mlp)
            grid.vector("attended", ramp="ramp-attended", at=(0, 4))
            grid.vector("embedding", label="Embedding", ramp="ramp-embedding", at=(1, 0))
```

Here `nodes`, `q-mlp`, and `q` fill cells (0, 0) to (0, 2). Column 3 holds no
child in either row. `column_widths={index: length}` reserves a minimum width
for a column even when it is empty, so it can serve as a corridor for a
connector without a `spacer` node. Row 1 contains one cell.

Placement is deterministic: children with `at=` claim their cells first, and
the others fill the remaining cells in order, skipping claimed ones. The number
of rows grows to include the highest row any child addresses. Two children
addressed to the same cell, a negative index, or a column outside the grid
raises `ValueError` at the call that places the child.

### Layout from the wiring

`layout="flow"` arranges a group's children from how they are wired instead of
from the order they were written, top to bottom (`"flow-right"`: left to
right). The children can be written flat:

```python
import flexo

with flexo.Figure("heads", width="single-column") as figure:
    with figure.module("m", label="Multi-task learning", layout="flow") as m:
        shared = m.block("shared", label="Shared encoder", input=m.text("x", "x"))
        heads = [m.block(name, label=name, input=shared) for name in ("depth", "normals")]
        m.add("total", inputs=heads)
```

Each child goes one layer after the latest child that feeds it, so every arrow
points down the flow; an arrow that closes a loop is left out when layers are
counted, so a cycle still has a first step. A child that nothing feeds -- real
data beside a generator -- goes one layer before the first child it feeds, and
a link with no arrowhead (`arrow="none"`) does not order layers at all, so
twins joined by "shared weights" stay side by side. Within a layer, children are
sorted by the mean position of the neighbours they are wired to, which removes
most crossings; ties keep author order. An arrow that skips layers keeps a lane
through each layer it passes. A layer of one child is centred on its own; a run
of wider layers becomes one grid, in which each child takes the column nearest
the ones feeding it, so a branch runs straight down its column. The compiled
figure has those rows and grids; the authored figure keeps its flow group.

`layout="cycle"` is for a loop of steps: its children go clockwise from the top
left, in the order written, round the border of the grid that holds them with
the fewest cells to spare (two rows by three columns for six, three by three
for eight), so each step sits beside the next and the arrow that closes the
loop is as short as the others.

### Spacing that is not square

`gap` sets the space between siblings on both axes. `row_gap` and `column_gap`
override it on one axis: a row reads `column_gap`, a column reads `row_gap`,
and a grid reads both. `padding` takes one length for all four sides, an
`(x, y)` pair, or a `(top, right, bottom, left)` tuple:

```python
import flexo

with flexo.Figure("spacing", width="double-column") as figure:
    with figure.root.group(
        "attention",
        label="Attention",
        layout="grid",
        columns=7,
        row_gap=flexo.pt(19),
        column_gap=flexo.pt(19),
        padding=(flexo.pt(11.5), flexo.pt(11.5), flexo.pt(32.5), flexo.pt(11.5)),
    ) as grid:
        grid.vector("q", label="Q", ramp="ramp-q")
        grid.vector("kv", label="K, V", ramp="ramp-kv")
```

The example gives the bottom more padding than the sides, which leaves room
for captions below the last row. Each value falls back to the one it refines:
`row_gap` and `column_gap` to `gap`, then to the style's gap; each padding side
to `padding`, then to the style's group padding.

### Aligning by port line instead of by box

`align` sets where children sit across the axis they are not laid out along.
It accepts `start`, `center`, `end`, `stretch`, `ports`, and `auto`.

- `start`, `center`, `end`, and `stretch` align the children's boxes.
- `ports` aligns the line the children's side ports sit on, as text aligns on
  a baseline.
- `auto`, the default for groups and for the figure's root, resolves per
  group: `ports` when the group's children are connected to one another,
  `start` for two or more columns in a row or rows in a column, and `center`
  otherwise. The root never takes `start`: a figure with nothing wired across
  its top level is centred.

Box alignment is wrong for a vector: its caption is part of the composite's
box, so the box centre falls below the cells and connectors between aligned
boxes slope. `align="ports"` fixes this:

```python
import flexo

with flexo.Figure("ports", width="double-column") as figure:
    with figure.module("m", label="Cryo-EM module") as outer:
        with outer.grid("cryo", columns=7, align="ports") as grid:
            rects = grid.inset("rectangles", label="Edge\nrectangles", height="60pt")
            edge_cnn = grid.cnn("edge-cnn", input=rects)
            grid.vector("kv", label="K, V", ramp="ramp-kv", input=edge_cnn)
```

In a **row**, each child is placed so the y of its west and east ports lies on
the row's shared line. In a **column**, the x of each child's north and south
ports lies on the column's shared line. A grid does both, per row and per
column. The row reserves its **ascent** (the furthest any child reaches above
the line) and its **descent** (the furthest below). A ports-aligned row can
therefore be taller than its tallest child.

A plain component's port line passes through its centre. A group's port line
is that of its **anchor child**, translated into the group's coordinates. The
anchor child is:

1. the child named by `anchor="<child>"`, if given;
2. otherwise, among children that are not `label` or `spacer` nodes, the one
   with the most connections leaving the group (if several tie with at least
   one connection, the group uses its own centre);
3. otherwise, the first child that is not a `label` or `spacer`.

This makes a captioned vector align on its cells, not on cells plus caption.
Name the anchor explicitly when the default picks the wrong child:

```python
import flexo

with flexo.Figure("anchor", width="double-column") as figure:
    with figure.module("m", label="Panel") as row:
        with row.column("panel", align="center", anchor="body") as panel:
            panel.block("badge", label="fig. 1")
            panel.mlp("body", label="Encoder")
```

### Heights that match a vector stack

To make a box exactly as tall as an N-cell vector stack, set its height to
`"cells:N"`. (To line up ports without matching heights, use `align="ports"`.)
`vector_stack_height(style, cells)` computes the same length in Python:

```python
import flexo

with flexo.Figure("heights", width="double-column") as figure:
    with figure.module("m", label="Attention") as module:
        nodes = module.vector("nodes", label="Node features", ramp="ramp-node")
        module.mlp("q-mlp", input=nodes, height="cells:3")
        module.mlp("k-mlp", height=flexo.vector_stack_height(flexo.STYLES["paper"], 3))
```

Prefer the string. It resolves against the style the figure is compiled with,
so it follows changes to `vector_cell`. A length computed in advance does not.

## Band rows and strip bands

To align a residual spine with a stack of modules, make the root a column of
**bands**. Each band is a row that starts with a spine cell of the same fixed
width. Module bands alternate with thin strip bands: a module band holds a
module, and the strip band after it holds the spine block that joins it to the
next module.

```python
import flexo


def band(root, id):
    """One band row, always starting with the spine column."""

    return root.row(id, gap="24pt", padding=0, align="start")


layout = flexo.LayoutSpec("column", gap=flexo.pt(20), align="start")
with flexo.Figure("gnn", width="presentation", layout=layout) as figure:
    with band(figure.root, "band1") as module_band:
        previous = module_band.block("previous", label="Previous layer", width="72pt")
        module_band.group("sequence", label="Sequence module", role="module", shadow=True)
    with band(figure.root, "strip1") as strip:
        strip.add_norm("addln1", label="Add LN", width="72pt", input=previous)
```

The sketch declares no port table. The spine reads downward, so each spine
block's auto-sided `input` faces north and its `output` faces south (see
*Ports pick the side they face*). An edge routed with `lane=` does not
influence port sides, so a port that such an edge arrives on must be declared.
The gallery's `add-norm` blocks declare `skip` on the north, a `feedback` port
on the east for the residual rail that arrives through a lane, and `output` on
the south.

Put each spine block in its own strip, not beside the top of its module. A
spine block level with the top of the module it follows has no reachable east
side, so its feedback rail must go up and over the module. In a strip, the rail
leaves the module's east side, runs south past the module, then west along the
strip into the east `feedback` port. A fan-out net from the last spine block
also places its rail in the strip, between the block and the row it feeds.

The zero-size `spacer` component holds the grid open without padding:

- A `width`-only spacer in the spine cell of a module band keeps every band's
  spine column at the same x.
- A zero-size spacer *after* the module extends the band's right edge one gap
  past the module. `lane="<band>-right"` then names an empty column outside
  the module where a residual rail can run south. Inside the module, the
  container fill would cover it.
- A `height`-only spacer above a row of heads reserves the fan-out corridor in
  one direction. `padding` would add the same space on all four sides.

`modelangelo_gnn` in [`flexo/gallery.py`](../src/flexo/gallery.py) is built
this way; its canvas ends at the content plus the standard margin on every
side.

## Paint: palettes, overrides, and retheming

A theme (see [Themes, palettes, and
fonts](../README.md#themes-palettes-and-fonts)) changes the whole look. Every
shape is painted by **role** -- `ink`, `container-fill`, `tone-2-stroke` -- so a
palette can also be adjusted role by role. Paint never changes geometry.

```python
import flexo

paint = flexo.resolve_palette("paper").with_overrides(
    {"container-fill": "#fbfaf7", "connector": "#5b5b5b"}
)
with flexo.Figure("adjusted", width="double-column") as figure:
    with figure.module("m", label="Attention") as module:
        module.mlp("q-mlp", label="MLP")

document = figure.compile(palette=paint).document
```

An unknown role raises `FlexoError` (`palette.role.unknown`) that lists the
valid roles. The legacy palette names `default`, `color-vision-safe`, and
`grayscale` (`DEFAULT_PALETTE`, `COLOR_VISION_SAFE_PALETTE`,
`GRAYSCALE_PALETTE`) keep their exact paint under the `classic` theme; other
themes read them as colour sets.

`flexo retheme` repaints a finished SVG by role without recompiling. It reads
the `data-flexo-fill` and `data-flexo-stroke` attributes on each emitted shape:

```bash
uv run flexo retheme build/fig.editable.svg "Okabe-Ito" --theme paper -o build/fig.cvd.svg
```

To change one component or group only, pass `paint`:

```python
import flexo

with flexo.Figure("painted", width="double-column") as figure:
    with figure.module("m", label="Attention", paint={"fill": "#0d2b26"}) as module:
        module.mlp("q-mlp", label="MLP", paint={"label": "#9fe1cb"})
        module.block("panel", label="Panel", paint={"fill": "#085041", "stroke": "#56bb9a"})
```

`paint` accepts three keys: `fill` and `stroke` (the component or container
body) and `label` (its text or title). Any other key, or a colour that is not
`#rgb` or `#rrggbb`, raises `ValueError` at the call. Parts you leave out keep
their role and retheme normally. `paint` changes no geometry.

Three kinds of paint are literal colours, not roles, and `flexo retheme` leaves
them unchanged: `VectorPreset` cells, `paint=` overrides, and `image` artwork.
Use a preset or an override when one element must differ; change the palette
when every component of a kind should.

### Titles and motifs

A group's title sits at the left of its top edge by default. A component's
motif -- the MLP's three dots, the CNN's zigzag, a matrix's cell grid -- is
decoration that `motif=False` removes:

```python
import flexo

with flexo.Figure("ornament", width="double-column") as figure:
    with figure.root.group("attention", label="Attention module", title_side="right") as module:
        module.mlp("q-mlp", label="MLP", motif=False)
```

`title_side="right"` places the title at the right end of the top edge.
`"bottom-left"` and `"bottom-right"` set it under the contents instead, in a
band of its own. The title band has the same height either way.

A **plate** is how a graphical model writes repetition: a bare frame round the
variables repeated, its count in the bottom-right corner. `plate(id, count)`
opens one; plates nest, and a plate is drawn as a plain frame in every theme.
Latent Dirichlet allocation (Blei et al. 2003) is three circles in two plates:

```python
import flexo

with flexo.Figure("lda", conventions={"lines": "straight"}) as figure:
    with figure.root.row("model") as model:
        alpha = model.circle("alpha", r"$\alpha$")
        with model.plate("documents", "$M$") as documents:
            theta = documents.circle("theta", r"$\theta$", input=alpha)
            with documents.plate("words", "$N$") as words:
                z = words.circle("z", "$z$", input=theta)
                w = words.circle("w", "$w$", shaded=True, input=z)
        beta = model.circle("beta", r"$\beta$")
    figure.connect(beta, w)
```

`module(id, label=...)` opens a titled container anywhere, not only on the
figure: a worker node inside a cluster is `cluster.module("node", label="Node 1")`. A title
accepts styled runs like any label, for example
`label=(TextRun("QK"), TextRun("T", baseline_shift="super"))`. Titles are set
at the style's `title_weight`; a run with a weight other than the default 400
keeps its own weight. `motif=False` changes only the motif: size, body, ports,
and label stay the same.

For `attention`, `channels`, `concat`, `feature-strip`, `graph`, `image`,
`inset`, `matrix`, and `sequence`, the motif sits below the label. The label
takes a band at the top, `motif_label_gap` separates it from the motif, and the
motif fills the rest of the interior. A two-line label makes the box taller
rather than overlapping the motif. An authored `height` still takes precedence;
if it leaves too little room, an `inset` scales its molecule down to fit.

An `add_norm` block has no motif; its label is the whole component.

## Artwork you drew yourself

For content Flexo does not draw -- a molecule, a density map -- draw it as an
`.svg` (or render it to a `.png`) and pass the file to `image`. The example
writes a small SVG so it runs as-is; replace `art` with the path to your own
file.

```python
import pathlib

import flexo

art = pathlib.Path("ligand.svg").resolve()
art.write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 30">'
    '<circle cx="20" cy="15" r="12" fill="#4f9b8f"/></svg>'
)

with flexo.Figure("artwork", width="double-column") as figure:
    with figure.module("m", label="Ligand") as panel:
        ligand = panel.image("ligand", art, width="96pt")
        panel.image("map", art, height="cells:3", label="Density")
        encoder = panel.mlp("encoder", label="Encoder")
        panel.connect(ligand, encoder)
```

An `image` is a component with four pinned ports at its side centres (`input`,
`output`, `north`, `south`). It wires, lays out, and blocks routes like a
block. An SVG source stays vector: Flexo nests the file's content at the
node's bounds with its viewBox intact, so it remains selectable in an editor
and stays vector in the PDF. A PNG is embedded as a data URI. Artwork is
**embedded, not linked**: the editable SVG, portable SVG, and PDF each contain
it.

**Size.** An SVG's intrinsic size comes from its `width` and `height`
attributes, or else from its viewBox read as CSS pixels. A PNG's comes from its
pixel size at 96 dpi. Give only `width` or only `height` and the other follows
the artwork's aspect ratio. Give both and the artwork is letterboxed inside
those bounds. Both accept any length or `"cells:N"`. A file with no size of its
own needs an explicit size.

**Paths.** A relative path resolves against the working directory at compile
time, so absolute paths are more reliable. A missing or unreadable file, or a
suffix other than `.svg` or `.png`, raises `FlexoError` with a diagnostic that
names the node and the path.

**Safety checks.** Artwork is checked before it is inlined. A file is rejected
with a diagnostic, not silently cleaned, if it contains a `<script>` element,
an `on*` event handler, an `href` or `src` that is not a `#fragment` or a
`data:image/` URI, a `url(...)` that is not a `#fragment` or `data:image/` URI,
or a stylesheet `@import`. The XML declaration, DOCTYPE, and comments are
dropped. Every id in the artwork is prefixed with the node's id, so the same
file can be embedded twice without the copies sharing definitions such as
gradients.

**Labels.** A `label` takes a band at the top of the box and the artwork gets
the rest, as on an `inset` or a `matrix`. An authored extent sets the size of
the whole box, so `height="40pt"` on a labelled image shrinks the artwork, not
the label. An image without a label reserves no band and is exactly the size of
its artwork. For a caption below the artwork, put the image and a `label` node
in a column, as `vector` does.

## Shadows

`shadow=True` adds a drop shadow to a group or a node. Shadows are off by
default.

```python
import flexo

with flexo.Figure("shadowed", width="double-column") as figure:
    with figure.root.group("cryo", label="Cryo-EM module", role="module", shadow=True) as module:
        module.mlp("q-mlp", label="MLP", shadow=True)
```

The shadow is built from rounded rectangles, not an SVG filter, because
Inkscape rasterizes filtered regions when it exports PDF. A soft shadow is five
equally faint rectangles offset down and to the right of the box. Each reaches
a fifth less far than the previous one, and together they reach
`shadow_opacity` where all five overlap.

The shadow shows only along the bottom and right edges. The offset is at least
`shadow_spread` (a smaller `shadow_offset` is raised to it), so no layer
extends above the top edge or left of the left edge. `shadow_offset`,
`shadow_spread`, and `shadow_opacity` tune it, and the `shadow` palette role
paints it. The `midcentury` theme draws a single solid offset slab instead. A
group's shadow is drawn only in themes whose containers are filled, outlined,
or dashed.

## Export formats

```python
import flexo
from flexo.gallery import vertical_slice

result = flexo.build(
    vertical_slice(),
    "build",
    stem="slice",
    formats=("editable", "png"),
    dpi=300.0,
)
print(result.report.format())
```

`flexo.build` accepts a `Figure` or a `FigureSpec`. It compiles the figure,
writes the requested formats, and lints the result. Files are written even
when lint reports errors; check `result.ok` or `result.report`.

| Format | File | What it is |
| --- | --- | --- |
| `editable` | `<stem>.editable.svg` | the SVG master: live text, named Inkscape layers, paint roles on every shape. Always written |
| `portable` | `<stem>.portable.svg` | plain SVG with every word drawn as its glyphs' outlines: looks the same in any viewer, with no fonts. Groups keep their ids; each text keeps its words as an `aria-label` |
| `pdf` | `<stem>.pdf` | vector PDF for submission: real, selectable text in embedded TrueType subsets (never Type 3), exact arrowheads, dashes and opacity |
| `png` | `<stem>.preview.png` | a raster preview at `dpi` (default 192), drawn by resvg from the portable SVG |

Every format is written in Python from the editable SVG, read back as a
`flexo.drawing` -- nothing else needs installing. The words in every format are
set in the faces the figure was measured with: the PDF embeds a subset of each
face at each weight used (a variable face at its weight; a CFF `.otf` face is
converted), and the portable SVG and the PNG draw the same glyphs' outlines.
For several figures (or slides) in one PDF, `flexo.pdf.write_pdf([svg1, svg2],
"all.pdf")` writes one page each, sharing fonts.

## Which role paints what

Use this table to find the role to override before writing a palette override.

| Role | Paints |
| --- | --- |
| `canvas` | the page background; the ring around a `junction` dot |
| `ink` | component labels (including `vector` captions), group titles, `channels` captions |
| `muted-ink` | connector and net captions; labels of nodes with `role="caption"`, such as the Q/K/V captions of `attention(vectors=...)` |
| `container-fill` / `container-stroke` | a group's container (or its rule or band, by theme); `sequence` body; `concat` body fill |
| `tone-N-fill` / `tone-N-stroke` / `tone-N-ink` / `tone-N-motif` | a component in tone `N`: body, outline, label, and motif ink (dots, zigzags, cell grids). Tones are numbered in the order they first appear in the figure. Attention, matrix, add-norm, MLP, CNN, feature-strip, sequence, prediction, and loss components carry a tone by kind in every theme except `classic`, and `tone=` gives any component one |
| `block-fill` / `block-stroke` / `block-motif` | an untoned `block`, `tensor`, `concat`, `op` |
| `accent-*`, `warm-*` | legacy names; in every theme except `classic` they equal `tone-1-*` and `tone-2-*` |
| `inset-fill` / `inset-stroke` | `graph` and `inset` bodies and borders |
| `connector` | edge shafts, net pieces, flow arrowheads, junction dots, the `junction` component's body, the `channels` split path |
| `residual` | connectors authored with `role="residual"`, arrowheads included |
| `ramp-node`, `ramp-embedding`, `ramp-q`, `ramp-kv`, `ramp-attended`, `ramp-output` | `vector` cells -- one role per glyph, fill and stroke, graded by `fill-opacity` |
| `shadow` | a `shadow=True` drop shadow (soft layers, or one slab in `midcentury`) |
| `grid` | defined by every palette; no renderer uses it |
