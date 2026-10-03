// One open document in the page: the copy being edited here, kept in step with
// the server's.
//
// Edits are sent a moment after they are made, together with the version they
// were made from; the server merges them with whatever others did meanwhile and
// answers with the result. Changes from others arrive as events and are merged
// into this copy, keeping edits not yet sent. Undo takes back this person's own
// change, and only that: it is a merge too, so others' later edits stay.

import { merge3, same, stable } from "./merge.js";
import { toast, h } from "./ui.js";

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
    state.note = toast(h("span.row", {}, h("span.spinner"), "Can't reach the studio — reconnecting…"), { seconds: 86400 });
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
    this.unread = Boolean(info.unread);   // nor has it since it was opened: there is nothing to show
    this.source = info.source ?? null;    // the file's words, while it is unread
    this.past = [];
    this.future = [];
    this.trips = [];                      // undos and redos waiting their turn
    this.lastMerge = null;
    this.listeners = {};
    this.sending = null;                  // the document in flight, while one is
    this.resyncing = false;
    this.failures = 0;                    // tries to send that failed in a row
    this.failed = null;                   // what the last said, while it stands
    this.pushTimer = null;
    this.drawTimer = null;
    this.drawBusy = false;
    this.drawWanted = false;
    this.drawVersion = 0;
    this.drawn = 0;
    this.pages = new Map();
    this.info = {};
    this.active = false;
    this.lastRemote = null;
    this.container = h("div.doc-view");
    this.tools = h("div.docbar-group");
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
    link(workspace);
  }

  on(event, listener) { (this.listeners[event] ||= []).push(listener); return this; }
  emit(event, detail) { for (const listener of this.listeners[event] || []) listener(detail); }

  get doc() { return this.document; }
  get catalogue() { return this.catalog; }
  get pendingLocal() { return !same(this.document, this.synced) || Boolean(this.sending); }
  // This page's own edits not yet in the file (others' are theirs to show).
  get unsaved() { return this.pendingLocal || this.savedVersion < this.ownVersion; }
  // Saving is those edits on their way to the file; with the studio out of reach, they
  // wait here ("offline") until it is back.
  get state() {
    if (this.problem) return "problem";
    if (this.unsaved) return link(this.workspace).away ? "offline" : "saving";
    return "saved";
  }

  // What the studio says is wrong with the file (`text`, or nothing now): `held`, it does
  // not read; `unread`, nor has it since it was opened, and `source` is its words.
  told({ text = null, held = false, unread = false, source = null } = {}) {
    const read = this.unread && !unread;
    this.problem = text;
    this.held = held;
    this.unread = unread;
    this.source = unread ? source : null;
    this.emit("status");
    if (read) this.requestDraw(0);  // it reads at last: there is something to draw
  }

  // Put right the words of a file that does not read: written once they read.
  async mend(text) {
    try { await this.workspace.api("/api/mend", { file: this.file, text }); }
    catch (error) { throw unreachable(error) ? new Error("Can't reach the studio.") : error; }
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
      if (joins) Object.assign(top, { after, at: now, said: null });
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
          to.push(entry);
          this.travelled(entry);
          return this.trip({ from, to, target, current, count }, done + 1);
        }, (error) => {
          const verb = target === "before" ? "undo" : "redo";
          const why = unreachable(error) ? "Can't reach the studio." : error?.message || error;
          toast(`Couldn't ${verb} “${this.said(entry).text || "Edit"}”. ${why}`, { kind: "error", icon: "error", seconds: 6 });
          this.emit("status");
        });
      }
      this.document = merge3(entry[current], this.document, entry[target]);
      from.pop();
      to.push(entry);
      moved = entry;
    }
    if (moved) this.travelled(moved);
    return null;
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
      let told = null;
      try { told = this.describe(entry.before, entry.after); } catch { told = null; }
      const said = typeof told === "string" ? { text: told } : told || {};
      entry.said = { text: entry.label || said.text || "", place: said.place, where: said.where };
    }
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
    if (this.sending || this.resyncing || same(this.document, this.synced)) return;
    const sent = this.document;
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
      // Out of reach, the page says so once and sends again when it is back; refused,
      // it says why once, not at every try.
      if (unreachable(error)) lost(this.workspace);
      else if (this.failed !== error.message) {
        this.failed = error.message;
        toast(`Couldn't sync your changes to ${this.file}: ${error.message}`, { kind: "error", icon: "error", seconds: 6 });
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
    else this.accept(result.version, result.document, sent);
    this.emit("status");
  }

  // The server's answer to what was sent: keep edits made since, on top of it.
  accept(version, document, sent) {
    if (version < this.version) return;
    const local = this.document;
    this.document = same(local, sent) ? document : merge3(sent, document, local);
    this.synced = document;
    this.version = version;
    this.ownVersion = Math.max(this.ownVersion, version);
    this.exists = true;
    if (!same(this.document, local)) {
      this.emit("change", { quiet: false, source: "remote" });
      this.requestDraw();
    }
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
    const before = this.document;
    this.document = same(before, this.synced) ? event.document : merge3(this.synced, event.document, before);
    this.synced = event.document;
    this.version = event.version;
    this.exists = true;
    if (!same(before, this.document)) {
      this.emit("change", { quiet: false, source: "remote", who: event.who, before });
      this.requestDraw();
    }
    if (!same(this.document, this.synced)) this.schedulePush();
    this.emit("status");
  }

  // The file holds `version` (or the studio has stopped holding back: the file reads again).
  saved(version) {
    this.savedVersion = Math.max(this.savedVersion, version);
    if (version >= this.version) this.written = this.synced;
    this.exists = true;
    this.told();
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
      info = await this.workspace.api(this.workspace.url("/api/open", { file: this.file }));
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
    const restarted = info.instance !== this.instance;
    const local = this.document;
    this.document = merge3(restarted ? this.written : this.synced, info.document, local);
    this.synced = info.document;
    this.version = info.version;
    this.instance = info.instance;
    this.savedVersion = info.saved;
    if (restarted) this.ownVersion = 0;
    if (info.saved >= info.version) this.written = info.document;
    this.exists = info.exists;
    this.problem = info.problem;
    this.held = Boolean(info.held);
    this.unread = Boolean(info.unread);
    this.source = info.source ?? null;
    this.resyncing = false;
    if (!same(local, this.document)) this.emit("change", { quiet: false, source: "remote" });
    const waiting = this.lastRemote;
    this.lastRemote = null;
    if (waiting && waiting.version > this.version) this.remote(waiting);
    this.emit("status");
    this.requestDraw(0);
    if (!same(this.document, this.synced)) this.schedulePush(0);
  }

  async saveNow() {
    await this.push();
    try { await this.workspace.api("/api/save", { file: this.file }); }
    catch (error) { throw unreachable(error) ? new Error("can't reach the studio") : error; }
  }

  // -- drawing --

  // Likewise drawing: one drawing at a time, and when it comes back the next
  // starts from the document as it is then. The page follows typing as fast as
  // the server draws.
  requestDraw(delay = 40) {
    this.drawWanted = true;
    if (this.drawBusy) return;
    if (this.drawTimer !== null) {
      if (delay > 0) return;
      clearTimeout(this.drawTimer);
    }
    this.drawTimer = setTimeout(() => { this.drawTimer = null; this.draw(); }, delay);
  }

  async draw() {
    this.drawWanted = false;
    this.drawBusy = true;
    try { await this.drawOnce(); } finally {
      this.drawBusy = false;
      if (this.drawWanted) this.requestDraw(0);
    }
  }

  async drawOnce() {
    // A file that has not read has nothing to draw (its editor says why instead).
    if (this.unread) return;
    const version = ++this.drawVersion;
    const known = Object.fromEntries([...this.pages].map(([id, page]) => [id, page.hash]));
    this.emit("drawing", { version });
    let result;
    try {
      result = await this.workspace.api("/api/draw", {
        file: this.file, document: this.document, version, known,
        hints: { ...this.hints(), client: this.workspace.client },
      });
    } catch (error) {
      // Out of reach, the drawing stays as it was until the studio is back (and draws again).
      if (unreachable(error)) { lost(this.workspace); return; }
      this.emit("drawn", { version, pages: [], messages: [{ text: String(error.message || error), severity: "error", where: "" }], failed: true });
      return;
    }
    if (result.stale || version < this.drawn) return;
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
  // `exports`) may ask first, in a sheet: `choose`, the formats to offer for it
  // ([{ format, label }]), and `options`, settings its export takes ([{ name, label,
  // value }]). Then the Mac app's one save panel puts the file, or a folder of several,
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
            ...(entry.options || []).map((option) => ui.toggle({ value: options[option.name], label: option.label, onChange: (value) => { options[option.name] = value; } })),
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
        toast(h("span.row", {}, `Exported “${saved.path.split("/").pop()}”`, show), { icon: "check", seconds: 10 });
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
      toast(`Exported “${name}”`, { icon: "check", seconds: 4 });
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
