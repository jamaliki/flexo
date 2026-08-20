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
