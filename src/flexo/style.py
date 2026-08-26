"""Geometry-affecting layout styles and paint-only palettes."""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Literal

from flexo.diagnostics import Diagnostic, FlexoError
from flexo.units import CellSpan, Extent, Length, mm, pt

_PT_0_8 = pt(0.8)
_PT_0_9 = pt(0.9)
_PT_1_5 = pt(1.5)
_PT_2 = pt(2.0)
_PT_2_5 = pt(2.5)
_PT_3 = pt(3.0)
_PT_3_5 = pt(3.5)
_PT_4 = pt(4.0)
_PT_5 = pt(5.0)
_PT_6 = pt(6.0)
_PT_7 = pt(7.0)
_PT_8 = pt(8.0)
_PT_8_5 = pt(8.5)
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
    elbow_radius: Length = _PT_6
    arrow_length: Length = _PT_4
    arrow_width: Length = _PT_3_5
    connector_standoff: Length = _PT_3
    """Air between a node boundary and connector ink, at both ends of a connector.

    The painted shaft starts this far past its source port and the arrowhead
    *tip* stops this far short of its target port. Ink only: routing centerlines
    stay port-to-port, so this token moves no route, lane, or label. Zero
    reproduces butt-jointed connectors exactly.
    """
    route_clearance: Length = _PT_5
    caption_clearance: Length = _PT_3
    """Air a route leaves around a caption -- text with no boundary of its own.

    Smaller than ``route_clearance`` on purpose: a caption is thin ink, and
    charging it a full component's clearance would let a stray word close a
    corridor that the component it names leaves open.
    """
    route_boundary_clearance: Length = _PT_8
    route_lane_spacing: Length = _PT_4
    port_spacing: Length = _PT_6
    bend_penalty: float = 14.0
    connector_hops: bool = True
    """Whether a shaft that crosses another bridges it with a hop arc (R34).

    On by default, and opt-out rather than opt-in: an author should get a
    legible figure without asking for one. A figure that wants the plain
    crossing back -- because it is being traced by hand, or because its house
    style forbids bridges -- compiles under
    ``style.with_updates(connector_hops=False)``, which restores the
    ``routing.connector.crossing`` warning for every crossing it disables.
    """
    hop_scale: float = 2.5
    """How many connector stroke widths wide the radius of one bridge arc is."""
    junction_dots: Literal["auto", "always", "never"] = "auto"
    widths: tuple[tuple[str, Length], ...] = _PUBLICATION_WIDTHS
    vector_cell: Length = _PT_8_5
    """Side of one square cell in a vector glyph (R19)."""
    vector_cell_gap: Length = _PT_1_5
    """Gap between stacked cells of one vector column."""
    vector_column_gap: Length = _PT_3
    """Gap between the side-by-side stacks of a multi-column vector."""
    vector_cell_radius: Length = _PT_1_5
    """Corner radius of a vector cell; cells read as rounded squares, not dots."""
    vector_label_gap: Length = _PT_3
    """Distance from the bottom cell to the label a ``vector()`` composite puts below it."""
    motif_label_gap: Length = _PT_3_5
    """Air between a component's label band and the motif drawn below it.

    The counterpart of ``vector_label_gap`` inside a single component: a molecule
    illustration, a token strip or a cell grid starts this far under the last
    line of the words that name it.
    """
    shadow_offset: Length = _PT_2_5
    """How far down *and to the right* of its box a ``shadow=True`` shadow sits.

    The figure is lit from the top left, so a shadow belongs along the bottom and
    right edges and nowhere else. That holds only while the offset is at least
    ``shadow_spread`` -- a shorter one lets the widest layer ring the top and
    left edges into a halo -- so ``soft_shadow`` raises a smaller value to the
    spread rather than drawing one.
    """
    shadow_spread: Length = _PT_2
    """How far past the offset box the faintest edge of a drop shadow reaches.

    The stand-in for a blur radius: the shadow is built from nested rounded
    rectangles rather than from an SVG filter (Inkscape rasterizes filtered
    regions on PDF export), so this is the width of the graded band, not a
    Gaussian sigma.
    """
    shadow_opacity: float = 0.18
    """Opacity of a drop shadow directly under its box, where every layer overlaps.

    Subtle on purpose. A shadow's job is to lift a container off the page by a
    hair; anything a reader notices as a shadow is already too strong for print.
    """

    @property
    def arrival_clearance(self) -> Length:
        """Air a route must leave at the end it points into.

        An arrowhead and the elbow that turns into it need more room than a
        plain approach, so a run that turns later than this cannot draw its
        arrow. The layout reserves it, the router escapes to it, the nudger
        protects it, and lint checks it -- all from this one number.
        """

        return Length(
            max(
                self.route_clearance.points,
                2.0 * self.arrow_length.points + self.elbow_radius.points,
            )
        )

    @property
    def hop_radius(self) -> Length:
        """The radius of one bridge arc where a connector hops another (R34).

        Stroke width sets the scale -- a bump proportional to the ink it
        interrupts reads as one wire passing over another rather than as a
        wobble -- and clearance sets the ceiling: half the minimum separation
        two parallel tracks are allowed, so an arc can never reach out of its
        own lane into a neighbouring one.
        """

        return Length(
            min(
                self.hop_scale * self.connector_width.points,
                self.port_spacing.points / 2.0,
            )
        )

    def resolve_width(self, value: str | Length | float) -> Length:
        if isinstance(value, str):
            presets = dict(self.widths)
            if value in presets:
                return presets[value]
        return Length.parse(value)

    def resolve_extent(self, value: Extent) -> Length:
        """Turn a declared node size into a physical length under this style."""

        if isinstance(value, CellSpan):
            return vector_stack_height(self, value.cells)
        return value

    def with_updates(self, **changes: object) -> LayoutStyle:
        return replace(self, **changes)


def vector_stack_height(style: LayoutStyle, cells: int = 3) -> Length:
    """The height of a vertical stack of ``cells`` vector cells under ``style``.

    A box whose side ports must line up with a vector's is exactly this tall, so
    the arithmetic -- ``cells`` cell sides plus the gaps between them -- belongs
    to the tokens rather than to every figure that aligns against a stack.
    """

    if cells < 1:
        raise ValueError("a vector stack needs at least one cell")
    return Length(cells * style.vector_cell.points + (cells - 1) * style.vector_cell_gap.points)


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


RAMP_ROLES = (
    "ramp-node",
    "ramp-embedding",
    "ramp-q",
    "ramp-kv",
    "ramp-attended",
    "ramp-output",
)
"""Paint roles a ``vector`` component may name through its ``ramp`` property.

One role carries one ramp: the cells of a stack all paint with that role and
differ only in ``fill-opacity``, so a ramp survives ``flexo retheme`` (which
rewrites paint by role) and stays geometrically identical in every palette.
Every palette must define every role, and the grayscale palette separates them
by lightness so the ramps remain distinguishable without hue.
"""


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
        "shadow": "#332e3b",
        "ramp-node": "#4a6cb0",
        "ramp-embedding": "#2f8f7d",
        "ramp-q": "#8a5bb5",
        "ramp-kv": "#c3792c",
        "ramp-attended": "#b04a6f",
        "ramp-output": "#5d8b38",
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
        # Okabe-Ito hues: the pairs an author is most likely to place side by
        # side (q / kv / attended) sit at opposite ends of the set.
        "ramp-node": "#0072b2",
        "ramp-embedding": "#009e73",
        "ramp-q": "#cc79a7",
        "ramp-kv": "#e69f00",
        "ramp-attended": "#56b4e9",
        "ramp-output": "#d55e00",
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
        "shadow": "#2b2b2b",
        # Six evenly spaced lightness steps: hueless ramps stay tellable apart.
        "ramp-node": "#0f0f0f",
        "ramp-embedding": "#333333",
        "ramp-q": "#575757",
        "ramp-kv": "#7b7b7b",
        "ramp-attended": "#9f9f9f",
        "ramp-output": "#c3c3c3",
    },
)

PALETTES = {
    palette.name: palette
    for palette in (DEFAULT_PALETTE, COLOR_VISION_SAFE_PALETTE, GRAYSCALE_PALETTE)
}

STYLES = {"paper": LayoutStyle()}

_HEX_DIGITS = frozenset("0123456789abcdef")
_TINT_LIMIT = 0.6
_SHADE_LIMIT = 0.35
"""How far the ends of a shade ramp travel from the base colour.

The light end mixes further than the dark end: a tint stays legible against the
canvas long after an equal shade has gone to mud.
"""


def _parse_hex(colour: object) -> tuple[int, int, int]:
    if not isinstance(colour, str):
        raise ValueError(f'invalid colour {colour!r}; expected a hex string like "#4a6cb0"')
    text = colour.strip().lower()
    if len(text) == 4 and text.startswith("#"):
        text = "#" + "".join(digit * 2 for digit in text[1:])
    if len(text) != 7 or not text.startswith("#") or not _HEX_DIGITS.issuperset(text[1:]):
        raise ValueError(f'invalid colour "{colour}"; expected "#rgb" or "#rrggbb"')
    return tuple(int(text[index : index + 2], 16) for index in (1, 3, 5))  # type: ignore[return-value]


def _format_hex(channels: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02x}" for channel in channels)


PAINT_PARTS = ("fill", "stroke", "label")
"""The parts of one node an author may paint literally instead of by role.

``fill`` and ``stroke`` are the component body; ``label`` is its text. Each
travels as its own ``paint-<part>`` scalar property, because a node property may
hold a scalar and never a mapping.
"""

PAINT_PROPERTY_PREFIX = "paint-"


def normalize_colour(colour: str) -> str:
    """One authored colour as ``#rrggbb``, rejecting anything that is not hex.

    Normalizing at the point of authoring is what stops ``#abc`` and ``#aabbcc``
    from serializing as two different figures.
    """

    return _format_hex(_parse_hex(colour))


def _mix(channels: tuple[int, int, int], target: int, factor: float) -> str:
    return _format_hex(
        tuple(round(channel + (target - channel) * factor) for channel in channels)  # type: ignore[arg-type]
    )


def _check_limit(name: str, value: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number between 0.0 and 1.0, not {value!r}")
    if not 0.0 <= value < 1.0:
        raise ValueError(f"{name} must be at least 0.0 and below 1.0, not {value}")
    return float(value)


def shade_ramp(
    base: str,
    count: int,
    *,
    tint: float = _TINT_LIMIT,
    shade: float = _SHADE_LIMIT,
) -> tuple[str, ...]:
    """``count`` opaque shades of ``base``, lightest first, base in the middle.

    Unlike a palette ramp role -- one colour graded by ``fill-opacity`` -- every
    step here is a literal colour, so the cells stay opaque and nothing behind
    them shows through. An odd ``count`` puts ``base`` itself at the centre.

    ``tint`` and ``shade`` are how far the two ends travel from ``base``, each
    at least 0.0 and below 1.0 (1.0 would end at pure white or pure black, which
    is no longer a shade of anything). The defaults are the module's own limits;
    lowering ``tint`` to about 0.35 keeps the light cells saturated rather than
    washed towards the canvas, which is what a dark panel usually wants.
    """

    if count < 1:
        raise ValueError(f"a shade ramp needs at least one shade, not {count}")
    tint_limit = _check_limit("tint", tint)
    shade_limit = _check_limit("shade", shade)
    channels = _parse_hex(base)
    if count == 1:
        return (_format_hex(channels),)
    shades = []
    for index in range(count):
        position = index / (count - 1)
        if position < 0.5:
            shades.append(_mix(channels, 255, (0.5 - position) * 2.0 * tint_limit))
        elif position > 0.5:
            shades.append(_mix(channels, 0, (position - 0.5) * 2.0 * shade_limit))
        else:
            shades.append(_format_hex(channels))
    return tuple(shades)


_MULTIPLICATION_SIGN = "\u00d7"
"""An author may spell a topology with the typographic sign instead of ``x``."""


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_topology(topology: int | str | tuple[int, int]) -> tuple[int, int]:
    message = f'invalid vector topology {topology!r}; use an int, "CxR", or (C, R)'
    if _is_count(topology):
        columns, cells = 1, int(topology)  # type: ignore[arg-type]
    elif isinstance(topology, str):
        parts = topology.replace(_MULTIPLICATION_SIGN, "x").lower().split("x")
        if len(parts) != 2 or not all(part.strip().lstrip("-").isdigit() for part in parts):
            raise ValueError(message)
        columns, cells = (int(part) for part in parts)
    elif isinstance(topology, tuple) and len(topology) == 2 and all(map(_is_count, topology)):
        columns, cells = topology
    else:
        raise ValueError(message)
    if columns < 1 or cells < 1:
        raise ValueError(
            f"a vector preset needs at least one column and one row, not {columns}x{cells}"
        )
    return columns, cells


def _column_bases(base: str | tuple[str, ...], columns: int) -> tuple[str, ...]:
    bases = base if isinstance(base, tuple) else (base,)
    if len(bases) == 1:
        bases = bases * columns
    if len(bases) != columns:
        raise ValueError(
            f"a {columns}-column vector preset takes 1 or {columns} base colours, "
            f"not {len(bases)}"
        )
    for colour in bases:
        _parse_hex(colour)
    return bases


SHADE_ORDERS = ("ramp", "shuffled")
"""How a preset arranges one column's shades down the stack.

``"ramp"`` keeps them light-to-dark, so the glyph reads as a gradient.
``"shuffled"`` permutes them, so it reads as a feature *vector*: cells whose
values have no order, which is what a real activation looks like. ``"shuffled"``
is the default for that reason -- the gradient is the special case, and it is
asked for by name.
"""

_SHUFFLE_ATTEMPTS = 8
"""How many candidate permutations a column may draw before the fallback.

A shuffled glyph that came back in ramp order would silently lie about what it
depicts, so an identity draw is rejected and the next candidate from the same
stream is taken instead. Eight draws make an accidental run of identities
vanishingly unlikely even for two cells; the rotation after them keeps the
function total and deterministic rather than looping on chance.
"""


def _column_rng(seed: int, column: int) -> random.Random:
    """The stream one column of one preset shuffles with.

    Seeding per column is what stops a multi-column glyph from repeating the
    same permutation side by side. The seed is text, not a tuple, because
    ``random.Random`` derives an integer from a string by digest -- identical in
    every process and on every platform, which is what "same preset, same
    figure, forever" requires.
    """

    return random.Random(f"flexo.vector-preset:{seed}:{column}")


def _shuffled_shades(shades: tuple[str, ...], rng: random.Random) -> tuple[str, ...]:
    """One Fisher--Yates pass over ``shades``, never returning them in order.

    Identity is compared by *value*: two equal shades in ramp positions would
    read as a ramp however they were permuted.
    """

    if len(shades) < 2:
        return shades
    for _ in range(_SHUFFLE_ATTEMPTS):
        candidate = list(shades)
        for index in range(len(candidate) - 1, 0, -1):
            swap = rng.randrange(index + 1)
            candidate[index], candidate[swap] = candidate[swap], candidate[index]
        if tuple(candidate) != shades:
            return tuple(candidate)
    return shades[-1:] + shades[:-1]


@dataclass(frozen=True, slots=True)
class VectorPreset:
    """An author's own colour and topology for a ``vector()`` glyph.

    Topology reads columns first: ``"1x3"`` is one column of three stacked
    cells, ``"3x3"`` a three-by-three grid. It may also be an int (that many
    rows in one column), a ``(columns, rows)`` tuple, or a string spelled with
    whitespace or a multiplication sign. ``base`` is one hex colour for every column, or one per
    column; each column derives its own light-to-dark shades from it.

    ``order`` is how each column arranges its shades, and it defaults to
    ``"shuffled"``: the shades are permuted so the glyph reads as a feature
    vector rather than a gradient, deterministically from ``seed`` -- the same
    preset always yields the same figure, and different columns of one glyph get
    different permutations. A ramp claims the cells are *ordered*, which is a
    claim about the data almost no activation supports, so an author who wants
    the gradient asks for it with ``order="ramp"``.

    ``tint`` and ``shade`` are how far the light and dark ends of each column
    travel from its base colour (see ``shade_ramp``).

    Preset colour is literal paint, not a role, so ``flexo retheme`` leaves it
    alone. A figure that must survive retheming names a ramp role instead.
    """

    base: str | tuple[str, ...]
    topology: int | str | tuple[int, int]
    order: Literal["ramp", "shuffled"] = "shuffled"
    seed: int = 0
    tint: float = _TINT_LIMIT
    shade: float = _SHADE_LIMIT

    def __post_init__(self) -> None:
        _column_bases(self.base, _parse_topology(self.topology)[0])
        if self.order not in SHADE_ORDERS:
            raise ValueError(
                f'unknown vector shade order "{self.order}"; '
                f"valid orders: {', '.join(SHADE_ORDERS)}"
            )
        _check_limit("tint", self.tint)
        _check_limit("shade", self.shade)

    @property
    def columns(self) -> int:
        return _parse_topology(self.topology)[0]

    @property
    def cells(self) -> int:
        return _parse_topology(self.topology)[1]

    def column_shades(self) -> tuple[tuple[str, ...], ...]:
        columns, cells = _parse_topology(self.topology)
        ramps = tuple(
            shade_ramp(colour, cells, tint=self.tint, shade=self.shade)
            for colour in _column_bases(self.base, columns)
        )
        if self.order == "ramp":
            return ramps
        return tuple(
            _shuffled_shades(ramp, _column_rng(self.seed, column))
            for column, ramp in enumerate(ramps)
        )

    def encode(self) -> str:
        """The shades as one scalar: columns split on ``;``, cells on ``,``.

        A node property may only hold a scalar, so the grid travels as text
        through the interchange format rather than as a nested structure.
        """

        return ";".join(",".join(column) for column in self.column_shades())
