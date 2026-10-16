"""A document's TODOs (``studio/static/studio/todos.js``): the word TODO in capitals, as a word of
its own, wherever it is in a document's words -- markup aside, in a figure's labels and runs --
found by the find bar's engine (finding.js) with Match Case and Whole Words; each field's words
read once for each value it has had; gone through one after another. Run in Node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import freeform

STATIC = Path(freeform.__file__).parent / "studio" / "static" / "studio"


def run(body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = (
        f"const F = await import({json.dumps((STATIC / 'finding.js').as_uri())});\n"
        f"const T = await import({json.dumps((STATIC / 'todos.js').as_uri())});\n"
        f"console.log(JSON.stringify(await (async () => {{ {body} }})()));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_todo_is_the_word_in_capitals_and_alone() -> None:
    found = run("""
      const said = ["TODO", "TODO: check the rates", "TODO — a figure", "(TODO)", "Fix this. TODO.",
        "two TODO and TODO", "TODO\\nthen", "«TODO»"];
      const not = ["todo", "Todo", "ToDo", "TODOs", "TODOS", "XTODO", "TODO_1", "TODO2", "to do",
        "T O D O"];
      return { said: said.map((text) => T.todosIn(text)), not: not.map((text) => T.todosIn(text)) };
    """)
    assert found["said"] == [
        [[0, 4]],
        [[0, 4]],
        [[0, 4]],
        [[1, 5]],
        [[10, 14]],
        [[4, 8], [13, 17]],
        [[0, 4]],
        [[1, 5]],
    ]
    assert found["not"] == [[]] * 10


def test_todo_is_found_in_words_as_they_read_markup_aside() -> None:
    found = run("""
      const index = T.todoIndex();
      const fields = [
        { kind: "markup", value: "**TODO** say why" },
        { kind: "markup", value: "a `TODO` in code" },
        { kind: "markup", value: "[TODO](https://example.org) linked" },
        { kind: "markup", value: "[TODO]{accent} coloured" },
        { kind: "markup", value: "$x$ TODO" },
        { kind: "markup", value: "TO**DO** split by bold" },
        { kind: "markup", value: "**todo** in lower case" },
        { kind: "label", value: "Structure\\\\nTODO" },
        { kind: "plain", value: "\\\\mathcal{L}_\\\\text{TODO}(q)" },
        { kind: "runs", value: [{ text: "TO" }, { text: "DO", weight: "bold" }, { text: ": it" }] },
        { kind: "runs", value: [{ text: "Todo" }, { text: "s" }] },
        { kind: "plain", value: "Notes, all done." },
      ];
      return index.find(fields).matches.map((match) => [match.index, match.start, match.end,
        match.field.words.text.slice(match.start, match.end)]);
    """)
    assert found == [
        [0, 0, 4, "TODO"],
        [1, 2, 6, "TODO"],
        [2, 0, 4, "TODO"],
        [3, 0, 4, "TODO"],
        [4, 2, 6, "TODO"],
        [5, 0, 4, "TODO"],
        [7, 10, 14, "TODO"],
        [8, 18, 22, "TODO"],
        [9, 0, 4, "TODO"],
    ]


def test_each_fields_words_are_read_once_for_each_value_it_has_had() -> None:
    found = run("""
      const index = T.todoIndex();
      const deck = () => [{ kind: "markup", value: "Title TODO" }, { kind: "plain", value: notes }];
      let notes = "Say why";
      const first = index.find(deck());
      const again = index.find(deck());
      notes = "Say why. TODO: the rates";
      const typed = index.find(deck());
      notes = "Say why";
      const back = index.find(deck());
      return {
        counts: [first, again, typed, back].map((read) => read.matches.length),
        // (The same words, read once: the very words read before.)
        same: first.fields[0].words === again.fields[0].words
          && typed.fields[0].words === first.fields[0].words,
        kept: back.fields[1].words === first.fields[1].words,
        fieldsKept: typed.fields.map((field) => field.kind),
      };
    """)
    assert found == {
        "counts": [1, 1, 2, 1],
        "same": True,
        "kept": True,
        "fieldsKept": ["markup", "plain"],
    }


def test_a_figures_todos_are_in_its_labels_lines_modules_and_drawn_shapes() -> None:
    found = run("""
      const figure = {
        nodes: [{ id: "a", label: "Encoder TODO" }, { id: "b", label: "todo: lower" },
          { id: "c", label: [{ text: "TODO", weight: "bold" }] }],
        edges: [{ id: "e1", from: "a", to: "b", label: "TODO rate", cofactors: ["NADH", "TODO"] }],
        groups: [{ id: "g", label: "Module TODO" }],
        shapes: [{ kind: "text", text: "TODO: arrow" }],
      };
      const { matches } = T.todoIndex().find(F.figureFields(figure));
      return matches.map((match) =>
        [match.field.element, match.field.target.type, match.field.target.id ?? null]);
    """)
    assert found == [
        ["a.label", "node", "a"],
        ["c.label", "node", "c"],
        ["e1.label", "edge", "e1"],
        ["e1.cofactors", "edge", "e1"],
        ["g.label", "group", "g"],
        ["shapes.0.text", "shape", None],
    ]


def test_todos_are_gone_through_one_after_another_round_from_the_last() -> None:
    found = run("""
      const { matches } = T.todoIndex().find([
        { kind: "markup", value: "TODO one, TODO two" }, { kind: "markup", value: "none" },
        { kind: "plain", value: "TODO three" }]);
      const at = (match) => match && [match.index, match.start];
      const on = [], back = [];
      let now = null;
      for (let k = 0; k < 4; k += 1) { now = T.stepFrom(matches, now, 1); on.push(at(now)); }
      now = null;
      for (let k = 0; k < 4; k += 1) { now = T.stepFrom(matches, now, -1); back.push(at(now)); }
      return { on, back, none: T.stepFrom([], null, 1), said: [T.todosSaid(1), T.todosSaid(3)],
        // From where one was, the deck changed about it: the one after that place.
        from: at(T.stepFrom(matches, { index: 0, start: 5 }, 1)) };
    """)
    assert found["on"] == [[0, 0], [0, 10], [2, 0], [0, 0]]
    assert found["back"] == [[2, 0], [0, 10], [0, 0], [2, 0]]
    assert found["none"] is None
    assert found["said"] == ["1 TODO", "3 TODOs"]
    assert found["from"] == [0, 10]
