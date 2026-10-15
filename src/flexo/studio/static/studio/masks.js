// A picture shown only inside a shape (flexo.masks): Keynote's Mask with Shape. A mask is a
// closed shape (freeform.js) whose places are fractions of the part of the picture kept; here it
// is drawn where that part is (`outline`, as flexo.masks draws it: a test runs both), and made
// from a shape drawn over a picture (`fromShape`).

import * as F from "./freeform.js";

// Whether a shape can mask a picture: any closed one (as its geometry says, whatever its
// kind), but a zoom inset and a box of words.
export function maskable(spec) {
  const kind = spec?.kind;
  if (!F.KINDS.includes(kind) || kind === "inset" || kind === "text" || kind === "group") return false;
  try { return Boolean(F.geometry(spec).closed); } catch { return false; }
}

// What of a shape is how it is drawn, or the page's -- no mask's: the rest is its outline.
const UNSHAPED = new Set(["id", "fill", "fill_opacity", "line", "line_width", "dash", "cap", "join", "start", "end", "head_size", "shadow", "opacity",
  "text", "font_size", "bold", "italic", "colour", "font", "align", "valign", "padding", "behind", "build", "hidden", "locked", "on", "around", "margin", "side"]);

// The outline a picture is shown within, masked by `mask`, its part kept drawn at `kept`
// ([x, y, w, h]): as freeform.js segments, turned as it is.
export function outline(mask, kept) {
  const [kx, ky, kw, kh] = kept;
  const page = ([x, y]) => [kx + x * kw, ky + y * kh];
  if (F.family(mask.kind) === "box") {
    const spec = F.mapped({ at: [0, 0], size: [1, 1], ...mask }, page);
    const made = F.geometry(spec);
    if (!made.turn) return made.segments;
    const centre = F.centreOf(made);
    return made.segments.map((segment) => moved(segment, (point) => F.turned(point, centre, made.turn)));
  }
  const made = F.geometry({ ...mask, closed: true });
  return made.segments.map((segment) => moved(segment, page));
}

function moved([kind, ...values], to) {
  const out = [kind];
  for (let n = 0; n < values.length; n += 2) out.push(...to([values[n], values[n + 1]]));
  return out;
}

// A picture masked by a shape over it: `shape` as drawn (in the page's units), the picture's
// whole drawn at `whole` ([x, y, w, h], the same units). The part kept is the shape's box, as
// far as it is on the picture -- `crop`, fractions of the whole -- and `mask`, the shape with
// its places as fractions of that part (its fill, line and words are no mask's). Null when the
// shape is not on the picture.
export function fromShape(shape, whole) {
  const spec = F.normalised(shape);
  if (!maskable(spec)) return null;
  const made = F.geometry(spec);
  const [left, top, right, bottom] = F.bounds(spec, made);
  const [wx, wy, ww, wh] = whole;
  const x0 = Math.max(left, wx), y0 = Math.max(top, wy), x1 = Math.min(right, wx + ww), y1 = Math.min(bottom, wy + wh);
  if (x1 - x0 < 1 || y1 - y0 < 1) return null;
  const round = (value) => Math.round(value * 10000) / 10000;
  const crop = [round((x0 - wx) / ww), round((y0 - wy) / wh), round((x1 - x0) / ww), round((y1 - y0) / wh)];
  const kept = [wx + crop[0] * ww, wy + crop[1] * wh, crop[2] * ww, crop[3] * wh];
  const fraction = ([x, y]) => [round((x - kept[0]) / kept[2]), round((y - kept[1]) / kept[3])];
  const written = Object.fromEntries(Object.entries(shape).filter(([key, value]) => !UNSHAPED.has(key) && value !== null && value !== undefined));
  const mask = F.mapped(written, fraction);
  if (F.family(spec.kind) === "points") mask.closed = true;
  if (F.family(spec.kind) === "box") {
    if (Array.isArray(mask.at) && mask.at.every((value) => Math.abs(value) < 0.0005)) delete mask.at;
    if (Array.isArray(mask.size) && mask.size.every((value) => Math.abs(value - 1) < 0.0005)) delete mask.size;
    if (!Number(mask.rotate)) delete mask.rotate;
    if (!mask.flip) delete mask.flip;
  }
  return { crop, mask };
}
