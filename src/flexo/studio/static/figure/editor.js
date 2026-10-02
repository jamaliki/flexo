// The figure editor: the figure drawn in the middle, its parts listed on the left,
// what is chosen on the right. Parts come from a palette, lines are drawn by
// choosing one part and then another, words are typed on the drawing, and parts
// are gathered into rows, columns, grids and modules (parts.js, shared with the
// deck editor, which edits figures on its slides the same way). Every edit is
// made by the server to the figure's own file (the Source tab), so the file stays
// the figure, comments and all, and anything the page offers no control for can
// be written there.

import { h, clear, icon, ui, menu, dialog, keepFocus, toast, themeField } from "/static/studio/studio.js";
import { figureParts, glyph, groupGlyph, plain, widenLines } from "/static/kinds/figure/parts.js";

const LINE = 12.5 * 1.6;

export function mount(studio, main) {
  if (!document.querySelector('link[href="/static/kinds/figure/editor.css"]')) {
    document.head.append(h("link", { rel: "stylesheet", href: "/static/kinds/figure/editor.css" }));
  }
  const catalog = studio.catalog.editor;
  const state = { tab: "parts", zoom: null, closed: new Set() };
  let messages = [];

  // -- the frame --
  const leftBody = h("div.panel-body.scroll-thin");
  const leftTabs = h("div.tabs");
  const left = h("section.panel.fig-left", {}, h("div.panel-head", {}, leftTabs), leftBody);
  const page = h("div.fig-page");
  const hover = h("div.fig-hover", { hidden: true });
  const marks = h("div.fig-marks");
  const stage = h("div.stage.fig-stage.scroll-thin", {}, h("div.fig-empty", {}, h("div.spinner"), "Drawing…"));
  const note = h("div.messages.fig-messages.scroll-thin");
  const hint = h("div.fig-hint", { hidden: true });
  const zoomValue = h("span.value", {}, "");
  const zoomBar = h("div.zoom", {},
    ui.button("", () => setZoom((state.zoom ?? fitScale()) / 1.25), { kind: "ghost", icon: "minus", small: true, title: "Zoom out" }),
    zoomValue,
    ui.button("", () => setZoom((state.zoom ?? fitScale()) * 1.25), { kind: "ghost", icon: "plus", small: true, title: "Zoom in" }),
    ui.button("Fit", () => setZoom(null), { kind: "ghost", small: true }),
    ui.button("1:1", () => setZoom(1), { kind: "ghost", small: true }));
  const center = h("section.fig-center", {}, stage, hint, note, zoomBar);
  const inspectorBody = h("div.panel-body.scroll-thin");
  const inspector = h("aside.panel.fig-inspector", {}, inspectorBody);
  const split = h("div.fig-split");
  const root = h("div.fig", {}, left, split, center, inspector);
  clear(main, root);
  split.addEventListener("pointerdown", (event) => {
    split.setPointerCapture(event.pointerId);
    split.classList.add("dragging");
    const move = (e) => root.style.setProperty("--left", `${Math.min(Math.max(200, e.clientX - root.getBoundingClientRect().left), 720)}px`);
    split.addEventListener("pointermove", move);
    split.addEventListener("pointerup", () => { split.classList.remove("dragging"); split.removeEventListener("pointermove", move); fitPage(); }, { once: true });
  });

  // -- the bar --
  const addButton = ui.button("Add", (event) => figure.addPalette(event.currentTarget), { icon: "plus", kind: "primary", title: "Add a part (A)" });
  const connectButton = ui.button("Connect", () => figure.toggleConnect(), { kind: "ghost", icon: "right", title: "Draw a line from one part to another (C)" });
  const gatherButton = ui.button("Group", (event) => figure.groupMenu(event.currentTarget), { kind: "ghost", icon: "layout", title: "Gather the chosen parts into a row, column, grid or module (G)" });
  const deleteButton = ui.button("", () => figure.remove(), { kind: "ghost", icon: "trash", title: "Delete (⌫)" });
  studio.tools.append(h("span.docbar-title", {}, icon("figure"), "Figure"), h("span.sep"), addButton, connectButton, gatherButton, deleteButton);
  studio.exports = [{ format: "pdf", label: "PDF" }, { format: "png", label: "PNG" }, { format: "editable", label: "Editable SVG" }];
  studio.actions.append(ui.button("Export", (event) => menu(event.currentTarget, [
    { icon: "export", label: "Editable SVG", hint: "Inkscape layers, live text", run: () => studio.exportFiles(["editable"]) },
    { icon: "export", label: "PDF", hint: "Embedded fonts", run: () => studio.exportFiles(["pdf"]) },
    { icon: "image", label: "PNG", run: () => studio.exportFiles(["png"]) },
    "-",
    { icon: "export", label: "Everything", run: () => studio.exportFiles(["editable", "portable", "pdf", "png"]) },
  ], { align: "end" }), { icon: "export", kind: "ghost" }));

  // -- the drawing's parts, edited --
  const elementOf = (id) => {
    const svg = page.querySelector("svg");
    return svg && [...svg.querySelectorAll("[id]")].find((el) => el.id === id);
  };
  function boxOf(id) {
    const target = elementOf(id);
    if (!target) return null;
    const outer = page.getBoundingClientRect(), inner = target.getBoundingClientRect();
    if (!inner.width && !inner.height) return null;
    return { left: inner.left - outer.left - 3, top: inner.top - outer.top - 3, width: inner.width + 6, height: inner.height + 6 };
  }
  const figure = figureParts({
    catalog,
    overlay: page,
    element: elementOf,
    idOf: (id) => id,
    box: boxOf,
    changed: () => { placeMarks(); renderOutline(); renderInspector(); renderBar(); showHint(); },
    settled: () => placeMarks(),
    reveal: (id) => {
      outlineBody.querySelector(`.tree-row[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "nearest" });
      if (state.tab === "source") find(id);
    },
    focus: (where) => studio.focus(where),
    chooseFile,
    themeField: (value, set) => themeField(studio, { value, onPick: set, onCustomise: (current) => customiseTheme(current, set) }),
    tones: () => studio.info?.tones,
    addAnchor: () => addButton,
    groupAnchor: () => gatherButton,
    // The server makes the edit to the file's words; if the file changed while it did
    // (someone typed, an agent wrote), it is made again on the file as it is now.
    run: async (action, { merge, label }) => {
      for (let attempt = 0; attempt < 3; attempt += 1) {
        const sent = studio.doc.text;
        const result = await studio.api("/api/act", { file: studio.file, document: studio.doc, action });
        if (studio.doc.text !== sent) continue;
        // A question asked of the figure (its parts, a structure's view) changes nothing.
        if (action.do === "structure-view" || action.do === "structure-settings") return result;
        studio.change((d) => ({ ...d, text: result.document.text }), { merge, label });
        // An edit made from the drawing is drawn at once: its parts are waiting to land.
        if (action.do !== "read" && action.do !== "update") studio.requestDraw?.(0);
        return result;
      }
      return null;
    },
  });

  function renderBar() {
    const chosen = figure.selected;
    deleteButton.disabled = !chosen.length || chosen.includes(figure.model?.root);
    connectButton.classList.toggle("on", Boolean(figure.connecting));
    gatherButton.disabled = !figure.model;
    addButton.disabled = !figure.model;
  }
  function showHint() {
    const words = figure.hint();
    hint.hidden = !words;
    stage.classList.toggle("connecting", Boolean(words));
    if (words) clear(hint, words);
  }

  // -- the drawing --
  let natural = { width: 1, height: 1 };
  const fitScale = () => {
    const room = stage.getBoundingClientRect();
    return Math.min((room.width - 96) / natural.width, (room.height - 96) / natural.height, 3);
  };
  const setZoom = (value) => { state.zoom = value && Math.min(Math.max(value, 0.1), 8); fitPage(); };
  function fitPage() {
    const svg = page.querySelector("svg");
    if (!svg) return;
    const scale = state.zoom ?? fitScale();
    svg.style.width = `${natural.width * scale}px`;
    svg.style.height = `${natural.height * scale}px`;
    zoomValue.textContent = `${Math.round(scale * 100)}%`;
    placeMarks();
    figure.placeInline();
  }
  new ResizeObserver(() => fitPage()).observe(stage);

  function placeMarks() {
    clear(marks, figure.markViews());
  }
  page.addEventListener("click", (event) => { if (!event.target.closest(".fig-inline")) figure.click(event); });
  page.addEventListener("pointerdown", (event) => { if (!event.target.closest(".fig-inline")) figure.pointerdown(event); });
  stage.addEventListener("click", (event) => { if (event.target === stage && !figure.connecting) figure.select([]); });
  page.addEventListener("dblclick", (event) => { if (!event.target.closest(".fig-inline")) figure.dblclick(event); });
  page.addEventListener("mousemove", (event) => {
    if (figure.dragging) return;
    const id = figure.idAt(event);
    const where = id && boxOf(id);
    hover.hidden = !where;
    if (where) Object.assign(hover.style, { left: `${where.left}px`, top: `${where.top}px`, width: `${where.width}px`, height: `${where.height}px` });
  });
  page.addEventListener("mouseleave", () => { hover.hidden = true; });

  // -- the outline --
  const outlineBody = h("div.tree");
  function renderOutline() {
    if (state.tab !== "parts") return;
    const found = figure.model;
    if (!found) { clear(outlineBody, h("div.empty", {}, "The parts appear once the file reads.")); return; }
    const chosen = figure.selected;
    const choose = (event, id) => {
      if (event.shiftKey || event.metaKey || event.ctrlKey) figure.select(chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id]);
      else figure.select([id]);
    };
    const row = (id, depth) => {
      const node = figure.nodeOf(id), group = figure.groupOf(id);
      const isRoot = id === found.root;
      const children = group ? group.children || [] : [];
      const open = !state.closed.has(id);
      const item = h(`div.tree-row${chosen.includes(id) ? ".on" : ""}${isRoot ? ".root" : ""}`, {
        draggable: isRoot ? "false" : "true", dataset: { id }, style: { paddingLeft: `${6 + depth * 14}px` },
        onclick: (event) => choose(event, id),
        ondblclick: () => (node ? figure.openInline(id) : null),
      },
      group && children.length ? h(`button.tree-caret${open ? ".open" : ""}`, { type: "button", onclick: (event) => {
        event.stopPropagation();
        if (open) state.closed.add(id); else state.closed.delete(id);
        renderOutline();
      } }, icon("chevron")) : h("span.tree-caret"),
      node ? glyph(node.kind || "block") : group ? glyph(groupGlyph(group)) : glyph("block"),
      h("span.tree-name", {}, isRoot ? "Figure" : figure.nameOf(id)),
      h("span.tree-id", {}, isRoot ? "" : id));
      outlineDrop(item, id, isRoot);
      if (!isRoot) outlineDrag(item, id);
      return [item, group && open ? children.map((child) => row(child, depth + 1)) : null];
    };
    const lines = [...found.edges, ...found.nets.map((net) => ({ ...net, net: true }))];
    clear(outlineBody,
      h("div.tree-head", {}, "Parts", h("span.count", {}, found.nodes.length)),
      figure.groupOf(found.root) ? row(found.root, 0) : null,
      h("div.tree-head", {}, "Lines", h("span.count", {}, lines.length)),
      lines.length ? lines.map((line) => h(`div.tree-row.line${chosen.includes(line.id) ? ".on" : ""}`, {
        dataset: { id: line.id }, onclick: () => figure.select([line.id]),
      }, h("span.tree-caret"), glyph(line.net ? "net" : "edge"),
      h("span.tree-name", {}, line.net
        ? `${figure.nameOf(figure.nodeOfRef(line.sources?.[0] || ""))} → ${(line.targets || []).map((t) => figure.nameOf(figure.nodeOfRef(t))).join(", ")}`
        : figure.nameOf(line.id)),
      line.label ? h("span.tree-id", {}, plain(line.label)) : null)) : h("div.empty.small", {}, "Choose a part, then Connect."));
  }

  let dragging = null;
  function outlineDrag(item, id) {
    item.addEventListener("dragstart", (event) => { dragging = id; item.classList.add("dragging"); event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("text/plain", id); });
    item.addEventListener("dragend", () => { dragging = null; item.classList.remove("dragging"); clearDrops(); });
  }
  const clearDrops = () => outlineBody.querySelectorAll(".drop-before,.drop-after,.drop-into").forEach((el) => el.classList.remove("drop-before", "drop-after", "drop-into"));
  function dropZone(item, id, event, isRoot) {
    if (isRoot) return "into";
    const box = item.getBoundingClientRect();
    const y = (event.clientY - box.top) / box.height;
    if (figure.groupOf(id) && y > 0.28 && y < 0.72) return "into";
    return y < 0.5 ? "before" : "after";
  }
  function outlineDrop(item, id, isRoot) {
    item.addEventListener("dragover", (event) => {
      if (!dragging || dragging === id) return;
      event.preventDefault();
      clearDrops();
      item.classList.add(`drop-${dropZone(item, id, event, isRoot)}`);
    });
    item.addEventListener("dragleave", () => item.classList.remove("drop-before", "drop-after", "drop-into"));
    item.addEventListener("drop", (event) => {
      event.preventDefault();
      const moving = dragging;
      clearDrops();
      if (!moving || moving === id) return;
      const zone = dropZone(item, id, event, isRoot);
      let parent, index;
      if (zone === "into") {
        parent = id;
        index = (figure.groupOf(id).children || []).filter((child) => child !== moving).length;
      } else {
        const holder = figure.parentOf(id);
        if (!holder) return;
        parent = holder.id;
        const siblings = (holder.children || []).filter((child) => child !== moving);
        index = siblings.indexOf(id) + (zone === "after" ? 1 : 0);
      }
      figure.act({ do: "move", id: moving, parent, index });
    });
  }

  // -- the source --
  const gutter = h("div.code-gutter");
  const area = h("textarea.code-area.scroll-thin", { wrap: "off" });
  area.spellcheck = false;  // h() leaves out what is false
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
  function numbers() {
    const count = area.value.split("\n").length;
    const bad = new Set(messages.map((m) => /^line (\d+)$/.exec(m.where)?.[1]).filter(Boolean).map(Number));
    if (gutter.childElementCount !== count || bad.size || gutter.querySelector(".bad")) {
      clear(gutter, Array.from({ length: count }, (_, i) => h(`div${bad.has(i + 1) ? ".bad" : ""}`, {}, i + 1)));
    }
  }
  function find(id) {
    const lines = area.value.split("\n");
    const pattern = new RegExp(`^\\s*(-\\s*)?id:\\s*['"]?${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}['"]?\\s*$`);
    const index = lines.findIndex((line) => pattern.test(line));
    if (index < 0) return;
    const start = lines.slice(0, index).reduce((sum, line) => sum + line.length + 1, 0);
    area.setSelectionRange(start, start + lines[index].length);
    area.scrollTop = Math.max(0, index * LINE - area.clientHeight / 3);
  }

  function showTab() {
    clear(leftTabs,
      h(`button.tab${state.tab === "parts" ? ".on" : ""}`, { onclick: () => { state.tab = "parts"; showTab(); } }, "Parts"),
      h(`button.tab${state.tab === "source" ? ".on" : ""}`, { onclick: () => { state.tab = "source"; showTab(); } }, "Source"));
    clear(leftBody, state.tab === "source" ? code : outlineBody);
    if (state.tab === "parts") renderOutline();
    else { numbers(); const id = figure.selected.length === 1 ? figure.selected[0] : null; if (id) find(id); }
  }
  showTab();

  // -- the inspector --
  function renderInspector() {
    root.classList.toggle("wide", figure.wantsRoom());
    keepFocus(inspectorBody, () => {
      clear(inspectorBody, figure.model ? figure.panel()
        : h("div.empty", {}, "The file does not read as a figure. Fix it in Source; the messages under the drawing say where."));
    });
  }

  // -- files --
  // A theme file made from the theme in use, next to the figure, and the figure put in it:
  // its colours, type and lines are then changed in the theme's own tab.
  async function customiseTheme(current, set) {
    const folder = studio.folder();
    if (/\.(ya?ml|json)$/i.test(current)) { studio.workspace.open(folder + current); return; }
    const stem = studio.file.split("/").pop().replace(/\.(ya?ml|json)$/i, "");
    const taken = new Set(studio.workspace.documents.map((item) => item.file));
    let file = `${folder}${stem}.theme.yaml`;
    for (let n = 2; taken.has(file); n++) file = `${folder}${stem}-${n}.theme.yaml`;
    const name = file.split("/").pop().replace(/\.theme\.yaml$/, "");
    try {
      const made = (await studio.api("/api/new", { file, kind: "theme", data: { theme: { name: `${name}-look`, base: current, description: `The look of ${stem}.` } } })).file;
      set(made.slice(folder.length));
      await studio.workspace.refreshDocuments();
      studio.workspace.open(made);
      toast("Change the theme in its tab: the figure redraws as you go.", { icon: "theme", seconds: 4 });
    } catch (error) {
      toast(`Could not make the theme: ${error.message}`, { kind: "error", icon: "error", seconds: 6 });
    }
  }

  function chooseFile({ title, types }) {
    return new Promise((resolve) => {
      let done = false;
      const finish = (value) => { if (!done) { done = true; resolve(value); box.close(); } };
      const list = h("div.list-rows", {}, h("div.empty", {}, h("div.spinner")));
      const accept = types.includes("image") ? "image/*,.svg,.pdf,.ai" : ".pdb,.cif,.mmcif,.ent";
      const upload = h("input", { type: "file", accept, hidden: true,
        onchange: async () => { const file = upload.files[0]; if (file) finish(await studio.upload(file)); } });
      const box = dialog({ title, body: [list, upload], actions: [
        { label: "Upload…", run: () => { upload.click(); return false; } },
        { label: "Cancel", run: () => finish(null) },
      ], onClose: () => finish(null) });
      studio.files(types).then((files) => {
        clear(list, files.length ? files.map((file) => h("button.menu-item", { type: "button", onclick: () => finish(file) },
          types.includes("image") ? h("img.pic", { src: studio.raw(file), alt: "" }) : icon("file"),
          h("span.menu-text", {}, h("span", {}, file.split("/").pop()), h("span.menu-hint", {}, file))))
          : h("div.empty", {}, "No such files beside the figure yet: upload one."));
      });
    });
  }

  // -- keys --
  const typing = (target) => target.closest?.("input, textarea, select, [contenteditable]");
  document.addEventListener("keydown", (event) => {
    if (!studio.active || typing(event.target) || document.querySelector(".scrim, .menu")) return;
    figure.key(event);
  });

  // -- what the drawing brings --
  const showMessages = () => {
    clear(note, messages.map((message) => h(`div.message.${message.severity}${message.where ? ".link" : ""}`,
      { onclick: () => {
        if (!message.where) return;
        if (message.where.startsWith("line ")) studio.reveal({ line: Number(message.where.slice(5)) });
        else if (figure.typeOf(message.where)) figure.select([message.where]);
      } },
      icon(message.severity === "error" ? "error" : message.severity === "note" ? "info" : "warning"),
      h("div", {}, message.text, message.where ? h("div.where", {}, message.where) : null))));
    if (state.tab === "source") numbers();
  };

  studio.on("drawn", (result) => {
    messages = result.messages || [];
    showMessages();
    if (result.info?.model) figure.setModel(result.info.model);
    const drawn = result.pages[0];
    if (!drawn) {
      if (!page.querySelector("svg")) clear(stage, h("div.fig-empty", {}, icon("warning"), "Nothing to draw yet"));
      page.style.opacity = "0.45";
      return;
    }
    page.style.opacity = "";
    const before = figure.landing();
    page.innerHTML = drawn.svg.replace(/^<\?xml[^>]*>\s*/, "");
    const svg = page.querySelector("svg");
    widenLines(svg);
    page.append(hover, marks);
    const view = svg.viewBox.baseVal;
    natural = view && view.width ? { width: view.width * 96 / 72, height: view.height * 96 / 72 } : { width: 600, height: 400 };
    svg.removeAttribute("width");
    svg.removeAttribute("height");
    if (page.parentNode !== stage) clear(stage, page);
    fitPage();
    figure.land(before);
  });

  // Someone else's change, or undo: the source follows, keeping the caret on its words.
  studio.on("change", ({ quiet }) => {
    if (quiet || area.value === studio.doc.text) return;
    const { selectionStart: start, selectionEnd: end, scrollTop } = area;
    const before = area.value;
    const shift = (at) => {
      const prefix = before.slice(0, at);
      const index = studio.doc.text.indexOf(prefix.slice(-40));
      return prefix.length <= 40 ? Math.min(at, studio.doc.text.length) : index >= 0 ? index + Math.min(40, prefix.length) : at;
    };
    area.value = studio.doc.text;
    if (document.activeElement === area) area.setSelectionRange(shift(start), shift(end));
    area.scrollTop = scrollTop;
    if (state.tab === "source") numbers();
  });
  studio.on("remote", () => { page.classList.remove("flash"); void page.offsetWidth; page.classList.add("flash"); });
  studio.reveal = (where) => {
    if (where?.id) figure.select([where.id]);
    else if (where?.line) {
      state.tab = "source"; showTab();
      const lines = area.value.split("\n");
      const start = lines.slice(0, where.line - 1).reduce((sum, line) => sum + line.length + 1, 0);
      area.focus({ preventScroll: true });
      area.setSelectionRange(start, start + (lines[where.line - 1] || "").length);
      area.scrollTop = Math.max(0, (where.line - 1) * LINE - area.clientHeight / 3);
    }
  };
  studio.commands = () => [
    { icon: "plus", label: "Add a part", run: () => figure.addPalette(addButton) },
    ...Object.entries(catalog.parts).filter(([, part]) => !part.unavailable).map(([kind, part]) => ({ icon: "plus", label: `Add ${part.title.toLowerCase()}`, hint: part.hint, run: () => figure.addPart(kind) })),
    { icon: "right", label: "Connect two parts", run: () => figure.toggleConnect(true) },
    { icon: "export", label: "Export editable SVG", run: () => studio.exportFiles(["editable"]) },
    { icon: "export", label: "Export PDF", run: () => studio.exportFiles(["pdf"]) },
    { icon: "code", label: "Show the source", run: () => { state.tab = "source"; showTab(); } },
    { icon: "list", label: "Show the parts", run: () => { state.tab = "parts"; showTab(); } },
    ...(figure.model ? figure.model.nodes.map((node) => ({ icon: "target", label: `Find ${figure.nameOf(node.id)}`, hint: node.id, run: () => figure.select([node.id]) })) : []),
  ];

  renderBar();
  renderInspector();
}
