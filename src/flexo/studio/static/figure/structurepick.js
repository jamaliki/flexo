// What a row of a structure's colours colours, chosen from what the molecule has
// (flexo.structure_colours.choices): its subunits -- a ribosome's large and small -- where it
// has more than one; its entities of more than one chain; each chain by the name of what it
// is, its chain's name beside it (28S rRNA, L5); its secondary structure; and its ligands. A
// long list -- a ribosome's eighty chains -- opens with a field that finds a choice by its
// name or its chain's, Return taking the first found: a chain named as typed, in its case,
// first.
import { h, clear, menu, popover, closeMenu } from "/static/studio/studio.js";

// What the molecule's own secondary structure is selected by.
const SECONDARY = [["Helices", "ss H"], ["Strands", "ss E"], ["Loops", "ss L and polymer"]];
// More choices than this, and the list opens with a field to search it.
const LONG = 24;

const counted = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;
const listed = (chains) => (chains.length > 3 ? counted(chains.length, "chain") : chains.join(", "));

// The menu's items, as menu() takes them: titles, lines between, and choices that each
// `choose` (text) a row's words -- a chain, subunit:L, entity:2, a selection.
export function pickItems(known, choose) {
  const offered = known?.colours?.choices || {};
  const chains = offered.chains || (known?.chains || []).map((chain) => ({ chain, name: "" }));
  const ligands = known?.colours?.ligands || [];
  const sections = [];
  if (offered.subunits?.length) {
    sections.push([{ title: "Subunits" }, ...offered.subunits.map((each) => ({ label: each.label, hint: `${each.group}: ${counted(each.chains, "chain")}`, run: choose(each.group) }))]);
  }
  if (offered.entities?.length) {
    sections.push([{ title: "Entities" }, ...offered.entities.map((each) => ({ label: each.label, keys: listed(each.chains), hint: `${each.group}: ${each.chains.join(", ")}`, run: choose(each.group) }))]);
  }
  sections.push([{ title: "Chains" }, ...(chains.length ? chains.map(({ chain, name }) => (name
    ? { label: name, keys: chain, hint: `Chain ${chain}: ${name}`, chain, run: choose(chain) }
    : { label: `Chain ${chain}`, chain, run: choose(chain) }))
    : [{ label: "No chains found", disabled: true }])]);
  sections.push([{ title: "Secondary Structure" }, ...SECONDARY.map(([label, text]) => ({ label, hint: text, run: choose(text) }))]);
  if (ligands.length) {
    sections.push([{ title: "Ligands" }, { label: "Every Ligand", hint: "hetatm and not water", run: choose("hetatm and not water") },
      ...ligands.map((ligand) => ({ label: ligand.label, run: choose(ligand.group) }))]);
  }
  return sections.flatMap((section, index) => (index ? ["-", ...section] : section));
}

// The menu under `anchor`: as any menu, or -- long -- with its search field.
export function openPick(anchor, items) {
  if (items.filter((item) => item.run).length <= LONG) return menu(anchor, items, { className: "mol-pick-menu" });
  const search = h("input.input.font-search", { type: "search", placeholder: "Search", spellcheck: false, "aria-label": "Search Choices" });
  const list = h("div.font-list", { role: "menu" });
  const row = (item) => h("button.menu-item", { type: "button", role: "menuitem", title: item.hint || "", disabled: Boolean(item.disabled),
    onclick: () => { closeMenu(); item.run?.(); } },
  h("span.menu-text", {}, h("span", {}, item.label)), item.keys ? h("span.kbd", {}, item.keys) : null);
  let first = null;
  const render = () => {
    const typed = search.value.trim(), query = typed.toLowerCase();
    if (!query) {
      first = null;
      clear(list, items.map((item) => (item === "-" ? h("div.menu-sep") : item.title ? h("div.menu-title", {}, item.title) : row(item))));
      return;
    }
    // Each section's choices found, under its title: a chain named as typed (Le, not LE) first.
    const found = [];
    let title = null;
    for (const item of items) {
      if (item === "-") continue;
      if (item.title) { title = { title: item.title, items: [] }; found.push(title); continue; }
      if (!item.run || ![item.label, item.keys, item.chain, item.hint].some((text) => String(text || "").toLowerCase().includes(query))) continue;
      if (item.chain === typed) title.items.unshift(item); else title.items.push(item);
    }
    const shown = found.filter((section) => section.items.length);
    first = shown.flatMap((section) => section.items).find((item) => item.chain === typed) || shown[0]?.items[0] || null;
    clear(list, shown.length
      ? shown.map((section) => [h("div.menu-title", {}, section.title), section.items.map(row)])
      : h("button.menu-item", { type: "button", disabled: true }, h("span.menu-text", {}, h("span", {}, "No Matches"))));
  };
  search.addEventListener("input", render);
  search.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.isComposing) return;
    event.preventDefault();
    if (!first) return;
    closeMenu();
    first.run();
  });
  render();
  // The search field has the keys: ↓ goes into the list.
  return popover(anchor, [search, list], { className: "font-menu.mol-pick-menu" });
}
