"""Themes: one name for a whole look -- type, line work, and colour.

A theme is what an author picks instead of tuning forty tokens. It bundles a
``LayoutStyle`` (the geometry: type, stroke weights, corners, arrowheads, how a
module draws its boundary) with the rules that turn any five-colour palette into
paint (how tinted a filled box is, how dark its outline, what the page is). So
``theme="dark"`` and ``palette="Cobalt Citrus"`` compose: every theme accepts
every palette.

The themes follow the modes of labviz, the group's plotting style, so a
diagram and the plots beside it read as one figure: ``paper``, ``slides``,
``dark``, ``archive``, ``print``, ``economist``, ``rams``, ``swiss``,
``bauhaus``, and ``midcentury`` -- plus ``tikz``, the look of a figure drawn in
TikZ for a LaTeX paper, set in Latin Modern.

Colour is allocated by *tone*. A tone is a name for a kind of thing --
``attention``, ``norm``, ``mlp`` by default, or any name an author writes with
``tone=`` -- and every tone in a figure takes the next colour of the palette in
contrast order, so the first two tones a figure uses are always its two most
distinct colours, and one kind of block is one colour everywhere it appears.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from flexo.colour import (
    chroma,
    contrast,
    curated,
    is_dark,
    mix,
    order_for_contrast,
    palette_colours,
    with_contrast,
    with_lightness,
)
from flexo.conventions import Conventions
from flexo.diagnostics import Diagnostic, FlexoError
from flexo.style import (
    PALETTES,
    RAMP_ROLES,
    STYLES,
    LayoutStyle,
    Palette,
    TypographyStyle,
)
from flexo.units import Length, pt

if TYPE_CHECKING:  # pragma: no cover
    from flexo.ir.semantic import FigureSpec

TONE_COUNT = 8
"""How many ``tone-N`` roles every palette defines. Tones past this reuse colours."""

DEFAULT_PALETTE_NAME = "default"
"""The palette name meaning "whatever the theme's own colours are"."""

type ToneRule = Callable[[tuple[str, ...], "Page"], list[tuple[str, str, str]]]


@dataclass(frozen=True, slots=True)
class Page:
    """The neutral paint of a theme: everything that is not a tone."""

    canvas: str = "#ffffff"
    ink: str = "#242126"
    muted: str = "#6b6570"
    connector: str = "#4a4550"
    container_fill: str = "#f6f5f8"
    container_stroke: str = "#d9d5de"
    neutral_fill: str = "#f1eff4"
    neutral_stroke: str = "#76707d"
    inset_fill: str = "#f3f5f6"
    shadow: str = "#2c2830"
    inset_stroke: str | None = None
    """Border of an illustration inset; ``None`` is a quiet mix of ink into the page."""
    residual: str | None = None
    """``None`` takes the palette's highest-contrast colour."""


@dataclass(frozen=True, slots=True)
class Theme:
    """A named look: geometry and type, the page, and how tones are painted."""

    name: str
    description: str
    style: LayoutStyle
    page: Page
    palette: tuple[str, ...]
    """The theme's own colours, used when the figure names no palette."""
    tones: ToneRule = field(repr=False, default=None)  # type: ignore[assignment]
    fixed_palette: bool = False
    """A theme whose colours *are* its identity (Swiss red, Bauhaus primaries)
    ignores a named palette for its tones."""

    def paint(self, palette: str | Sequence[str] | None = None) -> Palette:
        """The paint for this theme under ``palette`` (a name or hex colours)."""

        colours = self.palette if self.fixed_palette else _palette_argument(palette, self.palette)
        return _derive_palette(self, colours, _palette_label(self, palette))


def _palette_label(theme: Theme, palette: str | Sequence[str] | None) -> str:
    if palette is None or palette == DEFAULT_PALETTE_NAME:
        return theme.name
    if isinstance(palette, str):
        return f"{theme.name}/{palette}"
    return f"{theme.name}/custom"


def _palette_argument(
    palette: str | Sequence[str] | None, fallback: tuple[str, ...]
) -> tuple[str, ...]:
    if palette is None or palette == DEFAULT_PALETTE_NAME:
        return fallback
    if isinstance(palette, str):
        colours = parse_palette(palette)
        if colours is None:
            raise FlexoError(unknown_palette(palette))
        return colours
    return tuple(str(colour).lower() for colour in palette)


def parse_palette(value: str) -> tuple[str, ...] | None:
    """A palette name or ``"#rrggbb,#rrggbb,..."`` as colours, or ``None``."""

    text = value.strip()
    if text.startswith("#"):
        colours = tuple(part.strip().lower() for part in text.split(",") if part.strip())
        return colours or None
    named = palette_colours(text)
    if named is not None:
        return named
    legacy = PALETTES.get(text)
    if legacy is not None:
        return tuple(legacy.get(role) for role in RAMP_ROLES)
    return None


def unknown_palette(name: str) -> Diagnostic:
    from flexo.colour import design_palettes

    return Diagnostic(
        "palette.unknown",
        f'Unknown palette "{name}".',
        hint=(
            "Use a named palette ("
            + ", ".join(sorted(design_palettes()))
            + "), a list of hex colours, or 'default' for the theme's own."
        ),
    )


# -- tone rules ----------------------------------------------------------------------


def _usable(colours: tuple[str, ...], page: Page) -> list[str]:
    """Palette colours ordered for contrast, near-page colours moved last.

    A curated palette keeps the order it was written in: its order is the design.
    """

    ordered = list(colours) if curated(colours) else order_for_contrast(colours, page.canvas)
    visible = [colour for colour in ordered if contrast(colour, page.canvas) >= 1.35]
    faint = [colour for colour in ordered if colour not in visible]
    return (visible + faint) or [page.neutral_stroke]


def _cycle(colours: list[str], count: int = TONE_COUNT) -> list[tuple[str, int]]:
    """``count`` colours, repeating the palette with a generation counter."""

    return [(colours[index % len(colours)], index // len(colours)) for index in range(count)]


def tinted(
    fill_lightness: float = 0.935,
    fill_chroma: float = 0.045,
    stroke_lightness: float = 0.47,
    stroke_chroma: float = 0.12,
) -> ToneRule:
    """Pale fill of the tone and an outline of the same hue, each at one lightness.

    Every tone's fill sits at the same Oklab lightness and every outline at
    another, so a set of tints reads as a set whatever the palette: a pale sand
    and a deep navy come out as equally quiet boxes with equally firm edges,
    told apart by hue alone. On a dark page the two lightnesses swap ends.
    """

    def rule(colours: tuple[str, ...], page: Page) -> list[tuple[str, str, str]]:
        dark = is_dark(page.canvas)
        result = []
        for colour, generation in _cycle(_usable(colours, page)):
            shift = 0.025 * generation
            fill = with_lightness(
                colour,
                fill_lightness - shift if not dark else fill_lightness + shift,
                fill_chroma,
            )
            stroke = with_lightness(colour, stroke_lightness, stroke_chroma)
            stroke = with_contrast(stroke, page.canvas, 3.0)
            result.append((fill, stroke, page.ink))
        return result

    return rule


def solid(stroke: str | None = None) -> ToneRule:
    """The tone itself as the fill, labels in whichever of ink or page reads."""

    def rule(colours: tuple[str, ...], page: Page) -> list[tuple[str, str, str]]:
        result = []
        for colour, generation in _cycle(list(colours) or [page.neutral_stroke]):
            fill = mix(colour, page.canvas, 0.25 * generation) if generation else colour
            on_ink = contrast(fill, page.ink) >= contrast(fill, page.canvas)
            label = page.ink if on_ink else page.canvas
            result.append((fill, stroke or page.ink, label))
        return result

    return rule


def accent_then_grey(fill_mix: float = 0.82) -> ToneRule:
    """One colour for the first tone, greys for the rest (archive, rams)."""

    def rule(colours: tuple[str, ...], page: Page) -> list[tuple[str, str, str]]:
        first = max(colours, key=chroma) if colours else page.neutral_stroke
        first = with_contrast(first, page.canvas, 3.0)
        result = [(mix(first, page.canvas, fill_mix), first, page.ink)]
        greys = (0.93, 0.86, 0.78, 0.97, 0.9, 0.82, 0.74)
        for amount in greys[: TONE_COUNT - 1]:
            result.append((mix(page.ink, page.canvas, amount), page.neutral_stroke, page.ink))
        return result

    return rule


def greys() -> ToneRule:
    """Hueless tones separated by lightness (the Bertin print theme)."""

    def rule(colours: tuple[str, ...], page: Page) -> list[tuple[str, str, str]]:
        steps = (0.9, 0.72, 0.97, 0.82, 0.62, 0.94, 0.78, 0.86)
        return [(mix(page.ink, page.canvas, amount), page.ink, page.ink) for amount in steps]

    return rule


# -- palette derivation --------------------------------------------------------------


def _ramps(colours: tuple[str, ...], page: Page) -> dict[str, str]:
    usable = [with_contrast(colour, page.canvas, 2.2) for colour in _usable(colours, page)]
    return {
        role: usable[index % len(usable)] if index < len(usable) else mix(
            usable[index % len(usable)], page.ink, 0.3
        )
        for index, role in enumerate(RAMP_ROLES)
    }


def _derive_palette(theme: Theme, colours: tuple[str, ...], label: str) -> Palette:
    page = theme.page
    tones = theme.tones(colours, page)
    ordered = _usable(colours, page)
    residual = page.residual or with_contrast(ordered[0], page.canvas, 3.5)
    motifs = [
        stroke if contrast(stroke, fill) >= 2.0 else ink for fill, stroke, ink in tones
    ]
    paints = {
        "canvas": page.canvas,
        "ink": page.ink,
        "muted-ink": page.muted,
        "container-fill": page.container_fill,
        "container-stroke": page.container_stroke,
        "block-fill": page.neutral_fill,
        "block-stroke": page.neutral_stroke,
        "block-motif": page.neutral_stroke,
        "accent-fill": tones[0][0],
        "accent-stroke": tones[0][1],
        "accent-motif": motifs[0],
        "warm-fill": tones[1][0],
        "warm-stroke": tones[1][1],
        "warm-motif": motifs[1],
        "inset-stroke": page.inset_stroke or mix(page.ink, page.canvas, 0.72),
        "connector": page.connector,
        "residual": residual,
        "grid": page.muted,
        "inset-fill": page.inset_fill,
        "shadow": page.shadow,
        **_ramps(colours, page),
    }
    for index, ((fill, stroke, ink), motif) in enumerate(zip(tones, motifs, strict=True), 1):
        paints[f"tone-{index}-fill"] = fill
        paints[f"tone-{index}-stroke"] = stroke
        paints[f"tone-{index}-ink"] = ink
        paints[f"tone-{index}-motif"] = motif
    return Palette(label, paints)


def with_tone_roles(palette: Palette) -> Palette:
    """A legacy palette with ``tone-N`` roles derived from the roles it has.

    The three palettes Flexo shipped before themes name ``block``, ``accent``
    and ``warm`` but no tones; their tones are those three and then their ramp
    colours, tinted, so rendering and ``flexo retheme`` work with them unchanged.
    """

    if "tone-1-fill" in palette.paints and "tone-1-motif" in palette.paints:
        return palette
    canvas = palette.get("canvas", "#ffffff")
    pairs = [
        (palette.get("block-fill"), palette.get("block-stroke")),
        (palette.get("accent-fill"), palette.get("accent-stroke")),
        (palette.get("warm-fill"), palette.get("warm-stroke")),
    ] + [
        (mix(palette.get(role), canvas, 0.8), with_contrast(palette.get(role), canvas, 3.0))
        for role in RAMP_ROLES
    ]
    paints = dict(palette.paints)
    for family in ("block", "accent", "warm"):
        paints.setdefault(f"{family}-motif", palette.get(f"{family}-stroke"))
    paints.setdefault("inset-stroke", palette.get("container-stroke"))
    for index in range(TONE_COUNT):
        fill, stroke = pairs[index % len(pairs)]
        paints.setdefault(f"tone-{index + 1}-fill", fill)
        paints.setdefault(f"tone-{index + 1}-stroke", stroke)
        paints.setdefault(f"tone-{index + 1}-ink", palette.get("ink"))
        paints.setdefault(f"tone-{index + 1}-motif", paints[f"tone-{index + 1}-stroke"])
    return Palette(palette.name, paints, palette.tones)


# -- the themes ----------------------------------------------------------------------

_DEEP_SEA_HARVEST = palette_colours("Deep Sea Harvest") or ()
_FLEXO = palette_colours("Flexo") or ()

_BASE = LayoutStyle()

_FIGTREE = TypographyStyle(
    family="Figtree",
    size=pt(8.0),
    minimum_size=pt(7.0),
    line_height=1.2,
    label_weight=500,
    title_weight=700,
)
_HELVETICA = TypographyStyle(
    family="Liberation Sans",
    size=pt(7.5),
    minimum_size=pt(6.5),
    line_height=1.18,
    label_weight=400,
    title_weight=700,
)
_LATIN_MODERN = TypographyStyle(
    family="Latin Modern Roman",
    size=pt(8.5),
    minimum_size=pt(7.0),
    line_height=1.2,
    label_weight=400,
    title_weight=700,
    fallbacks=("STIX Two Text", "Times New Roman", "Noto Serif"),
    generic="serif",
)


def _style(name: str, **changes: object) -> LayoutStyle:
    defaults: dict[str, object] = {
        "name": name,
        "typography": _FIGTREE,
        "stroke_width": pt(0.75),
        "connector_width": pt(0.8),
        "corner_radius": pt(3.0),
        "arrow_shape": "stealth",
        "arrow_length": pt(4.6),
        "arrow_width": pt(3.8),
        "connector_standoff": pt(1.0),
        "container_stroke_width": pt(0.6),
        "motif_stroke_width": pt(0.7),
        "kind_tones": True,
    }
    defaults.update(changes)
    return replace(_BASE, **defaults)  # type: ignore[arg-type]


_SLIDE_WIDTHS = (
    ("single-column", Length(6.4 * 72.0)),
    ("double-column", Length(13.333 * 72.0)),
    ("presentation", Length(13.333 * 72.0)),
)
"""A slide is 13.33 x 7.5 in; a single column is half of it (labviz's ``halfslide``)."""

_PAPER_PAGE = Page()

THEMES: dict[str, Theme] = {}


def _register(theme: Theme) -> Theme:
    THEMES[theme.name] = theme
    return theme


_register(
    Theme(
        "paper",
        "Journal default: Figtree, tinted boxes with same-hue outlines, stealth arrows.",
        _style("paper"),
        _PAPER_PAGE,
        _FLEXO,
        tinted(),
    )
)
_register(
    Theme(
        "slides",
        "Paper at projection scale: larger type and heavier lines.",
        _style(
            "slides",
            typography=replace(_FIGTREE, size=pt(12.0), minimum_size=pt(10.0)),
            stroke_width=pt(1.2),
            connector_width=pt(1.4),
            corner_radius=pt(4.5),
            arrow_length=pt(7.0),
            arrow_width=pt(5.8),
            padding_x=pt(10.0),
            padding_y=pt(7.0),
            gap=pt(20.0),
            group_padding=pt(18.0),
            elbow_radius=pt(8.0),
            vector_cell=pt(12.0),
            vector_cell_gap=pt(2.0),
            vector_cell_radius=pt(2.0),
            container_stroke_width=pt(1.0),
            motif_stroke_width=pt(1.1),
            route_clearance=pt(7.0),
            route_lane_spacing=pt(6.0),
            port_spacing=pt(8.0),
            widths=_SLIDE_WIDTHS,
        ),
        _PAPER_PAGE,
        _FLEXO,
        tinted(),
    )
)
_register(
    Theme(
        "dark",
        "Slides on navy: dark tinted boxes, light outlines and type.",
        _style(
            "dark",
            typography=replace(_FIGTREE, size=pt(12.0), minimum_size=pt(10.0)),
            stroke_width=pt(1.2),
            connector_width=pt(1.4),
            corner_radius=pt(4.5),
            arrow_length=pt(7.0),
            arrow_width=pt(5.8),
            padding_x=pt(10.0),
            padding_y=pt(7.0),
            gap=pt(20.0),
            group_padding=pt(18.0),
            elbow_radius=pt(8.0),
            vector_cell=pt(12.0),
            vector_cell_gap=pt(2.0),
            vector_cell_radius=pt(2.0),
            container_stroke_width=pt(1.0),
            motif_stroke_width=pt(1.1),
            route_clearance=pt(7.0),
            route_lane_spacing=pt(6.0),
            port_spacing=pt(8.0),
            widths=_SLIDE_WIDTHS,
        ),
        Page(
            canvas="#0f172a",
            ink="#f2efe8",
            muted="#a8a49c",
            connector="#b8b4ac",
            container_fill="#16213a",
            container_stroke="#2a3654",
            neutral_fill="#1e293b",
            neutral_stroke="#8d96a8",
            inset_fill="#1a2438",
            shadow="#000000",
        ),
        _FLEXO,
        tinted(fill_lightness=0.3, fill_chroma=0.05, stroke_lightness=0.78),
    )
)
_register(
    Theme(
        "tikz",
        "A TikZ figure in a LaTeX paper: Latin Modern, hairline black strokes, "
        "10% tints, Stealth tips, dashed module boxes.",
        _style(
            "tikz",
            typography=_LATIN_MODERN,
            stroke_width=pt(0.5),
            connector_width=pt(0.5),
            corner_radius=pt(2.0),
            elbow_radius=pt(0.0),
            arrow_shape="stealth",
            arrow_length=pt(4.2),
            arrow_width=pt(3.2),
            connector_standoff=pt(0.5),
            container_style="dashed",
            container_radius=pt(3.0),
            container_stroke_width=pt(0.5),
            motif_stroke_width=pt(0.5),
        ),
        Page(
            ink="#000000",
            muted="#404040",
            connector="#000000",
            container_fill="#ffffff",
            container_stroke="#555555",
            neutral_fill="#ffffff",
            neutral_stroke="#000000",
            inset_fill="#ffffff",
            shadow="#000000",
            residual="#000000",
        ),
        ("#1f5fbf", "#c2362b", "#2f8f3a", "#d9901a", "#7a3fa0"),
        tinted(fill_lightness=0.955, fill_chroma=0.035, stroke_lightness=0.42),
    )
)
_register(
    Theme(
        "archive",
        "A 1970s technical report: cream page, Helvetica, hairlines, one accent, greys.",
        _style(
            "archive",
            typography=replace(_HELVETICA, title_transform="upper", tracking=0.0),
            stroke_width=pt(0.5),
            connector_width=pt(0.5),
            corner_radius=pt(0.0),
            elbow_radius=pt(0.0),
            arrow_shape="triangle",
            arrow_length=pt(4.0),
            arrow_width=pt(3.0),
            connector_standoff=pt(0.5),
            container_style="outline",
            container_radius=pt(0.0),
            container_stroke_width=pt(0.5),
            motif_stroke_width=pt(0.5),
        ),
        Page(
            canvas="#f7f5ee",
            ink="#1c1a17",
            muted="#6e6a62",
            connector="#1c1a17",
            container_fill="#f7f5ee",
            container_stroke="#1c1a17",
            neutral_fill="#ece8dc",
            neutral_stroke="#1c1a17",
            inset_fill="#efebe0",
            shadow="#1c1a17",
            residual="#1c1a17",
        ),
        _DEEP_SEA_HARVEST,
        accent_then_grey(0.8),
    )
)
_register(
    Theme(
        "print",
        "Bertin: ink only, tones told apart by lightness, never by hue.",
        _style(
            "print",
            typography=_HELVETICA,
            stroke_width=pt(0.6),
            connector_width=pt(0.7),
            corner_radius=pt(1.0),
            elbow_radius=pt(3.0),
            arrow_shape="triangle",
            container_style="outline",
            container_stroke_width=pt(0.5),
        ),
        Page(
            ink="#1a1a1a",
            muted="#555555",
            connector="#1a1a1a",
            container_fill="#ffffff",
            container_stroke="#1a1a1a",
            neutral_fill="#ffffff",
            neutral_stroke="#1a1a1a",
            inset_fill="#f2f2f2",
            shadow="#1a1a1a",
            residual="#1a1a1a",
        ),
        _DEEP_SEA_HARVEST,
        greys(),
        fixed_palette=True,
    )
)
_register(
    Theme(
        "economist",
        "News graphic: Helvetica, a red band over each module, crisp outlines.",
        _style(
            "economist",
            typography=_HELVETICA,
            stroke_width=pt(0.6),
            connector_width=pt(0.8),
            corner_radius=pt(0.0),
            elbow_radius=pt(3.0),
            arrow_shape="triangle",
            container_style="band",
            container_radius=pt(0.0),
        ),
        Page(
            ink="#121212",
            muted="#555555",
            connector="#333333",
            container_fill="#f2f2f2",
            container_stroke="#e3120b",
            inset_stroke="#b0b0b0",
            neutral_fill="#ffffff",
            neutral_stroke="#555555",
            inset_fill="#f7f7f7",
            shadow="#121212",
        ),
        _FLEXO,
        tinted(fill_lightness=0.93, fill_chroma=0.04),
    )
)
_register(
    Theme(
        "rams",
        "Dieter Rams: quiet greys, one signal colour, fine lines.",
        _style(
            "rams",
            typography=replace(_HELVETICA, label_weight=400, title_weight=700),
            stroke_width=pt(0.5),
            connector_width=pt(0.6),
            corner_radius=pt(2.0),
            elbow_radius=pt(4.0),
            arrow_shape="triangle",
            arrow_length=pt(3.8),
            arrow_width=pt(3.0),
            container_style="filled",
            container_stroke_width=pt(0.0),
        ),
        Page(
            ink="#1e1e1e",
            muted="#777777",
            connector="#4a4a4a",
            container_fill="#f2f2f0",
            container_stroke="#f2f2f0",
            neutral_fill="#ffffff",
            neutral_stroke="#9a9a9a",
            inset_fill="#ffffff",
            shadow="#1e1e1e",
            residual="#777777",
        ),
        _DEEP_SEA_HARVEST,
        accent_then_grey(0.85),
    )
)
_register(
    Theme(
        "swiss",
        "International Typographic Style: Helvetica, red and black, rules not boxes.",
        _style(
            "swiss",
            typography=replace(_HELVETICA, title_weight=700),
            stroke_width=pt(0.6),
            connector_width=pt(0.8),
            corner_radius=pt(0.0),
            elbow_radius=pt(0.0),
            arrow_shape="triangle",
            container_style="rule",
            container_stroke_width=pt(1.6),
        ),
        Page(
            ink="#111111",
            muted="#666666",
            connector="#111111",
            container_fill="#ffffff",
            container_stroke="#111111",
            neutral_fill="#ffffff",
            neutral_stroke="#111111",
            inset_fill="#f0f0f0",
            shadow="#111111",
            residual="#e63312",
        ),
        ("#e63312", "#111111", "#666666", "#aaaaaa"),
        solid(stroke="#111111"),
        fixed_palette=True,
    )
)
_register(
    Theme(
        "bauhaus",
        "Bauhaus: primary colours as solid fills, heavy black outlines, capitals.",
        _style(
            "bauhaus",
            typography=replace(
                _HELVETICA,
                size=pt(8.0),
                label_weight=700,
                title_weight=700,
                title_transform="upper",
            ),
            stroke_width=pt(1.4),
            connector_width=pt(1.3),
            corner_radius=pt(0.0),
            elbow_radius=pt(0.0),
            arrow_shape="triangle",
            arrow_length=pt(5.5),
            arrow_width=pt(5.0),
            container_style="outline",
            container_radius=pt(0.0),
            container_stroke_width=pt(1.4),
            motif_stroke_width=pt(1.2),
            vector_cell_radius=pt(0.0),
        ),
        Page(
            ink="#111111",
            muted="#444444",
            connector="#111111",
            container_fill="#ffffff",
            container_stroke="#111111",
            neutral_fill="#ffffff",
            neutral_stroke="#111111",
            inset_fill="#ffffff",
            shadow="#111111",
            residual="#d8262c",
        ),
        ("#d8262c", "#1b4fa3", "#f2b705", "#111111"),
        solid(stroke="#111111"),
        fixed_palette=True,
    )
)
_register(
    Theme(
        "midcentury",
        "Mid-century print: brick, teal and mustard on warm paper, hard offset shadows.",
        _style(
            "midcentury",
            stroke_width=pt(0.9),
            connector_width=pt(0.9),
            corner_radius=pt(5.0),
            elbow_radius=pt(7.0),
            arrow_shape="latex",
            shadow_style="hard",
            shadow_offset=pt(2.2),
            shadow_opacity=1.0,
            container_stroke_width=pt(0.9),
        ),
        Page(
            canvas="#fbf7ef",
            ink="#3b322c",
            muted="#7a6e66",
            connector="#3b322c",
            container_fill="#f3ecdf",
            container_stroke="#3b322c",
            neutral_fill="#fbf7ef",
            neutral_stroke="#3b322c",
            inset_fill="#f6f0e4",
            shadow="#3b322c",
            residual="#b5482f",
        ),
        ("#b5482f", "#2e6e6a", "#c99a2e", "#7a6e66"),
        tinted(fill_lightness=0.82, fill_chroma=0.08, stroke_lightness=0.42),
    )
)


def theme(name: str) -> Theme:
    """The theme named ``name``, or a diagnostic listing the ones there are."""

    found = THEMES.get(name)
    if found is None:
        raise FlexoError(unknown_theme(name))
    return found


def unknown_theme(name: str) -> Diagnostic:
    return Diagnostic(
        "style.unknown",
        f'Unknown theme "{name}".',
        hint=f"Valid themes: {', '.join(THEMES)}.",
    )


def resolve_style(
    name: str, font: str | None = None, conventions: Conventions | None = None
) -> LayoutStyle:
    """The layout style of theme ``name``, in ``font`` and under ``conventions`` if given."""

    style = theme(name).style
    if font:
        style = replace(style, typography=style.typography.with_family(font))
    if conventions is not None:
        style = replace(style, conventions=style.conventions.with_updates(conventions))
    return style


def resolve_palette(style_name: str, palette: str | Sequence[str] | None = None) -> Palette:
    """The paint for theme ``style_name`` under ``palette``.

    Under the ``classic`` theme a legacy palette name (``default``,
    ``color-vision-safe``, ``grayscale``) keeps its exact original paint. Every
    other theme derives its paint from colours, so those names are read as the
    colours they carry.
    """

    if style_name == "classic":
        name = palette if isinstance(palette, str) and palette in PALETTES else None
        if name is not None or palette is None:
            return with_tone_roles(PALETTES[name or DEFAULT_PALETTE_NAME])
    return theme(style_name).paint(palette)


def figure_style(figure: FigureSpec) -> LayoutStyle:
    """The layout style a figure compiles under: its theme, in its font and conventions."""

    return resolve_style(figure.style, figure.font, figure.conventions)


def figure_palette(figure: FigureSpec) -> Palette:
    """The paint a figure compiles with: its theme under its palette."""

    return resolve_palette(figure.style, figure.palette)


def theme_names() -> tuple[str, ...]:
    return tuple(THEMES)


# The pre-theme look, kept by name so an existing figure can ask for it exactly.
_register(
    Theme(
        "classic",
        "Flexo's original look: IBM Plex Sans, lavender blocks, triangle arrows.",
        replace(_BASE, name="classic", connector_standoff=Length(3.0)),
        _PAPER_PAGE,
        _DEEP_SEA_HARVEST,
        tinted(),
    )
)

STYLES.clear()
STYLES.update({name: registered.style for name, registered in THEMES.items()})
