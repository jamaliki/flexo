// Snapping: whether what is dragged catches at guides -- the edges and middles of the page, of
// the other shapes, of a slide's objects and a figure's parts -- or at the grid's lines instead
// (grid.js), and a line's end let go on a shape is glued to it. On (to guides or to the grid),
// ⌘ (or Ctrl) held while dragging leaves it off for that drag, as it always has; off, nothing
// catches and no end is glued, and ⌘ held catches at guides and glues for that drag. An end
// glued before stays glued; one dragged off is a free point.
//
// One setting for the person, not the document: a slide's shapes and a figure's alike, kept in
// this browser (localStorage, read with care) from one launch to the next. Turned in another
// window or tab of the studio, it is turned so here too (a storage event); in the Mac app,
// whose windows are each a folder's own, the app keeps it and tells the others (magnet.js).
// The magnet in the zoom bar shows it; it and % (Inkscape's key) go from guides to the grid to
// off and round again; the Mac app's View › Snap to Guides and Objects and Snap to Grid each
// turn it to theirs, or off.
//
// No page is needed: it is read in Node as it is in the studio.

const KEY = "flexo-studio-snapping";
const heard = new Set();
const MODES = ["guides", "grid", "off"];

// What this browser kept: the grid or off only if it was turned so (none kept, unreadable:
// guides). Kept as "on" (guides), "grid" or "off".
function kept() {
  try {
    const said = globalThis.localStorage?.getItem?.(KEY);
    return said === "off" ? "off" : said === "grid" ? "grid" : "guides";
  } catch { return "guides"; }
}
let mode = kept();
const word = (value) => (value === "guides" ? "on" : value);

// Whether snapping is on now (to guides or to the grid); which it is.
export const snapping = () => mode !== "off";
export const snapMode = () => mode;
export const toGrid = () => mode === "grid";
export const toGuides = () => mode === "guides";

// Whether a drag is free of guides and glue now, with ⌘ held or not: `held` a pointer or key
// event (its ⌘ or Ctrl), or whether ⌘ is held. On, ⌘ frees it; off, ⌘ catches.
export function free(held) {
  const pressed = held !== null && typeof held === "object" ? Boolean(held.metaKey || held.ctrlKey) : Boolean(held);
  return snapping() ? pressed : !pressed;
}
// What ⌘ does to a drag now, as a handle's hint says it: "(⌘: without snapping)".
export const withCommand = () => (snapping() ? "without snapping" : "with snapping");

// Turned to `value` ("guides", "grid" or "off"): `how` it was -- "here" (this page: its
// button, its key, the menu), "app" (the Mac app, from another window), "stored" (another tab
// of this browser, already kept). Kept but for "stored", each listener told (once, and only if
// it changed) whether it is on, how, and to what.
export function setSnapMode(value, how = "here") {
  const now = MODES.includes(value) ? value : "guides";
  if (now === mode) return mode;
  mode = now;
  if (how !== "stored") {
    try { globalThis.localStorage?.setItem?.(KEY, word(mode)); } catch { /* this window's alone */ }
  }
  for (const listener of [...heard]) {
    try { listener(snapping(), how, mode); } catch (error) { console.error(error); }
  }
  return mode;
}
// On or off: turned on, to guides (on already, to whichever it is).
export function setSnapping(value, how = "here") {
  return setSnapMode(value ? (mode === "off" ? "guides" : mode) : "off", how) !== "off";
}
export const toggleSnapping = (how = "here") => setSnapping(!snapping(), how);
// The magnet's and %'s turn: guides, the grid, off, and round again.
export const cycleSnapping = (how = "here") => setSnapMode(MODES[(MODES.indexOf(mode) + 1) % MODES.length], how);
// The Mac app's word for it ("on", "grid", "off") and back.
export const snapWord = () => word(mode);
export const fromWord = (said) => (said === "on" ? "guides" : said === "grid" || said === "off" ? said : null);

// `listener(on, how, mode)` each time it is turned; what it returns stops that.
export function onSnapping(listener) {
  heard.add(listener);
  return () => heard.delete(listener);
}

// The nearest of `values` to any of `mine` (a box's edges and middle, or a point) within
// `reach`: how far to move to it, and where. A value `values.edges` holds (the grid's squares'
// lines: grid.js) is caught at by a box's edges alone, not its middle -- else every square would
// catch a box three ways, a hair apart.
export function nearest(mine, values, reach) {
  let best = null;
  const middle = mine.length === 3 ? 1 : -1, edges = values?.edges;
  mine.forEach((own, index) => {
    for (const value of values) {
      if (index === middle && edges?.has(value)) continue;
      const gap = value - own;
      if (Math.abs(gap) <= reach && (!best || Math.abs(gap) < Math.abs(best.gap))) best = { gap, at: value };
    }
  });
  return best;
}

// Another window or tab of this browser turned it (or cleared what it keeps).
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("storage", (event) => {
    if (event.key === KEY || event.key === null) setSnapMode(kept(), "stored");
  });
}
