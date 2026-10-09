// Editing a figure's parts, wherever the figure is drawn: in the figure editor, or
// on a deck's slide. What is shared is here -- choosing parts on the drawing, the
// inspector's panels, the palette of parts, drawing lines, typing words on the
// drawing, and the keys -- and the page that holds the figure (the host) says
// where edits go and where the drawing is:
//
//   run(action, { merge })  makes an edit (the server does, to the figure's file or
//                           the deck's document) and answers { model, select };
//   element(id)             the drawn element of a part, by the figure's id;
//   idOf(elementId)         the figure's id for a drawn element's (a slide prefixes them);
//   box(id)                 where a part is drawn, in the overlay's pixels;
//   overlay                 the positioned element the words-on-the-drawing box sits in;
//   fixedPage               the overlay keeps its size as the figure grows (a slide);
//   changed()               what is chosen, or the figure, changed: draw again;
//   settled()               the parts have landed where they are drawn: mark them again;
//
// Parts are dragged on the drawing to another place in their row, column or grid,
// or into another group (pointerdown); and an edit that moves parts lands smoothly:
// the host takes landing() before it puts the new drawing in and gives it to land()
// after, and each part slides from where it was to where it is.
//   chooseFile({ title, types }), focus(where), nothing()  (the panel when nothing is chosen).

import { h, clear, icon, ui, menu, popover, closeMenu, dialog, toast, readable, inQuotes, typingName } from "/static/studio/studio.js";
import { mergeText, follows } from "/static/studio/merge.js";
import { dropPlace, stays, lineAt, groupAt, endAt, endsOf } from "/static/kinds/figure/drop.js";

// Small pictures of each kind of part, drawn on a 16-unit square.
export const GLYPHS = {
  block: "M2.5 4.5h11v7h-11z",
  text: "M4 4h8M8 4v8",
  op: "M8 3a5 5 0 100 10A5 5 0 008 3zM8 5.5v5M5.5 8h5",
  circle: "M8 3a5 5 0 100 10A5 5 0 008 3z",
  terminal: "M5 4.5h6a3.5 3.5 0 010 7H5a3.5 3.5 0 010-7z",
  decision: "M8 2.5L13.5 8 8 13.5 2.5 8z",
  io: "M5.5 4.5h8.5l-3.5 7H2z",
  database: "M3 4.5c0-1.1 2.2-2 5-2s5 .9 5 2v7c0 1.1-2.2 2-5 2s-5-.9-5-2zM3 4.5c0 1.1 2.2 2 5 2s5-.9 5-2",
  server: "M2.5 2h11v4.5h-11zM2.5 7.75h11v2.75h-11zM2.5 11.75h11v2.75h-11zM11 9.1h.01M11 13.1h.01",
  cloud: "M4.5 12.5a3 3 0 01-.5-5.96 4 4 0 017.6-1.04 3.25 3.25 0 01.9 7z",
  queue: "M1.5 5h13v6h-13zM8.5 5v6M10.5 5v6M12.5 5v6",
  document: "M3.5 2.5h9v8.5c-2.2-.9-3.2.3-4.5 1.3s-2.6 1.4-4.5.4z",
  person: "M8 2.5a2.25 2.25 0 100 4.5 2.25 2.25 0 000-4.5zM3.5 13.5V12A3.5 3.5 0 017 8.5h2a3.5 3.5 0 013.5 3.5v1.5z",
  image: "M2.5 3.5h11v9h-11zM2.5 11l3.5-3.5 3 3 2-2 2.5 2.5",
  junction: "M8 6.5a1.5 1.5 0 100 3 1.5 1.5 0 000-3zM2 8h4.5M9.5 8H14",
  mlp: "M2.5 4.5h11v7h-11zM5.5 8h.01M8 8h.01M10.5 8h.01",
  cnn: "M2.5 6.5h8v6h-8zM4.5 4.5h8v6M6.5 2.5h7v6",
  attention: "M2.5 5.5h11v8h-11zM5 2.5v3M8 2.5v3M11 2.5v3",
  "add-norm": "M2.5 4.5h11v7h-11zM8 6v4M6 8h4",
  concat: "M3.5 3.5h3v9h-3zM9.5 3.5h3v9h-3z",
  tensor: "M2.5 6.5h8v6h-8zM2.5 6.5l3-3h8l-3 3M13.5 3.5v6l-3 3",
  matrix: "M3 3h10v10H3zM3 6.3h10M3 9.6h10M6.3 3v10M9.6 3v10",
  graph: "M4 4.5a1.5 1.5 0 100 .1M12 5a1.5 1.5 0 100 .1M8 12a1.5 1.5 0 100 .1M5 5l6 .3M4.6 5.8L7.4 11M11.4 6.3L8.6 11",
  inset: "M8 2.5l5 2.8v5.4l-5 2.8-5-2.8V5.3z",
  prediction: "M2.5 4.5h11v7h-11zM5 8h6M9 6l2 2-2 2",
  loss: "M2.5 4.5h11v7h-11zM5 10l2-3 2 2 2-3",
  "feature-strip": "M2 6h12v4H2zM5 6v4M8 6v4M11 6v4",
  vector: "M6 1.5h4v3H6zM6 5.5h4v3H6zM6 9.5h4v3H6zM4.5 14.5h7",
  sequence: "M1.5 6h3v4h-3zM6.5 6h3v4h-3zM11.5 6h3v4h-3z",
  volume: "M2.5 6.5h7v7h-7zM2.5 6.5l3-3h7l-3 3M12.5 3.5v7l-3 3",
  construct: "M1.5 11h13M3.5 11V6.5h3.5M6 5l1.5 1.5L6 8M8.5 9h3.5l1.5 2-1.5 2H8.5z",
  plasmid: "M8 2.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM8 2.5a5.5 5.5 0 015.2 3.7",
  protein: "M1.5 8h13M3 6h4v4H3zM9.5 5.5h4v5h-4z",
  tree: "M2.5 3.5h4v4h-4M6.5 5.5h7M2.5 7.5v5h11M2.5 3.5v4",
  wellplate: "M2.5 3.5h11v9h-11zM5 6h.01M8 6h.01M11 6h.01M5 10h.01M8 10h.01M11 10h.01",
  timeline: "M1.5 8h13M4 8a1 1 0 100 .1M8 8a1 1 0 100 .1M12 8a1 1 0 100 .1M4 11.5h8",
  structure: "M2 11c1.5-6 3-6 4 0s2.5 6 4 0 2.5-6 4 0",
  cells: "M2.5 2.5h3v3h-3zM9.5 2.5h3v3h-3zM6 6h3v3H6zM2.5 9.5h3v3h-3zM9.5 9.5h3v3h-3z",
  row: "M1.5 5h3.5v6H1.5zM6.25 5h3.5v6h-3.5zM11 5h3.5v6H11z",
  column: "M4.5 1.5h7v3.5h-7zM4.5 6.25h7v3.5h-7zM4.5 11h7v3.5h-7z",
  grid: "M2.5 2.5h4.5v4.5H2.5zM9 2.5h4.5v4.5H9zM2.5 9h4.5v4.5H2.5zM9 9h4.5v4.5H9z",
  module: "M1.5 3.5h13v10h-13zM1.5 6h13M3.5 8.5h4v3h-4zM8.5 8.5h4v3h-4z",
  edge: "M2 8h10M9 5l3 3-3 3",
  net: "M2 8h5M7 8l5-4M7 8l5 4M7 8h5",
};

export function glyph(name) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  node.setAttribute("viewBox", "0 0 16 16");
  node.setAttribute("class", "glyph");
  // Drawn as it should be even before parts.css is in (the studio away when it was asked
  // for): its look written on it too, which the stylesheet's sizes override.
  for (const [name, value] of Object.entries({ width: 16, height: 16, fill: "none", stroke: "currentColor", "stroke-width": 1.3, "stroke-linecap": "round", "stroke-linejoin": "round" })) {
    node.setAttribute(name, value);
  }
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", GLYPHS[name] || GLYPHS.block);
  node.append(path);
  return node;
}

// A structure's name from its file: a PDB ID in capitals, any other file by its name.
export function fileLabel(source) {
  const stem = String(source).split("/").pop().replace(/\.(pdb|cif|mmcif|ent)$/i, "");
  return /^[0-9][A-Za-z0-9]{3}$/.test(stem) ? stem.toUpperCase() : stem;
}
// The colour a tone is seen in on the drawing: the outline of a tinted shape, the fill of a
// solid one -- whichever of the two is the more coloured (a solid theme's outline is ink).
export function painted(tone) {
  const chroma = (colour) => {
    const hex = /^#?([0-9a-f]{6})$/i.exec(String(colour || "").trim());
    if (!hex) return -1;
    const value = parseInt(hex[1], 16), rgb = [value >> 16, (value >> 8) & 255, value & 255];
    return Math.max(...rgb) - Math.min(...rgb);
  };
  return tone ? (chroma(tone.fill) > chroma(tone.stroke) ? tone.fill : tone.stroke || tone.fill) : undefined;
}
export const words = (label) => (Array.isArray(label) ? label.map((run) => run?.text ?? "").join("") : label ?? "");
export const plain = (label) => readable(words(label));
export const groupGlyph = (group) => (group.role === "module" ? "module" : ["grid", "row", "column"].includes(group.layout?.kind) ? group.layout.kind : "column");

// A value as a person reads it, in title case: "ink colour" and "engraved-colour" are
// "Ink Colour" and "Engraved Colour". Short words stay small inside a title.
const SMALL_WORDS = new Set(["a", "an", "the", "and", "or", "but", "nor", "as", "to", "of", "in", "on", "at", "by", "for",
  "with", "from", "into", "over", "onto", "upon", "like", "near"]);
export function titled(value) {
  const all = String(value ?? "").replace(/(?<=[A-Za-z])[-_](?=[A-Za-z])/g, " ").trim().split(/\s+/);
  return all.map((word, index) => (index && index < all.length - 1 && SMALL_WORDS.has(word) ? word : word.replace(/^[a-z]/, (letter) => letter.toUpperCase()))).join(" ");
}
// A choice's value as shown: the label the catalogue gives it, else the value in title case.
const choiceLabel = (field, option) => field.labels?.[option] ?? titled(option);
// A title inside a sentence: "Block" is "block", "MLP" stays "MLP".
const inSentence = (title) => (/^[A-Z][a-z]/.test(title) ? title.charAt(0).toLowerCase() + title.slice(1) : title);
const counted = (count, noun) => `${count} ${noun}${count === 1 ? "" : "s"}`;
const article = (word) => (/^[aeiou]/i.test(word) ? "an" : "a");

// Lines are thin: each is given a wide, invisible twin to click, named for the line
// as it is drawn (the host maps drawn ids to the figure's).
export function widenLines(svg) {
  for (const line of svg.querySelectorAll('[data-flexo-entity="connector"][id], [data-flexo-entity="net"][id]')) {
    const id = line.id;
    for (const path of line.querySelectorAll("path")) {
      if (!path.getAttribute("d") || path.classList.contains("hit-line")) continue;
      const twin = document.createElementNS("http://www.w3.org/2000/svg", "path");
      twin.setAttribute("d", path.getAttribute("d"));
      if (path.getAttribute("transform")) twin.setAttribute("transform", path.getAttribute("transform"));
      twin.setAttribute("class", "hit-line");
      // Unpainted by itself, not only by parts.css: a slide shows its figure's lines
      // widened before that sheet is loaded, and a path left to SVG's defaults is black.
      twin.setAttribute("fill", "none");
      twin.setAttribute("stroke", "transparent");
      twin.setAttribute("stroke-width", "9");
      // (Whole, a dashed line's too: clicked between its dashes, it is clicked all the same.)
      twin.setAttribute("stroke-dasharray", "none");
      twin.dataset.hitFor = id;
      path.after(twin);
    }
  }
}

// Where words are typed: a key there is the field's.
const TYPING = "input, textarea, select, [contenteditable]:not([contenteditable='false'])";
const typingIn = (node) => Boolean(node?.closest?.(TYPING));
let lastTyped = 0;
// Where the pointer was last pressed, and on what: a click acts on what was under the pointer
// as it was pressed -- the drawing as it was seen then -- not on whatever a drawing that came
// in before it was let go puts there.
let pressed = null;
if (typeof document !== "undefined") {
  document.addEventListener("input", (event) => { if (typingIn(event.target)) lastTyped = Date.now(); }, true);
  // A click ends the typing: what is chosen then is chosen to act on.
  document.addEventListener("pointerdown", (event) => {
    lastTyped = 0;
    pressed = { target: event.target, x: event.clientX, y: event.clientY, at: Date.now() };
  }, true);
}
// A press whose element is drawn anew before it is let go -- the figure come back from the
// studio and put in again, its panel drawn again with it -- is a click all the same, where a
// browser drops it: on what now stands where the pressed element stood, should that be the
// same thing drawn anew (the same switch, field or button of the panel; anything on the
// figure's drawing, which a click names by what was pressed: asPressed).
if (typeof document !== "undefined") {
  // (A control by its key, else by the name of the field it is in.)
  const keyOf = (element) => element?.closest?.("label")?.querySelector?.("[data-key]")?.dataset.key ?? element?.closest?.("[data-key]")?.dataset.key
    ?? (element?.closest?.(".field") ? `field:${element.closest(".field").querySelector("label, .label")?.textContent ?? ""}` : null);
  // (What was pressed is out of the page now: known by what it was, not where it was kept.)
  const alike = (was, now) => {
    if (was.closest?.("svg")) return Boolean(now.closest?.(".fig-page svg, .slide-page svg"));
    if (!now.closest?.(".panel-body") || was.tagName !== now.tagName) return false;
    const key = keyOf(was);
    return was.className === now.className && (key !== null ? key === keyOf(now) : Boolean(was.textContent) && was.textContent === now.textContent);
  };
  document.addEventListener("pointerup", (event) => {
    const press = pressed;
    if (!press || press.target?.isConnected !== false || event.button !== 0 || Date.now() - press.at > 3000
      || Math.abs(press.x - event.clientX) > 4 || Math.abs(press.y - event.clientY) > 4) return;
    const now = document.elementFromPoint(event.clientX, event.clientY);
    if (!now || !alike(press.target, now)) return;
    // (A browser that clicks something round it instead -- the panel the control was in --
    // has clicked no control: the drawing's own clicks are named by what was pressed.)
    const drawing = Boolean(press.target.closest?.("svg"));
    let clicked = false;
    const seen = (click) => { clicked = drawing || click.target === now || now.contains(click.target) || !click.target.contains?.(now); };
    document.addEventListener("click", seen, { capture: true, once: true });
    setTimeout(() => {
      document.removeEventListener("click", seen, { capture: true });
      if (clicked || !now.isConnected) return;
      now.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window, detail: 1, clientX: event.clientX, clientY: event.clientY,
        shiftKey: event.shiftKey, metaKey: event.metaKey, ctrlKey: event.ctrlKey, altKey: event.altKey }));
    }, 0);
  }, true);
}
// A click (or double-click) as it was pressed: on what was under the pointer then.
function asPressed(event) {
  const press = pressed;
  if (!press || press.target === event.target || Date.now() - press.at > 4000
    || Math.abs(press.x - event.clientX) > 4 || Math.abs(press.y - event.clientY) > 4) return event;
  return { target: press.target, clientX: event.clientX, clientY: event.clientY,
    shiftKey: event.shiftKey, metaKey: event.metaKey, ctrlKey: event.ctrlKey, altKey: event.altKey };
}

// At most one call every `ms`, and always the last: a colour dragged in the picker is
// sent as it goes, not at every step.
function throttled(run, ms = 100) {
  let waiting = null, timer = 0;
  const fire = () => {
    timer = 0;
    if (!waiting) return;
    const args = waiting;
    waiting = null;
    run(...args);
    timer = setTimeout(fire, ms);
  };
  return (...args) => { waiting = args; if (!timer) fire(); };
}

// A stylesheet of the figure's, asked for once -- and again, should the studio not have
// answered (a figure first chosen while it was away), until it does: never a page of
// unstyled parts (a glyph drawn as a great black square) once it is back.
export function lookFrom(href) {
  const old = document.querySelector(`link[href="${href}"]`);
  if (old && !old.dataset.failed) return;
  old?.remove();
  const link = h("link", { rel: "stylesheet", href });
  link.addEventListener("error", () => { link.dataset.failed = "1"; setTimeout(() => lookFrom(href), 2000); }, { once: true });
  document.head.append(link);
}

// Asked for as soon as an editor that may show a figure is loaded (a deck's, a figure's),
// not when a figure is first chosen: chosen with the studio away, its parts are styled.
lookFrom("/static/kinds/figure/parts.css");

export function figureParts(host) {
  lookFrom("/static/kinds/figure/parts.css");
  const catalog = host.catalog;
  const parts = catalog.parts;
  const state = { model: null, selected: [], missing: [], connecting: null, chain: true, landing: 0, settling: false, swallow: false, renamed: new Map(), inside: false };

  // -- the figure as its file writes it --
  const model = () => state.model;
  const nodeOf = (id) => model()?.nodes.find((n) => n.id === id);
  const groupOf = (id) => model()?.groups.find((g) => g.id === id);
  const edgeOf = (id) => model()?.edges.find((e) => e.id === id);
  const netOf = (id) => model()?.nets.find((n) => n.id === id);
  const typeOf = (id) => (nodeOf(id) ? "node" : groupOf(id) ? "group" : edgeOf(id) ? "edge" : netOf(id) ? "net" : null);
  const parentOf = (id) => model()?.groups.find((g) => (g.children || []).includes(id));
  const partOf = (node) => parts[node?.kind || "block"];
  // A kind of shape by the one name it has everywhere -- its type, the palette, the menus and
  // the history: "Block", "Decision".
  const kindTitle = (kind) => titled(parts[kind || "block"]?.title || "Shape");
  // (A name with no port and no shape of it -- a line "to: nowhere" -- is itself.)
  const nodeOfRef = (ref) => (nodeOf(ref) || !String(ref).includes(".") ? ref : String(ref).slice(0, String(ref).lastIndexOf(".")));
  const nameOf = (id) => {
    const node = nodeOf(id);
    // A shape with no words is called what it shows faintly on the drawing ("Block").
    if (node) return plain(node.label).trim() || hintOf(node) || partOf(node)?.title || node.kind;
    const group = groupOf(id);
    if (group) return plain(group.label) || (group.id === model()?.root ? "Layout" : titled(group.layout?.kind || "group"));
    const edge = edgeOf(id);
    if (edge) {
      const ends = `${nameOf(nodeOfRef(edge.from))} → ${nameOf(nodeOfRef(edge.to))}`;
      // Two lines between the same shapes are told apart: by their words, else by number.
      const twins = model().edges.filter((other) => nodeOfRef(other.from) === nodeOfRef(edge.from) && nodeOfRef(other.to) === nodeOfRef(edge.to));
      if (twins.length < 2) return ends;
      // (Numbered among those with no words: one, two -- no number skipped for one that has.)
      const said = plain(edge.label);
      return said ? `${ends} ${inQuotes(said)}` : `${ends} (${twins.filter((other) => !plain(other.label)).indexOf(edge) + 1})`;
    }
    // A line that branches, by all its ends: "Q and K, V → Attended value".
    const net = netOf(id);
    const listed = (names) => (names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`);
    if (net) return [net.sources, net.targets].map((ends) => listed((ends || []).map((ref) => nameOf(nodeOfRef(ref))))).join(" → ");
    return id;
  };
  const chosenOne = () => (state.selected.length === 1 ? state.selected[0] : null);
  // What several things are called together: "Shapes", "Lines", "Groups", or "Items".
  const isLine = (id) => Boolean(edgeOf(id) || netOf(id));
  // (A line or a joined line: their words typed alike, at the line.)
  const lineKind = (kind) => kind === "edge" || kind === "net";
  const pluralNoun = (ids) => (ids.every(isLine) ? "Lines" : ids.every((id) => groupOf(id)) ? "Groups" : ids.some(isLine) ? "Items" : "Shapes");

  // The words each run of typing in a label began from, by its run (its `merge`).
  const runFrom = new Map();
  // What an edit does, in words, for the history: "Move “Model”", "Connect “x” to “y”".
  // (Said before it is made: the names are the parts' as they were.)
  function said(action, merge = null) {
    const ref = (id) => (typeOf(id) ? id : nodeOfRef(id));
    const name = (id) => inQuotes(nameOf(ref(id)));
    const many = (ids = [], verb) => (ids.length === 1 ? `${verb} ${isLine(ids[0]) ? "Line" : name(ids[0])}` : `${verb} ${ids.length} ${pluralNoun(ids)}`);
    switch (action.do) {
      case "add": {
        // After a part, as the Add Shape menu says it: into the line on from it, under it as
        // a branch, or after it -- or into a line: between the two it joins.
        // (Named for the kind of shape it is, as the menus and its type name it: "Add Block".)
        if (action.into && edgeOf(action.into)) return lineWhere(action.into, { kind: action.kind }).label;
        if (action.after && !action.parent && nodeOf(action.after)) return addWhere(action.after, Boolean(action.source), action.kind).label;
        if (action.after && groupOf(action.after)) return `Add ${kindTitle(action.kind)} After ${name(action.after)}`;
        return `Add ${kindTitle(action.kind)}`;
      }
      case "connect": return `Connect ${name(action.source)} to ${name(action.target)}`;
      case "delete": return many(action.ids, "Delete");
      case "duplicate": return many(action.ids, "Duplicate");
      // (A module made of the shapes chosen is said so: "Make Module".)
      case "gather": return action.role === "module" ? "Make Module" : action.ids?.length ? many(action.ids, "Group") : "Add Group";
      case "ungroup": return `Ungroup ${name(action.id)}`;
      // (One group pasted is said as it is: a module, a group.)
      case "paste": {
        const group = action.top?.length === 1 ? (action.groups || []).find((each) => each.id === action.top[0]) : null;
        return action.top?.length > 1 ? "Paste Shapes" : group ? `Paste ${group.role === "module" ? "Module" : "Group"}` : "Paste Shape";
      }
      case "join": return action.add ? `Join ${name(action.add)} to the Line` : "Join Lines";
      case "separate": return action.end ? `Take ${name(action.end)} Out of the Line` : "Separate Lines";
      case "rename": return `Change ID of ${name(action.id)}`;
      // A part put on a line of its own beside another makes a row (a column) of the two: said so.
      case "move": {
        // Out of its own row (column), onto a line of its own beside it: said as its menu says it.
        if (action.line && action.of && action.of === parentOf(action.id)?.id) {
          const own = { below: "Row Below", above: "Row Above", left: "Column on the Left", right: "Column on the Right" }[action.line];
          if (own) return `Move ${name(action.id)} to Own ${own}`;
        }
        if (action.line && action.of && action.of !== model()?.root && (nodeOf(action.of) || groupOf(action.of))) {
          const way = { left: "Row", right: "Row", below: "Column", above: "Column" }[action.line];
          if (way) return `Put ${name(action.id)} in a ${way} with ${name(action.of)}`;
        }
        return `Move ${name(action.id)}`;
      }
      case "step": case "align": return `Move ${name(action.id)}`;
      case "update": {
        const target = action.target || action.targets?.[0] || {};
        const id = target.id, values = action.values || {}, keys = Object.keys(values);
        const all = (...wanted) => keys.length && keys.every((key) => wanted.includes(key));
        if (all("label")) {
          // Typed on in a field, one entry stands for it all: said by the name it had.
          const had = (nodeOf(id) || groupOf(id))?.label, was = plain(had), now = plain(values.label);
          // The same words in another look (a colour, code) are the label's format changed.
          // (Not the same words sent again, the typing done: a part just added named for them.)
          if (was && was === now && JSON.stringify(had) !== JSON.stringify(values.label)) return `Format ${inQuotes(now)}`;
          // Words typed (on a shape that had none, or typed on in, however quickly done):
          // said as every run of typing is, by what it typed since its run began (`merge`),
          // not as the shape's kind -- typingName.
          if (merge && !runFrom.has(merge)) {
            runFrom.set(merge, was);
            if (runFrom.size > 100) runFrom.delete(runFrom.keys().next().value);
          }
          // A group's title typed: the group renamed, said by the name it had.
          if (target.type === "group" && groupOf(id)) return `Rename ${inQuotes((merge ? runFrom.get(merge) : was) || now || nameOf(id))}`;
          if (now) return typingName(merge ? runFrom.get(merge) : was, now, 24);
          return `Edit ${name(id)}`;
        }
        if (keys.length && keys.every((key) => /^(properties\.tone$|properties\.paint-|paint\.|tone$)/.test(key))) return "Change Colour";
        if (all("line")) return `Make Line ${titled(values.line || "solid")}`;
        if (all("depart")) return "Change Where the Line Leaves";
        if (all("arrive")) return "Change Where the Line Arrives";
        if (all("properties.zoom")) return `Zoom ${name(id)}`;
        if (all("properties.yaw", "properties.pitch", "properties.roll")) return `Rotate ${name(id)}`;
        if (all("properties.yaw", "properties.pitch", "properties.roll", "properties.zoom")) return `Reset View of ${name(id)}`;
        if (all("properties.width", "properties.height")) return `Resize ${name(id)}`;
        // (A line's width is how thick it is drawn: its field's name, "Change Line Width".)
        if (all("width", "height") && target.type === "node") return values.width === null && values.height === null ? `Fit ${name(id)} to Its Words` : `Resize ${name(id)}`;
        if (all("bend", "lean")) return values.bend === null && values.lean === null ? "Reset Bend" : "Bend Line";
        // mol-sketch's settings, by the setting's label: "Change Line Width".
        const style = keys.filter((key) => key.startsWith("properties.style"));
        if (style.length && style.length === keys.length) {
          if (keys[0] === "properties.style" && values[keys[0]] === null) return "Reset Rendering";
          const label = style.length === 1 ? styleLabel(id, style[0].replace(/^properties\.style\.?/, "")) : null;
          return label ? `Change ${titled(label)}` : "Change Rendering";
        }
        if (all("properties.palette")) return "Change Palette";
        if (all("properties.colors")) return "Change Colours";
        if (all("properties.density")) return values["properties.density"] ? "Add Density Map" : "Remove Density Map";
        if (keys.includes("kind")) return "Change Shape Type";
        // One field of the inspector's, by its label: "Change Width"; a switch to show
        // something, "Show Ticks" or "Hide Ticks".
        // (A choice with the values it had hidden given back with it: named by the choice.)
        const lead = keys.length > 1 ? keys.find((key) => keys.every((other) => other === key || fieldOf(target, other)?.show?.[key] !== undefined)) : null;
        const field = keys.length === 1 ? fieldOf(target, keys[0]) : lead ? fieldOf(target, lead) : null;
        if (field?.type === "bool" && /^show /i.test(field.label)) {
          return `${(values[field.key] ?? field.default ?? false) ? "Show" : "Hide"} ${titled(field.label.slice(5))}`;
        }
        if (field?.label) return `Change ${titled(field.label)}`;
        return id ? `Edit ${name(id)}` : "Edit";
      }
      default: return null;
    }
  }
  // A field of the inspector's, and the label of one of mol-sketch's settings.
  function fieldOf(target, key) {
    const list = target.type === "node" ? partOf(nodeOf(target.id))?.fields : target.type === "group" ? catalog.group_fields
      : target.type === "edge" ? catalog.edge_fields : target.type === "net" ? catalog.net_fields || catalog.edge_fields
        : target.type === "figure" ? catalog.figure_fields : null;
    return (list || []).find((field) => field.key === key) || null;
  }
  function styleLabel(id, key) {
    const drawing = (partOf(nodeOf(id))?.fields || []).find((field) => field.type === "molsketch");
    return (drawing?.sections || []).flatMap((section) => section.fields).find((field) => field.key === key)?.label || null;
  }

  // `afresh`: the figure as another's edit or an undo left it, its words shown in the field
  // being typed in too (see typing).
  // (`back`: the figure as an undo or a redo left it: what that brought back is chosen.)
  function setModel(next, { afresh: fresh = false, back = false } = {}) {
    if (!next) return;
    const before = state.model;
    state.model = next;
    if (fresh) followRenamed(before, next);
    if (fresh && parked.length) unpark();
    // A drawing begun before an edit brings the figure as it was then: what is chosen that it
    // lacks (a part just named anew) is chosen again once the figure has it.
    const wanted = [...new Set([...state.selected, ...state.missing])];
    state.selected = wanted.filter((id) => typeOf(id));
    state.missing = wanted.filter((id) => !typeOf(id));
    if (back && before) chooseBack(before, next);
    afresh = fresh;
    try { host.changed(); } finally { afresh = false; }
    mergeTyping();
    // A part waiting to be typed on, now the figure knows it: typed on, if it is drawn -- or
    // given the words typed on it, should another have been chosen meanwhile.
    if (typeInto && !inline) placeInline();
    if (owed && typeOf(owed.id)) { const { id, text } = owed; owed = null; giveWords(id, text); }
    // (Words kept in sight for a part not drawn yet go with it, should it go: an undo, say.)
    if (typedOver?.box) showTyped();
  }

  // An undo or a redo chooses what it brought back or changed, as Keynote's does: a shape
  // deleted, or its words, or a group whole (not the shapes it holds) -- else, nothing of that
  // kind, a line that came back. Anything else leaves what is chosen as it was.
  function chooseBack(before, next) {
    const had = new Set([...(before.nodes || []), ...(before.groups || [])].map((item) => item.id));
    const was = new Map((before.nodes || []).map((node) => [node.id, JSON.stringify(node)]));
    const come = [...(next.groups || []).filter((group) => !had.has(group.id) && !group.implied),
      ...(next.nodes || []).filter((node) => !had.has(node.id) || was.get(node.id) !== JSON.stringify(node))].map((item) => item.id);
    const held = (id) => come.some((other) => (groupOf(other)?.children || []).includes(id));
    let found = come.filter((id) => !held(id));
    if (!found.length) {
      // (A line by what it is, not its id, which numbers it among the others.)
      const said = (line) => JSON.stringify({ ...line, id: null });
      const lines = new Set([...(before.edges || []), ...(before.nets || [])].map(said));
      found = [...(next.edges || []), ...(next.nets || [])].filter((line) => !lines.has(said(line))).map((line) => line.id);
    }
    if (found.length) { state.selected = found; state.missing = []; state.inside = false; }
  }

  // Shapes chosen that another renamed (an agent writing the file, its Name in File changed
  // in another window), as the figure comes back with them: chosen still under their new
  // names, and the panel's field typed in for one goes on in it -- its name follows (its
  // words and caret kept as the panel is drawn again, keepFocus), and so do the edits typed
  // in it on their way to the studio (renamedTo) -- as the drawing's own typing follows its
  // shape (the host's shapeGone).
  const renamedTo = new Map();
  function followRenamed(before, next) {
    const old = Array.isArray(before?.nodes) ? before.nodes : [], now = Array.isArray(next?.nodes) ? next.nodes : [];
    const ids = new Set(now.map((node) => node?.id)), had = new Set(old.map((node) => node?.id));
    for (const id of new Set([...state.selected, ...state.missing])) {
      const node = ids.has(id) ? null : old.find((item) => item?.id === id);
      const to = node ? now[follows([node], now)[0]] : null;
      if (!to?.id || had.has(to.id)) continue;
      renamedTo.set(id, to.id);
      state.selected = state.selected.map((each) => (each === id ? to.id : each));
      state.missing = state.missing.map((each) => (each === id ? to.id : each));
      const scoped = new RegExp(`^([\\w-]+):${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?=:|$)`);
      const rename = (key) => (typeof key === "string" ? key.replace(scoped, `$1:${to.id}`) : key);
      const field = document.activeElement;
      if (field?.dataset?.key && rename(field.dataset.key) !== field.dataset.key) field.dataset.key = rename(field.dataset.key);
      for (const map of [typed, drafts]) for (const [key, value] of [...map]) if (rename(key) !== key) { map.delete(key); map.set(rename(key), value); }
      for (const job of queue) if (job.action.target?.type === "node" && job.action.target.id === id) job.action = { ...job.action, target: { ...job.action.target, id: to.id } };
    }
  }
  // Edits refused for a shape the figure here still had (see run): sent again for it under its
  // new name -- unless words typed in the field since carry them -- or, not renamed, said.
  const parked = [];
  function unpark() {
    for (const { job, error } of parked.splice(0)) {
      const target = job.action.target, renamed = renamedTo.get(target.id);
      if (renamed && job.merge && (lastMade.get(job.merge) ?? 0) > job.made) { if (job.merge) typed.delete(job.merge); continue; }
      if (renamed) { queue.unshift({ ...job, retried: true, action: { ...job.action, target: { ...target, id: renamed } } }); continue; }
      toast(error.message, { kind: "error", icon: "error", seconds: 6 });
      if (job.merge) typed.delete(job.merge);
      job.failed?.();
    }
    run();
  }

  function select(ids, { reveal = true } = {}) {
    state.missing = [];
    state.inside = false;
    state.selected = [...new Set((Array.isArray(ids) ? ids : [ids]).filter(Boolean))];
    if (typeInto && !state.selected.includes(typeInto)) typeInto = null;
    host.changed();
    const id = state.selected[state.selected.length - 1];
    if (id && reveal) host.reveal?.(id);
    host.focus?.(id ? { label: nameOf(id), id } : null);
  }

  // -- edits, one at a time --
  const queue = [];
  let running = false;
  let waiting = false;  // edits held for the studio, out of reach
  let current = null;  // the edit on its way to the studio
  // What is typed in a field, until the figure that holds it comes back: a figure that
  // left before the latest keys must not put older words back in the field.
  const typed = new Map();
  let afresh = false;
  const LANDS = new Set(["move", "align", "step", "add", "delete", "duplicate", "gather", "ungroup", "connect"]);
  // A molecule changed is drawn again by mol-sketch, which takes a moment: a small
  // spinner shows on it meanwhile, until its new drawing is in.
  const redrawing = new Map();
  function redraws(action) {
    if (action.do !== "update") return;
    for (const target of action.targets || [action.target]) {
      if (target?.type !== "node" || nodeOf(target.id)?.kind !== "structure") continue;
      if (Object.keys(action.values || {}).every((key) => key === "label")) continue;
      redrawing.set(target.id, { element: moleculeOf(target.id), since: Date.now() });
    }
  }
  // `follow`: the part an edit may rename (its words typed, its id made from them): chosen
  // still, under its new id, when it was chosen as the edit came back.
  // What a change of the figure's parts is, said where it is refused (the studio away):
  // "Can't add shapes while…". Words and settings typed are not refused: they are held.
  const REFUSED = { add: "add shapes", connect: "connect shapes", delete: "delete shapes", paste: "paste shapes", duplicate: "duplicate shapes",
    gather: "group shapes", ungroup: "ungroup shapes", move: "move shapes", step: "move shapes", nudge: "move shapes", arrange: "rearrange shapes", "own-line": "move shapes", align: "move shapes" };
  const KEPT = new Set(["update", "read", "structure-view", "structure-settings", "structure-fetch"]);
  function act(action, { merge = null, hold = false, select: choose = true, then = null, failed = null, follow = null, label = null, fresh = false } = {}) {
    // With the studio away, a host that keeps its drawing as it was (a deck's slide) refuses
    // what would put the figure's parts elsewhere, and says so; what is typed is held.
    if (!KEPT.has(action.do) && host.away?.(REFUSED[action.do] || "change the figure’s shapes")) { failed?.(); return; }
    redraws(action);
    // (The host told at once that the figure is edited -- its first words typed, say -- before
    // the edit is sent: a deck's new figure is not "left empty" while they are on their way.)
    if (!["read", "structure-view", "structure-settings", "structure-fetch"].includes(action.do)) host.edited?.(action);
    // Any other edit made, those taken back while the studio was away are not to be made again.
    if (action.do !== "read" && !puttingBack) takenBack.length = 0;
    // Typing in one field: only its latest words wait to be sent -- typed over the words
    // the studio last had, not over any of those that never reached it.
    let older = [];
    if (merge) {
      older = queue.filter((job) => job.merge === merge);
      for (const job of older) queue.splice(queue.indexOf(job), 1);
      if (older[0]?.action.was !== undefined && action.was !== undefined) action = { ...action, was: older[0].action.was };
      if (action.do === "update") typed.set(merge, action.values);
    }
    // (When it was made, and which it is, for the history: a run of typing from its first key.)
    const job = { action, merge, hold, choose, then, failed, follow, fresh, label: action.do === "read" || action.do === "structure-view" ? null : label || said(action, merge),
      at: older[0]?.at ?? Date.now(), key: older[0]?.key ?? (jobCount += 1), made: (madeCount += 1) };
    if (merge) lastMade.set(merge, job.made);
    // Made while the studio is away, behind those held for it: shown as made at once (what
    // it shows put back, should it be taken back, to before the words it replaces).
    if (waiting) job.shown = [...older.flatMap((each) => each.shown || []), ...showWaiting(action)];
    queue.push(job);
    // (What Undo would take back is now this one: the page says so.)
    if (waiting && action.do !== "read") host.held?.();
    run();
  }
  // When every edit sent has come back: an undo waits for the typing before it.
  async function idle() {
    while (running || queue.length) await new Promise((done) => setTimeout(done, 20));
  }
  async function run() {
    if (running) return;
    running = true;
    try {
      while (queue.length) {
        const job = queue.shift();
        let result;
        try {
          current = job;
          result = await host.run(job.action, { merge: job.merge, hold: job.hold, label: job.label });
          // The studio back: what was held goes, and nothing is said to wait -- nor what was
          // taken back while it was away (made again by an edit of its own, not by ⇧⌘Z).
          if (waiting) { waiting = false; takenBack.length = 0; host.waiting?.(false); host.held?.(); }
        } catch (error) {
          // The studio out of reach (the request never got there): the edit waits, and those
          // after it, and goes when the studio answers again -- the document says it is not
          // saved meanwhile, and nothing is said to have failed.
          if (error instanceof TypeError) {
            if (!waiting) { waiting = true; host.waiting?.(true); }
            // Shown as made meanwhile: the inspector and the list say what waits, as the
            // drawing does.
            job.shown ??= showWaiting(job.action);
            current = null;
            // (Taken back meanwhile, it goes no further; nothing else held, nothing waits.)
            if (!job.taken) queue.unshift(job);
            if (!queue.some((next) => next.action.do !== "read")) { waiting = false; host.waiting?.(false); queue.length = 0; break; }
            await new Promise((done) => setTimeout(done, 2000));
            continue;
          }
          // (Sent for a shape another renamed as it went: sent again, for it under its new name
          // -- once the figure saying so is here, when it is not yet: refused for a shape the
          // figure here still has, it waits for it a moment, then is said.)
          const target = job.action.target, renamed = target?.type === "node" && renamedTo.get(target.id);
          if (renamed && !job.retried) { queue.unshift({ ...job, retried: true, action: { ...job.action, target: { ...target, id: renamed } } }); continue; }
          if (target?.type === "node" && nodeOf(target.id) && !job.retried) { parked.push({ job, error }); setTimeout(unpark, 2000); continue; }
          toast(error.message, { kind: "error", icon: "error", seconds: 6 });
          if (job.merge) typed.delete(job.merge);
          job.failed?.();
          continue;
        }
        if (!result) { if (job.merge) typed.delete(job.merge); job.failed?.(); continue; }
        // The drawing that comes after an edit that moves parts lands smoothly.
        if (LANDS.has(job.action.do)) state.landing = Date.now();
        if (job.merge && !queue.some((next) => next.merge === job.merge)) typed.delete(job.merge);
        const renamed = job.follow && result.select?.length === 1 && result.select[0] !== job.follow ? result.select[0] : null;
        const kept = renamed && state.selected.includes(job.follow) ? state.selected.map((id) => (id === job.follow ? renamed : id)) : null;
        // Its words, waiting to be drawn, are looked for under either name: a drawing begun
        // before the part was named anew still has it under the old.
        if (renamed && typedOver?.ids.includes(job.follow)) typedOver.ids.push(renamed);
        // Drawn under its new name, it lands from where it was, not as a part just made.
        if (renamed) state.renamed.set(renamed, job.follow);
        if (result.model) setModel(result.model, { afresh: job.fresh });
        // (`choose` may ask, as the edit comes back: a part added is not chosen should another
        // have been chosen meanwhile.)
        const choose = typeof job.choose === "function" ? job.choose() : job.choose;
        if (choose && result.select?.length) select(result.select);
        else if (kept) select(kept, { reveal: false });
        job.then?.(result);
      }
    } finally {
      running = false;
    }
  }
  const update = (target, values, merge = null, hold = false) => act({ do: "update", target, values }, { merge, hold, select: false });
  // An edit's values on the figure as the page has it, while the studio that makes it is
  // away: what is shown follows them until the figure comes back made with them.
  function showWaiting(action) {
    const was = [];
    if (action.do !== "update" || !state.model) return was;
    // Words given a shape (in its field, or the inspector's) are shown on the drawing too.
    const words = typeof action.values?.label === "string" ? action.values.label : null;
    if (words !== null && action.target?.type === "node" && nodeOf(action.target.id)) {
      typedOver = { ids: [action.target.id], words, until: Date.now() + 4000, box: null, patch: !/[$\\]/.test(words) };
      queueMicrotask(showTyped);
    }
    for (const target of action.targets || [action.target]) {
      const item = target?.type === "node" ? nodeOf(target.id) : target?.type === "group" ? groupOf(target.id) : target?.type === "edge" ? edgeOf(target.id) : null;
      if (!item) continue;
      for (const [key, value] of Object.entries(action.values || {})) {
        if (key === "id" || key === "kind") continue;
        const path = key.split("."), last = path.pop();
        let at = item;
        for (const step of path) at = at[step] ??= {};
        was.push([at, last, at[last]]);
        if (value === null || value === undefined) delete at[last]; else at[last] = value;
      }
    }
    host.changed();
    return was;
  }
  // The last edit held for the studio while it is away, taken back (⌘Z, Undo): as if never
  // made -- not sent when the studio is back, and what showed it (the drawing's words, the
  // inspector, the list) as it was. Answers whether there was one.
  // Those taken back, the latest last: ⇧⌘Z (Redo) makes them again, as a redo would, until
  // another edit is made.
  const takenBack = [];
  let puttingBack = false;
  let jobCount = 0;
  // Each edit's turn, and the latest made from each field (by its merge): words typed later
  // than an edit refused and sent again carry its words already.
  let madeCount = 0;
  const lastMade = new Map();
  // The edits held for the studio while it is away, in the order they were made ({ key, at,
  // label }): for one history with the document's own; and those taken back, the latest last.
  function heldEdits() {
    if (!waiting) return [];
    const jobs = [...(current && !current.taken && current.action.do !== "read" ? [current] : []),
      ...queue.filter((job) => job.action.do !== "read" && !job.taken)];
    return jobs.map((job) => ({ key: job.key, at: job.at, label: job.label || "Change" }));
  }
  const takenEdits = () => takenBack.map((job) => ({ key: job.key, at: job.at, label: job.label || "Change" }));
  // `key`: that edit (heldEdits'), else the last made.
  function takeBackWaiting(key = null) {
    if (!waiting) return false;
    const at = key === null ? queue.findLastIndex((job) => job.action.do !== "read") : queue.findIndex((job) => job.key === key);
    const job = at >= 0 ? queue.splice(at, 1)[0]
      : current && current.action.do !== "read" && (key === null || current.key === key) ? current : null;
    if (!job || job.taken) return false;
    job.taken = true;
    takenBack.push(job);
    for (const [where, key, value] of [...(job.shown || [])].reverse()) {
      if (value === undefined) delete where[key]; else where[key] = value;
    }
    const targets = job.action.targets || [job.action.target];
    for (const target of targets) {
      if (!target?.id) continue;
      unshowTyped(target.id);
      // Words held before it for the same part are what it shows again.
      const before = [...queue].reverse().find((next) => !next.taken && next.action.do === "update" && next.action.target?.id === target.id
        && typeof next.action.values?.label === "string");
      if (before) {
        const words = before.action.values.label;
        typedOver = { ids: [target.id], words, until: Date.now() + 4000, box: null, patch: !/[$\\]/.test(words) };
        showTyped();
      }
    }
    if (typedOver && targets.some((target) => typedOver.ids.includes(target?.id))) typedOver = null;
    if (inline && targets.some((target) => target?.id === inline.id)) closeInline(false);
    if (!queue.some((next) => next.action.do !== "read") && (!current || current.taken)) { waiting = false; host.waiting?.(false); }
    host.changed();
    toast(`Undid ${job.label || "the last change"}: it was not saved yet`, { icon: "undo", seconds: 2.5 });
    return true;
  }
  // The last edit taken back while the studio was away, made again (⇧⌘Z, Redo): held for
  // the studio as it was, and shown as made. Answers whether there was one.
  // (`key`: that one, takenEdits'; else the last taken back.)
  function putBackWaiting(key = null) {
    const at = key === null ? takenBack.length - 1 : takenBack.findIndex((each) => each.key === key);
    const job = at >= 0 ? takenBack.splice(at, 1)[0] : null;
    if (!job) return false;
    puttingBack = true;
    try {
      act(job.action, { merge: job.merge, hold: job.hold, select: false, follow: job.follow, label: job.label });
    } finally {
      puttingBack = false;
    }
    // Its words on the drawing, as they were shown when it was made.
    const words = job.action.do === "update" && typeof job.action.values?.label === "string" ? job.action.values.label : null;
    if (words !== null && job.action.target?.id) {
      typedOver = { ids: [job.action.target.id], words, until: Date.now() + 4000, box: null, patch: !/[$\\]/.test(words) };
      showTyped();
    }
    toast(`Redid ${job.label || "the change"}: it is saved when the studio is back`, { icon: "redo", seconds: 2.5 });
    return true;
  }
  // What ⌘Z would take back while the studio is away: the last edit held for it, if any.
  const waitingLabel = () => {
    if (!waiting) return null;
    const job = [...queue].reverse().find((next) => next.action.do !== "read") || (current && !current.taken ? current : null);
    return job ? job.label || "Change" : null;
  };
  // What ⇧⌘Z would make again: the last edit taken back while the studio was away.
  const takenLabel = () => (takenBack.length ? takenBack[takenBack.length - 1].label || "Change" : null);

  // -- adding --
  function placement() {
    const id = chosenOne();
    // A group chosen (a module): after it, beside it in what holds it, as a shape chosen is --
    // not inside it (its panel's Add Shape Inside… adds there). The figure chosen: at its end.
    if (id && groupOf(id) && (id === model().root || groupOf(id).implied)) return { parent: id, text: "Adds to the end of the figure" };
    if (id && groupOf(id)) return { after: id, text: `Adds after ${inQuotes(nameOf(id))}` };
    if (id && nodeOf(id)) return { after: id, source: state.chain ? id : null, text: addWhere(id, state.chain).text, from: id };
    // A line chosen: into it, between the two it joins.
    if (id && edgeOf(id)) return lineWhere(id);
    return { text: "Adds to the end of the figure" };
  }
  // A shape put into the line `id`: between the parts it joins, and what that is called --
  // by the Add Shape palette and by Undo alike. (`at`: where on the drawing it was let go, in
  // the overlay's pixels, its stand-in there until it is drawn; else it stands beside the
  // part the line leaves, those after it stepping aside, as a + there puts one.)
  function lineWhere(id, { parent = null, at = null, kind = "block" } = {}) {
    const edge = edgeOf(id), source = nodeOfRef(edge.from), target = nodeOfRef(edge.to);
    const from = inQuotes(nameOf(source)), to = inQuotes(nameOf(target));
    // (It goes in the group that holds both ends, after what there holds the one the line
    // leaves -- figure_edit's `place_between` -- and stands beside that meanwhile.)
    let both = parentOf(source);
    while (both && !inside(target, both.id)) both = parentOf(both.id);
    const holder = (both?.children || []).find((child) => child === source || inside(source, child));
    const beside = holder && host.box(holder) ? holder : source;
    return { into: id, parent, at, beside, text: `Adds between ${from} and ${to}`, label: `Insert ${kindTitle(kind)} Between ${from} and ${to}` };
  }
  // The line a shape added after `source`, joined to it, goes into: `source`'s one line out,
  // wherever it leads -- to the part after it, or to one in another group -- the new shape a
  // step into the flow, between the two (figure_edit's `splice`). Not after a decision: its
  // lines are branches; nor after a part with several lines out: a new one is a branch too.
  function spliceLine(source, kind = "block") {
    const node = nodeOf(source);
    if (!node || node.kind === "decision" || kind === "attention") return null;
    if ((model().nets || []).some((net) => (net.sources || []).some((ref) => nodeOfRef(ref) === source))) return null;
    const lines = model().edges.filter((edge) => nodeOfRef(edge.from) === source);
    const to = lines.length === 1 ? nodeOfRef(lines[0].to) : null;
    return to && to !== source && nodeOf(to) ? lines[0] : null;
  }
  const splices = (source, kind = "block") => { const line = spliceLine(source, kind); return line ? nodeOfRef(line.to) : null; };
  // Where a shape added after `id` goes, and what that is called -- by the Add Shape menu
  // and by Undo alike. A second line out of a part (a decision's other outcome) is a branch:
  // the shape goes on a line of its own under the part (beside it, in a column), beside any
  // branch already there. So does one joined to nothing, after a part joined to the next:
  // never between two parts a line joins. ({ branch: { of, side, word, towards }, text, label })
  // (`insert` false: after the part, joined to it, but never into its line -- a line of its
  // own, as the palette's After choice says.)
  function addWhere(id, joined, kind = "block", insert = true) {
    const name = inQuotes(nameOf(id));
    const into = joined && insert ? splices(id, kind) : null;
    const branch = into ? null : branchOf(id, joined, kind);
    if (branch) {
      return { branch, text: `Adds ${branch.word} ${name}${joined ? ", joined to it" : ""}`, label: `Add ${kindTitle(kind)} ${titled(branch.word)} ${name}` };
    }
    if (into) return { branch: null, text: `Adds between ${name} and ${inQuotes(nameOf(into))}, joined to both`, label: `Insert ${kindTitle(kind)} Between ${name} and ${inQuotes(nameOf(into))}` };
    return { branch: null, text: `Adds after ${name}${joined ? ", joined to it" : ""}`, label: `Add ${kindTitle(kind)} After ${name}` };
  }
  function branchOf(id, joined, kind) {
    const holder = parentOf(id);
    // (As drawn: a column turned to fit a slide is a row there, and written so first.)
    const way = holder && drawnKind(holder);
    if (!holder || !nodeOf(id) || kind === "attention" || !["row", "column"].includes(way)) return null;
    const children = holder.children || [], next = children[children.indexOf(id) + 1];
    // A pair made for a branch: the part, and on a line of its own beside it what branches
    // from it -- a new branch goes beside that one, not between the two.
    const layout = holder.layout || {};
    const pair = holder.id !== model().root && holder.role === "layout" && ["center", "ports"].includes(layout.align) && children.length === 2 && children[0] === id;
    const nodesIn = (child) => (nodeOf(child) ? [child] : (groupOf(child)?.children || []).flatMap(nodesIn));
    const linked = (other) => {
      const ends = new Set(nodesIn(other));
      return model().edges.some((edge) => (nodeOfRef(edge.from) === id && ends.has(nodeOfRef(edge.to))) || (nodeOfRef(edge.to) === id && ends.has(nodeOfRef(edge.from))))
        || (model().nets || []).some((net) => {
          const all = [...(net.sources || []), ...(net.targets || [])].map(nodeOfRef);
          return all.includes(id) && all.some((end) => ends.has(end));
        });
    };
    if (!pair && !(next && linked(next))) return null;
    // Across the flow as it is seen (the figure written as drawn first: see addPart).
    const across = (kind) => (kind === "row" ? "below" : "right");
    const of = pair ? children[1] : id, side = across(way);
    // Said as it is seen: under the part, where the flow runs across; beside it, down.
    const main = pair ? parentOf(holder.id) : holder;
    const word = drawnKind(main) === "row" ? "under" : "beside";
    const towards = drawnKind(parentOf(of) || holder) === "row" ? "bottom" : "right";
    return { of, side, word, towards };
  }

  // The palette of shapes, grouped and searchable: to add one, or (`change`, a part) to
  // make a part another kind of shape.
  // (`into`: a line, the shape chosen put into it, between the two it joins. `next`: a part
  // whose + was ⌥-clicked: the shape chosen is what the + adds, joined to it as the + joins.)
  // (`inside`: a group, the shape chosen added at its end -- its panel's Add Shape Inside….)
  function addPalette(anchor, { change = null, into = null, next = null, inside = null } = {}) {
    if (!model()) return;
    // (Its Connect switch on each time it opens: never off still, unseen, from the last time.)
    if (!change) state.chain = true;
    const where = change ? null : into && edgeOf(into) ? lineWhere(into)
      : inside && groupOf(inside) ? { parent: inside, text: inside === model().root ? "Adds to the end of the figure" : `Adds inside ${inQuotes(nameOf(inside))}` }
      : next && nodeOf(next) ? { after: next, source: next, text: addWhere(next, true).text, from: next } : placement();
    const search = ui.input({ placeholder: "Search shapes" });
    const grid = h("div.add-grid.scroll-thin");
    const current = change ? change.kind || "block" : null;
    // A shape is added by a click -- or dragged out onto the figure, to where it is let go.
    const tile = (kind, part) => h(`button.add-tile${part.unavailable ? ".off" : ""}${kind === current ? ".on" : ""}`, {
      type: "button", title: part.unavailable ? `${part.hint} (${part.unavailable})` : change ? part.hint : `${part.hint} · Drag onto the figure, or onto a line`,
      disabled: Boolean(part.unavailable),
      onclick: () => { if (state.swallow) return; closeMenu(); if (change) retype(change, kind); else addPart(kind, where); },
      onpointerdown: change || part.unavailable ? null : (event) => tilePress(event, kind),
      // (Never the page's own drag of what is under it once the palette goes -- a row of the
      // shapes' list -- and the keys left in the search.)
      onmousedown: change || part.unavailable ? null : (event) => event.preventDefault(),
    }, glyph(kind), h("span", {}, part.title));
    const render = () => {
      const query = search.value.trim().toLowerCase();
      // By its title, its hint, or any other name it goes by ("cylinder", "DB").
      const matches = (part) => !query || `${part.title} ${part.hint} ${part.kind} ${(part.words || []).join(" ")}`.toLowerCase().includes(query);
      const sections = catalog.categories.map((category) => {
        const found = Object.entries(parts).filter(([, part]) => part.category === category && matches(part));
        return found.length ? [h("div.add-head", {}, category), h("div.add-tiles", {}, found.map(([kind, part]) => tile(kind, part)))] : null;
      }).filter(Boolean);
      const groups = change ? [] : catalog.groups.filter((group) => !query || `${group.title} ${group.hint}`.toLowerCase().includes(query));
      if (groups.length) {
        sections.push([h("div.add-head", {}, "Layout"), h("div.add-tiles", {}, groups.map((group) =>
          h("button.add-tile", { type: "button", title: group.hint, onclick: () => { closeMenu(); gather(group, where); } }, glyph(group.kind), h("span", {}, group.title))))]);
      }
      clear(grid, sections.length ? sections : h("div.empty", {}, "No matching shapes"));
    };
    // Enter takes the best match: a title that starts with the words, then one that
    // holds them, then a description that does.
    const best = () => {
      const query = search.value.trim().toLowerCase();
      const ranked = [...grid.querySelectorAll(".add-tile:not(.off)")].map((item) => {
        const title = item.textContent.trim().toLowerCase();
        return { item, rank: !query ? 0 : title.startsWith(query) ? 0 : title.includes(query) ? 1 : 2 };
      });
      ranked.sort((a, b) => a.rank - b.rank);
      return ranked[0]?.item;
    };
    search.addEventListener("input", render);
    search.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); best()?.click(); } });
    const said = h("span", {}, change ? `Changes ${inQuotes(nameOf(change.id))} to another shape. Its text and lines stay.` : where.text);
    // After a part with one line on: into that line, between the two -- as the part's + puts
    // one -- or after it, on a line of its own: which is said, and chosen, here. (Between is
    // joined to both; After is joined to the part should its switch be on.)
    const from = where?.from || null, onto = from ? splices(from) : null;
    const short = (id) => { const name = nameOf(id); return name.length > 32 ? `${name.slice(0, 31).trimEnd()}…` : name; };
    const sayWhere = () => { said.textContent = addWhere(from, Boolean(where.source), "block", where.insert !== false).text; };
    const chain = from ? ui.toggle({ value: Boolean(where.source), label: `Connect from ${inQuotes(nameOf(from))}`, onChange: (value) => {
      state.chain = value;
      where.source = value ? from : null;
      sayWhere();
      search.focus();
    } }) : null;
    const way = onto && where.source ? ui.segmented({ value: "between", key: "add-way", options: [
      { value: "between", label: `Between ${inQuotes(short(from))} and ${inQuotes(short(onto))}`,
        title: `Into the line from ${inQuotes(nameOf(from))} to ${inQuotes(nameOf(onto))}, joined to both` },
      { value: "after", label: `After ${inQuotes(short(from))}`, title: `After ${inQuotes(nameOf(from))}, on a line of its own` },
    ], onChange: (value) => {
      where.insert = value === "between";
      where.source = value === "between" || state.chain ? from : null;
      if (chain) chain.hidden = value === "between";
      sayWhere();
      search.focus();
    } }) : null;
    way?.classList.add("add-way");
    // (Between, it is joined to both: its switch is for After.)
    if (way && chain) chain.hidden = true;
    // Clicked, the switch and the choice leave the keys in the search: what is typed next finds a shape.
    for (const control of [chain, way]) control?.addEventListener("mousedown", (event) => event.preventDefault());
    render();
    const node = popover(onScreen(anchor), h("div.add-palette", {}, search, way, h("div.add-where", {}, icon("info"), said), chain, grid), { className: "add-menu" });
    if (!change) besideFigure(node);
    // While it is open the keys are its own: a letter typed anywhere in it -- or with nothing
    // focused, the switch just clicked -- goes into its search, never to the figure as a command
    // (A, C, G). (A field elsewhere keeps its own.)
    const keys = (event) => {
      if (!node.isConnected) { document.removeEventListener("keydown", keys, true); return; }
      if (event.target === search || event.metaKey || event.ctrlKey || event.isComposing) return;
      if ([...event.key].length !== 1 && event.key !== "Backspace") return;
      if (typingIn(event.target) && !node.contains(event.target)) return;
      search.focus();
    };
    document.addEventListener("keydown", keys, true);
    // Kept to the room there is beside its button, and to the window: the shapes scroll,
    // not the palette -- and, still too tall where it opened, it moves up.
    const room = parseFloat(node.style.maxHeight);
    if (room) {
      grid.style.maxHeight = `${Math.max(120, grid.clientHeight - (node.scrollHeight - room))}px`;
      node.style.overflowY = "";
    }
    const over = () => node.getBoundingClientRect().bottom - (innerHeight - 8);
    if (over() > 0) grid.style.maxHeight = `${Math.max(160, grid.clientHeight - over())}px`;
    if (over() > 0) node.style.top = `${Math.max(8, node.getBoundingClientRect().top - over())}px`;
    setTimeout(() => search.focus(), 20);
  }
  // The palette beside the figure, never over the shape it adds after nor where the new one
  // goes: on whichever side of the figure it fits (over a panel, if need be, as a popover
  // floats), its top level with the figure's; else at the window's side away from the shape.
  function besideFigure(node) {
    const figure = host.element(model()?.root)?.getBoundingClientRect();
    const own = node?.isConnected ? node.getBoundingClientRect() : null;
    if (!figure?.width || !own?.width) return;
    const apart = (a, b) => a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom;
    if (apart(own, figure)) return;
    const chosen = state.selected.map((id) => host.element(id)?.getBoundingClientRect()).find((box) => box?.width) || figure;
    const top = Math.max(8, Math.min(figure.top, innerHeight - 8 - own.height));
    const gap = 12;
    const left = figure.right + gap + own.width <= innerWidth - 8 ? figure.right + gap
      : figure.left - gap - own.width >= 8 ? figure.left - gap - own.width
        : (chosen.left + chosen.right) / 2 < innerWidth / 2 ? innerWidth - 8 - own.width : 8;
    Object.assign(node.style, { left: `${left}px`, top: `${top}px` });
  }
  // Where a menu opens: by its button -- or, the button hidden, by what is chosen.
  function onScreen(anchor) {
    const box = anchor?.getBoundingClientRect?.();
    if (anchor && (!box || box.width || box.height)) return anchor;
    const id = state.selected[state.selected.length - 1];
    const at = id && host.element(id)?.getBoundingClientRect();
    if (at?.width) return { x: at.left, y: at.bottom + 8 };
    const root = host.element(model()?.root)?.getBoundingClientRect();
    return root?.width ? { x: root.left, y: root.top + 12 } : { x: innerWidth / 2 - 196, y: 120 };
  }

  // A part added is ready for its words: they are typed on it as soon as it is drawn.
  // One drawn from a file is named for it (a structure for its PDB ID).
  let typeInto = null;
  // Keys typed while it is on its way (the server adds it, the page draws it) are its words,
  // kept for its editor: "Cache" typed at once is its label, not Connect and Add Shape, and
  // ⌫ takes back a letter, never deletes a part. However long the studio takes, they wait
  // for it: none is lost, nor taken for a command meanwhile.
  let early = null;
  // `where`, as placement() or lineWhere() say it -- or where a shape dragged from the palette
  // was let go: `parent` and `index`, or `side` and `of` (a line of its own beside a part),
  // with the figure's `folds` as it was seen then; `at`, the point on the drawing it was let go
  // at (the overlay's pixels), where it stands until drawn; `label`, its name for Undo.
  async function addPart(kind, where = placement()) {
    // (Refused at once with the studio away, before anything stands in for it: see act.)
    if (host.away?.("add shapes")) return;
    const part = parts[kind];
    const action = { do: "add", kind, parent: where.parent || null, after: where.after || null, source: where.source || null };
    // Into a line: between the two it joins (in the group it was let go in, if it was).
    if (where.into) Object.assign(action, { into: where.into, after: null, source: null });
    else if (where.parent && Number.isInteger(where.index)) action.index = where.index;
    else if (where.side) Object.assign(action, { line: where.side, of: where.of });
    // After a part: where, and what Undo calls it, as the menu said it.
    const insert = where.insert !== false;
    const plan = !where.into && !where.side && where.after && !where.parent && nodeOf(where.after) ? addWhere(where.after, Boolean(where.source), kind, insert) : null;
    if (plan?.branch) Object.assign(action, { line: plan.branch.side, of: plan.branch.of });
    // (Joined to it, into its one line on, wherever that goes: between the two -- after it in
    // its own group, on the side its + is, as a part added after it goes. Not should After
    // have been chosen: then joined to it alone.)
    const onward = plan && !plan.branch && where.source && insert ? spliceLine(where.source, kind) : null;
    if (!insert && where.source) action.splice = false;
    // (Out of a module, should its line leave it: the module's chain goes on outside it, and the
    // new part with it -- after the module, where the line goes.)
    let holder = onward ? parentOf(where.source) : null;
    let framed = holder;
    while (framed && framed.role !== "module") framed = parentOf(framed.id);
    const leaves = Boolean(framed) && !inside(nodeOfRef(onward.to), framed.id);
    if (leaves) holder = framed;
    if (onward) Object.assign(action, { into: onward.id, parent: leaves ? null : holder?.id || null });
    if (part.needs_file) {
      const field = part.fields.find((item) => item.type === "file");
      const file = await host.chooseFile({ title: `Choose ${article(part.title)} ${titled(part.title)}`, types: field.types, action: "Insert" });
      if (!file) return;
      action.node = { properties: { source: file } };
      if (kind === "structure") action.node.label = fileLabel(file);
    }
    // Where it will be drawn, as nearly as can be told before it is: its words are typed
    // there as soon as the figure knows it, and follow it when it is drawn. (Let go at a
    // point, or put into a line, it stands there.)
    const merge = `add:${kind}:${Date.now()}`;
    const guessed = part.needs_file ? null : where.at ? guessAt(where.at, kind)
      : plan?.branch ? guessPlace(plan.branch.of, plan.branch.towards, kind) : guessPlace(leaves ? holder.id : where.after || where.beside, null, kind);
    const guess = part.node?.label ? guessed : null;
    // Until it lands, the figure's frame waits (a slide's): it would frame the figure as it was.
    if (guessed) { adding = Date.now(); host.settled?.(); }
    const mine = part.needs_file ? null : { text: null, done: false, guess, merge, after: where.after || where.source || where.into || null, kind };
    // A part with no words to type (a volume, a junction) stands where it will be all the
    // same, until it is drawn there.
    if (guessed && !guess) {
      const holder = typingPlace(), frame = holder.getBoundingClientRect(), outer = host.overlay.getBoundingClientRect();
      stand({ ...guessed, kind, left: outer.left + guessed.left - frame.left + holder.scrollLeft - holder.clientLeft,
        top: outer.top + guessed.top - frame.top + holder.scrollTop - holder.clientTop }, holder);
      const shown = standing;
      setTimeout(() => { if (standing === shown && !inline) stand(null); }, 4000);
    }
    // Put on its flow's side, before the part after it: those after it on its line step aside
    // for it at once, as the figure will draw them -- its stand-in never over them meanwhile.
    const stepped = guessed && !plan?.branch && guessed.stepping ? stepAside(leaves ? holder.id : where.after || where.beside, guessed) : null;
    early = mine;
    if (mine) leaveWith(mine);
    showEarly(mine);
    // (A group or a branch named as the figure was seen -- a line of a row folded to fit -- by
    // the name it is written with once the figure is written as seen.)
    const add = (written = (id) => id) => act({ ...action, ...(action.parent ? { parent: written(action.parent) } : {}), ...(action.of ? { of: written(action.of) } : {}) }, {
      merge,
      label: (where.into ? lineWhere(where.into, { kind }).label : where.label) || plan?.label || null,
      // (Not chosen, should another have been chosen meanwhile: see leaveWith.)
      select: () => !mine?.left,
      then: (result) => {
        if (!part.needs_file && result.select?.length === 1) arrived(mine, result.select[0]);
        else if (early === mine) early = null;
      },
      failed: () => { if (early === mine) { early = null; stand(null); } stepped?.(); if (adding) { adding = 0; host.settled?.(); } },
    });
    // A branch goes under its part as it is seen: the figure is written as it is drawn first
    // (turned to fit a slide, folded onto lines), in the same step. So is a figure seen folded
    // to fit (a long flow on two lines), whatever is added to it: the new shape takes its place
    // on its line, and the rest keep theirs -- where folding it afresh, its parts counted
    // again, could move one across the fold.
    // (Let go beside a part, the same: where its slot said -- "Right of “B”" on a column turned
    // to fit is right of it as drawn -- as a part dragged there goes: ownLine.)
    const folds = where.folds ?? asSeen().folds;
    const label = (where.into ? lineWhere(where.into, { kind }).label : where.label) || plan?.label || null;
    if (plan?.branch || (where.side && !folds.length)) writeAsDrawn({ merge, label }, add);
    else if (folds.length) {
      arrangeSeen(folds, { merge, label,
        failed: () => { if (early === mine) { early = null; stand(null); } stepped?.(); if (adding) { adding = 0; host.settled?.(); } } }, add);
    } else add();
  }
  // A part asked for, come: typed on as soon as it is drawn, the keys typed meanwhile in its
  // words -- or, another chosen meanwhile (`left`), given the words typed so far, and left be.
  function arrived(mine, id) {
    if (mine) mine.id = id;
    if (!mine?.left) { typeInto = id; placeInline(); return; }
    if (early === mine) early = null;
    giveWords(id, mine.text);
  }
  // A part asked for, not yet known to the figure (the studio slow), stands where it will be
  // drawn -- a new figure's one shape, drawn before the figure is read, where it is -- the
  // words typed on it meanwhile shown on it, a caret after them: never typed into nothing.
  // (Its editor opens there as soon as the figure knows it: placeInline.)
  function showEarly(mine = early) {
    if (!mine || early !== mine || inline) return;
    const kind = mine.kind || nodeOf(mine.id)?.kind || "block";
    const drawn = !mine.guess && mine.id && host.box(mine.id);
    // (In the look its words will have: the figure's, at the scale it is drawn.)
    const look = () => (model() ? figureLook() : { ...figureLook(), size: 8 * (host.element(mine.id)?.getScreenCTM?.()?.a || 1) });
    const guess = mine.guess || (drawn ? { ...drawn, look: look(), paint: paintOf(mine.id) } : null);
    if (!guess) return;
    const holder = typingPlace(), frame = holder.getBoundingClientRect(), outer = host.overlay.getBoundingClientRect();
    // (Over a shape drawn already, its words alone: the shape is there to be seen, but not
    // what it says faintly meanwhile.)
    if (drawn) for (const text of host.element(mine.id)?.querySelectorAll("text") || []) { text.style.visibility = "hidden"; mine.hid = [...(mine.hid || []), text]; }
    stand({ ...guess, kind, left: outer.left + guess.left - frame.left + holder.scrollLeft - holder.clientLeft, bare: Boolean(drawn),
      top: outer.top + guess.top - frame.top + holder.scrollTop - holder.clientTop, words: mine.text ?? "", hint: hintOf({ kind }) }, holder);
  }
  // (Named for them, as a part just added is: see closeInline. A figure not read yet -- just
  // made -- is given them once it is: setModel.)
  let owed = null;
  function giveWords(id, text) {
    if (!text?.trim()) return;
    if (!typeOf(id)) { if (!model()) owed = { id, text }; return; }
    act({ do: "update", target: { type: "node", id }, values: { label: text }, name: "" }, { select: false, follow: id });
  }
  // A part asked for and not yet drawn: a press anywhere but on it (another shape chosen, the
  // slide, a panel) ends its typing -- the keys are the page's again -- and what was typed on it
  // so far is its words when it comes. (So does Esc: see earlyKey.)
  function leaveWith(mine) {
    const leave = (event) => {
      window.removeEventListener("pointerdown", leave, true);
      if (early !== mine) return;
      if (event.target?.closest?.(".fig-inline, .fig-standing")) { window.addEventListener("pointerdown", leave, true); return; }
      mine.left = true;
      early = null;
      if (!inline) stand(null);
      for (const text of mine.hid || []) text.style.visibility = "";
      // (Drawn already, its words go to it now.)
      if (mine.id && typeInto === mine.id) { typeInto = null; giveWords(mine.id, mine.text); }
    };
    window.addEventListener("pointerdown", leave, true);
  }
  // Where a part let go at `point` (in the overlay's pixels) stands until it is drawn: centred
  // there, at the size it is drawn, painted as the figure's own shapes are.
  function guessAt(point, kind) {
    const look = figureLook(), ems = parts[kind]?.size || [5.5, 3.5];
    const width = ems[0] * look.size, height = ems[1] * look.size;
    const like = (model()?.nodes || []).find((node) => (node.kind || "block") === kind) || (model()?.nodes || []).find((node) => !node.kind);
    return { left: point.x - width / 2, top: point.y - height / 2, width, height, look, paint: like ? paintOf(like.id) : { fill: "", stroke: "" }, stepping: false };
  }
  // The figure written as it is drawn -- a column turned to fit the slide as the row it is
  // seen as, a row folded onto lines as those lines -- then `done`: one step with it
  // (`merge`). Should that fail, `done` all the same, on the figure as it is written.
  function writeAsDrawn({ merge, label }, done) {
    const { folds, drawn } = asSeen();
    const real = new Map();
    const steps = folds.length ? folds.map((fold) => () => ({ do: "arrange", id: real.get(fold.id) || fold.id, kind: fold.kind, lines: fold.lines, align: fold.align, fold }))
      : ["row", "column"].map((kind) => {
        const targets = (model()?.groups || []).filter((group) => {
          const shown = drawn.groups.find((each) => each.id === group.id)?.layout?.kind;
          return shown === kind && shown !== writtenKind(group);
        }).map((group) => ({ type: "group", id: group.id }));
        return targets.length ? () => ({ do: "update", targets, values: { "layout.kind": kind } }) : null;
      }).filter(Boolean);
    const next = (index) => {
      if (index >= steps.length) { done((id) => real.get(id) || id); return; }
      const { fold, ...action } = steps[index]();
      act(action, { merge, label, select: false, failed: () => done(),
        then: (result) => {
          if (fold) (result.select || []).forEach((made, line) => real.set(`${fold.id}~line${line + 1}`, made));
          next(index + 1);
        } });
    };
    next(0);
  }
  // A part added after `after` goes beside it, on the side its flow goes on, a step away:
  // its box there (in the overlay's pixels), and its words in the look of `after`'s.
  // (`kind`: what is added -- stood in at the size it is drawn, in ems of the figure's words:
  // a circle a circle's size, not its neighbour's.)
  function guessPlace(after, towards = null, kind = null) {
    const box = after && host.box(after);
    const label = after && host.element(`${after}.label`);
    if (!box) return null;
    const look = label?.getScreenCTM?.() ? lookOf(label) : figureLook();
    const ems = kind && parts[kind]?.size;
    const width = ems ? ems[0] * look.size : Math.max(box.width * 0.7, look.size * 5);
    const height = ems ? ems[1] * look.size : box.height, gap = look.size * 2.5;
    const middle = { x: box.left + box.width / 2, y: box.top + box.height / 2 };
    // On the page, on the side its flow goes on -- or, should a part be drawn there (the one
    // it goes before, say), the side of it that is free: never over another part while the
    // figure makes room for it.
    // On its flow's side the part it goes before is no matter: it steps aside as the figure
    // makes room, and the new one is drawn where it stood. A page that keeps its size (a
    // slide's) is not passed; one that grows with the figure (the figure editor's) may be.
    const page = host.overlay.getBoundingClientRect(), bounded = Boolean(host.fixedPage);
    // (A branch goes across the flow, `towards` that side: nothing steps aside for it.)
    const flow = towards || sideOf(after, box);
    // (The part it goes before: the next in its group -- or, in a figure of no groups, the
    // one its line goes to.)
    const holder = parentOf(after), siblings = holder?.children || [];
    const next = towards ? null : holder ? siblings[siblings.indexOf(after) + 1]
      : nodeOfRef(model()?.edges.find((edge) => nodeOfRef(edge.from) === after)?.to ?? "") || null;
    // On a slide those after it step aside only as far as the slide's edge: should that be
    // too little, the part it goes before is in the way there like any other. (All of
    // those after it on its line step aside: none of them is in its way.)
    const stepsAside = !bounded || roomAhead(after, box, flow, page) >= width + gap;
    const across = flow === "right" || flow === "left", sign = flow === "right" || flow === "bottom" ? 1 : -1;
    const aside = new Set(towards || !stepsAside ? [] : [next, ...followingOf(after, box, across, sign).map((item) => item.id)]);
    const placed = (side) => {
      const x = side === "right" ? box.left + box.width + gap + width / 2 : side === "left" ? box.left - gap - width / 2 : middle.x;
      const y = side === "bottom" ? box.top + box.height + gap + height / 2 : side === "top" ? box.top - gap - height / 2 : middle.y;
      const within = (value, room) => (bounded ? Math.max(4, Math.min(value, room - 4)) : value);
      const left = within(x - width / 2, page.width - width), top = within(y - height / 2, page.height - height);
      return { left, top, side, off: (Math.abs(left - (x - width / 2)) + Math.abs(top - (y - height / 2))) * Math.max(width, height) };
    };
    const others = (model()?.nodes || []).filter((node) => node.id !== after).map((node) => ({ id: node.id, box: host.box(node.id) })).filter((other) => other.box);
    // On a slide, the figure's own box is kept to as well: a stand-in outside it reads as a
    // part of something else.
    const root = bounded ? host.element(model()?.root)?.getBoundingClientRect() : null;
    const frame = root?.width ? { left: root.left - page.left - gap, top: root.top - page.top - gap, right: root.right - page.left + gap, bottom: root.bottom - page.top + gap } : null;
    const outside = ({ left, top }) => (!frame ? 0 : width * height
      - Math.max(0, Math.min(left + width, frame.right) - Math.max(left, frame.left)) * Math.max(0, Math.min(top + height, frame.bottom) - Math.max(top, frame.top)));
    const covers = ({ left, top, side, off }) => off + outside({ left, top }) * 0.5 + others.reduce((sum, { id, box: other }) => sum + (side === flow && aside.has(id) ? 0
      : Math.max(0, Math.min(left + width + 6, other.left + other.width) - Math.max(left - 6, other.left))
      * Math.max(0, Math.min(top + height + 6, other.top + other.height) - Math.max(top - 6, other.top))), 0);
    // (A branch goes where it goes, across the flow: its stand-in is there, never elsewhere.)
    const sides = (towards ? [towards] : [...new Set([flow, "bottom", "right", "top", "left"])]).map(placed);
    const { left, top, side } = sides.reduce((best, place) => (covers(place) < covers(best) ? place : best));
    const body = host.element(after)?.querySelector("rect, path, polygon, ellipse");
    const painted = body ? getComputedStyle(body) : null;
    const paint = { fill: painted?.fill && painted.fill !== "none" ? painted.fill : "", stroke: painted?.stroke && painted.stroke !== "none" ? painted.stroke : "" };
    // (Those after it step aside for it only where it goes on its flow's side.)
    return { left, top, width, height, look, paint, stepping: side === flow && !towards };
  }
  // How far the parts after `after` on its line (`flow` its way) may move along it before
  // one passes the page's edge, in the overlay's pixels.
  function roomAhead(after, box, flow, page) {
    const across = flow === "right" || flow === "left", sign = flow === "right" || flow === "bottom" ? 1 : -1;
    const ahead = followingOf(after, box, across, sign).map((item) => item.box);
    if (!ahead.length) return Infinity;
    return sign > 0
      ? (across ? page.width : page.height) - 4 - Math.max(...ahead.map((one) => (across ? one.left + one.width : one.top + one.height)))
      : Math.min(...ahead.map((one) => (across ? one.left : one.top))) - 4;
  }
  // The parts after `after` on its line, the way it goes (`across`, `sign`): those of its
  // group after it -- or, in a figure of no groups, any -- level with it and beyond it.
  function followingOf(after, box, across, sign) {
    const holder = parentOf(after);
    const level = (other) => (across ? other.top < box.top + box.height && other.top + other.height > box.top
      : other.left < box.left + box.width && other.left + other.width > box.left);
    const beyond = (other) => sign * ((across ? other.left - box.left : other.top - box.top)) > 0;
    const ids = holder ? (holder.children || []).slice((holder.children || []).indexOf(after) + 1)
      : (model()?.nodes || []).map((node) => node.id).filter((id) => id !== after);
    return ids.map((id) => ({ id, box: host.box(id) })).filter((item) => item.box && level(item.box) && beyond(item.box));
  }
  // How wide a part may be drawn where it is, its middle kept: up to the parts beside it on
  // its line (a little short of them), in the overlay's pixels.
  function roomBeside(id, at) {
    const middle = at.left + at.width / 2;
    let left = -Infinity, right = Infinity;
    for (const node of model()?.nodes || []) {
      const other = node.id !== id && host.box(node.id);
      if (!other || other.top >= at.top + at.height || other.top + other.height <= at.top) continue;
      if (other.left + other.width <= middle) left = Math.max(left, other.left + other.width);
      else if (other.left >= middle) right = Math.min(right, other.left);
    }
    const page = host.overlay.getBoundingClientRect();
    const half = Math.min(middle - Math.max(left, 0), Math.min(right, page.width) - middle);
    return Math.max(at.width, 2 * half - 16);
  }
  // How a part is painted where it is drawn: its body's fill and outline.
  function paintOf(id) {
    const body = host.element(id)?.querySelector("rect, path, polygon, ellipse");
    const painted = body ? getComputedStyle(body) : null;
    return { fill: painted?.fill && painted.fill !== "none" ? painted.fill : "", stroke: painted?.stroke && painted.stroke !== "none" ? painted.stroke : "" };
  }
  // How a part's words look where they are drawn: their face, their size in the window's
  // pixels, weight and colour, and the measure (ems) they wrap at.
  function lookOf(label) {
    const style = getComputedStyle(label);
    return { size: parseFloat(style.fontSize) * (label.getScreenCTM()?.a || 1), family: style.fontFamily, weight: style.fontWeight,
      fill: style.fill && style.fill !== "none" ? style.fill : "", measure: Number(label.closest("[data-flexo-measure]")?.dataset.flexoMeasure) || 16 };
  }
  // How words will look on a part that has none yet: as the other parts' words do -- or,
  // with none drawn, at the size a figure's words usually are, in the page's face.
  function figureLook() {
    const root = host.element(model()?.root);
    const label = [...(root?.querySelectorAll('[data-flexo-entity="component"] [id$=".label"]') || [])].find((element) => element.getScreenCTM?.());
    if (label) return lookOf(label);
    return { size: 8 * (root?.getScreenCTM?.()?.a || 1), family: getComputedStyle(host.overlay).fontFamily, weight: "400", fill: "", measure: 16 };
  }
  // What a part with no words is, said faintly where they will go while it is edited --
  // never drawn. Only a part whose kind is worded: a junction or a picture says nothing.
  // (A block's is its name, "Block", as its type and the menus call it.)
  const HINTS = { terminal: "Start", decision: "Decision" };
  // The least size (in the window's pixels) a hint is said at.
  const HINT_SIZE = 11;
  // Where a part's words go while it has none, as the figure will draw them once it has: in
  // the middle of most parts; above its length, in a plasmid's ring; over a panel with a
  // heading (a protein, a plate, a timeline, a construct, a tree, a grid of cells), at its
  // top left, the panel under it -- a structure's centred over it. (`y` is the words'
  // middle, `anchor` which end of them is at `x`; `size` their size, in pixels.)
  // A person's under the figure; a queue's left of its slots, a server's on its upper
  // half, a document's above its curled foot (their middles, as shares of the part).
  const HEADED = new Set(["protein", "wellplate", "timeline", "construct", "tree", "cells"]);
  // A picture with its words in a band over it (attention's grid, a graph, a sequence): over
  // the picture, centred, where the band will be once they are typed.
  const BANDED = new Set(["attention", "channels", "concat", "feature-strip", "graph", "inset", "matrix", "sequence"]);
  const OFF_MIDDLE = { queue: [0.35, 0.5], server: [0.5, 0.34], document: [0.5, 0.42], database: [0.5, 0.62] };
  function wordsAt(node, box, size) {
    const kind = node?.kind || "block", middle = box.left + box.width / 2;
    if (HEADED.has(kind)) return { x: box.left + 3, y: box.top - size * 0.75, anchor: "start" };
    if (kind === "structure" || BANDED.has(kind)) return { x: middle, y: box.top - size * 0.75, anchor: "middle" };
    // (A vector's words are under its cells too.)
    if (kind === "person" || kind === "vector") return { x: middle, y: box.top + box.height + size * 1.1, anchor: "middle" };
    if (kind === "plasmid") return { x: middle, y: box.top + box.height / 2 - size * 1.4, anchor: "middle" };
    const [across, down] = OFF_MIDDLE[kind] || [0.5, 0.5];
    return { x: box.left + box.width * across, y: box.top + box.height * down, anchor: "middle" };
  }
  // The words a shape just added keeps should its editor be done with none typed (Return): its
  // kind's own -- an MLP's "MLP", a database's "Database" -- shown in the field meanwhile. Not
  // a basic shape's sample words ("Block", "Decision?"): it is left without.
  const SAMPLE_WORDS = new Set(["block", "text", "op", "circle", "decision", "image", "junction", "cells", "tree"]);
  const givenWords = (node) => {
    const kind = node?.kind || "block";
    return SAMPLE_WORDS.has(kind) ? "" : words(parts[kind]?.node?.label ?? "").trim();
  };
  const hintOf = (node) => {
    const kind = node?.kind || "block";
    return parts[kind]?.node?.label ? HINTS[kind] || parts[kind].title : "";
  };
  // A key typed while a part just added waits for its editor: answers whether it took it.
  function earlyKey(event) {
    if (!early || event.isComposing) return false;
    // ⌘Return ends the typing once its editor opens, as it does in the editor.
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      if (early.text !== null) early.done = true;
      return true;
    }
    if (event.metaKey || event.ctrlKey) return false;
    const key = event.key;
    if (key === "Tab" || (key.startsWith("F") && key.length > 1)) return false;
    event.preventDefault();
    if (key === "Escape") {
      // Done typing: what was typed is its words when it comes, its editor not opened for it.
      const was = early;
      early = null;
      was.left = true;
      if (!inline) stand(null);
      for (const text of was.hid || []) text.style.visibility = "";
      if (was.id && typeInto === was.id) giveWords(was.id, was.text);
      typeInto = null;
    }
    // Return starts a new line, as in any text (with nothing typed, it opens the editor, as
    // it would).
    else if (key === "Enter") { if (early.text !== null || event.shiftKey) early.text = `${early.text ?? ""}\n`; }
    // Nothing typed yet: the label, chosen whole in its editor, is taken away.
    else if (key === "Backspace" || key === "Delete") early.text = early.text === null ? "" : [...early.text].slice(0, -1).join("");
    else if (key.length === 1 || [...key].length === 1) early.text = `${early.text ?? ""}${key}`;
    showEarly();
    return true;
  }

  // A part just made -- a new figure's one shape -- typed on as soon as it is drawn: the
  // keys typed before (`keys`, each {text} or {key, shift}) and since go into its words, as
  // into a new table's first cell, never taken for commands (A, C, G).
  // (`text`: the words it has been typed so far, typed on from their end -- a part renamed as
  // it was typed in, by another, its editor open again on its new id.)
  function typeSoon(id, keys = [], text = null) {
    const mine = { text, done: false, guess: null, merge: `made:${id}`, id };
    select([id], { reveal: false });
    early = mine;
    typeInto = id;
    leaveWith(mine);
    for (const key of keys) earlyKey({ key: key.text ?? key.key, shiftKey: Boolean(key.shift), preventDefault() {} });
    showEarly(mine);
    // However long it takes to be drawn, it is waited for: should the figure, read, have it no
    // more (deleted meanwhile), the keys are the page's again.
    const wait = () => {
      if (early !== mine) return;
      if (model() && !typeOf(id) && !state.missing.includes(id)) { early = null; if (typeInto === id) typeInto = null; return; }
      setTimeout(wait, 2000);
    };
    setTimeout(wait, 8000);
    placeInline();
  }

  // Those after `after` on its line, moved aside along it for a part put at `guessed` (in
  // the overlay's pixels) until the figure is drawn with it; answers how to put them back.
  function stepAside(after, guessed) {
    const box = after && host.box(after);
    if (!box) return null;
    const flow = sideOf(after, box);
    const across = flow === "right" || flow === "left", sign = flow === "right" || flow === "bottom" ? 1 : -1;
    const following = followingOf(after, box, across, sign);
    if (!following.length) return null;
    const gap = (guessed.look?.size || 8) * 2.5;
    const first = following.reduce((near, item) => (sign * ((across ? item.box.left : item.box.top) - (across ? near.box.left : near.box.top)) < 0 ? item : near));
    const wanted = across
      ? (sign > 0 ? guessed.left + guessed.width + gap - first.box.left : first.box.left + first.box.width - (guessed.left - gap))
      : (sign > 0 ? guessed.top + guessed.height + gap - first.box.top : first.box.top + first.box.height - (guessed.top - gap));
    // On a slide, never past its edge: as far as there is room for (guessPlace looks
    // elsewhere when that is too little).
    const shift = host.fixedPage ? Math.min(wanted, roomAhead(after, box, flow, host.overlay.getBoundingClientRect())) : wanted;
    if (shift <= 0) return null;
    const moved = following.flatMap((item) => elementsOf(item.id)).map((element) => ({ element, base: element.getAttribute("transform") || "" }));
    for (const { element, base } of moved) {
      const scale = unitsPerPixel(element), d = sign * shift * scale;
      element.setAttribute("transform", `${base} translate(${across ? d : 0} ${across ? 0 : d})`.trim());
    }
    // (Their lines, which would point where they were, are faded meanwhile.)
    const ids = new Set(following.map((item) => item.id));
    const lines = model().edges.filter((edge) => ids.has(nodeOfRef(edge.from)) || ids.has(nodeOfRef(edge.to)))
      .map((edge) => host.element(edge.id)).filter(Boolean);
    for (const line of lines) line.classList.add("fig-faded");
    const back = () => {
      for (const { element, base } of moved) if (element.isConnected) { if (base) element.setAttribute("transform", base); else element.removeAttribute("transform"); }
      for (const line of lines) line.classList.remove("fig-faded");
    };
    // (Drawn anew, they are where they go; should it not be, they go back.)
    setTimeout(back, 5000);
    return back;
  }

  function gather(group, where = null) {
    const chosen = state.selected.filter((id) => nodeOf(id) || (groupOf(id) && id !== model().root));
    const at = where || placement();
    // A group stands, dashed, round what it gathers -- or, made empty, where it will be --
    // until it is drawn.
    const boxes = chosen.map((id) => host.box(id)).filter(Boolean);
    const guessed = boxes.length ? null : at.after ? guessPlace(at.after) : null;
    const room = boxes.length ? {
      left: Math.min(...boxes.map((box) => box.left)) - 6, top: Math.min(...boxes.map((box) => box.top)) - 6,
      right: Math.max(...boxes.map((box) => box.left + box.width)) + 6, bottom: Math.max(...boxes.map((box) => box.top + box.height)) + 6,
    } : guessed ? { left: guessed.left, top: guessed.top, right: guessed.left + guessed.width, bottom: guessed.top + guessed.height } : null;
    if (room) {
      const holder = typingPlace(), frame = holder.getBoundingClientRect(), outer = host.overlay.getBoundingClientRect();
      stand({ kind: "group", left: outer.left + room.left - frame.left + holder.scrollLeft - holder.clientLeft,
        top: outer.top + room.top - frame.top + holder.scrollTop - holder.clientTop, width: room.right - room.left, height: room.bottom - room.top }, holder);
      const shown = standing;
      setTimeout(() => { if (standing === shown && !inline) stand(null); }, 4000);
    }
    act({ do: "gather", ids: chosen, layout: group.layout, role: group.role || null,
          parent: chosen.length ? null : at.parent || null, after: chosen.length ? null : at.after || null });
  }

  // `keep`: what stays chosen after (a shape whose line was deleted from its list). Else what
  // is taken out leaves nothing chosen -- the figure still open on its shapes, as Keynote leaves
  // a group being edited: a second ⌫ deletes nothing more (never the whole figure), and Esc
  // chooses the figure itself. (The lines through a shape taken out of a chain are joined up
  // round it: figure_edit's `rejoin`.)
  // (`cut`: taken away by ⌘X, and said so in the history.)
  function remove(ids = state.selected, keep = [], { cut = false } = {}) {
    const gone = ids.filter((id) => id !== model()?.root);
    if (!gone.length) return;
    const kept = keep.filter((id) => typeOf(id) && !gone.includes(id));
    act({ do: "delete", ids: gone }, { select: false, label: cut ? said({ do: "delete", ids: gone }).replace(/^Delete\b/, "Cut") : null });
    // (At once: a ⌫ pressed again before the figure comes back acts on nothing.)
    select(kept, { reveal: false });
    if (!kept.length) open();
  }
  // Nothing chosen in the figure, the figure itself not chosen either: its shapes are being
  // edited (see remove).
  function open() {
    state.inside = true;
    host.changed();
  }

  // What a part's right-click menu offers (the host adds cut, copy and paste): the
  // part is chosen first, as PowerPoint chooses what is right-clicked.
  function menuOf(id, anchor) {
    if (!state.selected.includes(id)) select([id]);
    const node = nodeOf(id), group = groupOf(id), edge = edgeOf(id);
    const isRoot = id === model()?.root;
    const items = [];
    // Several chosen, one of them right-clicked: what is done to them all, as the panel of
    // several offers -- nothing that acts on the one alone. (Lines chosen together into, or
    // out of, the same shape: one line, with a trunk they share.)
    if (state.selected.length > 1) {
      const chosen = [...state.selected], shapes = chosen.some((each) => !isLine(each));
      if (chosen.every(isLine) && joinable(chosen)) items.push({ icon: "right", label: "Join Lines", run: () => joinLines(chosen) });
      if (shapes && chosen.every((each) => !isLine(each))) items.push({ icon: "layout", label: "Group…", keys: "G", run: () => groupMenu(anchor) });
      if (shapes) items.push({ icon: "duplicate", label: "Duplicate", keys: "⌘D", run: () => duplicate(chosen) });
      items.push({ icon: "trash", label: "Delete", keys: "⌫", danger: true, run: () => remove(chosen) });
      return items;
    }
    if (!isRoot && (node || group || isLine(id))) items.push({ icon: "pencil", label: "Edit Text", keys: "↩", run: () => openInline(id) });
    if (node) {
      const kind = nextKind(node);
      // A opens the palette of shapes, to add after the shape chosen: it is that item's key.
      const word = addWhere(id, true, kind).branch?.word || "after";
      // (Into its one line on: inserted there, between the two.)
      const verb = !addWhere(id, true, kind).branch && splices(id, kind) ? "Insert" : "Add";
      items.push({ icon: "plus", label: `${verb} ${titled(parts[kind].title)} ${titled(word)}${parts[kind].needs_file ? "…" : ""}`, run: () => addPart(kind, { after: id, source: id }) },
        { icon: "plus", label: "Add Shape After…", keys: "A", run: () => addPalette(anchor) },
        { icon: "right", label: "Draw Line from Here", keys: "C", run: () => toggleConnect(true) });
    }
    // A line: a shape put into it, between the two it joins -- a block, or one chosen from the
    // palette -- ready for its words.
    if (edge) {
      items.push({ icon: "plus", label: `Insert ${kindTitle("block")}`, run: () => addPart("block", lineWhere(id)) },
        { icon: "plus", label: "Insert Shape…", keys: "A", run: () => addPalette(anchor, { into: id }) });
    }
    // A line joined of several made lines again.
    if (netOf(id)) items.push({ icon: "right", label: "Separate Lines", run: () => separateLine(id) });
    const holder = parentOf(id);
    // As drawn: a column turned to fit the slide is a row on screen.
    const row = holder && drawnKind(holder) === "row";
    if ((node || (group && !isRoot)) && row && (holder.children || []).some((child) => child !== id)) {
      items.push({ icon: "down", label: "Move to Own Row Below", run: () => ownLine(id, holder.id, "below") });
    }
    // A group: a shape added after it (A, as for a shape), or inside it.
    if (group && !isRoot) {
      items.push({ icon: "plus", label: "Add Shape After…", keys: "A", run: () => addPalette(anchor) },
        { icon: "plus", label: "Add Shape Inside…", run: () => addPalette(anchor, { inside: id }) });
    }
    if (group && !isRoot) items.push({ icon: "layout", label: "Ungroup", run: () => act({ do: "ungroup", id }) });
    if (node || (group && !isRoot)) items.push({ icon: "duplicate", label: "Duplicate", keys: "⌘D", run: () => duplicate() });
    if (!isRoot) items.push({ icon: "trash", label: "Delete", keys: "⌫", danger: true, run: () => remove() });
    return items;
  }

  function duplicate(ids = state.selected) {
    const chosen = ids.filter((id) => nodeOf(id) || (groupOf(id) && id !== model()?.root));
    if (chosen.length) act({ do: "duplicate", ids: chosen });
    // (Lines alone: said why nothing happens, as for copying them.)
    else if (ids.length && ids.every(isLine)) toast(linesGoWith("duplicated"), { icon: "info", seconds: 3 });
  }
  // Every part of the figure chosen (⌘A): what its layout holds at the top, as Keynote's Select
  // All chooses a group whole -- copied, its groups go with it.
  function chooseAll() {
    const top = groupOf(model()?.root)?.children || (model()?.nodes || []).map((node) => node.id);
    select(top.filter((id) => typeOf(id)), { reveal: false });
  }

  // -- copied, and pasted (into this figure or another) --
  // A line goes with the shapes it joins: chosen alone, it is not copied (a paste of a line
  // between no shapes would be nothing), nor duplicated -- and that is said.
  const linesGoWith = (done) => `A line is ${done} with the shapes it joins. Select them too.`;
  const uncopied = () => (state.selected.length && state.selected.every(isLine) ? linesGoWith("copied") : null);
  // The parts and groups chosen, with what they hold and the lines between them.
  function clip() {
    const figure = model();
    if (!figure) return null;
    const chosen = state.selected.filter((id) => nodeOf(id) || (groupOf(id) && id !== figure.root));
    const top = chosen.filter((id) => !chosen.some((other) => other !== id && inside(id, other)));
    if (!top.length) return null;
    const nodes = [], groups = [];
    const walk = (id) => {
      if (nodeOf(id)) { nodes.push(structuredClone(nodeOf(id))); return; }
      const group = groupOf(id);
      if (group) { groups.push(structuredClone(group)); (group.children || []).forEach(walk); }
    };
    top.forEach(walk);
    const held = new Set(nodes.map((node) => node.id));
    const edges = figure.edges.filter((edge) => held.has(nodeOfRef(edge.from)) && held.has(nodeOfRef(edge.to))).map((edge) => structuredClone(edge));
    // (The lines joined into one among them too, their look with them: what of each joins
    // the parts copied is pasted -- figure_edit's `carry_nets`.)
    const nets = (figure.nets || []).filter((net) => [...(net.sources || []), ...(net.targets || [])].filter((end) => held.has(nodeOfRef(end))).length > 1)
      .map((net) => structuredClone(net));
    return { top, nodes, groups, edges, nets };
  }
  // After the shape chosen (the one copied, just copied: beside it). A figure seen folded to
  // fit is written as seen first, one step with the paste, as adding does: the copy takes its
  // place on its line, and the rest keep theirs.
  function paste(clipped) {
    const where = placement(), merge = `paste:${Date.now()}`, label = said({ do: "paste", top: clipped.top, groups: clipped.groups });
    const send = (written = (id) => id) => act({ do: "paste", top: clipped.top, nodes: clipped.nodes, groups: clipped.groups, edges: clipped.edges, nets: clipped.nets || [],
      parent: where.parent ? written(where.parent) : null, after: where.after || null }, { merge, label });
    const folds = asSeen().folds;
    if (folds.length) arrangeSeen(folds, { merge, label }, send);
    else send();
  }

  // Whether what is chosen can be grouped: shapes and groups, no lines (nor the layout).
  const canGroup = () => state.selected.length > 0 && state.selected.every((id) => nodeOf(id) || (groupOf(id) && id !== model()?.root));
  function groupMenu(anchor) {
    menu(anchor, catalog.groups.map((group) => ({ label: group.title, hint: group.hint, run: () => gather(group) })));
  }

  // -- lines --
  function toggleConnect(force) {
    const on = force ?? !state.connecting;
    if (!on) state.connecting = null;
    else {
      const from = chosenOne();
      state.connecting = { source: from && nodeOf(from) ? from : null };
    }
    host.changed();
  }
  function hint() {
    const connecting = state.connecting;
    if (!connecting) return null;
    // (One more shape on a joined line, clicked on the drawing: see netEnds.)
    if (connecting.add) {
      return [icon("right"), h("span", {}, "Click the shape to join to ", h("b", {}, netOf(connecting.add)?.kind === "merge" ? `the line into ${nameOf(nodeOfRef(netOf(connecting.add).targets?.[0] || ""))}` : `the line from ${nameOf(nodeOfRef(netOf(connecting.add)?.sources?.[0] || ""))}`)),
        h("span.kbd", {}, "Esc")];
    }
    return [icon("right"),
      connecting.source ? h("span", {}, "Click the shape where the line from ", h("b", {}, nameOf(connecting.source)), " ends") : h("span", {}, "Click the shape where the line starts"),
      h("span.kbd", {}, "Esc")];
  }
  function connectTo(id) {
    const connecting = state.connecting;
    if (!nodeOf(id)) return;
    if (connecting.add) {
      const net = netOf(connecting.add);
      if (!net || [...(net.sources || []), ...(net.targets || [])].some((end) => nodeOfRef(end) === id)) return;
      state.connecting = null;
      closeMenu();
      host.changed();
      act({ do: "join", ids: [net.id], add: id });
      return;
    }
    if (!connecting.source) { connecting.source = id; select([id], { reveal: false }); return; }
    if (id === connecting.source) return;
    const source = connecting.source;
    state.connecting = null;
    host.changed();
    act({ do: "connect", source, target: id });
  }

  // -- choosing on the drawing --
  // A click on a part's empty space (inside a protein map, between a row's parts)
  // chooses the smallest part, then the smallest group, whose box holds the point.
  function around(event) {
    let best = null;
    for (const kind of ["node", "group"]) {
      const items = kind === "node" ? model()?.nodes || [] : (model()?.groups || []).filter((g) => g.id !== model().root);
      for (const item of items) {
        const box = host.element(item.id)?.getBoundingClientRect();
        if (!box || !box.width || event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) continue;
        const area = box.width * box.height;
        if (!best || area < best.area) best = { id: item.id, area };
      }
      if (best) return best.id;
    }
    return null;
  }
  // Pieces drawn inside a part carry ids of their own: the part is what is chosen.
  // A press acted on later (once the figure's parts are known) may find the drawing it
  // was on replaced: it is what is under the pointer now.
  // What a click or double-click was on -- in the drawing as it was then: drawn again since
  // (a figure chosen by that double-click, settled anew, its parts moved), the same element
  // in the new drawing, not whatever has come under the point.
  function targetOf(event) {
    if (event.target?.isConnected !== false) return event.target;
    const svg = host.overlay.querySelector("svg");
    const was = event.target?.closest?.("[data-hit-for], [id]");
    const same = was && (was.dataset?.hitFor ? svg?.querySelector(`[data-hit-for="${CSS.escape(was.dataset.hitFor)}"]`) : svg?.querySelector(`[id="${CSS.escape(was.id)}"]`));
    return same || document.elementsFromPoint(event.clientX, event.clientY).find((hit) => svg?.contains(hit)) || host.overlay;
  }
  function idAt(event) {
    const target = targetOf(event);
    const line = target?.closest?.("[data-hit-for]");
    const lineId = line && host.idOf(line.dataset.hitFor);
    if (lineId && typeOf(lineId)) return lineId;
    for (let at = target; at && at !== host.overlay; at = at.parentElement) {
      if (!at.matches?.("[data-flexo-entity][id]")) continue;
      const id = host.idOf(at.id);
      if (id && typeOf(id)) return id;
    }
    return around(event);
  }
  function click(event) {
    if (state.swallow) { state.swallow = false; return; }  // the end of a drag, not a click
    // (On what was under the pointer as it was pressed: never what a drawing that came in
    // meanwhile put there.)
    const id = idAt(asPressed(event));
    if (state.connecting) { if (id) connectTo(id); return; }
    // (The figure's own layout, clicked where nothing is drawn, is nothing: the page clicked,
    // as Keynote's canvas -- the layout is chosen from the list of shapes.)
    const part = id && id !== model()?.root ? id : null;
    if (event.shiftKey || event.metaKey || event.ctrlKey) {
      if (part) select(state.selected.includes(part) ? state.selected.filter((item) => item !== part) : [...state.selected, part]);
      return;
    }
    select(part ? [part] : []);
  }
  function dblclick(event) {
    const id = idAt(asPressed(event));
    if (!id) return;
    // The part typed on is the part chosen: its panel shows beside it.
    if (chosenOne() !== id) select([id], { reveal: false });
    openInline(id, { at: { x: event.clientX, y: event.clientY } });
  }
  function marks() {
    return state.selected.map((id) => ({ id, box: host.box(id), group: typeOf(id) === "group", name: nameOf(id) })).filter((mark) => mark.box);
  }

  // The marks as the host shows them over the drawing: a frame round each part chosen,
  // and on the one part chosen a + on the side its line leaves by, which adds the part
  // that usually comes next there, joined to it -- into its line, as a step in a flow.
  // What usually comes next: a box after a start, a decision, a structure or a picture
  // (a step that needs no file to be chosen first) -- after anything else too, a molecule's
  // picture, a sequence, a CNN, a grid of cells: what comes next is a step, not another of
  // the same picture. (⌥-click the +, or right-click it, to choose another shape.)
  const AFTER = { terminal: "block", decision: "block", io: "block", text: "block", junction: "block", op: "block", circle: "circle" };
  function nextKind(node) {
    const kind = AFTER[node.kind || "block"] || "block";
    return parts[kind] && !parts[kind].unavailable && !parts[kind].needs_file ? kind : "block";
  }
  // The side the flow goes on by: along the part's row or column as drawn, else toward
  // where its line goes.
  function sideOf(id, box) {
    const holder = parentOf(id);
    const way = holder && (holder.children || []).length > 1 ? shownKind(holder) : null;
    if (way) {
      // A long row folded to fit may run back along its second line (a column, up its
      // second): the flow goes the way the parts beside this one on its line run.
      const children = holder.children, at = children.indexOf(id), mine = centre({ left: box.left, right: box.left + box.width, top: box.top, bottom: box.top + box.height });
      const beside = (other, sign) => {
        const near = other && host.box(other);
        if (!near) return false;
        const middle = centre({ left: near.left, right: near.left + near.width, top: near.top, bottom: near.top + near.height });
        return way === "row" ? near.top < box.top + box.height && near.top + near.height > box.top && sign * (middle.x - mine.x) < 0
          : near.left < box.left + box.width && near.left + near.width > box.left && sign * (middle.y - mine.y) < 0;
      };
      const back = beside(children[at + 1], 1) || beside(children[at - 1], -1);
      return way === "row" ? (back ? "left" : "right") : back ? "top" : "bottom";
    }
    const line = model().edges.find((edge) => nodeOfRef(edge.from) === id);
    const other = line && host.box(nodeOfRef(line.to));
    if (!other) return drawnKind(holder) === "row" ? "right" : "bottom";
    const dx = other.left + other.width / 2 - (box.left + box.width / 2);
    const dy = other.top + other.height / 2 - (box.top + box.height / 2);
    if (Math.abs(dx) > Math.abs(dy)) return dx > 0 ? "right" : "left";
    return dy > 0 ? "bottom" : "top";
  }
  // Whether a + centred at (x, y), in the page's pixels, would cover something drawn: a
  // line, a label, another shape, the page's edge. What holds the part (a group's frame,
  // the slide) is not in the way.
  const PLUS = 18;
  function clearAt(x, y, own) {
    const svg = host.overlay.querySelector("svg");
    const whole = svg?.getBoundingClientRect();
    if (!whole || !own) return true;
    if (x < whole.left + 12 || x > whole.right - 12 || y < whole.top + 12 || y > whole.bottom - 12) return false;
    const mine = own.getBoundingClientRect();
    for (const [dx, dy] of [[0, 0], [11, 0], [-11, 0], [0, 11], [0, -11], [8, 8], [-8, 8], [8, -8], [-8, -8]]) {
      for (const hit of document.elementsFromPoint(x + dx, y + dy)) {
        if (hit === svg || !svg.contains(hit) || own.contains(hit) || /^(g|svg|defs|clipPath)$/i.test(hit.tagName)) continue;
        const box = hit.getBoundingClientRect();
        if (box.left <= mine.left + 1 && box.right >= mine.right - 1 && box.top <= mine.top + 1 && box.bottom >= mine.bottom - 1) continue;
        return false;
      }
    }
    return true;
  }
  // The + in clear space on the side the flow goes on -- slid along that side, or else
  // on another, if a line or a label is there.
  // (`cornered`: the part has handles at its corners, which the + keeps well clear of.)
  function plusPlace(id, box, towards = null, cornered = false) {
    // (A branch's on the side it goes: under the part, or beside it.)
    const flow = towards || sideOf(id, box);
    // On the side the part it adds will go, clear of what is drawn there: along that side,
    // nearer the part, or past its corner -- and only should none of those be clear, on
    // another side that is (never over another part's words or a line), else on its own.
    const outer = host.overlay.getBoundingClientRect();
    const onPage = (place) => place.x > PLUS / 2 && place.y > PLUS / 2 && place.x < outer.width - PLUS / 2 && place.y < outer.height - PLUS / 2;
    const own = host.element(id);
    const at = (side, shift, off = PLUS) => ({
      side,
      x: side === "right" ? box.left + box.width + off : side === "left" ? box.left - off : box.left + box.width / 2 + shift,
      y: side === "bottom" ? box.top + box.height + off : side === "top" ? box.top - off : box.top + box.height / 2 + shift,
    });
    const along = (side) => (side === "right" || side === "left" ? box.height : box.width);
    const tries = (side) => [PLUS, PLUS * 0.75].flatMap((off) => [0, 0.25, -0.25, 0.4, -0.4, 0.5 + PLUS / along(side), -0.5 - PLUS / along(side)]
      .map((share) => at(side, share * along(side), off)));
    // The lines, as points along them in the window's pixels: the + lies on none (a line's
    // drawing may let the pointer through it, so it is not found by pointing).
    const points = [];
    for (const path of host.element(model()?.root)?.querySelectorAll('[data-flexo-entity="connector"] path, [data-flexo-entity="net"] path') || []) {
      const matrix = path.getScreenCTM?.(), length = path.getTotalLength?.() || 0;
      if (!matrix || !length) continue;
      const step = Math.max(length / 200, 3 / (matrix.a || 1));
      for (let along = 0; along <= length; along += step) {
        const point = new DOMPoint(path.getPointAtLength(along).x, path.getPointAtLength(along).y).matrixTransform(matrix);
        points.push(point);
      }
    }
    const offLines = (x, y) => !points.some((point) => Math.abs(point.x - x) < PLUS / 2 + 3 && Math.abs(point.y - y) < PLUS / 2 + 3);
    const corners = cornered ? [[box.left, box.top], [box.left + box.width, box.top], [box.left, box.top + box.height], [box.left + box.width, box.top + box.height]] : [];
    const offCorners = (place) => corners.every(([x, y]) => Math.hypot(place.x - x, place.y - y) >= PLUS + 4);
    const clear = (place) => onPage(place) && offCorners(place) && offLines(outer.left + place.x, outer.top + place.y) && clearAt(outer.left + place.x, outer.top + place.y, own);
    for (const side of [flow, ...["right", "bottom", "left", "top"].filter((other) => other !== flow)]) {
      const found = tries(side).find(clear);
      if (found) return found;
    }
    return at(flow, 0);
  }
  // Where a chosen line's + goes, in the overlay's pixels: beside its middle, off its path --
  // never where the line is clicked, so that a double-click on it (to give it words) is the
  // line's -- clear of its words, of the shapes and of every other line; else beside it a
  // little along it either way. (Should nowhere be clear, off its own path all the same.)
  // (`handles`: where its handles are, in the overlay's pixels, which it keeps clear of too.)
  function plusOnLine(id, handles = []) {
    const element = host.element(id), outer = host.overlay?.getBoundingClientRect();
    const longest = (holder) => [...(holder?.querySelectorAll("path:not(.hit-line)") || [])].filter((each) => each.getTotalLength?.())
      .sort((a, b) => b.getTotalLength() - a.getTotalLength())[0];
    const path = longest(element);
    const matrix = path?.getScreenCTM?.();
    if (!path || !matrix || !outer) return null;
    const screen = (point) => new DOMPoint(point.x, point.y).matrixTransform(matrix);
    // (How far either side of a line a click on it reaches: half its twin's width.)
    const reach = Math.max(3, 4.5 * Math.hypot(matrix.a, matrix.b));
    const radius = 12;
    // (All its words: its label, and the words under it the other way, a reversible step's.)
    const words = [...element.querySelectorAll("text")].map((text) => text.getBoundingClientRect()).filter((rect) => rect.width);
    const shapes = (model()?.nodes || []).map((node) => host.element(node.id)?.getBoundingClientRect()).filter((rect) => rect?.width);
    const offHandles = (spot) => handles.every((handle) => Math.hypot(spot.x - outer.left - handle.x, spot.y - outer.top - handle.y) >= radius + 9);
    const meets = (spot, rect, room = radius) => rect && rect.width && spot.x + room > rect.left && spot.x - room < rect.right && spot.y + room > rect.top && spot.y - room < rect.bottom;
    // Every line's points, in the window's pixels: its own, and the others'.
    const points = [];
    for (const each of host.element(model()?.root)?.querySelectorAll('[data-flexo-entity="connector"] path:not(.hit-line), [data-flexo-entity="net"] path:not(.hit-line)') || []) {
      const at = each.getScreenCTM?.(), length = each.getTotalLength?.() || 0;
      if (!at || !length) continue;
      const step = Math.max(length / 200, 2 / (at.a || 1));
      for (let along = 0; along <= length; along += step) points.push(new DOMPoint(each.getPointAtLength(along).x, each.getPointAtLength(along).y).matrixTransform(at));
    }
    const offLines = (spot) => !points.some((point) => Math.hypot(point.x - spot.x, point.y - spot.y) < radius + reach);
    const own = [];
    const length = path.getTotalLength();
    for (let along = 0; along <= length; along += Math.max(length / 120, 1)) own.push(screen(path.getPointAtLength(along)));
    const offOwn = (spot) => !own.some((point) => Math.hypot(point.x - spot.x, point.y - spot.y) < radius + reach);
    const onPage = (spot) => spot.x - radius > outer.left && spot.y - radius > outer.top && spot.x + radius < outer.right && spot.y + radius < outer.bottom;
    const spots = [];
    for (const share of [0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8]) {
      const middle = screen(path.getPointAtLength(length * share));
      const ahead = screen(path.getPointAtLength(Math.min(length, length * share + 2))), behind = screen(path.getPointAtLength(Math.max(0, length * share - 2)));
      const run = Math.hypot(ahead.x - behind.x, ahead.y - behind.y) || 1;
      const across = { x: -(ahead.y - behind.y) / run, y: (ahead.x - behind.x) / run };
      // (Above a line across, right of one down: then the other side.)
      const first = across.y < 0 || (Math.abs(across.y) < 1e-6 && across.x > 0) ? 1 : -1;
      for (const off of [radius + reach + 3, radius + reach + 9]) {
        for (const sign of [first, -first]) spots.push({ x: middle.x + sign * across.x * off, y: middle.y + sign * across.y * off });
      }
    }
    const clearOf = (spot) => offHandles(spot) && !words.some((rect) => meets(spot, rect)) && !shapes.some((rect) => meets(spot, rect));
    const clear = spots.find((spot) => onPage(spot) && offLines(spot) && clearOf(spot))
      || spots.find((spot) => onPage(spot) && offOwn(spot) && clearOf(spot))
      || spots.find((spot) => onPage(spot) && offOwn(spot) && offHandles(spot)) || spots.find((spot) => onPage(spot) && offOwn(spot)) || spots[0];
    return { x: clear.x - outer.left, y: clear.y - outer.top };
  }
  // A hint said only when its shape is pointed at (too small, or too crowded, to be said
  // always): shown as the pointer comes over the shape, gone as it leaves.
  const pointing = new WeakSet();
  function pointHints() {
    const overlay = host.overlay;
    if (!overlay || pointing.has(overlay)) return;
    pointing.add(overlay);
    overlay.addEventListener("mousemove", (event) => {
      const id = idAt(event);
      for (const hint of overlay.querySelectorAll(".fig-wordless.tight")) {
        hint.classList.toggle("pointed", hint.dataset.id === id || state.selected.includes(hint.dataset.id));
      }
    });
  }
  function markViews() {
    // A line chosen is marked along its path, not by the box round it.
    // (The lines' twins are in the drawing, not the overlay.)
    for (const twin of document.querySelectorAll(".hit-line.chosen")) twin.classList.remove("chosen");
    // (But for one whose words are being typed: its words' box is where it is marked.)
    for (const id of state.selected) if (isLine(id) && inline?.id !== id) for (const twin of host.element(id)?.querySelectorAll(".hit-line") || []) twin.classList.add("chosen");
    // A group's name tag sits over its frame -- else in its top right corner, else under it
    // -- where it hides no words drawn: its own title, the slide's words over the figure.
    const outer = host.overlay.getBoundingClientRect();
    let page = host.element(model()?.root);
    while (page?.ownerSVGElement) page = page.ownerSVGElement;
    const words = [...(page?.querySelectorAll("text") || [])].map((text) => text.getBoundingClientRect()).filter((rect) => rect.width);
    const tagPlace = (box, name) => {
      const width = String(name).length * 6.5 + 14, height = 19;
      const spots = [["", box.left - 2, box.top - height], [".inside", box.left + box.width - width - 3, box.top + 3], [".below", box.left - 2, box.top + box.height]];
      const clear = ([, left, top]) => !words.some((rect) => rect.left < outer.left + left + width && rect.right > outer.left + left
        && rect.top < outer.top + top + height && rect.bottom > outer.top + top);
      return (spots.find(clear) || spots[0])[0];
    };
    // (A shape being typed on has one ring, its words' box: not its own frame behind it too.)
    const typed = inline?.kind === "node" && inline.inPlace ? inline.id : null;
    const views = marks().filter((mark) => !isLine(mark.id) && mark.id !== typed).map(({ id, box, group, name }) => h(`div.fig-mark${group ? ".group" : ""}`, { style: {
      left: `${box.left}px`, top: `${box.top}px`, width: `${box.width}px`, height: `${box.height}px` } },
    group ? h(`span.fig-mark-label${tagPlace(box, name)}`, {}, name) : null));
    // A shape with no words shows what it is, faintly, where they will go (but for one
    // being typed in, or whose drawing says it already, as a slide's lone new shape does).
    let look = null;
    // (Each hint's box, so that none is said over another, nor over a shape.)
    const said = [], shapes = (model()?.nodes || []).map((node) => ({ id: node.id, box: host.box(node.id) })).filter((item) => item.box);
    const meets = (one, other) => one.left < other.left + other.width && one.left + one.width > other.left && one.top < other.top + other.height && one.top + one.height > other.top;
    for (const node of model()?.nodes || []) {
      const hint = !plain(node.label).trim() && inline?.id !== node.id && !typedOver?.ids.includes(node.id) ? hintOf(node) : "";
      const at = hint && !host.element(`${node.id}.label`)?.textContent.trim() ? host.box(node.id) : null;
      if (!at) continue;
      look ??= figureLook();
      // Smaller, should it be wider than the shape has room for (a diamond's or a circle's is
      // its middle, a slanted box's between its slants, a cylinder's under its lid); a
      // heading's is as large as the words will be. Too small so to be read -- the drawing
      // zoomed far out -- it is said only as the shape is pointed at or chosen, under it, at a
      // size that is: never spilling over its neighbours, nor piled on another hint.
      const headed = HEADED.has(node.kind) || node.kind === "structure" || BANDED.has(node.kind);
      const room = at.width * ({ decision: 0.5, circle: 0.62, io: 0.55, queue: 0.6 }[node.kind] || 0.85);
      const tall = at.height * (node.kind === "database" ? 0.45 : 0.8);
      // (A hint is the editor's, not the figure's: never smaller than words on the page round
      // it are, however far the drawing is zoomed out.)
      const wanted = Math.max(look.size, HINT_SIZE);
      const fits = Math.min(wanted, room / (hint.length * 0.55), tall / 1.15);
      const under = !headed && fits < Math.max(HINT_SIZE, look.size * 0.85);
      const size = headed ? wanted : under ? Math.max(HINT_SIZE, look.size * 0.85) : fits;
      const place = under ? { x: at.left + at.width / 2, y: at.top + at.height + size * 0.9, anchor: "middle" } : wordsAt(node, at, size);
      const wide = hint.length * size * 0.58, box = { left: place.anchor === "start" ? place.x : place.x - wide / 2, top: place.y - size * 0.6, width: wide, height: size * 1.2 };
      const crowded = said.some((other) => meets(box, other)) || shapes.some((item) => item.id !== node.id && meets(box, item.box))
        || (headed && wide > at.width + size * 2);
      const tight = under || crowded;
      if (!tight) said.push(box);
      views.push(h(`div.fig-wordless${place.anchor === "start" ? ".start" : ""}${tight ? ".tight" : ""}${tight && state.selected.includes(node.id) ? ".pointed" : ""}`, {
        dataset: { id: node.id }, style: { left: `${place.x}px`, top: `${place.y}px`,
          fontSize: `${size}px`, fontFamily: look.family, fontWeight: HEADED.has(node.kind) || node.kind === "structure" ? "600" : "" } }, hint));
    }
    pointHints();
    const id = chosenOne();
    const box = id && nodeOf(id) && !state.connecting && !inline ? host.box(id) : null;
    // A shape that takes a size of its own (its drawing says the size that fits its words), and
    // a molecule or a picture: handles at its corners.
    const fits = box && !SIZED_PARTS.has(nodeOf(id)?.kind) && !inline ? fitOf(id) : null;
    const sizable = Boolean(box && (SIZED_PARTS.has(nodeOf(id)?.kind) || fits));
    const stop = (event) => event.stopPropagation();
    // ⌥-clicked or right-clicked, a + opens the palette of shapes, to choose what it adds.
    const choose = (event, into = null) => { event.preventDefault(); stop(event); addPalette(event.currentTarget, into ? { into } : { next: id }); };
    if (box) {
      const kind = nextKind(nodeOf(id));
      const { branch } = addWhere(id, true, kind);
      const { side, x, y } = plusPlace(id, box, branch?.towards, sizable);
      views.push(h(`button.fig-next.${side}`, {
        type: "button", style: { left: `${x}px`, top: `${y}px` },
        title: splices(id, kind) ? `Insert ${article(parts[kind].title)} ${inSentence(parts[kind].title)} between ${inQuotes(nameOf(id))} and ${inQuotes(nameOf(splices(id, kind)))} (⌥-click for other shapes)`
          : `Add a connected ${inSentence(parts[kind].title)} ${branch?.word || "after"} ${inQuotes(nameOf(id))} (⌥-click for other shapes)`,
        onpointerdown: stop, ondblclick: stop, onmousemove: stop,
        onclick: (event) => { if (event.altKey) { choose(event); return; } stop(event); addPart(kind, { after: id, source: id }); },
        oncontextmenu: (event) => choose(event),
      }, icon("plus")));
    }
    // A line chosen has its + beside its middle (off its path, clear of its words): a block put
    // into it, between the two it joins, ready for its words. A click that is the second of a
    // double-click is the line's, not the +'s: its words are typed, nothing is put in.
    // A line's handles, each where it is clear of the others: on a line too short for them all
    // (zoomed far out), its middle's goes first, then its ends' -- never one over another, nor
    // over the middle a double-click types its words at. (Its inspector sets them all.)
    const ended = id && isLine(id) && !state.connecting && !inline ? id : null;
    const ends = ended ? endsSeen(ended) : [];
    const apart = ends.length === 2 ? Math.hypot(ends[0].at.x - ends[1].at.x, ends[0].at.y - ends[1].at.y) : Infinity;
    const endsShown = apart >= 18 ? ends : [];
    const curving = ended && ["curved", "straight"].includes(edgeOf(ended)?.shape) ? bendSeen(ended) : null;
    const bending = curving && apart >= 56 && ends.every((end) => Math.hypot(end.at.x - curving.at.x, end.at.y - curving.at.y) >= 22) ? curving : null;
    const line = id && edgeOf(id) && !state.connecting && !inline ? id : null;
    const spot = line && plusOnLine(line, [...endsShown.map((end) => end.at), ...(bending ? [bending.at] : [])]);
    if (spot) {
      const edge = edgeOf(line);
      views.push(h("button.fig-next.on-line", {
        type: "button", style: { left: `${spot.x}px`, top: `${spot.y}px` },
        title: `Insert a block between ${inQuotes(nameOf(nodeOfRef(edge.from)))} and ${inQuotes(nameOf(nodeOfRef(edge.to)))} (⌥-click for other shapes)`,
        onpointerdown: stop, onmousemove: stop,
        ondblclick: (event) => { stop(event); openInline(line); },
        onclick: (event) => {
          stop(event);
          if (event.detail > 1) return;
          if (event.altKey) { choose(event, line); return; }
          addPart("block", lineWhere(line));
        },
        oncontextmenu: (event) => choose(event, line),
      }, icon("plus")));
    }
    // A line chosen has a handle at each end: dragged round its shape, to meet it on another
    // side -- a line's, onto another shape, to go to that one. Double-clicked, the end meets
    // its shape wherever the figure puts it again.
    for (const end of endsShown) {
      views.push(h("span.fig-end", {
        style: { left: `${end.at.x}px`, top: `${end.at.y}px` },
        title: edgeOf(ended) ? "Drag to another side of the shape, or onto another shape · Double-click to reset" : "Drag to another side of the shape · Double-click to reset",
        onpointerdown: (event) => endStart(event, ended, end), onclick: stop, onmousemove: stop,
        ondblclick: (event) => { stop(event); endTo(ended, end.key, ""); },
      }));
    }
    // A curved line chosen -- or a straight one -- has a handle on its middle: dragged, the
    // line bends through it (a straight one turning curved); double-clicked, it bows as it
    // would of itself again.
    if (bending) {
      views.push(h("span.fig-bend", {
        style: { left: `${bending.at.x}px`, top: `${bending.at.y}px` },
        title: "Drag to shape the curve (⌘: without snapping) · Double-click to reset",
        onpointerdown: (event) => bendStart(event, ended, bending), onclick: stop, onmousemove: stop,
        ondblclick: (event) => { stop(event); bendTo(ended, null); },
      }));
    }
    // A molecule chosen is moved by dragging, like any part; it is turned by its handle
    // (or by ⌥-dragging it).
    const molecule = box && nodeOf(id)?.kind === "structure" ? moleculeOf(id)?.getBoundingClientRect() : null;
    if (molecule?.width) {
      views.push(h("button.fig-rotate", {
        type: "button", title: "Drag to rotate the molecule (or ⌥-drag it)",
        style: { left: `${molecule.right - outer.left - 13}px`, top: `${molecule.top - outer.top + 13}px` },
        onpointerdown: (event) => { if (event.button === 0) turnStart(event, id); }, ondblclick: stop, onclick: stop,
      }, icon("refresh")));
    }
    // Molecules being drawn again: a spinner on each, until its new drawing is in.
    for (const [id, { element, since }] of redrawing) {
      const now = moleculeOf(id);
      if (!now || now !== element || Date.now() - since > 20000) { redrawing.delete(id); continue; }
      const at = now.getBoundingClientRect();
      views.push(h("div.fig-redrawing", { title: "Drawing…", style: { left: `${at.left - outer.left + 10}px`, top: `${at.top - outer.top + 10}px` } }, h("span.spinner")));
    }
    // A molecule or picture chosen has a handle at each corner: dragged, it is drawn
    // larger or smaller, and the figure is laid out round it again. Where the figure's own
    // handle is at the same corner, the part's steps inside it.
    // A shape that takes a size of its own (its drawing says the size that fits its words)
    // has one too: dragged, it is drawn that size, snapping to the size that fits its words.
    if (sizable) {
      const theirs = [...host.overlay.querySelectorAll(".size-handle")].map((handle) => handle.getBoundingClientRect()).filter((rect) => rect.width);
      // (A molecule's or a picture's at the corners of its picture, the size it is given: not
      // of its words over it.)
      const picture = fits ? null : host.element(id)?.querySelector("image")?.getBoundingClientRect();
      const whole = host.element(id)?.getBoundingClientRect(), pad = whole?.width ? (box.width - whole.width) / 2 : 0;
      const at = picture?.width ? { left: picture.left - outer.left - pad, top: picture.top - outer.top - pad, width: picture.width + 2 * pad, height: picture.height + 2 * pad } : box;
      for (const corner of ["nw", "ne", "sw", "se"]) {
        let left = corner.endsWith("w") ? at.left : at.left + at.width, top = corner.startsWith("n") ? at.top : at.top + at.height;
        if (theirs.some((rect) => Math.hypot(rect.left + rect.width / 2 - outer.left - left, rect.top + rect.height / 2 - outer.top - top) < 14)) {
          left += corner.endsWith("w") ? 12 : -12;
          top += corner.startsWith("n") ? 12 : -12;
        }
        views.push(h(`span.fig-size.${corner}`, fits ? {
          style: { left: `${left}px`, top: `${top}px` },
          title: "Drag to resize (⇧: keep its proportions) · Double-click to fit it to its words",
          onpointerdown: (event) => shapeSizeStart(event, id, corner, fits), onclick: stop, onmousemove: stop,
          ondblclick: (event) => { event.stopPropagation(); fitWords(id, fits); },
        } : {
          style: { left: `${left}px`, top: `${top}px` },
          title: "Drag to resize · Double-click to reset size",
          onpointerdown: (event) => partSizeStart(event, id, corner),
          ondblclick: (event) => { event.stopPropagation(); update({ type: "node", id }, { "properties.width": null, "properties.height": null }); },
        }));
      }
    }
    return views;
  }

  // A press that dragged, turned or sized something ends in a click on whatever the
  // pointer was let go over -- the slide's margin, say, which would choose nothing: that
  // click is not one, wherever it lands.
  function swallowClick() {
    state.swallow = true;
    const stop = (event) => { event.stopPropagation(); event.preventDefault(); };
    window.addEventListener("click", stop, { capture: true, once: true });
    setTimeout(() => { state.swallow = false; window.removeEventListener("click", stop, { capture: true }); }, 0);
  }

  // -- a molecule or picture sized by its corners --
  // It grows or shrinks about its opposite corner as the pointer goes -- its picture, the size
  // it is given: its words over it stay as they are, laid out round it again -- and let go, it
  // is given that width and height and the figure is laid out again, its parts gliding to
  // where they go. Esc puts it back as it was.
  const SIZED_PARTS = new Set(["structure", "image"]);
  let partSizing = null;
  function partSizeStart(event, id, corner) {
    if (event.button !== 0 || partSizing) return;
    event.preventDefault();
    event.stopPropagation();
    const element = host.element(id);
    const picture = element?.querySelector("image") || element;
    const box = picture?.getBoundingClientRect();
    const unit = element?.getScreenCTM?.()?.a;
    if (!box || !box.width || !unit) return;
    const west = corner.endsWith("w"), north = corner.startsWith("n");
    Object.assign(picture.style, { transformBox: "fill-box", transformOrigin: `${west ? "100%" : "0"} ${north ? "100%" : "0"}`, transform: "" });
    const tip = h("div.fig-turn-tip");
    host.overlay.append(tip);
    partSizing = { id, element: picture, box, unit, tip, scale: 1, moved: false, start: { x: event.clientX, y: event.clientY },
      anchor: { x: west ? box.right : box.left, y: north ? box.bottom : box.top }, handle: { x: west ? box.left : box.right, y: north ? box.top : box.bottom } };
    host.overlay.classList.add("fig-sizing");
    window.addEventListener("pointermove", partSizeMove);
    window.addEventListener("pointerup", partSizeEnd);
    window.addEventListener("pointercancel", partSizeCancel);
    window.addEventListener("keydown", partSizeKey, true);
  }
  function partSizeMove(event) {
    const sizing = partSizing;
    if (!sizing) return;
    if (!sizing.moved && Math.hypot(event.clientX - sizing.start.x, event.clientY - sizing.start.y) < 3) return;
    sizing.moved = true;
    const { anchor, handle, box } = sizing;
    const dx = handle.x - anchor.x, dy = handle.y - anchor.y;
    let scale = ((event.clientX - anchor.x) * dx + (event.clientY - anchor.y) * dy) / (dx * dx + dy * dy || 1);
    scale = Math.min(Math.max(scale, 24 / Math.min(box.width, box.height)), 6);
    if (Math.abs(scale - 1) * box.width < 4) scale = 1;
    sizing.scale = scale;
    sizing.element.style.transform = `scale(${scale})`;
    const outer = host.overlay.getBoundingClientRect();
    sizing.tip.textContent = `${Math.round(scale * 100)}%`;
    Object.assign(sizing.tip.style, { left: `${event.clientX - outer.left}px`, top: `${event.clientY - outer.top + 18}px` });
  }
  function partSizeFinish() {
    const sizing = partSizing;
    partSizing = null;
    window.removeEventListener("pointermove", partSizeMove);
    window.removeEventListener("pointerup", partSizeEnd);
    window.removeEventListener("pointercancel", partSizeCancel);
    window.removeEventListener("keydown", partSizeKey, true);
    host.overlay.classList.remove("fig-sizing");
    sizing?.tip.remove();
    if (sizing?.moved) swallowClick();
    return sizing;
  }
  function partSizeEnd() {
    const sizing = partSizeFinish();
    if (!sizing) return;
    if (!sizing.moved || Math.abs(sizing.scale - 1) < 0.01) { sizing.element.style.transform = ""; return; }
    const { box, unit, scale, id, element } = sizing;
    act({ do: "update", target: { type: "node", id }, values: { "properties.width": Math.round((box.width / unit) * scale), "properties.height": Math.round((box.height / unit) * scale) } },
      { then: () => { state.landing = Date.now(); }, failed: () => { element.style.transform = ""; } });
    // Should no new drawing come, it goes back to the size it is drawn at.
    setTimeout(() => { if (element.isConnected) element.style.transform = ""; }, 6000);
  }
  function partSizeCancel() {
    const sizing = partSizeFinish();
    if (sizing) sizing.element.style.transform = "";
  }
  function partSizeKey(event) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    // (Let go after Esc, the pointer chooses nothing where it is.)
    if (partSizing?.moved) window.addEventListener("pointerup", () => swallowClick(), { capture: true, once: true });
    partSizeCancel();
  }

  // -- a shape sized by its corners --
  // The size that fits a shape's words, as its drawing says (in the figure's units), for a
  // shape that takes a size of its own.
  function fitOf(id) {
    const [width, height] = (host.element(id)?.getAttribute("data-flexo-fit") || "").split(" ").map(Number);
    return width > 0 && height > 0 ? { width, height } : null;
  }
  // The size that fits a shape's words, as it is written: a box's is its own (no size of
  // its own); a diamond's hugs its words closer than it does of itself, so is written.
  const fitValues = (id, fit) => (nodeOf(id)?.kind === "decision"
    ? { width: `${Math.ceil(fit.width)}pt`, height: `${Math.ceil(fit.height)}pt` } : { width: null, height: null });
  // A shape fitted to its words, said so -- a diamond's too, though its size is written.
  const fitWords = (id, fit, options = {}) => act({ do: "update", target: { type: "node", id }, values: fitValues(id, fit) },
    { select: false, label: `Fit ${inQuotes(nameOf(id))} to Its Words`, ...options });
  // Dragged, its outline is drawn at the size it will be, its opposite corner kept: a side
  // within a few pixels of the size that fits its words snaps to it (both: it fits them
  // again, its size its own no longer), and a side not moved keeps what it was; ⇧ keeps
  // its proportions. It is never smaller than its words need (a diamond's, wider and
  // flatter about them as it is drawn so); a circle stays round, and a person keeps its
  // figure's proportions, as they are drawn. Let go, it is that size -- its outline there
  // until it is drawn so -- and the figure is laid out round it again.
  const SIZE_SNAP = 7; // (pixels)
  // Kinds drawn in proportions of their own: a circle round, a person as its figure is (a
  // head and shoulders 0.85 as wide as they are tall, its name under them).
  const PROPORTIONED = new Set(["circle", "person"]);
  const FIGURE_WIDTH = 0.85;
  let shapeSizing = null;
  function shapeSizeStart(event, id, corner, fit) {
    if (event.button !== 0 || shapeSizing || partSizing) return;
    event.preventDefault();
    event.stopPropagation();
    const element = host.element(id);
    const node = nodeOf(id);
    // (A person's box is its figure and its name under it, as it is laid out: not its figure alone.)
    const box = (node?.kind === "person" ? element : host.element(`${id}.body`) || element)?.getBoundingClientRect();
    const unit = element?.getScreenCTM?.()?.a;
    if (!box?.width || !box.height || !unit) return;
    const west = corner.endsWith("w"), north = corner.startsWith("n");
    const drawing = document.createElementNS(SVG_NS, "svg");
    drawing.classList.add("fig-end-drag", "fig-size-drag");
    const outline = document.createElementNS(SVG_NS, node?.kind === "decision" ? "polygon" : node?.kind === "circle" ? "ellipse" : "rect");
    drawing.append(outline);
    const tip = h("div.fig-turn-tip", { hidden: true });
    // (A person's name, under its figure: its band, which stays as it is.)
    const figure = node?.kind === "person" ? host.element(`${id}.body`)?.getBoundingClientRect() : null;
    const band = figure?.height ? Math.max(0, box.bottom - figure.bottom) / unit : 0;
    shapeSizing = { id, element, box, unit, fit, band, kind: node?.kind, drawing, outline, tip, moved: false, start: { x: event.clientX, y: event.clientY },
      had: { width: node?.width ?? null, height: node?.height ?? null },
      anchor: { x: west ? box.right : box.left, y: north ? box.bottom : box.top }, west, north, size: null };
    window.addEventListener("pointermove", shapeSizeMove);
    window.addEventListener("pointerup", shapeSizeEnd);
    window.addEventListener("pointercancel", shapeSizeCancel);
    window.addEventListener("keydown", shapeSizeKey, true);
  }
  // The size the pointer gives it (in the figure's units), snapped, and what is said of it.
  function shapeSizeAt(sizing, clientX, clientY, keep) {
    const { anchor, box, unit, fit, kind, band } = sizing;
    let width = Math.max(8, Math.abs(clientX - anchor.x)) / unit, height = Math.max(8, Math.abs(clientY - anchor.y)) / unit;
    const was = { width: box.width / unit, height: box.height / unit };
    // A person's figure is as tall as it is less its name, and as wide as its figure is, or its
    // name: the pointer gives it as tall as it reaches either way (the figure's width that far
    // out), never less than its words need.
    if (kind === "person") {
      height = Math.max(height, width / FIGURE_WIDTH + band, fit.height);
      width = Math.max(fit.width, FIGURE_WIDTH * (height - band));
    }
    // (In proportion: as far as the pointer reaches either way.)
    const ratio = kind === "circle" ? 1 : kind !== "person" && keep ? was.width / was.height : null;
    if (ratio) {
      const by = Math.max(width / ratio, height);
      width = by * ratio;
      height = by;
    }
    // Never smaller than its words need: the size that fits them -- a diamond any size its
    // words' corners keep inside it, as narrow as just over half its fit (then tall), or as
    // flat as half its fit's height (then wide).
    if (kind === "decision") {
      width = Math.max(width, 0.55 * fit.width);
      height = Math.max(height, fit.height / 2 / (1 - fit.width / (2 * width)));
    } else if (ratio) {
      const by = Math.max(1, fit.width / width, fit.height / height);
      width *= by;
      height *= by;
    } else {
      width = Math.max(width, fit.width);
      height = Math.max(height, fit.height);
    }
    const near = SIZE_SNAP / unit;
    const snapped = { width: false, height: false }, kept = { width: false, height: false };
    if (PROPORTIONED.has(kind)) {
      // (In proportion, both sides fit its words at once.)
      if (Math.abs(height - fit.height) < near) { snapped.width = snapped.height = true; width = fit.width; height = fit.height; }
    } else if (!keep) {
      for (const side of ["width", "height"]) {
        if (Math.abs((side === "width" ? width : height) - fit[side]) < near) { snapped[side] = true; if (side === "width") width = fit.width; else height = fit.height; }
        else if (Math.abs((side === "width" ? width : height) - was[side]) < near) { kept[side] = true; if (side === "width") width = was.width; else height = was.height; }
      }
    }
    const fitted = snapped.width && snapped.height;
    const said = fitted ? "Fits Its Words" : `${Math.round(width)} × ${Math.round(height)} pt`;
    return { width, height, snapped, kept, fitted, said };
  }
  function shapeSizeMove(event) {
    const sizing = shapeSizing;
    if (!sizing) return;
    if (!sizing.moved && Math.hypot(event.clientX - sizing.start.x, event.clientY - sizing.start.y) < 3) return;
    if (!sizing.moved) {
      sizing.moved = true;
      host.overlay.append(sizing.drawing, sizing.tip);
      host.overlay.classList.add("fig-sizing");
    }
    sizing.pointer = { x: event.clientX, y: event.clientY, keep: event.shiftKey };
    const size = shapeSizeAt(sizing, event.clientX, event.clientY, event.shiftKey);
    sizing.size = size;
    const outer = host.overlay.getBoundingClientRect();
    const { anchor, unit, west, north, drawing, outline, tip } = sizing;
    const w = size.width * unit, ht = size.height * unit;
    const left = (west ? anchor.x - w : anchor.x) - outer.left, top = (north ? anchor.y - ht : anchor.y) - outer.top;
    drawing.setAttribute("width", String(outer.width));
    drawing.setAttribute("height", String(outer.height));
    if (sizing.kind === "decision") outline.setAttribute("points", `${left + w / 2},${top} ${left + w},${top + ht / 2} ${left + w / 2},${top + ht} ${left},${top + ht / 2}`);
    else if (sizing.kind === "circle") for (const [key, value] of Object.entries({ cx: left + w / 2, cy: top + ht / 2, rx: w / 2, ry: ht / 2 })) outline.setAttribute(key, String(value));
    else for (const [key, value] of Object.entries({ x: left, y: top, width: w, height: ht, rx: 4 })) outline.setAttribute(key, String(value));
    outline.classList.toggle("fits", size.fitted);
    tip.hidden = false;
    tip.textContent = size.said;
    Object.assign(tip.style, { left: `${left + w / 2}px`, top: `${top + ht + 8}px` });
  }
  function shapeSizeFinish() {
    const sizing = shapeSizing;
    shapeSizing = null;
    window.removeEventListener("pointermove", shapeSizeMove);
    window.removeEventListener("pointerup", shapeSizeEnd);
    window.removeEventListener("pointercancel", shapeSizeCancel);
    window.removeEventListener("keydown", shapeSizeKey, true);
    if (sizing?.moved) swallowClick();
    return sizing;
  }
  function shapeSizeClear(sizing) {
    host.overlay.classList.remove("fig-sizing");
    sizing?.drawing.remove();
    sizing?.tip.remove();
  }
  function shapeSizeEnd() {
    const sizing = shapeSizeFinish();
    const size = sizing?.moved ? sizing.size : null;
    if (!size) { shapeSizeClear(sizing); return; }
    // Fitting its words, it is written as fitValues says. Else a side that fits them has
    // no size of its own, and one not moved keeps what it had -- but for a diamond, whose
    // height is its width's (and its width its height's), and a circle or a person, in
    // proportion: each is the size it is drawn at, both ways.
    const own = (side) => `${Math.round(size[side])}pt`;
    const both = sizing.kind === "decision" || PROPORTIONED.has(sizing.kind);
    const value = (side) => (both ? (size.kept[side] && sizing.had[side] !== null ? sizing.had[side] : own(side))
      : size.snapped[side] ? null : size.kept[side] ? sizing.had[side] : own(side));
    const values = size.fitted ? fitValues(sizing.id, sizing.fit) : { width: value("width"), height: value("height") };
    if (values.width === sizing.had.width && values.height === sizing.had.height) { shapeSizeClear(sizing); return; }
    // Its outline stays where it was let go, the tip gone, until it is drawn at that size (or
    // the edit is refused): it never goes back to the size it was meanwhile.
    sizing.tip.remove();
    const done = { then: () => { state.landing = Date.now(); }, failed: () => shapeSizeClear(sizing) };
    if (size.fitted) fitWords(sizing.id, sizing.fit, done);
    else act({ do: "update", target: { type: "node", id: sizing.id }, values }, done);
    const started = Date.now();
    const wait = () => {
      if (!sizing.element.isConnected || Date.now() - started > 6000) shapeSizeClear(sizing);
      else requestAnimationFrame(wait);
    };
    requestAnimationFrame(wait);
  }
  function shapeSizeCancel() { shapeSizeClear(shapeSizeFinish()); }
  function shapeSizeKey(event) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    // (Let go after Esc, the pointer chooses nothing where it is.)
    if (shapeSizing?.moved) window.addEventListener("pointerup", () => swallowClick(), { capture: true, once: true });
    shapeSizeCancel();
  }

  // -- a line's end dragged to another side of its shape --
  // Where a chosen line's ends are drawn, in the overlay's pixels: [{ key, ref, at, from }]
  // -- `key` the end's ("from" or "to"; a joined line's, its ref), `at` where it meets its
  // shape, `from` where the piece of the line into it starts.
  function shapeSeen(id, outer) {
    const rect = host.element(id)?.getBoundingClientRect();
    return rect && (rect.width || rect.height) ? { left: rect.left - outer.left, top: rect.top - outer.top, right: rect.right - outer.left, bottom: rect.bottom - outer.top } : null;
  }
  function endsSeen(id) {
    const element = host.element(id), outer = host.overlay?.getBoundingClientRect();
    const edge = edgeOf(id), net = netOf(id);
    if (!element || !outer || !(edge || net)) return [];
    const points = [];
    for (const path of element.querySelectorAll("path:not(.hit-line)")) {
      const matrix = path.getScreenCTM?.(), length = path.getTotalLength?.() || 0;
      if (!matrix || !length) continue;
      const seen = (along) => {
        const point = new DOMPoint(path.getPointAtLength(along).x, path.getPointAtLength(along).y).matrixTransform(matrix);
        return { x: point.x - outer.left, y: point.y - outer.top };
      };
      const start = seen(0), end = seen(length);
      points.push({ ...start, from: end }, { ...end, from: start });
    }
    const refs = edge ? [["from", edge.from], ["to", edge.to]] : [...(net.sources || []), ...(net.targets || [])].map((ref) => [String(ref), ref]);
    const ends = refs.map(([key, ref]) => ({ key, ref, ...shapeSeen(nodeOfRef(ref), outer) })).filter((end) => end.left !== undefined);
    const found = endsOf(points, ends);
    return ends.filter((end) => found.has(end.key)).map(({ key, ref }) => ({ key, ref, at: { x: found.get(key).x, y: found.get(key).y }, from: found.get(key).from }));
  }
  // Dragged, the end's way from where the line comes is drawn to the pointer -- to the middle
  // of the side it would meet, over a shape it may go to, the shape framed and the side named.
  // Let go there, it goes (endTo); anywhere else, or with Esc, it stays as it was. A line's
  // end may go to any shape but the one at its other end; a joined line's, round its own.
  let ending = null;
  const SVG_NS = "http://www.w3.org/2000/svg";
  function endStart(event, id, end) {
    if (event.button !== 0 || ending) return;
    event.preventDefault();
    event.stopPropagation();
    const edge = edgeOf(id), outer = host.overlay.getBoundingClientRect();
    const own = nodeOfRef(end.ref), far = edge ? nodeOfRef(edge[end.key === "from" ? "to" : "from"]) : null;
    const shapes = (edge ? model().nodes.map((node) => node.id).filter((node) => node === own || node !== far) : [own])
      .map((node) => ({ id: node, ...shapeSeen(node, outer) })).filter((shape) => shape.left !== undefined);
    ending = { id, end, own, shapes, line: host.element(id), start: { x: event.clientX, y: event.clientY }, pointer: null, moved: false, frame: 0, at: null };
    window.addEventListener("pointermove", endMove);
    window.addEventListener("pointerup", endUp);
    window.addEventListener("pointercancel", endCancel);
    window.addEventListener("keydown", endKey, true);
  }
  function endMove(event) {
    if (!ending) return;
    ending.pointer = { x: event.clientX, y: event.clientY };
    if (!ending.moved) {
      if (Math.hypot(event.clientX - ending.start.x, event.clientY - ending.start.y) < 3) return;
      ending.moved = true;
      const drawing = document.createElementNS(SVG_NS, "svg");
      drawing.classList.add("fig-end-drag");
      const way = document.createElementNS(SVG_NS, "line"), spot = document.createElementNS(SVG_NS, "circle");
      spot.setAttribute("r", "4");
      drawing.append(way, spot);
      const outline = h("div.fig-end-shape"), tip = h("div.fig-turn-tip");
      host.overlay.append(drawing, outline, tip);
      host.overlay.classList.add("fig-ending");
      ending.line?.classList.add("fig-faded");
      document.body.classList.add("fig-grabbing");
      Object.assign(ending, { drawing, way, spot, outline, tip });
    }
    event.preventDefault();
    if (!ending.frame) ending.frame = requestAnimationFrame(endFrame);
  }
  function endFrame() {
    if (!ending?.moved) return;
    ending.frame = 0;
    const { drawing, way, spot, outline, tip, end } = ending;
    const outer = host.overlay.getBoundingClientRect();
    const point = { x: ending.pointer.x - outer.left, y: ending.pointer.y - outer.top };
    const at = endAt(ending.shapes, point);
    ending.at = at;
    const to = at ? at.at : point;
    drawing.setAttribute("width", String(outer.width));
    drawing.setAttribute("height", String(outer.height));
    for (const [name, value] of [["x1", end.from.x], ["y1", end.from.y], ["x2", to.x], ["y2", to.y]]) way.setAttribute(name, String(value));
    spot.setAttribute("cx", String(to.x));
    spot.setAttribute("cy", String(to.y));
    spot.style.visibility = at ? "" : "hidden";
    const box = at && host.box(at.id);
    outline.hidden = !box;
    if (box) Object.assign(outline.style, { left: `${box.left}px`, top: `${box.top}px`, width: `${box.width}px`, height: `${box.height}px` });
    tip.hidden = !at;
    if (at) {
      const side = SIDES.find(([value]) => value === at.side)?.[1] || "Automatic";
      tip.textContent = at.id === ending.own ? side : `${nameOf(at.id)} · ${side}`;
      Object.assign(tip.style, { left: `${point.x}px`, top: `${point.y + 18}px` });
    }
  }
  function endFinish() {
    window.removeEventListener("pointermove", endMove);
    window.removeEventListener("pointerup", endUp);
    window.removeEventListener("pointercancel", endCancel);
    window.removeEventListener("keydown", endKey, true);
    document.body.classList.remove("fig-grabbing");
    const was = ending;
    ending = null;
    if (was?.frame) cancelAnimationFrame(was.frame);
    return was;
  }
  function endClear(was) {
    for (const part of [was.drawing, was.outline, was.tip]) part?.remove();
    was.line?.classList.remove("fig-faded");
    host.overlay.classList.remove("fig-ending");
  }
  function endUp() {
    const was = endFinish();
    if (!was?.moved) return;
    swallowClick();
    const at = was.at;
    const sent = at && endTo(was.id, was.end.key, at.side, { shape: at.id, failed: () => endClear(was) });
    if (!sent) { endClear(was); return; }
    // Its way shown where it goes until the line is drawn there (or the edit is refused).
    was.outline?.remove();
    was.tip?.remove();
    const started = Date.now();
    const wait = () => {
      if (!was.line?.isConnected || Date.now() - started > 6000) endClear(was);
      else requestAnimationFrame(wait);
    };
    requestAnimationFrame(wait);
  }
  function endCancel() { const was = endFinish(); if (was) endClear(was); }
  function endKey(event) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    // (Let go after Esc, the pointer chooses nothing where it is.)
    if (ending?.moved) window.addEventListener("pointerup", () => swallowClick(), { capture: true, once: true });
    endCancel();
  }

  // -- a line bent by its middle --
  // A curved line passes through its middle, and its handle is there: dragged anywhere,
  // the curve is drawn through it as it goes, as it will be -- its middle off the line
  // between its ends by its `bend`, and along that line by its `lean` (shares of the
  // line's length). The handle snaps to where a curve is likely to be wanted: half way
  // between its ends, straight, where it bows of itself, and level with either end, the
  // guide it keeps to drawn; ⌘ held, it snaps to nothing. Measured as the figure
  // measures it, from its whole curve side to side (the shaft's `data-flexo-curve`),
  // else -- a straight line, not yet bent -- from its own ends.
  let bendingNow = null;
  const BEND_SNAP = 7; // (pixels)
  const cubicAt = ([a, b, c, d], t) => {
    const u = 1 - t;
    return { x: u * u * u * a.x + 3 * u * u * t * b.x + 3 * u * t * t * c.x + t * t * t * d.x, y: u * u * u * a.y + 3 * u * u * t * b.y + 3 * u * t * t * c.y + t * t * t * d.y };
  };
  function bendSeen(id) {
    const shaft = host.element(id)?.querySelector("path[id$='.shaft']");
    const outer = host.overlay?.getBoundingClientRect();
    const matrix = shaft?.getScreenCTM?.(), length = shaft?.getTotalLength?.() || 0;
    if (!shaft || !outer || !matrix || !length) return null;
    const numbers = (name, count) => {
      const values = (shaft.getAttribute(name) || "").split(" ").map(Number);
      return values.length === count && values.every(Number.isFinite) ? values : null;
    };
    const whole = numbers("data-flexo-curve", 8);
    let curve;
    if (whole) curve = [0, 2, 4, 6].map((at) => ({ x: whole[at], y: whole[at + 1] }));
    else {
      const a = shaft.getPointAtLength(0), b = shaft.getPointAtLength(length);
      curve = [0, 1, 2, 3].map((step) => ({ x: a.x + ((b.x - a.x) * step) / 3, y: a.y + ((b.y - a.y) * step) / 3 }));
    }
    const rest = numbers("data-flexo-rest", 2);
    const middle = cubicAt(curve, 0.5);
    const seen = (point) => { const at = new DOMPoint(point.x, point.y).matrixTransform(matrix); return { x: at.x - outer.left, y: at.y - outer.top }; };
    return { shaft, matrix, curve, middle, rest: rest ? { x: rest[0], y: rest[1] } : null, at: seen(middle), seen };
  }
  // Where the pointer puts a line's middle (in the figure's units), snapped, the guides it
  // keeps to, what it is said to be, and its bend and lean there (none: as it bows of
  // itself).
  function bendPlace(bending, edge, clientX, clientY, free) {
    let point = new DOMPoint(clientX, clientY).matrixTransform(bending.matrix.inverse());
    point = { x: point.x, y: point.y };
    const [from, , , to] = bending.curve;
    const length = Math.hypot(to.x - from.x, to.y - from.y) || 1;
    const along = { x: (to.x - from.x) / length, y: (to.y - from.y) / length };
    const left = { x: along.y, y: -along.x };
    const near = BEND_SNAP / (Math.hypot(bending.matrix.a, bending.matrix.b) || 1);
    // (A lean kept for a line drawn straight, hidden while it is, leans nothing.)
    const lean = edge?.shape === "curved" ? edge?.lean || 0 : 0;
    // Half way between its ends: the line its middle is centred on.
    const centre = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
    const guides = [];
    let centred = false, straight = false, rest = false;
    if (!free) {
      if (bending.rest && Math.hypot(point.x - bending.rest.x, point.y - bending.rest.y) < near) {
        point = { ...bending.rest };
        rest = true;
      } else {
        const off = (point.x - centre.x) * along.x + (point.y - centre.y) * along.y;
        if (Math.abs(off) < near) {
          point = { x: point.x - off * along.x, y: point.y - off * along.y };
          guides.push({ at: centre, way: left });
          centred = true;
        }
        // (Straight, it is drawn as it will be, straight: no guide along it besides.)
        const rise = (point.x - from.x) * left.x + (point.y - from.y) * left.y;
        if (Math.abs(rise) < near) {
          point = { x: point.x - rise * left.x, y: point.y - rise * left.y };
          straight = true;
        }
        // Level with either end: across from it, or over or under it.
        if (!centred && !straight) {
          for (const end of [from, to]) {
            if (Math.abs(point.x - end.x) < near) { point.x = end.x; guides.push({ at: end, way: { x: 0, y: 1 } }); break; }
          }
          for (const end of [from, to]) {
            if (Math.abs(point.y - end.y) < near) { point.y = end.y; guides.push({ at: end, way: { x: 1, y: 0 } }); break; }
          }
        }
      }
    }
    const clamp = (value, most) => Math.round(Math.max(-most, Math.min(most, value)) * 100) / 100;
    const bend = clamp(((point.x - from.x) * left.x + (point.y - from.y) * left.y) / length, 1);
    const leaning = clamp(lean + ((point.x - bending.middle.x) * along.x + (point.y - bending.middle.y) * along.y) / length, 0.5);
    // Snapped straight, it is a straight line, as its Routing names one -- no bend of nothing,
    // no lean -- and back where it bows of itself, it bows so (as its Bend field says,
    // Automatic).
    const said = rest ? "Automatic" : straight ? "Straight" : centred ? "Centred" : "";
    return { point, guides, said, values: rest ? null : straight ? { straight: true } : { bend, lean: leaning } };
  }
  function bendTo(id, values) {
    const edge = edgeOf(id);
    if (!edge) return false;
    if (values === null) {
      if (edge.bend === undefined && edge.lean === undefined) return false;
      act({ do: "update", target: { type: "edge", id }, values: { bend: null, lean: null } }, { select: false, label: "Reset Bend" });
      return true;
    }
    if (values.straight) {
      if (edge.shape === "straight" && edge.bend === undefined && edge.lean === undefined) return false;
      act({ do: "update", target: { type: "edge", id }, values: { shape: "straight", bend: null, lean: null } }, { select: false, label: "Straighten Line" });
      return true;
    }
    const lean = values.lean || null;
    if (edge.shape === "curved" && (edge.bend ?? null) === values.bend && (edge.lean ?? null) === lean) return false;
    act({ do: "update", target: { type: "edge", id }, values: { shape: "curved", bend: values.bend, lean } },
      { select: false, label: edge.shape === "curved" ? "Bend Line" : "Curve Line" });
    return true;
  }
  function bendStart(event, id, bending) {
    if (event.button !== 0 || bendingNow || ending) return;
    event.preventDefault();
    event.stopPropagation();
    // (The shapes it joins, where they are drawn: its curve is shown from where it leaves one to
    // where it meets the other, as it is drawn -- not from inside them.)
    const edge = edgeOf(id), outer = host.overlay.getBoundingClientRect();
    const shapes = edge ? [shapeSeen(nodeOfRef(edge.from), outer), shapeSeen(nodeOfRef(edge.to), outer)] : [];
    bendingNow = { id, bending, edge, shapes, start: { x: event.clientX, y: event.clientY }, pointer: null, free: false, moved: false, frame: 0, line: host.element(id) };
    window.addEventListener("pointermove", bendMove);
    window.addEventListener("pointerup", bendUp);
    window.addEventListener("pointercancel", bendCancel);
    window.addEventListener("keydown", bendKey, true);
    window.addEventListener("keyup", bendKey, true);
  }
  function bendMove(event) {
    if (!bendingNow) return;
    bendingNow.pointer = { x: event.clientX, y: event.clientY };
    bendingNow.free = event.metaKey;
    if (!bendingNow.moved) {
      if (Math.hypot(event.clientX - bendingNow.start.x, event.clientY - bendingNow.start.y) < 3) return;
      bendingNow.moved = true;
      const drawing = document.createElementNS(SVG_NS, "svg");
      drawing.classList.add("fig-end-drag");
      const guides = document.createElementNS(SVG_NS, "g"), way = document.createElementNS(SVG_NS, "path"), spot = document.createElementNS(SVG_NS, "circle");
      const heads = document.createElementNS(SVG_NS, "g");
      guides.classList.add("fig-guides");
      heads.classList.add("fig-heads");
      spot.setAttribute("r", "4");
      drawing.append(guides, way, heads, spot);
      const tip = h("div.fig-turn-tip");
      host.overlay.append(drawing, tip);
      host.overlay.classList.add("fig-ending");
      bendingNow.line?.classList.add("fig-faded");
      document.body.classList.add("fig-grabbing");
      Object.assign(bendingNow, { drawing, guides, way, heads, spot, tip });
    }
    event.preventDefault();
    if (!bendingNow.frame) bendingNow.frame = requestAnimationFrame(bendFrame);
  }
  function bendFrame() {
    if (!bendingNow?.moved) return;
    bendingNow.frame = 0;
    const { drawing, guides, way, heads, spot, tip, bending, edge, shapes } = bendingNow;
    const outer = host.overlay.getBoundingClientRect();
    drawing.setAttribute("width", String(outer.width));
    drawing.setAttribute("height", String(outer.height));
    const placed = bendPlace(bending, edge, bendingNow.pointer.x, bendingNow.pointer.y, bendingNow.free);
    bendingNow.placed = placed;
    // The curve it will be: both controls moved 4/3 as far as its middle is.
    const shift = { x: (4 / 3) * (placed.point.x - bending.middle.x), y: (4 / 3) * (placed.point.y - bending.middle.y) };
    const [a, b, c, d] = bending.curve;
    const curve = [a, { x: b.x + shift.x, y: b.y + shift.y }, { x: c.x + shift.x, y: c.y + shift.y }, d].map(bending.seen);
    // From where it leaves the shape it starts at to where it meets the other, as it will be
    // drawn, its arrowheads on it.
    // (Snapped straight, it is drawn straight: between its shapes' middles.)
    const middle = (box) => (box ? { x: (box.left + box.right) / 2, y: (box.top + box.bottom) / 2 } : null);
    const ends = placed.values?.straight && shapes[0] && shapes[1] ? [middle(shapes[0]), middle(shapes[1])] : null;
    const points = Array.from({ length: 65 }, (_, step) => (ends
      ? { x: ends[0].x + ((ends[1].x - ends[0].x) * step) / 64, y: ends[0].y + ((ends[1].y - ends[0].y) * step) / 64 } : cubicAt(curve, step / 64)));
    const within = (point, box) => box && point.x > box.left && point.x < box.right && point.y > box.top && point.y < box.bottom;
    let first = points.findIndex((point) => !within(point, shapes[0])), last = points.findLastIndex((point) => !within(point, shapes[1]));
    if (first < 0 || last <= first) { first = 0; last = points.length - 1; }
    const shown = points.slice(first, last + 1);
    way.setAttribute("d", `M ${shown.map((point) => `${point.x} ${point.y}`).join(" L ")}`);
    const head = (tip, from) => {
      const run = Math.hypot(tip.x - from.x, tip.y - from.y) || 1, ux = (tip.x - from.x) / run, uy = (tip.y - from.y) / run;
      const polygon = document.createElementNS(SVG_NS, "polygon");
      polygon.setAttribute("points", [[0, 0], [-8, 3.5], [-8, -3.5]].map(([along, across]) => `${tip.x + ux * along - uy * across},${tip.y + uy * along + ux * across}`).join(" "));
      return polygon;
    };
    const arrow = edge?.arrow || "end", count = shown.length;
    heads.replaceChildren(...(count > 3 && arrow !== "none" ? [head(shown[count - 1], shown[count - 3])] : []),
      ...(count > 3 && ["both", "reversible"].includes(arrow) ? [head(shown[0], shown[2])] : []));
    const at = bending.seen(placed.point);
    spot.setAttribute("cx", String(at.x));
    spot.setAttribute("cy", String(at.y));
    // Each guide across the page, through the point it keeps to.
    const reach = 4000;
    guides.replaceChildren(...placed.guides.map(({ at: through, way: toward }) => {
      const one = bending.seen({ x: through.x - toward.x * reach, y: through.y - toward.y * reach });
      const two = bending.seen({ x: through.x + toward.x * reach, y: through.y + toward.y * reach });
      const line = document.createElementNS(SVG_NS, "line");
      for (const [key, value] of Object.entries({ x1: one.x, y1: one.y, x2: two.x, y2: two.y })) line.setAttribute(key, String(value));
      return line;
    }));
    tip.textContent = placed.said;
    tip.hidden = !placed.said;
    Object.assign(tip.style, { left: `${at.x}px`, top: `${at.y + 16}px` });
  }
  function bendFinish() {
    window.removeEventListener("pointermove", bendMove);
    window.removeEventListener("pointerup", bendUp);
    window.removeEventListener("pointercancel", bendCancel);
    window.removeEventListener("keydown", bendKey, true);
    window.removeEventListener("keyup", bendKey, true);
    document.body.classList.remove("fig-grabbing");
    const was = bendingNow;
    bendingNow = null;
    if (was?.frame) cancelAnimationFrame(was.frame);
    return was;
  }
  function bendClear(was) {
    was.drawing?.remove();
    was.tip?.remove();
    was.line?.classList.remove("fig-faded");
    host.overlay.classList.remove("fig-ending");
  }
  function bendUp() {
    const was = bendFinish();
    if (!was?.moved || !was.pointer) return;
    swallowClick();
    was.tip?.remove();
    const placed = bendPlace(was.bending, was.edge, was.pointer.x, was.pointer.y, was.free);
    if (!bendTo(was.id, placed.values)) { bendClear(was); return; }
    // Its curve shown until the line is drawn bent (or the edit is refused).
    was.guides?.replaceChildren();
    const started = Date.now();
    const wait = () => {
      if (!was.line?.isConnected || Date.now() - started > 6000) bendClear(was);
      else requestAnimationFrame(wait);
    };
    requestAnimationFrame(wait);
  }
  function bendCancel() { const was = bendFinish(); if (was) bendClear(was); }
  function bendKey(event) {
    // ⌘ pressed or let go: snapping off or on again, where the pointer is.
    if (event.key === "Meta") {
      if (bendingNow?.moved) { bendingNow.free = event.type === "keydown"; if (!bendingNow.frame) bendingNow.frame = requestAnimationFrame(bendFrame); }
      return;
    }
    if (event.type !== "keydown" || event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    if (bendingNow?.moved) window.addEventListener("pointerup", () => swallowClick(), { capture: true, once: true });
    bendCancel();
  }

  // -- a structure turned by dragging on it --
  // Chosen, a molecule is grabbed and turned as in a viewer: across turns it (yaw), up
  // and down tilts it (pitch). While it turns, its chains' trace is drawn turning over
  // it -- in mol-sketch's own frame, so it lies as the molecule will -- and once let go,
  // the molecule is drawn at the new turn.
  const views = new Map();
  const moleculeOf = (id) => host.element(`${id}.molecule`);
  // A press that turns the molecule chosen: ⌥ held, over the molecule. (Pressed
  // without, it is moved like any part.)
  function turnable(event) {
    const id = chosenOne();
    if (!event.altKey || !id || nodeOf(id)?.kind !== "structure") return false;
    const box = moleculeOf(id)?.getBoundingClientRect();
    return Boolean(box && event.clientX >= box.left && event.clientX <= box.right && event.clientY >= box.top && event.clientY <= box.bottom);
  }
  async function viewOf(id) {
    const node = nodeOf(id);
    const key = JSON.stringify([id, node?.properties]);
    if (!views.has(key)) views.set(key, host.run({ do: "structure-view", id }, { merge: null }).then((result) => result?.view || null).catch(() => null));
    return views.get(key);
  }
  let turning = null;
  function turnStart(event, id) {
    event.preventDefault();
    event.stopPropagation();
    const molecule = moleculeOf(id);
    if (!molecule) return;
    const outer = host.overlay.getBoundingClientRect(), box = molecule.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const canvas = h("canvas.fig-turn", { width: Math.round(box.width * ratio), height: Math.round(box.height * ratio),
      style: { left: `${box.left - outer.left}px`, top: `${box.top - outer.top}px`, width: `${box.width}px`, height: `${box.height}px` } });
    const tip = h("div.fig-turn-tip", { style: { left: `${box.left - outer.left + box.width / 2}px`, top: `${box.top - outer.top + box.height + 6}px` } });
    turning = { id, molecule, canvas, tip, from: { x: event.clientX, y: event.clientY }, by: { x: 0, y: 0 }, view: null, frame: 0, moved: false };
    const mine = turning;
    viewOf(id).then((view) => { if (turning === mine) { mine.view = view; turnDraw(); } });
    window.addEventListener("pointermove", turnMove);
    window.addEventListener("pointerup", turnEnd);
    window.addEventListener("pointercancel", turnCancel);
    window.addEventListener("keydown", turnKey, true);
  }
  const TURN = 0.5;  // degrees a pixel
  const angle = (value) => Math.round(((((value % 360) + 540) % 360) - 180) * 10) / 10;
  function turnAngles(turn = turning) {
    const camera = turn.view?.camera || { yaw: 0, pitch: 0, roll: 0 };
    return { yaw: angle(camera.yaw + turn.by.x * TURN), pitch: angle(camera.pitch + turn.by.y * TURN), roll: camera.roll || 0 };
  }
  function turnMove(event) {
    if (!turning) return;
    turning.by = { x: event.clientX - turning.from.x, y: event.clientY - turning.from.y };
    if (!turning.moved && Math.hypot(turning.by.x, turning.by.y) < 3) return;
    if (!turning.moved) {
      turning.moved = true;
      host.overlay.append(turning.canvas, turning.tip);
      turning.molecule.classList.add("fig-turning");
      document.body.classList.add("fig-grabbing");
    }
    if (!turning.frame) turning.frame = requestAnimationFrame(() => { if (turning) { turning.frame = 0; turnDraw(); } });
  }
  function turnDraw() {
    const { canvas, view, tip } = turning;
    if (!turning.moved) return;
    const { yaw, pitch, roll } = turnAngles();
    tip.textContent = `Yaw ${Math.round(yaw)}° · Pitch ${Math.round(pitch)}°`;
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    if (!view?.chains?.length) return;
    const [cy, sy, cp, sp, cr, sr] = [yaw, yaw, pitch, pitch, roll, roll].map((value, index) => (index % 2 ? Math.sin : Math.cos)(value * Math.PI / 180));
    // As mol-sketch turns it: about y by yaw, x by pitch, then z by roll; y up on the page.
    const chains = view.chains.map((chain) => chain.map(([x, y, z]) => {
      const x1 = cy * x + sy * z, z1 = -sy * x + cy * z;
      const y2 = cp * y - sp * z1, z2 = sp * y + cp * z1;
      return [cr * x1 - sr * y2, -(sr * x1 + cr * y2), z2];
    }));
    const all = chains.flat();
    const [left, right] = [Math.min(...all.map((p) => p[0])), Math.max(...all.map((p) => p[0]))];
    const [top, bottom] = [Math.min(...all.map((p) => p[1])), Math.max(...all.map((p) => p[1]))];
    const [near, far] = [Math.max(...all.map((p) => p[2])), Math.min(...all.map((p) => p[2]))];
    const pad = 0.08 * Math.min(canvas.width, canvas.height);
    const scale = Math.min((canvas.width - 2 * pad) / Math.max(right - left, 1), (canvas.height - 2 * pad) / Math.max(bottom - top, 1));
    const at = ([x, y]) => [canvas.width / 2 + (x - (left + right) / 2) * scale, canvas.height / 2 + (y - (top + bottom) / 2) * scale];
    // (The accent as a colour a canvas takes: the Mac's may be named, AccentColor, not given.)
    const probe = h("span", { style: { color: "var(--accent)", display: "none" } });
    host.overlay.append(probe);
    const ink = getComputedStyle(probe).color || "#0a7aff";
    probe.remove();
    context.lineCap = "round";
    context.lineJoin = "round";
    // Segments far to near, the near ones darker and thicker: the trace reads in depth.
    const segments = chains.flatMap((chain) => chain.slice(1).map((point, index) => [chain[index], point]));
    segments.sort((a, b) => (a[0][2] + a[1][2]) - (b[0][2] + b[1][2]));
    const ratio = window.devicePixelRatio || 1;
    for (const [a, b] of segments) {
      const depth = near > far ? ((a[2] + b[2]) / 2 - far) / (near - far) : 1;
      context.strokeStyle = ink;
      context.globalAlpha = 0.25 + 0.75 * depth;
      context.lineWidth = (1.2 + 2.2 * depth) * ratio;
      context.beginPath();
      context.moveTo(...at(a));
      context.lineTo(...at(b));
      context.stroke();
    }
    context.globalAlpha = 1;
  }
  function turnFinish() {
    window.removeEventListener("pointermove", turnMove);
    window.removeEventListener("pointerup", turnEnd);
    window.removeEventListener("pointercancel", turnCancel);
    window.removeEventListener("keydown", turnKey, true);
    document.body.classList.remove("fig-grabbing");
    const was = turning;
    turning = null;
    if (was?.frame) cancelAnimationFrame(was.frame);
    return was;
  }
  // The trace stays over the molecule until it is drawn again at its new turn.
  function turnClear(was) {
    was.canvas.remove();
    was.tip.remove();
    was.molecule.classList.remove("fig-turning");
  }
  function turnEnd() {
    const was = turnFinish();
    if (!was) return;
    if (!was.moved || !was.view) { turnClear(was); return; }
    // A press that turned it is not a click on it.
    swallowClick();
    const { yaw, pitch } = turnAngles(was);
    was.tip.textContent = "Rendering…";
    const values = { "properties.yaw": yaw || null, "properties.pitch": pitch || null };
    act({ do: "update", target: { type: "node", id: was.id }, values }, { select: false, failed: () => turnClear(was) });
    const started = Date.now();
    const wait = () => {
      if (moleculeOf(was.id) !== was.molecule || Date.now() - started > 8000) turnClear(was);
      else requestAnimationFrame(wait);
    };
    requestAnimationFrame(wait);
  }
  function turnCancel() { const was = turnFinish(); if (was) turnClear(was); }
  function turnKey(event) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    turnCancel();
  }

  // -- dragging a part to another place --
  // A part pressed and moved follows the pointer, lifted; a line between the parts it
  // would go between shows where it lands, gliding as the pointer goes, the group it
  // would join outlined and the parts either side of the line parted for it. Let go,
  // it is moved there (the server writes it into the file) and the drawing that comes
  // back lands smoothly (land); Esc, or letting go where it was, sends it home.
  let drag = null;
  const SVG = (element) => element?.ownerSVGElement || element;
  const unitsPerPixel = (element) => 1 / ((element?.parentNode?.getScreenCTM?.() || SVG(element)?.getScreenCTM?.())?.a || 1);
  const centre = (box) => ({ x: (box.left + box.right) / 2, y: (box.top + box.bottom) / 2 });
  // What is drawn of a part: a group's frame and everything it holds -- each element
  // once, the outermost, as a framed group draws its parts inside itself.
  function elementsOf(id) {
    const found = [];
    const walk = (at) => {
      const element = host.element(at);
      if (element) found.push(element);
      for (const child of groupOf(at)?.children || []) walk(child);
    };
    walk(id);
    return found.filter((element) => !found.some((other) => other !== element && other.contains(element)));
  }
  function boxOf(id, boxes) {
    if (boxes.has(id)) return boxes.get(id);
    let box = null;
    // A part's drawing; a group's frame and label, if it has them, and what it holds.
    const drawn = host.element(id)?.getBoundingClientRect();
    if (drawn && (drawn.width || drawn.height)) box = { left: drawn.left, top: drawn.top, right: drawn.right, bottom: drawn.bottom };
    for (const child of groupOf(id)?.children || []) {
      const inner = boxOf(child, boxes);
      if (!inner) continue;
      box = box ? { left: Math.min(box.left, inner.left), top: Math.min(box.top, inner.top),
        right: Math.max(box.right, inner.right), bottom: Math.max(box.bottom, inner.bottom) } : { ...inner };
    }
    boxes.set(id, box);
    return box;
  }
  function inside(id, ancestor) {
    for (let at = id; at; at = parentOf(at)?.id) if (at === ancestor) return true;
    return false;
  }

  function pointerdown(event) {
    if (event.button !== 0 || state.connecting || inline) return;
    if (turnable(event)) { turnStart(event, chosenOne()); return; }
    const id = idAt(event);
    // Pressed where nothing is drawn, in a figure that is the whole document (the figure
    // editor's): a drag chooses what it touches. (On a slide it moves the figure: the deck's.)
    if (host.whole && (!id || id === model()?.root) && !event.metaKey && !event.ctrlKey && !event.altKey) { band(event); return; }
    if (event.shiftKey || event.metaKey || event.ctrlKey || event.altKey) return;
    if (!id || id === model()?.root || !(nodeOf(id) || groupOf(id)) || !parentOf(id)) return;
    drag = { id, from: { x: event.clientX, y: event.clientY }, started: false, frame: 0, at: null };
    window.addEventListener("pointermove", dragMove);
    window.addEventListener("pointerup", dragEnd);
    window.addEventListener("pointercancel", dragCancel);
    window.addEventListener("keydown", dragKey, true);
  }

  // -- a band dragged from where nothing is, choosing the shapes it touches --
  // As on Keynote's canvas: pressed where nothing is drawn and dragged, a band is drawn from
  // there to the pointer, and the shapes it touches are chosen as it goes (with ⇧, as well as
  // those chosen already). Let go, they stay chosen; Esc puts back what was chosen before.
  let banding = null;
  function band(event) {
    if (event.button !== 0 || banding || drag || !model() || state.connecting) return;
    banding = { start: { x: event.clientX, y: event.clientY }, pointer: null, moved: false, frame: 0,
      had: [...state.selected], base: event.shiftKey ? [...state.selected] : [], touched: null };
    window.addEventListener("pointermove", bandMove);
    window.addEventListener("pointerup", bandUp);
    window.addEventListener("pointercancel", bandCancel);
    window.addEventListener("keydown", bandKey, true);
  }
  function bandMove(event) {
    if (!banding) return;
    banding.pointer = { x: event.clientX, y: event.clientY };
    if (!banding.moved) {
      if (Math.hypot(event.clientX - banding.start.x, event.clientY - banding.start.y) < 4) return;
      banding.moved = true;
      window.getSelection?.()?.removeAllRanges();
      banding.node = h("div.fig-band");
      host.overlay.append(banding.node);
      document.body.classList.add("fig-banding");
    }
    event.preventDefault();
    if (!banding.frame) banding.frame = requestAnimationFrame(bandFrame);
  }
  function bandFrame() {
    if (!banding?.moved) return;
    banding.frame = 0;
    const outer = host.overlay.getBoundingClientRect();
    const { start, pointer } = banding;
    const left = Math.min(start.x, pointer.x) - outer.left, top = Math.min(start.y, pointer.y) - outer.top;
    const width = Math.abs(pointer.x - start.x), height = Math.abs(pointer.y - start.y);
    Object.assign(banding.node.style, { left: `${left}px`, top: `${top}px`, width: `${width}px`, height: `${height}px` });
    // Every shape whose drawing it reaches -- a shape's, not the group round it, which would
    // choose all it holds as one.
    const touched = (model().nodes || []).map((node) => node.id).filter((id) => {
      const box = host.box(id);
      return box && box.left < left + width && box.left + box.width > left && box.top < top + height && box.top + box.height > top;
    });
    const key = touched.join("\n");
    if (key === banding.touched) return;
    banding.touched = key;
    select([...new Set([...banding.base, ...touched])], { reveal: false });
  }
  function bandFinish() {
    window.removeEventListener("pointermove", bandMove);
    window.removeEventListener("pointerup", bandUp);
    window.removeEventListener("pointercancel", bandCancel);
    window.removeEventListener("keydown", bandKey, true);
    document.body.classList.remove("fig-banding");
    const was = banding;
    banding = null;
    if (was?.frame) cancelAnimationFrame(was.frame);
    was?.node?.remove();
    return was;
  }
  function bandUp(event) {
    if (banding?.moved && event) { banding.pointer = { x: event.clientX, y: event.clientY }; bandFrame(); }
    const was = bandFinish();
    // (A band let go is not a click on where it ends: the page, which would choose nothing.)
    if (was?.moved) swallowClick();
  }
  function bandCancel() {
    const was = bandFinish();
    if (was?.moved) select(was.had, { reveal: false });
  }
  function bandKey(event) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    // (Let go after Esc, the pointer chooses nothing where it is.)
    if (banding?.moved) window.addEventListener("pointerup", () => swallowClick(), { capture: true, once: true });
    bandCancel();
  }

  // The figure as it is seen: where every part and group is drawn (`boxes`), each row and
  // column the way it is drawn, turned to fit or not (`drawn`) -- and a row (or column) folded
  // onto lines to fit, a long flow chart on a slide, as its lines (`folds`): each line one of
  // its own, the lines one under another (beside one another). A part moved among them is
  // written so first, in the same step: only the part moves.
  function asSeen() {
    const boxes = new Map();
    for (const group of model().groups) boxOf(group.id, boxes);
    for (const node of model().nodes) boxOf(node.id, boxes);
    const drawn = { ...model(), groups: model().groups.map((group) => (shownKind(group) ? { ...group, layout: { ...(group.layout || {}), kind: shownKind(group) } } : group)) };
    const folds = [];
    for (const group of drawn.groups) {
      const way = group.layout?.kind;
      const lines = way === "row" || way === "column" ? seenLines(group.children || [], way, boxes) : [];
      if (lines.length < 2) continue;
      const spans = lines.map((line) => union(line.map((child) => boxes.get(child))));
      const [start, end] = way === "row" ? ["left", "right"] : ["top", "bottom"];
      const even = (side) => spans.every((span) => Math.abs(span[side] - spans[0][side]) < 4);
      folds.push({ id: group.id, kind: way, lines, align: even(end) && !even(start) ? "end" : even(start) ? "start" : "center" });
      const ids = lines.map((line, index) => `${group.id}~line${index + 1}`);
      ids.forEach((line, index) => boxes.set(line, spans[index]));
      drawn.groups = [...drawn.groups.map((each) => (each.id === group.id ? { ...each, children: ids, layout: { ...(each.layout || {}), kind: way === "row" ? "column" : "row" } } : each)),
        ...lines.map((line, index) => ({ id: ids[index], children: line, layout: { kind: way } }))];
    }
    return { boxes, drawn, folds };
  }

  function dragStart() {
    const id = drag.id;
    window.getSelection?.()?.removeAllRanges();
    // Where every part is now, and every group's room, from the drawing as it stands.
    const { boxes, drawn, folds } = asSeen();
    const moving = elementsOf(id).map((element) => ({ element, base: element.getAttribute("transform") || "", scale: unitsPerPixel(element) }));
    const nodes = new Set(model().nodes.filter((node) => inside(node.id, id)).map((node) => node.id));
    const touches = (ref) => nodes.has(nodeOfRef(ref));
    const lines = [...model().edges.filter((edge) => touches(edge.from) || touches(edge.to)),
      ...model().nets.filter((net) => [...(net.sources || []), ...(net.targets || [])].some(touches))]
      .map((line) => host.element(line.id)).filter((element) => element && !moving.some((item) => item.element.contains(element)));
    const indicator = h("div.fig-drop-line");
    const zone = h("div.fig-drop-zone");
    host.overlay.append(zone, indicator);
    host.overlay.classList.add("fig-dragging");
    document.body.classList.add("fig-grabbing");
    for (const { element } of moving) element.classList.add("fig-lifted");
    for (const element of lines) element.classList.add("fig-faded");
    // (A shape, not a group, may be let go on a line -- one not its own -- to go into it.)
    const paths = nodeOf(id) ? linePaths(nodes) : [];
    Object.assign(drag, { started: true, boxes, moving, lines, indicator, zone, parted: [], drawn, folds, paths });
    select([id], { reveal: false });
  }

  function dragMove(event) {
    if (!drag) return;
    drag.pointer = { x: event.clientX, y: event.clientY };
    if (!drag.started) {
      if (Math.hypot(event.clientX - drag.from.x, event.clientY - drag.from.y) < 4) return;
      dragStart();
    }
    event.preventDefault();
    if (!drag.frame) drag.frame = requestAnimationFrame(dragFrame);
  }

  function dragFrame() {
    if (!drag?.started) return;
    drag.frame = 0;
    const { x, y } = drag.pointer;
    const dx = x - drag.from.x, dy = y - drag.from.y;
    for (const { element, base, scale } of drag.moving) {
      element.setAttribute("transform", `translate(${dx * scale} ${dy * scale})${base ? ` ${base}` : ""}`);
    }
    const at = dropTarget(drag.pointer);
    if (!sameDrop(at, drag.at)) { drag.at = at; showDrop(at); }
    else if (at?.kind === "splice") { drag.at = at; placeTag(at); }
    // (Over a line, the part is seen through: the line lit under it.)
    for (const { element } of drag.moving) { element.classList.toggle("fig-astray", !at); element.classList.toggle("fig-over-line", at?.kind === "splice"); }
  }
  // Over a line's body (not one of its own), a shape goes into the line, between the two it
  // joins, in the group it is let go in; anywhere else, where dropPlace says (a shape dragged
  // from the palette, as one being moved would go there).
  function dropTarget(point) {
    // (By a line's end, closer than half of what is carried, it goes beside the part there.)
    const own = drag.id ? drag.boxes.get(drag.id) : null;
    const carried = own ? { width: own.right - own.left, height: own.bottom - own.top } : drag.size || null;
    const line = lineAt(drag.paths || [], point, null, undefined, carried);
    if (line) return { kind: "splice", line: line.id, from: line.from, to: line.to, at: line.at, parent: groupAt(model(), drag.boxes, point, drag.id) };
    return drag.id ? dropAt(point) : dropPlace(drag.drawn || model(), drag.boxes, point, null);
  }
  // The lines a shape may be let go on (lineAt), as points along each in the window's pixels:
  // all but those of the parts being moved (`own`).
  function linePaths(own = new Set()) {
    const found = [];
    for (const edge of model()?.edges || []) {
      const from = nodeOfRef(edge.from), to = nodeOfRef(edge.to);
      if (own.has(from) || own.has(to)) continue;
      const path = [...(host.element(edge.id)?.querySelectorAll("path:not(.hit-line)") || [])].filter((each) => each.getTotalLength?.())
        .sort((a, b) => b.getTotalLength() - a.getTotalLength())[0];
      const matrix = path?.getScreenCTM?.();
      if (!matrix) continue;
      const length = path.getTotalLength(), steps = Math.min(200, Math.max(2, Math.ceil((length * Math.hypot(matrix.a, matrix.b)) / 4)));
      const points = Array.from({ length: steps + 1 }, (_, index) => {
        const at = path.getPointAtLength((length * index) / steps), seen = new DOMPoint(at.x, at.y).matrixTransform(matrix);
        return { x: seen.x, y: seen.y };
      });
      found.push({ id: edge.id, from, to, points });
    }
    return found;
  }
  // The line a shape would go into, lit as a chosen line is, and named -- "Between “A” and
  // “B”" -- beside what is carried, level with the line; none (null), unlit.
  function showLine(at) {
    for (const twin of document.querySelectorAll(".hit-line.target")) twin.classList.remove("target");
    drag.tag?.remove();
    drag.tag = null;
    if (!at) return;
    for (const twin of host.element(at.line)?.querySelectorAll(".hit-line") || []) twin.classList.add("target");
    drag.tag = h("div.fig-splice-tag", {}, `Between ${inQuotes(nameOf(at.from))} and ${inQuotes(nameOf(at.to))}`);
    host.overlay.append(drag.tag);
    placeTag(at);
  }
  function placeTag(at) {
    const tag = drag?.tag;
    if (!tag) return;
    const outer = host.overlay.getBoundingClientRect(), wide = tag.offsetWidth;
    const carried = [...drag.moving.map((item) => item.element), drag.ghost].filter(Boolean).map((element) => element.getBoundingClientRect());
    const right = Math.max(at.at.x + 12, ...carried.map((rect) => rect.right + 10));
    const left = right + wide < outer.right - 4 ? right : Math.min(at.at.x - 12, ...carried.map((rect) => rect.left - 10)) - wide;
    Object.assign(tag.style, { left: `${left - outer.left}px`, top: `${at.at.y - outer.top}px` });
  }

  // (Judged by where the pointer is, and where the part's middle now is: lined up under
  // another part by its middle, however it was picked up.)
  const dropAt = (point) => {
    const own = drag.boxes.get(drag.id);
    const centre = own ? { x: (own.left + own.right) / 2 + point.x - drag.from.x, y: (own.top + own.bottom) / 2 + point.y - drag.from.y } : point;
    return dropPlace(drag.drawn || model(), drag.boxes, point, drag.id, centre);
  };
  const sameDrop = (a, b) => (a && b ? a.parent === b.parent && a.index === b.index && a.side === b.side && a.of === b.of && a.with === b.with && a.line === b.line : a === b);
  const unchanged = (at, id, drawn = drag?.drawn) => stays(drawn || model(), at, id);
  // The lines `children` are seen on, laid out `way`: those level with one another (beside
  // one another, for a column) together, each line in the order seen.
  function seenLines(children, way, boxes) {
    const [low, high, along] = way === "row" ? ["top", "bottom", "left"] : ["left", "right", "top"];
    const placed = children.map((child) => ({ child, box: boxes.get(child) })).filter((item) => item.box).sort((a, b) => a.box[low] - b.box[low]);
    const lines = [];
    for (const item of placed) {
      const line = lines.find((each) => Math.min(each.high, item.box[high]) - Math.max(each.low, item.box[low]) > 0.3 * Math.min(each.high - each.low, item.box[high] - item.box[low]));
      if (line) { line.items.push(item); line.low = Math.min(line.low, item.box[low]); line.high = Math.max(line.high, item.box[high]); }
      else lines.push({ items: [item], low: item.box[low], high: item.box[high] });
    }
    return placed.length === children.length ? lines.map((line) => line.items.sort((a, b) => a.box[along] - b.box[along]).map((item) => item.child)) : [];
  }
  const union = (boxes) => ({ left: Math.min(...boxes.map((box) => box.left)), top: Math.min(...boxes.map((box) => box.top)),
    right: Math.max(...boxes.map((box) => box.right)), bottom: Math.max(...boxes.map((box) => box.bottom)) });

  function showDrop(at) {
    for (const { element } of drag.parted) element.style.transform = "";
    drag.parted = [];
    // Over a line: the line lit and named, and no slot -- it goes into the line.
    showLine(at?.kind === "splice" ? at : null);
    if (!at || at.kind === "splice") { drag.zone.classList.remove("on"); drag.indicator.classList.remove("on"); return; }
    const origin = host.overlay.getBoundingClientRect();
    drag.indicator.classList.remove("centre");
    drag.zone.classList.remove("named-beside", "named-left");
    const room = drag.boxes.get(at.parent) || SVG(host.element(model().root))?.getBoundingClientRect();
    const place = (node, box, extra = {}) => Object.assign(node.style, {
      transform: `translate(${box.left - origin.left}px, ${box.top - origin.top}px)`,
      width: `${Math.max(box.right - box.left, 0)}px`, height: `${Math.max(box.bottom - box.top, 0)}px`, ...extra });
    if (at.kind === "align") {
      // Along its own line: a slot where it lands, centred under the part (or the row) it
      // goes with, named -- and a line down the middle from that to it. Where it is already,
      // nothing.
      const own = drag.boxes.get(drag.id), over = drag.boxes.get(at.with);
      if (at.here || !own || !over) { drag.zone.classList.remove("on"); drag.indicator.classList.remove("on"); return; }
      const width = own.right - own.left, height = own.bottom - own.top;
      // (Kept within the line it goes with, as the figure keeps it: never wider for it.)
      const line = drag.boxes.get(at.of);
      const left = line && line.right - line.left >= width ? Math.max(line.left, Math.min(at.x - width / 2, line.right - width)) : at.x - width / 2;
      const slot = { left, top: own.top, right: left + width, bottom: own.bottom };
      const label = at.centred
        ? `Centred ${at.side} the ${groupOf(at.with) && !plain(groupOf(at.with).label) ? "row" : inQuotes(nameOf(at.with))}`
        : `${at.side === "below" ? "Under" : "Over"} ${inQuotes(nameOf(at.with))}`;
      // (Its name beside it, clear of the line down the middle; on its left at the page's
      // right edge.)
      drag.zone.style.setProperty("--label-shift", "0px");
      drag.zone.classList.remove("named-over");
      drag.zone.classList.add("named-beside");
      drag.zone.classList.toggle("named-left", slot.right + label.length * 6.2 + 30 > origin.right);
      place(drag.zone, slot);
      drag.zone.dataset.label = label;
      drag.zone.classList.add("on", "own-line");
      const [from, to] = at.side === "below" ? [over.bottom + 3, slot.top - 3] : [slot.bottom + 3, over.top - 3];
      if (to - from > 4 && height > 0) {
        place(drag.indicator, { left: at.x - 1, right: at.x + 1, top: from, bottom: to });
        drag.indicator.classList.add("on", "centre");
      } else drag.indicator.classList.remove("on");
      return;
    }
    if (at.kind === "line") {
      // A line of its own: a slot where it lands, centred past the rest of the figure -- or
      // past the part it goes beside.
      const all = drag.boxes.get(at.of) || drag.boxes.get(model().root) || room;
      // (A shape from the palette: at the size it will be drawn.)
      const own = drag.boxes.get(drag.id) || (drag.size && { left: 0, top: 0, right: drag.size.width, bottom: drag.size.height });
      const width = own ? own.right - own.left : 60, height = own ? own.bottom - own.top : 30;
      const mid = centre(all), gap = 18;
      const slot = at.side === "below" ? { left: mid.x - width / 2, top: all.bottom + gap }
        : at.side === "above" ? { left: mid.x - width / 2, top: all.top - gap - height }
          : at.side === "right" ? { left: all.right + gap, top: mid.y - height / 2 }
            : { left: all.left - gap - width, top: mid.y - height / 2 };
      const label = at.of !== model().root ? `${{ below: "Under", above: "Over", right: "Right of", left: "Left of" }[at.side]} ${inQuotes(nameOf(at.of))}`
        : at.side === "below" || at.side === "above" ? `New row ${at.side}` : `New column on the ${at.side}`;
      // Kept on the page, its name with it: a slot that would go past the page's edge is
      // drawn at the edge, and its name under it (over it, at the page's foot) slides in.
      const edge = 4, named = Math.min(label.length * 6.2 + 14, origin.width - 2 * edge);
      slot.left = Math.max(origin.left + edge, Math.min(slot.left, origin.right - edge - width));
      slot.top = Math.max(origin.top + edge, Math.min(slot.top, origin.bottom - edge - height));
      const middle = slot.left + width / 2;
      const shift = Math.max(origin.left + edge + named / 2 - middle, Math.min(0, origin.right - edge - named / 2 - middle));
      drag.zone.style.setProperty("--label-shift", `${shift}px`);
      drag.zone.classList.toggle("named-over", slot.top + height + 26 > origin.bottom);
      place(drag.zone, { ...slot, right: slot.left + width, bottom: slot.top + height });
      drag.zone.dataset.label = label;
      drag.zone.classList.add("on", "own-line");
      drag.indicator.classList.remove("on");
      return;
    }
    drag.zone.classList.remove("own-line");
    const home = unchanged(at, drag.id);
    drag.zone.classList.toggle("on", Boolean(room) && at.parent !== model().root && !home);
    if (room) place(drag.zone, { left: room.left - 6, top: room.top - 6, right: room.right + 6, bottom: room.bottom + 6 });
    if (at.empty || home) { drag.indicator.classList.remove("on"); return; }
    // The line between the part it goes next to and the one beyond, if there is one: on
    // its right (or under it) when it goes after it -- on its left, along a line of a row
    // run back to fit.
    const box = drag.boxes.get(at.near);
    const ahead = at.after !== Boolean(at.back);
    const beyond = at.siblings.map((child) => ({ child, box: drag.boxes.get(child) })).filter(({ child, box: other }) => child !== at.near && (at.across
      ? (ahead ? other.left >= box.right - 1 : other.right <= box.left + 1) && other.bottom > box.top && other.top < box.bottom
      : (ahead ? other.top >= box.bottom - 1 : other.bottom <= box.top + 1) && other.right > box.left && other.left < box.right))
      .sort((a, b) => (at.across ? Math.abs(centre(a.box).x - centre(box).x) - Math.abs(centre(b.box).x - centre(box).x)
        : Math.abs(centre(a.box).y - centre(box).y) - Math.abs(centre(b.box).y - centre(box).y)))[0];
    let line;
    if (at.across) {
      const edge = ahead ? box.right : box.left;
      const other = beyond ? (ahead ? beyond.box.left : beyond.box.right) : edge + (ahead ? 12 : -12);
      const x = (edge + other) / 2;
      const top = Math.min(box.top, beyond?.box.top ?? box.top), bottom = Math.max(box.bottom, beyond?.box.bottom ?? box.bottom);
      line = { left: x - 1.5, right: x + 1.5, top: top - 4, bottom: bottom + 4 };
    } else {
      const edge = ahead ? box.bottom : box.top;
      const other = beyond ? (ahead ? beyond.box.top : beyond.box.bottom) : edge + (ahead ? 12 : -12);
      const y = (edge + other) / 2;
      const left = Math.min(box.left, beyond?.box.left ?? box.left), right = Math.max(box.right, beyond?.box.right ?? box.right);
      line = { left: left - 4, right: right + 4, top: y - 1.5, bottom: y + 1.5 };
    }
    place(drag.indicator, line);
    drag.indicator.classList.add("on");
    // The parts either side of it step apart, a little, to make room.
    const apart = 7;
    const nudge = (id, sign) => {
      for (const element of elementsOf(id)) {
        if (drag.moving.some((item) => item.element === element)) continue;
        const shift = sign * apart * unitsPerPixel(element);
        element.style.transform = at.across ? `translate(${shift}px, 0px)` : `translate(0px, ${shift}px)`;
        drag.parted.push({ element });
      }
    };
    nudge(at.near, ahead ? -1 : 1);
    if (beyond) nudge(beyond.child, ahead ? 1 : -1);
  }

  function dragFinish() {
    window.removeEventListener("pointermove", dragMove);
    window.removeEventListener("pointerup", dragEnd);
    window.removeEventListener("pointermove", tileMove);
    window.removeEventListener("pointerup", tileEnd);
    window.removeEventListener("pointercancel", dragCancel);
    window.removeEventListener("keydown", dragKey, true);
    if (drag?.frame) cancelAnimationFrame(drag.frame);
    const was = drag;
    if (was?.started) showLine(null);
    drag = null;
    if (!was?.started) return null;
    was.indicator.remove();
    was.zone.remove();
    was.ghost?.remove();
    document.body.classList.remove("fig-grabbing");
    for (const { element } of was.parted) element.style.transform = "";
    // A drag ends in a click on whatever is under the pointer: that click is not one.
    swallowClick();
    return was;
  }
  // Home again: the part slides back to where it was drawn, the lines come back.
  function sendHome(was) {
    clearTimeout(was.wait);
    host.overlay.classList.remove("fig-dragging");
    for (const { element, base } of was.moving) {
      const moved = /translate\(([-\d.e]+) ([-\d.e]+)\)/.exec(element.getAttribute("transform") || "");
      if (base) element.setAttribute("transform", base);
      else element.removeAttribute("transform");
      element.classList.remove("fig-lifted", "fig-settling", "fig-astray", "fig-over-line");
      if (moved) element.animate([{ transform: `translate(${moved[1]}px, ${moved[2]}px)` }, { transform: "translate(0px, 0px)" }],
        { duration: 220, easing: "cubic-bezier(.2,.8,.2,1)" });
    }
    for (const element of was.lines) element.classList.remove("fig-faded");
    // Its frame and its + go back with it: at once, and again where it comes to rest.
    host.settled?.();
    setTimeout(() => host.settled?.(), 240);
  }
  function dragEnd(event) {
    if (drag?.started && event) drag.pointer = { x: event.clientX, y: event.clientY };
    if (drag?.started) dragFrame();
    const was = dragFinish();
    if (!was) return;
    const at = was.at;
    if (!at || unchanged(at, was.id, was.drawn)) { sendHome(was); return; }
    // It stays where it was let go until the drawing it makes comes back and lands.
    for (const { element } of was.moving) { element.classList.add("fig-settling"); element.classList.remove("fig-over-line"); }
    // Should no drawing come back (nothing changed after all), it goes home on its own.
    was.wait = setTimeout(() => { if (was.moving[0]?.element.isConnected) sendHome(was); }, 6000);
    // Let go on a line: put into it, between the two it joins -- a figure seen folded to fit
    // written as seen first, in the same step, so that the rest keep their lines.
    if (at.kind === "splice") {
      const merge = `as-drawn:${was.id}:${Date.now()}`, failed = () => sendHome(was);
      const label = `Insert ${inQuotes(nameOf(was.id))} Between ${inQuotes(nameOf(at.from))} and ${inQuotes(nameOf(at.to))}`;
      const into = () => act({ do: "move", id: was.id, into: at.line, parent: at.parent }, { merge, label, failed });
      if (was.folds?.length) arrangeSeen(was.folds, { merge, label, failed }, into);
      else into();
      return;
    }
    moveAsSeen(was.id, at, { folds: was.folds, drawn: was.drawn, failed: () => sendHome(was) });
  }
  // A part moved to `at` (a place in the figure as it is seen: asSeen), by a drag or a key:
  // a figure folded onto lines to fit is written as seen first, one step with the move,
  // which then goes into the lines as written.
  function moveAsSeen(id, at, { folds = [], drawn = null, failed = null } = {}) {
    // Lined up under a part of the line it goes with (or the line itself): only it moves.
    if (at.kind === "align") {
      const label = at.centred ? `Centre ${inQuotes(nameOf(id))}` : `Place ${inQuotes(nameOf(id))} ${at.side === "below" ? "Under" : "Over"} ${inQuotes(nameOf(at.with))}`;
      act({ do: "align", id, with: at.with }, { failed, label });
      return;
    }
    if (!folds.length) {
      if (at.kind === "line") ownLine(id, at.of, at.side, { failed, drawn });
      else act({ do: "move", id, parent: at.parent, index: at.index }, { failed });
      return;
    }
    const merge = `as-drawn:${id}:${Date.now()}`, label = said({ do: "move", id });
    arrangeSeen(folds, { merge, label, failed }, (written) => {
      if (at.kind === "line") ownLine(id, written(at.of), at.side, { failed, merge, label });
      else act({ do: "move", id, parent: written(at.parent), index: at.index }, { merge, label, failed });
    });
  }
  // The rows (columns) of a figure folded onto lines to fit, written as they are seen (`folds`,
  // asSeen's), one step (`merge`) with what is done after them: `done(written)`, `written`
  // naming each line seen ("row~line2") by the group it is written as now.
  function arrangeSeen(folds, { merge, label, failed = null }, done) {
    const real = new Map();
    const written = (each) => real.get(each) || each;
    const next = (index) => {
      if (index >= folds.length) { done(written); return; }
      const fold = folds[index];
      act({ do: "arrange", id: fold.id, kind: fold.kind, lines: fold.lines, align: fold.align }, { merge, label, select: false, failed,
        then: (result) => { (result.select || []).forEach((made, line) => real.set(`${fold.id}~line${line + 1}`, made)); next(index + 1); } });
    };
    next(0);
  }

  // -- a shape dragged from the palette onto the figure --
  // As from Keynote's shapes: the palette goes, and the shape follows the pointer -- over a
  // line, the line lit and named, it goes into the line; elsewhere, where a part dragged there
  // would go (its slot shown). Let go, it is added there, ready for its words. Let go off the
  // figure, or Esc, nothing is added; pressed and let go where it was, the tile is clicked.
  function tilePress(event, kind) {
    if (event.button !== 0 || drag || !model()) return;
    drag = { id: null, kind, from: { x: event.clientX, y: event.clientY }, started: false, frame: 0, at: null, moving: [], lines: [], parted: [] };
    window.addEventListener("pointermove", tileMove);
    window.addEventListener("pointerup", tileEnd);
    window.addEventListener("pointercancel", dragCancel);
    window.addEventListener("keydown", dragKey, true);
  }
  function tileMove(event) {
    if (!drag || drag.id !== null) return;
    drag.pointer = { x: event.clientX, y: event.clientY };
    if (!drag.started) {
      if (Math.hypot(event.clientX - drag.from.x, event.clientY - drag.from.y) < 5) return;
      tileStart();
    }
    event.preventDefault();
    Object.assign(drag.ghost.style, { left: `${drag.pointer.x}px`, top: `${drag.pointer.y}px` });
    if (!drag.frame) drag.frame = requestAnimationFrame(tileFrame);
  }
  function tileStart() {
    // (The palette goes: the figure is in sight, to be let go on.)
    closeMenu();
    window.getSelection?.()?.removeAllRanges();
    const { boxes, drawn, folds } = asSeen();
    const look = figureLook(), ems = parts[drag.kind]?.size || [5.5, 3.5];
    const ghost = h("div.fig-tile-ghost", {}, glyph(drag.kind), h("span", {}, parts[drag.kind].title));
    document.body.append(ghost);
    const indicator = h("div.fig-drop-line"), zone = h("div.fig-drop-zone");
    host.overlay.append(zone, indicator);
    host.overlay.classList.add("fig-dragging");
    document.body.classList.add("fig-grabbing");
    Object.assign(drag, { started: true, boxes, drawn, folds, ghost, indicator, zone, paths: linePaths(),
      size: { width: ems[0] * look.size, height: ems[1] * look.size } });
  }
  function tileFrame() {
    if (!drag?.started) return;
    drag.frame = 0;
    const at = dropTarget(drag.pointer);
    if (!sameDrop(at, drag.at)) { drag.at = at; showDrop(at); }
    else if (at?.kind === "splice") { drag.at = at; placeTag(at); }
    drag.ghost.classList.toggle("astray", !at);
  }
  function tileEnd(event) {
    if (drag?.started && event) { drag.pointer = { x: event.clientX, y: event.clientY }; tileFrame(); }
    const was = dragFinish();
    if (!was) return;
    host.overlay.classList.remove("fig-dragging");
    const at = was.at;
    if (!at || at.kind === "align") return;
    const outer = host.overlay.getBoundingClientRect();
    const point = (spot) => ({ x: spot.x - outer.left, y: spot.y - outer.top });
    // (Named for Undo by where it went, as the slot was named: "Add Block Right of “D”".)
    const near = (id) => (typeOf(id) ? inQuotes(nameOf(id)) : null);
    const added = `Add ${kindTitle(was.kind)}`;
    if (at.kind === "splice") addPart(was.kind, lineWhere(at.line, { parent: at.parent, at: point(at.at), kind: was.kind }));
    else if (at.kind === "line") {
      const side = { below: "Under", above: "Over", right: "Right of", left: "Left of" }[at.side];
      addPart(was.kind, { side: at.side, of: at.of, folds: was.folds, at: point(was.pointer), label: at.of !== model().root && near(at.of) ? `${added} ${side} ${near(at.of)}` : added });
    } else {
      const label = at.near && near(at.near) ? `${added} ${at.after ? "After" : "Before"} ${near(at.near)}` : groupOf(at.parent) && at.parent !== model().root ? `${added} Inside ${near(at.parent)}` : added;
      addPart(was.kind, { parent: at.parent, index: at.index, folds: was.folds, at: point(was.pointer), label });
    }
  }
  // ⌥ and an arrow: the part one place that way on screen, among the parts on its line --
  // or onto the line beside it, of a row folded onto lines -- as a drag there would put it.
  // Answers whether it moved (at the end of its line, it does not, and nothing is recorded).
  function nudge(id, key) {
    const place = nudgePlace(id, key);
    if (place) { moveAsSeen(id, place.at, place); return true; }
    // At the end of its line already (the start, the way it was pressed): said, not nothing
    // at all -- or, across its line, that it goes no further that way.
    const way = drawnKind(parentOf(id)) === "column" ? "column" : "row";
    const along = way === "row" ? ["ArrowLeft", "ArrowRight"] : ["ArrowUp", "ArrowDown"];
    const said = along.includes(key) ? `is at the ${key === along[0] ? "start" : "end"} of its ${way} already`
      : `can’t move further ${{ ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" }[key]}`;
    toast(`${inQuotes(nameOf(id))} ${said}.`, { icon: "info", seconds: 2 });
    return false;
  }
  function nudgePlace(id, key) {
    const { boxes, drawn, folds } = asSeen();
    const holder = drawn.groups.find((group) => (group.children || []).includes(id));
    if (!holder || !boxes.get(id)) return null;
    const way = holder.layout?.kind;
    if (way !== "row" && way !== "column") return null;
    const along = way === "row" ? ["ArrowLeft", "ArrowRight"] : ["ArrowUp", "ArrowDown"];
    const middle = (each) => centre(boxes.get(each));
    const axis = (point) => (way === "row" ? point.x : point.y);
    if (along.includes(key)) {
      const sign = key === along[0] ? -1 : 1;
      const seen = [...holder.children].filter((each) => boxes.get(each)).sort((a, b) => axis(middle(a)) - axis(middle(b)));
      const past = seen[seen.indexOf(id) + sign];
      if (!past) return null;
      // Past it, in the order its group writes them (a line run back is written the other way).
      const others = holder.children.filter((each) => each !== id);
      const after = holder.children.indexOf(past) > holder.children.indexOf(id);
      return { at: { parent: holder.id, index: others.indexOf(past) + (after ? 1 : 0) }, folds, drawn };
    }
    // Across its line: onto the next line that way, of a folded row (column), beside the part
    // nearest where it is -- or, a line of one row or column, onto a line of its own that
    // way, beside the rest (as dragging it there would).
    const outer = drawn.groups.find((group) => (group.children || []).includes(holder.id));
    if (!outer || !String(holder.id).includes("~line")) {
      if ((holder.children || []).filter((each) => each !== id).length === 0) return null;
      const side = way === "row" ? (key === "ArrowUp" ? "above" : "below") : key === "ArrowLeft" ? "left" : "right";
      return { at: { kind: "line", side, of: holder.id }, folds, drawn };
    }
    const sign = (way === "row" ? key === "ArrowUp" : key === "ArrowLeft") ? -1 : 1;
    const across = (box) => (way === "row" ? (box.top + box.bottom) / 2 : (box.left + box.right) / 2);
    const lines = [...outer.children].sort((a, b) => across(boxes.get(a)) - across(boxes.get(b)));
    const target = drawn.groups.find((group) => group.id === lines[lines.indexOf(holder.id) + sign]);
    if (!target) return null;
    // (A folded line is written as it is seen: its order is the order on screen.)
    const here = axis(middle(id));
    return { at: { parent: target.id, index: (target.children || []).filter((each) => axis(middle(each)) < here).length }, folds, drawn };
  }
  function dragCancel() { const was = dragFinish(); if (was) sendHome(was); }
  let landed = 0;
  // When a part was asked for, until it lands where it is drawn (0: none on its way).
  let adding = 0;
  function dragKey(event) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    // (Let go after Esc, the pointer chooses nothing where it is.)
    if (drag?.started) window.addEventListener("pointerup", () => swallowClick(), { capture: true, once: true });
    dragCancel();
  }

  // -- landing: the drawing after an edit, each part sliding from where it was --
  // What is drawn anew for where the parts go: the lines, and the frames of groups (a
  // frame's own drawing, not the parts it holds).
  const LINES = '[data-flexo-entity="connector"], [data-flexo-entity="net"]';
  function drawnAnew(root) {
    const found = [...(root?.querySelectorAll(LINES) || [])];
    for (const group of root?.querySelectorAll('[data-flexo-entity="group"]') || []) {
      for (const piece of group.children) {
        if (piece.matches('[data-flexo-entity], [id$=".components"], [id$=".connectors"]') || piece.querySelector("[data-flexo-entity]")) continue;
        found.push(piece);
      }
    }
    return found;
  }
  // An element as drawn, where it is on the page: the same twice is drawn just as it was.
  const drawnAs = (element, matrix) => `${element.outerHTML}@${matrix ? [matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f].map((value) => value.toFixed(2)).join(",") : ""}`;
  // A line drawn before and after an edit is the same line: by its id, or -- its end moved
  // to another part, as when a step is put into it -- by its place among the lines and the
  // part it leaves.
  const edgeKey = (id) => /(?:^|\.)edge\.(\d+)\.(.+?)-to-/.exec(id);
  function sameLine(id, old) {
    if (old.has(id)) return id;
    const key = edgeKey(id);
    return key ? [...old.keys()].find((other) => { const theirs = edgeKey(other); return theirs && theirs[1] === key[1] && theirs[2] === key[2]; }) : null;
  }
  // A path's points, its curved corners followed closely enough to move it by: null for a
  // path drawn some other way.
  function pathPoints(d) {
    const tokens = String(d || "").match(/[A-Za-z]|-?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?/g) || [];
    const points = [];
    let x = 0, y = 0, command = null, at = 0;
    const take = () => Number(tokens[at++]);
    while (at < tokens.length) {
      if (/[A-Za-z]/.test(tokens[at])) command = tokens[at++];
      if (command === "M" || command === "L") { x = take(); y = take(); points.push({ x, y }); }
      else if (command === "H") { x = take(); points.push({ x, y }); }
      else if (command === "V") { y = take(); points.push({ x, y }); }
      else if (command === "Q") {
        const [cx, cy, ex, ey] = [take(), take(), take(), take()];
        for (const t of [0.25, 0.5, 0.75, 1]) points.push({ x: (1 - t) ** 2 * x + 2 * (1 - t) * t * cx + t * t * ex, y: (1 - t) ** 2 * y + 2 * (1 - t) * t * cy + t * t * ey });
        [x, y] = [ex, ey];
      } else if (command === "C") {
        const [ax, ay, bx, by, ex, ey] = [take(), take(), take(), take(), take(), take()];
        for (const t of [0.25, 0.5, 0.75, 1]) {
          const u = 1 - t;
          points.push({ x: u ** 3 * x + 3 * u * u * t * ax + 3 * u * t * t * bx + t ** 3 * ex, y: u ** 3 * y + 3 * u * u * t * ay + 3 * u * t * t * by + t ** 3 * ey });
        }
        [x, y] = [ex, ey];
      } else return null;
      if (points.some((point) => !Number.isFinite(point.x) || !Number.isFinite(point.y))) return null;
    }
    return points.length > 1 ? points : null;
  }
  // `count` points spaced evenly along a polyline.
  function evenly(points, count) {
    const lengths = [0];
    for (let at = 1; at < points.length; at += 1) lengths.push(lengths[at - 1] + Math.hypot(points[at].x - points[at - 1].x, points[at].y - points[at - 1].y));
    const total = lengths[lengths.length - 1] || 1;
    const out = [];
    let segment = 1;
    for (let index = 0; index < count; index += 1) {
      const want = (total * index) / (count - 1);
      while (segment < points.length - 1 && lengths[segment] < want) segment += 1;
      const from = points[segment - 1], to = points[segment], span = lengths[segment] - lengths[segment - 1] || 1;
      const t = Math.min(1, Math.max(0, (want - lengths[segment - 1]) / span));
      out.push({ x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t });
    }
    return out;
  }
  // A line moved from where it was drawn to where it is now, its arrowhead with it, as the
  // parts it joins slide: one line all the way, never two, never none.
  const LAND = 300;
  // The parts' easing, cubic-bezier(.2, .8, .2, 1), for a line moved a frame at a time: its
  // ends keep pace with the parts they join.
  function eased(t) {
    const curve = (a, b, u) => 3 * a * u * (1 - u) ** 2 + 3 * b * u * u * (1 - u) + u ** 3;
    let low = 0, high = 1, u = t;
    for (let step = 0; step < 18; step += 1) { u = (low + high) / 2; if (curve(0.2, 0.2, u) < t) low = u; else high = u; }
    return curve(0.8, 1, u);
  }
  function morph(path, from, final) {
    const to = pathPoints(final);
    if (!from || !to) return false;
    const [a, b] = [evenly(from, 40), evenly(to, 40)];
    // Its arrowheads point as they will at the end all the way: the line bends, they only
    // move with its ends, never turning or twisting on the way.
    const last = a.length - 1;
    const along = (at, before) => { const dx = b[at].x - b[before].x, dy = b[at].y - b[before].y, length = Math.hypot(dx, dy) || 1; return { x: dx / length, y: dy / length }; };
    const [head, tail] = [along(last, last - 1), along(0, 1)];
    const drawAt = (e) => {
      const points = a.map((p, index) => ({ x: p.x + (b[index].x - p.x) * e, y: p.y + (b[index].y - p.y) * e }));
      const reach = (at, before) => Math.max(1, Math.hypot(points[at].x - points[before].x, points[at].y - points[before].y));
      const [end, start] = [reach(last, last - 1), reach(0, 1)];
      points[last - 1] = { x: points[last].x - head.x * end, y: points[last].y - head.y * end };
      points[1] = { x: points[0].x - tail.x * start, y: points[0].y - tail.y * start };
      path.setAttribute("d", `M ${points.map((p) => `${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(" L ")}`);
    };
    drawAt(0);
    const start = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - start) / LAND);
      if (t >= 1 || !path.isConnected) { path.setAttribute("d", final); return; }
      drawAt(eased(t));
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
    // However the frames go, it ends drawn as it is.
    setTimeout(() => { if (path.getAttribute("d") !== final) path.setAttribute("d", final); }, LAND + 200);
    return true;
  }
  // The figure is about to be drawn in the layout that suits it best, its edits done (a
  // deck draws it kept in the layout it had while it is changed): it lands there too.
  function settles() {
    state.landing = Date.now();
    state.settling = true;
  }
  function landing() {
    if (drag?.started) { dragFinish(); host.overlay.classList.remove("fig-dragging"); }  // its drawing is going
    if (!state.landing || Date.now() - state.landing > 6000 || !model()) return null;
    const before = new Map();
    for (const node of model().nodes) {
      const box = host.element(node.id)?.getBoundingClientRect();
      if (box && (box.width || box.height)) before.set(node.id, box);
    }
    before.settling = state.settling;
    state.settling = false;
    // A part being named where it stands, not drawn yet: it comes from its stand-in.
    if (standing && inline?.guess) before.standing = { id: inline.id, box: standing.getBoundingClientRect() };
    // The lines and frames as they are: each line to move to where it goes, and a copy of
    // each, to go out should it be drawn no more.
    const pieces = drawnAnew(host.element(model().root));
    before.drawn = pieces.map((element) => {
      const matrix = element.parentNode?.getScreenCTM?.();
      return { copy: element.cloneNode(true), matrix, as: drawnAs(element, matrix), id: element.matches(LINES) ? element.id : null };
    });
    before.lines = new Map(pieces.filter((element) => element.matches(LINES)).map((element) => [element.id, {
      own: element.getScreenCTM?.(),
      paths: new Map([...element.querySelectorAll("path[id]")].map((path) => [path.id.slice(element.id.length), path.getAttribute("d")])),
      label: element.querySelector('[id$=".label"]')?.getBoundingClientRect(),
    }]));
    return before;
  }
  function land(before) {
    host.overlay.classList.remove("fig-dragging");
    // (A part with no words, drawn now: its stand-in goes.)
    if (!inline && standing) stand(null);
    if (!before) return;
    state.landing = 0;
    // What is typed on a part goes with it to where it is drawn now, as one: from its
    // stand-in, or from where it was.
    if (inline) {
      const box = inline.box;
      box.classList.add("gliding");
      placeInline();
      setTimeout(() => box.classList.remove("gliding"), LAND + 40);
    }
    const ease = "cubic-bezier(.2,.8,.2,1)";
    // The marks of what is chosen wait for the parts to arrive, then fade in on them --
    // when a part moves: a figure drawn again as it was (settled in the layout it had) is
    // left be.
    let moved = !before.settling, added = false;
    for (const node of model()?.nodes || []) {
      const element = host.element(node.id);
      if (!element) continue;
      const now = element.getBoundingClientRect();
      const was = before.get(node.id) || before.get(state.renamed.get(node.id));
      moved ||= !was || Math.hypot(centre(was).x - centre(now).x, centre(was).y - centre(now).y) >= 0.5;
      added ||= !was;
      if (!was) {
        // The part being named, its stand-in where it stood: it goes from there to where it
        // is drawn, its words' box with it, as one.
        const stood = before.standing && [before.standing.id, state.renamed.get(node.id)].includes(node.id) ? before.standing.box : null;
        if (stood?.width) {
          const scale = unitsPerPixel(element);
          const dx = centre(stood).x - centre(now).x, dy = centre(stood).y - centre(now).y;
          Object.assign(element.style, { transformBox: "fill-box", transformOrigin: "center" });
          element.animate([{ transform: `translate(${dx * scale}px, ${dy * scale}px) scale(${stood.width / (now.width || 1)}, ${stood.height / (now.height || 1)})` },
            { transform: "translate(0px, 0px) scale(1, 1)" }], { duration: LAND, easing: ease });
          continue;
        }
        // A part just made grows in where it is drawn, once the parts beside it have
        // stepped aside for it -- but for the one being named, whose shape stood there
        // already: it is simply there.
        if (inline?.id === node.id || typedOver?.ids.includes(node.id)) continue;
        element.style.transformBox = "fill-box";
        element.style.transformOrigin = "center";
        element.animate([{ opacity: 0, transform: "scale(0.94)" }, { opacity: 0, transform: "scale(0.94)", offset: 0.35 }, { opacity: 1, transform: "scale(1)" }],
          { duration: LAND, easing: ease });
        continue;
      }
      const dx = centre(was).x - centre(now).x, dy = centre(was).y - centre(now).y;
      // One sized in proportion (a molecule's corner dragged) grows or shrinks the rest of the way.
      const grown = was.width / (now.width || 1);
      const sized = Math.abs(grown - 1) > 0.02 && Math.abs(was.height / (now.height || 1) - grown) < 0.05 * grown;
      if (Math.hypot(dx, dy) < 0.5 && !sized) continue;
      const scale = unitsPerPixel(element);
      if (sized) Object.assign(element.style, { transformBox: "fill-box", transformOrigin: "center" });
      element.animate([{ transform: `translate(${dx * scale}px, ${dy * scale}px)${sized ? ` scale(${grown})` : ""}` }, { transform: `translate(0px, 0px)${sized ? " scale(1)" : ""}` }],
        { duration: LAND, easing: ease });
    }
    state.renamed.clear();
    if (moved) {
      host.overlay.classList.add("fig-landing");
      clearTimeout(landed);
      // Landed: what is typed on a part follows it to where it is at rest -- and a part
      // asked for is there, the figure's frame round it all at once.
      landed = setTimeout(() => { adding = 0; host.overlay.classList.remove("fig-landing"); host.settled?.(); placeInline(); }, LAND + 20);
    } else if (adding) {
      adding = 0;
      host.settled?.();
    }
    // Lines are drawn anew for where the parts go: each moves there from where it was, its
    // words with it. One drawn no more goes out, and one drawn for the first time comes in
    // once it has: never two of a line, never none. Frames, and lines drawn just as they
    // were, stay as they are.
    const root = host.element(model()?.root);
    const now = drawnAnew(root).map((element) => ({ element, as: drawnAs(element, element.parentNode?.getScreenCTM?.()) }));
    const was = new Set((before.drawn || []).map((item) => item.as));
    const stays = new Set(now.filter((item) => was.has(item.as)).map((item) => item.as));
    const lines = before.lines || new Map(), moving = new Set();
    // A part added, the lines are drawn anew round it: they go out as the parts move and come
    // in once they are nearly there -- never bent across a part on its way.
    const late = added ? 0.7 : 0.45;
    for (const { element, as } of now) {
      if (stays.has(as)) continue;
      const old = element.matches(LINES) ? sameLine(element.id, lines) : null;
      const prior = old && !added && lines.get(old);
      const into = prior?.own && element.getScreenCTM?.()?.inverse().multiply(prior.own);
      let morphed = false;
      if (into) {
        for (const path of element.querySelectorAll("path[id]")) {
          const from = pathPoints(prior.paths.get(path.id.slice(element.id.length)));
          morphed = morph(path, from && from.map((point) => { const at = new DOMPoint(point.x, point.y).matrixTransform(into); return { x: at.x, y: at.y }; }), path.getAttribute("d")) || morphed;
        }
      }
      if (morphed) {
        moving.add(old);
        const label = element.querySelector('[id$=".label"]'), box = label?.getBoundingClientRect();
        if (label && box?.width && prior.label?.width) {
          const scale = unitsPerPixel(label);
          const dx = centre(prior.label).x - centre(box).x, dy = centre(prior.label).y - centre(box).y;
          label.animate([{ transform: `translate(${dx * scale}px, ${dy * scale}px)` }, { transform: "translate(0px, 0px)" }], { duration: LAND, easing: ease });
        }
        continue;
      }
      element.animate([{ opacity: 0 }, { opacity: 0, offset: late }, { opacity: 1 }], { duration: LAND, easing: "ease-out" });
    }
    const under = root?.parentNode, into = under?.getScreenCTM?.()?.inverse();
    if (!into) return;
    for (const { copy, matrix, as, id } of before.drawn || []) {
      if (stays.has(as) || !matrix || (id && moving.has(id))) continue;
      for (const named of [copy, ...copy.querySelectorAll("[id], [data-flexo-entity], .hit-line")]) {
        if (named.classList?.contains("hit-line")) { named.remove(); continue; }
        named.removeAttribute("id");
        named.removeAttribute("data-flexo-entity");
      }
      const at = into.multiply(matrix);
      const gone = document.createElementNS("http://www.w3.org/2000/svg", "g");
      gone.setAttribute("transform", `matrix(${at.a} ${at.b} ${at.c} ${at.d} ${at.e} ${at.f})`);
      gone.setAttribute("pointer-events", "none");
      gone.append(copy);
      under.insertBefore(gone, root);
      // (From as faint as it was: one faded while a part was on its way.)
      const faint = copy.classList?.contains("fig-faded") ? 0.18 : 1;
      gone.animate([{ opacity: faint }, { opacity: 0, offset: added ? 0.2 : 0.45 }, { opacity: 0 }], { duration: LAND, fill: "forwards" }).onfinish = () => gone.remove();
      // Should its frames stop, it goes all the same.
      setTimeout(() => gone.remove(), LAND + 200);
    }
  }

  // -- words typed on the drawing --
  // The middle of a line as it is drawn, in the window's pixels: where its words go.
  function lineMiddle(id) {
    const path = host.element(id)?.querySelector("path");
    if (!path?.getTotalLength || !path.getScreenCTM()) return null;
    const length = path.getTotalLength();
    if (!length) return null;
    const point = path.getPointAtLength(length / 2).matrixTransform(path.getScreenCTM());
    return { x: point.x, y: point.y };
  }
  // The colours a label's words may take, as the figure paints them: its first two tones'
  // strong colours for the accents ([words]{accent}, {accent2}), the theme's muted and ink.
  // A colour as the page writes it, whatever way it was given: two the same are equal.
  const colourPen = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;
  function sameColour(colour) {
    if (!colour || !colourPen) return String(colour || "").trim().toLowerCase();
    colourPen.fillStyle = "#000000";
    colourPen.fillStyle = String(colour);
    return colourPen.fillStyle;
  }
  function labelColours() {
    const tones = host.tones?.()?.colours || [], palette = host.palette?.() || {};
    const colours = { accent: painted(tones[0]), accent2: painted(tones[1]), muted: palette.muted, ink: palette.ink };
    // Each colour once: an accent painted in the ink (a black-and-white theme's) is the ink's,
    // however each is written ("#111", "#111111").
    const seen = new Set();
    for (const name of ["ink", "muted", "accent", "accent2"]) {
      const colour = sameColour(colours[name]);
      if (!colour) continue;
      if (seen.has(colour)) colours[name] = null; else seen.add(colour);
    }
    return Object.values(colours).some(Boolean) ? colours : false;
  }
  let inline = null;
  // The field whose ⌘Z is being done as the document's undo (see openInline): the undo
  // leaves it open.
  let undoing = null;
  // Where the box the words are typed in is kept: the host's \`typing\` element, which stays
  // as the drawing is put in again (so the keys go on through a redraw), else the overlay.
  const typingPlace = () => host.typing || host.overlay;
  // Return or Esc ends the typing and keeps what was typed, as a Mac text field does;
  // so does clicking elsewhere. ⌘Z takes it back.
  // `guess`: where a part just added will be drawn (guessPlace), typed on there until it is.
  // `after`: the part a part just added went after (chosen again should it be given no words).
  function openInline(id, { at = null, guess = null, fresh = null, after = null } = {}) {
    closeInline(false);
    const kind = typeOf(id);
    const item = kind === "node" ? nodeOf(id) : kind === "edge" ? edgeOf(id) : kind === "net" ? netOf(id) : groupOf(id);
    if (!item || !(host.box(id) || guess)) return;
    const original = words(item.label);
    // A label's words are names and maths, not prose: no spelling, no corrections.
    // Its format bar is the slide's words': the theme's colours too.
    const field = ui.markup({ value: original, rows: 1, colours: labelColours(), emphasis: false, spelling: false, lines: true });
    // Typed where the words are, as they look there, when the part has words drawn to
    // lie over; else in a box under it.
    // A shape with no words is typed on where they will go, what it is shown faintly there.
    // So is a line with none: at its middle, where its words will be drawn.
    const bare = (kind === "node" && !original.trim() && Boolean(hintOf(item)) && !host.element(`${id}.label`) && Boolean(host.box(id)))
      || (lineKind(kind) && !host.element(`${id}.label`) && Boolean(lineMiddle(id)));
    if (kind === "node" && !original.trim()) field.area.placeholder = (fresh && givenWords(item)) || hintOf(item);
    if (lineKind(kind) && !original.trim()) field.area.placeholder = "Label";
    // Its faint hint gives way to the field's own, said in the same place.
    for (const hint of host.overlay.querySelectorAll(`.fig-wordless[data-id="${CSS.escape(id)}"]`)) hint.remove();
    const label = host.element(`${id}.label`) || (guess && !host.box(id) ? guess : null) || (bare ? "bare" : null);
    const box = h(`div.fig-inline${label ? ".in-place" : ""}`, { title: "Esc or ⌘Return: done · $maths$ · *emphasis*" }, field,
      label ? null : h("div.inline-foot", {}, h("span", {}, "Esc or ⌘Return: done"), h("span", {}, "$maths$ · *emphasis*")));
    // A shape's words wrap where the drawing wraps them; a line's or a group's break only
    // where they are broken, as the drawing breaks them.
    if (label && kind === "node") field.area.style.whiteSpace = "pre-wrap";
    else if (label) field.area.setAttribute("wrap", "off");
    typingPlace().append(box);
    // The handles on the part step aside while it is typed on.
    for (const handle of host.overlay.querySelectorAll(".fig-next, .fig-rotate")) handle.remove();
    // So does a line's mark along it: its words' box is where it is now.
    for (const twin of host.element(id)?.querySelectorAll(".hit-line.chosen") || []) twin.classList.remove("chosen");
    inline = { id, kind, field: field.area, original, box, inPlace: Boolean(label), sent: original, merge: `label:${id}:${Date.now()}`, live: null,
      guess: label === guess ? guess : null, look: guess?.look || null, fresh, after, waiting: null,
      // The words as the figure has them, that what is typed is typed over; and every
      // version of them sent from here (one coming back late is not someone else's).
      base: original, mine: new Set([original]) };
    placeInline();
    field.area.focus();
    // Double-clicked on a word, the word is chosen, as on a Mac; else all of it. (A group's
    // title is a name, typed over whole as a shape's words in it are: all of it, always.)
    const byWord = at && kind !== "group" && label?.getScreenCTM;
    const word = byWord ? wordAt(label, at, field.area.value) : null;
    if (word) field.area.setSelectionRange(word.start, word.end);
    else field.area.select();
    // The figure just chosen by that double-click may still be settling where it is drawn:
    // the word is looked for again once it has, unless typing has begun.
    if (!word && byWord) {
      setTimeout(() => {
        const area = field.area;
        if (inline?.field !== area || area.selectionStart !== 0 || area.selectionEnd !== area.value.length || area.value !== original) return;
        const later = wordAt(host.element(`${id}.label`) || label, at, area.value);
        if (later) area.setSelectionRange(later.start, later.end);
      }, 300);
    }
    field.area.addEventListener("input", () => { placeInline(); drawSoon(); });
    // Its format bar shows once words are chosen in it, as the slide's words' does: not over a
    // caret waiting for the first key.
    const chosenWords = () => box.classList.toggle("words-chosen", field.area.selectionStart !== field.area.selectionEnd);
    for (const type of ["select", "selectionchange", "keyup", "mouseup", "input", "focus"]) field.area.addEventListener(type, chosenWords);
    chosenWords();
    field.area.addEventListener("keydown", (event) => {
      // Return starts a new line, as in any text; Esc or ⌘Return is done (as a click elsewhere
      // is) -- ⌘Return here, not the slide's Present.
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && !event.isComposing) { event.preventDefault(); event.stopPropagation(); closeInline(true); }
      if (event.key === "Escape" && !event.isComposing) { event.preventDefault(); event.stopPropagation(); closeInline(true); }
      // Someone else's words come in as it is typed in, the field's own undo knows nothing
      // of them: ⌘Z is the document's, which takes back this person's typing and keeps theirs.
      // (⇧⌘Z, or ⌘Y, is the document's redo then, too.)
      const typing = inline;
      const mod = event.metaKey || event.ctrlKey, letter = event.key.toLowerCase();
      const back = mod && !event.shiftKey && letter === "z", again = mod && ((event.shiftKey && letter === "z") || (!event.shiftKey && letter === "y"));
      if ((back || again) && typing?.merged && host.undo) {
        event.preventDefault();
        event.stopPropagation();
        clearTimeout(typing.live);
        if (typing.field.value !== typing.sent) { typing.sent = typing.field.value; sendWords(typing, typing.sent, { merge: typing.merge, hold: true, select: false }); }
        // What the figure has after the undo is the field's, as anyone else's words would be:
        // it stays open on them, as a field's own undo leaves it -- unless the undo took the
        // part away, or the figure (the host answers false when it has left it).
        idle().then(() => {
          typing.mine = new Set();
          typing.travelled = true;
          undoing = typing;
          let here = true;
          try { here = (back ? host.undo() : host.redo?.()) !== false; } finally { undoing = null; }
          if (inline !== typing || !typing.undone) return;
          typing.undone = false;
          if (!here) closeInline(false);
          else idle().then(() => { if (inline === typing && !typeOf(typing.id)) closeInline(false); });
        });
      }
    });
    // Left for anywhere else (the slide, another slide, the panel), what was typed is kept
    // -- at once, before what was clicked acts. Not when only the window was left.
    field.area.addEventListener("blur", (event) => {
      if (inline?.box !== box || box.contains(event.relatedTarget) || !document.hasFocus()) return;
      closeInline(true);
    });
  }
  // What is typed is drawn as it is typed, once the keys rest a moment -- and, should they
  // not rest, every so often all the same: the part grows to hold it, as it will when the
  // typing is done, and the box over it follows. It is all one step in the history with the
  // typing's end.
  const RESTED = 300, AT_LEAST = 600;
  function drawSoon() {
    const now = inline;
    if (!now?.inPlace) return;
    clearTimeout(now.live);
    // Waiting since the first key not yet drawn.
    now.waiting ??= Date.now();
    now.live = setTimeout(() => {
      now.waiting = null;
      if (inline !== now || now.field.value === now.sent) return;
      now.sent = now.field.value;
      sendWords(now, now.sent, { merge: now.merge, hold: true, select: false });
    }, Math.max(0, Math.min(RESTED, AT_LEAST - (Date.now() - now.waiting))));
  }
  // The word of the drawn words under a point, found in the words as written.
  function wordAt(label, point, written) {
    const texts = label.matches("text") ? [label] : [...label.querySelectorAll("text")];
    let before = "", hit = null;
    for (const text of texts) {
      const box = text.getBoundingClientRect();
      const inside = point.x >= box.left && point.x <= box.right && point.y >= box.top && point.y <= box.bottom;
      if (inside && !hit && text.getCharNumAtPosition && text.getScreenCTM()) {
        const local = new DOMPoint(point.x, point.y).matrixTransform(text.getScreenCTM().inverse());
        const index = text.getCharNumAtPosition(local);
        const content = text.textContent || "";
        if (index >= 0 && /[\p{L}\p{N}]/u.test(content[index] || "")) {
          let start = index, end = index + 1;
          while (start > 0 && /[\p{L}\p{N}'’-]/u.test(content[start - 1])) start -= 1;
          while (end < content.length && /[\p{L}\p{N}'’-]/u.test(content[end])) end += 1;
          hit = { word: content.slice(start, end), before: before + content.slice(0, start) };
        }
      }
      before += `${text.textContent || ""} `;
    }
    if (!hit) return null;
    // The same word, as often as it came before, in what is written.
    const occurrence = hit.before.split(hit.word).length - 1;
    let from = -1;
    for (let n = 0; n <= occurrence; n += 1) {
      from = written.indexOf(hit.word, from + 1);
      if (from < 0) return null;
    }
    return { start: from, end: from + hit.word.length };
  }
  const measuring = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;
  // Measured as the drawing sets its words: unhinted, to the fraction of a pixel (a slide's
  // words drawn small and scaled up are some 4% wider than the same words set large).
  if (measuring && "textRendering" in measuring) measuring.textRendering = "geometricPrecision";
  // A line of words wrapped at `room` (pixels, in `font`) as the figure wraps a label: at
  // the narrowest width that needs no more lines than filling each line would, so its
  // lines come out even ("Multi-head self-attention / with rotary embeddings").
  function wrapped(line, room, font) {
    if (!measuring) return [line];
    measuring.font = font;
    const space = measuring.measureText(" ").width;
    const all = line.split(/ +/).filter(Boolean);
    const sizes = all.map((word) => measuring.measureText(word).width);
    const fill = (limit) => {
      const lines = [[]];
      let run = 0;
      sizes.forEach((size, index) => {
        const next = run ? run + space + size : size;
        if (run && next > limit + 0.5) { lines.push([index]); run = size; } else { lines[lines.length - 1].push(index); run = next; }
      });
      return lines;
    };
    let lines = fill(room);
    if (lines.length > 1) {
      let low = Math.min(Math.max(...sizes), room), high = room;
      for (let step = 0; step < 12; step += 1) {
        const middle = (low + high) / 2;
        if (fill(middle).length <= lines.length) high = middle; else low = middle;
      }
      lines = fill(high);
    }
    return lines.map((indices) => indices.map((index) => all[index]).join(" "));
  }
  // Where the box over drawn words goes so that its words sit on theirs: its top such that
  // the field's first line has its baseline where the drawing's first line has it. (The
  // field's line is 1.2 of its size, its padding 2 px; the font's own ascent and descent
  // set where its baseline falls in the line.) Else 4 px over the words drawn.
  function alignedTop(drawn, label, look, size) {
    if (!measuring) return drawn.top - 4;
    measuring.font = `${look.weight} ${size}px ${look.family}`;
    const metrics = measuring.measureText("Hg");
    const ascent = metrics.fontBoundingBoxAscent ?? size * 0.95, descent = metrics.fontBoundingBoxDescent ?? size * 0.25;
    // The first line's baseline: from its y where it has one, else its box (whose top is
    // the font's ascent over it).
    const first = label?.matches?.("text") ? label.querySelector("tspan[y]") || label : label?.querySelector?.("tspan[y], text");
    const matrix = first?.getScreenCTM?.(), y = first?.getAttribute("y");
    const baseline = matrix && y !== null && y !== undefined && Number.isFinite(Number(y))
      ? new DOMPoint(Number(first.getAttribute("x")) || 0, Number(y)).matrixTransform(matrix).y : drawn.top + ascent;
    return baseline - (2 + (size * 1.2 - ascent - descent) / 2 + ascent);
  }
  function evened(line, room, font) {
    if (!measuring) return 0;
    const lines = wrapped(line, room, font);
    measuring.font = font;
    return Math.max(...lines.map((text) => measuring.measureText(text).width));
  }
  // Words typed on a part and done with, drawn on it at once -- over the words they
  // replace, in the drawing there is -- until the figure is drawn with them: no moment shows
  // the old words. (Maths is left for the figure to set.)
  let typedOver = null;
  const letters = (text) => String(text ?? "").replace(/[^\p{L}\p{N}]/gu, "");
  function showTyped() {
    const kept = typedOver;
    if (!kept) return;
    const label = kept.ids.map((id) => host.element(`${id}.label`)).find(Boolean);
    // A part added and named before it was first drawn is waited for, its words where they
    // were typed; drawn, they are drawn on it (maths is left for the figure to set).
    const gone = Boolean(kept.box && model() && !kept.ids.some((id) => typeOf(id)));
    const done = gone || Date.now() > kept.until || (label && (!kept.patch || (!label.dataset.typed && letters(label.textContent) === letters(plain(kept.words)))));
    if (label || done) { kept.box?.remove(); kept.box = null; stand(null); }
    if (done) { typedOver = null; return; }
    if (!label) return;
    const id = kept.ids.find((each) => host.element(`${each}.label`) === label);
    // Shown already: again only for other words (a later edit, held too, shows the latest).
    if (label.dataset.typed) {
      if (typedShown.get(id)?.words === kept.words) return;
      unshowTyped(id);
    }
    const style = getComputedStyle(label), scale = label.getScreenCTM()?.a || 1;
    const units = parseFloat(style.fontSize) || 10, size = units * scale;
    const measure = Number(label.closest("[data-flexo-measure]")?.dataset.flexoMeasure) || 16;
    const font = `${style.fontWeight} ${size}px ${style.fontFamily}`;
    const lines = plain(kept.words).split("\n").flatMap((line) => wrapped(line, measure * size, font));
    const box = label.getBBox();
    const x = label.querySelector("tspan")?.getAttribute("x") ?? label.getAttribute("x");
    const middle = box.y + box.height / 2;
    typedShown.set(id, { label, words: kept.words, children: [...label.childNodes].map((node) => node.cloneNode(true)), fontSize: label.style.fontSize });
    const draw = (units) => label.replaceChildren(...lines.map((text, index) => {
      const span = document.createElementNS("http://www.w3.org/2000/svg", "tspan");
      span.setAttribute("x", x);
      span.setAttribute("y", middle + units * 0.35 + (index - (lines.length - 1) / 2) * units * 1.25);
      span.textContent = text;
      return span;
    }));
    draw(units);
    label.dataset.typed = "1";
    // Wider than its shape (the studio away, the figure not drawn again to hold them): the
    // shape grows to hold them, as the figure will draw it -- as far as the parts beside it
    // leave room; past that the words are set a little smaller, never below 85%.
    const shape = host.element(id)?.querySelector('rect[id$=".body"]') || host.element(id)?.querySelector("rect, path, polygon, ellipse");
    const outline = shape?.getBBox?.();
    if (!outline?.width) return;
    const shown = typedShown.get(id);
    const inner = /polygon|ellipse/i.test(shape.tagName) ? 0.7 : 1, pad = units * 0.6;
    const grown = label.getBBox();
    let room = outline.width * inner;
    if (shape.matches('rect[id$=".body"]') && grown.width + 2 * pad > room) {
      const mine = host.box(id), perPixel = 1 / (label.getScreenCTM()?.a || 1);
      const beside = (model()?.nodes || []).filter((node) => node.id !== id).map((node) => host.box(node.id))
        .filter((box) => box && mine && box.top < mine.top + mine.height && box.top + box.height > mine.top);
      const gap = (side) => Math.min(Infinity, ...beside.map((box) => (side < 0 ? mine.left - (box.left + box.width) : box.left - (mine.left + mine.width))).filter((each) => each >= 0));
      // (Clear of the line between them, its arrowhead and its words: a third of the way.)
      const spare = Math.max(0, Math.min(gap(-1), gap(1), 400) * 0.33 - 4) * perPixel;
      const wide = Math.min(grown.width + 2 * pad, outline.width + 2 * spare);
      Object.assign(shown, { body: shape, x: shape.getAttribute("x"), width: shape.getAttribute("width") });
      const centre = Number(shape.getAttribute("x")) + Number(shape.getAttribute("width")) / 2;
      shape.setAttribute("x", centre - wide / 2);
      shape.setAttribute("width", wide);
      room = wide;
      // A line's words the grown shape would lie under step aside until it is drawn anew.
      const body = shape.getBoundingClientRect();
      shown.hidden = [...(host.element(model()?.root)?.querySelectorAll('[data-flexo-entity="connector"] [id$=".label"]') || [])].filter((words) => {
        const rect = words.getBoundingClientRect();
        return rect.width && rect.left < body.right && rect.right > body.left && rect.top < body.bottom && rect.bottom > body.top;
      });
      for (const words of shown.hidden) words.style.visibility = "hidden";
    }
    const fit = Math.min(1, (room - 2 * pad) / (grown.width || 1), (outline.height * inner - pad) / (grown.height || 1));
    if (fit < 0.98) {
      const smaller = units * Math.max(0.85, fit);
      label.style.fontSize = `${smaller}px`;
      draw(smaller);
    }
  }
  // Words typed over a part's, shown on the drawing before it was drawn with them: put back.
  const typedShown = new Map();
  function unshowTyped(id) {
    const shown = typedShown.get(id);
    typedShown.delete(id);
    for (const words of shown?.hidden || []) words.style.visibility = "";
    if (!shown?.label.isConnected) return;
    shown.label.replaceChildren(...shown.children);
    delete shown.label.dataset.typed;
    shown.label.style.fontSize = shown.fontSize || "";
    if (shown.body && shown.x !== undefined) { shown.body.setAttribute("x", shown.x); shown.body.setAttribute("width", shown.width); }
  }
  function placeInline() {
    // (Once the figure knows it -- read, for a figure just made -- and it is drawn, or has a
    // place to be typed on meanwhile.)
    if (typeInto && !inline && typeOf(typeInto) && (host.box(typeInto) || early?.guess)) {
      // At once, where it is drawn -- or, not drawn yet, where it will be: the caret is
      // there as the figure knows the part, and the words typed meanwhile are in it.
      const id = typeInto, waiting = early;
      typeInto = null;
      early = null;
      // (Its own words shown again: its editor is over them now.)
      for (const text of waiting?.hid || []) text.style.visibility = "";
      if (chosenOne() === id) {
        openInline(id, { guess: waiting?.guess, fresh: waiting?.merge, after: waiting?.after });
        if (inline?.id === id && waiting) {
          if (waiting.text !== null) {
            inline.field.value = waiting.text;
            inline.field.setSelectionRange(waiting.text.length, waiting.text.length);
            inline.field.dispatchEvent(new Event("input"));
          }
          if (waiting.done) closeInline(true);
        }
      }
    }
    showTyped();
    if (!inline) return;
    const holder = typingPlace();
    if (inline.box.parentNode !== holder) holder.append(inline.box);
    const drawnPart = host.box(inline.id);
    // Typed where a part just added will be until it is drawn; then it glides to it.
    if (drawnPart && inline.guess) {
      inline.look = inline.guess.look;
      inline.guess = null;
      inline.box.classList.add("gliding");
      setTimeout(() => inline?.box.classList.remove("gliding"), 340);
    }
    const where = drawnPart || inline.guess;
    if (!where) return;
    // From the window's pixels to the holder's (it may scroll), and the part where it is.
    const frame = holder.getBoundingClientRect(), outer = host.overlay.getBoundingClientRect();
    const x = (client) => client - frame.left + holder.scrollLeft - holder.clientLeft;
    const y = (client) => client - frame.top + holder.scrollTop - holder.clientTop;
    if (!inline.guess) stand(null);
    const part = { left: outer.left + where.left, top: outer.top + where.top, bottom: outer.top + where.top + where.height };
    const label = inline.inPlace && !inline.guess && host.element(`${inline.id}.label`);
    // In place on a shape with no words drawn: typed at its middle, as its words will be.
    const bare = !label && !inline.guess && inline.inPlace && (inline.kind === "node" || lineKind(inline.kind));
    if (!label && !inline.guess && !bare) {
      // Under the part, kept on the stage -- in sight, clear of what is beside it (a slide's
      // inspector), and over the part should there be no room under it.
      const wide = Math.max(where.width, 240), seen = inSight(holder);
      const left = Math.max(seen.left + 8, Math.min(part.left, seen.right - 8 - wide));
      const high = inline.box.getBoundingClientRect().height || 60;
      const top = part.bottom + 6 + high > seen.bottom - 8 ? Math.max(seen.top + 8, part.top - 6 - high) : part.bottom + 6;
      Object.assign(inline.box.style, { left: `${x(left)}px`, top: `${y(top)}px`, minWidth: `${wide}px` });
      return;
    }
    // Over the drawn words, in their face, size and colour; they step aside meanwhile.
    if (label && inline.label !== label) { inline.label?.style.removeProperty("visibility"); label.style.visibility = "hidden"; inline.label = label; }
    const style = label ? getComputedStyle(label) : null;
    const look = label ? { size: parseFloat(style.fontSize) * (label.getScreenCTM()?.a || 1), family: style.fontFamily, weight: style.fontWeight,
      fill: style.fill && style.fill !== "none" ? style.fill : "" } : inline.guess?.look || (inline.look ??= figureLook());
    const size = look.size;
    // As wide as its longest line, growing as it is typed. A shape's words wrap where the
    // drawing wraps them: at the measure the figure wraps them at (its ems), the lines
    // evened out as the drawing evens them -- or, for a shape given its width, as wide as
    // they are drawn when the drawing wrapped them (more lines than were typed).
    let room = Infinity;
    const measure = label ? Number(label.closest("[data-flexo-measure]")?.dataset.flexoMeasure) || 16 : look.measure;
    const drawn = label ? label.getBoundingClientRect() : null;
    if (inline.kind === "node") {
      const lines = drawn ? Math.max(1, Math.round(drawn.height / (size * 1.25))) : 1;
      const sized = nodeOf(inline.id)?.width != null;
      room = sized && drawn && lines > inline.sent.split("\n").length ? drawn.width + size * 0.6 : measure * size;
    }
    // Typed on a part with no words drawn yet, between others (one just added): the words
    // wrap to the room there is beside it -- in a diamond's or a circle's middle -- not across
    // its neighbours while the figure makes room for them.
    const kindHere = nodeOf(inline.id)?.kind || "block";
    if (bare && inline.kind === "node" && !inline.guess) {
      const share = { decision: 0.55, circle: 0.62, io: 0.7 }[kindHere] || 1;
      room = Math.max(size * 4, Math.min(room, roomBeside(inline.id, where) * share - size - 12));
    }
    const font = `${look.weight} ${size}px ${look.family}`;
    // With nothing typed yet, as wide as what it says it is.
    const lines = inline.field.value ? inline.field.value.split("\n") : [inline.field.placeholder || " "];
    const text = Math.min(Math.max(...lines.map((line) => evened(plain(line) || " ", room, font))), room);
    // (How many lines they take, wrapped so.)
    const rows = lines.reduce((sum, line) => sum + Math.max(1, wrapped(plain(line) || " ", room, font).length), 0);
    let width = text + size + 12;
    // Drawn as typed, the shape holds the words: the box keeps inside it, its ring within the
    // chosen frame -- and room for the words and the caret all the same, never cut short.
    // (A diamond's words sit in its middle: the box keeps to that, as they do.)
    const inner = ["decision", "circle"].includes(nodeOf(inline.id)?.kind) ? 0.62 : 1;
    if (drawn && inline.kind === "node" && inline.field.value === inline.sent) width = Math.min(width, Math.max(where.width * inner - 8, text + 12));
    // The words wrap in the box where the drawing will wrap them: as wide as the widest line
    // (and a caret).
    const pad = Math.max(2, (width - text - 8) / 2);
    // On a part with none drawn yet, where its words will be drawn (a heading at its top
    // left, a plasmid's over its length): the same place as its faint hint.
    const place = !drawn && !inline.guess && inline.kind === "node"
      ? wordsAt(nodeOf(inline.id), { left: part.left, top: part.top, width: where.width, height: where.height }, size)
      : !drawn && lineKind(inline.kind) ? (({ x, y } = lineMiddle(inline.id) || { x: part.left + where.width / 2, y: part.top + where.height / 2 }) => ({ x, y, anchor: "middle" }))() : null;
    let middle = drawn?.width ? drawn.left + drawn.width / 2
      : place ? (place.anchor === "start" ? place.x - pad + width / 2 : place.x) : part.left + where.width / 2;
    let top = drawn?.height ? alignedTop(drawn, inline.label, look, size)
      : (place ? place.y : part.top + where.height / 2) - size * 0.7 - 4;
    // A line's first words, on a short line, are typed clear of the parts it joins: over the
    // line or under it, or along it, wherever covers least of them (and of their words).
    if (!drawn && lineKind(inline.kind) && place) {
      const high = size * 1.4 + 8, parts = (model()?.nodes || []).map((node) => host.box(node.id)).filter(Boolean)
        .map((box) => ({ left: outer.left + box.left, top: outer.top + box.top, right: outer.left + box.left + box.width, bottom: outer.top + box.top + box.height }));
      const covered = ([left, top]) => parts.reduce((sum, box) => sum + Math.max(0, Math.min(left + width, box.right) - Math.max(left, box.left))
        * Math.max(0, Math.min(top + high, box.bottom) - Math.max(top, box.top)), 0);
      const tries = [[0, 0], [0, -high / 2 - 3], [0, high / 2 + 3], [-width / 2, -high / 2 - 3], [width / 2, -high / 2 - 3], [-width / 2, high / 2 + 3], [width / 2, high / 2 + 3]]
        .map(([dx, dy]) => [middle + dx - width / 2, top + dy]);
      const best = tries.reduce((chosen, spot) => (covered(spot) < covered(chosen) - 1 ? spot : chosen));
      [middle, top] = [best[0] + width / 2, best[1]];
    }
    // Kept within the figure's frame, wider than the shape as it may be: never past its edge.
    // (Not one not drawn yet: it is typed in its stand-in, wherever that is.)
    const all = inline.kind === "node" && !inline.guess ? host.box(model()?.root) : null;
    if (all?.width > width) middle = Math.max(outer.left + all.left + width / 2, Math.min(middle, outer.left + all.left + all.width - width / 2));
    Object.assign(inline.box.style, { left: `${x(middle - width / 2)}px`, top: `${y(top)}px`, width: `${width}px`, minWidth: "" });
    // Not drawn yet, the part stands where it will be, as a shape like the one before it --
    // wide enough for its words from the first, the box over them never past its edges.
    // So too a part drawn with no words yet (as it was added), while the words typed on it are
    // wider than it is: as that shape, grown to hold them, over it -- never hidden under them.
    const kind = nodeOf(inline.id)?.kind || "block";
    const inside = inline.kind === "node" && !["text", "label", "person", "structure", "plasmid"].includes(kind) && !HEADED.has(kind) && !BANDED.has(kind);
    if (inline.guess || (bare && inside && inline.field.value)) {
      // (At the size it will be drawn, for the words typed on it -- as the figure sizes a
      // shape for its words, not for the box they are typed in.)
      const grown = drawnSize(kind, text, rows, size, where);
      const wide = grown.width, high = grown.height;
      // (Words with no shape of their own -- a Text -- stand as words alone.)
      const alone = ["text", "label"].includes(kind);
      const paint = inline.guess ? where.paint : paintOf(inline.id);
      if (inline.guess || wide > where.width + 2 || high > where.height + 2) {
        stand({ left: x(outer.left + where.left + where.width / 2 - wide / 2), top: y(outer.top + where.top + where.height / 2 - high / 2),
          width: wide, height: high, paint, bare: alone, kind }, holder);
      }
    }
    Object.assign(inline.field.style, { fontSize: `${size}px`, fontFamily: look.family, fontWeight: look.weight,
      color: look.fill, textAlign: "center", paddingLeft: `${pad}px`, paddingRight: `${pad}px`, textRendering: "geometricPrecision" });
    // Wider than its shape until the drawing catches up, the words lie on the page's paper,
    // not across the parts beside it.
    // (A line's words, typed over the line, lie on the paper too: the line does not run through them.)
    const spills = inline.kind === "node" && width > where.width + 2;
    inline.box.classList.toggle("spills", spills);
    // (A veil of it, not a sheet: what is under the words -- a shape beside them -- shows through.)
    const paper = getComputedStyle(host.overlay).backgroundColor;
    inline.box.style.background = (spills || lineKind(inline.kind)) && paper ? `color-mix(in srgb, ${paper} 72%, transparent)` : "";
    // Its formatting bar sits over the part, under it or beside it: wherever it covers least
    // of what is drawn around -- the other parts, the lines and their words, the slide's own
    // title and words -- and in sight, on the stage.
    const tools = inline.box.querySelector(".markup-tools");
    if (tools && getComputedStyle(tools).position === "absolute") {
      Object.assign(tools.style, { left: "", top: "", bottom: "", transform: "", marginLeft: "" });
      const { width: wide, height: high } = tools.getBoundingClientRect();
      const box = inline.box.getBoundingClientRect();
      const shape = { left: Math.min(part.left, box.left), right: Math.max(part.left + where.width, box.right) };
      const middle = (box.left + box.right) / 2, level = (box.top + box.bottom) / 2 - high / 2;
      const seen = inSight(holder);
      const placed = (left, top) => {
        const x = Math.max(seen.left + 4, Math.min(left, seen.right - 4 - wide));
        return { left: x, top, right: x + wide, bottom: top + high };
      };
      const places = [
        placed(middle - wide / 2, Math.min(box.top - 8, part.top - 6) - high),
        placed(middle - wide / 2, Math.max(box.bottom + 8, part.bottom + 6)),
        placed(shape.right + 8, level),
        placed(shape.left - 8 - wide, level),
      ];
      const crowd = crowdAround(inline.id, outer);
      const page = host.overlay.querySelector("svg")?.getBoundingClientRect() || outer;
      const cost = (rect, rank) => {
        if (rect.top < seen.top + 4 || rect.bottom > seen.bottom - 4 || rect.left < seen.left + 2 || rect.right > seen.right - 2) return Infinity;
        const over = (other) => Math.max(0, Math.min(rect.right, other.right) - Math.max(rect.left, other.left)) * Math.max(0, Math.min(rect.bottom, other.bottom) - Math.max(rect.top, other.top));
        const inside = (point) => point.x >= rect.left && point.x <= rect.right && point.y >= rect.top && point.y <= rect.bottom;
        // Off the page it covers nothing, but lies a little apart from what it formats.
        const off = wide * high - over(page);
        return crowd.rects.reduce((sum, other) => sum + over(other) * other.weight, 0) + crowd.points.reduce((sum, point) => sum + (inside(point) ? point.weight : 0), 0)
          + over(box) * 4 + off * 0.05 + rank * 40;
      };
      const best = places.map((rect, rank) => ({ rect, price: cost(rect, rank) })).reduce((a, b) => (b.price < a.price ? b : a));
      Object.assign(tools.style, { left: `${best.rect.left - box.left}px`, top: `${best.rect.top - box.top}px`, bottom: "auto", transform: "none" });
    }
  }
  // Where the stage is in sight: inside the window and every box around that clips it.
  function inSight(element) {
    const sight = { left: 0, top: 0, right: innerWidth, bottom: innerHeight };
    for (let at = element; at && at !== document.documentElement; at = at.parentElement) {
      const style = getComputedStyle(at);
      if (style.overflowX === "visible" && style.overflowY === "visible") continue;
      const rect = at.getBoundingClientRect();
      Object.assign(sight, { left: Math.max(sight.left, rect.left), top: Math.max(sight.top, rect.top), right: Math.min(sight.right, rect.right), bottom: Math.min(sight.bottom, rect.bottom) });
    }
    return sight;
  }
  // What a bar over the drawing should not cover, in the window's pixels: the other parts,
  // the words on lines and what the slide draws beside the figure (its band, its title,
  // its other words), each a box; and the lines, as points along them, each worth the
  // stretch of line it stands for.
  const along = new WeakMap();
  function crowdAround(id, outer) {
    const rects = [], points = [];
    const add = (rect) => { if (rect.width || rect.height) rects.push({ left: rect.left, top: rect.top, right: rect.left + rect.width, bottom: rect.top + rect.height, weight: 1 }); };
    for (const node of model()?.nodes || []) {
      const other = node.id !== id && host.box(node.id);
      if (other) add({ left: outer.left + other.left, top: outer.top + other.top, width: other.width, height: other.height });
    }
    const root = host.element(model()?.root);
    for (const line of root?.querySelectorAll(LINES) || []) {
      for (const words of line.querySelectorAll('[id$=".label"]')) add(words.getBoundingClientRect());
      for (const path of line.querySelectorAll("path:not(.hit-line)")) {
        const matrix = path.getScreenCTM?.();
        if (!matrix || !path.getTotalLength) continue;
        if (!along.has(path)) {
          const length = path.getTotalLength(), steps = Math.min(200, Math.max(1, Math.ceil(length / 4)));
          along.set(path, { step: length / steps, points: Array.from({ length: steps + 1 }, (_, index) => path.getPointAtLength((length * index) / steps)) });
        }
        const { step, points: local } = along.get(path);
        // As if the line were six pixels wide.
        const weight = step * Math.hypot(matrix.a, matrix.b) * 6;
        for (const point of local) { const at = new DOMPoint(point.x, point.y).matrixTransform(matrix); points.push({ x: at.x, y: at.y, weight }); }
      }
    }
    for (let at = root; at?.parentNode && at.tagName !== "svg"; at = at.parentNode) {
      for (const beside of at.parentNode.children) {
        if (beside === at || ["defs", "style", "title"].includes(beside.tagName) || /(^|\.)background$/.test(beside.id)) continue;
        add(beside.getBoundingClientRect());
      }
    }
    return { rects, points };
  }
  // The shape of a part added, where it will be drawn, until it is: none when drawn.
  let standing = null;
  function stand(place, holder = typingPlace()) {
    if (!place) { standing?.remove(); standing = null; return; }
    // Put after what the holder holds: a slide's page stays the first thing in it.
    if (!standing) { standing = h("div.fig-standing"); holder.append(standing); }
    standing.classList.toggle("bare", Boolean(place.bare));
    standing.classList.toggle("group", place.kind === "group");
    // A shape not a box (a diamond, a circle, a cylinder) stands as that shape.
    const outline = place.bare ? null : outlineOf(place.kind, place.width, place.height);
    standing.classList.toggle("shaped", Boolean(outline));
    Object.assign(standing.style, { left: `${place.left}px`, top: `${place.top}px`, width: `${place.width}px`, height: `${place.height}px`,
      background: place.bare || outline ? "" : place.paint?.fill || "", borderColor: place.bare || outline ? "" : place.paint?.stroke || "" });
    const fill = place.paint?.fill || "var(--raised)", stroke = place.paint?.stroke || "var(--line-strong)";
    standing.innerHTML = outline ? `<svg width="${place.width}" height="${place.height}" style="overflow:visible;display:block"><g style="fill:${fill};stroke:${stroke};stroke-width:1.5">${outline}</g></svg>` : "";
    // (Its words typed so far, a caret after them -- or what it is, faintly: see showEarly.)
    if (typeof place.words === "string") {
      const look = place.look || {};
      standing.append(h(`span.fig-standing-words${place.words ? "" : ".hint"}`, {
        style: { fontSize: look.size ? `${look.size}px` : "", fontFamily: look.family || "", fontWeight: look.weight || "", color: look.fill || "" } },
      h("span", {}, place.words || place.hint || ""), h("span.caret")));
    }
  }
  // The outline of a shape of `kind`, `w` by `h` (SVG), for one that is not a box; else null.
  function outlineOf(kind, w, h) {
    const i = 1;
    switch (kind) {
      case "decision": return `<polygon points="${w / 2},${i} ${w - i},${h / 2} ${w / 2},${h - i} ${i},${h / 2}"/>`;
      case "circle": return `<ellipse cx="${w / 2}" cy="${h / 2}" rx="${w / 2 - i}" ry="${h / 2 - i}"/>`;
      case "terminal": return `<rect x="${i}" y="${i}" width="${w - 2 * i}" height="${h - 2 * i}" rx="${h / 2 - i}"/>`;
      case "io": { const slant = Math.min(h * 0.35, w * 0.2); return `<polygon points="${slant + i},${i} ${w - i},${i} ${w - slant - i},${h - i} ${i},${h - i}"/>`; }
      case "database": {
        const ry = Math.min(h * 0.14, 8), rx = w / 2 - i;
        return `<path d="M${i},${ry + i} A${rx},${ry} 0 0 1 ${w - i},${ry + i} V${h - ry - i} A${rx},${ry} 0 0 1 ${i},${h - ry - i} Z"/>`
          + `<path d="M${i},${ry + i} A${rx},${ry} 0 0 0 ${w - i},${ry + i}" style="fill:none"/>`;
      }
      default: return null;
    }
  }
  // How large a shape of `kind` must be to hold a box of typing `width` by `height` inside it
  // (a diamond's words in its middle, a cylinder's under its lid).
  // How large a part of `kind` is drawn for words `text` wide (in pixels) on `rows` lines,
  // `size` their size: as flexo sizes it (its padding, in ems of its words) -- never smaller
  // than `at`, the size it is drawn with the words it starts with.
  function drawnSize(kind, text, rows, size, at) {
    const high = rows * size * 1.2, padX = size * 0.875, padY = size * 0.625;
    switch (kind) {
      case "circle": { const across = Math.max(at.width, at.height, Math.hypot(text, high) + padY); return { width: across, height: across }; }
      case "decision": return { width: Math.max(at.width, 2 * text + 4 * padX), height: Math.max(at.height, 2 * high + 4 * padY) };
      default: return holding(kind, text + 2 * padX - 10, high + 2 * padY - 6, at);
    }
  }
  function holding(kind, width, height, at) {
    switch (kind) {
      case "decision": { const high = Math.max(at.height, height * 2.4); return { width: Math.max(at.width, width / (1 - height / high) + 6), height: high }; }
      case "circle": { const across = Math.max(at.width, at.height, Math.hypot(width, height) + 6); return { width: across, height: across }; }
      case "io": { const high = Math.max(at.height, height + 8); return { width: Math.max(at.width, width + high * 0.7 + 6), height: high }; }
      case "database": return { width: Math.max(at.width, width + 10), height: Math.max(at.height, height * 1.9 + 6) };
      default: return { width: Math.max(at.width, width + 10), height: Math.max(at.height, height + 6) };
    }
  }
  // Words typed on a part sent, with the words they were typed over: should someone else
  // have changed those meanwhile, the figure keeps both changes, merged.
  function sendWords(typing, text, { name, ...options }) {
    const action = { do: "update", target: { type: typing.kind, id: typing.id }, values: { label: text }, was: typing.base };
    if (name !== undefined) action.name = name;
    typing.base = text;
    typing.mine.add(text);
    act(action, options);
  }
  // A figure come back with other words on the part being typed on than those sent from
  // here: someone else changed them. They come into the field, merged with what is typed
  // there, the caret kept where it was among the words.
  function mergeTyping() {
    const typing = inline;
    if (!typing || typing.guess) return;
    const item = typing.kind === "node" ? nodeOf(typing.id) : typing.kind === "edge" ? edgeOf(typing.id) : typing.kind === "net" ? netOf(typing.id)
      : typing.kind === "group" ? groupOf(typing.id) : null;
    if (!item || typeof (item.label ?? "") !== "string") return;
    const theirs = item.label ?? "";
    if (theirs === typing.base || typing.mine.has(theirs)) return;
    const field = typing.field, before = field.value;
    const merged = mergeText(typing.base, before, theirs);
    typing.merged = true;
    typing.base = theirs;
    typing.sent = theirs;
    typing.mine.add(theirs);
    // (Undone or redone from the field, the caret goes where the words changed, as a field's
    // own undo puts it: after those put back.)
    const travelled = typing.travelled;
    typing.travelled = false;
    if (merged === before) return;
    let same = 0, after = 0;
    while (same < before.length && same < merged.length && before[same] === merged[same]) same += 1;
    while (after < before.length - same && after < merged.length - same && before.at(-1 - after) === merged.at(-1 - after)) after += 1;
    const shift = (at) => (at <= same ? at : at + merged.length - before.length);
    const [start, end] = travelled ? [merged.length - after, merged.length - after] : [shift(field.selectionStart), shift(field.selectionEnd)];
    field.value = merged;
    field.setSelectionRange(start, end);
    placeInline();
    // What was typed here and not yet sent goes, over their words.
    if (merged !== theirs) drawSoon();
  }
  // "\n" typed in words -- not in maths or code, where \nu and \n are their own -- as the
  // new line it means (⇧Return is the key for one).
  const typedBreaks = (text) => String(text).split(/(\$[^$]*\$|`[^`]*`)/).map((part, at) => (at % 2 ? part : part.replace(/\\n/g, "\n"))).join("");
  function closeInline(keep) {
    if (!inline) return;
    if (!keep && inline === undoing) { inline.undone = true; return; }
    const closing = inline;
    const { id, kind, field, original, box, sent, merge, inPlace, guess, fresh, after } = inline;
    clearTimeout(inline.live);
    inline.label?.style.removeProperty("visibility");
    const bare = inPlace && !inline.label && !guess;
    inline = null;
    // Words just added, left empty, are no words: the part goes with the step that made it.
    if (fresh && kind === "node" && nodeOf(id)?.kind === "text" && !field.value.trim()) {
      box.remove();
      stand(null);
      // (One step with its adding, however long after: the two are nothing, in the history too
      // -- no undo of it, nor a redo to bring back an empty part.)
      act({ do: "delete", ids: [id], rejoin: true }, { merge: fresh, hold: true, select: false });
      // The part it was added after is chosen again, as it was: not the whole figure.
      select(after && typeOf(after) ? [after] : []);
      return;
    }
    // "\n" typed in its words (as Graphviz has it) is the new line it means, kept as one.
    if (keep) field.value = typedBreaks(field.value);
    // A part just added, done with no words typed (Return, Esc, a click elsewhere): its kind's
    // own words, as its field showed them -- an MLP's "MLP" -- not none.
    const given = keep && fresh && kind === "node" && !original.trim() && !field.value.trim() ? givenWords(nodeOf(id)) : "";
    if (given) field.value = given;
    // Done before the part (or any words on it) is drawn, its words stay where they were
    // typed until they are -- however long the figure takes to be drawn with it.
    const waits = Boolean(keep && (guess || bare) && field.value.trim());
    if (waits) {
      box.classList.add("kept");
      field.readOnly = true;
      field.blur();
    } else {
      box.remove();
      stand(null);
    }
    // Drawn as it was typed, the last words join that step; else one step of their own. A
    // part named for the words it had (as the figure names a part it adds) is named for its
    // new words with them.
    // A part just added, given its first words, is named for them (as the figure names a
    // part it adds) -- before anyone else can know it by another name. A part that was
    // there already keeps its id, whatever its words: others may know it by it -- as they
    // do one someone else has typed in meanwhile (their words came into these).
    const named = keep && kind === "node" && Boolean(fresh) && !original.trim() && Boolean(field.value.trim()) && !closing.merged;
    if (keep && (field.value !== sent || named)) {
      sendWords(closing, field.value, { merge: sent === original ? null : merge, hold: true, select: false, follow: id, ...(named ? { name: "" } : {}) });
    }
    if (waits || (keep && inPlace && kind === "node" && field.value !== original)) {
      // (A part not drawn yet is waited for as long as a slow studio takes -- its words in
      // their box meanwhile, never gone from sight -- unless it goes: an undo, say.)
      const wait = waits ? 180000 : 4000;
      const kept = { ids: [id], words: field.value, until: Date.now() + wait, box: waits ? box : null, patch: !/[$\\]/.test(field.value) };
      typedOver = kept;
      setTimeout(() => { kept.box?.remove(); if (typedOver === kept) { typedOver = null; stand(null); } }, wait + 100);
      showTyped();
    }
    host.settled?.();
  }
  // -- keys --
  // Answers whether it took the key: the host does what it does with the rest.
  function key(event) {
    // A key typed in a field is the field's: nothing on the drawing acts on it.
    if (typingIn(event.target) || typingIn(document.activeElement)) return true;
    if (earlyKey(event)) return true;
    // Nor one typed just after, should the field have been drawn again under the keys
    // (the figure came back from the server): ⌫ deletes words, never the part.
    if ((event.key === "Backspace" || event.key === "Delete") && Date.now() - lastTyped < 1500
        && (!document.activeElement || document.activeElement === document.body)) { event.preventDefault(); return true; }
    const mod = event.metaKey || event.ctrlKey;
    if (event.key === "Escape") {
      if (state.connecting) { toggleConnect(false); return true; }
      if (state.selected.length) { select([]); return true; }
      // A shape just deleted: Esc chooses the figure itself (the next, the slide's).
      if (state.inside) { state.inside = false; host.changed(); return true; }
      return false;
    }
    if (mod) {
      if (event.key.toLowerCase() === "d" && state.selected.length) { event.preventDefault(); duplicate(); return true; }
      // ⌘A chooses every part of the figure being edited -- in the figure editor, always; on a
      // slide, once its shapes are being edited (one chosen, or one just deleted) -- as Keynote's
      // Select All does inside a group it is editing. (The figure alone chosen: the slide's.)
      if (event.key.toLowerCase() === "a" && !event.altKey && !event.shiftKey && model() && (host.whole || state.selected.length || state.inside)) {
        event.preventDefault();
        chooseAll();
        return true;
      }
      return false;
    }
    if (event.key === "Backspace" || event.key === "Delete") {
      // (Nothing chosen after a shape is deleted: nothing more goes.)
      if (!state.selected.length) { if (state.inside) event.preventDefault(); return state.inside; }
      event.preventDefault();
      remove();
      return true;
    }
    // Tab goes from one shape to the next (⇧Tab back), as Keynote's goes from object to object.
    if (event.key === "Tab" && state.selected.length && state.model?.nodes?.length) {
      event.preventDefault();
      const ids = state.model.nodes.map((node) => node.id);
      const at = ids.indexOf(state.selected[state.selected.length - 1]);
      select([ids[at < 0 ? 0 : (at + (event.shiftKey ? -1 : 1) + ids.length) % ids.length]]);
      return true;
    }
    // ⌥ (or ⇧) and an arrow move the part a place that way, as it is seen (nudge): a shape
    // laid out by the figure moves among the others, not by a few points.
    if ((event.altKey || event.shiftKey) && ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) {
      const id = chosenOne();
      if (!id) return false;
      event.preventDefault();
      // (A line goes where the shapes it joins go: it is not moved of itself.)
      if (isLine(id)) { toast("A line moves with the shapes it joins.", { icon: "info", seconds: 2 }); return true; }
      // (One at a time: the next from where the last is drawn.)
      if (!running && !queue.length) nudge(id, event.key);
      return true;
    }
    // An arrow alone chooses the shape drawn next that way, as Tab chooses the next in order:
    // the nearest ahead, and of those, the most nearly in line.
    const way = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
    if (way && !event.shiftKey) {
      const id = chosenOne(), from = id && nodeOf(id) ? host.box(id) : null;
      if (!from) return false;
      event.preventDefault();
      const middle = (box) => ({ x: box.left + box.width / 2, y: box.top + box.height / 2 });
      const here = middle(from);
      let best = null;
      for (const node of model().nodes) {
        const box = node.id !== id && host.box(node.id);
        if (!box) continue;
        const there = middle(box), dx = there.x - here.x, dy = there.y - here.y;
        const ahead = dx * way[0] + dy * way[1], aside = Math.abs(dx * way[1]) + Math.abs(dy * way[0]);
        if (ahead < 2 || aside > ahead * 3) continue;
        const score = ahead + aside * 2;
        if (!best || score < best.score) best = { id: node.id, score };
      }
      if (best) select([best.id]);
      return true;
    }
    const letter = event.key.toLowerCase();
    if (letter === "a") { event.preventDefault(); addPalette(host.addAnchor?.() || { x: innerWidth / 2 - 190, y: 120 }); return true; }
    if (letter === "c") { event.preventDefault(); toggleConnect(); return true; }
    // (Shapes to group chosen: an empty group is added from the palette's Layout.)
    if (letter === "g" && canGroup()) { event.preventDefault(); groupMenu(host.groupAnchor?.() || { x: innerWidth / 2 - 90, y: 120 }); return true; }
    if (letter === "enter") {
      const id = chosenOne();
      if (!id) return false;
      event.preventDefault();
      openInline(id);
      return true;
    }
    return false;
  }

  // -- the inspector's panels --
  function panel() {
    const figure = model();
    if (!figure) return h("div.empty", {}, "The figure can’t be read. See the messages for details.");
    const chosen = state.selected;
    if (chosen.length > 1) return manyPanel(chosen);
    if (!chosen.length) return host.nothing ? host.nothing() : figurePanel();
    const id = chosen[0];
    const kind = typeOf(id);
    return kind === "node" ? nodePanel(nodeOf(id)) : kind === "group" ? groupPanel(groupOf(id))
      : kind === "edge" ? edgePanel(edgeOf(id)) : kind === "net" ? netPanel(netOf(id)) : figurePanel();
  }
  // Parts with tables (a protein's features, a plate's groups) want the room a table needs.
  function wantsRoom() {
    const one = chosenOne();
    return Boolean(one && nodeOf(one) && (partOf(nodeOf(one))?.fields || []).some((field) => field.type === "records"));
  }

  // The way back up: what it is in, each a click away (what it is, its title under says).
  function crumbs(id) {
    const trail = [];
    for (let at = parentOf(id); at; at = parentOf(at.id)) trail.unshift(at.id);
    if (!host.crumbs && !trail.length) return null;
    return h("div.crumbs", {}, host.crumbs ? host.crumbs() : null, trail.map((group, index) => [
      index || host.crumbs ? icon("chevron") : null,
      h("button.crumb", { type: "button", onclick: () => select(group === model().root ? [] : [group]) }, group === model().root ? "Figure" : nameOf(group)),
    ]));
  }

  function headActions(id) {
    const holder = parentOf(id);
    // One place back or on, the way its line is seen (a row: left and right), as ⌥ and an
    // arrow move it.
    const across = holder && drawnKind(holder) === "row";
    const [back, on] = across ? ["ArrowLeft", "ArrowRight"] : ["ArrowUp", "ArrowDown"];
    const step = (key) => () => { if (!running && !queue.length) nudge(id, key); };
    return [
      ui.button("", step(back), { kind: "ghost", small: true, icon: across ? "left" : "up", title: across ? "Move Left (⌥←)" : "Move Up (⌥↑)", disabled: !nudgePlace(id, back) }),
      ui.button("", step(on), { kind: "ghost", small: true, icon: across ? "right" : "down", title: across ? "Move Right (⌥→)" : "Move Down (⌥↓)", disabled: !nudgePlace(id, on) }),
      ui.button("", () => duplicate([id]), { kind: "ghost", small: true, icon: "duplicate", title: "Duplicate (⌘D)" }),
      ui.button("", () => remove([id]), { kind: "ghost", small: true, icon: "trash", title: "Delete (⌫)" }),
    ];
  }

  // A part's ID is what lines and the file name it by: kept, but out of the way.
  function idField(id, type) {
    const input = ui.input({ value: typing(`id:${id}`) ?? id, mono: true, key: `id:${id}` });
    // Renamed once the field is left: not as the panel is drawn again under the keys, which a
    // web view says is a change too.
    input.addEventListener("change", () => setTimeout(() => {
      if (typing(`id:${id}`) !== null) return;
      const to = input.value.trim();
      if (!to || to === id) { input.value = id; return; }
      act({ do: "rename", id, to });
    }, 0));
    input.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); input.blur(); } });
    return ui.field("Name in File", input, { hint: type === "group" ? "What the file calls the group" : "What the file calls the shape; its lines name it so" });
  }
  const advanced = (...content) => h("details.more.advanced", { open: openAdvanced, ontoggle: (event) => { openAdvanced = event.currentTarget.open; } },
    h("summary", {}, icon("chevron"), "Advanced"), h("div.inner.fields", {}, content));
  let openAdvanced = false;

  // What is chosen: its kind (what it is, in its tooltip), and what is not said again below it.
  const titleBlock = (picture, name, hintText, tip = "") =>
    h("div.insp-title", { title: tip }, picture, h("div.insp-words", {}, h("div.insp-name", {}, name), hintText ? h("div.insp-hint", {}, hintText) : null));

  // A part made another kind of shape keeps its words and its lines; one drawn from a
  // file (a structure, a picture) asks for the file first.
  async function retype(node, kind) {
    const next = parts[kind];
    if (!next || kind === (node.kind || "block")) return;
    if (!next.needs_file) { update({ type: "node", id: node.id }, { kind }); return; }
    const field = next.fields.find((item) => item.type === "file");
    const file = await host.chooseFile({ title: `Choose ${article(next.title)} ${titled(next.title)}`, types: field?.types });
    if (file) update({ type: "node", id: node.id }, { kind, "properties.source": file });
  }

  // A line's fields: those of a reaction (its cofactors) only on a figure of biology or
  // chemistry -- or a line that has them already.
  function edgeFields(edge) {
    const science = (model()?.nodes || []).some((node) => ["Biology", "Chemistry"].includes(partOf(node)?.category));
    return catalog.edge_fields.filter((field) => !field.science || science || valueAt(edge, field.key) !== undefined);
  }
  function nodePanel(node) {
    const part = partOf(node) || { title: node.kind, fields: [], hint: "" };
    const kind = node.kind || "block";
    const type = h("button.type-pick", { type: "button", title: "Change the shape’s type", onclick: (event) => addPalette(event.currentTarget, { change: node }) },
      glyph(kind), h("span", {}, parts[kind]?.title || titled(kind)), icon("chevron-down"));
    const lines = model().edges.filter((edge) => nodeOfRef(edge.from) === node.id || nodeOfRef(edge.to) === node.id);
    // (Lines joined into one, it is among their ends.)
    const joined = (model().nets || []).filter((net) => [...(net.sources || []), ...(net.targets || [])].some((ref) => nodeOfRef(ref) === node.id));
    const shown = part.fields.filter((field) => field.key !== "properties.tone");
    return [
      h("div.section.insp-top", {}, crumbs(node.id),
        h("div.insp-row", {}, titleBlock(glyph(kind), part.title, null, part.hint), h("div.insp-actions", {}, headActions(node.id)))),
      kind === "structure" ? structureProblem(node) : null,
      shapeProblem(node, part),
      colourSection([{ type: "node", id: node.id, item: node }]),
      h("div.section", {}, ui.field("Type", type),
        fields(shown, node, (values, merge, hold) => update({ type: "node", id: node.id }, values, merge, hold), `node:${node.id}`)),
      h("div.section", {}, h("div.section-title", {}, "Lines", h("span.count", {}, lines.length + joined.length)),
        lines.length ? h("div.line-list", {}, lines.map((edge) => h("div.line-row", {},
          h("button.link", { type: "button", onclick: () => select([edge.id]) },
            nodeOfRef(edge.from) === node.id ? ["To ", h("b", {}, nameOf(nodeOfRef(edge.to)))] : ["From ", h("b", {}, nameOf(nodeOfRef(edge.from)))],
            edge.label ? h("span.muted", {}, ` · ${plain(edge.label)}`) : null),
          // The line goes; the shape stays chosen.
          ui.button("", () => remove([edge.id], [node.id]), { kind: "ghost", small: true, icon: "close", title: "Delete Line" })))) : null,
        joined.length ? h("div.line-list", {}, joined.map((net) => h("div.line-row", {},
          h("button.link", { type: "button", onclick: () => select([net.id]) }, glyph("net"), " ", nameOf(net.id),
            net.label ? h("span.muted", {}, ` · ${plain(net.label)}`) : null)))) : null,
        h("div.row", {},
          ui.button("Connect to…", () => { select([node.id]); toggleConnect(true); }, { small: true, icon: "right" }),
          // Chosen already, it is not chosen again: the panel would be drawn anew, and the
          // palette lose the button it opens by.
          ui.button("Add Shape After…", (event) => { const anchor = event.currentTarget; if (chosenOne() !== node.id) select([node.id]); addPalette(anchor.isConnected ? anchor : null); }, { small: true, icon: "plus" }))),
      ownLineSection(node.id),
      lineUpSection(node),
      h("div.section", {}, advanced(idField(node.id, "node"))),
    ];
  }

  // A part lined up with another anywhere in the figure, across the way its row or column
  // runs -- each Add LN centred under "Previous layer": a spine down the figure's side.
  function lineUpSection(node) {
    const holder = parentOf(node.id);
    // (In a grid, across its column: the blocks of a spine down one column centred on one line.)
    if (!holder || !["row", "column", "stack", "grid"].includes(writtenKind(holder))) return null;
    const told = namesTold();
    const choices = [{ value: "", label: "Automatic" },
      ...model().nodes.filter((other) => other.id !== node.id).map((other) => ({ value: other.id, label: told.get(other.id) })),
      ...model().groups.filter((group) => group.id !== model().root && !inside(node.id, group.id))
        .map((group) => ({ value: group.id, label: nameOf(group.id) }))];
    const across = writtenKind(holder) === "row" ? "Level with it, across its row" : "Centred on it, across its column";
    return h("div.section", {}, ui.field("Line Up With", ui.select({ value: node.align_with || "", key: `node:${node.id}:align_with`, options: choices,
      onChange: (value) => act({ do: "align", id: node.id, with: value || null }, { label: value ? `Line Up ${inQuotes(nameOf(node.id))} with ${inQuotes(told.get(value) || nameOf(value))}` : `Place ${inQuotes(nameOf(node.id))} as Its Group Does` }) }),
    { hint: across }));
  }

  // What keeps a structure from being drawn as written, said where it is edited.
  // What keeps a shape from being drawn as written (a protein with no length), as the
  // drawing says it (`host.problems()`: [{ id, text, what }]): said at the top of its panel,
  // and the field it is about marked -- the field to put it right in.
  function problemOf(id) {
    return (host.problems?.() || []).find((problem) => problem.id === id) || null;
  }
  // The field of a part's panel a problem is about (`what`: "length", "position", ...).
  function problemField(part, what) {
    if (!part || !what) return null;
    const fieldsOf = part.fields || [];
    return fieldsOf.find((field) => field.key === what || field.key === `properties.${what}` || field.key.endsWith(`.${what}`))
      || (/^(position|records|field|unknown|span|feature|event|track)/.test(what) ? fieldsOf.find((field) => field.type === "records") : null) || null;
  }
  function shapeProblem(node, part) {
    const problem = problemOf(node.id);
    if (!problem) return null;
    const field = problemField(part, problem.what);
    // (Said of the shape by its words; here, in its own panel, what to do is the rest.)
    const words = problem.text.replace(/^\u201c[^\u201d]*\u201d can\u2019t be drawn yet: /, "").replace(/ Choose it to set this in its panel\.$/, "");
    const said = `${words[0]?.toUpperCase() || ""}${words.slice(1)}${field ? ` Set ${field.label} below.` : ""}`;
    return h("div.section", {}, h("div.field-problem", {}, icon("error"), h("span", {}, said)));
  }
  // The part chosen, its panel showing the field a problem of it is about, ready to type in.
  // (A line: at the end of it that is at no shape.)
  function revealProblem(id, what = null) {
    if (!typeOf(id)) return;
    select([id]);
    const edge = edgeOf(id), lost = edge ? ["to", "from"].find((key) => !nodeOf(nodeOfRef(edge[key]))) : null;
    const field = problemField(partOf(nodeOf(id)), what || problemOf(id)?.what);
    if (!field && !lost) return;
    const key = lost ? `edge:${id}:${lost}` : `node:${id}:${field.key}`;
    const show = (tries = 0) => {
      const input = document.querySelector(`[data-key="${CSS.escape(key)}"]`)
        || document.querySelector(`[data-key^="${CSS.escape(key)}"]`);
      if (!input) { if (tries < 20) setTimeout(() => show(tries + 1), 50); return; }
      input.closest(".field, .records")?.classList.add("wanted");
      input.scrollIntoView({ block: "center" });
      input.focus?.({ preventScroll: true });
    };
    show();
  }
  function structureProblem(node) {
    const box = h("div.insp-problem");
    const section = h("div.section", { hidden: true }, box);
    settingsOf(node.id).then((settings) => {
      if (!settings?.problem) return;
      clear(box, icon("warning"), h("div", {}, h("b", {}, settings.problem), " ", settings.reason || ""));
      section.hidden = false;
    });
    return section;
  }

  // -- which way a row or column is drawn --
  // A figure fitted to a slide may be drawn turned, a column as a row: commands and
  // panels go by what is on screen, and are written as the figure has it.
  const writtenKind = (group) => group?.layout?.kind || (group?.id === model()?.root ? "column" : "row");
  // The way its parts lie on screen, when there are two to tell by.
  // Each part beside the one before it, or under it: a column whose lines are set off to
  // one side is still a column, and a row folded onto two lines still a row.
  function shownKind(group) {
    if (!group || !["row", "column"].includes(writtenKind(group))) return null;
    const boxes = new Map();
    const drawn = (group.children || []).map((child) => boxOf(child, boxes)).filter(Boolean);
    let beside = 0, under = 0;
    for (let at = 1; at < drawn.length; at += 1) {
      const [a, b] = [drawn[at - 1], drawn[at]];
      const apart = { x: Math.max(a.left, b.left) - Math.min(a.right, b.right), y: Math.max(a.top, b.top) - Math.min(a.bottom, b.bottom) };
      if (apart.x > apart.y) beside += 1; else under += 1;
    }
    if (beside !== under) return beside > under ? "row" : "column";
    const middles = drawn.map(centre);
    if (middles.length < 2) return null;
    const across = Math.max(...middles.map((at) => at.x)) - Math.min(...middles.map((at) => at.x));
    const down = Math.max(...middles.map((at) => at.y)) - Math.min(...middles.map((at) => at.y));
    return across > down ? "row" : "column";
  }
  const drawnKind = (group) => shownKind(group) || writtenKind(group);
  const turned = (group) => Boolean(shownKind(group)) && shownKind(group) !== writtenKind(group);
  // A part put on a line of its own `side` of the group `of`, as the figure is seen: one
  // drawn turned to fit the slide is first written as it is drawn, so the line goes where
  // it was asked for, under what is on screen -- one step to undo.
  // Let go from a drag, the groups are as they were drawn when it began (`drawn`): the part
  // let go is still where it was let go, which would make its column look like a row.
  // (`merge` and `label`: one step with what was done before it, a folded figure written as seen.)
  function ownLine(id, of, side, { failed = null, drawn = null, merge: joined = null, label: told = null } = {}) {
    const shown = (group) => (drawn ? drawn.groups.find((each) => each.id === group.id)?.layout?.kind || null : shownKind(group));
    const turnedGroups = joined ? [] : (model()?.groups || []).filter((group) => shown(group) && shown(group) !== writtenKind(group));
    const move = (merge = null) => act({ do: "move", id, line: side, of }, { merge: merge || joined, label: told, failed });
    if (!turnedGroups.length) { move(); return; }
    // One step, said as the move it is: its groups written as drawn are part of it.
    const merge = `as-drawn:${id}:${Date.now()}`, label = said({ do: "move", id, line: side, of });
    const steps = ["row", "column"].map((kind) => ({ kind, targets: turnedGroups.filter((group) => shown(group) === kind).map((group) => ({ type: "group", id: group.id })) }))
      .filter((step) => step.targets.length);
    const next = (index) => {
      if (index >= steps.length) { move(merge); return; }
      act({ do: "update", targets: steps[index].targets, values: { "layout.kind": steps[index].kind } }, { merge, label, select: false, failed, then: () => next(index + 1) });
    };
    next(0);
  }

  // A part in a row put on a line of its own, under (or over) that row and centred on
  // it: a result drawn under the steps it compares. (Dragged out beside a figure laid out
  // in a column, a part takes a column of its own.)
  function ownLineSection(id) {
    const holder = parentOf(id);
    if (!holder || drawnKind(holder) !== "row" || !(holder.children || []).some((child) => child !== id)) return null;
    return h("div.section", {}, h("div.section-title", {}, "Move to Own Row"),
      h("div.row", {}, [["below", "Below", "down"], ["above", "Above", "up"]].map(([side, label, glyphName]) =>
        ui.button(label, () => ownLine(id, holder.id, side),
          { small: true, icon: glyphName, title: `Move to a new row ${side}, centred on this one` }))));
  }

  function groupPanel(group) {
    const isRoot = group.id === model().root;
    const count = (group.children || []).length;
    return [
      h("div.section.insp-top", {}, isRoot ? null : crumbs(group.id),
        h("div.insp-row", {},
          titleBlock(glyph(["row", "column"].includes(writtenKind(group)) ? writtenKind(group) : groupGlyph(group)), isRoot ? "Layout" : group.role === "module" ? "Module" : "Group",
            // As its Layout pop-up says it: written so (the note under it says how it is drawn).
            `${counted(count, "shape")} · ${titled(writtenKind(group) || "column")}`),
          isRoot ? null : h("div.insp-actions", {}, headActions(group.id))),
        isRoot ? null : ui.button("Ungroup", () => act({ do: "ungroup", id: group.id }), { small: true, title: "Remove the group and keep its shapes" })),
      isRoot || group.implied ? null : colourSection([{ type: "group", id: group.id, item: group }]),
      h("div.section", {},
        turned(group) ? h("div.hint-line.turned", {}, icon("info"), `Drawn as a ${drawnKind(group)} to fit the slide; written as a ${writtenKind(group)}.`) : null,
        // The whole figure's layout is drawn with no frame of its own: no Frame to choose.
        fields(isRoot ? catalog.group_fields.filter((field) => field.key !== "role") : catalog.group_fields, group,
          (values, merge, hold) => update({ type: "group", id: group.id }, values, merge, hold), `group:${group.id}`)),
      h("div.section", {}, h("div.section-title", {}, "Contents", h("span.count", {}, count)),
        h("div.line-list", {}, (group.children || []).map((child, index) => h("div.line-row", {},
          h("button.link", { type: "button", onclick: () => select([child]) }, nodeOf(child) ? glyph(nodeOf(child).kind || "block") : glyph(groupGlyph(groupOf(child) || {})), nameOf(child)),
          ui.button("", () => act({ do: "step", id: child, delta: -1 }, { select: false }), { kind: "ghost", small: true, icon: "up", title: "Move Up", disabled: index === 0 }),
          ui.button("", () => act({ do: "step", id: child, delta: 1 }, { select: false }), { kind: "ghost", small: true, icon: "down", title: "Move Down", disabled: index === count - 1 })))),
        ui.button("Add Shape Inside…", (event) => { const anchor = event.currentTarget; select([group.id]); addPalette(anchor, { inside: group.id }); }, { small: true, icon: "plus" })),
      isRoot ? null : ownLineSection(group.id),
      isRoot || group.implied ? null : h("div.section", {}, advanced(idField(group.id, "group"))),
    ];
  }

  // -- lines: their ends, their colour, and lines joined into one --
  // Shapes as a line's panel names them: by their words, those with the same words told
  // apart by the module (or other named group) they are in, then by their order there as
  // read -- "MLP — Cryo-EM module, 2nd".
  const ordinal = (n) => {
    const last = n % 10, teen = n % 100 >= 11 && n % 100 <= 13;
    return `${n}${teen ? "th" : last === 1 ? "st" : last === 2 ? "nd" : last === 3 ? "rd" : "th"}`;
  };
  function namesTold() {
    const nodes = model()?.nodes || [];
    const told = new Map(nodes.map((node) => [node.id, nameOf(node.id)]));
    const alike = new Map();
    for (const node of nodes) alike.set(told.get(node.id), [...(alike.get(told.get(node.id)) || []), node.id]);
    // The nearest group with a name of its own (a module's title) that holds it.
    const home = (id) => {
      for (let at = parentOf(id); at && at.id !== model().root; at = parentOf(at.id)) if (plain(at.label)) return at.id;
      return null;
    };
    const boxes = new Map();
    const read = (a, b) => {
      const one = boxOf(a, boxes), two = boxOf(b, boxes);
      if (!one || !two) return 0;
      // Side by side (overlapping down the page), left first; else the higher first.
      const level = Math.min(one.bottom, two.bottom) - Math.max(one.top, two.top) > 0;
      return level ? one.left - two.left : one.top - two.top;
    };
    for (const [name, ids] of alike) {
      if (ids.length < 2) continue;
      const homes = new Map();
      for (const id of ids) homes.set(home(id), [...(homes.get(home(id)) || []), id]);
      for (const [where, same] of homes) {
        same.sort(read);
        same.forEach((id, index) => {
          // (The one alone outside every named group is told apart by the others' names.)
          const apart = [where ? nameOf(where) : null, same.length > 1 ? ordinal(index + 1) : null].filter(Boolean);
          if (apart.length) told.set(id, `${name} — ${apart.join(", ")}`);
        });
      }
    }
    return told;
  }
  // A line's end, said: its shape's name, and its port's after it ("Add LN — 2nd · Skip").
  function endSaid(ref, told = namesTold()) {
    const node = nodeOfRef(ref);
    const port = String(ref) !== node ? ` · ${titled(String(ref).slice(node.length + 1))}` : "";
    return `${told.get(node) || nameOf(node)}${port}`;
  }
  // Every end a line may have: each shape, then each of its ports.
  function endOptions(told = namesTold()) {
    return model().nodes.flatMap((node) => [{ value: node.id, label: told.get(node.id) },
      ...(node.ports || []).map((port) => ({ value: `${node.id}.${port}`, label: `${told.get(node.id)} · ${titled(port)}` }))]);
  }
  // Which side of its shape a line's end meets it on, as its panel says it: one it was
  // asked to (``depart``, ``arrive``), or the side of a port that keeps to one (a
  // vector's North) named as its end; else where the figure puts it.
  const SIDES = [["", "Automatic"], ["north", "Top"], ["east", "Right"], ["south", "Bottom"], ["west", "Left"]];
  function sideOfEnd(edge, key) {
    const asked = edge[key === "from" ? "depart" : "arrive"];
    if (asked) return asked;
    const ref = String(edge[key]), node = nodeOfRef(ref);
    return ref !== node ? model().sides?.[node]?.[ref.slice(node.length + 1)] || "" : "";
  }
  // A joined line's end's side: its own, or (a merge's, where it meets its shape) its `via`,
  // from before ends had sides.
  const hubOf = (net) => (net.kind === "merge" ? net.targets : net.sources)?.[0];
  const netSideOf = (net, ref) => net.sides?.[ref] || (net.kind === "merge" && ref === hubOf(net) ? net.via : "") || "";
  // One end of line `id` meeting its shape on `side` ("" where the figure puts it) -- a line's
  // end `key` ("from", "to"), a joined line's by its ref -- or, a line's, meeting `shape`,
  // another shape, there: one step, the line chosen still. Whether anything was to change.
  function endTo(id, key, side, { shape = null, failed = null } = {}) {
    const edge = edgeOf(id), net = netOf(id);
    if (edge) {
      const asked = key === "from" ? "depart" : "arrive", other = key === "from" ? "to" : "from";
      const moved = shape && shape !== nodeOfRef(edge[key]);
      if (!moved && sideOfEnd(edge, key) === side) return false;
      const ends = moved ? (key === "from" ? [shape, nodeOfRef(edge.to)] : [nodeOfRef(edge.from), shape]) : [nodeOfRef(edge.from), nodeOfRef(edge.to)];
      const label = moved ? `Reconnect Line to ${inQuotes(nameOf(shape))}` : null;
      act({ do: "update", target: { type: "edge", id }, values: { ...(moved ? { [key]: shape } : {}), [asked]: side || null } }, { select: false, label, failed, then: (result) => {
        // (Ended at another shape, or at a port of that side, it is chosen again by its shapes.)
        const now = edgeOf(result?.select?.[0]) || edgeOf(id) || model().edges.find((item) => nodeOfRef(item.from) === ends[0] && nodeOfRef(item.to) === ends[1] && (moved || item[other] === edge[other]));
        select(now ? [now.id] : [], { reveal: false });
      } });
      return true;
    }
    if (!net || netSideOf(net, key) === side) return false;
    const merge = net.kind === "merge", hub = hubOf(net);
    act({ do: "update", target: { type: "net", id }, values: { [`side:${key}`]: side || null, ...(merge && key === hub && net.via ? { via: null } : {}) } },
      { select: false, failed, label: key === hub ? (merge ? "Change Where the Line Arrives" : "Change Where the Line Leaves") : `Change Where ${inQuotes(endSaid(key))} Meets the Line` });
    return true;
  }
  // What each chosen line's ends are: the shapes on its two sides.
  function lineEnds(id) {
    const edge = edgeOf(id), net = netOf(id);
    if (edge) return { from: [edge.from], to: [edge.to] };
    return net ? { from: net.sources || [], to: net.targets || [] } : null;
  }
  // Lines that can be one: into the same shape, or out of the same one.
  function joinable(ids) {
    const ends = ids.map(lineEnds);
    if (ids.length < 2 || ends.some((end) => !end)) return false;
    const one = (side) => new Set(ends.flatMap((end) => end[side].map(nodeOfRef))).size === 1;
    const many = (side) => new Set(ends.flatMap((end) => end[side].map(String))).size > 1;
    return (one("to") && many("from")) || (one("from") && many("to"));
  }
  // Joined, lines have one label: those saying different things are joined with the words
  // the person keeps, asked -- none of them dropped unsaid.
  function joinLines(ids) {
    const labels = [];
    for (const id of ids) {
      const label = (edgeOf(id) || netOf(id))?.label;
      if (label && !labels.some((each) => JSON.stringify(each) === JSON.stringify(label))) labels.push(label);
    }
    if (labels.length < 2) { act({ do: "join", ids }); return; }
    const words = labels.map((label) => { const text = plain(label); return inQuotes(text.length > 28 ? `${text.slice(0, 27).trimEnd()}…` : text); });
    const keep = (index) => ({ label: `Keep ${words[index]}`, kind: index ? "" : "primary", run: () => act({ do: "join", ids, label: labels[index] }) });
    dialog({ title: "Join lines with different labels?",
      body: [h("p.export-hint", {}, `These lines say ${words.slice(0, -1).join(", ")} and ${words.at(-1)}, but a joined line has one label. Which should it keep?`)],
      actions: [{ label: "Cancel", cancel: true }, ...labels.slice(1).map((_, index) => keep(index + 1)), keep(0)] });
  }
  const separateLine = (id, end = null) => act(end ? { do: "separate", id, end } : { do: "separate", id });

  // A line's colour, and how it is drawn: the theme's line (Default), its grey (Neutral),
  // or one of its tones -- the colours shapes are given -- each chip the colour the line
  // will be. Several lines chosen are coloured together, in one step.
  function lineLookSection(targets) {
    const tones = host.tones?.();
    const scope = targets.map((target) => target.id).join(",");
    const toneOf = (line) => {
      const tone = line?.tone;
      if (tone === undefined || tone === null || tone === "") return null;
      return /^\d+$/.test(String(tone)) || String(tone) === "neutral" ? String(tone) : tones?.used?.[tone] !== undefined ? String(tones.used[tone]) : `named:${tone}`;
    };
    const shared = targets.map((target) => toneOf(target.item));
    const mixed = !shared.every((tone) => tone === shared[0]);
    const seen = new Set();
    const colours = (tones?.colours || []).map((colour, index) => ({ value: String(index + 1), colour: colour.stroke || painted(colour), title: index ? `Accent ${index + 1}` : "Accent" }))
      .filter((item) => item.value === shared[0] || !seen.has(String(item.colour).toLowerCase()) && seen.add(String(item.colour).toLowerCase()));
    const neutral = tones?.neutral ? [{ value: "neutral", colour: tones.neutral.stroke, title: "Neutral" }] : [];
    const chips = ui.swatches({ value: mixed ? "mixed" : shared[0], noneTitle: "Default", colours: [...neutral, ...colours],
      onChange: (value) => act({ do: "update", targets: targets.map(({ type, id }) => ({ type, id })), values: { tone: value } }, { merge: `colour:line:tone:${scope}`, select: false }) });
    const styles = targets.map((target) => target.item.line || "solid");
    const style = ui.segmented({ value: styles.every((value) => value === styles[0]) ? styles[0] : null, key: `line-style:${scope}`,
      options: [["solid", "Solid"], ["dashed", "Dashed"], ["dotted", "Dotted"]].map(([value, label]) => ({ value, label })),
      onChange: (value) => act({ do: "update", targets: targets.map(({ type, id }) => ({ type, id })), values: { line: value === "solid" ? null : value } }, { select: false }) });
    return h("div.section", {}, h("div.section-title", {}, "Colour"), ui.field("Theme", chips, mixed ? { hint: "Mixed" } : {}),
      ui.field("Dash", style));
  }

  function edgePanel(edge) {
    // Its ends by the shapes' names (and ports'), as they are seen -- shapes with the same
    // words told apart; their IDs are the file's.
    const told = namesTold();
    const options = endOptions(told);
    // An end at a shape the figure has none of (mistyped, or deleted): said, and its field
    // marked -- the one to choose a shape in.
    const lost = ["to", "from"].filter((key) => !nodeOf(nodeOfRef(edge[key])));
    const end = (key) => {
      const known = options.some((option) => option.value === edge[key]);
      return ui.select({ value: edge[key], key: `edge:${edge.id}:${key}`, options: known ? options : [{ value: edge[key], label: lost.includes(key) ? `\u201c${edge[key]}\u201d (no such shape)` : edge[key] }, ...options], onChange: (value) => {
        if (value === edge[key]) return;
        // The line, named by its ends, is chosen again by them.
        const other = key === "from" ? "to" : "from";
        act({ do: "update", target: { type: "edge", id: edge.id }, values: { [key]: value } }, { select: false, then: () => {
          const now = model().edges.find((item) => item[key] === value && item[other] === edge[other]);
          select(now ? [now.id] : [], { reveal: false });
        } });
      } });
    };
    // Where on its shape each end meets it: a side asked for, or wherever the figure puts it.
    const side = (key) => ui.select({ value: sideOfEnd(edge, key), key: `edge:${edge.id}:${key}:side`, options: SIDES.map(([value, label]) => ({ value, label })),
      onChange: (value) => endTo(edge.id, key, value || "") });
    // Joined with the other lines into (or out of) the same shape, if there are any.
    return [
      h("div.section.insp-top", {}, host.crumbs ? h("div.crumbs", {}, host.crumbs()) : null,
        h("div.insp-row", {}, titleBlock(glyph("edge"), "Line", lost.length ? nameOf(edge.id) : null, `${endSaid(edge.from, told)} → ${endSaid(edge.to, told)}`),
          h("div.insp-actions", {}, ui.button("", () => remove([edge.id]), { kind: "ghost", small: true, icon: "trash", title: "Delete (⌫)" })))),
      lost.length ? h("div.section", {}, h("div.field-problem.warning", {}, icon("warning"), h("span", {},
        `There is no shape \u201c${edge[lost[0]]}\u201d for it to ${lost[0] === "to" ? "go to" : "start from"}: choose one from ${lost[0] === "to" ? "To" : "From"} below.`))) : null,
      // From and To across the panel, as every pop-up is, the shapes' names read whole; the
      // side each meets its shape on under it.
      h("div.section", {}, ...["from", "to"].flatMap((key) => {
        const field = ui.field(key === "to" ? "To" : "From", end(key));
        if (lost.includes(key)) field.classList.add("wanted");
        return [field, lost.includes(key) ? null : ui.field("Side", side(key), { hint: key === "from" ? "Where it leaves its shape" : "Where it meets its shape" })];
      }),
        fields(edgeFields(edge).filter((field) => field.key !== "line"), edge, (values, merge, hold) => update({ type: "edge", id: edge.id }, values, merge, hold), `edge:${edge.id}`)),
      lineLookSection([{ type: "edge", id: edge.id, item: edge }]),
    ];
  }

  function netPanel(net) {
    const told = namesTold();
    const merge = net.kind === "merge";
    const hub = (merge ? net.targets : net.sources)?.[0];
    const branches = (merge ? net.sources : net.targets) || [];
    const write = (values, merging, hold) => update({ type: "net", id: net.id }, values, merging, hold);
    // One more shape on its branching side: any not on it yet.
    const taken = new Set([...branches.map(nodeOfRef), nodeOfRef(hub)]);
    const more = ui.button(merge ? "Add a Line From…" : "Add a Line To…", (event) => netEnds(event.currentTarget, net, taken, told),
      { small: true, icon: "plus", title: "Choose a shape, or click it on the drawing" });
    // Where on its shape each end meets it -- a skip line leaving its block's foot and
    // coming into the next one's head, down one straight trunk -- as a line's ends do.
    // (A merge's own side for where it meets its shape -- its `via`, from before ends had
    // sides -- is shown as its shape's end's, and given way to by it.)
    const sideOf = (ref) => netSideOf(net, ref);
    const sideSaid = (value) => SIDES.find(([side]) => side === value)?.[1] || "Automatic";
    const setSide = (ref, value) => endTo(net.id, ref, value || "");
    const SIDE_ICONS = { "": "more", north: "up", east: "right", south: "down", west: "left" };
    const branchSide = (ref) => ui.select({ value: sideOf(ref), icons: true, title: `Side of ${endSaid(ref, told)}`, key: `net:${net.id}:side:${ref}`,
      options: SIDES.map(([value, label]) => ({ value, label, icon: SIDE_ICONS[value] })), onChange: (value) => setSide(ref, value) });
    // The branch drawn straight into the shape the others join it at, its words above it.
    const trunk = merge && branches.length > 1 ? ui.field("Trunk", ui.select({ value: String(branches[0]), key: `net:${net.id}:trunk`,
      options: branches.map((ref) => ({ value: String(ref), label: endSaid(ref, told) })),
      onChange: (value) => act({ do: "update", target: { type: "net", id: net.id }, values: { trunk: value } },
        { select: false, label: `Make ${inQuotes(endSaid(value, told))} the Trunk` }) }),
    { hint: `Runs straight into ${endSaid(hub, told)}; the others join it, and its words go above it` }) : null;
    return [
      h("div.section.insp-top", {}, host.crumbs ? h("div.crumbs", {}, host.crumbs()) : null,
        h("div.insp-row", {}, titleBlock(glyph("net"), "Joined Line", merge ? `${branches.length} lines into ${endSaid(hub, told)}` : `${endSaid(hub, told)} to ${branches.length} shapes`),
          h("div.insp-actions", {}, ui.button("", () => remove([net.id]), { kind: "ghost", small: true, icon: "trash", title: "Delete (⌫)" })))),
      h("div.section", {}, ui.field(merge ? "To" : "From", h("div.fixed-end", {}, endSaid(hub, told))),
        ui.field("Side", ui.select({ value: sideOf(hub), key: `net:${net.id}:side:${hub}`, options: SIDES.map(([value, label]) => ({ value, label })), onChange: (value) => setSide(hub, value) }),
          { hint: merge ? "Where it meets its shape" : "Where it leaves its shape" }),
        h("div.section-title", {}, merge ? "From" : "To", h("span.count", {}, branches.length)),
        h("div.line-list", {}, branches.map((ref) => h("div.line-row", {},
          h("button.link", { type: "button", onclick: () => select([nodeOfRef(ref)]) }, endSaid(ref, told),
            sideOf(ref) ? h("span.muted", {}, ` · ${sideSaid(sideOf(ref))}`) : null),
          branchSide(ref),
          // Taken out, it is a line of its own again (and with two left, so is the rest).
          ui.button("", () => separateLine(net.id, ref), { kind: "ghost", small: true, icon: "close", title: "Make It a Line of Its Own" })))),
        more, trunk),
      h("div.section", {}, fields((catalog.net_fields || [catalog.edge_fields[0]]).filter((field) => field.key !== "line" && field.key !== "via"), net, write, `net:${net.id}`)),
      lineLookSection([{ type: "net", id: net.id, item: net }]),
      h("div.section", {}, h("div.row", {}, ui.button("Separate Lines", () => separateLine(net.id), { small: true, title: "Make each branch a line of its own again" }))),
    ];
  }

  // One more shape on a joined line's branching side: from a short list of the shapes, by
  // name, searched as it is typed -- a shape's own ports (an attention's Q, K and V; a vector's
  // top and bottom) beside its name, not every shape's every port -- or clicked on the drawing
  // while the list is open (as a line is drawn: Esc stops it).
  const PLAIN_PORTS = new Set(["input", "output"]);
  function netEnds(anchor, net, taken, told) {
    const search = ui.input({ placeholder: "Search shapes" });
    const list = h("div.net-ends.scroll-thin");
    const add = (value) => { closeMenu(); state.connecting = null; host.changed(); act({ do: "join", ids: [net.id], add: value }); };
    const render = () => {
      const query = search.value.trim().toLowerCase();
      const rows = (model()?.nodes || []).filter((node) => !taken.has(node.id) && (!query || String(told.get(node.id) || nameOf(node.id)).toLowerCase().includes(query)))
        .map((node) => h("div.net-end", {},
          h("button.net-end-name", { type: "button", title: `Join ${told.get(node.id) || nameOf(node.id)}`, onclick: () => add(node.id) }, glyph(node.kind || "block"), h("span", {}, told.get(node.id) || nameOf(node.id))),
          ...(node.ports || []).filter((port) => !PLAIN_PORTS.has(port)).map((port) => h("button.net-end-port", { type: "button", title: `${told.get(node.id) || nameOf(node.id)} · ${titled(port)}`,
            onclick: () => add(`${node.id}.${port}`) }, titled(port)))));
      clear(list, rows.length ? rows : h("div.empty", {}, "No matching shapes"));
    };
    search.addEventListener("input", render);
    search.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); list.querySelector(".net-end-name")?.click(); } });
    render();
    const node = popover(anchor, h("div.net-pick", {}, search, h("div.add-where", {}, icon("info"), h("span", {}, "Or click the shape on the drawing")), list), { className: "net-menu" });
    // Meanwhile, a shape clicked on the drawing is joined -- until the list goes another way
    // than by that click (Esc, a click elsewhere).
    state.connecting = { add: net.id, source: null };
    host.changed();
    new MutationObserver((_, watch) => {
      if (node.isConnected) return;
      watch.disconnect();
      const onDrawing = pressed && Date.now() - pressed.at < 1000 && host.overlay?.contains(pressed.target);
      if (!onDrawing && state.connecting?.add === net.id) { state.connecting = null; host.changed(); }
    }).observe(document.body, { childList: true, subtree: true });
    setTimeout(() => search.focus(), 20);
  }

  function figurePanel() {
    const figure = model();
    const counts = `${counted(figure.nodes.length, "shape")} · ${counted(figure.edges.length + figure.nets.length, "line")}`;
    return [
      // Named as its file is, where it has one of its own.
      h("div.section.insp-top", {}, titleBlock(icon("figure"), host.name?.() || "Figure", counts)),
      h("div.section", {}, fields(catalog.figure_fields, { figure: figure.figure }, (values, merge, hold) => update({ type: "figure" }, values, merge, hold), "figure")),
    ];
  }


  function manyPanel(ids) {
    const gatherable = ids.every((id) => nodeOf(id) || (groupOf(id) && id !== model().root));
    const colourable = ids.flatMap((id) => nodeOf(id) ? [{ type: "node", id, item: nodeOf(id) }]
      : groupOf(id) && id !== model().root && !groupOf(id).implied ? [{ type: "group", id, item: groupOf(id) }] : []);
    // Lines alone: coloured together, and joined into one where they meet.
    const lines = ids.every(isLine) ? ids.map((id) => ({ type: edgeOf(id) ? "edge" : "net", id, item: edgeOf(id) || netOf(id) })) : null;
    if (lines) {
      const join = joinable(ids), told = namesTold();
      const called = (id) => (edgeOf(id) ? `${endSaid(edgeOf(id).from, told)} → ${endSaid(edgeOf(id).to, told)}` : nameOf(id));
      return [
        h("div.section.insp-top", {}, titleBlock(glyph("edge"), `${ids.length} Lines Selected`, ids.map(called).join("; "))),
        lineLookSection(lines),
        h("div.section", {}, h("div.row", {}, ui.button("Join Lines", () => joinLines(ids), { small: true, disabled: !join, title: "One line, with a trunk they share" }),
          ui.button("Delete", () => remove(ids), { small: true, icon: "trash", kind: "danger" }))),
      ];
    }
    return [
      h("div.section.insp-top", {}, titleBlock(icon("layout"), `${ids.length} ${pluralNoun(ids)} Selected`, ids.map(nameOf).join(", "))),
      colourable.length ? colourSection(colourable) : null,
      h("div.section", {}, h("div.section-title", {}, "Group Into"),
        h("div.gather-tiles", {}, catalog.groups.map((group) => h("button.add-tile", { type: "button", disabled: !gatherable, title: group.hint, onclick: () => gather(group) },
          glyph(group.kind), h("span", {}, group.title)))),
        gatherable ? null : h("div.hint-line", {}, "Lines can’t be grouped. Select shapes only."),
        h("div.row", {}, ui.button("Duplicate", () => duplicate(ids), { small: true, icon: "duplicate" }),
          ui.button("Delete", () => remove(ids), { small: true, icon: "trash", kind: "danger" }))),
    ];
  }

  // -- fields, from the catalogue --
  const valueAt = (item, key) => key.split(".").reduce((at, part) => (at == null ? undefined : at[part]), item);
  // -- colours: a part's tone (a colour of the theme's, shared by parts with the same
  // tone), or colours of its own, which win over the tone and the theme --

  const OWN = [["fill", "Fill"], ["stroke", "Outline"], ["label", "Text"]];
  const GROUP_OWN = { fill: "Background", stroke: "Border", label: "Title" };
  const TONE_NAMES = () => Object.values(parts).flatMap((part) => part.fields).find((field) => field.key === "properties.tone")?.options.filter((name) => !/^\d+$/.test(name)) || [];

  function colourSection(targets) {
    const nodes = targets.filter((target) => target.type === "node");
    const tones = host.tones?.();
    const scope = targets.map((target) => target.id).join(",");
    // One edit for every chosen thing; a colour dragged in the picker is one undo step.
    const paint = (type, values) => {
      const list = targets.filter((target) => target.type === type);
      if (list.length) act({ do: "update", targets: list.map(({ type: kind, id }) => ({ type: kind, id })), values },
        { merge: `colour:${type}:${Object.keys(values)[0]}:${scope}`, select: false });
    };
    const common = (read) => {
      const values = targets.map((target) => read(target) ?? null);
      return values.every((value) => value === values[0]) ? values[0] : undefined;
    };
    const toneOf = (node) => {
      const tone = node.properties?.tone;
      if (tone === undefined || tone === null || tone === "") return null;
      if (String(tone).toLowerCase() === "neutral") return "neutral";
      return /^\d+$/.test(String(tone)) ? String(tone) : tones?.used?.[tone] !== undefined ? String(tones.used[tone]) : `named:${tone}`;
    };
    // (Shapes of different colours chosen together: no colour is theirs -- none is marked.)
    const shared = common((target) => target.type === "node" ? toneOf(target.item) : null);
    const mixed = shared === undefined;
    const toneNow = mixed ? "mixed" : shared ?? null;
    // A palette of five fills eight tones by going round again: each colour is offered once
    // (by its first tone), as the slide's colour rows offer it -- and the one in use, always.
    const seen = new Set();
    // Named as words' colours are named: Default, Accent, Accent 2...
    const offered = (tones?.colours || []).map((colour, index) => ({ value: String(index + 1), colour: painted(colour), title: index ? `Accent ${index + 1}` : "Accent" }))
      .filter((item) => item.value === toneNow || !seen.has(String(item.colour).toLowerCase()) && seen.add(String(item.colour).toLowerCase()));
    // The theme's grey, fill and outline both: a shape that is no colour, whatever its kind.
    const neutral = tones?.neutral ? [{ value: "neutral", colour: tones.neutral.fill, border: tones.neutral.stroke, title: "Neutral" }] : [];
    const chips = nodes.length && offered.length ? ui.field("Theme", ui.swatches({
      value: toneNow, noneTitle: "Default",
      // Each tone as a filled chip in its strong colour, as a palette's colours are shown.
      colours: [...neutral, ...offered],
      onChange: (value) => paint("node", { "properties.tone": value }),
    }), mixed ? { hint: "Mixed" } : {}) : null;
    // A tone by name: parts that share one share its colour, whichever the theme gives it.
    // Sent as it is typed; the words in the field stay the person's while they type.
    const toneKey = `colour:${scope}:tone`;
    const named = nodes.length ? ui.field("Tone Name", ui.combo({
      value: typing(toneKey) ?? (() => { const tone = common((target) => target.type === "node" ? target.item.properties?.tone : null); return tone && !/^\d+$/.test(String(tone)) ? tone : ""; })(),
      options: TONE_NAMES(), key: toneKey, placeholder: "None",
      onChange: (value) => paint("node", { "properties.tone": value.trim() || null }),
    }), { hint: "Same name, same colour" }) : null;
    const own = h("div.own-colours", {}, OWN.map(([part, label]) => h("div.own-colour", {},
      ui.colour({
        title: label, key: `colour:${scope}:${part}`,
        value: common((target) => target.type === "node" ? target.item.properties?.[`paint-${part}`] : target.item.paint?.[part]),
        onChange: (value) => paced(`colour:${scope}:${part}`, () => { paint("node", { [`properties.paint-${part}`]: value }); paint("group", { [`paint.${part}`]: value }); }),
      }),
      h("span", {}, nodes.length ? label : GROUP_OWN[part]))));
    return h("div.section", {}, h("div.section-title", {}, "Colour"), chips, named,
      ui.field("Custom", own, { hint: "Overrides the tone and the theme" }));
  }


  function fields(list, item, write, scope) {
    const holds = (key, wanted) => {
      const value = valueAt(item, key) ?? list.find((f) => f.key === key)?.default;
      return Array.isArray(wanted) ? wanted.includes(value) : value === wanted;
    };
    const shown = list.filter((field) => !field.show || Object.entries(field.show).every(([key, wanted]) => holds(key, wanted)));
    write = keepingHidden(list, item, write, scope);
    // Fields few reach for are folded away under the rest -- open, if one of them is set.
    const more = shown.filter((field) => field.more);
    const set = more.some((field) => valueAt(item, field.key) !== undefined && valueAt(item, field.key) !== null && valueAt(item, field.key) !== "");
    return h("div.fields", {}, shown.filter((field) => !field.more).map((field) => fieldControl(field, item, write, scope)),
      more.length ? h("details.more", { open: set }, h("summary", {}, icon("chevron"), "More"),
        h("div.inner.fields", {}, more.map((field) => fieldControl(field, item, write, scope)))) : null);
  }

  // A choice that hides fields of its own (a line's Arrow its arrowheads, its Routing its bend,
  // a group's Layout its columns): the values they had, which the file drops with them, are
  // kept here -- and given back as the choice comes back, as Keynote keeps a line's ends.
  const hiddenValues = new Map();
  function keepingHidden(list, item, write, scope) {
    const shownBy = (field, values) => Object.entries(field.show).every(([key, wanted]) => {
      const value = (key in values ? values[key] : valueAt(item, key)) ?? list.find((each) => each.key === key)?.default;
      return Array.isArray(wanted) ? wanted.includes(value) : value === wanted;
    });
    const given = (value) => value !== undefined && value !== null && value !== "";
    return (values, ...rest) => {
      const next = { ...values };
      for (const field of list) {
        if (!field.show || field.key in values || !Object.keys(field.show).some((key) => key in values)) continue;
        const now = shownBy(field, {}), then = shownBy(field, values), had = valueAt(item, field.key), kept = `${scope}:${field.key}`;
        if (now && !then && given(had)) hiddenValues.set(kept, had);
        else if (!now && then && !given(had) && hiddenValues.has(kept)) next[field.key] = hiddenValues.get(kept);
      }
      return write(next, ...rest);
    };
  }
  let themeColours = [];
  function fieldControl(field, item, write, scope) {
    const key = `${scope}:${field.key}`;
    const waiting = typed.get(key);
    const value = waiting && field.key in waiting ? waiting[field.key] : valueAt(item, field.key);
    const set = (next) => write({ [field.key]: next }, key);
    // Words typed: one run from focusing the field to leaving it, however long its pauses.
    const type = (next) => write({ [field.key]: next }, key, true);
    const options = { hint: field.hint };
    switch (field.type) {
      case "markup": {
        // Return starts a new line, as on the drawing; ⌘Return is done: the words are kept,
        // and nothing is left chosen in the field, nor its format bar over the panel.
        // A shape's words, while it has none, say faintly what it is, as on the drawing.
        const placeholder = field.key === "label" && item?.id && nodeOf(item.id) ? hintOf(item) : "";
        const control = ui.markup({ value: typing(key) ?? words(value), rows: 1, key, placeholder, colours: labelColours(), emphasis: false, spelling: false, lines: true, onInput: type });
        control.area.addEventListener("keydown", (event) => {
          if (event.key !== "Enter" || !(event.metaKey || event.ctrlKey) || event.isComposing) return;
          event.preventDefault();
          event.stopPropagation();
          const end = control.area.value.length;
          control.area.setSelectionRange(end, end);
          control.area.blur();
        });
        // Left, a "\n" typed in it is the new line it means.
        control.area.addEventListener("blur", () => {
          const broken = typedBreaks(control.area.value);
          if (broken === control.area.value) return;
          control.area.value = broken;
          control.area.dispatchEvent(new Event("input", { bubbles: true }));
        });
        return ui.field(field.label, control, options);
      }
      case "text": {
        if (item?.kind !== "structure") return ui.field(field.label, ui.input({ value: typing(key) ?? value ?? "", key, onInput: type }), options);
        // A structure's selection is sent once typed, and said when it selects nothing.
        const control = typedField({ value, key, onCommit: set });
        const note = h("div.field-problem.warning", { hidden: true });
        settingsOf(item.id).then((settings) => {
          const said = settings?.selections?.[field.key];
          if (!said || drafts.has(key) || typing(key) !== null) return;
          clear(note, icon("warning"), h("span", {}, said));
          note.hidden = false;
          control.classList.add("invalid");
        });
        return ui.field(field.label, h("div.field-stack", {}, control, note), options);
      }
      case "length": {
        // Sent once it reads as a length, as typed. ↑ and ↓ from "Auto" go from the size the
        // shape is drawn at.
        const drawn = item?.id && nodeOf(item.id) && (field.key === "width" || field.key === "height") ? () => {
          const element = host.element?.(item.id);
          const box = element?.getBoundingClientRect(), scale = element?.getScreenCTM?.()?.a;
          return box?.width && scale ? (field.key === "width" ? box.width : box.height) / scale : null;
        } : null;
        return ui.field(field.label, typedField({ value, key, placeholder: "Auto", length: true, current: drawn, onCommit: set }), options);
      }
      case "code":
        // Letters of a sequence and the like, not code to indent: Tab goes on to the next field.
        return ui.field(field.label, ui.textarea({ value: typing(key) ?? value ?? "", rows: 2, mono: true, key, onInput: type }), options);
      case "view": {
        // A molecule turned, tilted, and framed a step at a click, as in a viewer.
        const at = (name, fallback) => Number(valueAt(item, `properties.${name}`) ?? fallback);
        const turn = (name, by) => {
          const next = ((((at(name, 0) + by) % 360) + 540) % 360) - 180;
          write({ [`properties.${name}`]: next || null }, null);
        };
        const zoom = (by) => {
          const next = Math.round(at("zoom", 1) * by * 100) / 100;
          write({ "properties.zoom": next === 1 ? null : next }, null);
        };
        const button = (glyphName, title, run) => ui.button("", run, { small: true, icon: glyphName, title });
        return ui.field(field.label, h("div.view-pad", {},
          button("left", "Rotate left 30°", () => turn("yaw", -30)),
          button("right", "Rotate right 30°", () => turn("yaw", 30)),
          button("up", "Tilt back 30°", () => turn("pitch", -30)),
          button("down", "Tilt forward 30°", () => turn("pitch", 30)),
          h("span.sep"),
          button("minus", "Zoom Out", () => zoom(1 / 1.25)),
          button("plus", "Zoom In", () => zoom(1.25)),
          h("span.sep"),
          button("refresh", "Reset rotation and zoom", () => write({ "properties.yaw": null, "properties.pitch": null, "properties.roll": null, "properties.zoom": null }, null))), options);
      }
      case "integer":
      case "number":
        return ui.field(field.label, typedField({ value, key, placeholder: field.default !== undefined ? String(field.default) : "Auto",
          number: { min: field.min, max: field.max, step: field.step ?? (field.type === "integer" ? 1 : undefined), integer: field.type === "integer", unit: field.unit },
          onCommit: set }), options);
      case "bool": {
        const on = value ?? field.default ?? false;
        // A switch's hint is said beside it: the label column is narrow.
        return ui.field(field.label, h("div.switch-row", { title: field.hint || "" },
          ui.toggle({ value: on, onChange: (next) => set(next === (field.default ?? false) ? null : next) })), { inline: true });
      }
      case "choice":
        // Left as it is by default, the choice reads in grey, as an empty field's placeholder does.
        // (Keyed, a problem with it leads to it: a plate's Wells.)
        return ui.field(field.label, ui.select({ value: value ?? field.default ?? "", unset: value === undefined || value === null, key,
          options: field.options.map((option) => ({ value: option, label: field.labels?.[option] ?? (option === "" ? "None" : titled(option)), icon: field.icons?.[option] })),
          onChange: (next) => {
            const typed = field.options.find((option) => String(option) === next);
            set(typed === field.default || typed === "" ? null : typed);
          } }), options);
      case "combo":
        // A font is chosen from the fonts, each shown in its face.
        if (/(^|\.)font$/.test(field.key)) return ui.field(field.label, ui.font({ value: value ?? "", options: field.options.map(String), placeholder: field.default || "Default", onChange: (next) => set(next || null) }), options);
        {
          // Its choices by name ("Double Column"), what is typed read back to them.
          const shown = (text) => field.labels?.[text] ?? text;
          const meant = (text) => Object.entries(field.labels || {}).find(([, label]) => label.toLowerCase() === String(text).trim().toLowerCase())?.[0] ?? text;
          // Left as it is by default, the default is what it says, in ink: emptied, it goes back.
          return ui.field(field.label, ui.combo({ value: shown(typing(key) ?? value ?? field.default ?? ""), options: field.options.map((option) => shown(String(option))), key,
            placeholder: shown(field.default ?? ""), onChange: (text) => set(String(text).trim() ? meant(text) : null) }), options);
        }
      case "palette": {
        const current = value ?? field.default;
        // The default palette is the theme's: its colours as the figure is drawn with it.
        if (current === field.default && host.tones?.()?.colours?.length) themeColours = host.tones().colours.map(painted);
        const colours = (name) => (name === field.default ? themeColours : field.colours?.[name]) || [];
        const strip = (name) => h("span.palette-strip", {}, colours(name).slice(0, 8).map((colour) => h("span", { style: { background: colour } })));
        const title = (name) => (name === field.default ? "Default" : name);
        const choose = (event) => popover(event.currentTarget, h("div.palette-choices", {},
          field.options.map((name) => h(`button.palette-choice${name === current ? ".on" : ""}`, { type: "button",
            onclick: () => { closeMenu(); set(name === field.default ? null : name); } }, strip(name), h("span", {}, title(name))))),
          { className: "palette-menu" });
        return ui.field(field.label, h("button.palette-pick", { type: "button", onclick: choose }, strip(current), h("span", {}, title(current)), icon("chevron")), options);
      }
      case "theme":
        // A host that can show themes by sight does; otherwise, their names.
        return ui.field(field.label, host.themeField ? host.themeField(value, set)
          : ui.combo({ value: typing(key) ?? value ?? "", options: field.options.map(String), key, placeholder: field.default ?? "", onChange: set }), options);
      case "pair": {
        const pair = Array.isArray(value) ? [...value] : ["", ""];
        const half = (index) => ui.input({ value: typing(`${key}:${index}`) ?? pair[index] ?? "", key: `${key}:${index}`, placeholder: field.labels?.[index], onInput: (text) => {
          pair[index] = text;
          set(pair.some((part) => part) ? pair.map((part) => part ?? "") : null);
        } });
        return ui.field(field.label, h("div.grid2", {}, half(0), half(1)), options);
      }
      case "file":
        return ui.field(field.label, h("div.row", {}, ui.input({ value: typing(key) ?? value ?? "", mono: true, key, onChange: set }),
          h("span.fixed", {}, ui.button("Choose…", async () => { const file = await host.chooseFile({ title: "Choose a File", types: field.types }); if (file) set(file); }, { small: true, icon: "folder" }))), options);
      case "records":
        return recordsControl(field, Array.isArray(value) ? value : [], set, key, valueAt(item, "properties.length"), item);
      case "molpalette":
        return ui.field(field.label, groupPalette(item, value, set), options);
      case "molsketch":
        return styleSections(field, item, write);
      default:
        return null;
    }
  }

  // -- words and numbers typed in a field, sent once they are whole --
  // A number is sent on Return, when the field is left, or after a pause: "3.5" is sent as
  // 3.5, not as 3 and then 3.5. Esc ends the typing as Return does, as in a Mac field. ↑
  // and ↓ (and the steppers beside it) go a step at a time, ⇧ ten. What is typed is never
  // changed while it is typed: a panel drawn again meanwhile shows it as it is, and it is
  // written out (a length's "pt", a number kept in range) only when the typing ends. Words
  // that don't read as a number or a length are kept, said under the field, and not sent.
  const drafts = new Map();
  const pending = new Map();
  const unread = new Set();
  const touched = new Set();
  const PAUSE = 700;
  // The words in the field with this key, if it is the one being typed in.
  function typing(key) {
    const at = document.activeElement;
    // (Drawn again for another's edit or an undo, it shows the figure's words: unless its own
    // are still on their way.)
    if (afresh && !typed.has(key)) return null;
    return key && at?.dataset?.key === key && typeof at.value === "string" ? at.value : null;
  }
  // A length as the file has it ("120pt", "4cm"): its number, and its unit (points if none).
  const LENGTH = /^(\d+(?:\.\d*)?|\.\d+)\s*(pt|mm|cm|in|px)?$/i;
  const lengthParts = (text) => { const found = LENGTH.exec(String(text ?? "").trim()); return found ? [String(Number(found[1])), (found[2] || "pt").toLowerCase()] : null; };
  function typedField({ value, key, placeholder = "", number = null, length = false, mono = false, say = true, current = null, onCommit }) {
    // A length shows its number, and its unit after it as every number field's is ("120 pt"):
    // a number typed is in that unit; another unit may be typed after it.
    let lengthUnit = (length && lengthParts(value)?.[1]) || "pt";
    const written = value === undefined || value === null ? "" : length && lengthParts(value) ? lengthParts(value)[0] : String(value);
    const shown = typing(key) ?? (drafts.has(key) ? drafts.get(key) : written);
    const input = ui.input({ value: shown, key, placeholder, mono });
    if (number || length) input.inputMode = "decimal";
    const read = (text) => {
      const clean = String(text ?? "").trim();
      if (length) {
        const found = LENGTH.exec(clean);
        return !clean ? null : found ? `${Number(found[1])}${(found[2] || lengthUnit).toLowerCase()}` : NaN;
      }
      if (!number) return clean || null;
      const bare = clean.replace(/\s*(Å|°|×|σ|px|pt|%)$/u, "").replace(",", ".");
      if (!bare) return null;
      const parsed = Number(bare);
      return Number.isFinite(parsed) ? parsed : NaN;
    };
    const within = (parsed) => parsed === null || typeof parsed === "string"
      || (!Number.isNaN(parsed) && (number.min === undefined || parsed >= number.min) && (number.max === undefined || parsed <= number.max));
    const why = length ? "Not saved: type a length, such as 120, 120pt or 4cm."
      : number?.integer ? "Not saved: type a whole number, such as 3." : "Not saved: type a number, such as 1.5.";
    const note = say && (number || length) ? h("div.field-problem", { hidden: true }, icon("warning"), h("span", {}, why)) : null;
    // Said once the typing ends (not at each key on the way to "12mm"), and gone once it reads.
    const said = (bad) => {
      input.classList.toggle("invalid", bad);
      if (!bad) unread.delete(key); else unread.add(key);
      if (note) note.hidden = !bad;
      if (!say) input.title = bad ? why : "";
    };
    if (unread.has(key) && Number.isNaN(read(shown))) said(true);
    let sent = read(value);
    const send = (parsed, text) => {
      clearTimeout(pending.get(key));
      pending.delete(key);
      if (drafts.get(key) === text) drafts.delete(key);
      if (parsed === sent) return;
      sent = parsed;
      onCommit(parsed);
    };
    const whole = (parsed) => (number?.integer && typeof parsed === "number" ? Math.round(parsed) : parsed);
    const finish = () => {
      touched.delete(key);
      let parsed = read(input.value);
      if (Number.isNaN(parsed)) { clearTimeout(pending.get(key)); pending.delete(key); said(true); return; }
      if (number && parsed !== null) {
        parsed = whole(parsed);
        if (number.min !== undefined) parsed = Math.max(number.min, parsed);
        if (number.max !== undefined) parsed = Math.min(number.max, parsed);
        if (read(input.value) !== parsed) input.value = String(parsed);
      }
      if (length && parsed !== null) { [input.value, lengthUnit] = lengthParts(parsed); showUnit(); }
      said(false);
      send(parsed, drafts.get(key));
    };
    // The unit after the digits, unless one is typed in with them.
    let unitMark = null;
    function showUnit() {
      if (!unitMark || !length) return;
      unitMark.textContent = lengthUnit;
      unitMark.hidden = /[a-z]/i.test(input.value);
    }
    const later = (parsed, text, wait) => {
      clearTimeout(pending.get(key));
      pending.set(key, setTimeout(() => send(parsed, text), wait));
    };
    const stepBy = (sign, big) => {
      // A length steps in its own unit (points, if it has none), one at a time; left to fit
      // its words ("Auto"), from the size it is drawn at, if that is known.
      if (length) {
        const found = LENGTH.exec(input.value.trim());
        const drawn = found ? null : current?.();
        if (!found && !Number.isFinite(drawn)) return;
        if (found?.[2]) lengthUnit = found[2].toLowerCase();
        const from = found ? Number(found[1]) : Math.round(drawn);
        const next = Math.max(0, Math.round((from + sign * (big ? 10 : 1)) * 1e6) / 1e6);
        input.value = String(next);
        showUnit();
        drafts.set(key, input.value);
        touched.add(key);
        said(false);
        later(`${next}${lengthUnit}`, input.value, 300);
        return;
      }
      // Left to its default, it steps from the default it says; with none said, from what is
      // in use, else from nothing -- never from the bottom of its range.
      const now = read(input.value);
      const placed = parseFloat(input.placeholder);
      const using = Number.isFinite(placed) ? placed : current?.();
      const from = typeof now === "number" && !Number.isNaN(now) ? now : Number.isFinite(using) ? using : Math.max(number.min ?? 0, 0);
      const by = (Number(number.step) || 1) * (big ? 10 : 1);
      let next = Math.round((from + sign * by) * 1e6) / 1e6;
      if (number.min !== undefined) next = Math.max(number.min, next);
      if (number.max !== undefined) next = Math.min(number.max, next);
      input.value = String(next);
      drafts.set(key, input.value);
      touched.add(key);
      said(false);
      later(next, input.value, 300);
    };
    input.addEventListener("input", () => {
      showUnit();
      drafts.set(key, input.value);
      touched.add(key);
      const parsed = read(input.value);
      if (Number.isNaN(parsed)) input.classList.add("invalid"); else said(false);
      clearTimeout(pending.get(key));
      pending.delete(key);
      if (within(parsed)) later(whole(parsed), input.value, PAUSE);
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); finish(); input.select(); }
      else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); finish(); input.blur(); }
      else if ((number || length) && (event.key === "ArrowUp" || event.key === "ArrowDown")) { event.preventDefault(); stepBy(event.key === "ArrowUp" ? 1 : -1, event.shiftKey); }
    });
    // Only leaving the field ends the typing: a field drawn again under the keys (which a
    // web view says is a blur) is still being typed in.
    input.addEventListener("blur", () => setTimeout(() => {
      if (typing(key) === null && (touched.has(key) || pending.has(key) || drafts.has(key))) finish();
    }, 0));
    if (!number && !length) return input;
    // Drawn as every number field in the studio is (ui.numberBox): digits to the right, the
    // unit after them, steppers at the end.
    const control = ui.numberBox(input, { unit: length ? lengthUnit : number?.unit, step: stepBy });
    control.classList.add("typed-number");
    unitMark = control.querySelector(".unit");
    showUnit();
    const node = note ? h("div.field-stack", {}, control, note) : control;
    node.input = input;
    return node;
  }

  // A colour dragged in the system's picker changes at every step: it is sent as it goes,
  // at most every tenth of a second, and its last colour always.
  const pacers = new Map();
  function paced(key, run) {
    if (!pacers.has(key)) pacers.set(key, throttled((next) => next(), 100));
    pacers.get(key)(run);
  }

  // -- a structure's mol-sketch settings --
  // What it is drawn with -- its look's settings, the figure's colours, and its own --
  // asked of mol-sketch once for each way it is set, so each setting shows what it is.
  const settingsAsked = new Map();
  function settingsOf(id) {
    const key = JSON.stringify([id, nodeOf(id)?.properties]);
    if (!settingsAsked.has(key)) {
      if (settingsAsked.size > 40) settingsAsked.clear();
      settingsAsked.set(key, host.run({ do: "structure-settings", id }, { merge: null }).then((result) => result?.settings || null).catch(() => null));
    }
    return settingsAsked.get(key);
  }
  const swatchStrip = (colours = []) => h("span.palette-strip", {}, colours.slice(0, 8).map((colour) => h("span", { style: { background: colour } })));

  // mol-sketch's group palettes, by sight: the colours residues and chains take in turn.
  function groupPalette(item, value, set) {
    const name = () => value || "Default";
    const button = h("button.palette-pick", { type: "button", disabled: true }, swatchStrip(), h("span", {}, name()), icon("chevron"));
    settingsOf(item.id).then((settings) => {
      const palettes = settings?.palettes || {};
      button.disabled = !Object.keys(palettes).length;
      button.replaceChildren(swatchStrip(palettes[value || settings?.style?.group_palette_name]), h("span", {}, name()), icon("chevron"));
      button.onclick = () => popover(button, h("div.palette-choices", {},
        h(`button.palette-choice${value ? "" : ".on"}`, { type: "button", onclick: () => { closeMenu(); set(null); } },
          swatchStrip(palettes[settings?.style?.group_palette_name] || []), h("span", {}, "Default")),
        Object.entries(palettes).map(([option, colours]) => h(`button.palette-choice${option === value ? ".on" : ""}`, { type: "button",
          onclick: () => { closeMenu(); set(option); } }, swatchStrip(colours), h("span", {}, option)))),
      { className: "palette-menu" });
    });
    return button;
  }

  // Every section of mol-sketch's style the studio offers, folded away; one holding
  // settings of the structure's own says how many. Each setting shows what the look
  // (and the figure) make it until it is given its own; emptied, it is the look's again.
  const openSections = new Set();
  function styleSections(field, item, write) {
    const own = {};
    const walk = (value, prefix) => {
      for (const [key, part] of Object.entries(value || {})) {
        if (part && typeof part === "object" && !Array.isArray(part)) walk(part, `${prefix}${key}.`);
        else own[`${prefix}${key}`] = part;
      }
    };
    walk(item.properties?.style, "");
    const fills = [];
    const look = h("span.hint", {}, "Loading…");
    const ownCount = Object.keys(own).length;
    // Chains and residues given colours of their own are drawn in them, over these.
    const coloured = (item.properties?.colors || []).some((row) => row?.group && row?.color);
    const sections = field.sections.map((section) => {
      const count = section.fields.filter((each) => own[each.key] !== undefined).length;
      const control = (each) => {
        const merge = `style:${item.id}:${each.key}`;
        const waiting = typed.get(merge);
        const shown = waiting && `properties.style.${each.key}` in waiting ? waiting[`properties.style.${each.key}`] ?? undefined : own[each.key];
        const send = (next) => write({ [`properties.style.${each.key}`]: next }, merge);
        return styleControl(each, shown, fills, each.type === "colour" ? (next) => paced(merge, () => send(next)) : send, merge);
      };
      // Colours as a row of wells; the rest two to a row, their hints on hover.
      const colours = section.fields.filter((each) => each.type === "colour");
      const rest = section.fields.filter((each) => each.type !== "colour");
      const details = h("details.more.mol-section", { open: openSections.has(section.title) },
        h("summary", {}, icon("chevron"), section.title, count ? h("span.count", {}, count) : null),
        h("div.inner", {},
          rest.length ? h("div.mol-grid", {}, rest.map(control)) : null,
          colours.length ? h("div.mol-colours", { title: coloured && colours.some((each) => each.key.startsWith("palette."))
            ? "Chains and residues given a colour under Colours are drawn in it; these colours show where none is given." : "" }, colours.map(control)) : null));
      details.addEventListener("toggle", () => { if (details.open) openSections.add(section.title); else openSections.delete(section.title); });
      // A section for one way of drawing (engraved ribbons) shows while it is drawn that way.
      if (section.show && !count) {
        details.hidden = true;
        fills.push((drawn) => { details.hidden = !Object.entries(section.show).every(([key, wanted]) => drawn[key] === wanted); });
      }
      return details;
    });
    settingsOf(item.id).then((settings) => {
      if (!settings || settings.problem && !settings.style) { look.textContent = "Rendering settings unavailable"; return; }
      look.textContent = settings.look ? `Look: ${titled(settings.look)}` : "";
      for (const fill of fills) fill(settings.style || {});
    });
    return h("div.mol-style", {},
      h("div.mol-style-head", {}, h("span.section-title", {}, field.label), look,
        ownCount ? ui.button("Reset All", () => write({ "properties.style": null }, null), { small: true, kind: "ghost", icon: "refresh" }) : null),
      sections);
  }

  // One setting: what the look gives it shows until it has its own.
  function styleControl(field, value, fills, set, key) {
    const said = (drawn) => (drawn === null || drawn === undefined ? "" : typeof drawn === "number" ? String(Math.round(drawn * 1000) / 1000) : String(drawn));
    const options = {};
    const titled = (node) => { if (field.hint) node.title = field.hint; node.classList.toggle("own", value !== undefined); return node; };
    switch (field.type) {
      case "choice": {
        const select = ui.select({ value: value ?? "", options: [{ value: "", label: "Default" }, ...field.options.map((option) => ({ value: option, label: choiceLabel(field, option), icon: field.icons?.[option] }))],
          onChange: (next) => set(next || null) });
        fills.push((drawn) => { const inherited = drawn[field.key]; select.relabel("", inherited === null || inherited === undefined || inherited === "" ? "Default" : `Default (${choiceLabel(field, said(inherited))})`); });
        return titled(ui.field(field.label, select, options));
      }
      case "bool": {
        const select = ui.select({ value: value === undefined ? "" : value ? "on" : "off", options: [{ value: "", label: "Default" }, { value: "on", label: "On" }, { value: "off", label: "Off" }],
          onChange: (next) => set(next === "" ? null : next === "on") });
        fills.push((drawn) => { select.relabel("", `Default (${drawn[field.key] ? "On" : "Off"})`); });
        return titled(ui.field(field.label, select, options));
      }
      case "integer":
      case "number": {
        const control = typedField({ value, key, onCommit: set,
          number: { min: field.min, max: field.max, step: field.step, integer: field.type === "integer", unit: field.unit } });
        // What it is drawn with, else what leaving it empty means ("Recommended").
        fills.push((drawn) => { control.input.placeholder = said(drawn[field.key]) || field.placeholder || ""; });
        return titled(ui.field(field.label, control, options));
      }
      case "colour": {
        const control = ui.colour({ value, title: field.label, onChange: set, key });
        // Unset, the well shows the look's colour, faintly.
        fills.push((drawn) => { if (value === undefined && /^#[0-9a-f]{6}$/i.test(drawn[field.key] || "")) control.querySelector(".colour-chip").style.background = drawn[field.key]; });
        return titled(h("div.mol-colour", {}, control, h("span", {}, field.label)));
      }
      default: {
        const input = typedField({ value, key, onCommit: set });
        fills.push((drawn) => { input.placeholder = said(drawn[field.key]) || field.placeholder || ""; });
        return titled(ui.field(field.label, input, options));
      }
    }
  }

  // A table of records: a plasmid's features, a plate's groups, a timeline's events, a
  // structure's colours (each chain from a menu of the molecule's, each colour in a well).
  const COLOURS = ["#e69f00", "#56b4e9", "#009e73", "#f0e442", "#0072b2", "#d55e00", "#cc79a7"];
  const RESIDUE = /^[A-Za-z]{1,3}-?\d+[A-Za-z]?(\.\w+)?$/;
  // Why a number typed into a row's Start or End was not taken (one ending before it
  // starts), said under the rows until one is.
  const refused = new Map();
  function recordsControl(field, value, set, key, length, item = null) {
    const rows = value.map((row) => ({ ...(row && typeof row === "object" ? row : {}) }));
    // A span's end is after its start (a protein's may be the same residue; a time's not).
    const timed = field.columns.find((column) => column.name === "end")?.type === "number";
    // What a part of a type is called until it is named: as a new row is ("Gene" for a coding
    // sequence), else the type's own name ("RBS", "Active Site").
    const typeWords = (type) => (!type ? "" : type === field.row?.type && field.row?.label ? field.row.label
      : type.length <= 3 ? type.toUpperCase() : titled(type.replaceAll("-", " ")));
    const backwards = (row, name, number) => {
      if ((name !== "start" && name !== "end") || typeof number !== "number") return null;
      const start = name === "start" ? number : row.start, end = name === "end" ? number : row.end;
      if (typeof start !== "number" || typeof end !== "number" || end > start || (end === start && !timed)) return null;
      return name === "end" ? `Not saved: End (${end}) must be after Start (${start}). Type a later End, or change Start first.`
        : `Not saved: Start (${start}) must be before End (${end}). Type an earlier Start, or change End first.`;
    };
    const write = () => set(rows.map((row) => Object.fromEntries(Object.entries(row).filter(([, v]) => v !== "" && v !== null && v !== undefined))));
    const chains = item?.kind === "structure" ? settingsOf(item.id).then((settings) => settings?.chains || []) : Promise.resolve([]);
    const warnings = h("div.records-warnings");
    const cell = (row, index, column) => {
      const cellKey = `${key}:${index}:${column.name}`;
      const current = row[column.name];
      const change = (next) => { row[column.name] = next; write(); };
      if (column.type === "choice") {
        // (A value the menu does not offer -- a synonym written in the file -- is offered too.)
        const offered = current && !column.options.includes(current) ? [...column.options, current] : column.options;
        return ui.select({ value: current ?? "", key: cellKey, options: offered.map((option) => ({ value: option, label: column.labels?.[option] ?? (option === "" ? "–" : option) })),
          onChange: (next) => {
            // A part's words that only said what it was ("Gene", "Domain") are no words of its
            // own: it goes wordless, its hint saying what it is now (never drawn).
            if (column.name === "type" && field.columns.some((other) => other.name === "label")
                && row.label && row.label === typeWords(current || field.row?.type)) delete row.label;
            // A span made a site (one residue) is at where it started, its Start and End gone;
            // a site made a span runs on from where it was.
            const point = (type) => (column.points || []).includes(type || field.row?.type);
            if (column.points && point(next) !== point(current)) {
              if (point(next)) {
                row.at ??= row.start ?? row.end;
                delete row.start;
                delete row.end;
              } else if (typeof row.at === "number") {
                const reach = typeof length === "number" ? Math.max(1, Math.round(length / 10)) : 10;
                row.start = row.at;
                row.end = typeof length === "number" ? Math.min(row.at + reach - 1, length) : row.at + reach - 1;
                delete row.at;
              }
            }
            change(next || null);
          } });
      }
      if (column.type === "integer" || column.type === "number") {
        // A cell has no room under it to say what is wrong: its tooltip does. A start after
        // its end (a span ending before it begins, which could not be drawn) is not taken,
        // and said under the rows.
        return typedField({ value: current, key: cellKey, say: false, number: { step: column.type === "integer" ? 1 : undefined, integer: column.type === "integer" },
          onCommit: (number) => {
            // A Start typed past its End (a new row's, Start typed first in tab order) is
            // taken, the End moved along with it: the span keeps its length (within the
            // protein's or plasmid's).
            if (column.name === "start" && typeof number === "number" && typeof row.end === "number" && backwards(row, "start", number)) {
              const span = Math.max(typeof row.start === "number" ? row.end - row.start : 0, timed ? 1 : 0);
              const end = typeof length === "number" ? Math.min(number + span, length) : number + span;
              if (!backwards({ ...row, end }, "start", number)) {
                row.end = end;
                refused.delete(key);
                change(number);
                // (Its End field shows where it went, should the keys be in it already: Tab.)
                const shown = document.querySelector(`[data-key="${CSS.escape(`${key}:${index}:end`)}"]`);
                if (shown && "value" in shown) shown.value = String(end);
                return;
              }
            }
            const problem = backwards(row, column.name, number);
            if (problem) { refused.set(key, `Row ${index + 1}: ${problem}`); host.changed(); return; }
            refused.delete(key);
            change(number);
          } });
      }
      // A row's words, while it has none, say faintly what it is ("Domain", "RBS").
      const hint = column.name === "label" && field.columns.some((other) => other.name === "type") ? typeWords(row.type || field.row?.type) : "";
      const input = ui.input({ value: typing(cellKey) ?? current ?? "", key: cellKey, placeholder: hint || column.hint || "", onInput: (text) => change(text) });
      if (column.type === "chain") {
        // One of the molecule's chains from the menu; a residue or the like typed.
        const pick = h("button.cell-pick", { type: "button", tabIndex: -1, title: "Choose a chain", onclick: async (event) => {
          const anchor = event.currentTarget;
          const found = await chains;
          menu(anchor, found.length ? found.map((chain) => ({ label: `Chain ${chain}`, run: () => { input.value = chain; change(chain); } }))
            : [{ label: "No chains found", disabled: true }]);
        } }, icon("chevron-down"));
        return h("div.cell.with-pick", {}, input, pick);
      }
      if (column.type === "colour") {
        // A well for a colour of one's own; a tone of the figure's typed by name.
        const hex = /^#[0-9a-f]{6}$/i.test(current || "") ? current : null;
        const well = h("input.cell-well", { type: "color", value: hex || "#888888", title: "Choose a colour", tabIndex: -1 });
        if (!hex) well.classList.add("unset");
        well.addEventListener("input", () => { well.classList.remove("unset"); input.value = well.value; paced(cellKey, () => change(well.value)); });
        const id = `opts-${Math.random().toString(36).slice(2)}`;
        input.setAttribute("list", id);
        return h("div.cell.with-well", {}, well, input, h("datalist", { id }, (column.options || []).map((option) => h("option", { value: option }))));
      }
      if (column.type !== "combo") return input;
      const id = `opts-${Math.random().toString(36).slice(2)}`;
      input.setAttribute("list", id);
      return h("div.cell", {}, input, h("datalist", { id }, column.options.map((option) => h("option", { value: option }))));
    };
    const width = (column) => (column.type === "integer" || column.type === "number" ? "minmax(52px, .7fr)"
      : column.type === "choice" ? "minmax(92px, 1.2fr)"
        : column.type === "colour" ? "minmax(96px, 1.3fr)"
          : column.name === "label" || column.name === "tips" ? "minmax(80px, 1.6fr)" : "minmax(56px, 1fr)");
    const template = `${field.columns.map(width).join(" ")} 24px`;
    const remove = (index) => ui.button("", () => { rows.splice(index, 1); write(); }, { kind: "ghost", small: true, icon: "close", title: "Delete Row" });
    // More columns than an inspector has room for side by side (a protein's features have
    // seven, its tracks five): each row is a card of its own, its cells under their names,
    // wrapped to fit.
    const table = field.columns.length > 4
      ? h("div.records-cards", {}, rows.map((row, index) => h("div.records-card", {},
        field.columns.map((column) => h(`div.records-cell${column.type === "choice" || column.name === "label" ? ".wide" : ""}`, {},
          h("span.records-head", { title: column.title || column.hint || "" }, column.label), cell(row, index, column))),
        remove(index))))
      : h("div.records-table", { style: { gridTemplateColumns: template } },
        field.columns.map((column) => h("span.records-head", { title: column.title || column.hint || "" }, column.label)), h("span.records-head"),
        rows.map((row, index) => [...field.columns.map((column) => cell(row, index, column)), remove(index)]));
    // A row naming a chain the molecule lacks is said on it: it colours nothing, the rest is drawn.
    const chainColumn = field.columns.findIndex((column) => column.type === "chain");
    if (chainColumn >= 0) {
      chains.then((found) => {
        if (!found.length) return;
        const name = fileLabel(item?.properties?.source || "") || "the structure";
        const said = [];
        rows.forEach((row, index) => {
          const group = String(row[field.columns[chainColumn].name] ?? "").trim();
          const busy = typing(`${key}:${index}:${field.columns[chainColumn].name}`) !== null;
          const input = table.querySelector(`[data-key="${CSS.escape(`${key}:${index}:${field.columns[chainColumn].name}`)}"]`);
          const wrong = group && !busy && !group.includes(":") && !RESIDUE.test(group) && !found.includes(group);
          input?.classList.toggle("invalid", Boolean(wrong));
          if (!group) said.push(`Row ${index + 1} names no chain yet: it colours nothing.`);
          else if (wrong) said.push(`Row ${index + 1}: ${name} has no chain “${group}”, so it colours nothing. Its chains are ${found.join(", ")}.`);
        });
        clear(warnings, said.map((text) => h("div.field-problem.warning", {}, icon("warning"), h("span", {}, text))));
      });
    }
    return h("div.field.records", {},
      h("label.label", { title: field.hint || "" }, field.label, h("span.hint", {}, `${rows.length}`)),
      h("div.records-scroll.scroll-thin", {}, table),
      refused.has(key) ? h("div.field-problem", {}, icon("warning"), h("span", {}, refused.get(key))) : null,
      warnings,
      ui.button("Add Row", async () => {
        // A new row starts as the catalogue says: "+N" is the last row's value and N more,
        // "@chain" a chain of the molecule's that no row names yet.
        const last = rows[rows.length - 1];
        const fresh = {};
        const stepOf = (value) => (typeof value === "string" && /^\+\d+(\.\d+)?$/.test(value) ? Number(value.slice(1)) : null);
        // A new span (a protein's domain, a plasmid's gene) starts after the last one ends and
        // runs a tenth of the whole -- never a span of nothing.
        const spans = stepOf(field.row?.start) !== null && stepOf(field.row?.end) !== null ? {} : null;
        if (spans && timed) {
          // On a time axis: from where the last span ends (else the first event), for a tenth of
          // the time its events and spans cover.
          const times = [...(item?.properties?.events || []).map((event) => event?.at), ...rows.flatMap((row) => [row.start, row.end])]
            .filter((time) => typeof time === "number");
          const extent = times.length ? Math.max(...times) - Math.min(...times) : 0;
          const reach = extent > 0 ? Number((extent / 10).toPrecision(1)) : stepOf(field.row.end) || 1;
          spans.start = rows.some((row) => typeof row.end === "number") ? Math.max(...rows.map((row) => row.end).filter((end) => typeof end === "number"))
            : times.length ? Math.min(...times) : 0;
          spans.end = spans.start + reach;
        } else if (spans) {
          const after = Math.max(0, ...rows.map((row) => Number(row.end ?? row.at ?? row.start) || 0));
          const reach = typeof length === "number" ? Math.max(1, Math.round(length / 10)) : stepOf(field.row.end);
          let begin = typeof length === "number" ? Math.min(after + 1, Math.max(1, length - reach + 1)) : after + 1;
          // On a molecule of known length: in the first stretch no feature covers that has room
          // for it (else the widest), never on top of one.
          if (typeof length === "number") {
            // (A site, at one residue, may lie in a domain: it takes no stretch.)
            const points = field.columns.find((column) => column.name === "type")?.points || [];
            const taken = rows.filter((row) => !points.includes(row.type || field.row?.type))
              .map((row) => [Number(row.start ?? row.at), Number(row.end ?? row.at ?? row.start)])
              .filter(([from, to]) => Number.isFinite(from) && Number.isFinite(to)).sort((a, b) => a[0] - b[0]);
            const free = [];
            let from = 1;
            for (const [start, end] of taken) { if (start > from) free.push([from, start - 1]); from = Math.max(from, end + 1); }
            if (from <= length) free.push([from, length]);
            const room = free.find(([a, b]) => b - a + 1 >= reach) || free.sort((x, y) => (y[1] - y[0]) - (x[1] - x[0]))[0];
            if (room) begin = room[0];
            spans.start = begin;
            spans.end = room ? Math.min(begin + reach - 1, room[1]) : Math.min(begin + reach - 1, length);
            // With none left, it is said: the new one lies over another until it is moved.
            if (room) refused.delete(key);
            else refused.set(key, `Row ${rows.length + 1}: no stretch of the protein is free, so it overlaps another feature. Type its Start and End.`);
          } else {
            spans.start = begin;
            spans.end = begin + reach - 1;
          }
        }
        for (const [name, start] of Object.entries(field.row || { label: "New" })) {
          if (spans && (name === "start" || name === "end")) { fresh[name] = spans[name]; continue; }
          // No sample words: a new part's words are its person's (its hint says what it is).
          if (name === "label" && field.columns.some((column) => column.name === "type")) continue;
          if (typeof start === "string" && /^\+\d+(\.\d+)?$/.test(start)) {
            const step = Number(start.slice(1));
            const next = typeof last?.[name] === "number" ? last[name] + step : typeof last?.at === "number" ? last.at + step : step;
            // Positions stay on the molecule: a new domain past the end is drawn at it.
            fresh[name] = typeof length === "number" ? Math.min(next, length) : next;
          } else if (start === "@chain") {
            const found = await chains;
            const named = new Set(rows.map((row) => String(row[name] ?? "")));
            fresh[name] = found.find((chain) => !named.has(chain)) ?? found[0] ?? "";
          } else if (typeof start === "string" && /^#[0-9a-f]{6}$/i.test(start)) {
            // A colour not taken yet, so each row is told apart.
            const taken = new Set(rows.map((row) => String(row[name] ?? "").toLowerCase()));
            fresh[name] = [start, ...COLOURS].find((colour) => !taken.has(colour.toLowerCase())) || start;
          } else if (start !== "") fresh[name] = start;
        }
        rows.push(fresh);
        write();
        // The new row's first field, ready to be typed in, once the panel is drawn again.
        const first = `${key}:${rows.length - 1}:${field.columns[0].name}`;
        const focus = (tries = 0) => {
          const control = document.querySelector(`[data-key="${CSS.escape(first)}"]`);
          if (control) { control.focus(); control.scrollIntoView?.({ block: "nearest" }); } else if (tries < 20) setTimeout(() => focus(tries + 1), 50);
        };
        setTimeout(focus, 0);
      }, { small: true, icon: "plus" }));
  }

  return {
    get model() { return state.model; },
    get selected() { return state.selected; },
    get connecting() { return state.connecting; },
    get inline() { return inline; },
    get dragging() { return Boolean(drag?.started); },
    // (Its shapes being edited, none chosen: a shape just deleted.)
    get inside() { return state.inside; },
    get justDragged() { return state.swallow; },
    setModel, select, act, update, idle, pointerdown, landing, land, settles,
    // (A part on its way, till it lands: a slide's frame round the figure waits for it.)
    busy: () => Boolean(adding) && Date.now() - adding < 6000,
    typeOf, nameOf, nodeOf, groupOf, edgeOf, netOf, parentOf, nodeOfRef, partOf,
    idAt, click, dblclick, marks, markViews, hint, key, panel, wantsRoom, turnable,
    addPalette, addPart, gather, groupMenu, canGroup, band, remove, duplicate, chooseAll, toggleConnect, clip, uncopied, paste, menuOf, revealProblem,
    openInline, placeInline, closeInline, typeSoon, takeBackWaiting, waitingLabel, putBackWaiting, takenLabel, heldEdits, takenEdits,
  };
}
