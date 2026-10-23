"""A figure's ink is found without reading the shapes of the molecules it stands boxes in for
(flexo.drawn_spans): read as it would be read whole, those shapes taken out."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import flexo
from flexo.compiler import compile_figure
from flexo.drawn_spans import spans, without

DATA = Path(__file__).parent / "data"


def _structure_figure(words: str) -> flexo.Figure:
    with flexo.Figure("measured") as figure:
        row = figure.root.row("row", gap=24)
        before = row.block("before", label=words)
        model = row.structure(
            "model", DATA / "1a7g.cif", look="flat", width=200, height=120, frame="f"
        )
        row.structure(
            "part",
            DATA / "1a7g.cif",
            look="flat",
            width=200,
            height=120,
            frame="f",
            cartoon="resi 300-320",
            sticks="none",
        )
        figure.connect(before, model)
    return figure


def _read_whole(text: str, molecules: dict) -> str:
    """The figure read whole, each molecule's shapes taken out as ``figure_ink`` takes them."""

    import re

    from flexo.structure_fit import _AS_DRAWN
    from flexo.svg import local_name

    root = ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", text, count=1))
    for holder in root.iter():
        if holder.get("data-flexo-drawn") != "mol-sketch" or holder.get("id") not in molecules:
            continue
        nested = [child for child in holder if local_name(child.tag) == "svg"]
        if molecules[holder.get("id")] is _AS_DRAWN or len(nested) != 1:
            continue
        for child in list(nested[0]):
            nested[0].remove(child)
    return ET.tostring(root, encoding="unicode")


def test_a_figure_s_ink_is_found_without_reading_its_molecules_shapes() -> None:
    """``figure_ink`` reads a figure without the shapes of the molecules it stands boxes in
    for -- most of its words -- and reads it as it did when it read them and took them out."""

    pytest.importorskip("molsketch")
    from flexo.structure_fit import _AS_DRAWN, _without_molecules, figure_ink, noting

    with noting() as molecules:
        text = compile_figure(_structure_figure("A substrate").spec).document.text
    assert set(molecules) == {"row.model.molecule", "row.part.molecule"}
    found = spans(text)
    assert [span.holder for span in found] == ["row.model.molecule", "row.part.molecule"]
    smaller = _without_molecules(text, molecules)
    assert len(smaller) < len(text) / 3
    assert ET.tostring(ET.fromstring(smaller), encoding="unicode") == _read_whole(text, molecules)
    # One measured as drawn keeps its shapes, as ever.
    some = {**molecules, "row.part.molecule": _AS_DRAWN}
    assert ET.tostring(
        ET.fromstring(_without_molecules(text, some)), encoding="unicode"
    ) == _read_whole(text, some)
    assert figure_ink(text, molecules) == figure_ink(text, dict(molecules))


def test_words_not_plainly_as_elementtree_writes_them_are_read_whole() -> None:
    held = (
        '<svg xmlns="http://www.w3.org/2000/svg"><g id="m" data-flexo-drawn="mol-sketch">'
        '<rect/><svg viewBox="0 0 1 1">\n  <path d="M0 0"/>\n</svg></g></svg>'
    )
    (span,) = spans(held)
    assert held[span.inside : span.end] == '<path d="M0 0"/>\n'
    assert without(held, [span]).count("<path") == 0
    for odd in (
        held.replace("<path", "<!-- </svg> --><path"),
        held.replace("<rect/>", "<![CDATA[<svg>]]><rect/>"),
        held.replace("<rect/>", '<g data-flexo-drawn="mol-sketch" id="n"><svg/></g>'),
        held.replace("<svg viewBox", "<ns0:svg viewBox").replace("</svg></g>", "</ns0:svg></g>"),
    ):
        assert spans(odd) is None
    assert spans('<svg xmlns="http://www.w3.org/2000/svg"><g/></svg>') == ()


def test_a_figure_read_whole_reads_its_molecules_shapes_once(monkeypatch) -> None:
    """Read whole (lint), a figure is the tree reading its words makes, its molecules' shapes
    read once and copied in -- and lints as it did."""

    pytest.importorskip("molsketch")
    from flexo import drawn_spans
    from flexo.lint import lint_compilation

    compiled = compile_figure(_structure_figure("Linted").spec)
    text = compiled.document.text
    whole = ET.tostring(ET.fromstring(text), encoding="unicode")
    assert ET.tostring(drawn_spans.read(text), encoding="unicode") == whole
    read: list[str] = []
    real = ET.fromstring
    monkeypatch.setattr(ET, "fromstring", lambda words: read.append(words) or real(words))
    assert ET.tostring(drawn_spans.read(text), encoding="unicode") == whole
    assert len(read) == 1 and len(read[0]) < len(text) / 2
    monkeypatch.undo()
    report = lint_compilation(compiled)
    monkeypatch.setattr(drawn_spans, "read", ET.fromstring)
    from flexo import lint

    lint._LINTED.clear()
    assert lint_compilation(compiled) == report
