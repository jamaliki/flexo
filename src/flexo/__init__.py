"""Flexo: semantic compilation for editable scientific figures."""

from flexo.builder import Figure, GroupBuilder, NodeHandle
from flexo.compiler import Compilation, compile_figure
from flexo.diagnostics import Diagnostic, FlexoError, Severity
from flexo.geometry import Point, Rect, Segment, Size
from flexo.ir.semantic import (
    EdgeSpec,
    FigureSpec,
    GroupSpec,
    LayoutSpec,
    NetSpec,
    NodeSpec,
    PortRef,
    PortSpec,
    TextRun,
)
from flexo.style import VectorPreset, shade_ramp, vector_stack_height
from flexo.units import CellSpan, Length, cm, inch, mm, pt, px

__all__ = [
    "CellSpan",
    "Compilation",
    "Diagnostic",
    "EdgeSpec",
    "Figure",
    "FigureSpec",
    "FlexoError",
    "GroupBuilder",
    "GroupSpec",
    "LayoutSpec",
    "Length",
    "NetSpec",
    "NodeHandle",
    "NodeSpec",
    "Point",
    "PortRef",
    "PortSpec",
    "Rect",
    "Segment",
    "Severity",
    "Size",
    "TextRun",
    "VectorPreset",
    "cm",
    "compile_figure",
    "inch",
    "mm",
    "pt",
    "px",
    "shade_ramp",
    "vector_stack_height",
]

__version__ = "0.1.0"
