"""Tests draw structures afresh: the molecules flexo keeps on disk go to a scratch folder, and
so do the pictures it keeps drawn and the noised structures' trajectories."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _fresh_structure_cache(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FLEXO_STRUCTURE_CACHE", str(tmp_path_factory.mktemp("structures")))
    monkeypatch.setenv("FLEXO_PICTURE_CACHE", str(tmp_path_factory.mktemp("pictures")))
    monkeypatch.setenv("FLEXO_NOISE_CACHE", str(tmp_path_factory.mktemp("noise")))
