// Colours by their code, wherever a colour is set: the hex field beside every colour control
// (ui.swatches, ui.colour, a theme's colours), the popover ⇧⌘C opens (colourkey.js), and the
// colours the person applied last, offered again.
//
// What a colour may be written as, typed or pasted: #1f77b4 or 1f77b4, #17b, #1f77b4cc and
// #17bc (an alpha after), 0x1f77b4, rgb(31, 119, 180), rgba(31, 119, 180, 0.8),
// rgb(31 119 180 / 80%), hsl(205, 71%, 41%), a triple of numbers -- (31, 119, 180), or
// matplotlib's (0.12, 0.47, 0.71) -- a CSS colour's name (steelblue) and matplotlib's tab:
// colours (tab:blue). Quotes round it, a property's name before it ("fill: ") and a ";" after
// it are let go. Read as #rrggbb, its alpha apart (0 to 1, or null with none written).
//
// The colours applied last are kept in this browser (localStorage, read with care, as
// snapping.js keeps its setting): the person's own, whatever the document.
//
// What is chosen, offered to ⇧⌘C by its colours (colourChoices), is summed up here too.
//
// The parsing, the list and the sums need no page: they are read in Node as they are in the
// studio.

// -- reading a colour -------------------------------------------------------------------------

const CSS_NAMES = "aliceblue f0f8ff antiquewhite faebd7 aqua 00ffff aquamarine 7fffd4 azure f0ffff beige f5f5dc bisque ffe4c4 black 000000 blanchedalmond ffebcd blue 0000ff "
  + "blueviolet 8a2be2 brown a52a2a burlywood deb887 cadetblue 5f9ea0 chartreuse 7fff00 chocolate d2691e coral ff7f50 cornflowerblue 6495ed cornsilk fff8dc crimson dc143c "
  + "cyan 00ffff darkblue 00008b darkcyan 008b8b darkgoldenrod b8860b darkgray a9a9a9 darkgreen 006400 darkgrey a9a9a9 darkkhaki bdb76b darkmagenta 8b008b "
  + "darkolivegreen 556b2f darkorange ff8c00 darkorchid 9932cc darkred 8b0000 darksalmon e9967a darkseagreen 8fbc8f darkslateblue 483d8b darkslategray 2f4f4f "
  + "darkslategrey 2f4f4f darkturquoise 00ced1 darkviolet 9400d3 deeppink ff1493 deepskyblue 00bfff dimgray 696969 dimgrey 696969 dodgerblue 1e90ff firebrick b22222 "
  + "floralwhite fffaf0 forestgreen 228b22 fuchsia ff00ff gainsboro dcdcdc ghostwhite f8f8ff gold ffd700 goldenrod daa520 gray 808080 green 008000 greenyellow adff2f "
  + "grey 808080 honeydew f0fff0 hotpink ff69b4 indianred cd5c5c indigo 4b0082 ivory fffff0 khaki f0e68c lavender e6e6fa lavenderblush fff0f5 lawngreen 7cfc00 "
  + "lemonchiffon fffacd lightblue add8e6 lightcoral f08080 lightcyan e0ffff lightgoldenrodyellow fafad2 lightgray d3d3d3 lightgreen 90ee90 lightgrey d3d3d3 "
  + "lightpink ffb6c1 lightsalmon ffa07a lightseagreen 20b2aa lightskyblue 87cefa lightslategray 778899 lightslategrey 778899 lightsteelblue b0c4de lightyellow ffffe0 "
  + "lime 00ff00 limegreen 32cd32 linen faf0e6 magenta ff00ff maroon 800000 mediumaquamarine 66cdaa mediumblue 0000cd mediumorchid ba55d3 mediumpurple 9370db "
  + "mediumseagreen 3cb371 mediumslateblue 7b68ee mediumspringgreen 00fa9a mediumturquoise 48d1cc mediumvioletred c71585 midnightblue 191970 mintcream f5fffa "
  + "mistyrose ffe4e1 moccasin ffe4b5 navajowhite ffdead navy 000080 oldlace fdf5e6 olive 808000 olivedrab 6b8e23 orange ffa500 orangered ff4500 orchid da70d6 "
  + "palegoldenrod eee8aa palegreen 98fb98 paleturquoise afeeee palevioletred db7093 papayawhip ffefd5 peachpuff ffdab9 peru cd853f pink ffc0cb plum dda0dd "
  + "powderblue b0e0e6 purple 800080 rebeccapurple 663399 red ff0000 rosybrown bc8f8f royalblue 4169e1 saddlebrown 8b4513 salmon fa8072 sandybrown f4a460 "
  + "seagreen 2e8b57 seashell fff5ee sienna a0522d silver c0c0c0 skyblue 87ceeb slateblue 6a5acd slategray 708090 slategrey 708090 snow fffafa springgreen 00ff7f "
  + "steelblue 4682b4 tan d2b48c teal 008080 thistle d8bfd8 tomato ff6347 turquoise 40e0d0 violet ee82ee wheat f5deb3 white ffffff whitesmoke f5f5f5 yellow ffff00 "
  + "yellowgreen 9acd32";
// matplotlib's own ten, by the names its plots are coloured by.
const TAB_NAMES = "blue 1f77b4 orange ff7f0e green 2ca02c red d62728 purple 9467bd brown 8c564b pink e377c2 gray 7f7f7f grey 7f7f7f olive bcbd22 cyan 17becf";
let names = null;
function named(word) {
  if (!names) {
    names = new Map();
    const read = (list, prefix = "") => { const words = list.split(" "); for (let n = 0; n < words.length; n += 2) names.set(prefix + words[n], `#${words[n + 1]}`); };
    read(CSS_NAMES);
    read(TAB_NAMES, "tab:");
  }
  return names.get(word.toLowerCase().replace(/\s+/g, "")) || null;
}

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const byte = (value) => clamp(Math.round(value), 0, 255).toString(16).padStart(2, "0");
const hexOfBytes = (r, g, b) => `#${byte(r)}${byte(g)}${byte(b)}`;
// An alpha as an opacity: two places, as the inspector's sliders keep it.
const opacity = (value) => Math.round(clamp(value, 0, 1) * 100) / 100;

// A number of rgb() (0-255, or a percentage) or its alpha (0-1, or a percentage).
function channel(text, most) {
  const percent = text.endsWith("%");
  const value = Number(percent ? text.slice(0, -1) : text);
  if (!Number.isFinite(value)) return null;
  return percent ? (value / 100) * most : value;
}

// The hue's degrees, however written (deg, turn, rad), round the circle.
function hue(text) {
  const found = /^(-?[\d.]+)(deg|turn|rad|grad)?$/.exec(text);
  if (!found) return null;
  const value = Number(found[1]);
  if (!Number.isFinite(value)) return null;
  const degrees = { turn: value * 360, rad: (value * 180) / Math.PI, grad: value * 0.9 }[found[2]] ?? value;
  return ((degrees % 360) + 360) % 360;
}

function fromHsl(h, s, l) {
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0) * 255, f(8) * 255, f(4) * 255];
}

// The colour `text` is written as: { hex: "#rrggbb", alpha } (alpha null with none written),
// or null for words that are no colour.
export function parseColour(text) {
  if (typeof text !== "string") return null;
  let words = text.trim();
  // As copied from a style or a file: "fill: #1f77b4;", "'#1f77b4'", `#1f77b4`.
  words = words.replace(/^[a-z-]+\s*:\s*(?=\S)/i, (prefix) => (/^tab:/i.test(prefix) ? prefix : "")).replace(/;$/, "").trim();
  words = words.replace(/^(["'`])(.*)\1$/s, "$2").trim();
  if (!words || words.length > 64) return null;
  const hex = /^(?:#|0x)?([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.exec(words);
  if (hex) {
    let digits = hex[1].toLowerCase();
    // (0x: six or eight digits only, as a number is written in code.)
    if (/^0x/i.test(words) && digits.length < 6) return null;
    if (digits.length <= 4) digits = [...digits].map((digit) => digit + digit).join("");
    return { hex: `#${digits.slice(0, 6)}`, alpha: digits.length === 8 ? opacity(parseInt(digits.slice(6), 16) / 255) : null };
  }
  const call = /^(rgba?|hsla?)\(\s*([^()]*?)\s*\)$/i.exec(words);
  if (call) {
    const kind = call[1].toLowerCase().slice(0, 3);
    // Commas between (rgb(31, 119, 180, 0.5)), or spaces and a slash before the alpha.
    const [main, after] = call[2].includes("/") ? call[2].split("/").map((part) => part.trim()) : [call[2], null];
    const parts = main.split(/\s*,\s*|\s+/).filter(Boolean);
    if (after !== null && (parts.length !== 3 || !after)) return null;
    if (parts.length !== 3 && parts.length !== 4) return null;
    const alphaText = after ?? parts[3] ?? null;
    const alpha = alphaText === null ? null : channel(alphaText, 1);
    if (alphaText !== null && alpha === null) return null;
    let rgb;
    if (kind === "rgb") rgb = parts.slice(0, 3).map((part) => channel(part, 255));
    else {
      const h = hue(parts[0]);
      const s = parts[1].endsWith("%") ? channel(parts[1], 1) : null, l = parts[2].endsWith("%") ? channel(parts[2], 1) : null;
      rgb = h === null || s === null || l === null ? [null] : fromHsl(h, clamp(s, 0, 1), clamp(l, 0, 1));
    }
    if (rgb.some((value) => value === null)) return null;
    return { hex: hexOfBytes(...rgb), alpha: alpha === null ? null : opacity(alpha) };
  }
  // Three numbers, as a plot's code writes them: 0 to 255, or matplotlib's 0 to 1 (all of
  // them 1 or less); a fourth, its alpha.
  const triple = /^[[(]?\s*(-?[\d.]+%?)\s*,\s*(-?[\d.]+%?)\s*,\s*(-?[\d.]+%?)\s*(?:,\s*([\d.]+%?)\s*)?[\])]?$/.exec(words);
  if (triple) {
    const raw = triple.slice(1, 4);
    if (raw.some((part) => part.endsWith("%"))) {
      const rgb = raw.map((part) => channel(part.endsWith("%") ? part : `${part}%`, 255));
      if (rgb.some((value) => value === null)) return null;
      return { hex: hexOfBytes(...rgb), alpha: triple[4] ? opacity(channel(triple[4], 1)) : null };
    }
    const values = raw.map(Number);
    if (values.some((value) => !Number.isFinite(value) || value < 0)) return null;
    const unit = values.every((value) => value <= 1) ? 255 : 1;
    if (values.some((value) => value * unit > 255)) return null;
    const alpha = triple[4] !== undefined ? channel(triple[4], 1) : null;
    if (triple[4] !== undefined && alpha === null) return null;
    return { hex: hexOfBytes(...values.map((value) => value * unit)), alpha: alpha === null ? null : opacity(alpha) };
  }
  const word = named(words);
  return word ? { hex: word, alpha: null } : null;
}

// A colour as written in a file (#rgb, #rrggbb or #rrggbbaa) as #rrggbb; null for anything
// else -- a theme's colour by its name (accent), none.
export function hexOf(value) {
  if (typeof value !== "string" || !/^#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(value.trim())) return null;
  return parseColour(value).hex;
}

// A colour as the field shows it: #1F77B4.
export const shownHex = (hex) => String(hex || "").toUpperCase();

// -- the colours applied last ---------------------------------------------------------------

const KEY = "flexo-studio-recent-colours";
export const RECENT_MOST = 8;
const listeners = new Set();
let recent = null;

// What this browser kept: those of it that are colours, the newest first (none, unreadable,
// or not a list: none).
function kept() {
  try {
    const list = JSON.parse(globalThis.localStorage?.getItem?.(KEY) || "[]");
    if (!Array.isArray(list)) return [];
    const seen = new Set();
    return list.map(hexOf).filter((hex) => hex && !seen.has(hex) && seen.add(hex)).slice(0, RECENT_MOST);
  } catch { return []; }
}

// The colours the person applied last, the newest first.
export function recentColours() {
  recent ||= kept();
  return [...recent];
}

// A colour applied: first of the recent ones, kept for the next launch (refused storage: kept
// in this window alone); each listener told.
export function rememberColour(colour) {
  const hex = hexOf(colour);
  if (!hex) return recentColours();
  const list = [hex, ...recentColours().filter((each) => each !== hex)].slice(0, RECENT_MOST);
  recent = list;
  try { globalThis.localStorage?.setItem?.(KEY, JSON.stringify(list)); } catch { /* this window's alone */ }
  for (const listener of [...listeners]) {
    try { listener(list); } catch (error) { console.error(error); }
  }
  return [...list];
}

// `listener(list)` each time the list changes; what it returns stops that.
export function onRecentColours(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// Another tab of this browser applied one: read again.
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("storage", (event) => {
    if (event.key !== KEY && event.key !== null) return;
    recent = kept();
    for (const listener of [...listeners]) {
      try { listener(recentColours()); } catch (error) { console.error(error); }
    }
  });
}

// -- one step in the history ------------------------------------------------------------------

// A colour applied by its code is a step of its own: not joined to the colours clicked before
// it, nor to those after (a swatch's run of clicks is one step, as a slider's drag is).
export function stepHistory() {
  try { globalThis.flexoStudio?.active?.step?.(); } catch { /* no document */ }
}

// `apply(hex, alpha)` made one step of its own, the colour remembered first (so that the form
// the change draws again offers it).
export function applyColour(apply, hex, alpha = null) {
  rememberColour(hex);
  stepHistory();
  try { apply(hex, alpha); } finally { stepHistory(); }
}

// -- what is chosen, by its colours ----------------------------------------------------------

// The colours of what is chosen, as the popover offers them: [{ name, said, value, set,
// offered }], the one ⇧⌘C colours first -- `offered`, the theme's colours each takes by name
// (those all of them take, where several are coloured together).
export function colourChoices(kinds) {
  const each = (kinds || []).filter((kind) => kind?.colours?.length);
  if (!each.length) return [];
  const mainOf = (kind) => kind.colours[Math.min(Math.max(0, kind.main || 0), kind.colours.length - 1)];
  const same = (values) => (values.every((value) => value === values[0]) ? values[0] : undefined);
  const named = (item) => `${item?.value}|${String(item?.colour || "").toLowerCase()}`;
  const offeredBy = (colours) => {
    const lists = colours.map((colour) => colour.offered || []);
    return lists[0].filter((item) => lists.every((list) => list.some((other) => named(other) === named(item))));
  };
  if (each.length === 1) {
    const [kind] = each, main = mainOf(kind);
    return [main, ...kind.colours.filter((colour) => colour !== main)].map((colour) => ({ name: colour.name, said: `${colour.name} of ${kind.noun}`, value: colour.value, set: colour.set, offered: colour.offered || [] }));
  }
  const nouns = (list) => list.map((kind) => kind.noun).join(" and ");
  const names = [...new Set([...each.map((kind) => mainOf(kind).name), ...each.flatMap((kind) => kind.colours.map((colour) => colour.name))])];
  const byName = names.map((name) => {
    const having = each.filter((kind) => kind.colours.some((colour) => colour.name === name));
    const colours = having.map((kind) => kind.colours.find((colour) => colour.name === name));
    return { name, said: `${name} of ${nouns(having)}`, value: same(colours.map((colour) => colour.value)),
      set: (hex, alpha) => colours.forEach((colour) => colour.set(hex, alpha)), offered: offeredBy(colours) };
  });
  const mains = each.map(mainOf);
  // Each kind's own first -- or, where they are the same colour by name (a text's words and a
  // text box's), that one.
  if (mains.every((colour) => colour.name === mains[0].name)) return byName;
  return [{ name: "Both", said: each.map((kind) => `${mainOf(kind).name} of ${kind.noun}`).join(", "), value: same(mains.map((colour) => colour.value)),
    set: (hex, alpha) => mains.forEach((colour) => colour.set(hex, alpha)), offered: offeredBy(mains) }, ...byName];
}

// The box on the screen round `nodes` (elements; none drawn: null).
export function boxAround(nodes) {
  const boxes = [...nodes].filter(Boolean).map((node) => node.getBoundingClientRect()).filter((box) => box.width || box.height);
  if (!boxes.length) return null;
  const left = Math.min(...boxes.map((box) => box.left)), top = Math.min(...boxes.map((box) => box.top));
  const right = Math.max(...boxes.map((box) => box.right)), bottom = Math.max(...boxes.map((box) => box.bottom));
  return { left, top, right, bottom, width: right - left, height: bottom - top };
}

// -- the field --------------------------------------------------------------------------------

const QUIET = [["writingsuggestions", "false"], ["autocomplete", "off"], ["autocorrect", "off"], ["autocapitalize", "off"]];

// A colour's code, typed or pasted: `value` the colour now (one by its name -- the theme's --
// or none shows `placeholder`), `apply(hex, alpha)` what a code taken does. Taken on Return,
// on leaving the field, and at once when pasted; one that is no colour is ringed in red,
// changing nothing, and Esc puts back what the field showed. Shown as #1F77B4, in the studio's
// monospaced face. `key` keeps the keys in it as the form is drawn again (keepFocus); `title`
// names it (for VoiceOver, and its tooltip). With `leaving: false` (a popover's), leaving it
// takes nothing. It answers `show(value)`, `take(text)` and `wrong()`.
export function hexField({ value = null, placeholder = "Hex", apply, key = null, title = "Colour", leaving = true } = {}) {
  const input = document.createElement("input");
  input.type = "text";
  input.className = "hex-field";
  for (const [name, setting] of QUIET) input.setAttribute(name, setting);
  input.spellcheck = false;
  input.maxLength = 64;
  input.setAttribute("aria-label", `${title} (Hex)`);
  input.title = `${title}: type or paste a colour’s code (#1F77B4, rgb(31, 119, 180), steelblue)`;
  if (key) input.dataset.key = key;
  let shown = "";
  const show = (colour) => {
    const hex = hexOf(colour);
    shown = hex ? shownHex(hex) : "";
    input.value = shown;
    input.placeholder = placeholder;
    right();
  };
  const right = () => { input.classList.remove("invalid"); input.removeAttribute("aria-invalid"); };
  const wrong = () => { input.classList.add("invalid"); input.setAttribute("aria-invalid", "true"); };
  // What is typed, taken: false (and ringed) if it is no colour.
  const take = (text) => {
    const read = parseColour(text);
    if (!read) { wrong(); return false; }
    right();
    const was = shown;
    shown = shownHex(read.hex);
    input.value = shown;
    if (shown !== was || read.alpha !== null) apply?.(read.hex, read.alpha);
    return true;
  };
  show(value);
  input.addEventListener("input", right);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.isComposing) {
      event.preventDefault();
      event.stopPropagation();
      if (input.value.trim() === "" && !shown) return;
      if (take(input.value)) input.select();
    } else if (event.key === "Escape" && (input.value !== shown || input.classList.contains("invalid"))) {
      // What the field showed, put back; Esc again goes on (out of the panel).
      event.preventDefault();
      event.stopPropagation();
      input.value = shown;
      right();
      input.select();
    }
  });
  // A code pasted is taken at once: pasted over all of it, or where the caret is.
  input.addEventListener("paste", (event) => {
    const text = event.clipboardData?.getData("text/plain") ?? "";
    const before = input.value.slice(0, input.selectionStart ?? 0), after = input.value.slice(input.selectionEnd ?? input.value.length);
    const whole = parseColour(text) ? text : parseColour(before + text + after) ? before + text + after : null;
    event.stopPropagation();
    if (whole === null) { setTimeout(wrong, 0); return; }
    event.preventDefault();
    take(whole);
    input.select();
  });
  if (leaving) {
    input.addEventListener("blur", () => setTimeout(() => {
      // (Drawn again under the keys, it is still being typed in.)
      if (key && document.activeElement?.dataset?.key === key) return;
      if (!input.isConnected || input.value === shown) return;
      if (input.value.trim() === "") { input.value = shown; right(); return; }
      take(input.value);
    }, 0));
  }
  // Chosen whole as the keys come to it, so a code typed or pasted takes its place.
  let pressed = false;
  input.addEventListener("mousedown", () => { pressed = document.activeElement !== input; });
  input.addEventListener("focus", () => input.select());
  input.addEventListener("mouseup", (event) => { if (pressed) { event.preventDefault(); pressed = false; } });
  input.show = show;
  input.take = take;
  input.wrong = wrong;
  return input;
}
