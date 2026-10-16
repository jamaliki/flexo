// A figure file's TODOs (todos.js) -- the word TODO, in capitals, in its shapes' labels, its
// lines' words, its modules' titles, the words drawn over it -- marked amber where they are
// drawn, counted in its zoom bar ("2 TODOs", which goes to the next), and gone to one after
// another, its shape chosen, by Next TODO (⌘') and Previous TODO (⇧⌘'), as a deck's are. None
// of it is in what the figure exports: the marks are the studio's, over its drawing.

import { h } from "/static/studio/studio.js";
import { figureFields } from "/static/studio/finding.js";
import { todoIndex, stepFrom } from "/static/studio/todos.js";
import { markTodos, todoMarks, edgeMarkers, todoButton, todoKeys, darkPaper } from "/static/studio/todomarks.js";

// `editor`, the figure editor's: { figure (its parts, parts.js), center, stage, zoomBar, drawing() }.
export function figureTodos(studio, editor) {
  const { figure, center, stage, zoomBar, drawing } = editor;
  const index = todoIndex();
  let found = { fields: [], matches: [] }, current = null;
  const button = todoButton(() => step(1));
  const gap = h("span.zoom-sep", { hidden: true });
  zoomBar.prepend(button.node, gap);
  const edges = edgeMarkers(stage, { host: center, marks: () => todoMarks(drawing()) });
  const keyOf = (match) => JSON.stringify([match.field.path, match.start]);

  // Its words read again (the model comes with each drawing), the marks put on the drawing.
  function read() {
    found = index.find(figureFields(figure.model, { prefix: "" }));
    if (current) current = found.matches.find((match) => keyOf(match) === keyOf(current)) || null;
    button.set(found.matches.length);
    gap.hidden = !found.matches.length;
    show();
  }
  function show() {
    const svg = drawing();
    const mark = svg ? markTodos(svg, found.fields, found.matches, current, { dark: darkPaper(svg) }) : null;
    edges.place();
    return mark;
  }
  // The next (or the one before), round from the last: its shape chosen, its mark in sight.
  function step(way = 1) {
    const next = stepFrom(found.matches, current, way);
    if (!next) return;
    current = next;
    const id = next.field.target?.id;
    if (id && figure.typeOf?.(id)) figure.select([id]);
    show()?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }
  studio.on("drawn", read);
  studio.todos = { count: () => found.matches.length, step };
  todoKeys();
  // View › Next TODO and Previous TODO, as the palette has them, while there are any.
  const own = studio.commands;
  studio.commands = () => [...own(), ...(found.matches.length ? [
    { icon: "tag", label: "Next TODO", keys: "⌘'", hint: button.node.textContent, run: () => step(1) },
    { icon: "tag", label: "Previous TODO", keys: "⇧⌘'", run: () => step(-1) }] : [])];
  read();
  return studio.todos;
}
