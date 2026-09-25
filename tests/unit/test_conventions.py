"""Drawing conventions, math in labels, and the figure-level choices they ride on."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
import yaml

from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.conventions import Conventions
from flexo.ir.semantic import TextRun
from flexo.lint import lint_compilation
from flexo.markup import parse_label
from flexo.serialization import dump_figure, parse_figure
from flexo.svg import local_name

SVG_NS = "http://www.w3.org/2000/svg"


def _fork(**conventions: str) -> Figure:
    """One value read by three boxes below it, and two boxes merged into a third."""

    with Figure("fork", conventions=conventions or None) as figure:
        with figure.module("m", layout="column") as m:
            x = m.block("x", label="x")
            with m.row("branches", role="layout") as row:
                a = row.block("a", label="A")
                b = row.block("b", label="B")
                c = row.block("c", label="C")
            out = m.block("out", label="Out")
        figure.net(src=x, sinks=[a, b, c], id="fan")
        figure.merge(sinks=[a, c], dst=out, id="join")
    return figure


def _arrowheads(svg: str, net_id: str) -> int:
    root = ET.fromstring(svg)
    group = next(item for item in root.iter() if item.get("id") == net_id)
    return sum(1 for item in group.iter() if item.get("marker-end"))


def _circles(svg: str, prefix: str) -> list[ET.Element]:
    root = ET.fromstring(svg)
    return [
        item
        for item in root.iter(f"{{{SVG_NS}}}circle")
        if (item.get("id") or "").startswith(prefix)
    ]


def test_default_conventions_draw_plain_branches_and_an_arrowed_merge_of_two() -> None:
    compiled = compile_figure(_fork().spec)
    assert not _circles(compiled.document.text, "fan.junction")
    assert not _circles(compiled.document.text, "join.junction")
    assert _arrowheads(compiled.document.text, "join") > 1, "a merge of two arrows its join"


def test_branch_dots_mark_every_fork_and_nothing_else() -> None:
    compiled = compile_figure(_fork(branch="dot").spec)
    assert _circles(compiled.document.text, "fan.junction")
    assert not _circles(compiled.document.text, "join.junction")


def test_merge_conventions_choose_the_mark_at_a_join() -> None:
    plain = compile_figure(_fork(merge="plain").spec)
    assert _arrowheads(plain.document.text, "join") == 1
    assert not _circles(plain.document.text, "join.junction")
    dotted = compile_figure(_fork(merge="dot").spec)
    assert _circles(dotted.document.text, "join.junction")


def test_a_nets_joint_overrules_the_figure_conventions() -> None:
    with Figure("override", conventions={"branch": "dot"}) as figure:
        with figure.module("m", layout="column") as m:
            x = m.block("x", label="x")
            with m.row("r", role="layout") as row:
                a = row.block("a", label="A")
                b = row.block("b", label="B")
        figure.net(src=x, sinks=[a, b], id="fan", joint="auto")
    assert _circles(compile_figure(figure.spec).document.text, "fan.junction")


def test_values_arriving_at_one_port_get_one_arrow_each() -> None:
    def figure(**conventions: str) -> Figure:
        with Figure("arrivals", conventions=conventions or None) as built:  # noqa: SIM117
            with built.module("m") as m:
                with m.column("sources", role="layout") as column:
                    a = column.block("a", label="A")
                    b = column.block("b", label="B")
                m.block("sink", label="Sink", inputs=[a, b])
        return built

    separate = compile_figure(figure().spec)
    arrivals = {edge.centerline[-1] for edge in separate.routed.edges}
    assert len(arrivals) == 2
    assert not lint_compilation(separate).errors
    joined = compile_figure(figure(arrivals="joined").spec)
    assert len({edge.centerline[-1] for edge in joined.routed.edges}) == 1


def test_conventions_validate_and_round_trip() -> None:
    with pytest.raises(ValueError, match="branch convention"):
        Conventions(branch="circle")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown convention"):
        Conventions().with_updates({"branches": "dot"})
    spec = _fork(branch="dot", merge="plain").spec
    document = dump_figure(spec)
    assert "conventions" in document
    parsed = parse_figure(yaml.safe_load(document))
    assert parsed.conventions == Conventions(branch="dot", merge="plain")
    assert "conventions" not in dump_figure(_fork().spec)


def test_math_between_dollars_sets_scripts_italics_and_symbols() -> None:
    assert parse_label("c_{t-1}") == (TextRun("c_{t-1}"),)
    assert parse_label("$c_{t-1}$") == (
        TextRun("c", italic=True),
        TextRun("t", italic=True, baseline_shift="sub"),
        TextRun("\u22121", baseline_shift="sub"),
    )
    assert parse_label("softmax($QK^T$)") == (
        TextRun("softmax("),
        TextRun("QK", italic=True),
        TextRun("T", italic=True, baseline_shift="super"),
        TextRun(")"),
    )
    assert parse_label("$\\mu$, $\\Sigma$") == (
        TextRun("μ", italic=True),
        TextRun(", Σ"),
    )
    assert parse_label("$W_{\\text{out}}$")[1] == TextRun("out", baseline_shift="sub")
    assert parse_label("$\\hat{x}$") == (TextRun("x̂", italic=True),)
    assert parse_label("costs \\$5 or $6") == (TextRun("costs $5 or $6"),)


def test_a_math_label_survives_serialization() -> None:
    with Figure("math") as figure, figure.module("m") as m:
        m.block("h", label="$h_t$")
        m.block("plain", label="cost: \\$5")
    parsed = parse_figure(yaml.safe_load(dump_figure(figure.spec)))
    assert parsed.node("m.h").label == figure.spec.node("m.h").label
    assert parsed.node("m.plain").label == (TextRun("cost: $5"),)


def test_an_accent_the_primary_face_cannot_place_falls_back_with_its_letter() -> None:
    with Figure("accent") as figure, figure.module("m") as m:
        m.text("xhat", "$\\hat{x}$")
    root = ET.fromstring(compile_figure(figure.spec).document.text)
    label = next(item for item in root.iter() if item.get("id") == "m.xhat.label")
    spans = [item for item in label.iter() if local_name(item.tag) == "tspan" and item.text]
    assert ["".join(span.itertext()) for span in spans] == ["x̂"]
    assert spans[0].get("font-family") not in (None, "Figtree")


def test_text_objects_carry_no_indentation_between_runs() -> None:
    with Figure("runs") as figure, figure.module("m") as m:
        m.block("f", label="softmax($QK^T$)")
    root = ET.fromstring(compile_figure(figure.spec).document.text)
    label = next(item for item in root.iter() if item.get("id") == "m.f.label")
    assert "".join(label.itertext()) == "softmax(QKT)"


def test_module_takes_every_group_option() -> None:
    with Figure("grid") as figure:  # noqa: SIM117
        with figure.module("m", label="Grid", layout="grid", columns=2, row_gap="20pt") as m:
            m.block("a", label="A", at=(0, 0))
            m.block("b", label="B", at=(1, 1))
    group = figure.spec.group("m")
    assert group.layout.columns == 2
    assert group.layout.row_gap is not None
