// The colours of the shapes chosen (shapes.js), for Set Colour… (⇧⌘C, colourkey.js): their
// Fill (closed shapes), their Outline (a line's Colour) and their Text, each changed as the
// inspector changes it and named as it names it ("Change Fill") -- the main one a closed
// shape's fill, a line's colour, a text box's words. Chosen together, a box and a line are
// coloured each by its own: the box's fill, the line's line ("Colour").

import * as F from "./freeform.js";
import { boxAround } from "./hexcolour.js";

const leaves = (spec) => (spec?.kind === "group" ? (spec.shapes || []).flatMap(leaves) : spec ? [spec] : []);

// Which of a shape's colours is the one it is seen by: "fill", "line" or "colour" (its words).
export function mainPaint(spec) {
  if (spec.kind === "text") return "colour";
  if (F.isClosed(spec) && !(spec.kind === "path" && safeOpen(spec))) return "fill";
  return "line";
}
function safeOpen(spec) {
  try { return F.pathOpen(spec); } catch { return false; }
}

// A shape (or a group, each of its own) given `hex` in the colour it is seen by.
export function paintedMain(spec, hex, alpha = null) {
  if (spec.kind === "group") return { ...spec, shapes: (spec.shapes || []).map((each) => paintedMain(each, hex, alpha)) };
  const out = { ...spec };
  const paint = mainPaint(spec);
  out[paint] = hex;
  const opacity = paint === "fill" ? "fill_opacity" : paint === "line" ? "line_opacity" : null;
  if (opacity && alpha !== null) { if (alpha >= 1) delete out[opacity]; else out[opacity] = alpha; }
  return out;
}

const NAMES = { fill: "Fill", line: "Outline", colour: "Text" };

// The theme's colours a shape takes by name (`roles`, its palette's: role -> colour), as its
// panel offers them (shapes.js): a fill's tints, strong colours, grey, paper, muted and ink; a
// line's (and words') strong colours, muted, ink and paper. [{ value, colour }].
export function paintNames(roles = {}, paint = "line") {
  const tones = [1, 2, 3, 4, 5, 6].filter((n) => roles[`tone-${n}-stroke`]);
  const tone = (n) => (n === 1 ? "accent" : `accent${n}`);
  const names = paint === "fill" ? [...tones.map((n) => `${tone(n)}-fill`), ...tones.map(tone), "grey", "paper", "muted", "ink"]
    : [...tones.map(tone), "muted", "ink", "paper"];
  return names.filter((name) => roles[F.roleOf(name)]).map((value) => ({ value, colour: F.paintOf(value, roles) }));
}

// The shapes chosen as a kind of colourKey's: null with none chosen (or words being typed).
export function shapeColours(shapes) {
  if (!shapes || shapes.typing?.()) return null;
  const specs = shapes.specs?.() || [];
  if (!specs.length) return null;
  const flat = specs.flatMap(leaves).map((spec) => F.normalised(spec));
  if (!flat.length) return null;
  const shared = (key) => { const values = flat.map((spec) => spec[key]); return values.every((value) => value === values[0]) ? values[0] : undefined; };
  const linesAll = flat.every((spec) => F.family(spec.kind) === "line" || (F.family(spec.kind) === "points" && !spec.closed));
  const closedAny = flat.some((spec) => F.isClosed(spec) || spec.kind === "text");
  const opacity = (key, alpha) => (alpha !== null ? { [key]: alpha } : {});
  const roles = shapes.roles?.() || {};
  const fills = paintNames(roles, "fill"), lines = paintNames(roles, "line");
  const colours = [];
  if (closedAny) colours.push({ paint: "fill", name: "Fill", value: shared("fill"), offered: fills, set: (hex, alpha) => shapes.set({ fill: hex, ...opacity("fill_opacity", alpha) }, "Change Fill", "fill") });
  // (Lines alone are seen by their line: its colour, "Colour of 2 Lines".)
  colours.push({ paint: "line", name: linesAll ? "Colour" : "Outline", value: shared("line"), offered: lines,
    set: (hex, alpha) => shapes.set({ line: hex, ...opacity("line_opacity", alpha) }, linesAll ? "Change Line" : "Change Outline", "line") });
  if (!specs.some((spec) => spec.kind === "group")) colours.push({ paint: "colour", name: "Text", value: shared("colour"), offered: lines, set: (hex) => shapes.set({ colour: hex }, "Change Text Colour") });
  const mains = new Set(flat.map(mainPaint));
  let main = 0;
  if (mains.size === 1) main = Math.max(0, colours.findIndex((colour) => colour.paint === [...mains][0]));
  else {
    // Each by the colour it is seen by: a box's fill, a line's line.
    colours.unshift({ paint: "main", name: "Colour", value: undefined, offered: lines,
      set: (hex, alpha) => shapes.change((list) => { for (const index of shapes.order()) if (list[index]) list[index] = paintedMain(list[index], hex, alpha); }, "Change Colour") });
  }
  return { noun: shapes.label?.() || `${specs.length} Shapes`, colours, main, names: NAMES };
}

// Where the shapes chosen are drawn, on the screen (in `page`, the node their drawing is in).
export function shapesBox(shapes, page) {
  const root = typeof page === "function" ? page() : page;
  if (!root) return null;
  const nodes = (shapes.ids?.() || []).map((id) => root.querySelector(`[id="${CSS.escape(id)}"]`));
  return boxAround(nodes);
}
