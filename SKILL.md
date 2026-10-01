---
name: flexo
description: Make publication-quality, editable scientific figures in Python or YAML with flexo -- neural-network architectures, pipelines, flowcharts, graphical models, and biology (genetic constructs, plasmid maps, protein domain maps, phylogenetic trees, well plates, protocol timelines, pathways with SBGN arrows, molecular structures drawn by hand), and grids of cells (plate maps, heatmaps, generated artwork). Use when asked to draw or reproduce a model diagram, block diagram, flowchart, state machine, Bayesian network, pathway, construct, or any boxes-and-arrows figure for a paper, poster, or slide, or to work on figures in flexo studio.
---

# Making figures with flexo

flexo compiles a description of *what* a figure shows -- components and the values
that flow between them -- into an SVG made of ordinary editable objects. You never
give coordinates, sizes, colours, ports, or routes: it measures every word, lays
the figure out, routes every arrow, places every caption, and checks the result.

## Setup

```bash
uv sync --all-groups --all-extras    # in the flexo checkout: Python 3.12 to 3.14
```

Extras: `structures` (gemmi: read PDB/mmCIF), `molecules` (mol-sketch, for
`structure()`; it needs skia-python, which has wheels up to Python 3.14 only),
`assistant` (the Anthropic SDK, for Claude in the studio). Everything else is pure
Python plus wheels: no Inkscape, no Cairo, no LaTeX.

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
- Components go on the figure (`figure.block(...)`, the same as `figure.root.block(...)`)
  or a group; each returns a handle. `input=h`
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
`graph`, `image(id, "art.svg" or "photo.png")`, `inset`, `legend(entries=, badges=)`. Nets:
`figure.net(src=a, sinks=[b, c])` (one value to many), `figure.merge(sinks=[a, b], dst=c)`,
`figure.residual(a, b)`. Any component: `tone="name"` (same tone = same colour),
`badge="frozen"|"trained"|"tuned"` (snowflake/flame/bolt), `paint={"fill": "#..."}`,
`width=`, `height=`.

### Biology

Each is one component: it sizes itself, colours its parts by name (a tone per
gene, per domain, per condition), and has ports where arrows belong.

- `construct(id, parts=[{"type": "promoter", "label": "pTet"}, {"type": "cds",
  "label": "GFP", "id": "gfp"}, {"type": "terminator"}])`: SBOL Visual glyphs on
  a backbone (`promoter`, `rbs`, `cds`/`gene`, `terminator`, `operator`, `origin`,
  `insulator`, `primer`, `site`, `region`, `spacer`); `"strand": "-"` points left;
  a part with an `id` is a port (`handle.port("gfp")`), so a gene can point at
  what it makes.
- `plasmid(id, length=5400, features=[{"type": "cds", "label": "AmpR",
  "start": 100, "end": 960}, {"type": "site", "label": "EcoRI", "start": 396}])`:
  a circular map, features as arcs by base pair, labels outside on leaders.
- `protein(id, length, features=[{"type": "domain", "label": "SH3", "start": 60,
  "end": 120}, {"type": "mutation", "label": "T315I", "at": 315}])`: a domain map
  to scale (`region`, `motif`, `transmembrane`, `signal`, sites as lollipops,
  `disulfide` brackets), with `secondary=` / `sequence=` tracks.
  `flexo.from_uniprot("P00519", sites=True)` or `flexo.from_structure("1abc.cif")`
  returns `protein()`'s arguments: `figure.protein("abl", **flexo.from_uniprot(...))`.
- `tree(id, "((A:0.1,B:0.2):0.3,C:0.4);", layout="rectangular"|"circular",
  clades=[{"tips": "A, B", "label": "Clade 1"}], italic=True, support=True)`.
- `wellplate(id, groups=[{"wells": "A1-C6", "label": "Drug"}], wells=96)`.
- `timeline(id, events=[{"at": 0, "label": "Seed"}], spans=[{"start": 1, "end":
  3, "label": "Treatment"}], unit="day")`.
- `structure(id, "1ubq" or "model.cif", look=, colors={"A": "kinase"}, yaw=,
  pitch=, cartoon=, sticks=, surface=, site=)`: a molecule drawn by hand by
  mol-sketch (the `molecules` extra); a chain can take the tone of its domain.

**Grids**: `cells(id, grid, key, ...)` draws a grid written as text, one row per
line and one symbol per word (`.` empty), or rows of values -- a plate map, a
heatmap, a board. `key={"C": {"label": "Control"}, "K": "#262422", "Y": {"color":
"#f1bf24", "mark": "з"}}`: a colour is a tone name or an exact `#hex`; a symbol
not in the key takes a tone by its name. Numbers are shaded on
`ramp=("#lo", "#hi")` (`values=True` writes them). `cell=`, `gap=`, `corner=`,
`lines="muted"`, `row_labels`/`column_labels="numbers"|"letters"|[names]`,
`row_side`, `column_side`. `examples/jensen.py` is a generated artwork with it.

**Pathways and reactions**: `connect(a, b, head="inhibition")` (⊣), `"catalysis"`,
`"stimulation"`, `"necessary"`, `"modulation"` (SBGN heads);
`arrow="reversible"` draws ⇌ with `label=` over and `back_label=` under;
`cofactors=("ATP", "ADP")` curls what a step takes in and gives off onto its line
(opposite , so not with ).

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
- **Let the layout straighten lines.** A row feeding a block below it slides
  sideways, within its parent, when that lets more of its arrows run straight
  (kept only if the routed figure bends less); a plain box (block, MLP, CNN,
  terminal) that several straight arrows share a side of widens until they meet
  its middle (`pin_spread`), so each arrow leaves its own box's centre. You get
  this by grouping and ordering, not by sizing boxes.
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
- `sketch=True` (or `{"roughness": 0.3, "fill": "hatch"}`) draws any theme by hand;
  fills are `wash` (watercolour), `hatch`, `solid`, `gouache` (opaque, brushed), `none`.
- `conventions={"branch": "dot", "merge": "plain", "arrivals": "joined",
  "lines": "straight", "pin_spread": 0.8}` sets how lines meet. `pin_spread`
  is the middle share of a side that arrows sharing it are spread over (two at
  30% and 70%, three at 23/50/77%); an arrow alone on its side meets the middle.
- A look of your own is a YAML theme file: `flexo theme paper -o lab.yaml`,
  edit, then `Figure(theme="lab.yaml")` (or `FLEXO_THEME_PATH`). Palettes:
  `flexo.register_palette("Lab", [...])` or a `palettes:` file.

## Another shape: slides and posters

`flexo.fit_in_box(figure, width, height, words=13)` lays a figure out for a box
(as written, turned so a tall stack reads left to right, or spaced closer --
whichever sets its words largest); `flexo.turned(spec)` gives the turned figure
itself. Write the figure once, as the paper needs it. For a whole talk, use
flexo-talk (a sibling package with its own `SKILL.md`): its decks place flexo
figures this way and export to editable PowerPoint and PDF.

## Outputs and files

`flexo.build(figure, dir, formats=("editable", "portable", "pdf", "png"))`:
all pure Python: the editable SVG (live text, named layers), portable SVG (words
as outlines), PDF (selectable text, embedded fonts), and PNG. YAML figures (`flexo.load_figure`, `flexo build fig.yaml`)
may be short: nodes default to blocks, `from: a` / `to: b` name ports for you,
no `groups` stacks nodes. `flexo.dump_figure(figure.spec)` writes any figure as YAML.

## The studio: figures without code, with people and agents

`flexo studio` (in a folder, or on a file: `flexo studio fig.yaml`) opens a local
editor in the browser for every figure, theme, and (with flexo-talk) deck in the
folder. Parts are added from a palette (A), connected (C), typed on in place
(double-click), gathered into rows, columns, grids and modules (G), and set in an
inspector; every edit is written to the YAML file, comments and order kept.
People and agents edit the same files live.

**Working as an agent in a studio**: `claude mcp add flexo-studio -- flexo studio
mcp` (once, in the folder) gives you `list_documents`, `open_document`,
`read_document`, `edit_document` (replace text that occurs once, like an edit
tool), `write_document`, `look` (the pages as pictures, with lint), and
`status` (tell the people what you are doing, in a few words). The loop is the
same as above: read, edit the YAML, `look`, fix, `look` again. Write figures as
YAML there (`flexo.dump_figure(spec)` shows how any Python figure reads as YAML).

A folder's Python (a deck's plots) runs only once its person trusts the folder;
the studio reads and writes only inside the folder.

## Reference

`docs/tutorial.md` (step by step, every picture made from its code),
`docs/guide.md` (every component and option), `docs/routing.md` (how lines are
routed), `README.md` (biology components, the studio), `examples/literature.py`
(79 figures from papers to copy from), `examples/genetics.py`,
`examples/biology.py` and `examples/lab_figures.py` (biology to copy from),
`examples/cells.py` and `examples/jensen.py` (grids).
