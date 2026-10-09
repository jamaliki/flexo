// The figure editor: the figure drawn in the middle, its parts listed on the left,
// what is chosen on the right. Parts come from a palette, lines are drawn by
// choosing one part and then another, words are typed on the drawing, and parts
// are gathered into rows, columns, grids and modules (parts.js, shared with the
// deck editor, which edits figures on its slides the same way). Every edit is
// made by the server to the figure's own file (the Source tab), so the file stays
// the figure, comments and all, and anything the page offers no control for can
// be written there.

import { h, clear, icon, ui, menu, dialog, keepFocus, toast, themeField, ownResources, inQuotes, exportLabel } from "/static/studio/studio.js";
import { figureParts, glyph, groupGlyph, lookFrom, plain, titled, widenLines } from "/static/kinds/figure/parts.js";

const LINE = 12.5 * 1.6;
// Narrower than this (pixels), the editor folds its shapes' list away.
const NARROW = 1000;

export function mount(studio, main) {
  lookFrom("/static/kinds/figure/editor.css");
  const catalog = studio.catalog.editor;
  const state = { tab: "parts", zoom: null, closed: new Set() };
  let messages = [];
  let pointed = null;  // the part the pointer is over (placeHover)

  // -- the frame --
  const leftBody = h("div.panel-body.scroll-thin");
  const leftTabs = h("div.tabs");
  const left = h("section.panel.fig-left", {}, h("div.panel-head", {}, leftTabs), leftBody);
  const page = h("div.fig-page");
  const hover = h("div.fig-hover", { hidden: true });
  const marks = h("div.fig-marks");
  const stage = h("div.stage.fig-stage.scroll-thin", {}, h("div.fig-empty", {}, h("div.spinner"), "Loading…"));
  const note = h("div.messages.fig-messages.scroll-thin");
  const hint = h("div.fig-hint", { hidden: true });
  const zoomValue = h("span.value", {}, "");
  const zoomBar = h("div.fig-zoom", {},
    ui.button("", () => zoomBy(1 / 1.25), { kind: "ghost", icon: "minus", small: true, title: "Zoom Out (⌘−)" }),
    zoomValue,
    ui.button("", () => zoomBy(1.25), { kind: "ghost", icon: "plus", small: true, title: "Zoom In (⌘+)" }),
    ui.button("Fit", () => setZoom(null), { kind: "ghost", small: true, title: "Zoom to Fit (⇧⌘0)" }),
    ui.button("1:1", () => setZoom(1), { kind: "ghost", small: true, title: "Actual Size (⌘0)" }));
  // Clicked, a zoom button does not keep the keys (as a Mac window's toolbar buttons don't):
  // it would look pressed while the drawing is zoomed on from the keyboard.
  for (const button of zoomBar.querySelectorAll("button")) button.addEventListener("mousedown", (event) => event.preventDefault());
  const center = h("section.fig-center", {}, stage, hint, note, zoomBar);
  const inspectorBody = h("div.panel-body.scroll-thin");
  const inspector = h("aside.panel.fig-inspector", {}, inspectorBody);
  // A field left ends its run of edits in the history, as the deck's does: typed in again,
  // however soon, it is another step. (A field drawn again under the keys is not left.)
  inspector.addEventListener("focusout", (event) => {
    const key = event.target?.dataset?.key, run = studio.lastMerge?.key;
    setTimeout(() => Promise.resolve(figure.idle?.()).then(() => {
      if (run && studio.lastMerge?.key === run && (!key || document.activeElement?.dataset?.key !== key)) studio.step();
    }), 0);
  });
  const split = h("div.fig-split");
  const root = h("div.fig", {}, left, split, center, inspector);
  clear(main, root);
  // In a narrow window the shapes' list folds away -- opened over the figure by its button
  // in the bar -- and the inspector narrows: the figure keeps the room it is drawn in.
  const listButton = ui.button("", () => { root.classList.toggle("list-open"); fitPage(); }, { kind: "ghost", icon: "sidebar", title: "Shapes and Source" });
  new ResizeObserver(() => {
    const narrow = root.clientWidth < NARROW;
    root.classList.toggle("narrow", narrow);
    if (!narrow) root.classList.remove("list-open");
    listButton.hidden = !narrow;
  }).observe(root);
  center.addEventListener("pointerdown", () => { if (root.classList.contains("list-open")) { root.classList.remove("list-open"); fitPage(); } });
  split.addEventListener("pointerdown", (event) => {
    split.setPointerCapture(event.pointerId);
    split.classList.add("dragging");
    const move = (e) => root.style.setProperty("--left", `${Math.min(Math.max(200, e.clientX - root.getBoundingClientRect().left), 720)}px`);
    split.addEventListener("pointermove", move);
    split.addEventListener("pointerup", () => { split.classList.remove("dragging"); split.removeEventListener("pointermove", move); fitPage(); }, { once: true });
  });

  // -- the bar --
  const addButton = ui.button("Shape", (event) => figure.addPalette(event.currentTarget), { icon: "plus", kind: "ghost", title: "Add Shape (A)" });
  const connectButton = ui.button("Connect", () => figure.toggleConnect(), { kind: "ghost", icon: "right", title: "Draw a line from one shape to another (C)" });
  const gatherButton = ui.button("Group", (event) => figure.groupMenu(event.currentTarget), { kind: "ghost", icon: "layout", title: "Group the Selected Shapes (G)" });
  const deleteButton = ui.button("Delete", () => figure.remove(), { kind: "ghost", icon: "trash", title: "Delete (⌫)" });
  // As Keynote's toolbar: what adds and joins shapes in the middle (the tab names the figure).
  studio.tools.append(listButton);
  studio.inserts.append(addButton, connectButton, gatherButton, deleteButton);
  // In the Export menu's order, for the Mac app's File › Export To.
  // ("…" only where the Mac app's save panel follows: in a browser each is saved at once.)
  studio.exports = [
    { format: "editable", get label() { return exportLabel("Editable SVG"); } },
    { format: "pdf", get label() { return exportLabel("PDF"); } },
    { format: "png", get label() { return exportLabel("PNG"); } },
  ];
  studio.actions.append(ui.button("Export", (event) => menu(event.currentTarget, [
    { icon: "export", label: exportLabel("Editable SVG"), hint: "Inkscape layers and live text", run: () => studio.exportFiles(["editable"]) },
    { icon: "export", label: exportLabel("PDF"), hint: "Embedded fonts", run: () => studio.exportFiles(["pdf"]) },
    { icon: "image", label: exportLabel("PNG"), run: () => studio.exportFiles(["png"]) },
    "-",
    { icon: "export", label: exportLabel("All Formats"), run: () => studio.exportFiles(["editable", "portable", "pdf", "png"]) },
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
    // The figure is the whole document: ⌘A chooses all of it, and a drag from where nothing is
    // chooses what it touches.
    whole: true,
    // The box words are typed in stays on the stage as the drawing is put in again.
    typing: stage,
    element: elementOf,
    idOf: (id) => id,
    box: boxOf,
    changed: () => { placeMarks(); renderOutline(); renderInspector(); renderBar(); showHint(); },
    settled: () => placeMarks(),
    // What keeps a shape from being drawn as written, as the drawing says: its panel says it.
    problems: () => messages.filter((message) => message.severity === "error" && figure.typeOf(message.where) === "node")
      .map((message) => ({ id: message.where, text: message.text, what: String(message.code || "").split(".").pop() })),
    reveal: (id) => {
      outlineBody.querySelector(`.tree-row[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "nearest" });
      if (state.tab === "source") find(id);
    },
    focus: (where) => studio.focus(where),
    chooseFile,
    themeField: (value, set) => themeField(studio, { value, onPick: set, onCustomise: (current) => customiseTheme(current, set) }),
    tones: () => studio.info?.tones,
    // The figure is named as its file is.
    name: () => String(studio.file || "").split("/").pop().replace(/\.ya?ml$/i, ""),
    // Edits held while the studio is away: the document is not saved meanwhile.
    waiting: (on) => { studio.waiting = Math.max(0, (studio.waiting || 0) + (on ? 1 : -1)); studio.emit("status"); },
    held: () => studio.emit("status"),
    // (A label's ⌘Z, once someone else's words came into it, is the document's undo.)
    undo: () => studio.undo(),
    redo: () => studio.redo(),
    addAnchor: () => addButton,
    groupAnchor: () => gatherButton,
    // The server makes the edit to the file's words; if the file changed while it did
    // (someone typed, an agent wrote), it is made again on the file as it is now.
    run: async (action, { merge, hold, label }) => {
      for (let attempt = 0; attempt < 3; attempt += 1) {
        const sent = studio.doc.text;
        const result = await studio.api("/api/act", { file: studio.file, document: studio.doc, action });
        if (studio.doc.text !== sent) continue;
        // A question asked of the figure (its parts, a structure's view) changes nothing.
        if (action.do === "structure-view" || action.do === "structure-settings") return result;
        studio.change((d) => ({ ...d, text: result.document.text }), { merge, hold, label });
        // An edit made from the drawing is drawn at once: its parts are waiting to land.
        if (action.do !== "read" && action.do !== "update") studio.requestDraw?.(0);
        return result;
      }
      return null;
    },
  });
  let greeted = false;  // (a new figure's one shape opened for its words: see the end)
  // Keys typed while it was on its way, just made, are typed again once it is open: its
  // one shape's words (shell.js's create).
  studio.takesKeys = true;
  // ⌘Z and Undo take back an edit held for the studio while it is away, and say which.
  // (`key`: one of studio.heldEdits(), for one history with the document's own, in the
  // order they were made.)
  studio.takeBack = (key = null) => figure.takeBackWaiting(key);
  studio.heldEdits = () => figure.heldEdits();
  studio.takenEdits = () => figure.takenEdits();
  studio.takeBackLabel = () => figure.waitingLabel();
  // (And made again, ⇧⌘Z and Redo, should nothing else be done meanwhile.)
  studio.putBack = (key = null) => figure.putBackWaiting(key);
  studio.putBackLabel = () => figure.takenLabel();

  function renderBar() {
    const chosen = figure.selected;
    deleteButton.disabled = !chosen.length || chosen.includes(figure.model?.root);
    connectButton.classList.toggle("on", Boolean(figure.connecting));
    // (Shapes to group chosen: an empty group is added from the palette's Layout.)
    gatherButton.disabled = !figure.model || !figure.canGroup();
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
    // (In the room the stage leaves it: less the shapes' list, opened over it.)
    const room = stage.getBoundingClientRect(), style = getComputedStyle(stage);
    const width = room.width - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    return Math.min(width / natural.width, (room.height - 96) / natural.height, 3);
  };
  // Zoomed in or out, the drawing stays put under a point: the pointer's, for a pinch; else
  // the middle of what is chosen, if it is in sight; else the middle of the view.
  function setZoom(value, at = null) {
    const view = stage.getBoundingClientRect(), before = page.getBoundingClientRect();
    const chosen = figure.selected.map((id) => boxOf(id)).filter(Boolean);
    let point = at;
    if (!point && chosen.length) {
      const middle = { x: before.left + (Math.min(...chosen.map((box) => box.left)) + Math.max(...chosen.map((box) => box.left + box.width))) / 2,
        y: before.top + (Math.min(...chosen.map((box) => box.top)) + Math.max(...chosen.map((box) => box.top + box.height))) / 2 };
      if (middle.x > view.left && middle.x < view.right && middle.y > view.top && middle.y < view.bottom) point = middle;
    }
    point ??= { x: view.left + stage.clientWidth / 2, y: view.top + stage.clientHeight / 2 };
    // Where the point is on the drawing, as a share of it, before and after.
    const share = { x: (point.x - before.left) / (before.width || 1), y: (point.y - before.top) / (before.height || 1) };
    state.zoom = value && Math.min(Math.max(value, 0.1), 8);
    fitPage();
    const after = page.getBoundingClientRect();
    stage.scrollLeft += after.left + share.x * after.width - point.x;
    stage.scrollTop += after.top + share.y * after.height - point.y;
  }
  const zoomBy = (factor, at = null) => setZoom((state.zoom ?? fitScale()) * factor, at);
  function fitPage() {
    const svg = page.querySelector("svg");
    if (!svg) return;
    const scale = state.zoom ?? fitScale();
    svg.style.width = `${natural.width * scale}px`;
    svg.style.height = `${natural.height * scale}px`;
    // Zoomed, the canvas runs a view's width and height past the drawing each way: it can be
    // scrolled to keep any point where it was as the drawing grows or shrinks about it (a
    // short figure too, which would otherwise sit in the middle). Fitted, it is centred.
    page.style.margin = state.zoom ? `${stage.clientHeight}px ${stage.clientWidth}px` : "";
    zoomValue.textContent = `${Math.round(scale * 100)}%`;
    placeMarks();
    figure.placeInline();
  }
  new ResizeObserver(() => fitPage()).observe(stage);
  stage.addEventListener("wheel", (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    zoomBy(Math.exp(-event.deltaY / 200), { x: event.clientX, y: event.clientY });
  }, { passive: false });

  function placeMarks() {
    placeHover();
    clear(marks, figure.markViews());
  }
  page.addEventListener("click", (event) => { if (!event.target.closest(".fig-inline")) figure.click(event); });
  page.addEventListener("pointerdown", (event) => { if (!event.target.closest(".fig-inline")) figure.pointerdown(event); });
  stage.addEventListener("click", (event) => { if (event.target === stage && !figure.connecting && !figure.justDragged) figure.select([]); });
  // Pressed on the desk round the page and dragged, a band chooses the shapes it touches, as
  // from the page's own empty space.
  stage.addEventListener("pointerdown", (event) => { if (event.target === stage && figure.model) figure.band(event); });
  page.addEventListener("dblclick", (event) => { if (!event.target.closest(".fig-inline")) figure.dblclick(event); });
  // Right-click, as on a slide: what is under the pointer is chosen, and its menu offers what
  // can be done with it (a line: a shape inserted into it) -- Cut, Copy and Paste among it, as
  // the slide's object menu has them; on nothing (the page, or the desk round it), Add Shape.
  function partMenu(point, id) {
    const own = figure.menuOf(id, point), last = (label) => own.filter((item) => item?.label === label);
    const first = own.filter((item) => !["Duplicate", "Delete"].includes(item?.label));
    // (A line's offers no Cut or Copy: a line goes with the shapes it joins.)
    const clips = clipItems().filter((item) => item.label === "Paste" || !item.disabled);
    menu(point, [...first, ...(first.length ? ["-"] : []), ...clips, ...last("Duplicate"), "-", ...last("Delete")]);
  }
  function pageMenu(point) {
    figure.select([]);
    if (!figure.model) return;
    menu(point, [{ icon: "plus", label: "Add Shape…", keys: "A", run: () => figure.addPalette(point) },
      { icon: "paste", label: "Paste", keys: "⌘V", disabled: !clipboard, run: () => clipboard && figure.paste(clipboard.parts) },
      { icon: "target", label: "Select All", keys: "⌘A", run: () => figure.chooseAll() }]);
  }
  page.addEventListener("contextmenu", (event) => {
    if (event.target.closest(".fig-inline")) return;
    event.preventDefault();
    const point = { x: event.clientX, y: event.clientY }, id = figure.model ? figure.idAt(event) : null;
    if (id && id !== figure.model.root) partMenu(point, id);
    else pageMenu(point);
  });
  stage.addEventListener("contextmenu", (event) => {
    if (event.target !== stage) return;
    event.preventDefault();
    pageMenu({ x: event.clientX, y: event.clientY });
  });
  // What the pointer is over is framed, dashed -- not what is chosen, framed already -- and
  // stays framed as the drawing is zoomed under it.
  function placeHover() {
    const where = pointed && !figure.selected.includes(pointed) && boxOf(pointed);
    hover.hidden = !where;
    if (where) Object.assign(hover.style, { left: `${where.left}px`, top: `${where.top}px`, width: `${where.width}px`, height: `${where.height}px` });
  }
  page.addEventListener("mousemove", (event) => {
    if (figure.dragging) return;
    pointed = figure.idAt(event);
    placeHover();
  });
  page.addEventListener("mouseleave", () => { pointed = null; hover.hidden = true; });

  // -- the outline --
  const outlineBody = h("div.tree");
  const slug = (words) => String(words).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  // Whether a part's id says something its words do not: not when it is its words run
  // together, nor words of them ("y" for "Output y"), nor a name the figure gave it for
  // what it is ("database", "block-2", a group's "row").
  const MADE = new Set(["shape", "step", "check", "part", "row", "column", "grid", "module", "group"]);
  function telling(id, item) {
    const stem = id.replace(/-\d+$/, ""), said = slug(figure.nameOf(id)).split("-");
    if (stem.split("-").every((word) => said.includes(word))) return false;
    const kind = item?.kind || "block", part = catalog.parts?.[kind];
    return !MADE.has(stem) && stem !== kind && stem !== slug(part?.title || "") && stem !== slug(plain(part?.node?.label || ""));
  }
  function renderOutline() {
    if (state.tab !== "parts") return;
    const found = figure.model;
    if (!found) { clear(outlineBody, h("div.empty", {}, "No shapes")); return; }
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
        // Right-clicked, the row's shape has its menu, as on the drawing (the layout, the page's).
        oncontextmenu: (event) => { event.preventDefault(); const point = { x: event.clientX, y: event.clientY }; if (isRoot) pageMenu(point); else partMenu(point, id); },
      },
      group && children.length ? h(`button.tree-caret${open ? ".open" : ""}`, { type: "button", onclick: (event) => {
        event.stopPropagation();
        if (open) state.closed.add(id); else state.closed.delete(id);
        renderOutline();
      } }, icon("chevron")) : h("span.tree-caret"),
      node ? glyph(node.kind || "block") : group ? glyph(groupGlyph(group)) : glyph("block"),
      h("span.tree-name", {}, isRoot ? "Layout" : figure.nameOf(id)),
      // A shape is listed by its words; its id, where it says more than they do, is shown
      // when the row is pointed at or chosen.
      isRoot || !telling(id, node || group) ? null : h("span.tree-id.part-id", {}, id));
      outlineDrop(item, id, isRoot);
      if (!isRoot) outlineDrag(item, id);
      return [item, group && open ? children.map((child) => row(child, depth + 1)) : null];
    };
    const lines = [...found.edges, ...found.nets.map((net) => ({ ...net, net: true }))];
    clear(outlineBody,
      h("div.tree-head", {}, "Shapes", h("span.count", {}, found.nodes.length)),
      figure.groupOf(found.root) ? row(found.root, 0) : null,
      h("div.tree-head", {}, "Lines", h("span.count", {}, lines.length)),
      lines.length ? lines.map((line) => h(`div.tree-row.line${chosen.includes(line.id) ? ".on" : ""}`, {
        dataset: { id: line.id }, onclick: (event) => choose(event, line.id),
        oncontextmenu: (event) => { event.preventDefault(); partMenu({ x: event.clientX, y: event.clientY }, line.id); },
      }, h("span.tree-caret"), glyph(line.net ? "net" : "edge"),
      h("span.tree-name", {}, figure.nameOf(line.id)),
      // Its words beside its name -- unless its name says them already (a line beside its twin).
      line.label && !figure.nameOf(line.id).includes(inQuotes(plain(line.label))) ? h("span.tree-id", {}, plain(line.label)) : null))
      : h("div.empty.small", {}, "No lines"));
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
  // Tab indents the YAML; Ctrl-Tab, or Esc and then Tab, goes on (ui.js).
  ui.indent(area);
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
      h(`button.tab${state.tab === "parts" ? ".on" : ""}`, { onclick: () => { state.tab = "parts"; showTab(); } }, "Shapes"),
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
        : h("div.empty", {}, "This file can’t be read as a figure. Fix it in Source; the messages below the drawing show where."));
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
      toast("Theme created. Edit it in its tab and the figure updates as you go.", { icon: "theme", seconds: 4 });
    } catch (error) {
      toast(`Couldn’t create the theme: ${error.message}`, { kind: "error", icon: "error", seconds: 6 });
    }
  }

  // As a Mac's open panel: a click chooses a file, the arrows move along them, and a
  // double-click, Return or the default button (`action`: "Insert", "Choose") takes it.
  function chooseFile({ title, types, action = "Choose" }) {
    return new Promise((resolve) => {
      let done = false;
      const finish = (value) => { if (!done) { done = true; resolve(value); box.close(); } };
      const list = h("div.list-rows", {}, h("div.empty", {}, h("div.spinner")));
      const accept = types.includes("image") ? "image/*,.svg,.pdf,.ai" : ".pdb,.cif,.mmcif,.ent";
      const upload = h("input", { type: "file", accept, hidden: true,
        onchange: async () => { const file = upload.files[0]; if (file) finish(await studio.upload(file)); } });
      const actions = [{ label: "Upload…", aside: true, run: () => { upload.click(); return false; } }];
      // The PDB's sheet in this one's place, not over it: this one closes first.
      if (types.includes("structure")) actions.push({ label: "PDB ID…", aside: true, run: () => {
        done = true;
        askEntry().then((id) => resolve(id || null));
      } });
      let chosen = null;
      actions.push({ label: "Cancel", run: () => finish(null) });
      actions.push({ label: action, kind: "primary", run: () => { if (chosen) finish(chosen); return false; } });
      list.setAttribute("role", "listbox");
      list.setAttribute("aria-label", title);
      const box = dialog({ title, body: [list, upload], actions, onClose: () => finish(null) });
      const take = [...document.querySelectorAll(".dialog-foot .btn.primary")].pop();
      if (take) take.disabled = true;
      const pick = (row, file) => {
        chosen = file;
        for (const other of list.querySelectorAll("[role=option]")) other.setAttribute("aria-selected", String(other === row));
        if (take) take.disabled = false;
        row.focus({ preventScroll: true });
        row.scrollIntoView({ block: "nearest" });
      };
      list.addEventListener("keydown", (event) => {
        const rows = [...list.querySelectorAll("[role=option]")], at = rows.indexOf(document.activeElement);
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          const next = rows[Math.max(0, Math.min(rows.length - 1, at + (event.key === "ArrowDown" ? 1 : -1)))];
          if (next) pick(next, next.dataset.file);
        } else if (event.key === "Enter" && chosen) { event.preventDefault(); finish(chosen); }
      });
      studio.files(types).then((files) => {
        // Each file once, by its name; the folder it is in said only when it is in one.
        const seen = new Set();
        const shown = files.filter((file) => !seen.has(file) && seen.add(file));
        clear(list, shown.length ? shown.map((file) => {
          const row = h("button.menu-item", { type: "button", role: "option", "aria-selected": "false", dataset: { file },
            onclick: () => pick(row, file), ondblclick: () => finish(file) },
            types.includes("image") ? h("img.pic", { src: studio.raw(file), alt: "" }) : icon(types.includes("structure") ? "structure" : "file"),
            h("span.menu-text", {}, h("span", {}, file.split("/").pop()), file.includes("/") ? h("span.menu-hint", {}, file.slice(0, file.lastIndexOf("/") + 1)) : null));
          return row;
        })
          : h("div.empty", {}, types.includes("structure") ? "No structure files next to the figure. Upload a PDB or mmCIF file, or enter a PDB ID." : "No files of this type next to the figure. Click Upload to add one."));
        // The keys at the first file, to choose with the arrows.
        list.querySelector("[role=option]")?.focus({ preventScroll: true });
      });
    });
  }

  // A PDB entry, downloaded before it is added: if it can't be, the dialog says why and
  // nothing is added.
  function askEntry() {
    return new Promise((resolve) => {
      let done = false;
      const input = ui.input({ placeholder: "1UBQ", mono: true });
      const note = h("div.field-problem", { hidden: true });
      // While it downloads its button says so, and is not pressed twice.
      const download = ui.button("Download", () => fetchIt(), { kind: "primary" });
      const busy = (on) => { download.disabled = on; download.querySelector(".btn-label").textContent = on ? "Downloading…" : "Download"; };
      const fetchIt = async () => {
        const id = input.value.trim().toUpperCase();
        if (!id || download.disabled) { input.focus(); return; }
        clear(note, h("span.spinner"), h("span", {}, `Downloading ${id}…`));
        note.hidden = false;
        busy(true);
        try {
          const found = await studio.api("/api/act", { file: studio.file, document: studio.doc, action: { do: "structure-fetch", id } });
          // (One that can't be had is said in the answer, not as a failed request.)
          if (found.failed) throw new Error(found.failed);
          if (!done) { done = true; resolve(found.id); box.close(); }
        } catch (error) {
          clear(note, icon("warning"), h("span", {}, error.message));
          input.classList.add("invalid");
          input.focus();
        }
        busy(false);
      };
      input.addEventListener("input", () => { input.classList.remove("invalid"); note.hidden = true; });
      input.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); fetchIt(); } });
      const box = dialog({ title: "Add a Structure from the PDB", body: [ui.field("PDB ID", input, { hint: "Four characters, like 1UBQ" }), note],
        actions: [{ label: "Cancel", run: () => { done = true; resolve(null); } }, download],
        onClose: () => { if (!done) { done = true; resolve(null); } } });
      setTimeout(() => input.focus(), 20);
    });
  }

  // -- copied, cut and pasted --
  // The shapes chosen, with what they hold and the lines between them, as a slide's figure's
  // are copied (in the deck's own format): pasted after what is chosen -- in this figure,
  // another, or onto a slide.
  const CLIP = "application/x-flexo-deck";
  let clipboard = null;
  const typingNow = () => Boolean(typing(document.activeElement) || document.querySelector(".scrim"));
  // Words chosen to copy in the panel or a message -- not on the drawing.
  const wordsChosen = () => { const chosenWords = window.getSelection(); return Boolean(chosenWords?.toString()) && !page.contains(chosenWords.anchorNode); };
  const clipOf = () => {
    const parts = figure.model ? figure.clip() : null;
    return parts ? { what: "parts", parts, label: parts.top.length > 1 ? `${parts.top.length} shapes` : "shape" } : null;
  };
  const plainOf = (clip) => clip.parts.nodes.map((node) => plain(node.label) || node.id).join("\n");
  const clipName = (clip) => clip.label.replace(/(^|\s)\p{L}/gu, (first) => first.toUpperCase());
  const copied = (clip) => toast(`${clip.label.charAt(0).toUpperCase()}${clip.label.slice(1)} copied`, { icon: "copy", seconds: 1.5 });
  // (Lines chosen alone: why nothing was copied is said, not left to look done.)
  const uncopied = () => { const why = figure.uncopied(); if (why) toast(why, { icon: "info", seconds: 3 }); };
  const ownsClip = () => studio.active && !typingNow() && !wordsChosen() && Boolean(figure.model);
  function clipChosen(cut) {
    const clip = clipOf();
    if (!clip) { uncopied(); return; }
    clipboard = clip;
    navigator.clipboard?.writeText(plainOf(clip)).catch(() => {});
    if (cut) figure.remove(undefined, [], { cut: true }); else copied(clip);
  }
  // Greyed out, as a Mac menu's are, when there is nothing to cut, copy or paste.
  const clipItems = () => [
    { icon: "cut", label: "Cut", keys: "⌘X", disabled: !clipOf(), run: () => clipChosen(true) },
    { icon: "copy", label: "Copy", keys: "⌘C", disabled: !clipOf(), run: () => clipChosen(false) },
    { icon: "paste", label: "Paste", keys: "⌘V", disabled: !clipboard, run: () => clipboard && figure.paste(clipboard.parts) },
  ];
  function copyNow(event) {
    const clip = ownsClip() ? clipOf() : null;
    if (!clip) return null;
    event.preventDefault();
    clipboard = clip;
    event.clipboardData?.setData(CLIP, JSON.stringify(clip));
    event.clipboardData?.setData("text/plain", plainOf(clip));
    return clip;
  }
  document.addEventListener("copy", (event) => {
    keyed = null;
    const clip = copyNow(event);
    if (clip) copied(clip); else if (ownsClip()) uncopied();
  });
  document.addEventListener("cut", (event) => {
    keyed = null;
    const clip = copyNow(event);
    if (clip) figure.remove(undefined, [], { cut: true }); else if (ownsClip()) uncopied();
  });
  document.addEventListener("paste", (event) => {
    keyed = null;
    if (!ownsClip() || event.defaultPrevented) return;
    let clip = null;
    try { clip = JSON.parse(event.clipboardData?.getData(CLIP) || "null"); } catch { clip = null; }
    // A clipboard that keeps only words: what was copied here, if they are its words.
    if (!clip && clipboard && event.clipboardData?.getData("text/plain") === plainOf(clipboard)) clip = clipboard;
    if (clip?.what !== "parts" || !clip.parts?.top?.length) return;
    event.preventDefault();
    figure.paste(clip.parts);
  });
  // A web view that gives no copy, cut or paste to a page with nothing to type in (a Mac
  // app's, whose Edit menu waits for a selection) still passes the keys: if no such event
  // follows them, the page does it itself, with what it copied (as a deck's does).
  let keyed = null;
  document.addEventListener("keydown", (event) => {
    const letter = event.key.toLowerCase();
    if (!(event.metaKey || event.ctrlKey) || event.shiftKey || event.altKey || !["c", "x", "v"].includes(letter) || !ownsClip()) return;
    keyed = letter;
    setTimeout(() => {
      if (keyed !== letter) return;
      keyed = null;
      if (letter === "v") { if (clipboard) figure.paste(clipboard.parts); return; }
      clipChosen(letter === "x");
    }, 80);
  }, true);

  // -- keys --
  const typing = (target) => target.closest?.("input, textarea, select, [contenteditable]");
  document.addEventListener("keydown", (event) => {
    if (!studio.active || document.querySelector(".scrim, .menu")) return;
    // Esc puts the shapes' list away when it is open over the figure.
    if (event.key === "Escape" && root.classList.contains("list-open")) {
      event.preventDefault();
      root.classList.remove("list-open");
      fitPage();
      return;
    }
    if (typing(event.target)) return;
    const mod = event.metaKey || event.ctrlKey;
    // ⌘+ and ⌘− zoom the drawing, not the page round it; ⌘0 shows it at its actual size, and
    // ⇧⌘0 fits it to the window, as a deck's slide.
    if (mod && !event.altKey && ["=", "+", "-", "_"].includes(event.key)) {
      event.preventDefault();
      zoomBy(["-", "_"].includes(event.key) ? 1 / 1.25 : 1.25);
      return;
    }
    if (mod && !event.altKey && event.code === "Digit0") {
      event.preventDefault();
      setZoom(event.shiftKey ? null : 1);
      return;
    }
    figure.key(event);
  });

  // -- what the drawing brings --
  // Where a message is, as the page names it: a part by its name, the figure as the Figure.
  const placeName = (where) => (figure.typeOf(where) ? figure.nameOf(where)
    : where === figure.model?.figure?.id ? "Figure" : where.replace(/^line /, "Line "));
  const showMessages = () => {
    clear(note, messages.map((message) => h(`div.message.${message.severity}${message.where ? ".link" : ""}`,
      { onclick: () => {
        if (!message.where) return;
        if (message.where.startsWith("line ")) studio.reveal({ line: Number(message.where.slice(5)) });
        // A shape's problem: the shape chosen, its panel at the field to put it right in (a
        // line's, at its end that is at no shape).
        else if (["node", "edge"].includes(figure.typeOf(message.where))) figure.revealProblem(message.where, String(message.code || "").split(".").pop());
        else if (figure.typeOf(message.where)) figure.select([message.where]);
      } },
      icon(message.severity === "error" ? "error" : message.severity === "note" ? "info" : "warning"),
      // Where it is, by the name the part is shown by, not its ID (the figure as a whole, not
      // said: it is what is shown; nor a part the message names already).
      h("div", {}, message.text, message.where && placeName(message.where) !== "Figure" && !message.text.includes(`\u201c${placeName(message.where)}\u201d`)
        ? h("div.where", {}, placeName(message.where)) : null))));
    if (state.tab === "source") numbers();
  };

  // Drawn after another's edit or an undo, the words of the field being typed in follow too
  // -- and, after an undo or a redo, what it brought back is chosen (`travelled`).
  let afresh = false, travelled = false;
  studio.on("drawn", (result) => {
    messages = result.messages || [];
    if (result.info?.model) figure.setModel(result.info.model, { afresh, back: travelled });
    afresh = false;
    travelled = false;
    showMessages();
    const drawn = result.pages[0];
    if (!drawn) {
      if (!page.querySelector("svg")) clear(stage, h("div.fig-empty", {}, icon("warning"), "Nothing to show yet"));
      page.style.opacity = "0.45";
      return;
    }
    page.style.opacity = "";
    const before = figure.landing();
    page.innerHTML = drawn.svg.replace(/^<\?xml[^>]*>\s*/, "");
    const svg = ownResources(page.querySelector("svg"));
    widenLines(svg);
    page.append(hover, marks);
    const view = svg.viewBox.baseVal;
    natural = view && view.width ? { width: view.width * 96 / 72, height: view.height * 96 / 72 } : { width: 600, height: 400 };
    svg.removeAttribute("width");
    svg.removeAttribute("height");
    if (page.parentNode !== stage) clear(stage, page);
    fitPage();
    figure.land(before);
    // A new figure, its one shape with no words yet: chosen, its words typed at once.
    if (!greeted) {
      greeted = true;
      const nodes = figure.model?.nodes || [];
      if (nodes.length === 1 && !plain(nodes[0].label).trim() && !(figure.model.edges || []).length) figure.typeSoon(nodes[0].id);
    }
  });

  // Someone else's change, or undo: the source follows, keeping the caret on its words.
  studio.on("change", ({ quiet, source }) => {
    if (source === "history" || source === "remote") afresh = true;
    if (source === "history") travelled = true;
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
  // What is chosen, named for it: "Duplicate Shape", "Duplicate 3 Shapes" -- also the Mac
  // menu's plain Edit › Duplicate (`also`).
  const chosenName = () => {
    const shapes = figure.selected.filter((id) => figure.nodeOf(id) || (figure.groupOf(id) && id !== figure.model?.root)).length;
    return shapes > 1 ? `${shapes} Shapes` : shapes ? "Shape" : null;
  };
  studio.commands = () => [
    { icon: "plus", label: "Add Shape…", run: () => figure.addPalette(addButton) },
    // Cut and Copy of what is chosen, as ⌘X and ⌘C do them, named for it; Paste of what was.
    ...(!typingNow() && clipOf() ? [{ icon: "cut", label: `Cut ${clipName(clipOf())}`, keys: "⌘X", run: () => clipChosen(true) },
      { icon: "copy", label: `Copy ${clipName(clipOf())}`, keys: "⌘C", run: () => clipChosen(false) }] : []),
    ...(!typingNow() && clipboard ? [{ icon: "paste", label: `Paste ${clipName(clipboard)}`, keys: "⌘V", run: () => figure.paste(clipboard.parts) }] : []),
    ...(!typingNow() && chosenName() ? [{ icon: "duplicate", label: `Duplicate ${chosenName()}`, also: ["Duplicate"], keys: "⌘D", run: () => figure.duplicate() }] : []),
    ...(figure.model?.nodes.length ? [{ icon: "target", label: "Select All Shapes", keys: "⌘A", run: () => figure.chooseAll() }] : []),
    // View › Zoom, as a deck's slide is zoomed: by steps, a point to a point, or fitted.
    { icon: "plus", label: "Zoom In", keys: "⌘+", run: () => zoomBy(1.25) },
    { icon: "minus", label: "Zoom Out", keys: "⌘−", run: () => zoomBy(1 / 1.25) },
    { icon: "eye", label: "Actual Size", keys: "⌘0", run: () => setZoom(1) },
    { icon: "figure", label: "Zoom to Fit", also: ["Fit Slide"], keys: "⇧⌘0", run: () => setZoom(null) },
    ...Object.entries(catalog.parts).filter(([, part]) => !part.unavailable).map(([kind, part]) => ({ icon: "plus", label: `Add ${titled(part.title)}${part.needs_file ? "…" : ""}`, hint: part.hint, run: () => figure.addPart(kind) })),
    { icon: "right", label: "Connect Shapes", run: () => figure.toggleConnect(true) },
    { icon: "export", label: "Export as Editable SVG…", run: () => studio.exportFiles(["editable"]) },
    { icon: "export", label: "Export as PDF…", run: () => studio.exportFiles(["pdf"]) },
    { icon: "export", label: "Export as PNG…", run: () => studio.exportFiles(["png"]) },
    { icon: "code", label: "Show Source", run: () => { state.tab = "source"; showTab(); } },
    { icon: "list", label: "Show Shapes", run: () => { state.tab = "parts"; showTab(); } },
    ...(figure.model ? figure.model.nodes.map((node) => ({ icon: "target", label: `Select ${inQuotes(figure.nameOf(node.id))}`, hint: node.id, run: () => figure.select([node.id]) })) : []),
  ];

  renderBar();
  renderInspector();
  // A new figure -- one shape, with no words yet -- takes its words from the first key, the
  // keys typed before it is drawn among them, as a new table's first cell does.
  const text = String(studio.doc?.text || "");
  const ids = [...text.matchAll(/^\s*- id: (\S+)\s*$/gm)].map((found) => found[1]);
  const worded = /^\s+label: (?!(''|"")\s*$)\S/m.test(text);
  if (ids.length === 1 && !worded && !/^(edges|groups|nets):/m.test(text)) { greeted = true; figure.typeSoon(ids[0]); }
}
