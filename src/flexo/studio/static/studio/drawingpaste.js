// A drawing pasted, dropped or chosen -- Inkscape's, Illustrator's, Affinity's, a browser's,
// a PDF's page -- made the page's own shapes (flexo.svgimport, by the studio): every box,
// line, arrow, curve and word of it a shape, editable piece by piece, in one group, chosen,
// one step to undo ("Paste Drawing"). Its colours are the theme's where they are the theme's
// (Paste with Original Colours keeps them as drawn), and what no shape draws -- a picture, a
// blur, a clip -- is kept as a picture in its place.
//
// Paste as Picture (⌥⇧⌘V) places it as the one picture it was before: its words and colours
// restyled where it is placed, nothing else. A drawing of more pieces than editing one by
// one is for (SHAPES_AT_MOST, said by the studio) is placed as a picture whichever way it
// came. Dropped or chosen, an SVG is shapes and a PDF's (an Illustrator file's) page a
// picture -- its words, read from the PDF as outlines and parts drawn apart, would be
// pictures among the shapes, and a PDF is most often a plot to show as it is -- and the
// other way is offered beside the note that says what was done.
//
// The host is what holds the shapes: `studio`; `shapes` (its shape editor: paste, pointAt);
// `place()` ({ centre, fit } or { at }, in the shapes' units: where it goes); `markup`
// ("slide" or "figure"); `roles()` (the theme's colours); `asPicture(file)` (the page's own
// way to add a picture's file, a promise); `taken()` (names the page has already, a figure's
// parts', which no shape may take).

import { h, toast } from "./ui.js";
import { svgOfWords } from "./clipboard.js";

export const DRAWING_FILE = /\.(svg|pdf|ai)$/i;

const svgFile = (svg, name = "drawing.svg") => new File([svg], name, { type: "image/svg+xml" });

// The drawing on the clipboard now, as an SVG file (null if there is none): the Mac app's
// (clipboard_drawing reads Inkscape's flavours), else the browser's own, where it lets the
// page read it.
export async function clipboardDrawing() {
  const app = globalThis.pywebview?.api;
  if (app?.clipboard_drawing) {
    try {
      const svg = await app.clipboard_drawing();
      if (svg) return svgFile(svg);
    } catch { /* the app's clipboard unread: the browser's, below */ }
  }
  try {
    for (const item of (await navigator.clipboard?.read?.()) || []) {
      if (item.types.includes("image/svg+xml")) return svgFile(await (await item.getType("image/svg+xml")).text());
      if (item.types.includes("text/plain")) {
        const words = svgOfWords(await (await item.getType("text/plain")).text());
        if (words) return svgFile(words);
      }
    }
  } catch { /* not allowed here */ }
  try {
    const words = svgOfWords(await navigator.clipboard?.readText?.());
    if (words) return svgFile(words);
  } catch { /* not allowed here */ }
  return null;
}

export function drawingPaster(host) {
  const { studio } = host;
  let busy = false;

  // Shapes made of `file` (an SVG, or a PDF's or an Illustrator file's page) and added in
  // one step, or -- too many to edit one by one, or no drawing that reads -- the picture it
  // is. `how`: "paste" or "add" (a drop, a choice); `exact`: its colours as drawn.
  async function shapesOf(file, { how = "paste", exact = false } = {}) {
    if (busy) return false;
    busy = true;
    const label = how === "paste" ? "Paste Drawing" : "Add Drawing";
    try {
      const request = { file: studio.file, name: file.name, markup: host.markup || "slide", roles: host.roles?.() || studio.info?.roles || null, exact,
        // (Names the page has already -- a figure's parts' -- that no shape may take.)
        taken: host.taken?.() || [], ...host.place() };
      // (A file in the folder already -- one chosen -- is read there; one dropped or pasted,
      // an SVG's words sent, a PDF saved beside the document first.)
      if (file.path) request.path = file.path;
      else if (/\.svg$/i.test(file.name) || file.type === "image/svg+xml") request.svg = await file.text();
      else request.path = await studio.upload(file);
      let made;
      try {
        made = await studio.api("/api/import-drawing", request);
      } catch (error) {
        made = { whole: true, why: String(error?.message || error || "") };
      }
      if (made.whole || !made.shapes?.length) {
        await host.asPicture(file);
        const why = made.count ? `${made.count.toLocaleString()} pieces are more than are edited one by one: placed as a picture.` : made.why || "The drawing is placed as a picture.";
        toast(why, { icon: "image", seconds: 5 });
        return true;
      }
      host.shapes.paste({ what: "shapes", shapes: made.shapes, source: "drawing" }, { label });
      const entry = studio.past[studio.past.length - 1];
      const pieces = made.shapes.length === 1 && made.shapes[0].kind === "group" ? made.count - 1 : made.count;
      const kept = made.kept?.length ? ` · ${made.kept.length} kept as ${made.kept.length === 1 ? "a picture" : "pictures"}` : "";
      const undo = h("button.toast-action", { type: "button", onclick: async () => {
        note.remove();
        // (Only while the paste is the last change: taken back, the picture in its place.)
        if (studio.past[studio.past.length - 1] !== entry) { toast("The drawing was changed since: undo it first.", { icon: "info" }); return; }
        studio.undo();
        studio.future.pop();
        await host.asPicture(file);
      } }, "Place as Picture");
      const note = toast(h("span", {}, `${how === "paste" ? "Pasted" : "Added"} as ${pieces} ${pieces === 1 ? "shape" : "shapes"}${kept}`, " ", undo), { icon: "shape", seconds: 6 });
      if (made.approximated?.length || made.kept?.length) note.title = [...(made.kept || []), ...(made.approximated || [])].join("\n");
      return true;
    } finally {
      busy = false;
    }
  }

  // A file dropped or chosen: an SVG as shapes; a PDF's page as a picture, shapes offered.
  async function add(file) {
    if (!/\.(pdf|ai)$/i.test(file.name || file.path || "")) return shapesOf(file, { how: "add" });
    await host.asPicture(file);
    const entry = studio.past[studio.past.length - 1];
    const make = h("button.toast-action", { type: "button", onclick: async () => {
      note.remove();
      if (studio.past[studio.past.length - 1] !== entry) { toast("The picture was changed since: undo it first.", { icon: "info" }); return; }
      studio.undo();
      studio.future.pop();
      await shapesOf(file, { how: "add" });
    } }, "Make Editable Shapes");
    const note = toast(h("span", {}, "Added as a picture", " ", make), { icon: "image", seconds: 6 });
    return true;
  }

  // Paste as Picture and Paste with Original Colours: the drawing on the clipboard.
  async function fromClipboard(how) {
    const file = await clipboardDrawing();
    if (!file) { toast("There’s no drawing on the clipboard. Copy one in Inkscape, Illustrator or a browser first.", { icon: "info", seconds: 4 }); return; }
    if (how === "picture") await host.asPicture(file);
    else await shapesOf(file, { exact: true });
  }

  // The commands the page lists (its palette, the Mac app's Edit menu).
  const commands = () => [
    { icon: "image", label: "Paste as Picture", keys: "⌥⇧⌘V", hint: "A drawing on the clipboard, as one picture", run: () => fromClipboard("picture") },
    { icon: "paste", label: "Paste with Original Colours", hint: "A drawing on the clipboard, as shapes in its own colours", run: () => fromClipboard("exact") },
  ];

  // ⌥⇧⌘V in a browser (the Mac app's menu has it): Paste as Picture.
  function key(event) {
    if (!(event.metaKey || event.ctrlKey) || !event.altKey || !event.shiftKey || event.key.toLowerCase() !== "v") return false;
    event.preventDefault();
    fromClipboard("picture");
    return true;
  }

  return { shapesOf, add, fromClipboard, commands, key };
}
