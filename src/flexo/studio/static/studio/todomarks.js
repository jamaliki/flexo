// A document's TODOs (todos.js) shown where they are, in the studio only: an amber mark behind
// each where it is drawn (a slide's drawing, a figure's), the one gone to marked more strongly;
// at the stage's edges, a marker pointing to each that is out of sight while it is zoomed in;
// and a button saying how many there are ("3 TODOs"), that goes to the next. The marks are a
// layer of their own on the drawing shown, never in the drawing itself: nothing presented or
// exported has them, and the words are the author's, as written.

import { h, icon } from "./ui.js";
import { markDrawing, unmarkDrawing } from "./findbar.js";
import { TODO, TODO_FINDS, todosSaid } from "./todos.js";

const LAYER = "todo-marks";

// The TODOs on a drawing marked over their words (findbar.js's markDrawing, in a layer of their
// own): `fields` the drawing's own, `matches` theirs, `current` the one gone to (marked
// strongly). On a drawing of the words before the latest change, a TODO not drawn yet is not
// marked. The current one's mark is answered.
export function markTodos(svg, fields, matches, current = null, { dark = false } = {}) {
  if (!svg) return null;
  if (!matches.length) { unmarkTodos(svg); return null; }
  return markDrawing(svg, fields, matches, current, TODO, TODO_FINDS, { dark, layer: LAYER, lettered: true });
}
export const unmarkTodos = (svg) => unmarkDrawing(svg, LAYER);
// The marks on a drawing.
export const todoMarks = (svg) => [...(svg?.querySelectorAll(`:scope > g.${LAYER} > rect`) || [])];

// Whether a drawing's page is dark (its background's fill): its marks are lightened, not darkened.
export function darkPaper(svg) {
  const fill = svg?.querySelector('[id="canvas.background"]')?.getAttribute("fill") || "";
  const hex = /^#([0-9a-f]{6})$/i.exec(fill.trim())?.[1];
  if (!hex) return false;
  const [r, g, b] = [0, 2, 4].map((k) => parseInt(hex.slice(k, k + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.45;
}

// Markers at the edges of a stage that scrolls (a slide or a figure zoomed past it), each
// pointing to a TODO's mark out of sight that way -- those near each other one marker, with how
// many -- and, clicked, scrolling it into sight. `host` is the positioned box the stage is in,
// `marks()` the marks now. Placed again as the stage scrolls or changes size (a frame at most).
export function edgeMarkers(stage, { host = stage.parentNode, marks }) {
  const box = h("div.todo-edges");
  let frame = 0;
  const place = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(draw); };
  function draw() {
    const all = stage.isConnected ? marks() : [];
    if (!all.length) { box.replaceChildren(); return; }
    if (box.parentNode !== host) host.append(box);
    const view = stage.getBoundingClientRect(), into = host.getBoundingClientRect();
    // (The stage's room short of its scroll bars.)
    const left = view.left + stage.clientLeft, top = view.top + stage.clientTop;
    const right = left + stage.clientWidth, bottom = top + stage.clientHeight;
    const inset = 16, shown = [];
    for (const mark of all) {
      const at = mark.getBoundingClientRect();
      if (!at.width && !at.height) continue;
      const across = at.right < left ? -1 : at.left > right ? 1 : 0, down = at.bottom < top ? -1 : at.top > bottom ? 1 : 0;
      if (!across && !down) continue;
      const x = Math.min(Math.max(at.left + at.width / 2, left + inset), right - inset);
      const y = Math.min(Math.max(at.top + at.height / 2, top + inset), bottom - inset);
      const near = shown.find((one) => one.across === across && one.down === down && Math.hypot(one.x - x, one.y - y) < 30);
      if (near) near.marks.push(mark);
      else shown.push({ x, y, across, down, marks: [mark] });
    }
    box.replaceChildren(...shown.map((one) => {
      const turn = Math.round(Math.atan2(one.down, one.across) * 180 / Math.PI);
      return h("button.todo-edge", {
        type: "button", title: todosSaid(one.marks.length), tabindex: -1,
        style: { left: `${one.x - into.left}px`, top: `${one.y - into.top}px` },
        onmousedown: (event) => event.preventDefault(),
        onclick: (event) => { event.stopPropagation(); one.marks[0].scrollIntoView?.({ block: "center", inline: "center", behavior: "smooth" }); },
      }, h("span.todo-edge-arrow", { style: { transform: `rotate(${turn}deg)` } }, icon("chevron", { weight: "2.2" })),
      one.marks.length > 1 ? h("span.todo-edge-count", {}, String(one.marks.length)) : null);
    }));
  }
  stage.addEventListener("scroll", place, { passive: true });
  new ResizeObserver(place).observe(stage);
  return { place, clear: () => { cancelAnimationFrame(frame); box.replaceChildren(); } };
}

// The count of a document's TODOs, as a button that goes to the next: hidden with none.
export function todoButton(next, { title = "Next TODO (⌘')" } = {}) {
  const words = h("span.todo-count-words");
  const node = h("button.todo-count", { type: "button", title, hidden: true, onmousedown: (event) => event.preventDefault(), onclick: () => next() },
    h("span.todo-dot"), words);
  return {
    node,
    set(count) {
      node.hidden = !count;
      const said = count ? todosSaid(count) : "";
      if (words.textContent !== said) words.textContent = said;
    },
  };
}

// ⌘' and ⇧⌘' (the Mac app's View › Next TODO and Previous TODO): the document shown goes to its
// next TODO, or the one before (its `todos`: { count(), step(way) }) -- while words are typed
// too, as the menus' keys go. Never while a sheet or a show is up. Listened for once, whatever
// is opened.
let keyed = false;
export function todoKeys() {
  if (keyed) return;
  keyed = true;
  const mac = /Mac|iP/.test(navigator.platform || "");
  window.addEventListener("keydown", (event) => {
    if (event.code !== "Quote" || event.altKey || !(mac ? event.metaKey && !event.ctrlKey : event.ctrlKey)) return;
    if (document.querySelector(".scrim:not(.palette-scrim), .present")) return;
    const todos = window.flexoStudio?.active?.todos;
    if (!todos?.count()) return;
    event.preventDefault();
    event.stopPropagation();
    todos.step(event.shiftKey ? -1 : 1);
  }, true);
}
