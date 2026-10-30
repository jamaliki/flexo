"""Dark versions of the themes (``flexo.dark_themes``): each light theme turned over -- its page
mirrored, its words, lines, tints and colours as far from the dark page as they were from the
light one, hue kept -- and named for it, chosen as any theme is."""

from __future__ import annotations

import math

import pytest

import flexo
from flexo.colour import chroma, contrast, is_dark, to_oklab
from flexo.dark_themes import ACCENT, MUTED, WORDS, turned
from flexo.themes import BUILT_IN, THEMES, resolve_palette, theme, theme_names


def _hue(colour: str) -> float:
    _, a, b = to_oklab(colour)
    return math.degrees(math.atan2(b, a)) % 360.0


def test_every_light_theme_has_a_dark_version_named_for_it() -> None:
    light = [name for name in BUILT_IN if not name.endswith("-dark") and name != "dark"]
    assert len(light) >= 12
    for name in light:
        assert f"{name}-dark" in theme_names() and f"{name}-dark" in BUILT_IN
    # A theme on a dark page already is not turned over.
    assert "dark-dark" not in THEMES


def test_a_dark_version_reads_as_its_theme_does() -> None:
    for name in [name for name in BUILT_IN if name.endswith("-dark")]:
        made, base = theme(name), theme(name.removesuffix("-dark"))
        page = made.page
        assert is_dark(page.canvas), name
        assert contrast(page.ink, page.canvas) >= WORDS - 0.01, name
        assert contrast(page.muted, page.canvas) >= MUTED - 0.01, name
        # Its words as far from its page as they were, or farther.
        was = contrast(base.page.ink, base.page.canvas)
        assert contrast(page.ink, page.canvas) >= min(was, 15.0) - 0.5, name
        # Each of its colours -- the accents -- stands out from its page, its hue kept.
        for own, was in zip(made.palette, base.palette, strict=True):
            assert contrast(own, page.canvas) >= ACCENT - 0.01, (name, own)
            if chroma(was) > 0.05 and chroma(own) > 0.05:
                turn = abs(_hue(own) - _hue(was)) % 360.0
                assert min(turn, 360.0 - turn) < 12.0, (name, own, was)
        # And its style is its theme's.
        assert made.style.typography == base.style.typography and made.style.name == name


def test_a_tint_turned_over_is_as_quiet_and_an_outline_as_firm() -> None:
    paper, dark = resolve_palette("paper"), resolve_palette("paper-dark")
    light_page, dark_page = paper.get("canvas"), dark.get("canvas")
    assert dark_page == "#000000"
    for index in range(1, 5):
        fill, outline = f"tone-{index}-fill", f"tone-{index}-stroke"
        was = contrast(paper.get(fill), light_page)
        assert contrast(dark.get(fill), dark_page) == pytest.approx(was, rel=0.25)
        assert contrast(dark.get(outline), dark_page) >= 3.0
        # Dark boxes, light outlines.
        assert is_dark(dark.get(fill)) and not is_dark(dark.get(outline))


def test_turned_keeps_a_colours_contrast_with_the_page() -> None:
    for colour in ("#242126", "#6b6570", "#3f7fc0", "#e63312", "#f1eff4"):
        made = turned(colour, "#ffffff", "#000000")
        assert contrast(made, "#000000") == pytest.approx(contrast(colour, "#ffffff"), rel=0.03)


def test_a_figure_is_drawn_in_a_dark_version_and_a_theme_of_ones_own_has_one() -> None:
    figure = flexo.Figure("dark", theme="swiss-dark")
    figure.root.block("encoder", label="Encoder")
    svg = figure.compile().document.text
    assert theme("swiss-dark").page.canvas in svg
    own = {"theme": {"name": "lab-own", "base": "paper", "page": {"canvas": "#fbfaf5"}}}
    name = flexo.register_theme(own)
    made = theme(f"{name}-dark")
    assert is_dark(made.page.canvas) and made.name == f"{name}-dark"
    with pytest.raises(flexo.FlexoError):
        theme("nothing-like-it-dark")
    THEMES.pop(name, None)
    THEMES.pop(f"{name}-dark", None)


def test_a_dark_version_writes_out_as_a_theme_file() -> None:
    import yaml

    written = yaml.safe_load(flexo.dump_theme("paper-dark"))["theme"]
    assert written["page"]["canvas"] == "#000000"
    tones = written["tones"]
    assert tones["rule"] == "tinted" and tones["fill_lightness"] < 0.5 < tones["stroke_lightness"]
