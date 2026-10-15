// Groups of shapes entered as Inkscape's are, and taken apart at every level at once (for the
// shapes' editor, shapes.js: a slide's shapes, those drawn over a figure).
//
// A group double-clicked (or chosen and Return pressed, or Enter Group) is entered: its shapes
// are then the page's own to click, point at, drag, size, turn, restyle, retype, delete, copy,
// duplicate, nudge and lock one by one -- each change written back into the group, one step --
// and a group in it is entered by another double-click. A quiet frame shows the group's bounds,
// and a chip over it says where one is ("Slide 3 › Group › Group"), each level a way back to
// it. Esc steps out a level once nothing in it is chosen, the group then chosen; a click on the
// page's empty space leaves every level, and one on a shape outside the group leaves it and
// chooses that shape, at its own level, as Inkscape does. A change made inside is undone and
// redone inside, while the group is still there. ⌥-click chooses the shape under the pointer
// however deep in groups it is, entering them. Ungroup All takes the groups chosen apart,
// every level of them, in one step.
//
// What the page's host says (shapes.js) is seen from inside the group entered (`scoped`): its
// list the group's shapes, its edits written into the group, its ids the group's shapes' as the
// page draws them (`slide1.shapes.3.0`), its marks saying where the change was made
// (`inside`). What a page says of its own shapes -- a slide's builds, a figure's part a shape
// moves with -- is no group's shapes' to say: its commands and settings for them are not
// offered there, and what it says of a shape put in the group is taken off (but `locked`).
// (No imports: what it draws with is the editor's, given it by `bind`.)

// -- a group within groups, by the path to it --

const isGroup = (item) => Boolean(item) && typeof item === "object" && item.kind === "group" && Array.isArray(item.shapes);

// The group at `path` (an index in each level) in `list`, or null.
export function groupAt(list, path) {
  let group = null, shapes = list;
  for (const index of path) {
    const item = Array.isArray(shapes) ? shapes[index] : null;
    if (!isGroup(item)) return null;
    group = item;
    shapes = item.shapes;
  }
  return group;
}

// How many levels of `path` are groups in `list` still.
export function reached(list, path) {
  let shapes = list, depth = 0;
  for (const index of path) {
    const item = Array.isArray(shapes) ? shapes[index] : null;
    if (!isGroup(item)) break;
    shapes = item.shapes;
    depth += 1;
  }
  return depth;
}

// What a page says of its shapes that a group's may not (a slide's `build`, a figure's `on`):
// all of it but `locked`.
export const PLACED = ["on", "around", "margin", "side"];
export const strippedKeys = (ownKeys = []) => [...new Set([...ownKeys, ...PLACED])].filter((key) => key !== "locked");
const bare = (spec, strip) => (spec && typeof spec === "object" && strip.some((key) => key in spec)
  ? Object.fromEntries(Object.entries(spec).filter(([key]) => !strip.includes(key))) : spec);

// `list` with the shapes of the group at `path` changed by `mutate` (given them to change in
// place, or to answer anew), each group on the way to it copied, never changed where it is;
// what the page says of a shape (`strip`) taken off those put in it. A group left with no
// shapes goes, and so on up: a group is one shape at least.
export function within(list, path, mutate, { strip = [] } = {}) {
  const out = [...list];
  const levels = [];
  let shapes = out;
  for (const index of path) {
    if (!isGroup(shapes[index])) return out;
    const copy = { ...shapes[index], shapes: [...shapes[index].shapes] };
    shapes[index] = copy;
    levels.push({ holder: shapes, index, group: copy });
    shapes = copy.shapes;
  }
  if (!levels.length) {
    const changed = mutate(out);
    return Array.isArray(changed) ? changed : out;
  }
  const changed = mutate(shapes);
  levels[levels.length - 1].group.shapes = (Array.isArray(changed) ? changed : shapes).map((spec) => bare(spec, strip));
  for (let level = levels.length - 1; level >= 0; level -= 1) {
    const { holder, index, group } = levels[level];
    if (group.shapes.length) break;
    holder.splice(index, 1);
  }
  return out;
}

// A group's shapes with every level of it taken apart, in order: each as it was drawn (the
// opacity of the groups round it made its own).
export function leaves(group, opacity = 1) {
  const own = opacity * Number(group?.opacity ?? 1);
  return (group?.shapes || []).flatMap((child) => {
    if (!child || typeof child !== "object") return [];
    if (child.kind === "group") return leaves(child, own);
    if (Math.abs(own - 1) < 1e-9) return [child];
    const seen = Math.round(own * Number(child.opacity ?? 1) * 1000) / 1000;
    const out = { ...child };
    if (seen >= 1) delete out.opacity; else out.opacity = seen;
    return [out];
  });
}

// Whether a shape is a group with another in it: what Ungroup All takes apart and Ungroup not.
export const nested = (spec) => isGroup(spec) && spec.shapes.some(isGroup);
// Whether a group may be entered: one not locked, with shapes in it.
export const enterable = (spec) => isGroup(spec) && !spec.locked && spec.shapes.length > 0;

// The id the page draws a shape in the group at `path` with: the outermost group's (as the
// page names it), then its place in each level (`slide1.shapes.3.0.2`).
export const drawnId = (outer, path, index) => [outer, ...path.slice(1), index].join(".");

// -- the page's host, seen from inside a group --

const listOf = (host) => { const list = host.list(); return Array.isArray(list) ? list : []; };
const OWN = new Set(["commands", "panel", "grouped", "ungrouped", "attachNew", "drawnAt"]);

// `host` as the shapes' editor sees it from inside the group at `where()` (a path; empty, the
// page itself, `host` as it is).
export function scoped(host, where) {
  const inside = {
    list: () => groupAt(listOf(host), where())?.shapes || [],
    edit: (mutate, options) => {
      const path = where();
      // (The group gone meanwhile -- undone, another's change: nothing to write into.)
      if (!groupAt(listOf(host), path)) return false;
      return host.edit((list) => within(list, path, mutate, { strip: strippedKeys(host.ownKeys) }), options);
    },
    idOf: (index, at) => drawnId(host.idOf(where()[0], at), where(), index),
    mark: (said) => host.mark({ ...said, inside: [...where()] }),
    // (Copied in the group and pasted in it again, a copy is set aside, as on the page.)
    source: () => `${host.source?.() ?? `${host.noun || "page"}:${host.page()}`} › ${where().join(".")}`,
  };
  return new Proxy(host, {
    get(target, key) {
      if (!where().length) return Reflect.get(target, key);
      if (Object.hasOwn(inside, key)) return inside[key];
      if (OWN.has(key)) return undefined;
      return Reflect.get(target, key);
    },
  });
}

// -- going in and out --

// The groups entered on the page of `page` (the host as the page gives it). `host` is what the
// editor is to use instead; `bind(editor)` gives it what it draws and chooses with (see below).
export function groupTools(page) {
  let path = [];
  let on = null;
  let waiting = null;  // a change undone inside a group not yet drawn again (a figure's)
  let editor = null;
  const here = () => {
    if (path.length && page.page() !== on) path = [];
    return path;
  };
  const host = scoped(page, here);
  const topList = () => listOf(page);

  // `editor`: what the shapes' editor lends -- S, h, icon, ui (to draw with), layer, before
  // (the layer's group the frame goes under), pageNode(), stage() (what the page is shown
  // in), toScreen(point), unit(); list()
  // (the shapes where one is), chosen(), choose(indices, options), hit(event) (the shape
  // under the pointer where one is), union(indices) (their bounds), busy() (a drag under
  // way), settle() (words typed and points edited, put away), place(), renderInspector(),
  // reportFocus(), edit(mutate, label, options), ungrouped (the page's own, for those taken
  // apart), label(spec), crumb() (the page, as its way back up names it).
  function bind(given) {
    editor = given;
    frame = editor.S("g", { class: "shape-entered" });
    editor.layer.insertBefore(frame, editor.before);
  }

  // Into `next`, `picks` chosen there (`quiet`: the editor draws them).
  function go(next, picks = [], { quiet = false } = {}) {
    editor.settle();
    waiting = null;
    path = [...next];
    on = page.page();
    editor.choose(picks, { quiet });
    paint();
  }

  // The shape under the pointer from `from` -- and, `deep`, in the groups under it, those
  // entered: where it is, and which it is (null, none).
  function under(event, from, deep) {
    const was = path, wasOn = on;
    path = [...from];
    on = page.page();
    let found = null;
    try {
      for (;;) {
        const index = editor.hit(event);
        if (index === null) {
          // (A group hit, but none of its shapes -- its words beside it: the group itself.)
          if (path.length > from.length) found = path.pop();
          break;
        }
        if (deep && enterable(editor.list()[index])) { path.push(index); continue; }
        found = index;
        break;
      }
      return { path: [...path], index: found };
    } finally {
      path = was;
      on = wasOn;
    }
  }

  // The group `index` where one is, entered: what is under `at` in it chosen -- and, `deep`
  // (a drawing just made editable), the groups under it entered too.
  function enter(index, { at = null, deep = false } = {}) {
    const from = here();
    if (!enterable(editor.list()[index])) return false;
    const found = at ? under(at, [...from, index], deep) : { path: [...from, index], index: null };
    go(found.path, found.index === null ? [] : [found.index]);
    return true;
  }

  // Out to `depth` levels (0, the page), the group left there chosen (`pick`).
  function out(depth = here().length - 1, { pick = true } = {}) {
    const from = here();
    if (!from.length || depth < 0 || depth >= from.length) return false;
    go(from.slice(0, depth), pick ? [from[depth]] : []);
    return true;
  }

  // Out of every group, nothing chosen (`quiet`: what the page shows is the host's to draw).
  function leave({ quiet = false } = {}) {
    if (!here().length && !waiting) return false;
    const wasInside = here().length > 0;
    editor.settle();
    waiting = null;
    path = [];
    editor.choose([], { quiet: true });
    editor.place();
    if (!quiet && wasInside) { editor.renderInspector(); editor.reportFocus(); }
    paint();
    return wasInside;
  }

  // Pressed where nothing of the group is: a shape outside it, at its own level -- out to
  // there, nothing chosen yet (its index, for the press to choose); else out of every group
  // (null). Outside one, null.
  function outward(event) {
    const from = here();
    if (!from.length) return null;
    for (let depth = from.length - 1; depth >= 0; depth -= 1) {
      const found = under(event, from.slice(0, depth), false);
      if (found.index !== null && found.index !== from[depth]) {
        go(found.path, [], { quiet: true });
        return found.index;
      }
    }
    leave();
    return null;
  }

  // ⌥-click: the shape under the pointer however deep in groups, those round it entered.
  function deepPick(event) {
    const found = under(event, here(), true);
    if (found.index === null) return false;
    go(found.path, [found.index]);
    return true;
  }

  // Undone or redone: inside the group the change was made in, while it is there (`said`, the
  // shapes' mark; `picks`, what it chose). A figure drawn again only later: once it is.
  function restore(said, picks) {
    const want = Array.isArray(said?.inside) ? said.inside : [];
    if (!want.length) { leave({ quiet: true }); return true; }
    if (groupAt(topList(), want)) {
      editor.settle();
      path = [...want];
      on = page.page();
      waiting = null;
      paint();
      return true;
    }
    editor.settle();
    path = [];
    waiting = { path: [...want], picks: [...picks], on: page.page() };
    paint();
    return false;
  }

  // The page drawn again, or changed: a group no longer there is left (the level it was in
  // kept, while that is still there); one waited for, entered once it is. True if it went
  // elsewhere (and so drew what is chosen there).
  function check() {
    if (waiting && waiting.on === page.page() && groupAt(topList(), waiting.path)) {
      const { path: next, picks } = waiting;
      waiting = null;
      go(next, picks.filter((index) => index < (groupAt(topList(), next)?.shapes.length || 0)));
      return true;
    }
    const from = here();
    if (!from.length) return false;
    const depth = reached(topList(), from);
    if (depth === from.length) return false;
    go(from.slice(0, depth));
    return true;
  }
  // Inside a group, every name the page's shapes have (none taken twice: a copy made in the
  // group is named apart from them all), found again only once they change.
  let named = { list: null, names: [] };
  function names() {
    if (!here().length) return [];
    const list = topList();
    if (named.list !== list) {
      const found = [];
      const walk = (items) => items.forEach((item) => {
        if (!item || typeof item !== "object") return;
        if (item.id !== undefined && item.id !== null) found.push(String(item.id));
        if (isGroup(item)) walk(item.shapes);
      });
      walk(list);
      named = { list, names: found };
    }
    return named.names;
  }

  // What the editor's place() does first: true if it went elsewhere (and so placed it all).
  function update() {
    if (check()) return true;
    paint();
    return false;
  }

  // -- what shows it: a quiet frame round the group, and a chip naming where one is --

  let frame = null;
  let chip = null;
  let chipKey = "";
  let box = null;
  let boxOf = null;
  function paint() {
    if (!editor || !frame) return;
    const node = editor.pageNode(), inside = here();
    if (!inside.length || !node) {
      frame.replaceChildren();
      if (chip) chip.hidden = true;
      box = boxOf = null;
      return;
    }
    // (While a drag is under way, as it was when it began -- nothing measured, at each move --
    // and drawn again as it lands; its bounds found again only once its shapes change, or the
    // page is drawn again, its words measured anew.)
    if (editor.busy() && box && chip && !chip.hidden && chip.parentNode === node) return;
    const shapes = editor.list(), drawing = node.firstElementChild;
    if (shapes !== boxOf?.shapes || drawing !== boxOf?.drawing) box = editor.union(shapes.map((_, index) => index).filter((index) => shapes[index]));
    boxOf = box ? { shapes, drawing } : null;
    if (!box) { frame.replaceChildren(); if (chip) chip.hidden = true; return; }
    const px = 1 / editor.unit(), pad = 5 * px;
    const [x0, y0, x1, y1] = [box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad];
    let rect = frame.firstChild;
    if (!rect) frame.append(rect = editor.S("rect", { class: "shape-entered-frame" }));
    rect.setAttribute("x", x0);
    rect.setAttribute("y", y0);
    rect.setAttribute("width", Math.max(x1 - x0, 0));
    rect.setAttribute("height", Math.max(y1 - y0, 0));
    rect.setAttribute("stroke-width", px);
    rect.setAttribute("rx", 3 * px);
    // The chip: just over the page, in line with the frame's left -- off it, where it covers
    // nothing and stays put whatever is chosen -- or, the page filling the stage, over the
    // frame's top left, in view. (Under the handles of what is chosen, either way: shapes.css.)
    const key = `${editor.crumb()}|${inside.join(".")}`;
    if (!chip || key !== chipKey) { chip?.remove(); chip = crumbsChip(); chipKey = key; }
    if (chip.parentNode !== node) node.append(chip);
    chip.hidden = false;
    const outer = node.getBoundingClientRect(), seen = editor.stage()?.getBoundingClientRect();
    const [sx, sy] = editor.toScreen([x0, y0]);
    const height = chip.offsetHeight || 22, width = chip.offsetWidth || 120;
    const left = Math.max(0, Math.min(sx - outer.left, node.clientWidth - width));
    const room = seen ? outer.top - seen.top : 0;
    const off = room >= height + 10;
    const top = off ? -height - 6 : Math.max(sy - outer.top - height - 4, (seen ? seen.top - outer.top : -outer.top) + 4);
    chip.style.left = `${Math.round(left)}px`;
    chip.style.top = `${Math.round(top)}px`;
  }
  // The levels, each a way back to it: the page (out of every group, the outermost chosen),
  // each group round the one one is in (out to it, the one left chosen), the one one is in,
  // and ✕ (out a level, as Esc).
  function crumbsChip() {
    const { h, icon } = editor, inside = here();
    const kept = (event) => { event.stopPropagation(); };
    const items = [h("button.group-crumb", { type: "button", title: "Leave every group", onclick: () => out(0) }, editor.crumb())];
    let shapes = topList();
    inside.forEach((index, depth) => {
      const spec = shapes[index];
      shapes = spec?.shapes || [];
      const name = editor.label(spec);
      const named = spec?.id !== undefined ? `${name} · ${spec.id}` : name;
      items.push(icon("chevron"));
      items.push(depth === inside.length - 1
        ? h("span.group-crumb.here", { title: named }, name)
        : h("button.group-crumb", { type: "button", title: `Back to ${named}`, onclick: () => out(depth + 1) }, name));
    });
    items.push(h("button.group-leave", { type: "button", title: "Leave Group (Esc)", "aria-label": "Leave Group", onclick: () => out() }, icon("close")));
    const node = h("div.group-chip", { role: "navigation", "aria-label": "Group entered" }, items);
    // (Its own: never a press, a click or a double-click on the page under it.)
    for (const name of ["pointerdown", "mousedown", "click", "dblclick", "contextmenu", "mousemove"]) node.addEventListener(name, kept);
    return node;
  }

  // -- the keys, commands and settings --

  // Return with a group chosen enters it, as Return goes into what is chosen; inside one with
  // nothing chosen, Esc steps out (the group chosen) and ⌘A chooses all its shapes.
  function key(event) {
    if (!editor) return false;
    const mod = event.metaKey || event.ctrlKey, k = event.key, picks = editor.chosen(), list = editor.list();
    if (k === "Enter" && !mod && !event.altKey && !event.shiftKey && picks.length === 1 && enterable(list[picks[0]])) { enter(picks[0]); return true; }
    if (!here().length || picks.length) return false;
    if (k === "Escape" && !mod) { out(); return true; }
    if (mod && !event.altKey && !event.shiftKey && k.toLowerCase() === "a") { editor.choose(list.map((_, n) => n).filter((n) => list[n])); return true; }
    return false;
  }

  // The groups chosen taken apart at every level, one step: each shape of them where the
  // groups were, the page's own settings of the group (a slide's build, a figure's part) its.
  function ungroupAll() {
    const list = editor.list(), picks = editor.chosen().filter((index) => isGroup(list[index]));
    if (!picks.length) return;
    const next = [], after = [];
    list.forEach((spec, index) => {
      if (!picks.includes(index)) { next.push(spec); return; }
      for (const leaf of leaves(spec)) {
        after.push(next.length);
        next.push({ ...leaf, ...(editor.ungrouped(spec, leaf) || {}) });
      }
    });
    editor.edit(() => next, "Ungroup All", { after });
  }

  // The palette's (and the right-click menu's): Enter Group with one group chosen, Ungroup All
  // with a group of groups chosen, Leave Group inside one.
  function commands() {
    if (!editor) return [];
    const list = editor.list(), picks = editor.chosen(), found = [];
    const one = picks.length === 1 ? list[picks[0]] : null;
    if (enterable(one)) found.push({ icon: "layout", label: "Enter Group", keys: "↩", hint: "Its shapes, to choose one by one · or double-click it", run: () => enter(picks[0]) });
    if (picks.some((index) => nested(list[index]))) found.push({ icon: "layout", label: "Ungroup All", hint: "Every group in it taken apart too", run: () => ungroupAll() });
    if (here().length) found.push({ icon: "close", label: "Leave Group", hint: "Back out to the group, chosen (Esc)", run: () => out() });
    return found;
  }
  // The right-click menu's, by name from those commands (`named`).
  const menuItems = (named) => ["Enter Group", "Ungroup All", "Leave Group"].map(named).filter(Boolean);

  // The inspector's way back up, between the page and what is chosen: each group round it.
  function crumbs() {
    if (!editor) return [];
    const { h, icon } = editor, inside = here();
    let shapes = topList();
    return inside.flatMap((index, depth) => {
      const spec = shapes[index];
      shapes = spec?.shapes || [];
      return [icon("chevron"), h("button.crumb", { type: "button", title: "Back to this group, chosen", onclick: () => out(depth) }, editor.label(spec))];
    });
  }
  // The inspector's Arrange, for a group chosen: Enter Group, and Ungroup All for a group of groups.
  function panelRows(picks) {
    if (!editor) return [];
    const list = editor.list(), one = picks.length === 1 ? list[picks[0]] : null;
    const buttons = [
      enterable(one) ? editor.ui.button("Enter Group", () => enter(picks[0]), { small: true, kind: "ghost", icon: "layout", title: "Its shapes, to choose one by one (↩, or double-click it)" }) : null,
      picks.some((index) => nested(list[index])) ? editor.ui.button("Ungroup All", () => ungroupAll(), { small: true, kind: "ghost", icon: "layout", title: "Every group in it taken apart too" }) : null,
    ].filter(Boolean);
    return buttons.length ? [editor.h("div.row", {}, buttons)] : [];
  }

  return {
    host, bind, enter, out, leave, outward, deepPick, restore, check, update, paint, key, commands, menuItems, crumbs, panelRows, ungroupAll, names,
    path: () => [...here()],
    depth: () => here().length,
    // The page's own shapes, whatever group is entered.
    top: topList,
  };
}
