// The studio's controls: elements, icons, fields, menus, dialogs, and toasts.
// Every field a person types in can carry a `key`, so a form drawn again while
// they type (someone else changed the document) gives them their field back.

// -- elements -------------------------------------------------------------------------

export function h(tag, props, ...children) {
  const [name, ...classes] = tag.split(".");
  const node = name === "svg" || SVG_TAGS.has(name)
    ? document.createElementNS("http://www.w3.org/2000/svg", name)
    : document.createElement(name || "div");
  if (classes.length) node.setAttribute("class", classes.join(" "));
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.setAttribute("class", [node.getAttribute("class"), value].filter(Boolean).join(" "));
    else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key in node && !(node instanceof SVGElement) && key !== "list") node[key] = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  append(node, children);
  return node;
}

const SVG_TAGS = new Set(["path", "circle", "rect", "line", "polyline", "polygon", "g"]);

function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

// The Mac's help while typing -- words predicted ahead in grey (taken by a space or a
// tab), corrections, capitals -- gets in the way of labels, names and maths: no field
// of the studio's asks for it. Spelling is left as each field has it.
const QUIET = [["writingsuggestions", "false"], ["autocomplete", "off"], ["autocorrect", "off"], ["autocapitalize", "off"]];
export function plainTyping(node) {
  for (const [name, value] of QUIET) node.setAttribute(name, value);
  return node;
}
const TYPED = "textarea, [contenteditable], input:not([type]), input[type=text], input[type=search], input[type=url], input[type=email]";
if (typeof document !== "undefined") {
  document.documentElement.setAttribute("writingsuggestions", "false");
  // Fields made without ui (a code area, the palette's search): quietened as they are focused.
  document.addEventListener("focusin", (event) => {
    if (event.target.matches?.(TYPED) && event.target.getAttribute("writingsuggestions") !== "false") plainTyping(event.target);
  }, true);
}

export function clear(node, ...children) {
  node.replaceChildren();
  append(node, children);
  return node;
}

// -- icons ----------------------------------------------------------------------------

const ICONS = {
  plus: "M8 3v10M3 8h10",
  minus: "M3 8h10",
  close: "M4 4l8 8M12 4l-8 8",
  check: "M3.5 8.5l3 3 6-7",
  trash: "M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5",
  copy: "M5.5 5.5h7v7h-7zM3.5 10.5v-7h7",
  // A copy made beside it: Copy's two sheets, a plus on the front one.
  duplicate: "M5.5 5.5h7v7h-7zM3.5 10.5v-7h7M9 7.25v3.5M7.25 9h3.5",
  up: "M8 12.5v-9M4.5 7L8 3.5 11.5 7",
  down: "M8 3.5v9M4.5 9L8 12.5 11.5 9",
  left: "M12.5 8h-9M7 4.5L3.5 8 7 11.5",
  right: "M3.5 8h9M9 4.5L12.5 8 9 11.5",
  chevron: "M6 4l4 4-4 4",
  "chevron-down": "M4 6l4 4 4-4",
  grip: "M6 4h.01M10 4h.01M6 8h.01M10 8h.01M6 12h.01M10 12h.01",
  undo: "M5.5 3.5L2.5 6.5l3 3M2.5 6.5h7a3.5 3.5 0 010 7H7",
  history: "M2.6 9.2A5.5 5.5 0 102.9 5.4M2.5 2.5v3h3M8 5v3.2l2.2 1.4",
  cut: "M2.5 11.5a2 2 0 104 0 2 2 0 00-4 0M9.5 11.5a2 2 0 104 0 2 2 0 00-4 0M5.7 10L11.5 2.5M10.3 10L4.5 2.5",
  paste: "M5.5 3h-1A1.5 1.5 0 003 4.5v8A1.5 1.5 0 004.5 14h7a1.5 1.5 0 001.5-1.5v-8A1.5 1.5 0 0011.5 3h-1M6 2h4v2.5H6z",
  redo: "M10.5 3.5l3 3-3 3M13.5 6.5h-7a3.5 3.5 0 000 7H9",
  save: "M3 3h8l2 2v8H3zM5.5 3v3h4.5V3M5 13V9h6v4",
  play: "M5 3.5v9l7.5-4.5z",
  export: "M8 2.5v7.5M5 5.5l3-3 3 3M3 10v3.5h10V10",
  settings: "M8 5.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5zM8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4",
  warning: "M8 2.5l6 10.5H2zM8 6.5v3M8 11.5h.01",
  error: "M8 2a6 6 0 100 12A6 6 0 008 2zM6 6l4 4M10 6l-4 4",
  info: "M8 2a6 6 0 100 12A6 6 0 008 2zM8 7.5v3.5M8 5h.01",
  sun: "M8 5a3 3 0 100 6 3 3 0 000-6zM8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M3 13l1-1M12 4l1-1",
  moon: "M13 9.5A5.5 5.5 0 016.5 3a5.5 5.5 0 106.5 6.5z",
  eye: "M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8zM8 6a2 2 0 100 4 2 2 0 000-4z",
  text: "M3 4h10M3 8h10M3 12h6",
  "align-left": "M3 4h10M3 8h6.5M3 12h8.5",
  "align-centre": "M3 4h10M4.75 8h6.5M3.75 12h8.5",
  "align-right": "M3 4h10M6.5 8h6.5M4.5 12h8.5",
  heading: "M4 3v10M12 3v10M4 8h8",
  list: "M6 4h7M6 8h7M6 12h7M3 4h.01M3 8h.01M3 12h.01",
  numbered: "M7 4h6M7 8h6M7 12h6M3 3v3M2.5 9.5h1.5l-1.5 2.5H4",
  table: "M2.5 3.5h11v9h-11zM2.5 6.5h11M6.5 6.5v6",
  code: "M5.5 4.5L2 8l3.5 3.5M10.5 4.5L14 8l-3.5 3.5",
  quote: "M3 9.5c0-3 1-4.5 3-5.5M3 9.5h3v3H3zM9 9.5c0-3 1-4.5 3-5.5M9 9.5h3v3H9z",
  stats: "M3 13V8M8 13V3M13 13V6",
  callout: "M3 3h10v7H8l-3 3v-3H3z",
  figure: "M2 2.5h5.5V7H2zM8.5 9H14v4.5H8.5zM4.75 7v4.25H8.5",
  plot: "M2.5 2.5v11h11M4.5 11l3-4 2.5 2 3.5-5",
  image: "M2.5 3.5h11v9h-11zM2.5 11l3.5-3.5 3 3 2-2 2.5 2.5M10.5 6.5h.01",
  gallery: "M2.5 2.5h4.5v4.5H2.5zM9 2.5h4.5v4.5H9zM2.5 9h4.5v4.5H2.5zM9 9h4.5v4.5H9z",
  layout: "M2.5 2.5h11v11h-11zM2.5 5.5h11M8 5.5v8",
  slide: "M2 3.5h12v9H2z",
  section: "M2 3.5h12v9H2zM5 8h6",
  folder: "M2 4.5h4l1.5 1.5H14v7H2z",
  upload: "M8 10.5V3M5 6l3-3 3 3M3 11v2.5h10V11",
  bold: "M4.5 3h4a2.5 2.5 0 010 5h-4zM4.5 8h4.5a2.5 2.5 0 010 5H4.5z",
  italic: "M7 3h5M4 13h5M9.5 3l-3 10",
  link: "M7 9a3 3 0 004.2 0l2-2a3 3 0 00-4.2-4.2L8 3.8M9 7a3 3 0 00-4.2 0l-2 2a3 3 0 004.2 4.2L8 12.2",
  math: "M3 8h4M12 5l-3 6M9 5l3 6M3.5 4h3L5 12",
  mechanism: "M6 5l3 1.75v3.5L6 12l-3-1.75v-3.5zM8.5 3.5a3.5 3.5 0 015 3M13.5 6.5l.3-1.8M13.5 6.5l-1.7-.6",
  structure: "M2 8c1.5-6 3-6 4 0s2.5 6 4 0 2.5-6 4 0",
  flow: "M4.5 1.5h7v3h-7zM8 4.5v2M8 6.5l3.5 3L8 12.5l-3.5-3zM8 12.5v2",
  palette: "M8 2a6 6 0 100 12c1 0 1.5-.7 1.5-1.5S9 11 9 10s.8-1.5 1.8-1.5H12A2.5 2.5 0 0014 6c0-2.2-2.7-4-6-4zM5 7.5h.01M7 5h.01M10 5h.01",
  type: "M3 4V3h10v1M8 3v10M6 13h4",
  notes: "M4 2.5h8v11H4zM6 5.5h4M6 8h4M6 10.5h2",
  panel: "M2.5 3h11v10h-11zM10 3v10",
  sidebar: "M2.5 3h11v10h-11zM6 3v10",
  external: "M9 2.5h4.5V7M13.5 2.5L7.5 8.5M11 9.5v4H2.5V5h4",
  refresh: "M13 8a5 5 0 11-1.5-3.5M13 2.5v3h-3",
  reveal: "M3 4h10M3 8h7M3 12h4",
  more: "M4 8h.01M8 8h.01M12 8h.01",
  columns: "M2.5 3h3v10h-3zM6.5 3h3v10h-3zM10.5 3h3v10h-3z",
  twocol: "M2.5 3h5v10h-5zM8.5 3h5v10h-5z",
  blank: "M2.5 3h11v10h-11z",
  agenda: "M5 4.5h8M5 8h8M5 11.5h8M2.5 4.5h.01M2.5 8h.01M2.5 11.5h.01",
  statement: "M3 6.5h10M4.5 9.5h7",
  title: "M3 6h10M5 9h6M6.5 11.5h3",
  sparkle: "M8 1.8l1.3 3.9 3.9 1.3-3.9 1.3L8 12.2l-1.3-3.9L2.8 7l3.9-1.3zM12.8 11.2l.5 1.5 1.5.5-1.5.5-.5 1.5-.5-1.5-1.5-.5 1.5-.5z",
  activity: "M1.5 8h3l2-5 3 10 2-5h3",
  command: "M5.5 5.5h5v5h-5zM5.5 5.5V4a1.5 1.5 0 10-1.5 1.5zM10.5 5.5V4A1.5 1.5 0 1112 5.5zM5.5 10.5V12A1.5 1.5 0 114 10.5zM10.5 10.5V12a1.5 1.5 0 101.5-1.5z",
  plug: "M6 1.5v3M10 1.5v3M4 4.5h8v3a4 4 0 01-8 0zM8 11.5v3",
  collaborate: "M6.5 2.75a2.5 2.5 0 100 5 2.5 2.5 0 000-5zM2 13.25c.45-2.55 2.3-4.25 4.5-4.25s4.05 1.7 4.5 4.25M12.5 4.5v4M10.5 6.5h4",
  appearance: "M8 2.25a5.75 5.75 0 100 11.5 5.75 5.75 0 000-11.5z",
  target: "M8 2a6 6 0 100 12A6 6 0 008 2zM8 5a3 3 0 100 6 3 3 0 000-6zM8 7.5v1",
  file: "M4 1.5h5.5L12 4v10.5H4zM9.5 1.5V4H12",
  send: "M2.5 8L13.5 3 9 13.5 7.5 9z",
  stop: "M4.5 4.5h7v7h-7z",
  user: "M8 2.5a2.75 2.75 0 100 5.5 2.75 2.75 0 000-5.5zM3 14c.5-2.8 2.6-4.5 5-4.5s4.5 1.7 5 4.5",
  keyboard: "M1.5 4h13v8h-13zM4 6.5h.01M6.5 6.5h.01M9 6.5h.01M11.5 6.5h.01M4.5 9.5h7",
  search: "M7 2.5a4.5 4.5 0 100 9 4.5 4.5 0 000-9zM10.3 10.3L13.5 13.5",
  pencil: "M10.5 2.5l3 3L6 13H3v-3z",
  theme: "M8 2a6 6 0 100 12 1.5 1.5 0 001.2-2.4 1.5 1.5 0 011.2-2.4H12a2 2 0 002-2C14 4.4 11.3 2 8 2zM5 8h.01M6.5 5h.01M9.5 5h.01",
  deck: "M2 3h12v8H2zM5.5 14h5M8 11v3",
};
// Parts of an icon filled rather than drawn: Appearance's circle, half dark as on a Mac.
const FILLS = {
  appearance: "M8 2.25a5.75 5.75 0 000 11.5z",
};

export function icon(name, extra = {}) {
  const d = ICONS[name] || ICONS.info;
  const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  node.setAttribute("viewBox", "0 0 16 16");
  node.setAttribute("fill", "none");
  node.setAttribute("stroke", "currentColor");
  node.setAttribute("stroke-width", extra.weight || "1.4");
  node.setAttribute("stroke-linecap", "round");
  node.setAttribute("stroke-linejoin", "round");
  node.setAttribute("aria-hidden", "true");
  if (extra.class) node.setAttribute("class", extra.class);
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", d);
  node.append(path);
  if (FILLS[name]) {
    const fill = document.createElementNS("http://www.w3.org/2000/svg", "path");
    fill.setAttribute("d", FILLS[name]);
    fill.setAttribute("fill", "currentColor");
    fill.setAttribute("stroke", "none");
    node.append(fill);
  }
  return node;
}

// -- controls -------------------------------------------------------------------------

export const ui = {
  button(label, onClick, { kind = "", icon: iconName, title, small, disabled, id } = {}) {
    const classes = ["btn", kind, small ? "small" : "", !label ? "icon" : ""].filter(Boolean).join(" ");
    return h("button", { class: classes, type: "button", title, disabled, id, onclick: onClick },
      iconName ? icon(iconName) : null, label ? h("span.btn-label", {}, label) : null);
  },

  // A note too long to sit beside its name on a narrow panel goes under it, from the left,
  // rather than wrapping raggedly at the right.
  field(label, control, { hint, inline } = {}) {
    const long = typeof label === "string" && typeof hint === "string" && label.length + hint.length > 40;
    return h(`div.field${inline ? ".inline" : ""}`, {},
      label ? h("label.label", {}, label, hint ? h(`span.hint${long ? ".below" : ""}`, {}, hint) : null) : null, control);
  },

  input({ value = "", placeholder = "", onInput, onChange, type = "text", mono, list, width, key } = {}) {
    const node = plainTyping(h(`input.input${mono ? ".mono" : ""}`, { type, placeholder }));
    node.spellcheck = false;  // set here: h() leaves out what is false
    if (key) node.dataset.key = key;
    node.value = value ?? "";
    if (width) node.style.width = width;
    if (list) { node.setAttribute("list", list); node.removeAttribute("autocomplete"); }  // its own suggestions stay
    if (onInput) node.addEventListener("input", () => onInput(node.value));
    // A web view says a field taken away while it is typed in has changed: a form drawn
    // again under the keys gives the person the field back (keepFocus), and only leaving it
    // is a change.
    if (onChange) node.addEventListener("change", () => {
      if (!key) { onChange(node.value); return; }
      setTimeout(() => { if (document.activeElement?.dataset?.key !== key) onChange(node.value); }, 0);
    });
    return node;
  },

  // A number, as every number field in the studio is drawn (numberBox): ↑ and ↓, or its
  // steppers, go a step at a time, ⇧ ten. Left to its default, it steps from the value in
  // use -- `current()`, what is drawn, else the default its placeholder says, else `start`
  // -- never from the bottom of its range. What is typed is taken as it reads as a number
  // in range; when the field is left (or Return), a number out of range is set to the end it
  // passed and words that are not a number are put back, each said under the field a
  // moment. Esc puts back what the field held when it was entered, as a Mac field's Cancel
  // does. Empty is null: the default, said by `placeholder`.
  number({ value, placeholder = "", onChange, min, max, step = "any", key, unit, current, start } = {}) {
    const input = plainTyping(h("input.input", { type: "text", placeholder }));
    input.inputMode = "decimal";
    input.spellcheck = false;
    if (key) input.dataset.key = key;
    const shown = (number) => (number === null || number === undefined ? "" : String(number));
    // Drawn again while it is typed in (keepFocus gives it the keys back), it keeps what is
    // being typed, until it is done (Return, or leaving it) -- another's change meanwhile
    // does not take it away; what was only stepped to (↑, ↓) or undone (keepFocus's
    // `undone`) shows the value as it is now, so leaving it never puts an older value back.
    const was = key && document.activeElement?.dataset?.key === key ? document.activeElement : null;
    const typed = typeof was?.value === "string" && !was.undone && (was.typing || (was.untaken?.() ?? true)) ? was.value : null;
    input.value = typed ?? shown(value);
    input.typing = typed !== null && Boolean(was?.typing);
    // The field's own unit typed after the digits ("12pt", "30 °") is the number.
    const read = () => {
      let text = input.value.trim().replace(",", ".");
      if (unit && text.toLowerCase().endsWith(unit.toLowerCase())) text = text.slice(0, -unit.length).trim();
      return text === "" ? null : Number(text);
    };
    const clamp = (number) => Math.min(max ?? Infinity, Math.max(min ?? -Infinity, number));
    const named = (number) => (unit ? `${number}${TIGHT_UNITS.has(unit) ? "" : " "}${unit}` : String(number));
    let applied = value ?? null;
    const apply = (number) => { if (number === applied) return; applied = number; onChange?.(number); };
    input.untaken = () => !Object.is(read(), applied);
    const note = h("span.number-note", { role: "status", hidden: true });
    const hush = () => { note.hidden = true; if (key) noted.delete(key); };
    const say = (text, last = 4000) => {
      note.textContent = text;
      note.hidden = false;
      // Kept by its field's key: a form drawn again by the change still says it.
      if (key) noted.set(key, { text, until: Date.now() + last });
      clearTimeout(note.timer);
      note.timer = setTimeout(hush, last);
    };
    const said = key && noted.get(key);
    if (said && said.until > Date.now()) say(said.text, said.until - Date.now());
    // What it held when it was entered, kept by its key across the form being drawn again.
    let origin = null;
    const entered = () => (key ? entering.get(key) : origin);
    input.addEventListener("focus", () => { if (!key) origin ??= input.value; else if (!entering.has(key)) entering.set(key, input.value); });
    const commit = () => {
      settle();
      input.typing = false;
      const parsed = read();
      if (parsed === null) { input.classList.remove("invalid"); apply(null); return; }
      if (Number.isNaN(parsed)) { input.value = shown(applied); input.classList.remove("invalid"); say("Type a number"); return; }
      const kept = clamp(parsed);
      // Shown as the number alone ("24pt" typed is 24, its unit said after it).
      input.value = shown(kept);
      if (kept !== parsed) say(kept === min ? `The smallest is ${named(min)}` : `The largest is ${named(max)}`);
      apply(kept);
    };
    input.addEventListener("blur", () => setTimeout(() => {
      // Drawn again under the keys, it is still being typed in.
      if (key && document.activeElement?.dataset?.key === key) return;
      settle();
      if (input.isConnected) commit();
      if (key) entering.delete(key); else origin = null;
    }, 0));
    // A number typed is taken when it is done, as in Keynote: on Return, Tab or leaving the
    // field, or a step (↑, ↓, the steppers) -- not at each key ("44" is never 4 on its way,
    // seen by everyone and written to the file). A press anywhere else is leaving it, taken
    // before what it presses is done (which may draw the form again, the field gone with it).
    // (A field drawn again while typed in leaves it to the field that took its place.)
    const pressed = (event) => { if (!input.isConnected) settle(); else if (!node.contains(event.target)) commit(); };
    const settle = () => document.removeEventListener("pointerdown", pressed, true);
    input.addEventListener("input", () => {
      hush();
      if (!input.typing) document.addEventListener("pointerdown", pressed, true);
      input.typing = true;
      const parsed = read();
      input.classList.toggle("invalid", parsed !== null && Number.isNaN(parsed));
    });
    const stepBy = (sign, big) => {
      hush();
      input.typing = false;
      const now = read();
      const size = Number(step) || 1;
      let from = now !== null && !Number.isNaN(now) ? now : null;
      if (from === null) {
        const using = current?.();
        const said = parseFloat(input.placeholder);
        from = Number.isFinite(using) ? Math.round(using / size) * size : Number.isFinite(said) ? said : start ?? Math.max(min ?? 0, 0);
      }
      const next = clamp(Math.round((from + sign * size * (big ? 10 : 1)) * 1e6) / 1e6);
      input.value = String(next);
      input.classList.remove("invalid");
      apply(next);
    };
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowUp" || event.key === "ArrowDown") { event.preventDefault(); stepBy(event.key === "ArrowUp" ? 1 : -1, event.shiftKey); }
      else if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); commit(); input.select(); }
      else if (event.key === "Escape") {
        const was = entered();
        if (was === null || was === undefined || was === input.value) return;
        event.preventDefault();
        event.stopPropagation();
        input.value = was;
        input.classList.remove("invalid");
        hush();
        const parsed = read();
        apply(parsed === null || Number.isNaN(parsed) ? null : parsed);
        input.select();
      }
    });
    const node = ui.numberBox(input, { unit, step: stepBy, note });
    if (input.typing) document.addEventListener("pointerdown", pressed, true);
    return node;
  },

  // A number field's box, as a Mac's: the digits to the right, the unit after them ("12 pt",
  // "30°"), and steppers at its end (`step(sign, big)`). The figure's typed numbers are drawn
  // in it too. `note`: what it says under itself (ui.number).
  numberBox(input, { unit, step, note } = {}) {
    const stepper = (sign, title) => h("button.stepper", { type: "button", tabIndex: -1, title,
      onmousedown: (event) => event.preventDefault(), onclick: (event) => step(sign, event.shiftKey) }, icon("chevron-down"));
    // A sign that is part of the number ("30°", "0.4×") sits against its digits, in their ink.
    const node = h("div.number-field", {}, input, unit ? h(`span.unit${TIGHT_UNITS.has(unit) ? ".tight" : ""}`, {}, unit) : null,
      step ? h("span.steppers", {}, stepper(1, "Increase (↑)"), stepper(-1, "Decrease (↓)")) : null, note || null);
    // A click in the box beside the digits types in it.
    node.addEventListener("mousedown", (event) => { if (event.target === node || event.target.classList?.contains("unit")) { event.preventDefault(); input.focus(); } });
    node.input = input;
    return node;
  },

  // `indent`: Tab indents, for code and YAML; in any other field Tab goes on to the next.
  textarea({ value = "", rows = 3, placeholder = "", onInput, mono, grow = true, indent = false, key, spelling = !mono } = {}) {
    const node = plainTyping(h(`textarea.textarea${mono ? ".mono" : ""}${grow ? ".grow" : ""}`, { rows, placeholder }));
    node.spellcheck = Boolean(spelling);
    if (key) node.dataset.key = key;
    node.value = value ?? "";
    if (indent) ui.indent(node);
    node.addEventListener("input", () => { if (grow) fit(node); onInput?.(node.value); });
    if (grow) {
      requestAnimationFrame(() => fit(node));
      // Words wrap anew when the panel narrows or widens: the box follows.
      let width = 0;
      new ResizeObserver(([entry]) => {
        if (Math.abs(entry.contentRect.width - width) > 1) { width = entry.contentRect.width; fit(node); }
      }).observe(node);
    }
    return node;
  },

  // Words in flexo markup: **strong**, *emphasis*, $maths$, `code`, [links](url), [colour]{accent}.
  // `colours`: the theme's ({ accent, accent2, muted, ink } as colours) offered in its format bar,
  // true for the studio's own as stand-ins, or false for none.
  // `emphasis: false` for words that set no bold or italic -- a figure's labels, which keep
  // their asterisks -- leaves those tools out.
  markup({ value = "", rows = 1, placeholder = "", onInput, colours = true, emphasis = true, key, spelling = true } = {}) {
    const area = ui.textarea({ value, rows, placeholder, onInput, key, spelling });
    area.addEventListener("keydown", (event) => {
      const mod = event.metaKey || event.ctrlKey;
      if (emphasis && mod && event.key.toLowerCase() === "b") { event.preventDefault(); wrap(area, "**", "**", onInput); }
      if (emphasis && mod && event.key.toLowerCase() === "i") { event.preventDefault(); wrap(area, "*", "*", onInput); }
      if (mod && event.key.toLowerCase() === "k") { event.preventDefault(); wrap(area, "[", "](https://)", onInput); }
      // ⌥⌘E, as Keynote's Insert › Equation: ⌘M is the Mac's Window › Minimize.
      if (mod && event.altKey && event.code === "KeyE") { event.preventDefault(); wrap(area, "$", "$", onInput); }
      // A field of one line (a shape's label) takes Return as done, as the label's editor on
      // the slide does; ⇧Return starts a line of its own.
      if (rows === 1 && event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); area.blur(); }
    });
    // The tools show while the field is typed in (studio.css) and are worked by the pointer,
    // the keys beside each name doing the same: Tab goes from field to field, not through them.
    const tool = (label, title, before, after, style) =>
      h("button", { type: "button", title, style, tabIndex: -1, onmousedown: (event) => { event.preventDefault(); wrap(area, before, after, onInput); } }, label);
    // As the slide's words' format bar (richtext.js) has them, in its order and its look.
    const palette = colours === true ? { accent: "var(--accent)", accent2: "var(--accent-2)", muted: "var(--ink-3)", ink: "var(--ink)" } : colours || {};
    const swatch = (name, title) => (palette[name] ? tool(h("span.rt-swatch", { style: { background: palette[name] } }), title, "[", `]{${name}}`) : null);
    const tools = h("div.markup-tools", {},
      emphasis ? tool(h("b", {}, "B"), "Bold (⌘B)", "**", "**") : null,
      emphasis ? tool(h("i", {}, "I"), "Italic (⌘I)", "*", "*") : null,
      tool(h("span.tool-code", {}, "</>"), "Code", "`", "`"),
      tool(h("span.tool-maths", {}, "∑"), "Equation (⌥⌘E)", "$", "$"),
      tool(icon("link"), "Link (⌘K)", "[", "](https://)"),
      swatch("accent", "Accent"), swatch("accent2", "Accent 2"), swatch("muted", "Muted"), swatch("ink", "Default colour"));
    const node = h("div.markup", {}, tools, area);
    node.area = area;
    return node;
  },

  // A pop-up button, as a Mac's: what is chosen, and the choices in a menu under it, the
  // one in use ticked. It answers to `value` as a <select> does, and `relabel(value, label)`
  // renames a choice. A choice left as its default -- "" ("Default (On)", "None"), or
  // `unset`, the value shown being the default's -- reads as any choice does (marked
  // `.default`): in grey it would look disabled, as a Mac's pop-up never shows a choice.
  // `icons`: a narrow pop-up showing its choice's icon (each option's `icon`), the choice's
  // name in its tooltip after `title`; `actions`: commands under the choices, after a line
  // ({ label, icon, run }), as a column's pop-up in Numbers has. `key` keeps the keys on it
  // as the form is drawn again by the change (keepFocus). `acting(on)`: what the pop-up acts
  // on shown (a table's column) while its menu is open.
  select({ value, options, onChange, placeholder, unset = false, icons = false, title = "", actions = [], key, acting } = {}) {
    const items = [...(placeholder !== undefined ? [{ value: "", label: placeholder }] : []),
      ...options.map((option) => (typeof option === "object" ? { ...option, value: String(option.value ?? "") } : { value: String(option), label: String(option) }))];
    const label = h("span");
    const node = h(`button.select${icons ? ".icon-select" : ""}`, { type: "button", "aria-haspopup": "menu" }, label, icon("chevron-down"));
    if (key) node.dataset.key = key;
    let current = String(value ?? "");
    let fallback = unset;
    const show = () => {
      const item = items.find((each) => each.value === current);
      const words = item ? item.label : current;
      if (icons) {
        clear(label, icon(item?.icon || "more"));
        node.title = [title, words].filter(Boolean).join(": ");
        node.setAttribute("aria-label", node.title);
      } else label.textContent = words;
      node.classList.toggle("default", current === "" || fallback);
    };
    Object.defineProperty(node, "value", { configurable: true, get: () => current, set: (next) => { current = String(next ?? ""); fallback = false; show(); } });
    node.relabel = (choice, text) => { const item = items.find((each) => each.value === String(choice)); if (item) { item.label = text; show(); } };
    const open = (byKey) => {
      const opened = choices(node, actions.length ? [...items, "-", ...actions.map((action) => ({ ...action, action: true }))] : items, current, (next) => {
        if (next === current && !fallback) return;
        current = next;
        fallback = false;
        show();
        node.dispatchEvent(new Event("change", { bubbles: true }));
        onChange?.(next);
      }, byKey);
      if (acting) whileOpen(opened, acting);
    };
    // Opened by a click, or by Space, Return or an arrow key, as a Mac's is.
    node.addEventListener("click", (event) => open(event.detail === 0));
    node.addEventListener("keydown", (event) => { if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); open(true); } });
    show();
    return node;
  },

  // A combo box, as a Mac's: words typed, for values usually but not always from a list,
  // or one of the list chosen from the menu its button opens under the field (⌥↓ too).
  combo({ value, options = [], placeholder = "", onChange, mono, key } = {}) {
    const input = ui.input({ value, placeholder, mono, key, onInput: (text) => onChange?.(text) });
    const node = h("div.combo", {}, input);
    const button = h("button.combo-open", { type: "button", tabIndex: -1, title: "Show Choices", disabled: !options.length,
      onmousedown: (event) => event.preventDefault(),
      onclick: () => choices(node, options.map((option) => ({ value: String(option), label: String(option) })), input.value, (next) => {
        input.value = next;
        onChange?.(next);
        setTimeout(() => input.focus(), 0);
      }) }, icon("chevron-down"));
    input.addEventListener("keydown", (event) => { if (event.altKey && event.key === "ArrowDown") { event.preventDefault(); button.click(); } });
    node.append(button);
    node.input = input;
    return node;
  },

  // A font, from a pop-up button: its menu lists the fonts there are, each name in its own
  // face, and typing finds one -- or names one not listed. Empty is `placeholder`.
  font({ value, options = [], placeholder = "Default", onChange, key } = {}) {
    const label = h("span");
    const node = h("button.select.font-pick", { type: "button", "aria-haspopup": "menu", title: "Choose a Font" }, label, icon("chevron-down"));
    if (key) node.dataset.key = key;
    let current = value || "";
    const show = () => { label.textContent = current || placeholder; node.classList.toggle("default", !current); };
    const pick = (next) => {
      closeMenu();
      if (next === current) return;
      current = next;
      show();
      onChange?.(next);
    };
    const open = () => {
      const search = plainTyping(h("input.input.font-search", { type: "search", placeholder: "Search Fonts" }));
      search.spellcheck = false;
      const list = h("div.font-list", { role: "menu" });
      const item = (name, text, face) => h(`button.menu-item${name === current ? ".checked" : ""}`, { type: "button", role: "menuitemradio", "aria-checked": String(name === current), onclick: () => pick(name) },
        h("span.menu-tick", {}, name === current ? icon("check") : null),
        h("span.menu-text", {}, h("span", { style: face ? { fontFamily: `"${name}", var(--font)` } : {} }, text)));
      const render = () => {
        const typed = search.value.trim();
        const query = typed.toLowerCase();
        clear(list,
          query ? null : item("", placeholder),
          options.filter((name) => !query || name.toLowerCase().includes(query)).map((name) => item(name, name, true)),
          typed && !options.some((name) => name.toLowerCase() === query) ? item(typed, `Use “${typed}”`) : null);
      };
      search.addEventListener("input", render);
      search.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); list.querySelector(".menu-item")?.click(); } });
      render();
      // The search field has the keys: ↓ goes into the list.
      popover(node, [search, list], { className: "font-menu" });
      list.querySelector(".checked")?.scrollIntoView({ block: "nearest" });
    };
    node.addEventListener("click", open);
    node.addEventListener("keydown", (event) => { if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); open(); } });
    show();
    return node;
  },

  // A table's cell, typed in where it is: its words wrap, its row growing to hold them, and
  // they read as the slide sets them (strong, emphatic, code, maths) while it is not typed
  // in. It takes what an input given to h() does -- `value`, `dataset`, `oninput`,
  // `onpaste` -- and answers to `value`. Return goes to the cell under it.
  cell({ value = "", dataset, ...events } = {}) {
    const area = plainTyping(h("textarea.cell-area", { rows: 1, ...events }));
    area.spellcheck = false;
    if (dataset) Object.assign(area.dataset, dataset);
    area.value = value ?? "";
    // The words under the field give the cell its size: as typed while it is typed in (unseen,
    // the field over them), else as the slide sets them.
    const view = h("div.cell-view", { "aria-hidden": "true" });
    const show = () => clear(view, document.activeElement === area ? `${area.value}\u200b` : area.value ? markupNodes(area.value) : "\u200b");
    const node = h("div.cell-edit", {}, area, view);
    Object.defineProperty(node, "value", { configurable: true, get: () => area.value, set: (text) => { area.value = text ?? ""; show(); } });
    area.addEventListener("input", show);
    area.addEventListener("focus", show);
    area.addEventListener("blur", show);
    area.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.isComposing) return;
      event.preventDefault();
      // As in a spreadsheet: the cell under it, its words chosen, ready to type over.
      const cell = node.closest("td");
      const next = cell?.parentElement?.nextElementSibling?.children[cell.cellIndex]?.querySelector("textarea");
      next?.focus();
      next?.select();
    });
    show();
    return node;
  },

  // `key`: the form drawn again by the change keeps the keys on it (keepFocus); by default
  // its words name it.
  toggle({ value, label, onChange, key } = {}) {
    const box = h("input", { type: "checkbox" });
    box.checked = Boolean(value);
    if (key || label) box.dataset.key = key || `switch:${label}`;
    box.addEventListener("change", () => onChange?.(box.checked));
    return h("label.switch", {}, box, h("span.track"), label ? h("span", {}, label) : null);
  },

  // Segments, one chosen, as a Mac's segmented control: one stop for Tab, the arrow keys
  // going from segment to segment and Space choosing, the keys staying on it as the form is
  // drawn again by the change (its `key`, by default its choices).
  segmented({ value, options, onChange, key } = {}) {
    const items = options.map((option) => (typeof option === "object" ? option : { value: option, label: String(option) }));
    const node = h("div.segmented", { role: "radiogroup" });
    const buttons = items.map((item) => {
      const button = h("button", { type: "button", role: "radio", "aria-checked": String(item.value === value), title: item.title || item.label, class: item.value === value ? "on" : "",
        onclick: () => {
          buttons.forEach((b) => { b.classList.remove("on"); b.setAttribute("aria-checked", "false"); });
          button.classList.add("on");
          button.setAttribute("aria-checked", "true");
          keys.mark(button);
          onChange?.(item.value);
        } },
      item.icon ? icon(item.icon) : null, item.label ?? null);
      return button;
    });
    node.append(...buttons);
    const keys = roving(node, () => buttons, key || `segments:${items.map((item) => item.value).join("|")}`);
    return node;
  },

  // Colours to choose from; `custom` adds one more, any colour, from the system's picker. A
  // row of them is one stop for Tab, as a segmented control is; the chosen one is ticked,
  // the one with the keys ringed with the focus's glow.
  swatches({ value, colours, onChange, none = true, custom = false, key } = {}) {
    const node = h("div.swatches", { role: "radiogroup" });
    const all = [...(none ? [{ value: null, colour: null, title: "None" }] : []), ...colours];
    const choose = (button, next) => {
      node.querySelectorAll(".swatch").forEach((b) => { b.classList.remove("on"); b.setAttribute("aria-checked", "false"); });
      button.classList.add("on");
      button.setAttribute("aria-checked", "true");
      keys.mark(button.matches("label") ? button.querySelector("input") : button);
      onChange?.(next);
    };
    const buttons = all.map((item) => {
      const chosen = item.value === (value ?? null);
      const button = h("button.swatch", { type: "button", role: "radio", "aria-checked": String(chosen), title: item.title || item.value || "None",
        class: [chosen ? "on" : "", item.colour ? "" : "none", item.colour && light(item.colour) ? "light" : ""].join(" "),
        style: item.colour ? { background: item.colour, ...(item.border ? { borderColor: item.border } : {}) } : {},
        onclick: () => choose(button, item.value) });
      return button;
    });
    node.append(...buttons);
    let well = null;
    if (custom) {
      const own = HEX.test(value || "") && !all.some((item) => item.value === value) ? value : null;
      const input = h("input", { type: "color", value: own || "#888888", title: "Custom colour" });
      well = h(`label.swatch.custom${own ? ".on" : ""}${own && light(own) ? ".light" : ""}`, { title: "Custom colour", style: own ? { background: own } : {} }, icon("plus"), input);
      input.addEventListener("input", () => { well.style.background = input.value; well.classList.toggle("light", light(input.value)); choose(well, input.value); });
      node.append(well);
    }
    const keys = roving(node, () => [...buttons, ...(well ? [well.querySelector("input")] : [])],
      key || `swatches:${all.map((item) => item.value).join("|")}`);
    return node;
  },

  // One colour of a thing's own, or none (the theme's): a well that opens the system's
  // picker, and a button to go back to the theme's.
  colour({ value, onChange, title = "", key } = {}) {
    const set = HEX.test(value || "") ? value : null;
    const input = h("input", { type: "color", value: set || "#888888", "data-key": key });
    const well = h(`label.colour-well${set ? "" : ".unset"}`, { title: [title, set || "Default"].filter(Boolean).join(": ") },
      h("span.colour-chip", { style: set ? { background: set } : {} }), input);
    input.addEventListener("input", () => { well.classList.remove("unset"); well.firstChild.style.background = input.value; onChange?.(input.value); });
    const reset = ui.button("", () => { well.classList.add("unset"); well.firstChild.style.background = ""; onChange?.(null); },
      { kind: "ghost", small: true, icon: "undo", title: "Reset" });
    reset.hidden = !set;
    input.addEventListener("input", () => { reset.hidden = false; });
    return h("div.colour-control", {}, well, reset);
  },
};

const HEX = /^#[0-9a-f]{6}$/i;
// A colour light enough that a mark on it is drawn dark.
function light(colour) {
  if (!HEX.test(colour || "")) return false;
  const [r, g, b] = [1, 3, 5].map((at) => parseInt(colour.slice(at, at + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.6;
}

// A group of controls that is one stop for Tab, as a Mac's segmented control, a row of
// colours or a grid of layouts is: Tab comes to the chosen one (else the first), and the
// arrow keys go from one to the next within it -- ↑ and ↓ to the row above or below where
// they lie in rows -- Space or Return working the one with the keys. `key` goes with the
// one Tab comes to, so a form drawn again keeps the keys on it (keepFocus). Answers
// `mark(item)`: the one Tab comes to now.
export function roving(group, items = () => [...group.children], key = null) {
  const list = () => items().filter((item) => item && !item.disabled);
  const mark = (chosen) => {
    for (const item of list()) {
      item.tabIndex = item === chosen ? 0 : -1;
      if (key) { if (item === chosen) item.dataset.key = key; else delete item.dataset.key; }
    }
  };
  const all = list();
  // (A custom colour's well is a label round its field: the field has the keys.)
  mark(all.find((item) => item.matches(".on, .checked, [aria-checked=true]") || (item.matches("input") && item.parentElement?.matches(".on"))) || all[0]);
  group.addEventListener("focusin", (event) => { if (list().includes(event.target)) mark(event.target); });
  group.addEventListener("keydown", (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const each = list();
    const at = each.indexOf(document.activeElement);
    if (at < 0) return;
    let next;
    if (event.key === "ArrowLeft") next = each[at - 1];
    else if (event.key === "ArrowRight") next = each[at + 1];
    else if (event.key === "Home") next = each[0];
    else if (event.key === "End") next = each[each.length - 1];
    else if (event.key === "ArrowUp" || event.key === "ArrowDown") next = across(each, at, event.key === "ArrowDown" ? 1 : -1);
    else return;
    // The arrows are the group's: not the slide's (moving what is chosen), nor a menu's.
    event.preventDefault();
    event.stopPropagation();
    if (next) { mark(next); next.focus(); }
  });
  return { mark };
}

// The one in the row above or below (`way` -1 or 1), nearest across; in a single row, the
// one before or after, as a Mac's radio buttons go.
function across(items, at, way) {
  const boxes = items.map((item) => item.getBoundingClientRect());
  const here = boxes[at];
  if (new Set(boxes.map((box) => Math.round(box.top))).size === 1) return items[at + way] || null;
  const beyond = boxes.map((box, index) => ({ box, index })).filter(({ box }) => (way > 0 ? box.top >= here.bottom - 2 : box.bottom <= here.top + 2));
  if (!beyond.length) return null;
  const row = way > 0 ? Math.min(...beyond.map(({ box }) => box.top)) : Math.max(...beyond.map(({ box }) => box.top));
  const middle = (box) => box.left + box.width / 2;
  const nearest = beyond.filter(({ box }) => Math.abs(box.top - row) < 2)
    .sort((a, b) => Math.abs(middle(a.box) - middle(here)) - Math.abs(middle(b.box) - middle(here)))[0];
  return items[nearest.index];
}
ui.roving = roving;

// Units written against their digits, as a Mac writes them: "30°", "0.4×", "50%".
const TIGHT_UNITS = new Set(["°", "×", "%", "′", "″"]);
// What each number field (by its key) held when it was entered, and what it says under itself.
const entering = new Map();
const noted = new Map();

function fit(area) {
  area.style.height = "auto";
  area.style.height = `${area.scrollHeight + 2}px`;
}

function wrap(area, before, after, onInput) {
  const { selectionStart: start, selectionEnd: end, value } = area;
  const inner = value.slice(start, end);
  area.setRangeText(before + inner + after, start, end, "select");
  area.setSelectionRange(start + before.length, start + before.length + inner.length);
  area.dispatchEvent(new Event("input"));
  area.focus();
}

// Tab indents a code editor's lines and ⇧Tab outdents them, as in a Mac code editor;
// Ctrl-Tab, or Esc and then Tab, goes on to the next field instead. A Tab with nothing to
// indent or outdent changes nothing.
function indentKeys(area) {
  let leaving = false;
  area.addEventListener("blur", () => { leaving = false; });
  // An indent is the one the lines have (their least), else four spaces, as a code editor's.
  const unitOf = (value) => {
    const least = Math.min(...value.split("\n").map((line) => /^( *)\S/.exec(line)?.[1].length || 0).filter(Boolean));
    return " ".repeat(least >= 2 && least <= 8 ? least : 4);
  };
  area.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { leaving = true; return; }
    // Return starts the next line at this one's indent, a level in after one that opens a
    // block (ends in ":", "{", "[" or "("), as a code editor does.
    if (event.key === "Enter" && !event.shiftKey && !event.metaKey && !event.ctrlKey && !event.altKey && !event.isComposing) {
      leaving = false;
      const { selectionStart: start, selectionEnd: end, value } = area;
      const before = value.slice(value.lastIndexOf("\n", start - 1) + 1, start);
      const indent = /^[ \t]*/.exec(before)[0] + (/[:{[(]\s*$/.test(before) ? unitOf(value) : "");
      if (!indent) return;
      event.preventDefault();
      area.setRangeText(`\n${indent}`, start, end, "end");
      area.dispatchEvent(new Event("input"));
      return;
    }
    if (event.key !== "Tab") { if (!["Shift", "Control", "Alt", "Meta"].includes(event.key)) leaving = false; return; }
    if (event.metaKey || event.altKey) return;
    // The web view moves focus for a plain Tab only: Ctrl-Tab is moved here.
    if (event.ctrlKey) { event.preventDefault(); leaving = false; nextField(area, event.shiftKey ? -1 : 1); return; }
    if (leaving) { leaving = false; return; }
    event.preventDefault();
    const { selectionStart: start, selectionEnd: end, value } = area;
    const lineStart = value.lastIndexOf("\n", start - 1) + 1;
    const unit = unitOf(value);
    if (start === end && !event.shiftKey) {
      area.setRangeText(unit, start, end, "end");
    } else {
      const block = value.slice(lineStart, end);
      // Lines with words on them are indented; empty ones are left empty.
      const changed = event.shiftKey ? block.replace(new RegExp(`^ {1,${unit.length}}`, "gm"), "") : block.replace(/^(?=.)/gm, unit);
      if (changed === block) return;
      area.setRangeText(changed, lineStart, end, "select");
    }
    area.dispatchEvent(new Event("input"));
  });
  return area;
}
ui.indent = indentKeys;

// What Tab goes to, in order: within an open dialog, only its own.
export function tabbables(root = document) {
  return [...root.querySelectorAll("a[href], button, input, select, textarea, summary, [tabindex], [contenteditable]")].filter((node) =>
    !node.disabled && (node.tabIndex >= 0 || (node.isContentEditable && node.getAttribute("tabindex") !== "-1"))
    && !(node.isContentEditable && node.parentElement?.isContentEditable) && node.type !== "hidden"
    && node.getClientRects().length > 0 && getComputedStyle(node).visibility !== "hidden" && !node.closest("[inert]"));
}

function nextField(from, step) {
  const items = tabbables(from.closest(".dialog") || document);
  const at = items.indexOf(from);
  items[(at + step + items.length) % items.length]?.focus();
}

// -- popovers -------------------------------------------------------------------------

let openMenu = null;
let openAnchor = null;

// A floating panel beside `anchor` (an element, or a point {x, y}), closed by a click elsewhere.
export function popover(anchor, content, { align = "start", className = "" } = {}) {
  closeMenu();
  const node = h(`div.menu${className ? `.${className}` : ""}`, { role: "dialog" }, content);
  return place(node, anchor, align);
}

// `checked` on items: a pop-up's choices, the one in use ticked, as a Mac's menu ticks it.
export function menu(anchor, items, { align = "start", className = "" } = {}) {
  closeMenu();
  const node = h(`div.menu${className ? `.${className}` : ""}`, { role: "menu" });
  const ticks = items.some((item) => item?.checked !== undefined);
  for (const item of items) {
    if (item === "-") { node.append(h("div.menu-sep")); continue; }
    if (item.title) { node.append(h("div.menu-title", {}, item.title)); continue; }
    // `show(on)`: what the item would act on, shown while it is under the pointer or keys.
    const shown = item.show ? { onmouseenter: () => item.show(true), onmouseleave: () => item.show(false), onfocus: () => item.show(true), onblur: () => item.show(false) } : {};
    node.append(h(`button.menu-item${item.danger ? ".danger" : ""}${item.checked ? ".checked" : ""}`, { type: "button", role: ticks ? "menuitemradio" : "menuitem",
      "aria-checked": ticks ? String(Boolean(item.checked)) : undefined, disabled: Boolean(item.disabled),
      onclick: () => { item.show?.(false); closeMenu(); item.run?.(); }, ...shown },
      ticks ? h("span.menu-tick", {}, item.checked ? icon("check") : null) : null,
      item.icon ? icon(item.icon) : null,
      h("span.menu-text", {}, h("span", { style: item.style }, item.label), item.hint ? h("span.menu-hint", {}, item.hint) : null),
      item.keys ? h("span.kbd", {}, item.keys) : null));
  }
  // Closed any way, nothing stays shown.
  const showing = items.filter((item) => item?.show);
  if (showing.length) new MutationObserver((_, watch) => { if (!node.isConnected) { showing.forEach((item) => item.show(false)); watch.disconnect(); } }).observe(document.body, { childList: true });
  return place(node, anchor, align);
}

// Pop-up buttons: their menus are at least as wide as they are, as a Mac's are.
const POPUPS = ".select, .palette-pick, .type-pick, .theme-card.compact, .combo";
// Room enough under a button for a menu to scroll there, rather than open over it.
const ROOM = 240;

// A pop-up's menu over its button (overButton). Any other: under its button, where it fits,
// or scrolling there while a fair part of it does; else above, if it fits; else on the
// roomier side, scrolling -- never over the button that opened it, nor over the window's
// top bar, and a scrolling list ending on a whole row. A
// menu at a point (a context menu) opens there and moves up as far as it must to show every
// item, as on a Mac; only one taller than the window scrolls.
function place(node, anchor, align) {
  const point = !anchor.getBoundingClientRect;
  if (point) node.style.maxHeight = `${innerHeight - 16}px`;
  else if (anchor.matches?.(POPUPS)) node.style.minWidth = `${anchor.getBoundingClientRect().width}px`;
  document.body.append(node);
  const box = point ? { left: anchor.x, right: anchor.x, bottom: anchor.y, top: anchor.y } : anchor.getBoundingClientRect();
  const width = node.offsetWidth, height = node.offsetHeight;
  const bar = point ? null : document.querySelector(".studio > .bar")?.getBoundingClientRect();
  const ceiling = Math.max(8, bar?.height ? bar.bottom + 4 : 8);
  const below = innerHeight - 8 - (box.bottom + 4), above = box.top - 4 - ceiling;
  if (point || !anchor.matches?.(OVER) || !overButton(node, anchor, box, ceiling)) {
    let left = align === "end" ? box.right - width : box.left;
    let top = box.bottom + 4;
    if (point) {
      top = Math.max(8, Math.min(top, innerHeight - 8 - height));
      // Too near the right edge, it opens to the left of the pointer.
      if (left + width > innerWidth - 8 && box.left - width >= 8) left = box.left - width;
    } else if (height > below) {
      if (below >= ROOM) node.style.maxHeight = `${below}px`;
      else if (height <= above) top = null;
      else if (above > below) { node.style.maxHeight = `${above}px`; top = null; }
      else node.style.maxHeight = `${below}px`;
      if (height > Math.max(above, below) || below >= ROOM) node.style.overflowY = "auto";
    }
    if (!point) wholeRows(node);
    // Over its button, it ends just above it.
    if (top === null) top = box.top - 4 - node.offsetHeight;
    left = Math.min(Math.max(8, left), innerWidth - width - 8);
    Object.assign(node.style, { left: `${left}px`, top: `${top}px` });
  }
  // A menu that scrolls says there is more below, as a Mac's shows its arrow there.
  const more = () => node.classList.toggle("more-below", node.scrollTop + node.clientHeight < node.scrollHeight - 6);
  more();
  node.addEventListener("scroll", more, { passive: true });
  openMenu = node;
  // The button that opened it shows it is open, as a Mac's pop-up button does.
  openAnchor = point ? null : anchor;
  openAnchor?.classList?.add("menu-open");
  // Keys work in it at once, as in a Mac menu: arrows move, Return chooses, Esc goes back.
  returnTo = document.activeElement;
  node.tabIndex = -1;
  node.classList.add("fresh");
  node.addEventListener("pointermove", () => node.classList.remove("fresh"), { once: true });
  node.addEventListener("keydown", menuKeys);
  // A panel's first field has the keys -- or, with none, its choice in use, as a Mac's pop-up
  // menu opens on the item chosen; else its first button.
  const items = node.getAttribute("role") === "menu" ? [] : focusables(node);
  const first = items.find((item) => item.matches("input, textarea")) || items.find((item) => item.matches(".on, .checked")) || items[0];
  (first || node).focus({ preventScroll: true });
  if (first?.matches(".on, .checked")) first.scrollIntoView({ block: "nearest" });
  setTimeout(() => document.addEventListener("pointerdown", outside, true), 0);
  return node;
}
let returnTo = null;

// A pop-up button's menu opens as a Mac's does: its chosen item over the button, the item's
// words (or icon) where the button's are -- a menu that would run out of the window cut at
// its edge, scrolling there, the chosen item still over the button (moved only when that
// would leave a row or less beside it). Else (nothing chosen) it opens under the button
// (place).
const OVER = ".select:not(.font-pick), .palette-pick";
function overButton(node, anchor, box, ceiling) {
  const chosen = node.querySelector(".menu-item.checked, .palette-choice.on");
  if (!chosen) return false;
  const icons = anchor.matches(".icon-select");
  const label = anchor.querySelector(":scope > span:not(.palette-strip)");
  const words = icons ? chosen.querySelector(":scope > svg") : chosen.querySelector(".menu-text") || chosen.querySelector(":scope > span:not(.palette-strip)");
  const shift = label && words ? (words.getBoundingClientRect().left - node.getBoundingClientRect().left) - (label.getBoundingClientRect().left - box.left) : 0;
  let left = box.left - shift;
  // As wide as the button at least, from where it starts to the button's end.
  node.style.minWidth = `${Math.max(box.width, box.right - left)}px`;
  node.style.maxHeight = `${innerHeight - 8 - ceiling}px`;
  node.style.overflowY = "auto";
  const width = node.offsetWidth, height = node.offsetHeight;
  const frame = node.getBoundingClientRect(), row = chosen.getBoundingClientRect();
  const middle = row.top - frame.top + node.scrollTop + row.height / 2;
  const want = box.top + box.height / 2;
  const whole = node.scrollHeight + node.offsetHeight - node.clientHeight;
  let top = want - middle;
  const hidden = Math.max(0, ceiling - top);
  top += hidden;
  const room = innerHeight - 8 - top;
  if (whole - hidden > room && room >= middle - hidden + row.height * 1.5) node.style.maxHeight = `${room}px`;
  else top = Math.min(Math.max(want - middle, ceiling), innerHeight - 8 - height);
  left = Math.min(Math.max(8, left), innerWidth - width - 8);
  Object.assign(node.style, { left: `${left}px`, top: `${top}px` });
  node.scrollTop = Math.max(0, middle - (want - top));
  return true;
}

// A list that scrolls ends on a whole row, not on a row cut by the window's edge: the menu
// (or the list in it, under a search field) shows as many whole rows as fit, rows of two
// lines (a hint under a name) and lines between them as they are.
function wholeRows(node) {
  const list = node.querySelector(".font-list") || node;
  const rows = [...list.querySelectorAll(".menu-item, .palette-choice")];
  if (rows.length < 2) return;
  const top = node.getBoundingClientRect().top + node.clientTop, room = node.clientHeight;
  const end = parseFloat(getComputedStyle(node).paddingBottom) || 0;
  const bottoms = rows.map((row) => row.getBoundingClientRect().bottom - top);
  if (bottoms[bottoms.length - 1] + end <= room + 1) return;
  const last = bottoms.filter((bottom) => bottom + end <= room + 0.5).pop();
  if (last > 0) node.style.maxHeight = `${last + end + node.offsetHeight - node.clientHeight}px`;
}

// `shown(on)` called as a menu opens, and again once it has gone, however it went.
export function whileOpen(node, shown) {
  shown(true);
  new MutationObserver((_, watch) => { if (!node.isConnected) { shown(false); watch.disconnect(); } }).observe(document.body, { childList: true });
}

// A pop-up button's choices (`items`: { value, label }), the one in use ticked, under the
// button; `pick(value)` takes the one chosen. Opened by a key, the one in use has the keys.
function choices(anchor, items, current, pick, byKey = false) {
  const node = menu(anchor, items.map((item) => (item === "-" ? "-" : item.action ? { label: item.label, icon: item.icon, checked: false, disabled: item.disabled, show: item.show, run: item.run }
    : { label: item.label, icon: item.icon, checked: item.value === current, disabled: item.disabled, style: item.style, run: () => pick(item.value) })),
    { className: "choice-menu" });
  const chosen = node.querySelector(".menu-item.checked");
  chosen?.scrollIntoView({ block: "nearest" });
  if (byKey) (chosen || node.querySelector(".menu-item:not(:disabled)"))?.focus({ preventScroll: true });
  return node;
}

const focusables = (node) => [...node.querySelectorAll("button:not(:disabled), input, select, textarea, [tabindex='0']")].filter((item) => item.offsetParent !== null);

function menuKeys(event) {
  const node = event.currentTarget;
  const items = node.getAttribute("role") === "menu" ? [...node.querySelectorAll(".menu-item:not(:disabled)")] : focusables(node);
  const at = items.indexOf(document.activeElement);
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "") || Boolean(document.activeElement?.isContentEditable);
  const go = (index) => { event.preventDefault(); items[(index + items.length) % items.length]?.focus({ preventScroll: true }); };
  if (event.key === "ArrowDown" || (event.key === "ArrowRight" && !typing)) go(at + 1);
  else if (event.key === "ArrowUp" || (event.key === "ArrowLeft" && !typing)) go(at < 0 ? -1 : at - 1);
  else if (event.key === "Home" && !typing) go(0);
  else if (event.key === "End" && !typing) go(-1);
  else if (event.key === "Tab") go(at + (event.shiftKey ? -1 : 1));
  else if (event.key.length === 1 && !typing && !event.metaKey && !event.ctrlKey && /\S/.test(event.key)) {
    // A letter goes to the next item that starts with it.
    const next = [...items.slice(at + 1), ...items.slice(0, at + 1)].find((item) => item.textContent.trim().toLowerCase().startsWith(event.key.toLowerCase()));
    if (next) { event.preventDefault(); next.focus({ preventScroll: true }); }
  }
  event.stopPropagation();
}

function outside(event) {
  if (openMenu && !openMenu.contains(event.target)) closeMenu();
}

// Esc closes the menu and only the menu: not the dialog it was opened from, too.
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && openMenu) { event.stopImmediatePropagation(); closeMenu(); }
}, true);

export function closeMenu() {
  const had = openMenu?.contains(document.activeElement);
  openMenu?.remove();
  openMenu = null;
  openAnchor?.classList?.remove("menu-open");
  openAnchor = null;
  document.removeEventListener("pointerdown", outside, true);
  // Focus goes back where it was, so keys go on to what they went to before.
  if (had && returnTo?.isConnected) returnTo.focus({ preventScroll: true });
  returnTo = null;
}

// A dialog holds the keys while it is open, as a Mac sheet does: Tab goes round its own
// controls, never to the page behind, and when it closes, focus goes back where it was.
export function dialog({ title, body, actions = [], wide = false, onClose } = {}) {
  const before = document.activeElement;
  let open = true;
  const close = () => {
    if (!open) return;
    open = false;
    scrim.remove();
    document.removeEventListener("keydown", keys, true);
    const under = [...document.querySelectorAll(".scrim")].pop();
    if (before?.isConnected && before !== document.body && (!under || under.contains(before))) before.focus({ preventScroll: true });
    onClose?.();
  };
  const topmost = () => [...document.querySelectorAll(".scrim")].pop() === scrim;
  const keys = (event) => {
    if (!topmost()) return;
    if (event.key === "Escape") { event.stopPropagation(); close(); }
    // Keys from outside it (focus left on the page) come into it; a menu opened from it keeps its own.
    else if (event.key === "Tab" && !panel.contains(document.activeElement) && !document.activeElement?.closest?.(".menu")) {
      event.preventDefault();
      const items = tabbables(panel);
      (items[event.shiftKey ? items.length - 1 : 0] || panel).focus();
    }
  };
  // A sheet with a Cancel or a Done is closed by it (or Esc), as a Mac's is: no × beside its
  // title too.
  const cancels = actions.some((action) => action.label === "Cancel" || action.label === "Done");
  const panel = h(`div.dialog${wide ? ".wide" : ""}`, { role: "dialog", "aria-modal": "true", tabIndex: -1 },
    h("div.dialog-head", {}, h("div.dialog-title", {}, title), h("div.spacer"), cancels ? null : ui.button("", close, { kind: "ghost", icon: "close", title: "Close" })),
    h("div.dialog-body.scroll-thin", { tabIndex: -1 }, body),
    // Actions `aside` (Upload…, New Folder…) stand at the left, as in a Mac's open panel;
    // Cancel and the default at the right.
    actions.length ? h("div.dialog-foot", {}, [...actions.filter((action) => action.aside), ...(actions.some((action) => action.aside) ? [h("div.spacer")] : []), ...actions.filter((action) => !action.aside)].map((action) =>
      action.label === undefined ? action : ui.button(action.label, () => { if (action.run?.() !== false) close(); }, { kind: action.kind || "" }))) : null);
  // Tab from its last control goes to its first, ⇧Tab from its first to its last. A Tab
  // a field took (indenting code) is the field's.
  panel.addEventListener("keydown", (event) => {
    if (event.key !== "Tab" || event.defaultPrevented || event.metaKey || event.altKey || event.ctrlKey) return;
    const items = tabbables(panel);
    const at = items.indexOf(document.activeElement);
    const end = event.shiftKey ? at <= 0 : at === items.length - 1 || at < 0;
    if (!end) return;
    event.preventDefault();
    (items[event.shiftKey ? items.length - 1 : 0] || panel).focus();
  });
  const scrim = h("div.scrim", { onmousedown: (event) => { if (event.target === scrim) close(); } }, panel);
  document.addEventListener("keydown", keys, true);
  document.body.append(scrim);
  // The dialog has the keys at once (Esc, Tab, and the arrows scroll what it says); a caller
  // that wants a field focused focuses it.
  panel.querySelector(".dialog-body").focus({ preventScroll: true });
  return { close };
}

const toasts = () => document.querySelector(".toasts") || document.body.appendChild(h("div.toasts"));

// Nothing floats over a sheet, as on a Mac: a toast is out of sight while one is open
// (studio.css), and its time stands still -- one shown a moment before a sheet opened is
// still there when it closes.
const sheetOpen = () => Boolean(document.querySelector(".scrim:not(.palette-scrim)"));
// Toasts stand over the foot of the document's own room when it marks one (`data-toast-area`:
// a deck's stage, above its notes) -- not over the notes, the inspector or a menu (studio.css)
// -- else at the foot of the window.
function placeToasts(box) {
  const area = [...(document.querySelectorAll?.("[data-toast-area]") || [])].find((node) => node.offsetParent !== null);
  const room = area?.getBoundingClientRect();
  if (room?.width) Object.assign(box.style, { left: `${room.left + room.width / 2}px`, bottom: `${Math.max(16, innerHeight - room.bottom + 16)}px` });
  else Object.assign(box.style, { left: "", bottom: "" });
}
export function toast(message, { kind = "", seconds = 3.5, icon: iconName } = {}) {
  const node = h(`div.toast${kind ? `.${kind}` : ""}`, {}, iconName ? icon(iconName) : null, message);
  const box = toasts();
  placeToasts(box);
  box.append(node);
  const fade = () => { node.style.transition = "opacity .3s"; node.style.opacity = "0"; setTimeout(() => node.remove(), 300); };
  let left = seconds * 1000;
  const tick = () => {
    if (!node.isConnected) return;
    if (!sheetOpen()) left -= 250;
    if (left <= 0) fade(); else setTimeout(tick, 250);
  };
  setTimeout(tick, 250);
  return node;
}


// -- maths, as words to read in a list ----------------------------------------------------

const GREEK = "alpha α beta β gamma γ delta δ epsilon ϵ varepsilon ε zeta ζ eta η theta θ vartheta ϑ iota ι kappa κ lambda λ mu μ nu ν xi ξ pi π varpi ϖ rho ρ varrho ϱ sigma σ varsigma ς tau τ upsilon υ phi ϕ varphi φ chi χ psi ψ omega ω Gamma Γ Delta Δ Theta Θ Lambda Λ Xi Ξ Pi Π Sigma Σ Upsilon Υ Phi Φ Psi Ψ Omega Ω";
const SIGNS = "cdot · times × pm ± mp ∓ div ÷ le ≤ leq ≤ ge ≥ geq ≥ ne ≠ neq ≠ approx ≈ sim ∼ simeq ≃ equiv ≡ propto ∝ in ∈ notin ∉ subset ⊂ subseteq ⊆ cup ∪ cap ∩ to → rightarrow → leftarrow ← Rightarrow ⇒ implies ⟹ iff ⟺ mapsto ↦ infty ∞ partial ∂ nabla ∇ sum Σ prod Π int ∫ oint ∮ sqrt √ mid | parallel ∥ ldots … dots … cdots ⋯ langle ⟨ rangle ⟩ forall ∀ exists ∃ neg ¬ wedge ∧ vee ∨ oplus ⊕ otimes ⊗ odot ⊙ circ ∘ ell ℓ hbar ℏ emptyset ∅ top ⊤ perp ⊥ star ⋆ ast ∗ prime ′ lVert ‖ rVert ‖ lvert | rvert | lfloor ⌊ rfloor ⌋ lceil ⌈ rceil ⌉ degree °";
const TEX_WORDS = Object.fromEntries([...GREEK.split(" "), ...SIGNS.split(" ")].reduce((pairs, item, i, all) => (i % 2 ? pairs : [...pairs, [item, all[i + 1]]]), []));
const SUB = { 0: "₀", 1: "₁", 2: "₂", 3: "₃", 4: "₄", 5: "₅", 6: "₆", 7: "₇", 8: "₈", 9: "₉", "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎", a: "ₐ", e: "ₑ", o: "ₒ", x: "ₓ", h: "ₕ", k: "ₖ", l: "ₗ", m: "ₘ", n: "ₙ", p: "ₚ", s: "ₛ", t: "ₜ", i: "ᵢ", j: "ⱼ", r: "ᵣ", u: "ᵤ", v: "ᵥ",
  β: "ᵦ", γ: "ᵧ", ρ: "ᵨ", ϕ: "ᵩ", φ: "ᵩ", χ: "ᵪ" };
// Every letter Unicode raises: all but q of the small ones, most capitals, a few Greek.
const SUP = { 0: "⁰", 1: "¹", 2: "²", 3: "³", 4: "⁴", 5: "⁵", 6: "⁶", 7: "⁷", 8: "⁸", 9: "⁹", "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾", n: "ⁿ", i: "ⁱ", T: "ᵀ", "⊤": "ᵀ", "′": "′", k: "ᵏ", t: "ᵗ", x: "ˣ", "*": "*",
  ...Object.fromEntries([..."abcdefghjlmoprsuvwyz"].map((ch, at) => [ch, [..."ᵃᵇᶜᵈᵉᶠᵍʰʲˡᵐᵒᵖʳˢᵘᵛʷʸᶻ"][at]])),
  ...Object.fromEntries([..."ABDEGHIJKLMNOPRUVW"].map((ch, at) => [ch, [..."ᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵁⱽᵂ"][at]])),
  α: "ᵅ", β: "ᵝ", γ: "ᵞ", δ: "ᵟ", ϵ: "ᵋ", ε: "ᵋ", θ: "ᶿ", ι: "ᶥ", ϕ: "ᵠ", φ: "ᵠ", χ: "ᵡ" };
const ALPHABET = { mathcal: [0x1d49c, { B: "ℬ", E: "ℰ", F: "ℱ", H: "ℋ", I: "ℐ", L: "ℒ", M: "ℳ", R: "ℛ" }],
  mathbb: [0x1d538, { C: "ℂ", H: "ℍ", N: "ℕ", P: "ℙ", Q: "ℚ", R: "ℝ", Z: "ℤ" }] };

// A script Unicode cannot set keeps its mark: a power in brackets (e^(−x²/2)), a word
// lowered as it is (x_eff), and one letter lowered reads as itself beside what it is on
// (pθ, not p_θ). The marks kept are held aside (\u0005, \u0006) until the end, so they are
// not read again as scripts.
function script(text, table, mark) {
  const chars = [...text];
  if (chars.every((ch) => ch in table)) return chars.map((ch) => table[ch]).join("");
  if (mark === "_") return chars.length === 1 ? text : `\u0005${text}`;
  return `\u0006${chars.length > 1 ? `(${text})` : text}`;
}

// A fraction's part in brackets when it is more than one term.
const grouped = (tex) => { const words = mathWords(tex); return /[\s+−\-=/·×]/.test(words) ? `(${words})` : words; };

// A formula as a line of words: Greek and signs as themselves, fractions as a/b,
// scripts raised or lowered where Unicode can, commands without their backslashes.
export function mathWords(tex) {
  let text = String(tex ?? "").replace(/\\(left|right|big|Big|bigg|Bigg)[lrm]?\b\.?/g, "")
    .replace(/\\(displaystyle|textstyle|limits|nolimits|,|;|:|!|quad|qquad)\b|\\[,;:!]/g, " ")
    .replace(/\\begin\{[a-z*]+\}|\\end\{[a-z*]+\}/g, " ").replace(/&/g, "").replace(/\\\\/g, "; ")
    // Greek and signs first, so a script of one (p_{\theta}, x^{\prime}) is set as one; not
    // a command taking an argument (\sqrt{…}, set below).
    .replace(/\\([A-Za-z]+)(?![A-Za-z{])/g, (whole, name) => TEX_WORDS[name] ?? whole);
  for (let i = 0; i < 20; i++) {
    const before = text;
    text = text
      .replace(/\\[dtc]?frac\{([^{}]*)\}\{([^{}]*)\}/g, (_, a, b) => `${grouped(a)}/${grouped(b)}`)
      .replace(/\\sqrt\{([^{}]*)\}/g, (_, a) => `√${grouped(a)}`)
      .replace(/\\(mathcal|mathbb)\{([A-Z])\}/g, (_, font, ch) => ALPHABET[font][1][ch] || String.fromCodePoint(ALPHABET[font][0] + ch.charCodeAt(0) - 65))
      .replace(/\\(mathrm|mathbf|mathit|mathsf|mathtt|text|textrm|textbf|operatorname\*?|boldsymbol|bm|hat|bar|tilde|vec|dot|overline|underline|mathcal|mathbb|mathfrak|ce)\{([^{}]*)\}/g, "$2")
      .replace(/_\{([^{}]*)\}/g, (_, a) => script(a, SUB, "_"))
      .replace(/\^\{([^{}]*)\}/g, (_, a) => script(a, SUP, "^"))
      // A group of its own (not a command's argument) is only its contents.
      .replace(/(^|[^A-Za-z}])\{([^{}]*)\}/g, "$1$2");
    if (text === before) break;
  }
  return text
    .replace(/\\([A-Za-z]+)/g, (_, name) => TEX_WORDS[name] ?? name)
    .replace(/\\([{}$%#&_|])/g, "$1")
    .replace(/_([^\s_^])/g, (_, a) => script(a, SUB, "_"))
    .replace(/\^([^\s_^])/g, (_, a) => script(a, SUP, "^"))
    .replace(/\u0005/g, "_").replace(/\u0006/g, "^")
    .replace(/'/g, "′").replace(/-/g, "−").replace(/\s+/g, " ").trim();
}

// Words in flexo markup set as they read on a slide: strong, emphatic, code and maths (as
// words) as such, links and colours as their words in a colour; the marks themselves gone.
const MARKS = /\\([$*`\]\\])|\*\*(.+?)\*\*|\*(?!\s)(.+?)\*|`([^`]+)`|\$\$([\s\S]+?)\$\$|\$(?!\s)([^$]+?)(?<!\s)\$(?!\d)|\[([^\]]+)\]\([^)]*\)|\[([^\]]+)\]\{([^}]*)\}/g;
const ROLE_COLOURS = { accent: "var(--accent)", accent2: "var(--accent-2)", muted: "var(--ink-3)" };
export function markupNodes(markup) {
  const text = String(markup ?? "");
  const nodes = [];
  let at = 0;
  for (const match of text.matchAll(MARKS)) {
    const [whole, mark, strong, emphatic, code, shown, maths, linked, coloured, colour] = match;
    if (match.index > at) nodes.push(text.slice(at, match.index));
    if (mark !== undefined) nodes.push(mark);
    else if (strong !== undefined) nodes.push(h("b", {}, markupNodes(strong)));
    else if (emphatic !== undefined) nodes.push(h("i", {}, markupNodes(emphatic)));
    else if (code !== undefined) nodes.push(h("code", {}, code));
    else if (shown !== undefined || maths !== undefined) nodes.push(h("span.maths", {}, mathWords(shown ?? maths)));
    else if (linked !== undefined) nodes.push(h("u", {}, markupNodes(linked)));
    else nodes.push(h("span", { style: { color: ROLE_COLOURS[colour] || (HEX.test(colour) ? colour : "") } }, markupNodes(coloured)));
    at = match.index + whole.length;
  }
  if (at < text.length) nodes.push(text.slice(at));
  return nodes;
}

// Words in flexo markup as they read: maths as words, emphasis, links and colours as plain words.
export function readable(markup) {
  // Escaped marks (\$ \* \` \]) are the marks themselves, held aside while the rest is read,
  // and a backslash typed before a bracket (written \\( or \\[) is a backslash, not maths.
  const held = { "\u0000": "$", "\u0001": "*", "\u0002": "`", "\u0003": "]", "\u0004": "\\" };
  return String(markup ?? "").replace(/\\\\(?=[([\]])/g, "\u0004").replace(/\\\$/g, "\u0000").replace(/\\\*/g, "\u0001").replace(/\\`/g, "\u0002").replace(/\\\](?=[({])/g, "\u0003")
    .replace(/\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)/g, (_, a, b, c) => mathWords(a ?? b ?? c))
    .replace(/\$(?!\s)([^$]+?)(?<!\s)\$(?!\d)/g, (_, tex) => mathWords(tex))
    .replace(/\\\]/g, "\u0003")
    .replace(/\[([^\]]+)\]\{[^}]+\}/g, "$1").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\*\*|\*|`/g, "")
    .replace(/[\u0000-\u0004]/g, (mark) => held[mark]);
}
