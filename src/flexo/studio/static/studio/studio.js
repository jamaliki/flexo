// Flexo studio: what a kind's editor builds with. An editor
// (static/kinds/<kind>/editor.js) exports mount(session, container): `session`
// is the open document (see session.js), `container` the space it fills.

export { h, clear, icon, ui, menu, popover, closeMenu, dialog, toast, readable, mathWords } from "./ui.js";
export { merge3, same } from "./merge.js";
export { avatar, colourOf, ago, copyable } from "./shell.js";
export { themeCard, themeField, themeUses, themesFor } from "./themes.js";
import { start } from "./shell.js";

// Draw a form again without taking the field someone is typing in away from them.
export function keepFocus(container, render) {
  const active = document.activeElement;
  const key = active && container.contains(active) ? active.dataset?.key : null;
  const selection = key && "selectionStart" in active ? [active.selectionStart, active.selectionEnd] : null;
  const scroll = container.scrollTop;
  render();
  container.scrollTop = scroll;
  if (!key) return;
  const again = container.querySelector(`[data-key="${CSS.escape(key)}"]`);
  if (!again) return;
  again.focus({ preventScroll: true });
  if (selection && "setSelectionRange" in again) {
    try { again.setSelectionRange(...selection); } catch { /* a field without a caret */ }
  }
}

// A drawing shown small (a thumbnail, a sample): its SVG in a shadow root, so it
// uses the fonts the page loaded (an <img> cannot) while its ids and styles stay
// its own. Pictures are kept by hash, so an unchanged one is not parsed again.
// It fills its box, or with `natural` keeps the drawing's own size (at most the
// box's width).
const pictures = new Map();
const PICTURE_STYLE = ":host{display:block;position:relative}svg{display:block}"
  + ":host(:not(.natural)) svg{width:100%;height:100%}:host(.natural) svg{max-width:100%;height:auto}";

export function picture(svg, hash, { natural = false } = {}) {
  const key = hash && `${natural ? "n" : "f"}:${hash}`;
  const known = key && pictures.get(key);
  if (known) return known;
  const host = document.createElement("div");
  host.className = natural ? "picture natural" : "picture";
  const root = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = PICTURE_STYLE;
  const holder = document.createElement("template");
  holder.innerHTML = svg.replace(/^<\?xml[^>]*>\s*/, "");
  const drawing = holder.content.querySelector("svg");
  if (drawing && !natural) {
    drawing.removeAttribute("width");
    drawing.removeAttribute("height");
    drawing.setAttribute("preserveAspectRatio", "xMidYMid meet");
  }
  root.append(style, holder.content);
  if (key) {
    pictures.set(key, host);
    // Keep the pictures on screen; let the oldest of the rest go.
    for (const [old, kept] of pictures) {
      if (pictures.size <= 240) break;
      if (!kept.isConnected) pictures.delete(old);
    }
  }
  return host;
}

if (document.getElementById("studio")) start();
