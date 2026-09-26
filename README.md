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

![The Transformer (examples/transformer.py)](examples/build/transformer.preview.png)

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
stays inspectable. The editable SVG and the PNG preview need nothing else; the
portable SVG and the PDF are made by Inkscape. (With Inkscape installed, the
PNG is made by Inkscape too; without it, by resvg.) In a Jupyter notebook, a
figure displays itself: end a cell with `figure`.

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

[`examples/literature.py`](examples/literature.py) draws sixty-eight figures from
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
| Shapes | `circle`, `decision`, `terminal`, `volume`, `op` (and `add`, `multiply`) |
| Words and art | `text`, `vector`, `image`, `graph`, `inset`, `legend` |

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
m.text("out", r"$\hat{x}$")            # \hat, \bar, \tilde, \dot, \vec
m.block("w", label=r"$W_{\text{out}}$")  # \text{} and \mathrm{} are upright
```

Latin letters in math are italic and digits are upright, as in TeX. `-` is a
minus sign. `\alpha` to `\omega`, `\Gamma` to `\Omega`, and common operators
and relations (`\times`, `\cdot`, `\sim`, `\in`, `\nabla`, `\to`, `\le`,
`\sum`, ...) become their symbols; `\log`, `\exp`, `\max` and the other named
functions are upright; `\mathcal{L}`, `\mathbb{E}` and `\mathfrak{g}` give
script, blackboard, and fraktur capitals. A superscript and a subscript on one
letter (`$\sigma^2_B$`) are stacked, as in TeX. `\sqrt{d}` is `√d`, and
`\frac{a}{b}` is set inline as `a/b`.

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
a captioned edge. A caption that still finds no clear place above or below its
container's contents asks for that much room on that side, and the figure is
laid out again. Lint warns about any caption that overlaps a component, another
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

### Flowcharts

```python
start = m.terminal("start", label="Start")          # a pill: start or end
step = m.block("step", label="Update weights", input=start)
done = m.decision("done", label="Converged?", input=step)  # a diamond
m.connect(done, start, label="no")
```

A line meets a circle or a diamond only at the middle of a side of its box,
which for a diamond is a corner. Each line gets a corner of its own while
corners last. A line in line with the diamond chooses first, then the line to
the nearest neighbour, so the flow keeps its corners: the "no" of a loop leaves
by a side corner, not by the top corner its input came in by, and a loop back
from far down the chart comes in by a corner the flow does not use.

### Line styles and arrowheads

```python
m.connect(x, z, line="dashed")                  # or "dotted"
m.connect(top, bottom, arrow="none", label="shared weights")  # undirected
m.connect(a, b, arrow="both")
```

`line=` changes only the stroke. `arrow=` says where the arrowheads go:
`"end"` (the default, at the target), `"none"` for an undirected link, which
then meets both components, or `"both"`. Nets take `line=` too.

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

## Themes, palettes, and fonts

A **theme** is one name for a whole look -- typeface, line weights, corners,
arrowheads, how a module draws its boundary, and the rules that turn colours
into paint. A **palette** is the colours. They compose: every theme takes every
palette.

```python
flexo.Figure("f", theme="paper")                               # the default
flexo.Figure("f", theme="tikz")                                # a LaTeX/TikZ figure
flexo.Figure("f", theme="dark", palette="Cobalt Citrus")       # slides on navy
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
| `rams`, `economist` | Quiet greys and one signal colour; a news graphic with red section bands |
| `classic` | Flexo's original look, kept exactly |

The themes follow the modes of [labviz](https://github.com/jamaliki/labviz), and
the palettes are design-corner's, the same ones labviz plots with, so a diagram
and the plots beside it read as one figure. `flexo themes` lists them all;
`flexo build figure.yaml --theme tikz --palette "Deep Sea Harvest"` overrides a
figure's own choice from the command line.

**Fonts** resolve by family name, and whatever Flexo measures with is what the
SVG, the PDF and the PNG are drawn in. IBM Plex Sans, Figtree, Liberation Sans
(metric-compatible with Arial and Helvetica), Latin Modern Roman and Latin
Modern Math ship with Flexo and work everywhere; any installed family works by
name, and `flexo.register_font("path/to/Face.ttf")` (or `FLEXO_FONT_PATH`) adds
a file. Characters a family lacks -- Greek in Figtree, say -- fall back to the
next family that has them, measured in the face that will draw them. Bundled
faces are embedded in the SVG, cut down to the characters the figure uses, so
an editable SVG is tens of kilobytes rather than a megabyte and a half, and
export hands Inkscape the same files, so the PDF never falls back to a
substitute face.

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

`m.legend()` keys the colours: a swatch and a name for every tone the
components created so far are painted in. Pass `entries={"encoder": "Encoder
blocks", ...}` to choose the tones and their words, and `layout="column"` to
stack the entries.

## Conventions: branches, merges, arrivals, and lines

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
(the default) and straight ones.

Change a convention for a whole figure with `conventions=`, or in YAML with a
`conventions:` mapping on the figure:

```python
flexo.Figure("f", conventions={"branch": "dot"})     # a dot on every fork
flexo.Figure("f", conventions={"merge": "plain"})    # no arrowheads at joins
flexo.Figure("f", conventions={"arrivals": "joined"})  # join before the port
flexo.Figure("f", conventions={"lines": "straight"})     # diagonals, not routes
```

| Convention | Values (default first) |
| --- | --- |
| `branch` | `"plain"`, `"dot"` |
| `merge` | `"auto"`, `"arrow"`, `"plain"`, `"dot"` |
| `arrivals` | `"separate"`, `"joined"` |
| `lines` | `"orthogonal"`, `"straight"` |

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
```

The builder lowers to the same validated, versioned schema that YAML and JSON
parse into, so a figure is one thing written two ways -- see
[`examples/vertical_slice.py`](examples/vertical_slice.py) and its
[YAML equivalent](examples/vertical_slice.yaml). A figure's `style` (its theme),
`palette` and `font` are fields of that document too.

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

The repository is public but does not yet declare an open-source license.
