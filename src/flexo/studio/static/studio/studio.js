// Flexo studio: what a kind's editor builds with. An editor
// (static/kinds/<kind>/editor.js) exports mount(session, container): `session`
// is the open document (see session.js), `container` the space it fills.

export { h, clear, icon, ui, menu, popover, closeMenu, dialog, toast, readable, mathWords, inQuotes, typingName, exportLabel, suggestedFonts } from "./ui.js";
export { merge3, same } from "./merge.js";
export { avatar, colourOf, ago, copyable, nameOf } from "./shell.js";
export { themeCard, themeField, themeName, themeUses, themesFor } from "./themes.js";
import { start } from "./shell.js";
export { ownResources } from "./drawings.js";

// Draw a form again without taking the field someone is typing in away from them. Words
// another person added or took away before the caret move it along, so it stays where
// its person was typing. Drawn again for an undo or a redo (`undone`), words put back are
// chosen, as in TextEdit (else the caret is where words were taken away).
export function keepFocus(container, render, { undone = false } = {}) {
  const active = document.activeElement;
  const key = active && container.contains(active) ? active.dataset?.key : null;
  const selection = key && "selectionStart" in active ? [active.selectionStart, active.selectionEnd] : null;
  const caret = key && active.isContentEditable ? caretIn(active) : null;
  const was = selection && typeof active.value === "string" ? active.value : caret ? textIn(active) : null;
  const scroll = container.scrollTop;
  // (A field drawn again for an undo shows what is now, not what was being typed: ui.number.)
  if (undone && key) active.undone = true;
  render();
  container.scrollTop = scroll;
  if (!key) return;
  const again = container.querySelector(`[data-key="${CSS.escape(key)}"]`);
  if (!again) return;
  again.focus({ preventScroll: true });
  const follow = (now) => (at) => caretAfter(was, now, at);
  const put = (now) => { const [start, end] = alikeEnds(was, now); return [start, now.length - end]; };
  const placed = (now, range) => (undone ? put(now) : range.map(follow(now)));
  if (caret && again.isContentEditable) {
    const now = textIn(again);
    caretTo(again, now !== was ? placed(now, caret) : caret);
  }
  if (selection && "setSelectionRange" in again) {
    const now = typeof again.value === "string" ? again.value : null;
    const moved = was !== null && now !== null && now !== was ? placed(now, selection) : selection;
    try { again.setSelectionRange(...moved); } catch { /* a field without a caret */ }
  }
}

// How many letters `was` and `now` have alike at their start, and then at their end.
function alikeEnds(was, now) {
  let start = 0;
  while (start < was.length && start < now.length && was[start] === now[start]) start += 1;
  let end = 0;
  while (end < was.length - start && end < now.length - start && was[was.length - 1 - end] === now[now.length - 1 - end]) end += 1;
  return [start, end];
}

// Where a caret at `at` in `was` is in `now`: after the words that changed, if it was.
function caretAfter(was, now, at) {
  const [start, end] = alikeEnds(was, now);
  if (at <= start) return at;
  if (at >= was.length - end) return at + now.length - was.length;
  return now.length - end;
}

// The faces a drawing's words are set in, as CSS font shorthands ("italic 700 16px Figtree").
export function drawingFonts(svg) {
  const fonts = new Set();
  for (const node of svg.querySelectorAll("text, tspan")) {
    const family = node.closest("[font-family]")?.getAttribute("font-family");
    if (!family) continue;
    const weight = node.closest("[font-weight]")?.getAttribute("font-weight") || "400";
    const style = node.closest("[font-style]")?.getAttribute("font-style") || "normal";
    fonts.add(`${style} ${weight} 16px ${family}`);
  }
  return [...fonts];
}

// Settled once a drawing's faces are loaded: null if they are already, so a drawing
// whose words would show late (the faces load as they are first used) waits instead,
// and shows with its words, not without them for a moment.
export function fontsLoading(svg) {
  const fonts = drawingFonts(svg).filter((font) => { try { return !document.fonts.check(font); } catch { return false; } });
  if (!fonts.length) return null;
  const loads = Promise.all(fonts.map((font) => document.fonts.load(font).catch(() => null)));
  return Promise.race([loads, new Promise((done) => setTimeout(done, 1500))]);
}

// The words of a field of rich text, as the caret counts them.
function textIn(field) {
  const range = document.createRange();
  range.selectNodeContents(field);
  return range.toString();
}

// Where the caret is in a field of rich text, as counts of characters from its start;
// and the caret put back there in another.
function caretIn(field) {
  const chosen = getSelection();
  if (!chosen.rangeCount || !field.contains(chosen.anchorNode)) return null;
  const upTo = (node, offset) => { const range = document.createRange(); range.selectNodeContents(field); range.setEnd(node, offset); return range.toString().length; };
  return [upTo(chosen.anchorNode, chosen.anchorOffset), upTo(chosen.focusNode, chosen.focusOffset)];
}
function caretTo(field, [from, to]) {
  const at = (count) => {
    const walker = document.createTreeWalker(field, NodeFilter.SHOW_TEXT);
    let left = count;
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (left <= node.data.length) return [node, left];
      left -= node.data.length;
    }
    return [field, field.childNodes.length];
  };
  getSelection().setBaseAndExtent(...at(from), ...at(to));
}

// A drawing shown small (a thumbnail, a sample): its SVG in a shadow root, so it
// uses the fonts the page loaded (an <img> cannot) while its ids and styles stay
// its own. Pictures are kept by hash, so an unchanged one is not parsed again.
// It fills its box, or with `natural` keeps the drawing's own size (at most the
// box's width). Small words are set by their outlines, at their true widths: hinted
// to the pixel, the letters of a thumbnail's words run into each other.
const pictures = new Map();
// A picture is the drawing as it presents: an editor's placeholders' hints ("Title", "93%")
// are the editable slide's alone, never a thumbnail's or a preview's.
const PICTURE_STYLE = ":host{display:block;position:relative}svg{display:block;text-rendering:geometricPrecision}"
  + ":host(:not(.natural)) svg{width:100%;height:100%}:host(.natural) svg{max-width:100%;height:auto}"
  + "[data-flexo-placeholder]{display:none}";

export function picture(svg, hash, { natural = false } = {}) {
  const key = hash && `${natural ? "n" : "f"}:${hash}`;
  const known = key && pictures.get(key);
  if (known && !known.isConnected) return known;
  // One shown already (a slide's thumbnail, asked for again by the theme editor's preview of
  // the deck): a copy of it, as a node is in one place at a time -- moved, the thumbnail it
  // was taken from would go blank.
  if (known) {
    const copy = document.createElement("div");
    copy.className = known.className;
    copy.attachShadow({ mode: "open" }).append(...[...known.shadowRoot.childNodes].map((node) => node.cloneNode(true)));
    const waiting = known.style.visibility === "hidden" && fontsLoading(copy.shadowRoot.querySelector("svg"));
    if (waiting) { copy.style.visibility = "hidden"; waiting.then(() => { copy.style.visibility = ""; }); }
    return copy;
  }
  const host = document.createElement("div");
  host.className = natural ? "picture natural" : "picture";
  const root = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = PICTURE_STYLE;
  const holder = document.createElement("template");
  holder.innerHTML = svg.replace(/^<\?xml[^>]*>\s*/, "");
  const drawing = holder.content.querySelector("svg");
  // Its links are part of the picture: never a place for the keys, nor followed.
  for (const link of holder.content.querySelectorAll("a")) { link.removeAttribute("href"); link.removeAttributeNS("http://www.w3.org/1999/xlink", "href"); }
  if (drawing && !natural) {
    drawing.removeAttribute("width");
    drawing.removeAttribute("height");
    drawing.setAttribute("preserveAspectRatio", "xMidYMid meet");
  }
  root.append(style, holder.content);
  const loading = drawing && fontsLoading(drawing);
  if (loading) { host.style.visibility = "hidden"; loading.then(() => { host.style.visibility = ""; }); }
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
