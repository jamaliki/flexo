// The theme editor: samples drawn in a theme -- figures, slides, or a deck in the folder
// -- and its settings on the right, where a deck's inspector is, grouped as a designer
// thinks of them (colour, type, line, space). Only what differs from the base theme is
// written; every other setting shows the base's value, ready to change.

import { h, clear, icon, ui, menu, keepFocus, picture, themeName, themeUses } from "/static/studio/studio.js";

const WEIGHTS = [300, 400, 500, 600, 700, 800];
const PAGE_NAMES = {
  canvas: "Background", ink: "Text", muted: "Muted Text", connector: "Line", container_fill: "Group Fill",
  container_stroke: "Group Outline", neutral_fill: "Neutral Fill", neutral_stroke: "Neutral Outline",
  inset_fill: "Inset Fill", inset_stroke: "Inset Outline", shadow: "Shadow", residual: "Residual Line",
};
// A setting's name as a person reads it: "arrow_shape" is "Arrow Shape".
const titled = (text) => String(text).replace(/_/g, " ").replace(/(^|[\s-])([a-z])/g, (_, before, letter) => before + letter.toUpperCase());
const ARROW_NAMES = { triangle: "Triangle", stealth: "Stealth", latex: "LaTeX", open: "Open" };
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
  // Said in the history as the setting changed: "Change Arrow Shape".
  const NAMES = {
    sketch: "Hand-Drawn Style", base: "Base Theme", rule: "Tones", size: "Font Size", tracking: "Letter Spacing",
    title_transform: "Title Capitalisation", fill_chroma: "Fill Saturation", stroke_lightness: "Outline Lightness",
    stroke_chroma: "Outline Saturation", stroke_width: "Outline Width", connector_width: "Line Width",
    container_style: "Group Style", container_radius: "Group Corner Radius", gap: "Shape Spacing",
    compact_gap: "Compact Spacing", padding_x: "Horizontal Padding", padding_y: "Vertical Padding",
    lines: "Line Style", branch: "Branch Style", merge: "Merge Style",
  };
  const said = (path, value) => {
    const key = path[path.length - 1];
    const name = path[0] === "page" && PAGE_NAMES[key] ? `${PAGE_NAMES[key]} Colour` : NAMES[key] || titled(key);
    return value === null || value === undefined || value === "" ? `Reset ${name}` : `Change ${name}`;
  };
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
  }, { quiet: true, merge: path.join("."), label: said(path, value), ...options });

  // -- the panel --
  const form = h("div.theme-form.scroll-thin");
  const stage = h("div.stage.theme-stage.scroll-thin");
  const note = h("div.messages.theme-messages");
  const root = h("div.theme", {}, h("section.theme-right", {}, stage, note), h("section.panel.theme-panel", {}, form));
  clear(container, root);

  const row = (label, path, control, { hint } = {}) => {
    const changed = get(path) !== undefined;
    return h(`div.setting${changed ? ".changed" : ""}`, {},
      h("label.setting-label", {}, h("span.setting-dot", { title: changed ? "Differs from the base theme" : "" }), label, hint ? h("span.hint", {}, hint) : null),
      h("div.setting-control", {}, control),
      h("button.setting-reset", { type: "button", title: "Reset", disabled: !changed, onclick: () => { set(path, null, { quiet: false }); } }, icon("undo")));
  };

  const length = (label, path, { step = 0.25, unit = "pt", hint } = {}) => {
    const given = get(path);
    const shown = base(path);
    const parse = (text) => (text == null ? null : parseFloat(String(text)));
    return row(label, path, ui.number({ value: parse(given), placeholder: shown == null ? "None" : String(parse(shown)), step, key: path.join("."), unit,
      onChange: (value) => set(path, value === null ? null : `${value}${unit}`) }), { hint });
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
    const items = options.map((option) => ({ value: option, label: labels[option] ?? titled(option) }));
    return row(label, path, segmented
      ? ui.segmented({ value, options: items, onChange: (next) => set(path, next, { quiet: false }) })
      : ui.select({ value, options: items, onChange: (next) => set(path, WEIGHTS.includes(Number(next)) ? Number(next) : next, { quiet: false }) }));
  };

  const colour = (label, path) => {
    const value = get(path) ?? base(path);
    const picker = h("input", { type: "color", value: /^#[0-9a-f]{6}$/i.test(value || "") ? value : "#ffffff",
      oninput: () => { hex.value = picker.value; swatch.style.background = picker.value; swatch.classList.remove("none"); set(path, picker.value); } });
    // No colour is the hatched chip every "None" is drawn as.
    const swatch = h(`span.colour-swatch${value ? "" : ".none"}`, { style: { background: value || "" }, title: value || "None", onclick: () => picker.click() });
    const hex = ui.input({ value: get(path) || "", placeholder: base(path) || "None", mono: true, key: path.join("."),
      onInput: (text) => { if (/^#[0-9a-f]{6}$/i.test(text)) { picker.value = text; swatch.style.background = text; swatch.classList.remove("none"); set(path, text); } else if (!text) set(path, null); } });
    return row(label, path, h("div.colour-field", {}, swatch, picker, hex));
  };

  const paletteView = () => {
    const colours = get(["palette"]) ?? base(["palette"]) ?? [];
    const list = Array.isArray(colours) ? colours : [];
    const write = (next) => set(["palette"], next, { quiet: false });
    const chips = list.map((value, index) => {
      const picker = h("input", { type: "color", value, oninput: () => { chip.style.background = picker.value; const next = [...list]; next[index] = picker.value; set(["palette"], next); } });
      const chip = h("div.palette-chip", { style: { background: value }, title: `${value} — click to change`, onclick: () => picker.click() }, picker,
        h("button.palette-remove", { type: "button", title: "Remove colour", onclick: (event) => { event.stopPropagation(); write(list.filter((_, i) => i !== index)); } }, icon("close")));
      return chip;
    });
    const tones = studio.info?.tones || [];
    return h("div.palette-block", {},
      h("div.palette-chips", {}, chips,
        h("button.palette-add", { type: "button", title: "Add colour", onclick: () => write([...list, "#888888"]) }, icon("plus"))),
      h("div.row", {},
        h("div.fixed", {}, ui.button("Palettes…", (event) => menu(event.currentTarget, Object.entries(catalog.palettes).map(([name, values]) => ({
          label: name, hint: values.join(" "), run: () => write([...values]),
        }))), { kind: "ghost", small: true, icon: "palette" })),
        get(["palette"]) !== undefined ? h("div.fixed", {}, ui.button("Reset", () => set(["palette"], null, { quiet: false }), { kind: "ghost", small: true, icon: "undo" })) : null),
      // In rows of equal chips, never one left alone on a row of its own.
      tones.length ? h("div.tones", { title: "Fill and outline colours for shapes", style: { gridTemplateColumns: `repeat(${Math.ceil(tones.length / Math.ceil(tones.length / 10))}, minmax(0, 1fr))` } },
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
        h("div", {}, ui.field("Name", ui.input({ value: t.name || "", key: "name", onInput: (value) => set(["name"], value || null) }), { hint: "Figures and decks refer to the theme by this name" })),
        ui.field("Base Theme", ui.select({ value: t.base || "paper", options: catalog.bases.map((value) => ({ value, label: themeName({ value }) })), onChange: (value) => set(["base"], value, { quiet: false }) })),
        ui.field("Description", ui.input({ value: t.description || "", key: "description", placeholder: "What this theme is for", onInput: (value) => set(["description"], value || null) }))),
      section("Documents", uses),
      section("Colour",
        h("div.setting-group-label", {}, "Palette", h("span.hint", {}, "Colours for shapes, in order")),
        paletteView(),
        choice("Tones", ["tones", "rule"], catalog.tones, { labels: { tinted: "Tinted", solid: "Solid", "accent-then-grey": "Accent Then Grey", greys: "Greys" } }),
        rule === "tinted" ? [slider("Fill Lightness", ["tones", "fill_lightness"], { min: 0.8, max: 0.99 }), slider("Fill Saturation", ["tones", "fill_chroma"], { min: 0, max: 0.15 }),
          slider("Outline Lightness", ["tones", "stroke_lightness"], { min: 0.2, max: 0.75 }), slider("Outline Saturation", ["tones", "stroke_chroma"], { min: 0, max: 0.25 })] : null,
        h("div.setting-group-label", {}, "Page"),
        Object.keys(effective().page || PAGE_NAMES).map((key) => colour(PAGE_NAMES[key] || key, ["page", key]))),
      section("Type",
        row("Font", ["font"], ui.font({ value: t.font || "", options: catalog.fonts, placeholder: effective().font || "Default", key: "font", onChange: (value) => set(["font"], value || null, { quiet: false }) })),
        length("Font Size", ["type", "size"], { step: 0.5 }),
        choice("Label Weight", ["type", "label_weight"], WEIGHTS),
        choice("Title Weight", ["type", "title_weight"], WEIGHTS),
        number("Line Height", ["type", "line_height"], { step: 0.05, min: 0.8, max: 2 }),
        number("Letter Spacing", ["type", "tracking"], { step: 0.01 }),
        choice("Title Capitalisation", ["type", "title_transform"], catalog.choices.title_transform || ["none", "upper"], { segmented: true, labels: { none: "None", upper: "All Caps" } })),
      section("Lines & Shapes",
        length("Outline Width", ["style", "stroke_width"], { step: 0.05 }),
        length("Line Width", ["style", "connector_width"], { step: 0.05 }),
        length("Corner Radius", ["style", "corner_radius"], { step: 0.5 }),
        row("Arrow Shape", ["style", "arrow_shape"], h("div.arrow-choices", {}, (catalog.choices.arrow_shape || []).map((shape) => {
          const current = get(["style", "arrow_shape"]) ?? base(["style", "arrow_shape"]);
          return h(`button.arrow-choice${shape === current ? ".on" : ""}`, { type: "button", title: ARROW_NAMES[shape] || titled(shape), onclick: () => set(["style", "arrow_shape"], shape, { quiet: false }) },
            arrowIcon(shape));
        }))),
        choice("Group Style", ["style", "container_style"], catalog.choices.container_style || []),
        length("Group Corner Radius", ["style", "container_radius"], { step: 0.5 }),
        choice("Shadow Style", ["style", "shadow_style"], catalog.choices.shadow_style || []),
        slider("Shadow Opacity", ["style", "shadow_opacity"], { min: 0, max: 0.5 })),
      section("Spacing",
        length("Shape Spacing", ["style", "gap"], { step: 1 }),
        length("Compact Spacing", ["style", "compact_gap"], { step: 0.5 }),
        length("Horizontal Padding", ["style", "padding_x"], { step: 0.5 }),
        length("Vertical Padding", ["style", "padding_y"], { step: 0.5 }),
        length("Group Padding", ["style", "group_padding"], { step: 1 })),
      section("Drawing",
        choice("Line Style", ["conventions", "lines"], catalog.conventions.lines || [], { segmented: true, labels: { orthogonal: "Right Angles", straight: "Straight" } }),
        choice("Branch Style", ["conventions", "branch"], catalog.conventions.branch || [], { segmented: true, labels: { plain: "Plain", dot: "Dot" } }),
        choice("Merge Style", ["conventions", "merge"], catalog.conventions.merge || []),
        // Named once, by its row, as every switch in the panel is.
        row("Hand-Drawn Style", ["sketch"], ui.toggle({ value: Boolean(sketch), key: "sketch", onChange: (on) => set(["sketch"], on ? { roughness: 0.4 } : null, { quiet: false }) })),
        sketch ? slider("Roughness", ["sketch", "roughness"], { min: 0, max: 1.5, step: 0.05 }) : null),
      h("details.more.theme-more", {}, h("summary", {}, icon("chevron"), "Other Settings"),
        h("div.inner", {}, Object.entries(effective().style || {}).filter(([key]) => !SHOWN.has(key) && key !== "widths").map(([key, value]) =>
          typeof value === "string" && /pt$|mm$/.test(value) ? length(titled(key), ["style", key], { unit: value.endsWith("mm") ? "mm" : "pt" })
            : typeof value === "boolean" ? row(titled(key), ["style", key], ui.toggle({ value: get(["style", key]) ?? value, onChange: (on) => set(["style", key], on, { quiet: false }) }))
              : typeof value === "number" ? number(titled(key), ["style", key])
                : row(titled(key), ["style", key], ui.input({ value: get(["style", key]) ?? "", placeholder: String(value ?? ""), key: `style.${key}`, onInput: (text) => set(["style", key], text || null) }))))));
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
      ...(catalog.specimens.some((item) => item.name === "slides") ? decks.map((item) => ({ value: `deck:${item.file}`, label: item.file.split("/").pop().replace(/\.(ya?ml|json)$/i, "") })) : [])];
    const value = specimen.deck ? `deck:${specimen.deck}` : specimen.name;
    const onChange = (next) => {
      specimen = next.startsWith("deck:") ? { name: "slides", deck: next.slice(5) } : { name: next };
      pages = [];
      renderStage();
      studio.requestDraw(0);
    };
    // A few, side by side; more (a folder of decks), a pop-up, which keeps to its width.
    clear(showOn, h("span.show-on-label", {}, "Preview"), options.length > 3 ? ui.select({ value, options, onChange }) : ui.segmented({ value, options, onChange }));
  };
  studio.tools.append(h("span.docbar-title", {}, icon("theme"), "Theme"), h("span.sep"), showOn);
  studio.exports = [{ format: "yaml", label: "Full Theme…" }];
  studio.actions.append(ui.button("Export Full Theme…", () => studio.exportFiles(["yaml"]), { kind: "ghost", icon: "export", title: "Export the theme with every setting written out, including those it takes from its base theme" }));
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
    { icon: "palette", label: "Choose Palette…", run: () => form.querySelector(".palette-block .btn")?.click() },
    ...catalog.specimens.map((item) => ({ icon: "eye", label: `Preview ${item.title}`, run: () => { specimen = { name: item.name }; renderShowOn(); studio.requestDraw(0); } })),
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
