// The studio's frame: open documents as tabs, who is here, what happened, the
// assistant, and the command palette. A kind's editor fills a document's view.

import { h, clear, icon, ui, menu, popover, closeMenu, dialog, toast } from "./ui.js";
import { Session } from "./session.js";
import { AssistantPanel } from "./assistant.js";

const SETTINGS = window.STUDIO || { token: "", file: "" };
const KIND_ICONS = { deck: "deck", figure: "figure", theme: "theme" };
const COLOURS = ["#e8590c", "#7048e8", "#0ca678", "#d6336c", "#1c7ed6", "#f08c00", "#5c940d", "#ae3ec9"];
const MCP_COMMAND = "claude mcp add flexo-studio -- flexo studio mcp";

export function colourOf(who) {
  if (who?.id === "assistant") return "#d97757";
  let hash = 0;
  for (const ch of String(who?.id || who?.name || "")) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return COLOURS[hash % COLOURS.length];
}

export function avatar(who, { size = 24, ring = false } = {}) {
  const agent = who?.kind === "agent";
  const initials = agent ? null : String(who?.name || "?").split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
  return h("span.avatar", { title: who?.name || "", style: { width: `${size}px`, height: `${size}px`, background: colourOf(who), boxShadow: ring ? `0 0 0 2px var(--panel), 0 0 0 3.5px ${colourOf(who)}` : "" } },
    agent ? icon("sparkle", { weight: "1.3" }) : initials);
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
const docName = (file) => String(file).split("/").pop().replace(/\.(ya?ml|json)$/i, "");

// The word on a document's saving: what is true of it and its file, briefly.
function statusWords(session) {
  const state = session.state;
  if (state === "saved") return "Saved";
  if (state === "saving") return "Saving…";
  if (state === "offline") return "Not saved: can't reach the studio";
  const problem = session.problem || "";
  // The file on disk does not read: "Not saved" only while edits made here wait for it.
  if (session.held) return session.unsaved ? `Not saved: ${problem.replace(/^Can't/, "can't")}` : problem;
  return `Not saved: ${problem.replace(/^.*? could not be saved:\s*/, "")}`;
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
    this.me = { id: person, name: remembered("name", "You"), kind: "person" };
    this.sessions = new Map();
    this.order = [];
    this.active = null;
    this.presence = info.presence || [];
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

  close(file) {
    const session = this.sessions.get(file);
    if (!session) return;
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
    this.close(file);
    try {
      await this.open(file, { activate: active });
      this.order.splice(this.order.indexOf(file), 1);
      this.order.splice(place, 0, file);
      this.remember();
      this.emit("status", this.sessions.get(file));
    } catch (error) { toast(`Could not open ${file}: ${error.message}`, { kind: "error", icon: "error" }); }
  }

  remember() { remember(`tabs:${this.info.folder}`, JSON.stringify(this.order)); }
  rememberedTabs() { try { return JSON.parse(remembered(`tabs:${this.info.folder}`, "[]")); } catch { return []; } }

  async create(kind, name) {
    const result = await this.api("/api/new", { file: name, kind, client: this.client, who: this.me });
    await this.refreshDocuments();
    // Its editor knows it is new (and so ready to be typed in at once).
    this.justMade = result.file;
    return this.open(result.file);
  }

  async refreshDocuments() {
    this.documents = (await this.api(this.url("/api/documents"))).documents;
    this.emit("documents");
  }

  // -- who is where --

  reportFocus(file, where) {
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
    this.me = { ...this.me, name: name || "You" };
    remember("name", this.me.name);
    this.reportFocus(this.active?.file || null, null);
  }

  setFollow(on) { this.follow = on; remember("follow", on ? "1" : "0"); this.emit("follow"); }

  // -- events --

  connect() {
    const source = new EventSource(this.url("/api/events", { client: this.client, person: this.me.id, name: this.me.name }));
    source.onmessage = (message) => this.handle(JSON.parse(message.data));
    source.addEventListener("hello", () => this.emit("online", true));
    source.onerror = () => this.emit("online", false);
    this.source = source;
  }

  handle(event) {
    const session = event.file ? this.sessions.get(event.file) : null;
    switch (event.type) {
      case "doc":
        session?.remote(event);
        if (session && event.client !== this.client) session.emit("remote", event);
        break;
      case "saved":
        session?.saved(event.version);
        // What was wrong with the file is over (it is back, or reads again): so is its word.
        session?.notice?.remove();
        break;
      case "problem":
        if (session) {
          if (session.problem !== event.text && event.text) {
            session.notice?.remove();
            session.notice = toast(event.text, { kind: "error", icon: "error", seconds: 8 });
          }
          session.told(event);
        }
        break;
      case "reopened": this.reopen(event.file, event.kind); break;
      case "depends": if (session) { session.pages.clear(); session.requestDraw(0); } break;
      case "presence": this.presence = event.presence; this.emit("presence"); break;
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
        if (index >= 0) this.activity[index] = entry; else { this.activity.push(entry); if (entry.who?.id !== this.me.id) this.unseen += 1; }
        if (this.activity.length > 300) this.activity.shift();
        this.emit("activity", entry);
        if (this.follow && entry.who?.kind === "agent") this.goTo(entry.file, entry.where, { quiet: true });
        break;
      }
      case "assistant": this.emit("assistant", event); break;
      default: break;
    }
  }

  async goTo(file, where, { quiet = false } = {}) {
    if (!file) return;
    const session = await this.open(file, { activate: true });
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
    clear(root, h("div.fatal", {}, h("h1", {}, "Flexo Studio couldn't start"), h("pre", {}, String(error.message || error))));
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
  const claudeButton = h("button.btn.claude-button", { type: "button", title: "Ask Claude (⌘J)", onclick: () => side.toggle("assistant") }, icon("sparkle"), "Claude");
  const paletteButton = h("button.search-button", { type: "button", onclick: () => palette(workspace), title: "Command palette (⌘K)" }, icon("search"), h("span", {}, "Search or run a command"), h("span.kbd", {}, "⌘K"));
  const themeButton = ui.button("", () => {
    const order = ["auto", "light", "dark"];
    const next = order[(order.indexOf(remembered("theme", "auto")) + 1) % 3];
    remember("theme", next); applyTheme(next); showTheme(); toast(`Appearance: ${{ auto: "Auto", light: "Light", dark: "Dark" }[next]}`, { seconds: 1.5 });
  }, { kind: "ghost", title: "Appearance" });
  const showTheme = () => clear(themeButton, icon(remembered("theme", "auto") === "dark" ? "moon" : remembered("theme", "auto") === "light" ? "sun" : "appearance"));
  showTheme();
  const bar = h("header.bar", {},
    h("div.brand", { title: info.folder }, h("div.brand-mark", {}, markIcon()), h("span.brand-name", {}, "Flexo Studio")),
    tabs,
    h("div.spacer"),
    paletteButton,
    people, followChip,
    h("div.bar-sep"),
    activityButton, themeButton, claudeButton);

  // -- the document bar --
  const docLeft = h("div.docbar-slot");
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
    await session.settled?.();
    session[way]();
  };
  const undo = ui.button("", () => travel("undo"), { kind: "ghost", icon: "undo", title: "Undo (⌘Z)" });
  const redo = ui.button("", () => travel("redo"), { kind: "ghost", icon: "redo", title: "Redo (⇧⌘Z)" });
  const past = ui.button("", (event) => { const session = workspace.active; if (session) historyMenu(event.currentTarget, session); },
    { kind: "ghost", icon: "history", title: "Show History (⌥⌘Z)" });
  const docbar = h("div.docbar", {}, docLeft, h("div.spacer"), status, h("div.bar-group", {}, undo, redo, past), h("div.bar-sep"), docRight);
  // Too wide for the window (or beside the side panel), the bar shows its tools as icons
  // alone, and then its other buttons too, rather than run off the edge.
  const crowded = () => [docbar, docLeft, docRight].some((node) => node.scrollWidth > node.clientWidth + 1);
  const fitDocbar = () => {
    docbar.classList.remove("compact", "tight");
    if (!crowded()) return;
    docbar.classList.add("compact");
    if (crowded()) docbar.classList.add("tight");
  };
  const fitting = new ResizeObserver(fitDocbar);
  for (const node of [docbar, docLeft, docRight]) fitting.observe(node);

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
    ahead.forEach((entry, index) => rows.push(row(entry, { undone: true, run: () => session.redo(ahead.length - index) })));
    const shown = 60;
    for (let index = back.length - 1; index >= Math.max(0, back.length - shown); index -= 1) {
      rows.push(row(back[index], { now: index === back.length - 1, run: () => session.undo(back.length - 1 - index) }));
    }
    if (back.length > shown) rows.push(h("div.history-more", {}, `${back.length - shown} earlier ${back.length - shown === 1 ? "change" : "changes"} not shown`));
    rows.push(h(`button.history-row.start${back.length ? "" : ".now"}`, { type: "button", onclick: go(() => session.undo(back.length)), title: "Undo all changes" },
      h("span.history-mark"), h("span.history-text", {}, "Original")));
    popover(anchor, [h("div.menu-title", {}, "History"), h("div.history", {}, rows)], { align: "end", className: "history-menu" });
  }

  const views = h("main.views");
  const doing = h("div.doing-strip");
  const side = new SidePanel(workspace);
  // A folder someone else made runs none of its own Python until its person says so.
  const trustBar = h("div.trust-bar", { hidden: true }, icon("warning"),
    h("div.trust-words", {}, h("b", {}, "Python files in this folder haven't been run. "),
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
      case "save":
        if (session?.unread) { unread?.mend(); break; }
        session?.saveNow().then(() => toast("Saved", { icon: "check", seconds: 1.2 }),
          (error) => toast(`Not saved: ${error.message}`, { kind: "error", icon: "error", seconds: 8 }));
        break;
      case "export": if (session?.exports.some((item) => item.format === arg)) session.exportFiles([arg]); break;
      case "present": session?.present?.(); break;
      // One of the document's own commands, by the label reported below (the app's Insert
      // and Slide menus): "Add Picture" runs "Add Picture…".
      case "run": {
        const bare = (label) => String(label ?? "").trim().replace(/…$/, "");
        session?.commands().find((command) => bare(command.label) === bare(arg))?.run();
        break;
      }
      case "palette": palette(workspace); break;
      case "assistant": side.toggle("assistant"); break;
      case "activity": side.toggle("activity"); break;
      case "new": askName(workspace, arg, { figure: "figure.yaml", deck: "talk.yaml", theme: "theme.yaml" }[arg] || "document.yaml"); break;
      case "close-tab": if (session) workspace.close(session.file); break;
      case "agents": connectDialog(workspace); break;
      case "shortcuts": shortcutsDialog(); break;
      default: break;
    }
  };
  // What the document can do now, by label: the app enables its Insert and Slide items by it.
  const doable = (session) => {
    try { return session ? session.commands().map((command) => command.label) : []; } catch { return []; }
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
  const renderTabs = () => {
    clear(tabs, workspace.order.map((file) => {
      const session = workspace.sessions.get(file);
      const here = workspace.presenceOn(file);
      const tab = h(`div.tab${workspace.active === session ? ".on" : ""}`, {
        title: `${String(workspace.info.folder || "").replace(/\/+$/, "")}/${file}`, onclick: () => workspace.activate(file),
        onauxclick: (event) => { if (event.button === 1) workspace.close(file); },
      },
      icon(KIND_ICONS[session.kind] || "file"),
      h("span.tab-name", {}, docName(file)),
      session.state !== "saved" ? h(`span.tab-dot.${session.state}`, { title: statusWords(session) }) : null,
      here.length ? h("span.tab-people", {}, here.slice(0, 3).map((entry) => h("span.mini", { style: { background: colourOf(entry.who) }, title: entry.who.name }))) : null,
      h("button.tab-close", { type: "button", title: "Close", onclick: (event) => { event.stopPropagation(); workspace.close(file); } }, icon("close")));
      return tab;
    }), h("button.tab-new", { type: "button", title: "New or open a document", onclick: (event) => newMenu(event.currentTarget, workspace) }, icon("plus")));
  };

  const renderPeople = () => {
    const others = workspace.others();
    clear(people,
      others.map((entry) => {
        const button = h("button.person", { type: "button", onclick: () => entry.file && workspace.goTo(entry.file, entry.where),
          title: `${entry.who.name}${entry.doing ? ` · ${entry.doing}` : ""}${entry.file ? ` · ${entry.file}` : ""}` },
        avatar(entry.who, { ring: entry.who.kind === "agent" && Boolean(entry.doing) }));
        return button;
      }),
      h("button.person.add", { type: "button", title: "Work with agents", onclick: () => connectDialog(workspace) }, icon("collaborate")));
    followChip.hidden = !others.some((entry) => entry.who.kind === "agent");
    followChip.classList.toggle("on", workspace.follow);
    const working = others.filter((entry) => entry.who.kind === "agent" && entry.doing);
    clear(doing, working.map((entry) => h("button.doing", { type: "button", onclick: () => workspace.goTo(entry.file, entry.where) },
      avatar(entry.who, { size: 18 }), h("b", {}, entry.who.name), h("span", {}, entry.doing), h("span.pulse"))));
    renderTabs();
  };

  const renderStatus = () => {
    const session = workspace.active;
    docbar.hidden = !session;
    if (!session) { renderUnread(null); return; }
    undo.disabled = !session.past.length;
    redo.disabled = !session.future.length;
    past.disabled = !session.past.length && !session.future.length;
    const last = session.past[session.past.length - 1], next = session.future[session.future.length - 1];
    const what = (entry) => (entry && session.said(entry).text ? ` ${session.said(entry).text}` : "");
    undo.title = `Undo${what(last)} (⌘Z)`;
    redo.title = `Redo${what(next)} (⇧⌘Z)`;
    const state = session.state;
    status.className = `status ${state === "saved" ? "saved" : state === "problem" ? "problem" : state === "offline" ? "offline" : "busy"}`;
    const words = statusWords(session);
    status.title = state === "problem" ? session.problem || "" : state === "offline" ? "Your changes are kept here, and saved when the studio is back." : "";
    const text = status.querySelector(".status-text");
    if (text.textContent !== words) {
      text.textContent = words;
      // The bar has room again for its tools' words once a long word on saving is gone.
      fitDocbar();
    }
    // A document that has never read has nothing to edit, export or present.
    for (const slot of [docLeft, docRight]) slot.inert = session.unread;
    renderUnread(session);
  };

  // A document whose file has not read since it was opened: its editor has nothing to show,
  // so this says why over it, with the file's words to put right there (or in another app:
  // it opens as soon as it reads).
  let unread = null;
  const renderUnread = (session) => {
    unreadView.hidden = !session?.unread;
    if (!session?.unread) { unread = null; return; }
    if (unread?.session === session && unread.problem === session.problem && (unread.source === session.source || unread.edited)) return;
    const area = h("textarea.unread-source", { autocomplete: "off", "aria-label": `${session.file}, as written`, dataset: { ownUndo: "" } });
    area.spellcheck = false;
    // Words the person has typed here are kept when the file changes again.
    const kept = unread?.session === session && unread.edited;
    area.value = kept ? unread.area.value : session.source ?? "";
    const shown = kept || session.source != null;  // not a file too large to show
    // What is wrong, the file named once (in the heading).
    const said = h("div.unread-said", {}, (session.problem || "").replace(/^Can't read [^:]+: (.)/, (_, first) => first.toUpperCase()));
    const save = ui.button("Save", () => mend(), { kind: "primary" });
    const mend = async () => {
      if (!shown) return;
      save.disabled = true;
      try { await session.mend(area.value); }
      catch (error) { said.textContent = error.message; }
      finally { save.disabled = false; }
    };
    area.addEventListener("input", () => { if (unread) unread.edited = true; });
    clear(unreadView, h("div.unread-inner", {},
      h("div.unread-head", {}, icon("warning"), h("h2", {}, `${session.file.split("/").pop()} can't be read`)),
      said,
      h("p.unread-note", {}, `Nothing has been changed in the file. Put it right ${shown ? "here and save, or " : ""}in another app: it opens as soon as it reads.`),
      shown ? area : null,
      shown ? h("div.unread-foot", {}, save) : null));
    unread = { session, problem: session.problem, source: session.source, area, edited: kept, mend };
    // The line the problem names, chosen and in view.
    const line = Number((session.problem || "").match(/\bline (\d+)/)?.[1] || 0);
    if (line && shown) requestAnimationFrame(() => {
      const lines = area.value.split("\n");
      const start = lines.slice(0, line - 1).reduce((sum, item) => sum + item.length + 1, 0);
      area.focus({ preventScroll: true });
      area.setSelectionRange(start, start + (lines[line - 1] || "").length);
      area.scrollTop = Math.max(0, (line - 4) * parseFloat(getComputedStyle(area).lineHeight || "18"));
    });
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
    clear(docRight, session ? session.actions : null);
    renderTabs();
    renderStatus();
  };

  const welcome = h("div.welcome.scroll-thin");
  const renderWelcome = () => {
    const kinds = info.kinds.filter((kind) => kind.offered !== false).map((kind) => kind.name);
    const card = (kind, title, note, name) => kinds.includes(kind) ? h("button.start-card", { type: "button", onclick: () => askName(workspace, kind, name) },
      h("span.start-icon", {}, icon(KIND_ICONS[kind])), h("span.start-title", {}, title), h("span.start-note", {}, note)) : null;
    clear(welcome, h("div.welcome-inner", {},
      h("h1", {}, "New Document"),
      h("p.lead", {}, "Create decks, figures and themes. You and any agents you invite can edit them at the same time."),
      h("div.start-cards", {},
        card("deck", "Deck", "Slides for a talk, with live figures", "talk.yaml"),
        card("figure", "Figure", "A diagram that is laid out automatically", "figure.yaml"),
        card("theme", "Theme", "Fonts, colours and lines for decks and figures", "theme.yaml")),
      workspace.documents.length ? h("div.welcome-section", {}, h("h2", {}, "In This Folder"),
        h("div.doc-list", {}, workspace.documents.map((item) => h("button.doc-row", { type: "button", onclick: () => workspace.open(item.file) },
          icon(KIND_ICONS[item.kind] || "file"), h("span.doc-name", { title: item.file }, docName(item.file)),
          h("span.doc-kind", {}, [item.file.includes("/") ? item.file.split("/").slice(0, -1).join("/") : null, item.title].filter(Boolean).join(" · ")))))) : null,
      h("div.welcome-section", {}, h("h2", {}, "Work with Agents"),
        h("p", {}, "Ask Claude in the panel on the right, or connect Claude Code or another MCP agent. Run this command once in this folder, then ask the agent to make something. Its changes appear here as it works:"),
        copyable(MCP_COMMAND),
        // Which folder "this folder" is, said as such.
        h("p.hint-line.folder-line", { title: info.folder }, icon("folder"), h("span", {}, "This folder: ", h("span.folder-path", {}, homeShort(info.folder)))))));
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
    else if (key === "?" && !inField(event)) { event.preventDefault(); shortcutsDialog(); }
  });
  // Edits go as the page does. Ones that cannot (the studio is out of reach) would be lost
  // with it: while there are any, the browser asks first.
  addEventListener("beforeunload", (event) => {
    for (const session of workspace.sessions.values()) session.push();
    if ([...workspace.sessions.values()].some((session) => session.pendingLocal)) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  workspace.connect();
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

// A folder in the home folder as the Finder's Go menu says it: ~/Documents/talks.
const homeShort = (folder) => String(folder || "").replace(/\/+$/, "").replace(/^\/(Users|home)\/[^/]+(?=\/|$)/, "~");

function markIcon() {
  const node = icon("info");
  node.firstChild.setAttribute("d", "M3 4.5h4v7H3zM9 4.5h4v3H9zM9 9.5h4v2H9zM7 8h2");
  node.setAttribute("stroke-width", "1.6");
  return node;
}

export function copyable(text) {
  const button = ui.button("", async () => {
    try { await navigator.clipboard.writeText(text); toast("Copied", { icon: "check", seconds: 1.2 }); }
    catch { toast("Couldn't copy. Select the text and copy it instead.", { seconds: 2 }); }
  }, { kind: "ghost", icon: "copy", small: true, title: "Copy" });
  return h("div.copyable", {}, h("code", {}, text), button);
}

// Kinds the studio offers to make: all of them, unless whoever started it said fewer.
const offers = (workspace, kind) => (workspace.info.kinds || []).some((item) => item.name === kind && item.offered !== false);

function newMenu(anchor, workspace) {
  const open = workspace.documents.filter((item) => !workspace.sessions.has(item.file));
  menu(anchor, [
    { title: "New" },
    ...[
      { icon: "deck", label: "Deck", hint: "Slides for a talk", run: () => askName(workspace, "deck", "talk.yaml"), kind: "deck" },
      { icon: "figure", label: "Figure", hint: "A diagram laid out automatically", run: () => askName(workspace, "figure", "figure.yaml"), kind: "figure" },
      { icon: "theme", label: "Theme", hint: "Fonts, colours and lines", run: () => askName(workspace, "theme", "theme.yaml"), kind: "theme" },
    ].filter((item) => offers(workspace, item.kind)),
    ...(open.length ? ["-", { title: "Open" }, ...open.slice(0, 20).map((item) => ({ icon: KIND_ICONS[item.kind] || "file", label: item.file, hint: item.title, run: () => workspace.open(item.file) }))] : []),
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
    const why = !file ? "Enter a name." : /[/\\:]/.test(file) ? "A name can't contain / \\ or :."
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
  setTimeout(() => { input.focus(); input.select(); }, 30);
}

export function connectDialog(workspace) {
  const name = ui.input({ value: workspace.me.name, onChange: (value) => workspace.setName(value.trim()) });
  dialog({ title: "Work with Agents", body: [
    h("p", {}, "Any MCP agent can work in this folder. You see its changes as it makes them, where it's working and what it's doing, and you can keep editing at the same time."),
    h("ol.steps", {},
      h("li", {}, "In Terminal, run this command once in this folder to add Flexo Studio to Claude Code:", copyable(MCP_COMMAND)),
      h("li", {}, "Ask for what you want, for example “Make a 6-slide talk from the README with a figure of the model”. Its changes appear here as it works."),
      h("li", {}, "Turn on ", h("b", {}, "Follow"), " to show what the agent is changing as it works.")),
    h("p.hint-line", {}, "Other MCP clients: run ", h("code", {}, "flexo studio mcp"), " as a stdio server in this folder."),
    ui.field("Your Name", name, { hint: "Shown to others" }),
  ], actions: [{ label: "Done", kind: "primary" }] });
}

// Every key the studio answers to, by what it works on, as a Mac app's Help lists them.
const SHORTCUTS = [
  ["General", [["⌘ K", "Command Palette"], ["⌘ J", "Ask Claude"], ["⌘ Z", "Undo"], ["⇧ ⌘ Z", "Redo"], ["⌥ ⌘ Z", "Show History"],
    ["⌘ S", "Save (documents also save as you work)"], ["?", "Keyboard Shortcuts"]]],
  ["Slides", [["⇧ ⌘ N", "New Slide"], ["↑ ↓", "Previous or Next Slide"], ["Home End", "First or Last Slide"],
    ["⌘ D", "Duplicate"], ["⌘ ↩", "Present"], ["⌥ ⌘ ↩", "Play from Start"]]],
  ["Objects on a Slide", [["↩", "Edit Text, First Cell or First Shape"], ["Esc", "Deselect"], ["⌫", "Delete"], ["⌘ D", "Duplicate"],
    ["⌘ X", "Cut"], ["⌘ C", "Copy"], ["⌘ V", "Paste"], ["↑ ↓", "Move Up or Down"], ["← →", "Move to the Next Column"]]],
  ["Text", [["⌘ B", "Bold"], ["⌘ I", "Italic"], ["↩", "New Item (in a List) or Done (in a Title)"], ["⇥  ⇧ ⇥", "Indent or Outdent an Item"],
    ["⇥", "Next Title, Subtitle or Cell"], ["Esc", "Done"]]],
  ["Figures", [["A", "Add Shape"], ["C", "Connect"], ["G", "Group"], ["⌫", "Delete Shape"]]],
  ["Presenting", [["→ Space", "Next Build or Slide"], ["←", "Previous"], ["Home End", "First or Last Slide"], ["4 ↩", "Go to Slide 4"],
    ["X", "Show or Hide the Presenter View"], ["B W", "Black or White Screen"], ["Esc", "End the Show"]]],
];

function shortcutsDialog() {
  const row = (keys, what) => h("div.shortcut", {}, h("span", {}, what), h("span", {}, keys.split(" ").filter(Boolean).map((key) => h("span.kbd", {}, key))));
  dialog({ title: "Keyboard Shortcuts", wide: true, body: [h("div.shortcut-groups", {}, SHORTCUTS.map(([title, rows]) =>
    h("div.shortcuts", {}, h("div.section-title", {}, title), rows.map(([keys, what]) => row(keys, what)))))] });
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
      h(`button.side-tab${which === "assistant" ? ".on" : ""}`, { type: "button", onclick: () => this.show("assistant") }, icon("sparkle"), "Claude"),
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
      h("span.activity-text", {}, h("b", {}, entry.who?.name || "Someone"), " ", entry.text, entry.count > 1 ? h("span.times", {}, ` ×${entry.count}`) : null,
        h("span.activity-where", {}, [entry.file && docName(entry.file), entry.where?.label].filter(Boolean).join(" · "))),
      h("span.activity-time", {}, ago(entry.at)))) : h("div.empty", {}, "No activity yet. Changes made by you, Claude and other agents appear here."));
  }
}

// -- the command palette --------------------------------------------------------------

export function palette(workspace) {
  if (document.querySelector(".palette")) return;
  const session = workspace.active;
  const commands = [
    ...(session ? session.commands() : []),
    ...workspace.order.filter((file) => file !== session?.file).map((file) => ({ icon: "file", label: `Go to ${file}`, run: () => workspace.activate(file) })),
    ...workspace.documents.filter((item) => !workspace.sessions.has(item.file)).map((item) => ({ icon: KIND_ICONS[item.kind] || "file", label: `Open ${item.file}`, hint: item.title, run: () => workspace.open(item.file) })),
    ...[
      { icon: "deck", label: "New Deck", run: () => askName(workspace, "deck", "talk.yaml"), kind: "deck" },
      { icon: "figure", label: "New Figure", run: () => askName(workspace, "figure", "figure.yaml"), kind: "figure" },
      { icon: "theme", label: "New Theme", run: () => askName(workspace, "theme", "theme.yaml"), kind: "theme" },
    ].filter((item) => offers(workspace, item.kind)),
    { icon: "sparkle", label: "Ask Claude", keys: "⌘J", run: () => document.querySelector(".claude-button")?.click() },
    { icon: "target", label: workspace.follow ? "Stop Following Agents" : "Follow Agents", run: () => workspace.setFollow(!workspace.follow) },
    { icon: "collaborate", label: "Work with Agents…", run: () => connectDialog(workspace) },
    { icon: "keyboard", label: "Keyboard Shortcuts", keys: "?", run: () => shortcutsDialog() },
  ];
  const input = h("input.palette-input", { placeholder: session ? `Search commands, slides, files…` : "Search commands and files…" });
  input.spellcheck = false;
  const list = h("div.command-list.scroll-thin");
  let shown = [];
  let index = 0;
  // Letters of the query in order, closer together and nearer the start ranking higher;
  // null when they are not all there.
  const score = (label, query) => {
    const text = label.toLowerCase();
    let position = 0, total = 0;
    for (const ch of query) {
      const found = text.indexOf(ch, position);
      if (found < 0) return null;
      total += found - position;
      position = found + 1;
    }
    const whole = text.indexOf(query);
    return total + (whole >= 0 ? -20 + whole * 0.1 : 0) + text.length * 0.01;
  };
  const render = () => {
    const query = input.value.trim().toLowerCase();
    shown = query ? commands.map((command) => [score(`${command.label} ${command.hint || ""}`, query), command]).filter(([s]) => s !== null).sort((a, b) => a[0] - b[0]).map(([, c]) => c) : commands;
    shown = shown.slice(0, 60);
    index = Math.min(index, Math.max(0, shown.length - 1));
    clear(list, shown.length ? shown.map((command, i) => h(`button.menu-item${i === index ? ".active" : ""}`, { type: "button", onmouseenter: () => { index = i; mark(); }, onclick: () => run(command) },
      command.icon ? icon(command.icon) : null, h("span.menu-text", {}, h("span", {}, command.label), command.hint ? h("span.menu-hint", {}, command.hint) : null),
      command.keys ? h("span.kbd", {}, command.keys) : null)) : h("div.empty", {}, "No results"));
  };
  const mark = () => list.querySelectorAll(".menu-item").forEach((item, i) => { item.classList.toggle("active", i === index); if (i === index) item.scrollIntoView({ block: "nearest" }); });
  // Closed, it gives the keys back where they were, as Spotlight does; a command run then
  // takes them where it goes.
  const before = document.activeElement;
  const close = () => {
    scrim.remove();
    const under = [...document.querySelectorAll(".scrim")].pop();
    if (before?.isConnected && before !== document.body && (!under || under.contains(before))) before.focus({ preventScroll: true });
  };
  const run = (command) => { close(); command.run(); };
  input.addEventListener("input", () => { index = 0; render(); });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") { event.preventDefault(); index = Math.min(index + 1, shown.length - 1); mark(); }
    else if (event.key === "ArrowUp") { event.preventDefault(); index = Math.max(index - 1, 0); mark(); }
    else if (event.key === "Enter") { event.preventDefault(); if (shown[index]) run(shown[index]); }
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
