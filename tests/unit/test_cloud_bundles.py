"""A bundle in a folder a cloud service keeps, open on two computers at once
(``flexo.studio.cloud_bundles``): each computer's saving names itself and those it was made
from; the copy the service keeps when both save at once is merged into the bundle from the
version both had and put away, so the folder holds one bundle with both computers' edits."""

from __future__ import annotations

import json
import os
import shutil
import time
import zipfile
from pathlib import Path

import pytest
import yaml

from flexo import bundle as B
from flexo.bundle import Bundle
from flexo.studio import bundles as studio_bundles
from flexo.studio import cloud_bundles as cloud

FIGURE = "figure: {id: talk}\nnodes:\n" + "".join(
    f"- {{id: n{index}, label: Node {index}}}\n" for index in range(1, 13)
)


@pytest.fixture(autouse=True)
def _apart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # A home of the test's own (where the cloud services' folders are), and working folders,
    # studios' session files and copies put away of its own too.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FLEXO_BUNDLES", str(tmp_path / "support" / "bundles"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    return home


def _mirror(service: str, computer: str) -> Path:
    """The folder a service keeps on one computer (each computer has its own, kept alike)."""

    home = Path.home()
    storage = home / "Library" / "CloudStorage"
    folder = {
        "Google Drive": storage / f"GoogleDrive-{computer}@lab.org" / "My Drive" / "GBI 2026",
        "iCloud Drive": home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / computer,
        "Dropbox": storage / f"Dropbox-{computer}" / "talks",
        "OneDrive": storage / f"OneDrive-{computer}" / "talks",
    }[service]
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "talk.flexo"


def _carried(source: Path, target: Path) -> None:
    """A file carried to another computer by the service: put in place whole."""

    partial = target.with_name(f".{target.name}.carrying")
    shutil.copy2(source, partial)
    os.replace(partial, target)


def _two_computers(service: str = "Google Drive") -> tuple[Path, Path]:
    made = Path(os.environ["FLEXO_BUNDLES"]).parent / "made"
    made.mkdir(parents=True, exist_ok=True)
    (made / "talk.yaml").write_text(FIGURE, encoding="utf-8")
    ours, theirs = _mirror(service, "ada"), _mirror(service, "ben")
    B.pack(made / "talk.yaml", ours)
    _carried(ours, theirs)
    return ours, theirs


def _edit(keeper: studio_bundles.Keeper, old: str, new: str) -> None:
    document = keeper.root / "talk.yaml"
    text = document.read_text(encoding="utf-8")
    assert old in text, old
    document.write_text(text.replace(old, new, 1), encoding="utf-8")


def _labels(source: Path | studio_bundles.Keeper) -> list[str]:
    if isinstance(source, studio_bundles.Keeper):
        words = (source.root / "talk.yaml").read_bytes()
    else:
        with zipfile.ZipFile(source) as archive:
            words = archive.read("talk.yaml")
    return [node.get("label") for node in yaml.safe_load(words)["nodes"]]


def _revisions(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read("manifest.json")).get("revisions", [])


def _settled(ours: Path, theirs: Path, copy_name: str) -> None:
    """Two savings at once, settled as the service settles them: ``ours`` stays the bundle,
    ``theirs`` is kept beside it as ``copy_name`` -- on both computers."""

    _carried(theirs, ours.with_name(copy_name))
    os.rename(theirs, theirs.with_name(copy_name))  # (the other's own saving, renamed)
    _carried(ours, theirs)


def _put_away() -> Path:
    return Path(os.environ["FLEXO_BUNDLES"]).parent / "merged" / time.strftime("%Y-%m-%d")


EDITED_HERE = ("Node 5}", "Node 5 sharpened}")
EDITED_THERE = ("Node 9}", "Node 9 in two columns}")
MERGED = [
    *(f"Node {index}" for index in range(1, 5)),
    "Node 5 sharpened",
    *(f"Node {index}" for index in range(6, 9)),
    "Node 9 in two columns",
    *(f"Node {index}" for index in range(10, 13)),
]


# -- names ---------------------------------------------------------------------------------


def test_the_copies_cloud_services_keep_of_a_bundle_are_known_by_name(tmp_path: Path) -> None:
    talk = tmp_path / "talk.flexo"
    # Named with "conflict", wherever it is (Dropbox's, Syncthing's...); numbered, or with a
    # computer's name, only where the service names its copies so.
    named = {
        None: [
            "talk (Ben's conflicted copy 2026-10-19).flexo",
            "talk [Conflict].flexo",
            "talk.sync-conflict-20261019-101500-ABCDEFG.flexo",
        ],
        "Google Drive": ["talk (1).flexo", "talk (2).flexo"],
        "iCloud Drive": ["talk 2.flexo", "talk 3.flexo"],
        "OneDrive": ["talk-Bens-MacBook-Pro.flexo", "talk-DESKTOP-4F3K2L.flexo"],
    }
    for service, names in named.items():
        for name in names:
            assert cloud.is_copy_of(talk, tmp_path / name, service), (service, name)
            assert (service is None) == cloud.is_copy_of(talk, tmp_path / name, "Dropbox"), name
    for name in (
        "talk.flexo",
        "talks.flexo",
        "talk copy.flexo",
        "talk.yaml",
        "talk (edits not saved).flexo",
        "talk (1) notes.flexo",
        "other (1).flexo",
    ):
        for service in named:
            assert not cloud.is_copy_of(talk, tmp_path / name, service), (service, name)
    assert not cloud.is_copy_of(talk, tmp_path / "in" / "talk (1).flexo", "Google Drive")


# -- two computers -----------------------------------------------------------------------


def test_two_computers_saving_at_once_end_with_one_bundle_holding_both_edits() -> None:
    ours, theirs = _two_computers("Google Drive")
    here, there = studio_bundles.opened(ours), studio_bundles.opened(theirs)
    _edit(here, *EDITED_HERE)
    _edit(there, *EDITED_THERE)
    assert here.save() and there.save()
    mine, other = _revisions(ours)[0], _revisions(theirs)[0]
    assert mine != other
    # Both saved within moments: Google Drive keeps one as the bundle, one as a copy beside it.
    _settled(ours, theirs, "talk (1).flexo")

    # The other computer, its saving now the copy: the bundle taken in -- its own edits
    # kept, merged with it from the version both had -- and the copy left for this one.
    there.step(now=100.0)
    assert _labels(there) == MERGED
    assert theirs.with_name("talk (1).flexo").exists()
    there.step(now=110.0)
    assert _labels(theirs) != MERGED  # (waiting for this computer's merge: one saving, not two)

    # This computer: the copy merged into the bundle, which is written at once, and the
    # copy put away (here, a studio run apart, beside the working folders; else the Trash).
    here.step(now=100.0)
    assert _labels(here) == MERGED and _labels(ours) == MERGED
    assert not ours.with_name("talk (1).flexo").exists()
    assert (_put_away() / "talk (1).flexo").is_file()
    assert {mine, other} <= set(_revisions(ours))
    assert here.notices == [
        f"Merged edits from another computer (talk (1).flexo, now in {_put_away()})."
    ]

    # Carried back: the other computer takes the merge in, and has nothing more to write.
    _carried(ours, theirs)
    theirs.with_name("talk (1).flexo").unlink()
    there.step(now=120.0)
    assert _labels(there) == MERGED
    assert not there.save()
    assert sorted(path.name for path in ours.parent.glob("*.flexo")) == ["talk.flexo"]
    assert sorted(path.name for path in theirs.parent.glob("*.flexo")) == ["talk.flexo"]


def test_two_merges_of_one_conflict_saved_at_once_come_to_one_without_doubling() -> None:
    # Both computers merge the same two savings and save before either sees the other's
    # merge: a conflict again, of two merges -- merged from the merge each made, not from
    # before it, so nothing either added is added twice.
    ours, theirs = _two_computers("Dropbox")
    here, there = studio_bundles.opened(ours), studio_bundles.opened(theirs)
    _edit(
        here, "- {id: n12, label: Node 12}\n", "- {id: n12, label: Node 12}\n- {id: a, label: A}\n"
    )
    _edit(there, "- {id: n3, label: Node 3}\n", "- {id: n3, label: Node 3}\n- {id: b, label: B}\n")
    assert here.save() and there.save()
    copy = "talk (Ben's conflicted copy 2026-10-19).flexo"
    _settled(ours, theirs, copy)
    there.step(now=100.0)
    here.step(now=100.0)
    there.step(now=100.0 + studio_bundles.HOLD + 1)  # (the other merge never came: saved)
    both = _labels(here)
    assert both.count("A") == 1 and both.count("B") == 1 and _labels(there) == both
    # Saved at once again: the service keeps one merge as the bundle, one as a copy.
    second = "talk (Ada's conflicted copy 2026-10-19).flexo"
    _settled(theirs, ours, second)
    here.step(now=200.0)
    there.step(now=200.0)
    for keeper, path in ((here, ours), (there, theirs)):
        assert _labels(keeper) == both and _labels(path) == both
    assert not ours.with_name(second).exists()


@pytest.mark.parametrize(
    ("service", "copy"),
    [
        ("Google Drive", "talk (1).flexo"),
        ("iCloud Drive", "talk 2.flexo"),
        ("Dropbox", "talk (Ben's conflicted copy 2026-10-19).flexo"),
        ("OneDrive", "talk-Bens-MacBook-Pro.flexo"),
    ],
)
def test_each_services_copy_of_a_bundle_is_merged_into_it(service: str, copy: str) -> None:
    ours, theirs = _two_computers(service)
    here, there = studio_bundles.opened(ours), studio_bundles.opened(theirs)
    _edit(here, *EDITED_HERE)
    _edit(there, *EDITED_THERE)
    assert here.save() and there.save()
    _carried(theirs, ours.with_name(copy))
    here.step(now=50.0)
    assert _labels(ours) == MERGED and not ours.with_name(copy).exists()
    assert here.notices == [f"Merged edits from another computer ({copy}, now in {_put_away()})."]


def test_a_bundle_named_as_a_copy_but_another_is_left_alone() -> None:
    ours, theirs = _two_computers("Google Drive")
    here = studio_bundles.opened(ours)
    # Another deck, named as the service would name a copy: made at another moment.
    elsewhere = theirs.parent / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "talk.yaml").write_text(FIGURE.replace("Node 9", "Other"), encoding="utf-8")
    B.write(
        ours.with_name("talk (1).flexo"),
        {"talk.yaml": elsewhere / "talk.yaml"},
        B.manifest("talk.yaml", "figure", created="2020-01-01T00:00:00Z"),
    )
    # This deck, opened on this computer as itself (to compare it, say): someone's own.
    _carried(ours, ours.with_name("talk (2).flexo"))
    studio_bundles.opened(ours.with_name("talk (2).flexo"))
    _edit(here, *EDITED_HERE)
    here.step(now=10.0)
    assert here.save()
    assert ours.with_name("talk (1).flexo").exists() and ours.with_name("talk (2).flexo").exists()
    assert "Other" not in _labels(ours) and here.notices == []


def test_a_copy_changing_what_was_changed_here_is_kept_and_said_once() -> None:
    ours, theirs = _two_computers("Google Drive")
    here, there = studio_bundles.opened(ours), studio_bundles.opened(theirs)
    _edit(here, "Node 5}", "Knot 5}")
    _edit(there, "Node 5}", "Point 5}")
    assert here.save() and there.save()
    _carried(theirs, ours.with_name("talk (1).flexo"))
    before = ours.read_bytes()
    here.step(now=10.0)
    here.step(now=30.0)
    _edit(here, "Node 7}", "Node 7 edited}")
    assert here.save()
    here.step(now=50.0)
    assert ours.with_name("talk (1).flexo").is_file() and before != ours.read_bytes()
    assert "Knot 5" in _labels(ours)
    assert here.notices == [
        "\u201ctalk (1).flexo\u201d holds edits from another computer that change the same "
        "things as edits here, so it isn\u2019t merged: it is kept beside talk.flexo."
    ]


def test_a_copy_beside_a_bundle_as_it_opens_is_merged_before_it_is_shown() -> None:
    ours, theirs = _two_computers("Google Drive")
    here, there = studio_bundles.opened(ours), studio_bundles.opened(theirs)
    _edit(here, *EDITED_HERE)
    _edit(there, *EDITED_THERE)
    assert here.save() and there.save()
    here.close()
    # (Meanwhile, the app quit here, the two savings met in the cloud.)
    _carried(theirs, ours.with_name("talk (1).flexo"))
    again = studio_bundles.opened(ours)
    assert _labels(again) == MERGED and _labels(ours) == MERGED
    assert not ours.with_name("talk (1).flexo").exists()
    assert again.info()["notices"] == [
        f"Merged edits from another computer (talk (1).flexo, now in {_put_away()})."
    ]


def test_a_copy_of_a_saving_this_computer_has_is_put_away_once_the_bundle_has_it() -> None:
    ours, _ = _two_computers("iCloud Drive")
    here = studio_bundles.opened(ours)
    # Someone's own copy of the bundle from before it opened here: theirs to keep.
    _carried(ours, ours.with_name("talk 3.flexo"))
    os.utime(ours.with_name("talk 3.flexo"), (time.time() - 86400,) * 2)
    _edit(here, *EDITED_HERE)
    assert here.save()
    # A saving here the service kept as a copy too, the bundle being this same saving.
    _carried(ours, ours.with_name("talk 2.flexo"))
    here.step(now=10.0)
    assert not ours.with_name("talk 2.flexo").exists()
    assert ours.with_name("talk 3.flexo").exists()
    assert here.notices == [
        "\u201ctalk 2.flexo\u201d held nothing that isn\u2019t in talk.flexo: it is now in "
        f"{_put_away()}."
    ]


def test_a_bundle_saved_elsewhere_from_an_older_version_keeps_the_edits_made_here() -> None:
    # The service kept this computer's saving as a copy beside the bundle, and put the other
    # computer's -- made without it -- in its place: taken in, the edits here stay.
    ours, theirs = _two_computers("Google Drive")
    here, there = studio_bundles.opened(ours), studio_bundles.opened(theirs)
    _edit(here, *EDITED_HERE)
    _edit(there, *EDITED_THERE)
    assert here.save() and there.save()
    _carried(theirs, ours)
    here.step(now=10.0)
    assert _labels(here) == MERGED
    here.step(now=10.0 + studio_bundles.HOLD + here.quiet + 1)
    assert _labels(ours) == MERGED


def test_a_change_on_both_from_an_older_version_keeps_this_computers_beside_it() -> None:
    ours, theirs = _two_computers("Google Drive")
    here, there = studio_bundles.opened(ours), studio_bundles.opened(theirs)
    _edit(here, "Node 5}", "Knot 5}")
    _edit(there, "Node 5}", "Point 5}")
    assert here.save() and there.save()
    _carried(theirs, ours)
    here.step(now=10.0)
    assert "Point 5" in _labels(here)
    aside = ours.with_name("talk (edits not saved).flexo")
    assert "Knot 5" in _labels(aside)
    assert here.conflict == aside.name and len(here.notices) == 1


def test_a_bundle_renamed_as_a_copy_by_the_service_is_not_followed() -> None:
    ours, theirs = _two_computers("Google Drive")
    here, there = studio_bundles.opened(ours), studio_bundles.opened(theirs)
    _edit(here, *EDITED_HERE)
    _edit(there, *EDITED_THERE)
    assert here.save() and there.save()
    # Its own saving renamed as the service names a copy, the other's not yet in its place.
    os.rename(ours, ours.with_name("talk (1).flexo"))
    here.step(now=10.0)
    assert here.path == ours and here.problem is None
    _carried(theirs, ours)
    here.step(now=11.0)
    assert _labels(here) == MERGED
    assert here.path == ours


def test_a_copy_from_an_older_studio_is_merged_from_the_version_most_like_it() -> None:
    # Saved by a studio that names no savings: merged from the version here most like it.
    ours, theirs = _two_computers("Google Drive")
    here = studio_bundles.opened(ours)
    _edit(here, *EDITED_HERE)
    assert here.save()
    aside = theirs.parent / "older"
    with Bundle(theirs) as opened:
        opened.extract(aside)
        about = dict(opened.manifest)
    text = (aside / "talk.yaml").read_text(encoding="utf-8")
    (aside / "talk.yaml").write_text(text.replace(*EDITED_THERE), encoding="utf-8")
    about.pop("revisions", None)
    B.write(ours.with_name("talk (1).flexo"), {"talk.yaml": aside / "talk.yaml"}, about)
    here.step(now=10.0)
    assert _labels(ours) == MERGED and not ours.with_name("talk (1).flexo").exists()


def test_a_save_takes_in_a_bundle_saved_elsewhere_first(tmp_path: Path) -> None:
    ours, theirs = _two_computers("Google Drive")
    here, there = studio_bundles.opened(ours), studio_bundles.opened(theirs)
    _edit(there, *EDITED_THERE)
    assert there.save()
    _carried(theirs, ours)
    # (Saved at once -- a Save, the window closing -- before the next look.)
    _edit(here, *EDITED_HERE)
    assert here.save()
    assert _labels(ours) == MERGED


def test_a_bundle_changed_as_it_is_written_is_left_as_it_is(tmp_path: Path) -> None:
    (tmp_path / "talk.yaml").write_text(FIGURE, encoding="utf-8")
    made = B.pack(tmp_path / "talk.yaml", tmp_path / "talk.flexo")
    before = made.path.read_bytes()

    def changed() -> None:
        raise RuntimeError("changed meanwhile")

    with pytest.raises(RuntimeError):
        B.write(
            made.path, {"talk.yaml": tmp_path / "talk.yaml"}, B.manifest("talk.yaml"), check=changed
        )
    assert made.path.read_bytes() == before
    assert [path.name for path in tmp_path.iterdir() if path.name.startswith(".")] == []


# -- written from an older version --------------------------------------------------------


def _from_an_older_studio(source: Path, target: Path, *edits: tuple[str, str]) -> None:
    """The bundle at ``source`` (as it was), edited and saved by a studio that names no
    savings, carried to ``target``."""

    aside = Path(os.environ["FLEXO_BUNDLES"]).parent / "older"
    with Bundle(source) as opened:
        opened.extract(aside)
        about = dict(opened.manifest)
    text = (aside / "talk.yaml").read_text(encoding="utf-8")
    for edit in edits:
        text = text.replace(*edit)
    (aside / "talk.yaml").write_text(text, encoding="utf-8")
    about.pop("revisions", None)
    B.write(aside.parent / "older.flexo", {"talk.yaml": aside / "talk.yaml"}, about)
    _carried(aside.parent / "older.flexo", target)


def test_a_bundle_from_an_older_studio_in_its_place_keeps_the_edits_saved_here() -> None:
    # Saved by a studio that names no savings, from the bundle as it was before the edit saved
    # here: taken in from the version it is most like, the edit here kept.
    ours, theirs = _two_computers("Google Drive")
    here = studio_bundles.opened(ours)
    _edit(here, *EDITED_HERE)
    assert here.save()
    _from_an_older_studio(theirs, ours, EDITED_THERE)
    here.step(now=10.0)
    assert _labels(here) == MERGED
    here.step(now=10.0 + here.quiet + 1)
    assert _labels(ours) == MERGED


def test_a_bundle_from_an_older_studio_word_for_word_a_version_had_here_puts_it_back() -> None:
    ours, theirs = _two_computers("Google Drive")
    here = studio_bundles.opened(ours)
    _edit(here, *EDITED_HERE)
    assert here.save()
    _from_an_older_studio(theirs, ours)  # (the bundle as it first was)
    here.step(now=10.0)
    assert _labels(here) == [f"Node {index}" for index in range(1, 13)]


def test_another_computers_taking_back_an_edit_made_here_reaches_the_open_document() -> None:
    # The other computer, having this one's edit, takes it back and edits something else. Its
    # saving, merged into the folder from the one both had, is taken into the open document as
    # it is -- not as a change made from before the edit it takes back, which it is nearest.
    from flexo.studio.workspace import Workspace

    ours, theirs = _two_computers("Google Drive")
    here = studio_bundles.opened(ours)
    workspace = Workspace(here.root)
    workspace._stop.set()  # (no clock: the document takes the file in when asked)
    here.workspace, workspace.bundle = workspace, here
    try:
        doc = workspace.open("talk.yaml")
        person = {"id": "page-a", "name": "Ada", "kind": "person"}
        doc.update({"text": doc.document["text"].replace(*EDITED_HERE)}, doc.version, person)
        assert doc.write() and here.save()
        _carried(ours, theirs)
        there = studio_bundles.opened(theirs)
        _edit(there, "Node 5 sharpened}", "Node 5}")
        _edit(there, *EDITED_THERE)
        assert there.save()
        _carried(theirs, ours)
        here.step(now=10.0)
        workspace.reread(doc)
        labels = [node["label"] for node in yaml.safe_load(doc.document["text"])["nodes"]]
        assert labels[4] == "Node 5" and labels[8] == "Node 9 in two columns"
        assert doc.saved == doc.version
    finally:
        workspace.close()
