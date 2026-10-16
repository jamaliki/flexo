// Structures that share a frame (flexo.structure_frames): drawn with one camera, at one scale,
// about one centre, as the first of them -- its owner -- is turned and framed. What the figure's
// editor (parts.js) needs of them:
//
// - An edit of a framed structure's turn, zoom or offset (its handle dragged, its Camera tab's
//   fields and buttons) made to every structure of its frame alike, one step (framedAction): the
//   file says the same of each, so whichever comes first says it.
// - Each one's Camera tab showing the frame's (readFrom: its owner's settings).
// - All of them turning together while one is dragged round by its handle, each drawn as the
//   frame turns it (framedProjectors), as mol-sketch will draw it.
// - The Camera tab's Frame: None, a frame of the figure's (with how many structures it has), or
//   New Frame (frameSelect). One leaving a frame keeps the turn it is seen at; one coming first
//   in a frame turns the frame about its own axes, so that it is seen as it was.

const NAMES = ["yaw", "pitch", "roll", "zoom", "pan_x", "pan_y"];
export const FRAME_KEYS = NAMES.map((name) => `properties.${name}`);

// The frame a structure names, or null.
export function frameOf(node) {
  if (node?.kind !== "structure") return null;
  const name = node.properties?.frame;
  return typeof name === "string" || typeof name === "number" ? String(name).trim() || null : null;
}

// Each frame of the figure's, with the structures naming it, in the order of its nodes.
export function framesOf(nodes) {
  const found = new Map();
  for (const node of nodes || []) {
    const name = frameOf(node);
    if (name) found.set(name, [...(found.get(name) || []), node]);
  }
  return found;
}

// The structures in the frame of `id`, its owner first -- or null, in none or alone in it.
export function membersOf(nodes, id) {
  const node = (nodes || []).find((each) => each.id === id), name = frameOf(node);
  const members = name ? framesOf(nodes).get(name) : null;
  return members && members.length > 1 ? members : null;
}

// What a structure's settings are read from: the first of its frame's, for the frame's own.
export function readFrom(nodes, item, key) {
  if (item?.kind !== "structure" || !FRAME_KEYS.includes(key)) return item;
  return membersOf(nodes, item.id)?.[0] || item;
}

// An edit of the turn, zoom or offset of one structure of a frame, made to all of them: one
// step. Anything else is as it was.
export function framedAction(nodes, action) {
  if (action?.do !== "update" || action.targets || action.target?.type !== "node") return action;
  const keys = Object.keys(action.values || {});
  if (!keys.length || !keys.every((key) => FRAME_KEYS.includes(key))) return action;
  const members = membersOf(nodes, action.target.id);
  if (!members) return action;
  const others = members.filter((node) => node.id !== action.target.id);
  return { ...action, targets: [action.target, ...others.map((node) => ({ type: "node", id: node.id }))] };
}

// What the views asked for (each a frame's view, structure_frames.framed_view) depend on: the
// settings of every structure in the frame.
export function viewKey(nodes, id) {
  return JSON.stringify((membersOf(nodes, id) || []).map((node) => node.properties));
}

// -- turns --

// mol-sketch's turn (its rot3): about y by yaw, then x by pitch, then z by roll; y up.
export function turnMatrix(yaw, pitch, roll) {
  const [cy, sy, cp, sp, cr, sr] = [yaw, yaw, pitch, pitch, roll, roll].map((value, index) => (index % 2 ? Math.sin : Math.cos)(value * Math.PI / 180));
  const aboutY = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]];
  const aboutX = [[1, 0, 0], [0, cp, -sp], [0, sp, cp]];
  const aboutZ = [[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]];
  return times(aboutZ, times(aboutX, aboutY));
}
const times = (a, b) => a.map((row) => [0, 1, 2].map((c) => row[0] * b[0][c] + row[1] * b[1][c] + row[2] * b[2][c]));
const across = (m) => [0, 1, 2].map((r) => [0, 1, 2].map((c) => m[c][r]));
const apply = (m, [x, y, z]) => m.map((row) => row[0] * x + row[1] * y + row[2] * z);
// The yaw, pitch and roll of a turn (turnMatrix's inverse), in tenths of a degree.
export function anglesOf(m) {
  const tenth = (value) => Math.round(value * 10) / 10 || 0;
  const degrees = (value) => value * 180 / Math.PI;
  const pitch = degrees(Math.asin(Math.max(-1, Math.min(1, m[2][1]))));
  if (Math.abs(m[2][1]) < 1 - 1e-9) {
    return { yaw: tenth(degrees(Math.atan2(-m[2][0], m[2][2]))), pitch: tenth(pitch), roll: tenth(degrees(Math.atan2(-m[0][1], m[1][1]))) };
  }
  return { yaw: 0, pitch: tenth(pitch), roll: tenth(degrees(Math.atan2(m[1][0], m[0][0]))) };
}

// Where the frame draws each of its members' points while it is turned to `angles`: `views`,
// the members' framed views in the frame's order, its first first (their points in the frame's
// coordinates, the frame's camera), and
// `canvases`, what each is drawn on ({ width, height }, over its molecule's box). As the frame
// works it out (structure_frames.framing): about the middle of what they all draw, turned, at
// the scale at which each fits its own box -- the largest's -- times the frame's zoom, moved by
// its offset (shares of its first's box), from the frame's eye. One that is a frame alone is
// drawn as moleculeProjector draws it.
export function framedProjectors(views, canvases, { yaw, pitch, roll }) {
  const turn = turnMatrix(yaw, pitch, roll);
  const camera = views[0].camera;
  const turned = views.map((view) => view.fit.map((point) => apply(turn, point)));
  const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity];
  const lowAlong = [Infinity, Infinity, Infinity], highAlong = [-Infinity, -Infinity, -Infinity];
  views.forEach((view, index) => {
    view.fit.forEach((point, at) => {
      const seen = turned[index][at];
      for (let k = 0; k < 3; k++) {
        low[k] = Math.min(low[k], seen[k]); high[k] = Math.max(high[k], seen[k]);
        lowAlong[k] = Math.min(lowAlong[k], point[k]); highAlong[k] = Math.max(highAlong[k], point[k]);
      }
    });
  });
  if (!Number.isFinite(low[0])) { low.fill(0); high.fill(0); lowAlong.fill(0); highAlong.fill(0); }
  const [cx, cy] = [(low[0] + high[0]) / 2, (low[1] + high[1]) / 2];
  const [spanX, spanY, spanZ] = [0, 1, 2].map((k) => Math.max(high[k] - low[k], 1));
  const depth = apply(turn, [0, 1, 2].map((k) => (lowAlong[k] + highAlong[k]) / 2))[2];
  const reach = Math.max(spanX, spanY) / 2 + 1.5, opening = camera.fov * Math.PI / 180;
  const eye = opening > 0.002 ? reach / Math.tan(opening / 2) : Infinity;
  const nearer = eye === Infinity ? 1 : eye / Math.max(eye - spanZ / 2, eye * 0.3);
  const drawn = views.map((view, index) => {
    const { width, height } = canvases[index], { long_side: long, foot = 0, head = 0 } = view.frame;
    const [W, H] = width >= height ? [long, Math.round(long * height / width)] : [Math.round(long * width / height), long];
    return { W, H, foot, head, shrink: Math.min(width / W, height / H) };
  });
  const fits = turned.map((points, index) => {
    const { W, H, foot, head, shrink } = drawn[index];
    let wide = 1, tall = 1;
    for (const [x, y] of points) { wide = Math.max(wide, 2 * Math.abs(x - cx)); tall = Math.max(tall, 2 * Math.abs(y - cy)); }
    return Math.min((W * 0.9) / (wide + 2.6), (H * (1 - foot - head) - 24) / (tall + 2.4)) / Math.pow(nearer, 0.7) * shrink;
  });
  const scale = Math.min(...fits) * (camera.zoom ?? 1);
  // (Moved by shares of its first's box, as the frame's first is alone.)
  const shift = [(camera.pan_x || 0) * drawn[0].W * drawn[0].shrink, (camera.pan_y || 0) * drawn[0].H * drawn[0].shrink];
  return views.map((view, index) => {
    const { width, height } = canvases[index], { foot, head } = drawn[index];
    const [ox, oy] = [width / 2 + shift[0], (height * (1 - foot + head)) / 2 + shift[1]];
    return {
      perAngstrom: scale,
      at(point) {
        const [x, y, z] = apply(turn, point);
        const d = eye === Infinity ? 1 : Math.min(4, Math.max(0.2, eye / (eye - (z - depth))));
        return [ox + (x - cx) * scale * d, oy - (y - cy) * scale * d, z, d];
      },
    };
  });
}

// -- the Frame field --

const counted = (count) => `${count} Structure${count === 1 ? "" : "s"}`;

// A name for a new frame: the structure's file's (or its PDB ID's), as the frames it is not.
export function frameName(node, taken) {
  const source = String(node?.properties?.source ?? "").trim();
  const stem = source.split(/[\\/]/).pop().replace(/\.[^.]+$/, "").trim().replace(/\s+/g, "-") || node?.id || "frame";
  const used = new Set(taken);
  if (!used.has(stem)) return stem;
  let n = 2;
  while (used.has(`${stem}-${n}`)) n += 1;
  return `${stem}-${n}`;
}

const turnValues = (angles) => Object.fromEntries(["yaw", "pitch", "roll"].map((name) => [`properties.${name}`, angles[name] || null]));

// What putting `node` in the frame `name` (null: none) writes, structure by structure, as
// targets of one edit: [{ type, id, values }]. `views(id)` is a structure's framed view.
export async function frameMoves(nodes, node, name, views) {
  const values = new Map();
  const put = (id, more) => values.set(id, { ...(values.get(id) || {}), ...more });
  put(node.id, { "properties.frame": name });
  const left = membersOf(nodes, node.id);
  if (left) {
    // Out of a frame of others: drawn alone, turned as it is seen now, fitted to its box.
    const own = await views(node.id);
    if (own?.alone) put(node.id, { ...turnValues(own.alone), "properties.zoom": null, "properties.pan_x": null, "properties.pan_y": null });
    // Its first gone, the next is: turned about its own axes as the frame is seen now.
    const rest = left.filter((one) => one.id !== node.id);
    if (left[0].id === node.id && rest.length) {
      const next = await views(rest[0].id);
      if (next?.alone) for (const one of rest) put(one.id, turnValues(next.alone));
    }
  }
  const joined = name ? (framesOf(nodes).get(name) || []).filter((one) => one.id !== node.id) : [];
  if (joined.length) {
    const owner = joined[0];
    const settings = Object.fromEntries(FRAME_KEYS.map((key) => [key, owner.properties?.[key.slice(11)] ?? null]));
    if (nodes.indexOf(node) > nodes.indexOf(owner)) put(node.id, settings);
    else {
      // It comes first, so the frame is turned about its axes: by the turn that shows the frame
      // as it is seen now.
      const [theirs, mine] = await Promise.all([views(owner.id), views(node.id)]);
      const camera = theirs?.camera;
      if (camera && theirs?.base && mine?.base) {
        const seen = times(times(turnMatrix(camera.yaw, camera.pitch, camera.roll), theirs.base), across(mine.base));
        const turn = turnValues(anglesOf(seen));
        put(node.id, { ...settings, ...turn });
        for (const one of joined) put(one.id, turn);
      } else put(node.id, settings);
    }
  }
  return [...values].map(([id, more]) => ({ type: "node", id, values: more }));
}

// The Frame field's pop-up: None, the figure's frames (each with how many structures it has),
// or New Frame. `apply(targets, label)` makes the edit.
export function frameSelect({ ui, nodes, node, views, apply: make }) {
  const frames = framesOf(nodes), now = frameOf(node) || "";
  const NEW = "\u0000new";
  const options = [
    { value: "", label: "None" },
    ...[...frames.keys()].sort().map((name) => ({ value: name, label: `${name} · ${counted(frames.get(name).length)}` })),
    { line: true },
    { value: NEW, label: "New Frame" },
  ];
  return ui.select({ value: now, options, key: `structure.frame:${node.id}`, onChange: async (value) => {
    const name = value === NEW ? frameName(node, [...frames.keys()]) : value || null;
    if ((name || "") === now) return;
    const targets = await frameMoves(nodes, node, name, views);
    make(targets, name ? `Draw in Frame ${name}` : "Draw in No Frame");
  } });
}
