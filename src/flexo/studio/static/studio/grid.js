// The grid: graph paper over a page -- a deck's slide, a figure -- to see at a glance what lines
// up with what; and, snapping to the grid (snapping.js), what is dragged catches at its lines. In
// the studio alone: never presented, printed or exported.
//
// - Shown or hidden by # (Inkscape's key) while nothing is typed, View › Show Grid (the palette,
//   the Mac app's View menu) and Grid in the toolbar, beside Snap. One setting for
//   the person, kept in this browser, as the slides either side are (flexo-talk's across.js).
// - Drawn in non-photo blue: squares of `step` of the page's units (a slide's: 12 of the 960
//   across it, 80 by 45 on a wide slide), every `major`-th line darker (16 by 9), the page's
//   middles darker still -- and over them, in the mark's red, the layout its host gives: a
//   deck's margins, across the whole slide, and the places of the slide's layout, outlined. Each
//   line a pixel wide, or half of one, at any zoom; on a dark page, lighter.
// - Caught at, snapping to the grid: the squares' lines by a box's edges (a point: by itself);
//   the layout's lines, its places' edges and middles and the page's middles by its middle too.
//
// A page's host says, in the page's units, `{ step, major, layout: { xs, ys, boxes } }` (boxes
// [left, top, right, bottom]) -- any of it left out: a figure's squares are sized to it, and it
// has no layout. Here, whether it is shown and the sums, read in Node as in the studio; drawn,
// its toggle and its key: gridpaper.js.

const KEY = "flexo-studio-grid";
const heard = new Set();

// Hidden unless it was shown (none kept, unreadable: hidden).
function kept() {
  try { return globalThis.localStorage?.getItem?.(KEY) === "on"; } catch { return false; }
}
let shown = kept();

export const gridShown = () => shown;
// Shown or hidden: `how` as snapping's (snapping.js) -- "here", or "stored" (another tab).
export function setGrid(value, how = "here") {
  const now = Boolean(value);
  if (now === shown) return shown;
  shown = now;
  if (how !== "stored") {
    try { globalThis.localStorage?.setItem?.(KEY, shown ? "on" : "off"); } catch { /* this window's alone */ }
  }
  for (const listener of [...heard]) {
    try { listener(shown, how); } catch (error) { console.error(error); }
  }
  return shown;
}
export const toggleGrid = (how = "here") => setGrid(!shown, how);
// `listener(shown, how)` each time it is shown or hidden; what it returns stops that.
export function onGrid(listener) {
  heard.add(listener);
  return () => heard.delete(listener);
}
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("storage", (event) => { if (event.key === KEY || event.key === null) setGrid(kept(), "stored"); });
}

// -- its lines --

const round = (value) => Math.round(value * 1000) / 1000;
// (A square's side where the host gives none: the round number nearest an 80th of the page.)
const ROUND = [1, 2, 2.5, 5, 10, 12, 20, 25, 50, 100, 200, 250, 500, 1000];

// How large its squares are, and how many to a darker line, on `frame` ([x, y, width, height]).
export function spacingOf(frame, grid = {}) {
  const major = Math.max(1, Math.round(Number(grid?.major) || 5));
  const wanted = Number(grid?.step), width = Math.max(1, Number(frame?.[2]) || 1);
  // (Never so small that a page has more than 400 of them across.)
  if (wanted > 0) return { step: Math.max(wanted, width / 400), major };
  const ideal = width / 80;
  const step = ROUND.reduce((best, each) => (Math.abs(Math.log(each / ideal)) < Math.abs(Math.log(best / ideal)) ? each : best), ROUND[0]);
  return { step, major };
}

// The squares' lines across and down `frame`, from its top left, each `step` apart.
export function linesOf(frame, step) {
  const [x0, y0, width, height] = frame;
  const along = (from, length) => {
    const out = [];
    for (let k = 0; k * step <= length + 1e-6; k += 1) out.push(round(from + k * step));
    return out;
  };
  return { xs: along(x0, width), ys: along(y0, height) };
}

// The layout's lines: the page's middles, the host's lines, and its places' edges and middles.
function layoutLines(frame, layout) {
  const [x0, y0, width, height] = frame;
  const xs = new Set([round(x0 + width / 2)]), ys = new Set([round(y0 + height / 2)]);
  for (const at of layout?.xs || []) if (Number.isFinite(at)) xs.add(round(at));
  for (const at of layout?.ys || []) if (Number.isFinite(at)) ys.add(round(at));
  for (const box of placesOf(layout)) {
    const [left, top, right, bottom] = box;
    for (const at of [left, (left + right) / 2, right]) xs.add(round(at));
    for (const at of [top, (top + bottom) / 2, bottom]) ys.add(round(at));
  }
  return { xs: [...xs], ys: [...ys] };
}
export const placesOf = (layout) => (layout?.boxes || []).filter((box) => Array.isArray(box) && box.length === 4 && box.every(Number.isFinite) && box[2] > box[0] && box[3] > box[1]);

// What a drag catches at, snapping to the grid: its lines (`xs`, `ys`), those a box's middle
// does not catch at (the squares' alone) kept as their `edges` (snapping.js's nearest) -- no
// boxes to space among, nothing beside the page.
export function targetsOf(frame, grid = {}) {
  const { step } = spacingOf(frame, grid);
  const squares = linesOf(frame, step), layout = layoutLines(frame, grid?.layout);
  const xs = [...new Set([...squares.xs, ...layout.xs])], ys = [...new Set([...squares.ys, ...layout.ys])];
  const own = { x: new Set(layout.xs), y: new Set(layout.ys) };
  xs.edges = new Set(squares.xs.filter((at) => !own.x.has(at)));
  ys.edges = new Set(squares.ys.filter((at) => !own.y.has(at)));
  return { xs, ys, boxes: [], grid: true };
}
