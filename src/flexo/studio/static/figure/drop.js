// Where a part dragged on a figure's drawing would go if let go: worked out from the
// figure's groups and where its parts are drawn, with no page -- so it is the same in
// the figure editor and on a slide, and can be tried without one.
//
//   model    the figure as its file writes it: { root, groups: [{ id, children, layout }] }
//   boxes    a Map from each part's and group's id to its box ({ left, top, right, bottom },
//            in the page's pixels): a group's is its frame, or else what it holds
//   point    the pointer, { x, y }
//   id       the part being dragged
//
// The answer is null well outside the figure (let go there, the part goes home), or
// { parent, index, kind, empty } -- index as the server's "move" takes it, among the
// group's other parts -- with, beside a part, { near, after, across, siblings }:
// the part it goes next to, which side, and whether the line between them stands
// (across a row) or lies (down a column). Under or over a figure laid out in a row
// (beside one in a column) it is { kind: "line", side, of }: a line of its own there,
// centred on the rest -- the server's "move" with ``line``. Beside a part in a column, to
// its left or right, it is { kind: "line", side, of: that part }: the two side by side;
// well under a part in a row, in line with it, { kind: "line", side: "below", of: that
// part }: the two one over the other.
//
// A part on a line of its own under a row (or over one), moved along its line: centred
// under one of the row's parts, or under the row as a whole -- { kind: "align", with,
// of, centred } (the server's "align"), judged by where the part's middle now is
// (`centre`, the pointer if not given). Nothing moves but it: the row keeps its places.

const MARGIN = 36;
const PAD = 2;
// How far under (or beside) the figure a part may be let go to start a line of its own.
const LINE = 140;
// How far past a part's side, level with it, a part is let go to go beside it.
const BESIDE = 12;
// How far under a part in a row (at least), in line with its middle, a part is let go to
// go under it: just under a row, it goes into the row.
const UNDER = 20;

export function dropPlace(model, boxes, point, id, centre = point) {
  const groups = new Map(model.groups.map((group) => [group.id, group]));
  const parent = new Map();
  for (const group of model.groups) for (const child of group.children || []) parent.set(child, group.id);
  const inside = (at, ancestor) => {
    for (let here = at; here; here = parent.get(here)) if (here === ancestor) return true;
    return false;
  };
  const all = boxes.get(model.root);
  // Along its own line under a row: centred under one of its parts, or the row.
  const lined = alignUnder(model, groups, parent, boxes, point, id, centre);
  if (lined) return lined;
  // Let go over where it was drawn -- a nudge, a press that moved a little -- it stays.
  const own = boxes.get(id), holder = groups.get(parent.get(id));
  if (own && holder && point.x >= own.left && point.x <= own.right && point.y >= own.top && point.y <= own.bottom) {
    return { parent: holder.id, index: holder.children.indexOf(id), kind: holder.layout?.kind || "column", home: true };
  }
  const under = underPart(model, groups, boxes, point, id, inside);
  if (under) return under;
  const beside = besidePart(model, groups, parent, boxes, point, id, inside);
  if (beside) return beside;
  const line = all && ownLine(model, groups.get(model.root), all, point, id);
  if (line) return line;
  if (all && (point.x < all.left - MARGIN || point.x > all.right + MARGIN || point.y < all.top - MARGIN || point.y > all.bottom + MARGIN)) return null;
  // The smallest group whose frame holds the point, not the part itself nor inside it.
  let target = null;
  for (const group of model.groups) {
    if (group.id === model.root || inside(group.id, id)) continue;
    const box = boxes.get(group.id);
    if (!box || point.x < box.left - PAD || point.x > box.right + PAD || point.y < box.top - PAD || point.y > box.bottom + PAD) continue;
    const area = (box.right - box.left) * (box.bottom - box.top);
    if (!target || area < target.area) target = { group, area };
  }
  const group = target?.group || groups.get(model.root);
  const kind = group.layout?.kind || "column";
  const siblings = (group.children || []).filter((child) => child !== id && boxes.get(child));
  if (!siblings.length) return { parent: group.id, index: 0, kind, empty: true };
  // Level with a part in a column and off to its side: beside it, the two in a row there.
  if (kind === "column") {
    const level = siblings.find((child) => !groups.has(child) && point.y >= boxes.get(child).top && point.y <= boxes.get(child).bottom);
    const box = level && boxes.get(level);
    const side = !box ? null : point.x > box.right + BESIDE ? "right" : point.x < box.left - BESIDE ? "left" : null;
    if (side) return { kind: "line", side, of: level, parent: group.id, index: -1 };
  }
  // Next to the part nearest the point: before or after it, across a row or down a
  // column; in a grid (or any other), across when the point is level with it.
  const distance = (box) => Math.hypot(Math.max(box.left - point.x, 0, point.x - box.right), Math.max(box.top - point.y, 0, point.y - box.bottom));
  const near = siblings.reduce((best, child) => (distance(boxes.get(child)) < distance(boxes.get(best)) ? child : best));
  const box = boxes.get(near);
  const across = kind === "column" ? false : kind === "row" ? true : point.y >= box.top && point.y <= box.bottom;
  // A long row folded onto two lines to fit may run back along its second (`back`): which
  // side of a part is after it is read from the parts beside it on its line.
  const at = siblings.indexOf(near);
  const level = (child) => child && boxes.get(child).top < box.bottom && boxes.get(child).bottom > box.top;
  const middle = (child) => (boxes.get(child).left + boxes.get(child).right) / 2;
  const back = Boolean(across && kind === "row" && ((level(siblings[at + 1]) && middle(siblings[at + 1]) < middle(near))
    || (level(siblings[at - 1]) && middle(siblings[at - 1]) > middle(near))));
  const after = across ? (point.x > (box.left + box.right) / 2) !== back : point.y > (box.top + box.bottom) / 2;
  return { parent: group.id, index: at + (after ? 1 : 0), kind, near, after, across, siblings, back };
}

// A part alone on its line of a column, under a line of several parts (a row) -- or over
// one, should it be the first -- and let go on its own line, its middle within that line's
// width: under the part of it whose middle is nearest its own, or under the line as a
// whole, should the line's middle be nearer still. (Answers where it already is too: the
// page reads that as staying.)
function alignUnder(model, groups, parent, boxes, point, id, centre) {
  const holder = groups.get(parent.get(id));
  if (!holder || (holder.layout?.kind || "column") !== "column" || groups.has(id)) return null;
  const own = boxes.get(id);
  const lines = (holder.children || []).filter((child) => boxes.get(child));
  const at = lines.indexOf(id);
  if (!own || at < 0) return null;
  const of = lines[at - 1] ?? lines[at + 1];
  const row = of && groups.get(of);
  const box = of && boxes.get(of);
  if (!row || !box || !(row.children || []).length) return null;
  // On its own line: from just past the line it goes with to the next line on (or a little
  // past where it is).
  const above = lines[at - 1] === of;
  const next = boxes.get(lines[above ? at + 1 : at - 1]);
  const [low, high] = above ? [box.bottom + 2, next ? next.top - 2 : own.bottom + 40] : [next ? next.bottom + 2 : own.top - 40, box.top - 2];
  if (point.y < low || point.y > high) return null;
  if (centre.x < box.left - MARGIN || centre.x > box.right + MARGIN) return null;
  const middle = (rect) => (rect.left + rect.right) / 2;
  const targets = [{ with: of, x: middle(box), centred: true },
    ...(row.children || []).filter((child) => child !== id && boxes.get(child)).map((child) => ({ with: child, x: middle(boxes.get(child)), centred: false }))];
  const best = targets.reduce((near, each) => (Math.abs(each.x - centre.x) < Math.abs(near.x - centre.x) - 0.5 ? each : near));
  return { kind: "align", with: best.with, of, centred: best.centred, side: above ? "below" : "above", x: best.x,
    here: Math.abs(middle(own) - best.x) < 1.5, parent: holder.id, index: holder.children.indexOf(id) };
}

// Well under a part in a row, and in line with its middle, with nothing else there (no
// other part, no group it is not in): under that part, the two one over the other there --
// in the row's own frame too, where it is taller than the part (beside a column), but not
// under the first line of a row folded onto two, which is its second. Under the last part
// of a column, anywhere in the free space under it: under it, in its column.
function underPart(model, groups, boxes, point, id, inside) {
  const holds = (box) => box && point.x >= box.left - 2 && point.x <= box.right + 2 && point.y >= box.top - 2 && point.y <= box.bottom + 2;
  for (const group of model.groups) {
    const way = group.layout?.kind || "column";
    if ((way !== "row" && way !== "column") || inside(group.id, id)) continue;
    // (Of a column, only its last part has free space under it.)
    const lowest = way === "column" ? (group.children || []).filter((child) => child !== id && boxes.get(child))
      .reduce((low, child) => (!low || boxes.get(child).bottom > boxes.get(low).bottom ? child : low), null) : null;
    if (way === "column" && (!lowest || groups.has(lowest))) continue;
    // Within the row's frame, under a part only where the frame has room under it -- not in
    // a row folded onto two lines, where under a part of its first is one of its second
    // (the part dragged among them, from where it was).
    const frame = holds(boxes.get(group.id)) ? boxes.get(group.id) : null;
    const filled = (box) => [...boxes.entries()].some(([other, rect]) => !groups.has(other) && rect !== box
      && rect.top >= box.bottom - 1 && rect.top < frame.bottom && rect.left < box.right && rect.right > box.left);
    for (const child of way === "column" ? [lowest] : group.children || []) {
      const box = boxes.get(child);
      if (child === id || groups.has(child) || !box || (frame && filled(box))) continue;
      // (Anywhere under its width.)
      const below = point.y - box.bottom;
      const least = way === "column" ? 4 : Math.max(UNDER, (box.bottom - box.top) * 0.6);
      if (point.x < box.left - 2 || point.x > box.right + 2 || below < least || below > LINE) continue;
      const between = [...boxes.entries()].some(([other, rect]) => other !== child && other !== id && !inside(other, id)
        && (groups.has(other) ? other !== model.root && !inside(child, other) && holds(rect) : rect.top >= box.bottom && rect.top < point.y && rect.right > point.x && rect.left < point.x));
      if (!between) return { kind: "line", side: "below", of: child, parent: group.id, index: -1 };
    }
  }
  return null;
}

// Just past a part's side, level with it, at any depth (a part in a group in a row of the
// figure's), with nothing between: beside it -- next to it in its row, or, in a column, the
// two side by side ({ kind: "line", side, of }).
const NEAR = 40;
function besidePart(model, groups, parent, boxes, point, id, inside) {
  let found = null;
  for (const [child, box] of boxes) {
    if (child === id || groups.has(child) || inside(child, id) || !parent.has(child) || String(child).includes("~line")) continue;
    if (point.y < box.top || point.y > box.bottom) continue;
    const right = point.x - box.right, left = box.left - point.x;
    const off = right >= 2 ? { side: "right", by: right } : left >= 2 ? { side: "left", by: left } : null;
    if (!off || off.by > NEAR) continue;
    // Nothing between the part and the point.
    const [from, to] = off.side === "right" ? [box.right, point.x] : [point.x, box.left];
    const between = [...boxes.entries()].some(([other, rect]) => other !== child && other !== id && !groups.has(other) && !inside(other, id)
      && rect.left < to && rect.right > from && rect.top < point.y && rect.bottom > point.y);
    if (between || (found && found.by <= off.by)) continue;
    // In a column, only past the column's own parts that way: within them, it is in line.
    const holder = groups.get(parent.get(child));
    if ((holder?.layout?.kind || "column") === "column") {
      const others = (holder.children || []).filter((each) => each !== id).map((each) => boxes.get(each)).filter(Boolean);
      const edge = off.side === "right" ? Math.max(...others.map((rect) => rect.right)) : Math.min(...others.map((rect) => rect.left));
      if (off.side === "right" ? point.x <= edge : point.x >= edge) continue;
    }
    found = { child, ...off };
  }
  if (!found) return null;
  const holder = groups.get(parent.get(found.child));
  const way = holder?.layout?.kind || "column";
  if (way === "row") {
    // In a row, beside it is next to it there -- as its row runs, should it run back.
    const siblings = (holder.children || []).filter((child) => child !== id);
    const at = siblings.indexOf(found.child);
    const next = siblings[at + 1] && boxes.get(siblings[at + 1]);
    const back = Boolean(next && (next.left + next.right) / 2 < (boxes.get(found.child).left + boxes.get(found.child).right) / 2);
    const after = (found.side === "right") !== back;
    return { parent: holder.id, index: at + (after ? 1 : 0), kind: "row", near: found.child, after, across: true, siblings, back };
  }
  return { kind: "line", side: found.side, of: found.child, parent: holder?.id || model.root, index: -1 };
}

// Out past the figure's end, across the way it runs: a line of its own there. The part
// must leave the figure's box by more than a little (by its own pad, a row's room), so
// a part let go just past its row's edge still only moves along it.
function ownLine(model, root, all, point, id) {
  const kind = root?.layout?.kind || "column";
  if (!root || id === model.root || !["row", "column"].includes(kind)) return null;
  const others = (root.children || []).filter((child) => child !== id);
  if (!others.length) return null;
  if (kind === "row") {
    if (point.x < all.left - MARGIN || point.x > all.right + MARGIN) return null;
    const side = point.y > all.bottom + 12 && point.y < all.bottom + LINE ? "below" : point.y < all.top - 12 && point.y > all.top - LINE ? "above" : null;
    return side && { kind: "line", side, of: model.root, parent: model.root, index: -1 };
  }
  if (point.y < all.top - MARGIN || point.y > all.bottom + MARGIN) return null;
  const side = point.x > all.right + 12 && point.x < all.right + LINE ? "right" : point.x < all.left - 12 && point.x > all.left - LINE ? "left" : null;
  return side && { kind: "line", side, of: model.root, parent: model.root, index: -1 };
}

// Whether letting go at ``place`` leaves the part where it is.
export function stays(model, place, id) {
  if (!place) return true;
  if (place.kind === "line") return false;
  // Lined up as it is drawn already (under that part, or centred as it is): it stays.
  if (place.kind === "align") return Boolean(place.here);
  const holder = model.groups.find((group) => (group.children || []).includes(id));
  return holder?.id === place.parent && holder.children.indexOf(id) === place.index;
}
