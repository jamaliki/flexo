// Flexo studio: what a kind's editor builds with. An editor
// (static/kinds/<kind>/editor.js) exports mount(session, container): `session`
// is the open document (see session.js), `container` the space it fills.

export { h, clear, icon, ui, menu, popover, closeMenu, dialog, toast } from "./ui.js";
export { merge3, same } from "./merge.js";
export { avatar, colourOf, ago, copyable } from "./shell.js";
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

if (document.getElementById("studio")) start();
