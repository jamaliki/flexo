// One open document in the page: the copy being edited here, kept in step with
// the server's.
//
// Edits are sent a moment after they are made, together with the version they
// were made from; the server merges them with whatever others did meanwhile and
// answers with the result. Changes from others arrive as events and are merged
// into this copy, keeping edits not yet sent. Undo takes back this person's own
// change, and only that: it is a merge too, so others' later edits stay.

import { merge3, mergeAnswer, replay, same, stable } from "./merge.js";
import { toast, h, inQuotes, dialog } from "./ui.js";

// Whether the studio answers, for the page as a whole: while it doesn't, one notice
// says so (not a message for each edit), edits wait and drawings stay as they were;
// once it answers again, every document takes in what changed meanwhile and sends
// its edits.
const links = new WeakMap();

function link(workspace) {
  let state = links.get(workspace);
  if (!state) {
    state = { down: false, away: false, note: null, timer: null };
    links.set(workspace, state);
    workspace.on?.("online", (up) => (up ? reached(workspace) : lost(workspace)));
  }
  return state;
}

// Each document says again whether its edits are saved: out of reach, they are not.
function restate(workspace) {
  for (const session of workspace.sessions?.values() || []) session.emit("status");
}

function lost(workspace) {
  const state = link(workspace);
  if (state.down) return;
  state.down = true;
  // A moment's break (the event stream reconnecting) is not worth a word.
  state.timer = setTimeout(() => {
    state.away = true;
    state.note = toast(h("span.row", {}, h("span.spinner"), "Can’t reach the studio — reconnecting…"), { seconds: 86400 });
    restate(workspace);
  }, 1500);
}

function reached(workspace) {
  const state = link(workspace);
  if (!state.down) return;
  state.down = false;
  state.away = false;
  clearTimeout(state.timer);
  state.note?.remove();
  state.note = null;
  restate(workspace);
  for (const session of workspace.sessions?.values() || []) session.resync?.();
}

// A request that never reached the studio (fetch's own failure), not one it refused.
const unreachable = (error) => error instanceof TypeError;

// What an export did, said in one note in place of the last export's: the file, and what
// it left out (a figure that can't be drawn, left an empty box) summed up -- on how many
// slides -- each said in a sheet a click away. `more` is a link beside it (Show in Finder).
let lastExport = null;
function exported(name, notes = [], more = null) {
  lastExport?.remove();
  const said = [...new Set(notes || [])];
  const slides = new Set(said.map((note) => /^Slide (\d+)\b/.exec(note)?.[1]).filter(Boolean));
  const counted = slides.size === said.length ? `${slides.size} slide${slides.size === 1 ? "" : "s"}` : `${said.length} part${said.length === 1 ? "" : "s"}`;
  const show = said.length ? h("a", { href: "#", onclick: (event) => {
    event.preventDefault();
    lastExport?.remove();
    dialog({ title: `Notes on “${name}”`, body: [h("ul.export-notes", {}, said.map((note) => h("li", {}, note)))], actions: [{ label: "Done", kind: "primary" }] });
  } }, "Show") : null;
  lastExport = toast(h("span.row", {}, `Exported “${name}”${said.length ? ` with notes on ${counted}` : ""}`, show, more),
    { icon: said.length ? "info" : "check", seconds: said.length ? 12 : more ? 10 : 4 });
}

// Drawings asked for by this page, of any of its documents (see drawOnce).
let drawings = 0;

// A run of typing made in parts, others' typing between them (see change): where it began
// with its own words alone -- each letter kept as whoever typed it, and those others typed
// left out, those they took away kept. Null where it is not only words changed in place.
function ownWords(parts) {
  const at = (value, path) => path.reduce((into, key) => (into == null ? undefined : into[key]), value);
  // The words each part changed, where.
  const paths = new Map();
  const walk = (was, now, path) => {
    if (typeof was === "string" && typeof now === "string") { if (was !== now) paths.set(JSON.stringify(path), path); return true; }
    if (was === now) return true;
    if (!was || !now || typeof was !== "object" || typeof now !== "object" || Array.isArray(was) !== Array.isArray(now)) return false;
    const keys = new Set([...Object.keys(was), ...Object.keys(now)]);
    if (Array.isArray(was) ? was.length !== now.length : [...keys].some((key) => !(key in was) || !(key in now))) return false;
    return [...keys].every((key) => walk(was[key], now[key], [...path, key]));
  };
  if (!parts.every((part) => walk(part.before, part.after, []))) return null;
  const own = structuredClone(parts[0].before);
  for (const path of paths.values()) {
    if (typeof at(own, path) !== "string") return null;
    let letters = [...at(own, path)].map((letter) => ({ letter }));
    // One change to the words as they read: the letters it took away marked as taken by
    // `by`, those it put in as typed by `by`.
    const made = (was, now, by) => {
      if (typeof was !== "string" || typeof now !== "string") return false;
      const shown = letters.filter((one) => !one.gone);
      if (shown.map((one) => one.letter).join("") !== was) return false;
      const a = [...was], b = [...now];
      let start = 0, end = 0;
      while (start < a.length && start < b.length && a[start] === b[start]) start++;
      while (end < a.length - start && end < b.length - start && a[a.length - 1 - end] === b[b.length - 1 - end]) end++;
      const cut = a.length - start - end;
      let put = b.slice(start, b.length - end);
      // (Where it could as well have been made a letter or more back -- a space typed beside
      // another's space -- it is put by the same hand's letters: the run it goes on.)
      let best = start, kept = put, most = -1;
      for (let from = start, typed = put; ; ) {
        const near = cut ? shown.slice(from, from + cut).filter((one) => one.by === by).length : Number(shown[from - 1]?.by === by);
        if (near > most) { most = near; best = from; kept = typed; }
        if (!from || (cut ? put.length || a[from - 1] !== a[from - 1 + cut] : a[from - 1] !== typed[typed.length - 1])) break;
        if (!cut) typed = [a[from - 1], ...typed.slice(0, -1)];
        from--;
      }
      put = kept;
      for (const one of shown.slice(best, best + cut)) one.gone = by;
      const after = best ? letters.indexOf(shown[best - 1]) + 1 : 0;
      letters = [...letters.slice(0, after), ...put.map((letter) => ({ letter, by })), ...letters.slice(after)];
      return true;
    };
    for (const [index, part] of parts.entries()) {
      if (index && !made(at(parts[index - 1].after, path), at(part.before, path), "others")) return null;
      if (!made(at(part.before, path), at(part.after, path), "own")) return null;
    }
    const words = letters.filter((one) => one.by !== "others" && one.gone !== "own").map((one) => one.letter).join("");
    path.slice(0, -1).reduce((into, key) => into[key], own)[path[path.length - 1]] = words;
  }
  return own;
}

export class Session {
  constructor(workspace, info) {
    this.workspace = workspace;
    this.file = info.file;
    this.kind = info.kind;
    this.title = info.title;
    this.catalog = info.catalog;
    this.version = info.version;
    this.instance = info.instance;        // the run of the studio `version` counts in
    this.synced = info.document;          // the server's document at `version`
    this.document = structuredClone(info.document);
    this.savedVersion = info.saved;
    this.ownVersion = 0;                  // the version this page's own latest edit became
    this.written = info.document;         // the document last known written to the file
    this.exists = info.exists;
    this.problem = info.problem;
    this.held = Boolean(info.held);       // the file on disk does not read: nothing is written over it
    this.gone = Boolean(info.gone);       // its file went (moved, deleted) and is not found: edits wait for it, or a save
    this.unread = Boolean(info.unread);   // nor has it since it was opened: there is nothing to show
    this.source = info.source ?? null;    // the file's words, while it is unread
    this.past = [];
    this.future = [];
    this.trips = [];                      // undos and redos waiting their turn
    this.lastMerge = null;
    this.listeners = {};
    this.sending = null;                  // the document in flight, while one is
    this.unanswered = [];                 // documents sent that no answer came for: the studio may have them
    this.unwritten = [];                  // its answers since `written`: a studio started again may have read them
    this.echoing = false;                 // started again on the file unread: what of this page's it holds is settled when it reads
    this.waiting = 0;                     // how many editors (figures) hold edits made through the studio while it is away
    this.resyncing = false;
    this.failures = 0;                    // tries to send that failed in a row
    this.failed = null;                   // what the last said, while it stands
    this.pushTimer = null;
    this.drawTimer = null;
    this.drawBusy = 0;                    // drawings asked for and not yet back
    this.drawYields = false;              // the last asked for yields (see requestDraw)
    this.drawWanted = false;
    this.drawVersion = 0;
    this.drawn = 0;
    this.pages = new Map();
    this.info = {};
    this.active = false;
    this.lastRemote = null;
    this.lastWho = null;                  // who made the last change from elsewhere
    this.container = h("div.doc-view");
    this.tools = h("div.docbar-group");
    // What adds to the document (a deck's Text, Table, Figure...), in the middle of the bar,
    // as Keynote's are.
    this.inserts = h("div.docbar-group");
    this.actions = h("div.docbar-group");
    this.commands = () => [];
    this.exports = [];      // what the kind exports: [{ format, label }], for the Mac app's menu
    this.present = null;    // a kind that presents (a deck) sets how
    this.reveal = () => {};
    this.hints = () => ({});
    // What a change did, as its kind says it: { text, place, where } (`place` names
    // where it was made, "Slide 3" say, and `where` is that place for the kind to go
    // to when it is undone or redone), or words alone.
    this.describe = () => null;
    // Two edits merged here, put right by the kind where they meet badly (as the studio's
    // kinds do with theirs): told the merge's notes (it leaves out those it settles) and base.
    this.mended = (document) => document;
    // A step said where it was made (`said`, its kind's describe), placed where that now is.
    this.follow = () => {};
    link(workspace);
  }

  on(event, listener) { (this.listeners[event] ||= []).push(listener); return this; }
  emit(event, detail) { for (const listener of this.listeners[event] || []) listener(detail); }

  get doc() { return this.document; }
  get catalogue() { return this.catalog; }
  get pendingLocal() { return !same(this.document, this.synced) || Boolean(this.sending) || Boolean(this.waiting); }
  // This page's own edits not yet in the file (others' are theirs to show).
  get unsaved() { return this.pendingLocal || this.savedVersion < this.ownVersion; }
  // Saving is those edits on their way to the file; with the studio out of reach, they
  // wait here ("offline") until it is back.
  get state() {
    if (this.problem) return "problem";
    // Out of reach, nothing is said to be saved: what was is, but whether it still is (the
    // file put right by hand meanwhile, another's edits) the studio alone knows.
    if (link(this.workspace).away) return "offline";
    if (this.unsaved) return "saving";
    return "saved";
  }

  // What the studio says is wrong with the file (`text`, or nothing now): `held`, it does
  // not read; `unread`, nor has it since it was opened, and `source` is its words; `gone`,
  // it went from where it was and is not found.
  told({ text = null, held = false, unread = false, source = null, gone = false } = {}) {
    const read = this.unread && !unread;
    this.problem = text;
    this.held = held;
    this.gone = gone;
    this.unread = unread;
    this.source = unread || held ? source : null;
    this.emit("status");
    // It reads at last: there is something to draw, and this page's edits made meanwhile go.
    if (read) { this.requestDraw(0); this.schedulePush(); }
  }

  // Put right the words of a file that does not read: written once they read.
  async mend(text) {
    try { await this.workspace.api("/api/mend", { file: this.file, text }); }
    catch (error) { throw unreachable(error) ? new Error("Can’t reach the studio.") : error; }
  }

  // -- editing --

  // The next change starts a step of its own in the history, whatever its `merge`: a
  // change of look among typing.
  step() { this.lastMerge = null; }

  // Change the document: `mutate` edits a copy in place. `merge` names a run of
  // edits (typing in one field) that undo takes back together; `quiet` says the
  // control that made the change already shows it; `label` says what it did, for the
  // history (else the kind's `describe` says it); `hold` joins the run of edits however long
  // the pauses in it (words typed in one place, from opening to done, are one step).
  change(mutate, { merge = null, quiet = false, label = null, hold = false } = {}) {
    const before = this.document;
    const next = structuredClone(before);
    const result = mutate(next);
    const after = result === undefined ? next : result;
    if (same(after, before)) return;
    const now = Date.now();
    const top = this.past[this.past.length - 1];
    const joins = merge && top && this.lastMerge?.key === merge && (hold || now - this.lastMerge.at < 1500);
    // A run of edits that ends where it began (a letter typed and deleted) did nothing:
    // it leaves the history.
    if (joins && same(top.before, after)) { this.past.pop(); this.lastMerge = null; }
    else {
      // Others' changes come in since the run's last edit: the run goes on in a part of its
      // own, so that undone it takes back these edits alone -- never folding theirs in.
      if (joins && !same(top.after, before)) top.parts = [...(top.parts || [{ before: top.before, after: top.after }]), { before, after }];
      else if (joins && top.parts) top.parts[top.parts.length - 1].after = after;
      // (Named as its latest edit says, where it says: "Typing “Alice step”", not "“A”".)
      if (joins) Object.assign(top, { after, at: now, said: null }, label ? { label } : {});
      else this.past.push({ before, after, at: now, label });
      if (this.past.length > 300) this.past.shift();
      this.lastMerge = merge ? { key: merge, at: now } : null;
    }
    this.future = [];
    this.document = after;
    this.emit("change", { quiet, source: "edit" });
    this.schedulePush();
    this.requestDraw();
  }

  // A change made somewhere other than this document -- a file it draws, written where
  // it is kept -- put in its history: `apply("before" | "after")` makes it undone or done
  // again (it may answer with a promise), and `label`, `place` and `where` say it. With
  // the same `merge` as the change before, soon after, it joins that one when that one's
  // `absorb(entry)` takes it.
  record(entry, { merge = null, hold = false } = {}) {
    const now = Date.now();
    const top = this.past[this.past.length - 1];
    if (merge && top?.apply && top.merge === merge && (hold || now - top.at < 1500) && top.absorb?.(entry)) top.at = now;
    else this.past.push({ ...entry, before: this.document, after: this.document, at: now, merge });
    if (this.past.length > 300) this.past.shift();
    this.future = [];
    this.lastMerge = null;
    this.emit("status");
  }

  // Undo (redo) the last `count` changes: the history's menu goes back several at once.
  undo(count = 1) { this.travel(this.past, this.future, "before", "after", count); }
  redo(count = 1) { this.travel(this.future, this.past, "after", "before", count); }

  // One trip through the history at a time: one waiting on a change put back elsewhere
  // is done before the next starts.
  travel(from, to, target, current, count = 1) {
    this.trips.push({ from, to, target, current, count });
    if (this.trips.length === 1) this.nextTrip();
  }

  nextTrip() {
    while (this.trips.length) {
      const waiting = this.trip(this.trips[0]);
      if (waiting) {
        const next = () => { this.trips.shift(); this.nextTrip(); };
        waiting.then(next, next);
        return;
      }
      this.trips.shift();
    }
  }

  // Take back (or make again) each change alone: others' edits since stay. A change
  // made elsewhere (a figure's own file) is put back there first, and moves in the
  // history only once it is: one that cannot be stays where it is, with those before it.
  trip({ from, to, target, current, count }, done = 0) {
    let moved = null;
    for (; done < count && from.length; done += 1) {
      const entry = from[from.length - 1];
      if (entry.apply) {
        if (moved) this.travelled(moved);
        return Promise.resolve().then(() => entry.apply(target)).then(() => {
          from.pop();
          entry.undoneAt = target === "before" ? Date.now() : null;
          to.push(entry);
          this.travelled(entry);
          return this.trip({ from, to, target, current, count }, done + 1);
        }, (error) => {
          const verb = target === "before" ? "undo" : "redo";
          const why = unreachable(error) ? "Can’t reach the studio." : error?.message || error;
          const what = inQuotes(this.said(entry).text || "Edit");
          toast(`Couldn’t ${verb} ${what}. ${why}`, { kind: "error", icon: "error", seconds: 6 });
          this.emit("status");
        });
      }
      const was = this.document;
      const lost = [];
      const document = this.travelOne(entry, target, current, lost);
      from.pop();
      if (same(was, document)) {
        // Nothing of it can be done now -- others have changed or deleted all it changed (the
        // words typed in an object deleted since): it leaves the history, not offered to be
        // made again, and with it every step before it that can do nothing either, one ⌘Z for
        // them all, said once. The next ⌘Z takes back the step that can be.
        const skipped = [{ entry, lost }];
        while (from.length && !from[from.length - 1].apply) {
          const missed = [];
          if (!same(this.travelOne(from[from.length - 1], target, current, missed), was)) break;
          skipped.push({ entry: from.pop(), lost: missed });
        }
        this.unmade(skipped, target, false);
        this.lastMerge = null;
        this.emit("status");
        continue;
      }
      this.document = document;
      // (Undone, what the undo did is kept, for a redo to take it back: see travelOne.)
      entry.undid = target === "before" ? { from: was, to: document } : null;
      if (lost.length) this.unmade([{ entry, lost }], target, true);
      // (When it was undone: for one history with edits held elsewhere -- a figure's, while the
      // studio is away -- ⇧⌘Z making again the latest undone of either.)
      entry.undoneAt = target === "before" ? Date.now() : null;
      to.push(entry);
      moved = entry;
    }
    if (moved) this.travelled(moved);
    return null;
  }

  // Changes that could not be taken back (or made again) in full, or at all (`some`: what
  // could was done), as others have changed what they changed since (`lost`: merge.js's
  // replay notes): their person is told why, once -- who changed it, or took it away -- in a
  // notice of its own, not one more stacked on the last.
  unmade(steps, target, some) {
    const me = this.workspace.me, who = this.lastWho;
    const mine = Boolean(who) && ((who.id && who.id === me?.id) || (who.name && who.name === me?.name));
    // (Changed by this person, in another of their windows: said so, not as another's doing.)
    const name = mine ? "you" : who?.name || (who?.kind === "agent" ? "An agent" : "Someone else");
    const verb = target === "before" ? "undo" : "redo";
    // Named as the history names it, in quotation marks: those within it alternating (inQuotes).
    const named = (entry) => inQuotes(this.said(entry).text || "Edit");
    const what = named(steps[0].entry);
    const notes = steps.flatMap((step) => step.lost);
    // (Deleted only where objects went: words gone from about the change -- retyped, or a
    // paragraph made a list -- are changed.)
    const did = notes.length && notes.every((note) => note.removed !== undefined) ? "deleted" : "changed";
    const more = steps.length - 1;
    const has = mine ? "have" : "has", where = mine ? " in another window" : "";
    const words = some ? `Couldn’t ${verb} all of ${what}: ${name} ${has} ${did} some of it since${where}.`
      : more === 1 ? `Couldn’t ${verb} ${what} or ${named(steps[1].entry)}: ${name} ${has} ${did} what they changed since${where}.`
          : more ? `Couldn’t ${verb} ${what} or the ${more} steps before it: ${name} ${has} ${did} what they changed since${where}.`
            : `Couldn’t ${verb} ${what}: ${name} ${has} ${did} it since${where}.`;
    this.unmadeNote?.remove();
    this.unmadeNote = toast(words, { icon: "info", seconds: 6 });
  }

  // One change taken back (or made again) on the document as it is now, which wins where
  // the two meet (merge.js's replay): a run made in parts part by part, the last first (or
  // the first first), each by itself. Made again, it is its undo taken back -- the words
  // others wrote meanwhile stay as and where they were, with this person's back among them,
  // not put after them. What could not be done is put in `lost`.
  travelOne(entry, target, current, lost = []) {
    const made = (base, document, to) => {
      const [result, missed] = replay(base, to, document);
      lost.push(...missed);
      return result;
    };
    if (target === "after" && entry.undid) return made(entry.undid.to, this.document, entry.undid.from);
    const parts = entry.parts || [entry];
    let document = this.document;
    for (const part of target === "before" ? [...parts].reverse() : parts) document = made(part[current], document, part[target]);
    return document;
  }

  travelled(entry) {
    this.lastMerge = null;
    this.emit("change", { quiet: false, source: "history", entry: this.said(entry) });
    this.schedulePush(0);
    this.requestDraw(0);
  }

  // What a change in the history did, in words, and where: its label, else as the kind
  // describes it, and the place the kind says it was made (worked out once, when first asked).
  said(entry) {
    if (!entry.said && entry.apply) entry.said = { text: entry.label || "", place: entry.place, where: entry.where };
    if (!entry.said) {
      // Named by its own change, never by others' made during it (a layout changed while it
      // was typing is not this step's): a run made in parts, by its last.
      const own = entry.parts ? entry.parts[entry.parts.length - 1] : entry;
      let told = null;
      try { told = this.describe(own.before, own.after); } catch { told = null; }
      const said = typeof told === "string" ? { text: told } : told || {};
      // A run of typing others' changes cut into parts: named by all it typed, as its undo
      // takes it all back ("Typing “alice types on”") -- the words others typed between
      // its parts, in among its own, left out (ownWords).
      if (entry.parts && /^Typing\b/.test(said.text || "")) {
        try {
          const own = ownWords(entry.parts);
          const whole = own && this.describe(entry.parts[0].before, own);
          const text = typeof whole === "string" ? whole : whole?.text;
          if (/^Typing\b/.test(text || "")) said.text = text;
        } catch { /* by its last part */ }
      }
      entry.said = { text: entry.label || said.text || "", place: said.place, where: said.where };
    }
    // Placed where it is now, as the kind follows it (`follow`), the place it was made in
    // having moved since (another moving its slide): its row in the history, and where its
    // undo goes. (The same words, changed in place: what it is, is.)
    if (!entry.apply) try { this.follow(entry, entry.said); } catch { /* where it was made */ }
    return entry.said;
  }

  // -- keeping in step --

  // Edits go out while typing continues, not only after it stops: at most one is
  // in flight, and the next carries everything made meanwhile.
  schedulePush(delay = 60) {
    if (this.pushTimer !== null) {
      if (delay > 0) return;
      clearTimeout(this.pushTimer);
    }
    this.pushTimer = setTimeout(() => { this.pushTimer = null; this.push(); }, delay);
  }

  async push() {
    // (Not while the file does not read: the studio has nothing to merge it with, and takes
    // it in when it reads -- see told.)
    if (this.sending || this.resyncing || this.unread || same(this.document, this.synced)) return;
    // A send no answer came for may have reached the studio all the same: its document is
    // taken in first, merged from what of this page's it has (resync), not sent on top again --
    // a letter typed as it went entered twice.
    if (this.unanswered.length) { this.resync(); return; }
    const sent = this.document, from = this.synced;
    this.sending = sent;
    this.emit("status");
    let result = null;
    try {
      result = await this.workspace.api("/api/update", {
        file: this.file, kind: this.kind, base: this.version, instance: this.instance, document: sent, client: this.workspace.client, who: this.workspace.me,
      });
    } catch (error) {
      this.sending = null;
      this.failures += 1;
      if (unreachable(error)) this.unanswered = [...this.unanswered.slice(-19), sent];
      // Out of reach, the page says so once and sends again when it is back; refused,
      // it says why once, not at every try.
      if (unreachable(error)) lost(this.workspace);
      else if (this.failed !== error.message) {
        this.failed = error.message;
        toast(`Couldn’t sync your changes to ${this.file}: ${error.message}`, { kind: "error", icon: "error", seconds: 6 });
      }
      clearTimeout(this.retryTimer);
      this.retryTimer = setTimeout(() => this.schedulePush(), Math.min(30000, 1000 * 2 ** this.failures));
      this.emit("status");
      return;
    }
    this.sending = null;
    this.failures = 0;
    this.failed = null;
    // The studio started again since this page last heard from it: its versions count
    // from the file anew, so the page takes in its document before sending.
    if (result.restarted) this.resync();
    // The file is another kind of document now: it opens again in that kind's editor.
    else if (result.reopen) this.workspace.reopen?.(this.file, result.kind);
    else this.accept(result.version, result.document, sent, result.who, from);
    this.emit("status");
  }

  // The server's answer to what was sent: keep edits made since, on top of it. `who` made
  // the changes it was merged with, if others did.
  accept(version, document, sent, who = null, from = null) {
    if (version < this.version) return;
    const local = this.document;
    // What was sent came back as it went though others changed it meanwhile: theirs were the
    // same edit (a space both typed at one place), taken as one.
    if (who && from && same(document, sent) && same(local, sent)) this.emit("absorbed", { base: from, incoming: document, before: local, who });
    const notes = [];
    // (Come back as it is here, it stays the very document here: the editor's objects, and
    // what it knows by them, stay.)
    this.document = same(local, sent) ? (same(document, local) ? local : document) : this.mended(mergeAnswer(sent, document, local, notes), notes, sent);
    this.synced = document;
    this.unwritten = [...this.unwritten.slice(-19), document];
    this.version = version;
    this.ownVersion = Math.max(this.ownVersion, version);
    this.exists = true;
    if (!same(this.document, local)) {
      // (`base` and `incoming`: what was merged with what was here, for an editor to carry its
      // caret through the same merge.)
      // (`answer`: the studio's answer to what this page sent -- its own items, among others'
      // alike added at one place, the later.)
      this.emit("change", { quiet: false, source: "remote", who, before: local, base: sent, incoming: document, merged: true, answer: true });
      this.requestDraw();
    }
    if (who && !same(document, sent)) this.lastWho = who;
    this.kept(notes, who);
    const waiting = this.lastRemote;
    if (waiting && waiting.version > this.version) this.remote(waiting);
    if (!same(this.document, this.synced)) this.schedulePush();
  }

  // Another's change, from the workspace's events.
  remote(event) {
    if (this.resyncing) { this.lastRemote = event; return; }
    if (event.client === this.workspace.client && event.version <= this.version) return;
    if (event.version <= this.version) return;
    if (this.sending) { this.lastRemote = event; return; }
    // (Read at last after the studio started again on it unread: from what of this page's own
    // the file holds, as resync merges.)
    const base = this.echoing ? this.ownBase(this.synced, event.document, true) : this.synced;
    const before = this.document, merged = !same(before, base);
    this.echoing = false;
    const notes = [];
    this.document = merged ? this.mended(merge3(base, event.document, before, notes), notes, base) : event.document;
    this.synced = event.document;
    this.version = event.version;
    this.exists = true;
    this.lastWho = event.who || null;
    if (!same(before, this.document)) {
      this.emit("change", { quiet: false, source: "remote", who: event.who, before, base, incoming: event.document, merged });
      this.requestDraw();
    } else if (merged) this.emit("absorbed", { base, incoming: event.document, before, who: event.who });
    this.kept(notes, event.who);
    if (!same(this.document, this.synced)) this.schedulePush();
    this.emit("status");
  }

  // What a merge here kept of this page's edits against another's (`who`): something they
  // deleted while it was edited here, words they wrote anew while words were typed in them
  // here (merge.js's notes, where this page's copy is "theirs"). Said as the studio says
  // what its merges kept (a "merged" event): { kept: item, by } or { rewritten, typed, by }.
  // (`away`: merged as the studio came back, this page's edits made while it was away.)
  kept(notes, who = null, away = false) {
    const ours = notes.flatMap((note) => (note.kept === "theirs" ? [{ kept: note.item, by: who }]
      : note.rewritten === "ours" ? [{ rewritten: note.words, typed: note.typed, by: who }] : []));
    if (ours.length) this.emit("merged", { notes: ours, away });
    // What this page deleted that another was typing in, kept for them here before it left
    // (their typing came first): they are told, as the studio tells them of what it keeps.
    const theirs = notes.filter((note) => note.kept === "ours").map((note) => note.item);
    if (theirs.length) this.workspace.api("/api/kept", { file: this.file, client: this.workspace.client, who: this.workspace.me, items: theirs }).catch(() => {});
  }

  // The file holds `version` (or the studio has stopped holding back: the file reads again).
  saved(version) {
    this.savedVersion = Math.max(this.savedVersion, version);
    if (version >= this.version) { this.written = this.synced; this.unwritten = []; }
    this.exists = true;
    this.told();
  }

  // What of this page's own the studio's document (`incoming`) holds beyond `from` -- a send
  // no answer came for; `restarted`, too, an answer the studio had not yet said was written
  // when it stopped -- the newest it holds whole: the base this page's edits are merged from,
  // none of them entered twice (once its own, once the studio's). They are settled with it.
  ownBase(from, incoming, restarted) {
    const echoes = [...(restarted ? this.unwritten : []), ...this.unanswered];
    this.unanswered = [];
    this.unwritten = [];
    for (const document of echoes.reverse()) if (!same(document, from) && same(merge3(from, incoming, document), incoming)) return document;
    return from;
  }

  // After the studio was out of reach: take in its document as it is now, keep this
  // page's edits on top, send them, and draw again. A studio started again has
  // read the file afresh, so what it has is merged from what was last written there.
  async resync() {
    if (this.resyncing) return;
    this.resyncing = true;
    this.lastRemote = null;
    let info;
    try {
      // As the kind it is open as, and held here: a studio started again on a folder whose
      // file has gone meanwhile makes nothing new of it -- this page's document is kept.
      info = await this.workspace.api(this.workspace.url("/api/open", { file: this.file, kind: this.kind, held: "1" }));
    } catch (error) {
      this.resyncing = false;
      if (unreachable(error)) lost(this.workspace);
      else setTimeout(() => this.resync(), 3000);
      return;
    }
    if (this.sending) {
      // A push that set out before: its answer first.
      this.resyncing = false;
      setTimeout(() => this.resync(), 200);
      return;
    }
    // Opened again as another kind since (put right as one): its editor is that kind's.
    if (info.kind !== this.kind) { this.resyncing = false; this.workspace.reopen?.(this.file, info.kind); return; }
    const restarted = info.instance !== this.instance, echoing = restarted || this.echoing;
    const local = this.document;
    const from = restarted ? this.written : this.synced;
    if (info.unread) {
      // Started again on a file that does not read, the studio has nothing of it (an empty
      // document stands in): this page's stays, and so does what it last had of the file, the
      // base its edits are merged from once it reads -- not the empty one, beside which all
      // here would be new, a second copy of each slide edited.
      this.synced = from;
      this.echoing = echoing;
    } else {
      // Its file gone, a studio started again has nothing of it: this page's document stands.
      // (What it keeps of this page's that the file lost meanwhile -- a slide typed in while it
      // was away, deleted there by an agent -- is said.)
      const base = this.ownBase(from, info.document, echoing), notes = [];
      this.document = restarted && !info.exists ? local : this.mended(merge3(base, info.document, local, notes), notes, base);
      this.kept(notes, restarted ? { id: "disk", name: "Another app", kind: "file" } : this.lastWho, true);
      this.synced = info.document;
      this.echoing = false;
    }
    this.version = info.version;
    this.instance = info.instance;
    this.savedVersion = info.saved;
    if (restarted) this.ownVersion = 0;
    if (info.saved >= info.version && !info.unread) this.written = info.document;
    this.exists = info.exists;
    this.problem = info.problem;
    this.held = Boolean(info.held);
    this.gone = Boolean(info.gone);
    this.unread = Boolean(info.unread);
    this.source = info.source ?? null;
    this.resyncing = false;
    // Its file moved meanwhile, and the studio followed it (the word of it missed, the page
    // away): the document is that file now, as when it is told (shell.js renamed).
    if (info.file !== this.file) this.workspace.renamed?.(this.file, info.file);
    if (!same(local, this.document)) this.emit("change", { quiet: false, source: "remote" });
    const waiting = this.lastRemote;
    this.lastRemote = null;
    if (waiting && waiting.version > this.version) this.remote(waiting);
    this.emit("status");
    this.requestDraw(0);
    // (Its file gone meanwhile -- moved, renamed, deleted -- it is not written again until
    // its person saves it, told so: a second copy is not made behind their back.)
    if (!same(this.document, this.synced) && !(restarted && !info.exists)) this.schedulePush(0);
    else if (restarted && !info.exists && info.problem) {
      // Renamed while the studio was away: the file it is now is a click away.
      const open = info.moved ? h("a", { href: "#", onclick: (event) => { event.preventDefault(); this.workspace.open?.(info.moved); } }, `Open ${info.moved}`) : null;
      toast(h("span", {}, info.problem, open ? " · " : "", open), { icon: "info", seconds: 12 });
    }
  }

  async saveNow() {
    await this.push();
    try { await this.workspace.api("/api/save", { file: this.file }); }
    catch (error) { throw unreachable(error) ? new Error("can’t reach the studio") : error; }
  }

  // -- drawing --

  // Likewise drawing: one drawing at a time, and when it comes back the next
  // starts from the document as it is then. The page follows typing as fast as
  // the server draws. A drawing whose hints say it `yields` (a deck settling its
  // figures, which can take a while) is not waited for: the next is asked for at
  // once, and the studio gives the first up for it.
  requestDraw(delay = 40) {
    this.drawWanted = true;
    if (this.drawBusy && !this.drawYields) return;
    if (this.drawTimer !== null) {
      if (delay > 0) return;
      clearTimeout(this.drawTimer);
    }
    this.drawTimer = setTimeout(() => { this.drawTimer = null; this.draw(); }, delay);
  }

  async draw() {
    this.drawWanted = false;
    this.drawBusy += 1;
    try { await this.drawOnce(); } finally {
      this.drawBusy -= 1;
      if (this.drawWanted && !this.drawBusy) this.requestDraw(0);
    }
  }

  async drawOnce() {
    // A file that has not read has nothing to draw (its editor says why instead).
    if (this.unread) return;
    // (Counted for the page, not the document opened in it: the studio drops a drawing older
    // than the last it was asked for by this page, and a document closed and opened again in it
    // counts on from there -- never from one again, its every drawing taken for an old one.)
    const version = this.drawVersion = ++drawings;
    const known = Object.fromEntries([...this.pages].map(([id, page]) => [id, page.hash]));
    const hints = { ...this.hints(), client: this.workspace.client };
    this.drawYields = Boolean(hints.yields);
    this.emit("drawing", { version });
    let result;
    try {
      result = await this.workspace.api("/api/draw", { file: this.file, document: this.document, version, known, hints });
    } catch (error) {
      // Out of reach, the drawing stays as it was until the studio is back (and draws again).
      if (unreachable(error)) { lost(this.workspace); return; }
      this.emit("drawn", { version, pages: [], messages: [{ text: String(error.message || error), severity: "error", where: "" }], failed: true });
      return;
    }
    if (result.stale || version < this.drawn) {
      // Given up with nothing newer asked for, and no edit on its way to be drawn instead (an
      // edit given way to is the editor's to draw, or to ask for this again): asked again.
      if (result.stale && version === this.drawVersion && !result.edited) this.drawWanted = true;
      return;
    }
    this.drawn = version;
    const pages = result.pages.map((page) => {
      if (page.svg !== undefined) this.pages.set(page.id, { hash: page.hash, svg: page.svg });
      const kept = this.pages.get(page.id);
      return { ...page, svg: kept?.svg ?? "", hash: page.hash ?? kept?.hash, stale: Boolean(page.pending) };
    });
    const ids = new Set(pages.map((page) => page.id));
    for (const id of [...this.pages.keys()]) if (!ids.has(id)) this.pages.delete(id);
    this.info = result.info || {};
    const latest = version === this.drawVersion && !this.drawWanted;
    this.emit("drawn", { version, pages, messages: result.messages, info: this.info, seconds: result.seconds, latest, unfinished: result.unfinished });
    if (result.unfinished && latest) this.drawWanted = true;
  }

  // -- files beside the document --

  api(route, body, options) { return this.workspace.api(route, body, options); }

  url(route, params = {}) { return this.workspace.url(route, { file: this.file, ...params }); }

  raw(path, download = false) { return this.url("/api/raw", { path, ...(download ? { download: "1" } : {}) }); }

  async files(types) { return (await this.api(this.url("/api/files", { types: types.join(",") }))).files; }

  async upload(file) {
    return (await this.api(this.url("/api/upload", { name: file.name }), await file.arrayBuffer(), { raw: true })).path;
  }

  folder() { return this.file.includes("/") ? this.file.slice(0, this.file.lastIndexOf("/") + 1) : ""; }

  // Export, as Keynote's File › Export To does. The kind's entry for a format (in
  // `exports`) asks first, in a sheet, when there is anything to choose -- `choose`, the
  // formats to offer for it ([{ format, label }]); `options`, settings its export takes
  // ([{ name, label, value, onChange }], `onChange` to keep a setting for next time) --
  // its `hint` (what the file will be) said there too. With nothing to choose (a deck's
  // PowerPoint, its PDF with no builds) it goes straight on, as Keynote does. Then the Mac app's one save panel puts the file, or a folder of several,
  // where its person says, or the browser downloads it (several files as a zip): nothing
  // is left beside the document. `part` exports one part of the document by itself (a
  // figure on a slide), if its kind can. Answers where it went, or [] if it did not.
  async exportFiles(formats, part = null) {
    const { dialog, ui } = await import("./ui.js");
    const app = window.pywebview?.api?.save_export ? window.pywebview.api : null;
    const entry = part || formats.length !== 1 ? null : this.exports.find((item) => item.format === formats[0]);
    const named = entry?.label?.replace(/…$/, "") || formats.join(", ").toUpperCase();
    const options = {};
    if (entry?.choose?.length || entry?.options?.length) {
      let chosen = entry.format;
      for (const option of entry.options || []) options[option.name] = Boolean(option.value);
      const go = await new Promise((done) => {
        let going = false;
        dialog({
          title: `Export ${named}`,
          body: [
            entry.choose?.length ? ui.field("Format", ui.segmented({ value: chosen, options: entry.choose.map((item) => ({ value: item.format, label: item.label })), onChange: (value) => { chosen = value; } })) : null,
            ...(entry.options || []).map((option) => ui.toggle({ value: options[option.name], label: option.label, onChange: (value) => { options[option.name] = value; option.onChange?.(value); } })),
          ],
          actions: [{ label: "Cancel" }, { label: app ? "Next…" : "Export", kind: "primary", run: () => { going = true; } }],
          onClose: () => done(going),
        });
        [...document.querySelectorAll(".dialog-foot .btn.primary")].pop()?.focus();
      });
      if (!go) return [];
      formats = [chosen];
    }
    const note = toast(h("span.row", {}, h("span.spinner"), `Exporting ${named}…`), { seconds: 120 });
    try {
      const body = { file: this.file, document: this.document, formats, options, deliver: app ? "staged" : "download", ...(part ? { part } : {}) };
      const response = await fetch(this.workspace.url("/api/export"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || `${response.status} ${response.statusText}`);
      if (app) {
        const made = await response.json();
        note.remove();
        const saved = await app.save_export({ ...made, file: this.file });
        if (saved?.error) throw new Error(saved.error);
        if (!saved?.path) return [];
        const show = h("a", { href: "#", onclick: (event) => { event.preventDefault(); app.show_in_finder(saved.path); } }, "Show in Finder");
        exported(saved.path.split("/").pop(), made.notes, show);
        return [saved.path];
      }
      const said = response.headers.get("Content-Disposition") || "";
      const name = decodeURIComponent(said.match(/filename\*=UTF-8''([^;]+)/)?.[1] || "") || "export";
      const link = h("a", { href: URL.createObjectURL(await response.blob()), download: name });
      note.remove();
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 60000);
      let notes = [];
      try { notes = JSON.parse(decodeURIComponent(response.headers.get("X-Flexo-Notes") || "[]")); } catch { /* none to say */ }
      exported(name, notes);
      return [name];
    } catch (error) {
      note.remove();
      toast(`Export failed: ${error.message}`, { kind: "error", icon: "error", seconds: 8 });
      return [];
    }
  }

  // Tell the others where this person is: `where` is the kind's own, with a `label`.
  focus(where) {
    this.where = where;
    this.workspace.reportFocus(this.file, where);
    this.workspace.emit("focus", this);
  }

  others() { return this.workspace.presenceOn(this.file); }

  hash() { return stable(this.document); }
}
