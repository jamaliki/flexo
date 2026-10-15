// Snapping (snapping.js) where a person sees and turns it: the magnet, a button in the zoom bar of
// a deck and of a figure, pressed while it is on; % (Inkscape's key) while nothing is typed; and,
// in the Mac app, the app told when it is turned here and asked as a window opens or comes to
// the front -- its View › Snap to Guides and Objects turns it too (the shell's "snapping"
// command), ticked as the page reports it.

import { h, icon, toast } from "./ui.js";
import { snapping, setSnapping, toggleSnapping, onSnapping } from "./snapping.js";

// What the magnet says of itself: whether it is on, its key, and what ⌘ does to a drag now.
export const magnetTitle = (on = snapping()) => (on
  ? "Snapping On (%) · Hold ⌘ while dragging to place freely"
  : "Snapping Off (%) · Hold ⌘ while dragging to snap");

function shown(button, on) {
  button.classList.toggle("on", on);
  button.setAttribute("aria-pressed", String(on));
  button.title = magnetTitle(on);
}

// The magnet, for a zoom bar: drawn as its other small ghost buttons are, pressed while on.
export function magnetButton() {
  const button = h("button.btn.ghost.small.icon.magnet", { type: "button", "aria-label": "Snapping", onclick: () => toggleSnapping() }, icon("magnet"));
  // Clicked, it leaves the keys where they were, as the zoom bar's other buttons do.
  button.addEventListener("mousedown", (event) => event.preventDefault());
  shown(button, snapping());
  // (Followed while it is there: an editor closed lets it go, and it stops listening.)
  const kept = new WeakRef(button);
  const stop = onSnapping((on) => { const node = kept.deref(); if (node) shown(node, on); else stop(); });
  return button;
}

// Said when it is turned by its key or the menu, where the button may not be in sight.
export function sayTurned(on = snapping()) {
  toast(on ? "Snapping on" : "Snapping off · Hold ⌘ while dragging to snap", { icon: "magnet", seconds: on ? 1.5 : 2.5 });
}

const typedIn = (node) => Boolean(node && (node.isContentEditable || node.tagName === "TEXTAREA" || node.tagName === "SELECT"
  || (node.tagName === "INPUT" && !/^(button|checkbox|radio|range|color|file|submit|reset|image)$/.test(node.type || ""))));

// %, while nothing is typed (a field, a label, a shape's words: its own) and no sheet or show is
// up. Listened for where the document's own keys are, before an editor's: a shape chosen does
// not take it as the first of its new words.
export function magnetKeys(root = document) {
  root.addEventListener("keydown", (event) => {
    if (event.key !== "%" || event.defaultPrevented || event.metaKey || event.ctrlKey || event.isComposing) return;
    if (typedIn(event.target) || typedIn(document.activeElement) || document.querySelector(".scrim, .present")) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    sayTurned(toggleSnapping());
  });
}

// In the Mac app, whose windows each have their own storage (a folder's own address): the app
// keeps it for them all -- told when it is turned here, and asked as this window opens and each
// time it comes to the front. (Another window's turn reaches this one as the app's "snapping"
// command.) The app with none kept yet takes this window's.
export function snappingInApp() {
  const api = () => (typeof window === "undefined" ? null : window.pywebview?.api);
  onSnapping((on, how) => { if (how === "here") Promise.resolve(api()?.snapping?.(on)).catch(() => {}); });
  const ask = () => Promise.resolve(api()?.snapping?.()).then((kept) => {
    if (kept === "on" || kept === "off") setSnapping(kept === "on", "app");
    else if (kept === "" && !snapping()) api()?.snapping?.(false);
  }).catch(() => {});
  window.addEventListener("pywebviewready", ask);
  window.addEventListener("focus", ask);
  if (api()?.snapping) ask();
}
