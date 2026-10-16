// Align and Distribute, Inkscape's, for the shapes' editor (shapes.js) -- a slide's shapes and
// those drawn over a figure alike: the sums are aligning.js's, this is where the person meets
// them.
//
// - The inspector's Align and Distribute section, with shapes chosen: what they are aligned to
//   (Relative to: the selection, the first or last chosen, the biggest, the smallest, the slide
//   or the figure) and whether they move as a group -- a setting, there with one shape too; the
//   six sides and middles; the four besides (a right edge against its left edge...); the eight
//   ways to spread three or more, greyed with fewer, saying so; a gap to space them by, across
//   or down; and Arrange in a Grid…, which shows where they will go while its sheet is open.
//   One shape aligns to the page. ⇧⌘A (Inkscape's) shows it and puts the keys there.
// - The same as commands, for the palette and the Mac app's Arrange menu (by their labels), and
//   a menu of them for the right-click menu. Relative To and Move as a Group are the studio's
//   own (`settingCommands`), offered whatever is chosen; in the Mac app the app keeps them for
//   every window, as it keeps snapping (`aligningInApp`).
// - The equal spacing a drag catches at (aligning.js's `spacing`), shown: each gap as wide,
//   marked at its ends, its size written by it -- and a shape's edge sized or drawn (`edges`).
//
// Each change is one step, named for what it did: "Align 3 Shapes Left to the Biggest".
//
// `ctx` is the editor's: picks() (those chosen, in the order they were chosen), box(index)
// ([left, top, right, bottom] as drawn), locked(index), fixed(index) (what the page lays out,
// chosen with the shapes: never moved, but spread among -- aligning.js), name(index)
// ("Rectangle"), frame() (the page: [x, y, width, height]), noun ("slide", "figure"), word
// (what each is called: "Shape", the default; a slide's objects, "Object"),
// move(list, index, dx, dy) (one moved in a change of the list), edit(mutate, label),
// show(moves) (those moves drawn where they would go, as a drag draws them, not made; null:
// as they are), few (what Distribute says it needs), renderInspector(), and showPanel() (the
// inspector shown, if it was hidden).

import { h, icon, ui, menu, dialog, toast } from "./ui.js";
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
// Why Distribute is greyed, as its hint and tooltip say it; and the rest, with fewer than two.
export const FEW = "Choose three or more shapes";
export const TWO = "Choose two or more shapes";

// What Align lines shapes up with, and whether it moves them as a group: the person's setting,
// changed at any time, shapes chosen or not -- in the palette, and by these labels the Mac
// app's Arrange › Align Objects › Relative To. `pageName`: the page as the document names it
// ("Slide", "Figure").
export function settingCommands(pageName = "Page") {
  return [
    ...A.RELATIVE.map((value) => ({ icon: "align-centre", label: value === "page" ? `Align Relative to ${pageName}` : relativeLabel(value),
      ...(value === "page" && pageName !== "Page" ? { also: ["Align Relative to Page"] } : {}),
      hint: A.alignTo() === value ? "In use" : "What Align lines shapes up with", run: () => A.setAlignTo(value) })),
    { icon: "layout", label: GROUPED, hint: A.asGroup() ? "On: Align moves them together, as they are among themselves" : "Off: Align moves each on its own", run: () => A.setAsGroup(!A.asGroup()) },
  ];
}

const capital = (word) => word.charAt(0).toUpperCase() + word.slice(1);
const pt = (value) => `${Math.round(value * 100) / 100} pt`;

// Where the pointer was last pressed: the menu of them opens there.
let pressed = null;
if (typeof document !== "undefined") document.addEventListener?.("pointerdown", (event) => { pressed = { x: event.clientX, y: event.clientY }; }, true);

export function alignTools(ctx) {
  const noun = ctx.noun || "page";
  // What one is called, and several: "Shape", "3 Shapes" (a slide's objects, "3 Objects").
  const word = ctx.word || "Shape", lower = word.toLowerCase();
  const plural = (count) => (count === 1 ? word : `${count} ${word}s`);
  const two = word === "Shape" ? TWO : `Choose two or more ${lower}s`;
  const pageName = capital(noun);
  // What each choice of Relative to is called here: the page as the slide or the figure.
  const toName = (value) => (value === "page" ? pageName : A.RELATIVE_NAMES[value]);
  const items = () => ctx.picks().map((index) => ({ id: index, box: ctx.box(index), locked: Boolean(ctx.locked(index)), fixed: Boolean(ctx.fixed?.(index)) })).filter((item) => item.box);
  const few = () => (typeof ctx.few === "function" ? ctx.few() : ctx.few) || (word === "Shape" ? FEW : `Choose three or more ${lower}s`);
  // Whether Distribute may spread them: three or more, not locked (those fixed among them), one free to move.
  const spreads = () => A.distributable(items());
  const page = () => { const [x, y, width, height] = ctx.frame(); return [x, y, x + width, y + height]; };
  const named = (all) => (all.length === 1 ? ctx.name(all[0].id) : plural(all.length));

  // Moved as said, one step named `words` -- none when nothing would move.
  function apply(moves, words) {
    const moving = moves.filter((move) => Math.abs(move.dx) > 0.004 || Math.abs(move.dy) > 0.004);
    if (!moving.length) {
      toast(moves.length ? "Already in place" : `Locked ${lower}s stay where they are`, { icon: "align-left", seconds: 2 });
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
    const all = items().filter((item) => !item.locked || item.fixed);
    if (!A.distributable(all)) { toast(few(), { icon: "distribute-across", seconds: 2.5 }); return false; }
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
  // (`from`: where they were as a sheet opened -- drawn where they would go since.)
  function grid(options, from = null) {
    const all = from || items().filter((item) => !item.locked);
    if (all.length < 2) return false;
    const made = A.gridMoves(all, options);
    return apply(made.moves, `Arrange ${plural(all.length)} in a ${made.rows} × ${made.columns} Grid`);
  }

  // The inspector's section shown, the keys on its first control (⇧⌘A, Align and Distribute…):
  // in the page's tab of its own (`showTab`, Arrange) whatever is chosen, else in Format.
  function reveal() {
    if (ctx.tab?.()) ctx.showTab();
    else {
      if (!ctx.picks().length) return false;
      ctx.showPanel?.();
    }
    ctx.renderInspector();
    // (Drawn at once; else a moment later. Never waiting on a frame: a window behind others
    // draws none.)
    const show = (again) => {
      const node = [...document.querySelectorAll(".align-section")].find((each) => each.offsetParent !== null);
      if (!node) {
        if (again) setTimeout(() => show(false), 60);
        else toast(ctx.tab?.() ? "Show the inspector (Arrange) to align them" : "Show the inspector (Format) to align them", { icon: "align-left", seconds: 3 });
        return;
      }
      node.scrollIntoView({ block: "nearest" });
      node.classList.remove("shown");
      void node.offsetWidth;
      node.classList.add("shown");
      node.querySelector("button.select, button:not(:disabled)")?.focus({ focusVisible: true });
    };
    show(true);
    return true;
  }

  // Relative to, and moving as a group: the person's (aligning.js), shown again where shown.
  A.onAligning(() => { if ((ctx.picks().length || ctx.tab?.()) && document.querySelector(".align-section")) ctx.renderInspector(); });

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
    // (Greyed, saying why, with fewer than three to spread: the Mac app's menu says it too.)
    const spread = spreads();
    out.push(...SPREADS.map(([how, words, glyph, , said]) => ({ icon: glyph, label: words, hint: spread ? `${name}: ${said.toLowerCase()}` : few(), disabled: !spread, run: () => distribute(how) })));
    if (many) {
      out.push(
        { icon: "space-across", label: "Space Across by Gap", hint: `${name}, ${pt(A.gapSet())} apart, left to right`, run: () => space("across") },
        { icon: "space-down", label: "Space Down by Gap", hint: `${name}, ${pt(A.gapSet())} apart, top to bottom`, run: () => space("down") },
        { icon: "space-across", label: "Set Gap…", hint: `The gap they are spaced by (${pt(A.gapSet())})`, run: () => reveal() && focusGap() },
        { icon: "grid", label: "Arrange in a Grid…", hint: `${name}, in rows and columns`, run: () => gridSheet() },
        // (What Align aligns them to, and whether it moves them together, are the studio's:
        // offered whatever is chosen -- settingCommands.)
      );
    }
    out.push({ icon: "align-centre", label: SHOW, keys: "⇧⌘A", hint: "Every way to line them up and space them, in the inspector", run: () => reveal() });
    return out;
  }

  // A menu of every way, for the right-click menu's Align and Distribute (whose menus have no
  // submenus): what they are aligned to ticked.
  function menuItems(name) {
    const count = ctx.picks().length;
    if (!count) return [];
    const all = commands(name), find = (words) => all.find((command) => command.label === words);
    const many = count > 1;
    return [
      { title: "Align Relative To" },
      ...A.RELATIVE.map((value) => ({ label: toName(value), checked: A.alignTo() === value, run: () => A.setAlignTo(value) })),
      { label: GROUPED, checked: A.asGroup(), run: () => A.setAsGroup(!A.asGroup()) },
      ...(many ? ["-", ...BESIDE.map(([, words]) => find(words)), "-", ...SPREADS.map(([, words]) => find(words)),
        "-", find("Space Across by Gap"), find("Space Down by Gap"), find("Arrange in a Grid…")] : []),
      "-",
      { label: "Show in Inspector", keys: "⇧⌘A", run: () => reveal() },
    ].filter(Boolean);
  }
  // The right-click menu's own item: that menu, where it was opened (Relative To there with one).
  const menuItem = (name) => (!ctx.picks().length ? null : { icon: "align-centre", label: "Align and Distribute", hint: ctx.picks().length > 1 ? "Relative to, beside, distribute, a gap, a grid" : "Relative to: what Align lines shapes up with",
    run: () => menu(pressed || { x: innerWidth / 2, y: innerHeight / 3 }, menuItems(name)) });

  // -- the inspector --

  function focusGap() {
    setTimeout(() => { const input = [...document.querySelectorAll(".align-section [data-key='shape.align-gap']")].find((node) => node.offsetParent !== null); input?.focus(); input?.select?.(); }, 80);
    return true;
  }
  const button = (glyph, title, run) => ui.button("", run, { kind: "ghost", small: true, icon: glyph, title });
  // In the inspector: Relative to and Move as a Group, then the sides, beside, spread, a gap and
  // a grid. In a tab of its own (`tab`: the deck's Arrange, the figure's), every row is there
  // whatever is chosen, greyed where it does not apply, saying what it needs -- Relative to and
  // the gap still settings to change; elsewhere, as many rows as apply.
  function section({ tab = false } = {}) {
    const picks = ctx.picks(), count = picks.length;
    if (!count && !tab) return null;
    const many = count > 1, all = tab || many;
    const free = items().filter((item) => !item.locked).length;
    const relative = A.alignTo();
    const bits = [];
    // (A setting, changed with one shape chosen too, or none: what several will be aligned to.)
    bits.push(ui.field("Relative to", ui.select({ value: relative, key: "shape.align-to", options: A.RELATIVE.map((value) => ({ value, label: toName(value) })),
        onChange: (value) => A.setAlignTo(value) })),
      ui.toggle({ value: A.asGroup(), label: GROUPED, key: "shape.align-group", onChange: (on) => A.setAsGroup(on) }));
    const onto = many ? (relative === "selection" ? "" : ` to the ${toName(relative)}`) : ` to the ${pageName}`;
    // (A row greyed says why, in its buttons' tooltips.)
    const row = (on, why, entries) => h("div.row.arrange-row.align-row", { title: on ? "" : why }, entries.map(([glyph, title, run]) => {
      const node = button(glyph, on ? title : `${title.split(":")[0]}: ${why.charAt(0).toLowerCase()}${why.slice(1)}`, run);
      node.disabled = !on;
      return node;
    }));
    if (all) bits.push(h("div.align-label", {}, "Align"));
    bits.push(row(count > 0, `Choose a ${lower}`, SIDES.map(([side, words, glyph]) => [glyph, `${words}${onto}`, () => align(side)])));
    if (all) {
      const beside = relative === "selection" ? "the selection" : relative === "page" ? `the ${noun}` : `the ${toName(relative).toLowerCase()}`;
      bits.push(h("div.align-label", {}, "Beside"),
        row(many, two, BESIDE.map(([side, words, glyph, , how]) => [glyph, `${words} ${beside}: ${how}`, () => align(side)])));
      // (Greyed with fewer than three to spread, saying why.)
      const spread = spreads(), why = few();
      const ways = (list) => list.map(([how, words, glyph, , said]) => [glyph, `${words}: ${said.toLowerCase()}`, () => distribute(how)]);
      bits.push(h("div.align-label", {}, "Distribute", spread || !count ? null : h("span.align-why", {}, why)), row(spread, why, ways(SPREADS.slice(0, 4))), row(spread, why, ways(SPREADS.slice(4))));
      const gap = ui.number({ value: A.gapSet(), step: 1, min: -1000, max: 10000, unit: "pt", key: "shape.align-gap", onChange: (value) => A.setGap(value ?? A.GAP) });
      const spaces = row(free > 1, two, [["space-across", "Space Across by the Gap: left to right, the leftmost staying", () => space("across")],
        ["space-down", "Space Down by the Gap: top to bottom, the topmost staying", () => space("down")]]);
      bits.push(h("div.row.align-gap", {}, ui.field("Gap", gap), ...spaces.children));
      const grid = ui.button("Arrange in a Grid…", () => gridSheet(), { small: true, icon: "grid", title: free > 1 ? "In rows and columns, a gap between" : two });
      grid.disabled = free < 2;
      bits.push(h("div.row", {}, grid));
    }
    return h("div.section.align-section", {}, h("div.section-title", {}, "Align and Distribute"), bits);
  }
  // In Format, where Arrange and Align and Distribute have a tab of their own: one line, going there.
  function link() {
    const go = h("button.btn.ghost.small.align-link", { type: "button", title: "Where it is, its order, and Align and Distribute: the Arrange tab (⇧⌘A)", onclick: () => reveal() },
      icon("arrange"), h("span.btn-label", {}, "Arrange, Align and Distribute"), icon("chevron"));
    return h("div.section.align-link-section", {}, go);
  }

  // -- Arrange in a Grid… --

  // While its sheet is open, they are drawn where they would go -- as a drag draws them, not
  // changed -- each change in it (a number typed, before it is taken; a choice) drawn at once.
  // Cancel (Esc, a click beside it) puts them back; Arrange is one step. Locked shapes stay
  // where they are, and it says how many.
  const kept = { align: "centre", valign: "middle", columns: 0, across: null, down: null };
  function gridSheet() {
    const chosen = items(), free = chosen.filter((item) => !item.locked), count = free.length;
    const stay = chosen.filter((item) => item.locked && !item.fixed).length;
    if (count < 2) { toast(`Choose two or more ${lower}s (not locked) to arrange in a grid`, { icon: "grid", seconds: 3 }); return false; }
    let columns = kept.columns && kept.columns <= count ? kept.columns : Math.ceil(Math.sqrt(count));
    let rows = A.rowsFor(count, columns);
    let across = kept.across ?? A.gapSet(), down = kept.down ?? A.gapSet();
    const cell = { align: kept.align, valign: kept.valign };
    const options = () => ({ columns, rows, gap: across, gapDown: down, ...cell });
    let shown = false, arranged = false;
    const preview = () => { if (!ctx.show) return; shown = true; ctx.show(A.gridMoves(free, options()).moves); };
    const unshow = () => { if (shown && !arranged) ctx.show(null); shown = false; };
    const setRows = (value) => { rows = value; columns = A.columnsFor(count, rows); columnsField.input.value = String(columns); preview(); };
    const setColumns = (value) => { columns = value; rows = A.rowsFor(count, columns); rowsField.input.value = String(rows); preview(); };
    const rowsField = ui.number({ value: rows, min: 1, max: count, step: 1, key: "grid.rows", onChange: (value) => { if (value) setRows(value); } });
    const columnsField = ui.number({ value: columns, min: 1, max: count, step: 1, key: "grid.columns", onChange: (value) => { if (value) setColumns(value); } });
    const acrossField = ui.number({ value: across, step: 1, min: -1000, max: 10000, unit: "pt", key: "grid.across", onChange: (value) => { across = value ?? 0; preview(); } });
    const downField = ui.number({ value: down, step: 1, min: -1000, max: 10000, unit: "pt", key: "grid.down", onChange: (value) => { down = value ?? 0; preview(); } });
    // (A number drawn as it is typed, before the field takes it: "3", "12pt".)
    const typing = (field, low, high, use) => field.input.addEventListener("input", () => {
      const text = field.input.value.trim().replace(",", ".").replace(/\s*pt$/i, ""), value = text === "" ? NaN : Number(text);
      if (Number.isFinite(value) && value >= low && value <= high) use(value);
    });
    typing(rowsField, 1, count, (value) => setRows(Math.round(value)));
    typing(columnsField, 1, count, (value) => setColumns(Math.round(value)));
    typing(acrossField, -1000, 10000, (value) => { across = value; preview(); });
    typing(downField, -1000, 10000, (value) => { down = value; preview(); });
    const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
    const body = h("div.grid-sheet", {},
      h("div.row", {}, ui.field("Rows", rowsField), ui.field("Columns", columnsField)),
      h("div.row", {}, ui.field("Gap Across", acrossField), ui.field("Gap Down", downField)),
      ui.field("In Each Cell", h("div.grid-cell", {},
        ui.segmented({ value: cell.align, key: "grid.align", onChange: (value) => { cell.align = value; preview(); },
          options: [{ value: "left", icon: "align-left", title: "Left" }, { value: "centre", icon: "align-centre", title: "Centre" }, { value: "right", icon: "align-right", title: "Right" }] }),
        ui.segmented({ value: cell.valign, key: "grid.valign", onChange: (value) => { cell.valign = value; preview(); },
          options: [{ value: "top", icon: "align-top", title: "Top" }, { value: "middle", icon: "align-middle", title: "Middle" }, { value: "bottom", icon: "align-bottom", title: "Bottom" }] }))),
      h("div.hint-line", {}, `${plural(count, lower)}, in the order they read: left to right, then top to bottom. Each column is as wide as its widest; each row as tall as its tallest.`),
      stay ? h("div.hint-line.grid-locked", {}, `${plural(stay, `locked ${lower}`)} stay${stay === 1 ? "s" : ""} put`) : null);
    const arrange = () => {
      Object.assign(kept, { columns, across, down, ...cell });
      // (Drawn there already: the page's drawing takes its place as it comes -- or, nothing
      // moved, they are put back.)
      arranged = Boolean(grid(options(), free));
      unshow();
    };
    const sheet = dialog({ title: "Arrange in a Grid", body, onClose: unshow,
      actions: [{ label: "Cancel", run: () => { unshow(); } }, { label: "Arrange", kind: "primary", run: arrange }] });
    // (The page under it in sight: the sheet aside, at the top, nothing dimmed.)
    body.closest(".scrim")?.classList.add("grid-scrim");
    // Return in a number (taken by the field first) arranges them, as a Mac sheet's default does.
    body.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.isComposing || !event.target.matches?.("input")) return;
      setTimeout(() => { arrange(); sheet.close(); }, 0);
    });
    preview();
    setTimeout(() => { columnsField.input.focus(); columnsField.input.select(); }, 0);
    return true;
  }

  return { align, distribute, space, grid, gridSheet, reveal, commands, menuItem, menuItems, section, link };
}

// -- equal spacing while one is dragged --

// (Of a guide and an equal spacing, the nearer; and an edge sized or drawn caught at either:
// aligning.js's sums.)
export { nearer, sizeCatch } from "./aligning.js";

// -- in the Mac app --

// In the Mac app, whose windows each have their own storage (a folder's own address): the app
// keeps Relative to, Move as a Group and the gap for them all, from one launch to the next, as
// it keeps snapping (magnet.js) -- told when one is changed here, and asked as this window opens
// and each time it comes to the front; another window's change reaches this one as the app's
// "aligning" command (shell.js: `aligningFromApp`). The app with none kept yet takes this
// window's. What it keeps has a version, one later at each change: an answer older than one
// this window has seen -- an ask the app answered before it kept a change made here -- is not
// taken, nor one to an ask made while a change of this window's is on its way.
let seen = -1;
const newer = (kept) => { const version = Number(kept?.version ?? 0); if (!Number.isFinite(version) || version < seen) return false; seen = version; return true; };
export function aligningFromApp(kept) {
  if (kept && typeof kept === "object" && newer(kept)) A.setAligning(kept, "app");
}
export function aligningInApp() {
  const api = () => (typeof window === "undefined" ? null : window.pywebview?.api);
  let changes = 0, sending = 0;
  A.onAligning((said, how) => {
    if (how !== "here") return;
    changes += 1;
    sending += 1;
    Promise.resolve(api()?.aligning?.(said)).then((kept) => { if (kept && typeof kept === "object") newer(kept); }).catch(() => {}).finally(() => { sending -= 1; });
  });
  const ask = () => {
    const asked = changes;
    return Promise.resolve(api()?.aligning?.()).then((kept) => {
      if (asked !== changes || sending || !kept || typeof kept !== "object") return;
      if (Object.keys(kept).length) aligningFromApp(kept);
      else api()?.aligning?.(A.aligning());
    }).catch(() => {});
  };
  window.addEventListener("pywebviewready", ask);
  window.addEventListener("focus", ask);
  if (api()?.aligning) ask();
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
