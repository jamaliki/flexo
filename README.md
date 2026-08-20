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

## Quick start

```bash
uv sync --all-groups
```

The smallest figure worth drawing, and the one call that builds it:

```python
import flexo

with flexo.Figure("hello", width="single-column") as figure:
    with figure.module("encoder", label="Encoder") as module:
        features = module.feature_strip("features", label="Node features")
        module.mlp("head", input=features)

result = flexo.build(figure, "build", stem="hello", formats=("editable",))
print(result.summary())
```

`flexo.build` compiles, writes the formats you asked for, and lints — the three
calls a figure script used to make by hand. It returns the `Compilation`, the
paths it wrote, and the `LintReport`; outputs are written even when the report
has errors, so a flawed figure stays inspectable. `figure.render(...)` is the
same call spelled as a method.

Everything an author needs is re-exported from `flexo`, so one import line is
enough. Derived formats (`portable`, `pdf`, `png`) need Inkscape; `editable`
never does.

Fuller examples live in [`examples/`](examples/README.md).

## Authoring tour

### Components and wiring

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

Every component factory takes the same wiring keywords, so connecting a node
never depends on which one you reached for. `input=` takes one upstream value and
`inputs=` takes several; both work on `node` itself and on all of `block`,
`image`, `inset`, `graph`, `matrix`, `sequence`, `tensor`, `feature_strip`,
`vector`, `channels`, `add_norm`, `mlp`, `cnn`, `prediction`, and `loss`. One
source lands on the component's `input` port; several land on `input1`, `input2`,
… where the component has them and share `input` where it does not. `ports=`
composes with the factories that compute ports of their own — give `mlp` a port
table and yours is used whole, and the sources you passed are wired to the input
ports it declares.

Ids are scoped by the group that owns them, so `module.mlp("head")` inside
`encoder` is `encoder.head`; that is what lets the same component name appear in
every module of a figure.

#### Components you can create before their inputs exist

Wiring at creation is a convenience, never a requirement. **No component needs a
source to be created**, `attention` included: `q`, `k`, and `v` wire straight into
its three ports when they are given, and the ports are there either way.

```python
import flexo

with flexo.Figure("transformer", width="double-column") as figure:
    with figure.module("decoder", layout="column") as decoder:
        cross = decoder.attention("xmha", label="Multi-Head\nAttention")
    with figure.module("encoder", layout="column") as encoder:
        top = encoder.add_norm("an", label="Add & Norm")
    figure.net(src=top, sinks=[cross.k, cross.v], id="cross-kv")
```

A figure is not always written in flow order. A decoder's cross-attention reads
keys and values from an encoder that appears *later* in the source, and a
component that could not exist before its inputs would force the whole tower to be
authored inside out.

#### Attention that grows its own Q, K, V

`vectors=` draws the three values an attention block reads as vector glyphs
underneath it, the way the Transformer paper does — one cell stack per port, each
**centred exactly under the port it feeds**, captioned to one side:

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
    figure.root.connect(mha, norm)
```

`vectors=True` takes the palette's own `ramp-q` and `ramp-kv` roles (keys and
values share one, because they are read together). One `VectorPreset` or one ramp
role name paints all three alike, and a `{"q": ..., "k": ..., "v": ...}` mapping
paints each its own way — keyed case-insensitively, so the mapping you named `Q`,
`K`, `V` after the captions goes straight in. `vectors=None`, the default, is the
plain block: nothing about a figure that never asks for glyphs changes.

**The engine does the arithmetic.** Centring a glyph under a port at 0.24 of a
120pt block is the sort of sum that ends up as a magic inter-glyph gap in the
figure that needs it — and then silently wrong the next time the component's port
table moves. Here the block's own port offsets become the reserved column widths
of a one-row grid exactly as wide as the block: a pad, then a lane per port, then
a pad. A glyph centred in its lane *is* centred under its port, so the connector
between them comes out a plain two-point vertical with nothing to route around,
and the corridor above the glyphs is the ordinary edge-aware sibling gap rather
than a number anybody wrote down. The composite needs a `width` for that reason,
and says so if it does not get one.

The handle still speaks for the block — `output` is the attention output — but
`q`, `k` and `v` now answer from the **glyphs**, because that is where a value
entering this attention arrives:

```python
figure.net(src=embedding, sinks=[mha.q, mha.k, mha.v], id="qkv")   # into the glyphs
figure.root.connect(mha, norm)                                     # out of the block
```

Both of a glyph's ports are pinned, and that is the point: north is the drop into
the attention port above it, south is the feed. A value computed off to one side
travels to below its glyph and comes up, rather than entering between two glyphs
— a lane is only as wide as the port spacing it was cut from, so two runs
entering sideways would have to thread the same gap at the same height.

**The caption stands beside its stack**, not under it, and that follows from the
same sentence: the corridor under a glyph is the only approach its feed has, so a
caption parked in it makes every arriving arrow hook around the words. Beside, the
feeds are dead-straight verticals. The room is the lane's own surplus — a lane is
wider than the stack in it — so the caption takes the half-lane it stands in less
one `caption_clearance` of air, the glyph reserves that same room on the stack's
other side as padding, and the whole glyph comes out exactly one lane wide and
symmetric about its cells. The stack therefore keeps the port's x whichever side
the words take, and it is one side for all three: three captions leaning the same
way read as a convention, a mirrored pair around a middle glyph reads as an
accident. A lane too narrow to hold a caption beside the stack (an attention
pinned under about 56pt) puts it back underneath, `arrival_clearance +
caption_clearance` down, so the approach is at least still open.

A standalone `vector()` keeps its caption below, as it always has: it is wired
from the side and has no approach from underneath to protect.

Lanes are filled in **port-offset order**, not in q/k/v order, so an authored
`ports=` that reads the value on the left puts that glyph on the left too — which
is how the paper draws a cross-attention, with the encoder's V and K nearest the
line that feeds them and the decoder's own Q clear of it on the right:

```python
CROSS_PORTS = (
    flexo.PortSpec("v", flexo.Side.SOUTH, 0.24, adaptive=True, auto_side=True),
    flexo.PortSpec("k", flexo.Side.SOUTH, 0.5, adaptive=True, auto_side=True),
    flexo.PortSpec("q", flexo.Side.SOUTH, 0.76, adaptive=True, auto_side=True),
    flexo.PortSpec("output", flexo.Side.NORTH, 0.5, adaptive=True, auto_side=True),
)
```

In a ports-aligned parent the composite answers with the **block**, so a row of
towers lines up on the attention boxes rather than on the glyph row hanging
beneath them — the same principle as a `vector()` answering with its cell stack
rather than with its caption. See
[`examples/transformer.py`](examples/transformer.py) for all three attention
blocks of a Transformer authored this way.

#### Residual blocks name both of their wires

`add_norm` is a residual join, so it has a port for each wire rather than one
`input` doing double duty:

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

`input` is what the sublayer computed and `skip` is what went round it; `output`
carries the sum onward and `branch` is the same value tapped for the *next*
block's skip. Sending two values into one `input` puts two arrowheads on one point
— two runs a hair apart, each with a hook where the router pulled it off its twin,
and a `routing.track.separation` error for the pair. Naming the second arrival is
the fix, and `add_norm(input=..., skip=...)` says it at the point of creation.
`residual()` prefers a `residual` or `skip` port automatically for the same
reason.

`input` and `output` are auto-sided, so a tower that reads upward gets its spine
on the edges its ink actually uses with no port table written down. `skip` and
`branch` are **pinned east** instead: a residual is a convention, not a per-node
optimisation, and auto-siding sent one tower's bypass up the right margin and its
neighbour's up the left, so a reader who had learnt "the residual is the wire on
the right" had to learn it again per tower. Both stay adaptive — each slides
along the east edge to meet its counterpart — and they take two lanes there,
`skip` low and `branch` high, because a bypass arrives from below the block it
rejoins and leaves for the one above. The consequence to plan for is room: a
pinned bypass routes *outside* the block, so a content-hugging container needs
side padding (the reference Transformer's towers carry `34pt`) or routing has
nowhere to put the corridor. An author who wants a left-handed figure writes
`ports=` and gets it, exactly as an explicit port table has always worked.

#### Ports pick the side they face

A component's default ports carry a side because geometry needs one, and the
grammar can only guess the common case: values enter west and leave east. Figures
are not all read that way, so **a defaulted port chooses its side after layout,
before routing** — the side whose outward normal points at whatever the port is
wired to. A column of blocks comes out with south and north ports, a readout row
hanging under a trunk is entered from above, and neither costs a line of port
authoring.

The rules, in full:

- **an authored `PortSpec` is pinned.** Writing the side down is the choice, and
  nothing overrules it — neither for that port nor for the offset and adaptivity
  beside it. So is a port named by an edge carrying a `depart`/`arrive` hint.
- **a port whose side *is* the convention is pinned by the grammar.** `add_norm`'s
  `skip` and `branch` are the case in the box: a residual that changed hands from
  tower to tower would make the reader re-learn the figure, so those two are born
  east and stay east while the spine beside them auto-sides.
- **a net votes once, for its trunk.** A stem runs to the shared rail, not to the
  far port, so a wide fan-out does not drag its source port sideways toward
  whichever head happens to sit furthest out.
- **an edge routed through an authored corridor casts no vote.** Its ink goes
  where `lane=` sent it, not where its counterpart sits.
- **`via=` decides the side it arrives on.** Ink that comes round the west arrives
  from the west, so a `via` hint settles the *entry* side of an auto-sided target
  port — see *`via=`: which side a route should keep to*. The departure keeps its
  own vote.
- **a near-diagonal relationship names no side.** Below a decisive margin the
  grammar's own side stands, because a port that flipped on a few points of
  layout drift would be a worse surprise than one that never moved.
- **a loop-back does not share a side with the spine it leaves.** Where the onward
  hop and the return both face the same way, the short one keeps the straight run
  and the long one takes the wider margin beside the node — which is the lane its
  rail was going to travel anyway.
- **a port asked to face two ways at once** picks the side of least mismatch and
  says so, as a `layout.port.side.conflicted` lint note naming the node and
  suggesting explicit ports.

Ports no edge or net mentions keep the side they were born with; they are
invisible either way. And the choice is the compiler's, not the document's: the
figure serializes with the sides it was written with, and re-compiles to the same
picture.

### Feature values as vector glyphs

A feature value is not a box. `vector()` composes a vertical stack of rounded
cells with its caption below, and returns the cells so arrows attach to the glyph
itself:

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

A vector's four ports are its four side centres — west and east on the *middle
cell* — so a run into a vector comes out straight. The caption is a real node, so
routes keep clear of it; the one thing to know is that it sits directly under the
glyph's *south* port, so a route leaving south has to be given room (panel b
sends its prediction path out of `attended.north` for exactly that reason).

The `ramp` is paint only: `ramp-node`, `ramp-embedding`, `ramp-q`, `ramp-kv`,
`ramp-attended`, and `ramp-output` are defined by every palette, so `flexo
retheme` re-colours a figure without moving a coordinate.

When a panel needs its own colours instead, a `VectorPreset` carries one base
colour and a topology written columns-first, and derives the opaque shades of
each column for you:

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

A ramp says *ordered*, which is a claim about the data. Real activations are not
ordered, so a preset **shuffles by default**: `order="shuffled"` permutes each
column's shades and the glyph reads as a feature vector. The gradient is the
special case, and it is asked for by name:

```python
import flexo

with flexo.Figure("ordered", width="double-column") as figure:
    with figure.module("m", label="Attention") as module:
        module.vector("q", label="Q", preset=flexo.VectorPreset("#e2703a", "1x3"))
        ramped = flexo.VectorPreset("#e2703a", "1x3", order="ramp")
        module.vector("scale", label="Scale", preset=ramped)
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

### Grids, spacing, and alignment

A module whose chains should line up is a `grid`: rows are the chains, and columns
line them up. Cells are addressed, not counted. A child names its cell with
`at=(row, column)`, 0-indexed from the top left; the children that do not name
one keep author order and flow row-major into whatever cells are left. Nothing has
to fill the holes — a short last row, an empty column, or a gap in the middle of a
row costs no nodes at all:

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

Column 3 above holds no child in either row: it is the corridor the attention
arrow runs down, and its formula has to fit above it. `column_widths={index:
length}` reserves a minimum width for a column even when every cell in it is
empty, so the lane needs no width-carrying `spacer` node to prop it open. Row 1
is one cell long and the six cells beside it simply do not exist.

Mixed mode is deterministic: addressed children claim their cells first, then the
unaddressed ones flow into the remainder. A child addressed at (0, 4) pushes no
sibling sideways — the flow steps over that cell when it reaches it. Two children
addressed to the same cell, or a column outside the grid, is an error where it is
written rather than a puzzle in the rendered figure.

#### Spacing that is not square

`gap` spaces siblings on both axes at once, which is the wrong knob whenever a
panel wants vertical air: buying it out of a seven-column grid's gap spreads the
panel six times as far sideways. `row_gap` and `column_gap` override `gap` on one
axis each — a row reads `column_gap`, a column or stack reads `row_gap`, and a
grid reads both. `padding` is one length for all four sides, an `(x, y)` pair, or
a `(top, right, bottom, left)` 4-tuple:

```python
import flexo

with flexo.Figure("spacing", width="double-column") as figure:
    figure.root.group(
        "attention",
        layout="grid",
        columns=7,
        row_gap=flexo.pt(19),
        column_gap=flexo.pt(19),
        padding=(flexo.pt(11.5), flexo.pt(11.5), flexo.pt(32.5), flexo.pt(11.5)),
    )
```

The four sides are what let a panel's sides sit tighter than its top and bottom,
which is usually what a figure wants: captions hang below the bottom row, so the
floor needs more air than the flanks. Every one of these falls back to the value
it refines — `row_gap` to `gap` to the style token, each padding side to
`padding` — so a figure that asks for none of them keeps exactly the geometry it
had.

#### Aligning by port line instead of by box

`align` normally lines up *boxes*: `start`, `center`, `end`, and `stretch` all
ask where a child's rectangle sits across the axis it is not laid out along. That
is the wrong question for a figure made of arrows. A vector's caption is a
sibling node under its cell stack, so the composite's box is half again as tall
as the glyph and its middle is somewhere in the caption; align two of those by
box and their arrows run uphill.

`align="ports"` aligns the line the side ports live on, exactly the way type sits
on a baseline:

```python
import flexo

with flexo.Figure("ports", width="double-column") as figure:
    with figure.module("m", label="Cryo-EM module") as outer:
        with outer.grid("cryo", columns=7, align="ports") as grid:
            rects = grid.inset("rectangles", label="Edge\nrectangles", height="60pt")
            edge_cnn = grid.cnn("edge-cnn", input=rects)
            grid.vector("kv", label="K, V", ramp="ramp-kv", input=edge_cnn)
```

In a **row** each child is placed so its horizontal anchor — the y of its west
and east ports — lands on the row's shared line; in a **column**, so its vertical
anchor — the x of its north and south ports — lands on the column's shared x. A
grid does both, per row and per column. The line is measured like a line of type:
the row's **ascent** is the furthest any child reaches above it, its **descent**
the furthest below, and the row reserves both — so a ports-aligned row can be
*taller* than its tallest child, because two children may hang off the line in
opposite directions.

An anchor propagates up. A plain component answers with its own centre, which is
where the grammar puts a side-centre port. A group answers with its **anchor
child's** line, carried into the group's coordinates: the child named by
`anchor="<child>"`, or failing that the first child that is neither a label nor a
spacer. That default is what makes a captioned vector answer with its cell stack
rather than with cells-plus-caption, so the caption hangs below the shared line
instead of dragging it down. Name one explicitly when the first real child is not
the one the arrows use:

```python
import flexo

with flexo.Figure("anchor", width="double-column") as figure:
    with figure.module("m", label="Panel") as row:
        with row.column("panel", align="center", anchor="body") as panel:
            panel.block("badge", label="fig. 1")
            panel.mlp("body", label="Encoder")
```

Bounding-box alignment remains the default, and nothing about `center` has
changed — reach for `ports` when a figure is chains of components joined by
arrows, and leave it alone when a group is a shelf of unconnected panels.

#### Heights that match a vector stack

A box that should be exactly as tall as a vector's cell stack says so with
`"cells:N"`. For merely lining the *ports* up, reach for `align="ports"` above;
this is for when the matching height is itself the design.
`vector_stack_height(style, cells)` is the same arithmetic in Python:

```python
import flexo

with flexo.Figure("heights", width="double-column") as figure:
    with figure.module("m", label="Attention") as module:
        nodes = module.vector("nodes", label="Node features", ramp="ramp-node")
        module.mlp("q-mlp", input=nodes, height="cells:3")
        module.mlp("k-mlp", height=flexo.vector_stack_height(flexo.STYLES["paper"], 3))
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
import flexo


def band(root, id):
    """One band row, always starting with the spine column."""

    return root.row(id, gap="24pt", padding=0, align="start", role="layout")


layout = flexo.LayoutSpec("column", gap=flexo.pt(20), align="start")
with flexo.Figure("gnn", width="presentation", layout=layout) as figure:
    with band(figure.root, "band1") as module_band:
        previous = module_band.block("previous", label="Previous layer", width="72pt")
        module_band.group("sequence", label="Sequence module", role="module", shadow=True)
    with band(figure.root, "strip1") as strip:
        strip.add_norm("addln1", label="Add LN", width="72pt", input=previous)
```

No port table appears in that sketch. The spine reads downward, so the spine
blocks' `input` and `output` face north and south on their own (see *Ports pick
the side they face*); the one port that has to be named is the `feedback` port a
residual rail arrives on, because that rail is routed through an authored lane and
so has no counterpart to face. A spine block whose bypass arrives from an
authored lane rather than from the block below names its arrival too — the
gallery's `add-norm` puts `skip` on the north, which is a port table overruling
the east-pinned default on purpose.

Why the alternation matters: a spine block level with the *top* of the module it
feeds has no reachable east side, so its feedback rail is forced up and over the
module. Give it its own strip and the same rail reads correctly — east out of the
module's update MLP, south past the module, west along the strip, into the east
feedback port, always below the module. The strip is also where a fan-out net from
the last spine block lands its rail, between that block and the row it feeds
instead of below it.

Three uses of the zero-size `spacer` component hold that grid open without
padding anything:

- a `width`-only spacer in the spine cell of a module band, so every band's
  spine column shares one x;
- a zero-size spacer *after* the module, which carries the band's right edge one
  gutter past it — `lane="<band>-right"` then names an empty column where a
  residual rail can drop south. Inside the module the container fill would paint
  over it.
- a `height`-only spacer row above a row of heads, reserving the fan-out
  corridor in one direction only. A single `padding` would reserve it on all four
  sides and leave a dead strip at the canvas edge.

[`flexo/gallery.py`](src/flexo/gallery.py)'s `modelangelo_gnn` is authored this
way; its canvas ends at the content plus the ordinary margin on every side.

### Nets and rails

Shared values and true combinations are authored explicitly rather than inferred
from coincident lines:

```python
import flexo

with flexo.Figure("nets", width="double-column") as figure:
    with figure.module("m", label="Readout", layout="column") as module:
        trunk = module.add_norm("addln", label="Add LN")
        with module.row("heads", gap="18pt", padding=0, role="layout") as heads:
            first = heads.mlp("first", label="MLP")
            second = heads.mlp("second", label="MLP")
            third = heads.mlp("third", label="MLP")
        average = module.block("average", label="Average")
    figure.net(src=trunk, sinks=[first, second, third])
    figure.merge(sinks=[first, second, third], dst=average, rail="east", label="Average")
```

`net` emits one trunk with branches after the source; `merge` emits one rail and
combines before the destination. Only destination stems receive arrowheads, and
junction dots mark forks and merges only. Where a rail terminal serves a single
stem there is no fork, so rail and stem share one rounded corner instead of
meeting at a sharp one. The paper style turns every corner on a 6 pt elbow
fillet; set `elbow_radius=pt(0)` on a derived `LayoutStyle` for a sharp
technical-drawing treatment.

`net` and `merge` are figure-level calls, and also methods on every group builder:
`root.net(...)` works wherever `root.connect(...)` does, with the same arguments
and the same result, so authoring a net never means reaching back out of the block
you are writing.

An unhinted rail sits **in the middle of the free corridor** its stems leave it —
the gap between the hub component's edge and the nearest edge of what it feeds.
Trunk and stems each get half the run, so the rail reads as a corridor the figure
meant to leave rather than as a line drawn against the box its branches come out
of. The exception is a captioned rail in a corridor too narrow to halve: the
caption is written above the run, so halving it would draw the rail through the
words, and such a rail stays at the end of the corridor and hands the whole run to
the caption.

A trunk that leaves **along** the axis its rail runs on — an encoder's output
crossing the page into a decoder's cross-attention — halves its own run the same
way. Such a trunk draws a Z: a stretch along the port axis, a crossbar over to the
rail, and the rail carrying on the same way. The crossbar defaults to the middle of
the run between the hub's escape and the first stem it passes, so the two arms are
arms of one step instead of a stub, a long crossbar drawn against the box the
trunk just left, and the whole run beyond it. `rail`, `rail_at` and `via` place
the net themselves, and switch the default off.

Two hints place and mark that joint:

```python
import flexo

with flexo.Figure("joint", width="double-column") as figure:
    with figure.module("m", label="Attention") as module:
        q = module.vector("q", label="Q", ramp="ramp-q")
        kv = module.vector("kv", label="K, V", ramp="ramp-kv", columns=2)
        attended = module.vector("attended", ramp="ramp-attended")
        module.merge(sinks=[q, kv], dst=attended, rail_at=0.55, joint="arrow")
```

`rail_at=0.55` asks for the shared rail partway along the trunk run — the fraction
is measured from the trunk's start toward the destination, so a merge that would
otherwise join just before its sink can join mid-run instead. It is a request:
where clearances forbid it the router moves to the nearest rail that fits and
reports `routing.net.rail-at.clamped` as a lint warning rather than silently
obeying or failing. `joint="arrow"` then ends the joining ink in an arrowhead one
standoff short of the run it points into, leaving the trunk unbroken and dropping
the dot that would otherwise mark the branch; `joint="dot"` insists on the dot
even under `junction_dots="never"`.

#### Single-jog routes cross in the middle

Two ports that do not line up give a **Z**: a run out of the source, one crossbar,
and a run into the target the same way. Any coordinate in the span between the two
ports' clearance boundaries draws that shape with the same length and the same one
elbow, so the search has no reason to prefer one — and picking whichever it reached
first leaves the crossbar against an endpoint, which reads as an L with a kink in
it rather than as a step across. The default is the **midpoint of the free span**:
the stretch between those two clearance boundaries, less anything an obstacle
standing across the crossbar takes out of it.

A **C** — a route whose two arms double back over each other, wrapping a module or
running up a margin — keeps its corridor. Its arms share no span to be centred in,
and the corridor it took was chosen against the whole figure rather than between
two ports. So does any route the author aimed with `lane=`, a waypoint, or `via=`,
and any pair of parallel jogs a lane apart: balancing never overrides a hint, and
never pulls two crossings onto one coordinate.

#### `via=`: which side a route should keep to

A route that has to leave the straight line between its endpoints has two ways
round whatever stands in the way, and the router cannot see which one *reads*. A
connector that wraps the far face of a tower comes back through it; the same
connector taken round the near side stays in the margin. `via=` is one word for
which margin:

```python
root.connect(source, target, via="west")
figure.net(src=encoder_top, sinks=[cross.k, cross.v], via="west")
figure.merge(sinks=[first, second], dst=average, via="south")
```

It takes a `Side` or a side name on `connect`, `residual`, `net`, and `merge`, and
defaults to no hint at all. Three things follow from it:

- **the route pays for the corridor it refused.** Length spent beyond the region
  its two endpoints span, on the side opposite the hint, costs extra
  (`PathCosts.off_side`) — enough that the near corridor wins wherever it exists,
  little enough that the far one is still available when it is the only one.
  Inside the region nothing is priced: every route has to cross it.
- **a net answers with its rail.** The side names the axis the rail runs along —
  west and east rail vertically, north and south horizontally, exactly as `rail=`
  reads it — and the rail is then placed as far toward that side as its stems and
  the obstacles allow. Unlike `rail=`, which *pins* the rail to the routing
  boundary, `via=` is a lean, so it may not be combined with `rail=` or `rail_at=`.
- **the arrival faces the hint.** Ink that comes round the west arrives from the
  west, so an auto-sided target port takes that side (an authored `PortSpec` or a
  `depart`/`arrive` hint still wins). The departure keeps its own vote: a route may
  perfectly well leave east and still be asked to stay west of the tower it is
  crossing to.

Like `rail_at`, it is a request. Where the geometry leaves no corridor on that
side the router takes the nearest one and reports it —
`routing.via.clamped` for an edge, `routing.net.via.clamped` for a net — naming
the side it actually achieved, rather than failing or silently obeying.

A connector's own caption — a net's formula, an edge's `ESM-1b` — is route
geometry rather than a node, so no obstacle rule reaches it and it has to place
itself clear. It does, with `caption_clearance` measured from the other side: the
words sit that far above the run's ink, counting from the bottom of their own
descender box, which a subscript makes deeper than the font's descender. They also
keep clear *sideways*. A riser out of the middle of the run cuts it in two, and
the caption takes the wider stretch that is left rather than the midpoint of a run
it would be sitting across — which is how `softmax(QKᵀ)V` ends up left of the K,V
riser in panel b instead of flush against it.

Attention then reads as a formula rather than as a matrix: the merge carries its
caption in styled runs (`TextRun("T", baseline_shift="super")`) and Flexo anchors
it above the horizontal run the arrow draws.

### Paint: palettes, overrides, and retheming

Palette roles are how a figure stays rethemeable. A whole theme is a set of
overrides on an existing palette, and it moves no geometry:

```python
import flexo

dark = flexo.DEFAULT_PALETTE.with_overrides(
    {
        "container-fill": "#444441",
        "container-stroke": "#444441",
        "block-fill": "#085041",
        "block-stroke": "#56bb9a",
        "ink": "#eceae4",
        "muted-ink": "#c3c2b7",
        "connector": "#898781",
    }
)
with flexo.Figure("dark", width="double-column") as figure:
    with figure.module("m", label="Attention") as module:
        module.mlp("q-mlp", label="MLP")

document = figure.compile(palette=dark).document
```

An unknown role is a diagnostic listing the valid ones, so a typo cannot silently
paint nothing. Three palettes ship: `default`, `color-vision-safe` (Okabe–Ito
hues), and `grayscale` (ramps separated by lightness, so they stay tellable apart
without hue). `flexo retheme` re-paints a *finished* SVG by role, with no
recompile — which is what the `data-flexo-fill` and `data-flexo-stroke`
attributes on every emitted shape are for.

When exactly one component or module must differ — a caption that has to clear its
own dark body, say — `paint` overrides the role for that one entity:

```python
import flexo

with flexo.Figure("painted", width="double-column") as figure:
    with figure.module("m", label="Attention", paint={"fill": "#0d2b26"}) as module:
        module.mlp("q-mlp", label="MLP", paint={"label": "#9fe1cb"})
        module.block("panel", label="Panel", paint={"fill": "#085041", "stroke": "#56bb9a"})
```

The three parts are `fill` and `stroke` (the component or container body) and
`label` (its text or title); any other key is an error where it is written, as is
a colour that is not `#rgb` or `#rrggbb`. Parts left out keep their role and
retheme normally. `paint` is paint: it moves nothing, on a group or a node.

Three kinds of ink are **literal colour rather than a role**, and `flexo retheme`
walks straight past all three: `VectorPreset` cells, any `paint=` override, and an
`image`'s embedded artwork. Reach for a preset or an override when one panel has
to differ; change the palette when every component of a kind does.

#### Titles and motifs

A group's title sits at the left of its top edge unless it asks otherwise, and
component motifs — the MLP's three dots, the CNN's zigzag, a matrix's cell grid —
are ornament that `motif=False` drops:

```python
import flexo

with flexo.Figure("ornament", width="double-column") as figure:
    with figure.root.group("attention", label="Attention module", title_side="right") as module:
        module.mlp("q-mlp", label="MLP", motif=False)
```

`title_side="right"` anchors the title to the right end instead. The title band is
the same height either way, so nothing in the figure moves. A title takes styled
runs like any other label — `label=(TextRun("QK"), TextRun("T",
baseline_shift="super"))` — and is set at the style's `title_weight`, which a run
inherits unless it asks for a weight of its own; and `motif=False`
changes nothing else either — same size, same body, same ports, same label. Reach
for it when a panel repeats a component often enough that its ornament becomes
noise.

A motif that sits *below* the words rather than behind them — `inset`, `graph`,
`matrix`, `attention`, `sequence`, `concat`, `feature-strip` — stacks the two: the
label takes a band at the top, `motif_label_gap` of air comes off after it, and
the motif gets the rest of the interior. One band model, so a component's
intrinsic height, its label's baseline, and the area its motif paints in are the
same three numbers everywhere; a two-line caption makes the box taller instead of
being drawn over the drawing it names. An authored `height` still wins, and when
it leaves less room than the illustration wants, an `inset` scales its molecule
down to fit rather than colliding with the words.

An add-norm carries no motif: the words are the component. A circled plus before
`Add LN` says a second time what the label already says, and in a figure with an
Add/LN on every band it reads as clutter.

### Artwork you drew yourself

Some ink is not the compiler's to invent — a molecule, a density-map view, the one
panel that has to be the real thing. Draw it as an `.svg` (or render it to a
`.png`) and hand Flexo the file:

```python
import flexo

with flexo.Figure("artwork", width="double-column") as figure:
    with figure.module("m", label="Ligand") as panel:
        ligand = panel.image("ligand", "/figures/art/ligand.svg", width="96pt")
        panel.image("map", "/figures/art/density.png", height="cells:3", label="Density")
        encoder = panel.mlp("encoder", label="Encoder")
        panel.connect(ligand, encoder)
```

An `image` is an ordinary component with the four side-centre ports, so it wires,
lays out, and blocks routes exactly as a block does. An SVG source stays vector
the whole way: Flexo nests the file's own content at the node's bounds with its
viewBox intact, so the drawing is crisp at any zoom, still made of objects an
editor can select, and comes out as vector art in the PDF too. Artwork is
**embedded, not linked** — the editable SVG, the portable SVG, and the PDF each
carry it, with no companion file to lose.

Size follows the file. Its intrinsic size comes from its `width` and `height`, or
from its viewBox read as CSS pixels; a PNG's comes from its pixel size at 96 dpi.
Give `width` or `height` alone and the other follows the artwork's aspect ratio;
give both and the drawing letterboxes inside those bounds rather than distorting.
Both take any length or `"cells:N"`, so a row of icons can be exactly as tall as
the vector stack beside it. A file that declares no size at all has to be given
one. The path resolves against the working directory the figure is *compiled* in,
so absolute paths are the reliable choice; a missing file, an unreadable one, or a
suffix that is neither `.svg` nor `.png` is a diagnostic naming the node and the
path.

Artwork is checked before it is inlined, because inlining is what would make it
dangerous. A file carrying a `<script>` element, an `on*` event handler, or a
reference to anything outside itself — an `href` to `https://…` or to a
neighbouring file, a `url(…)` that is not a `#fragment`, a stylesheet `@import` —
is **rejected with a diagnostic**, not quietly stripped: a drawing that would not
survive embedding intact is one you want to hear about while you can still
re-export it. The XML declaration, the DOCTYPE, and comments never travel. Every
id in the artwork is rewritten under the node's id, so the same file may be
embedded twice in one figure without the two copies sharing a gradient.

A `label` **takes a band off the top and the artwork takes the rest**, exactly as
it does on an `inset` or a `matrix`: the words name the drawing, so they are never
printed across it. An authored extent is the box, which means `height="40pt"` on a
captioned image shrinks the *drawing* — the caption's line is the one size in
there the author did not choose. An image with no label reserves nothing and comes
out exactly as large as the file it carries. For a caption that hangs *under* the
drawing instead, put the image and a `label` node in a column, the way `vector`
captions its stack.

### Shadows

`shadow=True` gives a group or a node a soft drop shadow, and it is off everywhere
until asked for:

```python
import flexo

with flexo.Figure("shadowed", width="double-column") as figure:
    with figure.root.group("cryo", label="Cryo-EM module", role="module", shadow=True) as module:
        module.mlp("q-mlp", label="MLP", shadow=True)
```

It is built from nested rounded rectangles, not from an SVG filter, and that is
not an implementation detail to be tidied away later: Flexo's figures leave as
editable SVG and arrive as PDF through Inkscape, which does not know
`feDropShadow` at all and turns any `feGaussianBlur` subtree into a 96 dpi bitmap.
Either would put a raster patch behind every shadowed box in an otherwise fully
vector figure. Five equally faint rectangles, each reaching a fifth less far than
the last and all offset together down and to the right of the box, grade to
`shadow_opacity` where they overlap and stay selectable objects all the way to
print.

The figure is lit from the top left, so a shadow shows along the **bottom and
right** edges and nowhere else — a shadow that rings all four is a halo, not
light. That is geometry rather than clipping: with `shadow_offset` at least
`shadow_spread`, the widest layer's top-left corner lands on the box's own
top-left corner and every tighter layer starts further in, so no layer can put ink
above the top edge or left of the left edge at any corner radius. A smaller offset
is raised to the spread rather than drawn. `shadow_offset`, `shadow_spread`, and
`shadow_opacity` tune it; the `shadow` palette role paints it, so `flexo retheme`
moves it with everything else.

### Export formats

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

| Format | What it is |
| --- | --- |
| `editable` | the SVG master: live text, named Inkscape layers, paint roles on every shape. Always written |
| `portable` | the same figure as plain SVG, for viewers that do not know Inkscape's namespace |
| `pdf` | vector PDF for submission |
| `png` | a raster preview at `dpi` |

Everything but `editable` is produced from it by Inkscape, which must be on
`PATH`, in the standard macOS application location, or named by `FLEXO_INKSCAPE`.

## Which role paints what

An author overriding a palette needs to know which role reaches which ink before
writing the override, not after grepping the renderer. An `mlp` paints `block-*`,
not `accent-*`; a caption under an arrow paints `muted-ink` while a caption inside
a box paints `ink`.

| Role | Paints |
| --- | --- |
| `canvas` | the page background; the ring around a `junction` dot |
| `ink` | component labels, group titles, `channels` captions |
| `muted-ink` | connector and net captions — and nothing else |
| `container-fill` / `container-stroke` | a group's container rect; `sequence` body; `concat` body fill; the border of `graph` and `inset` |
| `block-fill` / `block-stroke` | `block`, `mlp`, `cnn`, `add-norm`, `tensor` bodies; `concat` body stroke. `block-stroke` also draws their motifs: MLP dots, CNN zigzag, sequence tokens, concat bars |
| `accent-fill` / `accent-stroke` | `matrix`, `attention`, `feature-strip` bodies. `accent-stroke` also draws matrix and attention cell grids, feature-strip cells, `graph` nodes and edges, `inset` spokes, `channels` bars |
| `warm-fill` / `warm-stroke` | `prediction` and `loss` bodies; `warm-stroke` also the `inset` centre dot |
| `inset-fill` | `graph` and `inset` bodies, bordered in `container-stroke` |
| `connector` | edge shafts, net rails and stems, flow arrowheads, junction dots, the `junction` component's body, the `channels` split path |
| `residual` | the same ink for anything authored `role="residual"`, arrowheads included |
| `ramp-node`, `ramp-embedding`, `ramp-q`, `ramp-kv`, `ramp-attended`, `ramp-output` | `vector` cells — one role per glyph, fill and stroke, graded by `fill-opacity` |
| `shadow` | the nested rectangles of a `shadow=True` drop shadow |
| `grid` | defined by every palette, painted by nothing today |

## Command line

```bash
uv run flexo build examples/vertical_slice.yaml --output examples/build
uv run flexo check examples/vertical_slice.yaml
uv run flexo inspect examples/vertical_slice.yaml
uv run flexo gallery --output examples/build
uv run flexo retheme build/slice.editable.svg grayscale -o build/slice.gray.svg
uv run flexo schema
```

The builder lowers to the same validated, versioned schema that YAML and JSON
parse into, so a figure is one thing written two ways — see
[`examples/vertical_slice.py`](examples/vertical_slice.py) and its
[YAML equivalent](examples/vertical_slice.yaml).

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

See [the architecture](docs/architecture.md), [the implementation report](docs/implementation-report.md),
and [the improvement beam](docs/improvement-beam.md).

## Design principles

- semantic authoring instead of routine SVG coordinates;
- immutable, deterministic compiler passes;
- physical publication dimensions and measured typography;
- stable semantic IDs, named ports, and localized diagnostics;
- first-class fan-out nets and authored merge rails;
- defaults that read the figure they are in, and authored values that always win;
- orthogonal routing with a theme-controlled local elbow radius;
- connector ink painted after the components it joins, so no run is interrupted
  by a container fill;
- native SVG primitives, live text, and named Inkscape layers;
- explicit editorial layout with bounded local automation;
- linting that reads the finished figure and never feeds back into it.

The repository is public but does not yet declare an open-source license.
