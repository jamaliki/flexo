// Editing a figure's parts, wherever the figure is drawn: in the figure editor, or
// on a deck's slide. What is shared is here -- choosing parts on the drawing, the
// inspector's panels, the palette of parts, drawing lines, typing words on the
// drawing, and the keys -- and the page that holds the figure (the host) says
// where edits go and where the drawing is:
//
//   run(action, { merge })  makes an edit (the server does, to the figure's file or
//                           the deck's document) and answers { model, select };
//   element(id)             the drawn element of a part, by the figure's id;
//   idOf(elementId)         the figure's id for a drawn element's (a slide prefixes them);
//   box(id)                 where a part is drawn, in the overlay's pixels;
//   overlay                 the positioned element the words-on-the-drawing box sits in;
//   changed()               what is chosen, or the figure, changed: draw again;
//   chooseFile({ title, types }), focus(where), nothing()  (the panel when nothing is chosen).

import { h, clear, icon, ui, menu, popover, closeMenu, toast } from "/static/studio/studio.js";

// Small pictures of each kind of part, drawn on a 16-unit square.
export const GLYPHS = {
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

export function glyph(name) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  node.setAttribute("viewBox", "0 0 16 16");
  node.setAttribute("class", "glyph");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", GLYPHS[name] || GLYPHS.block);
  node.append(path);
  return node;
}

export const words = (label) => (Array.isArray(label) ? label.map((run) => run?.text ?? "").join("") : label ?? "");
export const plain = (label) => words(label).replace(/\$|\*\*|\*|`/g, "");
export const groupGlyph = (group) => (group.role === "module" ? "module" : ["grid", "row", "column"].includes(group.layout?.kind) ? group.layout.kind : "column");

// Lines are thin: each is given a wide, invisible twin to click, named for the line
// as it is drawn (the host maps drawn ids to the figure's).
export function widenLines(svg) {
  for (const line of svg.querySelectorAll('[data-flexo-entity="connector"][id], [data-flexo-entity="net"][id]')) {
    const id = line.id;
    for (const path of line.querySelectorAll("path")) {
      if (!path.getAttribute("d") || path.classList.contains("hit-line")) continue;
      const twin = document.createElementNS("http://www.w3.org/2000/svg", "path");
      twin.setAttribute("d", path.getAttribute("d"));
      if (path.getAttribute("transform")) twin.setAttribute("transform", path.getAttribute("transform"));
      twin.setAttribute("class", "hit-line");
      twin.dataset.hitFor = id;
      path.after(twin);
    }
  }
}

export function figureParts(host) {
  if (!document.querySelector('link[href="/static/kinds/figure/parts.css"]')) {
    document.head.append(h("link", { rel: "stylesheet", href: "/static/kinds/figure/parts.css" }));
  }
  const catalog = host.catalog;
  const parts = catalog.parts;
  const state = { model: null, selected: [], connecting: null, chain: true };

  // -- the figure as its file writes it --
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
  const chosenOne = () => (state.selected.length === 1 ? state.selected[0] : null);

  function setModel(next) {
    if (!next) return;
    state.model = next;
    state.selected = state.selected.filter((id) => typeOf(id));
    host.changed();
  }

  function select(ids, { reveal = true } = {}) {
    state.selected = [...new Set((Array.isArray(ids) ? ids : [ids]).filter(Boolean))];
    host.changed();
    const id = state.selected[state.selected.length - 1];
    if (id && reveal) host.reveal?.(id);
    host.focus?.(id ? { label: nameOf(id), id } : null);
  }

  // -- edits, one at a time --
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
        let result;
        try {
          result = await host.run(job.action, { merge: job.merge });
        } catch (error) {
          toast(error.message, { kind: "error", icon: "error", seconds: 6 });
          continue;
        }
        if (!result) continue;
        if (result.model) setModel(result.model);
        if (job.choose && result.select?.length) select(result.select);
        job.then?.(result);
      }
    } finally {
      running = false;
    }
  }
  const update = (target, values, merge = null) => act({ do: "update", target, values }, { merge, select: false });

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
    // Enter takes the best match: a title that starts with the words, then one that
    // holds them, then a description that does.
    const best = () => {
      const query = search.value.trim().toLowerCase();
      const ranked = [...grid.querySelectorAll(".add-tile:not(.off)")].map((item) => {
        const title = item.textContent.trim().toLowerCase();
        return { item, rank: !query ? 0 : title.startsWith(query) ? 0 : title.includes(query) ? 1 : 2 };
      });
      ranked.sort((a, b) => a.rank - b.rank);
      return ranked[0]?.item;
    };
    search.addEventListener("input", render);
    search.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); best()?.click(); } });
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
      const file = await host.chooseFile({ title: `Choose the ${part.title.toLowerCase()}'s file`, types: field.types });
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

  function groupMenu(anchor) {
    menu(anchor, catalog.groups.map((group) => ({ label: group.title, hint: group.hint, run: () => gather(group) })));
  }

  // -- lines --
  function toggleConnect(force) {
    const on = force ?? !state.connecting;
    if (!on) state.connecting = null;
    else {
      const from = chosenOne();
      state.connecting = { source: from && nodeOf(from) ? from : null };
    }
    host.changed();
  }
  function hint() {
    const connecting = state.connecting;
    if (!connecting) return null;
    return [icon("right"),
      connecting.source ? h("span", {}, "Click the part that ", h("b", {}, nameOf(connecting.source)), " leads to") : h("span", {}, "Click the part the line starts from"),
      h("span.kbd", {}, "Esc")];
  }
  function connectTo(id) {
    const connecting = state.connecting;
    if (!nodeOf(id)) return;
    if (!connecting.source) { connecting.source = id; select([id], { reveal: false }); return; }
    if (id === connecting.source) return;
    const source = connecting.source;
    state.connecting = null;
    host.changed();
    act({ do: "connect", source, target: id });
  }

  // -- choosing on the drawing --
  // A click on a part's empty space (inside a protein map, between a row's parts)
  // chooses the smallest part, then the smallest group, whose box holds the point.
  function around(event) {
    let best = null;
    for (const kind of ["node", "group"]) {
      const items = kind === "node" ? model()?.nodes || [] : (model()?.groups || []).filter((g) => g.id !== model().root);
      for (const item of items) {
        const box = host.element(item.id)?.getBoundingClientRect();
        if (!box || !box.width || event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) continue;
        const area = box.width * box.height;
        if (!best || area < best.area) best = { id: item.id, area };
      }
      if (best) return best.id;
    }
    return null;
  }
  // Pieces drawn inside a part carry ids of their own: the part is what is chosen.
  function idAt(event) {
    const line = event.target.closest?.("[data-hit-for]");
    const lineId = line && host.idOf(line.dataset.hitFor);
    if (lineId && typeOf(lineId)) return lineId;
    for (let at = event.target; at && at !== host.overlay; at = at.parentElement) {
      if (!at.matches?.("[data-flexo-entity][id]")) continue;
      const id = host.idOf(at.id);
      if (id && typeOf(id)) return id;
    }
    return around(event);
  }
  function click(event) {
    const id = idAt(event);
    if (state.connecting) { if (id) connectTo(id); return; }
    if (event.shiftKey || event.metaKey || event.ctrlKey) {
      if (id) select(state.selected.includes(id) ? state.selected.filter((item) => item !== id) : [...state.selected, id]);
      return;
    }
    select(id ? [id] : []);
  }
  function dblclick(event) {
    const id = idAt(event);
    if (id && typeOf(id) !== "net") openInline(id);
  }
  function marks() {
    return state.selected.map((id) => ({ id, box: host.box(id), group: typeOf(id) === "group", name: nameOf(id) })).filter((mark) => mark.box);
  }

  // -- words typed on the drawing --
  let inline = null;
  function openInline(id) {
    closeInline(false);
    const kind = typeOf(id);
    const item = kind === "node" ? nodeOf(id) : kind === "edge" ? edgeOf(id) : groupOf(id);
    if (!item || !host.box(id)) return;
    const original = words(item.label);
    const field = ui.markup({ value: original, rows: 1, colours: false });
    const box = h("div.fig-inline", {}, field,
      h("div.inline-foot", {}, h("span", {}, "Enter to keep · Esc to leave"), h("span", {}, "$maths$ · *emphasis*")));
    host.overlay.append(box);
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
    if (!inline) return;
    if (!inline.box.isConnected) host.overlay.append(inline.box);
    const where = host.box(inline.id);
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

  // -- keys --
  // Answers whether it took the key: the host does what it does with the rest.
  function key(event) {
    const mod = event.metaKey || event.ctrlKey;
    if (event.key === "Escape") {
      if (state.connecting) { toggleConnect(false); return true; }
      if (state.selected.length) { select([]); return true; }
      return false;
    }
    if (mod) {
      if (event.key.toLowerCase() === "d" && state.selected.length) { event.preventDefault(); duplicate(); return true; }
      return false;
    }
    if (event.key === "Backspace" || event.key === "Delete") {
      if (!state.selected.length) return false;
      event.preventDefault();
      remove();
      return true;
    }
    if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
      const id = chosenOne();
      if (!id) return false;
      event.preventDefault();
      act({ do: "step", id, delta: event.key === "ArrowUp" ? -1 : 1 });
      return true;
    }
    const letter = event.key.toLowerCase();
    if (letter === "a") { event.preventDefault(); addPalette(host.addAnchor?.() || { x: innerWidth / 2 - 190, y: 120 }); return true; }
    if (letter === "c") { event.preventDefault(); toggleConnect(); return true; }
    if (letter === "g") { event.preventDefault(); groupMenu(host.groupAnchor?.() || { x: innerWidth / 2 - 90, y: 120 }); return true; }
    if (letter === "enter") {
      const id = chosenOne();
      if (!id || typeOf(id) === "net") return false;
      event.preventDefault();
      openInline(id);
      return true;
    }
    return false;
  }

  // -- the inspector's panels --
  function panel() {
    const figure = model();
    if (!figure) return h("div.empty", {}, "The figure does not read. Its messages say where.");
    const chosen = state.selected;
    if (chosen.length > 1) return manyPanel(chosen);
    if (!chosen.length) return host.nothing ? host.nothing() : figurePanel();
    const id = chosen[0];
    const kind = typeOf(id);
    return kind === "node" ? nodePanel(nodeOf(id)) : kind === "group" ? groupPanel(groupOf(id))
      : kind === "edge" ? edgePanel(edgeOf(id)) : kind === "net" ? netPanel(netOf(id)) : figurePanel();
  }
  // Parts with tables (a protein's features, a plate's groups) want the room a table needs.
  function wantsRoom() {
    const one = chosenOne();
    return Boolean(one && nodeOf(one) && (partOf(nodeOf(one))?.fields || []).some((field) => field.type === "records"));
  }

  function crumbs(id) {
    const trail = [];
    for (let at = parentOf(id); at; at = parentOf(at.id)) trail.unshift(at.id);
    return h("div.crumbs", {}, host.crumbs ? [host.crumbs(), icon("chevron")] : null, trail.map((group, index) => [
      index ? icon("chevron") : null,
      h("button.crumb", { type: "button", onclick: () => select(group === model().root ? [] : [group]) }, group === model().root ? "Figure" : nameOf(group)),
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
    input.addEventListener("change", () => {
      const to = input.value.trim();
      if (!to || to === id) { input.value = id; return; }
      act({ do: "rename", id, to });
    });
    input.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); input.blur(); } });
    return ui.field("Id", input, { hint: type === "group" ? "" : "Lines name it" });
  }

  const titleBlock = (picture, name, hintText) =>
    h("div.insp-title", {}, picture, h("div.insp-words", {}, h("div.insp-name", {}, name), hintText ? h("div.insp-hint", {}, hintText) : null));

  function nodePanel(node) {
    const part = partOf(node) || { title: node.kind, fields: [], hint: "" };
    const kinds = Object.entries(parts).filter(([kind, p]) => !p.needs_file || kind === node.kind);
    const retype = ui.select({ value: node.kind || "block", options: kinds.map(([kind, p]) => ({ value: kind, label: p.title })),
      onChange: (value) => update({ type: "node", id: node.id }, { kind: value }) });
    const lines = model().edges.filter((edge) => nodeOfRef(edge.from) === node.id || nodeOfRef(edge.to) === node.id);
    return [
      h("div.section.insp-top", {}, crumbs(node.id),
        h("div.insp-row", {}, titleBlock(glyph(node.kind || "block"), part.title, part.hint), h("div.insp-actions", {}, headActions(node.id)))),
      colourSection([{ type: "node", id: node.id, item: node }]),
      h("div.section", {}, h("div.grid2", {}, idField(node.id, "node"), ui.field("Kind", retype)),
        fields(part.fields.filter((field) => field.key !== "properties.tone"), node, (values, merge) => update({ type: "node", id: node.id }, values, merge), `node:${node.id}`)),
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
      isRoot || group.implied ? null : colourSection([{ type: "group", id: group.id, item: group }]),
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
      h("div.section.insp-top", {}, host.crumbs ? h("div.crumbs", {}, host.crumbs(), icon("chevron"), h("span.crumb.here", {}, "Line")) : null,
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
      howTo(),
    ];
  }

  function howTo() {
    const figure = model();
    return h("div.section", {}, h("div.section-title", {}, "Making it"),
      h("ul.how", {},
        h("li", {}, h("b", {}, "Add"), " a part (A). With a part chosen, the new one comes after it, a line between them."),
        h("li", {}, h("b", {}, "Connect"), " (C): click where a line starts, then where it ends."),
        h("li", {}, "Double-click a part to change its words; ⇧-click to choose several, then ", h("b", {}, "Group"), " (G).")),
      h("div.row", {}, ui.button("Add a part", (event) => addPalette(event.currentTarget), { small: true, icon: "plus" }),
        figure ? ui.button("The layout", () => select([figure.root]), { small: true, icon: "layout" }) : null));
  }

  function manyPanel(ids) {
    const gatherable = ids.every((id) => nodeOf(id) || (groupOf(id) && id !== model().root));
    const colourable = ids.flatMap((id) => nodeOf(id) ? [{ type: "node", id, item: nodeOf(id) }]
      : groupOf(id) && id !== model().root && !groupOf(id).implied ? [{ type: "group", id, item: groupOf(id) }] : []);
    return [
      h("div.section.insp-top", {}, titleBlock(icon("layout"), `${ids.length} chosen`, ids.map(nameOf).join(", "))),
      colourable.length ? colourSection(colourable) : null,
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
  // -- colours: a part's tone (a colour of the theme's, shared by parts with the same
  // tone), or colours of its own, which win over the tone and the theme --

  const OWN = [["fill", "Fill"], ["stroke", "Outline"], ["label", "Words"]];
  const GROUP_OWN = { fill: "Background", stroke: "Border", label: "Title" };
  const TONE_NAMES = () => Object.values(parts).flatMap((part) => part.fields).find((field) => field.key === "properties.tone")?.options.filter((name) => !/^\d+$/.test(name)) || [];

  function colourSection(targets) {
    const nodes = targets.filter((target) => target.type === "node");
    const tones = host.tones?.();
    const scope = targets.map((target) => target.id).join(",");
    // One edit for every chosen thing; a colour dragged in the picker is one undo step.
    const paint = (type, values) => {
      const list = targets.filter((target) => target.type === type);
      if (list.length) act({ do: "update", targets: list.map(({ type: kind, id }) => ({ type: kind, id })), values },
        { merge: `colour:${type}:${Object.keys(values)[0]}:${scope}`, select: false });
    };
    const common = (read) => {
      const values = targets.map((target) => read(target) ?? null);
      return values.every((value) => value === values[0]) ? values[0] : undefined;
    };
    const toneOf = (node) => {
      const tone = node.properties?.tone;
      if (tone === undefined || tone === null || tone === "") return null;
      return /^\d+$/.test(String(tone)) ? String(tone) : tones?.used?.[tone] !== undefined ? String(tones.used[tone]) : `named:${tone}`;
    };
    const chips = nodes.length && tones?.colours?.length ? ui.field("The theme's", ui.swatches({
      value: common((target) => target.type === "node" ? toneOf(target.item) : null) ?? null,
      colours: tones.colours.map((colour, index) => ({ value: String(index + 1), colour: colour.fill, border: colour.stroke, title: `The theme's colour ${index + 1}` })),
      onChange: (value) => paint("node", { "properties.tone": value }),
    })) : null;
    // A tone by name: parts that share one share its colour, whichever the theme gives it.
    const named = nodes.length ? ui.field("Tone name", ui.combo({
      value: (() => { const tone = common((target) => target.type === "node" ? target.item.properties?.tone : null); return tone && !/^\d+$/.test(String(tone)) ? tone : ""; })(),
      options: TONE_NAMES(), key: `colour:${scope}:tone`, placeholder: "none",
      onChange: (value) => paint("node", { "properties.tone": value.trim() || null }),
    }), { hint: "Parts with one name share a colour" }) : null;
    const own = h("div.own-colours", {}, OWN.map(([part, label]) => h("div.own-colour", {},
      ui.colour({
        title: label, key: `colour:${scope}:${part}`,
        value: common((target) => target.type === "node" ? target.item.properties?.[`paint-${part}`] : target.item.paint?.[part]),
        onChange: (value) => { paint("node", { [`properties.paint-${part}`]: value }); paint("group", { [`paint.${part}`]: value }); },
      }),
      h("span", {}, nodes.length ? label : GROUP_OWN[part]))));
    return h("div.section", {}, h("div.section-title", {}, "Colour"), chips, named,
      ui.field("Its own", own, { hint: "Win over tones and the theme" }));
  }


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
        // A switch's hint is said beside it: the label column is narrow.
        return ui.field(field.label, h("div.switch-row", { title: field.hint || "" },
          ui.toggle({ value: on, onChange: (next) => set(next === (field.default ?? false) ? null : next) }),
          field.hint ? h("span.switch-hint", {}, field.hint) : null), { inline: true });
      }
      case "choice":
        return ui.field(field.label, ui.select({ value: value ?? field.default ?? "", options: field.options.map((option) => ({ value: option, label: option === "" ? "None" : String(option) })),
          onChange: (next) => {
            const typed = field.options.find((option) => String(option) === next);
            set(typed === field.default || typed === "" ? null : typed);
          } }), options);
      case "combo":
        return ui.field(field.label, ui.combo({ value: value ?? "", options: field.options.map(String), key, placeholder: field.default ?? "", onChange: set }), options);
      case "palette": {
        const current = value ?? field.default;
        const strip = (name) => h("span.palette-strip", {}, (field.colours?.[name] || []).slice(0, 8).map((colour) => h("span", { style: { background: colour } })));
        const title = (name) => (name === field.default ? "The theme's own" : name);
        const choose = (event) => popover(event.currentTarget, h("div.palette-choices", {},
          field.options.map((name) => h(`button.palette-choice${name === current ? ".on" : ""}`, { type: "button",
            onclick: () => { closeMenu(); set(name === field.default ? null : name); } }, strip(name), h("span", {}, title(name))))),
          { className: "palette-menu" });
        return ui.field(field.label, h("button.palette-pick", { type: "button", onclick: choose }, strip(current), h("span", {}, title(current)), icon("chevron")), options);
      }
      case "theme":
        // A host that can show themes by sight does; otherwise, their names.
        return ui.field(field.label, host.themeField ? host.themeField(value, set)
          : ui.combo({ value: value ?? "", options: field.options.map(String), key, placeholder: field.default ?? "", onChange: set }), options);
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
          h("span.fixed", {}, ui.button("Choose…", async () => { const file = await host.chooseFile({ title: "Choose a file", types: field.types }); if (file) set(file); }, { small: true, icon: "folder" }))), options);
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

  return {
    get model() { return state.model; },
    get selected() { return state.selected; },
    get connecting() { return state.connecting; },
    get inline() { return inline; },
    setModel, select, act, update,
    typeOf, nameOf, nodeOf, groupOf, edgeOf, netOf, parentOf, nodeOfRef, partOf,
    idAt, click, dblclick, marks, hint, key, panel, wantsRoom, howTo,
    addPalette, addPart, gather, groupMenu, remove, duplicate, toggleConnect,
    openInline, placeInline, closeInline,
  };
}
