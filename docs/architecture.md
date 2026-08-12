# Architecture

Flexo is a deterministic compiler. Each pass consumes an immutable value and
returns a different immutable phase type:

```text
SemanticFigure -> MeasuredFigure -> FittedFigure -> RoutedFigure -> SVGDocument
```

The semantic phase owns meaning, references, layout declarations, and author
hints. Measurement adds shaped text and intrinsic sizes. Fitting assigns
rectangles and resolves ports. Routing computes logical centerlines and visible
marker-aware shafts. Only emission knows about SVG.

## Boundaries

- Internal geometry is floating-point PostScript points.
- External lengths accept `pt`, `mm`, `cm`, `in`, and CSS `px`.
- IDs are explicit, stable, and referenced as strings.
- Layout styles affect geometry and require recompilation.
- Palettes affect paint only and may be patched without relayout.
- SVG emission is deterministic and uses a canonical numeric formatter.

## Initial dependency policy

The runtime uses only four focused dependencies: fontTools and HarfBuzz for
typography, jsonschema for the interchange contract, and PyYAML for YAML input.
The compiler itself uses frozen dataclasses and standard-library XML APIs.
