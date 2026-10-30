"""Dark versions of the themes: ``paper-dark``, ``swiss-dark`` -- each light theme turned over.

A dark version keeps everything about its theme but its paint. Its page's lightness is
mirrored (Oklab's: white is black, a cream page a warm near-black), and every other colour --
its words, its lines, its tints, each of its palette's -- has its lightness turned over about
the page: as much lighter than the dark page as it was darker than the light one, measured as
contrast is, so its words read as well as they did and a pale tint is as quiet. Hue and
colourfulness are kept. Its tones are tinted at the lightnesses so turned: pale boxes with dark
outlines become dark boxes with light ones. Then each of its palette's colours -- the accents
-- is checked to stand out from the page as much as an outline must (``ACCENT``), and its words
and muted words to read (``WORDS``, ``MUTED``): a colour of middling lightness turns over to
one as middling.

Every light theme flexo has is given one, named for it (``theme_names``), so it is chosen as
any theme is -- in a theme picker, or as ``theme: swiss-dark`` -- and a theme of one's own has
one too, by its name and ``-dark``, once it is registered.
"""

from __future__ import annotations

from dataclasses import fields, replace
from functools import lru_cache
from typing import TYPE_CHECKING

from flexo.colour import (
    Written,
    curated,
    from_oklab,
    is_dark,
    luminance,
    to_oklab,
    with_contrast,
    with_lightness,
)

if TYPE_CHECKING:  # pragma: no cover
    from flexo.themes import Page, Theme, ToneRule

SUFFIX = "-dark"
"""What a theme's name is followed by to name its dark version."""

ACCENT = 3.0
"""How far each of a dark version's palette colours stands from its page: as an outline must."""
WORDS = 7.0
"""How far its words stand from its page, at the least."""
MUTED = 4.5
"""How far its muted words (captions, a slide's number) stand from its page, at the least."""


def mirrored(colour: str) -> str:
    """``colour`` with its Oklab lightness mirrored (white is black), hue and colourfulness
    kept as far as there is room for them at that lightness."""

    lightness, _, _ = to_oklab(colour)
    return with_lightness(colour, min(max(1.0 - lightness, 0.0), 1.0))


def _turned_luminance(own: float, light: float, dark: float) -> float:
    """The luminance a colour of luminance ``own`` on a page of ``light`` has on a page of
    ``dark``, standing as far from it -- by contrast -- on the other side."""

    if own <= light:
        return min(1.0, (light + 0.05) / (own + 0.05) * (dark + 0.05) - 0.05)
    return max(0.0, (dark + 0.05) / ((own + 0.05) / (light + 0.05)) - 0.05)


@lru_cache(maxsize=1024)
def turned(colour: str, light: str, dark: str) -> str:
    """``colour``, on a page of ``light``, turned over for a page of ``dark`` (``light``'s
    mirror): its lightness set so it stands as far from the dark page as it stood from the
    light one, its hue and colourfulness kept."""

    target = _turned_luminance(luminance(colour), luminance(light), luminance(dark))
    _, a, b = to_oklab(colour)
    low, high = 0.0, 1.0
    for _ in range(14):
        middle = (low + high) / 2.0
        if luminance(from_oklab((middle, a, b))) < target:
            low = middle
        else:
            high = middle
    return with_lightness(colour, (low + high) / 2.0)


def turned_lightness(lightness: float, light: str, dark: str) -> float:
    """An Oklab lightness (a tint's, an outline's), turned over as ``turned`` turns a colour."""

    target = _turned_luminance(lightness**3, luminance(light), luminance(dark))
    return round(max(target, 0.0) ** (1.0 / 3.0), 4)


def dark_page(page: Page) -> Page:
    """A page turned over: its own colour mirrored, every other turned about it, its words and
    lines made to read on it, and its shadow still a shadow (black)."""

    canvas = mirrored(page.canvas)
    colours = {
        item.name: turned(value, page.canvas, canvas)
        for item in fields(page)
        if isinstance(value := getattr(page, item.name), str) and item.name != "canvas"
    }
    colours["ink"] = with_contrast(colours["ink"], canvas, WORDS)
    colours["muted"] = with_contrast(colours["muted"], canvas, MUTED)
    for name in ("connector", "neutral_stroke", "residual"):
        if name in colours:
            colours[name] = with_contrast(colours[name], canvas, ACCENT)
    colours["shadow"] = "#000000"
    return replace(page, canvas=canvas, **colours)


def _dark_tones(theme: Theme, page: Page) -> ToneRule:
    """The rule a dark version paints its tones by: its theme's, at its lightnesses turned over
    (a tint's fill and outline), its outline's colour turned over (a solid fill's)."""

    from flexo.themes import tone_rule

    settings = dict(getattr(theme.tones, "settings", None) or {})
    if not settings:
        return theme.tones
    for name in ("fill_lightness", "stroke_lightness"):
        if name in settings:
            settings[name] = turned_lightness(float(settings[name]), theme.page.canvas, page.canvas)
    if isinstance(settings.get("stroke"), str):
        stroke = settings["stroke"]
        ink = stroke.lower() == theme.page.ink.lower()
        settings["stroke"] = page.ink if ink else turned(stroke, theme.page.canvas, page.canvas)
    return tone_rule(settings)


def dark_version(theme: Theme, name: str | None = None) -> Theme:
    """The dark version of ``theme`` (named ``name``, else the theme's name and ``-dark``)."""

    from flexo.themes import Theme

    made = name or f"{theme.name}{SUFFIX}"
    page = dark_page(theme.page)
    palette = tuple(
        with_contrast(turned(colour, theme.page.canvas, page.canvas), page.canvas, ACCENT)
        for colour in theme.palette
    )
    if curated(theme.palette):
        # (Its colours in the order they were written, as the theme's were.)
        palette = Written(palette)
    return Theme(
        made,
        f"{theme.description} On a dark page.",
        replace(theme.style, name=made),
        page,
        palette,
        _dark_tones(theme, page),
        fixed_palette=theme.fixed_palette,
    )


def has_dark_version(theme: Theme) -> bool:
    """Whether a theme is one to turn over: one on a light page."""

    return not is_dark(theme.page.canvas) and not theme.name.endswith(SUFFIX)
