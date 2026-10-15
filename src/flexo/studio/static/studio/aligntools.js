// Align and Distribute, Inkscape's, for the shapes' editor (shapes.js) -- a slide's shapes and
// those drawn over a figure alike: the sums are aligning.js's, this is where the person meets
// them.
//
// - The inspector's Align and Distribute section, with shapes chosen: what they are aligned to
//   (Relative to: the selection, the first or last chosen, the biggest, the smallest, the slide
//   or the figure) and whether they move as a group; the six sides and middles; the four
//   besides (a right edge against its left edge...); the eight ways to spread three or more;
//   a gap to space them by, across or down; and Arrange in a Grid…. One shape aligns to the
//   page. ⇧⌘A (Inkscape's) shows it and puts the keys there.
// - The same as commands, for the palette and the Mac app's Arrange menu (by their labels), and
//   a menu of them for the right-click menu.
// - The equal spacing a drag catches at (aligning.js's `spacing`), shown: each gap as wide,
//   marked at its ends, its size written by it.
//
// Each change is one step, named for what it did: "Align 3 Shapes Left to the Biggest".
//
// `ctx` is the editor's: picks() (those chosen, in the order they were chosen), box(index)
// ([left, top, right, bottom] as drawn), locked(index), name(index) ("Rectangle"), frame()
// (the page: [x, y, width, height]), noun ("slide", "figure"), move(list, index, dx, dy)
// (one moved in a change of the list), edit(mutate, label), renderInspector(), and
// showPanel() (the inspector shown, if it was hidden).

import { h, ui, menu, dialog, toast } from "./ui.js";
import * as A from "./aligning.js";

// The sides and middles, the besides, and the ways to spread: each [value, label, icon, words].
export const SIDES = [["left", "Align Left", "align-left", "Left"], ["centre", "Align Centre", "align-centre", "Centre"], ["right", "Align Right", "align-right", "Right"],
  ["top", "Align Top", "align-top", "Top"], ["middle", "Align Middle", "align-middle", "Middle"], ["bottom", "Align Bottom", "align-bottom", "Bottom"]];
export const BESIDE = [["left-of", "Place Left of", "place-left", "Left of", "right edges against its left edge"], ["right-of", "Place Right of", "place-right", "Right of", "left edges against its right edge"],
  ["above", "Place Above", "place-above", "Above", "bottom edges against its top edge"], ["below", "Place Below", "place-below", "Below", "top edges against its bottom edge"]];
export const SPREADS = [["across", "Distribute Horizontally", "distribute-across", "Horizontally", "Equal gaps across"],
  ["lefts", "Distribute Left Edges", "distribute-lefts", "Left Edges", "Left edges evenly apart"],
  ["centres", "Distribute Centres", "distribute-centres", "Centres", "Centres evenly apart, across"],
  ["rights", "Distribute Right Edges", "distribute-rights", "Right Edges", "Right edges evenly apart"],
  ["down", "Distribute Vertically", "distribute-down", "Vertically", "Equal gaps down"],
  ["tops", "Distribute Top Edges", "distribute-tops", "Top Edges", "Top edges evenly apart"],
  ["middles", "Distribute Middles", "distribute-middles", "Middles", "Middles evenly apart, down"],
  ["bottoms", "Distribute Bottom Edges", "distribute-bottoms", "Bottom Edges", "Bottom edges evenly apart"]];
// What the Mac app's Arrange › Align Objects › Relative To runs, by label.
export const relativeLabel = (value) => `Align Relative to ${A.RELATIVE_NAMES[value]}`;
export const GROUPED = "Move as a Group";
export const SHOW = "Align and Distribute…";

const plural = (count) => (count === 1 ? "Shape" : `${count} Shapes`);
const capital = (word) => word.charAt(0).toUpperCase() + word.slice(1);
const pt = (value) => `${Math.round(value * 100) / 100} pt`;

// Where the pointer was last pressed: the menu of them opens there.
let pressed = null;
if (typeof document !== "undefined") document.addEventListener?.("pointerdown", (event) => { pressed = { x: event.clientX, y: event.clientY }; }, true);

export function alignTools(ctx) {
  const noun = ctx.noun || "page";
  const pageName = capital(noun);
  // What each choice of Relative to is called here: the page as the slide or the figure.
  const toName = (value) => (value === "page" ? pageName : A.RELATIVE_NAMES[value]);
  const label = (value) => (value === "page" ? `Align Relative to ${pageName}` : relativeLabel(value));
  const items = () => ctx.picks().map((index) => ({ id: index, box: ctx.box(index), locked: Boolean(ctx.locked(index)) })).filter((item) => item.box);
  const page = () => { const [x, y, width, height] = ctx.frame(); return [x, y, x + width, y + height]; };
  const named = (all) => (all.length === 1 ? ctx.name(all[0].id) : plural(all.length));

  // Moved as said, one step named `words` -- none when nothing would move.
  function apply(moves, words) {
    const moving = moves.filter((move) => Math.abs(move.dx) > 0.004 || Math.abs(move.dy) > 0.004);
    if (!moving.length) {
      toast(moves.length ? "Already in place" : "Locked shapes stay where they are", { icon: "align-left", seconds: 2 });
      return false;
    }
    return ctx.edit((list) => { for (const { id, dx, dy } of moving) ctx.move(list, id, dx, dy); }, words);
  }

  // -- the commands --

  function align(side) {
    const all = items();
    if (!all.length) return false;
    const relative = A.alignTo(), group = A.asGroup();
    const { moves, anchor } = A.alignMoves(all, side, { relative, group, page: page() });
    const words = A.SIDES[side] ? (SIDES.find(([value]) => value === side) || BESIDE.find(([value]) => value === side)) : null;
    if (!words || !anchor) return false;
    const beside = BESIDE.some(([value]) => value === side);
    // To what: the page, a shape among them, or (Align's own) nothing said: their bounds.
    const onto = anchor.page ? `the ${pageName}` : anchor.id !== null ? `the ${toName(relative)}` : beside ? "the Selection" : "";
    const together = group && moves.length > 1 ? ", as a Group" : "";
    return apply(moves, beside ? `Place ${named(all)} ${words[3]} ${onto}${together}` : `Align ${named(all)} ${words[3]}${onto ? ` to ${onto}` : ""}${together}`);
  }
  function distribute(how) {
    const all = items().filter((item) => !item.locked);
    if (all.length < 3) return false;
    const words = SPREADS.find(([value]) => value === how);
    if (!words) return false;
    const gaps = how === "across" || how === "down";
    return apply(A.distributeMoves(all, how), gaps ? `Distribute ${plural(all.length)} ${words[3]}` : `Distribute ${plural(all.length)}’ ${words[3]}`);
  }
  function space(way, size = A.gapSet()) {
    const all = items().filter((item) => !item.locked);
    if (all.length < 2) return false;
    return apply(A.spacedMoves(all, way, size), `Space ${plural(all.length)} ${pt(size)} Apart ${way === "down" ? "Down" : "Across"}`);
  }
  function grid(options) {
    const all = items().filter((item) => !item.locked);
    if (all.length < 2) return false;
    const made = A.gridMoves(all, options);
    return apply(made.moves, `Arrange ${plural(all.length)} in a ${made.rows} × ${made.columns} Grid`);
  }

  // The inspector's section shown, the keys on its first control (⇧⌘A, Align and Distribute…).
  function reveal() {
    if (!ctx.picks().length) return false;
    ctx.showPanel?.();
    ctx.renderInspector();
    requestAnimationFrame(() => {
      const node = [...document.querySelectorAll(".align-section")].find((each) => each.offsetParent !== null);
      if (!node) { toast("Show the inspector (Format) to align them", { icon: "align-left", seconds: 3 }); return; }
      node.scrollIntoView({ block: "nearest" });
      node.classList.remove("shown");
      void node.offsetWidth;
      node.classList.add("shown");
      node.querySelector("button.select, button:not(:disabled)")?.focus({ focusVisible: true });
    });
    return true;
  }

  // Relative to, and moving as a group: the person's (aligning.js), shown again where shown.
  A.onAligning(() => { if (ctx.picks().length && document.querySelector(".align-section")) ctx.renderInspector(); });

  // The words a command's hint says of what they are aligned to now.
  const anchorWords = () => {
    const relative = A.alignTo();
    return relative === "selection" ? "their bounds" : relative === "page" ? `the ${noun}` : `the ${toName(relative).toLowerCase()}`;
  };

  // For the palette and the Mac app's menus: what may be done with `picks` chosen (`name`:
  // what they are called, "3 Shapes").
  function commands(name) {
    const picks = ctx.picks(), count = picks.length;
    if (!count) return [];
    const many = count > 1;
    const out = SIDES.map(([side, words, glyph]) => ({ icon: glyph, label: words, hint: many ? `${name}, to ${anchorWords()}` : `To the ${noun}`, run: () => align(side) }));
    if (many) {
      out.push(...BESIDE.map(([side, words, glyph, , how]) => ({ icon: glyph, label: words, hint: `${name}: ${how.replace("its", A.alignTo() === "selection" ? "their bounds’" : `${anchorWords()}’s`)}`, run: () => align(side) })));
    }
    if (count > 2) out.push(...SPREADS.map(([how, words, glyph, , said]) => ({ icon: glyph, label: words, hint: `${name}: ${said.toLowerCase()}`, run: () => distribute(how) })));
    if (many) {
      out.push(
        { icon: "space-across", label: "Space Across by Gap", hint: `${name}, ${pt(A.gapSet())} apart, left to right`, run: () => space("across") },
        { icon: "space-down", label: "Space Down by Gap", hint: `${name}, ${pt(A.gapSet())} apart, top to bottom`, run: () => space("down") },
        { icon: "space-across", label: "Set Gap…", hint: `The gap they are spaced by (${pt(A.gapSet())})`, run: () => reveal() && focusGap() },
        { icon: "grid", label: "Arrange in a Grid…", hint: `${name}, in rows and columns`, run: () => gridSheet() },
        // What Align aligns them to, and whether it moves them together: the one in use said.
        ...A.RELATIVE.map((value) => ({ icon: "align-centre", label: label(value), ...(value === "page" ? { also: ["Align Relative to Page"] } : {}),
          hint: A.alignTo() === value ? "In use" : "What Align lines them up with", run: () => A.setAlignTo(value) })),
        { icon: "layout", label: GROUPED, hint: A.asGroup() ? "On: Align moves them together, as they are among themselves" : "Off: Align moves each on its own", run: () => A.setAsGroup(!A.asGroup()) },
      );
    }
    out.push({ icon: "align-centre", label: SHOW, keys: "⇧⌘A", hint: "Every way to line them up and space them, in the inspector", run: () => reveal() });
    return out;
  }

  // A menu of every way, for the right-click menu's Align and Distribute (whose menus have no
  // submenus): what they are aligned to ticked.
  function menuItems(name) {
    const count = ctx.picks().length;
    if (count < 2) return [];
    const all = commands(name), find = (words) => all.find((command) => command.label === words);
    return [
      { title: "Align Relative To" },
      ...A.RELATIVE.map((value) => ({ label: toName(value), checked: A.alignTo() === value, run: () => A.setAlignTo(value) })),
      { label: GROUPED, checked: A.asGroup(), run: () => A.setAsGroup(!A.asGroup()) },
      "-",
      ...BESIDE.map(([, words]) => find(words)),
      ...(count > 2 ? ["-", ...SPREADS.map(([, words]) => find(words))] : []),
      "-",
      find("Space Across by Gap"), find("Space Down by Gap"), find("Arrange in a Grid…"),
      "-",
      { label: "Show in Inspector", keys: "⇧⌘A", run: () => reveal() },
    ].filter(Boolean);
  }
  // The right-click menu's own item: that menu, where it was opened.
  const menuItem = (name) => (ctx.picks().length < 2 ? null : { icon: "align-centre", label: "Align and Distribute", hint: "Relative to, beside, distribute, a gap, a grid",
    run: () => menu(pressed || { x: innerWidth / 2, y: innerHeight / 3 }, menuItems(name)) });

  // -- the inspector --

  function focusGap() {
    requestAnimationFrame(() => { const input = [...document.querySelectorAll(".align-section [data-key='shape.align-gap']")].find((node) => node.offsetParent !== null); input?.focus(); input?.select?.(); });
    return true;
  }
  const button = (glyph, title, run) => ui.button("", run, { kind: "ghost", small: true, icon: glyph, title });
  function section() {
    const picks = ctx.picks(), count = picks.length;
    if (!count) return null;
    const many = count > 1;
    const relative = A.alignTo();
    const bits = [];
    if (many) {
      bits.push(ui.field("Relative to", ui.select({ value: relative, key: "shape.align-to", options: A.RELATIVE.map((value) => ({ value, label: toName(value) })),
          onChange: (value) => A.setAlignTo(value) })),
        ui.toggle({ value: A.asGroup(), label: GROUPED, key: "shape.align-group", onChange: (on) => A.setAsGroup(on) }));
    } else bits.push(h("div.hint-line", {}, `One shape aligns to the ${noun}`));
    const onto = many ? (relative === "selection" ? "" : ` to the ${toName(relative)}`) : ` to the ${pageName}`;
    if (many) bits.push(h("div.align-label", {}, "Align"));
    bits.push(h("div.row.arrange-row.align-row", {}, SIDES.map(([side, words, glyph]) => button(glyph, `${words}${onto}`, () => align(side)))));
    if (many) {
      const beside = relative === "selection" ? "the selection" : relative === "page" ? `the ${noun}` : `the ${toName(relative).toLowerCase()}`;
      bits.push(h("div.align-label", {}, "Beside"),
        h("div.row.arrange-row.align-row", {}, BESIDE.map(([side, words, glyph, , how]) => button(glyph, `${words} ${beside}: ${how}`, () => align(side)))));
    }
    if (count > 2) {
      bits.push(h("div.align-label", {}, "Distribute"),
        h("div.row.arrange-row.align-row", {}, SPREADS.slice(0, 4).map(([how, words, glyph, , said]) => button(glyph, `${words}: ${said.toLowerCase()}`, () => distribute(how)))),
        h("div.row.arrange-row.align-row", {}, SPREADS.slice(4).map(([how, words, glyph, , said]) => button(glyph, `${words}: ${said.toLowerCase()}`, () => distribute(how)))));
    }
    if (many) {
      const gap = ui.number({ value: A.gapSet(), step: 1, min: -1000, max: 10000, unit: "pt", key: "shape.align-gap", onChange: (value) => A.setGap(value ?? A.GAP) });
      bits.push(h("div.row.align-gap", {}, ui.field("Gap", gap),
        button("space-across", "Space Across by the Gap: left to right, the leftmost staying", () => space("across")),
        button("space-down", "Space Down by the Gap: top to bottom, the topmost staying", () => space("down"))));
      bits.push(h("div.row", {}, ui.button("Arrange in a Grid…", () => gridSheet(), { small: true, icon: "grid", title: "In rows and columns, a gap between" })));
    }
    return h("div.section.align-section", {}, h("div.section-title", {}, "Align and Distribute"), bits);
  }

  // -- Arrange in a Grid… --

  const kept = { align: "centre", valign: "middle", columns: 0, across: null, down: null };
  function gridSheet() {
    const count = items().filter((item) => !item.locked).length;
    if (count < 2) { toast("Choose two or more shapes (not locked) to arrange in a grid", { icon: "grid", seconds: 3 }); return false; }
    let columns = kept.columns && kept.columns <= count ? kept.columns : Math.ceil(Math.sqrt(count));
    let rows = A.rowsFor(count, columns);
    let across = kept.across ?? A.gapSet(), down = kept.down ?? A.gapSet();
    const cell = { align: kept.align, valign: kept.valign };
    const rowsField = ui.number({ value: rows, min: 1, max: count, step: 1, key: "grid.rows", onChange: (value) => {
      if (!value) return;
      rows = value; columns = A.columnsFor(count, rows);
      columnsField.input.value = String(columns);
    } });
    const columnsField = ui.number({ value: columns, min: 1, max: count, step: 1, key: "grid.columns", onChange: (value) => {
      if (!value) return;
      columns = value; rows = A.rowsFor(count, columns);
      rowsField.input.value = String(rows);
    } });
    const acrossField = ui.number({ value: across, step: 1, min: -1000, max: 10000, unit: "pt", key: "grid.across", onChange: (value) => { across = value ?? 0; } });
    const downField = ui.number({ value: down, step: 1, min: -1000, max: 10000, unit: "pt", key: "grid.down", onChange: (value) => { down = value ?? 0; } });
    const body = h("div.grid-sheet", {},
      h("div.row", {}, ui.field("Rows", rowsField), ui.field("Columns", columnsField)),
      h("div.row", {}, ui.field("Gap Across", acrossField), ui.field("Gap Down", downField)),
      ui.field("In Each Cell", h("div.grid-cell", {},
        ui.segmented({ value: cell.align, key: "grid.align", onChange: (value) => { cell.align = value; },
          options: [{ value: "left", icon: "align-left", title: "Left" }, { value: "centre", icon: "align-centre", title: "Centre" }, { value: "right", icon: "align-right", title: "Right" }] }),
        ui.segmented({ value: cell.valign, key: "grid.valign", onChange: (value) => { cell.valign = value; },
          options: [{ value: "top", icon: "align-top", title: "Top" }, { value: "middle", icon: "align-middle", title: "Middle" }, { value: "bottom", icon: "align-bottom", title: "Bottom" }] }))),
      h("div.hint-line", {}, `${count} shapes, in the order they read: left to right, then top to bottom. Each column is as wide as its widest; each row as tall as its tallest.`));
    const arrange = () => {
      Object.assign(kept, { columns, across, down, ...cell });
      grid({ columns, rows, gap: across, gapDown: down, ...cell });
    };
    const sheet = dialog({ title: "Arrange in a Grid", body, actions: [{ label: "Cancel" }, { label: "Arrange", kind: "primary", run: arrange }] });
    // Return in a number (taken by the field first) arranges them, as a Mac sheet's default does.
    body.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.isComposing || !event.target.matches?.("input")) return;
      setTimeout(() => { arrange(); sheet.close(); }, 0);
    });
    setTimeout(() => { columnsField.input.focus(); columnsField.input.select(); }, 0);
    return true;
  }

  return { align, distribute, space, grid, gridSheet, reveal, commands, menuItem, menuItems, section };
}

// -- equal spacing while one is dragged --

// Of a guide caught (`guide`: { gap }) and an equal spacing (`even`: { shift }) one way, the
// nearer -- both when they put it in one place: [guide or null, even or null].
export function nearer(guide, even) {
  if (!even) return [guide, null];
  if (!guide) return [null, even];
  if (Math.abs(even.shift - guide.gap) < 1e-6) return [guide, even];
  return Math.abs(even.shift) < Math.abs(guide.gap) ? [null, even] : [guide, null];
}

const said = (size) => String(Math.round(size * 10) / 10);
// Each gap of a catch drawn in `into` (the editor's guides, in the page's units; `px` a
// screen pixel there): a line across it, its ends marked, its size beside it. `S` makes an
// SVG element.
export function drawSpacing(into, marks, px, S) {
  for (const { axis, from, to, at, size } of marks) {
    const tick = 4 * px, words = said(size);
    const width = (words.length * 6 + 8) * px, height = 13 * px;
    const line = axis === 0 ? [[from, at], [to, at]] : [[at, from], [at, to]];
    const ends = axis === 0 ? [[from, at - tick, from, at + tick], [to, at - tick, to, at + tick]] : [[at - tick, from, at + tick, from], [at - tick, to, at + tick, to]];
    const middle = (from + to) / 2;
    const [cx, cy] = axis === 0 ? [middle, at - tick - 3 * px - height / 2] : [at + tick + 3 * px + width / 2, middle];
    into.append(S("g", { class: "shape-spacing" },
      S("line", { x1: line[0][0], y1: line[0][1], x2: line[1][0], y2: line[1][1], "stroke-width": 1.2 * px }),
      ...ends.map(([x1, y1, x2, y2]) => S("line", { x1, y1, x2, y2, "stroke-width": 1.2 * px })),
      S("rect", { class: "shape-spacing-tag", x: cx - width / 2, y: cy - height / 2, width, height, rx: height / 2 }),
      Object.assign(S("text", { class: "shape-spacing-words", x: cx, y: cy + 3.6 * px, "text-anchor": "middle", "font-size": 10 * px }), { textContent: words })));
  }
}
