// The figure editor: the figure's file on the left, the figure drawn on the right.
// Its parts are listed in an outline; choosing one -- there or in the drawing --
// marks it and finds it in the file.

import { h, clear, icon, ui, menu } from "/static/studio/studio.js";

const LINE = 12.5 * 1.6;

export function mount(studio, main) {
  document.head.append(h("link", { rel: "stylesheet", href: "/static/kinds/figure/editor.css" }));

  let tab = "source";
  let selected = null;
  let zoom = null;             // null: fit to the stage
  let outlineData = null;
  let messages = [];

  // -- source --
  const gutter = h("div.code-gutter");
  const area = h("textarea.code-area.scroll-thin", { spellcheck: false, wrap: "off" });
  area.value = studio.doc.text;
  area.addEventListener("input", () => { numbers(); studio.change((doc) => { doc.text = area.value; }, { merge: "text", quiet: true }); });
  area.addEventListener("scroll", () => { gutter.scrollTop = area.scrollTop; });
  area.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    event.preventDefault();
    const { selectionStart: start, selectionEnd: end, value } = area;
    const lineStart = value.lastIndexOf("\n", start - 1) + 1;
    if (start === end && !event.shiftKey) area.setRangeText("  ", start, end, "end");
    else {
      const block = value.slice(lineStart, end);
      area.setRangeText(event.shiftKey ? block.replace(/^ {1,2}/gm, "") : block.replace(/^/gm, "  "), lineStart, end, "select");
    }
    area.dispatchEvent(new Event("input"));
  });
  const code = h("div.code", {}, gutter, area);

  const numbers = () => {
    const count = area.value.split("\n").length;
    const bad = new Set(messages.map((m) => /^line (\d+)$/.exec(m.where)?.[1]).filter(Boolean).map(Number));
    if (gutter.childElementCount !== count || bad.size || gutter.querySelector(".bad")) {
      clear(gutter, Array.from({ length: count }, (_, i) => h(`div${bad.has(i + 1) ? ".bad" : ""}`, {}, i + 1)));
    }
  };
  numbers();

  const find = (id) => {
    const lines = area.value.split("\n");
    const pattern = new RegExp(`^\\s*(-\\s*)?id:\\s*['"]?${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}['"]?\\s*$`);
    const index = lines.findIndex((line) => pattern.test(line));
    if (index < 0) return;
    const start = lines.slice(0, index).reduce((sum, line) => sum + line.length + 1, 0);
    if (tab !== "source") return;
    area.focus({ preventScroll: true });
    area.setSelectionRange(start, start + lines[index].length);
    area.scrollTop = Math.max(0, index * LINE - area.clientHeight / 3);
  };

  // -- outline --
  const outline = h("div.outline");
  const renderOutline = () => {
    if (!outlineData) { clear(outline, h("div.empty", {}, "The outline appears once the figure draws.")); return; }
    const item = (node) => {
      const glyph = node.type === "group" ? "layout" : node.kind === "text" ? "text" : "figure";
      const row = h(`div.outline-item${selected === node.id ? ".on" : ""}`, { onclick: () => select(node.id, true) },
        icon(glyph), h("span.id", {}, node.id), h("span.what", {}, [node.kind, node.label].filter(Boolean).join(" · ")));
      row.dataset.id = node.id;
      return node.children ? [row, h("div.outline-children", {}, node.children.map(item))] : [row];
    };
    clear(outline,
      h("div.outline-head", {}, "Parts"), item(outlineData.root),
      outlineData.edges.length ? h("div.outline-head", {}, `Edges · ${outlineData.edges.length}`) : null,
      outlineData.edges.map((edge) => {
        const row = h(`div.outline-item${selected === edge.id ? ".on" : ""}`, { onclick: () => select(edge.id, true) },
          icon("right"), h("span.id", {}, edge.source), h("span.what", {}, "→"), h("span.id", {}, edge.target),
          edge.label ? h("span.what", {}, edge.label) : null);
        row.dataset.id = edge.id;
        return row;
      }));
  };

  // -- the left panel --
  const body = h("div.panel-body.scroll-thin");
  const tabs = h("div.tabs");
  const showTab = () => {
    clear(tabs,
      h(`button.tab${tab === "source" ? ".on" : ""}`, { onclick: () => { tab = "source"; showTab(); } }, "Source"),
      h(`button.tab${tab === "outline" ? ".on" : ""}`, { onclick: () => { tab = "outline"; showTab(); } }, "Outline"));
    clear(body, tab === "source" ? code : outline);
    if (tab === "outline") renderOutline();
  };
  const left = h("section.panel.fig-left", {}, h("div.panel-head", {}, tabs), body);
  showTab();

  // -- the drawing --
  const page = h("div.fig-page");
  const mark = h("div.fig-mark", { hidden: true });
  const hover = h("div.fig-hover", { hidden: true });
  const stage = h("div.stage.fig-stage.scroll-thin", {}, h("div.fig-empty", {}, h("div.spinner"), "Drawing…"));
  const note = h("div.messages.fig-messages.scroll-thin");
  const zoomValue = h("span.value", {}, "");
  const zoomBar = h("div.zoom", {},
    ui.button("", () => setZoom((zoom ?? fitScale()) / 1.25), { kind: "ghost", icon: "minus", small: true, title: "Zoom out" }),
    zoomValue,
    ui.button("", () => setZoom((zoom ?? fitScale()) * 1.25), { kind: "ghost", icon: "plus", small: true, title: "Zoom in" }),
    ui.button("Fit", () => setZoom(null), { kind: "ghost", small: true }),
    ui.button("1:1", () => setZoom(1), { kind: "ghost", small: true }));
  const right = h("section.fig-right", {}, stage, note, zoomBar);

  const split = h("div.fig-split");
  split.addEventListener("pointerdown", (event) => {
    split.setPointerCapture(event.pointerId);
    split.classList.add("dragging");
    const move = (e) => root.style.setProperty("--left", `${Math.min(Math.max(260, e.clientX), innerWidth - 320)}px`);
    split.addEventListener("pointermove", move);
    split.addEventListener("pointerup", () => { split.classList.remove("dragging"); split.removeEventListener("pointermove", move); fitPage(); }, { once: true });
  });
  const root = h("div.fig", {}, left, split, right);
  clear(main, root);

  let natural = { width: 1, height: 1 };
  const fitScale = () => {
    const room = stage.getBoundingClientRect();
    return Math.min((room.width - 96) / natural.width, (room.height - 96) / natural.height, 3);
  };
  const setZoom = (value) => { zoom = value && Math.min(Math.max(value, 0.1), 8); fitPage(); };
  const fitPage = () => {
    const svg = page.querySelector("svg");
    if (!svg) return;
    const scale = zoom ?? fitScale();
    svg.style.width = `${natural.width * scale}px`;
    svg.style.height = `${natural.height * scale}px`;
    zoomValue.textContent = `${Math.round(scale * 100)}%`;
    placeMark();
  };
  new ResizeObserver(() => fitPage()).observe(stage);

  const box = (id) => {
    const svg = page.querySelector("svg");
    const target = svg && [...svg.querySelectorAll("[id]")].find((el) => el.id === id);
    if (!target) return null;
    const outer = page.getBoundingClientRect(), inner = target.getBoundingClientRect();
    return { left: inner.left - outer.left - 3, top: inner.top - outer.top - 3, width: inner.width + 6, height: inner.height + 6 };
  };
  const placeMark = () => {
    const where = selected && box(selected);
    mark.hidden = !where;
    if (where) Object.assign(mark.style, { left: `${where.left}px`, top: `${where.top}px`, width: `${where.width}px`, height: `${where.height}px` });
  };
  const select = (id, fromOutline = false) => {
    selected = id;
    placeMark();
    for (const row of outline.querySelectorAll(".outline-item")) row.classList.toggle("on", row.dataset.id === id);
    if (id) find(id);
    if (!fromOutline && tab === "outline") outline.querySelector(".outline-item.on")?.scrollIntoView({ block: "nearest" });
  };
  const entity = (target) => target.closest?.("[data-flexo-entity][id]");
  page.addEventListener("click", (event) => { const hit = entity(event.target); select(hit ? hit.id : null); });
  page.addEventListener("mousemove", (event) => {
    const hit = entity(event.target);
    const where = hit && box(hit.id);
    hover.hidden = !where;
    if (where) Object.assign(hover.style, { left: `${where.left}px`, top: `${where.top}px`, width: `${where.width}px`, height: `${where.height}px` });
  });
  page.addEventListener("mouseleave", () => { hover.hidden = true; });

  const showMessages = () => {
    clear(note, messages.map((message) => h(`div.message.${message.severity}${message.where ? ".link" : ""}`,
      { onclick: () => message.where && !message.where.startsWith("line ") && select(message.where) },
      icon(message.severity === "error" ? "error" : message.severity === "note" ? "info" : "warning"),
      h("div", {}, message.text, message.where ? h("div.where", {}, message.where) : null))));
    numbers();
  };

  studio.on("drawn", (result) => {
    messages = result.messages || [];
    showMessages();
    const drawn = result.pages[0];
    if (!drawn) {
      if (!page.querySelector("svg")) clear(stage, h("div.fig-empty", {}, icon("warning"), "Nothing to draw yet"));
      page.style.opacity = "0.45";
      return;
    }
    page.style.opacity = "";
    page.innerHTML = drawn.svg.replace(/^<\?xml[^>]*>\s*/, "");
    page.append(hover, mark);
    const svg = page.querySelector("svg");
    const view = svg.viewBox.baseVal;
    natural = view && view.width ? { width: view.width * 96 / 72, height: view.height * 96 / 72 } : { width: 600, height: 400 };
    svg.removeAttribute("width"); svg.removeAttribute("height");
    if (page.parentNode !== stage) clear(stage, page);
    outlineData = drawn.outline;
    if (tab === "outline") renderOutline();
    fitPage();
  });

  studio.on("change", ({ quiet }) => { if (!quiet && area.value !== studio.doc.text) { area.value = studio.doc.text; numbers(); } });

  const exportMenu = ui.button("Export", (event) => menu(event.currentTarget, [
    { icon: "export", label: "Editable SVG", hint: "Inkscape layers, live text", run: () => studio.exportFiles(["editable"]) },
    { icon: "export", label: "PDF", hint: "Embedded fonts", run: () => studio.exportFiles(["pdf"]) },
    { icon: "image", label: "PNG", run: () => studio.exportFiles(["png"]) },
    "-",
    { icon: "export", label: "Everything", run: () => studio.exportFiles(["editable", "portable", "pdf", "png"]) },
  ], { align: "end" }), { icon: "export", kind: "ghost" });
  studio.tools.append(exportMenu);
}
