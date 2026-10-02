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
//   settled()               the parts have landed where they are drawn: mark them again;
//
// Parts are dragged on the drawing to another place in their row, column or grid,
// or into another group (pointerdown); and an edit that moves parts lands smoothly:
// the host takes landing() before it puts the new drawing in and gives it to land()
// after, and each part slides from where it was to where it is.
//   chooseFile({ title, types }), focus(where), nothing()  (the panel when nothing is chosen).

import { h, clear, icon, ui, menu, popover, closeMenu, toast, readable } from "/static/studio/studio.js";
import { dropPlace, stays } from "/static/kinds/figure/drop.js";

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
  cells: "M2.5 2.5h3v3h-3zM9.5 2.5h3v3h-3zM6 6h3v3H6zM2.5 9.5h3v3h-3zM9.5 9.5h3v3h-3z",
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

// A structure's name from its file: a PDB ID in capitals, any other file by its name.
export function fileLabel(source) {
  const stem = String(source).split("/").pop().replace(/\.(pdb|cif|mmcif|ent)$/i, "");
  return /^[0-9][A-Za-z0-9]{3}$/.test(stem) ? stem.toUpperCase() : stem;
}
export const words = (label) => (Array.isArray(label) ? label.map((run) => run?.text ?? "").join("") : label ?? "");
export const plain = (label) => readable(words(label));
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
      // Unpainted by itself, not only by parts.css: a slide shows its figure's lines
      // widened before that sheet is loaded, and a path left to SVG's defaults is black.
      twin.setAttribute("fill", "none");
      twin.setAttribute("stroke", "transparent");
      twin.setAttribute("stroke-width", "9");
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
  const state = { model: null, selected: [], connecting: null, chain: true, landing: 0, swallow: false };

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

  // What an edit does, in words, for the history: "Moved “Model”", "Connected “x” to “y”".
  // (Said before it is made: the names are the parts' as they were.)
  function said(action) {
    const name = (id) => `“${nameOf(nodeOfRef(id))}”`;
    const many = (ids, verb) => (ids?.length === 1 ? `${verb} ${name(ids[0])}` : `${verb} ${ids?.length || 0} parts`);
    switch (action.do) {
      case "add": { const title = (parts[action.kind]?.title || "part").toLowerCase(); return `Added ${/^[aeiou]/.test(title) ? "an" : "a"} ${title}`; }
      case "connect": return `Connected ${name(action.source)} to ${name(action.target)}`;
      case "delete": return many(action.ids, "Deleted");
      case "duplicate": return many(action.ids, "Duplicated");
      case "gather": return `Grouped ${action.ids?.length || 0} parts`;
      case "ungroup": return `Ungrouped ${name(action.id)}`;
      case "paste": return "Pasted parts";
      case "rename": return `Renamed ${name(action.id)}'s id to ${action.to}`;
      case "move": case "step": return `Moved ${name(action.id)}`;
      case "update": {
        const id = action.target?.id, keys = Object.keys(action.values || {});
        const all = (...wanted) => keys.length && keys.every((key) => wanted.includes(key));
        if (all("label")) return `Retyped ${name(id)}`;
        if (all("properties.yaw", "properties.pitch", "properties.roll")) return `Turned ${name(id)}`;
        if (all("properties.width", "properties.height")) return `Sized ${name(id)}`;
        if (all("properties.zoom")) return `Zoomed ${name(id)}`;
        // mol-sketch's settings, by name: "Set the line width of “1A8O”".
        const style = keys.filter((key) => key.startsWith("properties.style"));
        if (style.length && style.length === keys.length) {
          if (keys[0] === "properties.style" && action.values[keys[0]] === null) return `Drew ${name(id)} as its look does`;
          return `Set the ${style.map((key) => key.replace(/^properties\.style\.?/, "").replace(/[._]/g, " ")).join(", ")} of ${name(id)}`;
        }
        if (all("properties.palette")) return action.values["properties.palette"] ? `Gave ${name(id)} the ${action.values["properties.palette"]} palette` : `Gave ${name(id)} its look's palette`;
        if (all("properties.colors")) return `Coloured ${name(id)}`;
        if (all("properties.density")) return action.values["properties.density"] ? `Drew a density map with ${name(id)}` : `Took the density map off ${name(id)}`;
        if (keys.includes("kind")) { const title = (parts[action.values.kind]?.title || "part").toLowerCase(); return `Made ${name(id)} ${/^[aeiou]/.test(title) ? "an" : "a"} ${title}`; }
        return `Changed ${name(id)}`;
      }
      default: return null;
    }
  }

  function setModel(next) {
    if (!next) return;
    state.model = next;
    state.selected = state.selected.filter((id) => typeOf(id));
    host.changed();
  }

  function select(ids, { reveal = true } = {}) {
    state.selected = [...new Set((Array.isArray(ids) ? ids : [ids]).filter(Boolean))];
    if (typeInto && !state.selected.includes(typeInto)) typeInto = null;
    host.changed();
    const id = state.selected[state.selected.length - 1];
    if (id && reveal) host.reveal?.(id);
    host.focus?.(id ? { label: nameOf(id), id } : null);
  }

  // -- edits, one at a time --
  const queue = [];
  let running = false;
  const LANDS = new Set(["move", "step", "add", "delete", "duplicate", "gather", "ungroup", "connect"]);
  function act(action, { merge = null, select: choose = true, then = null, failed = null } = {}) {
    // Typing in one field: only its latest words wait to be sent.
    if (merge) {
      const waiting = queue.findIndex((job) => job.merge === merge);
      if (waiting >= 0) queue.splice(waiting, 1);
    }
    queue.push({ action, merge, choose, then, failed, label: action.do === "read" || action.do === "structure-view" ? null : said(action) });
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
          result = await host.run(job.action, { merge: job.merge, label: job.label });
        } catch (error) {
          toast(error.message, { kind: "error", icon: "error", seconds: 6 });
          job.failed?.();
          continue;
        }
        if (!result) { job.failed?.(); continue; }
        // The drawing that comes after an edit that moves parts lands smoothly.
        if (LANDS.has(job.action.do)) state.landing = Date.now();
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

  // A part added is ready for its words: they are typed on it as soon as it is drawn.
  // One drawn from a file is named for it (a structure for its PDB ID).
  let typeInto = null;
  async function addPart(kind, where = placement()) {
    const part = parts[kind];
    const action = { do: "add", kind, parent: where.parent || null, after: where.after || null, source: where.source || null };
    if (part.needs_file) {
      const field = part.fields.find((item) => item.type === "file");
      const file = await host.chooseFile({ title: `Choose the ${part.title.toLowerCase()}'s file`, types: field.types });
      if (!file) return;
      action.node = { properties: { source: file } };
      if (kind === "structure") action.node.label = fileLabel(file);
    }
    act(action, { then: (result) => { if (!part.needs_file && result.select?.length === 1) typeInto = result.select[0]; } });
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

  // What a part's right-click menu offers (the host adds cut, copy and paste): the
  // part is chosen first, as PowerPoint chooses what is right-clicked.
  function menuOf(id, anchor) {
    if (!state.selected.includes(id)) select([id]);
    const node = nodeOf(id), group = groupOf(id), edge = edgeOf(id);
    const isRoot = id === model()?.root;
    const items = [];
    if (!isRoot && (node || group || edge)) items.push({ icon: "pencil", label: "Edit its words", run: () => openInline(id) });
    if (node) {
      const kind = nextKind(node);
      items.push({ icon: "plus", label: `Add ${parts[kind].title.toLowerCase()} after it`, keys: "A", run: () => addPart(kind, { after: id, source: id }) },
        { icon: "plus", label: "Add another kind after it…", run: () => addPalette(anchor) },
        { icon: "right", label: "Draw a line from it", keys: "C", run: () => toggleConnect(true) });
    }
    const holder = parentOf(id);
    const row = holder && (holder.layout?.kind || (holder.id === model()?.root ? "column" : "row")) === "row";
    if ((node || (group && !isRoot)) && row && (holder.children || []).some((child) => child !== id)) {
      items.push({ icon: "down", label: "On a line of its own, below", run: () => act({ do: "move", id, line: "below", of: holder.id }) });
    }
    if (state.selected.length > 1) items.push({ icon: "layout", label: "Group the chosen parts", keys: "G", run: () => groupMenu(anchor) });
    if (group && !isRoot) items.push({ icon: "layout", label: "Ungroup", run: () => act({ do: "ungroup", id }) });
    if (node || (group && !isRoot)) items.push({ icon: "copy", label: "Duplicate", run: () => duplicate() });
    if (!isRoot) items.push({ icon: "trash", label: "Delete", keys: "⌫", danger: true, run: () => remove() });
    return items;
  }

  function duplicate(ids = state.selected) {
    const chosen = ids.filter((id) => nodeOf(id) || (groupOf(id) && id !== model()?.root));
    if (chosen.length) act({ do: "duplicate", ids: chosen });
  }

  // -- copied, and pasted (into this figure or another) --
  // The parts and groups chosen, with what they hold and the lines between them.
  function clip() {
    const figure = model();
    if (!figure) return null;
    const chosen = state.selected.filter((id) => nodeOf(id) || (groupOf(id) && id !== figure.root));
    const top = chosen.filter((id) => !chosen.some((other) => other !== id && inside(id, other)));
    if (!top.length) return null;
    const nodes = [], groups = [];
    const walk = (id) => {
      if (nodeOf(id)) { nodes.push(structuredClone(nodeOf(id))); return; }
      const group = groupOf(id);
      if (group) { groups.push(structuredClone(group)); (group.children || []).forEach(walk); }
    };
    top.forEach(walk);
    const held = new Set(nodes.map((node) => node.id));
    const edges = figure.edges.filter((edge) => held.has(nodeOfRef(edge.from)) && held.has(nodeOfRef(edge.to))).map((edge) => structuredClone(edge));
    return { top, nodes, groups, edges };
  }
  function paste(clipped) {
    const where = placement();
    act({ do: "paste", top: clipped.top, nodes: clipped.nodes, groups: clipped.groups, edges: clipped.edges,
      parent: where.parent || null, after: where.after || null });
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
    if (state.swallow) { state.swallow = false; return; }  // the end of a drag, not a click
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
    if (!id || typeOf(id) === "net") return;
    // The part typed on is the part chosen: its panel shows beside it.
    if (chosenOne() !== id) select([id], { reveal: false });
    openInline(id);
  }
  function marks() {
    return state.selected.map((id) => ({ id, box: host.box(id), group: typeOf(id) === "group", name: nameOf(id) })).filter((mark) => mark.box);
  }

  // The marks as the host shows them over the drawing: a frame round each part chosen,
  // and on the one part chosen a + on the side its line leaves by, which adds the part
  // that usually comes next there, joined to it -- into its line, as a step in a flow.
  const AFTER = { terminal: "block", decision: "block", text: "block", junction: "block", op: "block", circle: "circle" };
  function nextKind(node) {
    const kind = AFTER[node.kind || "block"] || node.kind || "block";
    return parts[kind] && !parts[kind].unavailable ? kind : "block";
  }
  function sideOf(id, box) {
    const holder = parentOf(id);
    const siblings = holder?.children || [];
    const at = siblings.indexOf(id);
    const line = model().edges.find((edge) => nodeOfRef(edge.from) === id);
    const toward = line ? nodeOfRef(line.to) : siblings[at + 1] || null;
    const away = toward ? null : siblings[at - 1] || null;
    const other = (toward || away) && host.box(toward || away);
    if (!other) return holder?.layout?.kind === "row" ? "right" : "bottom";
    const dx = other.left + other.width / 2 - (box.left + box.width / 2);
    const dy = other.top + other.height / 2 - (box.top + box.height / 2);
    const sign = toward ? 1 : -1;
    if (Math.abs(dx) > Math.abs(dy)) return dx * sign > 0 ? "right" : "left";
    return dy * sign > 0 ? "bottom" : "top";
  }
  function markViews() {
    // A molecule chosen may be grabbed and turned: the pointer says so over it.
    for (const element of host.overlay.querySelectorAll(".fig-grab")) element.classList.remove("fig-grab");
    if (nodeOf(chosenOne())?.kind === "structure") moleculeOf(chosenOne())?.classList.add("fig-grab");
    const views = marks().map(({ box, group, name }) => h(`div.fig-mark${group ? ".group" : ""}`, { style: {
      left: `${box.left}px`, top: `${box.top}px`, width: `${box.width}px`, height: `${box.height}px` } },
    group ? h("span.fig-mark-label", {}, name) : null));
    const id = chosenOne();
    const box = id && nodeOf(id) && !state.connecting && !inline ? host.box(id) : null;
    if (box) {
      const side = sideOf(id, box);
      const kind = nextKind(nodeOf(id));
      const x = side === "right" ? box.left + box.width : side === "left" ? box.left : box.left + box.width / 2;
      const y = side === "bottom" ? box.top + box.height : side === "top" ? box.top : box.top + box.height / 2;
      const stop = (event) => event.stopPropagation();
      views.push(h(`button.fig-next.${side}`, {
        type: "button", style: { left: `${x}px`, top: `${y}px` },
        title: `Add ${parts[kind].title.toLowerCase()} after ${nameOf(id)}, joined to it (A for another kind)`,
        onpointerdown: stop, ondblclick: stop, onmousemove: stop,
        onclick: (event) => { stop(event); addPart(kind, { after: id, source: id }); },
      }, icon("plus")));
    }
    // A molecule or picture chosen has a handle at each corner: dragged, it is drawn
    // larger or smaller, and the figure is laid out round it again.
    if (box && SIZED_PARTS.has(nodeOf(id)?.kind)) {
      for (const corner of ["nw", "ne", "sw", "se"]) {
        views.push(h(`span.fig-size.${corner}`, {
          style: { left: `${corner.endsWith("w") ? box.left : box.left + box.width}px`, top: `${corner.startsWith("n") ? box.top : box.top + box.height}px` },
          title: "Drag to size it · double-click for its own size",
          onpointerdown: (event) => partSizeStart(event, id, corner),
          ondblclick: (event) => { event.stopPropagation(); update({ type: "node", id }, { "properties.width": null, "properties.height": null }); },
        }));
      }
    }
    return views;
  }

  // -- a molecule or picture sized by its corners --
  // It grows or shrinks about its opposite corner as the pointer goes; let go, it is
  // given that width and height and the figure is laid out again, its parts gliding to
  // where they go.
  const SIZED_PARTS = new Set(["structure", "image"]);
  let partSizing = null;
  function partSizeStart(event, id, corner) {
    if (event.button !== 0 || partSizing) return;
    event.preventDefault();
    event.stopPropagation();
    const element = host.element(id);
    const box = element?.getBoundingClientRect();
    const unit = element?.getScreenCTM?.()?.a;
    if (!box || !box.width || !unit) return;
    const west = corner.endsWith("w"), north = corner.startsWith("n");
    Object.assign(element.style, { transformBox: "fill-box", transformOrigin: `${west ? "100%" : "0"} ${north ? "100%" : "0"}`, transform: "" });
    const tip = h("div.fig-turn-tip");
    host.overlay.append(tip);
    partSizing = { id, element, box, unit, tip, scale: 1, moved: false, start: { x: event.clientX, y: event.clientY },
      anchor: { x: west ? box.right : box.left, y: north ? box.bottom : box.top }, handle: { x: west ? box.left : box.right, y: north ? box.top : box.bottom } };
    host.overlay.classList.add("fig-sizing");
    window.addEventListener("pointermove", partSizeMove);
    window.addEventListener("pointerup", partSizeEnd);
    window.addEventListener("pointercancel", partSizeCancel);
  }
  function partSizeMove(event) {
    const sizing = partSizing;
    if (!sizing) return;
    if (!sizing.moved && Math.hypot(event.clientX - sizing.start.x, event.clientY - sizing.start.y) < 3) return;
    sizing.moved = true;
    const { anchor, handle, box } = sizing;
    const dx = handle.x - anchor.x, dy = handle.y - anchor.y;
    let scale = ((event.clientX - anchor.x) * dx + (event.clientY - anchor.y) * dy) / (dx * dx + dy * dy || 1);
    scale = Math.min(Math.max(scale, 24 / Math.min(box.width, box.height)), 6);
    if (Math.abs(scale - 1) * box.width < 4) scale = 1;
    sizing.scale = scale;
    sizing.element.style.transform = `scale(${scale})`;
    const outer = host.overlay.getBoundingClientRect();
    sizing.tip.textContent = `${Math.round(scale * 100)}%`;
    Object.assign(sizing.tip.style, { left: `${event.clientX - outer.left}px`, top: `${event.clientY - outer.top + 18}px` });
  }
  function partSizeFinish() {
    const sizing = partSizing;
    partSizing = null;
    window.removeEventListener("pointermove", partSizeMove);
    window.removeEventListener("pointerup", partSizeEnd);
    window.removeEventListener("pointercancel", partSizeCancel);
    host.overlay.classList.remove("fig-sizing");
    sizing?.tip.remove();
    if (sizing?.moved) { state.swallow = true; setTimeout(() => { state.swallow = false; }, 0); }
    return sizing;
  }
  function partSizeEnd() {
    const sizing = partSizeFinish();
    if (!sizing) return;
    if (!sizing.moved || Math.abs(sizing.scale - 1) < 0.01) { sizing.element.style.transform = ""; return; }
    const { box, unit, scale, id, element } = sizing;
    act({ do: "update", target: { type: "node", id }, values: { "properties.width": Math.round((box.width / unit) * scale), "properties.height": Math.round((box.height / unit) * scale) } },
      { then: () => { state.landing = Date.now(); }, failed: () => { element.style.transform = ""; } });
    // Should no new drawing come, it goes back to the size it is drawn at.
    setTimeout(() => { if (element.isConnected) element.style.transform = ""; }, 6000);
  }
  function partSizeCancel() {
    const sizing = partSizeFinish();
    if (sizing) sizing.element.style.transform = "";
  }

  // -- a structure turned by dragging on it --
  // Chosen, a molecule is grabbed and turned as in a viewer: across turns it (yaw), up
  // and down tilts it (pitch). While it turns, its chains' trace is drawn turning over
  // it -- in mol-sketch's own frame, so it lies as the molecule will -- and once let go,
  // the molecule is drawn at the new turn.
  const views = new Map();
  const moleculeOf = (id) => host.element(`${id}.molecule`);
  function turnable(event) {
    const id = chosenOne();
    if (!id || nodeOf(id)?.kind !== "structure") return false;
    const box = moleculeOf(id)?.getBoundingClientRect();
    return Boolean(box && event.clientX >= box.left && event.clientX <= box.right && event.clientY >= box.top && event.clientY <= box.bottom);
  }
  async function viewOf(id) {
    const node = nodeOf(id);
    const key = JSON.stringify([id, node?.properties]);
    if (!views.has(key)) views.set(key, host.run({ do: "structure-view", id }, { merge: null }).then((result) => result?.view || null).catch(() => null));
    return views.get(key);
  }
  let turning = null;
  function turnStart(event, id) {
    event.preventDefault();
    event.stopPropagation();
    const molecule = moleculeOf(id);
    if (!molecule) return;
    const outer = host.overlay.getBoundingClientRect(), box = molecule.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const canvas = h("canvas.fig-turn", { width: Math.round(box.width * ratio), height: Math.round(box.height * ratio),
      style: { left: `${box.left - outer.left}px`, top: `${box.top - outer.top}px`, width: `${box.width}px`, height: `${box.height}px` } });
    const tip = h("div.fig-turn-tip", { style: { left: `${box.left - outer.left + box.width / 2}px`, top: `${box.top - outer.top + box.height + 6}px` } });
    turning = { id, molecule, canvas, tip, from: { x: event.clientX, y: event.clientY }, by: { x: 0, y: 0 }, view: null, frame: 0, moved: false };
    const mine = turning;
    viewOf(id).then((view) => { if (turning === mine) { mine.view = view; turnDraw(); } });
    window.addEventListener("pointermove", turnMove);
    window.addEventListener("pointerup", turnEnd);
    window.addEventListener("pointercancel", turnCancel);
    window.addEventListener("keydown", turnKey, true);
  }
  const TURN = 0.5;  // degrees a pixel
  const angle = (value) => Math.round(((((value % 360) + 540) % 360) - 180) * 10) / 10;
  function turnAngles(turn = turning) {
    const camera = turn.view?.camera || { yaw: 0, pitch: 0, roll: 0 };
    return { yaw: angle(camera.yaw + turn.by.x * TURN), pitch: angle(camera.pitch + turn.by.y * TURN), roll: camera.roll || 0 };
  }
  function turnMove(event) {
    if (!turning) return;
    turning.by = { x: event.clientX - turning.from.x, y: event.clientY - turning.from.y };
    if (!turning.moved && Math.hypot(turning.by.x, turning.by.y) < 3) return;
    if (!turning.moved) {
      turning.moved = true;
      host.overlay.append(turning.canvas, turning.tip);
      turning.molecule.classList.add("fig-turning");
      document.body.classList.add("fig-grabbing");
    }
    if (!turning.frame) turning.frame = requestAnimationFrame(() => { if (turning) { turning.frame = 0; turnDraw(); } });
  }
  function turnDraw() {
    const { canvas, view, tip } = turning;
    if (!turning.moved) return;
    const { yaw, pitch, roll } = turnAngles();
    tip.textContent = `Turn ${Math.round(yaw)}° · tilt ${Math.round(pitch)}°`;
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    if (!view?.chains?.length) return;
    const [cy, sy, cp, sp, cr, sr] = [yaw, yaw, pitch, pitch, roll, roll].map((value, index) => (index % 2 ? Math.sin : Math.cos)(value * Math.PI / 180));
    // As mol-sketch turns it: about y by yaw, x by pitch, then z by roll; y up on the page.
    const chains = view.chains.map((chain) => chain.map(([x, y, z]) => {
      const x1 = cy * x + sy * z, z1 = -sy * x + cy * z;
      const y2 = cp * y - sp * z1, z2 = sp * y + cp * z1;
      return [cr * x1 - sr * y2, -(sr * x1 + cr * y2), z2];
    }));
    const all = chains.flat();
    const [left, right] = [Math.min(...all.map((p) => p[0])), Math.max(...all.map((p) => p[0]))];
    const [top, bottom] = [Math.min(...all.map((p) => p[1])), Math.max(...all.map((p) => p[1]))];
    const [near, far] = [Math.max(...all.map((p) => p[2])), Math.min(...all.map((p) => p[2]))];
    const pad = 0.08 * Math.min(canvas.width, canvas.height);
    const scale = Math.min((canvas.width - 2 * pad) / Math.max(right - left, 1), (canvas.height - 2 * pad) / Math.max(bottom - top, 1));
    const at = ([x, y]) => [canvas.width / 2 + (x - (left + right) / 2) * scale, canvas.height / 2 + (y - (top + bottom) / 2) * scale];
    const ink = getComputedStyle(host.overlay).getPropertyValue("--accent").trim() || "#3d5afe";
    context.lineCap = "round";
    context.lineJoin = "round";
    // Segments far to near, the near ones darker and thicker: the trace reads in depth.
    const segments = chains.flatMap((chain) => chain.slice(1).map((point, index) => [chain[index], point]));
    segments.sort((a, b) => (a[0][2] + a[1][2]) - (b[0][2] + b[1][2]));
    const ratio = window.devicePixelRatio || 1;
    for (const [a, b] of segments) {
      const depth = near > far ? ((a[2] + b[2]) / 2 - far) / (near - far) : 1;
      context.strokeStyle = ink;
      context.globalAlpha = 0.25 + 0.75 * depth;
      context.lineWidth = (1.2 + 2.2 * depth) * ratio;
      context.beginPath();
      context.moveTo(...at(a));
      context.lineTo(...at(b));
      context.stroke();
    }
    context.globalAlpha = 1;
  }
  function turnFinish() {
    window.removeEventListener("pointermove", turnMove);
    window.removeEventListener("pointerup", turnEnd);
    window.removeEventListener("pointercancel", turnCancel);
    window.removeEventListener("keydown", turnKey, true);
    document.body.classList.remove("fig-grabbing");
    const was = turning;
    turning = null;
    if (was?.frame) cancelAnimationFrame(was.frame);
    return was;
  }
  // The trace stays over the molecule until it is drawn again at its new turn.
  function turnClear(was) {
    was.canvas.remove();
    was.tip.remove();
    was.molecule.classList.remove("fig-turning");
  }
  function turnEnd() {
    const was = turnFinish();
    if (!was) return;
    if (!was.moved || !was.view) { turnClear(was); return; }
    // A press that turned it is not a click on it.
    state.swallow = true;
    setTimeout(() => { state.swallow = false; }, 0);
    const { yaw, pitch } = turnAngles(was);
    was.tip.textContent = "Drawing it…";
    const values = { "properties.yaw": yaw || null, "properties.pitch": pitch || null };
    act({ do: "update", target: { type: "node", id: was.id }, values }, { select: false, failed: () => turnClear(was) });
    const started = Date.now();
    const wait = () => {
      if (moleculeOf(was.id) !== was.molecule || Date.now() - started > 8000) turnClear(was);
      else requestAnimationFrame(wait);
    };
    requestAnimationFrame(wait);
  }
  function turnCancel() { const was = turnFinish(); if (was) turnClear(was); }
  function turnKey(event) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    turnCancel();
  }

  // -- dragging a part to another place --
  // A part pressed and moved follows the pointer, lifted; a line between the parts it
  // would go between shows where it lands, gliding as the pointer goes, the group it
  // would join outlined and the parts either side of the line parted for it. Let go,
  // it is moved there (the server writes it into the file) and the drawing that comes
  // back lands smoothly (land); Esc, or letting go where it was, sends it home.
  let drag = null;
  const SVG = (element) => element?.ownerSVGElement || element;
  const unitsPerPixel = (element) => 1 / ((element?.parentNode?.getScreenCTM?.() || SVG(element)?.getScreenCTM?.())?.a || 1);
  const centre = (box) => ({ x: (box.left + box.right) / 2, y: (box.top + box.bottom) / 2 });
  // What is drawn of a part: a group's frame and everything it holds -- each element
  // once, the outermost, as a framed group draws its parts inside itself.
  function elementsOf(id) {
    const found = [];
    const walk = (at) => {
      const element = host.element(at);
      if (element) found.push(element);
      for (const child of groupOf(at)?.children || []) walk(child);
    };
    walk(id);
    return found.filter((element) => !found.some((other) => other !== element && other.contains(element)));
  }
  function boxOf(id, boxes) {
    if (boxes.has(id)) return boxes.get(id);
    let box = null;
    // A part's drawing; a group's frame and label, if it has them, and what it holds.
    const drawn = host.element(id)?.getBoundingClientRect();
    if (drawn && (drawn.width || drawn.height)) box = { left: drawn.left, top: drawn.top, right: drawn.right, bottom: drawn.bottom };
    for (const child of groupOf(id)?.children || []) {
      const inner = boxOf(child, boxes);
      if (!inner) continue;
      box = box ? { left: Math.min(box.left, inner.left), top: Math.min(box.top, inner.top),
        right: Math.max(box.right, inner.right), bottom: Math.max(box.bottom, inner.bottom) } : { ...inner };
    }
    boxes.set(id, box);
    return box;
  }
  function inside(id, ancestor) {
    for (let at = id; at; at = parentOf(at)?.id) if (at === ancestor) return true;
    return false;
  }

  function pointerdown(event) {
    if (event.button !== 0 || state.connecting || inline || event.shiftKey || event.metaKey || event.ctrlKey || event.altKey) return;
    if (turnable(event)) { turnStart(event, chosenOne()); return; }
    const id = idAt(event);
    if (!id || id === model()?.root || !(nodeOf(id) || groupOf(id)) || !parentOf(id)) return;
    drag = { id, from: { x: event.clientX, y: event.clientY }, started: false, frame: 0, at: null };
    window.addEventListener("pointermove", dragMove);
    window.addEventListener("pointerup", dragEnd);
    window.addEventListener("pointercancel", dragCancel);
    window.addEventListener("keydown", dragKey, true);
  }

  function dragStart() {
    const id = drag.id;
    const boxes = new Map();
    window.getSelection?.()?.removeAllRanges();
    // Where every part is now, and every group's room, from the drawing as it stands.
    for (const group of model().groups) boxOf(group.id, boxes);
    for (const node of model().nodes) boxOf(node.id, boxes);
    const moving = elementsOf(id).map((element) => ({ element, base: element.getAttribute("transform") || "", scale: unitsPerPixel(element) }));
    const nodes = new Set(model().nodes.filter((node) => inside(node.id, id)).map((node) => node.id));
    const touches = (ref) => nodes.has(nodeOfRef(ref));
    const lines = [...model().edges.filter((edge) => touches(edge.from) || touches(edge.to)),
      ...model().nets.filter((net) => [...(net.sources || []), ...(net.targets || [])].some(touches))]
      .map((line) => host.element(line.id)).filter((element) => element && !moving.some((item) => item.element.contains(element)));
    const indicator = h("div.fig-drop-line");
    const zone = h("div.fig-drop-zone");
    host.overlay.append(zone, indicator);
    host.overlay.classList.add("fig-dragging");
    document.body.classList.add("fig-grabbing");
    for (const { element } of moving) element.classList.add("fig-lifted");
    for (const element of lines) element.classList.add("fig-faded");
    Object.assign(drag, { started: true, boxes, moving, lines, indicator, zone, parted: [] });
    select([id], { reveal: false });
  }

  function dragMove(event) {
    if (!drag) return;
    drag.pointer = { x: event.clientX, y: event.clientY };
    if (!drag.started) {
      if (Math.hypot(event.clientX - drag.from.x, event.clientY - drag.from.y) < 4) return;
      dragStart();
    }
    event.preventDefault();
    if (!drag.frame) drag.frame = requestAnimationFrame(dragFrame);
  }

  function dragFrame() {
    if (!drag?.started) return;
    drag.frame = 0;
    const { x, y } = drag.pointer;
    const dx = x - drag.from.x, dy = y - drag.from.y;
    for (const { element, base, scale } of drag.moving) {
      element.setAttribute("transform", `translate(${dx * scale} ${dy * scale})${base ? ` ${base}` : ""}`);
    }
    const at = dropAt(drag.pointer);
    if (!sameDrop(at, drag.at)) { drag.at = at; showDrop(at); }
    for (const { element } of drag.moving) element.classList.toggle("fig-astray", !at);
  }

  const dropAt = (point) => dropPlace(model(), drag.boxes, point, drag.id);
  const sameDrop = (a, b) => (a && b ? a.parent === b.parent && a.index === b.index && a.side === b.side : a === b);
  const unchanged = (at, id) => stays(model(), at, id);

  function showDrop(at) {
    for (const { element } of drag.parted) element.style.transform = "";
    drag.parted = [];
    if (!at) { drag.zone.classList.remove("on"); drag.indicator.classList.remove("on"); return; }
    const origin = host.overlay.getBoundingClientRect();
    const room = drag.boxes.get(at.parent) || SVG(host.element(model().root))?.getBoundingClientRect();
    const place = (node, box, extra = {}) => Object.assign(node.style, {
      transform: `translate(${box.left - origin.left}px, ${box.top - origin.top}px)`,
      width: `${Math.max(box.right - box.left, 0)}px`, height: `${Math.max(box.bottom - box.top, 0)}px`, ...extra });
    if (at.kind === "line") {
      // A line of its own: a slot where it lands, centred past the rest of the figure.
      const all = drag.boxes.get(model().root) || room;
      const own = drag.boxes.get(drag.id);
      const width = own ? own.right - own.left : 60, height = own ? own.bottom - own.top : 30;
      const mid = centre(all), gap = 18;
      const slot = at.side === "below" ? { left: mid.x - width / 2, top: all.bottom + gap }
        : at.side === "above" ? { left: mid.x - width / 2, top: all.top - gap - height }
          : at.side === "right" ? { left: all.right + gap, top: mid.y - height / 2 }
            : { left: all.left - gap - width, top: mid.y - height / 2 };
      place(drag.zone, { ...slot, right: slot.left + width, bottom: slot.top + height });
      drag.zone.dataset.label = at.side === "below" || at.side === "above" ? `A line of its own, ${at.side}` : `A column of its own, ${at.side}`;
      drag.zone.classList.add("on", "own-line");
      drag.indicator.classList.remove("on");
      return;
    }
    drag.zone.classList.remove("own-line");
    const home = unchanged(at, drag.id);
    drag.zone.classList.toggle("on", Boolean(room) && at.parent !== model().root && !home);
    if (room) place(drag.zone, { left: room.left - 6, top: room.top - 6, right: room.right + 6, bottom: room.bottom + 6 });
    if (at.empty || home) { drag.indicator.classList.remove("on"); return; }
    // The line between the part it goes next to and the one beyond, if there is one.
    const box = drag.boxes.get(at.near);
    const beyond = at.siblings.map((child) => ({ child, box: drag.boxes.get(child) })).filter(({ child, box: other }) => child !== at.near && (at.across
      ? (at.after ? other.left >= box.right - 1 : other.right <= box.left + 1) && other.bottom > box.top && other.top < box.bottom
      : (at.after ? other.top >= box.bottom - 1 : other.bottom <= box.top + 1) && other.right > box.left && other.left < box.right))
      .sort((a, b) => (at.across ? Math.abs(centre(a.box).x - centre(box).x) - Math.abs(centre(b.box).x - centre(box).x)
        : Math.abs(centre(a.box).y - centre(box).y) - Math.abs(centre(b.box).y - centre(box).y)))[0];
    let line;
    if (at.across) {
      const edge = at.after ? box.right : box.left;
      const other = beyond ? (at.after ? beyond.box.left : beyond.box.right) : edge + (at.after ? 12 : -12);
      const x = (edge + other) / 2;
      const top = Math.min(box.top, beyond?.box.top ?? box.top), bottom = Math.max(box.bottom, beyond?.box.bottom ?? box.bottom);
      line = { left: x - 1.5, right: x + 1.5, top: top - 4, bottom: bottom + 4 };
    } else {
      const edge = at.after ? box.bottom : box.top;
      const other = beyond ? (at.after ? beyond.box.top : beyond.box.bottom) : edge + (at.after ? 12 : -12);
      const y = (edge + other) / 2;
      const left = Math.min(box.left, beyond?.box.left ?? box.left), right = Math.max(box.right, beyond?.box.right ?? box.right);
      line = { left: left - 4, right: right + 4, top: y - 1.5, bottom: y + 1.5 };
    }
    place(drag.indicator, line);
    drag.indicator.classList.add("on");
    // The parts either side of it step apart, a little, to make room.
    const apart = 7;
    const nudge = (id, sign) => {
      for (const element of elementsOf(id)) {
        if (drag.moving.some((item) => item.element === element)) continue;
        const shift = sign * apart * unitsPerPixel(element);
        element.style.transform = at.across ? `translate(${shift}px, 0px)` : `translate(0px, ${shift}px)`;
        drag.parted.push({ element });
      }
    };
    nudge(at.near, at.after ? -1 : 1);
    if (beyond) nudge(beyond.child, at.after ? 1 : -1);
  }

  function dragFinish() {
    window.removeEventListener("pointermove", dragMove);
    window.removeEventListener("pointerup", dragEnd);
    window.removeEventListener("pointercancel", dragCancel);
    window.removeEventListener("keydown", dragKey, true);
    if (drag?.frame) cancelAnimationFrame(drag.frame);
    const was = drag;
    drag = null;
    if (!was?.started) return null;
    was.indicator.remove();
    was.zone.remove();
    document.body.classList.remove("fig-grabbing");
    for (const { element } of was.parted) element.style.transform = "";
    // A drag ends in a click on whatever is under the pointer: that click is not one.
    state.swallow = true;
    setTimeout(() => { state.swallow = false; }, 0);
    return was;
  }
  // Home again: the part slides back to where it was drawn, the lines come back.
  function sendHome(was) {
    clearTimeout(was.wait);
    host.overlay.classList.remove("fig-dragging");
    for (const { element, base } of was.moving) {
      const moved = /translate\(([-\d.e]+) ([-\d.e]+)\)/.exec(element.getAttribute("transform") || "");
      if (base) element.setAttribute("transform", base);
      else element.removeAttribute("transform");
      element.classList.remove("fig-lifted", "fig-settling", "fig-astray");
      if (moved) element.animate([{ transform: `translate(${moved[1]}px, ${moved[2]}px)` }, { transform: "translate(0px, 0px)" }],
        { duration: 220, easing: "cubic-bezier(.2,.8,.2,1)" });
    }
    for (const element of was.lines) element.classList.remove("fig-faded");
  }
  function dragEnd(event) {
    if (drag?.started && event) drag.pointer = { x: event.clientX, y: event.clientY };
    if (drag?.started) dragFrame();
    const was = dragFinish();
    if (!was) return;
    const at = was.at;
    if (!at || unchanged(at, was.id)) { sendHome(was); return; }
    // It stays where it was let go until the drawing it makes comes back and lands.
    for (const { element } of was.moving) element.classList.add("fig-settling");
    // Should no drawing come back (nothing changed after all), it goes home on its own.
    was.wait = setTimeout(() => { if (was.moving[0]?.element.isConnected) sendHome(was); }, 6000);
    act(at.kind === "line" ? { do: "move", id: was.id, line: at.side, of: at.of }
      : { do: "move", id: was.id, parent: at.parent, index: at.index }, { failed: () => sendHome(was) });
  }
  function dragCancel() { const was = dragFinish(); if (was) sendHome(was); }
  let landed = 0;
  function dragKey(event) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    dragCancel();
  }

  // -- landing: the drawing after an edit, each part sliding from where it was --
  function landing() {
    if (drag?.started) { dragFinish(); host.overlay.classList.remove("fig-dragging"); }  // its drawing is going
    if (!state.landing || Date.now() - state.landing > 6000 || !model()) return null;
    const before = new Map();
    for (const node of model().nodes) {
      const box = host.element(node.id)?.getBoundingClientRect();
      if (box && (box.width || box.height)) before.set(node.id, box);
    }
    return before;
  }
  function land(before) {
    host.overlay.classList.remove("fig-dragging");
    if (!before) return;
    state.landing = 0;
    const ease = "cubic-bezier(.2,.8,.2,1)";
    // The marks of what is chosen wait for the parts to arrive, then fade in on them.
    host.overlay.classList.add("fig-landing");
    clearTimeout(landed);
    landed = setTimeout(() => { host.overlay.classList.remove("fig-landing"); host.settled?.(); }, 320);
    for (const node of model()?.nodes || []) {
      const element = host.element(node.id);
      if (!element) continue;
      const now = element.getBoundingClientRect();
      const was = before.get(node.id);
      if (!was) {
        // A part just made grows in where it is drawn.
        element.style.transformBox = "fill-box";
        element.style.transformOrigin = "center";
        element.animate([{ opacity: 0, transform: "scale(0.94)" }, { opacity: 1, transform: "scale(1)" }], { duration: 240, easing: ease });
        continue;
      }
      const dx = centre(was).x - centre(now).x, dy = centre(was).y - centre(now).y;
      // One sized in proportion (a molecule's corner dragged) grows or shrinks the rest of the way.
      const grown = was.width / (now.width || 1);
      const sized = Math.abs(grown - 1) > 0.02 && Math.abs(was.height / (now.height || 1) - grown) < 0.05 * grown;
      if (Math.hypot(dx, dy) < 0.5 && !sized) continue;
      const scale = unitsPerPixel(element);
      if (sized) Object.assign(element.style, { transformBox: "fill-box", transformOrigin: "center" });
      element.animate([{ transform: `translate(${dx * scale}px, ${dy * scale}px)${sized ? ` scale(${grown})` : ""}` }, { transform: `translate(0px, 0px)${sized ? " scale(1)" : ""}` }],
        { duration: 300, easing: ease });
    }
    // Lines and frames are drawn anew for where the parts go: they come in as the parts
    // arrive. A frame that holds its parts fades its own drawing only, not theirs.
    const root = host.element(model()?.root);
    const appear = (element) => element.animate([{ opacity: 0 }, { opacity: 0 }, { opacity: 1 }], { duration: 340, easing: "ease-out" });
    for (const element of root?.querySelectorAll('[data-flexo-entity="connector"], [data-flexo-entity="net"]') || []) appear(element);
    for (const group of root?.querySelectorAll('[data-flexo-entity="group"]') || []) {
      for (const piece of group.children) {
        if (piece.matches('[data-flexo-entity], [id$=".components"], [id$=".connectors"]') || piece.querySelector("[data-flexo-entity]")) continue;
        appear(piece);
      }
    }
  }

  // -- words typed on the drawing --
  let inline = null;
  function openInline(id) {
    closeInline(false);
    const kind = typeOf(id);
    const item = kind === "node" ? nodeOf(id) : kind === "edge" ? edgeOf(id) : groupOf(id);
    if (!item || !host.box(id)) return;
    const original = words(item.label);
    // A label's words are names and maths, not prose: no spelling, no corrections.
    const field = ui.markup({ value: original, rows: 1, colours: false, spelling: false });
    // Typed where the words are, as they look there, when the part has words drawn to
    // lie over; else in a box under it.
    const label = host.element(`${id}.label`);
    const box = h(`div.fig-inline${label ? ".in-place" : ""}`, { title: "Enter to keep · Esc to leave · $maths$ · *emphasis*" }, field,
      label ? null : h("div.inline-foot", {}, h("span", {}, "Enter to keep · Esc to leave"), h("span", {}, "$maths$ · *emphasis*")));
    host.overlay.append(box);
    inline = { id, kind, field: field.area, original, box, inPlace: Boolean(label) };
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
    if (typeInto && !inline && host.box(typeInto)) {
      // Once it has landed where it is drawn.
      const id = typeInto;
      typeInto = null;
      setTimeout(() => { if (!inline && chosenOne() === id && host.box(id)) openInline(id); }, 320);
    }
    if (!inline) return;
    if (!inline.box.isConnected) host.overlay.append(inline.box);
    const where = host.box(inline.id);
    if (!where) return;
    const label = inline.inPlace && host.element(`${inline.id}.label`);
    if (!label) {
      Object.assign(inline.box.style, { left: `${where.left}px`, top: `${where.top + where.height + 6}px`, minWidth: `${Math.max(where.width, 240)}px` });
      return;
    }
    // Over the drawn words, in their face, size and colour; they step aside meanwhile.
    if (inline.label !== label) { inline.label?.style.removeProperty("visibility"); label.style.visibility = "hidden"; inline.label = label; }
    const style = getComputedStyle(label);
    const size = parseFloat(style.fontSize) * (label.getScreenCTM()?.a || 1);
    const outer = host.overlay.getBoundingClientRect(), drawn = label.getBoundingClientRect();
    const width = Math.max(drawn.width + 2 * size, where.width, 120);
    const middle = drawn.width ? drawn.left + drawn.width / 2 - outer.left : where.left + where.width / 2;
    const top = (drawn.height ? drawn.top - outer.top : where.top + where.height / 2 - size * 0.7) - 4;
    Object.assign(inline.box.style, { left: `${middle - width / 2}px`, top: `${top}px`, width: `${width}px`, minWidth: "" });
    Object.assign(inline.field.style, { fontSize: `${size}px`, fontFamily: style.fontFamily, fontWeight: style.fontWeight,
      color: style.fill && style.fill !== "none" ? style.fill : "", textAlign: "center" });
  }
  function closeInline(keep) {
    if (!inline) return;
    const { id, kind, field, original, box } = inline;
    inline.label?.style.removeProperty("visibility");
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
    // A part made a structure or a picture is drawn from a file: it is asked for, and
    // the part keeps its words (under the molecule, say) and its lines.
    const kinds = Object.entries(parts).filter(([kind, p]) => !p.unavailable || kind === node.kind);
    const retype = ui.select({ value: node.kind || "block", options: kinds.map(([kind, p]) => ({ value: kind, label: p.title })),
      onChange: async (value) => {
        const next = parts[value];
        if (!next?.needs_file || value === node.kind) { update({ type: "node", id: node.id }, { kind: value }); return; }
        const field = next.fields.find((item) => item.type === "file");
        const file = await host.chooseFile({ title: `Choose the ${next.title.toLowerCase()}'s file`, types: field?.types });
        if (!file) { retype.value = node.kind || "block"; return; }
        update({ type: "node", id: node.id }, { kind: value, "properties.source": file });
      } });
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
      ownLineSection(node.id),
    ];
  }

  // A part in a row put on a line of its own, under (or over) that row and centred on
  // it: a result drawn under the steps it compares. (Dragged out beside a figure laid out
  // in a column, a part takes a column of its own.)
  function ownLineSection(id) {
    const holder = parentOf(id);
    const kind = holder?.layout?.kind || (holder?.id === model().root ? "column" : "row");
    if (!holder || kind !== "row" || !(holder.children || []).some((child) => child !== id)) return null;
    return h("div.section", {}, h("div.section-title", {}, "On a line of its own"),
      h("div.row", {}, [["below", "Below", "down"], ["above", "Above", "up"]].map(([side, label, glyphName]) =>
        ui.button(label, () => act({ do: "move", id, line: side, of: holder.id }),
          { small: true, icon: glyphName, title: `On a line of its own ${side} the row, centred on it` }))),
      h("div.hint-line", {}, "Or drag it out under or over the figure."));
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
      isRoot ? null : ownLineSection(group.id),
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
        h("li", {}, h("b", {}, "Drag"), " a part to another place in its row or column, or into another group; Esc takes it back."),
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
    // Fields few reach for are folded away under the rest -- open, if one of them is set.
    const more = shown.filter((field) => field.more);
    const set = more.some((field) => valueAt(item, field.key) !== undefined && valueAt(item, field.key) !== null && valueAt(item, field.key) !== "");
    return h("div.fields", {}, shown.filter((field) => !field.more).map((field) => fieldControl(field, item, write, scope)),
      more.length ? h("details.more", { open: set }, h("summary", {}, icon("chevron"), "More"),
        h("div.inner.fields", {}, more.map((field) => fieldControl(field, item, write, scope)))) : null);
  }

  function fieldControl(field, item, write, scope) {
    const key = `${scope}:${field.key}`;
    const value = valueAt(item, field.key);
    const set = (next) => write({ [field.key]: next }, key);
    const options = { hint: field.hint };
    switch (field.type) {
      case "markup":
        return ui.field(field.label, ui.markup({ value: words(value), rows: 1, key, colours: false, spelling: false, onInput: set }), options);
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
      case "view": {
        // A molecule turned, tilted, and framed a step at a click, as in a viewer.
        const at = (name, fallback) => Number(valueAt(item, `properties.${name}`) ?? fallback);
        const turn = (name, by) => {
          const next = ((((at(name, 0) + by) % 360) + 540) % 360) - 180;
          write({ [`properties.${name}`]: next || null }, null);
        };
        const zoom = (by) => {
          const next = Math.round(at("zoom", 1) * by * 100) / 100;
          write({ "properties.zoom": next === 1 ? null : next }, null);
        };
        const button = (glyphName, title, run) => ui.button("", run, { small: true, icon: glyphName, title });
        return ui.field(field.label, h("div.view-pad", {},
          button("left", "Turn left 30°", () => turn("yaw", -30)),
          button("right", "Turn right 30°", () => turn("yaw", 30)),
          button("up", "Tilt back 30°", () => turn("pitch", -30)),
          button("down", "Tilt forward 30°", () => turn("pitch", 30)),
          h("span.sep"),
          button("minus", "Zoom out", () => zoom(1 / 1.25)),
          button("plus", "Zoom in", () => zoom(1.25)),
          h("span.sep"),
          button("refresh", "As it was: no turn, tilt, or zoom", () => write({ "properties.yaw": null, "properties.pitch": null, "properties.roll": null, "properties.zoom": null }, null))), options);
      }
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
      case "molpalette":
        return ui.field(field.label, groupPalette(item, value, set), options);
      case "molsketch":
        return styleSections(field, item, write);
      default:
        return null;
    }
  }

  // -- a structure's mol-sketch settings --
  // What it is drawn with -- its look's settings, the figure's colours, and its own --
  // asked of mol-sketch once for each way it is set, so each setting shows what it is.
  const settingsAsked = new Map();
  function settingsOf(id) {
    const key = JSON.stringify([id, nodeOf(id)?.properties]);
    if (!settingsAsked.has(key)) {
      if (settingsAsked.size > 40) settingsAsked.clear();
      settingsAsked.set(key, host.run({ do: "structure-settings", id }, { merge: null }).then((result) => result?.settings || null).catch(() => null));
    }
    return settingsAsked.get(key);
  }
  const swatchStrip = (colours = []) => h("span.palette-strip", {}, colours.slice(0, 8).map((colour) => h("span", { style: { background: colour } })));

  // mol-sketch's group palettes, by sight: the colours residues and chains take in turn.
  function groupPalette(item, value, set) {
    const name = () => value || "The look's";
    const button = h("button.palette-pick", { type: "button", disabled: true }, swatchStrip(), h("span", {}, name()), icon("chevron"));
    settingsOf(item.id).then((settings) => {
      const palettes = settings?.palettes || {};
      button.disabled = !Object.keys(palettes).length;
      button.replaceChildren(swatchStrip(palettes[value || settings?.style?.group_palette_name]), h("span", {}, name()), icon("chevron"));
      button.onclick = () => popover(button, h("div.palette-choices", {},
        h(`button.palette-choice${value ? "" : ".on"}`, { type: "button", onclick: () => { closeMenu(); set(null); } },
          swatchStrip(palettes[settings?.style?.group_palette_name] || []), h("span", {}, "The look's")),
        Object.entries(palettes).map(([option, colours]) => h(`button.palette-choice${option === value ? ".on" : ""}`, { type: "button",
          onclick: () => { closeMenu(); set(option); } }, swatchStrip(colours), h("span", {}, option)))),
      { className: "palette-menu" });
    });
    return button;
  }

  // Every section of mol-sketch's style the studio offers, folded away; one holding
  // settings of the structure's own says how many. Each setting shows what the look
  // (and the figure) make it until it is given its own; emptied, it is the look's again.
  const openSections = new Set();
  function styleSections(field, item, write) {
    const own = {};
    const walk = (value, prefix) => {
      for (const [key, part] of Object.entries(value || {})) {
        if (part && typeof part === "object" && !Array.isArray(part)) walk(part, `${prefix}${key}.`);
        else own[`${prefix}${key}`] = part;
      }
    };
    walk(item.properties?.style, "");
    const fills = [];
    const look = h("span.hint", {}, "Reading mol-sketch…");
    const ownCount = Object.keys(own).length;
    const sections = field.sections.map((section) => {
      const count = section.fields.filter((each) => own[each.key] !== undefined).length;
      const control = (each) => styleControl(each, own[each.key], fills,
        (next) => write({ [`properties.style.${each.key}`]: next }, `style:${item.id}:${each.key}`));
      // Colours as a row of wells; the rest two to a row, their hints on hover.
      const colours = section.fields.filter((each) => each.type === "colour");
      const rest = section.fields.filter((each) => each.type !== "colour");
      const details = h("details.more.mol-section", { open: openSections.has(section.title) },
        h("summary", {}, icon("chevron"), section.title, count ? h("span.count", {}, count) : null),
        h("div.inner", {},
          rest.length ? h("div.mol-grid", {}, rest.map(control)) : null,
          colours.length ? h("div.mol-colours", {}, colours.map(control)) : null));
      details.addEventListener("toggle", () => { if (details.open) openSections.add(section.title); else openSections.delete(section.title); });
      return details;
    });
    settingsOf(item.id).then((settings) => {
      if (!settings) { look.textContent = "mol-sketch could not be asked"; return; }
      look.textContent = `Over the ${settings.look} look`;
      for (const fill of fills) fill(settings.style || {});
    });
    return h("div.mol-style", {},
      h("div.mol-style-head", {}, h("span.section-title", {}, field.label), look,
        ownCount ? ui.button(`Back to the look (${ownCount})`, () => write({ "properties.style": null }, null), { small: true, kind: "ghost", icon: "refresh" }) : null),
      sections);
  }

  // One setting: what the look gives it shows until it has its own.
  function styleControl(field, value, fills, set) {
    const said = (drawn) => (drawn === null || drawn === undefined ? "" : typeof drawn === "number" ? String(Math.round(drawn * 1000) / 1000) : String(drawn));
    const options = {};
    const titled = (node) => { if (field.hint) node.title = field.hint; node.classList.toggle("own", value !== undefined); return node; };
    switch (field.type) {
      case "choice": {
        const select = ui.select({ value: value ?? "", options: [{ value: "", label: "The look's" }, ...field.options.map((option) => ({ value: option, label: option }))],
          onChange: (next) => set(next || null) });
        fills.push((drawn) => { select.options[0].textContent = `The look's: ${said(drawn[field.key])}`; });
        return titled(ui.field(field.label, select, options));
      }
      case "bool": {
        const select = ui.select({ value: value === undefined ? "" : value ? "on" : "off", options: [{ value: "", label: "The look's" }, { value: "on", label: "On" }, { value: "off", label: "Off" }],
          onChange: (next) => set(next === "" ? null : next === "on") });
        fills.push((drawn) => { select.options[0].textContent = `The look's: ${drawn[field.key] ? "on" : "off"}`; });
        return titled(ui.field(field.label, select, options));
      }
      case "integer":
      case "number": {
        const input = ui.number({ value: value ?? "", min: field.min, max: field.max, step: field.step ?? "any",
          onChange: (number) => set(number === null ? null : field.type === "integer" ? Math.round(number) : number) });
        fills.push((drawn) => { input.placeholder = said(drawn[field.key]); });
        return titled(ui.field(field.label, input, options));
      }
      case "colour": {
        const control = ui.colour({ value, title: field.label, onChange: set });
        // Unset, the well shows the look's colour, faintly.
        fills.push((drawn) => { if (value === undefined && /^#[0-9a-f]{6}$/i.test(drawn[field.key] || "")) control.querySelector(".colour-chip").style.background = drawn[field.key]; });
        return titled(h("div.mol-colour", {}, control, h("span", {}, field.label)));
      }
      default: {
        const input = ui.input({ value: value ?? "", onInput: (text) => set(text.trim() || null) });
        fills.push((drawn) => { input.placeholder = said(drawn[field.key]); });
        return titled(ui.field(field.label, input, options));
      }
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
    get dragging() { return Boolean(drag?.started); },
    get justDragged() { return state.swallow; },
    setModel, select, act, update, pointerdown, landing, land,
    typeOf, nameOf, nodeOf, groupOf, edgeOf, netOf, parentOf, nodeOfRef, partOf,
    idAt, click, dblclick, marks, markViews, hint, key, panel, wantsRoom, howTo, turnable,
    addPalette, addPart, gather, groupMenu, remove, duplicate, toggleConnect, clip, paste, menuOf,
    openInline, placeInline, closeInline,
  };
}
