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

## R23. Authoring ergonomics: sides, corridors, and one operator sign (round 5)

Direct author feedback from a live session writing the panel-b bones script:
four of nine iterations were port-side fixes, the fan-out rail hugged its
source's edge, "what is that weird + sign?", and three separate wrappers
raised on keywords the others accepted.

- **Automatic port side selection — done** (the R3 backlog item above). A port
  whose side came from the component grammar rather than from an authored
  `PortSpec` now picks its side in a new pass, `flexo.layout.sides`, after fit
  and before adaptation: the side facing the counterpart's node centre, with a
  net voting once for its trunk direction rather than once per spoke, a
  decisive margin below which the grammar's side stands, a lane-hinted edge
  casting no vote, and a loop-back displaced off the side its spine leaves so
  the two runs are not drawn a hair apart. Authored `PortSpec`s and
  `depart`/`arrive` hints are pinned. A port pulled two ways emits
  `layout.port.side.conflicted` (info). The bones script lost every `PortSpec`,
  every `source_port=`/`target_port=`, and 31 lines, and renders the same
  figure with zero diagnostics.
- **Unhinted net rails sit at the corridor midpoint.** The default preference
  was one escape short of the hub, which drew the rail against the box its
  branches leave. It is now the middle of the band the stems leave free
  (`_corridor` / `_preferred_rail`), still subject to the existing feasibility
  search. A captioned rail in a corridor too narrow to halve keeps the end
  position, because the caption is written along the run it would otherwise
  cross. `rail`/`rail_at` are unchanged.
- **The add-norm motif is a circled plus on the label's line.** `⊕ Add LN`, a
  word space between the two, the pair centred as a unit, the box measured
  wide enough to hold both, the sign dropping out of a box pinned too narrow.
  Sizing lives in `components.operator_sign` so measurement and paint agree.
- **API uniformity.** `input=`/`inputs=` on `node` and on every component
  factory; `ports=` composing with the factories that compute ports
  (`mlp`/`cnn`/`concat`/`channels` no longer raise "got multiple values for
  keyword argument 'ports'"), the author's table winning whole; `properties=`
  merging under a factory's own; `net`/`merge` on `GroupBuilder` as well as
  `Figure`; `label=` accepting styled runs everywhere.

## Acceptance (round 5)

`uv run pytest` green (263), `ruff check` clean, `flexo gallery` with zero lint
errors and no new warnings. Gallery geometry moved in exactly three places, all
verified improved-or-neutral against the previous render: the heads fan-out rail
and the two unlabelled module rails now sit mid-corridor, and the three Add LN
boxes carry the new sign. `vertical-slice` is byte-identical.

## R24. Alignment by port line, captions that block, and container shadows (round 6)

Five items, straight from the user reading the rendered panel:

> "Attended value" gets clipped by the arrow, there should be a couple of pixels
> space. — The input features in the Cryo-EM module (and other modules) should be
> center aligned to each other. If this is difficult to do with the current
> architecture, make it simple! — The input and output arrows of the CNN should be
> aligned to each other and to the center of the CNN. — Just remove the plus from
> Add LN. — What about a shadow effect for some of the boxes, such as the modules?

- **A caption is ink, so nothing may route through it.** `TRANSPARENT_KINDS` now
  holds only `spacer` and `junction`; `label` moved to a new `CAPTION_KINDS` and
  takes `style.caption_clearance` (3 pt) instead of the full `route_clearance`
  (5 pt), through one `components.route_clearance(spec, style)` that every
  obstacle-building pass reads (`routing.solve`, `routing.nets`,
  `routing.nudge`). Ground truth from Inkscape `--query-all`: before, the
  `cryo.context` rail ran at x 600.1–601.3 while the "Attended value" text ended
  at 600.7 — overlapping ink. After, the rail sits at 605.0, a 4.3 px gap. The
  cost is a real cliff: a caption sits directly under its glyph's south port, so
  a south departure from a captioned vector can now fail with `routing.no-path`.
  Sibling-transparency was considered and rejected — the rail that crossed the
  caption belonged to a net that the captioned glyph is itself an endpoint of, so
  exempting siblings would have left the user's defect exactly as it was.

- **The two alignment items were one missing capability: `align="ports"`.**
  Children aligned by bounding box line up whatever the box happens to contain;
  figures want the line the *ports* sit on. New alignment mode on rows, columns,
  grids, and overlays, measured like a text baseline — child ascent is
  anchor-to-top, descent anchor-to-bottom, the line is `max(ascent)` and the
  extent `max(ascent) + max(descent)`, which is why a ports-aligned row can
  exceed its tallest child. A component's anchor is its own centre; a group's is
  its **anchor child's**, carried up into group coordinates: `anchor="<child>"`
  when authored, else the first child that is neither a label nor a spacer — so a
  captioned vector answers with its cell stack.

  The refactor that made it possible: cross-axis placement moved out of
  `layout/fit.py` into a new `layout/arrange.py` that measurement and fitting
  both call, because a ports-aligned group's *size* and its children's
  *positions* can no longer be derived from each other's assumptions. Anchors are
  computed bottom-up in `layout/measure.py` and ride on `MeasuredNode`/
  `MeasuredGroup`; `grid_tracks` grew anchor-aware tracks and `grid_anchor_lines`.
  Verified: every chain in every module is collinear to 0.0000 pt and every input
  column shares one centre-x to 0.0000 pt.

  The gallery adopted it and lost `_BOX_HEIGHT` entirely — the crutch that made
  every module box exactly one cell stack tall so its ports would land at the
  vector's middle cell. Heights are now free to be aesthetic.

- **The add-norm's circled plus is gone.** `operator_sign`, `label_advance`,
  `OperatorSign`, and the reserved label width with them, so the box re-centres
  its words and measures to them alone. R23 added it; the figure it was added to
  says three times per panel that it was ornament.

- **Containers may cast a soft shadow, and it is pure vector.** `shadow=True` on
  a group or a node, off by default, with a `shadow` palette role every palette
  defines. SVG filters were tested and rejected on evidence: Inkscape's PDF export
  reports `unknown type: svg:feDropShadow` and rasterizes the filtered region, and
  `feGaussianBlur` turns its whole subtree into a 96 dpi image XObject plus smask
  (`pdfimages -list` on both). The shipped shadow is five nested rounded rects,
  equally faint, offset together, compositing to `shadow_opacity`; three were
  still visible as rings under magnification. `pdfimages -list` on the shadowed
  gallery PDF lists nothing and `pdffonts` still shows embedded text — fully
  vector. On for the panel-b module containers and for the bones script.

## Acceptance (round 6)

`uv run pytest` green (274, from 263: five add-norm sign tests removed, sixteen
added for ports alignment, anchors, caption clearance, shadows, and their
interchange), `ruff check` clean, `flexo gallery` with zero lint errors and no new
warnings. `vertical-slice` is byte-identical; the scratchpad attention module is
byte-identical to its pre-change render. Module geometry moved everywhere, all of
it verified: chains collinear, columns centred, captions clear of ink.

### Backlog from this round

- The `softmax(QKᵀ)V` net caption sits hard against the vertical rail it labels
  in the cryo module — net and edge *labels* are route geometry, not nodes, so the
  caption-obstacle rule of this round does not reach them. Pre-existing (it is in
  the round-5 render too), and the same fix applies: measure a connector label and
  let it claim its own clearance.

## R25. Three defects the round-6 render put on the page (round 7)

Three items, straight from the user reading `modelangelo-gnn.preview.png`:

> The softmax(QKᵀ)V captions nearly touch the horizontal run they label. — The
> module shadow reads as a halo; light comes from the top left, so the shadow
> should show along the bottom and right edges only. — "Edge rectangles" and
> "Centre cube" overlap the inset's molecule illustration.

- **A connector caption now claims the clearance R24 gave component captions.**
  R24's backlog item, closed. `rail_label_position` had a flat `-4.0` from the
  run's centerline and `edge_label_position` a `descent + 2.0`; neither counted
  the shaft's own stroke, and the flat one counted no descender at all. Both now
  go through `nudge.caption_rise` — half the connector stroke, then
  `style.caption_clearance` (3 pt, the same token the obstacle rule spends), then
  the caption's lowest ink. That last term is new: `text.ink_descent` extends
  `TextMetrics.descent` for subscript runs by the OS/2 `ySubscriptYOffset` the
  renderers actually apply, because `softmax(−ΣD_q)V` reaches 2.75 pt below its
  baseline where the font's descender is 2.20. Ground truth from Inkscape
  `--query-all`, ink box to ink box: cryo 2.24 pt → 3.89, IPA 0.80 pt → 2.95,
  ESM-1b 3.65 pt → 3.80.

- **The caption also had to clear the riser, and that is not an end condition.**
  The first attempt shrank the run at whichever *end* a riser climbed out of and
  changed nothing: the cryo merge draws source stem, rail and target stem as one
  collinear run, so the K,V riser leaves from the run's **middle**. So risers now
  subtract intervals from the run — `_captioned_centre` cuts
  `[x − clearance, x + clearance]` out of it for every vertical the net draws
  *upward* through the caption's band, and the words take the widest stretch left
  (falling back to a clamped centre when even that is too narrow). A riser
  dropping away below the run is ignored, which is what leaves the IPA caption
  centred on its whole run. Cryo and sequence went from 0.11 pt of air beside the
  rail to 5.34.

- **The shadow is directional by geometry, not by clipping.** Layers are offset
  down *and right* now, and `shadow_offset` is raised to `shadow_spread` if the
  author set it smaller. That one inequality is the whole invariant: the widest
  layer's top-left corner lands on the box's own top-left corner and every
  tighter layer starts further in, so no layer can put ink above the top edge or
  left of the left edge — true at any corner radius, with no clip path, and still
  five plain rectangles. Defaults moved to offset 2.5 pt / spread 2.0 pt (from
  1.0 / 2.5), which is a flat band against the bottom and right edges fading over
  the next 2 pt. Verified from the SVG: the cryo shadow's top-left corner sits
  0.9 pt *inside* the painted container edge and it reaches 4.1 pt past the bottom
  and the right. `pdfimages -list` on both gallery PDFs still lists nothing.

- **An inset stacks its label and its illustration; it does not overlay them.**
  The label was centred at `0.24 × height` and the molecule at `0.67 × height`,
  two unrelated fractions that happened to collide once a caption ran to two
  lines — 5.7 pt of overlap for "Edge rectangles", 0.8 pt for "Centre cube".
  Replaced by one band model in `components.py`, read by all three passes that
  need it: `label_band_height` and `motif_area` give the label
  `padding_y + label.height` at the top, then `style.motif_label_gap` (3.5 pt),
  then the rest of the interior to the motif; `intrinsic_node_size` sizes a
  motif-label kind as that stack plus the kind's own `motif_height`; and
  `render._label_baseline` sets the words at the top of the same band. The inset's
  molecule has a declared natural ink box (`INSET_INK`, derived from its bond
  geometry so sizing and painting cannot disagree) and scales to fit the area,
  centred on its *ink* rather than on its central atom — so an authored height too
  small shrinks the drawing instead of colliding with the words.

- **Fixed uniformly, because the defect was the pattern and not the inset.**
  Every motif that draws below a label now paints inside `motif_area`:
  matrix/attention grids (their `top_fraction` fudge is gone), sequence tokens,
  concat bars, feature-strip cells, and the graph's little network, which keeps
  its own `GRAPH_INK_HEIGHT` and is centred in the area rather than pinned a
  fixed distance off the bottom edge. `sequence` and `feature-strip` minimums
  grew from 26 pt and 25 pt to 29.3 pt, which is the near miss the old code was
  living on: their motifs cleared a one-line label only at the default height.
  `vertical-slice` shows the win twice — its "Node features" strip was one point
  off its own caption.

- **The gallery's insets went from 42 pt to 60 pt.** An inset stacking two label
  lines, a gap and a full-size molecule needs 57 pt; 42 pt would have rendered the
  molecule at 40 % scale, which is the graceful degradation working and not a
  figure anyone wants. Both insets keep one shared height so the two molecules
  draw at the same size. The cryo module's first and third rows grew with them and
  the figure is 18 pt taller.

## Acceptance (round 7)

`uv run pytest` green (281, from 274: seven added — connector-caption rise and
reach, the riser-cut caption, a whole-figure assertion that every panel-b formula
keeps `caption_clearance` from every segment of its own net, bottom-right-only
shadow ink, the inset band for one- and two-line labels, a squeezed inset that
scales instead of colliding, and every motif-label kind painting inside its
area). `ruff check` clean. `flexo gallery` exits 0 with zero lint errors and the
one pre-existing `routing.connector.crossing` warning, unchanged. Both PDFs
carry no raster objects and embedded fonts. The scratchpad bones script shows the
directional shadow on all three bands; the attention module re-renders with no
diagnostics and its formula caption improved with the rest.

## R26. Two renderer defects the round-7 audit found (round 8)

Both were paint bugs with the same shape: an entity Flexo drew as a special case
rather than as an instance of what it actually is.

- **A group title flattened its styled runs.** `emit._render_group_label` built
  the same `<text>` object a component label does and then set
  `"".join(run.text for run in spec.label)` on it, so a title written as
  `(TextRun("QK"), TextRun("T", baseline_shift="super"))` came out as the plain
  string `QKT` — the one text object in a figure that silently dropped what its
  author wrote. It was the only one because it was the only one not built by a
  run loop, and there were two of those: `emit._connector_label` and
  `render._render_label`, twenty-eight-line near-copies that had drifted apart on
  which attributes a `tspan` spells out.

  Unified into one `render_common.render_runs`, now the single place Flexo sets
  text — component labels, connector captions, and group titles all go through
  it, so a superscript reaches all three or none. **The emission rule is the
  economical one, not the explicit one:** a run emits `font-weight` only where
  its author asked for a weight other than the `TextRun` default, `font-style`
  only where it is italic, and `baseline-shift` with the reduced `font-size` only
  where it is shifted. This is a correctness requirement rather than a taste for
  short attributes. A title declares `title_weight` once on its `<text>`, so the
  alternative — `render`'s habit of writing `font-weight="400"`,
  `font-style="normal"` and a redundant `font-size` onto every plain run — would
  have unbolded every group title in every figure the moment titles started
  emitting tspans. Inheritance from the text object is the mechanism that lets
  one helper serve a caption at 400 and a title at 600.

- **`paint=` did not reach a container.** `paint={"fill": ..., "stroke": ...,
  "label": ...}` worked on every node and was a `TypeError` on `group()`, so a
  module whose body had to differ from its palette could not be authored at all.
  Now `GroupSpec` carries `paint` as its own sorted `(part, colour)` pairs — a
  node routes the three parts through its property bag because a property holds a
  scalar and never a mapping, and a group has no bag to route them through — and
  `render_common.paint_override` answers for both spec kinds. `_render_container`
  honours `fill` and `stroke` on the container body and `_render_group_label`
  honours `label` on the title, with the node convention intact: an overridden
  part emits no `data-flexo-fill` or `data-flexo-stroke`, so `flexo retheme`
  leaves author paint exactly as written. Wired end to end — `group(paint=...)`
  and `module(paint=...)` validate and normalize to `#rrggbb` at the point of
  authoring through the same `_paint_parts` check nodes use, the pairs serialize
  as a `paint` object and round-trip, and both copies of the schema gained a
  `paint` definition constrained to the three parts and a hex colour.

Two things were noted and deliberately left alone, both older than this round and
both geometry rather than paint. A title is *measured* at its runs' own weights
and *drawn* at `title_weight`, so a semibold title is slightly wider than the
metrics that reserved its band; fixing that moves every figure with a titled
module. And a run beginning with a space loses it, because SVG whitespace
processing strips the leading whitespace of each `tspan` chunk — true of every
component and connector label since they were first drawn as tspans, and now
reachable from a title too, so `(TextRun("QK"), TextRun(" module"))` sets as
`QKmodule`. The fix is per-run advance rather than an `xml:space` switch, which
is a text-shaping change and not this round's business either.

## Acceptance (round 8)

`uv run pytest` green (295, from 286: nine added — a title's runs surviving into
tspans, a title run inheriting `title_weight` while an explicit weight overrides
it, container and title paint with no roles left for retheme, a part left out
keeping its role, group paint moving nothing, the builder lowering group paint to
sorted normalized pairs, both rejections, and the serialization round-trip).
`ruff check` clean. `flexo gallery` exits 0 with zero lint errors and the one
pre-existing `routing.connector.crossing` warning, unchanged.

Visual parity is exact rather than argued: both gallery preview PNGs at 300 dpi
are **byte-identical** to their pre-edit baselines (`compare -metric AE` = 0,
RMSE = 0), and crops of a group title, a node label, and the `softmax(QKᵀ)V` net
caption each differ in zero pixels. Structurally the only changed elements in
either editable SVG are `text` and `tspan` — no geometry, paint, or path moved:
node-label tspans shed `font-weight="400"`, `font-style="normal"` and their
redundant `font-size`; each `text` element's `fill` and `data-flexo-fill` swapped
order; and the three module titles gained the `tspan` they should always have
had. Connector captions are unchanged byte for byte. All three examples run
clean.

## R27. Five authoring gaps the Transformer figure found (round 9)

Panel b is not the only figure Flexo has to be able to write. Authoring the
Transformer ("Attention Is All You Need") — two towers, ten residual joins, a
cross-attention net between them — surfaced five gaps that had nothing to do with
paint and everything to do with what an author is *allowed to say*. Each one is
the same shape: the compiler knew the right answer and there was no way to write
it down.

- **`attention()` was the one component that could not be created first.** Its
  `q`, `k`, and `v` were required keywords, so an attention block could only be
  authored after all three of its sources existed. A Transformer decoder reads its
  keys and values from an encoder that is written *later* in the source, which made
  the whole pair of towers un-authorable in flow order: either the encoder moved
  above the decoder it feeds, or the decoder was built inside out. All three are
  optional now. They wire exactly as before when given; the q/k/v ports exist
  either way, so the missing legs are ordinary `connect(top, block.k)` calls once
  the source exists. Nothing else about the component changed.

- **A residual target had one arrival port and two arrivals.** `add-norm` offered
  `input`, so the sublayer output and the skip both landed on it — two arrowheads
  on one point, which the router draws as two runs a hair apart with a hook where
  it pulled each off its twin, and a `routing.track.separation` error per pair.
  Ten of them in the Transformer, which is why that figure reached for a plain
  `block()`: `add_norm()` had no advantage to offer. It does now. The grammar's
  table is `input`, `skip`, `output`, `branch` — the two wires a residual join sits
  on, named on the way in *and* on the way out, since the value leaving one block
  feeds the next sublayer and bypasses it too. All four are auto-sided, so a tower
  that reads upward gets them on the edges its ink uses with no port table.
  `add_norm(input=..., skip=...)` says it at creation,
  `connect(x, an, target_port="skip")` for a value authored later, and
  `residual()` now prefers a `residual` *or* `skip` port so a skip edge lands
  where the component meant it to. The gallery's hand-written `_add_norm` port
  table — which already called its skip port `skip` — is what named this.

- **Nothing could say which way round an obstacle a route should go.** The router
  prices bends, crossings, grazing and confinement, and between two corridors of
  similar length it takes the cheaper one — which is sometimes the one that wraps
  the far face of a module and slices back through it. `via=` is the missing word:
  a `Side` on `connect`, `residual`, `net`, and `merge`, `None` by default.
  It lands in three places, because a corridor preference is three separate
  decisions. **In the cost function** (`PathCosts.off_side`, 1.5 per point) it
  charges only for length spent *beyond the endpoints' own region on the side the
  hint refused* — never inside the region, which every route has to cross, and
  never on the hinted side. **In the net rail** it reads the side exactly as
  `rail=` does for the axis (west and east rail vertically) and then prefers the
  boundary edge on that side, letting the ordinary candidate search walk back
  inward to the nearest clear rail: a lean where `rail=` is a pin, which is why it
  may not be written beside `rail=` or `rail_at=`. **In the auto-side pass** it
  settles the *entry* side of an auto-sided target port, because ink arriving from
  the west arrives on a west port; the departure keeps its own vote, since a route
  may leave east and still be asked to stay west of what it crosses to. It is a
  request, and it borrows `rail_at`'s convention when it cannot be had:
  `routing.via.clamped` / `routing.net.via.clamped`, a warning naming the side
  actually achieved. `RoutedEdge` grew the `diagnostics` field `RoutedNet` already
  had, so an edge-level clamp reaches lint the same way.

- **An image's label painted over its own artwork.** `image` was the last
  motif-bearing kind still centring its label in the middle of its box, so
  "Positional Encoding" printed across the sine glyph it named. It joins
  `MOTIF_LABEL_KINDS` and reads the same `label_band_height` / `motif_area` pair
  R25 gave the inset: band on top, `motif_label_gap`, the drawing in what is left.
  Sizing follows — a labelled image is band + gap + artwork + padding, so an
  authored `height` shrinks the *drawing* and never the caption's line, and one
  authored extent still implies the other through the aspect ratio. An *unlabelled*
  image reserves nothing and its bounds stay exactly its artwork, which is the
  whole promise of the kind.

- **Both text bugs from round 8 are fixed.** A title was measured at its runs' own
  weights and drawn at `title_weight`; `TextMeasurer.measure(runs, weight=...)`
  now measures a run that named no weight at the weight it will *inherit*, which
  is the emission rule read backwards and shares one `DEFAULT_RUN_WEIGHT`
  constant with the emitter. The measurement had no consumer before — a group's
  intrinsic width came from its children alone — so `max(body.width,
  label.width)` makes the band real: a module can only grow, and only when its
  title is wider than its content. And a run beginning with a space lost it,
  because XML strips the leading whitespace of every `tspan` chunk, so
  `(TextRun("QK", weight=700), TextRun(" module"))` set as `QKmodule`. The fix is
  `xml:space="preserve"` on the run that owns the space, not on the text object:
  the document is indented, and preserving whitespace *around* the tspans would
  turn the indentation into ink. Verified through Inkscape rather than argued —
  the same three-variant probe shows `QKmodule`, `QKmodule`, `QK module`. Per-run
  absolute `x` was the alternative and was rejected: an `x` on a tspan starts a new
  text chunk, and `text-anchor="middle"` then centres every run on its own.

### Acceptance (round 9)

`uv run pytest` green (318, from 295: twenty-three added — unwired and partly
wired attention, the add-norm port table and its auto-siding, a skip edge that no
longer crowds its input, `residual()` preferring `skip`, `via` lowering on edges
and both net kinds, its rejections, its serialization round trip in both places
and its absence from a document that never asked for it, a detour routed both ways
round one wall, the entry side it settles, the edge clamp end to end and the net
clamp at the unit that decides it, a net rail leaning west and north, the image
label band, a height-only extent shrinking the drawing, an unlabelled image
reserving nothing, inherited weight in measurement and in wrapping, and a leading
space surviving into the SVG). `ruff check` clean.

`flexo gallery` exits 0 with zero lint errors and the one pre-existing
`routing.connector.crossing` warning, unchanged. **Both preview PNGs are
byte-identical to their pre-edit baselines**, and both editable SVGs diff to zero
lines: the title-weight fix moves nothing in either figure because every titled
module there is far wider than its own title, and every other change is reachable
only through authoring neither gallery figure uses. All three examples run clean.

The Transformer figure itself, unedited, still reports its ten
`routing.track.separation` errors, because it draws its Add & Norm boxes with
`block()` — which is the round's point, not a regression. Switching its one
helper to `tower.add_norm(...)` and adding `target_port="skip"` to its five skip
edges takes it to five errors, and every residual *arrival* comes out as two clean
separate arrows with no hooks. The five that remain are the departure half of the
same pattern — `an1.output` feeding both the sublayer and the skip, so two edges
leave one point — and taking those five to `source_port="branch"` leaves the
figure with **no diagnostics at all**. No `via=` hint is needed anywhere in it:
the cross-attention net already crosses to the decoder's near side.

## R28. An attention block that grows its own Q, K, V (round 10)

The round-9 Transformer drew its Q/K/V as `vector()` glyphs in a hand-authored
row under each attention block, and the authoring cost of that row was the
round's real finding. Three things were wrong with it, and all three are the same
thing:

**A magic gap reverse-engineered from a port table.** `row(gap=pt(22.7))` put the
three glyph centres under the component's q/k/v ports at 0.24/0.5/0.76 of a 120pt
block — 31.2pt of port spacing less an 8.5pt cell. It is correct arithmetic and
it is *unowned* arithmetic: nothing in the figure says it depends on
`COMPONENTS["attention"]`, so moving a port there would leave three glyphs
quietly off their arrows. It also only worked because the enclosing tower happens
to centre its children and the offsets happen to be symmetric about 0.5.

**Three authored edges per block.** `for vec, port in ((q, mha.q), ...)` — nine
lines across the figure saying the one thing the composite is *for*.

**Corridor contention that produced a warning.** The glyph-to-port drops left the
glyphs' east ports and hooked up into the block's south, so each drop had two
bends in the corridor that the cross-attention net also wanted; `cross-kv`
reported a `routing.connector.crossing` and several tried variants reported
separation errors instead.

`attention(..., vectors=...)` lowers all of it. The composite is the block over a
one-row grid whose reserved column widths come from `attachment_lane_tracks` and
the block's own port offsets: a pad, then a lane per port, then a pad, summing to
exactly the block's width. A glyph centred in its lane *is* centred under its
port, so every drop is a two-point vertical, and the corridor above the glyphs is
the ordinary edge-aware sibling gap — the three drops cross one boundary of the
composite's column, so `routing_gaps_for_group` reserves clearance, an arrival and
a lane per drop and arrives at the same 31pt the hand-authored version got by
accident.

Three findings came out of building it, none of which were visible from the
outside:

**A caption under a stack closes the only approach that stack has.** The glyph
feed arrives from underneath, and a route arriving at a port must run straight at
it for `arrival_clearance` — 14pt, the elbow plus two arrow lengths. A caption
3pt below the cells (the `vector_label_gap` a plain glyph uses) puts its own
clearance ring *on* the port: `routing.net.no-stem`, at any gap, because the
caption's ring is wider than an 8.5pt cell and no offset on that edge escapes it.
So the composite's caption gap is `arrival_clearance + caption_clearance`, and
that is the "corridor below the glyphs" the round asked for — a token sum, and
the reason these captions hang further from their stack than a `vector()` caption
does.

**An auto-sided feed port will choose the one side that must stay clear.** With
the feed declared south but `auto_side`, a cross-attention reading from an
encoder further *up* the page re-sides it to north — onto the drop's own edge,
two runs on one edge, `routing.track.separation`. `_separate_opposing` cannot
save it, because it only arbitrates between ports that are both auto-sided and
the drop is pinned. Both of a glyph's ports are therefore pinned: north is the
drop's and south is the feed's. The alternative reading — a west entry, which is
what the round-9 figure drew — is worse than it looks: a lane is only as wide as
the port spacing it was cut from, so two runs entering sideways thread the same
gap at the same height.

**The glyph order is the port order, and the port order is a design decision.**
Lanes are filled by ascending offset rather than in q/k/v order, so an authored
`ports=` moves the glyphs with the ports. That turned out to be the whole
cross-attention entry: with `q` leftmost, an encoder arriving from the left must
cross the decoder's own query feed to reach `k` and `v`, and the crossing is
*topological* — no `via`, `rail` or `rail_at` removes it. The paper draws V and K
on the left and Q on the right for exactly this reason. With that port table the
entry comes out as the figure in the paper: one horizontal from the encoder, a
junction under V, and two short verticals up into V and K, with no route through
a glyph gap and no hooks.

### Acceptance (round 10)

`uv run pytest` green (336, from 318: eighteen added — the composite's lowered
shape, its exact port-aligned x's, its two-point drops, its pinned port table,
handle resolution for `q`/`k`/`v` and `output`, wiring at creation, `vectors=True`
role defaults, single-preset and single-ramp broadcast, a case-insensitive
mapping, the partial/unknown/ill-typed rejections, the missing width, the block
anchor in a ports-aligned row, lanes following an authored port table, the caption
gap as a token sum, `vectors=None`/`False` lowering byte-for-byte to the plain
component, the lane-track arithmetic with its three rejections, and a
`caption`-role label painting `muted-ink` by role so it still rethemes). `ruff
check` clean.

`flexo gallery` exits 0 with zero lint errors and the one pre-existing
`routing.connector.crossing` warning, unchanged; both editable SVGs, both
portable SVGs and both preview PNGs are byte-identical to their pre-edit
baselines. (The PDFs differ, and differ between two consecutive runs of the
unmodified tool: Inkscape stamps a creation date.) `vectors=` is opt-in, and the
render path only changed for a node whose role is `caption`, which nothing else
in the gallery declares.

**The Transformer figure reports `ok: no diagnostics`** -- zero errors and zero
warnings, from three warnings before the round. All nine glyph-to-port drops are
two-point verticals; the self-attention triples come up into the glyph bottoms
from a rail halfway up from their embedding; and the cross-attention entry is the
figure in the paper: one horizontal from the encoder, a junction under V, and two
short verticals up into V and K, with no route through a glyph gap and no hooks.

Getting the last warning out took one authored port table, and it is worth
recording why, because the constraint is the router's rather than the figure's.
`shortest_orthogonal_path` minimizes crossings with *already-placed* runs
lexicographically ahead of bends and length, and nets are placed before edges. By
the time the encoder's feed-forward skip routes, `cross-kv`'s rail is lying across
the encoder's right margin at the one y it is allowed to occupy -- the decoder's
cross-attention glyphs are `arrival_clearance` above it and their captions
`caption_clearance` below, so the legal interval for that rail is a single point.
The skip has to cross that y somewhere, and everything from the blocks' left edge
to the right margin is the `ff` box at that height, so its choices are the right
margin (crossing the rail) or the left margin (crossing nothing yet placed -- and
then the 25pt `an1 -> ff` spine run, placed afterwards, has no lane of its own and
crosses *it*). An exhaustive sweep over `via`/`rail`/`rail_at`/`lane` on the three
nets and the five skips -- 180 combinations -- bottoms out at one warning, reached
several ways and never bettered.

What removes it is not a hint at all: the skip leaves on the wrong side. Its
`branch` port sits at 0.8 of the north edge, right of the spine, and the margin it
travels in is the left one, so it cuts the spine on the way across. `LEFT_BRANCH`
is `add_norm`'s own port table with `branch` moved to 0.2 -- the same wire, leaving
the side it was always going to travel on -- and the figure comes out clean. That
is `ports=` doing exactly what it is documented for ("the author's sides and
offsets are the design"), on the one block in the figure whose skip does not go
east. The router-side alternative, worth having eventually, would be to price a
crossing against the run it forces on whatever routes next, rather than counting
only the ink already on the page.

## R29. Captions beside the glyph, not under it (round 11)

Straight from the user reading the round-10 Transformer:

> The feed arrows into the Q/K/V glyphs bend around the "Q"/"K"/"V" captions
> beneath them. — The encoder-to-decoder connection turns down at a weird place;
> it should be an equal S shape rather than a one-sided L.

The first is the round-10 caption gap read back as a defect. That gap was the
right answer to the question it was asked -- a caption 3pt under an 8.5pt cell
puts its clearance ring on the port and there is no `routing.net.no-stem`-free
offset on that edge -- but the question was wrong. The corridor under a glyph is
the *only* approach that glyph has, and R28 spent 17pt of it on words. Every feed
then had to leave the corridor, go round the caption's ring and come back: nine
hooks in the figure, one per glyph, plus the decoder's `an3 -> q` feed, which had
a clear straight line to its port and drew a five-segment zigzag anyway.

**A caption beside the stack costs nothing.** A lane is wider than the stack in it
-- 31.2pt of port spacing around an 8.5pt cell for the standard offsets -- and the
11.35pt of surplus on each side is room no route may use either, because the lane
is exactly as wide as the separation its neighbours need. So the caption takes the
half-lane it stands in, less one `caption_clearance` of air against the cells, and
the glyph reserves that same `reserve + gap` on the stack's other side as padding
(`_SideCaption`). Two consequences, both load-bearing:

- **the stack does not move.** The glyph stays symmetric about its cells, so a
  box-centred child of the lane is a *stack*-centred child of the lane, and the
  port-fraction alignment R28 exists to guarantee survives a caption on one side
  of it. The glyph comes out exactly one lane wide, so the reserved grid tracks
  still sum to the block's width and nothing can overflow.
- **the caption box is measured, not the words.** A `label` node with an authored
  `width` is exactly that wide whatever it holds, so a wider caption overflows its
  box symmetrically rather than dragging the stack sideways. The words centre in
  the room they have; only the visible gap varies, by fractions of a point across
  Q, K and V.

One side for all three, not the outer side of each. Rendered both ways: mirrored
(Q left, V right) leaves the middle glyph's caption arbitrary and reads as an
accident, while three captions leaning the same way read as a convention. It is
also the only arrangement with no competition -- two captions meeting in one
inter-lane gap would sit a few points apart, each closer to the other glyph's
stack than to its own.

The narrow-lane fallback keeps R28's behaviour: below the stack, `arrival_clearance
+ caption_clearance` down, for a block pinned under about 56pt where the half-lane
cannot hold a caption at all. A standalone `vector()` is unchanged in every case --
it is wired from the side and has no approach from underneath to protect.

## R30. A Z crosses in the middle of its span (round 11)

The second half of the same critique. Two shapes were involved and they are the
same shape:

**The cross-attention trunk.** `_trunk_escapes` puts the junction where a trunk
meets a rail it leaves *along* at the hub escape, which is the earliest place it
can go. The encoder's output therefore drew a 5pt stub, a 50pt crossbar hard
against the box it had just left, and then 197pt of rail: a one-sided L. The
crossbar's own free run is from that escape to the first stem it passes, and its
middle is the reading of the shape a figure means -- the same default
`_preferred_rail` already takes one axis over, and a preference in the same way,
with the candidates walking outward from the midpoint until arm and crossbar both
clear every obstacle. The descent now lands in the gap between the towers with
88pt of arm above it and 114pt of rail below.

Two guards matter. The junction only moves when the crossbar is the trunk's alone
-- a spoke behind the hub escape rides on the same coordinate and dragging that
with the trunk would reshape a stem this has nothing to say about -- and only when
there is a crossbar at all: a trunk collinear with its rail (the panel-b skip
spine, hub and rail on one x) is left exactly where it was.

**Ordinary single-jog edges.** The same tie exists for any Z: every coordinate in
the span draws the same length with the same one elbow, so the visibility search
has no reason to prefer one and takes whichever it reached first. On clean geometry
the candidate grid happens to offer the midpoint and the search happens to find
it; put a third box near the run and the grid offers that box's edges and their
midpoints instead, and the crossbar lands 34pt from one endpoint and 145pt from
the other. `balance_jogs` (`routing/nudge.py`, run before the lane pass so the
lane pass has the last word) moves it to the midpoint of the free span: between
the two endpoints' clearance boundaries, less anything an obstacle standing across
the crossbar takes out of it. Testing the crossbar's extent covers the arms too --
each arm runs at one end of that extent, so a box in an arm's way reaches into it
by definition.

Three things are left alone, and the gallery is the argument for each:

- **a C.** Arms that double back over each other (`feedback.*` east then west,
  `recycle.node-features` west then east) share no span between the endpoints to
  be centred in, and the corridor they took was chosen against the whole figure.
  Balancing one would drag a margin route into the middle of the panel.
- **an aimed route.** A `lane=`, a waypoint or a `via=` is the author naming the
  corridor (`Run.hinted`). Lane nudging still applies to it: spacing two runs a
  lane apart is not a change of route.
- **a fan of parallel jogs.** `vertical-slice`'s three entries into `cryo.attention`
  all want the same midpoint; the first to reach for it gets it and the others are
  refused by the same defect test that guards lane nudging. Uniform 6pt spacing
  survives, which is what makes this change safe to apply figure-wide.

### Acceptance (round 11)

`uv run pytest` green (344, from 336: eight added, one rewritten -- captions beside
the stack at one `caption_clearance`, centred on the cells' port line; the glyph
exactly one lane wide and symmetric about its cells with no caption band; net
feeds arriving as two-point verticals; a Z centring on a span midpoint the
visibility grid does not offer; a waypoint keeping its corridor; a C left alone; a
hinted run left alone; the crossing trunk halving its run; and `rail_at`/`via`
standing the trunk default down). `ruff check` clean.

`flexo gallery` exits 0 with zero lint errors and the one pre-existing
`routing.connector.crossing` warning, unchanged. Both gallery figures and all four
other example figures are **byte-identical** to their pre-edit baselines: the two
new defaults are guarded well enough that nothing in the existing corpus moves.

**The Transformer figure still reports `ok: no diagnostics`,** and the two defects
are gone. All nine glyph feeds are two-point verticals -- including `an3 -> q`,
which lost a five-segment hook -- with the captions standing to the left of their
stacks on the cells' own centre line. The encoder-to-decoder connection leaves
`an2` east, runs 88pt, descends 77pt mid-gap between the towers, and hands 114pt
of rail to the junction under V and the two short verticals into V and K. The
canvas is 53pt shorter than the round-10 render (915.6 from 969.1), because the
caption bands came out of the towers and the glyph rows are now exactly as tall as
their cells.

## R31. A preset that ramps by default lies about its data (round 12)

`VectorPreset.order` defaulted to `"ramp"`, so the shortest way to write a vector
glyph -- one base colour and a topology -- produced a light-to-dark gradient. A
gradient is a claim: it says the cells are *ordered*, that cell 1 is less than
cell 2 is less than cell 3. That is true of a positional index or a sorted
similarity score and false of every activation a paper draws Q, K and V for. The
default was therefore the wrong way round: the common case had to be asked for by
name (`order="shuffled"`) and the rare case came for free.

The default is now `"shuffled"`. Nothing about the mechanism changes -- the
permutation is still drawn per column from `seed`, still rejects an identity draw,
still encodes byte-for-byte the same on every rebuild -- only which of the two an
author gets for free. `order="ramp"` is how the gradient is asked for now, and it
is still exactly the ramp: `shade_ramp`'s own output, monotone light-to-dark.

The blast radius is small by construction, because a preset is literal author
paint and both gallery figures colour their vectors with palette *ramp roles*
instead (`ramp-node`, `ramp-kv`, ...). Roles are untouched: a role still means the
palette's ramp, which is what makes `flexo retheme` work. Only figures that
authored a `VectorPreset` move, and in the corpus that is the Transformer (whose
Q/K/V triples now read as feature vectors, which is what the paper's own glyphs
depict) and `examples/attention_module.py`.

That example was rendering the ramp as its main figure and the shuffle as a named
variant. It is now the other way up: `attention-module` takes the default and
`attention-module-ramp` asks for `order="ramp"`, so the pair still demonstrates
both orders and the one shown first is the one an author will get.

## R32. A residual that changes hands from tower to tower (round 12)

`add-norm`'s `skip` and `branch` were auto-side eligible, so each one picked the
edge facing whatever it happened to be wired to. Per node that is the right
answer; per *figure* it is not. In the Transformer the decoder's three skips bowed
out to the east and the encoder's two were pushed west, and the encoder needed a
hand-written `LEFT_BRANCH` port table plus a `via="west"` to come out clean at
all. A reader who has learnt "the residual is the wire on the right" then has to
learn the encoder separately -- the figure carries two conventions for one
concept.

Both ports are now pinned to `Side.EAST`. They stay adaptive, so each still slides
along that edge to meet its counterpart, and the spine beside them (`input`,
`output`) still auto-sides, so a tower that reads upward still gets north and
south for free. What is gone is the per-node choice on the one relationship whose
whole value is being the same everywhere.

Sharing a side forced one further decision. Both ports sat at offset 0.8 on
opposite edges, where the collision could not happen; on one edge that is a single
point, and an arrival and a departure on a single point is the two-arrowheads
defect `_RESIDUAL_TARGET` exists to prevent -- it reported as
`routing.track.separation` for the overlapping jogs the moment the pin landed.
The pair now takes two lanes on the east edge, `skip` at 0.8 and `branch` at 0.2,
which is also the way the wire travels: a bypass arrives from *below* the block it
rejoins and leaves for the one *above*, so the low lane is the arrival and the
high lane the departure. It is the same 0.8/0.2 split the retired `LEFT_BRANCH`
table had already arrived at by hand.

The consequence an author has to plan for is room. A pinned bypass routes
*outside* the block it rejoins, so a content-hugging container leaves the corridor
nowhere to go and routing fails with `routing.no-path`; about 22pt of side padding
is enough, and the reference Transformer's towers already carry 34pt. `ports=`
still overrides the whole table, which is how the gallery's spine blocks keep
`skip` on the north for a rail that arrives from an authored lane, and how an
author who wants a left-handed figure gets one.

### Acceptance (round 12)

`uv run pytest` green (349, from 346: three added -- the shuffled default with
`order="ramp"` still yielding the monotone ramp, a mirrored pair of towers whose
bypasses both leave east with the arrival below the departure, and an explicit
port table still buying a left-handed residual -- and three rewritten to pin the
order they were assuming or to give a default residual its corridor). `ruff check`
clean.

`flexo gallery` exits 0 with zero lint errors and the one pre-existing
`routing.connector.crossing` warning, unchanged. Both gallery figures are
**byte-identical** to their pre-edit baselines in every SVG and PNG: they paint
vectors from ramp roles rather than presets, and they author `add-norm` ports
explicitly, so neither default reaches them.

**The Transformer figure still reports `ok: no diagnostics`** -- zero errors and
zero warnings -- with `LEFT_BRANCH` and the `via="west"` hint both deleted and
nothing put in their place. All five skips now bow east: each leaves its block's
east edge high, runs up the margin inside its own tower, and enters the next Add &
Norm's east edge low. The encoder reads as the decoder does. Nothing crosses the
central spine, and the encoder-to-decoder run into V and K is untouched -- the
skip corridors sit outboard of it. The Q, K, V glyphs in all three attention
blocks now read as feature vectors rather than gradients.

`examples/attention_module.py` renders `attention-module` (the default, shuffled)
and `attention-module-ramp` (`order="ramp"`), both `ok: no diagnostics`, at the
same 180.0mm x 77.4mm as before: the change is paint, not geometry.

## R33. Long edges that share a margin fight for it (round 13)

The see-more-alpha suite (`sketches/see-more/`, not for merging) is the first
figure whose semantics genuinely need long cross-band edges: a feature volume
and a token stream feeding two mid-stack sublayers, two logit streams leaving
those sublayers for a readout band below, and a recycle rail climbing back up.
Authored as edges, every margin scheme lost: five agents and one coordinator
proved by enumeration that with feeds and taps sharing one margin, some pair
must cross, and short of that ceiling the author still had to hand-build
nested spacer groups (`_lanes`) to give each run its own corridor. The shipped
figure works around the engine by moving values *by name* — glyphs redrawn
beside their consumers — which is good design language but must be a choice,
not a forced move.

Fix, part one — **corridors are the engine's to reserve**. Before fit, count
the long edges that must traverse each side margin (an edge is margin-bound
when its endpoints' groups do not share an ancestor row/column cell adjacent
along the route axis). Reserve that margin's width as `tracks × track pitch`
(pitch = clearance + stroke, the same arithmetic `nudge` uses), and have the
router assign tracks in nesting order — deeper arrival, outer track — the
provably-planar assignment wherever one exists. `lane=` hints stay as
overrides; a figure that authored no lanes gets the corridor arithmetic the
see-more suite wrote by hand.

## R34. A crossing the topology forces should be drawn, not warned about (round 13)

Where no planar assignment exists (the see-more feed/tap interleave), the
right answer is the one circuit diagrams settled on decades ago: the
later-routed edge hops the earlier one with a small bridge arc. Routed IR
records crossing points; emit paints the hop into the shaft path (`d` gains an
arc segment, still one editable object); lint reports a hopped crossing as
`info: routing.connector.hop` and reserves the `routing.connector.crossing`
warning for the un-hopped overlap of two shafts that genuinely obscures one.
Hops are opt-out (`style` knob), never opt-in: an author should get a legible
figure by default and remove hops only deliberately.

## R35. Three authoring conveniences the R2 design language earned (round 13)

The see-more user review (sketches/see-more/CRITIQUE.md, R2) settled a design
language the engine should carry natively rather than via idioms:

1. **`note=` on any component** — small muted type at the bottom edge of the
   body (dimension transitions: "384 → 768 → 384"), rendered inside the node's
   bounds like a motif so it neither blocks the south port nor sits on a
   downward stem (the caption-column workaround did both).
2. **`padding=` on `figure.module(...)`** — the one layout knob `module`
   swallows today; the R2 fleet needed asymmetric padding to pull a port up to
   its wall and had to rebuild the module as a raw `group` to get it.
3. **`operator()` factory** — a 14 pt circle-or-square bearing one glyph
   (`+`, `×`, `·`, `Σ`), four side ports, painted like a junction with ink.
   The 14 pt labelled-block idiom works but every figure re-authors it.

## R36. Superscripts an author can type (round 13)

The bundled face has no `ᵀ ∈ ⊕ ⊙`; today `softmax(QKᵀ)V` in a prose label is a
`font.glyph.missing` error and the only spelling is a hand-built `TextRun`
tuple. Normalization should translate Unicode super/subscript characters in
label strings (`ᵀ`, `₀`–`₉`, `ₖ`, …) into baseline-shifted runs automatically,
so the natural spelling of a formula measures, paints, and round-trips through
YAML without the author knowing `TextRun` exists.

## Acceptance (round 13)

`uv run pytest` green (349 baseline plus round-13 tests), `ruff check` clean.
`flexo gallery` and `examples/` figures byte-stable or improved (no new
diagnostics anywhere). The proof figure is `sketches/see-more/full_rails.py`:
the integration diagram with the mermaid's real long edges — volume → cryo,
tokens → sequence, both logit streams → IdentityFusion, and the layer loop —
authored with **zero** lane hints and **zero** hand-built spacer corridors,
compiling to `ok: no diagnostics` (hops rendered where topology forces them),
while the shipped `full.py` (values-by-name) still compiles byte-identically.

## Acceptance as landed (rounds 13-14)

Round 13 landed in four parts (corridor reservation, bridge hops, the three
authoring conveniences, typed super/subscripts) and one follow-up: the
acceptance figure showed the round-13 allocator planned only past-a-cell runs,
while the see-more edges thread a container's side margin to reach side ports
of nodes inside it. Round 14 extended the margin-bound definition to those
subtree traversals (one margin per edge, the deepest container threaded;
half-integer sentinels for runs that leave the group), taught the corridor
base to clear intruders standing in the margin, and left the allocator handing
`hops.py` cleanly separated tracks.

One amendment to the round-13 wording: `format()` has always printed info
lines, so a figure with hops does not literally say `ok: no diagnostics` —
the bar for the proof figure is zero errors, zero warnings, hops as
`info: routing.connector.hop`. `Build.ok` is unchanged and true.

Final state: `uv run pytest` **411 passed** (349 at open; +19 shifted runs,
+14 conveniences, +14 corridors, +9 hops, +6 traversal corridors, +9 from
test updates in flight), `ruff check` clean. Gallery and examples byte-stable
except `vertical-slice`, whose one pre-existing crossing warning is now a
drawn bridge arc and an info line — the SVG diff is a single `A 2.25 2.25`
arc segment in one shaft path. All nine `sketches/see-more` figures
byte-stable. The proof figure `sketches/see-more/full_rails.py` draws the
mermaid's real long edges with zero lane hints: the engine reserves a
four-track corridor on the layer's east margin (40pt, tracks one pitch
apart), nests the five runs shortest-reach-first, and bridges the nine
properly-overlapping pairs — the provable minimum, since a proper overlap
crosses on any track assignment. Zero warnings, zero errors, nine hop infos.
The values-by-name `full.py` still compiles byte-identically beside it: the
idiom is now a choice, which is what R33 asked for.
