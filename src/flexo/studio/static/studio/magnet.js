// Snapping (snapping.js) where a person sees and turns it: the magnet, Snap in the toolbar of a
// deck and of a figure (beside Arrange, with Grid), pressed while it is on -- a # beside it while
// it is the grid's -- each click the next of guides, the grid and off, said as it turns; %
// (Inkscape's key) the same while nothing is typed; and, in the Mac app, the app told when it is turned here and asked as a window opens or
// comes to the front -- its View › Snap to Guides and Objects and Snap to Grid turn it too (the
// shell's "snapping" and "snap-grid" commands), ticked as the page reports it.

import { h, icon, toast } from "./ui.js";
import { snapMode, setSnapMode, cycleSnapping, onSnapping, snapWord, fromWord } from "./snapping.js";

// What the magnet says of itself: what it catches at, its key, and what ⌘ does to a drag now.
export const magnetTitle = (mode = snapMode()) => (mode === "grid"
  ? "Snapping to Grid (%) · Hold ⌘ while dragging to place freely"
  : mode === "guides" ? "Snapping to Guides and Objects (%) · Hold ⌘ while dragging to place freely"
    : "Snapping Off (%) · Hold ⌘ while dragging to snap");

function shown(button, mode) {
  const on = mode !== "off";
  button.classList.toggle("on", on);
  button.classList.toggle("to-grid", mode === "grid");
  button.setAttribute("aria-pressed", String(on));
  button.title = magnetTitle(mode);
  const drawn = mode === "grid" ? "magnetGrid" : "magnet";
  if (button.dataset.icon !== drawn) { button.dataset.icon = drawn; (button.querySelector("svg") || button.appendChild(icon(drawn))).replaceWith(icon(drawn)); }
}

// The magnet: Snap, for a toolbar, drawn as its other buttons are (its icon, then its name);
// pressed while on.
export function magnetButton({ label = "Snap" } = {}) {
  const button = h("button.btn.ghost.magnet", { type: "button", "aria-label": "Snapping", onclick: () => sayTurned(cycleSnapping()) },
    icon("magnet"), h("span.btn-label", {}, label));
  button.dataset.icon = "magnet";
  // Clicked, it leaves the keys where they were, as the zoom bar's other buttons do.
  button.addEventListener("mousedown", (event) => event.preventDefault());
  shown(button, snapMode());
  // (Followed while it is there: an editor closed lets it go, and it stops listening.)
  const kept = new WeakRef(button);
  const stop = onSnapping((_on, _how, mode) => { const node = kept.deref(); if (node) shown(node, mode); else stop(); });
  return button;
}

// Said when it is turned by its key or the menu, where the button may not be in sight.
export function sayTurned(mode = snapMode()) {
  const said = mode === "grid" ? "Snapping to grid" : mode === "guides" ? "Snapping to guides and objects" : "Snapping off · Hold ⌘ while dragging to snap";
  toast(said, { icon: mode === "grid" ? "magnetGrid" : "magnet", seconds: mode === "off" ? 2.5 : 1.5 });
}

const typedIn = (node) => Boolean(node && (node.isContentEditable || node.tagName === "TEXTAREA" || node.tagName === "SELECT"
  || (node.tagName === "INPUT" && !/^(button|checkbox|radio|range|color|file|submit|reset|image)$/.test(node.type || ""))));
// Whether a key with no ⌘ is the page's own: nothing typed (a field, a label, a shape's words:
// their own) and no sheet or show up -- for % here, and # (the grid: grid.js).
export const pagesKey = (event) => !(event.defaultPrevented || event.metaKey || event.ctrlKey || event.isComposing
  || typedIn(event.target) || typedIn(document.activeElement) || document.querySelector(".scrim, .present"));

// %, while it is the page's. Listened for where the document's own keys are, before an
// editor's: a shape chosen does not take it as the first of its new words.
export function magnetKeys(root = document) {
  root.addEventListener("keydown", (event) => {
    if (event.key !== "%" || !pagesKey(event)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    sayTurned(cycleSnapping());
  });
}

// In the Mac app, whose windows each have their own storage (a folder's own address): the app
// keeps it for them all ("on", "grid" or "off") -- told when it is turned here, and asked as this
// window opens and each time it comes to the front. (Another window's turn reaches this one as
// the app's "snapping" command.) The app with none kept yet takes this window's.
export function snappingInApp() {
  const api = () => (typeof window === "undefined" ? null : window.pywebview?.api);
  onSnapping((_on, how) => { if (how === "here") Promise.resolve(api()?.snapping?.(snapWord())).catch(() => {}); });
  const ask = () => Promise.resolve(api()?.snapping?.()).then((kept) => {
    const mode = fromWord(kept);
    if (mode) setSnapMode(mode, "app");
    else if (kept === "" && snapMode() !== "guides") api()?.snapping?.(snapWord());
  }).catch(() => {});
  window.addEventListener("pywebviewready", ask);
  window.addEventListener("focus", ask);
  if (api()?.snapping) ask();
}
