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
from flexo.units import Length, cm, inch, mm, pt, px

__all__ = [
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
    "cm",
    "compile_figure",
    "inch",
    "mm",
    "pt",
    "px",
]

__version__ = "0.1.0"
