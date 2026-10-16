// What a click picks follows what is drawn, as Inkscape's does (for the shapes' editor,
// shapes.js): a box of words with no fill and no outline is only where its words are -- their
// letters' ink, a few pixels round it -- so a shape under it (a node's circle, its letters
// over it) is picked beside and round them; a box filled or outlined is picked anywhere in its
// frame, as before. On a slide, over a figure, and inside groups alike; and on every move of
// the pointer, so each box's words are measured once (as the page draws them), then kept.
//
// And the page's drawn shapes by id, found in one pass over its drawing, again only once it is
// drawn anew: what a move of the pointer asks for, many times over on a slide of drawings, is
// then no search through the whole page each time.

import * as F from "./freeform.js";

// How near its words a box of them is picked, in pixels on the screen.
export const WORDS_MARGIN = 3;

const painted = (paint, opacity) => Boolean(paint) && paint !== "none" && Number(opacity ?? 1) > 0;

// Whether a shape is a box of words with no fill and no outline: picked where its words are.
export function bare(spec) {
  if (spec?.kind !== "text") return false;
  const look = F.normalised(spec);
  const lined = painted(look.line, look.line_opacity) && Number(look.line_width || 0) > 0;
  return !painted(look.fill, look.fill_opacity) && !lined;
}

// Whether `point` (the page's units) is within `margin` of `words` -- their bounds as drawn,
// [left, top, right, bottom] from the box's top left, unturned -- in the box `made` (as
// freeform.geometry makes it), turned as it is.
export function onWords(made, words, point, margin) {
  const local = made.turn ? F.unturned(point, F.centreOf(made), made.turn) : point;
  const x = local[0] - made.box[0], y = local[1] - made.box[1];
  return x >= words[0] - margin && x <= words[2] + margin && y >= words[1] - margin && y <= words[3] + margin;
}

// A box's words' bounds as drawn, from its frame's top left, unturned: `corners`, the corners of
// their drawn bounds in the page's units; `made`, the box they are drawn in. Null, none drawn.
export function wordsFrom(corners, made) {
  const centre = F.centreOf(made);
  const local = made.turn ? corners.map((point) => F.unturned(point, centre, made.turn)) : corners;
  const xs = local.map((point) => point[0]), ys = local.map((point) => point[1]);
  const box = [Math.min(...xs) - made.box[0], Math.min(...ys) - made.box[1], Math.max(...xs) - made.box[0], Math.max(...ys) - made.box[1]];
  return box.every(Number.isFinite) && (box[2] > box[0] || box[3] > box[1]) ? box : null;
}

// How far a run of words' ink reaches above and below its baseline, set in `font` (CSS's
// shorthand): measured as the page would draw it, on a canvas of the page's own (null where
// none is).
let canvas = null;
export function inkOf(text, font) {
  canvas ||= globalThis.document?.createElement?.("canvas")?.getContext?.("2d") || null;
  if (!canvas) return null;
  canvas.font = font;
  const metrics = canvas.measureText(text);
  const up = metrics.actualBoundingBoxAscent, down = metrics.actualBoundingBoxDescent;
  return Number.isFinite(up) && Number.isFinite(down) ? { up, down } : null;
}

// A box of words' ink, in its <text>'s own units, [left, top, right, bottom]: each run of it
// (a <tspan> of its own, or its words) from its first letter to the end of its last, and from
// the top of its ink to the bottom of it about its baseline -- not the line's height, its
// letters' ("A1" has none below its baseline). Null where that cannot be said of it (words
// with more than runs of letters in them, a page with no way to measure): its bounds then.
export function wordsInk(element, ink = inkOf) {
  if ([...element.querySelectorAll("*")].some((child) => child.localName !== "tspan")) return null;
  const runs = [...element.querySelectorAll("tspan")].filter((run) => !run.querySelector("tspan"));
  const box = [Infinity, Infinity, -Infinity, -Infinity];
  for (const run of runs.length ? runs : [element]) {
    const count = run.getNumberOfChars?.() || 0, text = run.textContent || "";
    if (!count || !text.trim()) continue;
    const start = run.getStartPositionOfChar(0), end = run.getEndPositionOfChar(count - 1);
    const style = globalThis.getComputedStyle?.(run);
    const reach = style ? ink(text, `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`) : null;
    if (!reach) return null;
    box[0] = Math.min(box[0], start.x, end.x);
    box[2] = Math.max(box[2], start.x, end.x);
    box[1] = Math.min(box[1], start.y - reach.up);
    box[3] = Math.max(box[3], start.y + reach.down);
  }
  return box.every(Number.isFinite) ? box : null;
}

// The picker for a page: `node(id)`, its drawn element of that id; `layer`, the <svg> over it
// the shapes are edited on, in their units; `unit()`, pixels to one of them.
export function wordsPicker({ node, layer, unit, ink = inkOf }) {
  // (Each element's words, kept by the element: the page drawn anew, they are measured anew.)
  const kept = new WeakMap();
  function measure(element, made) {
    let inked = null, box;
    try { inked = wordsInk(element, ink); } catch { inked = null; }
    try { box = inked ? { x: inked[0], y: inked[1], width: inked[2] - inked[0], height: inked[3] - inked[1] } : element.getBBox(); } catch { return null; }
    if (!box || (!box.width && !box.height)) return null;
    const toScreen = element.getScreenCTM?.(), fromScreen = layer.getScreenCTM?.()?.inverse();
    if (!toScreen || !fromScreen) return null;
    const matrix = fromScreen.multiply(toScreen);
    const corners = [[box.x, box.y], [box.x + box.width, box.y], [box.x + box.width, box.y + box.height], [box.x, box.y + box.height]]
      .map(([x, y]) => { const at = new DOMPoint(x, y).matrixTransform(matrix); return [at.x, at.y]; });
    return wordsFrom(corners, made);
  }
  // Whether `point` is on the words of the box `spec` drawn as `id` (`made`, as it is now):
  // true or false; null where it draws none (it is then picked by its frame).
  return function hits(spec, made, point, id) {
    if (!bare(spec)) return null;
    const element = node(`${id}.text`);
    if (!element) return null;
    if (!kept.has(element)) kept.set(element, measure(element, made));
    const words = kept.get(element);
    return words ? onWords(made, words, point, WORDS_MARGIN / (unit() || 1)) : null;
  };
}

// The elements of the page's drawing (`drawing()`, its <svg>) by id, found in one pass and
// found again once it is another, or one found is no longer in it.
export function drawnIds(drawing) {
  let root = null, found = new Map();
  const index = (now) => {
    root = now;
    found = new Map();
    if (now) for (const element of now.querySelectorAll("[id]")) if (!found.has(element.id)) found.set(element.id, element);
  };
  return function byId(id) {
    const now = drawing();
    if (now !== root) index(now);
    let element = found.get(id) || null;
    if (element && !element.isConnected) { index(now); element = found.get(id) || null; }
    return element;
  };
}
