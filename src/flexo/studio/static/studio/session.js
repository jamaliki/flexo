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

export class Session {
  constructor(workspace, info) {
    this.workspace = workspace;
    this.file = info.file;
    this.kind = info.kind;
    this.title = info.title;
    this.catalog = info.catalog;
    this.version = info.version;
    this.synced = info.document;          // the server's document at `version`
    this.document = structuredClone(info.document);
    this.savedVersion = info.saved;
    this.exists = info.exists;
    this.problem = info.problem;
    this.past = [];
    this.future = [];
    this.lastMerge = null;
    this.listeners = {};
    this.sending = null;                  // the document in flight, while one is
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
  }

  on(event, listener) { (this.listeners[event] ||= []).push(listener); return this; }
  emit(event, detail) { for (const listener of this.listeners[event] || []) listener(detail); }

  get doc() { return this.document; }
  get catalogue() { return this.catalog; }
  get pendingLocal() { return !same(this.document, this.synced) || Boolean(this.sending); }
  get state() {
    if (this.problem) return "problem";
    if (this.pendingLocal || this.savedVersion < this.version) return "saving";
    return "saved";
  }

  // -- editing --

  // Change the document: `mutate` edits a copy in place. `merge` names a run of
  // edits (typing in one field) that undo takes back together; `quiet` says the
  // control that made the change already shows it.
  change(mutate, { merge = null, quiet = false } = {}) {
    const before = this.document;
    const next = structuredClone(before);
    const result = mutate(next);
    const after = result === undefined ? next : result;
    if (same(after, before)) return;
    const now = Date.now();
    const top = this.past[this.past.length - 1];
    if (merge && top && this.lastMerge?.key === merge && now - this.lastMerge.at < 1500) top.after = after;
    else this.past.push({ before, after });
    if (this.past.length > 300) this.past.shift();
    this.future = [];
    this.lastMerge = merge ? { key: merge, at: now } : null;
    this.document = after;
    this.emit("change", { quiet, source: "edit" });
    this.schedulePush();
    this.requestDraw();
  }

  undo() { this.travel(this.past, this.future, "before", "after"); }
  redo() { this.travel(this.future, this.past, "after", "before"); }

  travel(from, to, target, current) {
    const entry = from.pop();
    if (!entry) return;
    to.push(entry);
    // Take back this change alone: others' edits since stay.
    this.document = merge3(entry[current], this.document, entry[target]);
    this.lastMerge = null;
    this.emit("change", { quiet: false, source: "history" });
    this.schedulePush(0);
    this.requestDraw(0);
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
    if (this.sending || same(this.document, this.synced)) return;
    const sent = this.document;
    this.sending = sent;
    this.emit("status");
    try {
      const result = await this.workspace.api("/api/update", {
        file: this.file, base: this.version, document: sent, client: this.workspace.client, who: this.workspace.me,
      });
      this.sending = null;
      this.accept(result.version, result.document, sent);
    } catch (error) {
      this.sending = null;
      toast(`Could not send your change to ${this.file}: ${error.message}`, { kind: "error", icon: "error", seconds: 6 });
      setTimeout(() => this.schedulePush(), 2000);
    }
    this.emit("status");
  }

  // The server's answer to what was sent: keep edits made since, on top of it.
  accept(version, document, sent) {
    if (version < this.version) return;
    const local = this.document;
    this.document = same(local, sent) ? document : merge3(sent, document, local);
    this.synced = document;
    this.version = version;
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

  saved(version) {
    this.savedVersion = Math.max(this.savedVersion, version);
    this.problem = null;
    this.exists = true;
    this.emit("status");
  }

  async saveNow() {
    await this.push();
    await this.workspace.api("/api/save", { file: this.file });
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

  // `part` exports one part of the document by itself (a figure on a slide), if its kind can.
  async exportFiles(formats, part = null) {
    const note = toast(h("span.row", {}, h("span.spinner"), `Exporting ${formats.join(", ").toUpperCase()}…`), { seconds: 120 });
    try {
      const result = await this.api("/api/export", { file: this.file, document: this.document, formats, ...(part ? { part } : {}) });
      note.remove();
      const folder = this.folder();
      const links = result.files.map((file) => {
        const beside = file.startsWith(folder) ? file.slice(folder.length) : file;
        return h("a", { href: this.raw(beside, true), download: "" }, beside.split("/").pop());
      });
      toast(h("span", {}, "Exported ", links.flatMap((link, index) => (index ? [", ", link] : [link]))), { icon: "check", seconds: 10 });
      return result.files;
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
