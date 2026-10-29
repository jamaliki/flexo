// Colours matched: those a page has drawn, counted (the picker's "On This Slide", "In This
// Figure"), a colour sampled from the screen put back to one of them -- or to a theme's colour
// by its name -- when it is as near as a screen's rounding leaves it, and a colour's hue,
// saturation and brightness, for the picker's plane.
//
// A colour sampled is the screen's: in a display's colour space (P3 on a Mac's own), turned
// back into sRGB and rounded, so a swatch Flexo drew in #1f77b4 may come back #1f77b5. Within
// STEP of a colour the document has (each of red, green and blue), it is that colour -- its
// name, where the control takes the theme's by name -- not a colour a step off it.
//
// The counting and the matching need no page: they are read in Node as they are in the studio.

import { parseColour } from "./hexcolour.js";

// How far apart a colour sampled may be from one drawn (out of 255, in each of red, green
// and blue) and still be taken for it: a display's rounding, P3's coarser steps and sRGB's.
export const STEP = 3;
// How many colours drawn the picker offers, the most used first.
export const USED_MOST = 16;

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

// "#rrggbb" as [r, g, b] (0-255); null for anything else.
export function rgbOf(hex) {
  const found = /^#([0-9a-f]{6})$/i.exec(String(hex || ""));
  if (!found) return null;
  const digits = found[1];
  return [0, 2, 4].map((at) => parseInt(digits.slice(at, at + 2), 16));
}

// [r, g, b] (0-255, any number) as "#rrggbb".
export function hexOfRgb(rgb) {
  return `#${rgb.map((value) => clamp(Math.round(value), 0, 255).toString(16).padStart(2, "0")).join("")}`;
}

// The most two colours differ by in any one of red, green and blue (out of 255); Infinity
// where either is no colour.
export function apart(one, other) {
  const a = rgbOf(one), b = rgbOf(other);
  if (!a || !b) return Infinity;
  return Math.max(...a.map((value, n) => Math.abs(value - b[n])));
}

// A colour's hue (0-360), saturation and brightness (0-1), as the picker's plane has them.
export function hsvOf(hex) {
  const rgb = rgbOf(hex);
  if (!rgb) return null;
  const [r, g, b] = rgb.map((value) => value / 255);
  const most = Math.max(r, g, b), least = Math.min(r, g, b), range = most - least;
  let h = 0;
  if (range) {
    if (most === r) h = 60 * (((g - b) / range) % 6);
    else if (most === g) h = 60 * ((b - r) / range + 2);
    else h = 60 * ((r - g) / range + 4);
  }
  return { h: (h + 360) % 360, s: most ? range / most : 0, v: most };
}

// The colour of a hue, saturation and brightness, as "#rrggbb".
export function hexOfHsv({ h, s, v }) {
  const hue = (((h % 360) + 360) % 360) / 60;
  const chroma = clamp(v, 0, 1) * clamp(s, 0, 1);
  const x = chroma * (1 - Math.abs((hue % 2) - 1));
  const low = clamp(v, 0, 1) - chroma;
  const [r, g, b] = hue < 1 ? [chroma, x, 0] : hue < 2 ? [x, chroma, 0] : hue < 3 ? [0, chroma, x]
    : hue < 4 ? [0, x, chroma] : hue < 5 ? [x, 0, chroma] : [chroma, 0, x];
  return hexOfRgb([r, g, b].map((value) => (value + low) * 255));
}

// A colour as a drawing writes it (fill="#1F77B4", "#17b", "rgb(31, 119, 180)", "white") as
// "#rrggbb"; null for none, a gradient (url(...)), currentColor and the like.
const SKIPPED = new Set(["none", "transparent", "currentcolor", "inherit", "context-fill", "context-stroke", ""]);
export function paintHex(text) {
  const words = String(text ?? "").trim();
  if (/^#[0-9a-f]{6}$/i.test(words)) return words.toLowerCase();
  const lower = words.toLowerCase();
  if (SKIPPED.has(lower) || lower.startsWith("url(") || lower.startsWith("var(")) return null;
  const read = parseColour(words);
  // (One drawn at no opacity at all is not a colour seen.)
  return read && read.alpha !== 0 ? read.hex : null;
}

// The colours of `paints` (as drawn: "#1f77b4", "white", none...) by how often each is drawn,
// the most first (the first drawn first among those drawn as often), `skip` left out, at most
// `limit`: ["#rrggbb", ...].
export function countPaints(paints, { skip = [], limit = USED_MOST } = {}) {
  const left = new Set([...skip].map(paintHex).filter(Boolean));
  const counts = new Map();
  for (const paint of paints) {
    const hex = paintHex(paint);
    if (!hex || left.has(hex)) continue;
    counts.set(hex, (counts.get(hex) || 0) + 1);
  }
  // (A Map keeps the order each was first drawn in: sorting is stable.)
  return [...counts].sort((a, b) => b[1] - a[1]).slice(0, limit).map(([hex]) => hex);
}

const PAINTED = "[fill], [stroke], [stop-color], [style*='fill'], [style*='stroke'], [style*='stop-color']";
const STYLED = /(?:^|;)\s*(fill|stroke|stop-color)\s*:\s*([^;]+)/gi;

// The paints of what `root` draws (an <svg>, or what holds one): each fill, stroke and
// gradient stop as written, in the order drawn.
export function paintsIn(root) {
  const paints = [];
  if (!root?.querySelectorAll) return paints;
  for (const node of root.querySelectorAll(PAINTED)) {
    for (const name of ["fill", "stroke", "stop-color"]) {
      const value = node.getAttribute(name);
      if (value) paints.push(value);
    }
    const style = node.getAttribute("style");
    if (style) for (const found of style.matchAll(STYLED)) paints.push(found[2]);
  }
  return paints;
}

// The colours `root` draws, the most used first (countPaints).
export function usedColours(root, options = {}) {
  return countPaints(paintsIn(root), options);
}

// The one of `candidates` ([{ value, hex }], the most wanted first: the theme's names before
// colours by their code) `hex` is taken for: the nearest within `step`, the earlier of two as
// near; null with none so near.
export function snapped(hex, candidates, step = STEP) {
  let best = null, nearest = Infinity;
  for (const candidate of candidates || []) {
    const gap = apart(hex, candidate?.hex);
    if (gap <= step && gap < nearest) { best = candidate; nearest = gap; }
  }
  return best;
}

// What a control is given for `hex`: the name of one of its theme's colours (`offered`:
// [{ value, colour }], as ui.swatches has them) drawn in that very colour, else `hex` itself.
export function valueFor(hex, offered = []) {
  const want = paintHex(hex);
  if (!want) return null;
  const named = (offered || []).find((item) => item && item.value !== null && typeof item.value === "string" && !/^#/.test(item.value) && paintHex(item.colour) === want);
  return named ? named.value : want;
}

// The colours a sample is put back to: the control's theme colours by their names first, then
// those the document draws, the rest of its theme's and those applied last, by their codes.
export function candidatesFor({ offered = [], used = [], theme = [], recent = [] } = {}) {
  const list = [];
  const seen = new Set();
  const add = (value, colour) => {
    const hex = paintHex(colour);
    if (!hex || seen.has(`${value}|${hex}`)) return;
    seen.add(`${value}|${hex}`);
    list.push({ value, hex });
  };
  for (const item of offered || []) if (item && typeof item.value === "string") add(item.value, item.colour);
  for (const colour of [...(used || []), ...(theme || []), ...(recent || [])]) add(paintHex(colour), colour);
  return list;
}

// A colour sampled from the screen, as the control is to take it: `hex` put back to the
// nearest of `candidates` within STEP (its name, or its exact code), else as sampled.
// { value, hex, matched }.
export function matchSample(hex, candidates, step = STEP) {
  const sampled = paintHex(hex);
  if (!sampled) return null;
  const found = snapped(sampled, candidates, step);
  return found ? { value: found.value, hex: found.hex, matched: true } : { value: sampled, hex: sampled, matched: false };
}
