// A structure's colours, as rows (flexo.structure_colours): what each row colours -- a chain,
// a residue, a ligand, or a selection such as resi 10-24 -- typed, or chosen from what the
// molecule has: its subunits, its chains by name, its secondary structure and its ligands
// (structurepick.js); and its colour, in a well or by a tone's name. A later row wins over
// an earlier one, so a row is dragged up or down by its grip (or moved with ↑ and ↓ from it).
// What each row colours is asked of the studio: how many residues, said in its tooltip, and
// why one colours nothing, said under the rows. A dozen rows show at once; more scroll in
// their own list.
import { h, clear, icon, ui } from "/static/studio/studio.js";
import { parseColour, rememberColour } from "/static/studio/hexcolour.js";
import { pickItems, openPick } from "/static/kinds/figure/structurepick.js";

const COLOURS = ["#e69f00", "#56b4e9", "#009e73", "#f0e442", "#0072b2", "#d55e00", "#cc79a7"];
// What each structure file was last said to have, by its source: its menu opens at once from
// it while what the studio says now is on its way (a ribosome's takes a while).
const lastKnown = new Map();

const SHEET = "/static/kinds/figure/structurecolours.css";
// (Asked for once, as the first rows are drawn.)
function styled() {
  if (!document.querySelector(`link[href="${SHEET}"]`)) document.head.append(h("link", { rel: "stylesheet", href: SHEET }));
}

// `typedField` and `paced` are the inspector's own (parts.js): words sent once they are
// whole, a colour dragged in the system's picker sent as it goes.
export function structureColours({ field, value, set, key, settings, typedField, paced, source }) {
  styled();
  let settled = null;
  settings.then((known) => { settled = known; if (known && source) lastKnown.set(source, known); });
  const rows = value.map((row) => ({ ...(row && typeof row === "object" ? row : {}) }));
  const write = () => set(rows.map((row) => Object.fromEntries(Object.entries(row).filter(([, v]) => v !== "" && v !== null && v !== undefined))));
  const tones = field.columns.find((column) => column.name === "color")?.options || [];
  const placeholder = field.columns.find((column) => column.name === "group")?.hint || "";
  const list = h("div.mol-colour-rows.scroll-thin", { role: "list" });
  const warnings = h("div.records-warnings");
  const cellKey = (index, name) => `${key}:${index}:${name}`;

  // Moved, the row keeps the keys: its grip is focused again once the panel is drawn anew.
  const focusSoon = (target, tries = 0) => {
    const control = document.querySelector(`[data-key="${CSS.escape(target)}"]`);
    if (control) { control.focus(); control.scrollIntoView?.({ block: "nearest" }); } else if (tries < 20) setTimeout(() => focusSoon(target, tries + 1), 50);
  };
  const move = (from, to) => {
    if (to === from || to < 0 || to >= rows.length) return false;
    rows.splice(to, 0, rows.splice(from, 1)[0]);
    write();
    return true;
  };

  function rowOf(row, index) {
    const grip = h("button.mol-colour-grip", { type: "button", title: "Move", "aria-label": `Move Row ${index + 1}`, "data-key": cellKey(index, "grip") }, icon("grip"));
    grip.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
      event.preventDefault();
      const to = index + (event.key === "ArrowUp" ? -1 : 1);
      if (move(index, to)) setTimeout(() => focusSoon(cellKey(to, "grip")), 0);
    });
    grip.addEventListener("pointerdown", (event) => drag(event, index));

    const group = typedField({ value: row.group, key: cellKey(index, "group"), placeholder, mono: true, onCommit: (text) => { row.group = text; write(); } });
    const pick = h("button.cell-pick", { type: "button", tabIndex: -1, title: "Choose", "aria-label": "Choose What Row Colours" }, icon("chevron-down"));
    pick.addEventListener("click", async () => {
      const known = settled || (source && lastKnown.get(source)) || await settings;
      // (Chosen as if typed and Return pressed: words still on their way are not sent after.)
      const choose = (text) => () => {
        group.value = text;
        group.dispatchEvent(new Event("input"));
        group.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
      };
      openPick(pick, pickItems(known, choose));
    });

    const hex = /^#[0-9a-f]{6}$/i.test(row.color || "") ? row.color : null;
    const well = h("input.cell-well", { type: "color", value: hex || "#888888", title: "Choose a Colour", tabIndex: -1 });
    if (!hex) well.classList.add("unset");
    const colour = typedField({ value: row.color, key: cellKey(index, "color"), mono: true, onCommit: (text) => { row.color = text; write(); } });
    well.addEventListener("input", () => { well.classList.remove("unset"); colour.value = well.value; paced(cellKey(index, "color"), () => { row.color = well.value; write(); }); });
    // A colour's code pasted (rgb(31, 119, 180), #17b) is written as #rrggbb; a tone's name
    // as it is.
    colour.addEventListener("paste", (event) => {
      const text = event.clipboardData?.getData("text/plain") ?? "", read = /^\s*[a-z]+\s*$/i.test(text) ? null : parseColour(text);
      if (!read) return;
      event.preventDefault();
      colour.value = read.hex;
      well.value = read.hex;
      well.classList.remove("unset");
      rememberColour(read.hex);
      row.color = read.hex;
      write();
    });
    const toneList = `tones-${Math.random().toString(36).slice(2)}`;
    colour.setAttribute("list", toneList);

    const remove = ui.button("", () => { rows.splice(index, 1); write(); }, { kind: "ghost", small: true, icon: "close", title: "Delete Row" });
    return h("div.mol-colour-row", { role: "listitem", "data-row": String(index) },
      grip,
      h("div.mol-colour-what", {}, group, pick),
      h("div.mol-colour-paint", {}, well, colour, h("datalist", { id: toneList }, tones.map((tone) => h("option", { value: tone })))),
      remove);
  }

  // A row dragged by its grip: it follows the pointer, the rows it passes stepping out of its
  // way, and is put where it is let go (Esc, or no move, puts it back). Only transforms
  // change meanwhile: nothing is laid out, nothing written, till it lands.
  function drag(event, index) {
    if (event.button !== 0 || rows.length < 2) return;
    const shown = [...list.children];
    const moving = shown[index];
    const pitch = shown.length > 1 ? shown[1].offsetTop - shown[0].offsetTop : moving.offsetHeight;
    const startY = event.clientY;
    let to = index, started = false;
    const grip = event.currentTarget;
    grip.setPointerCapture?.(event.pointerId);
    const place = (y) => {
      const offset = y - startY;
      if (!started && Math.abs(offset) < 3) return;
      if (!started) { started = true; moving.classList.add("lifted"); list.classList.add("sorting"); }
      to = Math.max(0, Math.min(rows.length - 1, index + Math.round(offset / pitch)));
      moving.style.transform = `translateY(${offset}px)`;
      shown.forEach((other, at) => {
        if (at === index) return;
        const shift = at > index && at <= to ? -pitch : at < index && at >= to ? pitch : 0;
        other.style.transform = shift ? `translateY(${shift}px)` : "";
      });
    };
    const settle = () => { shown.forEach((other) => { other.style.transform = ""; }); moving.classList.remove("lifted"); list.classList.remove("sorting"); };
    const up = (done) => {
      grip.removeEventListener("pointermove", onMove);
      grip.removeEventListener("pointerup", onUp);
      grip.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("keydown", onKey, true);
      settle();
      if (done && started) move(index, to);
    };
    const onMove = (next) => place(next.clientY);
    const onUp = () => up(true);
    const onCancel = () => up(false);
    const onKey = (key) => { if (key.key === "Escape") { key.preventDefault(); key.stopPropagation(); up(false); } };
    grip.addEventListener("pointermove", onMove);
    grip.addEventListener("pointerup", onUp);
    grip.addEventListener("pointercancel", onCancel);
    window.addEventListener("keydown", onKey, true);
  }

  rows.forEach((row, index) => list.append(rowOf(row, index)));

  // What each row colours, once the studio says: a count in its tooltip, and a row that
  // colours nothing marked, and said under the rows.
  settings.then((known) => {
    const groups = known?.colours?.groups || {};
    const said = [];
    rows.forEach((row, index) => {
      const text = String(row.group ?? "").trim();
      const input = list.querySelector(`[data-key="${CSS.escape(cellKey(index, "group"))}"]`);
      const found = groups[text];
      if (!text) { said.push(`Row ${index + 1} colours nothing yet.`); return; }
      if (!found || !input) return;
      input.classList.toggle("invalid", Boolean(found.problem));
      input.title = found.problem ? found.problem : `${found.residues} residue${found.residues === 1 ? "" : "s"}`;
      if (found.problem) said.push(`Row ${index + 1}: ${found.problem}${found.hint ? ` ${found.hint}` : ""}`);
    });
    clear(warnings, said.map((text) => h("div.field-problem.warning", {}, icon("warning"), h("span", {}, text))));
  });

  const add = ui.button("Add Row", async () => {
    // A new row colours a chain no row names yet (else the first), in a colour none has.
    const known = await settings;
    const chains = known?.chains || [];
    const named = new Set(rows.map((row) => String(row.group ?? "")));
    const taken = new Set(rows.map((row) => String(row.color ?? "").toLowerCase()));
    rows.push({ group: chains.find((chain) => !named.has(chain)) ?? chains[0] ?? "", color: COLOURS.find((each) => !taken.has(each)) || COLOURS[0] });
    write();
    setTimeout(() => focusSoon(cellKey(rows.length - 1, "group")), 0);
  }, { small: true, icon: "plus" });

  return h("div.field.records.mol-colour-list", {},
    h("label.label", { title: field.hint || "" }, field.label, h("span.hint", {}, `${rows.length}`)),
    rows.length ? list : null,
    warnings,
    add);
}
