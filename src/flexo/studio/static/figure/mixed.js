// A figure's parts chosen with the shapes drawn over it (overlay.js), as a slide's objects are
// with its shapes (the studio's mixed.js): what the figure editor needs of it. ⇧-click or
// ⌘-click on a part or a shape puts it in, or takes it out, keeping the other kind; a band
// across both chooses what it touches of both. Chosen together they are deleted, cut, copied,
// pasted and duplicated together, one step; the parts move by their layout, the shapes freely.
//
// `ctx`: studio, figure (parts.js), shapes (overlay.js), page (what the drawing is in), box(id)
// (a part's frame on the page, as the editor draws it), render(), frame() (the drawing's, in
// the shapes' units), clipChosen(cut), clipItems().

import { mixedChoice } from "/static/studio/mixed.js";
import { toast } from "/static/studio/studio.js";

export function figureMixed({ studio, figure, shapes, page, box, render, frame, clipChosen, clipItems }) {
  const root = () => figure.model?.root;
  const isPart = (id) => Boolean(id && id !== root() && figure.typeOf(id));
  const picks = () => figure.selected.filter(isPart);
  // A part's box, in the shapes' units: as the figure laid it out (its drawing's info).
  const boxOf = (id) => {
    const [x, y, w, h] = studio.info?.boxes?.[id] || [];
    return [x, y, w, h].every(Number.isFinite) ? [x, y, x + w, y + h] : null;
  };
  const mixed = mixedChoice({
    studio, shapes, words: ["Shape", "Drawn Shape"], noun: "figure",
    own: {
      picks,
      name: (id) => figure.nameOf(id),
      box: boxOf,
      at: (event) => { const id = figure.idAt(event); return isPart(id) && picks().includes(id) ? id : null; },
      // (Those not drawn yet -- come back by an undo -- are chosen as the figure comes with them.)
      choose: (ids) => figure.select(ids.filter((id) => id && id !== root()), { reveal: false }),
      alone: () => {},
      remove: (ids, cut) => figure.remove(ids, [], { cut }),
      duplicate: (ids) => figure.duplicate(ids),
      clip: () => { const parts = figure.clip(); return parts ? { what: "parts", parts, label: parts.top.length > 1 ? `${parts.top.length} shapes` : "shape" } : null; },
      paste: (clipped) => figure.paste(clipped.parts),
      accepts: (clipped) => clipped?.what === "parts" && Boolean(clipped.parts?.top?.length),
      count: (clipped) => clipped.parts.top.length,
      all: () => (figure.groupOf(root())?.children || (figure.model?.nodes || []).map((node) => node.id)).filter(isPart),
      settled: () => figure.idle(),
    },
    page: () => 0, goTo: () => {},
    render, crumb: () => "Figure", frame,
    clipChosen, clipItems,
    undoNote: (text, options) => toast(text, { seconds: 3, ...options }),
    away: () => false,
  });
  // ⇧ or ⌘ pressed on a shape drawn over the figure, its parts chosen: both.
  const press = (event) => mixed.pressShape(event);
  // ⇧-click or ⌘-click on a part, shapes chosen: both.
  function click(event) {
    if (!(event.shiftKey || event.metaKey) || !shapes.any()) return false;
    const id = figure.idAt(event);
    if (!isPart(id)) return false;
    return mixed.pickOwn(id);
  }
  // A band across the figure that touches its shapes and the shapes drawn over it: both.
  function band(left, top, right, bottom, indices) {
    const outer = page.getBoundingClientRect();
    const ids = (figure.model?.nodes || []).map((node) => node.id).filter((id) => {
      const frame = box(id);
      return frame && frame.left < right - outer.left && frame.left + frame.width > left - outer.left && frame.top < bottom - outer.top && frame.top + frame.height > top - outer.top;
    });
    return mixed.band(ids, indices);
  }
  return { ...mixed, press, click, band };
}
