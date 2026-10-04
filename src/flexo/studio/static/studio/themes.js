// Themes, chosen by sight: a card for each (its page, its type, its colours), the
// folder's theme files first and flexo's own after, and a theme file put to use in
// the folder's figures and decks at once.

import { h, clear, icon, ui, popover, closeMenu, toast } from "./ui.js";

// A theme's name as a person reads it: flexo's own are named by id ("paper" is Paper);
// a theme file's name is as its file gives it.
const NAMES = { tikz: "TikZ", midcentury: "Mid-Century" };
export function themeName(card) {
  const name = String(card.title || card.value || "");
  if (card.source === "folder" || /\.(ya?ml|json)$/i.test(name)) return name;
  return NAMES[name] || name.replace(/[_-]+/g, " ").replace(/(^|\s)([a-z])/g, (_, before, letter) => before + letter.toUpperCase());
}

// A document's name as the studio shows it: without the extension of its file.
// (A theme file's ".theme" too: "Order queue.theme.yaml" is "Order queue".)
const docName = (file) => String(file).split("/").pop().replace(/(\.theme)?\.(ya?ml|json)$/i, "");

export function themeCard(card, { on = false, onclick, compact = false, chevron = false } = {}) {
  // The theme's own colours as filled chips, as a palette's colours are shown (else each
  // tone's strong colour): each colour once, so a theme in one ink (Print, Swiss) shows one
  // chip, not six alike.
  const colours = [...new Set((card.colours?.length ? card.colours : (card.tones || []).map((tone) => tone.stroke || tone.fill)).map((colour) => String(colour).toLowerCase()))];
  const tones = colours.map((colour) => h("span", { style: { background: colour } }));
  return h(`button.theme-card${on ? ".on" : ""}${compact ? ".compact" : ""}${card.problem ? ".problem" : ""}`, {
    type: "button", title: card.problem || [card.description || themeName(card), card.source === "folder" ? card.value : ""].filter(Boolean).join("\n"), onclick,
  },
    h("span.theme-page", { style: { background: card.canvas || "#fff", color: card.ink || "#222" } },
      h("span.theme-aa", { style: { fontFamily: card.font ? `"${card.font}", system-ui` : "" } }, "Aa"),
      h("span.theme-tones", {}, tones)),
    h("span.theme-words", {},
      h("span.theme-name", {}, themeName(card)),
      // A folder's theme says its file only when that is not its name already.
      card.problem ? h("span.theme-where.bad", {}, "Can't be read") : card.source === "folder" && docName(card.value) !== themeName(card) ? h("span.theme-where", {}, docName(card.value)) : null),
    chevron ? h("span.theme-chevron", {}, icon("chevron-down")) : null);
}

// The themes a document may use, asked of the studio; kept a moment, as a picker opens
// and closes often and a theme file changes rarely.
const known = new Map();
export async function themesFor(session, { fresh = false } = {}) {
  const key = session.file;
  const kept = known.get(key);
  if (!fresh && kept && Date.now() - kept.at < 4000) return kept.cards;
  const cards = (await session.api(session.url("/api/themes"))).themes;
  known.set(key, { at: Date.now(), cards });
  return cards;
}

// A field: the theme in use, as a card with a chevron in it, like a pop-up button;
// choosing it opens every theme to pick from. `onPick(value)` gets null for the
// fallback (the kind's own default).
export function themeField(session, { value, fallback = "paper", onPick, onCustomise } = {}) {
  const current = value || fallback;
  const holder = h("div.theme-field", {}, themeCard({ title: current, value: current }, { compact: true, chevron: true }));
  const pick = (card) => { closeMenu(); if (card.value !== current) onPick?.(card.value === fallback ? null : card.value); };
  const open = async (anchor) => {
    const cards = await themesFor(session, { fresh: true });
    const folder = cards.filter((card) => card.source === "folder");
    const grid = (list) => h("div.theme-grid", {}, list.map((card) => themeCard(card, { on: card.value === current, onclick: () => pick(card) })));
    popover(anchor, h("div.theme-picker", {},
      h("div.menu-title", {}, "In This Folder"),
      folder.length ? grid(folder) : h("div.hint-line", {}, "No theme files in this folder. ", onCustomise ? "Click Customise to make one from the current theme." : ""),
      h("div.menu-title", {}, "Built-In"),
      grid(cards.filter((card) => card.source === "built-in")),
      onCustomise ? h("div.row", {}, ui.button("Customise…", () => { closeMenu(); onCustomise(current); }, { small: true, icon: "pencil", title: "Create a theme file from this theme to edit its colours, fonts and lines" })) : null),
    { className: "theme-menu" });
  };
  themesFor(session).then((cards) => {
    const card = cards.find((item) => item.value === current) || { title: current, value: current };
    clear(holder, themeCard(card, { compact: true, chevron: true, onclick: (event) => open(event.currentTarget) }));
  }).catch(() => {});
  return holder;
}

// For a theme file's page: the figures and decks in the folder, which of them use it,
// and a button to use it in any or all of them.
export function themeUses(session) {
  const holder = h("div.theme-uses", {}, h("div.hint-line", {}, "Loading…"));
  const render = (documents) => {
    // A document that does not read is listed, said to be so, and offered nothing to do:
    // opened, it says why (and on which line).
    const others = documents.filter((entry) => !entry.uses && !entry.unread);
    const use = async (targets) => {
      try {
        const result = await session.api("/api/theme/use", { file: session.file, targets });
        render(result.documents);
        toast(targets.length === 1 ? `“${docName(targets[0])}” now uses this theme` : `${targets.length} documents now use this theme`, { icon: "theme", seconds: 3 });
      } catch (error) {
        toast(`Could not change the theme: ${error.message}`, { kind: "error", icon: "error", seconds: 6 });
      }
    };
    // Said as it would be said: Both of two, All of more -- the Other ones when some use it already.
    const useAll = (count, of) => (count < of ? `Use in the Other ${count} Documents` : count === 2 ? "Use in Both Documents" : `Use in All ${count} Documents`);
    clear(holder,
      documents.length ? h("div.theme-use-list", {}, documents.map((entry) => h("div.theme-use", {},
        icon(entry.kind === "deck" ? "deck" : "figure"),
        h("button.theme-use-name", { type: "button", title: `Open ${entry.file}`, onclick: () => session.workspace.open(entry.file) }, docName(entry.file)),
        entry.uses ? h("span.chip-on", {}, icon("check"), "In Use")
          : entry.unread ? h("span.hint-line", { title: `Open ${entry.file} to see why and put it right` }, "Can't be read")
          : ui.button("Use", () => use([entry.file]), { small: true, title: `Use this theme in “${docName(entry.file)}” (now ${entry.theme || "the default theme"})` }))))
        : h("div.hint-line", {}, "No figures or decks in this folder yet."),
      others.length > 1 ? h("div.row", {}, ui.button(useAll(others.length, documents.filter((entry) => !entry.unread).length), () => use(others.map((entry) => entry.file)), { small: true, icon: "theme" })) : null);
  };
  session.api(session.url("/api/theme/uses")).then((result) => render(result.documents))
    .catch((error) => clear(holder, h("div.hint-line", {}, `Could not list documents: ${error.message}`)));
  return holder;
}
