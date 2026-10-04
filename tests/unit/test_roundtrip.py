"""A YAML file written again keeps what its person wrote where the document did not change."""

from __future__ import annotations

from pathlib import Path

import yaml

from flexo.roundtrip import rewrite


def fresh(document: object) -> str:
    return yaml.safe_dump(document, sort_keys=False)


THEME = (
    "# Our lab's look.\n"
    "theme:\n"
    "  base: paper   # the closest built-in\n"
    '  name: "Lab"\n'
    "  palette:\n"
    "  - '#222e50'\n"
    "  - '#007991'\n"
    "\n"
    "  # The tones are softer than paper's.\n"
    "  tones:\n"
    "    fill_lightness: 0.94\n"
)


def test_comments_quoting_blank_lines_and_key_order_survive_an_edit() -> None:
    document = yaml.safe_load(THEME)
    document["theme"]["tones"]["fill_lightness"] = 0.9
    assert rewrite(THEME, document, fresh) == THEME.replace("0.94", "0.9")


def test_an_edit_to_a_list_keeps_the_comments_of_its_items_that_did_not_change() -> None:
    text = "items:\n- one   # first\n- two\n- three   # last\n"
    document = {"items": ["one", "2", "three"]}
    written = rewrite(text, document, fresh)
    assert written == "items:\n- one   # first\n- '2'\n- three   # last\n"
    assert yaml.safe_load(written) == document
    # A key added goes after the one before it in the document; one taken out goes.
    assert rewrite("a: 1  # kept\nc: 3\n", {"a": 1, "b": 2}, fresh) == "a: 1  # kept\nb: 2\n"


def test_what_cannot_be_kept_is_written_afresh() -> None:
    document = {"a": [1, 2]}
    assert rewrite(None, document, fresh) == fresh(document)
    assert rewrite("a: [1, 2", document, fresh) == fresh(document)  # does not read
    assert rewrite("- 1\n- 2\n", document, fresh) == fresh(document)  # not a mapping


def test_the_studio_writes_a_theme_over_the_words_it_read(tmp_path: Path) -> None:
    from flexo.studio.theme_kind import ThemeKind

    path = tmp_path / "lab.theme.yaml"
    document = yaml.safe_load(THEME)
    document["theme"]["name"] = "Lab look"
    ThemeKind().save(path, document, previous=THEME)
    assert path.read_text(encoding="utf-8") == THEME.replace('"Lab"', '"Lab look"')
