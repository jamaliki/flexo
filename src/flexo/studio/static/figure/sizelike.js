// A figure's shape sized by its handles catches where it is as wide (or as tall) as another of
// the figure's parts, as a shape on a slide catches another's size (snapping.js, aligning.js):
// while it is that size, a bar along it and along each part that size says which it matches.
// Its parts are looked at once, as the drag starts, where they are drawn.

import { drawSizes } from "/static/studio/aligntools.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const S = (name, attributes = {}, ...children) => {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  node.append(...children);
  return node;
};

// The figure's other parts (`rects`: each one's box on the page, as drawn), each with its
// width and height in the figure's points (`unit`: the page's pixels in one).
export const partsOf = (rects, unit) => rects.filter((rect) => rect?.width > 0 && rect.height > 0)
  .map((rect) => ({ rect, width: rect.width / unit, height: rect.height / unit }));

// Of the sizes a side may catch at (`candidates`: { size, how }, those first that win a tie),
// the nearest to `value` within `near`, if any.
export function nearestSize(value, candidates, near) {
  let best = null;
  for (const candidate of candidates) {
    const off = Math.abs(value - candidate.size);
    if (Number.isFinite(off) && off < near && (!best || off < best.off - 1e-9)) best = { ...candidate, off };
  }
  return best;
}
// The sizes of `parts` one way (`side`: "width" or "height"), none less than `least`, to catch at.
export const sizesOf = (parts, side, least = 0) => parts.map((part) => part[side]).filter((size) => size >= least - 1e-9).map((size) => ({ size, how: "like" }));

// The bars for the sizes caught at (`matched`: { width, height }, each a size or null), drawn in
// `holder` (a group of the overlay drawn over the page, `outer` its box on the page): along the
// part sized (`own`: [left, top, right, bottom] there) and each of `parts` that size.
export function drawLike(holder, outer, own, parts, matched) {
  holder.replaceChildren();
  const marks = [];
  for (const [side, axis] of [["width", 0], ["height", 1]]) {
    const size = matched?.[side];
    if (typeof size !== "number") continue;
    marks.push({ axis, box: own });
    for (const part of parts) {
      if (Math.abs(part[side] - size) >= 0.5) continue;
      const { left, top, right, bottom } = part.rect;
      marks.push({ axis, box: [left - outer.left, top - outer.top, right - outer.left, bottom - outer.top] });
    }
  }
  if (marks.length) drawSizes(holder, marks, 1, S);
}
