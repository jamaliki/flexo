// Paths taken apart and put together again, for the tools that make and change them: a path's
// pieces as anchors and their handles (as a pen draws them and points are edited), any shape
// made a path of the same outline (Make Editable), and shapes combined into one -- their union,
// one less the others, their intersection, or what one or other covers but not both.
//
// Nothing here touches the page: shapes are mappings, geometry plain numbers, so the tools and
// the tests run the same code.
//
// Shapes are combined by the arrangement their outlines make: each outline cut into lines (its
// curves as fine ones, each remembering the curve and the stretch of it it is), on a grid of
// 1/256 of a point, so that whether a point is left of a line is found exactly; every crossing
// found and each line cut there, lines lying on one another made one; each piece of line kept
// where what is inside the result on one side of it is not on the other, turned so the result
// is on its left; and the kept pieces joined into rings -- a run of pieces of one curve written
// as that stretch of the curve, so curves go in and curves come out.

import * as F from "./freeform.js";
import * as P from "./pathdata.js";

const same = (a, b) => Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9;
const copy = (anchor) => ({ at: [...anchor.at], in: anchor.in && [...anchor.in], out: anchor.out && [...anchor.out] });
const lerp = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];

// -- a path's pieces, as anchors --

// Segments as pieces: each its anchors -- { at, in, out }, `in` the handle a curve comes into it
// by and `out` the one it leaves by, null where it has none -- and whether it is closed.
export function piecesOf(segments) {
  const pieces = [];
  let piece = null;
  for (const segment of segments) {
    const kind = segment[0];
    if (kind === "M") { piece = { anchors: [{ at: [segment[1], segment[2]], in: null, out: null }], closed: false }; pieces.push(piece); }
    else if (!piece) continue;
    else if (kind === "L") piece.anchors.push({ at: [segment[1], segment[2]], in: null, out: null });
    else if (kind === "C") {
      const last = piece.anchors[piece.anchors.length - 1], first = [segment[1], segment[2]], second = [segment[3], segment[4]], end = [segment[5], segment[6]];
      last.out = same(first, last.at) ? null : first;
      piece.anchors.push({ at: end, in: same(second, end) ? null : second, out: null });
    } else {
      piece.closed = true;
      const anchors = piece.anchors, first = anchors[0], last = anchors[anchors.length - 1];
      // (A piece drawn back to its start before it is closed: its start is its end.)
      if (anchors.length > 1 && same(first.at, last.at)) { first.in = last.in; anchors.pop(); }
    }
  }
  return pieces;
}

const joint = (a, b) => (a.out || b.in ? ["C", ...(a.out || a.at), ...(b.in || b.at), ...b.at] : ["L", ...b.at]);

// Pieces as segments again: a curve where either end has a handle, else a line.
export function segmentsFrom(pieces) {
  const out = [];
  for (const { anchors, closed } of pieces) {
    if (!anchors.length) continue;
    out.push(["M", ...anchors[0].at]);
    for (let n = 1; n < anchors.length; n += 1) out.push(joint(anchors[n - 1], anchors[n]));
    if (closed) {
      const last = anchors[anchors.length - 1], first = anchors[0];
      if (anchors.length > 1 && (last.out || first.in)) out.push(joint(last, first));
      out.push(["Z"]);
    }
  }
  return out;
}
export const dataOf = (pieces) => P.written(segmentsFrom(pieces));

// Whether an anchor is smooth: both handles, opposite each other (as a pen's drag makes them).
export function smooth(anchor) {
  if (!anchor.in || !anchor.out) return false;
  const ux = anchor.in[0] - anchor.at[0], uy = anchor.in[1] - anchor.at[1], vx = anchor.out[0] - anchor.at[0], vy = anchor.out[1] - anchor.at[1];
  const lu = Math.hypot(ux, uy), lv = Math.hypot(vx, vy);
  if (!lu || !lv) return false;
  return (ux * vx + uy * vy) / (lu * lv) < 0 && Math.abs(ux * vy - uy * vx) / (lu * lv) < 0.02;
}

// The anchors either side of the nth of a piece: none past an open piece's ends.
function beside(piece, n) {
  const { anchors, closed } = piece, count = anchors.length;
  const before = n > 0 ? anchors[n - 1] : closed && count > 1 ? anchors[count - 1] : null;
  const after = n < count - 1 ? anchors[n + 1] : closed && count > 1 ? anchors[0] : null;
  return [before, after];
}

// The nth anchor of a piece made smooth (handles along the way through it, a third of the way
// to each neighbour), or a corner (no handles) if it was smooth or had any.
export function toggled(piece, n) {
  const anchor = piece.anchors[n];
  if (anchor.in || anchor.out) return { at: [...anchor.at], in: null, out: null };
  const [before, after] = beside(piece, n);
  if (!before && !after) return copy(anchor);
  const from = before ? before.at : anchor.at, to = after ? after.at : anchor.at;
  const dx = to[0] - from[0], dy = to[1] - from[1], length = Math.hypot(dx, dy) || 1, ux = dx / length, uy = dy / length;
  const back = before ? Math.hypot(anchor.at[0] - before.at[0], anchor.at[1] - before.at[1]) / 3 : 0;
  const ahead = after ? Math.hypot(after.at[0] - anchor.at[0], after.at[1] - anchor.at[1]) / 3 : 0;
  return { at: [...anchor.at], in: back ? [anchor.at[0] - ux * back, anchor.at[1] - uy * back] : null, out: ahead ? [anchor.at[0] + ux * ahead, anchor.at[1] + uy * ahead] : null };
}

// The cubic from the nth anchor of a piece to the next: its four points.
export function cubicOf(piece, n) {
  const { anchors } = piece, a = anchors[n], b = anchors[(n + 1) % anchors.length];
  return [a.at, a.out || a.at, b.in || b.at, b.at];
}
const straight = (piece, n) => { const a = piece.anchors[n], b = piece.anchors[(n + 1) % piece.anchors.length]; return !a.out && !b.in; };
export function cubicAt([p0, p1, p2, p3], t) {
  const u = 1 - t, a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t;
  return [a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]];
}
// A cubic cut at t: its two halves' points.
export function cutCubic([p0, p1, p2, p3], t) {
  const a = lerp(p0, p1, t), b = lerp(p1, p2, t), c = lerp(p2, p3, t), d = lerp(a, b, t), e = lerp(b, c, t), f = lerp(d, e, t);
  return [[p0, a, d, f], [f, e, c, p3]];
}
// The stretch of a cubic from t0 to t1 (either way round): its four points.
export function stretch(cubic, t0, t1) {
  if (t0 > t1) return stretch(cubic, t1, t0).reverse();
  let piece = cubic;
  if (t1 < 1) piece = cutCubic(piece, t1)[0];
  if (t0 > 0) piece = cutCubic(piece, t0 / (t1 || 1))[1];
  return piece;
}
const segmentsOfPiece = (piece) => piece.anchors.length - (piece.closed ? 0 : 1);

// A point added to a piece on its nth segment, at t along it, the curve's shape kept.
export function splitAt(piece, n, t) {
  const anchors = piece.anchors.map(copy), count = anchors.length, m = (n + 1) % count;
  const a = anchors[n], b = anchors[m];
  let made;
  if (straight(piece, n)) made = { at: lerp(a.at, b.at, t), in: null, out: null };
  else {
    const [[, q1, q2, mid], [, r1, r2]] = cutCubic(cubicOf(piece, n), t);
    a.out = same(q1, a.at) ? null : q1;
    b.in = same(r2, b.at) ? null : r2;
    made = { at: mid, in: q2, out: r1 };
  }
  anchors.splice(n + 1, 0, made);
  return { anchors, closed: piece.closed };
}

// Where on any piece's segments `point` is nearest: { piece, n, t, at, distance }.
export function nearestOn(pieces, point) {
  let best = null;
  const consider = (piece, n, t, at) => {
    const far = Math.hypot(at[0] - point[0], at[1] - point[1]);
    if (!best || far < best.distance) best = { piece, n, t, at, distance: far };
  };
  pieces.forEach((piece, p) => {
    for (let n = 0; n < segmentsOfPiece(piece); n += 1) {
      const cubic = cubicOf(piece, n);
      if (straight(piece, n)) {
        const [a, , , b] = cubic, dx = b[0] - a[0], dy = b[1] - a[1], length = dx * dx + dy * dy;
        const t = length ? Math.max(0, Math.min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length)) : 0;
        consider(p, n, t, lerp(a, b, t));
        continue;
      }
      let at = 0, far = Infinity;
      for (let k = 0; k <= 32; k += 1) { const q = cubicAt(cubic, k / 32), d = Math.hypot(q[0] - point[0], q[1] - point[1]); if (d < far) { far = d; at = k / 32; } }
      let low = Math.max(0, at - 1 / 32), high = Math.min(1, at + 1 / 32);
      for (let k = 0; k < 30; k += 1) {
        const a = low + (high - low) / 3, b = high - (high - low) / 3;
        const da = Math.hypot(...cubicAt(cubic, a).map((v, i) => v - point[i])), db = Math.hypot(...cubicAt(cubic, b).map((v, i) => v - point[i]));
        if (da < db) high = b; else low = a;
      }
      const t = (low + high) / 2;
      consider(p, n, t, cubicAt(cubic, t));
    }
  });
  return best;
}

// Pieces less the anchors `gone` holds ("piece:anchor"): a piece left with fewer than two goes.
export function without(pieces, gone) {
  return pieces.map((piece, p) => ({ anchors: piece.anchors.filter((_, n) => !gone.has(`${p}:${n}`)).map(copy), closed: piece.closed }))
    .filter((piece) => piece.anchors.length >= 2);
}

// -- a path in its frame: mirrored, turned about its box's middle --

// How a path's own points are placed on the page: about `centre`, mirrored (sx, sy), turned.
export function frameOf(spec, made) {
  const [x, y, w, h] = made.box, flip = spec.flip || null;
  return { centre: [x + w / 2, y + h / 2], turn: Number(made.turn || 0), sx: flip === "horizontal" || flip === "both" ? -1 : 1, sy: flip === "vertical" || flip === "both" ? -1 : 1 };
}
export function toPage(frame, [px, py]) {
  const [cx, cy] = frame.centre;
  return F.turned([cx + frame.sx * (px - cx), cy + frame.sy * (py - cy)], frame.centre, frame.turn);
}
export function toLocal(frame, point) {
  const [cx, cy] = frame.centre, [ux, uy] = F.unturned(point, frame.centre, frame.turn);
  return [cx + frame.sx * (ux - cx), cy + frame.sy * (uy - cy)];
}
const moveAll = (segments, dx, dy) => segments.map(([kind, ...values]) => [kind, ...values.map((value, n) => value + (n % 2 ? dy : dx))]);
// Segments edited in a path's own frame, moved so that what was not edited stays where it is
// on the page: a turned or mirrored path turns about its box's middle, which an edit moves.
export function steadied(frame, segments) {
  if (!frame.turn && frame.sx === 1 && frame.sy === 1) return segments;
  const [left, top, right, bottom] = P.extent(segments), shift = [(left + right) / 2 - frame.centre[0], (top + bottom) / 2 - frame.centre[1]];
  const placed = F.turned([frame.sx * shift[0], frame.sy * shift[1]], [0, 0], frame.turn);
  return moveAll(segments, placed[0] - shift[0], placed[1] - shift[1]);
}

// -- Make Editable: any shape as a path of the same outline --

const STYLE = ["fill", "fill_opacity", "line", "line_width", "dash", "cap", "join", "start", "end", "head_size", "shadow", "opacity"];
const PLACING = new Set(["kind", "at", "size", "from", "to", "points", "closed", "tail", "flip", "width", "rotate", "d", "fill_rule"]);

// Whether a shape may be made a path: any but words, and a path already.
export const editableKind = (spec) => Boolean(spec) && (spec.kind === "group" ? (spec.shapes || []).some(editableKind) : spec.kind !== "text" && spec.kind !== "path" && F.KINDS.includes(spec.kind));

const TEXT = ["text", "font_size", "bold", "italic", "colour", "font", "align", "valign", "padding"];
// A shape's look, as a path would say it: what it is painted with where a path's own would be
// another, and its words as written. (A group's, its first shape's.)
export function styleOf(spec) {
  if (spec?.kind === "group") return styleOf((spec.shapes || [])[0] || { kind: "rectangle" });
  const look = F.normalised(spec), theirs = F.defaults("path"), out = {};
  for (const key of STYLE) if (JSON.stringify(look[key]) !== JSON.stringify(theirs[key])) out[key] = look[key];
  for (const key of TEXT) if (spec[key] !== undefined) out[key] = spec[key];
  return out;
}

// `spec` as a path of the same outline -- where it is drawn (its ends where they are glued:
// `made`, its geometry as drawn), turned as it was, its look as it was (a line's arrowheads
// too) -- its own settings (a corner, a slant) gone into its outline; a group's shapes each.
export function editable(spec, made = null) {
  if (spec.kind === "group") return { ...spec, shapes: (spec.shapes || []).map((child) => editable(child)) };
  if (!editableKind(spec)) return spec;
  made ||= F.geometry(spec);
  const look = F.normalised(spec), bare = F.family(spec.kind) === "line" || F.family(spec.kind) === "points" ? F.geometry({ ...spec, start: "none", end: "none" }, made.ends) : made;
  const turn = Number(bare.turn || 0);
  const segments = steadied({ centre: F.centreOf(bare), turn, sx: 1, sy: 1 }, bare.segments.map((segment) => [...segment]));
  const own = new Set(Object.keys(F.PARAMETERS[spec.kind] || {}));
  const out = { kind: "path", ...(spec.id !== undefined ? { id: spec.id } : {}), d: P.written(segments) };
  for (const [key, value] of Object.entries(spec)) if (!PLACING.has(key) && !own.has(key) && key !== "id") out[key] = value;
  if (turn) out.rotate = Math.round(turn * 1000) / 1000;
  // (Its look as drawn, where a path's own would be another.)
  const theirs = F.defaults("path");
  for (const key of STYLE) {
    if (JSON.stringify(look[key]) !== JSON.stringify(theirs[key])) out[key] = look[key];
    else if (!(key in spec)) delete out[key];
  }
  return out;
}

// -- combining shapes --

const GRID = 256;
export const OPERATIONS = ["union", "subtract", "intersect", "exclude"];

// A shape's outline on the page (its segments turned as it is), and the rule it is filled by;
// a group's shapes each.
export function outlinesOf(spec, made = null) {
  if (spec.kind === "group") return (spec.shapes || []).flatMap((child) => outlinesOf(child));
  made ||= F.geometry(spec);
  const centre = F.centreOf(made), turn = Number(made.turn || 0);
  const segments = made.segments.map(([kind, ...values]) => {
    if (!turn) return [kind, ...values];
    const placed = [];
    for (let n = 0; n < values.length; n += 2) placed.push(...F.turned([values[n], values[n + 1]], centre, turn));
    return [kind, ...placed];
  });
  return [{ segments, rule: spec.kind === "path" ? spec.fill_rule || "nonzero" : "nonzero" }];
}

const into = (point) => [Math.round(point[0] * GRID), Math.round(point[1] * GRID)];
const keyOf = (point) => `${point[0]},${point[1]}`;
const orient = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
const within = (a, b, p) => Math.min(a[0], b[0]) <= p[0] && p[0] <= Math.max(a[0], b[0]) && Math.min(a[1], b[1]) <= p[1] && p[1] <= Math.max(a[1], b[1]);

// Each outline cut into lines on the grid, each saying which shape it is of and what it is a
// stretch of: a line written as one (`line`), or a curve (`curve`, from t0 to t1).
function cutUp(shapes) {
  const curves = [], edges = [];
  let lines = 0;
  const add = (shape, from, to, source) => {
    const a = into(from), b = into(to);
    if (a[0] !== b[0] || a[1] !== b[1]) edges.push({ a, b, shape, source, splits: [] });
  };
  shapes.forEach(({ segments }, shape) => {
    let here = null, start = null;
    const close = () => { if (here && start && !same(here, start)) add(shape, here, start, { line: lines++ }); };
    for (const segment of segments) {
      const kind = segment[0];
      if (kind === "M") { close(); here = start = [segment[1], segment[2]]; }
      else if (kind === "L") { const to = [segment[1], segment[2]]; add(shape, here, to, { line: lines++ }); here = to; }
      else if (kind === "C") {
        const cubic = [here, [segment[1], segment[2]], [segment[3], segment[4]], [segment[5], segment[6]]], id = curves.push(cubic) - 1;
        let reach = 0;
        for (let n = 0; n < 3; n += 1) reach += Math.hypot(cubic[n + 1][0] - cubic[n][0], cubic[n + 1][1] - cubic[n][1]);
        const steps = Math.max(2, Math.min(96, Math.ceil(Math.sqrt(reach * 2))));
        let last = here;
        for (let n = 1; n <= steps; n += 1) {
          const point = n === steps ? cubic[3] : cubicAt(cubic, n / steps);
          add(shape, last, point, { curve: id, t0: (n - 1) / steps, t1: n / steps });
          last = point;
        }
        here = cubic[3];
      } else { close(); here = start; }
    }
    close();
  });
  return { curves, edges };
}

// Every crossing of two lines, and every end of one lying on another, marked on both.
function meet(edges) {
  const order = edges.map((edge, n) => n).sort((m, n) => Math.min(edges[m].a[0], edges[m].b[0]) - Math.min(edges[n].a[0], edges[n].b[0]));
  let active = [];
  for (const n of order) {
    const e = edges[n], left = Math.min(e.a[0], e.b[0]), right = Math.max(e.a[0], e.b[0]);
    const low = Math.min(e.a[1], e.b[1]), high = Math.max(e.a[1], e.b[1]);
    active = active.filter((m) => Math.max(edges[m].a[0], edges[m].b[0]) >= left);
    for (const m of active) {
      const f = edges[m];
      if (Math.max(f.a[1], f.b[1]) < low || Math.min(f.a[1], f.b[1]) > high) continue;
      const d1 = orient(f.a, f.b, e.a), d2 = orient(f.a, f.b, e.b), d3 = orient(e.a, e.b, f.a), d4 = orient(e.a, e.b, f.b);
      if (((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))) {
        const s = d1 / (d1 - d2), point = [Math.round(e.a[0] + (e.b[0] - e.a[0]) * s), Math.round(e.a[1] + (e.b[1] - e.a[1]) * s)];
        e.splits.push(point); f.splits.push(point);
      } else {
        if (d1 === 0 && within(f.a, f.b, e.a)) f.splits.push(e.a);
        if (d2 === 0 && within(f.a, f.b, e.b)) f.splits.push(e.b);
        if (d3 === 0 && within(e.a, e.b, f.a)) e.splits.push(f.a);
        if (d4 === 0 && within(e.a, e.b, f.b)) e.splits.push(f.b);
      }
    }
    active.push(n);
  }
}

// The lines cut where they meet, and those lying on one another made one: each { a, b } (a
// before b, as their points sort), its source, and what it adds to each shape's winding.
function pieces(edges) {
  const found = new Map();
  for (const edge of edges) {
    const { a, b } = edge, dx = b[0] - a[0], dy = b[1] - a[1], length = dx * dx + dy * dy;
    const along = (p) => ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length;
    const points = [a, ...edge.splits.filter((p) => !(p[0] === a[0] && p[1] === a[1]) && !(p[0] === b[0] && p[1] === b[1])), b]
      .map((p) => ({ p, u: along(p) })).sort((m, n) => m.u - n.u);
    for (let n = 1; n < points.length; n += 1) {
      const from = points[n - 1], to = points[n];
      if (from.p[0] === to.p[0] && from.p[1] === to.p[1]) continue;
      const source = edge.source.curve === undefined ? edge.source : {
        curve: edge.source.curve,
        t0: edge.source.t0 + (edge.source.t1 - edge.source.t0) * Math.max(0, Math.min(1, from.u)),
        t1: edge.source.t0 + (edge.source.t1 - edge.source.t0) * Math.max(0, Math.min(1, to.u)),
      };
      const forward = from.p[0] < to.p[0] || (from.p[0] === to.p[0] && from.p[1] < to.p[1]);
      const [x, y] = forward ? [from.p, to.p] : [to.p, from.p], key = `${keyOf(x)}|${keyOf(y)}`;
      let piece = found.get(key);
      if (!piece) {
        piece = { a: x, b: y, adds: [], source: forward ? source : turnedSource(source) };
        found.set(key, piece);
      }
      piece.adds.push({ shape: edge.shape, way: forward ? 1 : -1 });
    }
  }
  return [...found.values()];
}
const turnedSource = (source) => (source.curve === undefined ? source : { curve: source.curve, t0: source.t1, t1: source.t0 });

// Each shape's winding at `point`: lines crossed by a ray from it towards +x, each as it runs.
function windings(bands, point, count) {
  const out = new Array(count).fill(0), [px, py] = point;
  for (const piece of bands.at(py)) {
    const { a, b } = piece;
    if ((a[1] > py) === (b[1] > py)) continue;
    const x = a[0] + (py - a[1]) * (b[0] - a[0]) / (b[1] - a[1]);
    if (x <= px) continue;
    const up = b[1] > a[1] ? 1 : -1;
    for (const { shape, way } of piece.adds) out[shape] += up * way;
  }
  return out;
}
function banded(found) {
  let low = Infinity, high = -Infinity;
  for (const { a, b } of found) { low = Math.min(low, a[1], b[1]); high = Math.max(high, a[1], b[1]); }
  const count = Math.max(1, Math.min(512, Math.ceil(Math.sqrt(found.length)))), size = (high - low) / count || 1;
  const bands = Array.from({ length: count }, () => []);
  const band = (y) => Math.max(0, Math.min(count - 1, Math.floor((y - low) / size)));
  for (const piece of found) for (let n = band(Math.min(piece.a[1], piece.b[1])); n <= band(Math.max(piece.a[1], piece.b[1])); n += 1) bands[n].push(piece);
  return { at: (y) => bands[band(y)] };
}

const RESULTS = {
  union: (inside) => inside.some(Boolean),
  intersect: (inside) => inside.every(Boolean),
  subtract: (inside) => inside[0] && !inside.slice(1).some(Boolean),
  exclude: (inside) => inside.filter(Boolean).length % 2 === 1,
};

// Shapes combined -- `shapes`, bottom first, each { segments (on the page), rule } -- by
// `operation`: union, subtract (the bottom one less the others), intersect, exclude (what an
// odd number of them cover). Its segments on the page, filled even-odd; null where nothing is
// left.
export function combined(operation, shapes) {
  const test = RESULTS[operation];
  if (!test || shapes.length < 2) return null;
  const { curves, edges } = cutUp(shapes);
  meet(edges);
  const found = pieces(edges), bands = banded(found);
  const filled = (winding) => winding.map((count, n) => (shapes[n].rule === "evenodd" ? Math.abs(count) % 2 === 1 : count !== 0));
  const kept = [];
  for (const piece of found) {
    const { a, b } = piece, dx = b[0] - a[0], dy = b[1] - a[1], length = Math.hypot(dx, dy), nx = -dy / length * 0.02, ny = dx / length * 0.02;
    const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const left = test(filled(windings(bands, [mid[0] + nx, mid[1] + ny], shapes.length)));
    const right = test(filled(windings(bands, [mid[0] - nx, mid[1] - ny], shapes.length)));
    if (left === right) continue;
    kept.push(left ? { from: a, to: b, source: piece.source } : { from: b, to: a, source: turnedSource(piece.source) });
  }
  if (!kept.length) return null;
  return written(rings(kept), curves);
}

// The kept lines joined into rings, end to start: where several leave a point, the one turning
// least from the way in.
function rings(kept) {
  const leaving = new Map();
  for (const edge of kept) {
    const key = keyOf(edge.from);
    if (!leaving.has(key)) leaving.set(key, []);
    leaving.get(key).push(edge);
  }
  const used = new Set(), out = [];
  for (const first of kept) {
    if (used.has(first)) continue;
    const ring = [first];
    used.add(first);
    let edge = first;
    for (let guard = 0; guard < kept.length; guard += 1) {
      if (edge.to[0] === first.from[0] && edge.to[1] === first.from[1]) break;
      const choices = (leaving.get(keyOf(edge.to)) || []).filter((next) => !used.has(next));
      if (!choices.length) break;
      let next = choices[0];
      if (choices.length > 1) {
        const back = Math.atan2(edge.from[1] - edge.to[1], edge.from[0] - edge.to[0]);
        let least = Infinity;
        for (const choice of choices) {
          let turn = Math.atan2(choice.to[1] - choice.from[1], choice.to[0] - choice.from[0]) - back;
          while (turn <= 0) turn += 2 * Math.PI;
          while (turn > 2 * Math.PI) turn -= 2 * Math.PI;
          if (turn < least) { least = turn; next = choice; }
        }
      }
      used.add(next);
      ring.push(next);
      edge = next;
    }
    if (ring.length > 1) out.push(ring);
  }
  return out;
}

// Rings as segments: a run of lines of one curve, one after another along it, that stretch of
// the curve; lines of one line, one line.
function written(found, curves) {
  const out = [], point = ([x, y]) => [x / GRID, y / GRID];
  const follows = (a, b) => (a.source.curve !== undefined && a.source.curve === b.source.curve && Math.abs(a.source.t1 - b.source.t0) < 1e-9)
    || (a.source.line !== undefined && a.source.line === b.source.line);
  for (const ring of found) {
    // (Begun where a run begins, so none is cut in two by where the ring starts.)
    let start = ring.findIndex((edge, n) => !follows(ring[(n + ring.length - 1) % ring.length], edge));
    if (start < 0) start = 0;
    const ordered = [...ring.slice(start), ...ring.slice(0, start)];
    out.push(["M", ...point(ordered[0].from)]);
    for (let n = 0; n < ordered.length;) {
      let m = n;
      while (m + 1 < ordered.length && follows(ordered[m], ordered[m + 1])) m += 1;
      const first = ordered[n], last = ordered[m], end = point(last.to);
      if (first.source.curve !== undefined) {
        const [, c1, c2] = stretch(curves[first.source.curve], first.source.t0, last.source.t1);
        out.push(["C", ...c1, ...c2, ...end]);
      } else out.push(["L", ...end]);
      n = m + 1;
    }
    // (A last line back to where the ring began is its close.)
    const begun = point(ordered[0].from), last = out[out.length - 1];
    if (last[0] === "L" && same([last[1], last[2]], begun)) out.pop();
    out.push(["Z"]);
  }
  return out;
}
