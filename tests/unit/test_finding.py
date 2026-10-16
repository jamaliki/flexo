"""Finding words and putting others in their place (``studio/static/studio/finding.js``): the
one engine the find bar (⌘F) and the top bar's search use -- words found as they read, markup
aside; Match Case and Whole Words; words replaced in rich text keeping its look; a figure's
labels -- run in Node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import freeform

SCRIPT = Path(freeform.__file__).parent / "studio" / "static" / "studio" / "finding.js"


def run(body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = (
        f"const F = await import({json.dumps(SCRIPT.as_uri())});\n"
        f"console.log(JSON.stringify(await (async () => {{ {body} }})()));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_words_are_found_without_case_unless_asked_and_whole_words_alone() -> None:
    found = run("""
      const text = "Enzyme design: an enzyme, ENZYMES and enzymatic means";
      return {
        any: F.findIn(text, "enzyme"),
        cased: F.findIn(text, "enzyme", { matchCase: true }),
        whole: F.findIn(text, "enzyme", { wholeWords: true }),
        both: F.findIn(text, "Enzyme", { matchCase: true, wholeWords: true }),
        nothing: F.findIn(text, "   "),
      };
    """)
    assert found["any"] == [[0, 6], [18, 24], [26, 32]]
    assert found["cased"] == [[18, 24]]
    # "ENZYMES" is a longer word: not found whole.
    assert found["whole"] == [[0, 6], [18, 24]]
    assert found["both"] == [[0, 6]]
    assert found["nothing"] == []


def test_spaces_and_quotes_match_as_typed_or_not() -> None:
    found = run("""
      return [
        F.findIn("Generated\\nbackbones", "generated backbones").length,
        F.findIn("Can we automate a chemist\\u2019s judgement?", "chemist's").length,
        F.findIn("a \\u201cquoted\\u201d word", '"quoted"').length,
        F.findIn("a.b.c", "a.b").length,
        F.findIn("x+y (z)", "+y (").length,
      ];
    """)
    assert found == [1, 1, 1, 1, 1]


def test_words_are_found_as_they_read_markup_aside() -> None:
    words = run("""
      const read = (s) => F.wordsOf(s).text;
      return [
        read("We work on methods for [enzyme design]{accent1}"),
        read("**mechazyme** and en**zy**me"),
        read("a [link](https://example.org) and `code *not italic*`"),
        read("maths $x^2$ and a price of $5 and $10"),
        read("an escaped \\\\* star and 2 * 3"),
        F.wordsOf("Structure\\\\ndesign model", "label").text,
      ];
    """)
    assert words == [
        "We work on methods for enzyme design",
        "mechazyme and enzyme",
        "a link and code *not italic*",
        "maths x^2 and a price of $5 and $10",
        "an escaped * star and 2 * 3",
        "Structure\ndesign model",
    ]


def test_a_match_spans_the_runs_of_rich_text() -> None:
    found = run("""
      const fields = F.wordIndex().build([
        { kind: "markup", value: "en**zy**me design" },
        { kind: "markup", value: "[enz]{accent}*yme*" },
        { kind: "runs", value: [{ text: "en" }, { text: "zy", weight: 700 }, { text: "me" }] },
        { kind: "plain", value: "no markup: en**zy**me" },
      ]);
      return F.search(fields, "enzyme").map((m) => [m.index, m.start, m.end]);
    """)
    # In notes (plain), the marks are words: not found there.
    assert found == [[0, 0, 6], [1, 0, 6], [2, 0, 6]]


def test_words_replaced_keep_the_look_about_them() -> None:
    made = run("""
      const put = (value, query, words, kind = "markup") =>
        F.replaced(value, kind, F.findIn(F.wordsOf(value, kind).text, query), words);
      return [
        put("**enzyme** design", "enzyme", "protein"),
        put("We work on methods for [enzyme design]{accent1}", "enzyme", "protein"),
        put("en**zy**me design", "enzyme", "protein"),
        put("**enzyme** design", "enzyme design", "protein work"),
        put("enzyme **design pipeline**", "enzyme design", "A"),
        put("[enzyme](https://x.org) design", "enzyme design", "protein work"),
        put("**enzyme** design", "enzyme", ""),
        put("Enzyme, enzyme and ENZYME", "enzyme", "protein"),
        put("costs 5 dollars", "5 dollars", "$5 *now*"),
        put("x `enzyme` y", "enzyme", "a`b"),
        put("Structure\\\\ndesign model", "structure design", "Fold design", "label"),
        put("Say *why* the motif matters", "motif", "site", "plain"),
        F.replaced([{ text: "en" }, { text: "zy", weight: 700 }, { text: "me x" }], "runs",
          [[0, 6]], "protein"),
      ];
    """)
    assert made == [
        "**protein** design",
        "We work on methods for [protein design]{accent1}",
        # Bold that held only words replaced holds nothing: it goes.
        "protein design",
        # The words put in take the look of the first letter they replace.
        "**protein work**",
        "A **pipeline**",
        "[protein work](https://x.org)",
        # Nothing put in: the bold about it goes with it.
        " design",
        "protein, protein and protein",
        # A mark typed is written escaped, so it reads back as itself.
        "costs \\$5 \\*now\\*",
        "x `a\\`b` y",
        "Fold design model",
        "Say *why* the site matters",
        [{"text": "protein"}, {"text": " x"}],
    ]


def test_every_match_is_replaced_at_once_from_the_last() -> None:
    made = run("""
      const value = "**motif** and motifs, [a motif]{accent} and `motif`";
      return F.replaced(value, "markup", F.findIn(F.wordsOf(value).text, "motif"), "site");
    """)
    assert made == "**site** and sites, [a site]{accent} and `site`"


def test_a_figures_words_are_its_labels_lines_modules_and_shapes() -> None:
    fields = run("""
      return F.figureFields({
        nodes: [{ id: "a", label: "Enzyme\\\\nnode" }, { id: "b" },
          { id: "c", label: [{ text: "Run" }, { text: "s", weight: 700 }] }],
        edges: [{ from: "a", to: "b.in", label: "binds" },
          { id: "named", from: "b", to: "c", back_label: "back", cofactors: ["ATP", "ADP"] }],
        groups: [{ id: "root", implied: true, label: "Not drawn" },
          { id: "module", label: "Module title", children: ["a"] }],
        shapes: [{ kind: "text", text: "Over it" },
          { kind: "group", shapes: [{ kind: "ellipse", text: "Inside" }] }],
      }, { prefix: "slide2.body.0." })
        .map((f) => [f.kind, f.element, f.path.join("."), f.target]);
    """)
    assert fields == [
        [
            "label",
            "slide2.body.0.a.label",
            "nodes.0.label",
            {"type": "node", "id": "a", "key": "label"},
        ],
        [
            "runs",
            "slide2.body.0.c.label",
            "nodes.2.label",
            {"type": "node", "id": "c", "key": "label"},
        ],
        [
            "label",
            "slide2.body.0.edge.1.a-to-b.label",
            "edges.0.label",
            {"type": "edge", "id": "edge.1.a-to-b", "key": "label"},
        ],
        [
            "label",
            "slide2.body.0.named.back_label",
            "edges.1.back_label",
            {"type": "edge", "id": "named", "key": "back_label"},
        ],
        [
            "label",
            "slide2.body.0.named.cofactors",
            "edges.1.cofactors.0",
            {"type": "edge", "id": "named", "key": "cofactors", "item": 0},
        ],
        [
            "label",
            "slide2.body.0.named.cofactors",
            "edges.1.cofactors.1",
            {"type": "edge", "id": "named", "key": "cofactors", "item": 1},
        ],
        [
            "label",
            "slide2.body.0.module.label",
            "groups.1.label",
            {"type": "group", "id": "module", "key": "label"},
        ],
        [
            "markup",
            "slide2.body.0.shapes.0.text",
            "shapes.0.text",
            {"type": "shape", "index": 0, "path": [0]},
        ],
        [
            "markup",
            "slide2.body.0.shapes.1.0.text",
            "shapes.1.shapes.0.text",
            {"type": "shape", "index": None, "path": [1, "shapes", 0]},
        ],
    ]


def test_a_match_is_counted_among_its_elements_words_spaces_aside() -> None:
    # The byline draws an author and a date as one line: the date's match is the second there.
    counted = run("""
      const fields = F.wordIndex().build([
        { kind: "markup", value: "Ada Enzyme" }, { kind: "markup", value: "2026 enzyme talk" }]);
      const matches = F.search(fields, "enzyme");
      return [...F.ordinals(fields, matches, "enzyme").values()];
    """)
    assert counted == [0, 1]


def test_words_about_a_match_are_cut_at_words() -> None:
    said = run("""
      const text = "We usually spend a lot of time and effort designing a perfect motif, "
        + "and then we need that motif to be scaffolded by a model";
      const at = text.indexOf("perfect motif") + 8;
      return F.around(text, at, at + 5);
    """)
    assert said == {
        "before": "…effort designing a perfect ",
        "found": "motif",
        "after": ", and then we need that motif to be…",
    }
