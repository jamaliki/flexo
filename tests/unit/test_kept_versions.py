"""What is kept between sessions says which version of the code made it: found by what it is
made from, a version's own is read back; another's stands in only where the studio's page may
be shown it while it is made again (``flexo.kept_versions.earlier``)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from flexo import kept_versions


def _version(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """The code as if it were the version ``name``: an update simulated."""

    monkeypatch.setattr(kept_versions, "_CODE", [name])


def test_what_is_kept_says_which_version_made_it(monkeypatch) -> None:
    _version(monkeypatch, "0123456789abcdef")
    kept = kept_versions.stamped(b"<svg/>")
    assert kept == b"flexo-kept 0123456789abcdef\n<svg/>"
    assert kept_versions.unstamped(kept) == ("0123456789abcdef", b"<svg/>")
    # (Kept before versions were said: no version's.)
    assert kept_versions.unstamped(b"<svg/>") == (None, b"<svg/>")


def test_an_earlier_version_stands_in_only_within_earlier() -> None:
    assert not kept_versions.allowed()
    kept_versions.took("nothing")  # (outside: told to no one)
    with kept_versions.earlier() as taken:
        assert kept_versions.allowed()
        kept_versions.took("a figure")
        seen = []
        # (Another thread drawing meanwhile -- an export -- is not within it.)
        thread = threading.Thread(target=lambda: seen.append(kept_versions.allowed()))
        thread.start()
        thread.join()
        assert seen == [False]
    assert taken == ["a figure"]
    assert not kept_versions.allowed()


def test_a_structure_drawn_by_another_version_is_drawn_again_in_its_place(
    tmp_path: Path, monkeypatch
) -> None:
    """After an update a molecule drawn before is not read back -- the code that draws it has
    changed -- and drawn again it replaces what was kept, in the same file: the version before's
    drawings do not take places among those kept."""

    from flexo import structure_kept
    from flexo.structures import _Ask

    kept = tmp_path / "kept"
    monkeypatch.setenv("FLEXO_STRUCTURE_CACHE", str(kept))
    source = tmp_path / "model.pdb"
    source.write_text("ATOM\n")
    ask = _Ask(str(source), 0.0, "flat", "#ffffff", (), (), (), None, ())
    _version(monkeypatch, "aaaaaaaaaaaaaaaa")
    structure_kept.keep_drawing(ask, 1.0, "<svg>old</svg>")
    structure_kept.keep_extent(ask, 1.0, "shapes", ((0, 0, 1, 1), (2, 2)))
    assert structure_kept.drawing(ask, 1.0) == "<svg>old</svg>"
    names = sorted(item.name for item in kept.iterdir())

    _version(monkeypatch, "bbbbbbbbbbbbbbbb")
    assert structure_kept.drawing(ask, 1.0) is None
    assert structure_kept.extent(ask, 1.0, "shapes") == (False, None)
    with kept_versions.earlier():
        # (Not even for the page: a molecule's drawing goes into a figure's layout, which
        # this version lays out with this version's molecules.)
        assert structure_kept.drawing(ask, 1.0) is None
    structure_kept.keep_drawing(ask, 1.0, "<svg>new</svg>")
    assert structure_kept.drawing(ask, 1.0) == "<svg>new</svg>"
    assert sorted(item.name for item in kept.iterdir()) == names
    svg = next(item for item in kept.iterdir() if item.suffix == ".svg")
    assert svg.read_bytes().startswith(b"flexo-kept bbbbbbbbbbbbbbbb\n")
