// Guides from beside the page: what a page's host has next to it -- a deck's slides overlaid on
// the one shown (flexo-talk's across.js) -- caught at as the page's own edges and middles are,
// its guides drawn in a colour of their own (`beside`), so a catch reads as "where it is on
// slide 29". The sums alone, for the shapes' editor (shapes.js) and a deck's objects
// (placing.js); read in Node as in the studio.
//
// - Dragged, sized or drawn: the edges and middles of what is beside (`boxes`, [left, top,
//   right, bottom] in the page's units) are guides as the page's are, with the same magnet and
//   ⌘ (snapping.js); a guide the page has itself is the page's, in its own colour. A box may say
//   the colour its guides are drawn in (`box.tint`: the tint its slide is overlaid in); the
//   box a guide was caught at, as given, says it.
// - Nudged by the arrows: a nudge that would pass one of those guides (or stop just short of
//   it) stops on it, so a few presses line an edge up with the slide before exactly, where a
//   point at a time would step over it; the next press goes on past.

// Each box's left, middle and right (top, middle, bottom), with the box each came from.
export function guidesOf(boxes = []) {
  const x = new Map(), y = new Map();
  for (const box of boxes) {
    if (!box || box.some((value) => !Number.isFinite(value))) continue;
    const [left, top, right, bottom] = box;
    for (const at of [left, (left + right) / 2, right]) if (!x.has(at)) x.set(at, box);
    for (const at of [top, (top + bottom) / 2, bottom]) if (!y.has(at)) y.set(at, box);
  }
  return { x, y };
}

// `targets` ({ xs, ys }, the page's own) with what is beside it caught at too: its values
// added, and those the page has not itself kept (`targets.beside`), for their guides to be told
// apart. `beside` is { boxes }, or nothing.
export function withBeside(targets, beside) {
  const found = guidesOf(beside?.boxes || []);
  if (!found.x.size && !found.y.size) return targets;
  const own = { x: new Set(targets.xs), y: new Set(targets.ys) };
  for (const at of found.x.keys()) if (!own.x.has(at)) targets.xs.push(at); else found.x.delete(at);
  for (const at of found.y.keys()) if (!own.y.has(at)) targets.ys.push(at); else found.y.delete(at);
  targets.beside = found;
  return targets;
}

// The box beside the page a guide at `at` (along `axis`, "x" or "y") was caught at, if that is
// what it was caught at -- not one of the page's own.
export const besideAt = (targets, axis, at) => targets?.beside?.[axis]?.get(at) || null;

// A nudge of `box` by `dx`, `dy` caught at what is beside: where one of its edges or its middle
// would pass a guide beside the page -- or come within `reach` of one -- it goes no further than
// that guide (the nearest passed, along each way). What it moves by, and the guides it then
// lies on ({ axis, at, box }).
const LINED = 0.05; // points: as near as a guide is to be lined up with it already

export function nudgeCaught(box, dx, dy, beside, reach = 0.5) {
  const found = beside?.x ? beside : guidesOf(beside?.boxes || []);
  const moved = { dx, dy, guides: [] };
  if (!box) return moved;
  const ways = [["x", dx, [box[0], (box[0] + box[2]) / 2, box[2]]], ["y", dy, [box[1], (box[1] + box[3]) / 2, box[3]]]];
  for (const [axis, by, mine] of ways) {
    if (!by) continue;
    let best = null;
    for (const at of found[axis].keys()) {
      for (const own of mine) {
        const gap = at - own;
        // Passed on the way (not where it starts -- lined up already, to a twentieth of a point,
        // it moves off), or nearly reached.
        const passed = Math.sign(gap) === Math.sign(by) && Math.abs(gap) > LINED && Math.abs(gap) <= Math.abs(by) + reach;
        if (passed && (!best || Math.abs(gap) < Math.abs(best))) best = gap;
      }
    }
    if (best !== null) moved[axis === "x" ? "dx" : "dy"] = best;
  }
  // The guides it lies on once moved.
  const now = [box[0] + moved.dx, box[1] + moved.dy, box[2] + moved.dx, box[3] + moved.dy];
  const lines = { x: [now[0], (now[0] + now[2]) / 2, now[2]], y: [now[1], (now[1] + now[3]) / 2, now[3]] };
  for (const axis of ["x", "y"]) {
    for (const [at, from] of found[axis]) {
      if (lines[axis].some((own) => Math.abs(own - at) < LINED)) moved.guides.push({ axis, at, box: from });
    }
  }
  return moved;
}
