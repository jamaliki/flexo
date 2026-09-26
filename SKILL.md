---
name: flexo
description: Make publication-quality, editable scientific and neural-network figures (architectures, pipelines, flowcharts, graphical models) in Python or YAML with flexo. Use when asked to draw or reproduce a model diagram, block diagram, flowchart, state machine, Bayesian network, or any boxes-and-arrows figure for a paper, poster, or slide.
---

# Making figures with flexo

flexo compiles a description of *what* a figure shows -- components and the values
that flow between them -- into an SVG made of ordinary editable objects. You never
give coordinates, sizes, colours, ports, or routes: it measures every word, lays
the figure out, routes every arrow, places every caption, and checks the result.

## The loop

1. Write the figure (below). Start plain: components, `input=`, one theme.
2. `result = flexo.build(figure, "build", formats=("editable", "png"))`, then
   `print(result.summary())` -- it lists any lint diagnostics.
3. Look at the PNG. Fix what the report or your eye finds, by changing *what the
   figure says* (grouping, order, wiring) before reaching for hints.
4. Done when the summary says `ok: no diagnostics` and the picture reads.

## Writing a figure

```python
import flexo

with flexo.Figure("block", width="single-column", theme="paper") as figure:
    with figure.module("layer", label="Transformer layer", layout="column", reverse=True) as m:
        x = m.text("x", "$x$")
        attn = m.attention("attn", label="Self-attention", input=x)      # q, k, v all from x
        norm = m.add_norm("norm1", label="Add & Norm", input=attn, skip=x)
        ffn = m.mlp("ffn", label="Feed forward", input=norm)
        m.add_norm("norm2", label="Add & Norm", input=ffn, skip=norm)
```

- `Figure(id, width=, theme=, palette=, font=, conventions=, sketch=, background=, layout=)`;
  `width` is `"single-column"`, `"double-column"` (default), `"presentation"`, or a length.
- Components go on `figure.root` or a group; each returns a handle. `input=h`
  (one) / `inputs=[a, b]` (several) draw the arrows in; `figure.connect(a, b)`
  draws any other arrow (`label=`, `line="dashed"|"dotted"`, `via="west"`,
  `arrow="none"|"both"`, `role="residual"`).
- Groups: `row`, `column`, `grid(columns=N)` with `at=(r, c)`, `module(id, label=)`
  (a titled box, nests anywhere), `plate(id, "$N$")` (graphical-model plate),
  `group(..., layout="flow")` / `Figure(layout="flow")` (placed from the wiring:
  write components in any order). `reverse=True` reads a column upward.
- Ids are scoped by their group (`"layer.ffn"`); reuse short names freely.

### Components

`block` (a box), `text` (words with ports), `attention` (grows Q/K/V glyphs with
`vectors=True`), `mlp`, `cnn`, `add_norm(input=, skip=)`, `add`/`multiply`/`op(id, "Σ")`
(operator circles; label with the symbol, caption the edge out), `circle`
(`shaded=True` for observed), `decision`, `terminal`, `loss`, `prediction`,
`concat`, `tensor`, `matrix`, `sequence`, `vector`, `volume`, `feature_strip`,
`graph`, `image(id, "art.svg")`, `inset`, `legend(entries=, badges=)`. Nets:
`figure.net(src=a, sinks=[b, c])` (one value to many), `figure.merge(sinks=[a, b], dst=c)`,
`figure.residual(a, b)`. Any component: `tone="name"` (same tone = same colour),
`badge="frozen"|"trained"|"tuned"` (snowflake/flame/bolt), `paint={"fill": "#..."}`,
`width=`, `height=`.

### Words

Labels and captions are text with math between `$...$`: sub/superscripts,
Greek (`\alpha`), `\mathcal{L}`, `\mathbb{E}`, `\hat{x}`, `\vec{h}`,
`\overleftarrow{h}`, `\frac{a}{b}` (inline), `\sqrt{d}`, TeX spacing. `"\n"`
breaks a line; long labels wrap on their own.

## Beautiful by default: habits that pay

- **Say the structure, not the picture.** Group what belongs together in a
  `module`; put things in the order values flow; let `layout="flow"` place
  branchy graphs. Layout follows grouping and wiring.
- **One tone per kind.** Give every box of a kind the same `tone=`; leave
  plain boxes neutral. Two to four tones read best. `legend()` keys them.
- **Graphs use straight lines:** `conventions={"lines": "straight"}` with
  `circle`s and `plate`s for Bayesian networks, HMMs, GNNs, Markov chains.
- **Captions on edges** (`label=`) for what a line carries; keep them short.
- **Hints last.** `via=` picks a side for a route; `lane=`/waypoints pin one.
  A hint that cannot be kept is reported, not silently obeyed.
- Read the report: `routing.connector.crossing` (lines cross; reorder or regroup),
  `routing.track.separation` (lines too close), `routing.caption.*` (a caption
  collides), `layout.width.grown` (content needs more width: widen or regroup).

## The look

- `theme=`: `paper` (default), `tikz` (LaTeX look), `slides`, `dark`, `archive`,
  `print`, `swiss`, `bauhaus`, `midcentury`, `rams`, `economist`, `sketch`
  (hand-drawn), `classic`. `flexo themes` lists them with palettes and fonts.
- `palette=` a name (`"Deep Sea Harvest"`) or a list of hex colours; `font=`
  any installed family. SVGs are transparent; `background=True` paints the page.
- `sketch=True` (or `{"roughness": 0.3, "fill": "hatch"}`) draws any theme by hand.
- `conventions={"branch": "dot", "merge": "plain", "arrivals": "joined",
  "lines": "straight", "pin_spread": 0.8}` sets how lines meet.
- A look of your own is a YAML theme file: `flexo theme paper -o lab.yaml`,
  edit, then `Figure(theme="lab.yaml")` (or `FLEXO_THEME_PATH`). Palettes:
  `flexo.register_palette("Lab", [...])` or a `palettes:` file.

## Outputs and files

`flexo.build(figure, dir, formats=("editable", "portable", "pdf", "png"))`:
the editable SVG (live text, named layers) and PNG need nothing else; portable
SVG and PDF use Inkscape. YAML figures (`flexo.load_figure`, `flexo build fig.yaml`)
may be short: nodes default to blocks, `from: a` / `to: b` name ports for you,
no `groups` stacks nodes. `flexo.dump_figure(figure.spec)` writes any figure as YAML.

## Reference

`docs/tutorial.md` (step by step, every picture made from its code),
`docs/guide.md` (every component and option), `docs/routing.md` (how lines are
routed), `examples/literature.py` (79 figures from papers to copy from).
