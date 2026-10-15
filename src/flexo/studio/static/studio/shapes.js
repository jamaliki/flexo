// Shapes drawn where they are put (flexo.freeform) -- a slide's `shapes` (flexo-talk), and
// those drawn over a figure (flexo.figure_shapes) -- edited where they are as Keynote's are.
// One editor, for whatever holds them: its `host` says where they are and how they are
// changed (see `shapeEditor`). Shape in the toolbar opens their kinds; one chosen is drawn by
// a drag on the page (a click makes it its usual size), a polyline by clicks, the pen by
// hand. A shape is chosen by a click (⇧ or ⌘ for one more, a band across the page for those
// it touches), moved by a drag (⇧ along one way, ⌥ a copy), sized by its handles (⇧ keeping
// its proportions, ⌥ about its middle), turned by the handle over it (⇧ by 15°), a line by
// its ends -- glued to a shape, an object of a slide or a part of a figure where one is let go
// on it, following it after -- and a curve by its middle; its own handles (a corner, a tail, a
// star's points) shape it. Each catches at the page's edges and middle, and the edges and
// middles of the other shapes and of what the page holds, a guide drawn where it does (⌘:
// none; with snapping off, none and no glue, ⌘ catching and gluing: snapping.js). The arrows
// nudge it (⇧: ten points); double-clicked, its words are typed in it.
// Everything moves on the page at once, drawn here (freeform.js) as the page will draw it;
// the page's own drawing takes its place as it comes. The pen draws a path point by point, a
// path's points are edited where it is (a double-click, Edit Points), any shape is made a path
// (Make Editable) and shapes are combined into one (pathtools.js, pathops.js). Moved, a shape
// also catches where it is as far from its neighbours as they are apart, each gap as wide
// marked; and those chosen are aligned and spaced as Inkscape's Align and Distribute does it
// (aligntools.js, aligning.js).

import { h, icon, ui, menu, popover, closeMenu, toast } from "/static/studio/studio.js";
import * as F from "/static/studio/freeform.js";
import * as I from "/static/studio/insets.js";
import * as Styles from "/static/studio/styles.js";
import * as P from "/static/studio/pathdata.js";
import * as O from "/static/studio/pathops.js";
import { pathTools } from "/static/studio/pathtools.js";
import { gradientFields } from "/static/studio/gradients.js";
import * as Snap from "/static/studio/snapping.js";
import * as Align from "/static/studio/aligning.js";
import { alignTools, nearer, drawSpacing } from "/static/studio/aligntools.js";

const SVG_NS = "http://www.w3.org/2000/svg";
function S(name, attributes = {}, ...children) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) if (value !== null && value !== undefined && value !== false) node.setAttribute(key, String(value));
  for (const child of children.flat()) if (child) node.append(child);
  return node;
}

const NEAR = 6; // pixels: how near a guide or a site catches
const BOX_HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
const isEnd = (end) => end && !Array.isArray(end) && typeof end === "object";
const copyOf = (value) => (value === undefined ? undefined : structuredClone(value));
const round = (value) => Math.round(value * 100) / 100;
const rounded = (point) => [round(point[0]), round(point[1])];
const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

// What a shape is called, as the studio names it: "Arrow", "Speech Bubble", "Group".
export const shapeLabel = (spec) => (spec?.kind === "group" ? "Group" : F.LABELS[spec?.kind] || "Shape");
// What the tool that draws a kind is called: its own name, but the pen's (which draws a path).
const toolName = (kind) => F.TOOLS?.[kind] || F.LABELS[kind];
const plural = (count, word = "Shape") => (count === 1 ? word : `${count} ${word}s`);

// Each kind as the popover draws it, small: its outline in the ink of the menu.
function iconSpec(kind) {
  const form = F.family(kind);
  const thin = { line_width: 1.6 };
  if (kind === "polyline") return { kind, points: [[4, 19], [11, 7], [19, 16], [28, 5]], ...thin };
  if (kind === "path") return { kind, d: "M 4 19 C 8 3 17 21 28 5", fill: "none", ...thin };
  if (kind === "pen") return { kind, points: [[4, 17], [9, 8], [15, 15], [21, 7], [28, 12]], ...thin };
  if (kind === "brace") return { kind, from: [12, 3], to: [12, 21], depth: 8, ...thin };
  if (kind === "bracket") return { kind, from: [13, 3], to: [13, 21], depth: 6, ...thin };
  if (kind === "dimension" || kind === "scale-bar") return { kind, from: [4, 13], to: [28, 13], ...(kind === "scale-bar" ? { line_width: 3.5 } : thin) };
  if (kind === "elbow") return { kind, from: [4, 19], to: [28, 5], ...thin };
  if (kind === "curved-arrow") return { kind, from: [4, 18], to: [28, 14], bend: 0.35, ...thin };
  if (kind === "arc") return { kind, from: [5, 18], to: [27, 18], bend: 0.45, ...thin };
  if (form === "line") return { kind, from: [4, 19], to: [28, 5], ...thin };
  if (kind === "bubble") return { kind, at: [5, 3], size: [22, 13], tail: [9, 21], ...thin };
  if (kind === "text") return null;
  const tall = ["arrow-up", "arrow-down"].includes(kind);
  const square = ["ellipse", "ring", "polygon", "star", "diamond", "plus", "cross", "triangle", "right-triangle"].includes(kind);
  const size = tall ? [12, 20] : square ? [19, 19] : kind === "highlight" ? [24, 9] : [24, 16];
  return { kind, at: [16 - size[0] / 2, 12 - size[1] / 2], size, ...thin, ...(kind === "rounded-rectangle" ? { corner: 4 } : {}), ...(kind === "highlight" ? { corner: 1.5 } : {}) };
}
const ICON_ROLES = { "tone-1-stroke": "currentColor", "tone-1-fill": "none", "block-fill": "none", "muted-ink": "currentColor", ink: "currentColor" };
export function shapeIcon(kind) {
  const holder = S("svg", { viewBox: "0 0 32 24", class: "shape-icon", "aria-hidden": "true" });
  const spec = iconSpec(kind);
  if (!spec) {
    holder.append(S("text", { x: 16, y: 18, "text-anchor": "middle", "font-size": 17, "font-weight": 600, fill: "currentColor", "font-family": "var(--font)" }));
    holder.lastChild.textContent = "T";
    return holder;
  }
  const look = { ...spec };
  if (["check", "cross"].includes(kind)) Object.assign(look, { fill: "accent" });
  if (kind === "highlight") Object.assign(look, { fill: "accent", fill_opacity: 0.35 });
  const roles = { ...ICON_ROLES, "tone-1-stroke": "currentColor" };
  holder.innerHTML = F.svg(look, F.geometry(look), roles);
  return holder;
}

// Words typed in a shape where the host has no editor of its own for them: a box of its
// words, as plain as they are written (their markup typed as it is).
export function plainWords({ value = "", placeholder = "" } = {}) {
  const area = h("textarea.rich.plain-words", { rows: 1, placeholder, spellcheck: "false" });
  area.value = value;
  const grow = () => { area.style.height = "auto"; area.style.height = `${area.scrollHeight}px`; };
  area.addEventListener("input", grow);
  area.selectAll = () => area.select();
  area.caretToEnd = () => { area.setSelectionRange(area.value.length, area.value.length); };
  area.selectWordAt = () => false;
  queueMicrotask(grow);
  return area;
}

// The shapes' editor, for a `host` that holds them (a deck's slide, a figure). It says:
// - studio, center (what the words typed are put in), stage, catalog (flexo.freeform's);
// - page() (which page is shown: a slide's index, a figure's 0), list() (its shapes, as they
//   are drawn: in the page's units, its places its own), pageNode() (what holds its <svg>),
//   idOf(index, page) (the id each is drawn with), frame() ([x, y, width, height] of the page
//   in the shapes' units);
// - edit(mutate, { label, merge, hold, quiet }) (a change of the list, mutated in place or
//   given anew: false if refused), mark({ page, before, after }) (what a change chose before
//   and after, for its undo to choose again), goTo(page);
// - objects() (what else the page holds that a shape may be glued to and catches at: by name,
//   { box, turn, outline, label }), glueKey ("object" for a slide's, "part" for a figure's),
//   pieceAt(event) (a piece of one under the pointer, smaller than any of them, if any);
// - partAt(event) (whether one is under the pointer: a shape behind them is not pressed there);
// - leaveOthers, renderInspector, reportFocus, swallowRelease, undoNote, awayFrom, clipItems,
//   canDraw, shapeButton; words(options) (an editor for a shape's words), wordSize(spec);
// - verb ("Add", "Draw": its commands' names), noun ("slide", "figure"), crumb() (the page, as
//   the inspector's way back up names it), ownKeys (what a shape on it says besides how it is
//   drawn), grouped(specs) and ungrouped(group) (what a group made of shapes, and each shape of
//   a group taken apart, says of those), commands(picks, name) and panel(picks, specs, set)
//   (the page's own commands and settings for the shapes chosen);
// - showPanel() (its inspector shown, if it was hidden: Align and Distribute's ⇧⌘A).
export function shapeEditor(host) {
  const studio = host.studio;
  const catalog = host.catalog || studio.catalog?.shapes || {};
  const verb = host.verb || "Add";
  const noun = host.noun || "page";
  const glueKey = host.glueKey || "object";
  const ownKeys = host.ownKeys || [];
  let chosen = [];
  let picked = [];
  let chosenOn = -1;
  let tool = null;
  let gesture = null;
  let words = null;
  let hovered = null;
  let fresh = null;
  const layer = S("svg", { class: "shape-layer", preserveAspectRatio: "xMidYMid meet" });
  const previews = S("g", { class: "shape-previews" });
  const marks = S("g", { class: "shape-marks" });
  const guides = S("g", { class: "shape-guides" });
  const handles = S("g", { class: "shape-handles" });
  layer.append(previews, marks, guides, handles);
  const tip = h("div.size-tip.shape-tip", { hidden: true });

  // -- the page, its shapes, and where they are --

  const slideIndex = () => host.page();
  const shapesOf = () => { const list = host.list(); return Array.isArray(list) ? list : []; };
  const page = () => host.pageNode();
  // The page's frame in the shapes' units: [x, y, width, height].
  const frameOf = () => host.frame();
  const frameSize = () => { const [, , width, height] = frameOf(); return [width, height]; };
  const roles = () => host.roles?.() || studio.info?.roles || {};
  const idOf = (index, at = slideIndex()) => host.idOf(index, at);
  const drawnOf = (index) => page()?.querySelector(`[id="${CSS.escape(idOf(index))}"]`) || null;
  const chosenNow = () => (chosenOn === slideIndex() ? chosen.filter((index) => index < shapesOf().length && shapesOf()[index]) : []);
  // (Read once a move while dragging -- `scaleNow`, and the page's place, `boxNow`: see step --
  // not after each change it makes: each read lays the page out again, a few milliseconds a
  // move with a full slide.)
  let scaleNow = 0, boxNow = null;
  const unit = () => scaleNow || layer.getScreenCTM?.()?.a || 1;
  const toFrame = (event) => {
    const matrix = layer.getScreenCTM?.();
    if (!matrix) return [0, 0];
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    return [point.x, point.y];
  };
  const toScreen = ([x, y]) => {
    const matrix = layer.getScreenCTM?.();
    const point = new DOMPoint(x, y).matrixTransform(matrix);
    return [point.x, point.y];
  };

  // Each shape's geometry as it is now -- moved meanwhile (`live`), its ends glued where what
  // they are glued to is -- a box of words as the slide measured it.
  let live = new Map();
  const specAt = (index) => live.get(index) || shapesOf()[index];
  const allIds = (list = shapesOf()) => {
    const found = new Map();
    const walk = (items, path) => items.forEach((item, n) => {
      if (!item || typeof item !== "object") return;
      if (item.id !== undefined) found.set(String(item.id), [...path, n]);
      if (item.kind === "group") walk(item.shapes || [], [...path, n]);
    });
    walk(list, []);
    return found;
  };
  const measured = (index, path = []) => {
    const node = page()?.querySelector(`[id="${CSS.escape([idOf(index), ...path].join("."))}"]`);
    const box = (node?.getAttribute("data-flexo-box") || "").split(" ").map(Number);
    return box.length === 4 && box.every(Number.isFinite) ? [box[2], box[3]] : null;
  };
  // What else the page holds -- a slide's objects, a figure's parts -- by name, in the shapes'
  // units (the host's: it finds them, given how a point on the screen is one here).
  const screenToFrame = (x, y) => toFrame({ clientX: x, clientY: y });
  let objectsSeen = null;
  const objectsNow = () => (objectsSeen ||= host.objects(screenToFrame));
  // (Kept by the shape as written -- a change makes another -- but a line glued to others,
  // which moves with them, and a box of words, as tall as the slide last drew it.)
  let drawnAs = new WeakMap();
  function geometryOf(index, spec = specAt(index), path = []) {
    if (!spec) return null;
    if (spec.kind === "text") return F.geometry(spec, null, measured(index, path) || undefined);
    if (F.family(spec.kind) === "line" && (isEnd(spec.from) || isEnd(spec.to))) return F.geometry(spec, F.glued(spec, find));
    if (!drawnAs.has(spec)) drawnAs.set(spec, F.geometry(spec));
    return drawnAs.get(spec);
  }
  function find(end) {
    if (end.shape !== undefined) {
      const at = allIds(shapesOf().map((_, n) => specAt(n))).get(String(end.shape));
      if (!at) return null;
      const spec = at.length === 1 ? specAt(at[0]) : at.slice(1).reduce((item, n) => item?.shapes?.[n], specAt(at[0]));
      if (!spec) return null;
      return F.targetOf(spec, spec.kind === "text" ? F.geometry(spec, null, measured(at[0], at.slice(1)) || undefined) : F.geometry(spec));
    }
    const named = end[glueKey] ?? end.object ?? end.part;
    return objectsNow().get(String(named)) || pieceNamed(String(named)) || null;
  }
  // A piece of what the page holds, named by an end glued to it (a protein's feature), as the
  // host finds it.
  const pieceNamed = (name) => host.piece?.(name, screenToFrame) || null;
  // What a zoom inset magnifies, as the host finds it: its box in the shapes' units, the id of
  // its drawing, and how that drawing's units are the shapes' (insets.js's markup).
  const insetSource = (spec) => (spec?.kind === "inset" ? host.insetSource?.(spec, screenToFrame) || null : null);
  // A shape's frame on the slide: its corners, turned as it is.
  const cornersOf = (made) => F.corners(made);
  const boundsOf = (index) => { const spec = specAt(index), made = geometryOf(index); return made ? F.bounds(spec, made) : null; };
  const unionOf = (indices) => {
    const all = indices.map(boundsOf).filter(Boolean);
    if (!all.length) return null;
    return [Math.min(...all.map((b) => b[0])), Math.min(...all.map((b) => b[1])), Math.max(...all.map((b) => b[2])), Math.max(...all.map((b) => b[3]))];
  };

  // -- what is chosen --

  function choose(indices, { quiet = false } = {}) {
    closeWords();
    chosen = [...new Set(indices)].filter((index) => Number.isInteger(index)).sort((a, b) => a - b);
    // (And the order they were chosen in, for Align's first and last chosen: aligntools.js.)
    picked = [...picked.filter((index) => chosen.includes(index)), ...indices.filter((index, n) => chosen.includes(index) && !picked.includes(index) && indices.indexOf(index) === n)];
    chosenOn = slideIndex();
    if (tools?.points.active() && !chosen.includes(tools.points.index())) tools.points.leave({ quiet: true });
    if (chosen.length) host.leaveOthers();
    if (!quiet) { place(); host.renderInspector(); host.reportFocus(); }
  }
  function clear({ quiet = false } = {}) {
    if (!chosen.length && !words) return;
    closeWords();
    chosen = [];
    if (!quiet) { place(); host.renderInspector(); host.reportFocus(); }
  }
  // Undone or redone, what a change did to the page's shapes is chosen again. (The host keeps
  // it with the change, as it lands: `{ slide, before, after }`, the page's place as `slide`.)
  const mark = (before, after) => host.mark({ slide: slideIndex(), before: before ? [...before] : [], after: after ? [...after] : [] });
  function restore(entry, undone) {
    const said = entry.shapes;
    const picks = (undone ? said.before : said.after) || [];
    if (said.slide !== slideIndex()) host.goTo?.(said.slide);
    chosen = picks.filter((index) => index < shapesOf().length);
    chosenOn = slideIndex();
    if (chosen.length) host.leaveOthers();
  }

  // An edit of the page's shapes, one step named `label`; `mutate(list)` changes the list in
  // place (or returns another). `after`: what is chosen once it is made.
  function edit(mutate, label, { after = undefined, merge = null, quiet = false } = {}) {
    if (host.awayFrom("change shapes")) return false;
    const before = chosenNow();
    // (Chosen as the change lands: the panel drawn by it shows what is chosen after it.)
    if (Array.isArray(after)) { chosen = after; chosenOn = slideIndex(); }
    const made = host.edit((list) => {
      const out = mutate(list);
      return Array.isArray(out) ? out : list;
    }, { label, ...(merge ? { merge, hold: true } : {}), ...(quiet ? { quiet: true } : {}) });
    if (!made) { chosen = before; return false; }
    mark(before, Array.isArray(after) ? after : before);
    objectsSeen = null;
    host.renderInspector();
    place();
    return true;
  }

  // -- the layer over the slide --

  function attach() {
    const node = page();
    if (!node) return;
    const [x, y, width, height] = frameOf();
    layer.setAttribute("viewBox", `${x} ${y} ${width} ${height}`);
    if (layer.parentNode !== node) node.append(layer);
    if (tip.parentNode !== node) node.append(tip);
  }

  // The page drawn again: what was moved here is where it is drawn now.
  function drawn() {
    live = new Map();
    drawnAs = new WeakMap();
    objectsSeen = null;
    held.clear();
    previews.replaceChildren();
    attach();
    place();
  }

  const held = new Map(); // drawn shapes set aside, or moved, while their change is on its way
  function setAside(index, how) {
    const node = drawnOf(index);
    if (!node) return;
    if (!held.has(index)) held.set(index, { node, transform: node.getAttribute("transform"), visibility: node.style.visibility });
    const was = held.get(index);
    if (how.hidden) node.style.visibility = "hidden";
    else node.style.removeProperty("visibility");
    if (how.transform !== undefined) node.setAttribute("transform", [how.transform, was.transform].filter(Boolean).join(" "));
  }
  function putBack() {
    for (const [, was] of held) {
      if (was.transform) was.node.setAttribute("transform", was.transform); else was.node.removeAttribute("transform");
      if (was.visibility) was.node.style.visibility = was.visibility; else was.node.style.removeProperty("visibility");
    }
    held.clear();
    previews.replaceChildren();
  }
  function preview(index, spec, made = null) {
    const node = S("g", { "data-index": index });
    // (A zoom inset, as the page will draw it: what it shows drawn again from the page's own.)
    const source = insetSource(spec);
    node.innerHTML = source ? I.markup(spec, made || geometryOf(index, spec), roles(), { source: source.box, target: source.target, toShapes: source.toShapes, clipId: `flexo-inset-clip-${index}` })
      : F.svg(spec, made || geometryOf(index, spec), roles());
    previews.append(node);
    setAside(index, { hidden: true });
  }

  // The frames of what is chosen, its handles, and a shape pointed at.
  function place() {
    attach();
    marks.replaceChildren();
    handles.replaceChildren();
    if (!page()) return;
    if (words) placeWords();
    // (A path's points being edited: they are what is shown.)
    if (tools?.points.active()) { tools.points.place(); return; }
    const picks = chosenNow();
    const px = 1 / unit();
    if (hovered !== null && !picks.includes(hovered) && !gesture && shapesOf()[hovered]) outline(hovered, "hover");
    if (!picks.length || words) return;
    for (const index of picks) outline(index, picks.length > 1 ? "chosen many" : "chosen");
    if (gesture?.started && gesture.type !== "move") return;
    const locked = picks.some((index) => shapesOf()[index]?.locked);
    if (locked) {
      // Locked, it shows so -- and has no handles.
      for (const index of picks) {
        const box = boundsOf(index);
        if (box) handles.append(S("g", { class: "shape-lock", transform: `translate(${box[2] + 4 * px} ${box[1] - 14 * px}) scale(${px})` },
          S("path", { d: "M2 6h8v6H2zM3.5 6V4a2.5 2.5 0 015 0v2", fill: "none", stroke: "currentColor", "stroke-width": 1.4 })));
      }
      return;
    }
    if (picks.length === 1) placeOne(picks[0]);
    else placeMany(picks);
  }
  function outline(index, kind) {
    const spec = specAt(index), made = geometryOf(index);
    if (!spec || !made) return;
    const px = 1 / unit();
    const form = F.family(spec.kind);
    if (form === "line" || (form === "points" && !made.closed)) {
      // A line is chosen as itself: its path, wide and faint, under it.
      const d = F.pathData(made.segments);
      marks.append(S("path", { d, class: `shape-mark ${kind} along`, "stroke-width": Math.max(Number(spec.line_width || 0) + 8 * px, 6 * px) }));
      return;
    }
    const corners = cornersOf(made);
    marks.append(S("polygon", { points: corners.map((p) => p.join(",")).join(" "), class: `shape-mark ${kind}`, "stroke-width": 1.5 * px }));
  }
  function handle(point, kind, cursor, onDown, title = "") {
    const px = 1 / unit();
    const size = (kind === "adjust" ? 5.5 : kind === "turn" ? 5 : 4.5) * px;
    const node = kind === "adjust"
      ? S("rect", { x: point[0] - size, y: point[1] - size, width: 2 * size, height: 2 * size, transform: `rotate(45 ${point[0]} ${point[1]})` })
      : kind === "turn" || kind === "end" || kind === "bend" ? S("circle", { cx: point[0], cy: point[1], r: size }) : S("rect", { x: point[0] - size, y: point[1] - size, width: 2 * size, height: 2 * size, rx: px });
    node.setAttribute("class", `shape-handle ${kind}`);
    node.style.cursor = cursor;
    node.setAttribute("stroke-width", 1.2 * px);
    if (title) node.append(Object.assign(S("title"), { textContent: title }));
    node.addEventListener("pointerdown", (event) => { if (event.button !== 0) return; event.preventDefault(); event.stopPropagation(); onDown(event); });
    node.addEventListener("dblclick", (event) => { event.stopPropagation(); event.preventDefault(); });
    handles.append(node);
    return node;
  }
  const resizeCursor = (name, turn = 0) => {
    const angles = { e: 0, se: 45, s: 90, sw: 135, w: 180, nw: 225, n: 270, ne: 315 };
    const angle = ((angles[name] + turn) % 180 + 180) % 180;
    return angle < 22.5 || angle >= 157.5 ? "ew-resize" : angle < 67.5 ? "nwse-resize" : angle < 112.5 ? "ns-resize" : "nesw-resize";
  };
  function placeOne(index) {
    const spec = F.normalised(specAt(index)), made = geometryOf(index);
    if (!made) return;
    const form = F.family(spec.kind), px = 1 / unit();
    if (form === "line") {
      const [a, b] = made.ends;
      handle(a, "end", "move", (event) => startEnd(event, index, "from"), "Drag to move this end · Let go on a shape to join it");
      handle(b, "end", "move", (event) => startEnd(event, index, "to"), "Drag to move this end · Let go on a shape to join it");
      for (const adjust of lineHandles(spec, made)) handle(adjust.at, adjust.kind || "bend", "move", (event) => startAdjust(event, index, adjust), adjust.title);
      return;
    }
    if (form === "points" && spec.kind === "polyline") {
      spec.points.forEach((point, n) => handle(point, "end", "move", (event) => startPoint(event, index, n), "Drag to move this point"));
      return;
    }
    const centre = F.centreOf(made), [x, y, w, h] = made.box;
    const turnAt = turned([x + w / 2, y - 24 * px], centre, made.turn);
    // (A zoom inset is never turned.)
    if (spec.kind !== "inset") {
      marks.append(S("line", { x1: turned([x + w / 2, y], centre, made.turn)[0], y1: turned([x + w / 2, y], centre, made.turn)[1], x2: turnAt[0], y2: turnAt[1], class: "shape-stalk", "stroke-width": px }));
      handle(turnAt, "turn", "grab", (event) => startTurn(event, [index]), "Drag to rotate (⇧: by 15°) · Double-click to set it straight").addEventListener("dblclick", () => straighten([index]));
    }
    const names = spec.kind === "text" ? ["e", "w"] : BOX_HANDLES;
    for (const name of names) handle(turned(boxPoint(made.box, name), centre, made.turn), "size", resizeCursor(name, made.turn), (event) => startSize(event, [index], name), "Drag to resize (⇧: keep its proportions · ⌥: about its middle)");
    for (const adjust of boxHandles(spec, made)) handle(adjust.at, adjust.kind || "adjust", adjust.cursor || "pointer", (event) => startAdjust(event, index, adjust), adjust.title);
  }
  function placeMany(picks) {
    const box = unionOf(picks);
    if (!box) return;
    const px = 1 / unit();
    const [x0, y0, x1, y1] = box;
    marks.append(S("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0, class: "shape-mark group-frame", "stroke-width": px }));
    const frame = [x0, y0, x1 - x0, y1 - y0];
    for (const name of BOX_HANDLES) handle(boxPoint(frame, name), "size", resizeCursor(name), (event) => startSize(event, picks, name), "Drag to resize them together");
    handle([x0 + (x1 - x0) / 2, y0 - 24 * px], "turn", "grab", (event) => startTurn(event, picks), "Drag to rotate them together (⇧: by 15°)");
  }
  const turned = (point, centre, degrees) => F.turned(point, centre, degrees || 0);
  function boxPoint([x, y, w, h], name) {
    const across = name.includes("w") ? x : name.includes("e") ? x + w : x + w / 2;
    const down = name.includes("n") ? y : name.includes("s") ? y + h : y + h / 2;
    return [across, down];
  }

  // A shape's own handles, where they are on the slide, and what dragging one sets.
  function boxHandles(spec, made) {
    const [x, y, w, h] = made.box, ss = Math.min(w, h), centre = F.centreOf(made), kind = spec.kind;
    const flipX = spec.flip === "horizontal" || spec.flip === "both", flipY = spec.flip === "vertical" || spec.flip === "both";
    const local = (point) => { const [px, py] = F.unturned(point, centre, made.turn); return [flipX ? 2 * centre[0] - px : px, flipY ? 2 * centre[1] - py : py]; };
    const page = ([px, py]) => turned([flipX ? 2 * centre[0] - px : px, flipY ? 2 * centre[1] - py : py], centre, made.turn);
    const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
    const out = [];
    const corner = Number(spec.corner || 0);
    if (["rectangle", "rounded-rectangle", "highlight"].includes(kind) || (kind === "bubble" && spec.body === "rounded")) {
      out.push({ at: page([x + Math.min(corner, ss / 2), y]), title: "Drag to round its corners", label: "Change Corner",
        set: (point) => ({ corner: round(clamp(local(point)[0] - x, 0, ss / 2)) }) });
    }
    if (kind === "bubble") {
      out.push({ at: spec.tail, title: "Drag to point its tail", label: "Move Tail", set: (point) => ({ tail: rounded(point) }) });
    }
    if (kind === "triangle") out.push({ at: page([x + w * spec.apex, y]), title: "Drag to move its top", label: "Change Shape", set: (point) => ({ apex: round(clamp((local(point)[0] - x) / w, 0, 1)) }) });
    if (kind === "parallelogram") out.push({ at: page([x + Math.min(ss * spec.slant, w), y]), title: "Drag to slant it", label: "Change Slant", set: (point) => ({ slant: round(clamp((local(point)[0] - x) / ss, 0, Math.min(1, w / ss))) }) });
    if (kind === "trapezoid") out.push({ at: page([x + Math.min(ss * spec.inset, w / 2), y]), title: "Drag to narrow its top", label: "Change Shape", set: (point) => ({ inset: round(clamp((local(point)[0] - x) / ss, 0, Math.min(0.5, w / 2 / ss))) }) });
    if (kind === "chevron") out.push({ at: page([x + Math.min(ss * spec.point, w), y + h / 2]), title: "Drag to sharpen its point", label: "Change Point", set: (point) => ({ point: round(clamp((local(point)[0] - x) / ss, 0, Math.min(1, w / ss))) }) });
    if (kind === "plus") out.push({ at: page([x + ss * spec.arm, y]), title: "Drag to thicken its arms", label: "Change Arms", set: (point) => ({ arm: round(clamp((local(point)[0] - x) / ss, 0.02, 0.48)) }) });
    if (kind === "cross") out.push({ at: page([x + w * spec.arm, y]), title: "Drag to thicken its arms", label: "Change Arms", set: (point) => ({ arm: round(clamp((local(point)[0] - x) / w, 0.02, 0.45)) }) });
    if (kind === "star") {
      const inner = made.segments[1];
      out.push({ at: page([inner[1], inner[2]]), title: "Drag to make its points deeper or shallower", label: "Change Points", set: (point) => {
        const [px, py] = local(point), n = Number(spec.tips);
        const outer = Array.from({ length: n }, (_, k) => [Math.cos(-Math.PI / 2 + 2 * Math.PI * k / n), Math.sin(-Math.PI / 2 + 2 * Math.PI * k / n)]);
        const xs = outer.map((p) => p[0]), ys = outer.map((p) => p[1]);
        const left = Math.min(...xs), top = Math.min(...ys), across = Math.max(...xs) - left, down = Math.max(...ys) - top;
        const ux = (px - x) / w * across + left, uy = (py - y) / h * down + top, angle = -Math.PI / 2 + Math.PI / n;
        return { ratio: round(clamp(ux * Math.cos(angle) + uy * Math.sin(angle), 0.05, 0.95)) };
      } });
    }
    // A zoom inset's region, on what it magnifies: its corners and its middle.
    if (kind === "inset") { const source = insetSource(spec); if (source) out.push(...I.handles(spec, source.box)); }
    const arrows = { "arrow-right": [1, 0], "arrow-left": [-1, 0], "arrow-up": [0, -1], "arrow-down": [0, 1], "arrow-left-right": [1, 0] };
    if (arrows[kind]) {
      const [ax, ay] = arrows[kind], across = ax !== 0;
      const head = Math.min(ss * spec.head, across ? (kind === "arrow-left-right" ? w / 2 : w) : h), half = (across ? h : w) * spec.shaft / 2;
      const at = across ? [ax > 0 ? x + w - head : x + head, y + h / 2 - half] : [x + w / 2 - half, ay > 0 ? y + h - head : y + head];
      out.push({ at: page(at), title: "Drag to shape its head and shaft", label: "Change Arrow", set: (point) => {
        const [px, py] = local(point);
        const headNow = across ? (ax > 0 ? x + w - px : px - x) : (ay > 0 ? y + h - py : py - y);
        const shaftNow = across ? 2 * Math.abs(y + h / 2 - py) / h : 2 * Math.abs(x + w / 2 - px) / w;
        return { head: round(clamp(headNow / ss, 0, 1)), shaft: round(clamp(shaftNow, 0.05, 1)) };
      } });
    }
    return out;
  }
  function lineHandles(spec, made) {
    const [a, b] = made.ends, length = distance(a, b) || 1;
    const [ux, uy] = [(b[0] - a[0]) / length, (b[1] - a[1]) / length], left = [uy, -ux], mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const across = (p) => (p[0] - a[0]) * left[0] + (p[1] - a[1]) * left[1];
    const along = (p) => (p[0] - a[0]) * ux + (p[1] - a[1]) * uy;
    const out = [];
    if (spec.kind === "curved-arrow") {
      const through = [mid[0] + (left[0] * spec.bend + ux * (spec.lean || 0)) * length, mid[1] + (left[1] * spec.bend + uy * (spec.lean || 0)) * length];
      out.push({ at: through, title: "Drag to bend it · Double-click to straighten it", label: "Bend Line", set: (point, free) => {
        let bend = across(point) / length, lean = (along(point) - length / 2) / length;
        const near = NEAR / unit() / length;
        if (!free && Math.abs(lean) < near) lean = 0;
        if (!free && Math.abs(bend) < near) bend = 0;
        return { bend: round(Math.max(-4, Math.min(4, bend))), lean: round(Math.max(-0.5, Math.min(0.5, lean))) };
      } });
    }
    if (spec.kind === "arc") {
      const top = [mid[0] + left[0] * spec.bend * length, mid[1] + left[1] * spec.bend * length];
      out.push({ at: top, title: "Drag to bow it more or less", label: "Bend Arc", set: (point) => ({ bend: round(Math.max(-4, Math.min(4, across(point) / length))) }) });
    }
    if (spec.kind === "elbow") {
      const share = spec.elbow ?? 0.5, down = spec.route === "down";
      const at = down ? [(a[0] + b[0]) / 2, a[1] + share * (b[1] - a[1])] : [a[0] + share * (b[0] - a[0]), (a[1] + b[1]) / 2];
      out.push({ at, title: "Drag to move its middle", label: "Move Elbow", set: (point) => {
        const span = down ? b[1] - a[1] : b[0] - a[0];
        return { elbow: round(Math.abs(span) < 1e-6 ? 0.5 : Math.max(-4, Math.min(5, ((down ? point[1] - a[1] : point[0] - a[0]) / span)))) };
      } });
    }
    if (spec.kind === "brace") {
      const tipAt = (spec.tip ?? 0.5) * length;
      out.push({ at: [a[0] + ux * tipAt + left[0] * spec.depth, a[1] + uy * tipAt + left[1] * spec.depth], kind: "adjust", title: "Drag to move its tip, or make it deeper", label: "Change Brace",
        set: (point) => ({ tip: round(Math.max(0.05, Math.min(0.95, along(point) / length))), depth: round(across(point)) }) });
    }
    if (spec.kind === "bracket") {
      out.push({ at: [mid[0] + left[0] * spec.depth, mid[1] + left[1] * spec.depth], kind: "adjust", title: "Drag to make it deeper", label: "Change Bracket",
        set: (point) => ({ depth: round(across(point)) }) });
    }
    return out;
  }

  // -- hit testing --

  // The shape under the pointer, topmost first: those over the slide's words, then -- where
  // no object of the slide is (`clear`) -- those behind them.
  function shapeAt(event, { behind = true, clearOf = null } = {}) {
    const point = toFrame(event), slack = NEAR / unit();
    const list = shapesOf();
    for (const under of [false, true]) {
      if (under && (!behind || clearOf?.())) break;
      for (let index = list.length - 1; index >= 0; index -= 1) {
        const spec = specAt(index);
        if (!spec || Boolean(spec.behind) !== under) continue;
        const made = geometryOf(index);
        if (made && hitsShape(spec, made, point, slack, index)) return index;
      }
    }
    return null;
  }
  function hitsShape(spec, made, point, slack, index, path = []) {
    if (spec.kind === "group") return (spec.shapes || []).some((child, n) => hitsShape(child, geometryOf(index, child, [...path, n]), point, slack, index, [...path, n]));
    if (F.hits(spec, made, point, slack)) return true;
    // Its words beside it (a line's label) are it too.
    const label = page()?.querySelector(`[id="${CSS.escape([idOf(index), ...path].join(".") + ".label")}"]`);
    if (label) { const box = label.getBoundingClientRect(), at = toScreen(point); return at[0] >= box.left && at[0] <= box.right && at[1] >= box.top && at[1] <= box.bottom; }
    return false;
  }

  // -- the pointer --

  function press(event) {
    if (tools?.points.active() && tools.points.press(event)) { event.shapes = true; return true; }
    if (event.button !== 0) return false;
    if (words && words.node.contains(event.target)) return false;
    if (tool?.kind === "path") { paths().pen.press(event); event.shapes = true; return true; }
    if (tool) { startDraw(event); event.shapes = true; return true; }
    if (event.target.closest?.(".shape-handle")) return true;
    const index = shapeAt(event, { clearOf: () => Boolean(host.partAt(event)) });
    if (index === null) return false;
    event.shapes = true;
    const picks = chosenNow();
    if (event.shiftKey || event.metaKey) {
      choose(picks.includes(index) ? picks.filter((one) => one !== index) : [...picks, index]);
      host.swallowRelease();
      return true;
    }
    if (!picks.includes(index)) choose([index]);
    startMove(event, chosenNow().includes(index) ? chosenNow() : [index], index);
    return true;
  }
  function hover(event) {
    if (tool?.kind === "path") return paths().pen.hover(event);
    if (tools?.points.active()) return true;
    if (gesture || tool) return true;
    const index = shapeAt(event, { clearOf: () => Boolean(host.partAt(event)) });
    if (index !== hovered) { hovered = index; place(); }
    return index !== null;
  }
  function leave() { if (hovered !== null) { hovered = null; place(); } }
  function dblclick(event) {
    if (tools?.points.active()) return tools.points.dblclick(event);
    const index = shapeAt(event, { clearOf: () => Boolean(host.partAt(event)) });
    if (index === null) return false;
    const spec = shapesOf()[index];
    if (!spec || spec.kind === "group" || spec.locked) return true;
    // A path double-clicked: its points, to edit (its words by Return, or Edit Text).
    if (spec.kind === "path") { choose([index]); paths().points.start(index); return true; }
    choose([index]);
    editWords(index, { point: { x: event.clientX, y: event.clientY } });
    return true;
  }
  function context(event) {
    const index = shapeAt(event, { clearOf: () => Boolean(host.partAt(event)) });
    if (index === null) return false;
    if (!chosenNow().includes(index)) choose([index]);
    menu({ x: event.clientX, y: event.clientY }, menuItems());
    return true;
  }

  // A drag under way: once the pointer has moved a little it starts; Esc takes it back.
  function begin(event, state) {
    gesture = { ...state, start: [event.clientX, event.clientY], from: toFrame(event), started: false, free: false, frame: 0 };
    window.addEventListener("pointermove", moveGesture);
    window.addEventListener("pointerup", endGesture);
    window.addEventListener("pointercancel", cancelGesture);
    window.addEventListener("keydown", keyGesture, true);
    window.addEventListener("keyup", keyGesture, true);
  }
  function finish() {
    window.removeEventListener("pointermove", moveGesture);
    window.removeEventListener("pointerup", endGesture);
    window.removeEventListener("pointercancel", cancelGesture);
    window.removeEventListener("keydown", keyGesture, true);
    window.removeEventListener("keyup", keyGesture, true);
    const was = gesture;
    gesture = null;
    tip.hidden = true;
    guides.replaceChildren();
    page()?.classList.remove("shape-dragging");
    return was;
  }
  function moveGesture(event) {
    if (!gesture) return;
    gesture.last = event;
    if (Math.hypot(event.clientX - gesture.start[0], event.clientY - gesture.start[1]) >= 1) gesture.moved = true;
    if (!gesture.started) {
      if (Math.hypot(event.clientX - gesture.start[0], event.clientY - gesture.start[1]) < 3) return;
      gesture.started = true;
      closeWords();
      hovered = null;
      page()?.classList.add("shape-dragging");
      gesture.targets = snapTargets(gesture.indices || []);
    }
    // (Moves come a frame at a time: each is drawn as it comes.)
    step(event);
  }
  function keyGesture(event) {
    if (!gesture) return;
    if (event.type === "keydown" && event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      cancelGesture();
      host.swallowRelease(true);
      return;
    }
    // ⇧, ⌥ or ⌘ pressed or let go mid-drag: drawn again with them.
    if (gesture.started && gesture.last && ["Shift", "Alt", "Meta", "Control"].includes(event.key)) {
      gesture.last = new PointerEvent("pointermove", { clientX: gesture.last.clientX, clientY: gesture.last.clientY, shiftKey: event.shiftKey, altKey: event.altKey, metaKey: event.metaKey, ctrlKey: event.ctrlKey });
      step(gesture.last);
    }
  }
  function cancelGesture() {
    const was = finish();
    if (!was) return;
    if (was.frame) cancelAnimationFrame(was.frame);
    live = new Map();
    putBack();
    if (was.type === "draw") drawingDone();
    place();
  }
  function endGesture(event) {
    if (!gesture) return;
    if (gesture.frame) { cancelAnimationFrame(gesture.frame); gesture.frame = 0; }
    // A handle pressed and let go where it was (the second click of a double-click on the
    // shape, say) changes nothing: not even a snap to a guide nearby.
    if (gesture.started && !gesture.moved && gesture.type !== "draw" && gesture.type !== "move") {
      finish();
      live = new Map();
      putBack();
      place();
      host.swallowRelease();
      return;
    }
    if (gesture.started) step(event);
    const was = finish();
    if (was.type === "draw") { commitDraw(was, event); return; }
    if (!was.started) {
      // A press let go where it was: what it was on is chosen alone.
      if (was.type === "move" && was.on !== undefined && chosenNow().length > 1) choose([was.on]);
      host.swallowRelease();
      return;
    }
    host.swallowRelease();
    commit(was);
  }
  function step(event) {
    const g = gesture;
    if (!g) return;
    if (!scaleNow) { scaleNow = layer.getScreenCTM?.()?.a || 1; boxNow = page()?.getBoundingClientRect() || null; queueMicrotask(() => { scaleNow = 0; boxNow = null; }); }
    // (Free of guides and glue: snapping off, or ⌘ held while it is on -- snapping.js.)
    const point = toFrame(event), free = Snap.free(event);
    guides.replaceChildren();
    if (g.type === "move") stepMove(g, point, event, free);
    else if (g.type === "size") stepSize(g, point, event, free);
    else if (g.type === "turn") stepTurn(g, point, event);
    else if (g.type === "end") stepEnd(g, point, event, free);
    else if (g.type === "point") stepPoint(g, point, event, free);
    else if (g.type === "adjust") stepAdjust(g, point, event, free);
    else if (g.type === "draw") stepDraw(g, point, event, free);
    place();
  }

  // What a drag catches at: the slide's edges and middles, and the edges and middles of the
  // shapes and objects not being dragged.
  function snapTargets(moving) {
    const [x0, y0, width, height] = frameOf();
    const xs = [x0, x0 + width / 2, x0 + width], ys = [y0, y0 + height / 2, y0 + height], boxes = [];
    // (Nor a line glued to what moves: it moves with it.)
    const names = new Set(moving.flatMap((index) => namesIn(shapesOf()[index])));
    const glued = (spec) => F.family(spec.kind) === "line" && [spec.from, spec.to].some((end) => isEnd(end) && names.has(String(end.shape)));
    shapesOf().forEach((spec, index) => {
      if (moving.includes(index) || !spec || glued(spec)) return;
      const box = boundsOf(index);
      if (!box) return;
      xs.push(box[0], (box[0] + box[2]) / 2, box[2]);
      ys.push(box[1], (box[1] + box[3]) / 2, box[3]);
      // (Spaced among, all but lines: aligning.js.)
      if (F.family(spec.kind) !== "line") boxes.push(box);
    });
    for (const object of objectsNow().values()) {
      const [x, y, w, h] = object.box;
      xs.push(x, x + w / 2, x + w);
      ys.push(y, y + h / 2, y + h);
      boxes.push([x, y, x + w, y + h]);
    }
    return { xs, ys, boxes };
  }
  // The nearest of `values` to any of `mine` within reach: how far to move to it, and where.
  function catchAt(mine, values) {
    let best = null;
    const reach = NEAR / unit();
    for (const own of mine) for (const value of values) {
      const gap = value - own;
      if (Math.abs(gap) <= reach && (!best || Math.abs(gap) < Math.abs(best.gap))) best = { gap, at: value };
    }
    return best;
  }
  function guide(axis, at) {
    const [x0, y0, width, height] = frameOf(), px = 1 / unit();
    guides.append(axis === "x" ? S("line", { x1: at, y1: y0, x2: at, y2: y0 + height, class: "shape-guide", "stroke-width": px })
      : S("line", { x1: x0, y1: at, x2: x0 + width, y2: at, class: "shape-guide", "stroke-width": px }));
  }
  function say(text, event) {
    const node = page();
    if (!node || !event) return;
    const outer = boxNow || node.getBoundingClientRect();
    tip.textContent = text;
    tip.hidden = false;
    tip.style.left = `${event.clientX - outer.left + 14}px`;
    tip.style.top = `${event.clientY - outer.top + 16}px`;
  }

  // -- moving --

  function startMove(event, indices, on) {
    const movable = indices.filter((index) => !shapesOf()[index]?.locked);
    if (!movable.length) { host.swallowRelease(); return; }
    begin(event, { type: "move", indices: movable, on, originals: movable.map((index) => copyOf(shapesOf()[index])), box: unionOf(movable) });
  }
  function stepMove(g, point, event, free) {
    let dx = point[0] - g.from[0], dy = point[1] - g.from[1];
    if (event.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }
    if (!free && g.box) {
      const [x0, y0, x1, y1] = g.box;
      let across = event.shiftKey && dx === 0 ? null : catchAt([x0 + dx, (x0 + x1) / 2 + dx, x1 + dx], g.targets.xs);
      let down = event.shiftKey && dy === 0 ? null : catchAt([y0 + dy, (y0 + y1) / 2 + dy, y1 + dy], g.targets.ys);
      // Or, the nearer, where it sits as far from its neighbours as they are apart (aligning.js:
      // what does not move looked at once, as the drag starts).
      const even = (g.spacing ||= Align.spacing(g.targets.boxes || [])).caught([x0 + dx, y0 + dy, x1 + dx, y1 + dy], NEAR / unit(), { x: !(event.shiftKey && dx === 0), y: !(event.shiftKey && dy === 0) });
      [across, even.x] = nearer(across, even.x);
      [down, even.y] = nearer(down, even.y);
      if (across) { dx += across.gap; guide("x", across.at); } else if (even.x) dx += even.x.shift;
      if (down) { dy += down.gap; guide("y", down.at); } else if (even.y) dy += even.y.shift;
      const now = [x0 + dx, y0 + dy, x1 + dx, y1 + dy];
      drawSpacing(guides, [...g.spacing.marks(even.x, now), ...g.spacing.marks(even.y, now)], 1 / unit(), S);
    }
    g.dx = dx; g.dy = dy;
    g.copy = event.altKey;
    live = new Map();
    previews.replaceChildren();
    putBack();
    if (g.copy) {
      // ⌥: a copy goes, the shapes stay.
      g.indices.forEach((index, n) => {
        const node = S("g", { opacity: 0.85 });
        const spec = F.moved(g.originals[n], dx, dy);
        node.innerHTML = F.svg(spec, geometryOf(index, spec), roles());
        previews.append(node);
      });
    } else {
      g.indices.forEach((index, n) => {
        live.set(index, F.moved(g.originals[n], dx, dy));
        setAside(index, { transform: `translate(${dx} ${dy})` });
      });
      followGlued(g.indices);
    }
    say(`${Math.round(g.box ? g.box[0] + dx : dx)}, ${Math.round(g.box ? g.box[1] + dy : dy)}`, event);
  }
  // Lines glued to what moves are drawn to where it is now.
  function followGlued(moved) {
    const names = new Set(moved.map((index) => specAt(index)).flatMap((spec) => namesIn(spec)));
    shapesOf().forEach((spec, index) => {
      if (!spec || moved.includes(index) || F.family(spec.kind) !== "line") return;
      if ([spec.from, spec.to].some((end) => isEnd(end) && end.shape !== undefined && names.has(String(end.shape)))) preview(index, spec);
    });
  }
  const namesIn = (spec) => (!spec ? [] : [...(spec.id !== undefined ? [String(spec.id)] : []), ...(spec.kind === "group" ? (spec.shapes || []).flatMap(namesIn) : [])]);

  // -- sizing --

  function startSize(event, indices, name) {
    const one = indices.length === 1 ? indices[0] : null;
    const made = one !== null ? geometryOf(one) : null;
    const box = one !== null && F.family(specAt(one).kind) !== "line" && specAt(one).kind !== "group" && specAt(one).kind !== "pen"
      ? made.box : (() => { const b = unionOf(indices); return [b[0], b[1], b[2] - b[0], b[3] - b[1]]; })();
    const turn = one !== null && made && specAt(one).kind !== "group" ? made.turn : 0;
    begin(event, { type: "size", indices, name, box, turn, centre: [box[0] + box[2] / 2, box[1] + box[3] / 2], originals: indices.map((index) => copyOf(shapesOf()[index])), single: one !== null && ["box", "text"].includes(F.family(specAt(one).kind)),
      path: one !== null && F.family(specAt(one).kind) === "path" });
    gesture.started = true;
    gesture.targets = snapTargets(indices);
    page()?.classList.add("shape-dragging");
  }
  function stepSize(g, point, event, free) {
    const [x, y, w, h] = g.box, name = g.name;
    const local = F.unturned(point, g.centre, g.turn);
    const fixed = event.altKey ? [x + w / 2, y + h / 2] : boxPoint(g.box, ({ n: "s", s: "n", e: "w", w: "e", ne: "sw", nw: "se", se: "nw", sw: "ne" })[name]);
    let left = x, right = x + w, top = y, bottom = y + h;
    const sides = { x: name.includes("e") || name.includes("w"), y: name.includes("n") || name.includes("s") };
    let px = local[0], py = local[1];
    if (!free && !g.turn) {
      if (sides.x) { const caught = catchAt([px], g.targets.xs); if (caught) { px += caught.gap; guide("x", caught.at); } }
      if (sides.y) { const caught = catchAt([py], g.targets.ys); if (caught) { py += caught.gap; guide("y", caught.at); } }
    }
    if (sides.x) { if (event.altKey) { left = fixed[0] - Math.abs(px - fixed[0]); right = fixed[0] + Math.abs(px - fixed[0]); } else { left = Math.min(px, fixed[0]); right = Math.max(px, fixed[0]); } }
    if (sides.y) { if (event.altKey) { top = fixed[1] - Math.abs(py - fixed[1]); bottom = fixed[1] + Math.abs(py - fixed[1]); } else { top = Math.min(py, fixed[1]); bottom = Math.max(py, fixed[1]); } }
    let width = Math.max(right - left, 1), height = Math.max(bottom - top, 1);
    if (event.shiftKey && sides.x && sides.y && w > 0 && h > 0) {
      // Its proportions kept: the larger change wins.
      const k = Math.max(width / w, height / h);
      width = w * k; height = h * k;
      if (!event.altKey) {
        left = name.includes("w") ? fixed[0] - width : fixed[0];
        top = name.includes("n") ? fixed[1] - height : fixed[1];
      } else { left = fixed[0] - width / 2; top = fixed[1] - height / 2; }
    }
    const fresh = [left, top, width, height];
    g.made = fresh;
    live = new Map();
    putBack();
    if (g.single) {
      const index = g.indices[0], spec = g.originals[0];
      // Its middle where the new box's is, on the slide (it turns about its own middle).
      const middle = turned([left + width / 2, top + height / 2], g.centre, g.turn);
      let resized = spec.kind === "text"
        ? { ...spec, at: rounded([middle[0] - width / 2, middle[1] - (measured(index)?.[1] || h) / 2]), width: round(width) }
        : { ...spec, at: rounded([middle[0] - width / 2, middle[1] - height / 2]), size: [round(width), round(height)] };
      // A zoom inset's region keeps the box's proportions: what it shows is never stretched.
      if (spec.kind === "inset") { const source = insetSource(spec); if (source) resized = I.matched(resized, source.box); }
      live.set(index, resized);
      if (spec.kind === "text") setAside(index, { transform: `translate(${resized.at[0] - spec.at[0]} 0)` });
      else preview(index, resized);
      say(`${Math.round(width)} × ${Math.round(spec.kind === "text" ? measured(index)?.[1] || h : height)}`, event);
    } else if (g.path) {
      // A path's points stretched in its own frame, its middle where the new box's is (it
      // turns about its own middle).
      const index = g.indices[0], middle = turned([left + width / 2, top + height / 2], g.centre, g.turn);
      const sx = w ? width / w : 1, sy = h ? height / h : 1, ox = middle[0] - (left + width / 2), oy = middle[1] - (top + height / 2);
      const resized = F.mapped(g.originals[0], ([px2, py2]) => [left + (px2 - x) * sx + ox, top + (py2 - y) * sy + oy]);
      live.set(index, resized);
      preview(index, resized);
      say(`${Math.round(width)} × ${Math.round(height)}`, event);
    } else {
      const sx = w ? width / w : 1, sy = h ? height / h : 1;
      const map = ([px2, py2]) => [round(left + (px2 - x) * sx), round(top + (py2 - y) * sy)];
      g.indices.forEach((index, n) => {
        const resized = F.mapped(g.originals[n], map);
        live.set(index, resized);
        preview(index, resized);
      });
      say(`${Math.round(width)} × ${Math.round(height)}`, event);
    }
    followGlued(g.indices);
  }

  // -- turning --

  function startTurn(event, indices) {
    const box = unionOf(indices);
    const one = indices.length === 1 ? indices[0] : null;
    const centre = one !== null && ["box", "text", "path"].includes(F.family(specAt(one).kind)) ? F.centreOf(geometryOf(one)) : [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
    begin(event, { type: "turn", indices, centre, originals: indices.map((index) => copyOf(shapesOf()[index])) });
    gesture.started = true;
    gesture.angle = Math.atan2(gesture.from[1] - centre[1], gesture.from[0] - centre[0]);
    gesture.was = one !== null ? Number(specAt(one).rotate || 0) : 0;
  }
  function stepTurn(g, point, event) {
    let turn = (Math.atan2(point[1] - g.centre[1], point[0] - g.centre[0]) - g.angle) * 180 / Math.PI;
    if (event.shiftKey) turn = Math.round((g.was + turn) / 15) * 15 - g.was;
    g.turn = turn;
    live = new Map();
    putBack();
    g.indices.forEach((index, n) => {
      const spec = g.originals[n];
      if (["box", "text", "path"].includes(F.family(spec.kind)) && g.indices.length === 1) {
        live.set(index, F.turnedAbout(spec, turn, g.centre));
        setAside(index, { transform: `rotate(${turn} ${g.centre[0]} ${g.centre[1]})` });
      } else {
        const made = F.turnedAbout(spec, turn, g.centre);
        live.set(index, made);
        if (spec.kind === "group" || !["box", "path"].includes(F.family(spec.kind))) preview(index, made); else setAside(index, { transform: `rotate(${turn} ${g.centre[0]} ${g.centre[1]})` });
      }
    });
    followGlued(g.indices);
    const shown = ((Math.round(g.was + turn) % 360) + 360) % 360;
    say(`${shown}°`, event);
  }
  function straighten(indices) {
    edit((list) => { for (const index of indices) if (list[index]) delete list[index].rotate; }, "Rotate Shape");
  }

  // -- a line's ends, a polyline's points, a shape's own handles --

  function startEnd(event, index, which) {
    begin(event, { type: "end", indices: [index], index, which, originals: [copyOf(shapesOf()[index])] });
    gesture.started = true;
    gesture.targets = snapTargets([index]);
  }
  // What a line's end let go at `point` is glued to: a shape, or else what the page holds (an
  // object, a part, the smallest of them it is in -- a piece of one under the pointer before
  // the part), at the site nearest the pointer -- a side's middle, or its centre -- else
  // nothing.
  function glueAt(point, own, event) {
    // (Snapping off, or ⌘ held while it is on: nothing is glued -- nor looked for.)
    if (Snap.free(event)) return null;
    const reach = 10 / unit();
    let best = null;
    const consider = (target, glue) => {
      const sites = F.sites(target), inside = target.traced ? F.over(target, point) : target.outline ? F.inside(target.outline, point) : within(target.box, target.turn, point);
      const area = Math.max(target.box[2] * target.box[3], 0);
      for (const [side, at] of Object.entries(sites)) {
        const far = distance(at, point);
        if (!(far <= reach || inside)) continue;
        // (In two -- a part and the group round it -- the smaller; else the nearer site.)
        const better = !best || (inside && best.inside && area < best.area - 1e-6) || (inside && !best.inside)
          || (Boolean(inside) === Boolean(best.inside) && Math.abs(area - best.area) < 1e-6 && far < best.far)
          || (!inside && !best.inside && far < best.far);
        if (better) best = { far, side, at, glue, target, inside, area };
      }
    };
    shapesOf().forEach((spec, index) => {
      if (!spec || index === own || F.family(spec.kind) === "line" || (F.family(spec.kind) === "points" && !spec.closed)) return;
      consider(F.targetOf(spec, geometryOf(index)), { index });
    });
    if (!best) {
      const piece = event ? host.pieceAt?.(event, screenToFrame) : null;
      if (piece) consider(piece, { [glueKey]: piece.name });
      for (const [name, object] of objectsNow()) consider(object, { [glueKey]: name });
    }
    if (!best) return null;
    return best;
  }
  // What the page holds an end is glued to, by name, as it is called ("Encoder", "List").
  const heldName = (glue) => objectsNow().get(String(glue[glueKey]))?.label || host.pieceLabel?.(glue[glueKey]) || (noun === "figure" ? "Part" : "Object");
  function within([x, y, w, h], turn, point) {
    const local = F.unturned(point, [x + w / 2, y + h / 2], turn || 0);
    return local[0] >= x && local[0] <= x + w && local[1] >= y && local[1] <= y + h;
  }
  function showGlue(found) {
    if (!found) return;
    const px = 1 / unit(), target = found.target, [x, y, w, h] = target.box;
    const corners = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]].map((p) => turned(p, [x + w / 2, y + h / 2], target.turn));
    guides.append(S("polygon", { points: corners.map((p) => p.join(",")).join(" "), class: "shape-target", "stroke-width": 1.5 * px }));
    for (const [side, at] of Object.entries(F.sites(target))) guides.append(S("circle", { cx: at[0], cy: at[1], r: (side === found.side ? 4.5 : 3) * px, class: `shape-site${side === found.side ? " on" : ""}`, "stroke-width": px }));
  }
  function stepEnd(g, point, event, free) {
    const spec = g.originals[0], other = F.pointOf(spec[g.which === "from" ? "to" : "from"]);
    const otherNow = geometryOf(g.index, spec)?.ends?.[g.which === "from" ? 1 : 0] || other;
    let at = point;
    if (event.shiftKey) {
      // Along one of eight ways from its other end.
      const angle = Math.round(Math.atan2(at[1] - otherNow[1], at[0] - otherNow[0]) / (Math.PI / 4)) * (Math.PI / 4), length = distance(at, otherNow);
      at = [otherNow[0] + Math.cos(angle) * length, otherNow[1] + Math.sin(angle) * length];
    }
    const found = event.shiftKey ? null : glueAt(at, g.index, event);
    g.glue = found;
    if (found) { at = found.at; showGlue(found); }
    else if (!free) {
      const across = catchAt([at[0]], g.targets.xs), down = catchAt([at[1]], g.targets.ys);
      if (across) { at = [at[0] + across.gap, at[1]]; guide("x", across.at); }
      if (down) { at = [at[0], at[1] + down.gap]; guide("y", down.at); }
    }
    g.at = at;
    const made = { ...spec, [g.which]: rounded(at) };
    live = new Map([[g.index, made]]);
    putBack();
    preview(g.index, made);
    say(found ? `Join to ${found.glue[glueKey] !== undefined ? heldName(found.glue) : shapeLabel(shapesOf()[found.glue.index])}${found.side === "centre" ? "" : ` · ${found.side}`}` : `${Math.round(distance(at, otherNow))} pt`, event);
  }
  function startPoint(event, index, n) {
    begin(event, { type: "point", indices: [index], index, n, originals: [copyOf(shapesOf()[index])] });
    gesture.started = true;
    gesture.targets = snapTargets([index]);
  }
  function stepPoint(g, point, event, free) {
    let at = point;
    if (!free) {
      const across = catchAt([at[0]], g.targets.xs), down = catchAt([at[1]], g.targets.ys);
      if (across) { at = [at[0] + across.gap, at[1]]; guide("x", across.at); }
      if (down) { at = [at[0], at[1] + down.gap]; guide("y", down.at); }
    }
    const spec = g.originals[0], points = spec.points.map((p) => [...p]);
    points[g.n] = rounded(at);
    const made = { ...spec, points };
    live = new Map([[g.index, made]]);
    putBack();
    preview(g.index, made);
  }
  function startAdjust(event, index, adjust) {
    begin(event, { type: "adjust", indices: [index], index, adjust, originals: [copyOf(shapesOf()[index])] });
    gesture.started = true;
  }
  function stepAdjust(g, point, event, free) {
    const values = g.adjust.set(point, free, event);
    const made = { ...g.originals[0], ...values };
    g.values = values;
    live = new Map([[g.index, made]]);
    putBack();
    preview(g.index, made);
    followGlued([g.index]);
    const shown = Object.entries(values).filter(([key]) => !["tail", "region", "size"].includes(key)).map(([key, value]) => `${keyName(key)} ${Array.isArray(value) ? "" : value}`).join(" · ");
    if (shown) say(shown, event);
  }
  const keyName = (key) => ({ corner: "Corner", apex: "Top", slant: "Slant", inset: "Inset", point: "Point", arm: "Arms", ratio: "Points", head: "Head", shaft: "Shaft", bend: "Bend", lean: "Lean", elbow: "Middle", tip: "Tip", depth: "Depth" })[key] || key;

  // Each drag made a step of its own, named for what it did.
  function commit(g) {
    if (g.type === "move") {
      const { dx = 0, dy = 0 } = g;
      if (!dx && !dy) { putBack(); live = new Map(); place(); return; }
      const count = g.indices.length;
      if (g.copy) {
        const made = g.originals.map((_, n) => shapesOf().length + n);
        edit((list) => {
          const taken = allIds(list), copies = g.originals.map((spec) => renamed(F.moved(spec, dx, dy), taken));
          return [...list, ...copies];
        }, `Duplicate ${plural(count)}`, { after: made });
        mark(g.indices, made);
        return;
      }
      edit((list) => { g.indices.forEach((index, n) => { list[index] = withPlaces(F.moved(g.originals[n], round(dx), round(dy))); }); },
        `Move ${plural(count)}`);
      return;
    }
    if (g.type === "size") {
      const changed = g.indices.map((index) => live.get(index)).filter(Boolean);
      if (!changed.length) return;
      edit((list) => { g.indices.forEach((index) => { if (live.has(index)) list[index] = live.get(index); }); }, `Resize ${plural(g.indices.length)}`);
      return;
    }
    if (g.type === "turn") {
      if (!g.turn) { putBack(); place(); return; }
      edit((list) => { g.indices.forEach((index) => { if (live.has(index)) list[index] = live.get(index); }); }, `Rotate ${plural(g.indices.length)}`);
      return;
    }
    if (g.type === "end") {
      const spec = copyOf(g.originals[0]);
      let end = rounded(g.at || F.pointOf(spec[g.which]));
      let named = null;
      const found = g.glue, onto = found?.glue;
      if (found) {
        if (onto[glueKey] !== undefined) end = { [glueKey]: onto[glueKey], side: found.side, at: rounded(found.at) };
        else {
          const target = shapesOf()[onto.index];
          named = target.id !== undefined ? String(target.id) : uniqueId(target.kind, allIds());
          end = { shape: named, side: found.side, at: rounded(found.at) };
        }
      }
      edit((list) => {
        if (onto?.index !== undefined && list[onto.index] && list[onto.index].id === undefined) list[onto.index] = { id: named, ...list[onto.index] };
        list[g.index] = { ...spec, [g.which]: end };
      }, found ? "Join Line" : "Move Line End");
      return;
    }
    if (g.type === "point") {
      edit((list) => { list[g.index] = live.get(g.index); }, "Move Point");
      return;
    }
    if (g.type === "adjust" && g.values) {
      edit((list) => { list[g.index] = { ...list[g.index], ...g.values }; }, g.adjust.label || "Change Shape");
    }
  }
  // A glued end's place kept as it is now (for when what it is glued to is gone).
  function withPlaces(spec) {
    if (F.family(spec.kind) !== "line" || (!isEnd(spec.from) && !isEnd(spec.to))) return spec;
    const made = F.geometry(spec, F.glued(spec, find));
    const out = { ...spec };
    ["from", "to"].forEach((key, n) => { if (isEnd(spec[key])) out[key] = { ...spec[key], at: rounded(made.ends[n]) }; });
    return out;
  }

  // -- ids --

  const SHORT = { rectangle: "box", "rounded-rectangle": "box", ellipse: "oval", "right-triangle": "triangle", "double-arrow": "arrow", "curved-arrow": "arrow",
    "arrow-right": "arrow", "arrow-left": "arrow", "arrow-up": "arrow", "arrow-down": "arrow", "arrow-left-right": "arrow", "scale-bar": "scale", text: "text" };
  function uniqueId(kind, taken) {
    const base = SHORT[kind] || String(kind || "shape").replace(/[^a-z]/g, "");
    let n = 1;
    while (taken.has(`${base}${n}`)) n += 1;
    taken.set(`${base}${n}`, []);
    return `${base}${n}`;
  }
  // A copy given ids of its own where its own are taken, its lines glued among themselves.
  function renamed(spec, taken) {
    const names = new Map();
    const walk = (item) => {
      if (item.id !== undefined && taken.has(String(item.id))) names.set(String(item.id), uniqueId(item.kind, taken));
      else if (item.id !== undefined) taken.set(String(item.id), []);
      if (item.kind === "group") (item.shapes || []).forEach(walk);
    };
    walk(spec);
    const apply = (item) => {
      const out = { ...item };
      if (out.id !== undefined && names.has(String(out.id))) out.id = names.get(String(out.id));
      for (const key of ["from", "to"]) if (isEnd(out[key]) && out[key].shape !== undefined && names.has(String(out[key].shape))) out[key] = { ...out[key], shape: names.get(String(out[key].shape)) };
      if (out.kind === "group") out.shapes = (out.shapes || []).map(apply);
      return out;
    };
    return apply(spec);
  }

  // -- drawing a new shape --

  function arm(kind) {
    closeWords();
    tools?.points.leave();
    tool = { kind };
    page()?.classList.add("shape-drawing");
    // (The pen draws a path point by point: pathtools.js.)
    if (kind === "path") { paths().pen.arm(); return; }
    const label = F.LABELS[kind];
    toast(kind === "polyline" ? `${label}: click each point, and double-click (or Return) at the last · Esc to stop`
      : kind === "pen" ? `${label}: draw on the ${noun} · Esc to stop`
        : host.armHint?.(kind, label) || `${label}: drag on the ${noun} to draw it, or click for its usual size · Esc to stop`, { icon: "shape", seconds: 3 });
  }
  function disarm() {
    if (tool?.kind === "path") tools?.pen.stop();
    tool = null;
    page()?.classList.remove("shape-drawing");
  }
  let drawingNow = false;
  function startDraw(event) {
    const kind = tool.kind, point = toFrame(event);
    if (kind === "polyline" && gesture?.type === "draw") return;
    drawingNow = true;
    begin(event, { type: "draw", kind, indices: [], points: [point], press: { clientX: event.clientX, clientY: event.clientY, target: event.target } });
    gesture.targets = snapTargets([]);
    if (kind === "polyline") gesture.started = true;
    event.preventDefault();
  }
  function caught(point, g, free) {
    if (free) return point;
    let [x, y] = point;
    const across = catchAt([x], g.targets.xs), down = catchAt([y], g.targets.ys);
    if (across) { x += across.gap; guide("x", across.at); }
    if (down) { y += down.gap; guide("y", down.at); }
    return [x, y];
  }
  function drawnSpec(g, point, event, free) {
    const kind = g.kind, form = F.family(kind), start = g.points[0];
    if (kind === "pen") return { kind, points: g.points.map(rounded) };
    if (kind === "polyline") return { kind, points: [...g.points, point].map(rounded) };
    if (form === "line") {
      let end = point;
      if (event.shiftKey) {
        const angle = Math.round(Math.atan2(end[1] - start[1], end[0] - start[0]) / (Math.PI / 4)) * (Math.PI / 4), length = distance(end, start);
        end = [start[0] + Math.cos(angle) * length, start[1] + Math.sin(angle) * length];
      } else end = caught(end, g, free);
      return { kind, from: rounded(start), to: rounded(end) };
    }
    let [x0, y0] = start, [x1, y1] = caught(point, g, free);
    let w = Math.abs(x1 - x0), h = Math.abs(y1 - y0);
    if (event.shiftKey) { const side = Math.max(w, h); w = h = side; x1 = x0 + Math.sign(x1 - x0 || 1) * side; y1 = y0 + Math.sign(y1 - y0 || 1) * side; }
    let left = Math.min(x0, x1), top = Math.min(y0, y1);
    if (event.altKey) { left = x0 - w; top = y0 - h; w *= 2; h *= 2; }
    if (kind === "text") return { kind, at: rounded([left, top]), width: round(Math.max(w, 40)) };
    return { kind, at: rounded([left, top]), size: [round(Math.max(w, 1)), round(Math.max(h, 1))] };
  }
  function stepDraw(g, point, event, free) {
    if (g.kind === "pen") g.points.push(point);
    const spec = drawnSpec(g, point, event, free);
    if (F.family(g.kind) === "line") {
      const found = glueAt(spec.to, -1, event);
      g.glueEnd = found;
      if (found) { spec.to = rounded(found.at); showGlue(found); }
      if (!g.glueStart) g.glueStart = glueAt(spec.from, -1, event);
    }
    g.spec = spec;
    previews.replaceChildren();
    const node = S("g");
    node.innerHTML = F.svg(spec, F.geometry(spec), roles());
    previews.append(node);
    if (spec.size) say(`${Math.round(spec.size[0])} × ${Math.round(spec.size[1])}`, event);
    else if (spec.from) say(`${Math.round(distance(spec.from, spec.to))} pt`, event);
  }
  function drawingDone() {
    drawingNow = false;
    previews.replaceChildren();
    if (tool?.kind !== "polyline" || !gesture) disarm();
  }
  // Let go: the shape is made -- its usual size about where it was clicked, a polyline only
  // once it is ended (a double-click, Return).
  function commitDraw(g, event) {
    const kind = g.kind;
    if (kind === "polyline") {
      const point = toFrame(event);
      if (g.points.length > 1 && distance(point, g.points[g.points.length - 1]) < 3 / unit()) { polylineDone(g); return; }
      g.points.push(point);
      g.started = true;
      gesture = g;
      window.addEventListener("pointermove", moveGesture);
      window.addEventListener("pointerup", endGesture);
      window.addEventListener("pointercancel", cancelGesture);
      window.addEventListener("keydown", polylineKey, true);
      window.addEventListener("dblclick", polylineDouble, true);
      return;
    }
    drawingNow = false;
    disarm();
    host.swallowRelease();
    // A click (no drag) makes it its usual size there -- or, on what the page holds that it
    // may be drawn round (a figure's part, for a ring), round that (the host's).
    let spec = g.started && g.spec ? g.spec : host.drawnAt?.(kind, g.points[0], g.press) || usual(kind, g.points[0]);
    if (kind === "pen") {
      const points = F.simplified(g.points, 1.2 / Math.max(unit(), 0.2));
      if (points.length < 2) { previews.replaceChildren(); return; }
      spec = { kind, points: points.map(rounded) };
    }
    if (F.family(kind) === "line" && g.started) {
      const taken = allIds();
      const ends = [["from", g.glueStart], ["to", g.glueEnd]];
      const names = {};
      for (const [key, found] of ends) {
        if (!found) continue;
        if (found.glue[glueKey] !== undefined) spec[key] = { [glueKey]: found.glue[glueKey], side: found.side, at: rounded(found.at) };
        else {
          const target = shapesOf()[found.glue.index];
          const name = target.id !== undefined ? String(target.id) : names[found.glue.index] || uniqueId(target.kind, taken);
          names[found.glue.index] = name;
          spec[key] = { shape: name, side: found.side, at: rounded(found.at) };
        }
      }
      add(spec, names);
    } else add(spec);
    previews.replaceChildren();
  }
  function usual(kind, at) {
    const size = F.SIZES[kind] || [160, 100], form = F.family(kind);
    if (form === "line") {
      const [dx, dy] = size;
      return kind === "brace" || kind === "bracket" ? { kind, from: rounded([at[0], at[1] - dy / 2]), to: rounded([at[0], at[1] + dy / 2]) }
        : { kind, from: rounded([at[0] - dx / 2, at[1] - dy / 2]), to: rounded([at[0] + dx / 2, at[1] + dy / 2]) };
    }
    if (form === "points") return { kind, points: [rounded([at[0] - 80, at[1] + 20]), rounded([at[0], at[1] - 20]), rounded([at[0] + 80, at[1] + 20])] };
    if (kind === "text") return { kind, at: rounded([at[0], at[1] - 14]) };
    return { kind, at: rounded([at[0] - size[0] / 2, at[1] - size[1] / 2]), size: [...size] };
  }
  function polylineKey(event) {
    if (!gesture || gesture.kind !== "polyline") return;
    if (event.key === "Enter" || event.key === "Return") { event.preventDefault(); event.stopPropagation(); const g = gesture; finish(); polylineDone(g); }
    else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); finish(); polylineOff(); previews.replaceChildren(); disarm(); drawingNow = false; host.swallowRelease(true); }
  }
  function polylineDouble(event) {
    if (!gesture || gesture.kind !== "polyline") return;
    event.preventDefault();
    event.stopPropagation();
    const g = gesture;
    finish();
    polylineDone(g);
  }
  function polylineOff() {
    window.removeEventListener("keydown", polylineKey, true);
    window.removeEventListener("dblclick", polylineDouble, true);
  }
  function polylineDone(g) {
    polylineOff();
    finish();
    drawingNow = false;
    disarm();
    previews.replaceChildren();
    // (The double-click's own two clicks added the last point twice: once is kept.)
    const points = g.points.filter((point, n) => n === 0 || distance(point, g.points[n - 1]) > 1.5 / unit());
    if (points.length < 2) return;
    add({ kind: "polyline", points: points.map(rounded) });
  }
  // A shape added, chosen, its words ready to type when it is words. (The host may attach
  // it to what it is drawn on: a figure's part, which it then moves with.)
  function add(spec, names = {}) {
    const label = `${verb} ${shapeLabel(spec)}`;
    const index = shapesOf().length;
    spec = host.attachNew?.(spec) || spec;
    host.leaveOthers();
    edit((list) => {
      for (const [at, name] of Object.entries(names)) if (list[at] && list[at].id === undefined) list[at] = { id: name, ...list[at] };
      return [...list, spec];
    }, label, { after: [index] });
    mark([], [index]);
    host.reportFocus();
    fresh = { slide: slideIndex(), index, entry: studio.past[studio.past.length - 1], length: studio.past.length, label };
    if (spec.kind === "text") editWords(index, { fresh: true });
  }

  // -- words typed in a shape --

  function editWords(index, { selectAll = false, replaceWith = null, point = null } = {}) {
    closeWords();
    const spec = shapesOf()[index];
    if (!spec || spec.kind === "group") return;
    const options = { value: String(spec.text ?? ""), palette: studio.info?.palette || {}, placeholder: spec.kind === "text" ? "Text" : "", room: () => host.stage.getBoundingClientRect() };
    const area = host.words ? host.words(options) : plainWords(options);
    const node = h(`div.inline-editor.in-place.shape-words${host.words ? "" : ".plain"}`, { onmousedown: (event) => event.stopPropagation(), title: "Esc or ⌘Return: done" }, area);
    const session = Date.now(), slideNow = slideIndex();
    const merge = `shape-words-${slideNow}-${index}-${session}`;
    area.addEventListener("input", () => {
      const value = area.value;
      host.edit((list) => { const item = list[index]; if (!item) return list; if (value) item.text = value; else delete item.text; return list; },
        { quiet: true, merge, hold: true, ...(host.wordsLabel ? { label: host.wordsLabel(spec) } : {}) });
    });
    area.addEventListener("keydown", (event) => {
      if (event.key === "Escape" || (event.key === "Enter" && (event.metaKey || event.ctrlKey) && !event.isComposing)) {
        event.preventDefault();
        event.stopPropagation();
        closeWords({ keep: true });
      }
    });
    words = { node, area, index, slide: slideNow };
    host.center.append(node);
    placeWords();
    area.focus();
    if (replaceWith !== null) { area.value = replaceWith; area.dispatchEvent(new Event("input", { bubbles: true })); area.caretToEnd?.(); }
    else if (selectAll) area.selectAll?.();
    else if (!(point && area.selectWordAt?.(point))) area.caretToEnd?.();
    setTimeout(() => document.addEventListener("mousedown", outside, true), 0);
    marks.replaceChildren();
    handles.replaceChildren();
    host.reportFocus();
  }
  function outside(event) {
    if (!words || words.node.contains(event.target) || event.target.closest?.(".rt-bar, .menu, .popover")) return;
    closeWords({ keep: true });
  }
  function closeWords({ keep = false } = {}) {
    if (!words) return;
    document.removeEventListener("mousedown", outside, true);
    const was = words;
    words = null;
    was.node.remove();
    page()?.querySelector(`[id="${CSS.escape(`${idOf(was.index, was.slide)}.text`)}"]`)?.style.removeProperty("visibility");
    page()?.querySelector(`[id="${CSS.escape(`${idOf(was.index, was.slide)}.label`)}"]`)?.style.removeProperty("visibility");
    if (studio.lastMerge) studio.step();
    // A box of words just made, left with none: it goes, as Keynote's does.
    const spec = shapesOf()[was.index];
    if (fresh && fresh.slide === was.slide && fresh.index === was.index && spec?.kind === "text" && !String(spec.text ?? "").trim()) {
      const { entry, length, label } = fresh;
      fresh = null;
      // (Its adding the last change -- or, for a host whose changes land later, the one change
      // made since -- it is taken back, as if never drawn.)
      const top = studio.past[studio.past.length - 1];
      if (top === entry && !host.later) { studio.undo(); studio.future.pop(); }
      else if (host.later && studio.past.length === length + 1 && top?.label === label) { studio.undo(); studio.future.pop(); }
      else edit((list) => { list.splice(was.index, 1); }, "Delete Text Box", { after: [] });
      chosen = [];
      host.renderInspector();
      place();
      return;
    }
    fresh = null;
    if (keep && was.slide === slideIndex()) choose([was.index]);
    else place();
  }
  function placeWords() {
    if (!words) return;
    const index = words.index, spec = F.normalised(shapesOf()[index] || {}), made = geometryOf(index);
    if (!made) return;
    const px = unit(), centre = F.centreOf(made);
    const size = spec.font_size || host.wordSize(spec);
    let box = made.area, turn = made.turn, pivot = centre;
    if (!box) {
      // A line's words, beside it, where the slide set them -- or would.
      const label = drawnOf(index)?.getAttribute("data-flexo-label")?.split(" ").map(Number);
      if (label?.length === 7) { box = label.slice(0, 4); turn = label[4]; pivot = [label[5], label[6]]; }
      else { const at = made.label || { x: centre[0], y: centre[1] }; box = [at.x - 60, at.y - size, 120, size * 1.6]; turn = 0; pivot = [at.x, at.y]; }
    }
    if (spec.kind === "text") box = [box[0], box[1], Math.max(box[2], spec.width || 0), box[3]];
    const [x, y, w, h] = box, middle = turned([x + w / 2, y + h / 2], pivot, turn), screen = toScreen(middle);
    const outer = host.center.getBoundingClientRect();
    const fonts = host.fonts?.() || studio.info?.fonts || {};
    const ink = spec.colour ? F.paintOf(spec.colour, roles()) : roles().ink || "#222";
    Object.assign(words.node.style, { left: `${screen[0] - outer.left - (w * px) / 2}px`, top: `${screen[1] - outer.top - (h * px) / 2}px`,
      width: `${w * px}px`, minHeight: `${h * px}px`, transform: turn ? `rotate(${turn}deg)` : "", transformOrigin: "50% 50%" });
    words.node.classList.toggle("middle", spec.valign === "middle" && Boolean(made.area));
    words.node.classList.toggle("bottom", spec.valign === "bottom" && Boolean(made.area));
    Object.assign(words.area.style, { fontSize: `${size * px}px`, fontFamily: spec.font || fonts.body || "", color: ink,
      fontWeight: spec.bold ? "700" : "", fontStyle: spec.italic ? "italic" : "",
      textAlign: { start: "left", middle: "center", end: "right" }[spec.align] || "center", padding: `${Number(spec.padding ?? 5) * px}px` });
    page()?.querySelector(`[id="${CSS.escape(`${idOf(index)}.text`)}"]`)?.style.setProperty("visibility", "hidden");
  }

  // -- the keys --

  function key(event) {
    const mod = event.metaKey || event.ctrlKey, k = event.key;
    if (tool && k === "Escape") { disarm(); return true; }
    const picks = chosenNow();
    if (!picks.length) return false;
    if (mod && !event.altKey && k.toLowerCase() === "g" && !event.shiftKey) { group(); return true; }
    if (mod && k.toLowerCase() === "g" && event.shiftKey) { ungroup(); return true; }
    if (mod && k.toLowerCase() === "d") { duplicate(); return true; }
    // ⇧⌘A, Inkscape's: Align and Distribute, in the inspector (aligntools.js).
    if (mod && event.shiftKey && !event.altKey && k.toLowerCase() === "a") { arranging.reveal(); return true; }
    if (mod && k.toLowerCase() === "a") { choose(shapesOf().map((_, n) => n).filter((n) => shapesOf()[n])); return true; }
    if (mod && k.toLowerCase() === "l") { lock(!event.altKey); return true; }
    // ⌥⌘C and ⌥⌘V (by the key's place: ⌥ makes another letter of it): Copy and Paste Style.
    if (mod && event.altKey && !event.shiftKey && event.code === "KeyC") { copyStyle(); return true; }
    if (mod && event.altKey && !event.shiftKey && event.code === "KeyV") { pasteStyle(); return true; }
    if (mod && event.shiftKey && k.toLowerCase() === "f") { order(event.altKey ? "forward" : "front"); return true; }
    if (mod && event.shiftKey && k.toLowerCase() === "b") { order(event.altKey ? "backward" : "back"); return true; }
    if (mod) return false;
    if (k.startsWith("Arrow")) {
      const by = event.shiftKey ? 10 : 1;
      const [dx, dy] = { ArrowLeft: [-by, 0], ArrowRight: [by, 0], ArrowUp: [0, -by], ArrowDown: [0, by] }[k];
      nudge(dx, dy);
      return true;
    }
    if (k === "Backspace" || k === "Delete") { remove(); return true; }
    if (k === "Escape") { clear(); return true; }
    if (k === "Tab") {
      const list = shapesOf().map((_, n) => n).filter((n) => shapesOf()[n]);
      const at = list.indexOf(picks[picks.length - 1]);
      choose([list[(at + (event.shiftKey ? -1 : 1) + list.length) % list.length]]);
      return true;
    }
    const one = picks.length === 1 ? shapesOf()[picks[0]] : null;
    if (one && !one.locked && one.kind !== "group" && k === "Enter") { editWords(picks[0], { selectAll: true }); return true; }
    if (one && !one.locked && one.kind !== "group" && [...k].length === 1 && !event.altKey && (F.isClosed(one) || one.kind === "text")) { editWords(picks[0], { replaceWith: k }); return true; }
    return false;
  }
  // Nudged by the arrows: one step in the history however many presses, as an object's are.
  let nudged = null;
  function nudge(dx, dy) {
    const picks = chosenNow().filter((index) => !shapesOf()[index]?.locked);
    if (!picks.length) return;
    const run = nudged && nudged.slide === slideIndex() && nudged.key === picks.join(",") && Date.now() - nudged.at < 1500 ? nudged : { slide: slideIndex(), key: picks.join(","), id: Date.now() };
    run.at = Date.now();
    nudged = run;
    edit((list) => { for (const index of picks) list[index] = withPlaces(F.moved(list[index], dx, dy)); }, `Move ${plural(picks.length)}`, { merge: `shape-nudge-${run.id}` });
  }

  // -- the arrangement --

  function remove(done = "deleted") {
    const picks = chosenNow();
    if (!picks.length) return;
    const gone = new Set(picks.flatMap((index) => namesIn(shapesOf()[index])));
    const count = picks.length, called = count === 1 ? shapeLabel(shapesOf()[picks[0]]) : plural(count);
    edit((list) => {
      // Lines glued to what goes stay where they were drawn, glued no more.
      const kept = list.map((spec, index) => (picks.includes(index) || !spec ? spec : unglued(spec, gone, index)));
      return kept.filter((_, index) => !picks.includes(index));
    }, `${done === "cut" ? "Cut" : "Delete"} ${called}`, { after: [] });
    host.undoNote(`${called} ${done}`, { icon: done === "cut" ? "cut" : "trash" });
    host.reportFocus();
  }
  function unglued(spec, gone, index) {
    if (F.family(spec.kind) !== "line") return spec;
    const made = geometryOf(index);
    const out = { ...spec };
    ["from", "to"].forEach((key, n) => { if (isEnd(spec[key]) && spec[key].shape !== undefined && gone.has(String(spec[key].shape))) out[key] = rounded(made?.ends?.[n] || F.pointOf(spec[key])); });
    return out;
  }
  function duplicate() {
    const picks = chosenNow();
    if (!picks.length) return;
    const made = picks.map((_, n) => shapesOf().length + n);
    edit((list) => {
      const taken = allIds(list);
      const copies = picks.map((index) => renamed(F.moved(list[index], 12, 12), taken));
      return [...list, ...copies];
    }, `Duplicate ${picks.length === 1 ? shapeLabel(shapesOf()[picks[0]]) : plural(picks.length)}`, { after: made });
    mark(picks, made);
    host.reportFocus();
  }
  function order(how) {
    const picks = chosenNow();
    if (!picks.length) return;
    const list = shapesOf().map((spec, index) => ({ spec, index }));
    const mine = list.filter((item) => picks.includes(item.index)), rest = list.filter((item) => !picks.includes(item.index));
    let next;
    if (how === "front") next = [...rest, ...mine];
    else if (how === "back") next = [...mine, ...rest];
    else {
      next = [...list];
      const forward = how === "forward";
      const indices = forward ? [...next.keys()].reverse() : [...next.keys()];
      for (const n of indices) {
        const m = n + (forward ? 1 : -1);
        if (m < 0 || m >= next.length) continue;
        if (picks.includes(next[n].index) && !picks.includes(next[m].index)) [next[n], next[m]] = [next[m], next[n]];
      }
    }
    const after = next.map((item, n) => (picks.includes(item.index) ? n : -1)).filter((n) => n >= 0);
    if (after.every((n, k) => n === picks[k])) return;
    const label = { front: "Bring to Front", back: "Send to Back", forward: "Bring Forward", backward: "Send Backward" }[how];
    edit(() => next.map((item) => item.spec), label, { after });
  }
  function group() {
    const picks = chosenNow();
    if (picks.length < 2) return;
    const list = shapesOf();
    const top = Math.max(...picks);
    // (Its shapes say nothing of the page of their own: the group says it for them.)
    const own = (spec) => Object.fromEntries(Object.entries(spec).filter(([key]) => !ownKeys.includes(key)));
    const made = { kind: "group", shapes: picks.map((index) => own(list[index])), ...(host.grouped ? host.grouped(picks.map((index) => list[index])) : {}) };
    const at = top - (picks.length - 1);
    edit((all) => { const kept = all.filter((_, index) => !picks.includes(index)); kept.splice(at, 0, made); return kept; }, "Group", { after: [at] });
  }
  function ungroup() {
    const picks = chosenNow().filter((index) => shapesOf()[index]?.kind === "group");
    if (!picks.length) return;
    const list = shapesOf();
    const next = [], after = [];
    list.forEach((spec, index) => {
      if (!picks.includes(index)) { next.push(spec); return; }
      for (const child of spec.shapes || []) {
        after.push(next.length);
        next.push({ ...child, ...(host.ungrouped ? host.ungrouped(spec, child) : {}) });
      }
    });
    edit(() => next, "Ungroup", { after });
  }
  function lock(on) {
    const picks = chosenNow();
    if (!picks.length) return;
    edit((list) => { for (const index of picks) { if (on) list[index].locked = true; else delete list[index].locked; } }, on ? `Lock ${plural(picks.length)}` : `Unlock ${plural(picks.length)}`);
  }
  // Align and Distribute (aligntools.js, its sums aligning.js's): those chosen lined up with
  // what Relative to says -- their bounds, the first or last chosen, the biggest, the smallest,
  // the page; one alone, the page -- or beside it; three or more spaced evenly (`way`: across,
  // down, or by their edges or middles), a gap apart, or in a grid. Locked ones stay.
  const arranging = alignTools({
    picks: () => { const now = chosenNow(); return [...picked.filter((index) => now.includes(index)), ...now.filter((index) => !picked.includes(index))]; },
    box: (index) => boundsOf(index), locked: (index) => shapesOf()[index]?.locked, name: (index) => shapeLabel(shapesOf()[index]),
    frame: () => frameOf(), noun,
    move: (list, index, dx, dy) => { list[index] = withPlaces(F.moved(list[index], round(dx), round(dy))); },
    edit: (mutate, label) => edit(mutate, label), renderInspector: () => host.renderInspector(), showPanel: () => host.showPanel?.(),
  });
  function align(side) { return arranging.align(side); }
  function distribute(way) { return arranging.distribute(way); }
  function flip(way) {
    const picks = chosenNow().filter((index) => !shapesOf()[index]?.locked);
    if (!picks.length) return;
    const box = unionOf(picks), cx = (box[0] + box[2]) / 2, cy = (box[1] + box[3]) / 2;
    const across = way === "horizontal";
    const mirror = (spec) => {
      if (spec.kind === "group") return { ...spec, shapes: (spec.shapes || []).map(mirror) };
      const form = F.family(spec.kind);
      if ((form === "box" && spec.kind !== "bubble" && spec.kind !== "inset") || form === "path") {
        const made = F.geometry(spec), centre = F.centreOf(made);
        const now = across ? [2 * cx - centre[0], centre[1]] : [centre[0], 2 * cy - centre[1]];
        const moved = F.moved(spec, round(now[0] - centre[0]), round(now[1] - centre[1]));
        const flips = { horizontal: [true, false], vertical: [false, true], both: [true, true] }[spec.flip] || [false, false];
        if (across) flips[0] = !flips[0]; else flips[1] = !flips[1];
        const named = flips[0] && flips[1] ? "both" : flips[0] ? "horizontal" : flips[1] ? "vertical" : null;
        const out = { ...moved, ...(named ? { flip: named } : {}) };
        if (!named) delete out.flip;
        if (spec.rotate) out.rotate = round((360 - Number(spec.rotate)) % 360);
        return out;
      }
      const out = F.mapped(spec, ([x, y]) => rounded(across ? [2 * cx - x, y] : [x, 2 * cy - y]), { box: form !== "text" && spec.kind !== "bubble" ? true : false });
      if (spec.kind === "bubble" || form === "text") {
        const made = F.geometry(spec), centre = F.centreOf(made), now = across ? [2 * cx - centre[0], centre[1]] : [centre[0], 2 * cy - centre[1]];
        return F.moved({ ...out, at: spec.at }, round(now[0] - centre[0]), round(now[1] - centre[1]));
      }
      if (["brace", "bracket"].includes(spec.kind)) out.depth = -Number(F.normalised(spec).depth);
      return out;
    };
    edit((list) => { for (const index of picks) list[index] = mirror(list[index]); }, across ? "Flip Horizontally" : "Flip Vertically");
  }

  // Copy Style: how the one chosen is drawn, to put on others (here, on another page, on a
  // figure's parts). Paste Style: what was copied put on those chosen, one step.
  function copyStyle() {
    const picks = chosenNow();
    if (picks.length !== 1) return false;
    Styles.keepStyle(Styles.shapeStyle(shapesOf()[picks[0]]));
    toast("Style copied", { icon: "copy", seconds: 1.5 });
    return true;
  }
  function pasteStyle() {
    const style = Styles.copiedStyle(), picks = chosenNow().filter((index) => !shapesOf()[index]?.locked);
    if (!style || !picks.length) return false;
    return edit((list) => { for (const index of picks) list[index] = Styles.onShape(list[index], style); }, "Paste Style");
  }

  // Settings changed on every shape chosen, one step (a slider dragged, one run).
  function set(changes, label, merge = null) {
    const picks = chosenNow();
    if (!picks.length) return;
    const apply = (spec) => {
      if (spec.kind === "group" && !Object.keys(changes).every((key) => [...ownKeys, "opacity"].includes(key))) {
        return { ...spec, shapes: (spec.shapes || []).map(apply) };
      }
      const out = { ...spec };
      for (const [key, value] of Object.entries(changes)) {
        const fallback = F.defaults(spec.kind)[key];
        if (value === null || value === undefined || (value === fallback && !["fill", "line"].includes(key)) || (value === false && [...ownKeys, "shadow", "bold", "italic"].includes(key))) delete out[key];
        else out[key] = value;
      }
      return out;
    };
    edit((list) => { for (const index of picks) list[index] = apply(list[index]); }, label, { merge: merge ? `shape-set-${merge}-${picks.join(",")}` : null });
  }

  // -- clipboard --

  function clip() {
    const picks = chosenNow();
    if (!picks.length) return null;
    const list = shapesOf();
    const names = new Set(picks.flatMap((index) => namesIn(list[index])));
    const shapes = picks.map((index) => {
      const spec = copyOf(list[index]);
      // Glued to what is not copied with it, an end is where it was drawn.
      if (F.family(spec.kind) === "line") {
        const made = geometryOf(index);
        ["from", "to"].forEach((key, n) => { if (isEnd(spec[key]) && (spec[key].shape === undefined || !names.has(String(spec[key].shape)))) spec[key] = { ...spec[key], at: rounded(made?.ends?.[n] || F.pointOf(spec[key])) }; });
      }
      return spec;
    });
    return { what: "shapes", shapes, slide: slideIndex(), source: host.source?.() ?? `${noun}:${slideIndex()}`, label: shapes.length === 1 ? shapeLabel(shapes[0]).toLowerCase() : `${shapes.length} shapes` };
  }
  // Shapes copied -- here, on another page, from a slide onto a figure or a figure onto a
  // slide -- pasted on the page shown: each saying only what a shape on it may say (a slide's
  // build, a figure's part it is on, go), an end glued to what is elsewhere where it was.
  function paste(clipped, { label = null } = {}) {
    const same = (clipped.source ?? `slide:${clipped.slide}`) === (host.source?.() ?? `${noun}:${slideIndex()}`);
    const list = shapesOf();
    const made = clipped.shapes.map((_, n) => list.length + n);
    // (What a shape is on, or round, is its page's: elsewhere it is where it was drawn.)
    const PLACED = ["on", "around", "margin", "side"], OWN = ["behind", "build", "hidden", "locked"];
    const fitting = (spec) => {
      const out = Object.fromEntries(Object.entries(spec).filter(([key]) => !PLACED.includes(key) && (!OWN.includes(key) || ownKeys.includes(key))));
      if (out.kind === "group") out.shapes = (out.shapes || []).map(fitting);
      return out;
    };
    host.leaveOthers();
    edit((all) => {
      const taken = allIds(all);
      const copies = clipped.shapes.map((spec) => {
        let out = renamed(same ? copyOf(spec) : fitting(copyOf(spec)), taken);
        // Elsewhere what a page holds is another's: an end glued to it is where it was.
        if (!same && F.family(out.kind) === "line") for (const key of ["from", "to"]) if (isEnd(out[key]) && (out[key].object !== undefined || out[key].part !== undefined)) out[key] = out[key].at || [0, 0];
        for (const key of ["from", "to"]) if (isEnd(out[key]) && out[key].shape !== undefined && !allIds([...all, ...clipped.shapes]).has(String(out[key].shape))) out[key] = out[key].at || [0, 0];
        // Pasted where it was copied, it is set a little aside, as Keynote sets it.
        if (same && list.some((other) => JSON.stringify(other) === JSON.stringify(spec))) out = F.moved(out, 12, 12);
        return out;
      });
      return [...all, ...copies];
    }, label || (clipped.shapes.length === 1 ? `Paste ${shapeLabel(clipped.shapes[0])}` : `Paste ${clipped.shapes.length} Shapes`), { after: made });
    mark([], made);
    host.reportFocus();
  }

  // -- paths: the pen, a path's points, Make Editable, shapes combined (pathtools.js) --

  let tools = null;
  function paths() {
    tools ||= pathTools({
      S, previews, marks, guides, handles, toFrame, unit, specAt, geometryOf, edit, add, preview, putBack, place, say, roles, disarm, noun,
      hideTip: () => { tip.hidden = true; },
      snapTargets, caught: (point, targets) => caught(point, { targets }, false),
      toast: (words, options = {}) => toast(words, { icon: "shape", seconds: 3, ...options }),
      swallowRelease: (cancelled) => host.swallowRelease(cancelled),
      renderInspector: () => host.renderInspector(),
      remove: (index) => { chosen = [index]; chosenOn = slideIndex(); remove(); },
    });
    return tools;
  }
  const COMBINED = [["union", "Union Shapes"], ["subtract", "Subtract Shapes"], ["intersect", "Intersect Shapes"], ["exclude", "Exclude Shapes"]];
  // Whether a shape is filled within an outline of its own (a group's, all of its shapes).
  const filled = (spec) => Boolean(spec) && (spec.kind === "group" ? (spec.shapes || []).length > 0 && spec.shapes.every(filled) : F.isClosed(spec));
  function pathCommands(picks, name, locked) {
    if (locked) return [];
    const list = shapesOf(), one = picks.length === 1 ? list[picks[0]] : null, out = [];
    if (one?.kind === "path") out.push({ icon: "pen", label: "Edit Points", hint: "Drag its points and handles · double-click one: smooth or a corner", run: () => paths().points.start(picks[0]) });
    if (picks.some((index) => O.editableKind(list[index]))) out.push({ icon: "shape", label: "Make Editable", also: ["Convert to Path"], hint: `${name}, as a path of the same outline`, run: () => makeEditable() });
    if (picks.length > 1 && picks.every((index) => filled(list[index]))) {
      for (const [operation, label] of COMBINED) out.push({ icon: "layout", label, also: [`Combine Shapes: ${label.split(" ")[0]}`], hint: `${name}, as one path`, run: () => combine(operation) });
    }
    return out;
  }
  function makeEditable() {
    const picks = chosenNow().filter((index) => O.editableKind(shapesOf()[index]) && !shapesOf()[index].locked);
    if (!picks.length) return;
    const label = picks.length === 1 ? `Make ${shapeLabel(shapesOf()[picks[0]])} Editable` : `Make ${plural(picks.length)} Editable`;
    const made = picks.map((index) => O.editable(specAt(index), geometryOf(index)));
    edit((list) => { picks.forEach((index, n) => { list[index] = made[n]; }); }, label);
    host.reportFocus();
  }
  // The shapes chosen made one path -- by `operation` -- styled as the one at the back, where
  // it was; what was glued to them left where it was drawn.
  function combine(operation) {
    const picks = chosenNow().filter((index) => filled(shapesOf()[index]));
    if (picks.length < 2) return;
    const outlines = picks.flatMap((index) => O.outlinesOf(specAt(index), geometryOf(index)));
    const made = O.combined(operation, outlines);
    const label = COMBINED.find(([one]) => one === operation)[1];
    if (!made) { toast("Nothing is left: those shapes do not overlap", { icon: "shape", seconds: 3 }); return; }
    const back = shapesOf()[picks[0]];
    const spec = { kind: "path", d: P.written(made), fill_rule: "evenodd", ...O.styleOf(back), ...Object.fromEntries(ownKeys.filter((key) => back[key] !== undefined).map((key) => [key, back[key]])) };
    const gone = new Set(picks.flatMap((index) => namesIn(shapesOf()[index])));
    const at = picks[0] - 0;
    edit((list) => list.flatMap((item, index) => (index === at ? [spec] : picks.includes(index) ? [] : [item && unglued(item, gone, index)])), label, { after: [at] });
    host.undoNote?.(`${plural(picks.length)} combined`, { icon: "shape" });
    host.reportFocus();
  }

  // -- the popover and the commands --

  function chooser(anchor) {
    const sections = (catalog.sections || F.SECTIONS.map(([name, kinds]) => ({ name, kinds }))).map((section) => (Array.isArray(section) ? { name: section[0], kinds: section[1] } : section));
    const grid = h("div.shape-grid", { role: "menu" }, sections.map((section) => [
      h("div.menu-title.shape-section", {}, section.name),
      h("div.shape-row", {}, section.kinds.map((kind) => h("button.shape-pick", { type: "button", role: "menuitem", title: toolName(kind), "aria-label": toolName(kind),
        onclick: () => { closeMenu(); arm(kind); } }, shapeIcon(kind), h("span.shape-name", {}, toolName(kind))))),
    ]));
    popover(anchor, [h("div.menu-title", {}, "Shapes"), grid], { className: "shape-menu" });
    grid.querySelector("button")?.focus({ preventScroll: true });
  }
  const shapeCount = () => chosenNow().length;
  function commands() {
    const out = [];
    if (host.canDraw()) {
      out.push({ icon: "shape", label: host.chooserLabel || "Add Shape…", hint: "Lines, arrows, shapes, callouts, braces, measures and text boxes", run: () => chooser(host.shapeButton()) });
      // (Each also by the name the Mac app's Insert › Shapes runs it by, whatever the page.)
      // (A zoom inset is added for what it magnifies, never drawn on its own; a path by its
      // tool's name: the pen.)
      for (const kind of F.KINDS.filter((each) => each !== "inset")) out.push({ icon: kind === "path" ? "pen" : "shape", label: `${verb} ${toolName(kind)}`, also: verb === "Draw" ? [] : [`Draw ${toolName(kind)}`], hint: kind === "path" ? `Click and drag on the ${noun}, point by point` : `Drag on the ${noun} to draw it`, run: () => arm(kind) });
    }
    const picks = chosenNow();
    if (!picks.length || words) return out;
    const name = picks.length === 1 ? shapeLabel(shapesOf()[picks[0]]) : plural(picks.length);
    const one = picks.length === 1 ? shapesOf()[picks[0]] : null;
    const locked = picks.some((index) => shapesOf()[index]?.locked);
    out.push(
      { icon: "duplicate", label: `Duplicate ${name}`, also: ["Duplicate"], keys: "⌘D", run: () => duplicate() },
      { icon: "trash", label: `Delete ${name}`, keys: "⌫", run: () => remove() },
      { icon: "front", label: "Bring to Front", keys: "⇧⌘F", hint: name, run: () => order("front") },
      { icon: "front", label: "Bring Forward", keys: "⌥⇧⌘F", hint: name, run: () => order("forward") },
      { icon: "back", label: "Send Backward", keys: "⌥⇧⌘B", hint: name, run: () => order("backward") },
      { icon: "back", label: "Send to Back", keys: "⇧⌘B", hint: name, run: () => order("back") },
      { icon: "back", label: picks.every((index) => shapesOf()[index]?.behind) ? behindNames[1] : behindNames[0], hint: name,
        run: () => set({ behind: !picks.every((index) => shapesOf()[index]?.behind) }, picks.every((index) => shapesOf()[index]?.behind) ? behindNames[1] : behindNames[0]) },
      ...(picks.length > 1 ? [{ icon: "layout", label: "Group", also: ["Group…"], keys: "⌘G", run: () => group() }] : []),
      ...(picks.some((index) => shapesOf()[index]?.kind === "group") ? [{ icon: "layout", label: "Ungroup", keys: "⇧⌘G", run: () => ungroup() }] : []),
      locked ? { icon: "unlock", label: "Unlock", keys: "⌥⌘L", hint: name, run: () => lock(false) } : { icon: "lock", label: "Lock", keys: "⌘L", hint: name, run: () => lock(true) },
      // Align and Distribute: the sides, beside, spread, a gap, a grid, Relative to (aligntools.js).
      ...arranging.commands(name),
      { icon: "flip-across", label: "Flip Horizontally", hint: name, run: () => flip("horizontal") },
      { icon: "flip-down", label: "Flip Vertically", hint: name, run: () => flip("vertical") },
      // Format › Copy Style and Paste Style (⌥⌘C, ⌥⌘V): how one is drawn, put on others.
      ...(picks.length === 1 ? [{ icon: "copy", label: "Copy Style", keys: "⌥⌘C", hint: name, run: () => copyStyle() }] : []),
      ...(Styles.copiedStyle() && !locked ? [{ icon: "paste", label: "Paste Style", keys: "⌥⌘V", hint: `${Styles.styleName(Styles.copiedStyle())}’s, on ${name}`, run: () => pasteStyle() }] : []),
      ...(host.commands ? host.commands(picks, name, { set, edit, choose }) : []),
      ...(one && one.kind !== "group" && !locked ? [{ icon: "pencil", label: one.text ? "Edit Text" : "Add Text", hint: name, run: () => editWords(picks[0], { selectAll: true }) }] : []),
      ...pathCommands(picks, name, locked),
    );
    return out;
  }
  // What being behind what the page holds is called: Keynote's "slide content", a figure.
  const behindNames = host.behindNames || ["Send Behind Slide Content", "Bring Above Slide Content"];
  function menuItems() {
    const picks = chosenNow();
    const named = (label) => commands().find((command) => command.label === label);
    const one = picks.length === 1 ? shapesOf()[picks[0]] : null;
    const locked = picks.some((index) => shapesOf()[index]?.locked);
    const items = [];
    if (one && one.kind !== "group" && !locked) items.push(named(one.text ? "Edit Text" : "Add Text"), "-");
    items.push(...host.clipItems(), named(`Duplicate ${picks.length === 1 ? shapeLabel(one) : plural(picks.length)}`), "-");
    items.push({ icon: "front", label: "Arrange", items: ["Bring to Front", "Bring Forward", "Send Backward", "Send to Back"].map(named) },
      { icon: "align-left", label: "Align", items: ["Align Left", "Align Centre", "Align Right", "Align Top", "Align Middle", "Align Bottom"].map(named) },
      // (And the rest of Align and Distribute, a menu of their own: aligntools.js.)
      arranging.menuItem(plural(picks.length)));
    const rest = ["Group", "Ungroup", "Lock", "Unlock", "Flip Horizontally", "Flip Vertically"].map(named).filter(Boolean);
    // (A path's points, any shape as a path, shapes combined into one.)
    const outlined = ["Edit Points", "Make Editable", ...COMBINED.map(([, label]) => label)].map(named).filter(Boolean);
    if (outlined.length) rest.push("-", ...outlined);
    // (And the page's own that it says belong here: Convert to Figure Parts.)
    const own = commands().filter((command) => command.menu);
    items.push(...rest, ...(own.length ? ["-", ...own] : []), "-", named(picks.length === 1 ? `Delete ${shapeLabel(one)}` : `Delete ${plural(picks.length)}`));
    // (A menu of the studio's has no submenus: Arrange and Align are their items, in place.)
    return items.flatMap((item) => (item?.items ? item.items.filter(Boolean).map((sub) => ({ ...sub })) : [item])).filter(Boolean)
      .map((item) => (item === "-" ? item : { ...item, danger: item.label?.startsWith("Delete") || undefined }));
  }

  // -- the inspector --

  function panel() {
    const picks = chosenNow(), list = shapesOf();
    const specs = picks.map((index) => F.normalised(list[index]));
    const flat = specs.flatMap(function leaves(spec) { return spec.kind === "group" ? spec.shapes.flatMap(leaves) : [spec]; });
    const count = picks.length, name = count === 1 ? shapeLabel(list[picks[0]]) : `${count} Shapes`;
    const shared = (key) => { const values = flat.map((spec) => spec[key]); return values.every((value) => JSON.stringify(value) === JSON.stringify(values[0])) ? values[0] : undefined; };
    const kinds = new Set(flat.map((spec) => spec.kind));
    const closedAll = flat.every((spec) => F.isClosed(spec) || spec.kind === "text");
    const linesAll = flat.every((spec) => F.family(spec.kind) === "line" || (F.family(spec.kind) === "points" && !spec.closed));
    // (A path open at an end takes arrowheads, and its line's ends, as a line does.)
    const anyLines = flat.some((spec) => (!F.isClosed(spec) && spec.kind !== "text") || (spec.kind === "path" && F.pathOpen(spec)));
    const palette = studio.info?.palette || {}, all = roles();
    const tone = (n) => (n === 1 ? "accent" : `accent${n}`);
    const tones = [1, 2, 3, 4, 5, 6].filter((n) => all[`tone-${n}-stroke`]);
    // Each colour offered once in a row: a theme whose tones repeat (or whose grey is its
    // muted ink) shows it once, by its first name.
    const row = (entries) => {
      const seen = new Set();
      return entries.map(([value, title]) => {
        const colour = F.paintOf(value, all), key = String(colour).toLowerCase();
        if (seen.has(key)) return null;
        seen.add(key);
        return { value, colour, title };
      }).filter(Boolean);
    };
    const fills = row([...tones.map((n) => [`${tone(n)}-fill`, n === 1 ? "Accent Tint" : `Accent ${n} Tint`]), ...tones.map((n) => [tone(n), n === 1 ? "Accent" : `Accent ${n}`]),
      ["grey", "Grey"], ["paper", "Paper"], ["muted", "Muted"], ["ink", "Ink"]]);
    const strokes = row([...tones.map((n) => [tone(n), n === 1 ? "Accent" : `Accent ${n}`]), ["muted", "Muted"], ["ink", "Ink"], ["paper", "Paper"]]);
    const glyph = (head, start) => { const node = icon(`head-${head === "open" ? "open" : head}`); if (start) node.style.transform = "scaleX(-1)"; return node; };
    const headOptions = (start) => F.HEADS.map((head) => ({ value: head, label: { none: "None", triangle: "Triangle", open: "Open", stealth: "Stealth", dot: "Dot", circle: "Circle", bar: "Bar", diamond: "Diamond" }[head], icon: `head-${head}` }));
    const sections = [];
    const leave = () => { clear(); };
    sections.push(h("div.section.block-top", {},
      h("div.crumbs", {}, h("button.crumb", { type: "button", onclick: leave }, host.crumb ? host.crumb() : `Slide ${slideIndex() + 1}`), icon("chevron"), h("span.crumb.here", {}, icon("shape"), name)),
      h("div.block-actions", { dataset: { head: "" } },
        ui.button("", () => order("front"), { kind: "ghost", small: true, icon: "front", title: "Bring to Front (⇧⌘F)" }),
        ui.button("", () => order("back"), { kind: "ghost", small: true, icon: "back", title: "Send to Back (⇧⌘B)" }),
        ui.button("", () => duplicate(), { kind: "ghost", small: true, icon: "duplicate", title: "Duplicate (⌘D)" }),
        ui.button("", () => remove(), { kind: "ghost", small: true, icon: "trash", title: "Delete (⌫)" }))));
    const style = [];
    if (closedAll || flat.some((spec) => F.isClosed(spec))) {
      style.push(ui.field("Fill", ui.swatches({ value: shared("fill") === "none" ? null : shared("fill") ?? undefined, colours: fills, none: true, noneTitle: "No Fill", custom: true, key: "shape.fill",
        onChange: (value) => set({ fill: value ?? "none" }, "Change Fill", "fill") })));
      // Or a gradient: its kind, its ends' colours and its way (gradients.js).
      style.push(...gradientFields({ value: shared("fill"), ui, h, set: (fill, label) => set({ fill }, label, "fill"),
        swatches: (value, onChange, key) => ui.swatches({ value, colours: fills, none: false, custom: true, key, onChange }) }));
      if (shared("fill") !== "none") style.push(ui.field("Fill Opacity", slider(shared("fill_opacity"), 0, 1, 0.05, (value) => set({ fill_opacity: value }, "Change Fill", "fill-opacity"), "shape.fill_opacity", true)));
    }
    style.push(ui.field(linesAll ? "Line" : "Outline", ui.swatches({ value: shared("line") === "none" ? null : shared("line") ?? undefined, colours: strokes, none: true, noneTitle: "No Line", custom: true, key: "shape.line",
      onChange: (value) => set({ line: value ?? "none" }, linesAll ? "Change Line" : "Change Outline", "line") })));
    if (shared("line") !== "none") {
      style.push(ui.field("Width", ui.number({ value: shared("line_width") ?? null, placeholder: shared("line_width") === undefined ? "Mixed" : "", min: 0, max: 200, step: 0.25, unit: "pt", key: "shape.line_width",
        onChange: (value) => set({ line_width: value ?? null }, "Change Line Width") })));
      style.push(ui.field("Dash", ui.segmented({ value: shared("dash") ?? null, key: "shape.dash", options: [{ value: "solid", label: "Solid" }, { value: "dashed", label: "Dashed" }, { value: "dotted", label: "Dotted" }],
        onChange: (value) => set({ dash: value }, "Change Dash") })));
      if (anyLines) style.push(ui.field("Ends", ui.select({ value: shared("cap") ?? "", key: "shape.cap", options: [{ value: "butt", label: "Flat" }, { value: "round", label: "Round" }, { value: "square", label: "Square" }],
        onChange: (value) => set({ cap: value }, "Change Line Ends") })));
      style.push(ui.field("Corners", ui.select({ value: shared("join") ?? "", key: "shape.join", options: [{ value: "miter", label: "Sharp" }, { value: "round", label: "Round" }, { value: "bevel", label: "Bevelled" }],
        onChange: (value) => set({ join: value }, "Change Line Corners") })));
    }
    if (anyLines && !kinds.has("brace") && !kinds.has("bracket")) {
      style.push(h("div.row.heads", {},
        ui.field("Start", ui.select({ value: shared("start") ?? "", options: headOptions(true), icons: true, title: "Start", key: "shape.start", onChange: (value) => set({ start: value }, "Change Arrowheads") })),
        ui.field("End", ui.select({ value: shared("end") ?? "", options: headOptions(false), icons: true, title: "End", key: "shape.end", onChange: (value) => set({ end: value }, "Change Arrowheads") })),
        ui.button("", () => { const a = shared("start"), b = shared("end"); if (a !== undefined && b !== undefined) set({ start: b, end: a }, "Swap Arrowheads"); }, { kind: "ghost", small: true, icon: "refresh", title: "Swap the ends" })));
      if (flat.some((spec) => spec.start !== "none" || spec.end !== "none")) style.push(ui.field("Arrowhead Size", ui.number({ value: shared("head_size") ?? null, placeholder: "Mixed", min: 0.25, max: 6, step: 0.25, unit: "×", key: "shape.head_size",
        onChange: (value) => set({ head_size: value ?? 1 }, "Change Arrowheads") })));
    }
    style.push(ui.field("Shadow", ui.toggle({ value: Boolean(shared("shadow")), key: "shape.shadow", onChange: (on) => set({ shadow: on }, on ? "Add Shadow" : "Remove Shadow") })));
    style.push(ui.field("Opacity", slider(count === 1 ? specs[0].opacity : shared("opacity"), 0, 1, 0.05, (value) => set({ opacity: value }, "Change Opacity", "opacity"), "shape.opacity", true)));
    sections.push(h("div.section", {}, h("div.section-title", {}, "Style"), style));
    // The kind's own settings, where every shape chosen is of one kind.
    const own = kinds.size === 1 ? ownFields([...kinds][0], shared, strokes) : [];
    if (own.length) sections.push(h("div.section", {}, h("div.section-title", {}, F.LABELS[[...kinds][0]] || "Shape"), own));
    // Words, for shapes that hold them.
    if (flat.length && !kinds.has("group")) {
      const fonts = host.fonts?.() || studio.info?.fonts || {};
      const textBits = [
        ui.field("Font", ui.font({ value: shared("font") || "", options: studio.catalog?.fonts || [], placeholder: `${host.fontOwner || "Deck"} (${fonts.body || "Default"})`, key: "shape.font", onChange: (value) => set({ font: value || null }, "Change Font") })),
        h("div.row", {},
          ui.field("Size", ui.number({ value: shared("font_size") ?? null, placeholder: "Auto", min: 4, max: 400, step: 1, unit: "pt", key: "shape.font_size", onChange: (value) => set({ font_size: value }, "Change Font Size") })),
          ui.field("Style", h("div.segmented", {}, [["bold", "B", "Bold"], ["italic", "I", "Italic"]].map(([name, letter, title]) => {
            const on = Boolean(shared(name));
            return h(`button${on ? ".on" : ""}`, { type: "button", title, "aria-pressed": String(on), onclick: () => set({ [name]: !on }, on ? `Remove ${title}` : title) },
              h(name === "bold" ? "b" : "i", {}, letter));
          })))),
        ui.field("Colour", ui.swatches({ value: shared("colour") ?? null, colours: strokes, none: true, noneTitle: "Automatic", custom: true, key: "shape.colour", onChange: (value) => set({ colour: value }, "Change Text Colour") })),
        ui.field("Align", ui.segmented({ value: shared("align") ?? null, key: "shape.align", options: [{ value: "start", label: "Left" }, { value: "middle", label: "Centre" }, { value: "end", label: "Right" }],
          onChange: (value) => set({ align: value }, "Change Alignment") })),
        closedAll ? ui.field("Vertical", ui.segmented({ value: shared("valign") ?? null, key: "shape.valign", options: [{ value: "top", label: "Top" }, { value: "middle", label: "Middle" }, { value: "bottom", label: "Bottom" }],
          onChange: (value) => set({ valign: value }, "Change Alignment") })) : null,
        ui.field("Padding", ui.number({ value: shared("padding") ?? null, placeholder: "5", min: 0, max: 200, step: 1, unit: "pt", key: "shape.padding", onChange: (value) => set({ padding: value }, "Change Padding") })),
      ];
      sections.push(h("div.section", {}, h("div.section-title", {}, "Text"), textBits,
        count === 1 && !specs[0].locked ? ui.button(specs[0].text ? "Edit Text" : "Add Text", () => editWords(picks[0], { selectAll: true }), { small: true, kind: "ghost", icon: "pencil" }) : null));
    }
    sections.push(h("div.section", {}, h("div.section-title", {}, "Arrange"), arrangeFields(picks, specs)));
    // Align and Distribute, with what they are aligned to (aligntools.js).
    sections.push(arranging.section());
    // The page's own settings for them: a slide's builds, a figure's part they move with.
    if (host.panel) sections.push(...host.panel(picks, specs, { set, edit, choose, slider }));
    return sections;
  }
  function slider(value, min, max, step, onChange, key, percent = false) {
    const input = h("input.range", { type: "range", min, max, step });
    input.value = String(value ?? max);
    input.dataset.key = key;
    const said = h("span.range-value", {}, percent ? `${Math.round((value ?? max) * 100)}%` : String(value ?? ""));
    input.addEventListener("input", () => { said.textContent = percent ? `${Math.round(Number(input.value) * 100)}%` : input.value; onChange(Number(input.value)); });
    return h("div.row.range-row", {}, input, said);
  }
  function ownFields(kind, shared, strokes = []) {
    const number = (key, label, options) => ui.field(label, ui.number({ value: shared(key) ?? null, placeholder: "Mixed", key: `shape.${key}`, ...options,
      onChange: (value) => set({ [key]: value }, `Change ${label}`) }));
    const share = (key, label, min = 0, max = 1) => ui.field(label, slider(shared(key), min, max, 0.01, (value) => set({ [key]: value }, `Change ${label}`, key), `shape.${key}`));
    switch (kind) {
      case "rectangle": case "rounded-rectangle": case "highlight": return [number("corner", "Corner", { min: 0, max: 500, step: 1, unit: "pt" })];
      case "polygon": return [number("sides", "Sides", { min: 3, max: 24, step: 1 })];
      case "star": return [number("tips", "Points", { min: 3, max: 32, step: 1 }), share("ratio", "Inner Size", 0.05, 0.95)];
      case "triangle": return [share("apex", "Top")];
      case "parallelogram": return [share("slant", "Slant")];
      case "trapezoid": return [share("inset", "Inset", 0, 0.5)];
      case "arrow-right": case "arrow-left": case "arrow-up": case "arrow-down": case "arrow-left-right": return [share("shaft", "Shaft", 0.05, 1), share("head", "Head")];
      case "chevron": return [share("point", "Point")];
      case "plus": case "cross": return [share("arm", "Arms", 0.02, 0.45)];
      case "bubble": return [ui.field("Body", ui.segmented({ value: shared("body") ?? null, key: "shape.body", options: [{ value: "rounded", label: "Rounded" }, { value: "rectangle", label: "Square" }, { value: "oval", label: "Oval" }],
        onChange: (value) => set({ body: value }, "Change Bubble") })), shared("body") === "rounded" ? number("corner", "Corner", { min: 0, max: 500, step: 1, unit: "pt" }) : null].filter(Boolean);
      case "curved-arrow": return [share("bend", "Bend", -1.5, 1.5), ui.button("Straighten", () => set({ bend: 0, lean: 0 }, "Straighten Line"), { small: true, kind: "ghost" })];
      case "arc": return [share("bend", "Bend", -1.5, 1.5)];
      case "elbow": return [ui.field("Route", ui.segmented({ value: shared("route") ?? null, key: "shape.route", options: [{ value: "across", label: "Across First" }, { value: "down", label: "Down First" }],
        onChange: (value) => set({ route: value }, "Change Route") })), share("elbow", "Middle")];
      case "brace": return [number("depth", "Depth", { min: -500, max: 500, step: 1, unit: "pt" }), share("curl", "Curl"), share("tip", "Tip", 0.05, 0.95)];
      case "bracket": return [number("depth", "Depth", { min: -500, max: 500, step: 1, unit: "pt" }), share("curl", "Rounding")];
      case "polyline": case "pen": return [ui.field("Closed", ui.toggle({ value: Boolean(shared("closed")), key: "shape.closed", onChange: (on) => set({ closed: on }, on ? "Close Shape" : "Open Shape") }))];
      // A zoom inset's frame round the part it shows, and the lines joining them: each as its
      // outline unless set (None: not drawn).
      case "inset": return [["frame", "Frame"], ["connector", "Lines"]].flatMap(([piece, title]) => [
        // (Unset, the outline's colour is shown: what it is drawn in.)
        ui.field(title, ui.swatches({ value: (shared(`${piece}_line`) ?? shared("line")) === "none" ? null : shared(`${piece}_line`) ?? shared("line") ?? undefined, colours: strokes, none: true, noneTitle: "None", custom: true, key: `shape.${piece}_line`,
          onChange: (value) => set({ [`${piece}_line`]: value ?? "none" }, `Change ${title}`, `${piece}-line`) })),
        h("div.row", {},
          ui.field("Width", ui.number({ value: shared(`${piece}_width`) ?? null, placeholder: "As Outline", min: 0, max: 200, step: 0.25, unit: "pt", key: `shape.${piece}_width`,
            onChange: (value) => set({ [`${piece}_width`]: value }, `Change ${title}`) })),
          ui.field("Dash", ui.select({ value: shared(`${piece}_dash`) ?? "", key: `shape.${piece}_dash`,
            options: [{ value: "", label: "As Outline" }, { value: "solid", label: "Solid" }, { value: "dashed", label: "Dashed" }, { value: "dotted", label: "Dotted" }],
            onChange: (value) => set({ [`${piece}_dash`]: value || null }, `Change ${title}`) }))),
      ]).concat([ui.button("Frame and Lines as Outline", () => set(Object.fromEntries(["frame_line", "frame_width", "frame_dash", "connector_line", "connector_width", "connector_dash"].map((key) => [key, null])), "Change Zoom Inset"),
        { small: true, kind: "ghost", icon: "refresh" })]);
      default: return [];
    }
  }
  function arrangeFields(picks, specs) {
    const one = picks.length === 1 ? specs[0] : null, out = [];
    // Where it is: a box's own top left (turned or not, as Keynote says it); else where what
    // is chosen reaches.
    const own = one && ["box", "text"].includes(F.family(one.kind));
    // (A path's own top left is its box's, as it is drawn: it writes none.)
    const traced = one && F.family(one.kind) === "path";
    const where = () => { if (own) return shapesOf()[picks[0]].at; if (traced) return geometryOf(picks[0]).box.slice(0, 2); const box = unionOf(picks); return box ? [box[0], box[1]] : null; };
    if (where()) {
      const moveTo = (axis) => (value) => {
        if (value === null) return;
        const delta = value - where()[axis === "x" ? 0 : 1];
        if (!delta) return;
        edit((list) => { for (const index of picks) list[index] = withPlaces(F.moved(list[index], axis === "x" ? round(delta) : 0, axis === "x" ? 0 : round(delta))); }, `Move ${plural(picks.length)}`);
      };
      out.push(h("div.row", {},
        ui.field("X", ui.number({ value: round(where()[0]), step: 1, unit: "pt", key: "shape.x", onChange: moveTo("x") })),
        ui.field("Y", ui.number({ value: round(where()[1]), step: 1, unit: "pt", key: "shape.y", onChange: moveTo("y") }))));
    }
    if (one && F.family(one.kind) === "box") {
      const resize = (axis) => (value) => { if (value) edit((list) => { const size = [...list[picks[0]].size]; size[axis] = value; list[picks[0]] = { ...list[picks[0]], size }; }, "Resize Shape"); };
      out.push(h("div.row", {},
        ui.field("Width", ui.number({ value: one.size[0], min: 1, step: 1, unit: "pt", key: "shape.w", onChange: resize(0) })),
        ui.field("Height", ui.number({ value: one.size[1], min: 1, step: 1, unit: "pt", key: "shape.h", onChange: resize(1) }))));
    }
    if (traced) {
      // A path sized from its box's top left, its points stretched.
      const [bx, by, bw, bh] = geometryOf(picks[0]).box;
      const resize = (axis) => (value) => {
        if (!value) return;
        const k = axis === 0 ? value / (bw || 1) : value / (bh || 1);
        edit((list) => { list[picks[0]] = F.mapped(list[picks[0]], ([px, py]) => (axis === 0 ? [bx + (px - bx) * k, py] : [px, by + (py - by) * k])); }, "Resize Shape");
      };
      out.push(h("div.row", {},
        ui.field("Width", ui.number({ value: round(bw), min: 1, step: 1, unit: "pt", key: "shape.w", onChange: resize(0) })),
        ui.field("Height", ui.number({ value: round(bh), min: 1, step: 1, unit: "pt", key: "shape.h", onChange: resize(1) }))));
    }
    if (one && ["box", "text", "path"].includes(F.family(one.kind)) && one.kind !== "inset") {
      out.push(ui.field("Rotate", ui.number({ value: Number(one.rotate || 0), min: -360, max: 360, step: 1, unit: "°", key: "shape.rotate",
        onChange: (value) => edit((list) => { const turned = ((Number(value || 0) % 360) + 360) % 360; if (turned) list[picks[0]].rotate = turned; else delete list[picks[0]].rotate; }, "Rotate Shape") })));
    }
    out.push(h("div.row.arrange-row", {},
      ui.button("", () => flip("horizontal"), { kind: "ghost", small: true, icon: "flip-across", title: "Flip Horizontally" }),
      ui.button("", () => flip("vertical"), { kind: "ghost", small: true, icon: "flip-down", title: "Flip Vertically" }),
      ui.button("", () => order("front"), { kind: "ghost", small: true, icon: "front", title: "Bring to Front (⇧⌘F)" }),
      ui.button("", () => order("forward"), { kind: "ghost", small: true, icon: "up", title: "Bring Forward (⌥⇧⌘F)" }),
      ui.button("", () => order("backward"), { kind: "ghost", small: true, icon: "down", title: "Send Backward (⌥⇧⌘B)" }),
      ui.button("", () => order("back"), { kind: "ghost", small: true, icon: "back", title: "Send to Back (⇧⌘B)" })));
    // (Aligned and spaced in a section of their own: Align and Distribute.)
    if (picks.length > 1) {
      out.push(h("div.row", {}, ui.button("Group", () => group(), { small: true, icon: "layout", title: "Group (⌘G)" })));
    }
    if (picks.some((index) => shapesOf()[index]?.kind === "group")) out.push(h("div.row", {}, ui.button("Ungroup", () => ungroup(), { small: true, icon: "layout", title: "Ungroup (⇧⌘G)" })));
    // (Where the page's own settings have it -- a figure's, In Front or Behind -- not here.)
    if (!host.behindInPanel) out.push(ui.toggle({ value: picks.every((index) => shapesOf()[index]?.behind), label: host.behindLabel || "Behind Slide Content", key: "shape.behind",
      onChange: (on) => set({ behind: on }, on ? behindNames[0] : behindNames[1]) }));
    out.push(ui.toggle({ value: picks.every((index) => shapesOf()[index]?.locked), label: "Locked", key: "shape.locked", onChange: (on) => lock(on) }));
    return out;
  }

  // The band dragged across the slide: the shapes it touches (by their frames on screen).
  function touched(left, top, right, bottom) {
    const a = screenToFrame(left, top), b = screenToFrame(right, bottom);
    return shapesOf().map((_, index) => index).filter((index) => {
      const box = boundsOf(index);
      return box && box[2] >= a[0] && box[0] <= b[0] && box[3] >= a[1] && box[1] <= b[1];
    });
  }

  return {
    press, hover, leave, dblclick, context, key, place, drawn, panel, commands, menuItems, clip, paste, touched,
    // (Where a point on the screen is on the page, in the shapes' units: a paste's place.)
    pointAt: (x, y) => screenToFrame(x, y),
    choose, clear, restore, arm, disarm, chooser, remove, duplicate, group, ungroup, align, distribute, order, flip, lock, copyStyle, pasteStyle,
    chosen: chosenNow,
    list: shapesOf,
    set,
    any: () => chosenNow().length > 0,
    busy: () => Boolean(gesture?.started || drawingNow || tools?.pen.drawing() || tools?.points.busy()),
    editPoints: (index) => paths().points.start(index),
    editingPoints: () => Boolean(tools?.points.active()),
    armed: () => Boolean(tool),
    typing: () => Boolean(words),
    closeWords,
    count: shapeCount,
    label: () => { const picks = chosenNow(); return picks.length === 1 ? shapeLabel(shapesOf()[picks[0]]) : picks.length ? `${picks.length} Shapes` : ""; },
  };
}
