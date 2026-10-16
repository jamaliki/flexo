// Set Colour… (⇧⌘C, the Mac's Show Colors key in Keynote and Pages): something chosen, the key
// pressed, a colour's code pasted -- and it is that colour. A small popover opens by what is
// chosen, the keys in its field: ⌘V there applies the code pasted at once and closes it, a code
// typed and Return does the same, Esc closes it with nothing changed. A clipboard that holds a
// colour already shows it in the field, chosen, so that Return alone applies it. It names what
// it will colour ("Fill of 3 Shapes"), and a switch under it goes to the thing's other colours
// (Fill, Outline, Text), Tab and the arrows going along it; the colours applied last are there
// to click. Each colour applied is one step in the history, named as the inspector's are.
//
// What is chosen comes as kinds, each with its colours (a slide's objects and its shapes, a
// figure's parts and the shapes drawn over it): [{ noun: "3 Shapes", colours: [{ name: "Fill",
// value, set(hex, alpha) }, ...], main }], `main` the one ⇧⌘C colours first -- a closed shape's
// fill, a line's colour, a text's words. Several kinds are coloured together: each its own main
// colour first ("Both"), then each colour they share by name.

import { h, ui, popover, closeMenu } from "./ui.js";
import { parseColour, hexOf, shownHex, recentColours, hexField, applyColour, colourChoices, boxAround } from "./hexcolour.js";
import { joinSteps } from "./mixing.js";

export { colourChoices, boxAround };

export const SET_COLOUR = "Set Colour…";
export const SET_COLOUR_KEYS = "⇧⌘C";

// ⇧⌘C (⇧Ctrl-C off a Mac), by the letter it types: as a Mac's menu matches it.
export function isColourKey(event) {
  return Boolean((event.metaKey || event.ctrlKey) && event.shiftKey && !event.altKey && String(event.key || "").toLowerCase() === "c");
}

// The colour on the clipboard now, if it holds one: the Mac app's (its own pasteboard, read
// for words few enough to be a colour's code), else the browser's where the page may read it
// without asking -- else none, and the popover waits for ⌘V.
export async function clipboardColour() {
  const app = globalThis.pywebview?.api;
  if (app?.clipboard_words) {
    try { return parseColour(String((await app.clipboard_words()) || "")); } catch { return null; }
  }
  try {
    const allowed = await navigator.permissions?.query?.({ name: "clipboard-read" });
    if (allowed?.state !== "granted") return null;
    return parseColour(await navigator.clipboard.readText());
  } catch { return null; }
}

let open = null;

// The popover for `choices` (colourChoices), by `anchor` (a box on the screen: what is chosen),
// else by `fallback` (an element: the inspector). `studio`: the document, for one step made of
// a colour given to several kinds at once, once `settled()` (a promise: a figure's edits have
// landed) -- as a change of both kinds is (mixed.js).
export function setColour(choices, { anchor = null, fallback = null, studio = null, settled = null } = {}) {
  if (!choices?.length) return null;
  let at = 0;
  let taken = false;
  const what = h("div.colour-pop-what");
  const chip = h("span.colour-pop-chip", { "aria-hidden": "true" });
  const hint = h("div.colour-pop-hint");
  const done = (hex, alpha) => {
    if (taken) return;
    taken = true;
    const choice = choices[at];
    closeMenu();
    const from = studio?.past?.length ?? -1;
    applyColour(() => choice.set(hex, alpha), hex, alpha);
    // (Several kinds' edits, made one step: undone together.)
    const join = () => { if (studio && from >= 0 && studio.past.length - from > 1) joinSteps(studio, from, `Change ${choice.name === "Both" ? "Colours" : choice.name}`); };
    const landed = settled?.();
    if (landed && typeof landed.then === "function") landed.then(join, join); else join();
  };
  const field = hexField({ placeholder: "Paste or type a colour", leaving: false, title: "Colour", apply: done });
  field.removeAttribute("title");
  const preview = () => {
    const read = parseColour(field.value);
    chip.style.background = read ? read.hex : "";
  };
  let typed = false;
  const HINT = "Paste a colour (⌘V), or type one and press Return";
  field.addEventListener("input", () => { typed = true; preview(); hint.textContent = HINT; });
  // The colour the thing has now, chosen in the field, to be typed or pasted over.
  const showChoice = () => {
    const choice = choices[at];
    what.textContent = choice.said;
    what.title = choice.said;
    if (!typed) {
      const hex = hexOf(choice.value);
      field.value = hex ? shownHex(hex) : "";
      preview();
    }
  };
  const switcher = choices.length > 1 ? ui.segmented({ value: 0, key: "colour-pop:switch", options: choices.map((choice, index) => ({ value: index, label: choice.name, title: choice.said })),
    onChange: (index) => { at = index; showChoice(); field.focus(); field.select(); } }) : null;
  const recent = recentColours();
  const recents = recent.length ? h("div.colour-pop-recent", { "aria-label": "Recent Colours" }, recent.map((hex) => h("button.recent-dot", {
    type: "button", title: shownHex(hex), "aria-label": `Recent Colour ${shownHex(hex)}`, style: { background: hex }, onclick: () => done(hex, null) }))) : null;
  hint.textContent = HINT;
  const node = popover(anchorPoint(anchor, fallback), [what, h("div.colour-pop-row", {}, field, chip), switcher, recents, hint], { className: "colour-pop" });
  node.setAttribute("aria-label", "Set Colour");
  open = node;
  showChoice();
  place(node, anchor, fallback);
  field.focus({ preventScroll: true });
  field.select();
  // A colour on the clipboard already: in the field, chosen -- Return applies it.
  clipboardColour().then((read) => {
    if (!read || !node.isConnected || typed || taken) return;
    field.value = shownHex(read.hex) + (read.alpha !== null ? Math.round(read.alpha * 255).toString(16).padStart(2, "0").toUpperCase() : "");
    preview();
    hint.textContent = "From the clipboard: Return applies it";
    if (document.activeElement === field) field.select();
  });
  return node;
}

// Where the popover opens: under what is chosen (or over it, where there is no room under it),
// its left edge with its left -- else by the inspector's top.
function anchorPoint(anchor, fallback) {
  if (anchor && anchor.width !== undefined) return { x: anchor.left, y: anchor.bottom + 8 };
  const box = fallback?.getBoundingClientRect?.();
  if (box?.width) return { x: box.left + 12, y: box.top + 12 };
  return { x: innerWidth / 2 - 124, y: innerHeight / 3 };
}
function place(node, anchor, fallback) {
  const width = node.offsetWidth, height = node.offsetHeight;
  let left, top;
  if (anchor && anchor.width !== undefined) {
    left = anchor.left + Math.min(0, (anchor.width - width) / 2);
    top = anchor.bottom + 8;
    if (top + height > innerHeight - 8) top = anchor.top - 8 - height;
    if (top < 8) top = Math.max(8, Math.min(innerHeight - 8 - height, anchor.top + 8));
  } else {
    const box = fallback?.getBoundingClientRect?.();
    left = box?.width ? box.left + Math.max(8, (box.width - width) / 2) : innerWidth / 2 - width / 2;
    top = box?.width ? box.top + 12 : innerHeight / 3;
  }
  node.style.left = `${Math.round(Math.min(Math.max(8, left), innerWidth - width - 8))}px`;
  node.style.top = `${Math.round(Math.min(Math.max(8, top), innerHeight - height - 8))}px`;
}

// Whether the popover is open now.
export const colourOpen = () => Boolean(open?.isConnected);

// What an editor gives: `kinds()` (what is chosen, by kind, with its colours: colourChoices),
// `anchor()` (where it is on the screen), `fallback()` (the inspector), `studio`, `settled()`. Its key
// (true if taken), its command for the palette and the Mac app's Format › Set Colour…, and the
// popover opened.
export function colourKey({ kinds, anchor = () => null, fallback = () => null, studio = null, settled = null }) {
  const now = () => { try { return colourChoices(kinds()); } catch (error) { console.error(error); return []; } };
  const show = () => {
    const choices = now();
    if (!choices.length) return false;
    setColour(choices, { anchor: anchor(), fallback: fallback(), studio, settled });
    return true;
  };
  return {
    key: (event) => isColourKey(event) && show(),
    commands: () => {
      const choices = now();
      return choices.length ? [{ icon: "palette", label: SET_COLOUR, keys: SET_COLOUR_KEYS, hint: choices[0].said, run: () => { show(); } }] : [];
    },
    show,
  };
}
