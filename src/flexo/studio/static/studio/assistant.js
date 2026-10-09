// The assistant's panel: one conversation, shared by everyone in the studio, answered by
// Claude, ChatGPT or another model (chosen at its top, with the model it answers in). Its
// words stream in as it writes them; its edits arrive in the documents as they happen;
// what it did is listed step by step under its reply.

import { h, clear, icon, ui, menu } from "./ui.js";

// A document by its name, as its tab says it: "talk", not "talk.yaml".
// (A theme file's ".theme" too: "Order queue.theme.yaml" is "Order queue".)
const docName = (file) => String(file).split("/").pop().replace(/(\.theme)?\.(ya?ml|json)$/i, "");

const SUGGESTIONS = {
  deck: ["Tighten the wording on this slide", "Add a slide that explains the method with a figure", "Make the whole deck shorter and punchier"],
  figure: ["Group the encoder’s parts", "Add a decoder after the encoder", "Label the arrows"],
  theme: ["Make it quieter: fewer colours, thinner lines", "A dark version for talks", "Use a serif for titles"],
  none: ["Make a 5-slide talk about this folder", "Draw a figure of a transformer", "Make a theme in our lab’s colours"],
};

// Each answerer's mark, in its own colour (white on it).
export const MARK_COLOURS = { claude: "#d97757", chatgpt: "#10a37f" };
export function assistantMark(provider, small = false) {
  return h(`span.assistant-mark${small ? ".small" : ""}`, { style: { background: MARK_COLOURS[provider] || "var(--ink-2)" } }, icon("sparkle"));
}

function remembered() { try { return JSON.parse(localStorage.getItem("flexo-studio-assistant") || "null"); } catch { return null; } }
function remember(choice) { try { localStorage.setItem("flexo-studio-assistant", JSON.stringify(choice)); } catch { /* private window */ } }

export class AssistantPanel {
  constructor(workspace) {
    this.workspace = workspace;
    this.state = workspace.info.assistant || { available: false, transcript: [], providers: [] };
    this.turns = new Map();
    this.models = new Map();
    this.list = h("div.chat.scroll-thin");
    this.input = h("textarea.chat-input", { rows: 1 });
    this.contextChip = h("div.chat-context");
    this.sendButton = h("button.chat-send", { type: "button", title: "Send (↩)", onclick: () => this.send() }, icon("send"));
    this.whoButton = h("button.who-pick", { type: "button", "aria-haspopup": "menu", title: "Choose Who Answers, and Its Model", onclick: () => this.pick() });
    this.includeContext = true;
    this.node = h("div.assistant", {}, h("div.assistant-head", {}, this.whoButton), this.list,
      h("div.composer", {}, this.contextChip, h("div.composer-row", {}, this.input, this.sendButton)));
    this.input.addEventListener("input", () => this.grow());
    this.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); this.send(); }
    });
    workspace.on("assistant", (event) => this.handle(event));
    workspace.on("active", () => this.renderContext());
    workspace.on("focus", () => this.renderContext());
    this.render();
    this.restore();
  }

  get name() { return this.state.name || "Claude"; }

  // The one its person chose last time answers again, where it can and nothing has been
  // said yet (a conversation under way keeps whoever answers it).
  restore() {
    const choice = remembered();
    const state = this.state;
    if (!choice?.provider || state.running || state.transcript.length) return;
    const known = (state.providers || []).find((item) => item.id === choice.provider);
    if (!known || known.why) return;
    if (choice.provider === state.provider && (!choice.model || choice.model === state.model)) return;
    this.choose(choice.provider, choice.model ?? null, { quiet: true });
  }

  async choose(provider, model = null, { quiet = false } = {}) {
    try {
      await this.workspace.api("/api/assistant/provider", { provider, model });
      if (!quiet) remember({ provider, model: model ?? (provider === this.state.provider ? this.state.model : null) });
    } catch (error) {
      if (!quiet) this.list.append(h("div.chat-error", {}, icon("error"), error.message));
    }
  }

  // The models one can answer in, read once from its API.
  async loadModels(provider) {
    if (this.models.has(provider)) return this.models.get(provider);
    const found = this.workspace.api(this.workspace.url("/api/assistant/models", { provider })).catch((error) => ({ models: [], error: error.message }));
    this.models.set(provider, found);
    const answer = await found;
    if (answer.error) this.models.delete(provider);
    return answer;
  }

  // Who answers, and in what model: a menu as a Mac's pop-up is, those not set up here
  // saying so (choosing one shows how to set it up).
  async pick() {
    const state = this.state;
    const current = state.provider;
    const items = [{ title: "Ask" }, ...(state.providers || []).map((item) => ({
      label: item.name,
      checked: item.id === current,
      hint: item.why ? "Not set up" : (item.id === current ? "" : item.model || ""),
      run: () => { if (item.id !== current) this.choose(item.id); },
    }))];
    if (state.available) {
      const button = this.whoButton;
      button.classList.add("loading");
      const answer = await this.loadModels(current);
      button.classList.remove("loading");
      if (this.state.provider !== current || !button.isConnected) return;
      // Its own choice, once its list says which that is.
      if (!this.state.model && answer.model) { this.state.model = answer.model; this.renderWho(); }
      const models = answer.models || [];
      const chosen = state.model || answer.model || "";
      const shown = models.includes(chosen) || !chosen ? models : [chosen, ...models];
      items.push("-", { title: "Model" });
      if (answer.error && !shown.length) items.push({ label: answer.error, disabled: true });
      for (const model of shown.slice(0, 40)) {
        items.push({ label: model, checked: model === chosen, run: () => { if (model !== chosen) this.choose(current, model); } });
      }
    }
    menu(this.whoButton, items, { className: "who-menu" });
  }

  focus() { setTimeout(() => this.input.focus(), 20); this.renderContext(); }

  grow() {
    this.input.style.height = "auto";
    this.input.style.height = `${Math.min(this.input.scrollHeight, 180)}px`;
  }

  context() {
    const session = this.workspace.active;
    if (!session || !this.includeContext) return { open: this.workspace.order };
    return { file: session.file, where: session.where || null, open: this.workspace.order };
  }

  renderContext() {
    const session = this.workspace.active;
    const where = session?.where?.label;
    clear(this.contextChip, session && this.includeContext
      ? h("span.context-pill", {}, icon("target"), `${docName(session.file)}${where ? ` · ${where}` : ""}`,
        h("button", { type: "button", title: "Remove context", onclick: () => { this.includeContext = false; this.renderContext(); } }, icon("close")))
      : session ? h("button.context-add", { type: "button", onclick: () => { this.includeContext = true; this.renderContext(); } }, icon("plus"), "Add Context") : null);
  }

  async send(text = this.input.value.trim()) {
    if (!this.state.available) return;
    if (this.state.running && !text) { this.stop(); return; }
    if (!text) return;
    this.input.value = "";
    this.grow();
    try {
      await this.workspace.api("/api/assistant", { text, context: this.context(), client: this.workspace.client, who: this.workspace.me });
    } catch (error) {
      this.list.append(h("div.chat-error", {}, icon("error"), error.message));
    }
  }

  stop() { this.workspace.api("/api/assistant/stop", {}).catch(() => {}); }

  handle(event) {
    const transcript = this.state.transcript;
    switch (event.event) {
      case "user": transcript.push(event.item); this.state.running = true; break;
      case "turn": transcript.push(event.item); break;
      case "text": case "thinking": {
        const turn = transcript.find((item) => item.id === event.turn);
        if (!turn) break;
        const type = event.event;
        let part = turn.parts[turn.parts.length - 1];
        if (!part || part.type !== type) { part = { type, text: "" }; turn.parts.push(part); }
        part.text += event.delta;
        this.updateTurn(turn);
        return;
      }
      case "tool": {
        const turn = transcript.find((item) => item.id === event.turn);
        if (!turn) break;
        const index = turn.parts.findIndex((part) => part.type === "tool" && part.id === event.part.id);
        if (index >= 0) turn.parts[index] = event.part; else turn.parts.push(event.part);
        this.updateTurn(turn);
        return;
      }
      case "error": case "stopped": {
        const turn = transcript.find((item) => item.id === event.turn);
        if (turn) turn.parts.push(event.event === "error" ? { type: "error", text: event.text } : { type: "note", text: "Stopped" });
        break;
      }
      case "idle": this.state.running = false; break;
      case "cleared": this.state.transcript = []; break;
      case "availability": case "provider": {
        const { type, event: kind, transcript: said, ...rest } = event;
        Object.assign(this.state, rest);
        if (said) this.state.transcript = said;
        if (kind === "availability") this.models.clear();
        break;
      }
      default: break;
    }
    this.render();
  }

  renderWho() {
    const state = this.state;
    clear(this.whoButton, assistantMark(state.provider, true), h("span.who-name", {}, this.name),
      state.model ? h("span.who-model", {}, state.model) : null, icon("chevron-down"));
    // Choosing waits for an answer to finish.
    this.whoButton.disabled = Boolean(state.running);
    document.documentElement.style.setProperty("--assistant", MARK_COLOURS[state.provider] || "var(--ink-2)");
  }

  render() {
    const state = this.state;
    const name = this.name;
    this.renderWho();
    this.sendButton.title = state.running ? "Stop" : "Send (↩)";
    // Where it can't be asked, nothing offers to send: the note above says why.
    this.input.disabled = !state.available && !state.running;
    this.sendButton.disabled = !state.available && !state.running;
    this.input.placeholder = state.available || state.running ? `Ask ${name} to make or change something…` : `${name} isn’t set up here`;
    clear(this.sendButton, icon(state.running ? "stop" : "send"));
    this.sendButton.classList.toggle("running", Boolean(state.running));
    this.sendButton.onclick = () => (state.running && !this.input.value.trim() ? this.stop() : this.send());
    this.turns.clear();
    if (!state.transcript.length) {
      const kind = this.workspace.active?.kind || "none";
      // The Mac app comes with what each needs: a copy without it is told so in plain
      // words, not given a command for Terminal.
      const why = window.pywebview && /pip install/.test(state.why || "")
        ? `${name} isn’t included in this copy of Flexo Studio. Download Flexo Studio again to ask ${name} here.` : state.why;
      const others = (state.providers || []).filter((item) => item.id !== state.provider && !item.why);
      clear(this.list, h("div.chat-empty", {},
        h("div.chat-hello", {}, assistantMark(state.provider), h("div", {}, h("b", {}, name), h("div.hint-line", {}, "Works with you on the documents open here"))),
        state.available ? null : h("div.chat-note", {}, icon("info"), h("div", {}, why || `${name} isn’t set up here.`,
          others.length ? [" Or ask ", others.map((item, i) => [i ? " or " : "", h("a", { href: "#", onclick: (event) => { event.preventDefault(); this.choose(item.id); } }, item.name)]), "."] : null,
          " You can also connect an agent such as Claude Code or Codex: see ", h("a", { href: "#", onclick: (event) => { event.preventDefault(); document.querySelector(".person.add")?.click(); } }, "Work with Agents"), ".")),
        // What to ask: only where it can be asked.
        state.available ? h("div.suggestions", {}, (SUGGESTIONS[kind] || SUGGESTIONS.none).map((text) => h("button.suggestion", { type: "button", onclick: () => this.send(text) }, text))) : null));
      return;
    }
    clear(this.list, state.transcript.map((item) => this.itemView(item)),
      // One chosen that can't answer here says why, under what was said.
      state.available || state.running ? null : h("div.chat-note", {}, icon("info"), h("div", {}, state.why || `${this.name} isn’t set up here.`)),
      h("div.chat-foot", {}, state.running ? null : ui.button("New Conversation", () => this.workspace.api("/api/assistant/clear", {}), { kind: "ghost", small: true, icon: "refresh" })));
    this.list.scrollTop = this.list.scrollHeight;
  }

  itemView(item) {
    if (item.role === "switch") return h("div.chat-switch", {}, h("span", {}, `${item.name} answers from here`));
    if (item.role === "user") {
      const where = item.context?.file ? [docName(item.context.file), item.context.where?.label].filter(Boolean).join(" · ") : "";
      return h("div.msg.user", {}, h("div.bubble", {}, item.text), where ? h("div.msg-context", {}, icon("target"), where) : null);
    }
    const node = h("div.msg.assistant-msg");
    this.turns.set(item.id, node);
    this.fillTurn(node, item);
    return node;
  }

  updateTurn(turn) {
    const node = this.turns.get(turn.id);
    if (!node) { this.render(); return; }
    const atBottom = this.list.scrollHeight - this.list.scrollTop - this.list.clientHeight < 40;
    this.fillTurn(node, turn);
    if (atBottom) this.list.scrollTop = this.list.scrollHeight;
  }

  fillTurn(node, turn) {
    const running = this.state.running && this.state.transcript[this.state.transcript.length - 1] === turn;
    const parts = turn.parts.map((part) => {
      if (part.type === "text") return h("div.msg-text", {}, markdown(part.text));
      if (part.type === "thinking") return h("details.thinking", {}, h("summary", {}, "Thinking"), h("div", {}, part.text));
      if (part.type === "tool") {
        return h(`div.step.${part.state}`, { title: part.error || "" },
          part.state === "running" ? h("span.spinner") : icon(part.state === "failed" ? "warning" : stepIcon(part.name)),
          h("span", {}, part.label || part.name), part.state === "failed" ? h("span.step-error", {}, part.error ? " — failed" : "") : null);
      }
      if (part.type === "error") return h("div.chat-error", {}, icon("error"), part.text);
      return h("div.chat-note", {}, part.text);
    });
    clear(node, h("div.msg-head", {}, assistantMark(turn.provider || "claude", true), turn.name || "Claude"), parts,
      running && !turn.parts.some((part) => part.type === "text") ? h("div.typing", {}, h("span"), h("span"), h("span")) : null);
  }
}

function stepIcon(name) {
  return { edit_document: "pencil", write_document: "pencil", look: "eye", read_document: "file", open_document: "file", list_documents: "folder", status: "info" }[name] || "check";
}

// A little markdown: paragraphs, lists, **strong**, *emphasis*, `code`. Text is
// escaped first; nothing a reply says becomes markup of its own.
export function markdown(text) {
  const container = h("div.md");
  const blocks = String(text).trim().split(/\n{2,}/);
  for (const block of blocks) {
    const lines = block.split("\n");
    if (lines.every((line) => /^\s*([-*]|\d+\.)\s+/.test(line))) {
      const ordered = /^\s*\d+\./.test(lines[0]);
      const list = h(ordered ? "ol" : "ul");
      for (const line of lines) list.append(h("li", {}, inline(line.replace(/^\s*([-*]|\d+\.)\s+/, ""))));
      container.append(list);
    } else if (/^```/.test(block)) {
      container.append(h("pre", {}, block.replace(/^```\w*\n?|```$/g, "")));
    } else {
      container.append(h("p", {}, lines.flatMap((line, i) => (i ? [h("br"), ...inline(line)] : inline(line)))));
    }
  }
  return container;
}

function inline(text) {
  const parts = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("**")) parts.push(h("strong", {}, token.slice(2, -2)));
    else if (token.startsWith("`")) parts.push(h("code", {}, token.slice(1, -1)));
    else parts.push(h("em", {}, token.slice(1, -1)));
    last = match.index + token.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}
