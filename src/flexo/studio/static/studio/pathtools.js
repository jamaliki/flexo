// The tools that draw and change a path (flexo.freeform's `path`), for the shapes' editor
// (shapes.js), on a slide and over a figure alike.
//
// The pen draws one point by point: a click puts a corner, a drag a smooth point whose handles
// it pulls out either side (⇧: along one of eight ways), a click on its first point closes it,
// Return or a double-click ends it open, ⌫ takes back its last point, Esc its last segment and
// again the whole of it; each point catches at the guides the editor's others do (⌘: none;
// with snapping off, none, ⌘ catching: snapping.js).
//
// A path's points are edited in place (a double-click on it, or Edit Points): a point or a
// handle dragged (⌥: a smooth point's handle on its own, a corner then), a point
// double-clicked made smooth or a corner, a click on its outline adds one there, ⌫ deletes
// those chosen, a band across them chooses them, the arrows nudge them (⇧: ten points); Return
// or Esc is done. Each is one step to undo. A turned or mirrored path is edited where it is
// shown, and stays there: what was not moved does not move.
//
// `ctx` is the editor's: its layers (`previews`, `guides`, `handles`), `S` (an SVG element),
// toFrame(event), unit() (screen pixels to a point), specAt(index), geometryOf(index, spec),
// edit(mutate, label, options), add(spec), preview(index, spec), putBack(), place(),
// say(words, event), snapTargets(indices), caught(point, targets) (caught at a guide, drawn),
// toast(words), disarm(), remove(index), noun.

import * as F from "./freeform.js";
import * as P from "./pathdata.js";
import * as O from "./pathops.js";
import * as Snap from "./snapping.js";

const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const SNAP = 7; // pixels: how near the first point closes, a point or handle is caught

// A point along one of eight ways from `from`, as far as `point` is.
function eightWays(point, from) {
  const angle = Math.round(Math.atan2(point[1] - from[1], point[0] - from[0]) / (Math.PI / 4)) * (Math.PI / 4), length = distance(point, from);
  return [from[0] + Math.cos(angle) * length, from[1] + Math.sin(angle) * length];
}
const square = ([x, y], size) => `M${x - size} ${y - size}h${2 * size}v${2 * size}h${-2 * size}z`;
const dot = ([x, y], size) => `M${x - size} ${y}a${size} ${size} 0 1 0 ${2 * size} 0a${size} ${size} 0 1 0 ${-2 * size} 0`;

export function pathTools(ctx) {
  return { pen: penTool(ctx), points: pointEditor(ctx) };
}

// -- the pen --

function penTool(ctx) {
  let state = null;
  const reach = () => SNAP / ctx.unit();
  const active = () => Boolean(state);

  function arm() {
    stop();
    state = { anchors: [], press: null, hover: null, escaped: false, targets: ctx.snapTargets([]) };
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("dblclick", onDouble, true);
    ctx.toast("Pen: click for a corner, drag for a curve · click the first point to close it · Return ends it · ⌫ takes back a point · Esc a segment, then the path", { seconds: 4 });
  }
  function stop() {
    if (!state) return;
    window.removeEventListener("keydown", onKey, true);
    window.removeEventListener("dblclick", onDouble, true);
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    state = null;
    ctx.previews.replaceChildren();
    ctx.guides.replaceChildren();
    ctx.hideTip?.();
  }
  // Where a point goes: along one of eight ways from `from` (⇧), else caught at a guide (⌘: free;
  // snapping off, free but for ⌘).
  function placed(point, event, from) {
    if (event.shiftKey && from) return eightWays(point, from);
    if (Snap.free(event)) return point;
    return ctx.caught(point, state.targets);
  }
  function press(event) {
    if (!state || event.button !== 0) return false;
    ctx.guides.replaceChildren();
    const at = ctx.toFrame(event), anchors = state.anchors, last = anchors[anchors.length - 1];
    state.escaped = false;
    if (anchors.length >= 2 && distance(at, anchors[0].at) <= reach()) state.press = { closing: true, was: { ...anchors[0] }, start: [event.clientX, event.clientY] };
    else {
      anchors.push({ at: placed(at, event, last?.at), in: null, out: null });
      state.press = { index: anchors.length - 1, start: [event.clientX, event.clientY] };
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    draw(event);
    event.preventDefault();
    return true;
  }
  function onMove(event) {
    const pressed = state?.press;
    if (!pressed) return;
    if (!pressed.dragging && Math.hypot(event.clientX - pressed.start[0], event.clientY - pressed.start[1]) < 3) return;
    pressed.dragging = true;
    ctx.guides.replaceChildren();
    const anchor = pressed.closing ? state.anchors[0] : state.anchors[pressed.index];
    // A drag pulls out its handles, either side alike: a smooth point.
    const handle = placed(ctx.toFrame(event), event, anchor.at);
    if (distance(handle, anchor.at) < 0.5) { anchor.in = anchor.out = null; } else {
      anchor.out = handle;
      anchor.in = [2 * anchor.at[0] - handle[0], 2 * anchor.at[1] - handle[1]];
    }
    draw(event);
  }
  function onUp() {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    const pressed = state?.press;
    if (!pressed) return;
    state.press = null;
    if (pressed.closing) finish(true);
    else draw();
  }
  function hover(event) {
    if (!state) return false;
    ctx.guides.replaceChildren();
    const last = state.anchors[state.anchors.length - 1], raw = ctx.toFrame(event);
    const closing = state.anchors.length >= 2 && distance(raw, state.anchors[0].at) <= reach();
    state.hover = { at: closing ? state.anchors[0].at : placed(raw, event, last?.at), closing };
    draw(event);
    return true;
  }
  // Ended: a path of what was drawn -- open, unfilled; closed, filled as a shape is.
  function finish(closed) {
    // (A double-click's two clicks put its last point twice: once is kept.)
    const anchors = state.anchors.filter((anchor, n, all) => n === 0 || distance(anchor.at, all[n - 1].at) > 1.5 / ctx.unit());
    stop();
    ctx.disarm();
    if (anchors.length < 2) return;
    ctx.add({ kind: "path", d: O.dataOf([{ anchors, closed }]), ...(closed ? {} : { fill: "none" }) });
  }
  function onKey(event) {
    if (!state) return;
    const key = event.key;
    if (key === "Enter" || key === "Return") finish(false);
    else if (key === "Escape") {
      const pressed = state.press;
      if (pressed) {
        // A point being placed: taken back.
        state.press = null;
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        if (pressed.closing) Object.assign(state.anchors[0], pressed.was); else state.anchors.pop();
        state.escaped = true;
      } else if (!state.escaped && state.anchors.length > 1) { state.anchors.pop(); state.escaped = true; }
      else { stop(); ctx.disarm(); ctx.swallowRelease?.(true); }
      if (state) draw();
    } else if (key === "Backspace" || key === "Delete") {
      state.anchors.pop();
      state.escaped = false;
      draw();
    } else return;
    event.preventDefault();
    event.stopPropagation();
  }
  function onDouble(event) {
    if (!state) return;
    event.preventDefault();
    event.stopPropagation();
    finish(false);
  }
  // What is drawn so far, the segment to the pointer, its points and the last one's handles.
  function draw(event = null) {
    if (!state) return;
    const { S } = ctx, px = 1 / ctx.unit(), anchors = state.anchors;
    ctx.previews.replaceChildren();
    if (!anchors.length) return;
    const look = { kind: "path", fill: "none", line: "accent", line_width: 1.5 };
    if (anchors.length > 1) {
      const node = S("g");
      node.innerHTML = F.svg({ ...look, d: O.dataOf([{ anchors, closed: false }]) }, null, ctx.roles());
      ctx.previews.append(node);
    }
    const last = anchors[anchors.length - 1], hover = state.press ? null : state.hover;
    if (hover && distance(hover.at, last.at) > 0.5) {
      const reachTo = hover.closing ? anchors[0] : { at: hover.at, in: null, out: null };
      ctx.previews.append(S("path", { d: P.written(O.segmentsFrom([{ anchors: [last, reachTo], closed: false }])), class: "path-ink", "stroke-width": px, "stroke-dasharray": `${4 * px} ${3 * px}` }));
    }
    const arms = [];
    for (const anchor of [last, ...(state.press?.closing ? [anchors[0]] : [])]) {
      for (const handle of [anchor.in, anchor.out]) if (handle) arms.push(`M${anchor.at[0]} ${anchor.at[1]}L${handle[0]} ${handle[1]}`);
    }
    if (arms.length) ctx.previews.append(S("path", { d: arms.join(""), class: "path-arm", "stroke-width": px }));
    const handles = [last.in, last.out].filter(Boolean).map((point) => dot(point, 3 * px)).join("");
    if (handles) ctx.previews.append(S("path", { d: handles, class: "path-handle", "stroke-width": px }));
    ctx.previews.append(S("path", { d: anchors.map((anchor) => square(anchor.at, 3 * px)).join(""), class: "path-anchor", "stroke-width": 1.2 * px }));
    if (hover?.closing || state.press?.closing) ctx.previews.append(S("path", { d: dot(anchors[0].at, 5 * px), class: "path-close", "stroke-width": px }));
    if (event) {
      const tip = state.press?.dragging ? "Curve" : hover?.closing ? "Close" : `${anchors.length} point${anchors.length === 1 ? "" : "s"}`;
      ctx.say(tip, event);
    }
  }
  return { arm, stop, active, press, hover, drawing: () => Boolean(state?.press) };
}

// -- a path's points, edited --

function pointEditor(ctx) {
  let state = null;
  const reach = () => SNAP / ctx.unit();
  const active = () => Boolean(state);
  const keyOf = (piece, n) => `${piece}:${n}`;

  // The path as it is now: its spec, its pieces (its own, to change freely) and its frame.
  function current() {
    if (!state) return null;
    const spec = ctx.specAt(state.index);
    if (!spec || spec.kind !== "path") return null;
    const made = ctx.geometryOf(state.index, spec), read = P.parsedOf(spec);
    const pieces = O.piecesOf(read.segments);
    return { spec, made, pieces, frame: O.frameOf(spec, made) };
  }
  function start(index) {
    leave({ quiet: true });
    state = { index, chosen: new Set(), gesture: null, nudged: null };
    if (!current()) { state = null; return false; }
    window.addEventListener("keydown", onKey, true);
    ctx.toast("Edit Points: drag a point or a handle (⌥: one handle alone) · double-click a point: smooth or a corner · click the outline to add a point · ⌫ deletes · Return or Esc when done", { seconds: 4 });
    ctx.place();
    return true;
  }
  function leave({ quiet = false } = {}) {
    if (!state) return;
    window.removeEventListener("keydown", onKey, true);
    cancelGesture();
    state = null;
    if (!quiet) { ctx.putBack(); ctx.place(); ctx.renderInspector?.(); }
  }

  // Where each anchor and the handles shown (the chosen points', and their neighbours' towards
  // them) are on the page.
  function shown(now) {
    const anchors = [], handles = [];
    now.pieces.forEach((piece, p) => piece.anchors.forEach((anchor, n) => {
      anchors.push({ key: keyOf(p, n), p, n, at: O.toPage(now.frame, anchor.at) });
    }));
    for (const key of state.chosen) {
      const [p, n] = key.split(":").map(Number), piece = now.pieces[p];
      if (!piece || !piece.anchors[n]) continue;
      const count = piece.anchors.length;
      const add = (q, side) => { const one = piece.anchors[q]; if (one?.[side]) handles.push({ p, n: q, side, at: O.toPage(now.frame, one[side]), from: O.toPage(now.frame, one.at) }); };
      add(n, "in"); add(n, "out");
      if (n > 0 || piece.closed) add((n - 1 + count) % count, "out");
      if (n < count - 1 || piece.closed) add((n + 1) % count, "in");
    }
    const seen = new Set();
    return { anchors, handles: handles.filter((one) => { const key = `${one.p}:${one.n}:${one.side}`; if (seen.has(key)) return false; seen.add(key); return true; }) };
  }
  function place() {
    if (!state) return;
    const now = current();
    if (!now) { leave(); return; }
    const { S } = ctx, px = 1 / ctx.unit(), { anchors, handles } = shown(now);
    ctx.marks.append(S("path", { d: P.written(O.segmentsFrom(now.pieces).map(([kind, ...values]) => {
      const out = [kind];
      for (let n = 0; n < values.length; n += 2) out.push(...O.toPage(now.frame, [values[n], values[n + 1]]));
      return out;
    })), class: "path-ink", "stroke-width": px }));
    if (handles.length) {
      ctx.handles.append(S("path", { d: handles.map((one) => `M${one.from[0]} ${one.from[1]}L${one.at[0]} ${one.at[1]}`).join(""), class: "path-arm", "stroke-width": px }));
      ctx.handles.append(S("path", { d: handles.map((one) => dot(one.at, 3.2 * px)).join(""), class: "path-handle", "stroke-width": px }));
    }
    const plain = anchors.filter((one) => !state.chosen.has(one.key)), chosen = anchors.filter((one) => state.chosen.has(one.key));
    if (plain.length) ctx.handles.append(S("path", { d: plain.map((one) => square(one.at, 3.2 * px)).join(""), class: "path-anchor", "stroke-width": 1.2 * px }));
    if (chosen.length) ctx.handles.append(S("path", { d: chosen.map((one) => square(one.at, 3.6 * px)).join(""), class: "path-anchor chosen", "stroke-width": 1.2 * px }));
    if (state.gesture?.band) {
      const [a, b] = state.gesture.band;
      ctx.handles.append(S("rect", { x: Math.min(a[0], b[0]), y: Math.min(a[1], b[1]), width: Math.abs(b[0] - a[0]), height: Math.abs(b[1] - a[1]), class: "path-band", "stroke-width": px }));
    }
  }

  // The path with its pieces changed: written, steadied where it is shown.
  function rewritten(now, pieces) {
    const segments = O.steadied(now.frame, O.segmentsFrom(pieces));
    return P.withOutline(now.spec, P.readOf(segments));
  }
  function commit(made, label, merge = null) {
    const index = state.index, words = made.d;
    ctx.edit((list) => { if (list[index]) list[index] = { ...list[index], d: words }; }, label, merge ? { merge } : {});
  }

  // -- the pointer --

  function press(event) {
    if (!state) return false;
    if (event.button !== 0) return true;
    const now = current();
    if (!now) { leave(); return false; }
    const point = ctx.toFrame(event), { anchors, handles } = shown(now), near = reach();
    const handle = handles.map((one) => ({ one, far: distance(one.at, point) })).filter((x) => x.far <= near).sort((a, b) => a.far - b.far)[0];
    const anchor = anchors.map((one) => ({ one, far: distance(one.at, point) })).filter((x) => x.far <= near).sort((a, b) => a.far - b.far)[0];
    if (handle && (!anchor || handle.far < anchor.far)) begin(event, { type: "handle", ...handle.one, now, targets: ctx.snapTargets([state.index]) });
    else if (anchor) {
      const key = anchor.one.key;
      if (event.shiftKey) { if (state.chosen.has(key)) state.chosen.delete(key); else state.chosen.add(key); }
      else if (!state.chosen.has(key)) state.chosen = new Set([key]);
      begin(event, { type: "points", key, now, targets: ctx.snapTargets([state.index]) });
    } else {
      const local = O.toLocal(now.frame, point), on = O.nearestOn(now.pieces, local);
      if (on && on.distance <= near) begin(event, { type: "segment", on, now });
      else {
        // A band, to choose the points it goes round -- or, a click away from the path, done.
        const [left, top, right, bottom] = F.bounds(now.spec, now.made), slack = 12 / ctx.unit();
        const away = point[0] < left - slack || point[0] > right + slack || point[1] < top - slack || point[1] > bottom + slack;
        begin(event, { type: "band", from: point, away, now, keep: event.shiftKey ? new Set(state.chosen) : new Set() });
      }
    }
    event.preventDefault();
    ctx.place();
    return true;
  }
  function begin(event, gesture) {
    state.gesture = { ...gesture, start: [event.clientX, event.clientY], from: gesture.from || ctx.toFrame(event), moved: false };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }
  function cancelGesture() {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    if (state?.gesture) { state.gesture = null; ctx.putBack(); ctx.guides.replaceChildren(); ctx.hideTip?.(); }
  }
  function onMove(event) {
    const g = state?.gesture;
    if (!g) return;
    if (!g.moved && Math.hypot(event.clientX - g.start[0], event.clientY - g.start[1]) < 3) return;
    g.moved = true;
    ctx.guides.replaceChildren();
    const point = ctx.toFrame(event);
    if (g.type === "band") { g.band = [g.from, point]; band(g); ctx.place(); return; }
    if (g.type === "segment") return;
    const now = g.now, pieces = now.pieces.map((piece) => ({ anchors: piece.anchors.map((a) => ({ at: [...a.at], in: a.in && [...a.in], out: a.out && [...a.out] })), closed: piece.closed }));
    if (g.type === "points") {
      // The points chosen moved together: the one pressed caught at the guides (⇧: one way).
      let to = point;
      const [p, n] = g.key.split(":").map(Number), pressed = O.toPage(now.frame, now.pieces[p].anchors[n].at);
      if (event.shiftKey) { const dx = to[0] - g.from[0], dy = to[1] - g.from[1]; to = Math.abs(dx) > Math.abs(dy) ? [to[0], g.from[1]] : [g.from[0], to[1]]; }
      let target = [pressed[0] + to[0] - g.from[0], pressed[1] + to[1] - g.from[1]];
      if (!Snap.free(event) && !event.shiftKey) target = ctx.caught(target, g.targets);
      const a = O.toLocal(now.frame, pressed), b = O.toLocal(now.frame, target), dx = b[0] - a[0], dy = b[1] - a[1];
      for (const key of state.chosen) {
        const [q, m] = key.split(":").map(Number), one = pieces[q]?.anchors[m];
        if (!one) continue;
        one.at = [one.at[0] + dx, one.at[1] + dy];
        if (one.in) one.in = [one.in[0] + dx, one.in[1] + dy];
        if (one.out) one.out = [one.out[0] + dx, one.out[1] + dy];
      }
      g.made = rewritten(now, pieces);
      g.label = state.chosen.size === 1 ? "Move Point" : "Move Points";
      ctx.say(`${Math.round(target[0])}, ${Math.round(target[1])}`, event);
    } else if (g.type === "handle") {
      // A handle: caught at the guides; a smooth point's other handle turning with it, as long
      // as it was (⌥: left where it is, the point a corner).
      const target = Snap.free(event) ? point : ctx.caught(point, g.targets);
      const one = pieces[g.p].anchors[g.n], other = g.side === "in" ? "out" : "in", wasSmooth = O.smooth(now.pieces[g.p].anchors[g.n]);
      one[g.side] = O.toLocal(now.frame, target);
      if (wasSmooth && !event.altKey && one[other]) {
        const length = distance(one[other], one.at), dx = one.at[0] - one[g.side][0], dy = one.at[1] - one[g.side][1], size = Math.hypot(dx, dy) || 1;
        one[other] = [one.at[0] + dx / size * length, one.at[1] + dy / size * length];
      }
      g.made = rewritten(now, pieces);
      g.label = "Move Handle";
    }
    ctx.putBack();
    ctx.preview(state.index, g.made);
  }
  function band(g) {
    const now = g.now || current(), [a, b] = g.band, chosen = new Set(g.keep);
    const [left, right, top, bottom] = [Math.min(a[0], b[0]), Math.max(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[1], b[1])];
    for (const one of shown(now).anchors) if (one.at[0] >= left && one.at[0] <= right && one.at[1] >= top && one.at[1] <= bottom) chosen.add(one.key);
    state.chosen = chosen;
  }
  function onUp() {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    const g = state?.gesture;
    if (!g) return;
    state.gesture = null;
    ctx.guides.replaceChildren();
    ctx.hideTip?.();
    ctx.swallowRelease?.();
    if (g.type === "segment" && !g.moved) {
      // A click on its outline: a point there, its curve kept.
      const { on, now } = g, pieces = now.pieces.map((piece, p) => (p === on.piece ? O.splitAt(piece, on.n, on.t) : piece));
      state.chosen = new Set([keyOf(on.piece, on.n + 1)]);
      commit(rewritten(now, pieces), "Add Point");
      return;
    }
    if (g.made && g.moved) { commit(g.made, g.label); return; }
    if (g.type === "band" && !g.moved) {
      if (g.away) { leave(); return; }
      state.chosen = new Set(g.keep);
    }
    ctx.putBack();
    ctx.place();
  }
  function dblclick(event) {
    if (!state) return false;
    const now = current();
    if (!now) return false;
    const point = ctx.toFrame(event), hit = shown(now).anchors.map((one) => ({ one, far: distance(one.at, point) })).filter((x) => x.far <= reach()).sort((a, b) => a.far - b.far)[0];
    if (!hit) return true;
    const { p, n } = hit.one, piece = now.pieces[p], was = piece.anchors[n].in || piece.anchors[n].out;
    const pieces = now.pieces.map((one, q) => (q === p ? { anchors: one.anchors.map((a, m) => (m === n ? O.toggled(one, n) : a)), closed: one.closed } : one));
    state.chosen = new Set([hit.one.key]);
    commit(rewritten(now, pieces), was ? "Make Point Corner" : "Make Point Smooth");
    return true;
  }

  // -- the keys --

  function onKey(event) {
    if (!state || event.target.closest?.("input, textarea, [contenteditable]")) return;
    const key = event.key, mod = event.metaKey || event.ctrlKey;
    if (key === "Escape" && state.gesture) { cancelGesture(); ctx.place(); }
    else if (key === "Enter" || key === "Return" || key === "Escape") leave();
    else if ((key === "Backspace" || key === "Delete") && !mod) remove();
    else if (key.startsWith("Arrow") && !mod) {
      const by = event.shiftKey ? 10 : 1, [dx, dy] = { ArrowLeft: [-by, 0], ArrowRight: [by, 0], ArrowUp: [0, -by], ArrowDown: [0, by] }[key];
      nudge(dx, dy);
    } else if (mod && key.toLowerCase() === "a") {
      const now = current();
      state.chosen = new Set(shown(now).anchors.map((one) => one.key));
      ctx.place();
    } else return;
    event.preventDefault();
    event.stopPropagation();
  }
  function remove() {
    const now = current();
    if (!now || !state.chosen.size) return;
    const count = state.chosen.size, pieces = O.without(now.pieces, state.chosen);
    state.chosen = new Set();
    if (!pieces.length) {
      // None left: the path goes.
      const index = state.index;
      leave({ quiet: true });
      ctx.remove(index);
      return;
    }
    commit(rewritten(now, pieces), count === 1 ? "Delete Point" : "Delete Points");
  }
  function nudge(dx, dy) {
    const now = current();
    if (!now || !state.chosen.size) return;
    const a = O.toLocal(now.frame, [0, 0]), b = O.toLocal(now.frame, [dx, dy]), lx = b[0] - a[0], ly = b[1] - a[1];
    const pieces = now.pieces.map((piece, p) => ({ closed: piece.closed, anchors: piece.anchors.map((one, n) => {
      if (!state.chosen.has(keyOf(p, n))) return one;
      const by = (point) => point && [point[0] + lx, point[1] + ly];
      return { at: by(one.at), in: by(one.in), out: by(one.out) };
    }) }));
    // (Pressed again and again, one step to undo.)
    const run = state.nudged && Date.now() - state.nudged.at < 1500 ? state.nudged : { id: Date.now() };
    run.at = Date.now();
    state.nudged = run;
    commit(rewritten(now, pieces), state.chosen.size === 1 ? "Move Point" : "Move Points", `path-nudge-${run.id}`);
  }

  return { start, leave, active, place, press, dblclick, busy: () => Boolean(state?.gesture?.moved), index: () => state?.index ?? null };
}
