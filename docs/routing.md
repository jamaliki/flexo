# How connectors are routed

Routing follows the routers that draw connectors well (libavoid, ELK, yFiles).
It never fails for lack of a path: if a figure is too tight for its
connectors, it is laid out again with the room they need. A hint that cannot
be honoured is reported as a warning, not an error. (A `lane=` or waypoint
that names nothing in the figure is still an error.)

1. **Pins.** Every end of every connection gets an attachment point (a pin)
   on one side of its component. The side is chosen by these rules, in order:
   - An authored port side, `depart=`/`arrive=`, or `via=` is kept.
   - Otherwise the side faces the other end. When one gap between the two
     boxes is at least twice the other, the wider gap decides; when they are
     comparable, the layout decides -- vertical if both ends share a column,
     horizontal if they share a row.
   - The branches of one net attach on one common side: branches spread left
     to right are entered from above or below, branches stacked top to bottom
     from the left or right.
   - A side whose approach another component blocks is exchanged for a facing
     side with a clear approach, or failing that any clear side.
   - A side does not take one value in and send a different one out. The end
     that is off its port's usual side moves to another side that faces its
     other end. A departure with no such side leaves by its port's usual side
     if the same value already leaves there, so a feedback loop taps the
     output line. Arrows in both directions between the same two boxes stay
     side by side.
   - A circle, diamond, or operator takes one line per corner while corners
     last, arrivals first.

   Ends then share a pin or get their own. Edges leaving one port share its
   pin and are drawn as a tree, unless their targets stand side by side
   within the component's span, when each gets its own arrow. Values arriving
   at one port get a pin each (the `arrivals` convention), and a captioned
   edge always has pins of its own. Pins on one side are ordered by where
   their lines go; ties put the farthest counterpart first, so skip
   connections nest. Two pins that face each other across a gap move to one
   coordinate, so the arrow between them is straight; the pin of a net's
   shared end stays at the middle of its side.
2. **Search.** Each connection is routed on its own with a bend-aware A* search
   over a grid of the figure's lines. Components, their clearance rings,
   group titles, and containers that the connection does not belong to are
   *priced*, not forbidden, so a route always exists. Connections that share a
   pin are routed together as one tree grown from that pin. An arrow normally
   ends on a straight run of `arrival_clearance`; it may end on as little as
   its head plus one elbow when the longer run would force a jog.
3. **Rip up and reroute.** Every connection is routed again with the others
   in view. Crossing another connector is expensive; sharing its corridor is
   cheap, because the next step spaces shared corridors apart.
4. **Separate.** Lines that share a corridor are ordered so that they cross
   least, and spaced one lane apart by a constraint solver (VPSC). The
   crossbar of a Z and the trunk of a tree sit in the middle of the room they
   have.
5. **Uncross.** If lines still cross, or run closer than a lane, neighbouring
   pins on the sides those lines attach to are swapped one pair at a time;
   then each end of such a line whose side is a default is tried on the two
   sides across from its own. The figure is rerouted and separated after each
   trial, and a trial is kept when fewer pairs of lines cross or crowd. This is
   what sends a loop back to an earlier step over the top instead of through
   everything between.
6. **Room.** A connector or caption that had to leave the container it belongs
   to, or a run pressed between a box and the container's edge, asks that
   container for more room, and the figure is laid out again (up to three
   rounds). A crossing whose route could instead run along the container's top
   or bottom edge is offered a lane there, kept only if it removes the crossing.

## Nets and rails

Shared values and true combinations are authored explicitly rather than inferred
from coincident lines:

```python
import flexo

with flexo.Figure("nets", width="double-column") as figure:
    with figure.module("m", label="Readout", layout="column") as module:
        trunk = module.add_norm("addln", label="Add LN")
        with module.row("heads", gap="18pt", padding=0, role="layout") as heads:
            first = heads.mlp("first", label="MLP")
            second = heads.mlp("second", label="MLP")
            third = heads.mlp("third", label="MLP")
        average = module.block("average", label="Average")
    figure.net(src=trunk, sinks=[first, second, third])
    figure.merge(sinks=[first, second, third], dst=average, rail="east", label="Average")
```

`net` draws one value going to several places as a tree grown from the source:
a trunk, and branches off it as plain Ts. `merge` draws several values arriving
at one place as a tree grown from the destination; in a merge of two, the one
that joins the other's line ends in an arrowhead pointing into it, and a merge
of three or more is a bus with its one arrow into the destination. Edges that
leave the same port are drawn the same way -- three `connect` calls from one
output are one tree. (Edges that *arrive* at one port stay separate arrows by
default.) Every bend inside a piece of the tree turns on the elbow fillet (6 pt
in `paper`, square in `tikz`, `swiss`, `archive` and `bauhaus`);
set `elbow_radius=pt(0)` on a derived `LayoutStyle` for a sharp
technical-drawing treatment anywhere.

`net` and `merge` are figure-level calls, and also methods on every group builder:
`root.net(...)` works wherever `root.connect(...)` does, with the same arguments
and the same result, so authoring a net never means reaching back out of the block
you are writing.

An unhinted rail sits **in the middle of the free corridor** its stems leave it —
the gap between the hub component's edge and the nearest edge of what it feeds.
Trunk and stems each get half the run, so the rail reads as a corridor the figure
meant to leave rather than as a line drawn against the box its branches come out
of. The exception is a net with a caption and no `rail_at`: the caption is
written above the run, so halving the run would draw the rail through the words.
Its joint goes to the far end of the corridor instead, and the whole run is the
caption's.

A trunk that leaves **along** the axis its rail runs on — an encoder's output
crossing the page into a decoder's cross-attention — draws a Z: a stretch along
the port axis, a crossbar over to the rail, and the rail carrying on the same
way. The crossbar sits in the middle of the free span between the hub's escape
and the first thing in its way, so the two arms are arms of one step rather than
a stub against the box the trunk just left. `rail`, `rail_at` and `via` place the
net themselves, and switch the default off.

Two hints place and mark that joint:

```python
import flexo

with flexo.Figure("joint", width="double-column") as figure:
    with figure.module("m", label="Attention") as module:
        q = module.vector("q", label="Q", ramp="ramp-q")
        kv = module.vector("kv", label="K, V", ramp="ramp-kv", columns=2)
        attended = module.vector("attended", ramp="ramp-attended")
        module.merge(sinks=[q, kv], dst=attended, rail_at=0.55, joint="arrow")
```

`rail_at=0.55` asks for the joint partway along the run -- the fraction is
measured from the source port toward the destination port. It is a request:
where clearances forbid it the router takes the nearest position that fits and
reports `routing.net.rail-at.clamped`, naming the fraction it got, as a lint
warning rather than silently obeying or failing. `joint="arrow"` puts an
arrowhead on every joining branch, even in a bus; `joint="dot"` marks the joints
with dots instead, whatever the figure's conventions say.

### Single-jog routes cross in the middle

Two ports that do not line up give a **Z**: a run out of the source, one crossbar,
and a run into the target the same way. Any coordinate in the span between the two
ports' clearance boundaries draws that shape with the same length and the same one
elbow, so the search has no reason to prefer one — and picking whichever it reached
first leaves the crossbar against an endpoint, which reads as an L with a kink in
it rather than as a step across. The default is the **midpoint of the free span**:
the stretch between those two clearance boundaries, less anything an obstacle
standing across the crossbar takes out of it.

A **C** — a route whose two arms double back over each other, wrapping a module or
running up a margin — keeps its corridor. Its arms share no span to be centred in,
and the corridor it took was chosen against the whole figure rather than between
two ports. So does any route the author aimed with `lane=` or a waypoint, and any
pair of parallel jogs a lane apart: balancing never overrides a hint, and
never pulls two crossings onto one coordinate.

### `via=`: which side a route should keep to

A route that has to leave the straight line between its endpoints has two ways
round whatever stands in the way, and the router cannot see which one *reads*. A
connector that wraps the far face of a tower comes back through it; the same
connector taken round the near side stays in the margin. `via=` is one word for
which margin:

```python
root.connect(source, target, via="west")
figure.net(src=encoder_top, sinks=[cross.k, cross.v], via="west")
figure.merge(sinks=[first, second], dst=average, via="south")
```

It takes a `Side` or a side name on `connect`, `residual`, `net`, and `merge`, and
defaults to no hint at all. Three things follow from it:

- **the route pays for the corridor it refused.** Length spent beyond the span
  of its pins, on the side opposite the hint, costs `OFF_SIDE_COST` per point
  (`flexo.routing.router`) -- enough that the near corridor wins wherever it
  exists, little enough that the far one is still available when it is the only
  one. Inside the span nothing is priced: every route has to cross it.
- **a net leans the same way.** `rail=` and `via=` on a net both price the far
  side. `rail=` also moves the trunk to the hinted edge of its corridor; a `via`
  trunk stays centred in the corridor it gets. The two may not be combined, and
  `via=` may not be combined with `rail_at=`.
- **the ends face the hint.** Ink that comes round the west arrives from the
  west, so an auto-sided target port takes that side (an authored `PortSpec` or a
  `depart`/`arrive` hint still wins, for edges and nets alike). The source takes it too when the hint is
  across the line of travel: an edge to the box above, kept west, leaves west and
  comes back in a C -- the drawing of a feedback loop. When the hint lies along
  the line of travel, the source keeps its own side, because leaving toward the
  hint would mean leaving backwards.

Like `rail_at`, it is a request. Where the geometry leaves no corridor on that
side the router takes the nearest one and reports it —
`routing.via.clamped` for an edge, naming the side it actually achieved, rather
than failing or silently obeying. (A net's `via` is not checked this way.)

A net's caption -- a formula such as `softmax(QKᵀ)V` -- sits above the
horizontal run its arrow draws, `caption_clearance` above the run's ink measured
from the bottom of the caption's own descender box (a subscript makes that box
deeper than the font's descender). A riser out of the middle of the run cuts it
in two, and the caption takes the wider stretch that is left. An edge's caption
is placed as described in [Captions on connectors](../README.md#captions-on-connectors).

Attention then reads as a formula rather than as a matrix: the merge carries its
caption in styled runs (`TextRun("T", baseline_shift="super")`) and Flexo anchors
it above the horizontal run the arrow draws.
