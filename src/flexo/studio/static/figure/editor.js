// The figure editor: the figure drawn in the middle, its parts listed on the left,
// what is chosen on the right. Parts come from a palette, lines are drawn by
// choosing one part and then another, words are typed on the drawing, and parts
// are gathered into rows, columns, grids and modules. Every edit is made by the
// server to the figure's own file (the Source tab), so the file stays the figure,
// comments and all, and anything the page offers no control for can be written
// there.

import { h, clear, icon, ui, menu, popover, closeMenu, dialog, toast, keepFocus } from "/static/studio/studio.js";

const LINE = 12.5 * 1.6;

// Small pictures of each kind of part, drawn on a 16-unit square.
const GLYPHS = {
  block: "M2.5 4.5h11v7h-11z",
  text: "M4 4h8M8 4v8",
  op: "M8 3a5 5 0 100 10A5 5 0 008 3zM8 5.5v5M5.5 8h5",
  circle: "M8 3a5 5 0 100 10A5 5 0 008 3z",
  terminal: "M5 4.5h6a3.5 3.5 0 010 7H5a3.5 3.5 0 010-7z",
  decision: "M8 2.5L13.5 8 8 13.5 2.5 8z",
  image: "M2.5 3.5h11v9h-11zM2.5 11l3.5-3.5 3 3 2-2 2.5 2.5",
  junction: "M8 6.5a1.5 1.5 0 100 3 1.5 1.5 0 000-3zM2 8h4.5M9.5 8H14",
  mlp: "M2.5 4.5h11v7h-11zM5.5 8h.01M8 8h.01M10.5 8h.01",
  cnn: "M2.5 6.5h8v6h-8zM4.5 4.5h8v6M6.5 2.5h7v6",
  attention: "M2.5 5.5h11v8h-11zM5 2.5v3M8 2.5v3M11 2.5v3",
  "add-norm": "M2.5 4.5h11v7h-11zM8 6v4M6 8h4",
  concat: "M3.5 3.5h3v9h-3zM9.5 3.5h3v9h-3z",
  tensor: "M2.5 6.5h8v6h-8zM2.5 6.5l3-3h8l-3 3M13.5 3.5v6l-3 3",
  matrix: "M3 3h10v10H3zM3 6.3h10M3 9.6h10M6.3 3v10M9.6 3v10",
  graph: "M4 4.5a1.5 1.5 0 100 .1M12 5a1.5 1.5 0 100 .1M8 12a1.5 1.5 0 100 .1M5 5l6 .3M4.6 5.8L7.4 11M11.4 6.3L8.6 11",
  inset: "M8 2.5l5 2.8v5.4l-5 2.8-5-2.8V5.3z",
  prediction: "M2.5 4.5h11v7h-11zM5 8h6M9 6l2 2-2 2",
  loss: "M2.5 4.5h11v7h-11zM5 10l2-3 2 2 2-3",
  "feature-strip": "M2 6h12v4H2zM5 6v4M8 6v4M11 6v4",
  sequence: "M1.5 6h3v4h-3zM6.5 6h3v4h-3zM11.5 6h3v4h-3z",
  volume: "M2.5 6.5h7v7h-7zM2.5 6.5l3-3h7l-3 3M12.5 3.5v7l-3 3",
  construct: "M1.5 11h13M3.5 11V6.5h3.5M6 5l1.5 1.5L6 8M8.5 9h3.5l1.5 2-1.5 2H8.5z",
  plasmid: "M8 2.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM8 2.5a5.5 5.5 0 015.2 3.7",
  protein: "M1.5 8h13M3 6h4v4H3zM9.5 5.5h4v5h-4z",
  tree: "M2.5 3.5h4v4h-4M6.5 5.5h7M2.5 7.5v5h11M2.5 3.5v4",
  wellplate: "M2.5 3.5h11v9h-11zM5 6h.01M8 6h.01M11 6h.01M5 10h.01M8 10h.01M11 10h.01",
  timeline: "M1.5 8h13M4 8a1 1 0 100 .1M8 8a1 1 0 100 .1M12 8a1 1 0 100 .1M4 11.5h8",
  structure: "M2 11c1.5-6 3-6 4 0s2.5 6 4 0 2.5-6 4 0",
  row: "M1.5 5h3.5v6H1.5zM6.25 5h3.5v6h-3.5zM11 5h3.5v6H11z",
  column: "M4.5 1.5h7v3.5h-7zM4.5 6.25h7v3.5h-7zM4.5 11h7v3.5h-7z",
  grid: "M2.5 2.5h4.5v4.5H2.5zM9 2.5h4.5v4.5H9zM2.5 9h4.5v4.5H2.5zM9 9h4.5v4.5H9z",
  module: "M1.5 3.5h13v10h-13zM1.5 6h13M3.5 8.5h4v3h-4zM8.5 8.5h4v3h-4z",
  edge: "M2 8h10M9 5l3 3-3 3",
  net: "M2 8h5M7 8l5-4M7 8l5 4M7 8h5",
};

function glyph(name) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  node.setAttribute("viewBox", "0 0 16 16");
  node.setAttribute("class", "glyph");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", GLYPHS[name] || GLYPHS.block);
  node.append(path);
  return node;
}

const words = (label) => (Array.isArray(label) ? label.map((run) => run?.text ?? "").join("") : label ?? "");
const plain = (label) => words(label).replace(/\$|\*\*|\*|`/g, "");
const groupGlyph = (group) => (group.role === "module" ? "module" : ["grid", "row", "column"].includes(group.layout?.kind) ? group.layout.kind : "column");

export function mount(studio, main) {
  if (!document.querySelector('link[href="/static/kinds/figure/editor.css"]')) {
    document.head.append(h("link", { rel: "stylesheet", href: "/static/kinds/figure/editor.css" }));
  }
  const catalog = studio.catalog.editor;
  const parts = catalog.parts;
  const state = { tab: "parts", selected: [], model: null, zoom: null, connecting: null, chain: true, closed: new Set() };
  let messages = [];

  // -- the model: the figure as its file writes it --
  const model = () => state.model;
  const nodeOf = (id) => model()?.nodes.find((n) => n.id === id);
  const groupOf = (id) => model()?.groups.find((g) => g.id === id);
  const edgeOf = (id) => model()?.edges.find((e) => e.id === id);
  const netOf = (id) => model()?.nets.find((n) => n.id === id);
  const typeOf = (id) => (nodeOf(id) ? "node" : groupOf(id) ? "group" : edgeOf(id) ? "edge" : netOf(id) ? "net" : null);
  const parentOf = (id) => model()?.groups.find((g) => (g.children || []).includes(id));
  const partOf = (node) => parts[node?.kind || "block"];
  const nodeOfRef = (ref) => (nodeOf(ref) ? ref : String(ref).slice(0, String(ref).lastIndexOf(".")));
  const nameOf = (id) => {
    const node = nodeOf(id);
    if (node) return plain(node.label) || partOf(node)?.title || node.kind;
    const group = groupOf(id);
    if (group) return plain(group.label) || (group.id === model()?.root ? "Figure" : group.layout?.kind || "group");
    const edge = edgeOf(id);
    if (edge) return `${nameOf(nodeOfRef(edge.from))} → ${nameOf(nodeOfRef(edge.to))}`;
    return id;
  };

  function setModel(next) {
    if (!next) return;
    state.model = next;
    state.selected = state.selected.filter((id) => typeOf(id));
    renderOutline();
    renderInspector();
    renderBar();
  }

  // -- edits: made by the server to the file, one at a time --
  const queue = [];
  let running = false;
  function act(action, { merge = null, select: choose = true, then = null } = {}) {
    // Typing in one field: only its latest words wait to be sent.
    if (merge) {
      const waiting = queue.findIndex((job) => job.merge === merge);
      if (waiting >= 0) queue.splice(waiting, 1);
    }
    queue.push({ action, merge, choose, then });
    run();
  }
  async function run() {
    if (running) return;
    running = true;
    try {
      while (queue.length) {
        const job = queue.shift();
        for (let attempt = 0; attempt < 3; attempt += 1) {
          const sent = studio.doc.text;
          let result;
          try {
            result = await studio.api("/api/act", { file: studio.file, document: studio.doc, action: job.action });
          } catch (error) {
            toast(error.message, { kind: "error", icon: "error", seconds: 6 });
            break;
          }
          if (studio.doc.text !== sent) continue; // changed meanwhile: made again on the file as it is now
          studio.change((d) => ({ ...d, text: result.document.text }), { merge: job.merge });
          if (result.model) setModel(result.model);
          if (job.choose && result.select?.length) select(result.select);
          job.then?.(result);
          break;
        }
      }
    } finally {
      running = false;
    }
  }
  const update = (target, values, merge = null) => act({ do: "update", target, values }, { merge, select: false });

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
  const addButton = ui.button("Add", (event) => addPalette(event.currentTarget), { icon: "plus", kind: "primary", title: "Add a part (A)" });
  const connectButton = ui.button("Connect", () => toggleConnect(), { kind: "ghost", icon: "right", title: "Draw a line from one part to another (C)" });
  const gatherButton = ui.button("Group", (event) => menu(event.currentTarget, catalog.groups.map((group) => ({
    label: group.title, hint: group.hint, run: () => gather(group),
  }))), { kind: "ghost", icon: "layout", title: "Gather the chosen parts into a row, column, grid or module (G)" });
  const deleteButton = ui.button("", () => remove(), { kind: "ghost", icon: "trash", title: "Delete (⌫)" });
  studio.tools.append(h("span.docbar-title", {}, icon("figure"), "Figure"), h("span.sep"), addButton, connectButton, gatherButton, deleteButton);
  studio.actions.append(ui.button("Export", (event) => menu(event.currentTarget, [
    { icon: "export", label: "Editable SVG", hint: "Inkscape layers, live text", run: () => studio.exportFiles(["editable"]) },
    { icon: "export", label: "PDF", hint: "Embedded fonts", run: () => studio.exportFiles(["pdf"]) },
    { icon: "image", label: "PNG", run: () => studio.exportFiles(["png"]) },
    "-",
    { icon: "export", label: "Everything", run: () => studio.exportFiles(["editable", "portable", "pdf", "png"]) },
  ], { align: "end" }), { icon: "export", kind: "ghost" }));

  function renderBar() {
    const chosen = state.selected;
    deleteButton.disabled = !chosen.length || chosen.includes(model()?.root);
    connectButton.classList.toggle("on", Boolean(state.connecting));
    gatherButton.disabled = !model();
    addButton.disabled = !model();
  }

  // -- choosing --
  function select(ids, { reveal = true } = {}) {
    state.selected = [...new Set((Array.isArray(ids) ? ids : [ids]).filter(Boolean))];
    placeMarks();
    renderOutline();
    renderInspector();
    renderBar();
    const id = state.selected[state.selected.length - 1];
    if (id && reveal) {
      outlineBody.querySelector(`.tree-row[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "nearest" });
      if (state.tab === "source") find(id);
    }
    studio.focus(id ? { label: nameOf(id), id } : null);
  }
  const chosenOne = () => (state.selected.length === 1 ? state.selected[0] : null);

  // -- adding --
  function placement() {
    const id = chosenOne();
    if (id && groupOf(id)) return { parent: id, text: id === model().root ? "Adds at the end of the figure" : `Adds inside ${nameOf(id)}` };
    if (id && nodeOf(id)) return { after: id, source: state.chain ? id : null, text: `Adds after ${nameOf(id)}`, from: id };
    return { text: "Adds at the end of the figure" };
  }

  function addPalette(anchor) {
    if (!model()) return;
    const where = placement();
    const search = ui.input({ placeholder: "Find a part…" });
    const grid = h("div.add-grid.scroll-thin");
    const tile = (kind, part) => h(`button.add-tile${part.unavailable ? ".off" : ""}`, {
      type: "button", title: part.unavailable ? `${part.hint} (${part.unavailable})` : part.hint, disabled: Boolean(part.unavailable),
      onclick: () => { closeMenu(); addPart(kind, where); },
    }, glyph(kind), h("span", {}, part.title));
    const render = () => {
      const query = search.value.trim().toLowerCase();
      const matches = (part) => !query || `${part.title} ${part.hint} ${part.kind}`.toLowerCase().includes(query);
      const sections = catalog.categories.map((category) => {
        const found = Object.entries(parts).filter(([, part]) => part.category === category && matches(part));
        return found.length ? [h("div.add-head", {}, category), h("div.add-tiles", {}, found.map(([kind, part]) => tile(kind, part)))] : null;
      }).filter(Boolean);
      const groups = catalog.groups.filter((group) => !query || `${group.title} ${group.hint}`.toLowerCase().includes(query));
      if (groups.length) {
        sections.push([h("div.add-head", {}, "Layout"), h("div.add-tiles", {}, groups.map((group) =>
          h("button.add-tile", { type: "button", title: group.hint, onclick: () => { closeMenu(); gather(group, where); } }, glyph(group.kind), h("span", {}, group.title))))]);
      }
      clear(grid, sections.length ? sections : h("div.empty", {}, "No part by that name."));
    };
    search.addEventListener("input", render);
    // Enter takes the best match: a title that starts with the words, then one that
    // holds them, then a description that does.
    const best = () => {
      const query = search.value.trim().toLowerCase();
      const ranked = [...grid.querySelectorAll(".add-tile:not(.off)")].map((tile) => {
        const title = tile.textContent.trim().toLowerCase();
        const rank = !query ? 0 : title.startsWith(query) ? 0 : title.includes(query) ? 1 : 2;
        return { tile, rank };
      });
      ranked.sort((a, b) => a.rank - b.rank);
      return ranked[0]?.tile;
    };
    search.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); best()?.click(); }
    });
    const chain = where.from ? ui.toggle({ value: state.chain, label: `Connect from ${nameOf(where.from)}`, onChange: (value) => {
      state.chain = value;
      where.source = value ? where.from : null;
    } }) : null;
    render();
    popover(anchor, h("div.add-palette", {}, search, h("div.add-where", {}, icon("info"), h("span", {}, where.text)), chain, grid), { className: "add-menu" });
    setTimeout(() => search.focus(), 20);
  }

  async function addPart(kind, where = placement()) {
    const part = parts[kind];
    const action = { do: "add", kind, parent: where.parent || null, after: where.after || null, source: where.source || null };
    if (part.needs_file) {
      const field = part.fields.find((item) => item.type === "file");
      const file = await chooseFile({ title: `Choose the ${part.title.toLowerCase()}'s file`, types: field.types });
      if (!file) return;
      action.node = { properties: { source: file } };
    }
    act(action);
  }

  function gather(group, where = null) {
    const chosen = state.selected.filter((id) => nodeOf(id) || (groupOf(id) && id !== model().root));
    const at = where || placement();
    act({ do: "gather", ids: chosen, layout: group.layout, role: group.role || null,
          parent: chosen.length ? null : at.parent || null, after: chosen.length ? null : at.after || null });
  }

  function remove(ids = state.selected) {
    const gone = ids.filter((id) => id !== model()?.root);
    if (!gone.length) return;
    act({ do: "delete", ids: gone }, { select: false, then: () => select([]) });
  }

  function duplicate(ids = state.selected) {
    const chosen = ids.filter((id) => nodeOf(id) || (groupOf(id) && id !== model()?.root));
    if (chosen.length) act({ do: "duplicate", ids: chosen });
  }

  // -- connecting --
  function toggleConnect(force) {
    const on = force ?? !state.connecting;
    if (!on) { state.connecting = null; showHint(); renderBar(); return; }
    const from = chosenOne();
    state.connecting = { source: from && nodeOf(from) ? from : null };
    showHint();
    renderBar();
  }
  function showHint() {
    const connecting = state.connecting;
    hint.hidden = !connecting;
    stage.classList.toggle("connecting", Boolean(connecting));
    if (!connecting) return;
    clear(hint, icon("right"),
      connecting.source ? h("span", {}, "Click the part that ", h("b", {}, nameOf(connecting.source)), " leads to") : h("span", {}, "Click the part the line starts from"),
      h("span.kbd", {}, "Esc"));
  }
  function connectTo(id) {
    const connecting = state.connecting;
    if (!nodeOf(id)) return;
    if (!connecting.source) { connecting.source = id; select([id], { reveal: false }); showHint(); return; }
    if (id === connecting.source) return;
    const source = connecting.source;
    state.connecting = null;
    showHint();
    renderBar();
    act({ do: "connect", source, target: id });
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
    if (inline) placeInline();
  }
  new ResizeObserver(() => fitPage()).observe(stage);

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
  function placeMarks() {
    clear(marks, state.selected.map((id) => {
      const where = boxOf(id);
      if (!where) return null;
      const group = typeOf(id) === "group";
      return h(`div.fig-mark${group ? ".group" : ""}`, { style: {
        left: `${where.left}px`, top: `${where.top}px`, width: `${where.width}px`, height: `${where.height}px` } },
      group ? h("span.fig-mark-label", {}, nameOf(id)) : null);
    }));
  }
  // Pieces drawn inside a part carry ids of their own: the part is what is chosen.
  const hitId = (target) => {
    const line = target.closest?.("[data-hit-for]");
    if (line) return line.dataset.hitFor;
    for (let at = target; at && at !== page; at = at.parentElement) {
      if (at.matches?.("[data-flexo-entity][id]") && typeOf(at.id)) return at.id;
    }
    return null;
  };
  // A click on a part's empty space (inside a protein map, between a row's parts)
  // chooses the smallest part, then the smallest group, whose box holds the point.
  function around(event) {
    let best = null;
    for (const kind of ["node", "group"]) {
      const items = kind === "node" ? model()?.nodes || [] : (model()?.groups || []).filter((g) => g.id !== model().root);
      for (const item of items) {
        const box = elementOf(item.id)?.getBoundingClientRect();
        if (!box || !box.width || event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) continue;
        const area = box.width * box.height;
        if (!best || area < best.area) best = { id: item.id, area };
      }
      if (best) return best.id;
    }
    return null;
  }
  page.addEventListener("click", (event) => {
    if (event.target.closest(".fig-inline")) return;
    const id = hitId(event.target) || around(event);
    if (state.connecting) { if (id) connectTo(id); return; }
    if (event.shiftKey || event.metaKey || event.ctrlKey) {
      if (!id) return;
      select(state.selected.includes(id) ? state.selected.filter((item) => item !== id) : [...state.selected, id]);
      return;
    }
    select(id ? [id] : []);
  });
  stage.addEventListener("click", (event) => { if (event.target === stage && !state.connecting) select([]); });
  page.addEventListener("dblclick", (event) => {
    const id = hitId(event.target) || around(event);
    if (id && typeOf(id) !== "net") openInline(id);
  });
  page.addEventListener("mousemove", (event) => {
    const id = hitId(event.target) || around(event);
    const where = id && boxOf(id);
    hover.hidden = !where;
    if (where) Object.assign(hover.style, { left: `${where.left}px`, top: `${where.top}px`, width: `${where.width}px`, height: `${where.height}px` });
  });
  page.addEventListener("mouseleave", () => { hover.hidden = true; });

  // Lines are thin: each is given a wide, invisible twin to click.
  function widenLines(svg) {
    for (const line of svg.querySelectorAll('[data-flexo-entity="connector"][id], [data-flexo-entity="net"][id]')) {
      for (const path of line.querySelectorAll("path")) {
        if (!path.getAttribute("d")) continue;
        const twin = document.createElementNS("http://www.w3.org/2000/svg", "path");
        twin.setAttribute("d", path.getAttribute("d"));
        if (path.getAttribute("transform")) twin.setAttribute("transform", path.getAttribute("transform"));
        twin.setAttribute("class", "hit-line");
        twin.dataset.hitFor = line.id;
        path.after(twin);
      }
    }
  }

  // -- words typed on the drawing --
  let inline = null;
  function openInline(id) {
    closeInline(false);
    const kind = typeOf(id);
    const item = kind === "node" ? nodeOf(id) : kind === "edge" ? edgeOf(id) : groupOf(id);
    if (!item || !boxOf(id)) return;
    const original = words(item.label);
    const field = ui.markup({ value: original, rows: 1, colours: false });
    const box = h("div.fig-inline", {}, field,
      h("div.inline-foot", {}, h("span", {}, "Enter to keep · Esc to leave"), h("span", {}, "$maths$ · *emphasis*")));
    page.append(box);
    inline = { id, kind, field: field.area, original, box };
    placeInline();
    field.area.focus();
    field.area.select();
    field.area.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); closeInline(true); }
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeInline(false); }
    });
    field.area.addEventListener("blur", () => setTimeout(() => { if (inline?.box === box && !box.contains(document.activeElement)) closeInline(true); }, 0));
  }
  function placeInline() {
    const where = boxOf(inline.id);
    if (!where) return;
    Object.assign(inline.box.style, { left: `${where.left}px`, top: `${where.top + where.height + 6}px`, minWidth: `${Math.max(where.width, 240)}px` });
  }
  function closeInline(keep) {
    if (!inline) return;
    const { id, kind, field, original, box } = inline;
    inline = null;
    box.remove();
    if (keep && field.value !== original) update({ type: kind, id }, { label: field.value });
  }

  // -- the outline --
  const outlineBody = h("div.tree");
  function renderOutline() {
    if (state.tab !== "parts") return;
    const figure = model();
    if (!figure) { clear(outlineBody, h("div.empty", {}, "The parts appear once the file reads.")); return; }
    const row = (id, depth) => {
      const node = nodeOf(id), group = groupOf(id);
      const isRoot = id === figure.root;
      const children = group ? group.children || [] : [];
      const open = !state.closed.has(id);
      const item = h(`div.tree-row${state.selected.includes(id) ? ".on" : ""}${isRoot ? ".root" : ""}`, {
        draggable: isRoot ? "false" : "true", dataset: { id }, style: { paddingLeft: `${6 + depth * 14}px` },
        onclick: (event) => {
          if (event.shiftKey || event.metaKey || event.ctrlKey) select(state.selected.includes(id) ? state.selected.filter((x) => x !== id) : [...state.selected, id]);
          else select([id]);
        },
        ondblclick: () => (node ? openInline(id) : null),
      },
      group && children.length ? h(`button.tree-caret${open ? ".open" : ""}`, { type: "button", onclick: (event) => {
        event.stopPropagation();
        if (open) state.closed.add(id); else state.closed.delete(id);
        renderOutline();
      } }, icon("chevron")) : h("span.tree-caret"),
      node ? glyph(node.kind || "block") : group ? glyph(groupGlyph(group)) : glyph("block"),
      h("span.tree-name", {}, isRoot ? "Figure" : nameOf(id)),
      h("span.tree-id", {}, isRoot ? "" : id));
      outlineDrop(item, id, isRoot);
      if (!isRoot) outlineDrag(item, id);
      return [item, group && open ? children.map((child) => row(child, depth + 1)) : null];
    };
    const lines = [...figure.edges, ...figure.nets.map((net) => ({ ...net, net: true }))];
    clear(outlineBody,
      h("div.tree-head", {}, "Parts", h("span.count", {}, figure.nodes.length)),
      groupOf(figure.root) ? row(figure.root, 0) : null,
      h("div.tree-head", {}, "Lines", h("span.count", {}, lines.length)),
      lines.length ? lines.map((line) => h(`div.tree-row.line${state.selected.includes(line.id) ? ".on" : ""}`, {
        dataset: { id: line.id }, onclick: () => select([line.id]),
      }, h("span.tree-caret"), glyph(line.net ? "net" : "edge"),
      h("span.tree-name", {}, line.net ? `${nameOf(nodeOfRef(line.sources?.[0] || ""))} → ${(line.targets || []).map((t) => nameOf(nodeOfRef(t))).join(", ")}` : nameOf(line.id)),
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
    if (groupOf(id) && y > 0.28 && y < 0.72) return "into";
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
        index = (groupOf(id).children || []).filter((child) => child !== moving).length;
      } else {
        const holder = parentOf(id);
        if (!holder) return;
        parent = holder.id;
        const siblings = (holder.children || []).filter((child) => child !== moving);
        index = siblings.indexOf(id) + (zone === "after" ? 1 : 0);
      }
      act({ do: "move", id: moving, parent, index });
    });
  }

  // -- the source --
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
    else { numbers(); const id = chosenOne(); if (id) find(id); }
  }
  showTab();

  // -- the inspector --
  function renderInspector() {
    // Parts with tables (a protein's features, a plate's groups) get the room a table needs.
    const one = chosenOne();
    root.classList.toggle("wide", Boolean(one && nodeOf(one) && (partOf(nodeOf(one))?.fields || []).some((field) => field.type === "records")));
    keepFocus(inspectorBody, () => {
      const figure = model();
      if (!figure) { clear(inspectorBody, h("div.empty", {}, "The file does not read as a figure. Fix it in Source; the messages under the drawing say where.")); return; }
      const chosen = state.selected;
      if (chosen.length > 1) clear(inspectorBody, manyPanel(chosen));
      else if (!chosen.length) clear(inspectorBody, figurePanel());
      else {
        const id = chosen[0];
        const kind = typeOf(id);
        clear(inspectorBody, kind === "node" ? nodePanel(nodeOf(id)) : kind === "group" ? groupPanel(groupOf(id))
          : kind === "edge" ? edgePanel(edgeOf(id)) : kind === "net" ? netPanel(netOf(id)) : figurePanel());
      }
    });
  }

  function crumbs(id) {
    const trail = [];
    for (let at = parentOf(id); at; at = parentOf(at.id)) trail.unshift(at.id);
    return h("div.crumbs", {}, trail.map((group, index) => [
      index ? icon("chevron") : null,
      h("button.crumb", { type: "button", onclick: () => select([group]) }, group === model().root ? "Figure" : nameOf(group)),
    ]), trail.length ? icon("chevron") : null, h("span.crumb.here", {}, nameOf(id)));
  }

  function headActions(id) {
    const holder = parentOf(id);
    const siblings = holder?.children || [];
    const at = siblings.indexOf(id);
    return [
      ui.button("", () => act({ do: "step", id, delta: -1 }), { kind: "ghost", small: true, icon: "up", title: "Earlier (⌥↑)", disabled: at <= 0 }),
      ui.button("", () => act({ do: "step", id, delta: 1 }), { kind: "ghost", small: true, icon: "down", title: "Later (⌥↓)", disabled: at < 0 || at >= siblings.length - 1 }),
      ui.button("", () => duplicate([id]), { kind: "ghost", small: true, icon: "copy", title: "Duplicate (⌘D)" }),
      ui.button("", () => remove([id]), { kind: "ghost", small: true, icon: "trash", title: "Delete (⌫)" }),
    ];
  }

  function idField(id, type) {
    const input = ui.input({ value: id, mono: true, key: `id:${id}` });
    const keep = () => {
      const to = input.value.trim();
      if (!to || to === id) { input.value = id; return; }
      act({ do: "rename", id, to });
    };
    input.addEventListener("change", keep);
    input.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); input.blur(); } });
    return ui.field("Id", input, { hint: type === "group" ? "" : "Lines name it" });
  }

  function titleBlock(picture, name, hintText) {
    return h("div.insp-title", {}, picture, h("div.insp-words", {}, h("div.insp-name", {}, name), hintText ? h("div.insp-hint", {}, hintText) : null));
  }

  function nodePanel(node) {
    const part = partOf(node) || { title: node.kind, fields: [], hint: "" };
    const kinds = Object.entries(parts).filter(([kind, p]) => !p.needs_file || kind === node.kind);
    const retype = ui.select({ value: node.kind || "block", options: kinds.map(([kind, p]) => ({ value: kind, label: p.title })),
      onChange: (value) => update({ type: "node", id: node.id }, { kind: value }) });
    const lines = model().edges.filter((edge) => nodeOfRef(edge.from) === node.id || nodeOfRef(edge.to) === node.id);
    return [
      h("div.section.insp-top", {}, crumbs(node.id),
        h("div.insp-row", {}, titleBlock(glyph(node.kind || "block"), part.title, part.hint), h("div.insp-actions", {}, headActions(node.id)))),
      h("div.section", {}, h("div.grid2", {}, idField(node.id, "node"), ui.field("Kind", retype)),
        fields(part.fields, node, (values, merge) => update({ type: "node", id: node.id }, values, merge), `node:${node.id}`)),
      h("div.section", {}, h("div.section-title", {}, "Lines", h("span.count", {}, lines.length)),
        lines.length ? h("div.line-list", {}, lines.map((edge) => h("div.line-row", {},
          h("button.link", { type: "button", onclick: () => select([edge.id]) },
            nodeOfRef(edge.from) === node.id ? ["to ", h("b", {}, nameOf(nodeOfRef(edge.to)))] : ["from ", h("b", {}, nameOf(nodeOfRef(edge.from)))],
            edge.label ? h("span.muted", {}, ` · ${plain(edge.label)}`) : null),
          ui.button("", () => remove([edge.id]), { kind: "ghost", small: true, icon: "close", title: "Remove the line" })))) : null,
        h("div.row", {},
          ui.button("Connect to…", () => { select([node.id]); toggleConnect(true); }, { small: true, icon: "right" }),
          ui.button("Add after…", (event) => { const anchor = event.currentTarget; select([node.id]); addPalette(anchor); }, { small: true, icon: "plus" }))),
    ];
  }

  function groupPanel(group) {
    const isRoot = group.id === model().root;
    const count = (group.children || []).length;
    return [
      h("div.section.insp-top", {}, isRoot ? null : crumbs(group.id),
        h("div.insp-row", {},
          titleBlock(glyph(groupGlyph(group)), isRoot ? "The figure's layout" : group.role === "module" ? "Module" : "Group",
            `${count} part${count === 1 ? "" : "s"}, ${group.layout?.kind || "column"}`),
          isRoot ? null : h("div.insp-actions", {}, headActions(group.id))),
        isRoot ? null : ui.button("Ungroup", () => act({ do: "ungroup", id: group.id }), { small: true, title: "Its parts take its place" })),
      h("div.section", {}, isRoot || group.implied ? null : idField(group.id, "group"),
        fields(catalog.group_fields, group, (values, merge) => update({ type: "group", id: group.id }, values, merge), `group:${group.id}`)),
      h("div.section", {}, h("div.section-title", {}, "Holds", h("span.count", {}, count)),
        h("div.line-list", {}, (group.children || []).map((child, index) => h("div.line-row", {},
          h("button.link", { type: "button", onclick: () => select([child]) }, nodeOf(child) ? glyph(nodeOf(child).kind || "block") : glyph(groupGlyph(groupOf(child) || {})), nameOf(child)),
          ui.button("", () => act({ do: "step", id: child, delta: -1 }, { select: false }), { kind: "ghost", small: true, icon: "up", title: "Earlier", disabled: index === 0 }),
          ui.button("", () => act({ do: "step", id: child, delta: 1 }, { select: false }), { kind: "ghost", small: true, icon: "down", title: "Later", disabled: index === count - 1 })))),
        ui.button("Add inside…", (event) => { const anchor = event.currentTarget; select([group.id]); addPalette(anchor); }, { small: true, icon: "plus" })),
    ];
  }

  function edgePanel(edge) {
    const options = model().nodes.flatMap((node) => [node.id, ...(node.ports || []).map((port) => `${node.id}.${port}`)]);
    const end = (key) => ui.combo({ value: edge[key], options, mono: true, key: `edge:${edge.id}:${key}`, onChange: (text) => {
      if (options.includes(text) && text !== edge[key]) act({ do: "update", target: { type: "edge", id: edge.id }, values: { [key]: text } }, { select: false, then: () => select([]) });
    } });
    return [
      h("div.section.insp-top", {},
        h("div.insp-row", {}, titleBlock(glyph("edge"), "Line", nameOf(edge.id)),
          h("div.insp-actions", {}, ui.button("", () => remove([edge.id]), { kind: "ghost", small: true, icon: "trash", title: "Delete (⌫)" })))),
      h("div.section", {}, h("div.grid2", {}, ui.field("From", end("from")), ui.field("To", end("to"))),
        fields(catalog.edge_fields, edge, (values, merge) => update({ type: "edge", id: edge.id }, values, merge), `edge:${edge.id}`)),
    ];
  }

  function netPanel(net) {
    return [
      h("div.section.insp-top", {},
        h("div.insp-row", {}, titleBlock(glyph("net"), "Branching line", `${(net.sources || []).join(", ")} → ${(net.targets || []).join(", ")}`),
          h("div.insp-actions", {}, ui.button("", () => remove([net.id]), { kind: "ghost", small: true, icon: "trash", title: "Delete (⌫)" })))),
      h("div.section", {}, fields([catalog.edge_fields[0]], net, (values, merge) => update({ type: "net", id: net.id }, values, merge), `net:${net.id}`),
        h("div.hint-line", {}, "One value into several ports, as into attention's query, key, and value. Its ends are edited in Source.")),
    ];
  }

  function figurePanel() {
    const figure = model();
    const counts = `${figure.nodes.length} parts · ${figure.edges.length + figure.nets.length} lines`;
    return [
      h("div.section.insp-top", {}, titleBlock(icon("figure"), "Figure", counts)),
      h("div.section", {}, fields(catalog.figure_fields, { figure: figure.figure }, (values, merge) => update({ type: "figure" }, values, merge), "figure")),
      h("div.section", {}, h("div.section-title", {}, "Making it"),
        h("ul.how", {},
          h("li", {}, h("b", {}, "Add"), " a part (A). With a part chosen, the new one comes after it, a line between them."),
          h("li", {}, h("b", {}, "Connect"), " (C): click where a line starts, then where it ends."),
          h("li", {}, "Double-click a part to change its words; ⇧-click to choose several, then ", h("b", {}, "Group"), " (G)."),
          h("li", {}, "Drag parts in the list on the left to move them between rows and columns.")),
        h("div.row", {}, ui.button("Add a part", (event) => addPalette(event.currentTarget), { small: true, icon: "plus" }),
          ui.button("The layout", () => select([figure.root]), { small: true, icon: "layout" }))),
    ];
  }

  function manyPanel(ids) {
    const gatherable = ids.every((id) => nodeOf(id) || (groupOf(id) && id !== model().root));
    return [
      h("div.section.insp-top", {}, titleBlock(icon("layout"), `${ids.length} chosen`, ids.map(nameOf).join(", "))),
      h("div.section", {}, h("div.section-title", {}, "Gather them into"),
        h("div.gather-tiles", {}, catalog.groups.map((group) => h("button.add-tile", { type: "button", disabled: !gatherable, title: group.hint, onclick: () => gather(group) },
          glyph(group.kind), h("span", {}, group.title)))),
        gatherable ? null : h("div.hint-line", {}, "Lines cannot be gathered; choose parts."),
        h("div.row", {}, ui.button("Duplicate", () => duplicate(ids), { small: true, icon: "copy" }),
          ui.button("Delete", () => remove(ids), { small: true, icon: "trash", kind: "danger" }))),
    ];
  }

  // -- fields, from the catalogue --
  const valueAt = (item, key) => key.split(".").reduce((at, part) => (at == null ? undefined : at[part]), item);
  function fields(list, item, write, scope) {
    const holds = (key, wanted) => {
      const value = valueAt(item, key) ?? list.find((f) => f.key === key)?.default;
      return Array.isArray(wanted) ? wanted.includes(value) : value === wanted;
    };
    const shown = list.filter((field) => !field.show || Object.entries(field.show).every(([key, wanted]) => holds(key, wanted)));
    return h("div.fields", {}, shown.map((field) => fieldControl(field, item, write, scope)));
  }

  function fieldControl(field, item, write, scope) {
    const key = `${scope}:${field.key}`;
    const value = valueAt(item, field.key);
    const set = (next) => write({ [field.key]: next }, key);
    const options = { hint: field.hint };
    switch (field.type) {
      case "markup":
        return ui.field(field.label, ui.markup({ value: words(value), rows: 1, key, colours: false, onInput: set }), options);
      case "text":
        return ui.field(field.label, ui.input({ value: value ?? "", key, onInput: set }), options);
      case "length":
        return ui.field(field.label, ui.input({ value: value ?? "", key, placeholder: "auto", mono: true, onInput: (text) => {
          const clean = text.trim();
          if (!clean) set(null);
          else if (/^\d+(\.\d+)?$/.test(clean)) set(`${clean}pt`);
          else if (/^\d+(\.\d+)?\s*(pt|mm|cm|in|px)$/.test(clean)) set(clean);
        } }), options);
      case "code":
        return ui.field(field.label, ui.textarea({ value: value ?? "", rows: 2, mono: true, key, onInput: set }), options);
      case "integer":
      case "number":
        return ui.field(field.label, ui.number({ value: value ?? "", key, min: field.min, step: field.type === "integer" ? 1 : "any",
          placeholder: field.default !== undefined ? String(field.default) : "auto",
          onChange: (number) => set(number === null ? null : field.type === "integer" ? Math.round(number) : number) }), options);
      case "bool": {
        const on = value ?? field.default ?? false;
        return ui.field(field.label, ui.toggle({ value: on, onChange: (next) => set(next === (field.default ?? false) ? null : next) }), { ...options, inline: true });
      }
      case "choice":
        return ui.field(field.label, ui.select({ value: value ?? field.default ?? "", options: field.options.map((option) => ({ value: option, label: option === "" ? "None" : String(option) })),
          onChange: (next) => {
            const typed = field.options.find((option) => String(option) === next);
            set(typed === field.default || typed === "" ? null : typed);
          } }), options);
      case "combo":
        return ui.field(field.label, ui.combo({ value: value ?? "", options: field.options.map(String), key, placeholder: field.default ?? "", onChange: set }), options);
      case "pair": {
        const pair = Array.isArray(value) ? [...value] : ["", ""];
        const half = (index) => ui.input({ value: pair[index] ?? "", key: `${key}:${index}`, placeholder: field.labels?.[index], onInput: (text) => {
          pair[index] = text;
          set(pair.some((part) => part) ? pair.map((part) => part ?? "") : null);
        } });
        return ui.field(field.label, h("div.grid2", {}, half(0), half(1)), options);
      }
      case "file":
        return ui.field(field.label, h("div.row", {}, ui.input({ value: value ?? "", mono: true, key, onChange: set }),
          h("span.fixed", {}, ui.button("Choose…", async () => { const file = await chooseFile({ title: "Choose a file", types: field.types }); if (file) set(file); }, { small: true, icon: "folder" }))), options);
      case "records":
        return recordsControl(field, Array.isArray(value) ? value : [], set, key, valueAt(item, "properties.length"));
      default:
        return null;
    }
  }

  // A table of records: a plasmid's features, a plate's groups, a timeline's events.
  function recordsControl(field, value, set, key, length) {
    const rows = value.map((row) => ({ ...(row && typeof row === "object" ? row : {}) }));
    const write = () => set(rows.map((row) => Object.fromEntries(Object.entries(row).filter(([, v]) => v !== "" && v !== null && v !== undefined))));
    const cell = (row, index, column) => {
      const cellKey = `${key}:${index}:${column.name}`;
      const current = row[column.name];
      const change = (next) => { row[column.name] = next; write(); };
      if (column.type === "choice") {
        return ui.select({ value: current ?? "", options: column.options.map((option) => ({ value: option, label: option === "" ? "–" : option })),
          onChange: (next) => change(next || null) });
      }
      if (column.type === "integer" || column.type === "number") {
        return ui.number({ value: current ?? "", key: cellKey, step: column.type === "integer" ? 1 : "any",
          onChange: (number) => change(number === null ? null : column.type === "integer" ? Math.round(number) : number) });
      }
      const input = ui.input({ value: current ?? "", key: cellKey, placeholder: column.hint || "", onInput: (text) => change(text) });
      if (column.type !== "combo") return input;
      const id = `opts-${Math.random().toString(36).slice(2)}`;
      input.setAttribute("list", id);
      return h("div.cell", {}, input, h("datalist", { id }, column.options.map((option) => h("option", { value: option }))));
    };
    const width = (column) => (column.type === "integer" || column.type === "number" ? "minmax(52px, .7fr)"
      : column.type === "choice" ? "minmax(92px, 1.2fr)"
        : column.name === "label" || column.name === "tips" ? "minmax(80px, 1.6fr)" : "minmax(56px, 1fr)");
    const template = `${field.columns.map(width).join(" ")} 24px`;
    return h("div.field.records", {},
      h("label.label", {}, field.label, h("span.hint", {}, `${rows.length}`)),
      field.hint ? h("div.hint-line", {}, field.hint) : null,
      h("div.records-scroll.scroll-thin", {}, h("div.records-table", { style: { gridTemplateColumns: template } },
        field.columns.map((column) => h("span.records-head", { title: column.hint || "" }, column.label)), h("span.records-head"),
        rows.map((row, index) => [
          ...field.columns.map((column) => cell(row, index, column)),
          ui.button("", () => { rows.splice(index, 1); write(); }, { kind: "ghost", small: true, icon: "close", title: "Remove the row" }),
        ]))),
      ui.button("Add a row", () => {
        // A new row starts as the catalogue says: "+N" is the last row's value and N more.
        const last = rows[rows.length - 1];
        const fresh = {};
        for (const [name, start] of Object.entries(field.row || { label: "New" })) {
          if (typeof start === "string" && /^\+\d+(\.\d+)?$/.test(start)) {
            const step = Number(start.slice(1));
            const next = typeof last?.[name] === "number" ? last[name] + step : typeof last?.at === "number" ? last.at + step : step;
            // Positions stay on the molecule: a new domain past the end is drawn at it.
            fresh[name] = typeof length === "number" ? Math.min(next, length) : next;
          } else if (start !== "") fresh[name] = start;
        }
        rows.push(fresh);
        write();
      }, { small: true, icon: "plus" }));
  }

  // -- files --
  function chooseFile({ title, types }) {
    return new Promise((resolve) => {
      let done = false;
      const finish = (value) => { if (!done) { done = true; resolve(value); box.close(); } };
      const list = h("div.list-rows", {}, h("div.empty", {}, h("div.spinner")));
      const accept = types.includes("image") ? "image/*,.svg" : ".pdb,.cif,.mmcif,.ent";
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
  const keys = (event) => {
    if (!studio.active || typing(event.target) || document.querySelector(".scrim, .menu")) return;
    const mod = event.metaKey || event.ctrlKey;
    if (event.key === "Escape") {
      if (state.connecting) { toggleConnect(false); return; }
      if (state.selected.length) { select([]); return; }
    }
    if (mod) {
      if (event.key.toLowerCase() === "d") { event.preventDefault(); duplicate(); }
      return;
    }
    if (event.key === "Backspace" || event.key === "Delete") { if (state.selected.length) { event.preventDefault(); remove(); } return; }
    if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
      const id = chosenOne();
      if (id) { event.preventDefault(); act({ do: "step", id, delta: event.key === "ArrowUp" ? -1 : 1 }); }
      return;
    }
    const key = event.key.toLowerCase();
    if (key === "a") { event.preventDefault(); addPalette(addButton); }
    else if (key === "c") { event.preventDefault(); toggleConnect(); }
    else if (key === "g") { event.preventDefault(); gatherButton.click(); }
    else if (key === "enter") { const id = chosenOne(); if (id && typeOf(id) !== "net") { event.preventDefault(); openInline(id); } }
  };
  document.addEventListener("keydown", keys);

  // -- what the drawing brings --
  const showMessages = () => {
    clear(note, messages.map((message) => h(`div.message.${message.severity}${message.where ? ".link" : ""}`,
      { onclick: () => {
        if (!message.where) return;
        if (message.where.startsWith("line ")) studio.reveal({ line: Number(message.where.slice(5)) });
        else if (typeOf(message.where)) select([message.where]);
      } },
      icon(message.severity === "error" ? "error" : message.severity === "note" ? "info" : "warning"),
      h("div", {}, message.text, message.where ? h("div.where", {}, message.where) : null))));
    if (state.tab === "source") numbers();
  };

  studio.on("drawn", (result) => {
    messages = result.messages || [];
    showMessages();
    if (result.info?.model) setModel(result.info.model);
    const drawn = result.pages[0];
    if (!drawn) {
      if (!page.querySelector("svg")) clear(stage, h("div.fig-empty", {}, icon("warning"), "Nothing to draw yet"));
      page.style.opacity = "0.45";
      return;
    }
    page.style.opacity = "";
    const keep = inline?.box;
    page.innerHTML = drawn.svg.replace(/^<\?xml[^>]*>\s*/, "");
    const svg = page.querySelector("svg");
    widenLines(svg);
    page.append(hover, marks);
    if (keep) page.append(keep);
    const view = svg.viewBox.baseVal;
    natural = view && view.width ? { width: view.width * 96 / 72, height: view.height * 96 / 72 } : { width: 600, height: 400 };
    svg.removeAttribute("width");
    svg.removeAttribute("height");
    if (page.parentNode !== stage) clear(stage, page);
    fitPage();
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
    if (where?.id) select([where.id]);
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
    { icon: "plus", label: "Add a part", run: () => addPalette(addButton) },
    ...Object.entries(parts).filter(([, part]) => !part.unavailable).map(([kind, part]) => ({ icon: "plus", label: `Add ${part.title.toLowerCase()}`, hint: part.hint, run: () => addPart(kind) })),
    { icon: "right", label: "Connect two parts", run: () => toggleConnect(true) },
    { icon: "export", label: "Export editable SVG", run: () => studio.exportFiles(["editable"]) },
    { icon: "export", label: "Export PDF", run: () => studio.exportFiles(["pdf"]) },
    { icon: "code", label: "Show the source", run: () => { state.tab = "source"; showTab(); } },
    { icon: "list", label: "Show the parts", run: () => { state.tab = "parts"; showTab(); } },
    ...(model() ? model().nodes.map((node) => ({ icon: "target", label: `Find ${nameOf(node.id)}`, hint: node.id, run: () => select([node.id]) })) : []),
  ];

  renderBar();
  renderInspector();
}
