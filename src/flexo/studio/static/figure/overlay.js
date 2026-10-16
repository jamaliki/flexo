// Shapes drawn over a figure (flexo.figure_shapes): the figure editor's host for the shapes'
// editor (studio/shapes.js), as a deck's slide is the deck editor's. The figure draws them where
// they are placed on it -- on a part, round parts, their ends glued to parts -- and says so
// (its drawing's `info`: each shape as placed, every part's box): here they are edited as
// placed, and written back as they are written -- on a part, its places from that part's top
// left; round parts, no places of their own while it still goes round them; moved or sized, on
// the first of them -- through the figure's own edit (`shapes`), made to its file's words.
// A shape drawn on a part is put on it, and moves with it; a ring, a highlight, a box or a brace
// drawn with a click on a part goes round it. An end let go on a part, or on a piece of one (a
// protein's feature, a tree's tip), is glued to it.

import { h, ui, menu, toast } from "/static/studio/studio.js";
import * as F from "/static/studio/freeform.js";
import { shapeEditor, shapeLabel, shapeIcon } from "/static/studio/shapes.js";
import * as Insets from "/static/studio/insets.js";
import { aroundBox, placedRound as placeRound, sideOf } from "/static/kinds/figure/around.js";
import { CONVERT, convertible, convertCommand } from "/static/studio/toparts.js";

// The kinds a click on a part draws round it.
const ROUNDABLE = new Set(["ring", "ellipse", "highlight", "rectangle", "rounded-rectangle", "cloud", "brace", "bracket", "dimension"]);
// What a shape on a figure says besides how it is drawn.
const OWN = ["on", "around", "margin", "side", "behind", "locked"];
const PLACES = { box: ["at", "size"], text: ["at", "width"], line: ["from", "to"], points: ["points"], path: ["d"] };
// Pieces of a drawing that are no part to point at of their own: a part's words, its box.
const PIECE_ENDS = /\.(label|body|outline|shadow|hit|text|container|components|connectors|artwork)$/;

const copyOf = (value) => (value === undefined ? undefined : structuredClone(value));
const round = (value) => Math.round(value * 100) / 100;
const roundAll = (value) => (typeof value === "number" ? round(value) : Array.isArray(value) ? value.map(roundAll)
  : value && typeof value === "object" ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, roundAll(item)])) : value);
const near = (a, b) => (Array.isArray(a) && Array.isArray(b) ? a.length === b.length && a.every((item, n) => near(item, b[n]))
  : typeof a === "number" && typeof b === "number" ? Math.abs(a - b) < 0.05 : JSON.stringify(a) === JSON.stringify(b));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
// The same whatever order its keys are written in.
const sorted = (value) => (Array.isArray(value) ? value.map(sorted) : value && typeof value === "object"
  ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, sorted(value[key])])) : value);
const alike = (a, b) => JSON.stringify(sorted(a)) === JSON.stringify(sorted(b));

// (Round parts, as the figure draws them: around.js.)
const placedRound = (spec, box) => placeRound(spec, box, F.family, F.fittedPath);

// The figure editor's shapes: `studio`, the figure's parts (`figure`, parts.js), its page (the
// element its <svg> is in), the stage and the middle (`center`), the toolbar's Draw button;
// what the editor does when they are chosen (`changed`: its inspector, its list, its bar), and
// its Cut, Copy and Paste for their menu (`clipItems`); and its parts chosen with them, when
// they are (`withParts`: mixed.js's choice of both).
export function figureShapes({ studio, figure, page, stage, center, button, changed, clipItems = () => [], withParts = () => null }) {
  const catalog = studio.catalog?.shapes || {};
  const margins = catalog.margins || { highlight: 2, ring: 3, ellipse: 3, brace: 4, bracket: 4 };
  const marginOf = (spec) => (spec.margin ?? margins[spec.kind] ?? catalog.margin ?? 6);
  let info = studio.info || {};
  // Shapes changed here, before the figure drawn with them comes: as changed (`list`), and as
  // they were sent to be written (`written`).
  let waiting = null;
  let swallowed = 0;
  const drawn = () => (Array.isArray(info.shapes) ? info.shapes : []);
  const list = () => waiting?.list || drawn();
  const writtenNow = () => waiting?.written || (Array.isArray(figure.model?.shapes) ? figure.model.shapes : []);
  const boxes = () => info.boxes || {};
  const svg = () => page.querySelector(":scope > svg:not(.shape-layer)");
  const nameOf = (id) => (figure.typeOf(id) ? figure.nameOf(id) : id);

  // -- what the figure holds, a shape may be glued to, put on or drawn round --
  // Its shapes, groups and frames by id, as the figure laid them out (but its own layout, and
  // a group that only arranges what it holds, which is drawn as nothing).
  function parts() {
    const found = new Map(), root = figure.model?.root;
    for (const [id, box] of Object.entries(boxes())) {
      const group = figure.groupOf(id);
      if (id === root || group?.implied || group?.role === "layout") continue;
      if (!figure.nodeOf(id) && !group) continue;
      found.set(id, { box: [...box], turn: 0, outline: null, name: id, label: nameOf(id) });
    }
    return found;
  }
  // The smallest part whose box holds `point`.
  function partUnder(point) {
    let best = null;
    for (const [id, part] of parts()) {
      const [x, y, w, h] = part.box;
      if (point[0] < x || point[0] > x + w || point[1] < y || point[1] > y + h) continue;
      if (!best || w * h < best.area) best = { id, area: w * h };
    }
    return best?.id || null;
  }
  // A piece of a part under the pointer: the innermost element of the figure's drawing there
  // with an id of its own under a part's (a protein's feature, `spike.feature2`), not its words.
  function pieceAt(event, toFrame) {
    const drawing = svg();
    if (!drawing) return null;
    const nodes = new Set((figure.model?.nodes || []).map((node) => node.id));
    for (const hit of document.elementsFromPoint(event.clientX, event.clientY)) {
      if (!drawing.contains(hit) || hit === drawing) continue;
      for (let at = hit; at && at !== drawing; at = at.parentElement) {
        const id = at.id || "";
        const owner = id.includes(".") ? [...nodes].find((node) => id.startsWith(`${node}.`)) : null;
        if (!owner || PIECE_ENDS.test(id) || nodes.has(id)) continue;
        const rect = at.getBoundingClientRect();
        if (!rect.width && !rect.height) continue;
        const a = toFrame(rect.left, rect.top), b = toFrame(rect.right, rect.bottom);
        return { box: [a[0], a[1], b[0] - a[0], b[1] - a[1]], turn: 0, outline: null, name: id, label: `${nameOf(owner)} · ${id.slice(owner.length + 1)}` };
      }
      return null;
    }
    return null;
  }
  // A piece a shape names, where the figure drew it: as it said, else as it is on the page.
  function piece(name, toFrame) {
    if (boxes()[name]) return { box: [...boxes()[name]], turn: 0, outline: null, name, label: name };
    const element = svg()?.querySelector(`[id="${CSS.escape(name)}"]`);
    const rect = element?.getBoundingClientRect();
    if (!rect || (!rect.width && !rect.height)) return null;
    const a = toFrame(rect.left, rect.top), b = toFrame(rect.right, rect.bottom);
    return { box: [a[0], a[1], b[0] - a[0], b[1] - a[1]], turn: 0, outline: null, name, label: name };
  }

  // -- as drawn, and as written --
  // Each shape as it is to be written, from as it is drawn: on a part, its places from that
  // part's top left; round parts, none of its own while it is still round them -- moved or
  // sized, it is on the first of them instead, where it was put. One unchanged is as written.
  // (One not drawn -- written wrong, or round parts the figure has none of -- is kept as it is
  // written: the nth of those in the list is the nth it had.)
  function written(next, before, wrote) {
    const unwritten = before.map((spec, index) => (spec ? null : wrote[index])).filter((spec) => spec !== null && spec !== undefined);
    return next.map((spec) => {
      if (!spec) return unwritten.length ? copyOf(unwritten.shift()) : null;
      const was = before.findIndex((old) => old && same(old, spec));
      if (was >= 0 && wrote[was]) return copyOf(wrote[was]);
      return writtenOne(spec);
    }).filter(Boolean);
  }
  function writtenOne(spec) {
    let out = copyOf(spec);
    const places = PLACES[F.family(out.kind)] || [];
    if (Array.isArray(out.around) && out.around.length) {
      const found = out.around.map((id) => boxes()[id]).filter(Boolean);
      const placed = found.length ? placedRound(out, aroundBox(found, marginOf(out), out.kind)) : null;
      if (placed && places.every((key) => near(placed[key], out[key]))) {
        for (const key of places) delete out[key];
        return roundAll(out);
      }
      // Moved, sized or turned out of its place round them: on the first, where it is now.
      const on = out.around[0];
      delete out.around; delete out.margin; delete out.side;
      out = { ...out, on };
    }
    if (out.on !== undefined && out.on !== null) {
      const box = boxes()[out.on];
      if (box) out = F.moved(out, -box[0], -box[1]);
      if (out.kind === "group") out.shapes = (out.shapes || []).map((child) => { const { on: _on, ...rest } = child; return rest; });
    }
    return roundAll(out);
  }
  // A shape put on the part it is drawn on: what its middle is on, the smallest such part.
  function attachNew(spec) {
    if (spec.on !== undefined || spec.around || F.family(spec.kind) === "line") return spec;
    const made = F.geometry(spec), [x, y, w, h] = made.box;
    // (A box of words by where its words start, as wide as they are yet unknown.)
    const at = spec.kind === "text" && !spec.width ? [x + 8, y + h / 2] : [x + w / 2, y + h / 2];
    const on = partUnder(at);
    return on ? { ...spec, on } : spec;
  }
  // Drawn with a click on a part, a ring (a highlight, a box, a brace) goes round it -- and one
  // filled, so that it would hide the part, behind it: a backdrop the part stands on.
  function drawnAt(kind, point, press) {
    if (!ROUNDABLE.has(kind)) return null;
    const under = press && figure.idAt(press);
    const id = under && under !== figure.model?.root && (figure.nodeOf(under) || figure.groupOf(under)) ? under : partUnder(point);
    if (!id || !boxes()[id]) return null;
    const spec = { kind, around: [id], ...(hides(spec0(kind)) ? { behind: true } : {}) };
    return placedRound(spec, aroundBox([boxes()[id]], marginOf(spec), kind));
  }
  const spec0 = (kind) => F.normalised({ kind });
  // Whether a shape would hide what it is drawn over: a fill of its own, more than half there.
  const hides = (spec) => F.isClosed(spec) && spec.fill && spec.fill !== "none" && Number(spec.fill_opacity ?? 1) > 0.5;

  // -- edits, through the figure's own --
  let lastJob = null;
  function edit(mutate, { label = null, merge = null, hold = false, show = null } = {}) {
    if (!figure.model) return false;
    const before = copyOf(list()), wrote = copyOf(writtenNow());
    const next = mutate(copyOf(before)) || before;
    const sent = written(next, before, wrote);
    waiting = { list: next, written: sent };
    // (What it chose before and after, kept with the change once it has landed: its undo.)
    const job = { said: null };
    lastJob = job;
    figure.act({ do: "shapes", shapes: sent, ...(show ? { show } : {}) }, {
      label: label || "Edit Shapes", merge, hold, select: false,
      then: () => {
        const entry = studio.past[studio.past.length - 1];
        if (entry && job.said) studio.said(entry).shapes = job.said;
      },
      failed: () => { waiting = null; editor.drawn(); },
    });
    return true;
  }

  const editor = shapeEditor({
    studio, center, stage, catalog,
    later: true,
    page: () => 0,
    list,
    pageNode: () => page,
    idOf: (index) => { const spec = list()[index]; return spec?.id !== undefined && spec?.id !== null ? String(spec.id) : `shapes.${index}`; },
    frame: () => { const view = svg()?.viewBox?.baseVal; return view && view.width ? [view.x, view.y, view.width, view.height] : [0, 0, 600, 400]; },
    roles: () => info.roles || {},
    edit,
    mark: (said) => { if (lastJob) lastJob.said = said; },
    goTo: () => {},
    glueKey: "part",
    objects: () => parts(),
    piece, pieceAt,
    pieceLabel: (name) => name,
    partAt: (event) => { const id = figure.idAt(event); return Boolean(id && id !== figure.model?.root); },
    leaveOthers: () => { if (figure.selected.length && !withParts()?.joining()) figure.select([]); },
    others: () => Boolean(withParts()?.on()),
    renderInspector: () => changed(),
    reportFocus: () => {},
    swallowRelease: () => { swallowed = Date.now(); },
    undoNote: () => {},
    awayFrom: () => false,
    clipItems: () => clipItems(),
    canDraw: () => Boolean(figure.model),
    shapeButton: () => button,
    wordSize: () => info.sizes?.words || 8,
    fonts: () => info.fonts || {},
    wordsLabel: (spec) => (spec.text ? "Edit Text" : "Add Text"),
    verb: "Draw", noun: "figure", chooserLabel: "Draw Shape…", crumb: () => "Figure", fontOwner: "Figure",
    source: () => `figure:${studio.file}`,
    behindNames: ["Send Behind the Figure", "Bring Above the Figure"], behindInPanel: true,
    armHint: (kind, label) => (ROUNDABLE.has(kind) ? `${label}: drag on the figure to draw it, or click a part to draw it round that · Esc to stop` : null),
    ownKeys: OWN,
    attachNew, drawnAt,
    grouped: (specs) => {
      const on = specs.every((spec) => spec?.on !== undefined && spec.on === specs[0].on) ? { on: specs[0].on } : {};
      return { ...on, ...(specs.every((spec) => spec?.behind) ? { behind: true } : {}) };
    },
    ungrouped: (group) => ({ ...(group.on !== undefined ? { on: group.on } : {}), ...(group.behind ? { behind: true } : {}), ...(group.locked ? { locked: true } : {}) }),
    commands: (picks, name) => showCommands(picks, name),
    panel: (picks, specs, tools) => attachPanel(picks, specs, tools),
    // A zoom inset's part, as the figure laid it out and drew it (its own id, in its units).
    insetSource: (spec, toFrame) => {
      const id = spec?.of !== undefined ? String(spec.of) : "", box = id ? boxes()[id] || piece(id, toFrame)?.box : null;
      if (!box || !svg()?.querySelector(`[id="${CSS.escape(id)}"]`)) return null;
      return { box: [...box], target: id, toShapes: { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 } };
    },
  });

  // Add Zoom Inset, with a part chosen: a box beside it showing its middle magnified, on it
  // (moving with it as the figure is laid out), chosen at once -- one step.
  const insettable = (id) => Boolean(id && id !== figure.model?.root && (figure.nodeOf(id) || figure.groupOf(id)) && boxes()[id]);
  function addInset(id) {
    if (!insettable(id)) return false;
    // (Beside it, the page growing to hold it where the figure has no room: as large as a
    // part of it would be.)
    const view = svg()?.viewBox?.baseVal, [vx, vy, vw, vh] = view && view.width ? [view.x, view.y, view.width, view.height] : [0, 0, 600, 400];
    const frame = [vx - vw * 0.5, vy - vh * 0.5, vw * 2, vh * 2];
    const spec = { ...Insets.fresh(boxes()[id], frame, { of: id, margin: 12 }), on: id };
    const index = list().length;
    edit((all) => [...all, spec], { label: "Add Zoom Inset" });
    editor.choose([index]);
    return true;
  }

  // -- shown plainly, faint, or not at all: the figure's own hide and dim --
  const shownAs = (spec, index) => {
    const id = spec?.id !== undefined ? String(spec.id) : `shapes.${index}`, settings = figure.model?.figure || {};
    return (settings.hide || []).includes(id) ? "hidden" : (settings.dim || []).includes(id) ? "dimmed" : "shown";
  };
  // Named first, should it have no name of its own (a shape's place in the list is no name to
  // keep: it changes as shapes are added and stacked).
  function showAs(picks, how) {
    const shapes = list(), taken = new Set(shapes.flatMap(function names(spec) { return spec ? [spec.id, ...(spec.kind === "group" ? (spec.shapes || []).flatMap(names) : [])] : []; }).filter((id) => id !== undefined).map(String));
    const named = picks.map((index) => {
      const spec = shapes[index];
      if (spec?.id !== undefined) return String(spec.id);
      const base = ({ "rounded-rectangle": "box", rectangle: "box", ellipse: "oval", text: "label" })[spec.kind] || String(spec.kind).replace(/[^a-z]/g, "");
      let n = 1;
      while (taken.has(`${base}${n}`) || figure.typeOf(`${base}${n}`)) n += 1;
      taken.add(`${base}${n}`);
      return `${base}${n}`;
    });
    const label = `${{ hidden: "Hide", dimmed: "Dim", shown: "Show" }[how]} ${picks.length === 1 ? shapeLabel(shapes[picks[0]]) : `${picks.length} Shapes`}`;
    // (Named and shown so in one step.)
    if (picks.some((index) => shapes[index]?.id === undefined)) {
      edit((all) => { picks.forEach((index, n) => { if (all[index] && all[index].id === undefined) all[index] = { kind: all[index].kind, id: named[n], ...all[index] }; }); return all; },
        { label, show: { ids: named, as: how } });
      return;
    }
    figure.act({ do: "show", ids: named, as: how }, { select: false, label });
  }
  function showCommands(picks, name) {
    const ways = picks.map((index) => shownAs(list()[index], index));
    return [
      // Those that draw a diagram made the figure's own parts (figure_convert.py).
      ...(convertible(picks.map((index) => list()[index])) ? [convertCommand(() => toParts(picks), name)] : []),
      ...(ways.every((way) => way === "hidden") ? [] : [{ icon: "eye", label: "Hide", hint: `${name}: not drawn, its place kept`, run: () => showAs(picks, "hidden") }]),
      ...(ways.every((way) => way === "dimmed") ? [] : [{ icon: "eye", label: "Dim", hint: `${name}: drawn faint`, run: () => showAs(picks, "dimmed") }]),
      ...(ways.every((way) => way === "shown") ? [] : [{ icon: "eye", label: "Show", hint: `${name}: drawn plainly again`, run: () => showAs(picks, "shown") }]),
    ];
  }

  // -- Convert to Figure Parts --
  // The shapes chosen made the figure's parts, in one step: sent with where each is drawn and
  // each part's box, as drawn here (the figure is not drawn again to find them); what was
  // made chosen, and said.
  async function toParts(picks) {
    if (!figure.model) return;
    await figure.idle?.();
    const shapes = list(), placed = picks.map((index) => shapes[index]);
    const drawnHere = !waiting && placed.every(Boolean);
    editor.clear({ quiet: true });
    figure.act({ do: "convert", shapes: picks, ...(drawnHere ? { placed: copyOf(placed), boxes: copyOf(boxes()) } : {}) }, {
      label: CONVERT,
      then: (result) => { if (result?.said) toast(`${result.said}.`, { icon: "figure", seconds: 4 }); },
    });
  }

  // -- what it moves with: the inspector's own section --
  function attachPanel(picks, specs, { slider, set }) {
    const shapes = list(), chosen = picks.map((index) => shapes[index]).filter(Boolean);
    if (!chosen.length) return [];
    const options = [{ value: "", label: "Nothing — stays where it is" }, ...[...parts()].map(([id, part]) => ({ value: id, label: part.label }))];
    const ons = new Set(chosen.map((spec) => (spec.around?.length ? `around:${spec.around.join(",")}` : spec.on ?? "")));
    const one = ons.size === 1 ? [...ons][0] : null;
    const round = one?.startsWith("around:") ? one.slice(7).split(",") : null;
    const out = [];
    // On a part: its places from that part's; nothing, where it is on the figure.
    const moveWith = (id) => edit((all) => {
      for (const index of picks) {
        const spec = all[index];
        if (!spec) continue;
        delete spec.around; delete spec.margin; delete spec.side;
        if (id) spec.on = id; else delete spec.on;
      }
      return all;
    }, { label: id ? `Attach to ${nameOf(id)}` : "Detach" });
    if (round) {
      out.push(ui.field("Drawn Round", h("div.shape-round", {}, round.map((id) => h("span.chip", {}, nameOf(id))),
        ui.button("Detach", () => moveWith(round[0]), { kind: "ghost", small: true, title: "Keep it where it is, moving with the first of them" }))));
      const margin = chosen.every((spec) => same(spec.around, chosen[0].around)) ? marginOf(chosen[0]) : null;
      out.push(ui.field("Margin", ui.number({ value: margin, placeholder: "Mixed", min: -100, max: 200, step: 1, unit: "pt", key: "shape.margin",
        onChange: (value) => edit((all) => {
          for (const index of picks) {
            const spec = all[index];
            if (!spec?.around?.length) continue;
            if (value === null || value === margins[spec.kind] || (margins[spec.kind] === undefined && value === (catalog.margin ?? 6))) delete spec.margin; else spec.margin = value;
            const found = spec.around.map((id) => boxes()[id]).filter(Boolean);
            if (found.length) all[index] = placedRound(spec, aroundBox(found, marginOf(spec), spec.kind));
          }
          return all;
        }, { label: "Change Margin" }) })));
      if (chosen.every((spec) => F.family(spec.kind) === "line")) {
        out.push(ui.field("Side", ui.segmented({ value: chosen.every((spec) => sideOf(spec) === sideOf(chosen[0])) ? sideOf(chosen[0]) : null, key: "shape.side",
          options: [{ value: "top", label: "Top" }, { value: "right", label: "Right" }, { value: "bottom", label: "Bottom" }, { value: "left", label: "Left" }],
          onChange: (value) => edit((all) => {
            for (const index of picks) {
              const spec = all[index];
              if (!spec?.around?.length) continue;
              spec.side = value;
              const found = spec.around.map((id) => boxes()[id]).filter(Boolean);
              if (found.length) all[index] = placedRound(spec, aroundBox(found, marginOf(spec), spec.kind));
            }
            return all;
          }, { label: "Change Side" }) })));
      }
    } else {
      out.push(ui.field("Moves With", ui.select({ value: one ?? "", options, key: "shape.on", onChange: (value) => moveWith(value || null) }),
        { hint: "The part it stays on as the figure is laid out again" }));
      // Drawn round a part instead: sized to it, and sized again as it is.
      if (chosen.every((spec) => ROUNDABLE.has(spec.kind))) {
        const target = one || null;
        out.push(ui.button(target ? `Draw Round ${nameOf(target)}` : "Draw Round a Part…", (event) => {
          if (target) { roundOn(picks, [target]); return; }
          menu(event.currentTarget, [...parts()].map(([id, part]) => ({ label: part.label, run: () => roundOn(picks, [id]) })));
        }, { small: true, kind: "ghost", icon: "shape", title: "Sized to it, and sized again as the figure is laid out" }));
      }
    }
    // In front of the figure's parts or behind them, a backdrop they stand on.
    const behind = chosen.every((spec) => spec.behind), front = chosen.every((spec) => !spec.behind);
    out.push(ui.field("Drawn", ui.segmented({ value: behind ? "behind" : front ? "front" : null, key: "shape.layer",
      options: [{ value: "front", label: "In Front" }, { value: "behind", label: "Behind" }],
      onChange: (value) => set({ behind: value === "behind" }, value === "behind" ? "Send Behind the Figure" : "Bring Above the Figure") }),
    { hint: "Behind, it is a backdrop the parts stand on: over the box of the group that holds them" }));
    const ways = picks.map((index) => shownAs(shapes[index], index));
    out.push(ui.field("Shown", ui.segmented({ value: ways.every((way) => way === ways[0]) ? ways[0] : null, key: "shape.shown",
      options: [{ value: "shown", label: "Plainly" }, { value: "dimmed", label: "Faint" }, { value: "hidden", label: "Hidden" }],
      onChange: (value) => showAs(picks, value) }), { hint: "As the figure's hide and dim say: the layout is the same" }));
    void slider; void specs;
    return [h("div.section", {}, h("div.section-title", {}, "On the Figure"), out)];
  }
  function roundOn(picks, ids) {
    edit((all) => {
      for (const index of picks) {
        const spec = all[index];
        if (!spec) continue;
        delete spec.on;
        const found = ids.map((id) => boxes()[id]).filter(Boolean);
        all[index] = placedRound({ ...spec, around: [...ids] }, aroundBox(found, marginOf(spec), spec.kind));
      }
      return all;
    }, { label: `Draw Round ${nameOf(ids[0])}` });
  }

  // -- the drawing --
  // The figure drawn again: what it says of its shapes now, and those changed here meanwhile
  // given up once it was drawn with them (or changed by another, or by an undo).
  // (What it says is taken as it comes, before the figure's parts are: its list and its
  // panel are drawn with them; the shapes are placed once its drawing is in.)
  function took(next, model) {
    info = next || {};
    const shapes = Array.isArray(model?.shapes) ? model.shapes : [];
    if (waiting && alike(shapes, waiting.written)) waiting = null;
  }
  function drawnWith() {
    editor.drawn();
    if (editor.any()) changed();
  }
  // Another's change, or an undo: what is drawn is what is.
  function afresh() { waiting = null; }

  // A click let go after a press the shapes took: not the figure's.
  const swallow = () => Date.now() - swallowed < 400;

  // Those drawn over the figure, listed beside its shapes (the editor's list): each by its kind
  // and its words.
  function rows() {
    const shapes = list();
    return shapes.map((spec, index) => (spec ? h(`div.tree-row.drawn${editor.chosen().includes(index) ? ".on" : ""}`, {
      dataset: { shape: index },
      onclick: (event) => editor.choose(event.shiftKey || event.metaKey ? [...new Set([...editor.chosen(), index])] : [index]),
    }, h("span.tree-caret"), h("span.tree-glyph.shape-glyph", {}, shapeIcon(spec.kind === "group" ? "rectangle" : spec.kind)),
    h("span.tree-name", {}, shapeLabel(spec)), spec.text ? h("span.tree-id", {}, String(spec.text).split("\n")[0].slice(0, 32)) : null) : null)).filter(Boolean);
  }
  // What a message about a shape names it as, and the shape it is about.
  function named(where) {
    const shapes = list();
    const index = shapes.findIndex((spec, n) => spec && (String(spec.id ?? `shapes.${n}`) === where));
    const by = /^shapes\.(\d+)$/.exec(String(where || ""));
    const at = index >= 0 ? index : by ? Number(by[1]) : -1;
    return at >= 0 ? { index: at, name: shapes[at] ? shapeLabel(shapes[at]) : `Shape ${at + 1}` } : null;
  }

  return { ...editor, took, drawnWith, afresh, swallow, rows, named, written, addInset, insettable };
}
