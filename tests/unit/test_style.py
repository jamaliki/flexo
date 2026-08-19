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
    VectorPreset,
    _shuffled_shades,
    shade_ramp,
    vector_stack_height,
)
from flexo.units import CellSpan, pt


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


def test_shade_ramp_puts_the_base_in_the_middle_of_an_odd_count() -> None:
    assert shade_ramp("#4A6CB0", 1) == ("#4a6cb0",)
    assert len(shade_ramp("#4a6cb0", 2)) == 2
    light, middle, dark = shade_ramp("#4a6cb0", 3)
    assert middle == "#4a6cb0"
    assert _channel_sum(light) > _channel_sum(middle) > _channel_sum(dark)


def test_shade_ramp_darkens_monotonically() -> None:
    sums = [_channel_sum(shade) for shade in shade_ramp("#e2703a", 6)]
    assert all(first > second for first, second in pairwise(sums))


def test_shade_ramp_expands_shorthand_hex() -> None:
    assert shade_ramp("#f0a", 3) == shade_ramp("#ff00aa", 3)


def test_shade_ramp_rejects_a_bad_base_or_count() -> None:
    for bad in ("4a6cb0", "#12345", "#gggggg", "rebeccapurple", 12):
        with pytest.raises(ValueError, match="invalid colour"):
            shade_ramp(bad, 3)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least one shade"):
        shade_ramp("#4a6cb0", 0)


def test_vector_preset_reads_topology_columns_first() -> None:
    """``"1x3"`` is one column of three stacked cells, not the transpose."""

    for topology in (3, "1x3", "1 x 3", (1, 3)):
        preset = VectorPreset("#4a6cb0", topology)  # type: ignore[arg-type]
        assert (preset.columns, preset.cells) == (1, 3)
    wide = VectorPreset("#4a6cb0", "3 \u00d7 3")
    assert (wide.columns, wide.cells) == (3, 3)


def test_vector_preset_rejects_an_unreadable_topology() -> None:
    for bad in ("3", "1x", "axb", 0, (2, 0), (0, 2), (1, 2, 3), 1.5):
        with pytest.raises(ValueError):
            VectorPreset("#4a6cb0", bad)  # type: ignore[arg-type]


def test_vector_preset_takes_one_base_per_column_or_one_for_all() -> None:
    broadcast = VectorPreset(("#4a6cb0",), "2x3").column_shades()
    assert broadcast[0] == broadcast[1] == shade_ramp("#4a6cb0", 3)
    per_column = VectorPreset(("#d0568c", "#7fae3f"), "2x3").column_shades()
    assert per_column == (shade_ramp("#d0568c", 3), shade_ramp("#7fae3f", 3))
    with pytest.raises(ValueError, match="base colours"):
        VectorPreset(("#d0568c", "#7fae3f", "#4a6cb0"), "2x3")
    with pytest.raises(ValueError, match="invalid colour"):
        VectorPreset(("#d0568c", "nope"), "2x3")


def test_vector_preset_encodes_columns_then_cells() -> None:
    preset = VectorPreset(("#d0568c", "#7fae3f"), "2x3")
    encoded = preset.encode()
    assert encoded.split(";") == [",".join(column) for column in preset.column_shades()]
    assert encoded.count(";") == 1 and encoded.count(",") == 4


def _channel_sum(colour: str) -> int:
    return sum(int(colour[index : index + 2], 16) for index in (1, 3, 5))


def _lightness(colour: str) -> float:
    red, green, blue = (int(colour[index : index + 2], 16) for index in (1, 3, 5))
    assert red == green == blue, f"{colour} is not a grey"
    return float(red)


def test_vector_stack_height_is_cells_plus_the_gaps_between_them() -> None:
    style = LayoutStyle()
    for cells in (1, 2, 3, 7):
        expected = (
            cells * style.vector_cell.points + (cells - 1) * style.vector_cell_gap.points
        )
        assert vector_stack_height(style, cells).points == pytest.approx(expected)
    assert vector_stack_height(style).points == vector_stack_height(style, 3).points
    assert vector_stack_height(style, 1) == style.vector_cell


def test_vector_stack_height_follows_the_style_tokens() -> None:
    style = LayoutStyle().with_updates(vector_cell=pt(10), vector_cell_gap=pt(2))
    assert vector_stack_height(style, 3).points == pytest.approx(34.0)


def test_vector_stack_needs_a_cell() -> None:
    with pytest.raises(ValueError, match="at least one cell"):
        vector_stack_height(LayoutStyle(), 0)


def test_resolve_extent_passes_lengths_through_and_expands_cell_spans() -> None:
    style = LayoutStyle()
    assert style.resolve_extent(pt(17)) == pt(17)
    assert style.resolve_extent(CellSpan(4)) == vector_stack_height(style, 4)


def test_shade_ramp_limits_move_the_ends_and_leave_the_base_alone() -> None:
    base = "#e0603a"
    default = shade_ramp(base, 3)
    tighter = shade_ramp(base, 3, tint=0.35)
    assert tighter[1] == default[1] == base, "the middle step is the base itself"
    assert tighter[2] == default[2], "shade is untouched by the tint"
    # A smaller tint keeps the light cell nearer its base instead of the canvas.
    assert _channel_sum(base) < _channel_sum(tighter[0]) < _channel_sum(default[0])
    deeper = shade_ramp(base, 3, shade=0.6)
    assert _channel_sum(deeper[2]) < _channel_sum(default[2])


def test_shade_ramp_rejects_limits_outside_the_unit_interval() -> None:
    for bad in (-0.1, 1.0, 1.5):
        with pytest.raises(ValueError, match="tint"):
            shade_ramp("#e0603a", 3, tint=bad)
        with pytest.raises(ValueError, match="shade"):
            shade_ramp("#e0603a", 3, shade=bad)
        with pytest.raises(ValueError, match="tint"):
            VectorPreset("#e0603a", "1x3", tint=bad)
        with pytest.raises(ValueError, match="shade"):
            VectorPreset("#e0603a", "1x3", shade=bad)
    assert shade_ramp("#e0603a", 3, tint=0.0)[0] == "#e0603a"


def test_vector_preset_plumbs_its_limits_into_every_column() -> None:
    preset = VectorPreset(("#d0568c", "#7fae3f"), "2x3", tint=0.35, shade=0.5)
    assert preset.column_shades() == (
        shade_ramp("#d0568c", 3, tint=0.35, shade=0.5),
        shade_ramp("#7fae3f", 3, tint=0.35, shade=0.5),
    )


def test_shuffled_preset_is_the_same_figure_every_time() -> None:
    """Reproducible builds: one preset must encode identically forever."""

    options = {"order": "shuffled", "seed": 7}
    first = VectorPreset(("#d0568c", "#7fae3f"), "2x5", **options)
    second = VectorPreset(("#d0568c", "#7fae3f"), "2x5", **options)
    assert first.encode() == second.encode()
    assert first.column_shades() == second.column_shades()
    # The permutation is a rearrangement, not a recolouring.
    assert sorted(first.column_shades()[0]) == sorted(shade_ramp("#d0568c", 5))


def test_shuffled_columns_differ_from_each_other_and_from_the_ramp() -> None:
    preset = VectorPreset(("#d0568c", "#d0568c"), "2x5", order="shuffled")
    left, right = preset.column_shades()
    assert left != right, "each column seeds its own permutation"
    assert left != shade_ramp("#d0568c", 5) and right != shade_ramp("#d0568c", 5)


def test_a_shuffled_glyph_never_comes_back_as_a_ramp() -> None:
    """The identity guard: "shuffled" may not silently look light-to-dark."""

    for cells in range(2, 8):
        for seed in range(24):
            preset = VectorPreset("#4a6cb0", (1, cells), order="shuffled", seed=seed)
            (column,) = preset.column_shades()
            assert column != shade_ramp("#4a6cb0", cells)
    # One cell has no other arrangement, so it is left exactly as it is.
    assert VectorPreset("#4a6cb0", "1x1", order="shuffled").column_shades() == (
        shade_ramp("#4a6cb0", 1),
    )


def test_shuffled_falls_back_to_a_rotation_when_every_draw_is_identity() -> None:
    ramp = shade_ramp("#4a6cb0", 4)

    class _Identity:
        def randrange(self, stop: int) -> int:
            return stop - 1  # every element swaps with itself

    assert _shuffled_shades(ramp, _Identity()) == ramp[-1:] + ramp[:-1]


def test_a_seed_changes_the_permutation() -> None:
    shades = {
        VectorPreset("#4a6cb0", "1x5", order="shuffled", seed=seed).encode()
        for seed in range(6)
    }
    assert len(shades) > 1, "the seed has to reach the permutation"


def test_vector_preset_rejects_an_unknown_shade_order() -> None:
    with pytest.raises(ValueError, match="unknown vector shade order"):
        VectorPreset("#4a6cb0", "1x3", order="gradient")  # type: ignore[arg-type]
    assert VectorPreset("#4a6cb0", "1x3").order == "ramp"
    assert VectorPreset("#4a6cb0", "1x3").column_shades() == (shade_ramp("#4a6cb0", 3),)
