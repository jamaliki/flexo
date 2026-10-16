// Find and replace, across a whole document: the find bar ⌘F opens (Edit › Find in the Mac
// app), and what the top bar's search finds in the document (shell.js's palette). One engine
// for both (finding.js); each kind says where its words are and how to go to them.
//
// A kind's editor makes its finder -- finder(studio, host) -- and the studio has it as
// `studio.finder`. `host` is the kind's:
//   fields()           its words, as finding.js's fields (read again only after a change)
//   place(bar)         the bar put where it goes; unplace(bar), taken away
//   from()             where the document is shown now, to find on from there (a slide's index)
//   group(match)       where a match is, for the search's list: { key, label, title }
//   go(match)          shown: its slide, its notes
//   show(matches, current, query, options), hide()   the matches marked where they are shown
//   replace(changes, words, label)   each change { field, ranges } made, one step in the history
//   leave(match)       the bar closed (Esc): what is chosen left on the last match
//
// As words are typed every match is found, the first from where the document is shown gone
// to; Return and ⇧Return in its field go to the next and the one before -- and n and ⇧N
// (vim's) wherever no words are typed, while it is open. Match Case and
// Whole Words narrow what is found. Replace puts the words typed in place of the match gone
// to and goes on to the next; Replace All, of every match. Esc closes it.

import { h, icon, ui, toast } from "./ui.js";
import { wordIndex, search, around, ordinals, patternOf, findIn, findStep } from "./finding.js";

const MAC = typeof navigator !== "undefined" && /Mac|iP/.test(navigator.platform || "");
// What a match is known by again once the document has changed: its field, where it is.
const keyOf = (field) => JSON.stringify(field.path ?? [field.file, field.target]);

export function finder(studio, host) {
  const index = wordIndex();
  let fields = [], stale = true;
  const state = { query: "", matchCase: false, wholeWords: false, replacing: false, words: "", open: false };
  let matches = [], current = -1;
  const read = () => {
    if (stale) { fields = index.build(host.fields()); stale = false; }
    return fields;
  };
  const options = () => ({ matchCase: state.matchCase, wholeWords: state.wholeWords });

  // -- the bar --
  const input = h("input.find-input", { type: "text", placeholder: "Find", spellcheck: false, "aria-label": "Find" });
  const count = h("span.find-count", { "aria-live": "polite" });
  const words = h("input.find-input", { type: "text", placeholder: "Replace", spellcheck: false, "aria-label": "Replace" });
  const toggle = (label, key, title) => {
    const button = h("button.chip-toggle.find-option", { type: "button", title, "aria-pressed": "false",
      onmousedown: (event) => event.preventDefault(),
      onclick: () => { state[key] = !state[key]; showOptions(); run({ keep: true }); } }, label);
    return button;
  };
  const caseButton = toggle("Match Case", "matchCase", "Match Case");
  const wholeButton = toggle("Whole Words", "wholeWords", "Whole Words");
  const showOptions = () => {
    for (const [button, key] of [[caseButton, "matchCase"], [wholeButton, "wholeWords"]]) {
      button.classList.toggle("on", state[key]);
      button.setAttribute("aria-pressed", String(state[key]));
    }
  };
  const step = (glyph, title, way) => {
    const button = ui.button("", () => go(way), { kind: "ghost", small: true, icon: glyph, title });
    button.addEventListener("mousedown", (event) => event.preventDefault());
    return button;
  };
  const previousButton = step("up", "Previous (⇧↩, or ⇧N)", -1), nextButton = step("down", "Next (↩, or N)", 1);
  const more = h("button.btn.ghost.small.icon.find-more", { type: "button", title: "Replace (⌥⌘F)", "aria-expanded": "false",
    onmousedown: (event) => event.preventDefault(), onclick: () => showReplace(!state.replacing, { focus: !state.replacing }) }, icon("chevron"));
  const replaceButton = ui.button("Replace", () => replaceOne(), { small: true });
  const allButton = ui.button("Replace All", () => replaceAll(), { small: true });
  const done = ui.button("Done", () => close(), { small: true });
  const replaceRow = h("div.find-row.find-replace", { hidden: true },
    h("label.find-field", {}, words), replaceButton, allButton);
  const bar = h("div.find-bar", { role: "search" },
    h("div.find-row", {}, more,
      h("label.find-field", {}, icon("search"), input, count),
      previousButton, nextButton, caseButton, wholeButton, h("span.find-gap"), done),
    replaceRow);
  // (Its keys are its own: none goes on to the document under it.)
  bar.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); return; }
    if (event.key === "Enter" && event.target === input) { event.preventDefault(); event.stopPropagation(); go(event.shiftKey ? -1 : 1); return; }
    if (event.key === "Enter" && event.target === words) { event.preventDefault(); event.stopPropagation(); if (event.altKey || event.metaKey) replaceAll(); else replaceOne(); }
  });
  input.addEventListener("input", () => { state.query = input.value; current = -1; run({ go: true }); });
  words.addEventListener("input", () => { state.words = words.value; });

  function showReplace(on, { focus = false } = {}) {
    state.replacing = on;
    replaceRow.hidden = !on;
    more.classList.toggle("open", on);
    more.setAttribute("aria-expanded", String(on));
    more.title = on ? "Hide Replace" : "Replace (⌥⌘F)";
    if (focus) { words.focus(); words.select(); }
    else if (!on && bar.contains(document.activeElement)) input.focus();
  }

  // -- what is found --
  function said() {
    const total = matches.length;
    count.textContent = !state.query.trim() ? "" : !total ? "No matches" : current >= 0 ? `${current + 1} of ${total}` : `${total} found`;
    count.classList.toggle("none", Boolean(state.query.trim()) && !total);
    for (const button of [previousButton, nextButton]) button.disabled = !total;
    replaceButton.disabled = current < 0;
    allButton.disabled = !total;
  }
  // Found again: the match gone to kept where it was (`keep`), else the first from where
  // the document is shown; gone to (`go`), or only marked.
  function run({ keep = false, go: going = false, after = null } = {}) {
    const was = keep && current >= 0 ? matches[current] : null;
    matches = state.open || state.query ? search(read(), state.query, options()) : [];
    current = -1;
    if (matches.length) {
      if (after) current = Math.max(0, matches.findIndex((match) => keyOf(match.field) === after.key ? match.start >= after.start : match.index > after.index));
      else if (was) {
        const key = keyOf(was.field);
        current = matches.findIndex((match) => keyOf(match.field) === key && match.start === was.start);
        if (current < 0) current = Math.max(0, matches.findIndex((match) => match.index >= was.index));
      } else {
        const from = host.from?.() ?? 0;
        current = Math.max(0, matches.findIndex((match) => (match.field.slide ?? 0) >= from));
      }
      if (current >= matches.length || current < 0) current = 0;
    }
    said();
    if (going && current >= 0) host.go(matches[current]);
    mark();
  }
  function mark() {
    if (!state.open || !matches.length) { host.hide(); return; }
    host.show(matches, current >= 0 ? matches[current] : null, state.query, options(), read());
  }
  function go(way) {
    if (!matches.length) return;
    current = current < 0 ? (way > 0 ? 0 : matches.length - 1) : (current + way + matches.length) % matches.length;
    said();
    host.go(matches[current]);
    mark();
  }

  // -- putting words in their place --
  const changesOf = (list) => {
    const byField = new Map();
    for (const match of list) {
      const key = keyOf(match.field);
      if (!byField.has(key)) byField.set(key, { field: match.field, ranges: [] });
      byField.get(key).ranges.push([match.start, match.end]);
    }
    return [...byField.values()];
  };
  let busy = false;
  async function replaceOne() {
    const match = current >= 0 ? matches[current] : null;
    if (!match || busy) return;
    busy = true;
    try {
      await host.replace(changesOf([match]), state.words, "Replace");
      stale = true;
      // On to the next: the first match after the words put in.
      run({ go: true, after: { key: keyOf(match.field), start: match.start + state.words.length, index: match.index } });
    } catch (error) {
      toast(`Couldn’t replace: ${error?.message || error}`, { kind: "error", icon: "error", seconds: 5 });
    } finally { busy = false; }
  }
  async function replaceAll() {
    if (!matches.length || busy) return;
    busy = true;
    const total = matches.length;
    try {
      await host.replace(changesOf(matches), state.words, "Replace All");
      stale = true;
      run();
      toast(`Replaced ${total} ${total === 1 ? "match" : "matches"}`, { icon: "check", seconds: 2.5 });
    } catch (error) {
      toast(`Couldn’t replace: ${error?.message || error}`, { kind: "error", icon: "error", seconds: 5 });
    } finally { busy = false; }
  }

  // -- opening and closing --
  function open({ replace = false, query = null, select = true } = {}) {
    if (!state.open) {
      state.open = true;
      host.place(bar);
    }
    if (query !== null && query !== state.query) { state.query = query; current = -1; }
    if (input.value !== state.query) input.value = state.query;
    if (replace) showReplace(true);
    showOptions();
    // (Find and Replace… with words to find already: the words to put in their place typed.)
    const field = replace && state.query.trim() ? words : input;
    field.focus({ preventScroll: true });
    if (select || field === words) field.select();
    run({ go: true, keep: query === null });
    studio.workspace?.emit?.("status", studio);
  }
  function close({ leave = true } = {}) {
    if (!state.open) return;
    state.open = false;
    const match = current >= 0 ? matches[current] : null;
    host.hide();
    host.unplace(bar);
    if (leave && match) host.leave(match);
    studio.workspace?.emit?.("status", studio);
  }

  // The document changed (typed in, undone, another's edit): found again, the match gone to
  // kept, a moment after the change -- never at each key typed.
  let soon = 0;
  studio.on("change", () => {
    stale = true;
    if (!state.open) return;
    clearTimeout(soon);
    soon = setTimeout(() => run({ keep: true }), 120);
  });

  const api = {
    open, close,
    get isOpen() { return state.open; },
    get query() { return state.query; },
    next: () => { if (!state.open) open({ select: false }); else go(1); },
    previous: () => { if (!state.open) open({ select: false }); else go(-1); },
    // Words chosen as what is found (Use Selection for Find, ⌘E).
    useSelection(text) {
      const chosen = String(text ?? "").replace(/\s+/g, " ").trim();
      if (!chosen) return false;
      open({ query: chosen });
      return true;
    },
    // Its marks placed again (the slide drawn again, the notes typed in).
    shown: () => { if (state.open) mark(); },
    // Its words read again (a figure file read), found again.
    refresh: () => { stale = true; if (state.open) run({ keep: true }); },
    // What the top bar's search finds, by where each is: [{ key, label, title, rows: [{
    // match, name, before, found, after }] }], as many as `most` matches in all, with how
    // many there are (`total`).
    results(query, { most = 40 } = {}) {
      const found = search(read(), query, {});
      const groups = new Map();
      for (const match of found.slice(0, most)) {
        const where = host.group(match);
        if (!groups.has(where.key)) groups.set(where.key, { ...where, rows: [] });
        groups.get(where.key).rows.push({ match, name: match.field.name || "", ...around(match.field.words.text, match.start, match.end) });
      }
      return { total: found.length, groups: [...groups.values()] };
    },
    // One of those chosen: gone to and marked, as the find bar goes to it -- the bar opened on
    // it, its words found.
    choose(query, match) {
      state.matchCase = false;
      state.wholeWords = false;
      open({ query, select: false });
      const key = keyOf(match.field);
      const at = matches.findIndex((one) => keyOf(one.field) === key && one.start === match.start);
      if (at >= 0 && at !== current) { current = at; said(); host.go(matches[current]); mark(); }
    },
  };
  studio.finder = api;
  return api;
}

// The keys, wherever the keys are in the document: ⌘F (Find…), ⌥⌘F (Find and Replace…), n
// and ⇧N while the bar is open and no words are typed (Find Next, Find Previous: finding.js's
// findStep), ⌘E (Use Selection for Find: but while words are typed on a slide, where it is
// Code). In the Mac app the menus' items do the same. (Taken on the window as the key comes,
// before the document's own keys: n never starts typing over a shape chosen while finding.)
export function findKeys(workspace) {
  window.addEventListener("keydown", (event) => {
    const found = workspace.active?.finder;
    if (!found || document.querySelector(".scrim, .present")) return;
    const take = () => { event.preventDefault(); event.stopImmediatePropagation(); };
    // (A menu open -- a right-click's, a pop-up's -- has the keys.)
    const step = document.querySelector(".menu") ? 0 : findStep(event, { open: found.isOpen, at: document.activeElement });
    if (step) { take(); if (step > 0) found.next(); else found.previous(); return; }
    if (!(MAC ? event.metaKey : event.ctrlKey) || (MAC && event.ctrlKey)) return;
    if (event.code === "KeyF" && !event.shiftKey) { take(); found.open({ replace: event.altKey }); return; }
    if (event.code === "KeyE" && !event.altKey && !event.shiftKey) {
      const at = document.activeElement;
      // (Words typed in on a slide: ⌘E makes them code.)
      if (at?.isContentEditable) return;
      const text = chosenWords();
      if (text && found.useSelection(text)) take();
    }
  }, true);
}

// The words chosen now: in the field being typed in, else on the page.
export function chosenWords() {
  const at = document.activeElement;
  if (at && /^(INPUT|TEXTAREA)$/.test(at.tagName) && typeof at.selectionStart === "number") return at.value.slice(at.selectionStart, at.selectionEnd);
  return String(globalThis.getSelection?.() || "");
}

// -- the matches on a drawing --------------------------------------------------------------

const SVG_NS = "http://www.w3.org/2000/svg";

// The matches on a drawing (a slide's, a figure's: `svg`), marked over their words: each
// faint, `current` strong. `fields` are the drawing's own, in order (those it draws; matches
// in others are not on it). A field's words are found under its `element` id -- else the
// nearest id above it that the drawing has (a line's own words under its line) -- at the same
// count among the words of the fields there, spaces aside, as the drawing breaks its lines
// where they wrap. Words drawn otherwise (an equation) have their object framed instead.
// The current mark, if any, is answered. `layer` names the marks' own layer, so that other
// marks (a document's TODOs, todomarks.js) lie beside these and are taken away apart from
// them; with `lettered`, words not found among letters that are drawn (a drawing of the
// words before the latest change) are not framed: only those drawn with no letters at all.
export function markDrawing(svg, fields, matches, current, query, options = {}, { dark = false, layer: kind = "find-marks", lettered = false } = {}) {
  unmarkDrawing(svg, kind);
  if (!svg || !matches.length) return null;
  const layer = document.createElementNS(SVG_NS, "g");
  layer.setAttribute("class", `${kind}${dark ? " dark" : ""}`);
  layer.setAttribute("aria-hidden", "true");
  const elements = new Map();
  const elementOf = (field) => {
    if (elements.has(field)) return elements.get(field);
    let id = field.element || "", found = null;
    while (id && !found) {
      found = svg.querySelector(`[id="${CSS.escape(id)}"]`);
      if (found === svg) found = null;
      id = id.includes(".") ? id.slice(0, id.lastIndexOf(".")) : "";
    }
    elements.set(field, found);
    return found;
  };
  const shown = new Set(matches.map((match) => match.field));
  // The fields drawn under each element that holds a match, in order.
  const under = new Map();
  for (const field of fields) {
    const element = elementOf(field);
    if (!element) continue;
    if (!under.has(element)) under.set(element, []);
    under.get(element).push(field);
  }
  const toRoot = svg.getScreenCTM()?.inverse();
  const pattern = patternOf(query, { ...options, spaced: false });
  let mine = null;
  const rect = (box, strong, whole = false) => {
    const node = document.createElementNS(SVG_NS, "rect");
    for (const [key, value] of Object.entries({ x: box.x - 1.5, y: box.y - 0.5, width: box.width + 3, height: box.height + 1, rx: 2 })) node.setAttribute(key, String(Math.round(value * 100) / 100));
    node.setAttribute("class", [strong ? "current" : "", whole ? "whole" : ""].filter(Boolean).join(" "));
    layer.append(node);
    if (strong) mine = node;
  };
  // A box in an element's own units, in the drawing's.
  const inRoot = (element, box) => {
    const matrix = toRoot && element.getScreenCTM() ? toRoot.multiply(element.getScreenCTM()) : null;
    if (!matrix) return box;
    const corners = [[box.x, box.y], [box.x + box.width, box.y], [box.x, box.y + box.height], [box.x + box.width, box.y + box.height]]
      .map(([x, y]) => new DOMPoint(x, y).matrixTransform(matrix));
    const xs = corners.map((point) => point.x), ys = corners.map((point) => point.y);
    return { x: Math.min(...xs), y: Math.min(...ys), width: Math.max(...xs) - Math.min(...xs), height: Math.max(...ys) - Math.min(...ys) };
  };
  for (const [element, own] of under) {
    const here = matches.filter((match) => own.includes(match.field));
    if (!here.length || !own.some((field) => shown.has(field))) continue;
    const counted = ordinals(own, here, query, options);
    // The element's letters, spaces aside, each where it is drawn.
    const texts = element.localName === "text" ? [element] : [...element.querySelectorAll("text")];
    const letters = [];
    for (const text of texts) {
      const words = text.textContent || "";
      const many = Math.min(words.length, typeof text.getNumberOfChars === "function" ? text.getNumberOfChars() : 0);
      for (let k = 0; k < many; k += 1) if (!/\s/.test(words[k])) letters.push({ text, k, letter: words[k] });
    }
    const places = pattern ? findIn(letters.map((one) => one.letter).join(""), pattern) : [];
    for (const match of here) {
      const strong = match === current;
      const place = places[counted.get(match)];
      if (!place) {
        if (lettered && letters.length) continue;
        try { rect(inRoot(element, element.getBBox()), strong, true); } catch { /* not drawn */ }
        continue;
      }
      // Its letters' boxes, one a line.
      let line = null;
      for (let k = place[0]; k < place[1]; k += 1) {
        const { text, k: at } = letters[k];
        let box;
        try { box = inRoot(text, text.getExtentOfChar(at)); } catch { continue; }
        if (line && line.text === text && Math.abs(line.box.y - box.y) < box.height / 2) {
          const right = Math.max(line.box.x + line.box.width, box.x + box.width), left = Math.min(line.box.x, box.x);
          line.box = { x: left, y: Math.min(line.box.y, box.y), width: right - left, height: Math.max(line.box.height, box.height) };
        } else {
          if (line) rect(line.box, strong);
          line = { text, box };
        }
      }
      if (line) rect(line.box, strong);
    }
  }
  svg.append(layer);
  return mine;
}
export function unmarkDrawing(svg, kind = "find-marks") {
  for (const layer of svg?.querySelectorAll(`:scope > g.${kind}`) || []) layer.remove();
}
