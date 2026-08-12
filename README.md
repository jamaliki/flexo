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
