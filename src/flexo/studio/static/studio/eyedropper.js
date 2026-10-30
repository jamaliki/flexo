// A colour taken from anywhere on the screen. In the Mac app, the Mac's own magnifier
// (NSColorSampler, flexo_studio.mac): any window, any app's -- a micrograph open in Preview, a
// co-author's figure in a PDF -- and where it was clicked, when that was on this page. In a
// browser, Chromium's EyeDropper; a browser without one offers none (canPick).
//
// Clicked on something the page drew (a shape, a part, a word), the colour taken is what it is
// drawn in, exactly -- not the screen's rounding of it, nor its edge's blend with what is
// behind it (drawnAt): a colour matched is the very colour.

import { paintHex, apart } from "./colourmatch.js";

const bridge = () => globalThis.pywebview?.api;

// Whether a colour can be taken from the screen here.
export function canPick() {
  return typeof bridge()?.sample_colour === "function" || typeof globalThis.EyeDropper === "function";
}

// The colour the person clicks, anywhere on the screen: { hex, at } -- `at` where on this
// page it was ({ x, y }, as the pointer's are), when it was on it and that is known -- or null
// (Esc, or a screen that could not be read). `hide` (the popover that asked) is out of sight
// meanwhile, so that what is under it can be taken.
export async function pickFromScreen({ hide = null } = {}) {
  const app = bridge();
  const native = typeof app?.sample_colour === "function" ? null : globalThis.EyeDropper;
  if (typeof app?.sample_colour !== "function" && typeof native !== "function") return null;
  const restore = hide ? hide.style.visibility : "";
  if (hide) hide.style.visibility = "hidden";
  try {
    if (native) {
      // (Opened at once, in the click that asked: Chromium's wants it so.)
      const got = await new native().open();
      const hex = paintHex(got?.sRGBHex);
      return hex ? { hex, at: null } : null;
    }
    const got = await app.sample_colour();
    const hex = paintHex(got?.hex);
    if (!hex) return null;
    const at = Number.isFinite(got.x) && Number.isFinite(got.y) ? { x: got.x, y: got.y } : null;
    return { hex, at };
  } catch {
    // Esc is a cancel; a screen that cannot be read is the same to the person.
    return null;
  } finally {
    if (hide) hide.style.visibility = restore;
  }
}

// How near what is drawn at a point must be to the colour seen there to be taken for it (out
// of 255, in each of red, green and blue): an edge's blend, a light opacity.
const SEEN = 48;
// What is drawn by itself (not through a <use>, a marker, a mask or a pattern) and is painted.
const SHAPES = "path, rect, circle, ellipse, line, polyline, polygon, text, image, foreignObject";
const UNDRAWN = "defs, clipPath, mask, marker, pattern, symbol";
const GEOMETRY = new Set(["path", "rect", "circle", "ellipse", "line", "polyline", "polygon"]);

// What `root` (a page's drawing) draws at ({x}, {y}) on the screen, in the colour seen there
// (`seen`, "#rrggbb", as sampled): { hex, paint, node } -- its fill or its stroke, as drawn --
// or null where a picture is there (its pixels are its colours), nothing of the drawing is, or
// what is there is drawn in no colour near the one seen.
export function drawnAt(root, x, y, seen) {
  if (!root?.querySelectorAll || !Number.isFinite(x) || !Number.isFinite(y)) return null;
  const frame = root.getBoundingClientRect?.();
  if (!frame || x < frame.left || x > frame.right || y < frame.top || y > frame.bottom) return null;
  const nodes = root.querySelectorAll(SHAPES);
  // The last drawn is on top.
  for (let n = nodes.length - 1; n >= 0; n -= 1) {
    const node = nodes[n];
    if (node.closest(UNDRAWN)) continue;
    const box = node.getBoundingClientRect();
    if (!box.width && !box.height) continue;
    if (x < box.left - 1 || x > box.right + 1 || y < box.top - 1 || y > box.bottom + 1) continue;
    const name = node.localName;
    const style = getComputedStyle(node);
    if (style.visibility === "hidden" || style.display === "none") continue;
    // A picture on top: what is seen there is its own.
    if (name === "image" || name === "foreignObject") return null;
    const fill = paintHex(style.fill), stroke = paintHex(style.stroke);
    let hitStroke = false, hitFill = false;
    if (GEOMETRY.has(name) && typeof node.isPointInFill === "function") {
      const matrix = node.getScreenCTM?.();
      if (!matrix) continue;
      const local = new DOMPoint(x, y).matrixTransform(matrix.inverse());
      hitStroke = Boolean(stroke) && node.isPointInStroke(local);
      hitFill = Boolean(fill) && node.isPointInFill(local);
    } else {
      // Words: their box (the colour seen says whether a letter or the gap between was hit).
      hitFill = Boolean(fill);
    }
    // (A stroke is drawn over its fill.)
    if (hitStroke && apart(stroke, seen) <= SEEN) return { hex: stroke, paint: "stroke", node };
    if (hitFill && apart(fill, seen) <= SEEN) return { hex: fill, paint: "fill", node };
    // Hit, and solid, but drawn in another colour than is seen (a filter over it, a sketch's
    // wash): the pixel's colour is the one.
    const solid = Number(style.opacity) >= 1 && Number(style.fillOpacity) >= 1;
    if (GEOMETRY.has(name) && solid && hitFill) return null;
  }
  return null;
}
