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
    """PNG bytes of an SVG, drawn by resvg; text is best given as outlines. An SVG placed
    in it as a picture is drawn first, with the fonts (resvg draws a picture's text
    without them, so it vanished); a picture much enlarged shows its pixels."""

    import resvg_py

    fonts = [str(directory) for directory in font_directories()]
    if "data:image/svg+xml;base64," in svg_text:
        svg_text = _pictures_drawn(svg_text, dpi, fonts)
    if "<image" in svg_text:
        svg_text = _pixels_shown(svg_text, dpi)
    return bytes(resvg_py.svg_to_bytes(svg_string=svg_text, font_dirs=fonts, dpi=dpi))


def _pixels_shown(svg_text: str, dpi: float) -> str:
    """Each PNG or JPEG drawn at twice its pixels or more, drawn in its pixels rather than
    smoothed: a PDF viewer draws it so, and a 16-pixel icon or a plot's coarse image
    (``imshow``) is then the same in the PNG as in the PDF, not a blur."""

    import re

    from flexo.drawing import _length
    from flexo.pdf import _decode, _pixel_size

    root = re.search(r"<svg\b[^>]*>", svg_text)
    if root is None:
        return svg_text
    view = re.search(r'\bviewBox="([^"]*)"', root.group(0))
    width = re.search(r'\bwidth="([^"]*)"', root.group(0))
    span = [float(value) for value in re.split(r"[ ,]+", view.group(1).strip())][2] if view else 0.0
    points = _length(width.group(1)) if width else span
    # Device pixels per unit of the drawing, as resvg sizes the page at ``dpi``.
    scale = points / 72.0 * dpi / span if span else dpi / 72.0

    def shown(match: re.Match[str]) -> str:
        tag = match.group(0)
        mime, data = _decode(match.group(1))
        size = _pixel_size(mime, data) if mime else None
        box = [re.search(rf'\b{name}="([\d.]+)', tag) for name in ("width", "height")]
        if size is None or None in box or "image-rendering" in tag:
            return tag
        across, down = (float(found.group(1)) for found in box if found)
        if min(across / size[0], down / size[1]) * scale < 2.0:
            return tag
        return tag.replace("<image", '<image image-rendering="optimizeSpeed"', 1)

    pictures = r'<image\b[^>]*?href="(data:image/(?:png|jpeg);base64,[^"]+)"[^>]*>'
    return re.sub(pictures, shown, svg_text)


def _pictures_drawn(svg_text: str, dpi: float, fonts: list[str]) -> str:
    """Each SVG picture in ``svg_text`` as a PNG, at the resolution it is drawn at."""

    import base64
    import re

    import resvg_py

    def drawn(match: re.Match[str]) -> str:
        tag = match.group(0)
        size = re.search(r'\bwidth="([\d.]+)', tag)
        nested = base64.b64decode(match.group(2)).decode("utf-8", "replace")
        # Twice the pixels it covers, so it stays sharp when the slide is enlarged.
        scale = dpi / 72.0 * 2.0 * (float(size.group(1)) if size else 300.0)
        try:
            png = bytes(
                resvg_py.svg_to_bytes(svg_string=nested, font_dirs=fonts, width=max(int(scale), 1))
            )
        except Exception:  # a picture resvg cannot draw is left as it was
            return tag
        encoded = "data:image/png;base64," + base64.b64encode(png).decode()
        return tag.replace(match.group(1), encoded)

    pictures = r'<image\b[^>]*?href="(data:image/svg\+xml;base64,([A-Za-z0-9+/=]+))"[^>]*>'
    return re.sub(pictures, drawn, svg_text)


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
