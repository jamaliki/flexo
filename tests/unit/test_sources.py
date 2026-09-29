"""A protein's map from a structure file and from a UniProt entry."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import flexo
from flexo.compiler import compile_figure
from flexo.lint import lint_compilation

DATA = Path(__file__).parent / "data"


def test_a_structure_gives_its_sequence_and_recorded_secondary_structure() -> None:
    pytest.importorskip("gemmi")
    read = flexo.from_structure(DATA / "1a7g.cif")
    assert read["length"] == len(read["sequence"]) == len(read["secondary"]) == 82
    assert read["label"] == "1A7G"  # its title is too long to name a map
    # The deposited records: a strand first, then a helix.
    assert read["secondary"].startswith("CEEEEEEEEECHHHH")
    with flexo.Figure("e2") as figure:
        figure.root.protein("e2", **read)
    assert not lint_compilation(compile_figure(figure.spec)).diagnostics


def test_assigned_secondary_structure_agrees_with_the_records() -> None:
    pytest.importorskip("gemmi")
    recorded = flexo.from_structure(DATA / "1a7g.cif")["secondary"]
    assigned = flexo.from_structure(DATA / "1a7g.cif", assign=True)["secondary"]

    def kind(letter: str) -> str:
        return "H" if letter in "HG" else "E" if letter == "E" else "-"

    agreement = sum(kind(a) == kind(b) for a, b in zip(recorded, assigned, strict=True))
    assert agreement / len(recorded) > 0.9


def test_a_missing_chain_says_so() -> None:
    pytest.importorskip("gemmi")
    with pytest.raises(ValueError, match="found no chain Z"):
        flexo.from_structure(DATA / "1a7g.cif", chain="Z")


def test_a_uniprot_entry_gives_domains_and_on_request_sites_and_structure() -> None:
    entry = DATA / "uniprot-abl1-excerpt.json"
    plain = flexo.from_uniprot(entry)
    assert plain["label"] == "ABL1" and plain["length"] == 60
    kinds = [(feature["type"], feature.get("label")) for feature in plain["features"]]
    assert ("domain", "SH3") in kinds and ("motif", "Nuclear localization signal") in kinds
    assert ("disulfide", None) in kinds
    assert not any(kind in {"phosphorylation", "helix", "mutation"} for kind, _ in kinds)
    full = flexo.from_uniprot(entry, sites=True, variants=True, structure=True)
    labelled = {(f["type"], f.get("label")) for f in full["features"]}
    assert ("phosphorylation", "Y24") in labelled and ("glycosylation", "N49") in labelled
    assert ("mutation", "I6T") in labelled and ("helix", None) in labelled
    assert "disordered" not in str(flexo.from_uniprot(entry, disordered=False)).lower()
    with flexo.Figure("abl") as figure:
        figure.root.protein("abl", **full)
    assert not lint_compilation(compile_figure(figure.spec)).diagnostics


def test_an_accession_that_cannot_be_fetched_says_how_to_work_offline(monkeypatch) -> None:
    import urllib.error
    import urllib.request

    def refuse(*args: object, **kwargs: object) -> None:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    with pytest.raises(
        ValueError, match=re.escape("Save https://rest.uniprot.org/uniprotkb/P00519.json")
    ):
        flexo.from_uniprot("P00519")
