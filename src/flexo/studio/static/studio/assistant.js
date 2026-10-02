// The Claude panel: one conversation, shared by everyone in the studio. Claude's
// words stream in as it writes them; its edits arrive in the documents as they
// happen; what it did is listed step by step under its reply.

import { h, clear, icon, ui } from "./ui.js";

const SUGGESTIONS = {
  deck: ["Tighten the wording on this slide", "Add a slide that explains the method with a figure", "Make the whole deck shorter and punchier"],
  figure: ["Group the encoder's parts", "Add a decoder after the encoder", "Label the arrows"],
  theme: ["Make it quieter: fewer colours, thinner lines", "A dark version for talks", "Use a serif for titles"],
  none: ["Make a 5-slide talk about this folder", "Draw a figure of a transformer", "Make a theme in our lab's colours"],
};

export class AssistantPanel {
  constructor(workspace) {
    this.workspace = workspace;
    this.state = workspace.info.assistant || { available: false, transcript: [] };
    this.turns = new Map();
    this.list = h("div.chat.scroll-thin");
    this.input = h("textarea.chat-input", { rows: 1, placeholder: "Ask Claude to make or change something…" });
    this.contextChip = h("div.chat-context");
    this.sendButton = h("button.chat-send", { type: "button", title: "Send (↩)", onclick: () => this.send() }, icon("send"));
    this.includeContext = true;
    this.node = h("div.assistant", {}, this.list,
      h("div.composer", {}, this.contextChip, h("div.composer-row", {}, this.input, this.sendButton)));
    this.input.addEventListener("input", () => this.grow());
    this.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); this.send(); }
    });
    workspace.on("assistant", (event) => this.handle(event));
    workspace.on("active", () => this.renderContext());
    workspace.on("focus", () => this.renderContext());
    this.render();
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
      ? h("span.context-pill", {}, icon("target"), `${session.file.split("/").pop()}${where ? ` · ${where}` : ""}`,
        h("button", { type: "button", title: "Remove context", onclick: () => { this.includeContext = false; this.renderContext(); } }, icon("close")))
      : session ? h("button.context-add", { type: "button", onclick: () => { this.includeContext = true; this.renderContext(); } }, icon("plus"), "Add Context") : null);
  }

  async send(text = this.input.value.trim()) {
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
      case "availability": this.state.available = event.available; this.state.why = event.why; break;
      default: break;
    }
    this.render();
  }

  render() {
    const state = this.state;
    this.sendButton.title = state.running ? "Stop" : "Send (↩)";
    clear(this.sendButton, icon(state.running ? "stop" : "send"));
    this.sendButton.classList.toggle("running", Boolean(state.running));
    this.sendButton.onclick = () => (state.running && !this.input.value.trim() ? this.stop() : this.send());
    this.turns.clear();
    if (!state.transcript.length) {
      const kind = this.workspace.active?.kind || "none";
      clear(this.list, h("div.chat-empty", {},
        h("div.chat-hello", {}, h("span.claude-mark", {}, icon("sparkle")), h("div", {}, h("b", {}, "Claude"), h("div.hint-line", {}, "Works with you on the documents open here"))),
        state.available ? null : h("div.chat-note", {}, icon("info"), h("div", {}, state.why || "Claude isn't available here.", " You can still connect Claude Code. See ", h("a", { href: "#", onclick: (event) => { event.preventDefault(); document.querySelector(".person.add")?.click(); } }, "Work with Agents"), ".")),
        h("div.suggestions", {}, (SUGGESTIONS[kind] || SUGGESTIONS.none).map((text) => h("button.suggestion", { type: "button", onclick: () => this.send(text) }, text)))));
      return;
    }
    clear(this.list, state.transcript.map((item) => this.itemView(item)),
      h("div.chat-foot", {}, state.running ? null : ui.button("New Conversation", () => this.workspace.api("/api/assistant/clear", {}), { kind: "ghost", small: true, icon: "refresh" })));
    this.list.scrollTop = this.list.scrollHeight;
  }

  itemView(item) {
    if (item.role === "user") {
      const where = item.context?.file ? [item.context.file.split("/").pop(), item.context.where?.label].filter(Boolean).join(" · ") : "";
      return h("div.msg.user", {}, h("div.bubble", {}, item.text), where ? h("div.msg-context", {}, icon("target"), where) : null);
    }
    const node = h("div.msg.claude");
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
    clear(node, h("div.msg-head", {}, h("span.claude-mark.small", {}, icon("sparkle")), "Claude"), parts,
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
