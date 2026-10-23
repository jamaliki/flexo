"""An edit made to a figure written in a deck answers its model without reading its words again
-- made from the document the edit was made on, as reading them again makes it -- and checks
the figure by libyaml."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

_FIGURE = {
    "figure": {"id": "steps"},
    "nodes": [
        {"id": "a", "label": "Read"},
        {"id": "b", "label": "Yes", "properties": {"tone": "2"}},
        {"id": "c", "kind": "text", "label": "1:30"},
    ],
    "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c", "label": "on"}],
}


@pytest.mark.parametrize(
    "words",
    [
        "yes",
        "No",
        "off",
        "12",
        "1e3",
        "0o17",
        "1:30",
        "null",
        "~",
        "a\nb",
        "a\n",
        " lead",
        "trail ",
        "#hash",
        "a: b",
        "[x]",
        "'q'",
        '"dq"',
        "tab\there",
        "é 🙂",
        "2024-01-01",
        "x" * 120,
    ],
)
def test_an_edit_to_a_figure_written_in_a_deck_answers_its_model_as_its_words_read(
    words: str,
) -> None:
    """Edited inline (``apply_to_data``), a figure's model is made from the document the edit
    was made on: as reading the words it was written as again makes it."""

    from flexo.studio.figure_edit import _applied, apply_to_data, model

    for edit in (
        {"do": "update", "targets": [{"type": "node", "id": "a"}], "values": {"label": words}},
        {
            "do": "update",
            "targets": [{"type": "node", "id": "b"}],
            "values": {"properties.tone": words},
        },
        {
            "do": "update",
            "targets": [{"type": "edge", "id": "edge.2.b-to-c"}],
            "values": {"label": words},
        },
        {"do": "add", "kind": "block", "after": "a", "node": {"label": words}},
    ):
        made = apply_to_data(copy.deepcopy(_FIGURE), edit)
        text = yaml.safe_dump(copy.deepcopy(_FIGURE), sort_keys=False, allow_unicode=True)
        result, _ = _applied(text, edit)
        assert made["model"] == model(result["text"])
        assert made["data"] == yaml.safe_load(result["text"])


def test_words_yaml_reads_otherwise_are_read_again_for_the_model() -> None:
    from flexo.studio.figure_edit import _reads_as_held

    assert _reads_as_held({"figure": {}, "nodes": [{"label": "a b"}]})
    for odd in ("a\rb", "a\u2028b", "a\x85b", "\ufeffa"):
        assert not _reads_as_held({"figure": {}, "nodes": [{"label": odd}]})
    assert not _reads_as_held({"figure": {}, "nodes": [{"when": object()}]})
    assert not _reads_as_held({"nodes": []})


def test_a_figure_read_by_libyaml_is_the_figure_safe_load_reads() -> None:
    from flexo.studio.figure_kind import parse

    text = yaml.safe_dump(_FIGURE, sort_keys=False, allow_unicode=True)
    assert parse(text, Path.cwd(), libyaml=True) == parse(text, Path.cwd())
