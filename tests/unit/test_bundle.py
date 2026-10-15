"""A document and every file it names as one file (``flexo.bundle``): what is gathered, written
and read back, what is left out and said, what a bundle from a stranger may not do, and a
bundle open in the studio kept in step with its working folder (``flexo.studio.bundles``)."""

from __future__ import annotations

import io
import json
import stat
import struct
import threading
import time
import urllib.request
import zipfile
import zlib
from pathlib import Path

import pytest
import yaml

from flexo import bundle as B
from flexo.bundle import Bundle, BundleError
from flexo.cli import main as flexo_main
from flexo.studio import bundles as studio_bundles

DATA = Path(__file__).parent / "data"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
SQUARE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    '<rect width="10" height="10"/></svg>'
)
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture(autouse=True)
def _apart(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    # Working folders, studios' session files and mol-sketch's downloads: the test's own.
    monkeypatch.setenv("FLEXO_BUNDLES", str(tmp_path_factory.mktemp("bundles")))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("run")))
    cache = tmp_path_factory.mktemp("molsketch")
    (cache / "1CRN.cif").write_text("data_1CRN\n# crambin, as fetched\n", encoding="utf-8")
    monkeypatch.setenv("MOLSKETCH_CACHE", str(cache))


def _write(path: Path, text: str | bytes = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


FIGURE = """\
figure: {id: everything, theme: themes/lab.theme.yaml, palette: colours.yaml}
nodes:
- {id: drawing, kind: image, properties: {source: art/glyph.svg}}
- {id: photo, kind: image, properties: {source: art/photo.png}}
- {id: page, kind: image, properties: {source: art/poster.pdf#2}}
- {id: protein, kind: structure, properties: {source: shared/protein.cif}}
- {id: fetched, kind: structure, properties: {source: 1crn}}
- {id: unfetched, kind: structure, properties: {source: 9ZZZ}}
- {id: em, kind: structure, properties: {source: model.pdb, density: maps/emd.map}}
- {id: auto, kind: structure, properties: {source: model.pdb, density: auto}}
- {id: reaction, kind: structure, properties: {source: scenes/reaction.json}}
- id: loss
  kind: plot
  properties: {source: plots/loss.py, function: loss, data: [data/runs/, "data/*.csv"]}
- {id: gone, kind: image, properties: {source: art/gone.png}}
- {id: away, kind: image, properties: {source: /etc/hosts}}
shapes:
- {kind: picture, at: [0, 0], size: [10, 10], source: assets/drawing-part-1.svg}
- kind: group
  shapes:
  - {kind: picture, at: [0, 0], size: [10, 10], source: assets/drawing-part-2.png}
"""


def _figure_folder(root: Path) -> Path:
    """A figure that names every kind of file a figure can, in a folder of its own."""

    folder = root / "paper"
    _write(folder / "figure.yaml", FIGURE)
    _write(
        folder / "themes/lab.theme.yaml", "theme: {name: lab, base: paper}\nfonts: [../fonts/]\n"
    )
    _write(folder / "fonts/Lab-Regular.ttf", b"font")
    _write(folder / "fonts/README.txt", "not a font")
    _write(folder / "colours.yaml", "palettes: {Lab: ['#123456']}\n")
    _write(folder / "art/glyph.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
    _write(folder / "art/photo.png", PNG)
    _write(folder / "art/poster.pdf", b"%PDF-1.4")
    _write(folder / "shared/protein.cif", "data_PROT\n")
    _write(folder / "model.pdb", "ATOM\n")
    _write(folder / "maps/emd.map", b"MAP")
    _write(folder / "scenes/reaction.json", (DATA / "pi_star.json").read_text(encoding="utf-8"))
    _write(
        folder / "plots/loss.py",
        "import helpers\nfrom tools import shapes\nfrom pathlib import Path\n\n"
        "HERE = Path(__file__).parent\n\n\ndef loss():\n"
        '    return open(HERE / "tables" / "loss.tsv").read()\n\n\n'
        'def other():\n    return open("never.csv")\n',
    )
    _write(folder / "plots/helpers.py", 'SETTINGS = "plots/style.json"\n')
    _write(folder / "plots/tools/__init__.py", "")
    _write(folder / "plots/tools/shapes.py", "")
    _write(folder / "plots/tables/loss.tsv", "1\t2\n")
    _write(folder / "plots/style.json", "{}")
    _write(folder / "plots/never.csv", "not this function's")
    _write(folder / "data/runs/a.h5", b"run a")
    _write(folder / "data/runs/b.h5", b"run b")
    _write(folder / "data/summary.csv", "x,y\n")
    _write(folder / "assets/drawing-part-1.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
    _write(folder / "assets/drawing-part-2.png", PNG)
    _write(folder / "notes.txt", "not named by the figure")
    return folder


# -- gathering ---------------------------------------------------------------------------


def test_a_figure_brings_every_file_it_names_and_those_they_name(tmp_path: Path) -> None:
    folder = _figure_folder(tmp_path)
    gathered = B.gather(folder / "figure.yaml")
    assert gathered.kind == "figure" and gathered.document == "figure.yaml"
    assert sorted(gathered.files) == [
        ".flexo/pdb/1CRN.cif",  # a PDB ID fetched before: kept, so it draws offline
        "art/glyph.svg",
        "art/photo.png",
        "art/poster.pdf",  # (its second page is what is named)
        "assets/drawing-part-1.svg",
        "assets/drawing-part-2.png",
        "colours.yaml",
        "data/runs/a.h5",
        "data/runs/b.h5",
        "data/summary.csv",
        "figure.yaml",
        "fonts/Lab-Regular.ttf",  # the theme file's fonts, named from its own folder
        "maps/emd.map",
        "model.pdb",
        "plots/helpers.py",  # imported from beside the plot's Python
        "plots/loss.py",
        "plots/style.json",  # named in so many words by a module it imports
        "plots/tables/loss.tsv",  # named by its function's words
        "plots/tools/__init__.py",
        "plots/tools/shapes.py",
        "scenes/reaction.json",
        "shared/protein.cif",
        "themes/lab.theme.yaml",
    ]
    assert "plots/never.csv" not in gathered.files  # another function's
    assert [(item.name, item.why) for item in gathered.left] == [
        ("art/gone.png", "missing"),
        ("/etc/hosts", "outside"),
    ]
    assert gathered.left[0].where == "nodes[10].source"


def test_a_file_outside_the_documents_folder_is_left_out_and_said(tmp_path: Path) -> None:
    folder = _figure_folder(tmp_path)
    _write(tmp_path / "shared/protein.cif", "data_PROT\n")
    (folder / "figure.yaml").write_text(
        FIGURE.replace("shared/protein.cif", "../../shared/protein.cif"), encoding="utf-8"
    )
    gathered = B.gather(folder / "figure.yaml")
    assert ("../../shared/protein.cif", "outside") in [(i.name, i.why) for i in gathered.left]
    assert not any("protein" in name for name in gathered.files)


def test_a_link_out_of_the_folder_is_outside_it(tmp_path: Path) -> None:
    folder = tmp_path / "talk"
    _write(tmp_path / "secret.png", PNG)
    _write(
        folder / "figure.yaml",
        "figure: {id: f}\nnodes:\n- {id: a, kind: image, properties: {source: pic.png}}\n",
    )
    (folder / "pic.png").symlink_to(tmp_path / "secret.png")
    gathered = B.gather(folder / "figure.yaml")
    assert [(item.name, item.why) for item in gathered.left] == [("pic.png", "outside")]
    assert sorted(gathered.files) == ["figure.yaml"]


# -- writing and reading -----------------------------------------------------------------


def test_a_bundle_unpacks_to_the_very_files_it_was_made_of(tmp_path: Path) -> None:
    folder = _figure_folder(tmp_path)
    made = B.pack(folder / "figure.yaml")
    assert made.path == folder / "figure.flexo" and made.path.is_file()
    about = made.about
    assert about["format"] == "flexo-bundle" and about["version"] == 1
    assert about["document"] == "figure.yaml" and about["kind"] == "figure"
    assert about["files"] == len(made.gathered.files) and about["app"]
    assert about["created"] == about["modified"] and about["created"].endswith("Z")
    assert about["missing"] == [{"name": "art/gone.png", "where": "nodes[10].source"}]
    assert about["outside"] == [{"name": "/etc/hosts", "where": "nodes[11].source"}]
    with zipfile.ZipFile(made.path) as archive:
        assert archive.testzip() is None
        assert archive.namelist()[:2] == ["manifest.json", "figure.yaml"]
        # Already packed, a picture is stored as it is; words are deflated.
        assert archive.getinfo("art/photo.png").compress_type == zipfile.ZIP_STORED
        assert archive.getinfo("plots/loss.py").compress_type == zipfile.ZIP_DEFLATED
        assert all(
            (info.external_attr >> 16) == stat.S_IFREG | 0o644 for info in archive.infolist()
        )
    out = tmp_path / "out"
    opened = B.unpack(made.path, out)
    assert opened.document == "figure.yaml" and opened.kind == "figure"
    assert [item["name"] for item in opened.left] == ["art/gone.png", "/etc/hosts"]
    for name, source in made.gathered.files.items():
        assert (out / name).read_bytes() == source.read_bytes(), name
    assert sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()) == sorted(
        made.gathered.files
    )
    # Never over a folder holding its files already.
    with pytest.raises(BundleError, match="already"):
        B.unpack(made.path, out)


def test_a_bundle_written_again_copies_what_did_not_change_as_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _figure_folder(tmp_path)
    files = {name: path for name, path in B.gather(folder / "figure.yaml").files.items()}
    target = tmp_path / "again.flexo"
    known = B.write(target, files, B.manifest("figure.yaml", "figure"))
    packed: list[str] = []
    real = B._Writer.add_file

    def counted(self, name, source, mtime):
        packed.append(name)
        return real(self, name, source, mtime)

    monkeypatch.setattr(B._Writer, "add_file", counted)
    (folder / "figure.yaml").write_text(FIGURE + "# changed\n", encoding="utf-8")
    B.write(target, files, B.manifest("figure.yaml", "figure"), previous=target, known=known)
    assert packed == ["figure.yaml"]
    # Not known (a bundle opened, not written here): what reads the same is copied too.
    packed.clear()
    B.write(target, files, B.manifest("figure.yaml", "figure"), previous=target)
    assert packed == []
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert archive.read("figure.yaml").endswith(b"# changed\n")
        assert archive.read("maps/emd.map") == b"MAP"


def test_a_bundle_never_half_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = _figure_folder(tmp_path)
    made = B.pack(folder / "figure.yaml")
    before = made.path.read_bytes()

    def broken(self, name, source, mtime):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(B._Writer, "add_file", broken)
    with pytest.raises(OSError):
        B.write(made.path, {"figure.yaml": folder / "figure.yaml"}, B.manifest("figure.yaml"))
    assert made.path.read_bytes() == before
    assert [p.name for p in made.path.parent.iterdir() if p.name.startswith(".")] == []


def test_a_bundle_zipped_in_the_finder_opens_too(tmp_path: Path) -> None:
    zipped = tmp_path / "talk.flexo"
    with zipfile.ZipFile(zipped, "w") as archive:
        archive.writestr("talk/figure.yaml", "figure: {id: f}\nnodes: []\n")
        archive.writestr("talk/pic.png", PNG)
        archive.writestr("__MACOSX/talk/._pic.png", b"resource fork")
        archive.writestr("talk/.DS_Store", b"finder")
    with Bundle(zipped) as opened:
        assert opened.document == "figure.yaml" and opened.manifest == {}
        assert sorted(opened.names) == ["figure.yaml", "pic.png"]


# -- a bundle from a stranger --------------------------------------------------------------


def _zip(path: Path, entries: list[tuple[zipfile.ZipInfo | str, bytes]]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json", json.dumps({"format": "flexo-bundle", "document": "a.yaml"})
        )
        archive.writestr("a.yaml", "figure: {id: a}\nnodes: []\n")
        for info, data in entries:
            archive.writestr(info, data)
    return path


@pytest.mark.parametrize(
    "name", ["../evil.py", "/etc/passwd", "a/../../evil", "C:/evil", "a\\..\\evil", "a//b", "./a"]
)
def test_a_name_out_of_the_bundle_is_refused(tmp_path: Path, name: str) -> None:
    path = _zip(tmp_path / "bad.flexo", [(zipfile.ZipInfo(name), b"x")])
    with pytest.raises(BundleError, match="isn\u2019t opened"):
        Bundle(path)
    assert not (tmp_path / "evil.py").exists()


def test_a_link_in_a_bundle_is_refused(tmp_path: Path) -> None:
    link = zipfile.ZipInfo("pictures/photo.png")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    path = _zip(tmp_path / "bad.flexo", [(link, b"/Users/someone/.ssh/id_ed25519")])
    with pytest.raises(BundleError, match="holds a link"):
        Bundle(path)


def test_a_zip_bomb_is_refused_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Packed tight: a gigabyte of nothing in a megabyte -- claimed by its sizes, never unpacked.
    path = tmp_path / "bomb.flexo"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("a.yaml", "figure: {id: a}\nnodes: []\n")
        with archive.open("data/zeros.bin", "w", force_zip64=True) as entry:
            block = bytes(1 << 20)
            for _ in range(40):
                entry.write(block)
    monkeypatch.setattr(B, "MOST_BYTES", 32 * 1024 * 1024)
    with pytest.raises(BundleError, match="more than"):
        Bundle(path)
    # And a header claiming far less than it holds: its entry is read no further than claimed.
    liar = tmp_path / "liar.flexo"
    _zip(liar, [("data/zeros.bin", bytes(1 << 16))])
    raw = bytearray(liar.read_bytes())
    at = raw.rfind(b"PK\x01\x02")  # the last entry in the central directory
    struct.pack_into("<I", raw, at + 24, 100)  # its size, said to be 100 bytes
    liar.write_bytes(bytes(raw))
    with pytest.raises(BundleError), Bundle(liar) as opened:
        opened.extract(tmp_path / "liar")


def test_two_names_a_mac_takes_for_one_are_refused(tmp_path: Path) -> None:
    path = _zip(tmp_path / "bad.flexo", [("Photo.png", PNG), ("photo.png", b"other")])
    with pytest.raises(BundleError, match="take for one"):
        Bundle(path)
    path = _zip(tmp_path / "worse.flexo", [("assets", b"a file"), ("assets/x.png", PNG)])
    with pytest.raises(BundleError, match="a file and a"):
        Bundle(path)


def test_a_bundle_that_is_no_zip_says_so(tmp_path: Path) -> None:
    path = _write(tmp_path / "talk.flexo", "slides: []\n")
    with pytest.raises(BundleError, match="can\u2019t be opened as a Flexo bundle"):
        Bundle(path)


def test_unpacking_never_writes_through_a_link_in_the_folder(tmp_path: Path) -> None:
    path = _zip(tmp_path / "talk.flexo", [("assets/x.png", PNG)])
    folder, elsewhere = tmp_path / "folder", tmp_path / "elsewhere"
    folder.mkdir()
    elsewhere.mkdir()
    (folder / "assets").symlink_to(elsewhere)
    with Bundle(path) as opened, pytest.raises(BundleError, match="outside the folder"):
        opened.extract(folder, ["assets/x.png"], replace=True)
    assert not (elsewhere / "x.png").exists()


# -- the command line --------------------------------------------------------------------


def test_bundle_and_unbundle_on_the_command_line(tmp_path: Path, capsys) -> None:
    folder = _figure_folder(tmp_path)
    target = tmp_path / "sent" / "figure.flexo"
    assert flexo_main(["bundle", str(folder / "figure.yaml"), "-o", str(target)]) == 0
    said = capsys.readouterr()
    assert str(target) in said.out and "art/gone.png" in said.err and "/etc/hosts" in said.err
    out = tmp_path / "received"
    assert flexo_main(["unbundle", str(target), "-o", str(out)]) == 0
    assert (out / "plots/tables/loss.tsv").read_text(encoding="utf-8") == "1\t2\n"
    assert flexo_main(["unbundle", str(target), "-o", str(out)]) == 2  # never over it


def test_a_figure_builds_straight_from_its_bundle(tmp_path: Path, capsys) -> None:
    folder = tmp_path / "fig"
    _write(
        folder / "figure.yaml",
        "figure: {id: fig}\nnodes:\n"
        "- {id: a, kind: image, properties: {source: art/glyph.svg}}\n- {id: b, label: Words}\n",
    )
    _write(folder / "art/glyph.svg", SQUARE)
    made = B.pack(folder / "figure.yaml", tmp_path / "fig.flexo")
    out = tmp_path / "build"
    assert flexo_main(["build", str(made.path), "-o", str(out), "--formats", "editable"]) == 0
    assert (out / "fig.editable.svg").is_file()
    # A bundle bringing Python is built only when its person says they trust it.
    _write(folder / "plot.py", "def loss():\n    return None\n")
    (folder / "figure.yaml").write_text(
        "figure: {id: fig}\nnodes:\n"
        "- {id: p, kind: plot, properties: {source: plot.py, function: loss}}\n",
        encoding="utf-8",
    )
    made = B.pack(folder / "figure.yaml", tmp_path / "plot.flexo")
    assert flexo_main(["build", str(made.path), "-o", str(out)]) == 2
    assert "--trust" in capsys.readouterr().err


# -- a PDB entry a bundle keeps ------------------------------------------------------------


def test_a_structure_named_by_its_id_draws_from_the_bundles_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("molsketch")
    import molsketch

    from flexo import structures
    from flexo.confine import folder_root

    root = tmp_path / "work"
    _write(root / ".flexo/pdb/1A7G.cif", (DATA / "1a7g.cif").read_text(encoding="utf-8"))

    def offline(pdb_id: str, **_: object):
        raise ConnectionError("no network in this test")

    monkeypatch.setattr(molsketch, "fetch", offline)
    structures._loaded.cache_clear()
    token = folder_root.set(root.resolve())
    try:
        assert structures._loaded("1a7g", 0.0) is not None
    finally:
        folder_root.reset(token)
    # Elsewhere, the bundle's copy is not this folder's: fetched, as ever.
    with pytest.raises(ConnectionError):
        structures._loaded("1a7g", 0.0)
    assert B.kept_entry("1a7g", root) == root / ".flexo/pdb/1A7G.cif"
    _write(root / ".flexo/pdb/2XYZ.cif", "not an entry")
    assert B.kept_entry("2XYZ", root) is None


# -- in the studio -----------------------------------------------------------------------


def _deck_free_bundle(tmp_path: Path) -> Path:
    folder = tmp_path / "made"
    _write(folder / "figure.yaml", "figure: {id: shared}\nnodes:\n- {id: a, label: First}\n")
    _write(folder / "art/photo.png", PNG)
    _write(
        folder / "sketch.yaml",
        "figure: {id: s}\nnodes:\n- {id: b, kind: image, properties: {source: art/photo.png}}\n",
    )
    (folder / "figure.yaml").write_text(
        "figure: {id: shared}\nnodes:\n- {id: a, label: First}\n"
        "- {id: p, kind: image, properties: {source: art/photo.png}}\n",
        encoding="utf-8",
    )
    return B.pack(folder / "figure.yaml", tmp_path / "Shared Figure.flexo").path


def test_a_bundle_opens_in_a_working_folder_of_its_own_and_again_as_it_was(tmp_path: Path) -> None:
    path = _deck_free_bundle(tmp_path)
    keeper = studio_bundles.opened(path)
    assert keeper.root.name == "Shared Figure" and keeper.document == "figure.yaml"
    assert keeper.root.is_relative_to(studio_bundles.support()) and not keeper.trusted
    assert (keeper.root / "art/photo.png").read_bytes() == PNG
    (keeper.root / "figure.yaml").touch()  # (not unpacked again: it keeps this)
    stamp = (keeper.root / "figure.yaml").stat().st_mtime_ns
    again = studio_bundles.opened(path)
    assert again.root == keeper.root and (again.root / "figure.yaml").stat().st_mtime_ns == stamp


def test_what_changes_in_the_folder_is_written_back_once_quiet(tmp_path: Path) -> None:
    path = _deck_free_bundle(tmp_path)
    keeper = studio_bundles.opened(path)
    document = keeper.root / "figure.yaml"
    document.write_text(
        document.read_text(encoding="utf-8").replace("First", "Edited"), encoding="utf-8"
    )
    _write(keeper.root / "assets/new.png", PNG)  # a picture dropped in
    keeper.step(now=100.0)
    assert b"Edited" not in zipfile.ZipFile(path).read("figure.yaml")  # (not yet: it changed)
    keeper.step(now=100.0 + keeper.quiet + 0.01)
    with zipfile.ZipFile(path) as archive:
        assert b"Edited" in archive.read("figure.yaml")
        assert archive.read("assets/new.png") == PNG
        about = json.loads(archive.read("manifest.json"))
    assert about["document"] == "figure.yaml" and about["files"] == 3
    assert keeper.problem is None


def test_a_bundle_saved_on_another_computer_is_taken_in_and_merged(tmp_path: Path) -> None:
    path = _deck_free_bundle(tmp_path)
    keeper = studio_bundles.opened(path)
    # Here: a line added, written in the folder, not yet in the bundle.
    ours = keeper.root / "figure.yaml"
    ours.write_text(
        ours.read_text(encoding="utf-8").replace("label: First", "label: Ours"), encoding="utf-8"
    )
    # There: another shape added, the bundle written as another Mac writes it.
    aside = tmp_path / "theirs"
    with Bundle(path) as opened:
        opened.extract(aside)
    # (As a studio writes a figure: its words, a line added.)
    theirs = (aside / "figure.yaml").read_text(encoding="utf-8") + "- {id: c, label: Theirs}\n"
    (aside / "figure.yaml").write_text(theirs, encoding="utf-8")
    files = {name: aside / name for name in B.snapshot(aside)}
    time.sleep(0.01)
    B.write(path, files, B.manifest("figure.yaml", "figure"))
    keeper.step(now=200.0)
    merged = yaml.safe_load(ours.read_text(encoding="utf-8"))
    assert [node.get("label") for node in merged["nodes"]] == ["Ours", None, "Theirs"]
    keeper.step(now=200.0 + keeper.patience + 1)
    written = yaml.safe_load(zipfile.ZipFile(path).read("figure.yaml"))
    assert [node.get("label") for node in written["nodes"]] == ["Ours", None, "Theirs"]


def test_edits_that_never_reached_a_bundle_changed_since_are_kept_beside_it(tmp_path: Path) -> None:
    path = _deck_free_bundle(tmp_path)
    keeper = studio_bundles.opened(path)
    (keeper.root / "figure.yaml").write_text(
        "figure: {id: shared}\nnodes:\n- {id: a, label: Mine}\n", encoding="utf-8"
    )
    # (The app quit before the bundle was written; it changed on another Mac meanwhile.)
    aside = tmp_path / "theirs"
    with Bundle(path) as opened:
        opened.extract(aside)
    (aside / "figure.yaml").write_text(
        "figure: {id: shared}\nnodes:\n- {id: a, label: Theirs}\n", encoding="utf-8"
    )
    B.write(path, {name: aside / name for name in B.snapshot(aside)}, B.manifest("figure.yaml"))
    again = studio_bundles.opened(path)
    assert again.conflict == "Shared Figure (edits not saved).flexo"
    assert b"Theirs" in (again.root / "figure.yaml").read_bytes()
    with Bundle(path.with_name(again.conflict)) as kept:
        assert b"Mine" in kept.read("figure.yaml")


def test_a_studio_serves_a_bundle_untrusted_and_saves_it_back(tmp_path: Path) -> None:
    from flexo.studio.server import start

    path = _deck_free_bundle(tmp_path)
    server, workspace = start(path, browser=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert workspace.bundle.path == path.resolve() and workspace.trusted is False
        request = urllib.request.Request(
            f"{url}/api/session", headers={"X-Studio-Token": workspace.token}
        )
        with OPENER.open(request) as response:
            session = json.loads(response.read())
        assert session["bundle"]["name"] == "Shared Figure.flexo"
        assert session["bundle"]["document"] == "figure.yaml" and session["trusted"] is False
        # Save as Bundle: the document as the page has it, every file it names, as one file.
        doc = workspace.open("figure.yaml")
        text = doc.document["text"].replace("First", "Unsaved yet")
        body = json.dumps(
            {
                "file": "figure.yaml",
                "formats": ["flexo"],
                "deliver": "download",
                "document": {"text": text},
            }
        ).encode()
        request = urllib.request.Request(
            f"{url}/api/export",
            data=body,
            headers={"Content-Type": "application/json", "X-Studio-Token": workspace.token},
        )
        with OPENER.open(request) as response:
            assert "Shared%20Figure.flexo" in response.headers["Content-Disposition"]
            made = zipfile.ZipFile(io.BytesIO(response.read()))
        assert sorted(made.namelist()) == ["art/photo.png", "figure.yaml", "manifest.json"]
        assert b"Unsaved yet" in made.read("figure.yaml")
        # An edit, saved: written back into the bundle as the studio closes at the latest.
        doc.update({"text": text}, doc.version, {"id": "test", "name": "Test"})
        workspace.trust()
        assert json.loads((workspace.bundle.home / "bundle.json").read_text())["trusted"] is True
    finally:
        workspace.close()
        server.shutdown()
        server.server_close()
    assert b"Unsaved yet" in zipfile.ZipFile(path).read("figure.yaml")
    # Opened again, it is trusted: its person said so.
    server, workspace = start(path, browser=False)
    try:
        assert workspace.trusted is True
    finally:
        workspace.close()
        server.server_close()


def test_a_bundle_that_will_not_open_is_said_and_nothing_served(tmp_path: Path) -> None:
    from flexo.studio.server import start

    bad = _zip(tmp_path / "bad.flexo", [(zipfile.ZipInfo("../../evil.py"), b"import os")])
    with pytest.raises(BundleError):
        start(bad, browser=False)
    assert not list(studio_bundles.support().glob("*/*/evil.py"))


def test_crc_of_a_file_is_the_zips(tmp_path: Path) -> None:
    file = _write(tmp_path / "a.bin", bytes(range(256)) * 5000)
    assert B._crc(file) == zlib.crc32(file.read_bytes())


def test_another_bundle_put_in_a_trusted_ones_place_is_asked_about_again(tmp_path: Path) -> None:
    path = _deck_free_bundle(tmp_path)
    keeper = studio_bundles.opened(path)
    keeper.remember_trust()
    assert studio_bundles.opened(path).trusted
    # Saved again (here or on another Mac), it is the same bundle: still trusted.
    keeper.save(force=True)
    assert studio_bundles.opened(path).trusted
    # Another bundle of the same name, sent and saved over it: not.
    aside = tmp_path / "other"
    _write(aside / "figure.yaml", "figure: {id: other}\nnodes: []\n")
    B.write(
        path,
        {"figure.yaml": aside / "figure.yaml"},
        B.manifest("figure.yaml", "figure", created="2020-01-01T00:00:00Z"),
    )
    again = studio_bundles.opened(path)
    assert again.replaced and not again.trusted
