// What a click picks follows what is drawn, as Inkscape's does (for the shapes' editor,
// shapes.js): a box of words with no fill and no outline is only where its words are -- their
// letters' ink, a few pixels round it -- so a shape under it (a node's circle, its letters
// over it) is picked beside and round them; a box filled or outlined is picked anywhere in its
// frame, as before. On a slide, over a figure, and inside groups alike; and on every move of
// the pointer, so each box's words are measured once (as the page draws them), then kept.
// Its words are their letters and any maths among them drawn as shapes; pointed at, it shows
// where it is picked -- round its words, not its frame (shapes.js).
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

// A box of words' ink, in its element's own units, [left, top, right, bottom]. A <text>: each
// run of it (a <tspan> of its own -- a link's too -- or its words) from its first letter to
// the end of its last, and from the top of its ink to the bottom of it about its baseline --
// not the line's height, its letters' ("A1" has none below its baseline). Words with maths
// among them (a <g> of <text>s, each formula a `flexo-math` group of the shapes it is drawn
// as; or of lines, each its own): their letters' ink and each formula as it is drawn, all
// told. Null where that cannot be said of it (anything else drawn in them, a page with no way
// to measure): its bounds then.
export function wordsInk(element, ink = inkOf) {
  const box = [Infinity, Infinity, -Infinity, -Infinity];
  if (!inkInto(box, element, ink, null, true)) return null;
  return box.every(Number.isFinite) ? box : null;
}
const isMaths = (node) => node.localName === "g" && Boolean(node.classList?.contains("flexo-math"));
// (Each piece of it put in `box`, in the element's units: `placed`, how its parent's are those
// -- a formula moved to where it is set, its letters as they are; the element's own transform
// none of them. False, it cannot be said.)
function inkInto(box, node, ink, placed, outer = false) {
  const local = outer ? null : matrixOf(node);
  const own = placed && local ? compose(placed, local) : placed || local;
  if (node.localName === "text") return textInk(box, node, ink, own);
  if (isMaths(node)) {
    let drawn;
    try { drawn = node.getBBox(); } catch { return false; }
    if (drawn && (drawn.width || drawn.height)) put(box, own, [drawn.x, drawn.y, drawn.x + drawn.width, drawn.y + drawn.height]);
    return true;
  }
  if (node.localName !== "g") return false;
  for (const child of node.children || []) if (!inkInto(box, child, ink, own)) return false;
  return true;
}
function textInk(box, element, ink, placed) {
  if ([...element.querySelectorAll("*")].some((child) => child.localName !== "tspan" && child.localName !== "a")) return false;
  const runs = [...element.querySelectorAll("tspan")].filter((run) => !run.querySelector("tspan"));
  for (const run of runs.length ? runs : [element]) {
    const count = run.getNumberOfChars?.() || 0, text = run.textContent || "";
    if (!count || !text.trim()) continue;
    const start = run.getStartPositionOfChar(0), end = run.getEndPositionOfChar(count - 1);
    const style = globalThis.getComputedStyle?.(run);
    const reach = style ? ink(text, `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`) : null;
    if (!reach) return false;
    put(box, placed, [Math.min(start.x, end.x), start.y - reach.up, Math.max(start.x, end.x), start.y + reach.down]);
  }
  return true;
}
// A node's own transform, as a matrix: null, none.
function matrixOf(node) {
  try { return node.transform?.baseVal?.consolidate?.()?.matrix || null; } catch { return null; }
}
const compose = (m, n) => ({ a: m.a * n.a + m.c * n.b, b: m.b * n.a + m.d * n.b, c: m.a * n.c + m.c * n.d, d: m.b * n.c + m.d * n.d,
  e: m.a * n.e + m.c * n.f + m.e, f: m.b * n.e + m.d * n.f + m.f });
function put(box, matrix, [left, top, right, bottom]) {
  const corners = matrix ? [[left, top], [right, top], [right, bottom], [left, bottom]].map(([x, y]) => [matrix.a * x + matrix.c * y + matrix.e, matrix.b * x + matrix.d * y + matrix.f])
    : [[left, top], [right, bottom]];
  for (const [x, y] of corners) {
    box[0] = Math.min(box[0], x); box[1] = Math.min(box[1], y);
    box[2] = Math.max(box[2], x); box[3] = Math.max(box[3], y);
  }
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
  // The words of the box `spec` drawn as `id` (`made`, as it is now), as wordsFrom says them:
  // null where it is filled or outlined, or draws none (it is then its frame).
  function words(spec, made, id) {
    if (!bare(spec)) return null;
    const element = node(`${id}.text`);
    if (!element) return null;
    if (!kept.has(element)) kept.set(element, measure(element, made));
    return kept.get(element);
  }
  // Whether `point` is on them: true or false; null where it draws none (it is then picked by
  // its frame). And `hits.words`, them -- where the pointer shows it is.
  function hits(spec, made, point, id) {
    const found = words(spec, made, id);
    return found ? onWords(made, found, point, WORDS_MARGIN / (unit() || 1)) : null;
  }
  hits.words = words;
  return hits;
}

// The corners of `words` (as wordsFrom says them) on the page, `margin` round them, in the box
// `made`, turned as it is: what a box of words with no fill nor outline shows pointed at.
export function wordsCorners(made, words, margin = 0) {
  const [x, y] = made.box, centre = F.centreOf(made);
  const left = x + words[0] - margin, top = y + words[1] - margin, right = x + words[2] + margin, bottom = y + words[3] + margin;
  return [[left, top], [right, top], [right, bottom], [left, bottom]].map((point) => (made.turn ? F.turned(point, centre, made.turn) : point));
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
