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
that every figure script wants after them. Before measuring, it resolves every
`shape="auto"` edge to the style's `lines` convention, so later passes see a
concrete shape. If the measured figure is wider than its page, it measures again
with gaps and group padding scaled by `COMPACT_SCALES` and keeps the first that
fits.

Routing feeds back into layout only through padding, for up to `ROOM_ROUNDS`
rounds: when a route or
its caption leaves the container it belongs to, or a route runs pressed between
a box and that container's edge, `routing.room` asks for more room on that side
(`LayoutSpec.room`, counted as padding by layout but not by the title), and the
compiler lays the figure out and routes it again. Then, if connectors still
cross, `_uncrossed` offers a lane of room along the top or bottom of a crossing
edge's container, where both of the edge's ends sit in that row, and keeps the
room only if a relayout removes crossings (at most `CROSSING_ROOM_TRIALS`
tries). The authored figure is never changed; only the compiled one is.

## Modules by phase

| Phase | Modules |
| --- | --- |
| authoring | `builder` lowers ergonomic Python into `ir.semantic`; `markup` turns `$...$` in string labels into styled runs; `validate` normalizes and checks the figure, resolves `align="auto"`, and merges rows (or columns) wired one-to-one into one grid (`merge_matched_stacks`); `serialization` and `schema` carry the same figure as YAML/JSON |
| style | `themes` defines each theme (a `LayoutStyle`, a page, and a tone rule) and derives a palette's paint roles; `colour` holds the Oklab arithmetic and the palette catalogue; `conventions` holds how branches, merges, and shared arrivals are drawn; `fonts` finds, matches, and loads font faces |
| measure | `layout.measure` walks bottom-up for intrinsic sizes; `components` owns per-kind port tables, motif bands, and intrinsic geometry; `text` shapes and measures runs, falling back per cluster through the font stack; `artwork` loads, sanitizes, and sizes an `image` node's file |
| fit | `layout.fit` places children into containers; `layout.arrange` computes where a group's children sit and how much room they need; `layout.grid` assigns grid cells (shared by measure and fit, so both agree); `layout.gaps` spaces linear groups; `layout.order` reorders small columns to cut crossings; `layout.ports` places adaptive ports once bounds are known; `layout.sides` picks the side a defaulted port faces |
| route | `routing.router` plans pins, groups connections that share a pin into trees, routes them, and turns the result into `RoutedEdge`s and `RoutedNet`s; `routing.search` is the bend-aware A* over a grid of priced zones; `routing.separate` orders and spaces runs that share a corridor, with `routing.vpsc` as its constraint solver; `routing.room` reports the room a container needs for its routes and captions, and the crossings room could remove; `routing.labels` places edge captions after routing; `routing.ink` supplies shaft and caption geometry (`edge_shaft`, `caption_rise`, `rail_label_position`); `routing.hints` reads `lane=`, waypoints, and `via=` (`forced_points`, `via_diagnostics`) |
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
The router makes the final choice per connection end (its pin), reading the
side the author or the component grammar declared, not the one layout chose.

## Routing, step by step

1. **Pins** (`router._pins`). Each end gets a side: an authored side is kept;
   a default side is replaced by the side facing the other end when one gap
   dominates (`DOMINANT_GAP`). The branches of a net share one side across the
   axis they spread along (`_common_net_sides`). Arrivals of different values
   at one port get separate pins unless `conventions.arrivals == "joined"`.
   A captioned edge always has its own pins. An edge's `via=` puts its
   arriving end on that side, and its departing end too when the side is
   across the line of travel (`_via_side`). Pins on a side are ordered by
   their counterparts (ties: farthest first, then by connection) and aligned
   across gaps by `_align`.
2. **Trees** (`_bundles`). Connections that share a pin are one bundle, routed
   as a tree grown from that pin (`_Scene.grow`).
3. **Search** (`search.Grid.route_from_tree`). A* over states
   `(x, y, heading, turned)`; zones are priced, not walls. An arriving spoke may
   finish at its full `arrival_clearance` stub or, at a surcharge, at
   `shortest_arrival`.
4. **Rip up and reroute** (`REROUTE_PASSES`), pricing other bundles' ink
   (`_Traffic`): crossings cost `CROSSING_COST` bends, shared corridors a small
   `OVERLAP_COST` per point.
5. **Separate** (`separate.separate`). Per axis, runs in one corridor are
   ordered to cross least and spaced by VPSC.
6. **Uncross** (`_reorder_crossing_pins`). While lines cross after separation,
   neighbouring pins on the affected sides are swapped, and the figure rerouted
   and separated again; a swap that removes crossings is kept (at most
   `PIN_ORDER_TRIALS` tries).
7. **Straight edges** (`_straight_edge`) skip steps 1-6: one segment from
   outline to outline, offset a lane apart when two join the same pair.
8. **Captions** (`labels.place_edge_labels`). Each edge caption takes the first
   candidate position beside its own line that overlaps nothing, or the
   least-overlapping one.
9. **Marks.** Where a bundle's lines join, the conventions (or the net's
   `joint=`) decide between a plain T, an arrowhead into the joined line, and
   a dot (`_arrows_at_joins`, `_dots_at_joins`).

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
