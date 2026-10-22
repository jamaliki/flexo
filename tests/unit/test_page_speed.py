"""The page keeps up with typing and going from slide to slide: a change copies only what it
can reach and shares the rest with the document before it, the word on saving compares the
document with the studio's once for each pair of them, and nothing lays the window out there
and then where the next frame will."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STUDIO = Path(__file__).parents[2] / "src/flexo/studio/static/studio"


def _node(code: str) -> object:
    from test_studio import FAKE_PAGE

    result = subprocess.run(
        ["node", "--input-type=module", "-e", FAKE_PAGE + code],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_copy_changed_shares_with_its_original_all_it_did_not_change() -> None:
    said = _node(
        f"const {{ share, same }} = await import({json.dumps((STUDIO / 'merge.js').as_uri())});\n"
        """
const was = {
  deck: { title: "T" }, slides: [{ title: "a", body: [{ text: "x" }] }, { title: "b" }],
};
const next = structuredClone(was);
next.slides[1].title = "c";
const out = share(next, was);
const alike = structuredClone(was);
// (Alike as same finds them -- nothing and null -- but its own words and numbers kept.)
const loose = { a: undefined, b: { c: 1 }, d: 2 }, strict = { a: null, b: { c: 1 }, d: 3 };
const mixed = share(loose, strict);
console.log(JSON.stringify({
  changed: [out === next, out.deck === was.deck, out.slides[0] === was.slides[0],
    out.slides[1] === was.slides[1], out.slides === was.slides, out.slides[1].title,
    was.slides[1].title],
  alike: share(alike, was) === was,
  sameAsSame: share({ a: undefined }, { a: null }) !== null && same({ a: undefined }, { a: null }),
  mixed: [mixed === loose, "a" in mixed && mixed.a === undefined, mixed.b === strict.b, mixed.d],
  lists: [share([1, 2], [1, 2, 3]), share([{ x: 1 }], [{ x: 1 }, 2])[0]],
}));
"""
    )
    assert said == {
        "changed": [True, True, True, False, False, "c", "b"],
        "alike": True,
        "sameAsSame": True,
        "mixed": [True, True, True, 2],
        "lists": [[1, 2], {"x": 1}],
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_change_within_one_slide_copies_that_slide_alone() -> None:
    said = _node(
        f"const {{ Session }} = await import({json.dumps((STUDIO / 'session.js').as_uri())});\n"
        f"const {{ same }} = await import({json.dumps((STUDIO / 'merge.js').as_uri())});\n"
        """
const workspace = {
  client: "me", me: { id: "me" }, sessions: new Map(), on() {}, url: (route) => route,
  api: async () => new Promise(() => {}),
};
const document = {
  deck: { title: "T" }, slides: [{ title: "a" }, { title: "b", body: [{ text: "x" }] }],
};
const info = { file: "talk.yaml", version: 1, saved: 1, exists: true, document };
const session = new Session(workspace, info);
const first = session.document;
const said = { before: session.state };
const typing = { merge: "typing", within: ["slides", 1] };
session.change((d) => { d.slides[1].body[0].text = "xy"; }, typing);
const typed = session.document;
said.typed = [typed.deck === first.deck, typed.slides[0] === first.slides[0],
  typed.slides[1] === first.slides[1], first.slides[1].body[0].text, typed.slides[1].body[0].text,
  session.state];
// A change copying the whole: what it did not change is the document before's own still.
session.change((d) => { d.deck.title = "U"; });
const now = session.document;
said.whole = [now.slides === typed.slides, now.deck === typed.deck, now.deck.title];
// A part that is not there: the whole is copied.
session.change((d) => { d.slides.push({ title: "c" }); }, { within: ["slides", 5] });
said.missing = [session.document.slides.length, typed.slides.length];
// Nothing changed, nothing in the history.
const steps = session.past.length;
session.change((d) => { d.slides[0].title = "a"; }, { within: ["slides", 0] });
said.nothing = session.past.length === steps;
session.undo(3);
said.undone = [same(session.document, first), session.future.length];
// Told the studio has it, it is saved.
session.synced = session.document;
said.after = session.state;
console.log(JSON.stringify(said));
process.exit(0);
"""
    )
    assert said == {
        "before": "saved",
        "typed": [True, True, False, "x", "xy", "saving"],
        "whole": [True, False, "U"],
        "missing": [3, 2],
        "nothing": True,
        "undone": [True, 3],
        "after": "saved",
    }


def test_nothing_lays_the_window_out_as_a_slide_is_put_on_the_stage() -> None:
    # A form drawn again keeps its scroll as it last scrolled, not read there and then.
    studio = (STUDIO / "studio.js").read_text("utf-8")
    assert "const scroll = scrolledOf(container);" in studio
    assert "const scroll = container.scrollTop;" not in studio
    # The shapes' frames placed with nothing chosen read nothing of the page's scale.
    shapes = (STUDIO / "shapes.js").read_text("utf-8")
    place = shapes[shapes.index("  function place() {") : shapes.index("  function outline(")]
    assert place.index("const px = 1 / unit();") > place.index("if (locked) {")
    # The word on saving asks whether the document is the studio's once for each pair of them.
    session = (STUDIO / "session.js").read_text("utf-8")
    assert "same(this.document, this.synced)" not in session.replace(
        "same: same(this.document, this.synced)", ""
    )
