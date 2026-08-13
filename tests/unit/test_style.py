from __future__ import annotations

from itertools import pairwise

import pytest

from flexo.diagnostics import FlexoError
from flexo.style import (
    DEFAULT_PALETTE,
    GRAYSCALE_PALETTE,
    PALETTES,
    RAMP_ROLES,
    LayoutStyle,
)


def test_publication_width_preset() -> None:
    assert LayoutStyle().resolve_width("double-column").to("mm") == pytest.approx(180.0)


def test_palette_rejects_unknown_role() -> None:
    with pytest.raises(FlexoError, match="Unknown paint role"):
        DEFAULT_PALETTE.with_overrides({"padding": "pink"})


def test_palette_mapping_is_immutable() -> None:
    with pytest.raises(TypeError):
        DEFAULT_PALETTE.paints["ink"] = "red"  # type: ignore[index]


def test_every_palette_defines_the_same_roles_including_the_ramps() -> None:
    """R19: a figure may name any ramp and still re-theme into any palette."""

    for palette in PALETTES.values():
        assert set(palette.paints) == set(DEFAULT_PALETTE.paints), palette.name
        assert set(RAMP_ROLES) <= set(palette.paints), palette.name


def test_grayscale_ramps_stay_apart_by_lightness() -> None:
    """R19: without hue, the ramps must still be tellable apart."""

    lightness = [_lightness(GRAYSCALE_PALETTE.get(role)) for role in RAMP_ROLES]
    assert lightness == sorted(lightness), "ramps form one monotone ladder"
    steps = [second - first for first, second in pairwise(lightness)]
    assert min(steps) >= 20.0, f"ramp lightness steps too small: {steps}"


def test_vector_cell_tokens_are_positive_and_smaller_than_the_cells() -> None:
    style = LayoutStyle()
    assert style.vector_cell.points > 0.0
    assert 0.0 < style.vector_cell_gap.points < style.vector_cell.points
    assert 0.0 < style.vector_cell_radius.points < style.vector_cell.points / 2.0
    assert style.vector_column_gap.points >= style.vector_cell_gap.points


def _lightness(colour: str) -> float:
    red, green, blue = (int(colour[index : index + 2], 16) for index in (1, 3, 5))
    assert red == green == blue, f"{colour} is not a grey"
    return float(red)
