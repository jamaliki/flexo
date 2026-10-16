// The Design bar: a document's design -- its theme, colours, fonts and the rest -- in one low
// row of pop-up buttons under the toolbar, each naming what is in use, shared by the deck and
// figure editors (flexo-talk's designbar.js, figure/designbar.js). What is here is the bar's own:
//   - its pop-up buttons, each opening a panel under the bar that stays open while a pop-up in
//     it (a font's list, a choice) is open, as a ribbon's drop-down galleries do;
//   - a gallery of thumbnails for a panel (a deck's slide, a figure, in each theme), in a grid,
//     drawn as they come into sight, kept, and drawn again only once what they show has changed;
//   - the live preview: what the pointer is over in an open panel shown on the document as it
//     would be, the document itself unchanged until it is chosen. Nothing in the bar itself is.

import { h, clear, icon, closeMenu, roving } from "./ui.js";
import { keepFocus, picture } from "./studio.js";

if (typeof document !== "undefined" && !document.querySelector('link[href="/static/studio/ribbon.css"]')) {
  document.head.append(h("link", { rel: "stylesheet", href: "/static/studio/ribbon.css" }));
}

// The bar: its pop-up buttons side by side. They don't take the keys from the document when
// clicked, as a Mac toolbar's don't.
export function ribbonBar(label = "Design") {
  const node = h("div.ribbon", { role: "toolbar", "aria-label": label, hidden: true });
  node.addEventListener("mousedown", (event) => {
    if (event.target.closest("button") && !event.target.closest("input, select, textarea")) event.preventDefault();
  });
  // Narrower, its pull-downs lose their names, then more (ribbon.css): told by its width.
  new ResizeObserver(() => {
    const width = node.clientWidth;
    if (!width) return;
    node.classList.toggle("narrow", width < 1080);
    node.classList.toggle("tight", width < 760);
  }).observe(node);
  return node;
}

export const ribbonSep = () => h("div.ribbon-sep", { role: "separator" });

// A pop-up button: what is in use -- its face (a palette's colours, a theme's page) and its name
// ("Paper", "16:9", a font's name in itself), else the button's own -- and a chevron; pressed,
// its panel (`panel()`, drawn again as the document changes) under the bar, or away again.
export function pull({ label, face = null, title = "", panel, className = "", onOpen, onClose }) {
  const faced = h("span.ribbon-face", {}, face);
  const said = h("span.ribbon-label", {}, label);
  const button = h(`button.ribbon-pull${className ? `.${className}` : ""}`, {
    type: "button", title: title || label, "aria-label": title || label, "aria-haspopup": "dialog", "aria-expanded": "false",
    onclick: () => { if (openDrop?.anchor === button) closeDrop(); else { onOpen?.(); drop(button, panel, { onClose }); } },
  }, faced, said, icon("chevron-down", { class: "ribbon-chevron" }));
  faced.hidden = !face;
  // What it shows now: `face` beside `text` (words, or a node), its tooltip naming both.
  button.show = ({ face: shown = null, text = label, title: named = label } = {}) => {
    clear(faced, shown);
    faced.hidden = !shown;
    clear(said, text);
    button.title = named;
    button.setAttribute("aria-label", named);
  };
  return button;
}

// -- the panels --

let openDrop = null;

// A panel under `anchor`, as a ribbon's drop-down: closed by a press elsewhere (but in a menu
// opened from it, or a dialog), Esc, its button again, or another opening. `render()` is its
// content, drawn again by redrawDrop() with the keys kept where they were (keepFocus).
export function drop(anchor, render, { className = "", onClose } = {}) {
  closeDrop();
  closeMenu();
  const node = h(`div.ribbon-drop${className ? `.${className}` : ""}`, { role: "dialog", tabIndex: -1, "aria-label": anchor.title || "" });
  const before = document.activeElement;
  // (Drawn again with the keys in it, they stay in it: on what has them still, else the panel.)
  const draw = () => {
    const had = node.contains(document.activeElement);
    // (What it shows is the same nodes still -- a gallery, which keeps itself current: left as
    // it is, scrolled where it was.)
    const made = [render()].flat(Infinity).filter(Boolean);
    if (made.length === node.childNodes.length && made.every((child, index) => node.childNodes[index] === child)) return;
    keepFocus(node, () => clear(node, made));
    if (had && !node.contains(document.activeElement)) node.focus({ preventScroll: true });
  };
  draw();
  document.body.append(node);
  // Under the bar, as a ribbon's drop-down is: the bar's other buttons in reach over it.
  const place = () => {
    const box = anchor.getBoundingClientRect(), width = node.offsetWidth;
    const top = Math.max(box.bottom, anchor.closest(".ribbon")?.getBoundingClientRect().bottom ?? 0) + 2;
    node.style.left = `${Math.max(8, Math.min(box.left, innerWidth - width - 8))}px`;
    node.style.top = `${top}px`;
    node.style.maxHeight = `${Math.max(160, innerHeight - top - 12)}px`;
  };
  place();
  anchor.classList.add("menu-open");
  anchor.setAttribute("aria-expanded", "true");
  const outside = (event) => {
    if (node.contains(event.target) || anchor.contains(event.target) || event.target.closest?.(".menu, .scrim, .toast")) return;
    closeDrop();
  };
  // Esc closes it wherever the keys are (a pop-up in it closes first: ui.js takes that Esc).
  const keys = (event) => {
    if (event.key !== "Escape" || event.defaultPrevented || document.querySelector(".scrim")) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    closeDrop(true);
  };
  document.addEventListener("keydown", keys, true);
  // (Its arrows go from choice to choice, as a menu's do; not to the document under it.)
  node.addEventListener("keydown", (event) => { if (/^Arrow/.test(event.key) && !/^(INPUT|TEXTAREA)$/.test(event.target.tagName)) event.stopPropagation(); });
  setTimeout(() => document.addEventListener("pointerdown", outside, true), 0);
  window.addEventListener("resize", place);
  openDrop = {
    node, anchor, draw, place,
    close: (refocus) => {
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("keydown", keys, true);
      window.removeEventListener("resize", place);
      node.remove();
      onClose?.();
      anchor.classList.remove("menu-open");
      anchor.setAttribute("aria-expanded", "false");
      if ((refocus || node.contains(document.activeElement)) && before?.isConnected) before.focus({ preventScroll: true });
    },
  };
  // The keys come to its first field of words, else its choice in use, else its first control:
  // as a pop-up menu opens.
  const first = node.querySelector("textarea, input:not([type=color]), [contenteditable=true]") || node.querySelector(".on:not(:disabled), [aria-checked=true], [aria-pressed=true]")
    || node.querySelector("button:not(:disabled), [tabindex='0']");
  (first || node).focus({ preventScroll: true });
  return node;
}

export function closeDrop(refocus = false) {
  const was = openDrop;
  openDrop = null;
  was?.close(refocus);
}

export const dropOpen = () => openDrop?.node || null;
// The panel open drawn again: what it shows changed (a choice made, another's edit).
export function redrawDrop() {
  if (!openDrop?.node.isConnected) return;
  openDrop.draw();
  openDrop.place();
}

// -- the live preview --

// What the pointer is over shown on the document (`target()`: the page it is drawn on) as it
// would be: `draw(variant)` answers its drawing ({svg, key}), kept here by `keyOf(variant)`.
// A pointer passing over many is shown the one it stops on (`DWELL`); the document comes back
// as soon as it leaves. Shown, it lies over the page, which is not touched.
const DWELL = 90;
export function previewer({ target, draw, keyOf = (variant) => JSON.stringify(variant), most = 40 }) {
  const kept = new Map();
  let wanted = null, timer = 0, shown = null, holding = null;
  const lay = (svg, key) => {
    const page = target();
    if (!page) return;
    if (!shown || shown.page !== page || !shown.node.isConnected) {
      shown?.node.remove();
      shown = { page, node: h("div.design-preview", { "aria-hidden": "true" }) };
      page.append(shown.node);
    }
    clear(shown.node, picture(svg, `preview:${key}`));
  };
  const fetch = async (variant, key) => {
    if (kept.has(key)) return kept.get(key);
    const asked = Promise.resolve(draw(variant)).catch(() => null);
    kept.set(key, asked);
    const found = await asked;
    if (!found?.svg) kept.delete(key);
    while (kept.size > most) kept.delete(kept.keys().next().value);
    return found;
  };
  const api = {
    // The variant the pointer is over now (null: none, the document as it is).
    show(variant) {
      clearTimeout(timer);
      if (variant === null || variant === undefined) { api.clear(); return; }
      const key = keyOf(variant);
      if (wanted === key) return;
      wanted = key;
      holding = null;
      const run = async () => {
        const found = await fetch(variant, key);
        if (wanted !== key) return;
        if (found?.svg) lay(found.svg, found.key || key);
        else api.drop();
      };
      // (A drawing kept is shown at once: the pointer going back over one is not kept waiting.)
      if (kept.has(key)) run(); else timer = setTimeout(run, DWELL);
    },
    // Nothing shown: the document as it is.
    clear() {
      clearTimeout(timer);
      wanted = null;
      // (Just chosen, it stays over the page until the page is drawn so: no flash of the old.)
      if (holding && shown?.page === target() && shown.node.isConnected) return;
      api.drop();
    },
    drop() { shown?.node.remove(); shown = null; },
    // A variant chosen: kept over the page until the page is drawn anew (`drawn()`).
    hold() { if (shown) holding = wanted || "chosen"; },
    drawn() {
      if (!holding) return;
      // (Drawn anew, the page is another node, or its drawing changed under the preview.)
      holding = null;
      if (wanted === null) api.drop();
    },
    get showing() { return Boolean(shown?.node.isConnected); },
    forget() { kept.clear(); },
  };
  return api;
}

// -- the gallery --

// Thumbnails in a grid that scrolls, each named under it, the one in use marked; the arrows go
// among them. Each is drawn as it comes into sight -- `thumbs(items)` answers their drawings in
// order ({svg, key} or nothing) -- and drawn again only once `version(item)` says what it shows
// has changed, the old one kept in sight meanwhile. `card(item)` stands in until then. Pointed at
// (or reached by the keys), each is shown on the document (`preview(item)`, null once it is
// left); clicked, it is chosen (`pick(item)`).
export function gallery({ label, items = [], name, current, thumbs, card, version, pick, preview, aspect = () => 16 / 9 }) {
  const node = h("div.ribbon-gallery.scroll-thin", { role: "group", "aria-label": label });
  const cells = new Map();
  let list = [];
  // -- drawn as they come into sight, a few asked for at once --
  const seen = new Set();
  let asking = false, again = false;
  const ask = async () => {
    if (asking) { again = true; return; }
    const due = list.filter((item) => seen.has(cells.get(keyOf(item))) && cells.get(keyOf(item)).drawnFor !== version(item) && cells.get(keyOf(item)).failedFor !== version(item));
    if (!due.length) return;
    asking = true;
    const batch = due.slice(0, 6);
    const versions = batch.map((item) => version(item));
    let found = [];
    try { found = (await thumbs(batch)) || []; } catch { found = []; }
    batch.forEach((item, n) => {
      const cell = cells.get(keyOf(item));
      if (!cell) return;
      const drawn = found[n];
      if (drawn?.svg) {
        clear(cell.querySelector(".ribbon-pic"), picture(drawn.svg, `thumb:${drawn.key || versions[n]}`));
        cell.drawnFor = versions[n];
        cell.classList.remove("waiting");
      } else {
        cell.failedFor = versions[n];
        cell.classList.toggle("problem", Boolean(drawn?.error));
        if (drawn?.error) cell.title = `${name(item)}: ${drawn.error}`;
      }
    });
    asking = false;
    if (again || due.length > batch.length) { again = false; ask(); }
  };
  const sight = new IntersectionObserver((entries) => {
    for (const entry of entries) { if (entry.isIntersecting) seen.add(entry.target); else seen.delete(entry.target); }
    ask();
  }, { root: node, rootMargin: "120px 0px" });
  const keyOf = (item) => String(item.value);
  // -- pointed at, reached by the keys --
  let over = null;
  const point = (item) => { over = item; preview?.(item); };
  node.addEventListener("pointerleave", () => { if (over) { over = null; preview?.(null); } });
  node.addEventListener("focusout", (event) => { if (!node.contains(event.relatedTarget) && over) { over = null; preview?.(null); } });
  const cellOf = (item) => {
    const cell = h("button.ribbon-thumb.waiting", {
      type: "button", title: name(item), "aria-label": name(item), "aria-pressed": "false",
      onclick: () => pick(item),
      onpointerenter: () => point(item),
      onfocus: () => { if (cell.matches(":focus-visible")) point(item); },
    }, h("span.ribbon-frame", {}, h("span.ribbon-pic", {}, card(item))), h("span.ribbon-name", {}, name(item)));
    sight.observe(cell);
    return cell;
  };
  const mark = () => {
    const now = current();
    for (const item of list) {
      const cell = cells.get(keyOf(item));
      const chosen = keyOf(item) === String(now);
      cell.classList.toggle("on", chosen);
      cell.setAttribute("aria-pressed", String(chosen));
    }
  };
  let keys = null;
  const api = {
    node,
    // The items it shows (as they change: a theme file added to the folder).
    set(next) {
      list = next;
      const wanted = new Set(list.map(keyOf));
      for (const [key, cell] of cells) if (!wanted.has(key)) { sight.unobserve(cell); seen.delete(cell); cells.delete(key); }
      for (const item of list) if (!cells.has(keyOf(item))) cells.set(keyOf(item), cellOf(item));
      clear(node, list.map((item) => cells.get(keyOf(item))));
      keys ||= roving(node, () => [...node.children]);
      api.refresh();
    },
    // What is in use marked.
    mark() {
      node.style.setProperty("--thumb-ratio", String(aspect()));
      mark();
      keys?.mark(node.querySelector(".ribbon-thumb.on") || node.firstElementChild);
    },
    // ... and what shows something else now drawn again.
    refresh() {
      api.mark();
      ask();
    },
    // The one in use in sight.
    reveal() {
      const chosen = node.querySelector(".ribbon-thumb.on");
      if (!chosen) return;
      const box = chosen.getBoundingClientRect(), room = node.getBoundingClientRect();
      if (box.top < room.top || box.bottom > room.bottom) node.scrollTop += box.top - room.top - (room.height - box.height) / 2;
    },
  };
  // (Filled once it is shown: what it asks of its host may not be there yet.)
  if (items.length) api.set(items);
  return api;
}
