// Zoom insets (flexo.insets): part of a picture, a figure or a part of one, shown magnified in
// a box of its own, a frame round that part and two lines joining them. Here as the page draws
// it while it is dragged -- its box, its region, what it shows (the slide's own drawing of what
// it magnifies, drawn again: <use>) -- number for number as flexo.insets draws it (a test runs
// both). Nothing here touches the page but `markup`'s answer, SVG put in it by its caller.

import * as F from "./freeform.js";

// The part an inset written without one shows: the middle.
export const REGION = [0.35, 0.35, 0.3, 0.3];

export function regionOf(spec) {
  const region = spec?.region;
  if (Array.isArray(region) && region.length === 4 && region.every(Number.isFinite) && region[2] > 0 && region[3] > 0) return region.map(Number);
  return [...REGION];
}

// `region` (fractions of `source`) on the page.
export function regionBox(source, region) {
  const [x, y, w, h] = source;
  return [x + region[0] * w, y + region[1] * h, region[2] * w, region[3] * h];
}

// The two lines joining the region to the box, from the region's corners on the side facing it
// to the box's facing them; none where they overlap (flexo.insets.connectors).
export function connectors(region, box) {
  const [rx, ry, rw, rh] = region, [bx, by, bw, bh] = box;
  const right = bx - (rx + rw), left = rx - (bx + bw), below = by - (ry + rh), above = ry - (by + bh);
  const across = Math.max(right, left), down = Math.max(below, above);
  if (across < 0 && down < 0) return [];
  if (across >= down) {
    if (right >= left) return [[[rx + rw, ry], [bx, by]], [[rx + rw, ry + rh], [bx, by + bh]]];
    return [[[rx, ry], [bx + bw, by]], [[rx, ry + rh], [bx + bw, by + bh]]];
  }
  if (below >= above) return [[[rx, ry + rh], [bx, by]], [[rx + rw, ry + rh], [bx + bw, by]]];
  return [[[rx, ry], [bx, by + bh]], [[rx + rw, ry], [bx + bw, by + bh]]];
}

// How the region is drawn in the box: its scale, and the offset after it -- filling the box,
// centred where their proportions differ.
export function view(region, box) {
  const [rx, ry, rw, rh] = region, [bx, by, bw, bh] = box;
  const scale = Math.max(bw / Math.max(rw, 1e-9), bh / Math.max(rh, 1e-9));
  return { scale, offset: [bx + bw / 2 - scale * (rx + rw / 2), by + bh / 2 - scale * (ry + rh / 2)] };
}

// An inset placed: its box, its region on `source` (the box of what it shows part of).
export function placed(spec, source) {
  const box = [Number(spec.at[0]), Number(spec.at[1]), Math.max(Number(spec.size[0]), 0), Math.max(Number(spec.size[1]), 0)];
  const region = regionBox(source, regionOf(spec));
  const { scale, offset } = view(region, box);
  return { box, region, scale, offset, connectors: connectors(region, box) };
}

// How a piece is drawn (frame, connector): as it says, else as the box's outline.
export function piece(spec, name) {
  const made = F.normalised(spec);
  const line = made[`${name}_line`], width = made[`${name}_width`], dash = made[`${name}_dash`];
  return {
    line: line ?? made.line,
    line_width: width ?? Number(made.line_width || 0),
    dash: dash ?? (made.dash || "solid"),
    cap: "butt", join: "miter",
  };
}

// The region an inset shows set to `box` on the page (fractions of `source`, to four places),
// kept within what it shows part of.
export function regionFrom(box, source) {
  const [sx, sy, sw, sh] = source;
  const round = (value) => Math.round(value * 10000) / 10000;
  let w = Math.min(Math.max(box[2] / sw, 0.002), 1), h = Math.min(Math.max(box[3] / sh, 0.002), 1);
  let x = Math.min(Math.max((box[0] - sx) / sw, 0), 1 - w), y = Math.min(Math.max((box[1] - sy) / sh, 0), 1 - h);
  w = round(w); h = round(h); x = round(x); y = round(y);
  return [x, y, Math.min(w, round(1 - x)), Math.min(h, round(1 - y))];
}

// Where a new inset goes beside what it magnifies (`source`, in a page `frame`): to its right
// where there is room, else its left, below or above -- as large as the room there lets it
// be, at most four fifths of what it magnifies (and no smaller than a small one need be) --
// in the proportions of its region. Its region: the middle of it, a fifth across.
export function fresh(source, frame, { of, margin = 16 } = {}) {
  const region = [0.4, 0.4, 0.2, 0.2];
  const [sx, sy, sw, sh] = source, [fx, fy, fw, fh] = frame;
  const aspect = (region[2] * sw) / Math.max(region[3] * sh, 1e-9);
  const rooms = [
    { x: sx + sw + margin, y: fy + margin, w: fx + fw - margin - (sx + sw + margin), h: fh - 2 * margin },
    { x: fx + margin, y: fy + margin, w: sx - margin - (fx + margin), h: fh - 2 * margin },
    { x: fx + margin, y: sy + sh + margin, w: fw - 2 * margin, h: fy + fh - margin - (sy + sh + margin) },
    { x: fx + margin, y: fy + margin, w: fw - 2 * margin, h: sy - margin - (fy + margin) },
  ];
  const fit = (room) => {
    const most = Math.max(Math.min(room.w, room.h * aspect, Math.max(sw * 0.8, sh * 0.8, 120)), 0);
    return { w: most, h: most / aspect };
  };
  let best = null;
  for (const [n, room] of rooms.entries()) {
    const size = fit(room);
    if (size.w < 40 || size.h < 30) continue;
    // Beside it, centred on it as far as the room lets it be.
    const x = n < 2 ? room.x + (n === 1 ? room.w - size.w : 0) : Math.min(Math.max(sx + sw / 2 - size.w / 2, room.x), room.x + room.w - size.w);
    const y = n < 2 ? Math.min(Math.max(sy + sh / 2 - size.h / 2, room.y), room.y + room.h - size.h) : room.y + (n === 3 ? room.h - size.h : 0);
    best = { x, y, ...size };
    break;
  }
  // No room beside it: over its bottom right, half its size.
  if (!best) { const w = sw / 2, h = w / aspect; best = { x: sx + sw - w - 8, y: sy + sh - h - 8, w, h }; }
  const round = (value) => Math.round(value * 100) / 100;
  return { kind: "inset", of, region, at: [round(best.x), round(best.y)], size: [round(best.w), round(best.h)] };
}

// An inset whose box was sized: its region as tall again as the box's proportions make it,
// about its middle, within what it shows part of -- the view never stretched.
export function matched(spec, source) {
  const [, , sw, sh] = source, region = regionOf(spec), [bw, bh] = spec.size.map(Number);
  if (!(bw > 0 && bh > 0 && sw > 0 && sh > 0)) return spec;
  const tall = Math.min((region[2] * sw * bh / bw) / sh, 1);
  const wide = tall < (region[2] * sw * bh / bw) / sh ? (tall * sh * bw / bh) / sw : region[2];
  const middle = [region[0] + region[2] / 2, region[1] + region[3] / 2];
  const box = [source[0] + (middle[0] - wide / 2) * sw, source[1] + (middle[1] - tall / 2) * sh, wide * sw, tall * sh];
  return { ...spec, region: regionFrom(box, source) };
}

// The handles of an inset's region, on what it magnifies: a corner each, dragged to size it
// (in the box's proportions: ⌘, freely, the box following), and one in its middle to move it.
// Each as shapes.js's own handles are: where it is, and what dragging it to a point sets.
export function handles(spec, source) {
  const shown = placed(spec, source), [rx, ry, rw, rh] = shown.region, [, , bw, bh] = shown.box;
  const corners = { nw: [rx, ry], ne: [rx + rw, ry], se: [rx + rw, ry + rh], sw: [rx, ry + rh] };
  const across = { nw: "se", ne: "sw", se: "nw", sw: "ne" };
  const round = (value) => Math.round(value * 100) / 100;
  const out = Object.entries(corners).map(([name, at]) => ({
    at, kind: "size", cursor: name === "nw" || name === "se" ? "nwse-resize" : "nesw-resize", label: "Resize Zoom Region",
    title: "Drag to choose the part shown (⌘: any proportions)",
    set: (point, free) => {
      const fixed = corners[across[name]];
      let w = Math.max(Math.abs(point[0] - fixed[0]), 2), h = Math.max(Math.abs(point[1] - fixed[1]), 2);
      if (!free) { const ratio = bh / Math.max(bw, 1e-9); if (w * ratio > h) h = w * ratio; else w = h / ratio; }
      const x = point[0] < fixed[0] ? fixed[0] - w : fixed[0], y = point[1] < fixed[1] ? fixed[1] - h : fixed[1];
      const region = regionFrom([x, y, w, h], source);
      if (!free) return { region };
      // Free: the box as tall as the region's proportions make it.
      const [, , sw, sh] = source, ratio = (region[3] * sh) / Math.max(region[2] * sw, 1e-9);
      return { region, size: [round(bw), round(bw * ratio)] };
    },
  }));
  out.push({ at: [rx + rw / 2, ry + rh / 2], kind: "adjust", cursor: "move", label: "Move Zoom Region", title: "Drag to move the part shown",
    set: (point) => ({ region: regionFrom([point[0] - rw / 2, point[1] - rh / 2, rw, rh], source) }) });
  return out;
}

const escape = (text) => String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");

// An inset as SVG markup, as the page draws it: the frame round its region, the lines, its box
// filled, what it shows (`target`, the id of what it magnifies on the page, drawn again: a
// <use> whose `matrix` takes that drawing's units to the shapes'), its outline. `source`: the
// box of what it magnifies, in the shapes' units; none, its box alone.
export function markup(spec, made, roles = {}, { source = null, target = null, toShapes = null, clipId = "flexo-inset-clip" } = {}) {
  const normal = F.normalised(spec);
  made ||= F.geometry(normal);
  const parts = [];
  const shown = source ? placed(normal, source) : null;
  if (shown) {
    const [rx, ry, rw, rh] = shown.region;
    const frame = { kind: "rectangle", at: [rx, ry], size: [rw, rh], fill: "none", ...piece(normal, "frame") };
    parts.push(F.svg(frame, F.geometry(frame), roles));
    const joining = piece(normal, "connector");
    if (joining.line && joining.line !== "none" && joining.line_width > 0) {
      for (const [a, b] of shown.connectors) { const line = { kind: "line", from: a, to: b, ...joining }; parts.push(F.svg(line, F.geometry(line), roles)); }
    }
  }
  parts.push(F.svg({ ...normal, line: "none" }, made, roles));
  if (shown && target) {
    const [x, y, w, h] = shown.box;
    // `toShapes`: the drawing's own units to the shapes' (a DOMMatrix-like a..f), else the same.
    const unit = toShapes || { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 };
    const k = shown.scale, [ox, oy] = shown.offset;
    const m = [k * unit.a, k * unit.b, k * unit.c, k * unit.d, k * unit.e + ox, k * unit.f + oy];
    parts.push(`<clipPath id="${escape(clipId)}"><rect x="${x}" y="${y}" width="${w}" height="${h}"/></clipPath>`
      + `<g clip-path="url(#${escape(clipId)})"><use href="#${escape(target)}" transform="matrix(${m.join(" ")})"/></g>`);
  }
  parts.push(F.svg({ ...normal, fill: "none", shadow: false }, made, roles));
  const fade = Number(normal.opacity ?? 1) < 1 ? ` opacity="${Number(normal.opacity)}"` : "";
  return `<g${fade}>${parts.join("")}</g>`;
}
