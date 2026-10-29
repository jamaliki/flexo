// The side panel's Comments: every comment thread in the document shown, a list to work through
// (flexo/studio/commenting.py says how they are written). Open ones, or those resolved; each
// by whom and when, its words, how many replies, and where it is ("Slide 3 · Figure"); a
// click goes there and opens it. Resolve, from the row. A kind whose editor has comments
// gives its document's `comments` (a deck's comments.js): `list()`, each { id, open, thread,
// place }, `open(id)`, `resolve(id, on)`, `writer(name)` and `when(time)`.

import { h, clear, ui } from "./ui.js";

export class CommentList {
  constructor(workspace, { avatar }) {
    this.workspace = workspace;
    this.avatar = avatar;
    this.showing = "open";
    this.node = h("div.comment-list");
    this.shown = false;
    let soon = 0;
    const later = () => { if (!this.shown) return; clearTimeout(soon); soon = setTimeout(() => this.render(), 120); };
    workspace.on("comments", later);
    workspace.on("active", later);
  }

  render() {
    const session = this.workspace.active;
    const adapter = session?.comments;
    const all = adapter ? adapter.list() : [];
    const open = all.filter((one) => one.open), done = all.filter((one) => !one.open);
    const listed = this.showing === "open" ? open : done;
    const head = h("div.comment-list-head", {}, ui.segmented({
      value: this.showing, key: "comment-list",
      options: [{ value: "open", label: open.length ? `Open ${open.length}` : "Open" }, { value: "resolved", label: done.length ? `Resolved ${done.length}` : "Resolved" }],
      onChange: (value) => { this.showing = value; this.render(); },
    }));
    const rows = listed.map((one) => this.row(adapter, one));
    const empty = h("div.empty", {}, !adapter ? "No comments here" : this.showing === "open" ? "No open comments" : "No resolved comments");
    clear(this.node, head, h("div.comment-rows.scroll-thin", {}, rows.length ? rows : empty));
  }

  row(adapter, one) {
    const thread = one.thread || {};
    const replies = Array.isArray(thread.replies) ? thread.replies.length : 0;
    const who = adapter.writer(thread.author);
    const resolve = ui.button("", (event) => { event.stopPropagation(); adapter.resolve(one.id, one.open); },
      { kind: "ghost", small: true, icon: one.open ? "check" : "undo", title: one.open ? "Resolve" : "Reopen" });
    return h(`div.comment-list-row${one.open ? "" : ".resolved"}`, { dataset: { thread: one.id } },
      this.avatar(who, { size: 22 }),
      h("button.comment-list-go", { type: "button", onclick: () => adapter.open(one.id) },
        h("span.comment-list-who", {}, h("b", {}, String(thread.author || "Someone")), h("span.comment-list-time", {}, adapter.when(thread.time))),
        h("span.comment-list-text", {}, String(thread.text ?? "")),
        h("span.comment-list-where", {}, [one.place, replies ? `${replies} ${replies === 1 ? "reply" : "replies"}` : ""].filter(Boolean).join(" · "))),
      resolve);
  }

  show() { this.shown = true; this.render(); }
  hide() { this.shown = false; }
}
