// One choice of two kinds, as Keynote's is: a slide's objects (its words, lists, pictures,
// figures) chosen with the shapes drawn on it, and a figure's parts with the shapes drawn over
// it. ⇧-click or ⌘-click puts any of either into the choice, or takes it out, keeping what is
// chosen of the other; a band across both chooses what it touches of both. Each shows as
// chosen as it does alone. Chosen together they are:
// - named in the inspector ("2 Objects, 3 Shapes"), with Cut, Copy, Duplicate and Delete, and
//   Align and Distribute for the shapes, what the page holds among what they align to (it stays:
//   it is laid out, not placed) -- a drawing's left edge to a text's;
// - deleted by ⌫, cut, copied and pasted by ⌘X, ⌘C and ⌘V (each kind's copy in one: pasted,
//   each goes where it goes pasted alone), duplicated by ⌘D -- each one step in the history,
//   named for both; undone or redone, both are chosen again;
// - nudged by the arrows, the shapes alone (the page's own things are laid out); dragged as
//   each kind is dragged, the other staying where it is;
// - the same commands by name, for the palette, the right-click menu and the Mac app's menus.
// A plain click chooses one thing, as ever; Esc, or a click where nothing is, chooses none.
//
// `ctx` is the page's (a deck's editor, a figure's), with what it holds (`own`) and its shapes'
// editor (`shapes`, shapes.js's):
// - studio, shapes, words ([its things' word, the shapes' word]: ["Object", "Shape"]), noun;
// - own: picks() (those chosen now), name(pick), box(pick) ([left, top, right, bottom] in the
//   shapes' units, as drawn), at(event) (the one chosen under the pointer, else null),
//   choose(picks) (those chosen, the shapes kept), alone() (one left alone chosen as one is),
//   remove(picks, cut), duplicate(picks) (the copies chosen), clip(), paste(clip) (what is
//   pasted chosen), accepts(clip) (a copy of its own kind), count(clip) (how many it holds),
//   all(), settled() (a promise: its edits have landed) -- each change one step or more;
// - page(), goTo(page), render(), crumb(), frame(), clipChosen(cut), clipItems(), undoNote(text,
//   options), away(what).

import { h, icon, ui, menu } from "/static/studio/studio.js";
import { alignTools } from "/static/studio/aligntools.js";
import * as M from "/static/studio/mixing.js";
import { chosenOrder, acrossOrder } from "/static/studio/ordering.js";

export function mixedChoice(ctx) {
  const { studio, shapes, own } = ctx;
  // (What they are called may hang on what is chosen: a slide's objects, or its figure's parts.)
  const wordsNow = () => (typeof ctx.words === "function" ? ctx.words() : ctx.words) || ["Object", "Shape"];
  // While a choice of both is made, or a change of both is on its way, neither kind's own
  // choosing takes the other's away.
  let joining = 0;
  let held = null;
  const ownNow = () => own.picks() || [];
  const shapesNow = () => shapes.chosen() || [];
  const on = () => ownNow().length > 0 && shapesNow().length > 0 && !shapes.typing?.();
  const counts = () => [ownNow().length, shapesNow().length];
  const name = () => M.mixedName(...counts(), wordsNow());
  const label = (verb) => M.mixedLabel(verb, ...counts(), wordsNow());
  function together(run) {
    joining += 1;
    try { return run(); } finally { joining -= 1; }
  }
  // Kept: what is chosen of the page's own, as both were last chosen (`picks`: as they will be,
  // once the page has them -- a figure's parts come back with its drawing): a drawing that
  // comes, those parts chosen again, takes the shapes away from them no more.
  const remember = (picks = ownNow()) => { held = picks.length && shapesNow().length ? M.choiceKey(picks) : null; };
  const holds = () => joining > 0 || (held !== null && held === M.choiceKey(ownNow()));
  // One kind left alone: chosen as that kind is chosen alone (one of the page's own, as one is).
  function settle(picks = undefined) {
    if (!shapesNow().length && ownNow().length === 1) own.alone();
    remember(picks);
    ctx.render();
  }

  // -- choosing --

  // ⇧-click (⌘-click) on a shape, the page's own chosen: it is put in, or taken out, they kept.
  function pressShape(event) {
    if (!(event.shiftKey || event.metaKey) || event.button !== 0 || shapes.armed?.() || shapes.at(event) === null) return false;
    if (!ownNow().length) return false;
    clicked(() => together(() => { own.choose(ownNow()); shapes.press(event); }));
    settle();
    return true;
  }
  // ⇧-click on one of the page's own, shapes chosen: it is put in, or taken out, they kept.
  function pickOwn(pick, same) {
    if (!pick || !shapesNow().length) return false;
    const picks = M.toggled(ownNow(), pick, same);
    clicked(() => together(() => { shapes.choose(shapesNow()); own.choose(picks); }));
    settle();
    return true;
  }
  // A band across the page: what it touches of both (with ⇧, those chosen as it began among them).
  function band(picks, indices) {
    if (!picks.length || !indices.length) return false;
    together(() => { own.choose(picks); shapes.choose(indices, { quiet: true }); });
    // (No click order: what it chose, in reading order, across both -- ordering.js.)
    across.banded(banding);
    ownSeen = ownKeys();
    remember();
    return true;
  }
  function clear() {
    held = null;
    shapes.clear({ quiet: true });
    own.choose([]);
    ctx.render();
  }
  function chooseAll() {
    const picks = own.all(), every = shapes.list().map((_, index) => index).filter((index) => shapes.list()[index]);
    together(() => { own.choose(picks); shapes.choose(every, { quiet: true }); });
    settle();
  }

  // -- changes of both, one step --

  // What is chosen before a change and after it, kept with its step: undone or redone, chosen again.
  const snapshot = () => ({ own: ownNow(), shapes: shapesNow() });
  function mark(entry, before, after) {
    if (entry) studio.said(entry).mixed = { page: ctx.page(), before, after };
  }
  // `steps`, each a change (or a promise of one), made in turn, then one step named `said`.
  // (`then`: once it is all done.)
  let busy = 0;
  function oneStep(said, steps, then = null) {
    const from = studio.past.length, before = snapshot();
    joining += 1;
    busy += 1;
    const done = () => {
      joining -= 1;
      busy -= 1;
      const entry = M.joinSteps(studio, from, said);
      mark(entry, before, snapshot());
      studio.emit?.("status");
      then?.();
      settle();
    };
    const run = (k) => {
      for (; k < steps.length; k += 1) {
        let out;
        try { out = steps[k](); } catch (error) { console.error(error); }
        if (out && typeof out.then === "function") return out.then(() => run(k + 1), () => run(k + 1));
      }
      const landed = own.settled?.();
      if (landed && typeof landed.then === "function") return landed.then(done, done);
      done();
      return null;
    };
    return run(0);
  }
  function remove(cut = false) {
    if (!on() || ctx.away?.(cut ? "cut objects" : "delete objects")) return false;
    const said = label(cut ? "Cut" : "Delete"), what = name().toLowerCase();
    // (The shapes first: a figure's part taken away puts the shapes on it where they were.)
    const picks = ownNow();
    oneStep(said, [() => shapes.remove(cut ? "cut" : "deleted"), () => own.remove(picks, cut)],
      () => ctx.undoNote?.(`${what.charAt(0).toUpperCase()}${what.slice(1)} ${cut ? "cut" : "deleted"}`, { icon: cut ? "cut" : "trash" }));
    return true;
  }
  function duplicate() {
    if (!on() || ctx.away?.("duplicate objects")) return false;
    const picks = ownNow();
    oneStep(label("Duplicate"), [() => shapes.duplicate(), () => own.duplicate(picks)]);
    return true;
  }
  // Flexo's own copy of both: each kind's, as it copies alone.
  const clip = () => (on() ? M.mixedClip([own.clip(), shapes.clip()], name().toLowerCase()) : null);
  // A copy of both pasted: each where it goes pasted alone, both chosen, one step. (Of one kind
  // the page takes -- a slide's objects pasted on a figure -- that kind, as it is pasted alone.)
  function paste(clipped) {
    const each = M.clipsOf(clipped);
    const mine = each.filter((one) => own.accepts(one)), drawn = each.filter((one) => one.what === "shapes" && Array.isArray(one.shapes) && one.shapes.length);
    if (!mine.length && !drawn.length) return false;
    if (!mine.length || !drawn.length) {
      for (const one of mine) own.paste(one);
      for (const one of drawn) shapes.paste(one);
      return true;
    }
    const count = [mine.reduce((sum, one) => sum + own.count(one), 0), drawn.reduce((sum, one) => sum + one.shapes.length, 0)];
    oneStep(M.mixedLabel("Paste", ...count, wordsNow()), [
      ...mine.map((one) => () => own.paste(one)),
      // (What was pasted of the page's own is kept chosen as the shapes are: mixed.)
      () => own.choose(ownNow()),
      ...drawn.map((one) => () => shapes.paste(one)),
    ]);
    return true;
  }
  // Undone or redone, both are chosen again, as they were before it or after.
  function restore(said, undone) {
    if (!said) return false;
    const picks = (undone ? said.before : said.after) || { own: [], shapes: [] };
    if (said.page !== undefined && said.page !== ctx.page()) ctx.goTo?.(said.page);
    together(() => {
      own.choose(picks.own || []);
      if ((picks.shapes || []).length) shapes.choose(picks.shapes, { quiet: true }); else shapes.clear({ quiet: true });
    });
    settle(picks.own || []);
    return true;
  }

  // -- Align and Distribute: the shapes, what the page holds among what they align to --

  // Each by a key of its own: a shape by its place, one of the page's own by "own:" and its pick.
  const OWN = "own:";
  const ownOf = (key) => JSON.parse(key.slice(OWN.length));
  const isOwn = (key) => typeof key === "string" && key.startsWith(OWN);
  // In the order they were chosen, one order across both kinds -- each shape's when, kept by the
  // shapes' editor, and the page's own here (ordering.js): what the page holds chosen before the
  // shapes were, first; a band's, in reading order.
  const ownKeys = () => ownNow().map((pick) => OWN + JSON.stringify(pick));
  const ownOrder = chosenOrder();
  let ownSeen = [], banding = null;
  const across = acrossOrder([
    { keys: ownKeys, stampOf: (key) => ownOrder.stampOf(key), stampAs: (key, when) => ownOrder.stampAs(key, when), box: (key) => own.box(ownOf(key)) },
    { keys: () => shapesNow(), stampOf: (index) => shapes.stampOf?.(index) ?? null, stampAs: (index, when) => shapes.stampAs?.(index, when), box: (index) => shapes.boxOf(index) },
  ]);
  // (A press: a band from it keeps, with ⇧ or ⌘, what is chosen as it is pressed.)
  window.addEventListener("pointerdown", (event) => { banding = { kept: new Set(event.shiftKey || event.metaKey ? [...ownKeys(), ...shapesNow()] : []), base: null }; }, true);
  // A click that puts one in (or takes one out): what the page holds chosen alone before, when
  // it was chosen; one it puts in, now.
  function clicked(run) {
    const was = on() ? ownSeen : (ownOrder.chose([], ownKeys()), ownKeys());
    const out = run();
    ownOrder.chose(was, ownKeys());
    ownSeen = ownKeys();
    return out;
  }
  const picksInOrder = () => across.ordered();
  // (What it moves: the shapes not locked -- one by its name.)
  const moved = () => { const moving = shapesNow().filter((index) => !shapes.lockedAt(index)); return moving.length === 1 ? shapes.nameOf(moving[0]) : M.counted(moving.length, wordsNow()[1]); };
  const arranging = alignTools({
    picks: () => (on() ? picksInOrder() : []),
    box: (key) => (isOwn(key) ? own.box(ownOf(key)) : shapes.boxOf(key)),
    // (The page's own stay where they are laid out: what the shapes align to, never moved --
    // but spread among, as fixed members of a Distribute.)
    locked: (key) => isOwn(key) || shapes.lockedAt(key),
    fixed: (key) => isOwn(key),
    few: () => `Choose three or more ${wordsNow()[1].toLowerCase()}s or ${wordsNow()[0].toLowerCase()}s`,
    name: (key) => (isOwn(key) ? own.name(ownOf(key)) : shapes.nameOf(key)),
    frame: () => ctx.frame(), noun: ctx.noun || "page",
    move: (list, key, dx, dy) => { if (!isOwn(key)) shapes.moveIn(list, key, dx, dy); },
    // Named for the shapes it moves: "Align 2 Shapes Left".
    edit: (mutate, said) => shapes.change(mutate, said.replace(/^(\w+) (\d+ Shapes|\S+)/, (_, verb) => `${verb} ${moved()}`)),
    renderInspector: () => ctx.render(), showPanel: () => ctx.showPanel?.(),
    // (Arrange in a Grid…'s sheet: the shapes drawn where they would go.)
    show: (moves) => shapes.showMoves?.(moves),
  });

  // -- what may be done with both, by name --

  function commands() {
    if (!on()) return [];
    const called = name();
    return [
      { icon: "duplicate", label: `Duplicate ${called}`, also: ["Duplicate"], keys: "⌘D", run: () => duplicate() },
      { icon: "trash", label: `Delete ${called}`, keys: "⌫", run: () => remove() },
      ...arranging.commands(called),
    ];
  }
  // The shapes' own commands, while both are chosen: none that would take or copy the shapes
  // alone (Delete, Duplicate), nor Align and Distribute for them alone.
  function shapeCommands(list) {
    if (!on()) return list;
    const mine = new Set(commands().map((command) => command.label));
    return list.filter((command) => !mine.has(command.label) && !/^(Delete|Duplicate|Cut|Copy) /.test(command.label) && !(command.also || []).includes("Duplicate"));
  }
  function menuItems() {
    const called = name();
    return [
      ...(ctx.clipItems?.() || []),
      { icon: "duplicate", label: `Duplicate ${called}`, keys: "⌘D", run: () => duplicate() },
      "-",
      ...["Align Left", "Align Centre", "Align Right", "Align Top", "Align Middle", "Align Bottom"].map((words) => arranging.commands(called).find((command) => command.label === words)).filter(Boolean),
      arranging.menuItem(called),
      "-",
      { icon: "trash", label: `Delete ${called}`, keys: "⌫", danger: true, run: () => remove() },
    ].filter(Boolean);
  }
  // A right-click on one of them: their menu, both kept.
  function context(event) {
    if (!on()) return false;
    const shape = shapes.at(event);
    const mine = shape !== null ? shapesNow().includes(shape) : own.at(event) !== null;
    if (!mine) return false;
    event.preventDefault?.();
    menu({ x: event.clientX, y: event.clientY }, menuItems());
    return true;
  }

  // -- the keys --

  function key(event) {
    if (!on()) return false;
    const mod = event.metaKey || event.ctrlKey, k = event.key;
    if (!mod && !event.altKey && (k === "Backspace" || k === "Delete")) { remove(); return true; }
    if (mod && !event.altKey && !event.shiftKey && k.toLowerCase() === "d") { duplicate(); return true; }
    if (mod && !event.altKey && !event.shiftKey && k.toLowerCase() === "a") { chooseAll(); return true; }
    if (mod && event.shiftKey && !event.altKey && k.toLowerCase() === "a") { arranging.reveal(); return true; }
    if (!mod && k === "Escape") { clear(); return true; }
    // (The arrows nudge the shapes: the page's own are laid out, never nudged.)
    if (!mod && k.startsWith("Arrow")) return shapes.key(event);
    // (Return and the letters type in one shape chosen alone, never in several things.)
    if (!mod && !event.altKey && (k === "Enter" || [...k].length === 1)) return true;
    return false;
  }

  // -- the inspector --

  function panel() {
    const names = [...ownNow().map((pick) => own.name(pick)), ...shapesNow().map((index) => shapes.nameOf(index))];
    return [
      h("div.section.block-top.mixed-top", {},
        h("div.crumbs", {}, h("button.crumb", { type: "button", onclick: () => clear() }, ctx.crumb())),
        h("div.insp-title", {}, icon("layout"), h("div.insp-words", {}, h("div.insp-name", {}, `${name()} Selected`),
          h("div.insp-hint", {}, names.join(", ")))),
        h("div.row", {},
          ui.button("Cut", () => ctx.clipChosen?.(true), { small: true, icon: "cut", title: "Cut (⌘X)" }),
          ui.button("Copy", () => ctx.clipChosen?.(false), { small: true, icon: "copy", title: "Copy (⌘C)" })),
        h("div.row", {},
          ui.button("Duplicate", () => duplicate(), { small: true, icon: "duplicate", title: "Duplicate (⌘D)" }),
          ui.button("Delete", () => remove(), { small: true, icon: "trash", kind: "danger", title: "Delete (⌫)" })),
        h("div.hint-line", {}, `The arrows move the ${wordsNow()[1].toLowerCase()}s; the ${wordsNow()[0].toLowerCase()}s stay where they are laid out.`)),
      arranging.section(),
    ].filter(Boolean);
  }

  return {
    on, name, label, together, joining: () => joining > 0, holds, remember,
    pressShape, pickOwn, band, clear, chooseAll,
    remove, duplicate, clip, paste, restore,
    commands, shapeCommands, menuItems, context, key, panel,
    align: (side) => arranging.align(side),
  };
}
