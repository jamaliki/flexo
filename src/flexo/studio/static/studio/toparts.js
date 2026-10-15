// Convert to Figure Parts: shapes drawn as a diagram -- boxes with words, arrows between them,
// words alone, a box round some with a title -- made a figure's own parts, laid out and themed
// as anything built in flexo (flexo.recognise). Over a figure the shapes chosen become its parts
// (figure/overlay.js); on a slide, a figure of their own on it (the deck editor).

import * as F from "/static/studio/freeform.js";

export const CONVERT = "Convert to Figure Parts";

// Shapes that mark a diagram up, whatever words they have: kept as shapes (flexo.recognise's
// NOT_PARTS).
const MARKS = new Set(["highlight", "ring", "bubble", "check", "cross", "plus", "star"]);

// Whether shapes chosen hold anything a part could be made of: a closed shape (but a mark), or
// words alone. (A line alone joins nothing; what is made is the server's to say.)
export function convertible(specs) {
  const leaves = (specs || []).flatMap(function leaves(spec) {
    return spec?.kind === "group" ? (spec.shapes || []).flatMap(leaves) : spec ? [spec] : [];
  });
  return leaves.some((spec) => (spec.kind === "text" && String(spec.text ?? "").trim())
    || (F.isClosed(spec) && !MARKS.has(spec.kind)));
}

// The command, for the palette, the shapes' right-click menu (`menu`) and the Mac app's
// Format menu, which runs it by its label.
export const convertCommand = (run, hint) => ({
  icon: "figure", label: CONVERT, hint: hint ? `${hint}: made the figure’s own shapes and lines` : "Made the figure’s own shapes and lines", menu: true, run,
});
