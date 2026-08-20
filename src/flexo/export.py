"""Derived output generation, and the one call that compiles, writes, and lints."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from flexo.compiler import Compilation, compile_figure
from flexo.diagnostics import Diagnostic, FlexoError
from flexo.ir.semantic import FigureSpec
from flexo.lint import LintReport, lint_compilation
from flexo.style import LayoutStyle, Palette

if TYPE_CHECKING:  # pragma: no cover - import cycle only the type checker sees
    from flexo.builder import Figure

_MACOS_INKSCAPE = Path("/Applications/Inkscape.app/Contents/MacOS/inkscape")

FORMATS = ("editable", "portable", "pdf", "png")
"""Every output format ``export_outputs`` and ``build`` accept, in write order."""


@dataclass(frozen=True, slots=True)
class OutputFiles:
    editable_svg: Path
    portable_svg: Path | None = None
    pdf: Path | None = None
    png: Path | None = None

    def existing(self) -> tuple[Path, ...]:
        return tuple(
            target_file
            for target_file in (self.editable_svg, self.portable_svg, self.pdf, self.png)
            if target_file is not None
        )


def find_inkscape() -> Path | None:
    configured = os.environ.get("FLEXO_INKSCAPE")
    if configured:
        candidate = Path(configured).expanduser()
        return candidate if candidate.is_file() else None
    executable = shutil.which("inkscape")
    if executable:
        return Path(executable)
    return _MACOS_INKSCAPE if _MACOS_INKSCAPE.is_file() else None


def export_outputs(
    compilation: Compilation,
    output_directory: str | Path,
    *,
    stem: str | None = None,
    formats: tuple[str, ...] = FORMATS,
    dpi: float = 192.0,
) -> OutputFiles:
    """Write the editable SVG master and whichever derivatives ``formats`` names.

    The editable SVG is always written, because every derivative is produced from
    it by Inkscape.
    """

    unknown = sorted(set(formats) - set(FORMATS))
    if unknown:
        raise FlexoError(
            Diagnostic(
                "export.format.unknown",
                f"Unknown output format(s): {', '.join(unknown)}.",
                hint="Use editable, portable, pdf, or png.",
            )
        )
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    base = stem or compilation.measured.semantic.id
    editable = compilation.document.write(destination / f"{base}.editable.svg")
    portable = destination / f"{base}.portable.svg" if "portable" in formats else None
    pdf = destination / f"{base}.pdf" if "pdf" in formats else None
    png = destination / f"{base}.preview.png" if "png" in formats else None
    derived = (portable, pdf, png)
    if any(target_file is not None for target_file in derived):
        inkscape = find_inkscape()
        if inkscape is None:
            raise FlexoError(
                Diagnostic(
                    "export.inkscape.missing",
                    "Inkscape is required for portable SVG, PDF, and PNG outputs.",
                    hint="Install Inkscape or set FLEXO_INKSCAPE to its executable.",
                )
            )
        if portable is not None:
            _run(
                inkscape,
                editable,
                "--export-plain-svg",
                f"--export-filename={portable}",
            )
        if pdf is not None:
            _run(inkscape, editable, "--export-type=pdf", f"--export-filename={pdf}")
        if png is not None:
            _run(
                inkscape,
                editable,
                "--export-type=png",
                f"--export-filename={png}",
                f"--export-dpi={dpi:g}",
            )
    return OutputFiles(editable, portable, pdf, png)


@dataclass(frozen=True, slots=True)
class Build:
    """Everything one ``build`` produced: the compilation, the files, the lint."""

    compilation: Compilation
    outputs: OutputFiles
    report: LintReport

    @property
    def ok(self) -> bool:
        """Whether the figure linted without errors. Files are written either way."""

        return self.report.ok

    def summary(self) -> str:
        """The written paths and the lint report, ready to print."""

        written = [str(target_file) for target_file in self.outputs.existing()]
        return "\n".join([*written, self.report.format()])


def build(
    figure: Figure | FigureSpec,
    output_directory: str | Path = "build",
    *,
    stem: str | None = None,
    formats: tuple[str, ...] = FORMATS,
    dpi: float = 192.0,
    style: LayoutStyle | None = None,
    palette: Palette | None = None,
) -> Build:
    """Compile ``figure``, write the requested formats, and lint the result.

    The three calls every figure script used to make by hand. Outputs are written
    even when the figure lints with errors, so a flawed figure stays inspectable;
    read ``Build.ok`` or ``Build.report`` to decide what to do about it.
    """

    spec = figure if isinstance(figure, FigureSpec) else figure.spec
    compilation = compile_figure(spec, style=style, palette=palette)
    outputs = export_outputs(
        compilation,
        output_directory,
        stem=stem,
        formats=formats,
        dpi=dpi,
    )
    return Build(compilation, outputs, lint_compilation(compilation, style=style))


def query_bounds(source_file: str | Path) -> dict[str, tuple[float, float, float, float]]:
    inkscape = find_inkscape()
    if inkscape is None:
        raise FlexoError(Diagnostic("export.inkscape.missing", "Inkscape is not installed."))
    completed = _run(inkscape, Path(source_file), "--query-all")
    result = {}
    for line in completed.stdout.splitlines():
        parts = line.rsplit(",", 4)
        if len(parts) != 5:
            continue
        entity_id, x, y, width, height = parts
        result[entity_id] = (float(x), float(y), float(width), float(height))
    return result


def _run(
    executable: Path,
    source_file: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [str(executable), str(source_file), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        stderr = _compact_subprocess_message(completed.stderr)
        raise FlexoError(
            Diagnostic(
                "export.inkscape.failed",
                f"Inkscape exited with status {completed.returncode}: {stderr}",
                entity_id=source_file.name,
            )
        )
    return completed


def _compact_subprocess_message(message: str) -> str:
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    rendered = " ".join(lines[:3])
    return rendered[:500] or "no error message"
