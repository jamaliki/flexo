// A bundle (one .flexo file holding a document and every file it names) in the studio's
// window: the window and its document's tab named for the bundle, what the bundle was made
// without and what happens to it (saved on another computer and taken in, a copy a cloud
// service made of it merged, moved, not writable) said as it happens; and, for every deck
// and figure, Save as Bundle… (in the palette, the Mac app's File menu and the Export
// menus), and in a bundle's window Unpack Bundle…, which writes it out as a plain folder.
// The bundle is kept in step by the studio (flexo.studio.bundles): nothing here writes it.

import { h, toast } from "./ui.js";

let shown = null; // the bundle this window edits: { name, stem, document, ... }

// What a document is called in this window: the bundle's own name for the bundle's document
// ("talk" for talk.flexo, whatever its deck's file is called); else nothing (its file's).
export function bundleName(file) {
  return shown && file === shown.document ? shown.stem : null;
}

const asks = () => Boolean(window.pywebview?.api?.save_export);

// The entry each deck and figure gets in its Export menu (and the Mac app's File › Export To).
const ENTRY = {
  format: "flexo",
  get label() { return `Flexo Bundle${asks() ? "…" : ""}`; },
  hint: "This document and every file it names, as one file to send",
  icon: "export",
};

export function bundles(workspace) {
  shown = workspace.info.bundle || null;
  if (shown) {
    retitle(workspace);
    workspace.on("active", () => retitle(workspace));
    const left = shown.left || [];
    if (left.length) {
      const names = left.slice(0, 4).map((item) => item.name).join(", ") + (left.length > 4 ? ` and ${left.length - 4} more` : "");
      toast(`${shown.name} was made without ${names}: ${left.length === 1 ? "it was" : "they were"} not in its folder.`, { icon: "info", seconds: 10 });
    }
    if (shown.conflict) {
      toast(`Changes made here that never reached ${shown.name} before it changed on another computer are in “${shown.conflict}”, beside it.`, { icon: "info", seconds: 14 });
    }
    // What became of the copies a cloud service made beside it, as it opened.
    for (const said of shown.notices || []) toast(said, { icon: "info", seconds: 12 });
  }
  workspace.on("bundle", (event) => {
    const was = shown;
    shown = { ...(shown || {}), ...event };
    workspace.info.bundle = shown;
    if (event.problem && event.problem !== was?.problem) toast(event.problem, { kind: "error", icon: "error", seconds: 8 });
    if (event.taken?.length) toast(`${shown.name} was saved on another computer: its changes are taken in.`, { icon: "info", seconds: 6 });
    if (event.renamed) toast(`The bundle is now “${event.renamed}”.`, { icon: "info" });
    for (const said of event.notices || []) toast(said, { icon: "info", seconds: 12 });
    retitle(workspace);
    workspace.emit("status", workspace.active);
  });
  workspace.on("opened", (session) => {
    if (session.kind !== "deck" && session.kind !== "figure") return;
    if (!session.exports.some((item) => item.format === ENTRY.format)) session.exports.push(ENTRY);
    // Its kind's commands, and these: run by name from the palette and the Mac app's menus.
    const own = session.commands;
    session.commands = () => [...own(), ...commands(workspace, session)];
  });
}

function commands(workspace, session) {
  return [
    { icon: "export", label: "Save as Bundle…", hint: "This document and every file it names, as one .flexo file to send",
      run: () => session.exportFiles([ENTRY.format]) },
    ...(shown ? [{ icon: "folder", label: "Unpack Bundle…", hint: `${shown.name}, written out as a plain folder`, run: () => unpack(workspace) }] : []),
  ];
}

// The window's title: the bundle's name for its document, and beside any other in it.
function retitle(workspace) {
  if (!shown) return;
  const file = workspace.active?.file;
  if (!file || file === shown.document) document.title = `${shown.name} — Flexo Studio`;
  else document.title = `${String(file).split("/").pop().replace(/(\.theme)?\.(ya?ml|json)$/i, "")} — ${shown.name}`;
}

async function unpack(workspace) {
  const app = window.pywebview?.api;
  try {
    // In the Mac app, where it goes is asked; in a browser, it goes beside the bundle.
    const made = app?.unpack_bundle ? await app.unpack_bundle() : await workspace.api("/api/bundle/unpack", {});
    if (made?.error) throw new Error(made.error);
    if (!made?.folder) return;
    const name = made.folder.split("/").pop();
    const open = app?.open_path ? h("a", { href: "#", onclick: (event) => { event.preventDefault(); app.open_path(made.folder); } }, "Open") : null;
    toast(h("span.row", {}, `Unpacked into “${name}”`, open), { icon: "check", seconds: open ? 10 : 6 });
  } catch (error) {
    toast(`Couldn’t unpack the bundle: ${error.message}`, { kind: "error", icon: "error", seconds: 8 });
  }
}
