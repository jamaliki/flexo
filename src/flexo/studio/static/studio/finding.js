// Finding words in a document, and putting others in their place: the one engine the find
// bar (⌘F, findbar.js) and the top bar's search (the palette) both use, read in Node as it
// is in the studio.
//
// A document's words are a list of fields, each a line of words where it is kept: a slide's
// title, an item of a list, a table's cell, the notes, a figure's label. A field is
// { kind, value, ... } -- its kind says how its words are written: "markup" (flexo markup:
// **bold**, *italic*, `code`, $maths$, [links](url), [colours]{accent}), "label" (a figure's
// label: markup, \n a new line in it, as flexo.markup.parse_label reads it), "plain" (notes,
// code: as they are), or "runs" (a figure label written as runs, [{ text, weight }...]). The
// rest of a field is its kind's own (where it is, for going there), kept as it is.
//
// Words are found as they read, markup aside: "enzyme" is found in en**zy**me. Any run of
// spaces or new lines typed matches any other, and a straight quote a curly one. Put back,
// the words that replace those found take the look of the first letter found, and every mark
// about them is kept.

// -- a field's words as they read --------------------------------------------------------

const SPACE = /\s/;
const WORD = /[\p{L}\p{N}_]/u;

// Where maths is, as flexo reads it (richtext.js's mathSpans): $...$ (not a price: no space
// inside its ends, no digit after it, unless plainly TeX), $$...$$, \(...\) and \[...\].
function closingDollar(text, start) {
  for (let index = start; index < text.length; index += 1) {
    if (text[index] === "\\") { index += 1; continue; }
    if (text[index] !== "$") continue;
    const inside = text.slice(start, index);
    if (!inside) return -1;
    const tex = /[\\^_{]/.test(inside.replace(/\\\$/g, ""));
    if (/\d/.test(text[index + 1] || "") && !tex) return -1;
    if ((SPACE.test(inside[0]) || SPACE.test(inside[inside.length - 1])) && !tex) return -1;
    return index;
  }
  return -1;
}

// Markup read for its letters: which of its characters are marks (`mark`), which are read
// as they are whatever they look like (`literal`: inside code and maths, an escaped mark),
// and the marks that go in pairs (`groups`: each { open: [from, to], close: [from, to] }, the
// words between them its own). With `breaks` (a figure's label), \n is a new line: its n
// read as one (`breaking`).
export function parseMarkup(source, { breaks = false } = {}) {
  const text = String(source ?? "");
  const n = text.length;
  const mark = new Uint8Array(n), literal = new Uint8Array(n), breaking = new Set();
  const groups = [];
  const pair = (a, b, c, d, kind) => {
    for (let k = a; k < b; k += 1) mark[k] = 1;
    for (let k = c; k < d; k += 1) mark[k] = 1;
    groups.push({ open: [a, b], close: [c, d], kind });
  };
  const plainly = (from, to) => { for (let k = from; k < to; k += 1) literal[k] = 1; };
  // Escapes, code and maths, from the start: what is in them is no mark.
  for (let index = 0; index < n;) {
    const character = text[index], next = text[index + 1] || "";
    if (character === "\\" && "*`]$[".includes(next) && next) {
      mark[index] = 1; literal[index + 1] = 1; index += 2; continue;
    }
    if (character === "\\" && next === "\\") { mark[index] = 1; literal[index + 1] = 1; index += 2; continue; }
    if (breaks && character === "\\" && next === "n") { mark[index] = 1; literal[index + 1] = 1; breaking.add(index + 1); index += 2; continue; }
    if (character === "`") {
      const end = text.indexOf("`", index + 1);
      if (end > index) { pair(index, index + 1, end, end + 1, "code"); plainly(index + 1, end); index = end + 1; continue; }
    }
    if (text.startsWith("$$", index) || text.startsWith("\\[", index)) {
      const end = text.indexOf(character === "$" ? "$$" : "\\]", index + 2);
      if (end > index + 2) { pair(index, index + 2, end, end + 2, "maths"); plainly(index + 2, end); index = end + 2; continue; }
    }
    if (text.startsWith("\\(", index)) {
      const end = text.indexOf("\\)", index + 2);
      if (end > index + 2) { pair(index, index + 2, end, end + 2, "maths"); plainly(index + 2, end); index = end + 2; continue; }
    }
    if (character === "$") {
      const end = closingDollar(text, index + 1);
      if (end > index) { pair(index, index + 1, end, end + 1, "maths"); plainly(index + 1, end); index = end + 1; continue; }
    }
    index += 1;
  }
  const free = (k) => !mark[k] && !literal[k];
  // Links and colours: [words](address), [words]{colour} -- one inside another too.
  for (let index = 0; index < n; index += 1) {
    if (text[index] !== "[" || !free(index)) continue;
    let depth = 0, end = -1;
    for (let k = index; k < n && text[k] !== "\n"; k += 1) {
      if (!free(k)) continue;
      if (text[k] === "[") depth += 1;
      else if (text[k] === "]" && --depth === 0) { end = k; break; }
    }
    if (end < 0 || end === index + 1) continue;
    const tail = /^(\([^)\s]+\)|\{[^}\s]+\})/.exec(text.slice(end + 1));
    if (tail) pair(index, index + 1, end, end + 1 + tail[0].length, tail[0][0] === "(" ? "link" : "colour");
  }
  // Emphasis: * and ** paired as Markdown pairs them (richtext.js's emphasis): an opener
  // touches the word after it, a closer the word before.
  const marks = [];
  for (let index = 0; index < n; index += 1) {
    if (text[index] !== "*" || !free(index)) continue;
    let run = 0;
    while (index + run < n && text[index + run] === "*" && free(index + run)) run += 1;
    let at = index;
    for (let left = run; left > 0;) { const size = left >= 2 ? 2 : 1; marks.push({ at, size }); at += size; left -= size; }
    index += run - 1;
  }
  const open = [];
  for (const one of marks) {
    const before = text[one.at - 1], after = text[one.at + one.size];
    const canClose = before !== undefined && !SPACE.test(before), canOpen = after !== undefined && !SPACE.test(after);
    const same = open.filter((other) => other.size === one.size);
    if (canClose && same.length) {
      const opener = same[same.length - 1];
      open.splice(open.indexOf(opener), 1);
      pair(opener.at, opener.at + opener.size, one.at, one.at + one.size, one.size === 2 ? "bold" : "italic");
    } else if (canOpen) open.push(one);
  }
  return { text, mark, literal, groups, breaking };
}

// A field's words as they read: `text`, and where each of its letters is in what is written
// (`at`, one more than its letters: where the last ends).
export function wordsOf(value, kind = "markup") {
  if (kind === "runs") {
    const runs = Array.isArray(value) ? value : [];
    let text = "";
    const at = [];
    runs.forEach((run, index) => {
      const words = String(run?.text ?? "");
      for (let k = 0; k < words.length; k += 1) at.push([index, k]);
      text += words;
    });
    const last = runs.length ? [runs.length - 1, String(runs[runs.length - 1]?.text ?? "").length] : [0, 0];
    at.push(last);
    return { text, at };
  }
  const source = String(value ?? "");
  if (kind !== "markup" && kind !== "label") {
    const at = new Array(source.length + 1);
    for (let k = 0; k <= source.length; k += 1) at[k] = k;
    return { text: source, at };
  }
  const { mark, breaking } = parseMarkup(source, { breaks: kind === "label" });
  let text = "";
  const at = [];
  for (let k = 0; k < source.length; k += 1) {
    if (mark[k]) continue;
    at.push(k);
    text += breaking.has(k) ? "\n" : source[k];
  }
  at.push(at.length ? at[at.length - 1] + 1 : 0);
  return { text, at };
}

// -- finding -------------------------------------------------------------------------------

const QUOTES = { "'": "['‘’]", "‘": "['‘’]", "’": "['‘’]", "\"": "[\"“”]", "“": "[\"“”]", "”": "[\"“”]" };
const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\/-]/g, "\\$&");

// What is typed to find, as a pattern: spaces as any spaces, a quote as any quote of its
// kind. `spaced: false` leaves spaces out altogether (words found in a drawing, whose lines
// drop the spaces they break at). Null when there is nothing to find.
export function patternOf(query, { matchCase = false, spaced = true } = {}) {
  const typed = String(query ?? "");
  if (!typed.trim()) return null;
  let source = "";
  for (const part of typed.split(/(\s+)/)) {
    if (!part) continue;
    if (SPACE.test(part)) { source += spaced ? "\\s+" : ""; continue; }
    for (const character of part) source += QUOTES[character] || escapeRegExp(character);
  }
  return source ? new RegExp(source, matchCase ? "gu" : "giu") : null;
}

// Where `query` is in `text`: [[start, end], ...] -- with `wholeWords`, only where it is not
// part of a longer word.
export function findIn(text, query, options = {}) {
  const pattern = query instanceof RegExp ? new RegExp(query.source, query.flags) : patternOf(query, options);
  if (!pattern) return [];
  const words = String(text ?? "");
  const found = [];
  for (let match = pattern.exec(words); match; match = pattern.exec(words)) {
    const start = match.index, end = start + match[0].length;
    if (end === start) { pattern.lastIndex += 1; continue; }
    if (options.wholeWords) {
      const first = words[start], last = words[end - 1];
      if (WORD.test(first) && WORD.test(words[start - 1] || "")) continue;
      if (WORD.test(last) && WORD.test(words[end] || "")) continue;
    }
    found.push([start, end]);
  }
  return found;
}

// A document's words, read once each: fields kept as they are, each with its words as they
// read (`words`), those read before taken again as they were (the same words read once,
// however often the document changes about them).
export function wordIndex() {
  let read = new Map();
  return {
    build(fields) {
      if (read.size > 50000) read = new Map();
      return fields.map((field) => {
        const key = field.kind === "runs" ? `r\u0000${JSON.stringify(field.value)}` : `${field.kind}\u0000${field.value}`;
        let words = read.get(key);
        if (!words) { words = wordsOf(field.value, field.kind); read.set(key, words); }
        return { ...field, words };
      });
    },
  };
}

// Every match in fields read by wordIndex: { field, index (the field's place), start, end }
// in the fields' order, then each field's.
export function search(fields, query, options = {}) {
  const pattern = patternOf(query, options);
  if (!pattern) return [];
  const found = [];
  fields.forEach((field, index) => {
    const words = field.words || wordsOf(field.value, field.kind);
    for (const [start, end] of findIn(words.text, pattern, options)) found.push({ field, index, start, end });
  });
  return found;
}

// The words about a match, to show it in a list: { before, found, after }, cut at words with
// an ellipsis, one line.
export function around(text, start, end, { before = 30, after = 46 } = {}) {
  const words = String(text ?? "");
  let from = Math.max(0, start - before), to = Math.min(words.length, end + after);
  if (from > 0) { const space = words.slice(from, start).search(/\s/); if (space >= 0) from += space + 1; }
  if (to < words.length) { const tail = words.slice(end, to), space = tail.search(/\s\S*$/); if (space > 0) to = end + space; }
  const flat = (part) => part.replace(/\s+/g, " ");
  return {
    before: `${from > 0 ? "…" : ""}${flat(words.slice(from, start)).trimStart()}`,
    found: flat(words.slice(start, end)),
    after: `${flat(words.slice(end, to)).trimEnd()}${to < words.length ? "…" : ""}`,
  };
}

// -- putting words in their place ----------------------------------------------------------

// Words as markup that reads back as them: each mark escaped (richtext.js's markupOfWords).
export const markupOfWords = (text) => String(text ?? "").replace(/\\(?=[([])/g, "\\\\").replace(/[*`$]/g, "\\$&")
  .replace(/\\?\](?=[({])|\\\]/g, (found) => (found.length > 1 ? "\\\\]" : "\\]"));

// Marks that pair with nothing between them (bold about words since replaced by none) taken
// out, until there are none.
export function tidyMarkup(source) {
  let text = String(source ?? "");
  for (let round = 0; round < 6; round += 1) {
    const { groups } = parseMarkup(text);
    const empty = groups.filter((group) => group.open[1] === group.close[0]);
    if (!empty.length) break;
    const cut = new Uint8Array(text.length);
    for (const group of empty) for (const [from, to] of [group.open, group.close]) for (let k = from; k < to; k += 1) cut[k] = 1;
    text = [...text].filter((_, k) => !cut[k]).join("");
  }
  return text;
}

// A field's value with the words at `ranges` ([[start, end], ...], as they read) replaced by
// `words`: each takes the look of the first letter it replaces, the marks within it kept
// (those both of whose ends it held, which would now hold nothing, go).
export function replaced(value, kind, ranges, words) {
  const typed = String(words ?? "");
  const order = [...ranges].sort((a, b) => b[0] - a[0]);
  if (kind === "runs") {
    const runs = (Array.isArray(value) ? value : []).map((run) => ({ ...run, text: String(run?.text ?? "") }));
    for (const [start, end] of order) {
      const { at } = wordsOf(runs, "runs");
      const [first, offset] = at[start];
      // Each run's letters within the match taken out, the last run's first.
      for (let k = end - 1; k >= start; k -= 1) {
        const [run, place] = at[k];
        runs[run].text = runs[run].text.slice(0, place) + runs[run].text.slice(place + 1);
      }
      runs[first].text = runs[first].text.slice(0, offset) + typed + runs[first].text.slice(offset);
    }
    const kept = runs.filter((run, index) => run.text || index === 0);
    return kept.length ? kept : [{ text: "" }];
  }
  let text = String(value ?? "");
  if (kind !== "markup" && kind !== "label") {
    for (const [start, end] of order) text = text.slice(0, start) + typed + text.slice(end);
    return text;
  }
  const parsed = parseMarkup(text, { breaks: kind === "label" });
  const { at } = wordsOf(text, kind);
  for (const [start, end] of order) {
    const from = at[start], to = at[end - 1] + 1;
    const inside = (k) => k >= from && k < to;
    const closers = [], openers = [];
    for (const group of parsed.groups) {
      const opens = inside(group.open[0]), closes = inside(group.close[0]);
      if (opens && closes) continue;
      if (closes) closers.push(group.close);
      if (opens) openers.push(group.open);
    }
    const piece = ([a, b]) => text.slice(a, b);
    closers.sort((a, b) => a[0] - b[0]);
    openers.sort((a, b) => a[0] - b[0]);
    // In code or maths, the words go in as typed (a backtick in code escaped); elsewhere each
    // mark typed is written escaped, so it reads back as itself.
    const code = parsed.groups.find((group) => group.kind === "code" && group.open[1] <= from && group.close[0] >= to);
    const maths = parsed.literal[from] && !code && parsed.groups.some((group) => group.kind === "maths" && group.open[1] <= from && group.close[0] >= to);
    const put = code ? typed.replace(/`/g, "\\`") : maths ? typed : markupOfWords(typed);
    // (A mark closing goes against the last word put in, one opening against the next word
    // after it: each touching its words, so it pairs as before.)
    const trail = /\s*$/.exec(put)[0], body = put.slice(0, put.length - trail.length);
    const gap = openers.length ? /^\s*/.exec(text.slice(to))[0] : "";
    text = text.slice(0, from) + body + closers.map(piece).join("") + trail + gap + openers.map(piece).join("") + text.slice(to + gap.length);
  }
  return tidyMarkup(text);
}

// -- a figure's words ----------------------------------------------------------------------

// The words of a figure -- its shapes' labels, its lines' words, its modules' titles, the
// words of the shapes drawn over it -- as fields: each with where it is in the figure
// (`path`, from the figure), what an edit of it names (`target`: { type, id, key }, a shape's,
// a line's or a module's; or { type: "shape", index } for one drawn over it), and the id its
// words are drawn under (`element`, after `prefix`: "slide3.body.0." on a slide).
export function figureFields(figure, { prefix = "", name = "Figure" } = {}) {
  const fields = [];
  if (!figure || typeof figure !== "object") return fields;
  const label = (value) => (Array.isArray(value) ? "runs" : "label");
  const add = (value, path, target, element, part) => {
    if (typeof value === "string" ? !value : !Array.isArray(value) || !value.length) return;
    fields.push({ kind: label(value), value, path, target, element: `${prefix}${element}`, name, part });
  };
  (Array.isArray(figure.nodes) ? figure.nodes : []).forEach((node, k) => {
    if (!node || typeof node !== "object" || node.id == null) return;
    add(node.label, ["nodes", k, "label"], { type: "node", id: String(node.id), key: "label" }, `${node.id}.label`, "Shape");
  });
  const end = (value) => String(typeof value === "object" && value ? value.node ?? value.part ?? "" : value ?? "").split(/[.:]/)[0];
  (Array.isArray(figure.edges) ? figure.edges : []).forEach((edge, k) => {
    if (!edge || typeof edge !== "object") return;
    const id = String(edge.id ?? `edge.${k + 1}.${end(edge.from)}-to-${end(edge.to)}`);
    add(edge.label, ["edges", k, "label"], { type: "edge", id, key: "label" }, `${id}.label`, "Line");
    add(edge.back_label, ["edges", k, "back_label"], { type: "edge", id, key: "back_label" }, `${id}.back_label`, "Line");
    if (Array.isArray(edge.cofactors)) edge.cofactors.forEach((value, c) => add(value, ["edges", k, "cofactors", c], { type: "edge", id, key: "cofactors", item: c }, `${id}.cofactors`, "Line"));
  });
  (Array.isArray(figure.groups) ? figure.groups : []).forEach((group, k) => {
    if (!group || typeof group !== "object" || group.id == null || group.implied) return;
    add(group.label, ["groups", k, "label"], { type: "group", id: String(group.id), key: "label" }, `${group.id}.label`, "Module");
  });
  const shapes = (list, path, element) => (Array.isArray(list) ? list : []).forEach((shape, k) => {
    if (!shape || typeof shape !== "object") return;
    if (Array.isArray(shape.shapes)) shapes(shape.shapes, [...path, k, "shapes"], `${element}.${k}`);
    if (typeof shape.text === "string" && shape.text) fields.push({ kind: "markup", value: shape.text, path: [...path, k, "text"], target: { type: "shape", index: path.length === 1 ? k : null, path: [...path.slice(1), k] }, element: `${prefix}${element}.${k}.text`, name, part: "Shape" });
  });
  shapes(figure.shapes, ["shapes"], "shapes");
  return fields;
}

// -- the matches on a drawing --------------------------------------------------------------

// A match's words found again on its drawing (an SVG, its lines broken where it wraps, its
// marks drawn as looks): the same words at the same count in the drawing's letters, spaces
// aside. `fields` are those of one element, in order; what comes back is, for each match in
// them, which occurrence of its words, spaces aside, it is among them.
export function ordinals(fields, matches, query, options = {}) {
  const pattern = patternOf(query, { ...options, spaced: false });
  const counted = new Map();
  if (!pattern) return counted;
  let before = 0;
  for (const field of fields) {
    const text = (field.words || wordsOf(field.value, field.kind)).text;
    // Each letter's place with spaces taken out.
    const squeezed = [], places = new Array(text.length + 1);
    for (let k = 0; k < text.length; k += 1) { places[k] = squeezed.length; if (!SPACE.test(text[k])) squeezed.push(text[k]); }
    places[text.length] = squeezed.length;
    const starts = findIn(squeezed.join(""), pattern).map(([start]) => start);
    for (const match of matches) {
      if (match.field !== field) continue;
      const at = starts.indexOf(places[match.start]);
      if (at >= 0) counted.set(match, before + at);
    }
    before += starts.length;
  }
  return counted;
}
