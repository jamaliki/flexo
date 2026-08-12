"""Flexo: semantic compilation for editable scientific figures."""

from flexo.diagnostics import Diagnostic, FlexoError, Severity
from flexo.geometry import Point, Rect, Segment, Size
from flexo.ir.semantic import (
    EdgeSpec,
    FigureSpec,
    GroupSpec,
    LayoutSpec,
    NodeSpec,
    PortRef,
    PortSpec,
    TextRun,
)
from flexo.units import Length, cm, inch, mm, pt, px

__all__ = [
    "Diagnostic",
    "EdgeSpec",
    "FigureSpec",
    "FlexoError",
    "GroupSpec",
    "LayoutSpec",
    "Length",
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
    "inch",
    "mm",
    "pt",
    "px",
]

__version__ = "0.1.0"
