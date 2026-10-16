// The figure editor's Design bar, as a deck's (flexo-talk's designbar.js) and PowerPoint's
// Design tab: across the window under the toolbar, the figure drawn in each theme, and beside
// it its colours, font, page, panel letters and sizes. A theme, a palette or a font pointed at
// is shown on the figure as it would be; chosen, it is one step. The figure's inspector keeps
// what is its parts' own (parts.js: `designBar`, the settings it leaves to the bar).

import { h, clear, icon, themesFor, themeName, suggestedFonts } from "/static/studio/studio.js";
import { ribbonBar, ribbonSep, ribbonStack, pull, closeDrop, dropOpen, redrawDrop, previewer, gallery } from "/static/studio/ribbon.js";
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
  // A design chosen: one step, as the inspector's field would make it.
  const choose = (values) => {
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
  const loadThemes = async () => {
    let cards = [];
    try { cards = await themesFor(studio, { fresh: true }); } catch { return; }
    const named = cards.some((card) => card.value === themeOf()) ? [] : [{ value: themeOf(), title: themeOf(), source: "folder" }];
    themes.set([...named, ...cards].map((card) => ({ value: card.value, card })));
    themes.reveal();
  };
  const themeButton = h("button.btn.ghost.small.ribbon-button", { type: "button" });
  const renderThemeButton = () => {
    const file = /\.(ya?ml|json)$/i.test(themeOf());
    clear(themeButton, icon(file ? "external" : "pencil"), h("span.btn-label", {}, file ? "Edit Theme" : "Customise…"));
    themeButton.title = file ? "Edit Theme" : "Customise Theme…";
    themeButton.onclick = () => { closeDrop(); host.customise(themeOf(), (value) => figure.update({ type: "figure" }, { "figure.style": value })); };
  };

  // -- the pull-downs --
  const strip = (colours) => h("span.palette-strip", {}, (colours || []).slice(0, 5).map((colour) => h("span", { style: { background: colour } })));
  const paletteField = fieldOf("figure.palette");
  const paletteNow = () => settings().palette ?? paletteField?.default ?? "default";
  // (The theme's own: each tone's colour, as its chips are painted -- parts.js.)
  const coloursOf = (name) => (name === paletteField?.default ? (studio.info?.tones?.colours || []).map(painted) : paletteField?.colours?.[name] || []);
  const colours = pull({ label: "Colours", title: "Colours", panel: () => {
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
    return [h("div.drop-title", {}, "Font"), unshown(h("div.drop-choices", { role: "group", "aria-label": "Font" }, offered.map((name) => {
      const variant = { "figure.font": name || null };
      return shows(h(`button.drop-choice${name === now ? ".on" : ""}`, { type: "button", "aria-pressed": String(name === now), onclick: () => choose(variant) },
        h("span.drop-sample", { style: { fontFamily: name ? `"${name}", var(--font)` : "inherit" } }, "Aa"), h("span.drop-name", { style: { fontFamily: name ? `"${name}", var(--font)` : "inherit" } }, name || "Theme’s")), variant);
    }))), h("div.drop-title", {}, "Custom"), h("div.drop-body", {}, figure.figureField("figure.font"))];
  } });
  const page = pull({ label: "Page Size", title: "Page Size", face: icon("slide"), panel: () =>
    [h("div.drop-body.drop-page", {}, ["figure.page", "figure.width", "figure.height"].map((key) => figure.figureField(key)))] });
  const lettersField = fieldOf("figure.panel_labels");
  const letters = pull({ label: "Panel Letters", title: "Panel Letters", panel: () => {
    const now = settings().panel_labels ?? lettersField?.default;
    return [h("div.drop-title", {}, "Panel Letters"), h("div.drop-choices", { role: "group", "aria-label": "Panel Letters" }, (lettersField?.options || []).map((option) =>
      h(`button.drop-choice${option === now ? ".on" : ""}`, { type: "button", "aria-pressed": String(option === now), onclick: () => choose({ "figure.panel_labels": option === lettersField.default ? null : option }) },
        h("span.drop-sample.letters", {}, String(lettersField.labels?.[option] ?? option).split(",")[0]), h("span.drop-name", {}, lettersField.labels?.[option] ?? option))))];
  } });
  const sizes = pull({ label: "Sizes", title: "Sizes", face: icon("type"), panel: () => [h("div.drop-title", {}, "Sizes"), h("div.drop-body", {}, SIZED.map((key) => figure.figureField(key)))] });

  // -- drawn --
  const faces = () => {
    colours.setFace(strip(coloursOf(paletteNow())));
    font.setFace(h("span.ribbon-aa", { style: { fontFamily: fontNow() ? `"${fontNow()}", var(--font)` : "" } }, "Aa"));
    font.title = `Font: ${fontNow() || "Theme’s"}`;
    const now = settings().panel_labels ?? lettersField?.default;
    letters.setFace(h("span.ribbon-aa", {}, String(lettersField?.labels?.[now] ?? now ?? "a").split(",")[0]));
    const width = settings().width ?? fieldOf("figure.width")?.default;
    page.title = `Page Size: ${fieldOf("figure.width")?.labels?.[width] ?? width}${settings().height ? ` × ${settings().height}` : ""}`;
  };
  function build() {
    if (built) return;
    built = true;
    clear(node, themes.node, h("div.ribbon-stack.ribbon-themes", {}, themeButton), ribbonSep(),
      ribbonStack(colours, font), ribbonStack(page, letters), ribbonSep(), ribbonStack(sizes));
    loadThemes();
  }
  let later = 0;
  function refresh() {
    if (!open || !figure.model) return;
    faces();
    renderThemeButton();
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
