// The keys that matter now, for the help bar along the foot of the studio's window
// (helpbar.js): for what is being done -- a drag, words typed, a find, a picture cropped, a
// path drawn -- and else for what is chosen, the most to the point first, a keycap and a word
// or two each, no more than seven. Each key is written as the Keyboard Shortcuts sheet writes
// it (shell.js's SHORTCUTS: "⇧ ⌘ N", "↩ ⇧ ↩") and drawn as its keycaps are (`chords`), and
// each is there in the sheet, among the rows of the groups the context names
// (tests/unit/test_helpbar.py holds the two to each other).
//
// What is being done is a plain object, said by the studio's shell and the document's editor
// together (helpbar.js, an editor's `studio.help()`):
//   hidden                  presenting, a sheet or the search up: no keys
//   page                    "deck", "figure", a theme's, or none
//   find                    "find" or "replace" (its field typed in), "open" (the keys elsewhere)
//   typing                  words typed: "words" (a slide's, its title's), "list", "cell", "code",
//                           "maths", "stat", "caption", "shape" (a shape's, on a slide), "plain"
//                           (a shape's, over a figure), "label" (a figure's), "notes", "field"
//   drag                    a drag under way, by what its keys do (DRAGS)
//   mode                    "crop", "pen" (a path drawn point by point), "polyline", "freehand",
//                           "tool" or "tool-line" (a shape to draw), "points" (a path's, edited),
//                           "connect" (a figure's lines drawn)
//   chosen                  "shape", "path", "group", "shapes", "locked", "object", "placed",
//                           "objects", "placed-objects", "mixed", "words" (a slide's title, its
//                           byline), "logo", "slides" (the slide list has the keys), "part",
//                           "parts"
//   edit                    what ↩ does to the object chosen: "text", "cells", "numbers",
//                           "captions", "crop", "shapes", or none
//   inGroup                 a group of shapes entered, as Inkscape's is
//   grid, snapping          the grid shown; snapping "guides", "grid" or "off"
// Here too, whether the bar is shown. Read in Node as in the studio; drawn: helpbar.js.

export const MOST = 7;

// -- shown, or not: the person's, kept in this browser --

const KEY = "flexo-studio-help-bar";
const heard = new Set();

// Shown unless it was hidden (none kept, unreadable: shown).
function kept() {
  try { return globalThis.localStorage?.getItem?.(KEY) !== "off"; } catch { return true; }
}
let shown = kept();

export const helpShown = () => shown;
// Shown or hidden: `how` "here", or "stored" (another tab's choice).
export function setHelpShown(value, how = "here") {
  const now = Boolean(value);
  if (now === shown) return shown;
  shown = now;
  if (how !== "stored") {
    try { globalThis.localStorage?.setItem?.(KEY, shown ? "on" : "off"); } catch { /* this window's alone */ }
  }
  for (const listener of [...heard]) {
    try { listener(shown, how); } catch (error) { console.error(error); }
  }
  return shown;
}
export const toggleHelp = (how = "here") => setHelpShown(!shown, how);
// `listener(shown, how)` each time it is shown or hidden; what it returns stops that.
export function onHelp(listener) {
  heard.add(listener);
  return () => heard.delete(listener);
}
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("storage", (event) => { if (event.key === KEY || event.key === null) setHelpShown(kept(), "stored"); });
}

// For the palette and the Mac app's View menu: one command, named for what it will do (as Show
// Speaker Notes is).
export const helpCommand = () => ({ icon: "keyboard", label: shown ? "Hide Help Bar" : "Show Help Bar", run: () => toggleHelp() });

// Keycaps as the sheet draws them: one a chord, as a Mac menu shows it (⇧⌘N) -- modifiers go
// with the keys after them, and keys given side by side ("↑ ↓", "Home End") are each a keycap
// of their own. "or" is a word between keycaps: between two chords ("Esc or ⌘ ↩") each is as
// it would be alone; between modifiers ("⌥ or ⇧ ← →") the modifiers are each a keycap of their
// own and the keys after them too. "Click" (and "Drag", "Double-Click", "Type") is a word,
// after its modifier's keycap ("⇧ Click"). Each part { key } or { word }.
export function chords(keys) {
  const out = [];
  const words = String(keys).split(" ").filter(Boolean);
  const modifier = (key) => /^[⌘⇧⌥⌃]$/.test(key || "");
  const alone = words.some((key, at) => key === "or" && modifier(words[at - 1]) && modifier(words[at + 1]));
  let held = "";
  for (const [at, key] of words.entries()) {
    // (A modifier after a key begins another chord: "⌘ ' ⇧ ⌘ '" is ⌘' and ⇧⌘'.)
    if (modifier(key) && at && !modifier(words[at - 1])) held = "";
    if (modifier(key)) { if (alone) out.push({ key }); else held += key; }
    else if (["or", "Click", "Drag", "Double-Click", "Type"].includes(key)) { if (held) out.push({ key: held }); held = ""; out.push({ word: key === "or" ? "or" : key.toLowerCase() }); }
    else out.push({ key: held + key });
  }
  // (A modifier alone -- held while dragging -- is a keycap of its own.)
  if (!alone && modifier(words[words.length - 1])) out.push({ key: held });
  return out;
}

// The bar's keycaps, narrower than the sheet's: arrows side by side, under one modifier, one
// keycap ("← → ↑ ↓" is ←→↑↓, "⌥ ↑ ↓" ⌥↑↓) -- the bar has one row for them all.
const ARROWS = /^([⌘⇧⌥⌃]*)([←→↑↓]+)$/;
export function compact(parts) {
  const out = [];
  for (const part of parts) {
    const arrow = part.key && ARROWS.exec(part.key), last = out[out.length - 1], before = last?.key && ARROWS.exec(last.key);
    if (arrow && before && arrow[1] === before[1]) last.key += arrow[2];
    else out.push({ ...part });
  }
  return out;
}

const row = (keys, words) => ({ keys, words });
// A list of keys, with the groups of the sheet they are found in.
const said = (sheet, ...items) => Object.assign(items.flat().filter(Boolean), { sheet });

// ⌘ held while dragging: the other way from the magnet (snapping.js).
const freely = (c) => row("⌘", c.snapping === "off" ? "With Snapping" : "Without Snapping");
const NUDGE = [row("← → ↑ ↓", "Nudge"), row("⇧", "×10")];
const CANCEL = row("Esc", "Cancel");
const DESELECT = row("Esc", "Deselect");

// -- a drag under way: what ⇧, ⌥ and ⌘ do to it now, and Esc taking it back --
const DRAG = ["Shapes", "Objects on a Slide", "Figures", "Cropping a Picture", "Logos", "Drawing a Path", "A Path’s Points"];
const DRAGS = {
  // A shape (or an object placed where it is put) moved.
  move: (c) => [row("⇧", "One Way"), row("⌥", "Copy"), freely(c), CANCEL],
  // A shape sized by a corner, or by a side.
  corner: (c) => [row("⇧", "Keep Proportions"), row("⌥", "From Centre"), freely(c), CANCEL],
  side: (c) => [row("⌥", "From Centre"), freely(c), CANCEL],
  // An object placed, or a figure's shape, sized.
  scale: (c) => [row("⇧", "Keep Proportions"), freely(c), CANCEL],
  turn: () => [row("⇧", "15° Steps"), CANCEL],
  // A line's end, or a line drawn.
  end: (c) => [row("⇧", "45° Steps"), freely(c), CANCEL],
  "draw-line": (c) => [row("⇧", "45° Steps"), freely(c), CANCEL],
  draw: (c) => [row("⇧", "Square"), row("⌥", "From Centre"), freely(c), CANCEL],
  // Any other handle: a curve's middle, a shape's own, a text's width, a picture's size.
  handle: (c) => [freely(c), CANCEL],
  // A path's point or handle, edited; one put down by the pen, its handles pulled out.
  point: (c) => [row("⌥", "One Handle"), freely(c), CANCEL],
  pen: (c) => [row("⇧", "45° Steps"), freely(c), CANCEL],
  // The crop's frame, or a side of it.
  crop: () => [row("⇧", "Keep Proportions"), CANCEL],
  // A figure's shape moved among the others.
  part: () => [row("⌥", "Copy"), CANCEL],
  // A band, an object carried among the others, a logo along its row: Esc alone.
  plain: () => [CANCEL],
};

// -- words typed --
const STYLED = ["While Typing", "Styling a Slide’s Words (Not a Figure’s Labels)"];
const BOLD = [row("⌘ B", "Bold"), row("⌘ I", "Italic")];
const DONE = row("Esc", "Done");
const TYPING = {
  words: () => said(STYLED, BOLD, row("⌘ E", "Code"), row("⌘ K", "Link"), row("⌥ ⌘ E", "Equation"), row("⇥", "Next"), DONE),
  list: () => said(STYLED, row("⇥", "Indent"), row("⇧ ⇥", "Outdent"), row("↩", "New Item"), row("⇧ ↩", "New Line"), BOLD, DONE),
  cell: () => said(STYLED, row("⇥", "Next Cell"), row("↩", "Cell Below"), row("⇧ ↩", "New Line"), BOLD, DONE),
  code: () => said(STYLED, row("⇥", "Indent"), row("⇧ ⇥", "Outdent"), DONE),
  maths: () => said(STYLED, row("⇥", "Next"), DONE),
  stat: () => said(STYLED, row("⇥", "Next"), BOLD, DONE),
  caption: () => said(STYLED, row("⇥", "Next Caption"), BOLD, DONE),
  shape: () => said(STYLED, BOLD, row("⌘ E", "Code"), DONE),
  plain: () => said(["Shapes"], row("↩", "New Line"), DONE),
  label: () => said(["Figures"], row("↩", "New Line"), row("⇥", "Next Shape"), row("⇧ ⇥", "Previous"), DONE),
  notes: () => said(["While Typing"], DONE),
  // (Esc leaves a field of a deck's inspector; elsewhere a field keeps it.)
  field: (c) => said(["While Typing"], row("⇥", "Next"), c.page === "deck" ? DONE : row("⇧ ⇥", "Previous")),
};

// -- the find bar --
const FINDING = ["Finding"];
const FIND = {
  find: () => said(FINDING, row("↩", "Next"), row("⇧ ↩", "Previous"), row("⌥ ⌘ F", "Replace"), row("Esc", "Close")),
  replace: () => said(FINDING, row("↩", "Replace"), row("⌥ ↩", "Replace All"), row("Esc", "Close")),
};
// Open, the keys elsewhere and no words typed: n and ⇧N, as vim's, before what is chosen.
const FOUND = [row("N", "Next"), row("⇧ N", "Previous"), row("⌘ F", "Find")];

// -- what is being done: a crop, a path drawn or edited, a shape to draw --
const MODES = {
  crop: () => said(["Cropping a Picture"], row("↩", "Keep Crop"), row("← → ↑ ↓", "Move Frame"), row("⇧", "×10"), CANCEL),
  pen: (c) => said(["Drawing a Path", "Shapes"], row("↩", "Finish"), row("⌫", "Remove Point"), row("⇧", "45° Steps"), freely(c), CANCEL),
  polyline: () => said(["Drawing a Path"], row("↩", "Finish"), CANCEL),
  freehand: () => said(["Shapes"], CANCEL),
  tool: (c) => said(["Shapes"], row("⇧", "Square"), row("⌥", "From Centre"), freely(c), CANCEL),
  "tool-line": (c) => said(["Shapes"], row("⇧", "45° Steps"), freely(c), CANCEL),
  points: () => said(["A Path’s Points"], row("↩", "Done"), row("⌫", "Delete Point"), NUDGE, row("⌘ A", "All Points"), row("⌥", "One Handle")),
  connect: () => said(["Figures"], CANCEL),
};

// -- what is chosen --
const OBJECTS = ["Objects on a Slide", "Shapes"];
const EDITS = { text: "Edit Text", cells: "Edit Cells", numbers: "Edit Numbers", captions: "Edit Captions", crop: "Crop", shapes: "Edit Shapes" };
const editing = (c) => (EDITS[c.edit] ? row("↩", EDITS[c.edit]) : null);
const CHOSEN = {
  shape: () => said(["Shapes"], row("↩", "Edit Text"), NUDGE, row("⌘ D", "Duplicate"), row("⌫", "Delete"), row("⇧ ⌘ C", "Set Colour"), DESELECT),
  path: () => said(["Shapes"], row("Double-Click", "Edit Points"), row("↩", "Edit Text"), NUDGE, row("⌘ D", "Duplicate"), row("⌫", "Delete"), DESELECT),
  group: () => said(["Shapes"], row("↩", "Enter Group"), row("⇧ ⌘ G", "Ungroup"), NUDGE, row("⌘ D", "Duplicate"), row("⌫", "Delete"), DESELECT),
  shapes: () => said(["Shapes", "General"], row("⌘ G", "Group"), row("⇧ ⌘ A", "Align"), NUDGE, row("⌘ D", "Duplicate"), row("⌫", "Delete"), DESELECT),
  locked: () => said(["Shapes"], row("⌥ ⌘ L", "Unlock"), row("⌘ D", "Duplicate"), DESELECT),
  object: (c) => said(OBJECTS, editing(c), row("↑ ↓", "Choose"), row("⌥ ↑ ↓", "Move"), row("⌘ D", "Duplicate"), row("⌫", "Delete"), DESELECT),
  placed: (c) => said(OBJECTS, editing(c), NUDGE, row("⌘ D", "Duplicate"), row("⌫", "Delete"), row("⌘ L", "Lock"), DESELECT),
  "locked-object": (c) => said(OBJECTS, editing(c), row("⌥ ⌘ L", "Unlock"), row("⌘ D", "Duplicate"), DESELECT),
  objects: () => said([...OBJECTS, "General"], row("⇧ ⌘ A", "Align"), row("⌥ ↑ ↓", "Move"), row("⌫", "Delete"), DESELECT),
  "placed-objects": () => said([...OBJECTS, "General"], row("⇧ ⌘ A", "Align"), NUDGE, row("⌘ L", "Lock"), row("⌫", "Delete"), DESELECT),
  mixed: () => said([...OBJECTS, "General"], row("⇧ ⌘ A", "Align"), NUDGE, row("⌘ D", "Duplicate"), row("⌫", "Delete"), DESELECT),
  words: () => said(OBJECTS, row("↩", "Edit Text"), row("↑ ↓", "Choose"), BOLD, DESELECT),
  logo: () => said(["Logos", "Objects on a Slide"], row("← →", "Choose"), row("⌥ ← →", "Move"), row("⌫", "Delete"), DESELECT),
  slides: () => said(["In the Slide List", "Slides"], row("↑ ↓", "Slides"), row("↩", "New Slide"), row("⌘ D", "Duplicate"), row("⌫", "Delete"), row("⌥ ↑ ↓", "Move"), row("⇧ ↑ ↓", "Select More")),
  part: () => said(["Figures"], row("↩", "Edit Label"), row("← → ↑ ↓", "Choose"), row("⌥ ← → ↑ ↓", "Move"), row("⌘ D", "Duplicate"), row("⌫", "Delete"), row("⌘ G", "Group"), DESELECT),
  parts: () => said(["Figures"], row("⌘ G", "Group"), row("⌥ ← → ↑ ↓", "Move"), row("⌘ D", "Duplicate"), row("⌫", "Delete"), DESELECT),
};

// -- nothing chosen: the page's own keys --
const GENERAL = ["General", "Slides", "Finding", "Figures"];
const viewing = (c) => [row("⌘ F", "Find"), row("#", c.grid ? "Hide Grid" : "Show Grid"), row("%", "Snapping"), row("⌘ K", "Search"), row("⌘ /", "Shortcuts")];
const PAGES = {
  deck: (c) => said(GENERAL, row("⇧ ⌘ N", "New Slide"), row("↑ ↓", "Slides"), viewing(c)),
  figure: (c) => said(GENERAL, row("⌘ A", "Select All"), viewing(c)),
};
const ANYWHERE = () => said(["General"], row("⌘ K", "Search"), row("⌘ /", "Shortcuts"));
const IN_GROUP = [row("Esc", "Leave Group"), row("⌘ A", "Select All")];

// The keys for `c`, at most MOST of them: each { keys, words }, with the sheet's groups they
// are found in (`sheet`).
export function itemsFor(c = {}) {
  if (!c || c.hidden) return said([]);
  if (c.drag) return said(DRAG, (DRAGS[c.drag] || DRAGS.plain)(c));
  if (FIND[c.find]) return FIND[c.find](c);
  if (c.typing) return (TYPING[c.typing] || TYPING.field)(c);
  const own = MODES[c.mode]?.(c) || CHOSEN[c.chosen]?.(c)
    || (c.inGroup ? said(["Shapes", ...GENERAL], IN_GROUP, (PAGES[c.page] || ANYWHERE)(c)) : null)
    || (PAGES[c.page] || ANYWHERE)(c);
  const head = c.find === "open" ? FOUND : [];
  // (A key once: the first said of it.)
  const seen = new Set();
  const items = [...head, ...own].filter((item) => !seen.has(item.keys) && seen.add(item.keys));
  return said([...(head.length ? FINDING : []), ...own.sheet], items.slice(0, MOST));
}

// What the bar shows for `c`, as one string: drawn again only when it changes.
export const keyOf = (items) => items.map((item) => `${item.keys}\u0001${item.words}`).join("\u0002");

// -- what an editor says of its shapes and its figure's shapes --

// From the shapes' editor (shapes.js's `doing()`): what a drag of a shape is, a tool armed, a
// path drawn or its points edited, a group entered, and what is chosen.
export function fromShapes(doing) {
  if (!doing) return {};
  const c = {};
  // (A polyline is drawn click by click, its drag begun at the first: Return or Esc ends it.)
  if (doing.drag === "draw" && doing.tool === "polyline") c.mode = "polyline";
  else if (doing.drag === "draw" && doing.tool === "pen") c.drag = "plain";
  else if (doing.drag) {
    c.drag = doing.drag === "size" ? (doing.corner ? "corner" : "side")
      : doing.drag === "draw" ? (doing.line ? "draw-line" : "draw")
        : doing.drag === "band" ? "plain"
          : doing.drag === "point" || doing.drag === "adjust" ? "handle"
            : ["move", "turn", "end"].includes(doing.drag) ? doing.drag : "plain";
  }
  // (A point of the pen's, or of a path's being edited, dragged.)
  else if (doing.pointDrag) c.drag = doing.points ? "point" : "pen";
  if (doing.points) c.mode = "points";
  else if (doing.tool === "path") c.mode = "pen";
  else if (doing.tool === "polyline") c.mode = "polyline";
  else if (doing.tool === "pen") c.mode = "freehand";
  else if (doing.tool) c.mode = doing.line ? "tool-line" : "tool";
  if (doing.chosen > 1) c.chosen = doing.locked ? "locked" : "shapes";
  else if (doing.chosen === 1) c.chosen = doing.locked ? "locked" : doing.kind === "group" ? "group" : doing.kind === "path" ? "path" : "shape";
  if (doing.group) c.inGroup = true;
  return c;
}

// From a figure's shapes (parts.js's figureParts): a drag of one, its size, a line bent, its
// lines drawn, and what is chosen. `sizing` and `bending`, as the page says them (its marks).
export function fromParts(parts, { sizing = false, bending = false } = {}) {
  if (!parts) return {};
  const c = {};
  if (sizing) c.drag = "scale";
  else if (bending) c.drag = "handle";
  else if (parts.dragging) c.drag = "part";
  if (parts.connecting) c.mode = "connect";
  const count = parts.selected?.length || 0;
  if (count) c.chosen = count > 1 ? "parts" : "part";
  return c;
}

// Several says of what is being done, the first of them that says each thing having it.
export function together(...says) {
  const out = {};
  for (const one of says) for (const [name, value] of Object.entries(one || {})) if (out[name] === undefined || out[name] === "" || out[name] === null) out[name] = value;
  return out;
}
