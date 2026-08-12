# Panel-b routing and layout critique

Status assessment against the ModelAngelo panel-b acceptance target
(`modelangelo-gnn` in `src/flexo/gallery.py`, rendered via
`flexo gallery modelangelo-gnn`). The defects below are systemic; each item
names the mechanism, not just the symptom.

## R1. Greedy, order-dependent routing without corridors

`route_figure` routes nets, then edges, in authoring order; each route only
sees earlier routes as occupied. Long inter-module rails route last and hug
inflated obstacle boundaries at exactly `route_clearance`. Editorial figures
read calmly because long-haul traffic runs **centered in gutters** (spine
column, inter-module gaps, margins).

Required behavior:

- Route order must be deterministic and quality-driven: inter-container
  (long-haul) connectors first, short intra-container connectors last.
- Horizontal/vertical runs longer than ~3x `route_clearance` should prefer the
  center of the free corridor they traverse rather than the obstacle-hugging
  coordinate. The candidate grid already contains midpoints between obstacle
  boundaries; add a mild cost for coordinates that lie within
  `route_clearance` of an obstacle boundary so mid-gutter candidates win when
  free.

## R2. Group containers are not routing obstacles

Only node bounds become obstacles. An edge from a module interior to the
spine may cut through a *different* module's container. Every fitted group
with a drawn boundary (role not in {"layout", "canvas"}) must be an obstacle
for any route whose endpoints are both outside that group. Endpoints inside
the group keep it transparent (they must exit through its padding).

## R3. No cross-container alignment

The Add/LN spine relies on `justify="space-between"` luck. There is no way to
state "spine block N sits level with the gap between module N and module
N+1". Consequence: `addln3` landed below the heads row, so the heads fan-out
rail was placed under the row and every stem hooked around its column.

Two-part fix:

- Documented authoring pattern: band rows. Each band is a row containing the
  spine element and its module; the heads band contains the final Add/LN and
  the heads row. `modelangelo-gnn` must be restructured this way.
- The net rail feasibility interval (`_rail_interval` in `routing/nets.py`)
  already prevents doubling back; with band structure the fan-out rail lands
  between the Add/LN and the heads row.

## R4. Track assignment is emergent

Separation currently comes from penalties plus occupied-offset candidates in
the visibility grid. Two problems: spacing is irregular (whatever coordinate
the grid offered), and candidate explosion made compile ~18s for panel-b.

Required behavior:

- Candidate pruning: only coordinates within the routing boundary (inflated
  by one clearance) participate; coordinates closer than 0.5 pt are merged;
  occupied-offset candidates are only derived from segments that overlap the
  start/end bounding box inflated by 4x separation. Target: full gallery
  build under 3 seconds.
- A nudging post-pass (`routing/nudge.py`) that, after all routes exist,
  groups parallel segments sharing a corridor (pairwise distance below
  `port_spacing`, longitudinal overlap > 0) and redistributes them
  symmetrically about the group mean at exactly `port_spacing`, moving only
  interior segments (never port stubs, first or final segments) and keeping
  junction points of net stems attached to their rails.

## R5. Straight lines must be guaranteed when possible

Port adaptation aligns endpoint coordinates, then the router rediscovers the
straight line through a quantized grid; any near-miss yields 2-4 pt S-jogs
right after ports. Invariants:

- If source and target escape points are collinear along the port axis and
  the direct segment is obstacle-free, the route is exactly that segment.
- After simplification, collapse interior zigzags whose middle segment is
  shorter than 2x `elbow_radius` by aligning it with its neighbors, when the
  shifted segment stays obstacle-free.

## R6. Layout must reserve room for edge labels

Edge labels are measured only at routing time, so gaps never reserve space
("ESM-1b" clips its neighbors). Measure edge labels in the measurement pass
(extend `MeasuredFigure` with per-edge label metrics) and let
`routing_gaps_for_group` widen the crossed boundary to at least the label
width plus two paddings.

## R7. Failed builds must still be inspectable

`flexo build` / `flexo gallery` refuse to write any output when lint reports
an error. Keep the nonzero exit code, but always write the outputs so the
failure can be seen. Print diagnostics to stderr. (Crossing diagnostics are
warnings; obstacle intersections, separation violations, and misses remain
errors.)

## R8. Junction dots

`emit.py` draws junction dots on nets only when *any* crossing exists
anywhere in the figure (a global flag). Branch points are semantic: always
draw dots at fan-out and merge junctions; never draw them elsewhere.

## Acceptance

`uv run flexo gallery` builds both gallery figures with zero errors; the
panel-b preview shows: straight port-aligned runs, mid-gutter rails, no route
through any container it does not own, heads fan-out entering all head MLPs
from above with a single rail between the last Add/LN and the heads row, and
uniform lane spacing on parallel runs. Full build under ~3 s. `uv run pytest`
stays green.

# Round 2 (post band-restructure review)

## R9. Fan-out rail orientation must fit the targets, not the hub

`_vertical_rail` picks the rail perpendicular to the hub port axis. For the
skip nets (hub = Add/LN south output; targets = next module's node features
west port + next Add/LN north skip) this yields a horizontal rail whose
junctions sit ~85 pt east of the spine: the trunk doglegs instead of dropping
straight down the spine as in the reference.

Rule: choose orientation by target-port-side majority — NORTH/SOUTH targets
want a horizontal rail, EAST/WEST targets want a vertical rail; ties resolve
*along* the hub port axis (south hub → vertical trunk). Verify: heads fan-out
keeps its horizontal rail; skip nets become a straight vertical trunk at the
hub x with L-branches east into each module's node features; the attended
nets keep their vertical rails.

## R10. 1:1 adaptive port pairs must end exactly collinear

Multi-output blocks (cryo MLP Q/V, sequence MLP K/V, IPA MLP Qpoints/V) still
show 2-4 pt S-jogs immediately after the source port. Extract the actual port
coordinates from the emitted SVG before changing code and find why
`adapt_ports` (three-pass target/source/target alignment plus
`_pack_coordinates` clamping) leaves the pair misaligned. Invariant to
enforce and test: when an adaptive port's only connection is to another
adaptive port and neither is coordinate-constrained by packing conflicts, the
two ports end at identical cross-axis coordinates and the route between them
is a single segment.

## R11. Add/LN blocks belong in inter-module strips

Feedback (residual) rails currently route up and over their module because
each Add/LN sits level with the *top of the following module*, so its east
feedback port is unreachable from the inter-module gap. Restructure
`modelangelo_gnn`: each Add/LN gets its own thin band row between module
bands (spine column position unchanged). The feedback rail must then read:
east out of the module's update MLP, south along the module's right, west
along the Add/LN strip, arriving at the east feedback port — always below its
module, never above. If the router still prefers a top route after the
restructure, extend `Figure`/`GroupBuilder.residual()` to accept semantic
waypoints (EdgeSpec already carries them) and pin one waypoint in the strip;
prefer making the automatic route correct first.

## R12. Corridor reservation must not leak whitespace

The 52 pt heads corridor is uniform group padding, so it also pads the bottom
and right of the heads band, leaving a dead strip at the canvas bottom.
Replace with a directional mechanism (e.g. an explicit spacer row above the
heads row, or per-side padding if that is cleaner in the layout model). The
canvas must end at the content plus the normal margin on every side.

## R13. Polish toward the reference

- Attention blocks: label with styled runs — softmax(QK^T)V with a
  superscript T (TextRun baseline_shift already exists) instead of the word
  "Attention"; keep component sizing correct via measured label metrics.
- Optional if it stays clean: the recycle loop from the "Node features" head
  output back up the left margin into "Previous layer" (west ports, residual
  role), as in the reference. Drop it if it cannot route cleanly.

## Acceptance (round 2)

Preview shows: straight vertical skip spine through all Add/LNs; residual
rails below their modules in the inter-module strips; no over-the-top
arcs; no S-jogs at multi-output MLPs; no dead bottom strip; heads rail
unchanged. Zero lint errors, `uv run pytest` green, gallery build < 3 s.

# Round 3 (fine geometry)

## R14. Net port adaptation must respect rail geometry

`adapt_ports` averages a port's desired coordinate over ALL its layout
connections, including net pairings between perpendicular ports. Consequences
in panel-b: the skip trunk taps the Add/LNs off-center (the east branch into
each module pulls the hub x toward the module), and the four head MLP north
ports clamp to their left band edge chasing an unreachable hub x.

Rules, applied to NET connections only (edge connections unchanged):
- a net pairing contributes a desired coordinate only when the two ports'
  axes are parallel (N/S with N/S, E/W with E/W) — perpendicular pairings are
  served by the rail junction and must not pull;
- a net sink adapting toward a hub aligns all-or-nothing: if the desired
  coordinate is outside the feasible band, keep the authored offset rather
  than clamping to the band edge.

Expected: the skip trunk runs through the centers of Previous layer and all
Add/LNs; head MLP taps return to their centers; attended/merge nets keep
their current good shape.

## R15. Cryo attention must share the encoders' port band

The last S-jogs (`edge.4`, `edge.6`: y 74.26 → 85.26 and 80.26 → 91.26) are
the proven disjoint-band fixed point. Fix in `gallery.py`: align the cryo
module row so the attention block's west port band overlaps the qv MLP's east
band (e.g. `align="start"` on the module row, or an equivalent structure).
Verify the sequence and IPA modules stay straight.

## R16. IPA graph output must face its target

`edge.16` leaves the graph's east port and doubles back 46 pt west over its
own box to reach the attention above-left. Give the IPA graph an explicit
north-side adaptive output port in `gallery.py`. (Engine-level automatic port
side selection is out of scope for this round; note it in the critique
backlog instead.)

## R17. Lint and router must agree on transparent kinds

Routing ignores {"label", "spacer", "junction"} nodes (see TRANSPARENT_KINDS
in `routing/nets.py`); `lint.py` obstacle checks (`_routing_diagnostics`,
`_net_obstacle_diagnostics`) do not filter them, which already forced a
zero-width-spacer workaround in the gallery. Import and apply the same set in
both lint checks.

## Backlog (deferred from round 3)

Both items concern *edge* endpoints whose two ports face perpendicular axes;
R14 fixed the equivalent defect for net legs only, because edge adaptation is
covered by a byte-for-byte determinism test.

- **Automatic port side selection.** An author still has to name the side that
  faces the target (`PortSpec("output", Side.NORTH, ...)` on the IPA graph). The
  engine has the geometry to choose it: pick the side whose outward vector
  points at the other endpoint, unless the author pinned one.
- **Clearance-aware adaptation for perpendicular edge pairs.** Aligning a north
  port's x with a west port's x puts the corner exactly on the target port, so
  the arrival cannot reserve its clearance and the router answers with a small
  hook (8 pt on `edge.16`). Such a pair wants the desired coordinate offset by
  one target clearance *away* from the target's side, not equal to it.

## Acceptance (round 3)

Zoomed preview shows: skip trunk through block centers with centered head
taps; zero S-jogs anywhere; IPA k-line rises directly from the graph top into
the attention with no doubling back. Zero lint errors, warnings limited to
the three reference-consistent crossings, `uv run pytest` green, build < 3 s.

# Round 4 (design language: center ports and vector glyphs)

Reference conventions supplied by the author (two mock images):

- Fan-out: the trunk leaves the source's south center, runs a horizontal rail
  with junction dots, and each branch drops into the target's north center.
- Fan-in: sources emit east from their vertical centers into a shared
  vertical rail that turns down into the sink's north center.
- Feature values are standalone vertical vector glyphs: a stack of ~3 rounded
  square cells in a color ramp, label BELOW the cells, optionally two columns
  side by side (e.g. "K, V"). Arrows attach at the middle cell's height.
- Attention reads as a formula-labeled arrow: the Q vector's east arrow runs
  toward the attended vector with softmax(QK^T)V above it, and the K,V
  vector's arrow rises and merges into it before the sink.

## R18. Boxes take arrows at side centers only

Multiplicity must never stack ports on a box edge. Consequences:

- Components keep exactly one center port per side; fan-out/fan-in use nets
  (already image-2-shaped after R9/R14).
- Port adaptation may fine-tune alignment but must stay near center: clamp
  the adapted coordinate to a centered band (fraction of the side length,
  constant in `layout/ports.py`, ~0.3 of the side); outside the band, keep
  the authored offset (a centered Z-bend beats an off-center attachment).

## R19. Vertical vector glyph

New component kind "vector" (`components.py` / `render.py`):

- geometry: `cells` (default 3) rounded-square cells stacked vertically with
  a small gap; `columns` (default 1, e.g. 2 for "K, V") side-by-side stacks;
  cell size and gap are layout-style tokens;
- paint: each instance names a `ramp` property resolved through palette
  roles (e.g. ramp-1..ramp-6 or named roles); cells shade along the ramp
  (opacity or explicit shades) — paint-only, geometry identical across
  palettes; all three palettes must define the roles and stay lintably
  distinguishable in grayscale;
- label: BELOW the cells. Implement as a builder composite (`vector()` in
  `builder.py`): a small layout column group containing the cells node and a
  label node, so port geometry stays the trivial cells rect and the engine
  needs no label-aware port math. Ports: west/east at the middle of the cell
  stack, north/south at its top/bottom center.

## R20. Panel-b re-authored in the vector language (after R18/R19)

- Every feature value becomes a vector glyph: node features, sequence
  embedding, Q, K/V (two columns), C, attended value, module outputs /
  residue predictions where the reference shows strips.
- Multi-input boxes disappear: the cryo update MLP's attended + C inputs
  become a fan-in merge before its single west center port; MLP multi-outputs
  become one center arrow into a multi-column vector.
- Attention: Q vector → attended vector as a merge net labeled
  softmax(QK^T)V above the horizontal run, with the K,V vector rising into
  the rail (image-3 shape). The matrix glyph remains an available component
  but panel-b uses the formula-arrow form.
- Keep: band/strip structure, spine, feedback rails, heads, average merge,
  recycle loop.

## Acceptance (round 4)

Every arrow endpoint in panel-b lands at a side center (of a box or of a
vector's middle cell); vectors render as labeled vertical cell stacks with
distinct ramps; the attention reads as the formula-labeled merge arrow; zero
lint errors; pytest green; both palettes re-theme without geometry change.

## R21. Rounded arrows

Author feedback: connectors should turn on visibly rounded corners, not
near-sharp elbows. The plumbing exists (`rounded_polyline_path`,
`LayoutStyle.elbow_radius` = 3 pt); raise the paper style's `elbow_radius`
to ~6 pt and verify the knock-on constraints still hold: target clearance
(2×arrow + radius), the zigzag-collapse threshold (2×radius), nudging slack,
and short segments whose length is below two radii (the path helper must
degrade gracefully rather than overshoot). Check junction dots still sit on
the rounded rails. If 6 pt visibly harms any dense corridor, choose the
largest radius that stays clean and report it.

## R22. Net rails must round their terminal elbows

Where a net rail terminal serves exactly one stem there is no junction dot,
and rail and stem are emitted as separate straight paths — that elbow stays
sharp while every other corner now turns on the 6 pt radius (~15 places in
panel-b, e.g. the bottom of predictions.merge into Average). Merge the
terminal geometry so the corner carries a fillet: shorten the rail by one
radius at a single-stem terminal and let the stem own the rounded corner (or
emit rail + terminal stem as one polyline). Junction dots at multi-stem
points must remain exactly on the rail.
