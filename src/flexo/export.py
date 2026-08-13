"""Derived output generation through the installed Inkscape CLI."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from flexo.compiler import Compilation
from flexo.diagnostics import Diagnostic, FlexoError

_MACOS_INKSCAPE = Path("/Applications/Inkscape.app/Contents/MacOS/inkscape")


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
    formats: tuple[str, ...] = ("editable", "portable", "pdf", "png"),
    dpi: float = 192.0,
) -> OutputFiles:
    unknown = sorted(set(formats) - {"editable", "portable", "pdf", "png"})
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
