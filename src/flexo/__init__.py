"""Flexo: semantic compilation for editable scientific figures.

Everything a figure author needs is re-exported here, so a figure script opens
with one import: the builder, the semantic types it lowers into, physical units,
style and palette tokens, and the one-call ``build`` that compiles, writes, and
lints.
"""

from flexo.builder import Figure, GroupBuilder, NodeHandle
from flexo.compiler import Compilation, compile_figure
from flexo.diagnostics import Diagnostic, FlexoError, Severity
from flexo.export import FORMATS, Build, OutputFiles, build, export_outputs, find_inkscape
from flexo.geometry import Point, Rect, Segment, Side, Size
from flexo.ir.semantic import (
    EdgeSpec,
    FigureSpec,
    GroupSpec,
    JointStyle,
    LayoutKind,
    LayoutSpec,
    NetSpec,
    NodeSpec,
    PortRef,
    PortSpec,
    TextRun,
)
from flexo.lint import LintReport, lint_compilation, lint_svg
from flexo.serialization import dump_figure, load_figure, save_figure
from flexo.style import (
    COLOR_VISION_SAFE_PALETTE,
    DEFAULT_PALETTE,
    GRAYSCALE_PALETTE,
    PALETTES,
    RAMP_ROLES,
    STYLES,
    LayoutStyle,
    Palette,
    TypographyStyle,
    VectorPreset,
    shade_ramp,
    vector_stack_height,
)
from flexo.theme import retheme_svg
from flexo.units import CellSpan, Extent, Length, cm, inch, mm, pt, px

__all__ = [
    "COLOR_VISION_SAFE_PALETTE",
    "DEFAULT_PALETTE",
    "FORMATS",
    "GRAYSCALE_PALETTE",
    "PALETTES",
    "RAMP_ROLES",
    "STYLES",
    "Build",
    "CellSpan",
    "Compilation",
    "Diagnostic",
    "EdgeSpec",
    "Extent",
    "Figure",
    "FigureSpec",
    "FlexoError",
    "GroupBuilder",
    "GroupSpec",
    "JointStyle",
    "LayoutKind",
    "LayoutSpec",
    "LayoutStyle",
    "Length",
    "LintReport",
    "NetSpec",
    "NodeHandle",
    "NodeSpec",
    "OutputFiles",
    "Palette",
    "Point",
    "PortRef",
    "PortSpec",
    "Rect",
    "Segment",
    "Severity",
    "Side",
    "Size",
    "TextRun",
    "TypographyStyle",
    "VectorPreset",
    "build",
    "cm",
    "compile_figure",
    "dump_figure",
    "export_outputs",
    "find_inkscape",
    "inch",
    "lint_compilation",
    "lint_svg",
    "load_figure",
    "mm",
    "pt",
    "px",
    "retheme_svg",
    "save_figure",
    "shade_ramp",
    "vector_stack_height",
]

__version__ = "0.1.0"
