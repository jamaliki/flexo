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
        q, v = module.mlp("projection", inputs=[features], outputs=["Q", "V"])
        k = module.cnn("keys", input=features.branch, output="K")
        attended = module.attention("attention", q=q, k=k, v=v)
        prediction = module.prediction("prediction", input=attended)
        module.residual(features, prediction, lane="encoder-bottom")

figure.compile().document.write("attention-flow.editable.svg")
```

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
- native SVG primitives, live text, and named Inkscape layers;
- explicit editorial layout with bounded local automation.

The repository is public but does not yet declare an open-source license.
