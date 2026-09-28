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
  up: "M8 12.5v-9M4.5 7L8 3.5 11.5 7",
  down: "M8 3.5v9M4.5 9L8 12.5 11.5 9",
  left: "M12.5 8h-9M7 4.5L3.5 8 7 11.5",
  right: "M3.5 8h9M9 4.5L12.5 8 9 11.5",
  chevron: "M6 4l4 4-4 4",
  "chevron-down": "M4 6l4 4 4-4",
  grip: "M6 4h.01M10 4h.01M6 8h.01M10 8h.01M6 12h.01M10 12h.01",
  undo: "M5.5 3.5L2.5 6.5l3 3M2.5 6.5h7a3.5 3.5 0 010 7H7",
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
  heading: "M4 3v10M12 3v10M4 8h8",
  list: "M6 4h7M6 8h7M6 12h7M3 4h.01M3 8h.01M3 12h.01",
  numbered: "M7 4h6M7 8h6M7 12h6M3 3v3M2.5 9.5h1.5l-1.5 2.5H4",
  table: "M2.5 3.5h11v9h-11zM2.5 6.5h11M6.5 6.5v6",
  code: "M5.5 4.5L2 8l3.5 3.5M10.5 4.5L14 8l-3.5 3.5",
  quote: "M3 9.5c0-3 1-4.5 3-5.5M3 9.5h3v3H3zM9 9.5c0-3 1-4.5 3-5.5M9 9.5h3v3H9z",
  stats: "M3 13V8M8 13V3M13 13V6",
  callout: "M3 3h10v7H8l-3 3v-3H3z",
  figure: "M2.5 5.5h4v5h-4zM9.5 5.5h4v5h-4zM6.5 8h3",
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
  return node;
}

// -- controls -------------------------------------------------------------------------

export const ui = {
  button(label, onClick, { kind = "", icon: iconName, title, small, disabled, id } = {}) {
    const classes = ["btn", kind, small ? "small" : "", !label ? "icon" : ""].filter(Boolean).join(" ");
    return h("button", { class: classes, type: "button", title, disabled, id, onclick: onClick },
      iconName ? icon(iconName) : null, label || null);
  },

  field(label, control, { hint, inline } = {}) {
    return h(`div.field${inline ? ".inline" : ""}`, {},
      label ? h("label.label", {}, label, hint ? h("span.hint", {}, hint) : null) : null, control);
  },

  input({ value = "", placeholder = "", onInput, onChange, type = "text", mono, list, width, key } = {}) {
    const node = h(`input.input${mono ? ".mono" : ""}`, { type, placeholder, spellcheck: false });
    if (key) node.dataset.key = key;
    node.value = value ?? "";
    if (width) node.style.width = width;
    if (list) node.setAttribute("list", list);
    if (onInput) node.addEventListener("input", () => onInput(node.value));
    if (onChange) node.addEventListener("change", () => onChange(node.value));
    return node;
  },

  number({ value, placeholder = "", onChange, min, max, step = "any", key } = {}) {
    const node = h("input.input", { type: "number", placeholder, step });
    if (key) node.dataset.key = key;
    if (min !== undefined) node.min = min;
    if (max !== undefined) node.max = max;
    node.value = value ?? "";
    node.addEventListener("input", () => {
      const text = node.value.trim();
      const parsed = text === "" ? null : Number(text);
      node.classList.toggle("invalid", parsed !== null && Number.isNaN(parsed));
      if (parsed === null || !Number.isNaN(parsed)) onChange?.(parsed);
    });
    return node;
  },

  textarea({ value = "", rows = 3, placeholder = "", onInput, mono, grow = true, tabs = mono, key } = {}) {
    const node = h(`textarea.textarea${mono ? ".mono" : ""}${grow ? ".grow" : ""}`, { rows, placeholder, spellcheck: !mono });
    if (key) node.dataset.key = key;
    node.value = value ?? "";
    if (tabs) node.addEventListener("keydown", (event) => indentKeys(event, node));
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
  markup({ value = "", rows = 1, placeholder = "", onInput, colours = true, tabs = false, key } = {}) {
    const area = ui.textarea({ value, rows, placeholder, onInput, tabs, key });
    area.addEventListener("keydown", (event) => {
      const mod = event.metaKey || event.ctrlKey;
      if (mod && event.key.toLowerCase() === "b") { event.preventDefault(); wrap(area, "**", "**", onInput); }
      if (mod && event.key.toLowerCase() === "i") { event.preventDefault(); wrap(area, "*", "*", onInput); }
      if (mod && event.key.toLowerCase() === "k") { event.preventDefault(); wrap(area, "[", "](https://)", onInput); }
      if (mod && event.key.toLowerCase() === "m") { event.preventDefault(); wrap(area, "$", "$", onInput); }
    });
    const tool = (label, title, before, after, style) =>
      h("button", { type: "button", title, style, onmousedown: (event) => { event.preventDefault(); wrap(area, before, after, onInput); } }, label);
    const tools = h("div.markup-tools", {},
      tool("B", "Strong (⌘B)", "**", "**", { fontWeight: 700 }),
      tool("I", "Emphasis (⌘I)", "*", "*", { fontStyle: "italic", fontFamily: "Georgia, serif" }),
      tool("$x$", "Maths (⌘M)", "$", "$", { fontFamily: "Georgia, serif", fontStyle: "italic" }),
      tool("</>", "Code", "`", "`", { fontFamily: "var(--mono)", fontSize: "11px" }),
      tool("🔗", "Link (⌘K)", "[", "](https://)"),
      colours ? h("span.sep") : null,
      colours ? tool("A", "Accent colour", "[", "]{accent}", { color: "var(--accent)", fontWeight: 700 }) : null,
      colours ? tool("A", "Second accent", "[", "]{accent2}", { color: "#c2410c", fontWeight: 700 }) : null,
      colours ? tool("A", "Muted", "[", "]{muted}", { color: "var(--ink-3)", fontWeight: 700 }) : null,
    );
    const node = h("div.markup", {}, tools, area);
    node.area = area;
    return node;
  },

  select({ value, options, onChange, placeholder } = {}) {
    const node = h("select.select");
    if (placeholder !== undefined) node.append(h("option", { value: "" }, placeholder));
    for (const option of options) {
      const item = typeof option === "object" ? option : { value: option, label: String(option) };
      node.append(h("option", { value: item.value }, item.label));
    }
    node.value = value ?? "";
    node.addEventListener("change", () => onChange?.(node.value));
    return node;
  },

  // A text input offering suggestions, for values that are usually but not always from a list.
  combo({ value, options = [], placeholder = "", onChange, mono, key } = {}) {
    const id = `list-${Math.random().toString(36).slice(2)}`;
    const list = h("datalist", { id }, options.map((option) => h("option", { value: option })));
    const input = ui.input({ value, placeholder, mono, list: id, key, onInput: (text) => onChange?.(text) });
    return h("div", { style: { display: "contents" } }, input, list);
  },

  toggle({ value, label, onChange } = {}) {
    const box = h("input", { type: "checkbox" });
    box.checked = Boolean(value);
    box.addEventListener("change", () => onChange?.(box.checked));
    return h("label.switch", {}, box, h("span.track"), label ? h("span", {}, label) : null);
  },

  segmented({ value, options, onChange } = {}) {
    const node = h("div.segmented", { role: "radiogroup" });
    const buttons = options.map((option) => {
      const item = typeof option === "object" ? option : { value: option, label: String(option) };
      const button = h("button", { type: "button", title: item.title || item.label, class: item.value === value ? "on" : "",
        onclick: () => { buttons.forEach((b) => b.classList.remove("on")); button.classList.add("on"); onChange?.(item.value); } },
        item.icon ? icon(item.icon) : null, item.label ?? null);
      return button;
    });
    node.append(...buttons);
    return node;
  },

  swatches({ value, colours, onChange, none = true } = {}) {
    const node = h("div.swatches");
    const all = [...(none ? [{ value: null, colour: null, title: "None" }] : []), ...colours];
    const buttons = all.map((item) => {
      const button = h("button.swatch", { type: "button", title: item.title || item.value || "None",
        class: [item.value === (value ?? null) ? "on" : "", item.colour ? "" : "none"].join(" "),
        style: item.colour ? { background: item.colour } : {},
        onclick: () => { buttons.forEach((b) => b.classList.remove("on")); button.classList.add("on"); onChange?.(item.value); } });
      return button;
    });
    node.append(...buttons);
    return node;
  },
};

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

function indentKeys(event, area) {
  if (event.key !== "Tab") return;
  event.preventDefault();
  const { selectionStart: start, selectionEnd: end, value } = area;
  const lineStart = value.lastIndexOf("\n", start - 1) + 1;
  if (start === end && !event.shiftKey) {
    area.setRangeText("  ", start, end, "end");
  } else {
    const block = value.slice(lineStart, end);
    const changed = event.shiftKey ? block.replace(/^ {1,2}/gm, "") : block.replace(/^/gm, "  ");
    area.setRangeText(changed, lineStart, end, "select");
  }
  area.dispatchEvent(new Event("input"));
}

// -- popovers -------------------------------------------------------------------------

let openMenu = null;

// A floating panel beside `anchor` (an element, or a point {x, y}), closed by a click elsewhere.
export function popover(anchor, content, { align = "start", className = "" } = {}) {
  closeMenu();
  const node = h(`div.menu${className ? `.${className}` : ""}`, { role: "dialog" }, content);
  return place(node, anchor, align);
}

export function menu(anchor, items, { align = "start" } = {}) {
  closeMenu();
  const node = h("div.menu", { role: "menu" });
  for (const item of items) {
    if (item === "-") { node.append(h("div.menu-sep")); continue; }
    if (item.title) { node.append(h("div.menu-title", {}, item.title)); continue; }
    node.append(h(`button.menu-item${item.danger ? ".danger" : ""}`, { type: "button", role: "menuitem",
      onclick: () => { closeMenu(); item.run?.(); } },
      item.icon ? icon(item.icon) : null,
      h("span.menu-text", {}, h("span", {}, item.label), item.hint ? h("span.menu-hint", {}, item.hint) : null),
      item.keys ? h("span.kbd", {}, item.keys) : null));
  }
  return place(node, anchor, align);
}

function place(node, anchor, align) {
  document.body.append(node);
  const box = anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : { left: anchor.x, right: anchor.x, bottom: anchor.y, top: anchor.y };
  const width = node.offsetWidth, height = node.offsetHeight;
  let left = align === "end" ? box.right - width : box.left;
  let top = box.bottom + 4;
  if (top + height > innerHeight - 8) top = Math.max(8, box.top - height - 4);
  left = Math.min(Math.max(8, left), innerWidth - width - 8);
  Object.assign(node.style, { left: `${left}px`, top: `${top}px` });
  openMenu = node;
  setTimeout(() => document.addEventListener("pointerdown", outside, true), 0);
  return node;
}

function outside(event) {
  if (openMenu && !openMenu.contains(event.target)) closeMenu();
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && openMenu) { event.stopPropagation(); closeMenu(); }
}, true);

export function closeMenu() {
  openMenu?.remove();
  openMenu = null;
  document.removeEventListener("pointerdown", outside, true);
}

export function dialog({ title, body, actions = [], wide = false, onClose } = {}) {
  const close = () => { scrim.remove(); document.removeEventListener("keydown", keys, true); onClose?.(); };
  const keys = (event) => { if (event.key === "Escape") { event.stopPropagation(); close(); } };
  const scrim = h("div.scrim", { onmousedown: (event) => { if (event.target === scrim) close(); } },
    h(`div.dialog${wide ? ".wide" : ""}`, { role: "dialog" },
      h("div.dialog-head", {}, h("div.dialog-title", {}, title), h("div.spacer"), ui.button("", close, { kind: "ghost", icon: "close", title: "Close" })),
      h("div.dialog-body.scroll-thin", {}, body),
      actions.length ? h("div.dialog-foot", {}, actions.map((action) =>
        ui.button(action.label, () => { if (action.run?.() !== false) close(); }, { kind: action.kind || "" }))) : null));
  document.addEventListener("keydown", keys, true);
  document.body.append(scrim);
  return { close };
}

const toasts = () => document.querySelector(".toasts") || document.body.appendChild(h("div.toasts"));

export function toast(message, { kind = "", seconds = 3.5, icon: iconName } = {}) {
  const node = h(`div.toast${kind ? `.${kind}` : ""}`, {}, iconName ? icon(iconName) : null, message);
  toasts().append(node);
  setTimeout(() => { node.style.transition = "opacity .3s"; node.style.opacity = "0"; setTimeout(() => node.remove(), 300); }, seconds * 1000);
  return node;
}

