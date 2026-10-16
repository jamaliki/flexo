// The grid (grid.js) drawn on a page, and where a person shows or hides it: the toggle beside
// the magnet in a zoom bar, View › Show Grid (the palette, the Mac app) and #.

import { h, icon } from "./ui.js";
import { pagesKey } from "./magnet.js";
import { gridShown, toggleGrid, onGrid, spacingOf, linesOf, placesOf } from "./grid.js";

const SVG_NS = "http://www.w3.org/2000/svg";

function S(name, attributes = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
}
const lightness = (colour) => {
  const rgb = /rgba?\(([^)]+)\)/.exec(colour || "")?.[1].split(",").map((value) => Number(value) / 255);
  if (!rgb || rgb.length < 3 || (rgb.length > 3 && rgb[3] * 255 === 0)) return 1;
  return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
};

// A page's grid: laid on `page` (a slide's or a figure's, over its drawing and the slides
// either side, under its frames and handles) for `frame` and the host's grid (`grid()`, asked
// only while it is shown: a slide's layout is measured) -- drawn again only when they change;
// taken off while it is hidden.
export function gridPaper() {
  const node = h("div.flexo-grid", { "aria-hidden": "true" });
  const svg = S("svg", { preserveAspectRatio: "xMidYMid meet" });
  node.append(svg);
  let made = "";
  function lay(page, frame, own = () => ({})) {
    const drawing = page?.querySelector(":scope > svg");
    if (!gridShown() || !drawing || !frame || !(frame[2] > 0 && frame[3] > 0)) { node.remove(); return; }
    const grid = own() || {};
    let at = drawing;
    while (at.nextElementSibling?.classList.contains("onion")) at = at.nextElementSibling;
    if (at.nextElementSibling !== node) at.after(node);
    const dark = lightness(getComputedStyle(page).backgroundColor) < 0.45;
    node.classList.toggle("dark", dark);
    const { step, major } = spacingOf(frame, grid);
    const key = JSON.stringify([frame, step, major, grid?.layout || null]);
    if (key === made) return;
    made = key;
    svg.setAttribute("viewBox", frame.join(" "));
    const [x0, y0, width, height] = frame, x1 = x0 + width, y1 = y0 + height;
    const { xs, ys } = linesOf(frame, step);
    const minor = [], darker = [];
    xs.forEach((x, k) => (k % major ? minor : darker).push(`M${x} ${y0}V${y1}`));
    ys.forEach((y, k) => (k % major ? minor : darker).push(`M${x0} ${y}H${x1}`));
    const line = (d, kind, weight) => S("path", { d, class: kind, "stroke-width": weight, "vector-effect": "non-scaling-stroke" });
    const layout = grid?.layout || {};
    const lines = [
      ...(layout.xs || []).filter(Number.isFinite).map((x) => `M${x} ${y0}V${y1}`),
      ...(layout.ys || []).filter(Number.isFinite).map((y) => `M${x0} ${y}H${x1}`),
    ];
    svg.replaceChildren(
      line(minor.join(""), "grid-minor", 0.5),
      line(darker.join(""), "grid-major", 0.75),
      line(`M${x0 + width / 2} ${y0}V${y1}M${x0} ${y0 + height / 2}H${x1}`, "grid-middle", 1),
      ...placesOf(layout).map(([left, top, right, bottom]) => S("rect", {
        x: left, y: top, width: right - left, height: bottom - top, class: "grid-place", "stroke-width": 0.75, "vector-effect": "non-scaling-stroke",
      })),
      ...(lines.length ? [line(lines.join(""), "grid-layout", 0.75)] : []),
    );
  }
  return { node, lay };
}

// -- shown, or not --

// The zoom bar's toggle, beside the magnet: pressed while the grid is shown.
export function gridButton() {
  const button = h("button.btn.ghost.small.icon.grid-toggle", { type: "button", onclick: () => toggleGrid() }, icon("graph"));
  // Clicked, it leaves the keys where they were, as the zoom bar's other buttons do.
  button.addEventListener("mousedown", (event) => event.preventDefault());
  const show = (on) => {
    button.classList.toggle("on", on);
    button.setAttribute("aria-pressed", String(on));
    button.title = on ? "Hide Grid (#)" : "Show Grid (#)";
    button.setAttribute("aria-label", button.title);
  };
  show(gridShown());
  // (Followed while it is there: an editor closed lets it go, and it stops listening.)
  const kept = new WeakRef(button);
  const stop = onGrid((on) => { const node = kept.deref(); if (node) show(on); else stop(); });
  return button;
}

// For the palette and the Mac app's View menu: one command, named for what it will do (as Show
// Speaker Notes is).
export const gridCommand = () => ({ icon: "graph", label: gridShown() ? "Hide Grid" : "Show Grid", keys: "#", run: () => toggleGrid() });

// #, while it is the page's (magnet.js): before an editor's, as % is.
export function gridKeys(root = document) {
  root.addEventListener("keydown", (event) => {
    if (event.key !== "#" || !pagesKey(event)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    toggleGrid();
  });
}
