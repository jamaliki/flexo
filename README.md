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

Attention then reads as a formula, not as a matrix: the merge above carries its
caption in styled runs (`TextRun("T", baseline_shift="super")`) and Flexo anchors
it above the horizontal run the arrow draws, with the second source rising into
that run just before the sink.

### Module interiors as grids

A module whose chains should line up is a `grid`: rows are the chains, columns
line them up, and `align="start"` puts each cell's content at the top of its row.
Give the boxes the height of a vector's cell stack and every run along a row is
straight by construction, with no port adaptation left to absorb. Empty cells and
reserved corridors are authored with zero-height `spacer` nodes, because grid gaps
are uniform: one lane column widens the boundary an edge label needs, another
lengthens the attention arrow until its formula fits above it.

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
  corridor in one direction only. Group padding would reserve it on all four
  sides and leave a dead strip at the canvas edge.

`flexo.gallery.modelangelo_gnn` is authored this way; its canvas ends at the
content plus the ordinary margin on every side.

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
