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
// (across a row) or lies (down a column).

const MARGIN = 36;
const PAD = 2;

export function dropPlace(model, boxes, point, id) {
  const groups = new Map(model.groups.map((group) => [group.id, group]));
  const parent = new Map();
  for (const group of model.groups) for (const child of group.children || []) parent.set(child, group.id);
  const inside = (at, ancestor) => {
    for (let here = at; here; here = parent.get(here)) if (here === ancestor) return true;
    return false;
  };
  const all = boxes.get(model.root);
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
  // Next to the part nearest the point: before or after it, across a row or down a
  // column; in a grid (or any other), across when the point is level with it.
  const distance = (box) => Math.hypot(Math.max(box.left - point.x, 0, point.x - box.right), Math.max(box.top - point.y, 0, point.y - box.bottom));
  const near = siblings.reduce((best, child) => (distance(boxes.get(child)) < distance(boxes.get(best)) ? child : best));
  const box = boxes.get(near);
  const across = kind === "column" ? false : kind === "row" ? true : point.y >= box.top && point.y <= box.bottom;
  const after = across ? point.x > (box.left + box.right) / 2 : point.y > (box.top + box.bottom) / 2;
  return { parent: group.id, index: siblings.indexOf(near) + (after ? 1 : 0), kind, near, after, across, siblings };
}

// Whether letting go at ``place`` leaves the part where it is.
export function stays(model, place, id) {
  if (!place) return true;
  const holder = model.groups.find((group) => (group.children || []).includes(id));
  return holder?.id === place.parent && holder.children.indexOf(id) === place.index;
}
