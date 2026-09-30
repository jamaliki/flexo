// Themes, chosen by sight: a card for each (its page, its type, its colours), the
// folder's theme files first and flexo's own after, and a theme file put to use in
// the folder's figures and decks at once.

import { h, clear, icon, ui, popover, closeMenu, toast } from "./ui.js";

export function themeCard(card, { on = false, onclick, compact = false } = {}) {
  const tones = (card.tones || []).map((tone) => h("span", { style: { background: tone.fill, borderColor: tone.stroke } }));
  return h(`button.theme-card${on ? ".on" : ""}${compact ? ".compact" : ""}${card.problem ? ".problem" : ""}`, {
    type: "button", title: card.problem || card.description || card.title, onclick,
  },
    h("span.theme-page", { style: { background: card.canvas || "#fff", color: card.ink || "#222" } },
      h("span.theme-aa", { style: { fontFamily: card.font ? `"${card.font}", system-ui` : "" } }, "Aa"),
      h("span.theme-tones", {}, tones)),
    h("span.theme-words", {},
      h("span.theme-name", {}, card.title || card.value),
      card.problem ? h("span.theme-where.bad", {}, "Does not read") : card.source === "folder" ? h("span.theme-where", {}, card.value) : null));
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

// A field: the theme in use, as a card; choosing it opens every theme to pick from.
// `onPick(value)` gets null for the fallback (the kind's own default).
export function themeField(session, { value, fallback = "paper", onPick, onCustomise } = {}) {
  const current = value || fallback;
  const holder = h("div.theme-field", {}, themeCard({ title: current, value: current }, { compact: true }));
  const pick = (card) => { closeMenu(); if (card.value !== current) onPick?.(card.value === fallback ? null : card.value); };
  const open = async (anchor) => {
    const cards = await themesFor(session, { fresh: true });
    const folder = cards.filter((card) => card.source === "folder");
    const grid = (list) => h("div.theme-grid", {}, list.map((card) => themeCard(card, { on: card.value === current, onclick: () => pick(card) })));
    popover(anchor, h("div.theme-picker", {},
      h("div.menu-title", {}, "In this folder"),
      folder.length ? grid(folder) : h("div.hint-line", {}, "No theme files here yet. ", onCustomise ? "Customise makes one from the theme in use." : ""),
      h("div.menu-title", {}, "Built in"),
      grid(cards.filter((card) => card.source === "built-in")),
      onCustomise ? h("div.row", {}, ui.button("Customise…", () => { closeMenu(); onCustomise(current); }, { small: true, icon: "pencil", title: "Make a theme file from this theme, to change its colours, type and lines" })) : null),
    { className: "theme-menu" });
  };
  themesFor(session).then((cards) => {
    const card = cards.find((item) => item.value === current) || { title: current, value: current };
    clear(holder, themeCard(card, { compact: true, onclick: (event) => open(event.currentTarget) }),
      ui.button("", (event) => open(event.currentTarget.previousSibling), { kind: "ghost", small: true, icon: "chevron", title: "Choose another theme" }));
  }).catch(() => {});
  return holder;
}

// For a theme file's page: the figures and decks in the folder, which of them use it,
// and a button to use it in any or all of them.
export function themeUses(session) {
  const holder = h("div.theme-uses", {}, h("div.hint-line", {}, "Looking for figures and decks…"));
  const render = (documents) => {
    const others = documents.filter((entry) => !entry.uses);
    const use = async (targets) => {
      try {
        const result = await session.api("/api/theme/use", { file: session.file, targets });
        render(result.documents);
        toast(`${targets.length === 1 ? targets[0].split("/").pop() : `${targets.length} documents`} now in this theme`, { icon: "theme", seconds: 3 });
      } catch (error) {
        toast(`Could not change the theme: ${error.message}`, { kind: "error", icon: "error", seconds: 6 });
      }
    };
    clear(holder,
      documents.length ? h("div.line-list", {}, documents.map((entry) => h("div.line-row.theme-use", {},
        icon(entry.kind === "deck" ? "slide" : "figure"),
        h("button.link", { type: "button", title: `Open ${entry.file}`, onclick: () => session.workspace.open(entry.file) }, entry.file),
        entry.uses ? h("span.chip-on", {}, icon("check"), "Uses it")
          : ui.button("Use", () => use([entry.file]), { small: true, title: entry.theme ? `Now: ${entry.theme}` : "Now: the default theme" }))))
        : h("div.hint-line", {}, "No figures or decks in this folder yet."),
      others.length > 1 ? h("div.row", {}, ui.button(`Use in all ${others.length}`, () => use(others.map((entry) => entry.file)), { small: true, icon: "theme" })) : null);
  };
  session.api(session.url("/api/theme/uses")).then((result) => render(result.documents))
    .catch((error) => clear(holder, h("div.hint-line", {}, `Could not list them: ${error.message}`)));
  return holder;
}
