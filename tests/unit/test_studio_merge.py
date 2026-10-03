"""Two people's edits to one document are both kept, and the newer wins a tie."""

from __future__ import annotations

from flexo.studio.merge import merge3


def deck(*slides: dict) -> dict:
    return {"deck": {"id": "talk"}, "slides": list(slides)}


def test_edits_to_different_slides_are_both_kept() -> None:
    base = deck({"title": "A"}, {"title": "B"}, {"title": "C"})
    ours = deck({"title": "A!"}, {"title": "B"}, {"title": "C"})
    theirs = deck({"title": "A"}, {"title": "B"}, {"title": "C", "notes": "say it"})
    assert merge3(base, ours, theirs) == deck(
        {"title": "A!"}, {"title": "B"}, {"title": "C", "notes": "say it"}
    )


def test_an_edit_survives_the_other_side_inserting_before_it() -> None:
    base = deck({"title": "A"}, {"title": "B"})
    ours = deck({"title": "A"}, {"title": "B, edited"})
    theirs = deck({"title": "New"}, {"title": "A"}, {"title": "B"})
    assert merge3(base, ours, theirs)["slides"] == [
        {"title": "New"},
        {"title": "A"},
        {"title": "B, edited"},
    ]


def test_both_sides_editing_one_slide_keep_both_fields() -> None:
    base = deck({"title": "A", "body": [{"text": "x"}]})
    ours = deck({"title": "A, better", "body": [{"text": "x"}]})
    theirs = deck({"title": "A", "body": [{"text": "x"}, {"bullets": ["y"]}]})
    assert merge3(base, ours, theirs)["slides"] == [
        {"title": "A, better", "body": [{"text": "x"}, {"bullets": ["y"]}]}
    ]


def test_both_sides_adding_at_the_end_keep_both() -> None:
    base = deck({"title": "A"})
    ours = deck({"title": "A"}, {"title": "Mine"})
    theirs = deck({"title": "A"}, {"title": "Theirs"})
    assert [s["title"] for s in merge3(base, ours, theirs)["slides"]] == ["A", "Mine", "Theirs"]


def test_a_real_conflict_goes_to_the_newer_change() -> None:
    assert merge3({"title": "A"}, {"title": "B"}, {"title": "C"}) == {"title": "C"}


def test_removals_and_additions_of_keys() -> None:
    base = {"a": 1, "b": 2, "c": 3}
    ours = {"a": 1, "c": 3, "d": 4}  # removed b, added d
    theirs = {"a": 10, "b": 2, "c": 3}  # changed a
    assert merge3(base, ours, theirs) == {"a": 10, "c": 3, "d": 4}


def test_text_over_several_lines_merges_line_by_line() -> None:
    base = "one\ntwo\nthree\nfour\n"
    ours = "ONE\ntwo\nthree\nfour\n"
    theirs = "one\ntwo\nthree\nFOUR\n"
    assert merge3(base, ours, theirs) == "ONE\ntwo\nthree\nFOUR\n"


def test_undo_is_a_merge_that_keeps_later_edits_by_others() -> None:
    before = deck({"title": "A"}, {"title": "B"})
    after = deck({"title": "A, mine"}, {"title": "B"})
    now = deck({"title": "A, mine"}, {"title": "B, theirs"})
    assert merge3(after, now, before) == deck({"title": "A"}, {"title": "B, theirs"})


def test_two_people_typing_in_one_line_keep_both_their_words() -> None:
    base = deck({"title": "The pipeline"})
    ours = deck({"title": "The pipeline by Alice"})
    theirs = deck({"title": "Bob: The pipeline"})
    assert merge3(base, ours, theirs)["slides"][0]["title"] == "Bob: The pipeline by Alice"
    assert merge3("one two three", "one TWO three", "one two THREE") == "one TWO THREE"


def test_the_same_words_changed_both_ways_go_to_the_newer_change() -> None:
    assert merge3("one two three", "one TWO three", "one 2 three") == "one 2 three"
    # One word alone (a name, a colour) is not taken apart.
    assert merge3("terminal", "decision", "terminal2") == "terminal2"
    assert merge3("#ff0000", "#00ff00", "#ff00aa") == "#ff00aa"


def test_one_line_of_several_changed_by_both_merges_word_by_word() -> None:
    base = "one\ntwo words here\nthree\n"
    ours = "one\nfirst words here\nthree\n"
    theirs = "one\ntwo words there\nthree\n"
    assert merge3(base, ours, theirs) == "one\nfirst words there\nthree\n"
    assert merge3("a\n", "b\n", "c\n") == "c\n"
