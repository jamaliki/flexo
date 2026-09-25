"""Colour maths for palettes: Oklab mixing, WCAG contrast, and ordering.

Ported from labviz so a figure and the plots beside it derive their colours the
same way: lightness edits and interpolation happen in Oklab, where equal steps
look equal, and every ink is checked against the page it sits on.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from functools import cache
from importlib import resources

_HEX = frozenset("0123456789abcdef")


def to_rgb(colour: str) -> tuple[float, float, float]:
    text = colour.strip().lower()
    if len(text) == 4 and text.startswith("#"):
        text = "#" + "".join(digit * 2 for digit in text[1:])
    if len(text) != 7 or not text.startswith("#") or not _HEX.issuperset(text[1:]):
        raise ValueError(f'invalid colour "{colour}"; expected "#rgb" or "#rrggbb"')
    return tuple(int(text[index : index + 2], 16) / 255.0 for index in (1, 3, 5))  # type: ignore[return-value]


def to_hex(rgb: Sequence[float]) -> str:
    return "#" + "".join(f"{round(min(1.0, max(0.0, channel)) * 255):02x}" for channel in rgb)


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _gamma(channel: float) -> float:
    channel = min(1.0, max(0.0, channel))
    return 12.92 * channel if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055


def to_oklab(colour: str) -> tuple[float, float, float]:
    r, g, b = (_linear(channel) for channel in to_rgb(colour))
    long = math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    medium = math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    short = math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (
        0.2104542553 * long + 0.7936177850 * medium - 0.0040720468 * short,
        1.9779984951 * long - 2.4285922050 * medium + 0.4505937099 * short,
        0.0259040371 * long + 0.7827717662 * medium - 0.8086757660 * short,
    )


def from_oklab(lab: Sequence[float]) -> str:
    lightness, a, b = lab
    long = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    medium = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    short = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return to_hex(
        (
            _gamma(4.0767416621 * long - 3.3077115913 * medium + 0.2309699292 * short),
            _gamma(-1.2684380046 * long + 2.6097574011 * medium - 0.3413193965 * short),
            _gamma(-0.0041960863 * long - 0.7034186147 * medium + 1.7076147010 * short),
        )
    )


def luminance(colour: str) -> float:
    r, g, b = (_linear(channel) for channel in to_rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(first: str, second: str) -> float:
    """WCAG contrast ratio between two colours, 1 to 21."""

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def is_dark(colour: str) -> bool:
    return luminance(colour) < 0.2


def mix(first: str, second: str, amount: float) -> str:
    """``first`` moved ``amount`` of the way to ``second``, in Oklab."""

    start, end = to_oklab(first), to_oklab(second)
    return from_oklab(tuple(a + (b - a) * amount for a, b in zip(start, end, strict=True)))


def chroma(colour: str) -> float:
    _, a, b = to_oklab(colour)
    return math.hypot(a, b)


def with_lightness(colour: str, lightness: float, max_chroma: float | None = None) -> str:
    """``colour`` at Oklab ``lightness``, hue kept, chroma capped at ``max_chroma``.

    Setting every tone's fill to one lightness is what makes a set of tints read
    as a set: mixing each toward the page by the same amount leaves a pale
    palette colour nearly white and a dark one muddy.
    """

    _, a, b = to_oklab(colour)
    current = math.hypot(a, b)
    if max_chroma is not None and current > max_chroma > 0.0:
        a, b = a * max_chroma / current, b * max_chroma / current
    # Pull chroma in until the colour is inside the sRGB gamut at this lightness.
    for _ in range(40):
        candidate = (lightness, a, b)
        if _in_gamut(candidate):
            break
        a, b = a * 0.92, b * 0.92
    return from_oklab((lightness, a, b))


def _in_gamut(lab: Sequence[float]) -> bool:
    lightness, a, b = lab
    long = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    medium = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    short = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    channels = (
        4.0767416621 * long - 3.3077115913 * medium + 0.2309699292 * short,
        -1.2684380046 * long + 2.6097574011 * medium - 0.3413193965 * short,
        -0.0041960863 * long - 0.7034186147 * medium + 1.7076147010 * short,
    )
    return all(-1e-4 <= channel <= 1.0001 for channel in channels)


def hue_distance(first: str, second: str) -> float:
    """How different two colours look once lightness is set aside (mostly)."""

    l1, a1, b1 = to_oklab(first)
    l2, a2, b2 = to_oklab(second)
    return math.hypot(a1 - a2, b1 - b2) + 0.25 * abs(l1 - l2)


def with_contrast(colour: str, background: str, ratio: float) -> str:
    """``colour`` with its Oklab lightness moved away from ``background`` until
    their contrast reaches ``ratio``. Hue and chroma are kept."""

    lightness, a, b = to_oklab(colour)
    step = 0.02 if is_dark(background) else -0.02
    result = to_hex(to_rgb(colour))
    for _ in range(50):
        if contrast(result, background) >= ratio:
            break
        lightness += step
        result = from_oklab((lightness, a, b))
    return result


def order_for_contrast(colours: Sequence[str], background: str) -> list[str]:
    """Colours ordered so each next one is the farthest from those already taken.

    The first is the one with the highest contrast on the page; the first two are
    then the most distinct pair, the first three the most distinct triple, and so
    on -- which is the order categories should take colours in, since most
    figures use only the first few.
    """

    rest = list(dict.fromkeys(colours))
    if not rest:
        return []
    first = max(rest, key=lambda colour: contrast(colour, background))
    order = [first]
    rest.remove(first)
    while rest:
        following = max(
            rest, key=lambda colour: min(hue_distance(colour, taken) for taken in order)
        )
        order.append(following)
        rest.remove(following)
    return order


EXTRA_PALETTES = {
    "Flexo": ("#3f7fc0", "#e08a2e", "#4f9a55", "#7a68c2", "#d0607a", "#a9a232"),
    "Okabe-Ito": ("#0072b2", "#e69f00", "#009e73", "#cc79a7", "#56b4e9", "#d55e00", "#f0e442"),
    "Tableau": ("#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948", "#b07aa1"),
}
"""Palettes that are not design-corner's but that figures keep asking for.

``Flexo`` is the diagram default: six hues spaced round the wheel, as the
original Transformer figure paints attention, add-norm, feed-forward, embedding,
linear and softmax. Okabe-Ito is safe for every common colour-vision deficiency.
"""


CURATED_PALETTES = frozenset(EXTRA_PALETTES)
"""Palettes whose order is the design: taken as written, not re-sorted for contrast."""


def curated(colours: Sequence[str]) -> bool:
    """Whether ``colours`` is one of the curated palettes, to be used in its own order."""

    wanted = tuple(colour.lower() for colour in colours)
    return any(wanted == palette for palette in EXTRA_PALETTES.values())


@cache
def design_palettes() -> dict[str, tuple[str, ...]]:
    """The named five-colour palettes shared with labviz and design-corner."""

    text = resources.files("flexo.resources").joinpath("palettes.json").read_text("utf-8")
    named = {
        name: tuple(colour.lower() for colour in colours)
        for name, colours in json.loads(text).items()
    }
    named.update(EXTRA_PALETTES)
    return named


def palette_colours(name: str) -> tuple[str, ...] | None:
    """A named palette's colours, matched case-insensitively, or ``None``."""

    folded = name.strip().casefold()
    for key, colours in design_palettes().items():
        if key.casefold() == folded:
            return colours
    return None
