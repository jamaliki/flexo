// Shapes lined up and spaced, as Inkscape's Align and Distribute does it: the sums alone, for
// the shapes' editor (shapes.js, by way of aligntools.js) on a slide and over a figure alike.
//
// Each shape is its box as it is drawn -- [left, top, right, bottom], turned as it is -- and an
// `id` its caller knows it by (its place in the page's list), with `locked` if it is locked: a
// locked shape is never moved, but may be what the others are lined up with. What comes back is
// how far each moves ({ id, dx, dy }), for the caller to move them by in one step.
//
// - Align: a side or a middle of each lined up with the same of what they are aligned to --
//   or, beside it, one's edge against the other side of it (a right edge to its left edge).
//   They are aligned to (`to`) the selection's bounds, the first or last chosen, the biggest or
//   the smallest of them, or the page; one shape alone, to the page. Moved as a group, they
//   go together, kept as they are among themselves. The one aligned to stays where it is.
// - Distribute: three or more spaced evenly -- the gaps between them, or their left edges,
//   middles or right edges (top edges, middles or bottom edges down) -- the outermost staying.
// - A set gap: each so far from the one before it, across or down, the first staying.
// - A grid: rows and columns, each column as wide as its widest, each row as tall as its
//   tallest, a gap between, each shape set in its cell as asked; in the order they read.
// - Equal spacing while one is dragged: where it sits as far from its neighbours as they are
//   from theirs, or as two others in its row or column are apart (`spacing`); and while one is
//   sized or drawn, where the edge that moves is as far from its neighbour (`sizeCatch`).
//
// What the person last chose -- what to align to, whether to move them as a group, the gap --
// is one setting for the person, changed at any time, shapes chosen or not: kept in this
// browser (localStorage, read with care), as snapping.js keeps snapping, and turned in another
// tab of it, turned here too; in the Mac app, whose windows each have their own storage, the
// app keeps it for them all and tells the others (aligntools.js's aligningInApp). No page is
// needed: it is read in Node as it is in the studio.

const KEYS = { to: "flexo-studio-align-to", group: "flexo-studio-align-group", gap: "flexo-studio-align-gap" };

// What they may be aligned to, as the inspector offers it.
export const RELATIVE = ["selection", "first", "last", "biggest", "smallest", "page"];
// What each is called: in the inspector's choice, and after "to the" in a change's name.
export const RELATIVE_NAMES = { selection: "Selection", first: "First Chosen", last: "Last Chosen", biggest: "Biggest", smallest: "Smallest", page: "Page" };
export const GAP = 20; // the set gap, until one is set (in the page's units)

const read = (key) => { try { return globalThis.localStorage?.getItem?.(key) ?? null; } catch { return null; } };
const write = (key, value) => { try { globalThis.localStorage?.setItem?.(key, value); } catch { /* this window's alone */ } };
const keptTo = () => { const value = read(KEYS.to); return RELATIVE.includes(value) ? value : "selection"; };
const keptGroup = () => read(KEYS.group) === "on";
const keptGap = () => { const said = read(KEYS.gap), value = said === null || said === "" ? NaN : Number(said); return Number.isFinite(value) ? value : GAP; };

let to = keptTo();
let together = keptGroup();
let gap = keptGap();
const heard = new Set();
const tell = (how) => { for (const listener of [...heard]) { try { listener({ to, group: together, gap }, how); } catch (error) { console.error(error); } } };

// What they are aligned to now, whether they move as a group, and the gap set.
export const alignTo = () => to;
export const asGroup = () => together;
export const gapSet = () => gap;
export const aligning = () => ({ to, group: together, gap });

// Each set: `how` it was -- "here", "app" (the Mac app, from another window: aligntools.js's
// aligningInApp), or "stored" (another tab of this browser, already kept).
export function setAlignTo(value, how = "here") {
  if (!RELATIVE.includes(value) || value === to) return to;
  to = value;
  if (how !== "stored") write(KEYS.to, value);
  tell(how);
  return to;
}
export function setAsGroup(value, how = "here") {
  const now = Boolean(value);
  if (now === together) return together;
  together = now;
  if (how !== "stored") write(KEYS.group, now ? "on" : "off");
  tell(how);
  return together;
}
export function setGap(value, how = "here") {
  const now = Number(value);
  if (!Number.isFinite(now) || now === gap) return gap;
  gap = now;
  if (how !== "stored") write(KEYS.gap, String(now));
  tell(how);
  return gap;
}
// All three at once (`said`: { to, group, gap }, what is missing or not one of them left as
// it is), as the Mac app keeps them for every window: `how` "app" (another window's, kept here
// too) or "stored". Told once, and only if one changed.
export function setAligning(said = {}, how = "app") {
  const was = [to, together, gap];
  if (RELATIVE.includes(said?.to)) to = said.to;
  if (typeof said?.group === "boolean") together = said.group;
  const size = said?.gap === null || said?.gap === undefined || said?.gap === "" ? NaN : Number(said.gap);
  if (Number.isFinite(size)) gap = size;
  if (was[0] === to && was[1] === together && was[2] === gap) return aligning();
  if (how !== "stored") { write(KEYS.to, to); write(KEYS.group, together ? "on" : "off"); write(KEYS.gap, String(gap)); }
  tell(how);
  return aligning();
}
// `listener({ to, group, gap }, how)` each time one changes; what it returns stops that.
export function onAligning(listener) {
  heard.add(listener);
  return () => heard.delete(listener);
}
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("storage", (event) => {
    if (event.key !== null && !Object.values(KEYS).includes(event.key)) return;
    const [was, wasGroup, wasGap] = [to, together, gap];
    to = keptTo(); together = keptGroup(); gap = keptGap();
    if (was !== to || wasGroup !== together || wasGap !== gap) tell("stored");
  });
}

// -- boxes --

const usable = (box) => Array.isArray(box) && box.length === 4 && box.every(Number.isFinite);
export function union(boxes) {
  const all = boxes.filter(usable);
  if (!all.length) return null;
  return [Math.min(...all.map((b) => b[0])), Math.min(...all.map((b) => b[1])), Math.max(...all.map((b) => b[2])), Math.max(...all.map((b) => b[3]))];
}
const area = (box) => Math.max(0, box[2] - box[0]) * Math.max(0, box[3] - box[1]);
// A box's start, middle or end along an axis (0 across, 1 down).
const place = (box, axis, which) => (which === "middle" ? (box[axis] + box[axis + 2]) / 2 : which === "end" ? box[axis + 2] : box[axis]);

// What they are aligned to: its box, and the shape it is (`id`, or null: the selection's
// bounds, the page). One alone is aligned to the page.
export function anchorOf(items, relative, page) {
  const shapes = items.filter((item) => usable(item.box));
  if (shapes.length < 2 || relative === "page") return { box: page, id: null, page: true };
  if (relative === "first") return { box: shapes[0].box, id: shapes[0].id };
  if (relative === "last") return { box: shapes.at(-1).box, id: shapes.at(-1).id };
  if (relative === "biggest" || relative === "smallest") {
    // (By the room each takes; of two alike, the first chosen.)
    let best = shapes[0];
    for (const item of shapes) {
      if (relative === "biggest" ? area(item.box) > area(best.box) + 1e-9 : area(item.box) < area(best.box) - 1e-9) best = item;
    }
    return { box: best.box, id: best.id };
  }
  return { box: union(shapes.map((item) => item.box)), id: null };
}

// Each side: the axis, which of each shape's is put where, and where on what it is aligned to.
export const SIDES = {
  left: { axis: 0, mine: "start", theirs: "start" },
  centre: { axis: 0, mine: "middle", theirs: "middle" },
  right: { axis: 0, mine: "end", theirs: "end" },
  top: { axis: 1, mine: "start", theirs: "start" },
  middle: { axis: 1, mine: "middle", theirs: "middle" },
  bottom: { axis: 1, mine: "end", theirs: "end" },
  // Beside it: a right edge against its left edge, and so on.
  "left-of": { axis: 0, mine: "end", theirs: "start" },
  "right-of": { axis: 0, mine: "start", theirs: "end" },
  above: { axis: 1, mine: "end", theirs: "start" },
  below: { axis: 1, mine: "start", theirs: "end" },
};

// Those chosen (`items`, in the order chosen) aligned at `side` to `relative` (`page` the
// page's box): how far each moves, and what they were aligned to. As a group (`group`), the
// bounds of those that move are put there, each moved as far.
export function alignMoves(items, side, { relative = "selection", group = false, page = null } = {}) {
  const rule = SIDES[side];
  const shapes = items.filter((item) => usable(item.box));
  if (!rule || !shapes.length) return { moves: [], anchor: null };
  const anchor = anchorOf(shapes, relative, page);
  if (!usable(anchor.box)) return { moves: [], anchor };
  const movers = shapes.filter((item) => !item.locked && !(anchor.id !== null && item.id === anchor.id));
  const whole = group && movers.length > 1 ? union(movers.map((item) => item.box)) : null;
  const target = place(anchor.box, rule.axis, rule.theirs);
  const moves = movers.map((item) => {
    const by = target - place(whole || item.box, rule.axis, rule.mine);
    return { id: item.id, dx: rule.axis === 0 ? by : 0, dy: rule.axis === 1 ? by : 0 };
  });
  return { moves, anchor };
}

// The ways three or more are spaced evenly: the gaps between them (across, down), or one of
// their edges or middles. Locked shapes stay, and are not counted. Those `fixed` -- what the page
// lays out, chosen with the shapes (a slide's objects, a figure's parts: mixed.js) -- stay where
// they are but are counted: the shapes are spread among them, the gaps between all of them as
// even as the ones that stay allow -- each run of those that move spread evenly between the two
// that stay either side of it, the first and the last staying too. Two objects and a shape
// between them are three: the shape is put midway.
export const SPREADS = {
  across: { axis: 0, gaps: true },
  down: { axis: 1, gaps: true },
  lefts: { axis: 0, which: "start" },
  centres: { axis: 0, which: "middle" },
  rights: { axis: 0, which: "end" },
  tops: { axis: 1, which: "start" },
  middles: { axis: 1, which: "middle" },
  bottoms: { axis: 1, which: "end" },
};
// Those that take part in a spread: not locked (but those fixed, which are counted).
const members = (items) => items.filter((item) => usable(item.box) && (item.fixed || !item.locked));
// Whether they may be spread: three or more taking part, one of them free to move.
export const distributable = (items) => { const all = members(items); return all.length >= 3 && all.some((item) => !item.fixed); };
export function distributeMoves(items, how) {
  const rule = SPREADS[how];
  if (!rule || !distributable(items)) return [];
  const all = members(items);
  const { axis } = rule;
  const along = (item, which) => place(item.box, axis, which);
  const move = (item, by) => ({ id: item.id, dx: axis === 0 ? by : 0, dy: axis === 1 ? by : 0 });
  const sorted = [...all].sort(rule.gaps ? (a, b) => along(a, "start") - along(b, "start") : (a, b) => along(a, rule.which) - along(b, rule.which));
  // Those that stay: the first, the last, and each fixed one; each run between two spread.
  const stays = sorted.flatMap((item, n) => (n === 0 || n === sorted.length - 1 || item.fixed ? [n] : []));
  const out = [];
  for (let k = 1; k < stays.length; k++) {
    const from = stays[k - 1], to = stays[k], run = sorted.slice(from + 1, to);
    if (!run.length) continue;
    if (rule.gaps) {
      // The gaps between them made equal, from the end of the one before to the start of the one after.
      const start = along(sorted[from], "end"), end = along(sorted[to], "start");
      const sizes = run.map((item) => along(item, "end") - along(item, "start"));
      const between = (end - start - sizes.reduce((sum, size) => sum + size, 0)) / (run.length + 1);
      let at = start + between;
      run.forEach((item, n) => { out.push(move(item, at - along(item, "start"))); at += sizes[n] + between; });
    } else {
      const first = along(sorted[from], rule.which), step = (along(sorted[to], rule.which) - first) / (run.length + 1);
      run.forEach((item, n) => out.push(move(item, first + (n + 1) * step - along(item, rule.which))));
    }
  }
  // (Those that stay and are free to move are said too, as not moving: "Already in place".)
  for (const n of stays) if (!sorted[n].fixed) out.push(move(sorted[n], 0));
  return out;
}

// Each so far (`size`, in the page's units) from the one before it, across or down: the first
// (the leftmost, or the topmost) stays, the rest follow in the order they are in.
export function spacedMoves(items, way, size) {
  const axis = way === "down" ? 1 : 0;
  const shapes = items.filter((item) => usable(item.box) && !item.locked);
  if (shapes.length < 2 || !Number.isFinite(size)) return [];
  const sorted = [...shapes].sort((a, b) => a.box[axis] - b.box[axis] || a.box[axis + 2] - b.box[axis + 2]);
  let edge = sorted[0].box[axis + 2];
  return sorted.map((item, n) => {
    const by = n ? edge + size - item.box[axis] : 0;
    edge = item.box[axis + 2] + by;
    return { id: item.id, dx: axis === 0 ? by : 0, dy: axis === 1 ? by : 0 };
  });
}

// In the order they read: in lines, top to bottom (a shape in the line above it while its
// middle is within that line's height, as far down as its shapes reach), each line left to
// right.
export function readingOrder(items) {
  const middle = (item) => (item.box[1] + item.box[3]) / 2;
  const sorted = [...items].sort((a, b) => middle(a) - middle(b) || a.box[0] - b.box[0]);
  const lines = [];
  for (const item of sorted) {
    const line = lines.at(-1);
    if (line && middle(item) <= line.bottom) { line.items.push(item); line.bottom = Math.max(line.bottom, item.box[3]); }
    else lines.push({ bottom: item.box[3], items: [item] });
  }
  return lines.flatMap((line) => line.items.sort((a, b) => a.box[0] - b.box[0] || a.box[1] - b.box[1]));
}

// How many rows `columns` makes of `count` shapes, and how many columns `rows` does.
export const rowsFor = (count, columns) => Math.max(1, Math.ceil(count / Math.max(1, Math.round(columns) || 1)));
export const columnsFor = (count, rows) => Math.max(1, Math.ceil(count / Math.max(1, Math.round(rows) || 1)));

// Those chosen in a grid of `columns` (as many rows as that takes; at least `rows`), from where
// the first of them is, `gap` apart across and `gapDown` down; each set in its cell at `across`
// ("left", "centre", "right") and `down` ("top", "middle", "bottom"). How far each moves, and
// the grid made.
export function gridMoves(items, { rows = 0, columns = 0, gap: across = 0, gapDown = across, align = "centre", valign = "middle" } = {}) {
  const shapes = items.filter((item) => usable(item.box) && !item.locked);
  if (!shapes.length) return { moves: [], rows: 0, columns: 0 };
  const count = shapes.length;
  const cols = Math.max(1, Math.min(count, Math.round(columns) || columnsFor(count, rows || Math.ceil(Math.sqrt(count)))));
  const lines = rowsFor(count, cols);
  const ordered = readingOrder(shapes);
  const widths = new Array(cols).fill(0), heights = new Array(lines).fill(0);
  ordered.forEach((item, n) => {
    const row = Math.floor(n / cols), column = n % cols;
    widths[column] = Math.max(widths[column], item.box[2] - item.box[0]);
    heights[row] = Math.max(heights[row], item.box[3] - item.box[1]);
  });
  const whole = union(ordered.map((item) => item.box));
  const lefts = [], tops = [];
  widths.reduce((at, width, n) => { lefts[n] = at; return at + width + across; }, whole[0]);
  heights.reduce((at, height, n) => { tops[n] = at; return at + height + gapDown; }, whole[1]);
  const put = (start, room, size, how) => (how === "start" ? start : how === "end" ? start + room - size : start + (room - size) / 2);
  const ways = { left: "start", centre: "middle", right: "end", top: "start", middle: "middle", bottom: "end" };
  const moves = ordered.map((item, n) => {
    const row = Math.floor(n / cols), column = n % cols;
    const width = item.box[2] - item.box[0], height = item.box[3] - item.box[1];
    return { id: item.id, dx: put(lefts[column], widths[column], width, ways[align] || "middle") - item.box[0],
      dy: put(tops[row], heights[row], height, ways[valign] || "middle") - item.box[1] };
  });
  return { moves, rows: lines, columns: cols };
}

// -- equal spacing while one is dragged --

// What a drag can catch at, made once as it starts from the boxes of what does not move
// (`boxes`, [left, top, right, bottom]): those boxes, and each one's nearest neighbour after
// it across (and down) among those it overlaps the other way -- the gaps the page already has.
// `caught(box, reach)` is then, for the box dragged where it is now, the nearest place within
// `reach` (each way) where it sits at a spacing its row (or column) has: as far from the one
// before it as from the one after, or as far from either as two neighbours there are apart.
// Each move looks at every box once, never at every two of them.
export function spacing(boxes) {
  const list = boxes.filter(usable);
  const pairs = [neighbours(list, 0), neighbours(list, 1)];
  return {
    boxes: list,
    pairs,
    caught(box, reach, ways = {}) {
      const near = narrowed(reach);
      return { x: ways.x === false ? null : nearest(list, pairs[0], 0, box, near), y: ways.y === false ? null : nearest(list, pairs[1], 1, box, near) };
    },
    // While one is sized, or drawn: its edge on `side` ("start" or "end") along `axis` (0
    // across, 1 down), the other staying, caught within `reach` where the gap to its neighbour
    // that way is one its row (or column) has -- as wide as two others there are apart, or as
    // its own gap the other way. As `caught` says it (`shift`: how far that edge moves).
    edge(box, axis, side, reach) {
      return usable(box) ? nearestEdge(list, pairs[axis], axis, box, side, narrowed(reach)) : null;
    },
    // The gaps to show for a catch (`found`, one way), the box dragged now `box`: its own, and
    // every one of its row's (or column's) as wide.
    marks(found, box, slack = 0.05) {
      return found ? marksOf(list, pairs[found.axis], found, box, slack) : [];
    },
  };
}

// How near an equal spacing catches: two thirds of a guide's reach. And of a row's gaps, only its
// neighbours' and the nearest few (`FEW`) of the rest, none narrower than that reach (too narrow
// to see), two near alike as one -- a row of many gaps (a drawing's pieces, made editable) caught
// it at nearly every step else, handing it on from one place to the next a pixel away.
const narrowed = (reach) => (reach * 2) / 3;
const FEW = 2;
// The gaps one dragged (or sized) at `box` may be as wide as: its neighbours' to theirs (the
// one before its neighbour before it, the one after its neighbour after it), then the nearest
// few of the rest of its row's.
function gapsNear(list, pairs, row, axis, box, before, after, reach) {
  const middle = (box[axis] + box[axis + 2]) / 2, chained = [], rest = [];
  for (const pair of pairs) {
    if (pair.size < reach) continue;
    if (pair.b === before || pair.a === after) chained.push(pair.size);
    else if (row[pair.a] && row[pair.b]) rest.push({ size: pair.size, far: Math.abs((list[pair.a][axis + 2] + list[pair.b][axis]) / 2 - middle) });
  }
  if (rest.length > FEW) rest.sort((a, b) => a.far - b.far);
  // (Two near alike, the first: places a pixel apart would hand it on from one to the next.)
  const out = [];
  for (const size of [...chained, ...rest.slice(0, FEW).map((pair) => pair.size)]) if (!out.some((kept) => Math.abs(kept - size) < reach / 2)) out.push(size);
  return out;
}

// Whether two boxes overlap the other way from `axis` (are in one row, for across).
const level = (a, b, axis) => { const o = 1 - axis; return a[o] < b[o + 2] && a[o + 2] > b[o]; };

// Each box's nearest neighbour after it along `axis`, of those it overlaps the other way: the
// gaps between them ({ a, b, size }), each box's to the next.
function neighbours(list, axis) {
  const order = list.map((_, n) => n).sort((m, n) => list[m][axis] - list[n][axis]);
  const starts = order.map((n) => list[n][axis]);
  const out = [];
  for (let a = 0; a < list.length; a++) {
    const end = list[a][axis + 2];
    // (The first that starts at or after its end, by halving; then on to the first level with it.)
    let low = 0, high = order.length;
    while (low < high) { const mid = (low + high) >> 1; if (starts[mid] < end - 1e-9) low = mid + 1; else high = mid; }
    for (let k = low; k < order.length; k++) {
      const b = order[k];
      if (b === a || !level(list[a], list[b], axis)) continue;
      out.push({ a, b, size: list[b][axis] - end });
      break;
    }
  }
  return out;
}

// The nearest place along `axis` within `reach` of `box`'s where it is evenly spaced, if any:
// how far it moves (`shift`), the spacing (`size`), and its neighbours either side.
// Of those in `box`'s row (or column, down), level with it, its nearest neighbour before it and
// after it along `axis` (-1: none), and which are in the row (`row[n]`). One look at each.
function beside(list, axis, box, reach) {
  const start = box[axis], end = box[axis + 2], middle = (start + end) / 2;
  let before = -1, after = -1;
  const row = new Uint8Array(list.length);
  for (let n = 0; n < list.length; n++) {
    const other = list[n];
    if (!level(other, box, axis)) continue;
    row[n] = 1;
    const centre = (other[axis] + other[axis + 2]) / 2;
    if (other[axis + 2] <= start + reach && centre < middle) { if (before < 0 || other[axis + 2] > list[before][axis + 2]) before = n; }
    else if (other[axis] >= end - reach && centre > middle) { if (after < 0 || other[axis] < list[after][axis]) after = n; }
  }
  return { before, after, row };
}

function nearest(list, pairs, axis, box, reach) {
  const start = box[axis], end = box[axis + 2], size = end - start;
  const { before, after, row } = beside(list, axis, box, reach);
  if (before < 0 && after < 0) return null;
  const low = before >= 0 ? list[before][axis + 2] : -Infinity, high = after >= 0 ? list[after][axis] : Infinity;
  let best = null;
  const consider = (at, spacingSize) => {
    const shift = at - start;
    if (Math.abs(shift) > reach || spacingSize < 0) return;
    // (Never over its neighbour on the other side.)
    if (at < low - 1e-6 || at + size > high + 1e-6) return;
    if (!best || Math.abs(shift) < Math.abs(best.shift) - 1e-9) best = { axis, shift, size: spacingSize, before, after };
  };
  // Midway between its neighbours.
  if (before >= 0 && after >= 0) consider((low + high - size) / 2, (high - low - size) / 2);
  // As far from one as its neighbour is from the next -- or as two others near it in its row are apart.
  for (const gap of gapsNear(list, pairs, row, axis, box, before, after, reach)) {
    if (before >= 0) consider(low + gap, gap);
    if (after >= 0) consider(high - gap - size, gap);
  }
  return best;
}

// The nearest place within `reach` for `box`'s edge on `side` along `axis` where the gap to its
// neighbour that way is one of its row's: how far the edge moves (`shift`), the gap (`size`),
// and its neighbours either side -- as `nearest` says it, for the same marks.
function nearestEdge(list, pairs, axis, box, side, reach) {
  const start = box[axis], end = box[axis + 2];
  const { before, after, row } = beside(list, axis, box, reach);
  const toward = side === "end" ? after : before;
  if (toward < 0) return null;
  const edge = side === "end" ? end : start;
  let best = null;
  const consider = (size) => {
    if (!(size >= 0)) return;
    const at = side === "end" ? list[after][axis] - size : list[before][axis + 2] + size;
    const shift = at - edge;
    // (Never past its own other edge.)
    if (Math.abs(shift) > reach || (side === "end" ? at <= start : at >= end)) return;
    if (!best || Math.abs(shift) < Math.abs(best.shift) - 1e-9) best = { axis, shift, size, before, after, side };
  };
  // As far from that neighbour as it is from the one the other way, whose gap stays.
  const other = side === "end" ? (before >= 0 ? start - list[before][axis + 2] : NaN) : (after >= 0 ? list[after][axis] - end : NaN);
  if (other >= reach) consider(other);
  // As far as its neighbour is from the next -- or as two others near it in its row are apart.
  for (const gap of gapsNear(list, pairs, row, axis, box, before, after, reach)) consider(gap);
  return best;
}

// The gaps a catch shows: the dragged box's to its neighbours as wide as the spacing, and each
// gap of its row (or column) as wide -- where each is ({ axis, from, to, at }: along `axis`
// from `from` to `to`, at `at` the other way: the middle of where the two overlap).
function marksOf(list, pairs, found, box, slack) {
  const { axis, size } = found, o = 1 - axis;
  const across = (a, b) => (Math.max(a[o], b[o]) + Math.min(a[o + 2], b[o + 2])) / 2;
  const out = [];
  const seen = new Set();
  const add = (a, b) => {
    const from = a[axis + 2], to = b[axis];
    const key = `${from.toFixed(3)} ${to.toFixed(3)} ${across(a, b).toFixed(3)}`;
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ axis, from, to, at: across(a, b), size });
  };
  if (found.before >= 0 && Math.abs(box[axis] - list[found.before][axis + 2] - size) <= slack) add(list[found.before], box);
  if (found.after >= 0 && Math.abs(list[found.after][axis] - box[axis + 2] - size) <= slack) add(box, list[found.after]);
  for (const pair of pairs) {
    if (Math.abs(pair.size - size) > slack) continue;
    const a = list[pair.a], b = list[pair.b];
    if (!(level(a, box, axis) && level(b, box, axis)) && pair.b !== found.before && pair.a !== found.after) continue;
    add(a, b);
  }
  return out;
}

// -- while one is sized, or drawn --

// Of a guide caught (`guide`: { gap }) and an equal spacing (`even`: { shift }) one way, the
// nearer -- both when they put it in one place: [guide or null, even or null].
export function nearer(guide, even) {
  if (!even) return [guide, null];
  if (!guide) return [null, even];
  if (Math.abs(even.shift - guide.gap) < 1e-6) return [guide, even];
  return Math.abs(even.shift) < Math.abs(guide.gap) ? [null, even] : [guide, null];
}

// While a shape is sized by a handle, or drawn, as Keynote's spacing guides catch it: each edge
// that moves (`sides`: { x, y }, whether one does each way) is where the pointer is (`point`),
// the rest of `box` ([left, top, right, bottom]) staying, `fixed` the point that stays. Each
// way, the nearer of a guide (`guide(at, "x" | "y")`: { gap, at }, or null) and the place where
// the gap from that edge to its neighbour is one its row (or column) has (`spacing`'s edge, made
// once as the drag starts; null: guides alone; `ways` the ways it is looked for). What comes
// back: the point moved there, the guides to draw ({ axis, at }), and the gaps to mark,
// `marks(box)`, once the box is made.
export function sizeCatch(spacing, { point, fixed, box, sides, reach, guide, ways = { x: true, y: true } }) {
  let [px, py] = point;
  const lines = [], found = { x: null, y: null };
  const now = () => [sides.x ? Math.min(px, fixed[0]) : box[0], sides.y ? Math.min(py, fixed[1]) : box[1], sides.x ? Math.max(px, fixed[0]) : box[2], sides.y ? Math.max(py, fixed[1]) : box[3]];
  for (const [axis, name] of [[0, "x"], [1, "y"]]) {
    if (!sides[name]) continue;
    const at = axis === 0 ? px : py;
    const even = spacing && ways[name] !== false ? spacing.edge(now(), axis, at >= fixed[axis] ? "end" : "start", reach) : null;
    const [hit, gap] = nearer(guide(at, name), even);
    const by = hit ? hit.gap : gap ? gap.shift : 0;
    if (axis === 0) px += by; else py += by;
    if (hit) lines.push({ axis: name, at: hit.at });
    found[name] = gap;
  }
  return { point: [px, py], guides: lines, marks: (made) => (spacing ? [...spacing.marks(found.x, made), ...spacing.marks(found.y, made)] : []) };
}
