# Architecture

Flexo is a deterministic compiler. Each pass consumes an immutable value and
returns a different immutable phase type:

```text
FigureSpec -> MeasuredFigure -> FittedFigure -> RoutedFigure -> SVGDocument
```

The semantic phase owns meaning, references, layout declarations, and author
hints. Measurement adds shaped text and intrinsic sizes. Fitting assigns
rectangles and resolves ports. Routing computes logical centerlines and visible
marker-aware shafts. Only emission knows about SVG.

`compile_figure` joins the four passes; `build` wraps it in the export and lint
that every figure script wants after them.

## Modules by phase

| Phase | Modules |
| --- | --- |
| authoring | `builder` lowers ergonomic Python into `ir.semantic`; `validate` normalizes and checks it; `serialization` and `schema` carry the same figure as YAML/JSON |
| measure | `layout.measure` walks bottom-up for intrinsic sizes; `components` owns per-kind port tables, motif bands, and intrinsic geometry; `text` shapes and measures runs; `artwork` loads, sanitizes, and sizes an `image` node's file |
| fit | `layout.fit` places children into containers; `layout.arrange` computes where a group's children sit and how much room they need; `layout.grid` assigns grid cells (shared by measure and fit, so both agree); `layout.gaps` spaces linear groups; `layout.order` reorders small columns to cut crossings; `layout.ports` places adaptive ports once bounds are known; `layout.sides` picks the side a defaulted port faces |
| route | `routing.solve` resolves ports and hints into obstacle-free orthogonal routes; `routing.visibility` builds the visibility graph and searches it; `routing.nets` routes fan-out buses and merge rails; `routing.nudge` trims shafts, collapses zigzags, and separates parallel tracks |
| emit | `emit` writes the document and its layers; `render`, `render_common`, and `render_scientific` draw component bodies and motifs; `svg` and `svg_resources` are the primitive and font plumbing; `style` and `theme` own paint |
| after | `export` writes derivatives through Inkscape and provides `build`; `lint` re-checks the result independently; `cli` is the command line |
| shared | `geometry` and `units` are the value types; `hierarchy` answers which group owns an entity or a relationship; `diagnostics` is the error vocabulary |

`hierarchy` exists because emission, routing, and lint all have to agree on who
owns a connector: emission nests it in that group, routing confines it to that
group's bounds, and lint checks it stayed inside them. One walk, one answer.

`layout.grid` exists because cell assignment has to be identical in measurement
and in fitting: a grid measured with one row count and fitted with another would
be a silently wrong figure rather than a diagnostic.

`layout.sides` runs after fitting and before routing, which is the only window in
which a defaulted port's side can be chosen from what it is actually wired to.

## Boundaries

- Internal geometry is floating-point PostScript points.
- External lengths accept `pt`, `mm`, `cm`, `in`, and CSS `px`.
- IDs are explicit, stable, and referenced as strings.
- Layout styles affect geometry and require recompilation.
- Palettes affect paint only and may be patched without relayout — which is what
  `flexo retheme` does, through the `data-flexo-fill` and `data-flexo-stroke`
  role attributes emission leaves behind.
- Literal paint carries no role: `VectorPreset` cells, `paint=` overrides, and an
  `image`'s embedded artwork are deliberately outside retheming.
- SVG emission is deterministic and uses a canonical numeric formatter.
- Linting reads a finished `Compilation` and never feeds back into it, so a lint
  rule can never change the figure it judges.

## Initial dependency policy

The runtime uses only four focused dependencies: fontTools and HarfBuzz for
typography, jsonschema for the interchange contract, and PyYAML for YAML input.
The compiler itself uses frozen dataclasses and standard-library XML APIs.
