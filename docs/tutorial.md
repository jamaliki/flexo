# Tutorial: figures step by step

This tutorial builds figures from the first box to a finished, themed, hand-drawn
panel. Each step is a complete program: copy it, run it, and you get the picture
beside it. (The pictures are made from these very blocks by
[`examples/tutorial.py`](../examples/tutorial.py), and the test suite checks that
every one compiles with no lint diagnostics.)

- [1. A first figure](#1-a-first-figure)
- [2. Let the wiring lay it out](#2-let-the-wiring-lay-it-out)
- [3. Kinds of component](#3-kinds-of-component)
- [4. Modules](#4-modules)
- [5. Words on lines, and math](#5-words-on-lines-and-math)
- [6. Loops, and a nudge](#6-loops-and-a-nudge)
- [7. Graphs: circles, straight lines, plates](#7-graphs-circles-straight-lines-plates)
- [8. The look: themes, palettes, fonts](#8-the-look-themes-palettes-fonts)
- [9. Drawing by hand](#9-drawing-by-hand)
- [10. Your own colours](#10-your-own-colours)
- [11. Conventions](#11-conventions)
- [12. The same figure as a file](#12-the-same-figure-as-a-file)
- [13. Building, checking, and editing](#13-building-checking-and-editing)
- [Where each choice lives](#where-each-choice-lives)

## 1. A first figure

A figure is a `flexo.Figure` used as a `with` block. Components go on
`figure.root`, which stacks them top to bottom, and `input=` says where a
component's value comes from: that is the arrow.

```python
# step: first-figure
import flexo

with flexo.Figure("classifier", width="single-column") as figure:
    tokens = figure.root.text("tokens", "Tokens")
    embed = figure.root.block("embed", label="Embedding", input=tokens)
    encoder = figure.root.block("encoder", label="Encoder", input=embed)
    figure.root.block("head", label="Classifier", input=encoder)
```

![A first figure](../examples/build/tutorial/first-figure.preview.png)

There are no coordinates, sizes, colours, or ports: Flexo measures every word,
sizes each box to fit, stacks them, and routes the arrows. Write it to disk
with `flexo.build`:

```python
flexo.build(figure, "build", formats=("editable", "pdf", "png"))
```

`width` is `"single-column"`, `"double-column"` (the default), `"presentation"`,
or any length (`"120mm"`, `"5in"`). In a notebook, end a cell with `figure` to
see it.

## 2. Let the wiring lay it out

A figure need not say where anything goes. With `layout="flow"`, components can
be written in any order and are placed by how they are wired: each goes one
layer after what feeds it, branches run side by side, and a merge sits under
its branches.

```python
# step: flow
import flexo

with flexo.Figure("two-views", width="single-column", layout="flow") as figure:
    image = figure.root.text("image", "Image $x$")
    first = figure.root.block("first", label="Crop, recolour", input=image)
    second = figure.root.block("second", label="Blur, flip", input=image)
    one = figure.root.block("f1", label="Encoder $f$", input=first, tone="encoder")
    two = figure.root.block("f2", label="Encoder $f$", input=second, tone="encoder")
    figure.root.block("loss", label="Contrastive loss", inputs=[one, two])
```

![Laid out from its wiring](../examples/build/tutorial/flow.preview.png)

`inputs=[...]` takes several values. `tone="encoder"` is a name for a *kind*
of box: every box with the same tone gets the same colour, and each new tone
gets the next colour of the palette. `layout="flow-right"` runs the same
layers left to right.

## 3. Kinds of component

Beyond `block` and `text`, Flexo knows the parts papers draw: `attention`,
`mlp`, `add_norm`, `add` and `multiply` (circles with the sign in them),
`circle`, `decision`, `terminal`, `loss`, `concat`, `tensor`, `vector`, and
more (see the [guide](guide.md)). Each kind is coloured as a kind.

```python
# step: kinds
import flexo

with flexo.Figure("layer", width="single-column") as figure:
    with figure.module("layer", label="Transformer layer", layout="column", reverse=True) as m:
        x = m.text("x", "$x$")
        attention = m.attention("attention", label="Self-attention", q=x, k=x, v=x)
        first = m.add_norm("norm1", label="Add & Norm", input=attention, skip=x)
        ffn = m.mlp("ffn", label="Feed forward", input=first)
        m.add_norm("norm2", label="Add & Norm", input=ffn, skip=first)
```

![Kinds of component](../examples/build/tutorial/kinds.preview.png)

`reverse=True` stacks the column bottom to top, so the code reads in the order
the values flow and the picture reads upward, as Transformer figures do.
`add_norm(input=..., skip=...)` names both of its wires: the residual comes in
from the side.

## 4. Modules

`figure.module(...)` opens a titled box; `row`, `column`, and `grid` arrange
without drawing anything. They nest, and an arrow may leave one module for
another: `figure.connect(source, target)` draws any arrow `input=` cannot.

```python
# step: modules
import flexo

with flexo.Figure("seq2seq") as figure:
    with figure.root.row("model", gap="30pt") as model:
        with model.module("encoder", label="Encoder", layout="column", reverse=True) as enc:
            source = enc.text("source", "Source words")
            state = enc.block("rnn", label="RNN", input=source, tone="encoder")
        with model.module("decoder", label="Decoder", layout="column", reverse=True) as dec:
            target = dec.text("target", "Target words")
            out = dec.block("rnn", label="RNN", input=target, tone="decoder")
            dec.text("words", "Next word", input=out)
    figure.connect(state, out, label="context")
```

![Modules](../examples/build/tutorial/modules.preview.png)

Ids are scoped by the group they are written in, so both modules can have an
`"rnn"`. `gap` spaces the children of a group; `padding`, `align`, and
`justify` do what they say (see [grids, spacing, and
alignment](guide.md#grids-spacing-and-alignment)).

## 5. Words on lines, and math

`label=` on a connection is a caption. Anything between `$...$` is math in a
subset of TeX: sub- and superscripts, Greek, `\frac`, `\sqrt`, accents
(`\hat{x}`, `\vec{h}`), and TeX's spacing.

```python
# step: captions
import flexo

with flexo.Figure("scores") as figure:
    with figure.root.row("model", gap="44pt") as model:
        query = model.block("q", label=r"Query $\vec{q}_i$")
        weights = model.block("softmax", label=r"$\mathrm{softmax}(QK^T/\sqrt{d})$")
        total = model.block("sum", label="Weighted sum")
    figure.connect(query, weights, label="scores")
    figure.connect(weights, total, label=r"$\alpha_{ij}$")
```

![Captions and math](../examples/build/tutorial/captions.preview.png)

A caption goes where it reads as its own line's: above a horizontal run if
there is room, otherwise beside the line, never over a box or another line.
If nowhere is free, the figure is laid out again with more room.

## 6. Loops, and a nudge

An arrow back to an earlier step is just another connection; the router takes
it round the outside. `line="dashed"` or `"dotted"` changes the stroke, and
`via="west"` (or north, east, south) says which side a route should keep to
when the choice is yours to make.

```python
# step: loops
import flexo

with flexo.Figure("training", width="single-column") as figure:
    with figure.root.column("loop") as loop:
        batch = loop.block("batch", label="Mini-batch")
        model = loop.block("model", label="Model", input=batch, tone="model")
        loss = loop.loss("loss", label="Loss", input=model)
        step = loop.block("step", label="Optimizer step", input=loss)
    figure.connect(step, model, label="update", line="dashed", via="west")
```

![A loop](../examples/build/tutorial/loops.preview.png)

Hints are rarely needed, and a hint that cannot be honoured is reported, not
obeyed blindly (see [routing](routing.md)).

## 7. Graphs: circles, straight lines, plates

Graphical models and networks are circles joined by straight lines:
`conventions={"lines": "straight"}`. `shaded=True` marks an observed variable,
and `plate(id, count)` draws a plate round what repeats.

```python
# step: graphs
import flexo

with flexo.Figure("regression", width="single-column", conventions={"lines": "straight"}) as figure:
    with figure.root.row("model", gap="28pt") as model:
        weights = model.circle("w", "$w$")
        with model.plate("data", "$N$", layout="column") as data:
            x = data.circle("x", "$x_n$", shaded=True)
            y = data.circle("y", "$y_n$", shaded=True, input=x)
        noise = model.circle("noise", r"$\sigma^2$")
    figure.connect(weights, y)
    figure.connect(noise, y)
```

![A graphical model](../examples/build/tutorial/graphs.preview.png)

## 8. The look: themes, palettes, fonts

A **theme** is the whole look in one word; a **palette** is the colours; a
**font** is any family Flexo can find. They compose freely, and none of them
changes what the figure *says*. Here one function draws the same figure four
ways:

```python
# step: themes
import flexo


def pipeline(**look):
    with flexo.Figure("pipeline", width="single-column", **look) as figure:
        with figure.module("model", label="Model") as m:
            x = m.text("x", "$x$")
            h = m.block("encoder", label="Encoder", input=x, tone="encoder")
            m.block("head", label="Head", input=h, tone="head")
    return figure


figures = {
    "paper": pipeline(),
    "tikz": pipeline(theme="tikz"),
    "dark": pipeline(theme="dark", palette="Cobalt Citrus"),
    "sketch": pipeline(theme="sketch"),
}
```

| `paper` (the default) | `tikz` |
| --- | --- |
| ![paper](../examples/build/tutorial/themes-paper.preview.png) | ![tikz](../examples/build/tutorial/themes-tikz.preview.png) |
| **`dark`, palette "Cobalt Citrus"** | **`sketch`** |
| ![dark](../examples/build/tutorial/themes-dark.preview.png) | ![sketch](../examples/build/tutorial/themes-sketch.preview.png) |

`flexo themes` lists every theme, palette, and bundled font. `font="Helvetica"`
(or any installed family) sets the figure in that face at the theme's sizes.

## 9. Drawing by hand

`theme="sketch"` is drawn by hand: every line in two wandering strokes, washes
of watercolour, cream paper, Kalam lettering. Any theme can be drawn by hand
with `sketch=True`, and the hand is tuned with a few settings.

```python
# step: sketch
import flexo


def unet(**look):
    with flexo.Figure("unet", width="single-column", **look) as figure:
        with figure.module("net", label="U-Net", layout="grid", columns=2) as m:
            down = [m.block(f"d{c}", label=str(c), tone="down", at=(r, 0))
                    for r, c in enumerate((64, 128))]
            up = [m.block(f"u{c}", label=str(c), tone="up", at=(r, 1))
                  for r, c in enumerate((64, 128))]
        figure.connect(down[0], down[1])
        figure.connect(down[1], up[1])
        figure.connect(up[1], up[0])
        figure.connect(down[0], up[0], label="copy", role="residual")
    return figure


figures = {
    "wash": unet(theme="sketch"),
    "hatch": unet(theme="sketch", sketch={"fill": "hatch", "roughness": 0.35}),
    "paper": unet(sketch=True),
}
```

| `theme="sketch"` | `sketch={"fill": "hatch", "roughness": 0.35}` | `sketch=True` on `paper` |
| --- | --- | --- |
| ![wash](../examples/build/tutorial/sketch-wash.preview.png) | ![hatch](../examples/build/tutorial/sketch-hatch.preview.png) | ![paper](../examples/build/tutorial/sketch-paper.preview.png) |

The drawing happens after layout, so a sketched figure has exactly the clean
one's geometry, and its text stays live in the SVG. The settings are
`roughness` (0 ruled to 1 loose), `passes`, `fill` (`"wash"`, `"hatch"`,
`"solid"`, `"none"`), `paper`, and `seed`.

## 10. Your own colours

Three levels, from broadest to most local:

- `palette=["#2a6f97", "#e76f51", "#2a9d8f"]` gives the figure your colours;
  every theme derives its fills and outlines from them.
- `tone=` decides which boxes share a colour. A number (`tone=2`) picks the
  palette's second colour; `tone="neutral"` takes a kind's colour away.
- `paint={"fill": "#fde68a", "stroke": "#92400e"}` on one component paints it
  exactly, and nothing else.

```python
# step: colours
import flexo

with flexo.Figure("paint", width="single-column", palette=["#2a6f97", "#e76f51"]) as figure:
    with figure.root.row("row") as row:
        a = row.block("a", label="Encoder", tone="encoder")
        b = row.block("b", label="Decoder", tone="decoder", input=a)
        row.block("c", label="Frozen", input=b, paint={"fill": "#fde68a", "stroke": "#92400e"})
    figure.root.legend(entries={"encoder": "trained", "decoder": "fine-tuned"})
```

![Colours](../examples/build/tutorial/colours.preview.png)

`legend()` keys the colours; `flexo retheme figure.svg --palette "Tropical
Rose"` recolours a finished SVG without touching its geometry, because every
paint in it carries its role.

## 11. Conventions

Papers disagree on how lines meet. A figure picks with `conventions=`:
`branch` (a fork as a plain T or with a dot), `merge` (how joining lines end),
`arrivals` (arrows into one port kept apart or joined), `lines` (routed or
straight), and `pin_spread` (how much of a side arrows spread across).

```python
# step: conventions
import flexo


def fork(**conventions):
    with flexo.Figure("fork", width="single-column", conventions=conventions) as figure:
        with figure.root.column("c") as c:
            x = c.block("x", label="Shared trunk")
            with c.row("heads") as heads:
                a = heads.block("a", label="Head A", input=x)
                b = heads.block("b", label="Head B", input=x)
                d = heads.block("d", label="Head C", input=x)
        c.merge(sinks=[a, b, d], dst=c.block("sum", label="Sum"))
    return figure


figures = {
    "default": fork(),
    "dots": fork(branch="dot", merge="dot"),
}
```

| defaults | `{"branch": "dot", "merge": "dot"}` |
| --- | --- |
| ![default](../examples/build/tutorial/conventions-default.preview.png) | ![dots](../examples/build/tutorial/conventions-dots.preview.png) |

A theme can carry its own conventions, and a net's `joint="arrow"` or
`joint="dot"` overrides them for that one net.

## 12. The same figure as a file

Everything above can be written as YAML (or JSON) instead of Python, checked
against [`schemas/figure.schema.json`](../schemas/figure.schema.json). This is
the first figure again, drawn by hand:

```yaml
# step: yaml
figure:
  id: classifier
  width: single-column
  theme: sketch
nodes:
  - {id: tokens, kind: text, label: Tokens}
  - {id: embed, label: Embedding}
  - {id: encoder, label: Encoder}
  - {id: head, label: Classifier}
edges:
  - {from: tokens, to: embed}
  - {from: embed, to: encoder}
  - {from: encoder, to: head}
```

A file may leave out anything the Python did not ask for: a node is a `block`
unless it says otherwise, an edge end that names only a node means its usual
port (`output` leaving, `input` arriving), edges are numbered for you, and with
no `groups` the nodes are stacked in a column. Groups, nets, captions, tones,
`conventions:` and `sketch:` are all written the way the Python writes them.

![From YAML](../examples/build/tutorial/yaml.preview.png)

Build it from the command line with `uv run flexo build classifier.yaml`, or
load it with `flexo.load_figure("classifier.yaml")`. `flexo.dump_figure(figure.spec)`
writes any figure out as YAML, so the Python and the file are one thing.

## 13. Building, checking, and editing

`flexo.build` compiles, writes each format you ask for, and checks the result:

```python
result = flexo.build(figure, "build", formats=("editable", "pdf", "png"))
print(result.summary())      # "ok: no diagnostics", or what is wrong and where
```

- **editable SVG**: live text, one object per box and line, Inkscape layers,
  every element named after its id, fonts embedded. Open it and move things.
- **PDF** and **portable SVG** (text as outlines) are made by Inkscape.
- **PNG** previews are made by Inkscape if you have it, otherwise by resvg.

The check (`flexo.lint_compilation`) reports what a careful reader would: lines
that cross, lines closer than a lane, a caption over a line, a figure that grew
past its width, a hint that could not be kept. Errors are things to fix;
warnings say what the figure had to give up. Outputs are written either way, so
a flawed figure is still there to look at.

## Where each choice lives

| You want to change | Write |
| --- | --- |
| The whole look | `Figure(theme="tikz")` (or `paper`, `dark`, `sketch`, ...) |
| The colours | `Figure(palette="Deep Sea Harvest")` or `palette=["#..", ...]` |
| The typeface | `Figure(font="Helvetica")`, or `flexo.register_font(path)` for a file |
| Hand-drawn lines | `Figure(sketch=True)` or `sketch={"roughness": 0.3, "fill": "hatch"}` |
| How forks, joins and arrivals look | `Figure(conventions={"branch": "dot", ...})` |
| Straight lines for a graph | `Figure(conventions={"lines": "straight"})` |
| Which boxes match | `tone="name"` on each component |
| One box's paint | `paint={"fill": "#..", "stroke": "#..", "label": "#.."}` |
| The size of the figure | `Figure(width="single-column")`, `width="120mm"` |
| Space between things | `gap=`, `row_gap=`, `column_gap=`, `padding=` on a group |
| Where things go | `row`, `column`, `grid(columns=...)` with `at=(row, column)`, `layout="flow"` |
| Which way a route goes | `via="west"` on `connect`, `net`, or `merge` |
| Order read upward or leftward | `reverse=True` on a row or column |
| A box's size | `width=`, `height=` on the component |
