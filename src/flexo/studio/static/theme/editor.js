// The theme editor: a theme's settings on the left, grouped as a designer thinks of
// them (colour, type, line, space), and samples drawn in it on the right -- figures,
// slides, or a deck in the folder. Only what differs from the base theme is
// written; every other setting shows the base's value, ready to change.

import { h, clear, icon, ui, menu, keepFocus, picture, themeUses } from "/static/studio/studio.js";

const WEIGHTS = [300, 400, 500, 600, 700, 800];
const PAGE_NAMES = {
  canvas: "Page", ink: "Words", muted: "Quiet words", connector: "Lines", container_fill: "Group fill",
  container_stroke: "Group outline", neutral_fill: "Plain fill", neutral_stroke: "Plain outline",
  inset_fill: "Inset fill", inset_stroke: "Inset outline", shadow: "Shadow", residual: "Residual lines",
};
const ARROWS = { triangle: "M2 4l10 4-10 4z", stealth: "M2 4l10 4-10 4 3-4z", latex: "M3 4.5c3 1.5 6 3 9 3.5-3 .5-6 2-9 3.5 1-2.3 1-4.7 0-7z", open: "M3 4l9 4-9 4" };

export function mount(studio, container) {
  if (!document.querySelector('link[href="/static/kinds/theme/editor.css"]')) {
    document.head.append(h("link", { rel: "stylesheet", href: "/static/kinds/theme/editor.css" }));
  }
  const catalog = studio.catalog;
  let specimen = { name: "figures" };
  let pages = [];
  let messages = [];
  let effectiveKey = "";

  studio.hints = () => ({ specimen: specimen.name, deck: specimen.deck });
  const theme = () => studio.doc.theme || {};
  const effective = () => studio.info?.effective || {};

  // -- changing a setting --
  const get = (path) => path.reduce((value, key) => (value && typeof value === "object" ? value[key] : undefined), theme());
  const base = (path) => path.reduce((value, key) => (value && typeof value === "object" ? value[key] : undefined), effective());
  const set = (path, value, options = {}) => studio.change((doc) => {
    doc.theme ||= {};
    let target = doc.theme;
    for (const key of path.slice(0, -1)) target = target[key] = target[key] && typeof target[key] === "object" && !Array.isArray(target[key]) ? target[key] : {};
    const last = path[path.length - 1];
    if (value === null || value === undefined || value === "") delete target[last]; else target[last] = value;
    // Drop sections left empty.
    for (let depth = path.length - 1; depth > 0; depth--) {
      const parent = path.slice(0, depth - 1).reduce((node, key) => node[key], doc.theme);
      const key = path[depth - 1];
      if (parent[key] && typeof parent[key] === "object" && !Object.keys(parent[key]).length) delete parent[key];
    }
  }, { quiet: true, merge: path.join("."), ...options });

  // -- the panel --
  const form = h("div.theme-form.scroll-thin");
  const stage = h("div.stage.theme-stage.scroll-thin");
  const note = h("div.messages.theme-messages");
  const root = h("div.theme", {}, h("section.panel.theme-panel", {}, form), h("section.theme-right", {}, stage, note));
  clear(container, root);

  const row = (label, path, control, { hint } = {}) => {
    const changed = get(path) !== undefined;
    return h(`div.setting${changed ? ".changed" : ""}`, {},
      h("label.setting-label", {}, h("span.setting-dot", { title: changed ? "Changed from the base theme" : "" }), label, hint ? h("span.hint", {}, hint) : null),
      h("div.setting-control", {}, control),
      h("button.setting-reset", { type: "button", title: "Back to the base theme's", disabled: !changed, onclick: () => { set(path, null, { quiet: false }); } }, icon("undo")));
  };

  const length = (label, path, { step = 0.25, unit = "pt", hint } = {}) => {
    const given = get(path);
    const shown = base(path);
    const parse = (text) => (text == null ? null : parseFloat(String(text)));
    return row(label, path, h("div.unit-input", {},
      ui.number({ value: parse(given), placeholder: shown == null ? "none" : String(parse(shown)), step, key: path.join("."),
        onChange: (value) => set(path, value === null ? null : `${value}${unit}`) }),
      h("span.unit", {}, unit)), { hint });
  };

  const number = (label, path, { step = 0.05, min, max, hint } = {}) => row(label, path,
    ui.number({ value: get(path), placeholder: String(base(path) ?? ""), step, min, max, key: path.join("."), onChange: (value) => set(path, value) }), { hint });

  const slider = (label, path, { min = 0, max = 1, step = 0.01 } = {}) => {
    const value = get(path) ?? base(path) ?? min;
    const shown = h("span.value", {}, Number(value).toFixed(2));
    const range = h("input", { type: "range", min, max, step, value, oninput: () => { shown.textContent = Number(range.value).toFixed(2); set(path, Number(range.value)); } });
    return row(label, path, h("div.slider", {}, range, shown));
  };

  const choice = (label, path, options, { segmented = false, labels = {} } = {}) => {
    const value = get(path) ?? base(path);
    const items = options.map((option) => ({ value: option, label: labels[option] ?? String(option) }));
    return row(label, path, segmented
      ? ui.segmented({ value, options: items, onChange: (next) => set(path, next, { quiet: false }) })
      : ui.select({ value, options: items, onChange: (next) => set(path, WEIGHTS.includes(Number(next)) ? Number(next) : next, { quiet: false }) }));
  };

  const colour = (label, path) => {
    const value = get(path) ?? base(path);
    const picker = h("input", { type: "color", value: /^#[0-9a-f]{6}$/i.test(value || "") ? value : "#ffffff",
      oninput: () => { hex.value = picker.value; swatch.style.background = picker.value; set(path, picker.value); } });
    const swatch = h("span.colour-swatch", { style: { background: value || "transparent" }, onclick: () => picker.click() });
    const hex = ui.input({ value: get(path) || "", placeholder: base(path) || "none", mono: true, key: path.join("."),
      onInput: (text) => { if (/^#[0-9a-f]{6}$/i.test(text)) { picker.value = text; swatch.style.background = text; set(path, text); } else if (!text) set(path, null); } });
    return row(label, path, h("div.colour-field", {}, swatch, picker, hex));
  };

  const paletteView = () => {
    const colours = get(["palette"]) ?? base(["palette"]) ?? [];
    const list = Array.isArray(colours) ? colours : [];
    const write = (next) => set(["palette"], next, { quiet: false });
    const chips = list.map((value, index) => {
      const picker = h("input", { type: "color", value, oninput: () => { chip.style.background = picker.value; const next = [...list]; next[index] = picker.value; set(["palette"], next); } });
      const chip = h("div.palette-chip", { style: { background: value }, title: `${value} — click to change`, onclick: () => picker.click() }, picker,
        h("button.palette-remove", { type: "button", title: "Remove", onclick: (event) => { event.stopPropagation(); write(list.filter((_, i) => i !== index)); } }, icon("close")));
      return chip;
    });
    const tones = studio.info?.tones || [];
    return h("div.palette-block", {},
      h("div.palette-chips", {}, chips,
        h("button.palette-add", { type: "button", title: "Add a colour", onclick: () => write([...list, "#888888"]) }, icon("plus"))),
      h("div.row", {},
        h("div.fixed", {}, ui.button("Named palettes", (event) => menu(event.currentTarget, Object.entries(catalog.palettes).map(([name, values]) => ({
          label: name, hint: values.join(" "), run: () => write([...values]),
        }))), { kind: "ghost", small: true, icon: "palette" })),
        get(["palette"]) !== undefined ? h("div.fixed", {}, ui.button("The base's", () => set(["palette"], null, { quiet: false }), { kind: "ghost", small: true, icon: "undo" })) : null),
      tones.length ? h("div.tones", { title: "The tones blocks are drawn in: fill and outline" },
        tones.map((tone) => h("span.tone", { style: { background: tone.fill, borderColor: tone.stroke, color: tone.stroke } }, "Aa"))) : null);
  };

  const section = (title, ...children) => h("div.section.theme-section", {}, h("div.section-title", {}, title), ...children);
  // The folder's figures and decks, and which of them are drawn in this theme: kept
  // across redraws of the form, and asked for again when documents come and go.
  let uses = themeUses(studio);
  studio.workspace.on?.("documents", () => { if (form.isConnected) { uses = themeUses(studio); renderForm(); } });

  const renderForm = () => keepFocus(form, () => {
    const t = theme();
    const rule = get(["tones", "rule"]) ?? base(["tones", "rule"]) ?? "tinted";
    const sketch = t.sketch ?? base(["sketch"]);
    clear(form,
      section("Theme",
        h("div", {}, ui.field("Name", ui.input({ value: t.name || "", mono: true, key: "name", onInput: (value) => set(["name"], value || null) }), { hint: "how figures and decks name it" })),
        ui.field("Starts from", ui.select({ value: t.base || "paper", options: catalog.bases, onChange: (value) => set(["base"], value, { quiet: false }) })),
        ui.field("Description", ui.input({ value: t.description || "", key: "description", placeholder: "What it is for", onInput: (value) => set(["description"], value || null) }))),
      section("Use this theme in", uses),
      section("Colour",
        h("div.setting-group-label", {}, "Palette", h("span.hint", {}, "the tones blocks are drawn in, in order")),
        paletteView(),
        choice("Tones", ["tones", "rule"], catalog.tones, { labels: { tinted: "Tinted", solid: "Solid", "accent-then-grey": "Accent, then grey", greys: "Greys" } }),
        rule === "tinted" ? [slider("Fill lightness", ["tones", "fill_lightness"], { min: 0.8, max: 0.99 }), slider("Fill colour", ["tones", "fill_chroma"], { min: 0, max: 0.15 }),
          slider("Outline darkness", ["tones", "stroke_lightness"], { min: 0.2, max: 0.75 }), slider("Outline colour", ["tones", "stroke_chroma"], { min: 0, max: 0.25 })] : null,
        h("div.setting-group-label", {}, "Page"),
        Object.keys(effective().page || PAGE_NAMES).map((key) => colour(PAGE_NAMES[key] || key, ["page", key]))),
      section("Type",
        row("Font", ["font"], ui.combo({ value: t.font || "", options: catalog.fonts, placeholder: effective().font || "", key: "font", onChange: (value) => set(["font"], value || null) })),
        length("Size", ["type", "size"], { step: 0.5 }),
        choice("Labels", ["type", "label_weight"], WEIGHTS),
        choice("Titles", ["type", "title_weight"], WEIGHTS),
        number("Line height", ["type", "line_height"], { step: 0.05, min: 0.8, max: 2 }),
        number("Letter spacing", ["type", "tracking"], { step: 0.01 }),
        choice("Titles set", ["type", "title_transform"], catalog.choices.title_transform || ["none", "upper"], { segmented: true, labels: { none: "As written", upper: "UPPER" } })),
      section("Lines & shapes",
        length("Outlines", ["style", "stroke_width"], { step: 0.05 }),
        length("Connectors", ["style", "connector_width"], { step: 0.05 }),
        length("Corners", ["style", "corner_radius"], { step: 0.5 }),
        row("Arrowheads", ["style", "arrow_shape"], h("div.arrow-choices", {}, (catalog.choices.arrow_shape || []).map((shape) => {
          const current = get(["style", "arrow_shape"]) ?? base(["style", "arrow_shape"]);
          return h(`button.arrow-choice${shape === current ? ".on" : ""}`, { type: "button", title: shape, onclick: () => set(["style", "arrow_shape"], shape, { quiet: false }) },
            arrowIcon(shape));
        }))),
        choice("Groups", ["style", "container_style"], catalog.choices.container_style || []),
        length("Group corners", ["style", "container_radius"], { step: 0.5 }),
        choice("Shadows", ["style", "shadow_style"], catalog.choices.shadow_style || []),
        slider("Shadow depth", ["style", "shadow_opacity"], { min: 0, max: 0.5 })),
      section("Space",
        length("Between parts", ["style", "gap"], { step: 1 }),
        length("Close together", ["style", "compact_gap"], { step: 0.5 }),
        length("Inside, across", ["style", "padding_x"], { step: 0.5 }),
        length("Inside, down", ["style", "padding_y"], { step: 0.5 }),
        length("Inside groups", ["style", "group_padding"], { step: 1 })),
      section("Drawing",
        choice("Lines", ["conventions", "lines"], catalog.conventions.lines || [], { segmented: true, labels: { orthogonal: "Right angles", straight: "Straight" } }),
        choice("Branches", ["conventions", "branch"], catalog.conventions.branch || [], { segmented: true, labels: { plain: "Plain", dot: "Dot" } }),
        choice("Merges", ["conventions", "merge"], catalog.conventions.merge || []),
        row("By hand", ["sketch"], ui.toggle({ value: Boolean(sketch), label: sketch ? "Drawn as if by hand" : "Ruled", onChange: (on) => set(["sketch"], on ? { roughness: 0.4 } : null, { quiet: false }) })),
        sketch ? slider("Roughness", ["sketch", "roughness"], { min: 0, max: 1.5, step: 0.05 }) : null),
      h("details.more.theme-more", {}, h("summary", {}, icon("chevron"), "Every other setting"),
        h("div.inner", {}, Object.entries(effective().style || {}).filter(([key]) => !SHOWN.has(key) && key !== "widths").map(([key, value]) =>
          typeof value === "string" && /pt$|mm$/.test(value) ? length(key.replace(/_/g, " "), ["style", key], { unit: value.endsWith("mm") ? "mm" : "pt" })
            : typeof value === "boolean" ? row(key.replace(/_/g, " "), ["style", key], ui.toggle({ value: get(["style", key]) ?? value, onChange: (on) => set(["style", key], on, { quiet: false }) }))
              : typeof value === "number" ? number(key.replace(/_/g, " "), ["style", key])
                : row(key.replace(/_/g, " "), ["style", key], ui.input({ value: get(["style", key]) ?? "", placeholder: String(value ?? ""), key: `style.${key}`, onInput: (text) => set(["style", key], text || null) }))))));
  });

  // -- the samples --
  const renderStage = () => {
    const figures = specimen.name === "figures";
    const cards = pages.map((page) => h(`figure.sample${page.stale ? ".stale" : ""}${figures ? "" : ".slide"}`, {},
      page.svg ? picture(page.svg, page.hash, { natural: figures }) : h("div.sample-wait", {}, h("div.spinner")),
      h("figcaption", {}, page.label)));
    clear(stage, h(`div.samples${specimen.name === "figures" ? "" : ".slides"}`, {}, cards.length ? cards : h("div.empty", {}, h("div.spinner"))));
    clear(note, messages.filter((m) => m.severity !== "note").map((message) => h(`div.message.${message.severity}`, {}, icon(message.severity === "error" ? "error" : "warning"), h("div", {}, message.text))));
  };

  // -- what to show it on --
  const showOn = h("div.show-on");
  const renderShowOn = () => {
    const decks = studio.workspace.documents.filter((item) => item.kind === "deck");
    const options = [...catalog.specimens.map((item) => ({ value: item.name, label: item.title })),
      ...(catalog.specimens.some((item) => item.name === "slides") ? decks.map((item) => ({ value: `deck:${item.file}`, label: item.file.split("/").pop() })) : [])];
    const value = specimen.deck ? `deck:${specimen.deck}` : specimen.name;
    clear(showOn, h("span.show-on-label", {}, "Show on"), ui.segmented({ value, options, onChange: (next) => {
      specimen = next.startsWith("deck:") ? { name: "slides", deck: next.slice(5) } : { name: next };
      pages = [];
      renderStage();
      studio.requestDraw(0);
    } }));
  };
  studio.tools.append(h("span.docbar-title", {}, icon("theme"), "Theme"), h("span.sep"), showOn);
  studio.actions.append(ui.button("Full theme file", () => studio.exportFiles(["yaml"]), { kind: "ghost", icon: "export", title: "Write every setting, the base's included, to build/" }));
  studio.workspace.on("documents", renderShowOn);
  renderShowOn();

  studio.on("drawn", (result) => {
    if (result.pages.length || !result.unfinished) pages = result.pages;
    messages = result.messages || [];
    const key = JSON.stringify(studio.info?.effective || {}) + JSON.stringify(studio.info?.tones || []);
    if (key !== effectiveKey) { effectiveKey = key; renderForm(); }
    renderStage();
  });
  studio.on("change", ({ quiet }) => { if (!quiet) renderForm(); });
  studio.reveal = () => {};
  studio.commands = () => [
    { icon: "palette", label: "Use a named palette…", run: () => form.querySelector(".palette-block .btn")?.click() },
    ...catalog.specimens.map((item) => ({ icon: "eye", label: `Show on ${item.title.toLowerCase()}`, run: () => { specimen = { name: item.name }; renderShowOn(); studio.requestDraw(0); } })),
  ];
  renderForm();
  renderStage();
}

const SHOWN = new Set(["stroke_width", "connector_width", "corner_radius", "arrow_shape", "container_style", "container_radius",
  "shadow_style", "shadow_opacity", "gap", "compact_gap", "padding_x", "padding_y", "group_padding"]);

function arrowIcon(shape) {
  const node = icon("right");
  node.innerHTML = "";
  const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
  line.setAttribute("d", "M1 8h8");
  const head = document.createElementNS("http://www.w3.org/2000/svg", "path");
  head.setAttribute("d", ARROWS[shape] || ARROWS.triangle);
  head.setAttribute("transform", "translate(3 0)");
  if (shape !== "open") head.setAttribute("fill", "currentColor");
  node.append(line, head);
  node.setAttribute("viewBox", "0 0 18 16");
  return node;
}
