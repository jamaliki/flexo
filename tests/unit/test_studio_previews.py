"""A figure drawn in a design before it is chosen (``flexo.studio.previews``), for the figure
editor's Design bar: each variant -- a theme, a palette, a font -- drawn in order, the figure's
file left as it is, one that can't be drawn said in its place, a drawing kept while what it was
drawn from is; asked of the studio, a read (no drawing gives way to it), drawn with the folder's
trust as the figure's own drawings are."""

from __future__ import annotations

import json
import threading
import urllib.request
from collections import OrderedDict
from collections.abc import Iterator
from pathlib import Path

import pytest

from flexo.studio import code_allowed
from flexo.studio import previews as previews_module
from flexo.studio.figure_kind import SAMPLE_FIGURE, FigureKind
from flexo.studio.server import start
from flexo.studio.workspace import Workspace

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    monkeypatch.setattr(previews_module, "_kept", OrderedDict())
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("run")))


def _asked(variants: list[object], base: Path, text: str = SAMPLE_FIGURE) -> list[dict]:
    action = {"do": "previews", "variants": variants}
    return FigureKind().act({"text": text}, action, base)["previews"]


def test_each_variant_is_the_figure_drawn_so_in_order(tmp_path: Path) -> None:
    paper, dark, tableau = _asked(
        [{"figure.style": None}, {"figure.style": "dark"}, {"figure.palette": "Tableau"}], tmp_path
    )
    assert all("<svg" in item["svg"] and item["key"] for item in (paper, dark, tableau))
    assert len({paper["svg"], dark["svg"], tableau["svg"]}) == 3


def test_the_figure_is_left_as_it_is(tmp_path: Path) -> None:
    document = {"text": SAMPLE_FIGURE}
    answer = FigureKind().act(
        document, {"do": "previews", "variants": [{"figure.style": "dark"}]}, tmp_path
    )
    assert document == {"text": SAMPLE_FIGURE} and set(answer) == {"previews"}


def test_a_design_that_cant_be_drawn_is_said_in_its_place(tmp_path: Path) -> None:
    wrong, right = _asked([{"figure.style": "no-such-theme"}, {"figure.style": "swiss"}], tmp_path)
    assert wrong.get("error") and "svg" not in wrong
    assert "<svg" in right["svg"]


def test_a_variant_changes_the_design_alone(tmp_path: Path) -> None:
    plain, relabelled = _asked([{}, {"label": "Other", "nodes": []}], tmp_path)
    assert plain["svg"] == relabelled["svg"]


def test_a_drawing_is_kept_while_the_figure_is_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drawn: list[int] = []
    real = previews_module._draw

    def counted(*args: object) -> tuple[dict, list[Path]]:
        drawn.append(1)
        return real(*args)

    monkeypatch.setattr(previews_module, "_draw", counted)
    first = _asked([{"figure.style": "rams"}], tmp_path)
    assert _asked([{"figure.style": "rams"}], tmp_path) == first and len(drawn) == 1
    _asked([{"figure.style": "rams"}], tmp_path, SAMPLE_FIGURE.replace("Encoder", "Decoder"))
    assert len(drawn) == 2


def test_a_preview_is_a_read_that_no_drawing_gives_way_to(tmp_path: Path) -> None:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    workspace = Workspace(tmp_path)
    try:
        workspace.acting("figure.yaml", {"do": "previews", "variants": []})
        assert workspace.acts.get("figure.yaml", 0) == 0
        workspace.acting("figure.yaml", {"do": "update"})
        assert workspace.acts["figure.yaml"] == 1
    finally:
        workspace.close()


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[str, Workspace]]:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    server, workspace = start(tmp_path / "figure.yaml", browser=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", workspace
    finally:
        workspace.close()
        server.shutdown()
        server.server_close()


def test_the_studio_draws_previews_with_the_folders_trust(
    served: tuple[str, Workspace], monkeypatch: pytest.MonkeyPatch
) -> None:
    url, workspace = served
    trusted: list[bool] = []
    real = previews_module.previews

    def watched(*args: object) -> dict:
        trusted.append(code_allowed.get())
        return real(*args)

    monkeypatch.setattr(previews_module, "previews", watched)
    workspace.trusted = False
    body = {
        "file": "figure.yaml",
        "document": {"text": SAMPLE_FIGURE},
        "action": {"do": "previews", "variants": [{"figure.style": "dark"}]},
    }
    request = urllib.request.Request(
        f"{url}/api/act",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Studio-Token": workspace.token},
    )
    with OPENER.open(request) as response:
        answer = json.loads(response.read())
    assert "<svg" in answer["previews"][0]["svg"]
    assert trusted == [False]
