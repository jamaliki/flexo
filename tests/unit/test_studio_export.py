"""The studio's exports: written into build/ beside a document for agents and the CLI, or
made aside and handed to the page's person -- downloaded (one file, or a zip of several),
or staged for the Mac app to move where its save panel says."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from flexo.studio.figure_kind import SAMPLE_FIGURE
from flexo.studio.server import start
from flexo.studio.workspace import Workspace

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@pytest.fixture(autouse=True)
def _sessions(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("run")))


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[str, Workspace, Path]]:
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    server, workspace = start(folder / "figure.yaml", browser=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", workspace, folder
    finally:
        workspace.close()
        server.shutdown()
        server.server_close()


def export(url: str, token: str, body: dict) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(
        f"{url}/api/export",
        data=json.dumps({"file": "figure.yaml", **body}).encode(),
        headers={"Content-Type": "application/json", "X-Studio-Token": token},
    )
    try:
        with OPENER.open(request) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def test_an_export_is_written_into_build_by_default(served) -> None:
    url, workspace, folder = served
    status, _, body = export(url, workspace.token, {"formats": ["pdf"]})
    assert status == 200
    files = json.loads(body)["files"]
    assert "build/figure.pdf" in files and (folder / "build" / "figure.pdf").is_file()


def test_one_file_is_downloaded_as_itself_and_nothing_is_left_beside_it(served) -> None:
    url, workspace, folder = served
    asked = {"formats": ["pdf"], "deliver": "download"}
    status, headers, body = export(url, workspace.token, asked)
    assert status == 200 and body.startswith(b"%PDF")
    assert headers["Content-Type"] == "application/pdf"
    assert headers["Content-Disposition"].startswith('attachment; filename="figure.pdf"')
    # Only what was asked for: not the editable SVG every build writes as well.
    assert sorted(path.name for path in folder.iterdir()) == ["figure.yaml"]
    assert not list(Path(tempfile.gettempdir()).glob("flexo-export-*/files/figure.pdf"))


def test_several_files_are_downloaded_as_a_zip(served) -> None:
    url, workspace, folder = served
    status, headers, body = export(
        url, workspace.token, {"formats": ["pdf", "png"], "deliver": "download"}
    )
    assert status == 200 and headers["Content-Type"] == "application/zip"
    assert "filename*=UTF-8''figure.zip" in headers["Content-Disposition"]
    names = zipfile.ZipFile(io.BytesIO(body)).namelist()
    assert {"figure.pdf", "figure.preview.png"} <= set(names)
    assert not (folder / "build").exists()


def test_a_staged_export_waits_aside_for_the_app_to_move_it(served) -> None:
    url, workspace, folder = served
    status, _, body = export(url, workspace.token, {"formats": ["png"], "deliver": "staged"})
    made = json.loads(body)
    assert status == 200 and made["name"] == "figure.preview.png" and made["folder"] is False
    path = Path(made["path"])
    try:
        assert path.is_file() and path.parent.parent.name.startswith("flexo-export-")
        assert not (folder / "build").exists()
    finally:
        shutil.rmtree(path.parent.parent, ignore_errors=True)


def test_an_export_is_delivered_only_in_ways_the_studio_knows(served) -> None:
    url, workspace, _ = served
    status, _, body = export(url, workspace.token, {"formats": ["pdf"], "deliver": "email"})
    assert status == 400 and "download" in json.loads(body)["error"]
