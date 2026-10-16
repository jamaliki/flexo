// The figure editor's Design bar, as a deck's (flexo-talk's designbar.js): one low row under
// the toolbar of pop-up buttons, each naming what is in use -- Theme (a grid of the figure
// drawn in each theme), Colours, Font, Page Size, Sizes -- and More (panel letters,
// Customise…). Only in an open menu, and only a theme or a palette, is what the pointer is over
// shown on the figure as it would be; chosen, it is one step. The figure's inspector keeps what
// is its parts' own (parts.js: `designBar`, the settings it leaves to the bar).

import { h, clear, icon, themesFor, themeName, suggestedFonts } from "/static/studio/studio.js";
import { ribbonBar, ribbonSep, pull, drop, closeDrop, dropOpen, redrawDrop, previewer, gallery } from "/static/studio/ribbon.js";
import { painted } from "/static/kinds/figure/parts.js";

// The figure's settings the bar holds: the inspector leaves them to it.
export const BAR_FIELDS = ["figure.style", "figure.palette", "figure.page", "figure.width", "figure.height", "figure.font",
  "figure.panel_labels", "figure.spacing", "figure.shape_padding", "figure.line_width", "figure.head_size"];
const SIZED = ["figure.spacing", "figure.shape_padding", "figure.line_width", "figure.head_size"];
// Shown open from one visit to the next, as a deck's is.
const KEPT = "flexo-figure-design-bar";

export function figureBar(host) {
  const { studio, figure } = host;
  const catalog = studio.catalog.editor;
  const fieldOf = (key) => catalog.figure_fields.find((field) => field.key === key);
  const settings = () => figure.model?.figure || {};
  const node = ribbonBar("Design");
  let built = false, open = false;
  const keyOf = (...parts) => JSON.stringify(parts);
  // A design chosen: one step, as the inspector's field would make it. A choice from a menu of
  // them closes the menu.
  const choose = (values, { close = true } = {}) => {
    if (close) closeDrop(true);
    if (!figure.model || Object.entries(values).every(([key, value]) => (settings()[key.replace(/^figure\./, "")] ?? null) === value)) return;
    previews.hold();
    figure.update({ type: "figure" }, values);
  };

  // -- the live preview: the figure as the design pointed at would draw it --
  const ask = async (variants) => {
    if (!variants.length) return [];
    const found = await studio.api("/api/act", { file: studio.file, document: studio.doc, action: { do: "previews", variants } });
    return found?.previews || [];
  };
  const previews = previewer({ target: () => host.page(), keyOf: (variant) => keyOf(variant, studio.doc?.text), draw: async (variant) => (await ask([variant]))[0] });
  const shows = (element, variant) => {
    element.addEventListener("pointerenter", () => previews.show(variant));
    element.addEventListener("focus", () => { if (element.matches(":focus-visible")) previews.show(variant); });
    return element;
  };
  const unshown = (element) => {
    element.addEventListener("pointerleave", () => previews.show(null));
    element.addEventListener("focusout", (event) => { if (!element.contains(event.relatedTarget)) previews.show(null); });
    return element;
  };

  // -- the themes --
  const themeOf = () => settings().style || "paper";
  // (What a theme's thumbnail shows: the figure, all but its theme.)
  const drawnFrom = () => { const model = figure.model; return model ? keyOf({ ...model, figure: { ...model.figure, style: undefined } }) : studio.doc?.text; };
  const themes = gallery({
    label: "Themes",
    name: (item) => themeName(item.card),
    current: () => themeOf(),
    aspect: () => host.aspect(),
    card: (item) => h("span.ribbon-card", { style: { background: item.card.canvas || "#fff", color: item.card.ink || "#222" } },
      h("span.theme-aa", { style: { fontFamily: item.card.font ? `"${item.card.font}", system-ui` : "" } }, "Aa"),
      h("span.theme-tones", {}, [...new Set((item.card.colours || []).map((colour) => String(colour).toLowerCase()))].slice(0, 4).map((colour) => h("span", { style: { background: colour } })))),
    version: (item) => keyOf(item.value, drawnFrom()),
    thumbs: (items) => ask(items.map((item) => ({ "figure.style": item.value === "paper" ? null : item.value }))),
    pick: (item) => { if (!item.card.problem) choose({ "figure.style": item.value === "paper" ? null : item.value }); },
    preview: (item) => previews.show(item && !item.card.problem ? { "figure.style": item.value === "paper" ? null : item.value } : null),
  });
  let cards = [];
  const loadThemes = async () => {
    try { cards = await themesFor(studio, { fresh: true }); } catch { return; }
    const named = cards.some((card) => card.value === themeOf()) ? [] : [{ value: themeOf(), title: themeOf(), source: "folder" }];
    themes.set([...named, ...cards].map((card) => ({ value: card.value, card })));
    themes.reveal();
    faces();
  };
  const unpreview = () => previews.show(null);
  const themePull = pull({ label: "Theme", title: "Theme", panel: () => [themes.node], className: "theme-pull",
    onOpen: () => { loadThemes(); requestAnimationFrame(() => themes.reveal()); }, onClose: unpreview });
  const cardOf = () => cards.find((card) => card.value === themeOf());
  const chip = (card) => h("span.ribbon-chip", { style: { background: card?.canvas || "#fff" } },
    [...new Set((card?.colours || []).map((colour) => String(colour).toLowerCase()))].slice(0, 3).map((colour) => h("i", { style: { background: colour } })));

  // -- the pull-downs --
  const strip = (colours) => h("span.palette-strip", {}, (colours || []).slice(0, 5).map((colour) => h("span", { style: { background: colour } })));
  const paletteField = fieldOf("figure.palette");
  const paletteNow = () => settings().palette ?? paletteField?.default ?? "default";
  // (The theme's own: each tone's colour, as its chips are painted -- parts.js.)
  const coloursOf = (name) => (name === paletteField?.default ? (studio.info?.tones?.colours || []).map(painted) : paletteField?.colours?.[name] || []);
  const colours = pull({ label: "Colours", title: "Colours", onClose: unpreview, panel: () => {
    const now = paletteNow();
    return [h("div.drop-title", {}, "Palette"), unshown(h("div.palette-choices", { role: "group", "aria-label": "Palette" }, (paletteField?.options || []).map((name) => {
      const variant = { "figure.palette": name === paletteField.default ? null : name };
      return shows(h(`button.palette-choice${name === now ? ".on" : ""}`, { type: "button", "aria-pressed": String(name === now), onclick: () => choose(variant) },
        strip(coloursOf(name)), h("span", {}, name === paletteField.default ? "Theme’s Own" : name)), variant);
    })))];
  } });
  const fontNow = () => settings().font || "";
  const font = pull({ label: "Font", title: "Font", panel: () => {
    const now = fontNow();
    const offered = ["", ...suggestedFonts(catalog.fonts || studio.catalog.fonts || []).filter((name) => name !== "Helvetica Neue")];
    if (now && !offered.includes(now)) offered.push(now);
    return [h("div.drop-title", {}, "Font"), h("div.drop-choices", { role: "group", "aria-label": "Font" }, offered.map((name) =>
      h(`button.drop-choice${name === now ? ".on" : ""}`, { type: "button", "aria-pressed": String(name === now), onclick: () => choose({ "figure.font": name || null }) },
        h("span.drop-sample", { style: { fontFamily: name ? `"${name}", var(--font)` : "inherit" } }, "Aa"), h("span.drop-name", { style: { fontFamily: name ? `"${name}", var(--font)` : "inherit" } }, name || "Theme’s")))),
    h("div.drop-title", {}, "Custom"), h("div.drop-body", {}, figure.figureField("figure.font"))];
  } });
  const page = pull({ label: "Page Size", title: "Page Size", panel: () =>
    [h("div.drop-body.drop-page", {}, ["figure.page", "figure.width", "figure.height"].map((key) => figure.figureField(key)))] });
  const lettersField = fieldOf("figure.panel_labels");
  const lettersPanel = () => {
    const now = settings().panel_labels ?? lettersField?.default;
    return [h("div.drop-title", {}, "Panel Letters"), h("div.drop-choices", { role: "group", "aria-label": "Panel Letters" }, (lettersField?.options || []).map((option) =>
      h(`button.drop-choice${option === now ? ".on" : ""}`, { type: "button", "aria-pressed": String(option === now), onclick: () => choose({ "figure.panel_labels": option === lettersField.default ? null : option }) },
        h("span.drop-sample.letters", {}, String(lettersField.labels?.[option] ?? option).split(",")[0]), h("span.drop-name", {}, lettersField.labels?.[option] ?? option))))];
  };
  const sizes = pull({ label: "Sizes", title: "Sizes", panel: () => [h("div.drop-title", {}, "Sizes"), h("div.drop-body", {}, SIZED.map((key) => figure.figureField(key)))] });
  // More: the panels' letters, a panel of its own from here, and the theme's file -- made from
  // it (Customise…), or opened (Edit Theme).
  const more = pull({ label: "More", title: "More", panel: () => {
    const file = /\.(ya?ml|json)$/i.test(themeOf());
    const row = (glyph, label, run) => h("button.drop-choice.drop-command", { type: "button", onclick: run }, icon(glyph), h("span.drop-name", {}, label));
    return [h("div.drop-choices", { role: "group", "aria-label": "More" },
      row("panel", "Panel Letters", () => drop(more, lettersPanel)),
      h("div.drop-sep"),
      row(file ? "external" : "pencil", file ? "Edit Theme" : "Customise Theme…", () => {
        closeDrop();
        host.customise(themeOf(), (value) => figure.update({ type: "figure" }, { "figure.style": value }));
      }))];
  } });

  // -- drawn --
  // What each button shows: what is in use, named where it fits.
  const faces = () => {
    if (!built) return;
    const card = cardOf(), named = card ? themeName(card) : themeOf();
    themePull.show({ face: chip(card), text: named, title: `Theme: ${named}` });
    const palette = paletteNow();
    colours.show({ face: strip(coloursOf(palette)), text: "", title: `Colours: ${palette === paletteField?.default ? "Theme’s Own" : palette}` });
    font.show({ text: h("span.ribbon-font", { style: { fontFamily: fontNow() ? `"${fontNow()}", var(--font)` : "" } }, fontNow() || "Theme’s"), title: `Font: ${fontNow() || "Theme’s"}` });
    const width = settings().width ?? fieldOf("figure.width")?.default;
    const sized = `${fieldOf("figure.width")?.labels?.[width] ?? width}${settings().height ? ` × ${settings().height}` : ""}`;
    page.show({ text: sized, title: `Page Size: ${sized}` });
  };
  function build() {
    if (built) return;
    built = true;
    clear(node, themePull, colours, font, ribbonSep(), page, sizes, ribbonSep(), more);
    loadThemes();
  }
  let later = 0;
  function refresh() {
    if (!open || !figure.model) return;
    faces();
    themes.mark();
    clearTimeout(later);
    later = setTimeout(() => themes.refresh(), 800);
    if (dropOpen()) redrawDrop();
  }
  studio.on("change", () => refresh());
  studio.on("drawn", () => { previews.drawn(); refresh(); });
  document.addEventListener("keydown", (event) => {
    if (!studio.active || event.defaultPrevented || document.querySelector(".scrim, .present")) return;
    const mod = event.metaKey || event.ctrlKey;
    if (!mod || !event.shiftKey || event.altKey || event.code !== "KeyD") return;
    event.preventDefault();
    event.stopImmediatePropagation();
    toggle();
  }, true);

  function toggle(on = !open, { remember = true } = {}) {
    if (on === open) return open;
    open = on;
    if (on) build();
    node.hidden = !on;
    host.root().classList.toggle("designing", on);
    if (!on) { closeDrop(); previews.show(null); previews.drop(); }
    if (remember) { try { localStorage.setItem(KEPT, on ? "1" : "0"); } catch { /* a private window */ } }
    if (on) { refresh(); themes.refresh(); requestAnimationFrame(() => themes.reveal()); }
    host.shown?.(on);
    // (Told, so the Mac app's View menu names what it will do now: Hide Design.)
    studio.emit("status");
    return open;
  }
  return {
    node,
    get open() { return open; },
    toggle,
    start() {
      host.root().prepend(node);
      let kept = "0";
      try { kept = localStorage.getItem(KEPT) || "0"; } catch { /* a private window */ }
      if (kept === "1") toggle(true, { remember: false });
    },
    command: () => ({ icon: "palette", label: open ? "Hide Design" : "Show Design", keys: "⇧⌘D", run: () => toggle() }),
  };
}
