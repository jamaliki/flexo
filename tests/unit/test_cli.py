from __future__ import annotations

from pathlib import Path

from flexo.cli import main
from flexo.gallery import vertical_slice
from flexo.serialization import save_figure


def test_build_editable_svg(tmp_path: Path) -> None:
    source = save_figure(vertical_slice(), tmp_path / "figure.yaml")
    output = tmp_path / "output"
    assert main(["build", str(source), "-o", str(output), "--formats", "editable"]) == 0
    assert (output / "figure.editable.svg").is_file()


def test_check_semantic_source(tmp_path: Path, capsys) -> None:
    source = save_figure(vertical_slice(), tmp_path / "figure.yaml")
    assert main(["check", str(source)]) == 0
    assert "ok: no diagnostics" in capsys.readouterr().out


def test_schema_command(tmp_path: Path) -> None:
    output = tmp_path / "schema.json"
    assert main(["schema", "--output", str(output)]) == 0
    assert '"schema_version"' in output.read_text(encoding="utf-8")
