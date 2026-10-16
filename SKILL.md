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
  `page="nature-2"` (or `"nature-1"`, `"nature-page"`, `"science-2"`, `"cell-2"`, `"pnas-2"`, `"a4"`,
  `"letter"`, ...) names the page instead, and `height=` fixes its depth.
- A box round shapes in different groups, which moves none of them: a frame, in a file
  `{id, kind: frame, label, properties: {around: "a, b", layer: behind|front|over,
  title_side: left|right|bottom-left|bottom-right}}` (the corner its label stands at:
  the top left by default). A line may end at it, from a shape outside it:
  `{from: block, to: stage, arrive: south}` meets the middle of that side of its outline.
- A data plot in a figure: `panel.plot(id, "plots.py", "function", width=, height=)`; in a
  file `{kind: plot, properties: {source: plots.py, function: f}}`. The function returns
  a matplotlib figure; flexo sets the font, sizes and colours and lays it out at that size.
  It is drawn again when a file it reads changes; `data=["loss.h5", "runs/*.parquet"]`
  (`properties.data`) names data read by a library that opens files itself (HDF5, Parquet).
- Arrows, rings, braces, highlights, dimensions and labels drawn over a figure (no Inkscape):
  its `shapes:`, each a slide's shape (`flexo.freeform`), taking no room. Attach them to the
  parts they mark, so they follow the layout: `to: {part: encoder, side: top}` glues a
  line's end, `on: encoder` puts a shape's places from that part's top left, `around:
  [encoder, decoder]` (with `margin`) draws a ring, a highlight, a box or a brace round them.
  `figure.shape("ring", around=["encoder"])` in Python. `behind: true` draws one under the
  parts; `hide`/`dim`/`highlight` name one by its `id`.
- One figure shown several ways with nothing moved (a talk's build-up):
  `Figure(..., hide=[ids], dim=[ids], highlight=[ids])`, in a file `figure: {hide: [...]}`.
- A shape's words set apart: `properties={"bold": True}`, `"italic"`, `"size": "6pt"`,
  `"align": "left"`; a picture cropped: `properties={"crop_left": 10, ...}` (hundredths).
- An SVG picture's words are in the figure's font; `properties={"font": "drawn"}` keeps its
  file's faces, `"texts": [{"id": "text1", "words": "...", "size": 12, "bold": True}]` and
  `"colours": {"#4a90d9": "#2e7d32"}` restyle it -- its file is never changed.
- An outline dashed or dotted (what is optional, or not yet there): `line="dashed"` or
  `"dotted"` on a shape, a group or a frame, as on an arrow (`line:` in a file).
- A figure of several panels: `figure.panel(id)` for each (a group with no frame, lettered
  a, b, c in order; `figure.panel(id, "Title")` sets a title after the letter), on a figure
  with `layout="row"` or `layout=flexo.LayoutSpec("grid", columns=2)`.
  `Figure(panel_labels="A")` letters them A, B, C.
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
(`shaded=True` for observed), `decision`, `terminal`, `io` (flowchart input/output),
`database`, `server`, `cloud`, `queue`, `document`, `person` (software diagrams; lines
meet their drawn outlines), `loss`, `prediction`,
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
  pitch=, cartoon=, sticks=, surface=, site=, frame=, title_side=)`: a molecule drawn by
  hand by mol-sketch (the `molecules` extra); a chain can take the tone of its domain.
  `colors` keys are chains, residues (`SER195`, a ligand `6V0401`) or selections
  (`"resi 10-24"`), a later one over an earlier one; `ss_from="end.pdb"` colours
  it by another file's secondary structure. Structures naming one `frame` (a diffusion
  trajectory, a motif held fixed) are drawn with one camera, at one scale, about one
  centre, turned and framed as the first of them is; `title_side="bottom"` sets the
  name under the molecule.
  `look="flat"`: PyMOL's flat, outlined style in the theme's fills, as vector shapes
  that `flexo retheme` recolours. `noise=0.3` draws it as a diffusion model does on its
  way (0 the file, 1 a random coil; t = 30 of 100), `fixed="resi 34+94 or resn LIG"`
  holds a motif, `seed=` picks the run: copies alike but for `noise` are one trajectory.

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
(double-click), gathered into rows, columns, grids and modules (⌘G), and set in an
inspector; every edit is written to the YAML file, comments and order kept.
People and agents edit the same files live.

**Working as an agent in a studio**: `claude mcp add flexo-studio -- flexo studio
mcp` (once, in the folder) gives you `list_documents`, `open_document`,
`read_document`, `edit_document` (replace text that occurs once, like an edit
tool), `write_document`, `look` (the pages as pictures, with lint), and
`status` (tell the people what you are doing, in a few words). The loop is the
same as above: read, edit the YAML, `look`, fix, `look` again. Write figures as
YAML there (`flexo.dump_figure(spec)` shows how any Python figure reads as YAML).

A folder's Python (a deck's plots, a figure's) runs only once its person trusts the
folder; the studio reads and writes only inside the folder.

## Reference

`docs/tutorial.md` (step by step, every picture made from its code),
`docs/guide.md` (every component and option), `docs/routing.md` (how lines are
routed), `README.md` (biology components, the studio), `examples/literature.py`
(79 figures from papers to copy from), `examples/genetics.py`,
`examples/biology.py` and `examples/lab_figures.py` (biology to copy from),
`examples/cells.py` and `examples/jensen.py` (grids).
