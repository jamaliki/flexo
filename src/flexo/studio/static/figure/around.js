// Where a shape drawn round parts of a figure goes (flexo.figure_shapes' `around_box` and
// `placed_round`, kept to them by a test): the box round the parts, a margin out -- an oval's
// through their box's corners -- and the places that draw a shape there. `family` is
// freeform.js's: how a kind of shape is placed.

const ROUND = ["ellipse", "ring"];

// The box a shape of `kind` is drawn in round `boxes` ([x, y, width, height] each).
export function aroundBox(boxes, margin, kind) {
  let left = Math.min(...boxes.map((box) => box[0])), top = Math.min(...boxes.map((box) => box[1]));
  let right = Math.max(...boxes.map((box) => box[0] + box[2])), bottom = Math.max(...boxes.map((box) => box[1] + box[3]));
  if (ROUND.includes(kind)) {
    const grow = (Math.SQRT2 - 1) / 2, across = (right - left) * grow, down = (bottom - top) * grow;
    left -= across; right += across; top -= down; bottom += down;
  }
  left -= margin; top -= margin; right += margin; bottom += margin;
  return [left, top, Math.max(right - left, 0), Math.max(bottom - top, 0)];
}

// The side of what it goes round a line drawn round parts runs along.
export const sideOf = (spec) => spec.side || (["brace", "bracket"].includes(spec.kind) ? "right" : "bottom");

// `spec` given the places that draw it round `box`: a box's at and size, a box of words' at
// and width, a line along its side (a brace, a bracket and a dimension pointing away), points
// stretched over it.
export function placedRound(spec, [x, y, w, h], family) {
  const made = { ...spec }, form = family(spec.kind);
  if (form === "box") { made.at = [x, y]; made.size = [w, h]; }
  else if (form === "text") { made.at = [x, y]; made.width = Math.max(w, 1); }
  else if (form === "line") {
    const corners = { tl: [x, y], tr: [x + w, y], br: [x + w, y + h], bl: [x, y + h] };
    const away = ["brace", "bracket", "dimension"].includes(spec.kind);
    const ends = { right: ["tr", "br"], left: away ? ["bl", "tl"] : ["tl", "bl"], top: ["tl", "tr"], bottom: away ? ["br", "bl"] : ["bl", "br"] }[sideOf(spec)];
    made.from = corners[ends[0]]; made.to = corners[ends[1]];
  } else if (form === "points" && (spec.points || []).length) {
    const xs = spec.points.map((p) => p[0]), ys = spec.points.map((p) => p[1]);
    const left = Math.min(...xs), top = Math.min(...ys), across = Math.max(...xs) - left || 1, down = Math.max(...ys) - top || 1;
    made.points = spec.points.map(([px, py]) => [x + (px - left) / across * w, y + (py - top) / down * h]);
  }
  return made;
}
