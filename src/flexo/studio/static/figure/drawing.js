// An SVG picture's words and colours, restyled in its panel -- a figure's picture part's, or
// a slide's picture's (flexo.restyle). Its words are set in the figure's font (a slide's:
// the deck's figure font), the faces its file names (As Drawn), or a font chosen; each of
// its texts, in the order they are read, has its words (a line each), size, bold, italic and
// colour; and each colour it is painted in is a well, every use of it changed together. What
// is changed is kept beside the picture -- `font`, `texts` and `colours` -- never in its file.
//
//   drawingSections({ source, describe, family, fonts, owner, font, texts, colours, write, scope })
//
// `describe(source)` answers what the file has (the studio's /api/drawing); `family` is the
// font its words are in unless it says (shown with `owner`'s name: "The Figure’s"); `current()`
// is the picture's `font`, `texts` and `colours` as they are now, and `write(values, { label,
// merge, hold, quiet })` changes them (null: as drawn) -- `quiet` where the control changed
// shows the change already (words typed, a colour dragged).

import { h, clear, icon, ui, inQuotes, typingName } from "/static/studio/studio.js";

const SHOWN = 12;
const kept = new Map();
const opened = new Set();

// What the studio says a picture file has, asked once a few seconds at most: a file
// changed in its program meanwhile is asked again, and the panel drawn again from it.
export function describeDrawing(studio, source) {
  const now = Date.now();
  const known = kept.get(source);
  if (known && now - known.at < 3000) return known;
  const asked = studio.api(studio.url("/api/drawing", { path: source })).catch(() => null);
  const entry = { at: now, asked, value: known?.value ?? null };
  asked.then((value) => { entry.value = value; });
  kept.set(source, entry);
  return entry;
}

const isSvg = (source) => /\.svg$/i.test(String(source || "").trim());
// A text's key as the document writes it, and whether a change is to it.
const keyOf = (text) => (text.id !== undefined ? { id: text.id } : { text: text.text });
const sameKey = (change, text) => (text.id !== undefined ? change?.id === text.id : change?.id === undefined && change?.text === text.text);
const words = (text) => text.lines.join("\n");

export function drawingSections({ source, describe, family, fonts = [], owner = "Figure", current, write, scope }) {
  if (!isSvg(source) || !describe) return null;
  const holder = h("div.drawing-sections");
  const entry = describe(source);
  const fill = (found) => clear(holder, found && (found.texts?.length || found.colours?.length)
    ? sections(found, { family, fonts, owner, current, write, scope }) : null);
  holder.shown = entry.value;
  fill(entry.value);
  // (Drawn from what was known, it is drawn again only should the file say otherwise now.)
  entry.asked.then((found) => {
    if (!found || JSON.stringify(found) === JSON.stringify(holder.shown)) return;
    holder.shown = found;
    if (holder.isConnected) fill(found);
  });
  return holder;
}

function sections(found, options) {
  const { family, fonts, owner, current, write, scope } = options;
  // The picture as it is now -- not as it was when the panel was drawn: an edit made since
  // (words typed) is kept by the next.
  const now = () => {
    const { font, texts, colours } = current() || {};
    return { font, texts: (Array.isArray(texts) ? texts : []).filter((change) => change && typeof change === "object"),
      colours: colours && typeof colours === "object" && !Array.isArray(colours) ? colours : {} };
  };
  const { font } = now(), swaps = now().colours;
  // What is changed of its texts the file still has: one it no longer has goes, quietly, with
  // the next change written.
  const changes = () => now().texts.filter((change) => found.texts.some((text) => sameKey(change, text)));
  const named = (text) => inQuotes(words(text).split("\n")[0].trim().slice(0, 28) || "Text");
  const changeText = (text, values, options) => {
    const others = changes().filter((change) => !sameKey(change, text));
    const was = changes().find((change) => sameKey(change, text)) || {};
    const next = { ...keyOf(text), ...Object.fromEntries(Object.entries(was).filter(([name]) => !["id", "text"].includes(name))) };
    for (let [name, value] of Object.entries(values)) {
      // As drawn is no change: left out, so the file's own shows -- and follows it.
      const drawn = name === "words" ? words(text) : text[name];
      if (name === "words" && typeof value === "string") value = value.replace(/\n+$/, "");
      if (value === null || value === undefined || value === drawn) delete next[name];
      else next[name] = value;
    }
    const kept = Object.keys(next).length > Object.keys(keyOf(text)).length ? [...others, next] : others;
    // In the order the file reads, as the panel lists them.
    kept.sort((a, b) => found.texts.findIndex((text) => sameKey(a, text)) - found.texts.findIndex((text) => sameKey(b, text)));
    write({ texts: kept.length ? kept : null }, options);
  };
  const shownOf = (text) => {
    const change = changes().find((each) => sameKey(each, text)) || {};
    const colour = change.colour ?? swaps[text.colour] ?? text.colour;
    return { words: (change.words ?? words(text)).replace(/\n+$/, ""), size: change.size ?? text.size, bold: change.bold ?? text.bold, italic: change.italic ?? text.italic, colour, change };
  };

  const fontLabel = (value) => (value === "drawn" ? "the Fonts Drawn" : value ? value : `the ${owner}’s Font`);
  const fontField = found.texts.length ? ui.field("Font", ui.font({ value: font || "", options: fonts, key: `${scope}:drawing.font`,
    placeholder: `The ${owner}’s${family ? ` (${family})` : ""}`, specials: [{ value: "drawn", label: "As Drawn" }],
    onChange: (next) => write({ font: next || null }, { label: `Set Words in ${fontLabel(next)}` }) }),
  { hint: font === "drawn" ? "In the fonts the file names, where there are; else in the fallback font" : "The same in the slide, the exports and the PowerPoint" }) : null;

  const textCard = (text, index) => {
    const shown = shownOf(text);
    const key = `${scope}:drawing:${index}`;
    let typedFrom = null;
    // (Drawn again while it is typed in, it keeps what is typed: the figure may not have it yet.)
    const typing = document.activeElement?.dataset?.key === `${key}:words` ? document.activeElement.value : null;
    const area = ui.textarea({ value: typing ?? shown.words, rows: Math.max(1, shown.words.split("\n").length), key: `${key}:words`,
      onInput: (value) => {
        typedFrom ??= shown.words;
        changeText(text, { words: value }, { label: typingName(typedFrom, value, 24), merge: `${key}:words`, hold: true, quiet: true });
      } });
    area.addEventListener("blur", () => { typedFrom = null; });
    const pressed = (name, title, on, label) => {
      const button = ui.button("", () => changeText(text, { [name]: !on }, { label }), { kind: "ghost", small: true, icon: name, title });
      button.classList.toggle("on", on);
      button.setAttribute("aria-pressed", String(on));
      return button;
    };
    const size = ui.number({ value: Math.round(shown.size * 10) / 10, min: 1, max: 400, step: 1, unit: "pt", key: `${key}:size`,
      onChange: (value) => changeText(text, { size: value }, { label: `Change Size of ${named(text)}`, merge: `${key}:size` }) });
    const changed = Object.keys(shown.change).some((name) => !["id", "text"].includes(name));
    return h("div.drawing-text", {},
      area,
      h("div.row.text-style", {},
        pressed("bold", "Bold", shown.bold, `Make ${named(text)} ${shown.bold ? "Regular" : "Bold"}`),
        pressed("italic", "Italic", shown.italic, `Make ${named(text)} ${shown.italic ? "Upright" : "Italic"}`),
        h("span.drawing-size", { title: "Size, at the picture’s own size" }, size),
        well(shown.colour, shown.change.colour !== undefined, `${key}:colour`, "Text Colour",
          (value, dragged) => changeText(text, { colour: value }, { label: `Change Colour of ${named(text)}`, merge: `${key}:colour`, quiet: dragged })),
        changed ? ui.button("", () => changeText(text, { words: null, size: null, bold: null, italic: null, colour: null }, { label: `Reset ${named(text)}` }),
          { kind: "ghost", small: true, icon: "refresh", title: "All of It As Drawn" }) : null));
  };

  const all = opened.has(scope) || found.texts.length <= SHOWN + 2;
  const listed = all ? found.texts : found.texts.slice(0, SHOWN);
  const wordsSection = found.texts.length ? h("div.section.drawing-words", {},
    h("div.section-title", {}, "Words", h("span.count", {}, found.texts.length),
      changes().length ? h("span.drawing-reset", {}, ui.button("Reset All", () => write({ texts: null }, { label: "Reset the Picture’s Words" }), { small: true, kind: "ghost", icon: "refresh" })) : null),
    fontField,
    h("div.drawing-texts", {}, listed.map(textCard)),
    all ? null : h("div", {}, ui.button(`Show All ${found.texts.length}`, (event) => { opened.add(scope); event.currentTarget.closest(".drawing-words")?.replaceWith(sections(found, options)[0]); },
      { small: true, kind: "ghost", icon: "chevron-down" }))) : null;

  const swapped = Object.keys(swaps).length;
  const colourWell = (entry) => {
    const how = entry.fill && entry.outline ? "Fill and Outline" : entry.outline ? "Outline" : "Fill";
    const shown = swaps[entry.colour] ?? entry.colour;
    return h("div.drawing-colour", { title: `${how}, drawn ${entry.colour}` },
      well(shown, swaps[entry.colour] !== undefined, `${scope}:drawing:colour:${entry.colour}`, how, (value, dragged) => {
        const next = { ...now().colours };
        if (value === null || value === entry.colour) delete next[entry.colour];
        else next[entry.colour] = value;
        write({ colours: Object.keys(next).length ? next : null },
          { label: value === null ? `Reset ${entry.colour}` : "Recolour Picture", merge: `${scope}:drawing:colour:${entry.colour}`, quiet: dragged });
      }));
  };
  const coloursSection = found.colours.length ? h("div.section.drawing-colours", {},
    h("div.section-title", {}, "Colours", h("span.count", {}, found.colours.length),
      swapped ? h("span.drawing-reset", {}, ui.button("Reset All", () => write({ colours: null }, { label: "Reset the Picture’s Colours" }), { small: true, kind: "ghost", icon: "refresh" })) : null),
    h("div.drawing-wells", {}, found.colours.map(colourWell)),
    h("div.hint-line", {}, "Each changes every use of its colour")) : null;
  return [wordsSection, coloursSection].filter(Boolean);
}

// A colour well: the system's picker, a drag through it one change; changed from what is
// drawn, a button takes it back.
function well(value, own, key, title, onChange) {
  const input = h("input", { type: "color", value, "data-key": key, "aria-label": title });
  const chip = h("span.colour-chip", { style: { background: value } });
  const body = h("label.colour-well", { title: `${title}: ${value}` }, chip, input);
  let timer = 0, last = null;
  input.addEventListener("input", () => {
    chip.style.background = input.value;
    last = input.value;
    // (At most every tenth of a second, and its last colour always.)
    if (!timer) timer = setTimeout(() => { timer = 0; onChange(last, true); }, 100);
  });
  const reset = own ? ui.button("", () => onChange(null, false), { kind: "ghost", small: true, icon: "undo", title: "As Drawn" }) : null;
  return h("div.colour-control", {}, body, reset);
}

// What a panel's thumbnail of a slide's picture shows: the picture as the slide draws it --
// its words in the deck's figure font, or as it says -- not the file as it is.
export function drawnUrl(studio, block, family) {
  if (!isSvg(block?.image)) return studio.raw(block?.image);
  return studio.url("/api/drawn", { path: block.image, family: family || "", font: block.font || "",
    texts: block.texts ? JSON.stringify(block.texts) : "", colours: block.colours ? JSON.stringify(block.colours) : "" });
}
