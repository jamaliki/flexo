"""Geometry-affecting layout styles and paint-only palettes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.units import Length, mm, pt

_PT_0_8 = pt(0.8)
_PT_0_9 = pt(0.9)
_PT_3 = pt(3.0)
_PT_3_5 = pt(3.5)
_PT_4 = pt(4.0)
_PT_5 = pt(5.0)
_PT_6 = pt(6.0)
_PT_7 = pt(7.0)
_PT_8 = pt(8.0)
_PT_11 = pt(11.0)
_PT_14 = pt(14.0)
_PUBLICATION_WIDTHS = (
    ("single-column", mm(85.0)),
    ("double-column", mm(180.0)),
    ("presentation", mm(254.0)),
)


@dataclass(frozen=True, slots=True)
class TypographyStyle:
    family: str = "IBM Plex Sans"
    size: Length = _PT_8
    minimum_size: Length = _PT_7
    line_height: float = 1.22
    label_weight: int = 500
    title_weight: int = 600


_DEFAULT_TYPOGRAPHY = TypographyStyle()


@dataclass(frozen=True, slots=True)
class LayoutStyle:
    name: str = "paper"
    typography: TypographyStyle = _DEFAULT_TYPOGRAPHY
    padding_x: Length = _PT_7
    padding_y: Length = _PT_5
    gap: Length = _PT_14
    compact_gap: Length = _PT_7
    group_padding: Length = _PT_14
    stroke_width: Length = _PT_0_8
    connector_width: Length = _PT_0_9
    corner_radius: Length = _PT_3
    arrow_length: Length = _PT_4
    arrow_width: Length = _PT_3_5
    route_clearance: Length = _PT_5
    route_boundary_clearance: Length = _PT_8
    route_lane_spacing: Length = _PT_4
    port_spacing: Length = _PT_6
    bend_penalty: float = 14.0
    widths: tuple[tuple[str, Length], ...] = _PUBLICATION_WIDTHS

    def resolve_width(self, value: str | Length | float) -> Length:
        if isinstance(value, str):
            presets = dict(self.widths)
            if value in presets:
                return presets[value]
        return Length.parse(value)

    def with_updates(self, **changes: object) -> LayoutStyle:
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class Palette:
    """Paint tokens only. No field in this type may affect geometry."""

    name: str
    paints: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "paints", MappingProxyType(dict(self.paints)))

    def get(self, role: str, fallback: str = "#000000") -> str:
        return self.paints.get(role, fallback)

    def with_overrides(self, overrides: Mapping[str, str]) -> Palette:
        unknown = sorted(set(overrides) - set(self.paints))
        if unknown:
            raise FlexoError(
                Diagnostic(
                    "palette.role.unknown",
                    f"Unknown paint role(s): {', '.join(unknown)}.",
                    hint=f"Valid roles: {', '.join(sorted(self.paints))}.",
                )
            )
        return Palette(self.name, {**self.paints, **overrides})


DEFAULT_PALETTE = Palette(
    "default",
    {
        "canvas": "#ffffff",
        "ink": "#25232a",
        "muted-ink": "#625e6b",
        "container-fill": "#f7f5fa",
        "container-stroke": "#c9c2d3",
        "block-fill": "#eee8f5",
        "block-stroke": "#665477",
        "accent-fill": "#d9f1f0",
        "accent-stroke": "#237f84",
        "warm-fill": "#f8e5d7",
        "warm-stroke": "#a96133",
        "connector": "#4e4856",
        "residual": "#6d4ba0",
        "grid": "#80758b",
        "inset-fill": "#eef4f5",
    },
)

COLOR_VISION_SAFE_PALETTE = Palette(
    "color-vision-safe",
    {
        **dict(DEFAULT_PALETTE.paints),
        "block-fill": "#e8eef8",
        "block-stroke": "#3f6c9e",
        "accent-fill": "#e1f2e8",
        "accent-stroke": "#29845a",
        "warm-fill": "#fff0ce",
        "warm-stroke": "#9b6b00",
        "residual": "#8c4b78",
    },
)

GRAYSCALE_PALETTE = Palette(
    "grayscale",
    {
        "canvas": "#ffffff",
        "ink": "#191919",
        "muted-ink": "#555555",
        "container-fill": "#f5f5f5",
        "container-stroke": "#b8b8b8",
        "block-fill": "#e6e6e6",
        "block-stroke": "#555555",
        "accent-fill": "#d7d7d7",
        "accent-stroke": "#3d3d3d",
        "warm-fill": "#eeeeee",
        "warm-stroke": "#707070",
        "connector": "#444444",
        "residual": "#1f1f1f",
        "grid": "#777777",
        "inset-fill": "#f0f0f0",
    },
)

PALETTES = {
    palette.name: palette
    for palette in (DEFAULT_PALETTE, COLOR_VISION_SAFE_PALETTE, GRAYSCALE_PALETTE)
}

STYLES = {"paper": LayoutStyle()}
