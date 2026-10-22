"""What a document drawn in the studio may read: the folder served, however a file is reached
(flexo.confine) -- each file looked at once, without letting one outside in."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from flexo import confine
from flexo.confine import folder_root, found, once, outside


@pytest.fixture
def served(tmp_path: Path):
    """A folder served, with a file in it, and a folder beside it holding a file of yours."""

    root = tmp_path / "folder"
    (root / "models").mkdir(parents=True)
    (root / "models" / "model.pdb").write_text("ATOM\n")
    away = tmp_path / "away"
    away.mkdir()
    (away / "secret.pdb").write_text("SECRET\n")
    (away / "model.pdb").write_text("ELSEWHERE\n")
    confine._SEEN.clear()
    token = folder_root.set(root.resolve())
    try:
        yield root.resolve(), away.resolve()
    finally:
        folder_root.reset(token)


def test_a_file_outside_the_folder_is_refused_however_it_is_reached(served) -> None:
    root, away = served
    (root / "link.pdb").symlink_to(away / "secret.pdb")
    (root / "linked").symlink_to(away)
    assert not outside(root / "models" / "model.pdb")
    assert not outside(root)
    assert outside(away / "secret.pdb")
    assert outside(root / "link.pdb")  # a link to a file outside
    assert outside(root / "linked" / "secret.pdb")  # through a folder linked outside
    assert outside(root / ".." / "away" / "secret.pdb")
    assert outside(Path(f"{root}-beside") / "model.pdb")  # a folder named as it begins
    for name in ("link.pdb", "linked/secret.pdb"):
        stat, away_from_it = found(root / name)
        assert stat is not None and away_from_it
    token = folder_root.set(None)
    try:
        assert not outside(away / "secret.pdb")  # (outside the studio, anything may be read)
    finally:
        folder_root.reset(token)


def test_a_file_found_inside_is_looked_at_once_until_it_is_another(served, monkeypatch) -> None:
    """Found inside the folder, the same file is not followed to where it lies again -- but
    one put in its place, a link to a file outside the folder or the folder on the way
    linked outside, is looked at afresh and refused."""

    root, away = served
    model = root / "models" / "model.pdb"
    followed: list[str] = []
    real = os.path.realpath

    def realpath(name, *args, **kwargs):
        followed.append(os.fspath(name))
        return real(name, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", realpath)
    stat, away_from_it = found(model)
    assert stat is not None and not away_from_it and len(followed) == 1
    assert found(model)[1] is False and len(followed) == 1  # (the same file: not followed)

    model.unlink()
    model.symlink_to(away / "secret.pdb")
    assert found(model)[1] is True

    model.unlink()
    model.write_text("ATOM\n")
    assert found(model)[1] is False
    shutil.rmtree(root / "models")
    (root / "models").symlink_to(away)  # the folder on the way, now a link outside
    assert found(model)[1] is True

    assert found(root / "missing.pdb") == (None, False)


def test_while_a_figure_is_laid_out_each_file_is_looked_at_once(served, monkeypatch) -> None:
    root, _ = served
    model = root / "models" / "model.pdb"
    looked: list[object] = []
    real = os.stat

    def stat(name, *args, **kwargs):
        looked.append(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)
    with once():
        for _ in range(5):
            assert found(model)[1] is False
        with once():  # (nested: the outermost holds)
            assert found(model)[1] is False
    assert len(looked) == 1
    found(model)
    assert len(looked) == 2  # (laid out, a file is looked at each time it is asked about)


def test_a_structure_whose_file_becomes_a_link_outside_the_folder_is_refused(served) -> None:
    """Drawn once from a file in the folder, a structure whose file is then made a link to
    one outside the folder is refused: it is not drawn from what it was found to be."""

    import flexo
    from flexo.structures import structure_problem
    from flexo.themes import figure_style

    root, away = served
    model = root / "models" / "model.pdb"

    def problem():
        with flexo.Figure("confined") as figure:
            figure.root.row("row").structure("model", model, look="flat")
        node = next(node for node in figure.spec.nodes if node.id == "row.model")
        return structure_problem(node, figure_style(figure.spec))

    first = problem()
    assert first is None or "outside the folder" not in first.message
    model.unlink()
    model.symlink_to(away / "secret.pdb")
    said = problem()
    assert said is not None and "outside the folder" in said.message
