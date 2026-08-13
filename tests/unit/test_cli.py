from __future__ import annotations

from pathlib import Path

from flexo.cli import main
from flexo.gallery import vertical_slice
from flexo.ir.semantic import (
    EdgeSpec,
    FigureSpec,
    GroupSpec,
    LayoutSpec,
    NodeSpec,
    PortRef,
    TextRun,
)
from flexo.serialization import save_figure
from flexo.units import pt


def clipped_label_figure() -> FigureSpec:
    """Compiles cleanly but lints with an error: the label cannot fit its block."""

    return FigureSpec(
        "clipped",
        width=pt(120),
        nodes=(
            NodeSpec(
                "tiny",
                "block",
                (TextRun("A label far too long for this block"),),
                width=pt(12),
                height=pt(8),
            ),
        ),
        groups=(GroupSpec("root", ("tiny",), LayoutSpec("row"), role="canvas"),),
    )


def clean_pair_figure() -> FigureSpec:
    """One straight connector between two blocks: no diagnostic of any kind."""

    return FigureSpec(
        "pair",
        width=pt(180),
        nodes=(
            NodeSpec("source", "block", (TextRun("Source"),)),
            NodeSpec("target", "block", (TextRun("Target"),)),
        ),
        edges=(EdgeSpec("flow", PortRef("source", "output"), PortRef("target", "input")),),
        groups=(
            GroupSpec(
                "root",
                ("source", "target"),
                LayoutSpec("row", gap=pt(24), justify="start"),
                role="canvas",
            ),
        ),
    )


def test_build_editable_svg(tmp_path: Path) -> None:
    source = save_figure(vertical_slice(), tmp_path / "figure.yaml")
    output = tmp_path / "output"
    assert main(["build", str(source), "-o", str(output), "--formats", "editable"]) == 0
    assert (output / "figure.editable.svg").is_file()


def test_build_writes_outputs_and_reports_lint_errors(tmp_path: Path, capsys) -> None:
    source = save_figure(clipped_label_figure(), tmp_path / "clipped.yaml")
    output = tmp_path / "output"
    assert main(["build", str(source), "-o", str(output), "--formats", "editable"]) == 1
    assert (output / "clipped.editable.svg").is_file()
    captured = capsys.readouterr()
    assert "layout.text.overflow" in captured.err
    assert "clipped.editable.svg" in captured.out


def test_gallery_writes_outputs_before_linting(tmp_path: Path) -> None:
    output = tmp_path / "output"
    assert main(["gallery", "vertical-slice", "-o", str(output), "--formats", "editable"]) == 0
    assert (output / "vertical-slice.editable.svg").is_file()


def test_hard_compile_failure_writes_no_output(tmp_path: Path, capsys) -> None:
    source = save_figure(
        FigureSpec(
            "overflowing",
            width=pt(40),
            nodes=(NodeSpec("wide", "block", (TextRun("Far too wide to ever fit"),)),),
            groups=(
                GroupSpec("root", ("box",), LayoutSpec("row"), role="canvas"),
                GroupSpec("box", ("wide",), LayoutSpec("row", width=pt(20), height=pt(20))),
            ),
        ),
        tmp_path / "overflowing.yaml",
    )
    output = tmp_path / "output"
    assert main(["build", str(source), "-o", str(output), "--formats", "editable"]) == 2
    assert not (output / "overflowing.editable.svg").exists()
    assert "layout.overflow" in capsys.readouterr().err


def test_check_semantic_source(tmp_path: Path, capsys) -> None:
    source = save_figure(vertical_slice(), tmp_path / "figure.yaml")
    assert main(["check", str(source)]) == 0
    printed = capsys.readouterr().out
    # R18 keeps the attention's K and V arrows on their authored side centres,
    # so the two swap order in the corridor and cross once. A crossing is a
    # warning by design (R7); nothing in this figure may be an error.
    assert "error" not in printed


def test_check_reports_a_figure_without_diagnostics(tmp_path: Path, capsys) -> None:
    source = save_figure(clean_pair_figure(), tmp_path / "pair.yaml")
    assert main(["check", str(source)]) == 0
    assert "ok: no diagnostics" in capsys.readouterr().out


def test_schema_command(tmp_path: Path) -> None:
    output = tmp_path / "schema.json"
    assert main(["schema", "--output", str(output)]) == 0
    assert '"schema_version"' in output.read_text(encoding="utf-8")
