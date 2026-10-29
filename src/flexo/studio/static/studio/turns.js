// An agent's turn, as its row of the activity, and undone from there (flexo/studio/turns.py).
//
// The edits an agent makes for one request -- Claude Code's, the assistant's -- are one row,
// named as the agent named them ("Claude: Add a results slide"), what they did under it
// ("added slide 5 · edited the title on slide 4"), where, when, and Undo. Undo takes the whole
// turn back as this person's own change, one step in their history ("Undo “Claude: Add a
// results slide”"), on the document as it is now: each run of the agent's edits taken back
// with merge.js's replay, the last first, so what anyone did since -- or between the agent's
// edits -- stays as they have it. ⌘Z then makes the turn again, and ⇧⌘Z takes it back again:
// the row says which, for everyone.

import { h, ui, toast, inQuotes } from "./ui.js";
import { replay, same } from "./merge.js";

// A turn's name, as its row and its undo say it: "Claude: Add a results slide" -- or, unnamed,
// what it did ("Claude edited slide 4").
export function turnName(entry, nameOf) {
  const who = nameOf(entry.who);
  return entry.turn?.named ? `${who}: ${entry.text}` : `${who} ${entry.text}`;
}

// The row: `helpers` are the frame's { avatar, nameOf, ago, docName }.
export function turnRow(workspace, entry, { avatar, nameOf, ago, docName }) {
  const turn = entry.turn || {};
  const undone = turn.undone;
  const go = () => workspace.goTo(entry.file, entry.where);
  // (What it did, each once: its name says the rest.)
  const done = (turn.done || []).filter((text) => text !== entry.text);
  const where = [entry.file && docName(entry.file), entry.where?.label].filter(Boolean).join(" · ");
  const words = turn.named ? [h("b", {}, nameOf(entry.who)), ": ", entry.text] : [h("b", {}, nameOf(entry.who)), " ", entry.text];
  const side = undone ? h("span.turn-undone", {}, `Undone${undone.who?.id === workspace.me?.id ? "" : ` by ${nameOf(undone.who)}`}`)
    : turn.kept === false ? null
      : Object.assign(ui.button("Undo", (event) => { event.stopPropagation(); undoTurn(workspace, entry, nameOf); }, { small: true, kind: "ghost" }),
        { title: `Undo ${inQuotes(turnName(entry, nameOf))}` });
  return h(`div.activity-row.turn-row${undone ? ".undone" : ""}`, { dataset: { turn: entry.id } },
    avatar(entry.who, { size: 22 }),
    h("button.turn-go", { type: "button", onclick: go },
      h("span.activity-text", {}, h("span", {}, ...words),
        done.length ? h("span.turn-done", {}, done.join(" · ")) : null,
        where ? h("span.activity-where", {}, where) : null)),
    h("span.turn-side", {}, h("span.activity-time", {}, ago(entry.at)), side));
}

// The turn `entry` (its row) taken back, in each document it changed: one step of this
// person's in each. Whether anything was.
export async function undoTurn(workspace, entry, nameOf) {
  const turn = entry.turn || {};
  const name = turnName(entry, nameOf);
  const files = turn.files?.length ? turn.files : [entry.file];
  let did = false, short = false;
  const sessions = [];
  for (const file of files) {
    let session, answer;
    try {
      session = await workspace.open(file, { activate: file === entry.file || files.length === 1 });
      if (session.unread || session.held) {
        toast(`Couldn’t undo ${inQuotes(name)} in ${file.split("/").pop()}: it can’t be read.`, { icon: "info", seconds: 5 });
        continue;
      }
      await session.settled?.();
      answer = await workspace.api(workspace.url("/api/turn", { id: entry.id, file }));
    } catch (error) {
      toast(`Couldn’t undo ${inQuotes(name)}. ${error?.message || error}`, { kind: "error", icon: "error", seconds: 6 });
      return did;
    }
    const taken = takeBack(session.document, answer.runs || []);
    if (same(taken.document, session.document)) { short = short || taken.lost.length > 0; continue; }
    session.change(() => taken.document, { label: `Undo ${inQuotes(name)}` });
    // (Its step knows the turn: undone and made again by ⌘Z and ⇧⌘Z, the row is told.)
    const step = session.past[session.past.length - 1];
    if (step) step.turn = entry.id;
    sessions.push(session);
    did = true;
    short = short || taken.lost.length > 0;
  }
  if (did) told(workspace, sessions, entry.id, true);
  if (short) toast(did ? `Couldn’t undo all of ${inQuotes(name)}: some of it has been changed since.`
    : `Couldn’t undo ${inQuotes(name)}: what it changed has been changed since.`, { icon: "info", seconds: 6 });
  else if (!did) toast(`Nothing of ${inQuotes(name)} is left to undo.`, { icon: "info", seconds: 4 });
  return did;
}

// The studio told the turn `id` is undone (or made again), once the changes that did it have
// reached it from `sessions`: its row says so, and so does the row of the change that did it.
async function told(workspace, sessions, id, undone) {
  const start = Date.now();
  while (sessions.some((session) => session.pendingLocal) && Date.now() - start < 5000) await new Promise((done) => setTimeout(done, 40));
  workspace.api("/api/turn/undone", { id, undone, who: workspace.me }).catch(() => {});
}

// A turn's runs (each { before, after }, the first first) taken back from `document`, the last
// first: { document, lost } -- `lost`, what could not be (replay's notes).
export function takeBack(document, runs) {
  const lost = [];
  for (const run of [...runs].reverse()) {
    const [made, missed] = replay(run.after, run.before, document);
    lost.push(...missed);
    document = made;
  }
  return { document, lost };
}

// The frame's: each document's undo of a turn undone and made again by ⌘Z and ⇧⌘Z (session.js's
// "turn"), told to the studio; and the palette's Undo of the latest turn on the document shown.
export function turns(workspace, { nameOf }) {
  workspace.on("opened", (session) => {
    session.on("turn", (step) => told(workspace, [session], step.turn, !step.undoneAt));
  });
  // The latest turn an agent made on `file` that can be undone, if any.
  const latest = (file) => [...(workspace.activity || [])].sort((a, b) => b.at - a.at)
    .find((entry) => entry.turn && !entry.turn.undone && entry.turn.kept !== false && (entry.turn.files || [entry.file]).includes(file));
  return {
    commands(session) {
      const entry = session && latest(session.file);
      return entry ? [{ icon: "undo", label: `Undo ${inQuotes(turnName(entry, nameOf))}`, run: () => undoTurn(workspace, entry, nameOf) }] : [];
    },
  };
}
