// Snapping: whether what is dragged catches at guides -- the edges and middles of the page, of
// the other shapes, of a slide's objects and a figure's parts -- and a line's end let go on a
// shape is glued to it. On, ⌘ (or Ctrl) held while dragging leaves it off for that drag, as it
// always has; off, nothing catches and no end is glued, and ⌘ held catches and glues for that
// drag. An end glued before stays glued; one dragged off is a free point.
//
// One setting for the person, not the document: a slide's shapes and a figure's alike, kept in
// this browser (localStorage, read with care) from one launch to the next. Turned on or off in
// another window or tab of the studio, it is turned so here too (a storage event); in the Mac
// app, whose windows are each a folder's own, the app keeps it and tells the others
// (magnet.js). The magnet in the zoom bar shows it, % turns it on or off (Inkscape's key), and
// so does the Mac app's View › Snap to Guides and Objects.
//
// No page is needed: it is read in Node as it is in the studio.

const KEY = "flexo-studio-snapping";
const heard = new Set();

// What this browser kept: off only if it was turned off (none kept, unreadable: on).
function kept() {
  try { return globalThis.localStorage?.getItem?.(KEY) !== "off"; } catch { return true; }
}
let on = kept();

// Whether snapping is on now.
export const snapping = () => on;

// Whether a drag is free of guides and glue now, with ⌘ held or not: `held` a pointer or key
// event (its ⌘ or Ctrl), or whether ⌘ is held. On, ⌘ frees it; off, ⌘ catches.
export function free(held) {
  const pressed = held !== null && typeof held === "object" ? Boolean(held.metaKey || held.ctrlKey) : Boolean(held);
  return on ? pressed : !pressed;
}

// What ⌘ does to a drag now, as a handle's hint says it: "(⌘: without snapping)".
export const withCommand = () => (on ? "without snapping" : "with snapping");

// Turned on or off: `how` it was -- "here" (this page: its button, its key, the menu), "app"
// (the Mac app, from another window), "stored" (another tab of this browser, already kept).
// Kept but for "stored", each listener told (once, and only if it changed).
export function setSnapping(value, how = "here") {
  const now = Boolean(value);
  if (now === on) return on;
  on = now;
  if (how !== "stored") {
    try { globalThis.localStorage?.setItem?.(KEY, on ? "on" : "off"); } catch { /* this window's alone */ }
  }
  for (const listener of [...heard]) {
    try { listener(on, how); } catch (error) { console.error(error); }
  }
  return on;
}
export const toggleSnapping = (how = "here") => setSnapping(!on, how);

// `listener(on, how)` each time it is turned on or off; what it returns stops that.
export function onSnapping(listener) {
  heard.add(listener);
  return () => heard.delete(listener);
}

// Another window or tab of this browser turned it (or cleared what it keeps).
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("storage", (event) => {
    if (event.key === KEY || event.key === null) setSnapping(kept(), "stored");
  });
}
