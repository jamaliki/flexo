// The help bar: one quiet row along the foot of the studio's window, under the documents and
// their panels, of the keys that matter for what is being done now -- each a keycap and a word
// or two, the most to the point first (helpkeys.js) -- as Blender's and Inkscape's status bars
// say them. While a shape is dragged it says what ⇧, ⌥ and ⌘ do to the drag, each keycap lit
// while it is held; while the find bar is open, its keys; while words are typed, theirs.
// Nothing while presenting, or with a sheet or the search up.
//
// - Shown unless hidden: View › Hide Help Bar (the palette, the Mac app's View menu), or its
//   own right-click. One setting for the person, kept in this browser, as the grid is.
// - What is being done is asked as it may change -- a key, a press, a document's focus, the
//   keys going elsewhere -- once a frame at most, of the shell (the find bar, words typed) and
//   of the document's editor (`studio.help()`: what it is dragging, cropping, drawing, what is
//   chosen). The row is drawn again only when what it says changes; a drag's moves ask
//   nothing once the drag has said what it is.

import { h, menu } from "./ui.js";
import { itemsFor, keyOf, chords, compact, together, helpShown, setHelpShown, onHelp } from "./helpkeys.js";
import { gridShown, onGrid } from "./grid.js";
import { snapMode, onSnapping } from "./snapping.js";

export { helpShown, setHelpShown, toggleHelp, onHelp, helpCommand } from "./helpkeys.js";

// -- what is being done, as the shell sees it --

const typedIn = (node) => Boolean(node && (node.isContentEditable || node.tagName === "TEXTAREA"
  || (node.tagName === "INPUT" && /^(text|search|email|url|tel|password|number|)$/.test(node.type || ""))));
// Words typed: where (the editor says more of its own: a list, a table's cell).
function typingOf(at) {
  if (!typedIn(at)) return "";
  if (at.closest(".shape-words")) return at.closest(".shape-words.plain") ? "plain" : "shape";
  if (at.closest(".fig-inline")) return "label";
  if (at.closest(".inline-editor")) return "words";
  if (at.closest(".notes")) return "notes";
  return "field";
}

function contextOf(workspace) {
  // (The show, a sheet, the search: their own keys, said where they are.)
  if (document.querySelector(".present, .scrim")) return { hidden: true };
  const session = workspace.active;
  const at = document.activeElement;
  const shell = { page: session?.kind || "", grid: gridShown(), snapping: snapMode(), typing: typingOf(at) };
  if (session?.finder?.isOpen) {
    const field = at?.closest?.(".find-bar") && typedIn(at);
    shell.find = field ? (at.getAttribute("aria-label") === "Replace" ? "replace" : "find") : "open";
  }
  let own = {};
  try { own = (session?.help?.() || {}); } catch (error) { console.error(error); }
  // (What is typed the editor says more of, while words are typed; the rest the shell's first.)
  const { typing, ...rest } = own;
  return together({ typing: shell.typing && typing ? typing : shell.typing }, shell, rest);
}

// -- the bar --

const HELD = { "⇧": "Shift", "⌥": "Alt", "⌘": "Meta" };

export function helpBar(workspace) {
  const node = h("footer.help-bar", { hidden: !helpShown(), "aria-label": "Keys" });
  let drawn = null, frame = 0, pressing = false, dragging = false;
  const held = { Shift: false, Alt: false, Meta: false };

  function draw(items) {
    node.replaceChildren(...items.map((item) => {
      // (A gesture -- Double-Click, Drag -- a keycap too, as named: "or" a word between them.)
      const caps = compact(chords(item.keys)).map((part) => (part.word === "or" ? h("span.help-word", {}, "or")
        : h("kbd.help-key", {}, part.key ?? part.word.replace(/(^|-)\p{L}/gu, (first) => first.toUpperCase()))));
      return h("span.help-item", HELD[item.keys] ? { dataset: { held: HELD[item.keys] } } : {}, h("span.help-keys", {}, caps), h("span.help-what", {}, item.words));
    }));
    light();
  }
  // Those for a modifier held lit, as it is held.
  function light() {
    for (const item of node.children) if (item.dataset.held) item.classList.toggle("held", Boolean(held[item.dataset.held]));
  }
  function update() {
    frame = 0;
    if (!helpShown()) return;
    const context = contextOf(workspace);
    dragging = Boolean(context.drag);
    const items = itemsFor(context);
    const key = keyOf(items);
    if (key === drawn) return;
    drawn = key;
    draw(items);
  }
  // (A window out of sight draws no frames: its bar is said all the same, by then.)
  const soon = () => { if (!frame && helpShown()) frame = document.hidden ? setTimeout(update, 30) : requestAnimationFrame(update); };

  // What ⇧, ⌥ and ⌘ are now, from the keys and the pointer as they come.
  const mods = (event) => {
    const now = { Shift: Boolean(event.shiftKey), Alt: Boolean(event.altKey), Meta: Boolean(event.metaKey) };
    if (now.Shift === held.Shift && now.Alt === held.Alt && now.Meta === held.Meta) return;
    Object.assign(held, now);
    light();
  };
  // (A modifier's own keydown says it with it held, its keyup without.)
  const keyed = (event) => { mods(event); soon(); };
  window.addEventListener("keydown", keyed, true);
  window.addEventListener("keyup", keyed, true);
  window.addEventListener("pointerdown", (event) => { pressing = true; dragging = false; mods(event); soon(); }, true);
  // A drag's moves ask what it is until it says; then nothing, however long it goes on.
  window.addEventListener("pointermove", () => { if (pressing && !dragging) soon(); }, { capture: true, passive: true });
  for (const type of ["pointerup", "pointercancel"]) window.addEventListener(type, () => { pressing = false; soon(); }, true);
  window.addEventListener("dblclick", soon, true);
  window.addEventListener("blur", () => { Object.assign(held, { Shift: false, Alt: false, Meta: false }); pressing = false; light(); soon(); });
  document.addEventListener("focusin", soon);
  document.addEventListener("focusout", soon);
  for (const event of ["status", "active", "opened", "closed", "focus", "side"]) workspace.on(event, soon);
  onGrid(soon);
  onSnapping(soon);
  // (A sheet, the search or the show opening and closing.)
  new MutationObserver(soon).observe(document.body, { childList: true });

  node.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    menu({ x: event.clientX, y: event.clientY }, [{ icon: "keyboard", label: "Hide Help Bar", run: () => setHelpShown(false) }]);
  });
  // Pressed, it leaves the keys where they were.
  node.addEventListener("mousedown", (event) => event.preventDefault());
  onHelp((on) => {
    node.hidden = !on;
    drawn = null;
    if (on) soon(); else node.replaceChildren();
  });
  soon();
  return { node, update: soon };
}
