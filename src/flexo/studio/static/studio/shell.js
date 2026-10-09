// The studio's frame: open documents as tabs, who is here, what happened, the
// assistant, and the command palette. A kind's editor fills a document's view.

import { h, clear, icon, ui, menu, popover, closeMenu, dialog, toast, tabbables } from "./ui.js";
import { Session } from "./session.js";
import { AssistantPanel, MARK_COLOURS, OTHER_MARK } from "./assistant.js";

const SETTINGS = window.STUDIO || { token: "", file: "" };
const KIND_ICONS = { deck: "deck", figure: "figure", theme: "theme" };
// A new document's name, as a Mac app's: Untitled (Untitled 2, if that is taken).
const UNTITLED = { deck: "Untitled.yaml", figure: "Untitled Figure.yaml", theme: "Untitled Theme.yaml" };
// Each far from the others in hue, the first few most of all (they are given in the order
// people come), and none near the blue of what is chosen here, which is one's own.
const COLOURS = ["#e8590c", "#0ca678", "#d6336c", "#5c940d", "#ae3ec9", "#1098ad", "#f59f00", "#795548"];
// What gives an agent the studio's tools: `flexo studio mcp` -- or, in the Mac app, which
// puts no flexo command in Terminal, the app itself, as its address says (`mcp`), read
// before the address is made the document's.
const MCP = new URLSearchParams(location.search).get("mcp") || "flexo studio mcp";

// Each person here has the colour the studio gave them as they came, none shared with
// another here (see given); one not here (in the activity) has one by their id.
const given = new Map();
function give(presence) {
  given.clear();
  for (const entry of presence || []) if (entry?.who?.id && Number.isInteger(entry.colour)) given.set(entry.who.id, entry.colour);
}

export function colourOf(who) {
  if (who?.id === "assistant") return MARK_COLOURS[who.provider || "claude"] || OTHER_MARK;
  if (given.has(who?.id)) return COLOURS[given.get(who.id) % COLOURS.length];
  let hash = 0;
  for (const ch of String(who?.id || who?.name || "")) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return COLOURS[hash % COLOURS.length];
}

// Who someone is, in words: "You" to themselves (whatever they are called to others),
// else their name, else what they are.
let selfId = null;
export function nameOf(who) {
  if (who?.id && who.id === selfId) return "You";
  return who?.name || (who?.kind === "agent" ? "An agent" : "Someone");
}

export function avatar(who, { size = 24, ring = false } = {}) {
  const agent = who?.kind === "agent";
  // Someone with no name yet is a person's outline, not a "?" (which reads as Help).
  const named = who?.name || (who?.id === selfId ? "You" : "");
  const initials = agent || !named ? null : named.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
  return h("span.avatar", { title: nameOf(who), style: { width: `${size}px`, height: `${size}px`, background: colourOf(who), boxShadow: ring ? `0 0 0 2px var(--panel), 0 0 0 3.5px ${colourOf(who)}` : "" } },
    agent ? icon("sparkle", { weight: "1.3" }) : initials || icon("user", { weight: "1.4" }));
}

export function ago(seconds) {
  const delta = Math.max(0, Date.now() / 1000 - seconds);
  if (delta < 10) return "Just now";
  if (delta < 60) return `${Math.floor(delta)}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)} min ago`;
  return new Date(seconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// When a file was last changed, as the Finder's Date Modified says it: Today at 14:32,
// Yesterday at 09:10, else its date.
function changedWhen(seconds) {
  const when = new Date(seconds * 1000), now = new Date();
  const time = when.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const day = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const days = Math.round((day(now) - day(when)) / 86400000);
  if (days === 0) return `Today at ${time}`;
  if (days === 1) return `Yesterday at ${time}`;
  return when.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function remembered(key, fallback) { try { return localStorage.getItem(`flexo-studio-${key}`) ?? fallback; } catch { return fallback; } }
function remember(key, value) { try { localStorage.setItem(`flexo-studio-${key}`, value); } catch { /* private window */ } }

// A document's name as a Mac app shows it: "Lab meeting", not "Lab meeting.yaml".
// (A theme file's ".theme" too: "Order queue.theme.yaml" is "Order queue".)
const docName = (file) => String(file).split("/").pop().replace(/(\.theme)?\.(ya?ml|json)$/i, "");

// A file renamed: what is said of it, with the file it is now to open.
function movedNote(workspace, text, moved) {
  return h("span", {}, text, " · ", h("a", { href: "#", onclick: (event) => { event.preventDefault(); workspace.open(moved); } }, `Open ${moved}`));
}

// A document whose file does not read -- not since it was opened, or not now (broken while
// open): shown the one way, the file's words to put right, its line chosen.
const unreadable = (session) => Boolean(session?.unread || (session?.held && session?.source != null));

// The word on a document's saving: what is true of it and its file, briefly.
function statusWords(session) {
  const state = session.state;
  if (state === "saved") return "Saved";
  if (state === "saving") return "Saving…";
  if (state === "offline") return session.unsaved ? "Not saved: can’t reach the studio" : "Can’t reach the studio";
  const problem = session.problem || "";
  // A document that never read: which file, whole -- why is said on the page under it.
  if (unreadable(session)) return /^Can[’']t read [^:]+/.exec(problem)?.[0] || problem;
  // The file on disk does not read: "Not saved" only while edits made here wait for it.
  if (session.held) return session.unsaved ? `Not saved: ${problem.replace(/^Can[’']t/, "can’t")}` : problem;
  // Nothing made here waiting (a file moved or deleted under it): what is so, not "Not saved".
  // A reason why it could not be saved starts the sentence; a file's name keeps its spelling.
  const why = /^.*? could not be saved:\s*/.exec(problem);
  const said = why ? problem.slice(why[0].length) : problem;
  return session.unsaved ? `Not saved: ${said}` : why ? said.charAt(0).toUpperCase() + said.slice(1) : said;
}

// Settled once every stylesheet the page has asked for has loaded (or a moment has
// passed): an editor is shown styled, never as its bare elements.
function stylesLoaded() {
  const waiting = [...document.querySelectorAll('link[rel="stylesheet"]')].filter((link) => !link.sheet);
  const loads = waiting.map((link) => new Promise((done) => {
    link.addEventListener("load", done, { once: true });
    link.addEventListener("error", done, { once: true });
  }));
  return Promise.race([Promise.all(loads), new Promise((done) => setTimeout(done, 2000))]);
}

export class Workspace {
  constructor(info) {
    this.info = info;
    // This window; and the person, the same in each of their windows and after a reload,
    // so they keep their colour and are never shown to themselves as someone else.
    this.client = Math.random().toString(36).slice(2, 10);
    let person = remembered("person", "");
    if (!person) { person = Math.random().toString(36).slice(2, 10); remember("person", person); }
    // Unnamed, a person is "You" to themselves and "Someone" to others (once, the name "You"
    // was given to everyone unnamed, so others were shown as "You" too).
    // Else the name the Mac app gives (its account's), when it gives one.
    const named = remembered("name", "") || new URLSearchParams(location.search).get("me") || "";
    this.me = { id: person, name: named === "You" ? "" : named, kind: "person" };
    selfId = person;
    this.sessions = new Map();
    this.order = [];
    this.active = null;
    this.presence = info.presence || [];
    give(this.presence);
    this.activity = info.activity || [];
    this.documents = info.documents || [];
    this.follow = remembered("follow", "1") === "1";
    this.unseen = 0;
    this.listeners = {};
    this.focusTimer = null;
  }

  on(event, listener) { (this.listeners[event] ||= []).push(listener); return this; }
  emit(event, detail) { for (const listener of this.listeners[event] || []) listener(detail); }

  async api(route, body, { method = body === undefined ? "GET" : "POST", raw = false } = {}) {
    const response = await fetch(route, {
      method,
      headers: { "X-Studio-Token": SETTINGS.token, ...(raw ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
    });
    // An answer, whatever it says, is the studio there: its news is listened for again at once.
    this.wake();
    const data = await response.json().catch(() => ({ error: `${response.status} ${response.statusText}` }));
    if (!response.ok) throw new Error(data.error || `${response.status}`);
    return data;
  }

  url(route, params = {}) {
    return `${route}?${new URLSearchParams({ token: SETTINGS.token, ...params })}`;
  }

  // -- documents --

  async open(file, { activate = true } = {}) {
    let session = this.sessions.get(file);
    if (!session) {
      const info = await this.api(this.url("/api/open", { file }));
      if (this.sessions.has(info.file)) session = this.sessions.get(info.file);
      else {
        session = new Session(this, info);
        this.sessions.set(info.file, session);
        this.order.push(info.file);
        session.on("status", () => this.emit("status", session));
        session.on("change", () => this.emit("status", session));
        // Said once its editor is built and styled: the page goes from what it showed to the
        // document, with no welcome page or unstyled editor between.
        await this.mount(session);
        this.emit("opened", session);
        session.requestDraw(0);
        // Its file renamed (while the studio was away): the file it is now, a click away.
        if (info.moved && !info.exists) session.notice = toast(movedNote(this, info.problem, info.moved), { icon: "info", seconds: 12 });
      }
      file = session.file;
    }
    this.remember();
    if (activate) this.activate(file);
    return session;
  }

  async mount(session) {
    try {
      const editor = await import(`/static/kinds/${session.kind}/editor.js`);
      await editor.mount(session, session.container);
      await stylesLoaded();
    } catch (error) {
      console.error(error);
      clear(session.container, h("div.fatal", {}, h("h1", {}, `The ${session.title.toLowerCase()} editor failed to start`), h("pre", {}, String(error.stack || error))));
    }
  }

  activate(file) {
    const session = this.sessions.get(file);
    if (!session) return;
    for (const other of this.sessions.values()) {
      if (other.active && other !== session) { other.active = false; other.emit("deactivate"); }
    }
    this.active = session;
    session.active = true;
    session.emit("activate");
    history.replaceState(null, "", `?file=${encodeURIComponent(file)}`);
    document.title = `${docName(file)} — Flexo Studio`;
    this.emit("active", session);
    this.reportFocus(file, null);
  }

  close(file, { asked = false } = {}) {
    const session = this.sessions.get(file);
    if (!session) return;
    // Edits not yet saved -- the studio out of reach -- are not thrown away unasked: a sheet,
    // as a Mac app's for a document with changes, its default keeping the tab open.
    // Words typed in the file of one that does not read, not yet saved, are asked about as
    // a Mac app asks of a document with changes.
    if (!asked && session.sourceDraft != null) {
      const name = docName(file);
      const save = () => {
        session.mend(session.sourceDraft).then(() => { session.sourceDraft = null; this.close(file, { asked: true }); })
          .catch((error) => toast(`Not saved: ${error.message}`, { kind: "error", icon: "error" }));
      };
      dialog({ title: `Do you want to save the changes you made to “${name}”?`,
        body: [h("p.export-hint", {}, "Your changes will be lost if you don’t save them.")],
        actions: [{ label: "Don’t Save", danger: true, run: () => { session.sourceDraft = null; this.close(file, { asked: true }); } },
          { label: "Cancel", cancel: true }, { label: "Save", kind: "primary", run: save }] });
      return;
    }
    // Held for any reason -- the studio out of reach, the file not reading (they are saved
    // once it reads), or gone from where it was (saved once it is found, or saved again) --
    // they are asked about, never lost unasked.
    // (Held by the studio, they are lost should it stop before the file reads again.)
    const held = session.state === "offline" ? session.pendingLocal && "the studio can’t be reached. Keep it open until the studio is back?"
      : (session.held || session.unread) && session.unsaved ? "its file can’t be read. Keep it open until the file is put right?"
        : session.gone && session.unsaved ? "its file was moved or deleted. Keep it open, to save it again?" : null;
    if (!asked && held) {
      const name = docName(file);
      dialog({ title: `Close “${name}”?`,
        body: [h("p.export-hint", {}, `This document has changes that couldn’t be saved yet, as ${held}`)],
        actions: [{ label: "Close and Lose Changes", danger: true, run: () => this.close(file, { asked: true }) }, { label: "Keep Open", kind: "primary", cancel: true }] });
      return;
    }
    session.push();
    session.emit("close");
    this.sessions.delete(file);
    this.order = this.order.filter((name) => name !== file);
    if (this.active === session) {
      this.active = null;
      const next = this.order[this.order.length - 1];
      if (next) this.activate(next);
      else { history.replaceState(null, "", "?"); document.title = "Flexo Studio"; this.emit("active", null); }
    }
    this.emit("closed", session);
    this.remember();
  }

  // A document whose file has become another kind's (put right by hand as one): opened
  // again in that kind's editor, in its tab's place. What its old editor held was never
  // written over the file, and goes.
  async reopen(file, kind) {
    const session = this.sessions.get(file);
    if (!session || session.kind === kind) return;
    const place = this.order.indexOf(file), active = this.active === session;
    session.document = session.synced;
    this.close(file, { asked: true });
    try {
      await this.open(file, { activate: active });
      this.order.splice(this.order.indexOf(file), 1);
      this.order.splice(place, 0, file);
      this.remember();
      this.emit("status", this.sessions.get(file));
    } catch (error) { toast(`Could not open ${file}: ${error.message}`, { kind: "error", icon: "error" }); }
  }

  // Its file renamed as it was open (in the Finder, by an agent): the document follows it, as
  // a Mac document does -- its tab, the window's title and the address name the file it is
  // now, and its edits are saved there; no second tab, nothing written under the old name.
  renamed(file, to) {
    const session = this.sessions.get(file);
    if (!session || this.sessions.has(to)) return;
    this.sessions.delete(file);
    session.file = to;
    this.sessions.set(to, session);
    this.order = this.order.map((name) => (name === file ? to : name));
    session.notice?.remove();
    session.exists = true;
    session.told();
    if (this.focused?.[0] === file) this.focused = [to, this.focused[1]];
    if (this.active === session) {
      history.replaceState(null, "", `?file=${encodeURIComponent(to)}`);
      document.title = `${docName(to)} — Flexo Studio`;
    }
    this.remember();
    this.emit("status", session);
  }

  // The document `by` tabs on from the one in front (-1: the one before), round from the
  // last to the first.
  step(by) {
    if (!this.order.length) return;
    const at = this.active ? this.order.indexOf(this.active.file) : -1;
    const next = this.order[(Math.max(at, by > 0 ? -1 : 0) + by + this.order.length) % this.order.length];
    if (next && next !== this.active?.file) this.activate(next);
  }

  remember() { remember(`tabs:${this.info.folder}`, JSON.stringify(this.order)); }
  rememberedTabs() { try { return JSON.parse(remembered(`tabs:${this.info.folder}`, "[]")); } catch { return []; } }

  async create(kind, name) {
    // What is typed while it is on its way -- asked for, opened -- is kept for it.
    this.held?.stop();
    const held = this.held = holdKeys();
    try {
      const result = await this.api("/api/new", { file: name, kind, client: this.client, who: this.me });
      await this.refreshDocuments();
      // Its editor knows it is new (and so ready to be typed in at once).
      this.justMade = result.file;
      const session = await this.open(result.file);
      held.stop();
      // Its editor, open now, has those keys as though typed there -- if it takes keys typed
      // before it was ready (it says so as it is mounted: a figure's one shape is typed on).
      if (session?.takesKeys && session === this.active) typeAgain(held.keys);
      return session;
    } finally {
      held.stop();
      if (this.held === held) this.held = null;
    }
  }

  async refreshDocuments() {
    this.documents = (await this.api(this.url("/api/documents"))).documents;
    this.emit("documents");
  }

  // -- who is where --

  reportFocus(file, where) {
    this.focused = [file, where];
    clearTimeout(this.focusTimer);
    this.focusTimer = setTimeout(() => {
      this.api("/api/presence", { client: this.client, who: this.me, file, where }).catch(() => {});
    }, 250);
  }

  presenceOn(file) {
    return this.presence.filter((entry) => entry.file === file && entry.who.id !== this.me.id);
  }

  others() {
    return this.presence.filter((entry) => entry.who.id !== this.me.id);
  }

  setName(name) {
    this.me = { ...this.me, name: name || "" };
    remember("name", this.me.name);
    this.reportFocus(this.active?.file || null, null);
  }

  setFollow(on) { this.follow = on; remember("follow", on ? "1" : "0"); this.emit("follow"); }

  // -- events --

  connect() {
    const source = new EventSource(this.url("/api/events", { client: this.client, person: this.me.id, name: this.me.name }));
    source.onmessage = (message) => this.handle(JSON.parse(message.data));
    // Who is here comes with the hello, as the studio knows it now -- started again, it knows
    // only those back since, and no one gone meanwhile is left shown -- and it is told again
    // where this window is.
    source.addEventListener("hello", (message) => {
      clearTimeout(this.awayTimer);
      let hello = {};
      try { hello = JSON.parse(message.data || "{}"); } catch { hello = {}; }
      if (Array.isArray(hello.presence)) { this.presence = hello.presence; give(this.presence); this.emit("presence"); }
      if (this.focused) this.reportFocus(...this.focused);
      this.retryIn = 0;
      this.emit("online", true);
    });
    source.onerror = () => {
      this.emit("online", false);
      // Tried again soon, then less often (half a second, a second, at most two): back
      // quickly from a restart, not knocking twice a second while it is away -- and at once
      // on any sign it is back (wake).
      if (this.source === source) {
        source.close();
        this.retryIn = Math.min(2000, Math.max(500, (this.retryIn || 250) * 2));
        clearTimeout(this.retryTimer);
        this.retryTimer = setTimeout(() => { this.retryTimer = null; if (this.source === source) this.connect(); }, this.retryIn);
      }
      // Out of reach for more than a moment, who is here is not known: no one is shown, rather
      // than as they were last known, until the studio says again (its hello).
      clearTimeout(this.awayTimer);
      this.awayTimer = setTimeout(() => { if (this.presence.length) { this.presence = []; give([]); this.emit("presence"); } }, 1500);
    };
    this.source = source;
  }

  // The event stream, waiting to be tried again, tried now: the studio answered a request,
  // or the window is looked at again.
  wake() {
    if (!this.retryTimer) return;
    clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.connect();
  }

  handle(event) {
    const session = event.file ? this.sessions.get(event.file) : null;
    switch (event.type) {
      case "doc":
        session?.remote(event);
        if (session && event.client !== this.client) session.emit("remote", event);
        break;
      // What the studio's merge kept for someone: told to their pages (see Doc._tell).
      case "merged":
        session?.emit("merged", { notes: event.notes.filter((note) => (note.to ? note.to === this.client : event.client !== this.client)) });
        break;
      case "saved":
        session?.saved(event.version);
        // What was wrong with the file is over (it is back, or reads again): so is its word.
        session?.notice?.remove();
        break;
      case "problem":
        if (session) {
          // (Not said twice: a file that no longer reads, in view, says so over its editor.)
          const said = this.active === session && (event.unread || (event.held && event.source != null));
          if (session.problem !== event.text && event.text && !said) {
            session.notice?.remove();
            // Renamed as it was open: the file it is now, a click away.
            session.notice = event.moved ? toast(movedNote(this, event.text, event.moved), { icon: "info", seconds: 12 })
              : toast(event.text, { kind: "error", icon: "error", seconds: 8 });
          }
          session.told(event);
        }
        break;
      // Saved on two computers at once, the copy the cloud service kept of it merged in
      // (see Workspace.take_conflicts).
      case "conflict":
        if (session) toast(`${event.service || "The cloud service"} had two versions of ${event.file.split("/").pop()}, saved on two computers at once. Both sets of changes are kept.`, { icon: "info", seconds: 8 });
        break;
      case "reopened": this.reopen(event.file, event.kind); break;
      case "renamed": this.renamed(event.file, event.to); break;
      case "depends": if (session) { session.pages.clear(); session.requestDraw(0); } break;
      case "presence": this.presence = event.presence; give(this.presence); this.emit("presence"); break;
      case "documents": this.documents = event.documents; this.emit("documents"); break;
      case "trusted":
        this.info.trusted = true;
        for (const session of this.sessions.values()) session.requestDraw(0);
        this.emit("trusted");
        break;
      case "opened":
        if (!this.sessions.has(event.file)) {
          this.open(event.file, { activate: this.follow }).then(() => {
            if (!this.follow) toast(h("span", {}, `${event.who?.name || "An agent"} opened `, h("a", { href: "#", onclick: (e) => { e.preventDefault(); this.open(event.file); } }, event.file)), { icon: "sparkle" });
          });
        } else if (this.follow && event.who?.kind === "agent") this.activate(event.file);
        break;
      case "activity": {
        const entry = event.entry;
        const index = this.activity.findIndex((item) => item.id === entry.id);
        // What others do is news; what you did yourself is not.
        if (index >= 0) this.activity[index] = entry; else { this.activity.push(entry); if (entry.who?.id !== this.me.id && entry.who?.kind !== "system") this.unseen += 1; }
        if (this.activity.length > 300) this.activity.shift();
        this.emit("activity", entry);
        // (One that has only kept up with where its slide or object is now is not news.)
        if (this.follow && entry.who?.kind === "agent" && !event.followed) this.goTo(entry.file, entry.where, { quiet: true });
        break;
      }
      case "assistant": this.emit("assistant", event); break;
      default: break;
    }
  }

  async goTo(file, where, { quiet = false } = {}) {
    if (!file) return;
    const session = await this.open(file, { activate: true });
    // A slide or object since deleted is said to be, not looked for.
    if (where?.gone) { if (!quiet) toast(where.gone, { icon: "info" }); return; }
    if (where) session.reveal(where, { quiet });
  }
}

// -- the frame --------------------------------------------------------------------------

function applyTheme(mode) {
  if (mode === "light" || mode === "dark") document.documentElement.dataset.theme = mode;
  else delete document.documentElement.dataset.theme;
}

export async function start() {
  applyTheme(remembered("theme", "auto"));
  const root = document.getElementById("studio");
  let info;
  try {
    const response = await fetch(`/api/session?token=${encodeURIComponent(SETTINGS.token)}`, { headers: { "X-Studio-Token": SETTINGS.token } });
    info = await response.json();
    if (!response.ok) throw new Error(info.error || response.statusText);
  } catch (error) {
    clear(root, h("div.fatal", {}, h("h1", {}, "Flexo Studio couldn’t start"), h("pre", {}, String(error.message || error))));
    return;
  }
  const workspace = new Workspace(info);
  window.flexoStudio = workspace;
  // Settled once the tabs open when the page was last left are open again: what an app
  // around the page asks (open this document) waits for it, rather than being undone.
  let settled;
  workspace.ready = new Promise((done) => { settled = done; });

  // -- the top bar --
  const tabs = h("nav.tabs.scroll-thin", { role: "tablist", "aria-label": "Documents" });
  // New, after the tabs and never scrolled out of sight with them.
  const newTab = h("button.tab-new", { type: "button", title: "New Document", onclick: (event) => newMenu(event.currentTarget, workspace) }, icon("plus"));
  const people = h("div.people");
  const followChip = h("button.chip-toggle", { type: "button", title: "Follow agents as they work", onclick: () => workspace.setFollow(!workspace.follow) }, icon("target"), "Follow");
  const activityButton = ui.button("", () => side.toggle("activity"), { kind: "ghost", icon: "activity", title: "Show Activity (⌥⌘A)" });
  const activityCount = h("span.badge-count", { hidden: true });
  activityButton.append(activityCount);
  // The assistant -- Claude, ChatGPT or another, whichever is set up (assistant.js) -- a plain
  // button among the others, its mark in colour: the slide stays the brightest thing there is.
  const assistantButton = h("button.btn.assistant-button", { type: "button", title: "Show Assistant (⌘J)", onclick: () => side.toggle("assistant") }, icon("sparkle"), h("span.btn-label", {}, "Assistant"));
  // Pressed, it leaves the keys where they were (words being typed, the slide list) until
  // the palette has seen what they are on: its commands are for that.
  const paletteButton = h("button.search-button", { type: "button", "data-keeps-typing": true, onmousedown: (event) => event.preventDefault(), onclick: () => palette(workspace), title: "Command Palette (⌘K)" }, icon("search"), h("span", {}, "Search or run a command"), h("span.kbd", {}, "⌘K"));
  // Appearance as a Mac's: Automatic, Light or Dark, the one in use ticked.
  const themeButton = ui.button("", (event) => {
    const now = remembered("theme", "auto");
    const choose = (value) => () => workspace.appearance(value);
    menu(event.currentTarget, [{ title: "Appearance" },
      ...[["auto", "Automatic"], ["light", "Light"], ["dark", "Dark"]].map(([value, label]) => ({ label, checked: now === value, run: choose(value) }))], { align: "end" });
  }, { kind: "ghost", title: "Appearance" });
  const showTheme = () => clear(themeButton, icon(remembered("theme", "auto") === "dark" ? "moon" : remembered("theme", "auto") === "light" ? "sun" : "appearance"));
  showTheme();
  // In the Mac app the appearance is the app's, every window's (its welcome and Settings
  // too): told to it when chosen here, and taken from it as this window opens or is looked at.
  workspace.appearance = (value, { tell = true } = {}) => {
    remember("theme", value); applyTheme(value); showTheme();
    if (tell) window.pywebview?.api?.appearance?.(value)?.catch?.(() => {});
  };
  const appAppearance = () => Promise.resolve(window.pywebview?.api?.appearance?.()).then((mode) => {
    const mine = remembered("theme", "auto");
    // (The app with none chosen yet takes this window's.)
    if (mode === "" && mine !== "auto") window.pywebview.api.appearance(mine);
    else if (["auto", "light", "dark"].includes(mode) && mode !== mine) workspace.appearance(mode, { tell: false });
  }).catch(() => {});
  window.addEventListener("pywebviewready", appAppearance);
  window.addEventListener("focus", appAppearance);
  if (window.pywebview?.api) appAppearance();
  const bar = h("header.bar", {},
    h("div.brand", { title: info.folder }, h("div.brand-mark", {}, markIcon())),
    tabs, newTab,
    h("div.spacer"),
    paletteButton,
    people, followChip,
    h("div.bar-sep"),
    activityButton, themeButton, assistantButton);

  // -- the document bar --
  const docLeft = h("div.docbar-slot");
  const docCentre = h("div.docbar-slot.docbar-centre");
  const docRight = h("div.docbar-slot");
  const status = h("div.status", {}, h("span.dot"), h("span.status-text"));
  // Undo and redo wait for edits still on their way (a figure's typing), so they take
  // back the latest edit, not the one before it. Text being typed that is not yet in the
  // document (a shape's label in its editor) is undone as text, by the field itself.
  const ownUndo = () => document.activeElement?.closest?.(".fig-inline, [data-own-undo]");
  const travel = async (way) => {
    const session = workspace.active;
    if (!session) return;
    if (ownUndo()) { document.execCommand(way); return; }
    // Its file not reading, nothing is undone unseen behind the page that says so: said.
    if (unreadable(session)) {
      toast(`Can’t ${way} while ${session.file.split("/").pop()} can’t be read. Your changes wait here, saved once it reads.`, { icon: "info", seconds: 5 });
      return;
    }
    // An edit held for the studio while it is away (a figure's) is taken back first, and
    // made again first.
    if (way === "undo" && session.takeBack?.()) return;
    if (way === "redo" && session.putBack?.()) return;
    await session.settled?.();
    session[way]();
  };
  const undo = ui.button("", () => travel("undo"), { kind: "ghost", icon: "undo", title: "Undo (⌘Z)" });
  const redo = ui.button("", () => travel("redo"), { kind: "ghost", icon: "redo", title: "Redo (⇧⌘Z)" });
  const past = ui.button("", (event) => { const session = workspace.active; if (session) historyMenu(event.currentTarget, session); },
    { kind: "ghost", icon: "history", title: "Show History (⌥⌘Z)" });
  // As Keynote's toolbar: the document's own tools at the left, what adds to it in the
  // middle, saving, its history and the rest at the right.
  const docEnd = h("div.docbar-end", {}, status, h("div.bar-group", {}, undo, redo, past), h("div.bar-sep"), docRight);
  const docbar = h("div.docbar", {}, docLeft, docCentre, docEnd);
  // In a narrow window the side panel lies over the inspector (studio.css): the inspector's
  // own buttons (a deck's Format and Design) are not shown pressed under it, and one pressed
  // puts the panel away and shows the inspector -- never hides it, unseen.
  docRight.addEventListener("click", (event) => {
    const button = event.target.closest?.("button[aria-pressed]");
    if (!button || side.node.hidden || !matchMedia("(max-width: 1239px)").matches) return;
    side.hide();
    if (button.getAttribute("aria-pressed") === "true") { event.preventDefault(); event.stopPropagation(); }
  }, true);
  // A toolbar button clicked does not take the keys, as a Mac toolbar's doesn't: they stay
  // with the document (Delete deletes what is chosen, not the button's next press).
  docbar.addEventListener("mousedown", (event) => { if (event.target.closest("button") && !event.target.closest("input, select, textarea")) event.preventDefault(); });
  // Too wide for the window (or beside the side panel), the bar's middle group moves off
  // the centre to make room, then its tools show as icons alone, and then its other
  // buttons too, rather than run into each other or off the edge.
  const groups = [docLeft, docCentre, docEnd];
  const crowded = () => {
    if ([docbar, ...groups, docRight].some((node) => node.scrollWidth > node.clientWidth + 1)) return true;
    const boxes = groups.map((node) => node.getBoundingClientRect());
    return boxes[0].right > boxes[1].left - 8 || boxes[1].right > boxes[2].left - 8;
  };
  const fitDocbar = () => {
    docbar.classList.remove("shifted", "compact", "tight");
    for (const step of ["shifted", "compact", "tight"]) {
      if (!crowded()) return;
      docbar.classList.add(step);
    }
  };
  const fitting = new ResizeObserver(fitDocbar);
  for (const node of [docbar, ...groups, docRight]) fitting.observe(node);

  // The document's history, newest first: each row is the document as a change left
  // it, the one it is now marked; a click goes back (or forward) to that point.
  function historyMenu(anchor, session) {
    const when = (at) => {
      const seconds = Math.max(0, Math.round((Date.now() - at) / 1000));
      return seconds < 50 ? "Just now" : seconds < 3000 ? `${Math.round(seconds / 60)} min` : `${Math.round(seconds / 3600)} h`;
    };
    const go = (run) => () => { closeMenu(); run(); };
    const row = (entry, { now = false, undone = false, run }) => {
      const said = session.said(entry);
      return h(`button.history-row${now ? ".now" : ""}${undone ? ".undone" : ""}`, { type: "button", onclick: go(run), title: now ? "Current state" : undone ? "Redo to this point" : "Undo to this point" },
        h("span.history-mark"), h("span.history-text", {}, said.text || "Edit"),
        said.place ? h("span.history-place", {}, said.place) : null, h("span.history-when", {}, when(entry.at)));
    };
    const rows = [];
    const ahead = session.future, back = session.past;
    // Edits held for the studio while it is away (a figure's), each among the others where it
    // falls in time, as ⌘Z takes them -- and those taken back among those undone, as ⇧⌘Z makes
    // them again -- each said where it was made, as the others are, and as waiting.
    const helds = session.heldEdits?.() || (session.takeBackLabel?.() ? [{ label: session.takeBackLabel(), at: Infinity }] : []);
    const takens = session.takenEdits?.() || (session.putBackLabel?.() ? [{ label: session.putBackLabel() }] : []);
    // (Gone back or forward to by a click: as many ⌘Z or ⇧⌘Z, held edits and the document's
    // alike, each in turn.)
    const steps = (way, count) => (helds.length || takens.length ? async () => { for (let n = 0; n < count; n += 1) await travel(way); }
      : () => session[way](count));
    const waiting = (edit, { now = false, undone = false, run }) => h(`button.history-row${undone ? ".undone" : now ? ".now" : ""}`, { type: "button", onclick: go(run),
      title: undone ? "Redo to this point: it is saved when the studio is back" : now ? "Current state: not saved yet" : "Undo to this point: it was not saved yet" },
    h("span.history-mark"), h("span.history-text", {}, edit.label), edit.place ? h("span.history-place", {}, edit.place) : null, h("span.history-when", {}, "Waiting"));
    // Undone, the first undone last: what ⇧⌘Z makes again next is nearest the present.
    const later = [...ahead.map((entry) => ({ entry, when: entry.undoneAt ?? 0 })), ...takens.map((edit) => ({ edit, when: edit.undone ?? Infinity }))];
    if (takens.length) later.sort((a, b) => a.when - b.when);
    later.forEach((item, index) => rows.push(item.entry ? row(item.entry, { undone: true, run: steps("redo", later.length - index) })
      : waiting(item.edit, { undone: true, run: steps("redo", later.length - index) })));
    // Done, the latest first: the present, then what ⌘Z takes back in turn.
    const shown = 60, kept = back.slice(-shown);
    const done = [...kept.map((entry) => ({ entry, when: entry.at })), ...helds.map((edit) => ({ edit, when: edit.at }))];
    if (helds.length) done.sort((a, b) => a.when - b.when);
    done.reverse().forEach((item, index) => rows.push(item.entry ? row(item.entry, { now: !index, run: steps("undo", index) })
      : waiting(item.edit, { now: !index, run: steps("undo", index) })));
    if (back.length > shown) rows.push(h("div.history-more", {}, `${back.length - shown} earlier ${back.length - shown === 1 ? "change" : "changes"} not shown`));
    rows.push(h(`button.history-row.start${done.length ? "" : ".now"}`, { type: "button", onclick: go(steps("undo", back.length + helds.length)), title: "Undo all changes" },
      h("span.history-mark"), h("span.history-text", {}, "Original")));
    popover(anchor, [h("div.menu-title", {}, "History"), h("div.history", {}, rows)], { align: "end", className: "history-menu" });
    // The keys start at where the document is now, not at the newest change undone.
    requestAnimationFrame(() => document.querySelector(".history-menu .history-row.now")?.focus({ preventScroll: false }));
  }

  const views = h("main.views");
  const doing = h("div.doing-strip");
  const side = new SidePanel(workspace);
  workspace.side = side;
  // A folder someone else made runs none of its own Python until its person says so: said
  // here, once, for every slide whose plot waits (each slide only marks where it goes).
  const trustBar = h("div.trust-bar", { hidden: true }, icon("warning"),
    h("div.trust-words", {}, h("b", {}, "This folder’s Python hasn’t been run. "),
      "Its plots and figures appear once you trust the folder. Trust it only if you know where it came from."),
    ui.button("Trust and Run", async () => {
      try { await workspace.api("/api/trust", {}); }
      catch (error) { toast(`Could not trust the folder: ${error.message}`, { kind: "error", icon: "error" }); }
    }, { kind: "primary", small: true }));
  const untrusted = (drawn) => {
    if (!workspace.info.trusted && drawn?.messages?.some((message) => message.code === "code.untrusted")) trustBar.hidden = false;
  };
  workspace.on("opened", (session) => session.on("drawn", untrusted));
  workspace.on("trusted", () => { trustBar.hidden = true; });

  // -- the Mac app: its menus do what the page does, and it is told what they may do --
  workspace.command = (name, arg) => {
    const session = workspace.active;
    const field = typingIn(document.activeElement) ? document.activeElement : null;
    // A sheet open (a name asked for, the shortcuts): the menus wait, as a Mac's do while a
    // sheet is up -- all but Edit's, which are its field's then.
    if (document.querySelector(".scrim:not(.palette-scrim)")) {
      if (field && ["undo", "redo", "delete", "select-all"].includes(name)) editField(field, name);
      report();
      return;
    }
    // The palette open: closed first (⌘K, Find… again: only that), the command then run on
    // the document under it.
    if (document.querySelector(".palette")) {
      closePalette();
      if (name === "palette" || name === "find") { report(); return; }
    }
    switch (name) {
      case "undo": travel("undo"); break;
      case "redo": travel("redo"); break;
      case "history": if (session && !past.disabled) historyMenu(past, session); break;
      case "save":
        if (unreadable(session)) { unread?.mend(); break; }
        session?.saveNow().then(() => toast("Saved", { icon: "check", seconds: 1.2 }),
          (error) => toast(`Not saved: ${error.message}`, { kind: "error", icon: "error", seconds: 8 }));
        break;
      case "export": if (session?.exports.some((item) => item.format === arg)) session.exportFiles([arg]); break;
      case "present": session?.present?.(); break;
      // One of the document's own commands, by the label reported below (the app's Insert
      // and Slide menus): "Add Picture" runs "Add Picture…".
      case "run": {
        const bare = (label) => String(label ?? "").trim().replace(/…$/, "");
        session?.commands().find((command) => !command.disabled && [command.label, ...(command.also || [])].some((label) => bare(label) === bare(arg)))?.run();
        break;
      }
      case "palette": palette(workspace); break;
      case "find": palette(workspace, { find: true }); break;
      case "assistant": side.toggle("assistant"); break;
      case "activity": side.toggle("activity"); break;
      case "new": askName(workspace, arg, UNTITLED[arg] || "Untitled.yaml"); break;
      case "close-tab": if (session) workspace.close(session.file); break;
      case "rename": if (session) nameDocument(workspace, session.file); break;
      case "duplicate-document": if (session) nameDocument(workspace, session.file, { copy: true }); break;
      // Window › Show Next Tab, Show Previous Tab, and a document by its name.
      case "next-tab": workspace.step(1); break;
      case "previous-tab": workspace.step(-1); break;
      case "show": if (workspace.sessions.has(arg)) workspace.activate(arg); break;
      // Edit › Delete and Select All, chosen with the mouse: what ⌫ and ⌘A do here -- to the
      // words being typed, else to what is chosen in the document (its objects, its shapes).
      case "delete": case "select-all":
        if (field) editField(field, name);
        else pressKey(name === "delete" ? { key: "Backspace" } : { key: "a", mod: true });
        break;
      case "agents": connectDialog(workspace); break;
      case "shortcuts": shortcutsDialog(); break;
      default: break;
    }
    // What a command did may change what can be done (Show Speaker Notes is then Hide).
    report();
  };
  // What the document can do now, by label: the app enables its Insert and Slide items by it.
  // A command named for what it acts on ("Duplicate Table") is also the menu's plain one
  // (`also`: Edit › Duplicate); one greyed is not offered.
  const doable = (session) => {
    try { return session ? session.commands().filter((command) => !command.disabled).flatMap((command) => [command.label, ...(command.also || [])]) : []; } catch { return []; }
  };
  // Whether the document does something now with a key (⌫, ⌘C): one of its commands says so.
  const doesKey = (session, keys) => {
    try { return Boolean(session?.commands().some((command) => !command.disabled && command.keys === keys)); } catch { return false; }
  };
  let reporting = null;
  const report = () => {
    if (reporting) return;
    reporting = setTimeout(() => {
      reporting = null;
      const session = workspace.active;
      const field = typingIn(document.activeElement) ? document.activeElement : null;
      window.pywebview?.api?.studio_state?.({
        file: session?.file || "", kind: session?.kind || "", title: session?.title || "",
        can_undo: Boolean(session?.past.length), can_redo: Boolean(session?.future.length),
        undo_label: session?.past.length ? session.said(session.past[session.past.length - 1]).text : "",
        redo_label: session?.future.length ? session.said(session.future[session.future.length - 1]).text : "",
        exports: session?.exports || [], present: Boolean(session?.present), saved: session ? session.state === "saved" : true,
        commands: doable(session),
        // The open documents, for the Window menu (their names as their tabs have them); a
        // sheet up, which the menus wait for; and the side panel shown (Show or Hide Assistant).
        tabs: workspace.order.map((file) => ({ file, name: tabName(file, workspace.sessions.get(file)) })),
        sheet: Boolean(document.querySelector(".scrim:not(.palette-scrim)")),
        side: side.open || "",
        // Edit › Delete: words chosen in the field typed in, else what ⌫ deletes in the document.
        deletable: field ? chosenIn(field) : doesKey(session, "⌫"),
      });
    }, 80);
  };
  // A slide or part chosen changes what can be done; so does a field taking the keys
  // (⌘D is then the field's), and a sheet opening or closing.
  for (const event of ["status", "active", "opened", "closed", "documents", "focus", "side"]) workspace.on(event, report);
  document.addEventListener("focusin", report);
  document.addEventListener("focusout", report);
  // (So does choosing words in a field, or no longer: Edit › Delete is for them.)
  let wordsChosen = false;
  document.addEventListener("selectionchange", () => {
    const now = typingIn(document.activeElement) && chosenIn(document.activeElement);
    if (now !== wordsChosen) { wordsChosen = now; report(); }
  });
  // Edit › Cut, Copy and Paste, chosen with the pointer in the Mac app, for what is chosen in
  // the document (an object, a figure's shapes, a slide): the web view offers them only for
  // words chosen, unless the page says first that it has something of its own to cut, copy or
  // paste (its beforecut, beforecopy and beforepaste, as WebKit asks before its Edit menu
  // shows); the page's own cut, copy and paste then do it, as for ⌘X, ⌘C and ⌘V. Words typed
  // or chosen keep the web view's own.
  for (const [name, keys] of [["beforecut", "⌘X"], ["beforecopy", "⌘C"], ["beforepaste", "⌘V"]]) {
    document.addEventListener(name, (event) => {
      if (typingIn(document.activeElement) || !getSelection().isCollapsed || document.querySelector(".scrim, .present")) return;
      if (doesKey(workspace.active, keys)) event.preventDefault();
    });
  }
  window.addEventListener("pywebviewready", report);
  new MutationObserver(report).observe(document.body, { childList: true });
  const docHead = h("div", {}, docbar, trustBar);
  const unreadView = h("div.unread-view.scroll-thin", { hidden: true });
  const body = h("div.workbench", {}, h("div.center", {}, docHead, views, unreadView, doing), side.node);
  // In a narrow window the side panel lies over the document below its bar (studio.css),
  // so Present, Export, Undo and the word on saving stay in reach.
  new ResizeObserver(() => body.style.setProperty("--doc-head", `${docHead.offsetHeight}px`)).observe(docHead);
  // The spinner the page opened with stays over the frame until the first document is
  // ready to show (below): then the window goes from it to the document in one step.
  const loading = root.querySelector(".loading");
  clear(root, h("div.studio", {}, bar, body), loading);

  // -- keeping the frame current --
  // A tab is named for its document -- with its kind (Theme, Figure) when another open
  // document has its name, as a deck and the theme made from it may, and its folder when
  // that one is of its kind too.
  const tabName = (file, session) => {
    const name = docName(file);
    const twins = workspace.order.filter((other) => other !== file && docName(other) === name);
    if (!twins.length) return name;
    if (twins.every((other) => workspace.sessions.get(other)?.kind === session.kind)) {
      const path = `${String(workspace.info.folder || "").replace(/\/+$/, "")}/${file}`.split("/");
      return `${name} — ${path[path.length - 2]}`;
    }
    return session.kind === "deck" ? name : `${name} ${session.kind[0].toUpperCase()}${session.kind.slice(1)}`;
  };
  // The tabs as a Mac's: one stop for Tab (the one in front), ← and → to the others, Return or
  // Space to show one; a tab's × for the pointer alone (⌘W closes it). A right-click offers
  // what the File menu does to a document.
  const tabMenu = (event, file) => {
    event.preventDefault();
    workspace.activate(file);
    const path = `${String(workspace.info.folder || "").replace(/\/+$/, "")}/${file}`;
    menu({ x: event.clientX, y: event.clientY }, [
      { icon: "pencil", label: "Rename…", run: () => nameDocument(workspace, file) },
      { icon: "duplicate", label: "Duplicate…", keys: "⇧⌘S", run: () => nameDocument(workspace, file, { copy: true }) },
      ...(window.pywebview?.api?.show_in_finder ? [{ icon: "folder", label: "Show in Finder", run: () => window.pywebview.api.show_in_finder(path) }] : []),
      "-",
      { icon: "close", label: "Close Tab", keys: window.pywebview ? "⌘W" : undefined, run: () => workspace.close(file) },
    ]);
  };
  const tabKeys = (event, file) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); workspace.activate(file); return; }
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight" && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    const at = workspace.order.indexOf(file), last = workspace.order.length - 1;
    const next = event.key === "Home" ? 0 : event.key === "End" ? last : Math.max(0, Math.min(last, at + (event.key === "ArrowRight" ? 1 : -1)));
    workspace.activate(workspace.order[next]);
    tabs.querySelector(`.tab[data-file="${CSS.escape(workspace.order[next])}"]`)?.focus();
  };
  const renderTabs = () => {
    // A tab with the keys has them still once the tabs are drawn again.
    const keyed = tabs.contains(document.activeElement) ? document.activeElement.closest(".tab")?.dataset.file : null;
    clear(tabs, workspace.order.map((file) => {
      const session = workspace.sessions.get(file);
      const here = workspace.presenceOn(file);
      const on = workspace.active === session;
      const tab = h(`div.tab${on ? ".on" : ""}`, {
        role: "tab", tabIndex: on ? 0 : -1, "aria-selected": String(on), dataset: { file },
        title: `${String(workspace.info.folder || "").replace(/\/+$/, "")}/${file}`, onclick: () => workspace.activate(file),
        onauxclick: (event) => { if (event.button === 1) workspace.close(file); },
        oncontextmenu: (event) => tabMenu(event, file), onkeydown: (event) => tabKeys(event, file),
      },
      icon(KIND_ICONS[session.kind] || "file"),
      h("span.tab-name", {}, tabName(file, session)),
      session.state !== "saved" ? h(`span.tab-dot.${session.state}`, { title: statusWords(session) }) : null,
      here.length ? h("span.tab-people", {}, here.slice(0, 3).map((entry) => h("span.mini", { style: { background: colourOf(entry.who) }, title: nameOf(entry.who) }))) : null,
      h("button.tab-close", { type: "button", tabIndex: -1, title: "Close Tab", onclick: (event) => { event.stopPropagation(); workspace.close(file); } }, icon("close")));
      return tab;
    }));
    if (keyed) tabs.querySelector(`.tab[data-file="${CSS.escape(keyed)}"]`)?.focus();
    // The one in front is in view, however many there are.
    const shown = tabs.querySelector(".tab.on");
    if (shown) {
      const strip = tabs.getBoundingClientRect(), box = shown.getBoundingClientRect();
      if (box.left < strip.left + 24) tabs.scrollLeft -= strip.left + 24 - box.left;
      else if (box.right > strip.right - 24) tabs.scrollLeft += box.right - strip.right + 24;
    }
    fadeTabs();
  };
  // Where tabs are out of sight, the strip's end fades (studio.css).
  const fadeTabs = () => {
    tabs.classList.toggle("more-before", tabs.scrollLeft > 1);
    tabs.classList.toggle("more-after", tabs.scrollLeft + tabs.clientWidth < tabs.scrollWidth - 1);
  };
  tabs.addEventListener("scroll", fadeTabs, { passive: true });
  new ResizeObserver(fadeTabs).observe(tabs);

  const renderPeople = () => {
    const others = workspace.others();
    clear(people,
      others.map((entry) => {
        const button = h("button.person", { type: "button", onclick: () => entry.file && workspace.goTo(entry.file, entry.where),
          title: `${nameOf(entry.who)}${entry.doing ? ` · ${entry.doing}` : ""}${entry.file ? ` · ${docName(entry.file)}` : ""}` },
        avatar(entry.who, { ring: entry.who.kind === "agent" && Boolean(entry.doing) }));
        return button;
      }),
      h("button.person.add", { type: "button", title: "Work with Agents…", onclick: () => connectDialog(workspace) }, icon("collaborate")));
    followChip.hidden = !others.some((entry) => entry.who.kind === "agent");
    followChip.classList.toggle("on", workspace.follow);
    const working = others.filter((entry) => entry.who.kind === "agent" && entry.doing);
    clear(doing, working.map((entry) => h("button.doing", { type: "button", onclick: () => workspace.goTo(entry.file, entry.where) },
      avatar(entry.who, { size: 18 }), h("b", {}, nameOf(entry.who)), h("span", {}, entry.doing), h("span.pulse"))));
    renderTabs();
  };

  const renderStatus = () => {
    const session = workspace.active;
    docbar.hidden = !session;
    if (!session) { renderUnread(null); return; }
    // A document that does not read has nothing to undo or redo here (its words are put
    // right in the sheet, which has its own).
    // (An edit held for the studio while it is away is what Undo takes back first.)
    const held = session.takeBackLabel?.(), again = session.putBackLabel?.();
    undo.disabled = unreadable(session) || (!session.past.length && !held);
    redo.disabled = unreadable(session) || (!session.future.length && !again);
    past.disabled = unreadable(session) || (!session.past.length && !session.future.length && !held && !again);
    const last = session.past[session.past.length - 1], next = session.future[session.future.length - 1];
    const what = (entry) => (entry && session.said(entry).text ? ` ${session.said(entry).text}` : "");
    // (Named as the history names any step: "Undo Typing “away”".)
    undo.title = `Undo${held ? ` ${held}` : what(last)} (⌘Z)`;
    redo.title = `Redo${again ? ` ${again}` : what(next)} (⇧⌘Z)`;
    const state = session.state;
    status.className = `status ${state === "saved" ? "saved" : state === "problem" ? "problem" : state === "offline" ? "offline" : "busy"}${unreadable(session) ? " unread" : ""}`;
    const words = statusWords(session);
    status.title = state === "problem" ? session.problem || "" : state === "offline" && session.unsaved ? "Your changes are kept here, and saved when the studio is back." : "";
    const text = status.querySelector(".status-text");
    if (text.textContent !== words) {
      text.textContent = words;
      // The bar has room again for its tools' words once a long word on saving is gone.
      fitDocbar();
    }
    // A document that has never read has nothing to edit, export or present.
    for (const slot of [docLeft, docCentre, docRight]) slot.inert = unreadable(session);
    renderUnread(session);
  };

  // A document whose file has not read since it was opened: its editor has nothing to show,
  // so this says why over it, with the file's words to put right there (or in another app:
  // it opens as soon as it reads).
  let unread = null;
  const renderUnread = (session) => {
    unreadView.hidden = !unreadable(session);
    // (Read again, what was typed in its words is put right, or is no longer wanted.)
    if (!unreadable(session)) {
      // Put right elsewhere (another app) while words were typed in it here: those words are
      // kept, and it is said, to put them in the file after all or let them go.
      const draft = session?.sourceDraft;
      if (draft != null && !session.draftTold) {
        session.draftTold = true;
        const name = session.file.split("/").pop();
        const note = toast(h("span.row", {}, `${name} was put right elsewhere. What you typed in it here isn’t saved.`,
          h("a", { href: "#", onclick: (event) => {
            event.preventDefault(); note.remove();
            workspace.api("/api/mend", { file: session.file, text: draft, over: true }).then(() => { session.sourceDraft = null; toast(`Your words were saved in ${name}`, { icon: "check" }); })
              .catch((error) => toast(`Not saved: ${error.message}`, { kind: "error", icon: "error", seconds: 6 }));
          } }, "Use Mine"),
          h("a", { href: "#", onclick: (event) => { event.preventDefault(); note.remove(); session.sourceDraft = null; } }, "Discard")),
        { icon: "info", seconds: 60 });
      }
      unread = null;
      return;
    }
    if (session) session.draftTold = false;
    // (Said again as the page's edits wait, or no longer do.)
    const waiting = () => `${session.pendingLocal ? "Your changes wait here, saved once it reads; nothing" : "Nothing"} has been changed in the file. Put it right ${session.source != null || session.sourceDraft != null ? "here and save, or " : ""}in another app: it opens as soon as it reads.`;
    if (unread?.session === session && unread.problem === session.problem && (unread.source === session.source || unread.edited)) {
      if (unread.note.textContent !== waiting()) unread.note.textContent = waiting();
      return;
    }
    const area = h("textarea.unread-source", { autocomplete: "off", "aria-label": `${session.file}, as written`, dataset: { ownUndo: "" } });
    area.spellcheck = false;
    // Words the person has typed here are kept when the file changes again, or another tab
    // is looked at meanwhile -- and asked about before its tab or the window closes.
    const kept = session.sourceDraft != null;
    area.value = kept ? session.sourceDraft : session.source ?? "";
    const shown = kept || session.source != null;  // not a file too large to show
    // What is wrong, the file named once (in the heading).
    const said = h("div.unread-said", {}, (session.problem || "").replace(/^Can[’']t read [^:]+: (.)/, (_, first) => first.toUpperCase()));
    const save = ui.button("Save", () => mend(), { kind: "primary" });
    const mend = async () => {
      if (!shown) return;
      save.disabled = true;
      try { await session.mend(area.value); session.sourceDraft = null; }
      // The words typed here, not the file (which the bar above speaks of), are what does not read.
      catch (error) {
        said.textContent = /reach the studio/.test(error.message) ? error.message : `Not saved: as typed here, ${error.message.charAt(0).toLowerCase()}${error.message.slice(1)}`;
        // The line it now names, chosen, as when the sheet opened.
        chooseLine(error.message);
      }
      finally { save.disabled = false; }
    };
    // The line a problem names, chosen and in view -- or, named past the last words (a bracket
    // left open at the end), the last line with words before it. A bracket or quote never
    // closed is named where the reading gave up: the line it was opened on is chosen.
    const opened = (problem, lines, line) => {
      const marks = /expected ',' or '\]'/.test(problem) ? ["[", "]"] : /expected ',' or '\}'/.test(problem) ? ["{", "}"]
        : /quoted scalar|end of stream/.test(problem) ? ["\"", "'"] : null;
      if (!marks) return line;
      const count = (text, mark) => text.split(mark).length - 1;
      for (let at = Math.min(line, lines.length); at >= 1; at -= 1) {
        const text = lines[at - 1];
        if (marks[0] === "[" || marks[0] === "{" ? count(text, marks[0]) > count(text, marks[1]) : count(text, marks[0]) % 2 || count(text, marks[1]) % 2) return at;
      }
      return line;
    };
    const chooseLine = (problem) => {
      const named = Number((problem || "").match(/\bline (\d+)/i)?.[1] || 0);
      let line = named;
      if (!line || !shown) return;
      requestAnimationFrame(() => {
        const lines = area.value.split("\n");
        while (line > 1 && !(lines[line - 1] || "").trim()) line -= 1;
        line = opened(problem || "", lines, line);
        // What is said names the line chosen, not the one the reading stopped at (nor its
        // column there).
        if (line !== named) said.textContent = said.textContent.replace(new RegExp(`\\b(l)ine ${named}\\b(?:, column \\d+)?`, "gi"), (_, l) => `${l}ine ${line}`);
        const start = lines.slice(0, line - 1).reduce((sum, item) => sum + item.length + 1, 0);
        // The keys are not taken from words being typed elsewhere (a slide's, held till the
        // file reads): what is typed next would go over the file's line.
        const at = document.activeElement;
        const typing = at && at !== document.body && !unreadView.contains(at) && (at.isContentEditable || /^(INPUT|TEXTAREA)$/.test(at.tagName));
        if (!typing) area.focus({ preventScroll: true });
        area.setSelectionRange(start, start + (lines[line - 1] || "").length);
        area.scrollTop = Math.max(0, (line - 4) * parseFloat(getComputedStyle(area).lineHeight || "18"));
      });
    };
    area.addEventListener("input", () => {
      if (unread) unread.edited = true;
      session.sourceDraft = area.value !== (session.source ?? "") ? area.value : null;
    });
    // (Changes made here meanwhile wait here, saved once it reads: said so.)
    const note = h("p.unread-note", {}, waiting());
    clear(unreadView, h("div.unread-inner", {},
      h("div.unread-head", {}, icon("warning"), h("h2", {}, `${session.file.split("/").pop()} can’t be read`)),
      said, note,
      shown ? area : null,
      shown ? h("div.unread-foot", {}, save) : null));
    unread = { session, problem: session.problem, source: session.source, area, edited: kept, mend, note };
    chooseLine(session.problem);
  };

  const renderViews = () => {
    const session = workspace.active;
    for (const other of workspace.sessions.values()) if (other.container.parentNode !== views) views.append(other.container);
    for (const child of [...views.children]) {
      const owner = [...workspace.sessions.values()].find((item) => item.container === child);
      if (!owner) child.remove();
      else child.hidden = owner !== session;
    }
    welcome.hidden = Boolean(session);
    if (!session) { views.append(welcome); renderWelcome(); workspace.refreshDocuments().catch(() => {}); }
    clear(docLeft, session ? session.tools : null);
    clear(docCentre, session ? session.inserts : null);
    clear(docRight, session ? session.actions : null);
    renderTabs();
    renderStatus();
  };

  const welcome = h("div.welcome.scroll-thin");
  const renderWelcome = () => {
    const folderName = String(info.folder).split("/").filter(Boolean).pop() || "this folder";
    // Each kind offered, said as the New menu says it, side by side however many there are.
    const offered = [["deck", "Deck", "Slides for a talk"], ["figure", "Figure", "A diagram laid out automatically"], ["theme", "Theme", "Fonts, colours and lines"]]
      .filter(([kind]) => offers(workspace, kind));
    const card = ([kind, title, hint]) => h("button.start-card", { type: "button", onclick: () => askName(workspace, kind, UNTITLED[kind]) },
      h("span.start-icon", {}, icon(KIND_ICONS[kind])), h("span.start-words", {}, h("span.start-title", {}, title), h("span.start-hint", {}, hint)));
    // The folder's documents by name, as the Finder lists them, each with when it was changed.
    const listed = [...workspace.documents].sort((a, b) => docName(a.file).localeCompare(docName(b.file), undefined, { numeric: true, sensitivity: "base" }) || a.file.localeCompare(b.file));
    clear(welcome, h("div.welcome-inner", {},
      h("h1", {}, "New Document"),
      h("div.start-cards", { style: { gridTemplateColumns: `repeat(${Math.max(2, offered.length)}, minmax(0, 1fr))` } }, offered.map(card)),
      // Where what is made goes: a file in the folder (its whole path in the tooltip).
      h("p.start-where", { title: info.folder }, `Each is a file in “${folderName}”, saved as you work.`),
      listed.length ? h("div.welcome-section", {}, h("h2", { title: info.folder }, folderName),
        h("div.doc-list", {}, listed.map((item) => h("button.doc-row", { type: "button", title: item.file, onclick: () => workspace.open(item.file) },
          icon(KIND_ICONS[item.kind] || "file"), h("span.doc-name", {}, docName(item.file)),
          // One that does not read, or does not draw as written, says so, as the themes' list does.
          item.unread || item.faulty ? h("span.doc-kind.bad", { title: `Open ${docName(item.file)} to see why and put it right` }, item.unread ? "Can’t be read" : "Has problems") : null,
          item.file.includes("/") ? h("span.doc-kind", {}, item.file.split("/").slice(0, -1).join("/")) : null,
          item.modified ? h("span.doc-when", {}, changedWhen(item.modified)) : null)))) : null));
  };

  // The side panel's buttons pressed while it shows theirs, each named for what it does next.
  workspace.on("side", () => {
    for (const [button, which, name, keys] of [[assistantButton, "assistant", "Assistant", "⌘J"], [activityButton, "activity", "Activity", "⌥⌘A"]]) {
      const shown = side.open === which;
      button.classList.toggle("on", shown);
      button.setAttribute("aria-pressed", String(shown));
      button.title = `${shown ? "Hide" : "Show"} ${name} (${keys})`;
    }
  });

  workspace.on("opened", renderViews).on("closed", renderViews).on("active", renderViews)
    .on("status", (session) => { if (session === workspace.active) renderStatus(); renderTabs(); })
    .on("presence", renderPeople).on("follow", renderPeople)
    .on("documents", () => { if (!workspace.active) renderWelcome(); })
    .on("activity", () => {
      activityCount.hidden = side.open === "activity" || !workspace.unseen;
      activityCount.textContent = workspace.unseen > 9 ? "9+" : String(workspace.unseen);
    });

  // -- keys --
  document.addEventListener("keydown", (event) => {
    // A key the page has taken already (a field's ⌘K, Link; a shape's ⌘Z) is not the frame's too.
    if (event.defaultPrevented) return;
    const mod = event.metaKey || event.ctrlKey;
    const key = event.key.toLowerCase();
    const session = workspace.active;
    // ⌘K again closes the palette, as Spotlight's key does. While words are typed it opens
    // nothing (it is Link where words can have one), and not the Mac app's menu item either.
    if (mod && key === "k" && !event.altKey) {
      event.preventDefault();
      if (document.querySelector(".palette")) closePalette();
      else if (!typingIn(event.target) && !document.querySelector(".scrim:not(.palette-scrim), .present")) palette(workspace);
      return;
    }
    // ⌘J: the assistant, the palette put away for it -- but nothing behind a sheet, as the Mac
    // app's View menu waits for one, nor during a show.
    if (mod && key === "j" && !event.altKey) {
      event.preventDefault();
      if (document.querySelector(".scrim:not(.palette-scrim), .present")) return;
      closePalette();
      side.toggle("assistant");
      return;
    }
    if (document.querySelector(".scrim, .present")) return;
    if (mod && event.altKey && event.code === "KeyA") { event.preventDefault(); side.toggle("activity"); return; }
    // ⇧⌘] and ⇧⌘[: the next or the previous document, as a Mac app's tabs are gone through.
    if (mod && event.shiftKey && !event.altKey && (event.code === "BracketRight" || event.code === "BracketLeft")) {
      event.preventDefault();
      workspace.step(event.code === "BracketRight" ? 1 : -1);
      return;
    }
    // ⇧⌘S: File › Duplicate, as Keynote's.
    if (mod && event.shiftKey && key === "s") { event.preventDefault(); if (session) nameDocument(workspace, session.file, { copy: true }); }
    else if (mod && key === "s") {
      event.preventDefault();
      // A file that does not read is saved as it has been put right, once it reads.
      if (session?.unread) unread?.mend();
      else session?.saveNow().then(() => toast("Saved", { icon: "check", seconds: 1.2 }),
        (error) => toast(`Not saved: ${error.message}`, { kind: "error", icon: "error", seconds: 8 }));
    }
    else if (mod && event.altKey && event.code === "KeyZ") { event.preventDefault(); if (session && !past.disabled) historyMenu(past, session); }
    else if (mod && key === "z" && ownUndo()) { /* the field's own undo */ }
    else if (mod && key === "z" && !event.shiftKey) { event.preventDefault(); travel("undo"); }
    else if (mod && ((key === "z" && event.shiftKey) || key === "y")) { event.preventDefault(); travel("redo"); }
    // Once the page has had the key: a word typed into a shape on its way (a decision's
    // "?") is the shape's.
    else if (key === "?" && !inField(event)) setTimeout(() => { if (!event.defaultPrevented) shortcutsDialog(); });
    // ⌘/: Help › Keyboard Shortcuts, as the Mac app's menu has it.
    else if (mod && key === "/" && !event.altKey) { event.preventDefault(); shortcutsDialog(); }
    // ⌥⌘I: to the document's inspector, for a kind that does not take the key itself (a
    // deck's does), as the shortcuts sheet has it for every document.
    else if (mod && event.altKey && event.code === "KeyI") setTimeout(() => { if (!event.defaultPrevented) toInspector(); });
  });
  // Tab in a document's inspector goes round it, as in a sheet: from its last control to its
  // first (⇧⇥ the other way), never off its end to nothing. Esc leaves it.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Tab" || event.defaultPrevented || event.metaKey || event.altKey || event.ctrlKey) return;
    const panel = document.activeElement?.closest?.(".inspector, .fig-inspector, .theme-panel");
    if (!panel || document.querySelector(".scrim")) return;
    const items = tabbables(panel);
    const at = items.indexOf(document.activeElement);
    if (at < 0 || !(event.shiftKey ? at === 0 : at === items.length - 1)) return;
    event.preventDefault();
    items[event.shiftKey ? items.length - 1 : 0]?.focus();
  });
  // Edits go as the page does. Ones that cannot (the studio is out of reach) would be lost
  // with it: while there are any, the browser asks first.
  // A window closing tells the studio, so the others see it go at once.
  addEventListener("pagehide", () => { navigator.sendBeacon?.(workspace.url("/api/leave"), JSON.stringify({ client: workspace.client })); });
  addEventListener("beforeunload", (event) => {
    for (const session of workspace.sessions.values()) session.push();
    if ([...workspace.sessions.values()].some((session) => session.pendingLocal || session.sourceDraft != null || ((session.held || session.unread || session.gone) && session.unsaved))) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  workspace.connect();
  // Looked at again (back from another app, the Mac woken), the studio is tried at once.
  addEventListener("focus", () => workspace.wake());
  document.addEventListener("visibilitychange", () => { if (!document.hidden) workspace.wake(); });
  renderPeople();
  const first = SETTINGS.file || info.start;
  const tabsToOpen = [...new Set([...workspace.rememberedTabs().filter((file) => info.documents.some((item) => item.file === file) || file === first), ...(first ? [first] : [])])];
  for (const file of tabsToOpen) {
    try { await workspace.open(file, { activate: file === first || (!first && file === tabsToOpen[tabsToOpen.length - 1]) }); }
    catch (error) { toast(`Could not open ${file}: ${error.message}`, { kind: "error", icon: "error" }); }
  }
  settled();
  renderViews();
  if (remembered("side", "") && info.assistant) side.show(remembered("side", ""));
  // The document shows drawn, words and all, rather than filling in: its first drawing
  // and the faces it uses are waited for (a moment at most).
  const shown = workspace.active;
  if (loading && shown) {
    const drawn = shown.drawn ? null : new Promise((done) => shown.on("drawn", done));
    await Promise.race([
      (async () => { await drawn; await new Promise(requestAnimationFrame); await document.fonts?.ready; })(),
      new Promise((done) => setTimeout(done, 1200)),
    ]);
  }
  loading?.remove();
}

function inField(event) {
  return /^(INPUT|TEXTAREA|SELECT)$/.test(event.target?.tagName || "") || Boolean(event.target?.isContentEditable);
}

// Edit › Undo, Redo, Delete and Select All on the words of the field being typed in: its
// own, as its keys are. Delete takes the words chosen, and nothing with none chosen.
function editField(field, name) {
  if (name === "undo" || name === "redo") { document.execCommand(name); return; }
  if (name === "select-all") { if (field.isContentEditable) document.execCommand("selectAll"); else field.select(); return; }
  if (chosenIn(field)) document.execCommand("delete");
}

// Words chosen in a field typed in, not the caret alone.
function chosenIn(field) {
  return field.isContentEditable ? !getSelection().isCollapsed : field.selectionStart !== field.selectionEnd;
}

// A key pressed where the keys are, as if typed (Edit › Delete is ⌫ there): `mod` is ⌘ on a
// Mac, Control elsewhere, as the editors take either.
function pressKey({ key, mod = false }) {
  const mac = /Mac|iP/.test(navigator.platform);
  const code = key.length === 1 ? `Key${key.toUpperCase()}` : key;
  (document.activeElement || document.body).dispatchEvent(new KeyboardEvent("keydown", {
    key, code, metaKey: mod && mac, ctrlKey: mod && !mac, bubbles: true, cancelable: true }));
}

// Words being typed there: a text field, a text area or words edited in place -- not a
// switch, a slider or a pop-up, which take no words.
function typingIn(node) {
  if (!node) return false;
  if (node.isContentEditable || node.tagName === "TEXTAREA") return true;
  return node.tagName === "INPUT" && /^(text|search|email|url|tel|password|number|)$/.test(node.type || "");
}

// Keys typed with nothing yet to take them (a document just made, its editor still on its
// way), held, in order: each {text} or {key, shift}, as an editor's early keys are. Not
// those typed in a field, or with ⌘; and not for long, should nothing come to take them.
function holdKeys() {
  const keys = [];
  const hold = (event) => {
    if (event.metaKey || event.ctrlKey || event.isComposing || inField(event)) return;
    const key = event.key;
    if ([...key].length === 1) keys.push({ text: key });
    else if (["Backspace", "Delete", "Enter", "Escape"].includes(key)) keys.push({ key, shift: event.shiftKey });
    else return;
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  document.addEventListener("keydown", hold, true);
  const timer = setTimeout(() => stop(), 10000);
  const stop = () => { clearTimeout(timer); document.removeEventListener("keydown", hold, true); };
  return { keys, stop };
}

// Keys held (holdKeys) typed again, where the page now has the keys: into the field typed
// in, or to the page for its editor to take as it takes a key.
function typeAgain(keys) {
  for (const key of keys) {
    const target = document.activeElement || document.body;
    if (inField({ target }) && key.text) { document.execCommand("insertText", false, key.text); continue; }
    if (inField({ target }) && key.key === "Backspace") { document.execCommand("delete"); continue; }
    target.dispatchEvent(new KeyboardEvent("keydown", { key: key.text ?? key.key, shiftKey: Boolean(key.shift), bubbles: true, cancelable: true }));
  }
}

// A folder in the home folder as the Finder's Go menu says it: ~/Documents/talks.

function markIcon() {
  const node = icon("info");
  node.firstChild.setAttribute("d", "M3 4.5h4v7H3zM9 4.5h4v3H9zM9 9.5h4v2H9zM7 8h2");
  node.setAttribute("stroke-width", "1.6");
  return node;
}

// Copied, its button says so where it is -- a tick a moment, as a Mac's does -- not in a note
// (which waits under a sheet it is in); not copied, its words are chosen to copy by hand.
export function copyable(text) {
  const code = h("code", {}, text);
  const button = ui.button("", async () => {
    try {
      await navigator.clipboard.writeText(text);
      clear(button, icon("check"));
      button.title = "Copied";
      setTimeout(() => { clear(button, icon("copy")); button.title = "Copy"; }, 1500);
    } catch {
      getSelection().selectAllChildren(code);
      button.title = "Couldn’t copy: the command is chosen, press ⌘C";
    }
  }, { kind: "ghost", icon: "copy", small: true, title: "Copy" });
  return h("div.copyable", {}, code, button);
}

// Kinds the studio offers to make: all of them, unless whoever started it said fewer.
const offers = (workspace, kind) => (workspace.info.kinds || []).some((item) => item.name === kind && item.offered !== false);

function newMenu(anchor, workspace) {
  const open = workspace.documents.filter((item) => !workspace.sessions.has(item.file));
  menu(anchor, [
    { title: "New" },
    ...[
      { icon: "deck", label: "Deck", hint: "Slides for a talk", run: () => askName(workspace, "deck", UNTITLED.deck), kind: "deck" },
      { icon: "figure", label: "Figure", hint: "A diagram laid out automatically", run: () => askName(workspace, "figure", UNTITLED.figure), kind: "figure" },
      { icon: "theme", label: "Theme", hint: "Fonts, colours and lines", run: () => askName(workspace, "theme", UNTITLED.theme), kind: "theme" },
    ].filter((item) => offers(workspace, item.kind)),
    ...(open.length ? ["-", { title: "Open" }, ...open.slice(0, 20).map((item) => ({ icon: KIND_ICONS[item.kind] || "file", label: docName(item.file), note: item.file.includes("/") ? item.file.split("/").slice(0, -1).join("/") : "", hint: item.title, run: () => workspace.open(item.file) }))] : []),
  ]);
}

export function askName(workspace, kind, suggestion) {
  const taken = new Set(workspace.documents.map((item) => item.file.toLowerCase()));
  // A name, as a Mac app asks for one: the file's extension is the studio's business.
  const fileOf = (name) => (/\.(ya?ml|json)$/i.test(name) ? name : `${name}.yaml`);
  const stem = suggestion.replace(/\.(ya?ml|json)$/i, "");
  let name = stem;
  for (let n = 2; taken.has(fileOf(name).toLowerCase()); n++) name = `${stem} ${n}`;
  const input = ui.input({ value: name });
  const problem = h("div.field-problem", { hidden: true });
  // A name already used is said at once, and nothing is opened or overwritten.
  const check = () => {
    const file = input.value.trim();
    const why = !file ? "Enter a name." : /[/\\:]/.test(file) ? "A name can’t contain / \\ or :."
      : taken.has(fileOf(file).toLowerCase()) ? `“${file}” is already used in this folder. Choose a different name.` : "";
    problem.textContent = why;
    problem.hidden = !why;
    return !why;
  };
  input.addEventListener("input", () => { if (!problem.hidden) check(); });
  const go = () => {
    if (!check()) { input.focus(); return false; }
    workspace.create(kind, fileOf(input.value.trim())).catch((error) => toast(error.message, { kind: "error", icon: "error" }));
    return true;
  };
  input.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); if (go()) box.close(); } });
  const kindTitle = (workspace.info.kinds || []).find((item) => item.name === kind)?.title || kind.charAt(0).toUpperCase() + kind.slice(1);
  const box = dialog({ title: `New ${kindTitle}`, body: [ui.field("Name", input, { hint: "Saved in this folder" }), problem],
    actions: [{ label: "Cancel" }, { label: "Create", kind: "primary", run: go }] });
  // The keys are the name's at once: a key typed straight after the menu's click is its first
  // letter. (And again once the menu that asked has closed, should it have taken them back.)
  input.focus();
  input.select();
  setTimeout(() => { if (document.activeElement !== input && box && input.isConnected) input.focus(); }, 30);
}

// File › Rename… and File › Duplicate: a name for the document's file, asked in a sheet as
// New asks one -- its folder and its ending (".theme.yaml") kept -- then renamed on disk (its
// tab follows, as one renamed in the Finder does) or copied there and opened.
export function nameDocument(workspace, file, { copy = false } = {}) {
  const base = file.split("/").pop();
  const folder = file.slice(0, file.length - base.length);
  const ending = /(\.theme)?\.(ya?ml|json)$/i.exec(base)?.[0] || ".yaml";
  const fileOf = (name) => `${folder}${name}${ending}`;
  const taken = new Set(workspace.documents.map((item) => item.file.toLowerCase()).filter((name) => copy || name !== file.toLowerCase()));
  const stem = docName(file);
  let suggested = copy ? `${stem} copy` : stem;
  for (let n = 2; copy && taken.has(fileOf(suggested).toLowerCase()); n++) suggested = `${stem} copy ${n}`;
  const input = ui.input({ value: suggested });
  const problem = h("div.field-problem", { hidden: true });
  const check = () => {
    const name = input.value.trim();
    const why = !name ? "Enter a name." : /[/\\:]/.test(name) ? "A name can’t contain / \\ or :."
      : taken.has(fileOf(name).toLowerCase()) ? `“${name}” is already used in this folder. Choose a different name.` : "";
    problem.textContent = why;
    problem.hidden = !why;
    return !why;
  };
  input.addEventListener("input", () => { if (!problem.hidden) check(); });
  const go = () => {
    if (!check()) { input.focus(); return false; }
    const to = fileOf(input.value.trim());
    if (!copy && to === file) return true;
    workspace.api(copy ? "/api/duplicate" : "/api/rename", { file, to, client: workspace.client, who: workspace.me })
      .then(async (result) => {
        if (copy) { await workspace.refreshDocuments(); await workspace.open(result.file); }
        else { workspace.renamed(file, result.file); await workspace.refreshDocuments(); }
      })
      .catch((error) => toast(`${copy ? "Not duplicated" : "Not renamed"}: ${error.message}`, { kind: "error", icon: "error", seconds: 6 }));
    return true;
  };
  input.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); if (go()) box.close(); } });
  const box = dialog({ title: copy ? `Duplicate “${stem}”` : `Rename “${stem}”`, body: [ui.field("Name", input, { hint: copy ? "Saved beside it, in this folder" : "" }), problem],
    actions: [{ label: "Cancel" }, { label: copy ? "Duplicate" : "Rename", kind: "primary", run: go }] });
  input.focus();
  input.select();
}

// Words for Terminal as typed there: in single quotes when they hold anything a shell reads.
const shellWords = (text) => (/^[\w@%+=:,./~-]+$/.test(text) ? text : `'${text.replace(/'/g, "'\\''")}'`);

export function connectDialog(workspace) {
  const name = ui.input({ value: workspace.me.name, placeholder: "Your name, as others see it", onChange: (value) => workspace.setName(value.trim()) });
  // Each a whole command to paste: the folder to go to first, then the agent told, once,
  // where the studio's tools are.
  dialog({ title: "Work with Agents", body: [
    h("p", {}, "In Terminal, go to this folder and add Flexo Studio to your agent, once. Then ask the agent there for what you want: its changes appear here as it makes them."),
    ui.field("This Folder", copyable(`cd ${shellWords(String(workspace.info.folder || "."))}`)),
    ui.field("Claude Code", copyable(`claude mcp add flexo-studio -- ${MCP}`)),
    ui.field("Codex", copyable(`codex mcp add flexo-studio -- ${MCP}`)),
    ui.field("Other MCP Clients", copyable(MCP)),
    ui.field("Your Name", name),
  ], actions: [{ label: "Done", kind: "primary" }] });
}

// Every key the studio answers to, by what it works on, as a Mac app's Help lists them. A
// row marked `app` is the Mac app's menus' own (a browser keeps those keys for itself).
const SHORTCUTS = [
  ["General", [["⌘ K", "Command Palette (Except While Typing)"], ["⌘ F", "Find", "app"], ["⌘ J", "Show or Hide the Assistant"], ["⌥ ⌘ A", "Show or Hide Activity"],
    ["⌘ Z", "Undo"], ["⇧ ⌘ Z", "Redo"], ["⌥ ⌘ Z", "Show History"],
    ["⌘ S", "Save (Documents Also Save as You Work)"], ["⇧ ⌘ S", "Duplicate the Document"], ["⌘ N", "New Deck", "app"], ["⌘ W", "Close Tab", "app"],
    ["⇧ ⌘ ] [", "Next or Previous Tab"], ["⌥ ⌘ R", "Show in Finder", "app"],
    ["⌥ ⌘ I", "Go to the Inspector (Esc: Back)"], ["? ⌘ /", "Keyboard Shortcuts"]]],
  ["Slides", [["⇧ ⌘ N", "New Slide"], ["↑ ↓ PgUp PgDn", "Previous or Next Slide"], ["Home End", "First or Last Slide"],
    ["⌘ D", "Duplicate"], ["⌘ ↩", "Present"], ["⌥ ⌘ P", "Play Slideshow", "app"], ["⌥ ⌘ ↩", "Play from Start"],
    ["⌘ + −", "Zoom In or Out (or Pinch, or ⌘-Scroll)"], ["⌘ 0", "Actual Size"], ["⇧ ⌘ 0", "Fit Slide"]]],
  ["In the Slide List", [["↩", "New Slide"], ["⇧ ↑ ↓", "Select the Slide Above or Below Too"], ["⌘ A", "Select All Slides"], ["⌫", "Delete"],
    ["⌘ X", "Cut"], ["⌘ C", "Copy"], ["⌘ V", "Paste"], ["⌥ ↑ ↓", "Move the Slides Up or Down"]]],
  ["Objects on a Slide", [["⇥", "Next Title or Object (⇧⇥: Previous)"], ["↩", "Edit Text, First Cell or First Shape"], ["⌘ A", "Select All Objects"], ["⇧ or ⌘ Click", "Select One More (or One Less)"], ["Drag", "Select the Objects It Touches (from an Empty Spot)"], ["Esc", "Deselect"], ["⌫", "Delete"], ["⌘ D", "Duplicate"],
    ["⌘ X", "Cut"], ["⌘ C", "Copy"], ["⌘ V", "Paste"], ["⌘ B", "Bold (All Its Words)"], ["⌘ I", "Italic (All Its Words)"], ["Type", "Type Over a Chosen Text’s Words"], ["↑ ↓", "Previous or Next Object"], ["⌥ ↑ ↓", "Move Up or Down"], ["⌥ ← →", "Move to the Column Beside It"]]],
  ["While Typing", [["⌘ B", "Bold"], ["⌘ I", "Italic"], ["⌘ K", "Link"], ["⌘ E", "Code"], ["⌥ ⌘ E", "Inline Equation"], ["⌃ ⇥", "Go to the Format Bar (Esc: Back)"],
    ["↩", "New Line (in a List: New Item; in a Table: the Cell Below)"], ["⇧ ↩", "New Line in a List’s Item or a Cell (or ⌥ ↩)"],
    ["⇥", "In a List: Indent (⇧⇥: Outdent)"], ["⇥", "Elsewhere: Next Title, Text, Object, Caption or Cell (⇧⇥: Previous)"], ["Esc or ⌘ ↩", "Done"]]],
  ["Figures", [["A", "Add Shape"], ["C", "Connect"], ["G", "Group the Selected Shapes"], ["⇥", "Next Shape (⇧⇥: Previous), Also While Typing a Label"], ["⇧ or ⌘ Click", "Select One More Shape (or One Less)"],
    ["Drag", "Select the Shapes It Touches (from an Empty Spot, in a Figure File)"], ["⌘ A", "Select All Shapes"], ["← → ↑ ↓", "Select the Shape That Way"],
    ["⌥ or ⇧ ← → ↑ ↓", "Move the Shape That Way, Among the Others"], ["↩", "Edit Label (Then ↩: New Line; Esc or ⌘ ↩: Done)"],
    ["+ Drag", "Draw a Line from a Shape’s + to Another Shape"], ["⌥ Drag", "Copy the Shape to Where It Is Let Go"], ["⌘ Drag", "Place a Handle Freely, Without Snapping"],
    ["Double-Click", "Fit a Shape to Its Words (on a Corner Handle)"], ["⌘ X", "Cut Shapes"], ["⌘ C", "Copy Shapes"], ["⌘ V", "Paste Shapes"],
    ["⌘ D", "Duplicate Shape"], ["⌫", "Delete Shape"], ["Esc", "Deselect"], ["⌘ + −", "Zoom In or Out (a Figure File)"], ["⌘ 0", "Actual Size (a Figure File)"], ["⇧ ⌘ 0", "Zoom to Fit (a Figure File)"]]],
  ["Presenting", [["→ Space ↩", "Next Build or Slide"], ["PgDn", "Next (a Clicker’s Forward)"], ["← ⌫", "Previous"], ["PgUp", "Previous (a Clicker’s Back)"], ["Home End", "First or Last Slide"], ["0–9 ↩", "Go to a Slide"],
    ["X", "Show or Hide the Presenter View"], ["B W", "Black or White Screen"], ["Esc", "End the Show"]]],
];

// The first control of the document's inspector (a figure's, a theme's settings), its ring
// shown: put there by the keys. Esc there (not taken by a control: a menu, a field put back)
// goes back to where the keys were, as a deck's inspector does.
function toInspector() {
  const view = [...document.querySelectorAll(".views > *")].find((node) => !node.hidden);
  const panel = view?.querySelector(".inspector, .fig-inspector, .theme-panel");
  const first = panel && [...panel.querySelectorAll("button:not(:disabled), input, select, textarea, [contenteditable=true], [tabindex='0']")]
    // (Words typed as they look -- a contenteditable -- say -1 and still take the keys.)
    .find((node) => node.offsetParent && (node.tabIndex >= 0 || node.isContentEditable));
  if (!first) return;
  const before = document.activeElement;
  first.focus({ focusVisible: true });
  first.dataset.keyed = "";
  first.addEventListener("blur", () => { delete first.dataset.keyed; }, { once: true });
  const back = (event) => {
    if (event.key !== "Escape" || event.defaultPrevented || document.querySelector(".menu, .popover, .scrim")) return;
    event.preventDefault();
    done();
    if (before?.isConnected && before !== document.body && !panel.contains(before)) before.focus({ preventScroll: true });
    else document.activeElement?.blur();
  };
  const left = (event) => { if (!panel.contains(event.relatedTarget)) done(); };
  const done = () => { panel.removeEventListener("keydown", back); panel.removeEventListener("focusout", left); };
  panel.addEventListener("keydown", back);
  panel.addEventListener("focusout", left);
}

function shortcutsDialog() {
  // One keycap a chord, as a Mac menu shows it (⇧⌘N): modifiers go with the keys after
  // them, and keys given side by side ("↑ ↓", "Home End") are each a keycap of their own.
  // "or" between modifiers ("⌥ or ⇧ ← →") is a word between keycaps, the modifiers then
  // each a keycap of their own and the keys after them too; "Click" (and "Drag",
  // "Double-Click", "Type") is a word, after its modifier's keycap ("⇧ Click").
  const chords = (keys) => {
    const out = [];
    const words = keys.split(" ").filter(Boolean);
    const alone = words.includes("or");
    let held = "";
    for (const key of words) {
      if (/^[⌘⇧⌥⌃]$/.test(key)) { if (alone) out.push({ key }); else held += key; }
      else if (["or", "Click", "Drag", "Double-Click", "Type"].includes(key)) { if (held) out.push({ key: held }); held = ""; out.push({ word: key === "or" ? "or" : key.toLowerCase() }); }
      else out.push({ key: held + key });
    }
    return out;
  };
  const row = (keys, what) => h("div.shortcut", {}, h("span", {}, what), h("span.shortcut-keys", {}, chords(keys).map((part) => (part.word ? h("span.shortcut-word", {}, part.word) : h("span.kbd", {}, part.key)))));
  const app = Boolean(window.pywebview);
  dialog({ title: "Keyboard Shortcuts", wide: true, body: [h("div.shortcut-groups", {}, SHORTCUTS.map(([title, rows]) =>
    h("div.shortcuts", {}, h("div.section-title", {}, title), rows.filter(([, , only]) => app || only !== "app").map(([keys, what]) => row(keys, what)))))],
  // Closed as a Mac's sheet is: by its Done (Return, Esc), not an ×.
  actions: [{ label: "Done", kind: "primary" }] });
}

// -- the side panel: Claude and activity --------------------------------------------

class SidePanel {
  constructor(workspace) {
    this.workspace = workspace;
    this.open = null;
    this.assistant = new AssistantPanel(workspace);
    this.tabs = h("div.side-tabs");
    this.body = h("div.side-body");
    this.node = h("aside.side", { hidden: true }, h("div.side-head", {}, this.tabs, h("div.spacer"),
      ui.button("", () => this.hide(), { kind: "ghost", icon: "close", small: true, title: "Close" })), this.body);
    this.activityList = h("div.activity-list.scroll-thin");
    workspace.on("activity", () => { if (this.open === "activity") this.renderActivity(); });
  }

  toggle(which) { if (this.open === which) this.hide(); else this.show(which); }

  show(which) {
    this.open = which;
    remember("side", which);
    this.node.hidden = false;
    clear(this.tabs,
      h(`button.side-tab${which === "assistant" ? ".on" : ""}`, { type: "button", onclick: () => this.show("assistant") }, icon("sparkle"), "Assistant"),
      h(`button.side-tab${which === "activity" ? ".on" : ""}`, { type: "button", onclick: () => this.show("activity") }, icon("activity"), "Activity"));
    if (which === "assistant") { clear(this.body, this.assistant.node); this.assistant.focus(); }
    else { this.workspace.unseen = 0; this.workspace.emit("activity"); this.renderActivity(); clear(this.body, this.activityList); }
    document.body.classList.toggle("side-open", true);
    this.workspace.emit("side");
  }

  hide() {
    if (this.node.contains(document.activeElement)) this.assistant.giveBack();
    this.open = null;
    remember("side", "");
    this.node.hidden = true;
    document.body.classList.remove("side-open");
    this.workspace.emit("side");
  }

  renderActivity() {
    const entries = [...this.workspace.activity].reverse();
    clear(this.activityList, entries.length ? entries.map((entry) => h("button.activity-row", { type: "button", onclick: () => this.workspace.goTo(entry.file, entry.where) },
      avatar(entry.who, { size: 22 }),
      // Who did what, and how many times, one sentence; where, under it.
      h("span.activity-text", {}, h("span", {}, h("b", {}, nameOf(entry.who)), " ", entry.text, entry.count > 1 ? h("span.times", {}, `\u00a0×${entry.count}`) : null),
        h("span.activity-where", {}, [entry.file && docName(entry.file), entry.where?.label].filter(Boolean).join(" · "))),
      h("span.activity-time", {}, ago(entry.at)))) : h("div.empty", {}, "No activity yet"));
  }
}

// -- the command palette --------------------------------------------------------------

// The palette open now, closed (⌘K again, or a menu command run while it is open).
let closePalette = () => {};

// A deck's slides by their words, for Find: each slide's words as one line -- what was typed
// in it (titles, text, lists, labels, captions, cells, notes), not its settings -- markup aside.
const WORDS = new Set(["title", "subtitle", "words", "text", "label", "caption", "callout", "quote", "by", "author", "date", "notes", "footnotes",
  "bullets", "numbered", "items", "rows", "header", "cells", "value", "code", "equation", "footer", "name"]);
// (`named`: but for the words the slide is named by in the palette -- its title, or a
// statement's words -- which its row says already.)
function slideWords(slide, { named = false } = {}) {
  const words = [];
  const walk = (value, key) => {
    if (typeof value === "string") { if (WORDS.has(key) && /\p{L}/u.test(value)) words.push(value); }
    else if (Array.isArray(value)) value.forEach((item) => walk(item, key));
    else if (value && typeof value === "object") for (const [name, item] of Object.entries(value)) walk(item, name);
  };
  const name = slide?.words ? "words" : "title";
  walk(named && slide && typeof slide === "object" ? Object.fromEntries(Object.entries(slide).filter(([key]) => key !== name)) : slide, "");
  return words.join(" · ").replace(/\[([^\]]*)\]\{[^}]*\}/g, "$1").replace(/\*\*|[*`]/g, "").replace(/\s+/g, " ");
}

export function palette(workspace, { find = false } = {}) {
  if (document.querySelector(".palette")) return;
  const session = workspace.active;
  const own = session ? session.commands() : [];
  // Words being typed (on the slide, in a field): the Edit menu's Cut, Copy and Paste are for
  // them, as the field's own ⌘X, ⌘C and ⌘V are (run once the palette has given the keys back).
  const field = document.activeElement?.isContentEditable || /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName || "") ? document.activeElement : null;
  const chosen = !field ? "" : field.isContentEditable ? String(getSelection()) : field.value.slice(field.selectionStart ?? 0, field.selectionEnd ?? 0);
  const pasteWords = () => navigator.clipboard?.readText().then((text) => { if (text) document.execCommand("insertText", false, text); })
    .catch(() => toast("Paste with ⌘V: the studio may not read the clipboard here.", { icon: "paste", seconds: 3 }));
  // The document's commands first, then the studio's; places to go (a deck's slides, other
  // documents) last, and all of them: none is left out of a long list.
  const commands = [
    ...own.filter((command) => !command.later),
    ...(field ? [
      { icon: "cut", label: "Cut", keys: "⌘X", disabled: !chosen, hint: chosen ? "" : "Choose the words first", run: () => document.execCommand("cut") },
      { icon: "copy", label: "Copy", keys: "⌘C", disabled: !chosen, hint: chosen ? "" : "Choose the words first", run: () => document.execCommand("copy") },
      { icon: "paste", label: "Paste", keys: "⌘V", run: pasteWords },
    ] : []),
    // The Edit menu's, by name: greyed with nothing to undo, as the menu's are.
    ...(session ? [
      { icon: "undo", label: "Undo", keys: "⌘Z", disabled: !session.past.length, hint: session.past.length ? session.said(session.past[session.past.length - 1]).text : "Nothing to undo", run: () => workspace.command("undo") },
      { icon: "redo", label: "Redo", keys: "⇧⌘Z", disabled: !session.future.length, hint: session.future.length ? session.said(session.future[session.future.length - 1]).text : "Nothing to redo", run: () => workspace.command("redo") },
      { icon: "history", label: "Show History", keys: "⌥⌘Z", disabled: !session.past.length && !session.future.length, hint: session.past.length || session.future.length ? "" : "No changes yet", run: () => workspace.command("history") },
    ] : []),
    // The document itself, as the File menu has it.
    ...(session ? [
      { icon: "pencil", label: "Rename…", hint: `Rename “${docName(session.file)}”`, run: () => nameDocument(workspace, session.file) },
      { icon: "duplicate", label: "Duplicate Document…", keys: "⇧⌘S", hint: `A copy of “${docName(session.file)}”`, run: () => nameDocument(workspace, session.file, { copy: true }) },
      ...(window.pywebview?.api?.show_in_finder ? [{ icon: "folder", label: "Show in Finder", keys: "⌥⌘R", run: () => window.pywebview.api.show_in_finder(`${String(workspace.info.folder).replace(/\/+$/, "")}/${session.file}`) }] : []),
      { icon: "close", label: "Close Tab", keys: window.pywebview ? "⌘W" : undefined, hint: `Close “${docName(session.file)}”`, run: () => workspace.close(session.file) },
    ] : []),
    { icon: "sparkle", label: workspace.side?.open === "assistant" ? "Hide Assistant" : "Show Assistant", keys: "⌘J", run: () => workspace.side?.toggle("assistant") },
    { icon: "activity", label: workspace.side?.open === "activity" ? "Hide Activity" : "Show Activity", keys: "⌥⌘A", run: () => workspace.side?.toggle("activity") },
    { icon: "target", label: workspace.follow ? "Stop Following Agents" : "Follow Agents", run: () => workspace.setFollow(!workspace.follow) },
    { icon: "collaborate", label: "Work with Agents…", run: () => connectDialog(workspace) },
    { icon: "keyboard", label: "Keyboard Shortcuts", keys: "⌘/", run: () => shortcutsDialog() },
    // Appearance, as the toolbar's button offers it: the one in use is there, greyed.
    ...[["auto", "Automatic"], ["light", "Light"], ["dark", "Dark"]].map(([value, name]) => ({ icon: value === "dark" ? "moon" : value === "light" ? "sun" : "appearance",
      label: `Appearance: ${name}`, disabled: remembered("theme", "auto") === value, hint: remembered("theme", "auto") === value ? "In use" : "", run: () => workspace.appearance?.(value) })),
    ...[
      // Each said as the New menu says it.
      { icon: "deck", label: "New Deck", hint: "Slides for a talk", run: () => askName(workspace, "deck", UNTITLED.deck), kind: "deck" },
      { icon: "figure", label: "New Figure", hint: "A diagram laid out automatically", run: () => askName(workspace, "figure", UNTITLED.figure), kind: "figure" },
      { icon: "theme", label: "New Theme", hint: "Fonts, colours and lines", run: () => askName(workspace, "theme", UNTITLED.theme), kind: "theme" },
    ].filter((item) => offers(workspace, item.kind)),
    ...workspace.order.filter((file) => file !== session?.file).map((file) => ({ icon: "file", label: `Go to ${docName(file)}`, run: () => workspace.activate(file) })),
    ...workspace.documents.filter((item) => !workspace.sessions.has(item.file)).map((item) => ({ icon: KIND_ICONS[item.kind] || "file", label: `Open ${docName(item.file)}`, hint: item.title, run: () => workspace.open(item.file) })),
    ...own.filter((command) => command.later),
  ];
  // Slides found by their words as well as their titles (Edit › Find… opens the palette to
  // find words): each with the words around what was found, the title its row names aside.
  const slides = Array.isArray(session?.doc?.slides) ? session.doc.slides.map((slide) => [slideWords(slide), slideWords(slide, { named: true })]) : [];
  const foundOn = (query) => {
    if (query.length < 2) return [];
    return slides.flatMap(([all, rest], index) => {
      if (!all.toLowerCase().includes(query)) return [];
      const named = own.find((command) => command.later && command.label.startsWith(`Slide ${index + 1}:`))?.label;
      const words = named ? rest : all, at = words.toLowerCase().indexOf(query);
      // (Whole words, not a word's last letters.)
      let from = Math.max(0, at - 24), to = Math.min(words.length, at + query.length + 40);
      if (from && words.indexOf(" ", from) >= 0 && words.indexOf(" ", from) < at) from = words.indexOf(" ", from) + 1;
      if (to < words.length && words.lastIndexOf(" ", to) > at + query.length) to = words.lastIndexOf(" ", to);
      const note = at < 0 ? "" : `${from ? "…" : ""}${words.slice(from, to).trim()}${to < words.length ? "…" : ""}`;
      return [{ icon: "slide", label: named || `Slide ${index + 1}`, note, later: true, run: () => session.reveal?.({ page: index + 1 }) }];
    }).slice(0, 12);
  };
  const input = h("input.palette-input", { placeholder: find && slides.length ? "Find words on the slides, or a command…" : session ? "Search commands, slides, files…" : "Search commands and files…" });
  input.spellcheck = false;
  const list = h("div.command-list.scroll-thin");
  let shown = [];
  let index = 0;
  // A command is found by its name: the words typed in it, at a word's start best; each
  // word typed starting one of its words; or the first letters of its words ("ns", New
  // Slide). What it says of itself counts only for words typed whole. Lower ranks
  // higher: a label starting with what is typed, then a word of it starting so, then a word
  // holding it; those alike keep the list's order (Export's PDF, PowerPoint, Images; New
  // Slide's layouts; what is typed in before what may be added) -- never their length. Null
  // when it is not found.
  const wordsOf = (text) => text.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  const score = (command, query) => {
    const label = command.label.toLowerCase(), names = wordsOf(label), said = wordsOf((command.hint || "").toLowerCase());
    const at = label.indexOf(query);
    const starts = at === 0 || /[^\p{L}\p{N}]/u.test(label[at - 1] ?? "");
    if (at >= 0 && starts) return at === 0 ? -30 : -20;
    // Inside a word, a few letters are as often chance ("cut" in Shortcuts) as meant; more
    // ("point" in PowerPoint) are meant.
    if (at >= 0 && query.length > 3) return -10;
    const typed = wordsOf(query);
    if (typed.every((word) => names.some((name) => name.startsWith(word)))) return 0;
    if (typed.every((word) => names.some((name) => name.startsWith(word)) || said.some((name) => name.startsWith(word)))) return 10;
    // The first letters of its words, in order: never letters strung across them.
    const initials = names.map((name) => name[0]).join(""), letters = query.replace(/\s+/g, "");
    if (letters.length < 2) return null;
    let position = 0, total = 0;
    for (const ch of letters) {
      const found = initials.indexOf(ch, position);
      if (found < 0) return null;
      total += found - position;
      position = found + 1;
    }
    return 20 + total * 0.1;
  };
  const render = () => {
    const query = input.value.trim().toLowerCase();
    // A place to go (a slide) found as well as a command, after it: "slide" is New Slide first.
    const ranked = (command) => { const found = score(command, query); return found === null ? null : found + (command.later ? 15 : 0); };
    shown = query ? commands.map((command) => [ranked(command), command]).filter(([s]) => s !== null).sort((a, b) => a[0] - b[0]).map(([, c]) => c) : commands;
    // (A slide found by its title already is not listed again for its words.)
    if (query) shown = [...shown, ...foundOn(query).filter((slide) => !shown.some((command) => command.label === slide.label))];
    index = Math.min(index, Math.max(0, shown.length - 1));
    clear(list, shown.length ? shown.map((command, i) => h(`button.menu-item${i === index ? ".active" : ""}`, { type: "button", title: command.hint || "", "aria-disabled": command.disabled ? "true" : undefined, onmouseenter: () => { index = i; mark(); }, onclick: () => run(command) },
      command.icon ? icon(command.icon) : null, h("span.menu-text", {}, h("span", {}, command.label), command.note ? h("span.menu-hint", {}, command.note) : null),
      command.keys ? h("span.kbd", {}, command.keys) : null)) : h("div.empty", {}, "No results"));
  };
  const mark = () => list.querySelectorAll(".menu-item").forEach((item, i) => { item.classList.toggle("active", i === index); if (i === index) item.scrollIntoView({ block: "nearest" }); });
  // Closed, it gives the keys back where they were, as Spotlight does; a command run then
  // takes them where it goes.
  const before = document.activeElement;
  // Words being typed get their words chosen back too: Bold, run from here, is for them.
  const chosenWords = before?.isContentEditable && getSelection().rangeCount ? getSelection().getRangeAt(0).cloneRange() : null;
  const close = () => {
    if (!scrim.isConnected) return;
    scrim.remove();
    closePalette = () => {};
    const under = [...document.querySelectorAll(".scrim")].pop();
    if (before?.isConnected && before !== document.body && (!under || under.contains(before))) {
      before.focus({ preventScroll: true });
      if (chosenWords && before.contains(chosenWords.startContainer)) { getSelection().removeAllRanges(); getSelection().addRange(chosenWords); }
    }
  };
  // One greyed (Undo with nothing to undo) is shown for what it is, and does nothing.
  const run = (command) => { if (command.disabled) return; close(); command.run(); };
  input.addEventListener("input", () => { index = 0; render(); });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") { event.preventDefault(); index = Math.min(index + 1, shown.length - 1); mark(); }
    else if (event.key === "ArrowUp") { event.preventDefault(); index = Math.max(index - 1, 0); mark(); }
    else if (event.key === "Enter") { event.preventDefault(); event.stopPropagation(); if (shown[index]) run(shown[index]); }
    else if (event.key === "Escape") { event.preventDefault(); close(); }
    // Its one field holds the keys: Tab goes nowhere behind it.
    else if (event.key === "Tab") event.preventDefault();
  });
  const scrim = h("div.scrim.palette-scrim", { onmousedown: (event) => { if (event.target === scrim) close(); } },
    h("div.palette", {}, h("div.palette-head", {}, icon("search"), input), list));
  document.body.append(scrim);
  closePalette = close;
  render();
  input.focus();
}
