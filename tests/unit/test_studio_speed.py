"""The studio keeps up with typing: a document is written without holding up the edits made
meanwhile, a deck's YAML is written over from the slides that changed, and answers go to the
page as they are."""

from __future__ import annotations

import copy
import json
import threading
import time
import urllib.request
from collections import OrderedDict
from pathlib import Path

import pytest
import yaml

from flexo import roundtrip
from flexo.studio.figure_kind import SAMPLE_FIGURE
from flexo.studio.server import start
from flexo.studio.workspace import Workspace

PERSON = {"id": "page-a", "name": "Ada", "kind": "person"}


@pytest.fixture(autouse=True)
def _sessions(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("run")))


def test_edits_are_taken_while_the_document_is_being_written(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("figure.yaml")
        writing, go = threading.Event(), threading.Event()
        save = doc.kind.save

        def slow(path, document, *args, **kwargs):
            writing.set()
            assert go.wait(10)
            return save(path, document, *args, **kwargs)

        doc.kind.save = slow
        first = SAMPLE_FIGURE.replace("Input $x$", "Input $x_0$")
        doc.update({"text": first}, 1, PERSON)
        writer = threading.Thread(target=doc.write)
        writer.start()
        assert writing.wait(10)
        # Taken at once, the file still being written with the edit before it.
        started = time.monotonic()
        second = first.replace("Output $y$", "Output $z$")
        version, _ = doc.update({"text": second}, 2, PERSON)
        assert version == 3 and time.monotonic() - started < 2
        go.set()
        writer.join(10)
        assert doc.saved == 2 or doc.saved == 3
        doc.kind.save = save
        workspace.flush()
        assert doc.saved == 3
        assert "Output $z$" in (tmp_path / "figure.yaml").read_text(encoding="utf-8")
    finally:
        workspace.close()


DECK = """\
# The lab meeting -- keep this comment
schema_version: 1
deck:
  id: talk
  theme: paper   # chosen by Kiarash

slides:
# --- opening ---
- title: "Making it fast"
  subtitle: 'What we found'
  layout: title

- title: The pipeline   # the first real slide
  body:
  - bullets:
    - Generate   # step one
    - Design
    - "Quoted: with a colon"
  - figure:
      nodes:
      - id: start
        label: Start
      - {id: check, label: Check}
# A comment between slides, over the third.
- title: Words
  body:
  - text: |
      A literal block,
      over two lines.
  notes: Say this slowly.

  # A comment inside a slide, after a blank line.
- title: LONG
  body:
  - bullets: [one, two, three]
- layout: section
  title: Part two
- title: Shapes
  shapes:
  - kind: rectangle
    at: [100, 120]   # where it was put
    size: [200, 100]
- title: Last one
  body:
  - bullets:
    - 'no'
    - "12"
# end of the slides

figures:
  pipeline:
    nodes:
    - id: a
      label: A
# the very end
""".replace("LONG", "A very long title, past where a line is wrapped, going on" + " and on" * 9)


def _edits(document: dict) -> list[dict]:
    """A run of edits as typing and dragging make them, each from the one before."""

    made, now = [], copy.deepcopy(document)

    def then(change) -> None:
        nonlocal now
        now = copy.deepcopy(now)
        change(now["slides"])
        made.append(now)

    then(lambda slides: slides[1]["body"][0]["bullets"].__setitem__(1, "Design it"))
    then(lambda slides: slides[1]["body"][0]["bullets"].pop(0))  # a bullet taken out...
    made.append(copy.deepcopy(made[0]))  # ... and put back (an undo)
    now = copy.deepcopy(made[-1])
    then(lambda slides: slides[2].__setitem__("title", "Words, words"))
    then(lambda slides: slides[5]["shapes"][0].__setitem__("at", [104.5, 120]))
    then(lambda slides: slides[0].__setitem__("title", "Making it faster"))
    then(lambda slides: slides[6]["body"][0]["bullets"].append("yes, quoted"))
    then(lambda slides: slides[3].__setitem__("notes", "A note\nover two lines"))
    then(lambda slides: (slides[0].pop("subtitle"), slides[6].__setitem__("title", "Last")))
    return made


def _whole(previous: str, document: dict, kept) -> str:
    token = roundtrip._GONE.set(kept)
    try:
        return roundtrip._rewrite_whole(previous, document, lambda data: yaml.safe_dump(data))
    finally:
        roundtrip._GONE.reset(token)


def _in_part(previous: str, document: dict, kept) -> str | None:
    token = roundtrip._GONE.set(kept)
    try:
        return roundtrip._in_part(previous, document)
    finally:
        roundtrip._GONE.reset(token)


def test_a_deck_written_over_from_its_changed_slides_is_the_file_written_whole() -> None:
    previous = DECK
    whole_kept: tuple = (OrderedDict(), OrderedDict())
    part_kept: tuple = (OrderedDict(), OrderedDict())
    for document in _edits(yaml.safe_load(DECK)):
        whole = _whole(previous, document, whole_kept)
        part = _in_part(previous, document, part_kept)
        assert part == whole
        previous = whole
    # The comments the person wrote are all there still.
    for comment in (
        "# The lab meeting",
        "# chosen by Kiarash",
        "# --- opening ---",
        "# where it was put",
        "# end of the slides",
        "# the very end",
    ):
        assert comment in previous


def test_what_is_not_an_edit_of_slides_in_place_is_written_whole() -> None:
    document = yaml.safe_load(DECK)
    added = copy.deepcopy(document)
    added["slides"].insert(2, {"title": "New"})
    assert _in_part(DECK, added, None) is None
    moved = copy.deepcopy(document)
    moved["slides"].append(moved["slides"].pop(1))
    assert _in_part(DECK, moved, None) is None
    deck = copy.deepcopy(document)
    deck["deck"]["theme"] = "dark"
    assert _in_part(DECK, deck, None) is None
    anchored = DECK.replace("theme: paper", "theme: &look paper")
    typed = copy.deepcopy(document)
    typed["slides"][1]["title"] = "Typed"
    assert _in_part(anchored, typed, None) is None
    assert _in_part(DECK, typed, None) is not None


def test_a_file_opened_is_read_ahead_a_little_at_a_time_for_its_first_writing() -> None:
    roundtrip._READ.clear()
    rounds = 1
    while not roundtrip.prime(DECK, budget=0.0):  # (one part at a time)
        rounds += 1
    assert rounds > 5
    read = len(roundtrip._READ)
    document = yaml.safe_load(DECK)
    document["slides"][2]["title"] = "Words, words"
    assert _in_part(DECK, document, None) == _whole(DECK, document, None)
    assert len(roundtrip._READ) == read  # (every part of the file read before)


def test_a_long_deck_is_written_over_in_a_fraction_of_the_time_of_the_whole() -> None:
    slides = [
        {
            "title": f"Slide {n}",
            "body": [{"bullets": [f"Point {n} " * 6, ["sub a", "sub b"]]}],
            "notes": f"Notes for slide {n}",
        }
        for n in range(60)
    ]
    previous = yaml.safe_dump(
        {"schema_version": 1, "deck": {"id": "long"}, "slides": slides}, sort_keys=False, width=100
    )
    document = yaml.safe_load(previous)
    document["slides"][30]["title"] += " typed"

    def fastest(write) -> float:
        best = float("inf")
        for _ in range(3):
            started = time.process_time()
            write()
            best = min(best, time.process_time() - started)
        return best

    part = fastest(lambda: _in_part(previous, document, None))
    whole = fastest(lambda: _whole(previous, document, None))
    assert _in_part(previous, document, None) == _whole(previous, document, None)
    # (About a seventh; asked for a half, for a busy computer's sake.)
    assert part < whole / 2


def test_answers_go_to_the_page_as_they_are(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    server, workspace = start(tmp_path / "figure.yaml", browser=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/api/open?file=figure.yaml"
        request = urllib.request.Request(
            url, headers={"X-Studio-Token": workspace.token, "Accept-Encoding": "gzip"}
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request) as reply:
            assert reply.headers.get("Content-Encoding") is None
            assert json.loads(reply.read())["file"] == "figure.yaml"
    finally:
        workspace.close()
        server.shutdown()
        server.server_close()


def test_a_bundle_left_alone_is_looked_at_less_often_and_at_once_when_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from flexo import bundle as B
    from flexo.studio import bundles as studio_bundles

    monkeypatch.setenv("FLEXO_BUNDLES", str(tmp_path / "bundles"))
    folder = tmp_path / "made"
    folder.mkdir()
    (folder / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    keeper = studio_bundles.opened(B.pack(folder / "figure.yaml", tmp_path / "Figure.flexo").path)
    keeper.step(now=100.0)
    assert keeper._interval(101.0) == studio_bundles.POLL
    assert keeper._interval(100.0 + studio_bundles.RESTED + 1) == studio_bundles.RESTING
    edited = SAMPLE_FIGURE.replace("Input $x$", "Input $x_0$")
    (keeper.root / "figure.yaml").write_text(edited, encoding="utf-8")
    keeper.step(now=200.0)  # (changed, waiting to be written: looked at as often as ever)
    assert keeper._interval(200.0 + studio_bundles.RESTED + 1) == studio_bundles.POLL
    keeper._wake.clear()
    keeper.nudge()  # (a document the studio wrote: looked at now)
    assert keeper._wake.is_set()


def test_a_photograph_kept_from_another_run_of_the_studio_is_shown_with_this_runs_token(
    tmp_path: Path,
) -> None:
    from flexo.studio import Drawing, Page

    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        doc = workspace.open("figure.yaml")
        kept = '<svg><image href="/api/picture?path=a.png&amp;v=1&amp;token=another-run"/></svg>'
        doc.kind.draw = lambda document, base, hints: Drawing([Page("figure", kept)])
        result = workspace.draw("figure.yaml", doc.document, 1, {}, {})
        (page,) = result["pages"]
        assert f"token={workspace.token}" in page["svg"] and "another-run" not in page["svg"]
        again = workspace.draw("figure.yaml", doc.document, 2, {"figure": page["hash"]}, {})
        assert "svg" not in again["pages"][0]  # (the same drawing: not sent again)
    finally:
        del doc.kind.draw
        workspace.close()


def test_who_can_answer_is_said_at_once_as_last_found_while_nothing_deciding_it_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from flexo.studio import availability
    from flexo.studio.server import _assistant_said

    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "anthropic"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-test-key")
    assert availability.remembered() is None
    workspace = Workspace(tmp_path)
    try:
        found = _assistant_said(workspace)  # (found out, the SDKs asked)
        assert workspace.assistant is not None
    finally:
        workspace.close()
    kept = availability.remembered()
    assert kept == {key: found[key] for key in kept}
    assert "a-test-key" not in availability._file().read_text(encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        # A studio started again says so at once, its assistant not yet made.
        assert _assistant_said(workspace) == {**kept, "running": False, "transcript": []}
        assert workspace.assistant is None
    finally:
        workspace.close()
    # A key changed, or the SDK's configuration, and it is found out again.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "another-test-key")
    assert availability.remembered() is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-test-key")
    assert availability.remembered() == kept
    (tmp_path / "anthropic").mkdir()
    (tmp_path / "anthropic" / "active_config").write_text("work\n", encoding="utf-8")
    assert availability.remembered() is None


def test_the_assistant_is_found_out_again_once_the_pages_stop_asking_for_drawings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from flexo.studio import availability, warmup

    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "anthropic"))
    monkeypatch.setattr(warmup, "QUIET", 0.4)
    availability.remember({"available": False, "why": "As it was.", "provider": "nobody"})
    workspace = Workspace(tmp_path)
    told: list[dict] = []
    workspace.broadcast = told.append
    try:
        workspace.drawn_at = time.monotonic()
        warmup.warm_assistant(workspace)
        for _ in range(6):  # (a page drawing its slides)
            time.sleep(0.1)
            workspace.drawn_at = time.monotonic()
        assert workspace.assistant is None
        deadline = time.monotonic() + 20
        while not told and time.monotonic() < deadline:
            time.sleep(0.05)
        assert workspace.assistant is not None
        # The pages told who answers, as it is found now.
        assert told[0]["event"] == "availability" and told[0]["provider"] != "nobody"
        assert availability.remembered()["provider"] == told[0]["provider"]
    finally:
        workspace.close()
