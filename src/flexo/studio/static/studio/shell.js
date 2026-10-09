// The studio's frame: open documents as tabs, who is here, what happened, the
// assistant, and the command palette. A kind's editor fills a document's view.

import { h, clear, icon, ui, menu, popover, closeMenu, dialog, toast, tabbables } from "./ui.js";
import { Session } from "./session.js";
import { AssistantPanel, MARK_COLOURS } from "./assistant.js";

const SETTINGS = window.STUDIO || { token: "", file: "" };
const KIND_ICONS = { deck: "deck", figure: "figure", theme: "theme" };
// A new document's name, as a Mac app's: Untitled (Untitled 2, if that is taken).
const UNTITLED = { deck: "Untitled.yaml", figure: "Untitled Figure.yaml", theme: "Untitled Theme.yaml" };
// Each far from the others in hue, the first few most of all (they are given in the order
// people come), and none near the blue of what is chosen here, which is one's own.
const COLOURS = ["#e8590c", "#0ca678", "#d6336c", "#5c940d", "#ae3ec9", "#1098ad", "#f59f00", "#795548"];
const MCP_COMMAND = "claude mcp add flexo-studio -- flexo studio mcp";
const CODEX_COMMAND = "codex mcp add flexo-studio -- flexo studio mcp";

// Each person here has the colour the studio gave them as they came, none shared with
// another here (see given); one not here (in the activity) has one by their id.
const given = new Map();
function give(presence) {
  given.clear();
  for (const entry of presence || []) if (entry?.who?.id && Number.isInteger(entry.colour)) given.set(entry.who.id, entry.colour);
}

export function colourOf(who) {
  if (who?.id === "assistant") return MARK_COLOURS[who.provider || "claude"] || "#6b6b70";
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
      else { history.replaceState(null, "", "?"); this.emit("active", null); }
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
  const tabs = h("nav.tabs.scroll-thin");
  const people = h("div.people");
  const followChip = h("button.chip-toggle", { type: "button", title: "Follow agents as they work", onclick: () => workspace.setFollow(!workspace.follow) }, icon("target"), "Follow");
  const activityButton = ui.button("", () => side.toggle("activity"), { kind: "ghost", icon: "activity", title: "Activity" });
  const activityCount = h("span.badge-count", { hidden: true });
  activityButton.append(activityCount);
  // The assistant -- Claude, ChatGPT or another, whichever is set up (assistant.js) -- a plain
  // button among the others, its mark in colour: the slide stays the brightest thing there is.
  const assistantButton = h("button.btn.assistant-button", { type: "button", title: "Ask the Assistant (⌘J)", onclick: () => side.toggle("assistant") }, icon("sparkle"), h("span.btn-label", {}, "Assistant"));
  // Pressed, it leaves the keys where they were (words being typed, the slide list) until
  // the palette has seen what they are on: its commands are for that.
  const paletteButton = h("button.search-button", { type: "button", "data-keeps-typing": true, onmousedown: (event) => event.preventDefault(), onclick: () => palette(workspace), title: "Command palette (⌘K)" }, icon("search"), h("span", {}, "Search or run a command"), h("span.kbd", {}, "⌘K"));
  // Appearance as a Mac's: Automatic, Light or Dark, the one in use ticked.
  const themeButton = ui.button("", (event) => {
    const now = remembered("theme", "auto");
    const choose = (value) => () => { remember("theme", value); applyTheme(value); showTheme(); };
    menu(event.currentTarget, [{ title: "Appearance" },
      ...[["auto", "Automatic"], ["light", "Light"], ["dark", "Dark"]].map(([value, label]) => ({ label, checked: now === value, run: choose(value) }))], { align: "end" });
  }, { kind: "ghost", title: "Appearance" });
  const showTheme = () => clear(themeButton, icon(remembered("theme", "auto") === "dark" ? "moon" : remembered("theme", "auto") === "light" ? "sun" : "appearance"));
  showTheme();
  const bar = h("header.bar", {},
    h("div.brand", { title: info.folder }, h("div.brand-mark", {}, markIcon())),
    tabs,
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
  // A folder someone else made runs none of its own Python until its person says so.
  const trustBar = h("div.trust-bar", { hidden: true }, icon("warning"),
    h("div.trust-words", {}, h("b", {}, "Python files in this folder haven’t been run. "),
      "Decks in this folder use them to draw plots and figures. Run them only if you trust where the folder came from."),
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
      case "assistant": side.toggle("assistant"); break;
      case "activity": side.toggle("activity"); break;
      case "new": askName(workspace, arg, UNTITLED[arg] || "Untitled.yaml"); break;
      case "close-tab": if (session) workspace.close(session.file); break;
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
  let reporting = null;
  const report = () => {
    if (reporting) return;
    reporting = setTimeout(() => {
      reporting = null;
      const session = workspace.active;
      window.pywebview?.api?.studio_state?.({
        file: session?.file || "", kind: session?.kind || "", title: session?.title || "",
        can_undo: Boolean(session?.past.length), can_redo: Boolean(session?.future.length),
        undo_label: session?.past.length ? session.said(session.past[session.past.length - 1]).text : "",
        redo_label: session?.future.length ? session.said(session.future[session.future.length - 1]).text : "",
        exports: session?.exports || [], present: Boolean(session?.present), saved: session ? session.state === "saved" : true,
        commands: doable(session),
      });
    }, 80);
  };
  // A slide or part chosen changes what can be done; so does a field taking the keys
  // (⌘D is then the field's).
  for (const event of ["status", "active", "opened", "closed", "documents", "focus"]) workspace.on(event, report);
  document.addEventListener("focusin", report);
  document.addEventListener("focusout", report);
  window.addEventListener("pywebviewready", report);
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
  const renderTabs = () => {
    clear(tabs, workspace.order.map((file) => {
      const session = workspace.sessions.get(file);
      const here = workspace.presenceOn(file);
      const tab = h(`div.tab${workspace.active === session ? ".on" : ""}`, {
        title: `${String(workspace.info.folder || "").replace(/\/+$/, "")}/${file}`, onclick: () => workspace.activate(file),
        onauxclick: (event) => { if (event.button === 1) workspace.close(file); },
      },
      icon(KIND_ICONS[session.kind] || "file"),
      h("span.tab-name", {}, tabName(file, session)),
      session.state !== "saved" ? h(`span.tab-dot.${session.state}`, { title: statusWords(session) }) : null,
      here.length ? h("span.tab-people", {}, here.slice(0, 3).map((entry) => h("span.mini", { style: { background: colourOf(entry.who) }, title: nameOf(entry.who) }))) : null,
      h("button.tab-close", { type: "button", title: "Close", onclick: (event) => { event.stopPropagation(); workspace.close(file); } }, icon("close")));
      return tab;
    }), h("button.tab-new", { type: "button", title: "New Document", onclick: (event) => newMenu(event.currentTarget, workspace) }, icon("plus")));
  };

  const renderPeople = () => {
    const others = workspace.others();
    clear(people,
      others.map((entry) => {
        const button = h("button.person", { type: "button", onclick: () => entry.file && workspace.goTo(entry.file, entry.where),
          title: `${nameOf(entry.who)}${entry.doing ? ` · ${entry.doing}` : ""}${entry.file ? ` · ${docName(entry.file)}` : ""}` },
        avatar(entry.who, { ring: entry.who.kind === "agent" && Boolean(entry.doing) }));
        return button;
      }),
      h("button.person.add", { type: "button", title: "Work with agents", onclick: () => connectDialog(workspace) }, icon("collaborate")));
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
    for (const slot of [docLeft, docRight]) slot.inert = unreadable(session);
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
    if (!session) { views.append(welcome); renderWelcome(); }
    clear(docLeft, session ? session.tools : null);
    clear(docCentre, session ? session.inserts : null);
    clear(docRight, session ? session.actions : null);
    renderTabs();
    renderStatus();
  };

  const welcome = h("div.welcome.scroll-thin");
  const renderWelcome = () => {
    const kinds = info.kinds.filter((kind) => kind.offered !== false).map((kind) => kind.name);
    const card = (kind, title, name) => kinds.includes(kind) ? h("button.start-card", { type: "button", onclick: () => askName(workspace, kind, name) },
      h("span.start-icon", {}, icon(KIND_ICONS[kind])), h("span.start-title", {}, title)) : null;
    clear(welcome, h("div.welcome-inner", {},
      h("h1", {}, "New Document"),
      h("div.start-cards", {}, card("deck", "Deck", UNTITLED.deck), card("figure", "Figure", UNTITLED.figure), card("theme", "Theme", UNTITLED.theme)),
      // What is in the folder, under its name (its whole path in the tooltip).
      workspace.documents.length ? h("div.welcome-section", {}, h("h2", { title: info.folder }, String(info.folder).split("/").filter(Boolean).pop() || "This Folder"),
        h("div.doc-list", {}, workspace.documents.map((item) => h("button.doc-row", { type: "button", title: item.file, onclick: () => workspace.open(item.file) },
          icon(KIND_ICONS[item.kind] || "file"), h("span.doc-name", {}, docName(item.file)),
          // One that does not read, or does not draw as written, says so, as the themes' list does.
          item.unread || item.faulty ? h("span.doc-kind.bad", { title: `Open ${docName(item.file)} to see why and put it right` }, item.unread ? "Can’t be read" : "Has problems") : null,
          item.file.includes("/") ? h("span.doc-kind", {}, item.file.split("/").slice(0, -1).join("/")) : null)))) : null));
  };

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
    const mod = event.metaKey || event.ctrlKey;
    const key = event.key.toLowerCase();
    const session = workspace.active;
    if (mod && key === "k") { event.preventDefault(); palette(workspace); return; }
    if (mod && key === "j") { event.preventDefault(); side.toggle("assistant"); return; }
    if (document.querySelector(".scrim, .present")) return;
    if (mod && key === "s") {
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

export function connectDialog(workspace) {
  const name = ui.input({ value: workspace.me.name, placeholder: "Your name, as others see it", onChange: (value) => workspace.setName(value.trim()) });
  dialog({ title: "Work with Agents", body: [
    h("p", {}, "Run one of these once in Terminal, in this folder, then ask the agent for what you want. Its changes appear here as it makes them."),
    ui.field("Claude Code", copyable(MCP_COMMAND)),
    ui.field("Codex", copyable(CODEX_COMMAND)),
    ui.field("Other MCP Clients", copyable("flexo studio mcp")),
    ui.field("Your Name", name),
  ], actions: [{ label: "Done", kind: "primary" }] });
}

// Every key the studio answers to, by what it works on, as a Mac app's Help lists them.
const SHORTCUTS = [
  ["General", [["⌘ K", "Command Palette (Except While Typing)"], ["⌘ J", "Ask the Assistant"], ["⌘ Z", "Undo"], ["⇧ ⌘ Z", "Redo"], ["⌥ ⌘ Z", "Show History"],
    ["⌘ S", "Save (documents also save as you work)"], ["⌥ ⌘ I", "Go to the Inspector (Esc: back)"], ["?", "Keyboard Shortcuts"]]],
  ["Slides", [["⇧ ⌘ N", "New Slide"], ["↩", "New Slide (in the Slide List)"], ["↑ ↓", "Previous or Next Slide"],
    ["⇧ ↑ ↓", "Choose a Run of Slides"], ["Home End", "First or Last Slide"],
    ["⌘ D", "Duplicate"], ["⌘ ↩", "Present"], ["⌥ ⌘ ↩", "Play from Start"],
    ["⌘ + −", "Zoom In or Out (or Pinch, or ⌘-Scroll)"], ["⌘ 0", "Actual Size"], ["⇧ ⌘ 0", "Fit Slide"]]],
  ["Objects on a Slide", [["⇥", "Next Title or Object (⇧⇥: Previous)"], ["↩", "Edit Text, First Cell or First Shape"], ["⌘ A", "Choose All Objects"], ["⇧ or ⌘ Click", "Choose One More (or One Less)"], ["Drag", "From Where Nothing Is: Choose the Objects It Touches"], ["Esc", "Deselect"], ["⌫", "Delete"], ["⌘ D", "Duplicate"],
    ["⌘ X", "Cut"], ["⌘ C", "Copy"], ["⌘ V", "Paste"], ["↑ ↓", "Previous or Next Object"], ["⌥ ↑ ↓", "Move Up or Down"], ["⌥ ← →", "Move to the Next Column"]]],
  ["While Typing", [["⌘ B", "Bold"], ["⌘ I", "Italic"], ["⌘ K", "Link"], ["⌘ E", "Code"], ["⌥ ⌘ E", "Inline Equation"], ["⌃ ⇥", "Go to the Format Bar (Esc: back)"],
    ["↩", "New Item (in a List) or Done (in a Title)"], ["⇥", "In a List: Indent (⇧⇥: Outdent)"],
    ["⇥", "Elsewhere: Next Title, Text, Object or Cell (⇧⇥: Previous)"], ["Esc", "Done"]]],
  ["Figures", [["A", "Add Shape"], ["C", "Connect"], ["G", "Group"], ["⇥", "Next Shape (⇧⇥: Previous)"], ["⇧ or ⌘ Click", "Choose One More Shape (or One Less)"], ["← → ↑ ↓", "Choose the Shape That Way"],
    ["⌥ or ⇧ ← → ↑ ↓", "Move the Shape That Way, Among the Others"], ["↩", "Edit Label (Then ↩: New Line; Esc or ⌘ ↩: Done)"], ["⌫", "Delete Shape"], ["⌘ + −", "Zoom In or Out (a Figure File)"]]],
  ["Presenting", [["→ Space", "Next Build or Slide"], ["←", "Previous"], ["Home End", "First or Last Slide"], ["0–9 ↩", "Go to a Slide"],
    ["X", "Show or Hide the Presenter View"], ["B W", "Black or White Screen"], ["Esc", "End the Show"]]],
];

// The first control of the document's inspector (a figure's, a theme's settings), its ring
// shown: put there by the keys. Esc there (not taken by a control: a menu, a field put back)
// goes back to where the keys were, as a deck's inspector does.
function toInspector() {
  const view = [...document.querySelectorAll(".views > *")].find((node) => !node.hidden);
  const panel = view?.querySelector(".inspector, .fig-inspector, .theme-panel");
  const first = panel && [...panel.querySelectorAll("button:not(:disabled), input, select, textarea, [contenteditable=true], [tabindex='0']")]
    .find((node) => node.offsetParent && node.tabIndex >= 0);
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
  // each a keycap of their own and the keys after them too; "Click" is a word, after its
  // modifier's keycap ("⇧ Click").
  const chords = (keys) => {
    const out = [];
    const words = keys.split(" ").filter(Boolean);
    const alone = words.includes("or");
    let held = "";
    for (const key of words) {
      if (/^[⌘⇧⌥⌃]$/.test(key)) { if (alone) out.push({ key }); else held += key; }
      else if (key === "or" || key === "Click" || key === "Drag") { if (held) out.push({ key: held }); held = ""; out.push({ word: key === "or" ? "or" : key.toLowerCase() }); }
      else out.push({ key: held + key });
    }
    return out;
  };
  const row = (keys, what) => h("div.shortcut", {}, h("span", {}, what), h("span.shortcut-keys", {}, chords(keys).map((part) => (part.word ? h("span.shortcut-word", {}, part.word) : h("span.kbd", {}, part.key)))));
  dialog({ title: "Keyboard Shortcuts", wide: true, body: [h("div.shortcut-groups", {}, SHORTCUTS.map(([title, rows]) =>
    h("div.shortcuts", {}, h("div.section-title", {}, title), rows.map(([keys, what]) => row(keys, what)))))],
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
  }

  hide() {
    this.open = null;
    remember("side", "");
    this.node.hidden = true;
    document.body.classList.remove("side-open");
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

export function palette(workspace) {
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
    { icon: "sparkle", label: "Ask the Assistant", keys: "⌘J", run: () => document.querySelector(".assistant-button")?.click() },
    { icon: "target", label: workspace.follow ? "Stop Following Agents" : "Follow Agents", run: () => workspace.setFollow(!workspace.follow) },
    { icon: "collaborate", label: "Work with Agents…", run: () => connectDialog(workspace) },
    { icon: "keyboard", label: "Keyboard Shortcuts", keys: "?", run: () => shortcutsDialog() },
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
  const input = h("input.palette-input", { placeholder: session ? `Search commands, slides, files…` : "Search commands and files…" });
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
    scrim.remove();
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
  render();
  input.focus();
}
