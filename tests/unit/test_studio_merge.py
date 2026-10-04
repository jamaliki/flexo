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


def test_a_slide_added_beside_one_the_other_side_edited_keeps_both() -> None:
    slides = [{"title": t, "body": [{"text": f"{t}."}]} for t in "ABCDE"]
    base = deck(*slides)
    ours = deck(*slides[:3], {"title": "New"}, *slides[3:])
    theirs = deck(*slides[:3], {**slides[3], "title": "D, by Bob"}, slides[4])
    for merged in (merge3(base, ours, theirs), merge3(base, theirs, ours)):
        assert [s["title"] for s in merged["slides"]] == ["A", "B", "C", "New", "D, by Bob", "E"]


def test_a_paragraph_added_beside_one_the_other_side_typed_in_keeps_both() -> None:
    base = {"body": [{"text": "First paragraph."}, {"text": "Second paragraph."}]}
    ours = {"body": [{"text": "First paragraph."}, {"text": "New"}, {"text": "Second paragraph."}]}
    theirs = {"body": [{"text": "First paragraph."}, {"text": "Second paragraph. More"}]}
    assert merge3(base, ours, theirs)["body"] == [
        {"text": "First paragraph."},
        {"text": "New"},
        {"text": "Second paragraph. More"},
    ]


def test_a_slide_moved_while_the_other_side_types_in_it_moves_with_the_typing() -> None:
    slides = [{"title": t, "body": [{"text": f"{t}."}]} for t in "ABCDE"]
    base = deck(*slides)
    ours = deck(*slides[:3], {**slides[3], "title": "D and then we typ"}, slides[4])
    theirs = deck(slides[0], slides[1], slides[3], slides[2], slides[4])
    for merged in (merge3(base, ours, theirs), merge3(base, theirs, ours)):
        assert [s["title"] for s in merged["slides"]] == ["A", "B", "D and then we typ", "C", "E"]
        assert merged["slides"][2]["body"] == [{"text": "D."}]


def test_undo_takes_back_only_its_own_addition() -> None:
    before = {"body": [{"text": "p0"}, {"text": "p1"}]}
    after = {"body": [{"text": "p0"}, {"text": "Alice's"}, {"text": "p1"}]}
    now = {"body": [{"text": "p0"}, {"text": "Alice's"}, {"text": "p1, edited by Bob"}]}
    assert merge3(after, now, before) == {"body": [{"text": "p0"}, {"text": "p1, edited by Bob"}]}


def test_an_item_removed_by_one_side_and_edited_by_the_other_is_kept_edited() -> None:
    assert merge3(["a b", "c d"], ["a b"], ["a b", "c d e"]) == ["a b", "c d e"]
    assert merge3(["a b", "c d"], ["a b", "c d e"], ["a b"]) == ["a b", "c d e"]
    # And said, for whoever was editing it.
    base = {"body": [{"text": "P"}, {"text": "Q"}]}
    edited = {"body": [{"text": "P, typed on"}, {"text": "Q"}]}
    notes: list = []
    merge3(base, edited, {"body": [{"text": "Q"}]}, notes)
    assert notes == [{"kept": "ours", "item": {"text": "P, typed on"}}]
    notes.clear()
    merge3(base, {"body": [{"text": "Q"}]}, edited, notes)
    assert notes == [{"kept": "theirs", "item": {"text": "P, typed on"}}]


def test_words_written_anew_while_typed_in_are_kept_whole_with_the_typing_after() -> None:
    # A sentence rewritten while words were typed after its first word: not a jumble of
    # both, held together by their spaces, but the new sentence and the words typed.
    base = "First paragraph written by Alice."
    typing = "First m0 m1 m2 m3paragraph written by Alice."
    notes: list = []
    merged = merge3(base, typing, "A completely different sentence.", notes)
    assert merged == "A completely different sentence. m0 m1 m2 m3"
    assert notes == [{"rewritten": "theirs", "words": merged, "typed": "m0 m1 m2 m3"}]
    assert merge3(base, "A completely different sentence.", typing) == merged
    # The space typed after the last word stays, for the next.
    assert merge3(base, "First m0 paragraph written by Alice.", "Something new.") == (
        "Something new. m0 "
    )
    # The page, typing on as the merged words come back: the typing goes on after them.
    assert (
        merge3(
            "First m0 m1 m2 m3 paragraph written by Alice.",
            "A completely different sentence. m0 m1 m2 m3",
            "First m0 m1 m2 m3 m4paragraph written by Alice.",
        )
        == "A completely different sentence. m0 m1 m2 m3 m4"
    )
    # Typed on from words kept before, the typing runs on from them.
    assert (
        merge3(
            "First m0 mparagraph written by Alice.",
            "A different sentence. m0 m",
            "First m0 m3paragraph written by Alice.",
        )
        == "A different sentence. m0 m3"
    )
    # A line of several rewritten: the typing goes before its end.
    assert merge3("one\ntwo three\n", "one\ntwo three four\n", "one\nfive\n") == (
        "one\nfive four\n"
    )
    # A title retitled while typed on keeps both.
    assert merge3("Title", "Title of the talk", "Heading") == "Heading of the talk"
    # Both written anew: the newer stands, as for any words changed both ways.
    assert merge3("one two three", "four five six", "seven eight nine") == "seven eight nine"


def test_words_taken_away_while_typed_among_go_and_the_typing_stays() -> None:
    assert merge3("a b c d e f", "a b e f", "a b c x d e f") == "a b x e f"
    assert merge3("a b c d e f", "a b c x d e f", "a b e f") == "a b x e f"


def test_items_both_sides_added_are_each_kept_however_alike() -> None:
    # Two people adding a new slide at one place at once: two slides, each typed in by its own.
    new = {"title": "", "body": [{"bullets": [""]}]}
    deck = {"slides": [{"title": "One"}, {"title": "Two"}]}
    both = {"slides": [{"title": "One"}, new, {"title": "Two"}]}
    assert merge3(deck, both, both)["slides"] == [{"title": "One"}, new, new, {"title": "Two"}]
    assert merge3([1, 2], [1, 2, {"a": 1}], [1, 2, {"a": 1}]) == [1, 2, {"a": 1}, {"a": 1}]
    assert merge3(["a"], ["x", "a"], ["a", "x"]) == ["x", "a", "x"]
    # Both changed alike, words or a setting are one change.
    assert merge3({"size": 30}, {"size": 40}, {"size": 40}) == {"size": 40}
    assert merge3(["a", "b"], ["a", "c"], ["a", "c"]) == ["a", "c"]


def test_numbers_in_a_list_merge_place_by_place() -> None:
    assert merge3([0.5, 0.5], [0.3, 0.5], [0.5, 0.6]) == [0.3, 0.6]
    assert merge3([0.5, 0.5], [0.3, 0.7], [0.4, 0.6]) == [0.4, 0.6]


def test_shapes_are_known_by_their_ids() -> None:
    base = {"nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
    ours = {"nodes": [{"id": "b", "label": "B"}, {"id": "a", "label": "A"}]}
    theirs = {"nodes": [{"id": "a", "label": "A, renamed"}, {"id": "b", "label": "B"}]}
    assert merge3(base, ours, theirs) == {
        "nodes": [{"id": "b", "label": "B"}, {"id": "a", "label": "A, renamed"}]
    }


def test_letters_two_people_type_into_one_word_are_both_kept() -> None:
    # Two people typing on at one place, their words run together: each letter stays
    # where it was typed, none lost to the other's.
    assert merge3("A mc", "A m4c", "A mco") == "A m4co"
    assert merge3("A m", "A m4", "A mc") == "A m4c"


def test_undone_typing_leaves_words_typed_after_it_letter_by_letter() -> None:
    # Words typed here, undone while another types on after them, a letter at a time: the
    # undo takes back these words alone, and each of his letters still comes.
    before, after = "Second paragraph.", "Second paragraph. alicewords"
    for n in range(1, len(" bobafter") + 1):
        theirs = " bobafter"[:n]
        assert merge3(after, after + theirs, before) == before + theirs
        if n > 1:
            assert merge3(after + theirs[:-1], after + theirs, before + theirs[:-1]) == (
                before + theirs
            )


def test_two_typing_at_one_end_keep_their_words_apart() -> None:
    # Each started a word at the same place: never run together into one.
    assert merge3("What we asked ", "What we asked a", "What we asked b") == "What we asked a b"
    # One typing on in her word as the other's arrives after it.
    assert merge3("What we asked a", "What we asked a b", "What we asked al") == (
        "What we asked al b"
    )


def test_a_word_made_bold_while_another_types_in_it_keeps_both() -> None:
    # Each run of letters changed is its own: the two ends made bold, the letters typed between.
    assert merge3("First paragraph w", "First **paragraph** w", "First paraQQgraph w") == (
        "First **paraQQgraph** w"
    )
    assert merge3("First paragraph w", "First paraQQgraph w", "First [paragraph](x.org) w") == (
        "First [paraQQgraph](x.org) w"
    )
    # A word written anew is one change, not the letters it shares with the old: the newer stands.
    assert merge3("a paragraph", "a page", "a paraQQgraph") == "a paraQQgraph"


def test_an_object_moved_to_another_column_while_typed_in_goes_with_the_typing() -> None:
    base = {"body": [{"text": "First."}, {"text": "Second paragraph."}]}
    typed = {"body": [{"text": "First."}, {"text": "Second paragraph. alice"}]}
    laid = {
        "layout": "two-columns",
        "left": [{"text": "First."}],
        "right": [{"text": "Second paragraph."}],
    }
    for ours, theirs in ((typed, laid), (laid, typed)):
        merged = merge3(base, ours, theirs)
        # One copy, where it went, with the typing: no body left beside the columns.
        assert "body" not in merged
        assert merged["right"] == [{"text": "Second paragraph. alice"}]


def test_a_slide_moved_and_changed_while_typed_in_is_one_slide() -> None:
    def slide(title: str, words: str) -> dict:
        return {"title": title, "body": [{"text": "First."}, {"text": words}]}

    base = deck({"title": "0"}, {"title": "1"}, slide("The question", "Second paragraph."))
    typed = deck({"title": "0"}, {"title": "1"}, slide("The question", "Second paragraph. alice"))
    moved = deck({"title": "0"}, slide("The question moved", "Second paragraph."), {"title": "1"})
    for ours, theirs in ((typed, moved), (moved, typed)):
        assert merge3(base, ours, theirs)["slides"] == [
            {"title": "0"},
            slide("The question moved", "Second paragraph. alice"),
            {"title": "1"},
        ]
