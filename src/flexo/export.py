"""Derived output generation, and the one call that compiles, writes, and lints."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from flexo.compiler import Compilation, compile_figure
from flexo.diagnostics import Diagnostic, FlexoError
from flexo.drawing import read_drawing
from flexo.fonts import font_directories
from flexo.ir.semantic import FigureSpec
from flexo.lint import LintReport, lint_compilation
from flexo.pdf import write_pdf
from flexo.portable import portable_svg
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


def export_outputs(
    compilation: Compilation,
    output_directory: str | Path,
    *,
    stem: str | None = None,
    formats: tuple[str, ...] = FORMATS,
    dpi: float = 192.0,
) -> OutputFiles:
    """Write the editable SVG master and whichever derivatives ``formats`` names.

    Every derivative is written in Python from the master, read back as a
    ``flexo.drawing``: the portable SVG with its words as outlines
    (``flexo.portable``), the PDF with real text in embedded fonts
    (``flexo.pdf``), and the PNG rasterised from the portable SVG by resvg, so
    it shows exactly the glyphs Flexo measured. No external program is needed.
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
    if portable is None and pdf is None and png is None:
        return OutputFiles(editable)
    text = compilation.document.text
    drawing = read_drawing(text)
    if portable is not None or png is not None:
        root = ET.fromstring(text)
        outlined = portable_svg(drawing, width=root.get("width"), height=root.get("height"))
        if portable is not None:
            portable.write_text(outlined, encoding="utf-8")
        if png is not None:
            png.write_bytes(rasterise(outlined, dpi))
    if pdf is not None:
        write_pdf(drawing, pdf, title=compilation.measured.semantic.id)
    return OutputFiles(editable, portable, pdf, png)


def rasterise(svg_text: str, dpi: float = 192.0) -> bytes:
    """PNG bytes of an SVG, drawn by resvg; text is best given as outlines."""

    import resvg_py

    return bytes(
        resvg_py.svg_to_bytes(
            svg_string=svg_text,
            font_dirs=[str(directory) for directory in font_directories()],
            dpi=dpi,
        )
    )


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
