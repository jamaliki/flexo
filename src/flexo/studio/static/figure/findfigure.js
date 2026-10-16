// Find and replace in a figure file (⌘F, Edit › Find in the Mac app), and what the top bar's
// search finds in it: its shapes' labels, its lines' words, its modules' titles and the words
// of the shapes drawn over it (finding.js's figureFields), found by the studio's one engine
// (findbar.js) and marked where they are drawn. Replaced, the change is one edit of the file:
// one step in its history.

import { finder, markDrawing, unmarkDrawing } from "/static/studio/findbar.js";
import { figureFields, replaced } from "/static/studio/finding.js";

// `editor`, the figure editor's: { figure (its parts, parts.js), center, drawing(), name() }.
export function figureFinder(studio, editor) {
  const { figure, center } = editor;
  // The stage under the bar, however tall it is (its replace row shown or not).
  let placed = null;
  const sized = new ResizeObserver(() => { if (placed) center.style.setProperty("--find-height", `${placed.offsetHeight}px`); });
  const show = (matches, current, query, options, fields) => {
    const svg = editor.drawing();
    if (!svg) return;
    const mark = markDrawing(svg, fields, matches, current, query, options);
    mark?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  };
  const hide = () => unmarkDrawing(editor.drawing());
  async function replace(changes, words, label) {
    const model = figure.model;
    if (!model) return;
    const targets = [];
    const shapes = Array.isArray(model.shapes) ? structuredClone(model.shapes) : null;
    let reshaped = false;
    for (const { field, ranges } of changes) {
      const value = replaced(field.value, field.kind, ranges, words), target = field.target;
      if (target.type === "shape") {
        let into = shapes;
        for (const key of target.path.slice(0, -1)) into = into?.[key];
        const shape = into?.[target.path[target.path.length - 1]];
        if (shape) { shape.text = value; reshaped = true; }
      } else if (target.key === "cofactors") {
        const edge = (model.edges || []).find((one) => one.id === target.id);
        const both = [...(edge?.cofactors || [])];
        both[target.item] = value;
        targets.push({ type: "edge", id: target.id, values: { cofactors: both } });
      } else targets.push({ type: target.type, id: target.id, values: { [target.key]: value } });
    }
    // Made by the server to the file's words, as every edit of the figure is: then the
    // document changed once, one step.
    const sent = studio.doc.text;
    let text = sent;
    for (const action of [...(targets.length ? [{ do: "update", targets }] : []), ...(reshaped ? [{ do: "shapes", shapes }] : [])]) {
      const result = await studio.api("/api/act", { file: studio.file, document: { ...studio.doc, text }, action });
      text = result?.document?.text ?? text;
    }
    if (studio.doc.text !== sent) throw new Error("The figure changed meanwhile. Try again.");
    if (text !== sent) {
      studio.change((d) => ({ ...d, text }), { label });
      studio.requestDraw?.(0);
    }
  }
  const found = finder(studio, {
    // (Each said by what it is in the figure: a shape's, a line's, a module's.)
    fields: () => figureFields(figure.model, { prefix: "" }).map((field) => ({ ...field, name: field.part })),
    place: (bar) => { placed = bar; center.prepend(bar); sized.observe(bar); },
    unplace: (bar) => { sized.disconnect(); placed = null; bar.remove(); center.style.removeProperty("--find-height"); },
    from: () => 0,
    group: () => ({ key: "figure", label: editor.name(), title: "" }),
    // (Marked where it is drawn: the parts chosen are left as they are until the bar closes.)
    go: () => {},
    show, hide, replace,
    // Closed, the shape (line, module) the last match is in is chosen.
    leave: (match) => { const id = match.field.target?.id; if (id && figure.typeOf?.(id)) figure.select([id]); },
  });
  // Its model comes with each drawing: its words read again, the marks put on the new one.
  studio.on("drawn", () => { found.refresh(); found.shown(); });
  return found;
}
