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


DECK = (
    "# The lab meeting -- keep this comment\n"
    "deck:\n"
    "  id: talk\n"
    "  theme: paper   # chosen by Kiarash\n"
    "slides:\n"
    "# --- opening ---\n"
    '- title: "Making it fast"\n'
    "  subtitle: 'What we found'\n"
    "- title: The pipeline\n"
    "  body:\n"
    "  - bullets:\n"
    "    - Generate   # step one\n"
    "    - Design\n"
    "  - figure:\n"
    "      edges:\n"
    "      - {from: start, to: check}\n"
    "      - from: check\n"
    "        label: 'yes'\n"
    "# --- the middle ---\n"
    "- body:\n"
    '  - text: "First paragraph."   # Alice wrote this\n'
    "  - text: Second paragraph.\n"
    "  title: The question\n"
    "# end of deck\n"
)


def moved(document: dict, at: int, to: int) -> dict:
    import copy

    changed = copy.deepcopy(document)
    changed["slides"].insert(to, changed["slides"].pop(at))
    return changed


def test_a_slide_moved_takes_its_comments_and_quotes_and_an_undo_puts_the_file_back() -> None:
    document = yaml.safe_load(DECK)
    for at, to in [(1, 0), (2, 1), (1, 2), (0, 2)]:
        written = rewrite(DECK, moved(document, at, to), fresh)
        assert yaml.safe_load(written) == moved(document, at, to)
        # Every comment once, each over the slide it was over; every quote kept.
        for comment in [
            "# --- the middle ---\n- body:",
            "# Alice wrote this",
            "# step one",
            "'yes'",
            '"Making it fast"',
        ]:
            assert written.count(comment) == 1, (at, to, comment)
        assert written.endswith("# end of deck\n") and written.startswith("# The lab meeting")
        assert rewrite(written, document, fresh) == DECK  # undone


def test_a_slide_duplicated_or_deleted_and_undone_is_written_as_it_was() -> None:
    import copy

    document = yaml.safe_load(DECK)
    twice = copy.deepcopy(document)
    twice["slides"].insert(2, copy.deepcopy(twice["slides"][1]))
    written = rewrite(DECK, twice, fresh)
    assert yaml.safe_load(written) == twice and written.count("# step one") == 2
    assert rewrite(written, document, fresh) == DECK
    fewer = copy.deepcopy(document)
    del fewer["slides"][1]
    written = rewrite(DECK, fewer, fresh, name="talk.yaml")
    assert "# step one" not in written and "# --- the middle ---\n- body:" in written
    # Its deletion undone, its comments back -- the file's own, put back where they were.
    assert rewrite(written, document, fresh, name="talk.yaml") == DECK


def test_a_copy_is_the_later_of_the_two_and_keeps_the_style_of_what_it_copies() -> None:
    import copy

    text = DECK.replace("- title: The pipeline", "# Pipeline first\n- title: The pipeline")
    document = yaml.safe_load(text)
    twice = copy.deepcopy(document)
    twice["slides"].insert(2, copy.deepcopy(twice["slides"][1]))
    # Its figure given an id of its own, it is still a copy: its rows in flow, its comments.
    twice["slides"][2]["body"][1]["figure"]["id"] = "copy"
    written = rewrite(text, twice, fresh)
    assert yaml.safe_load(written) == twice
    assert "# Pipeline first\n- title: The pipeline" in written
    assert written.count("# Pipeline first") == 1
    assert written.index("# Pipeline first") < written.index("The pipeline")
    assert written.count("- {from: start, to: check}") == 2 and written.count("# step one") == 2


def test_comments_go_to_no_other_file_nor_a_new_empty_object_and_the_end_stays_at_the_end() -> None:
    import copy

    document = yaml.safe_load(DECK)
    other = DECK + "# private: from notes2.yaml\n"
    # In another file: a Text added and taken away again (Esc).
    added = copy.deepcopy(document)
    added["slides"][2]["body"].append({"text": ""})
    written = rewrite(other, added, fresh, name="notes2.yaml")
    assert rewrite(written, document, fresh, name="notes2.yaml") == other
    # Here, a Text added to another slide brings no comments with it.
    here = copy.deepcopy(document)
    here["slides"][1]["body"].append({"text": ""})
    written = rewrite(DECK, here, fresh, name="talk.yaml")
    assert "private" not in written and written.count("# end of deck") == 1
    # An object moved down past the file's last comment leaves it at the end, undone or redone.
    down = copy.deepcopy(document)
    body = down["slides"][2]["body"]
    body.append(body.pop(0))
    written = rewrite(DECK, down, fresh, name="talk.yaml")
    assert written.count("# end of deck") == 1 and written.endswith("# end of deck\n")
    undone = rewrite(written, document, fresh, name="talk.yaml")
    assert undone == DECK and rewrite(undone, down, fresh, name="talk.yaml") == written


def test_an_object_moved_in_a_slide_and_back_keeps_its_comment_and_quotes() -> None:
    import copy

    document = yaml.safe_load(DECK)
    changed = copy.deepcopy(document)
    body = changed["slides"][2]["body"]
    body.insert(1, body.pop(0))
    written = rewrite(DECK, changed, fresh)
    assert '- text: "First paragraph."   # Alice wrote this' in written
    assert rewrite(written, document, fresh) == DECK


def test_new_words_are_plain_unless_yaml_or_their_person_quotes_them() -> None:
    text = "slides:\n- title: ''\n  body:\n  - text: '**Bold** start'\n- title: \"The pipeline\"\n"
    document = {
        "slides": [{"title": "Mine", "body": [{"text": "Bold start"}]}, {"title": "The pipelines"}]
    }
    written = rewrite(text, document, fresh)
    assert (
        written
        == 'slides:\n- title: Mine\n  body:\n  - text: Bold start\n- title: "The pipelines"\n'
    )
    # A word YAML would read otherwise (as the studio reads it, YAML 1.1) is quoted.
    labels = rewrite(
        "edges:\n- from: a  # first\n", {"edges": [{"from": "a", "label": "yes"}]}, fresh
    )
    assert labels == "edges:\n- from: a  # first\n  label: 'yes'\n"


def test_a_comment_after_words_keeps_its_room_as_they_change() -> None:
    text = "slides:\n- body:\n  - text: First   # Alice wrote this\n"
    longer = {"slides": [{"body": [{"text": "First paragraph, longer"}]}]}
    written = rewrite(text, longer, fresh)
    assert "  - text: First paragraph, longer   # Alice wrote this\n" in written
    assert rewrite(written, yaml.safe_load(text), fresh) == text


COLUMNS = (
    "slides:\n"
    "- layout: two-columns\n"
    "  title: Treatments\n"
    "  left:\n"
    "  - bullets:\n"
    "    - Mechanism\n"
    "  right:\n"
    "  # The numbers\n"
    "  - table:\n"
    "    - [Drug, Spliced]\n"
    "    - - DTT, 2 mM  # n = 3 biological repeats\n"
    "      - '91'\n"
    "    caption: Table 2\n"
    "  - text: Our own numbers.\n"
    "- title: A switch\n"
    "  body:\n"
    "  - quote: The decision is made by duration.\n"
    "    by: Lin 2007\n"
    "  # Callout: say this slowly\n"
    "  - callout: Brief activity protects.\n"
    "    title: Duration decides\n"
)


def test_an_object_moved_to_another_column_takes_its_comments_and_an_undo_puts_them_back() -> None:
    import copy

    document = yaml.safe_load(COLUMNS)
    for emptied in (False, True):
        moved = copy.deepcopy(document)
        slide = moved["slides"][0]
        slide["left"].append(slide["right"].pop(0))
        if emptied:
            slide["left"].append(slide.pop("right")[0])
        written = rewrite(COLUMNS, moved, fresh, name="talk.yaml")
        assert yaml.safe_load(written) == moved
        # Its comment over it, a row's at its end, its rows' style: all in the left column now.
        assert "    - Mechanism\n  # The numbers\n  - table:\n    - [Drug, Spliced]\n" in written
        assert "    - - DTT, 2 mM  # n = 3 biological repeats\n" in written
        assert written.count("# The numbers") == 1
        assert rewrite(written, document, fresh, name="talk.yaml") == COLUMNS  # undone


def test_an_object_moved_up_takes_the_comment_over_it_and_an_undo_puts_it_back() -> None:
    import copy

    document = yaml.safe_load(COLUMNS)
    up = copy.deepcopy(document)
    body = up["slides"][1]["body"]
    body.insert(0, body.pop())
    written = rewrite(COLUMNS, up, fresh, name="talk.yaml")
    assert "  body:\n  # Callout: say this slowly\n  - callout:" in written
    undone = rewrite(written, document, fresh, name="talk.yaml")
    assert undone == COLUMNS
    # The comment over the first item is that item's too: moved down, it goes with it.
    assert rewrite(undone, up, fresh, name="talk.yaml") == written


def test_a_slide_with_a_comment_over_it_copied_and_undone_keeps_its_comment() -> None:
    import copy

    document = yaml.safe_load(DECK)
    for at in (0, 2):
        twice = copy.deepcopy(document)
        twice["slides"].insert(at + 1, copy.deepcopy(twice["slides"][at]))
        written = rewrite(DECK, twice, fresh, name="talk.yaml")
        # The original keeps the comment over it; the copy, after it, has none.
        assert written.count("# --- opening ---") == 1
        assert written.count("# --- the middle ---") == 1
        assert rewrite(written, document, fresh, name="talk.yaml") == DECK

