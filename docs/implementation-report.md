# Flexo Implementation Running Report

## Objective

Build a semantic Python compiler that produces deterministic, attractive,
publication-sized figures whose text, blocks, connectors, and composite
internals remain independently editable in Inkscape.

## Baseline

- Code/config baseline: empty public repository at `jamaliki/flexo`.
- Data/artifacts: no figures or tests.
- Current promoted settings: none.
- Reproduction command: `uv run flexo gallery --output examples/build`.
- Primary metric: acceptance gallery passes structural and geometric lint with
  no errors and is judged editorially clear at final physical size.
- Guardrails: deterministic output, minimum 7 pt typography, live editable
  text, obstacle-free routing, stable IDs, and passing tests.

## Metrics And Views

- Aggregate metric: validation errors and warnings per gallery figure.
- Grouped metrics: overlaps, overflow, route intersections, text fit, SVG
  structure, output dimensions, and canonical-repeat equality.
- Visual artifact checks: PNG render at 2x, full-size SVG inspection, and
  Inkscape Objects and Layers structure.
- Validation suite: unit, property, structural, integration, and Inkscape CLI.

## Current Best State

- Best promoted configuration: coordinate-free `vertical-slice` gallery figure.
- Why it is currently best: zero lint diagnostics; all four output variants;
  clean 180 x 47.2 mm render; semantic residual lane; live text and named layers.
- Known weaknesses: the scientific inset is generated rather than imported;
  embedded variable-font CSS produces an Inkscape support warning; the gallery
  does not yet stress multiple modules or encoder-decoder layouts.
- Live beam note: `docs/improvement-beam.md`.
- Current beam checkpoint: checkpoint 2.

## Experimental Log

### Cycle 1: First integrated editorial baseline

- Branch owner: primary agent.
- Observation: the initial automatic residual left the normal east output and
  doubled back around the stacked inputs before reaching the bottom lane.
- Hypothesis: a semantically named residual port on the source component would
  turn the skip path into an intentional boundary rail.
- Mechanism: port side controls the forced departure segment before routing.
- Branch guardrails: same semantic components, no coordinates, zero lint errors.
- Success criteria: direct visual departure into the protected lane with no
  obstacle intersections.
- Minimal experiment: add a west-side feature-strip residual port and make the
  builder prefer it for residual edges.
- Command(s): `uv run python examples/vertical_slice.py`; Inkscape PNG export;
  `uv run pytest -q`.
- Result: residual centerline reduced from 7 to 5 vertices; the rail now leaves
  directly from the component boundary; zero lint diagnostics; 39 tests pass.
- Plots: `examples/build/vertical-slice.preview.png`.
- Interpretation: semantic ports provide higher-quality control than raw route
  waypoints while preserving automatic obstacle avoidance.
- Decision: accepted.

### Cycle 2: Marker orientation and visual weight

- Branch owner: primary agent.
- Observation: 5.5 pt markers were longer than the 5 pt target approach, so
  shortening consumed the last segment and oriented several west-port arrows
  vertically from the preceding elbow.
- Hypothesis: markers shorter than the routing clearance will preserve final
  approach orientation and reduce clutter around multi-port components.
- Mechanism: the shaft retains a positive-length segment in the same direction
  as the logical centerline before the marker base.
- Success criteria: centerline and shaft final orientations match for every
  gallery edge; zero route failures; visibly lighter arrowheads.
- Minimal experiment: reduce markers to 4.0 x 3.5 pt and lint final-segment
  orientation plus port-direction conformance.
- Result: every vertical-slice edge has a matching final orientation; all
  west-facing targets receive right-pointing arrows; zero lint diagnostics.
- Decision: accepted.

### Cycle 3: Coupled layout and routing

- Branch owner: primary agent.
- Observation: widening dense gutters fixed arrowhead crowding but the
  edge-at-a-time router still produced 17 elbows and one feed-forward crossing.
- Hypothesis: routing quality depends on target-port placement and layer order,
  not just shortest-path search after geometry is frozen.
- Mechanism: enlarge edge-dense sibling gutters, align adaptive receiving ports
  with their producers, reorder small adjacent columns only when crossings
  strictly decrease, then rank visibility paths lexicographically.
- Guardrails: explicit port offsets and semantic lanes remain fixed; rounded
  corners retain clearance; author order wins every tie.
- Success criteria: zero feed-forward crossings, no insufficient port stubs,
  and at most one non-straight feed-forward connection in the vertical slice.
- Result: total elbows fell from 17 to 7; feed-forward elbows fell from 14 to 2;
  seven of eight feed-forward connections are straight; crossings fell from one
  to zero; zero lint diagnostics; 43 tests pass.
- Plots: `examples/build/vertical-slice.optimized-routing.png`.
- Interpretation: orthogonal routing must be coupled to limited coordinate and
  ordering freedom; a more elaborate path search alone cannot beat geometric
  lower bounds imposed by fixed ports.
- Decision: accepted.

## Accepted Changes

- Public repository, compiler contract, and validation objectives established.
- Immutable semantic, measured, fitted, and routed IR pipeline.
- Exact HarfBuzz/fontTools measurement with bundled IBM Plex Sans.
- Deterministic lane layout, visibility routing, editable SVG, validation, CLI,
  palette re-theming, and Inkscape-derived outputs.
- West-side source residual port for deliberate bottom-rail composition.
- Marker geometry bounded below route clearance, with direction linting.
- Edge-aware routing gutters, adaptive generated ports, bounded crossing
  minimization, and lexicographic clean-path/bend/length routing.

## Rejected Changes

- None.

## Remaining Residuals

- Replace the generated inset with safe imported SVG/image support.
- Expand the gallery to transformer, U-Net, and multi-module acceptance figures.
- Compare static font instances against the current variable-font embedding.
- Add property tests and native/plain SVG round-trip checks.

## Reproducibility

- Main command: `uv run flexo gallery --output examples/build`.
- Validation command: `uv run pytest && uv run ruff check .`.
- Key artifacts: `examples/build/` and `tests/artifacts/`.
