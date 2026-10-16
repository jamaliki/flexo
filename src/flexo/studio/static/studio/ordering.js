// The order things were chosen in, for Align's First Chosen and Last Chosen (aligntools.js):
// the sums alone, for the shapes' editor (shapes.js) and a choice of both kinds (mixed.js).
//
// - Each is kept by when it was chosen (a stamp: later than any before it, on this page), not
//   by where it is in the page's list -- Bring to Front, Send Backward, a shape taken away
//   before it, move it in the list, never in the order (`moved`); undone, it is as it was then.
// - One order across a slide's objects and its shapes chosen together, and a figure's parts
//   and the shapes over it: each kind's stamps come from the one count.
// - A band has no click order: what it chooses is in reading order -- top to bottom, then left
//   to right (aligning.js's readingOrder) -- after what was chosen before it began, kept by ⇧
//   or ⌘ in the order that was.
//
// No page is needed: it is read in Node as it is in the studio.

import { readingOrder } from "./aligning.js";

let count = 0;
// When something is chosen: later than anything chosen before it.
export const stamp = () => ++count;

// A kind's own order: what each chosen is known by (its key: a shape's place, an object's
// pick) and when it was chosen.
export function chosenOrder() {
  let stamps = new Map();
  // A band under way: whether it keeps what was chosen as it began (⇧, ⌘), and once it chooses,
  // when it began and what it kept.
  let band = null;
  // Those chosen in a band, in reading order, stamped as one: after those kept, before anything
  // chosen after it.
  const inBand = (keys, boxOf) => {
    const boxed = keys.map((key) => ({ key, box: boxOf(key) }));
    const read = readingOrder(boxed.filter((item) => usable(item.box))).map((item) => item.key);
    return [...read, ...keys.filter((key) => !read.includes(key))];
  };
  return {
    // The pointer pressed: a band dragged from it keeps (`keep`, ⇧ or ⌘) what is chosen then.
    pressed(keep) { band = { keep: Boolean(keep), base: null, kept: null }; },
    // Those chosen now (`now`, in the order given) of those chosen before (`was`): those still
    // chosen keep when they were; the rest are chosen now, in the order given -- or, chosen by
    // a band (`band`: each one's box, by its key), in reading order.
    chose(was, now, { band: boxOf = null } = {}) {
      const before = stamps, had = new Set(was);
      stamps = new Map();
      if (boxOf) {
        band ||= { keep: false, base: null, kept: null };
        if (band.base === null) { band.base = stamp(); band.kept = band.keep ? new Set(was) : new Set(); }
        const kept = now.filter((key) => band.kept.has(key) && had.has(key));
        for (const key of kept) stamps.set(key, before.get(key) ?? band.base - 0.5);
        const rest = inBand(now.filter((key) => !stamps.has(key)), boxOf);
        rest.forEach((key, n) => stamps.set(key, band.base + (n + 1) / (rest.length + 1)));
        return;
      }
      // (Those chosen before but never stamped -- chosen again by an undo -- before those new.)
      for (const key of now) if (had.has(key)) stamps.set(key, before.get(key) ?? stamp());
      for (const key of now) if (!stamps.has(key)) stamps.set(key, stamp());
    },
    // Each moved in the page's list (`place(key)`: where it is now, or null or -1: gone).
    moved(place) {
      const next = new Map();
      for (const [key, when] of stamps) { const now = place(key); if (now !== null && now !== undefined && now !== -1) next.set(now, when); }
      stamps = next;
    },
    // `keys` in the order they were chosen (those never stamped last, as given).
    ordered(keys) {
      const when = (key) => stamps.get(key) ?? Infinity;
      return keys.map((key, n) => [key, n]).sort((a, b) => when(a[0]) - when(b[0]) || a[1] - b[1]).map(([key]) => key);
    },
    stampOf: (key) => stamps.get(key) ?? null,
    stampAs(key, when) { if (Number.isFinite(when)) stamps.set(key, when); },
    // As it is now, and as it was, for a step's undo to put back.
    entries: () => [...stamps],
    restore(entries) { stamps = new Map(Array.isArray(entries) ? entries : []); },
  };
}

// Where each of `was` (the page's list before a change) is in `now` (after it), by itself: its
// place, else -1 -- but one changed where it was (a shape moved: another made in its place, the
// list as long) is still there. (`also`: the same list as another holds it -- the editor's own,
// where the change was made on a copy -- each found by either.)
export function placesAfter(was, now, also = null) {
  const at = new Map(now.map((item, n) => [item, n]));
  const before = new Set([...was, ...(also || [])]);
  return (index) => {
    if (!Number.isInteger(index) || index < 0 || index >= was.length) return -1;
    if (at.has(was[index])) return at.get(was[index]);
    if (also && at.has(also[index])) return at.get(also[index]);
    return now.length === was.length && !before.has(now[index]) ? index : -1;
  };
}

// Several kinds chosen together (`kinds`: each { keys(), stampOf(key), stampAs(key, when),
// box(key) }), in the order they were chosen: a band's, across them all, in reading order
// (`band`: when it began, what it kept).
export function acrossOrder(kinds) {
  return {
    ordered() {
      const all = kinds.flatMap((kind, k) => kind.keys().map((key, n) => ({ key, when: kind.stampOf(key) ?? Infinity, k, n })));
      return all.sort((a, b) => a.when - b.when || a.k - b.k || a.n - b.n).map((item) => item.key);
    },
    // Chosen by a band across them: all but what it kept stamped again, as one, in reading order.
    banded(band) {
      if (!band) return;
      band.base ??= stamp();
      const rest = kinds.flatMap((kind) => kind.keys().filter((key) => !band.kept?.has(key)).map((key) => ({ key, box: kind.box(key), kind })));
      const read = readingOrder(rest.filter((item) => usable(item.box)));
      const all = [...read, ...rest.filter((item) => !read.includes(item))];
      all.forEach((item, n) => item.kind.stampAs(item.key, band.base + (n + 1) / (all.length + 1)));
    },
  };
}

const usable = (box) => Array.isArray(box) && box.length === 4 && box.every(Number.isFinite);
