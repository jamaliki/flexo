"""A dark-panel attention module: presets, a reserved lane, and a captioned merge.

One module, two rows, seven grid columns::

    node features -> MLP -> Q ---- softmax(QK^T)V ----> attended -> MLP -> output
    embedding     -> MLP -> K,V .............^

Rendered twice: once with ramped presets, and once with ``order="shuffled"`` --
the same colours permuted per column, so each glyph reads as a feature vector
rather than as a gradient.

What this example is here to show:

* **palette overrides** turn the default light theme dark without touching a
  coordinate (``DEFAULT_PALETTE.with_overrides``);
* **``VectorPreset``** gives every glyph the author's own base colour and
  topology instead of a palette ramp role, and ``order="shuffled"`` permutes it;
* **a reserved grid lane** (``column_widths={3: ...}``) holds the attention
  corridor open with no node in it, and everything past that lane names its cell
  with ``at=``, because flow would fall into the empty column;
* **``rail_at`` and ``joint``** place and mark the joint where K, V enters the
  attention run;
* **``paint={"label": ...}``** recolours one component's caption where the
  palette must keep serving every other label;
* **``title_side="right"``** and **``motif=False``** are the two ornament knobs.

Run it with ``uv run python examples/attention_module.py``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from flexo import (
    DEFAULT_PALETTE,
    STYLES,
    Figure,
    FigureSpec,
    LayoutStyle,
    TextRun,
    TypographyStyle,
    VectorPreset,
    build,
    pt,
    vector_stack_height,
)

OUTPUT = Path(__file__).parent / "build"
DPI = 200.0

CELL = pt(9.8)
"""Side of one vector cell: the unit every other proportion reads against."""

CELLS = 3
"""Cells in every vector glyph, and so the height every box matches."""

MLP_WIDTH = pt(64.0)
FORMULA_LANE = pt(50.0)
"""Width reserved for column 3, which carries the attention arrow and nothing else."""

# Sides sit tighter than top and bottom, and the bottom carries the most air,
# because the captions hang below the last row of vectors.
PADDING = (pt(11.5), pt(11.5), pt(32.5), pt(11.5))
GAP = pt(19.0)
"""Rows and columns space independently, so vertical air is not bought seven
columns wide."""

STYLE: LayoutStyle = STYLES["paper"].with_updates(
    typography=TypographyStyle(size=pt(8.5)),
    vector_cell=CELL,
    corner_radius=pt(4.7),
    # measure.py builds a group's title band from the label height plus
    # compact_gap, so this is the air between the title and the first row.
    compact_gap=pt(16.0),
)

PALETTE = DEFAULT_PALETTE.with_overrides(
    {
        "canvas": "#ffffff",
        "container-fill": "#444441",
        "container-stroke": "#444441",
        # An MLP paints block-fill/block-stroke; accent-* is kept in step so any
        # accented component matches the same dark teal.
        "block-fill": "#085041",
        "block-stroke": "#56bb9a",
        "accent-fill": "#085041",
        "accent-stroke": "#56bb9a",
        # Node labels and the module title paint "ink"; only connector and net
        # captions paint "muted-ink".
        "ink": "#eceae4",
        "muted-ink": "#c3c2b7",
        "connector": "#898781",
    }
)

TINT = 0.35
"""On a dark panel the light cells must stay richer than the default 0.6 tint,
which mixes them towards the page."""

PRESETS = {
    "nodes": VectorPreset("#8a7de8", "1x3", tint=TINT),
    "embedding": VectorPreset("#eaa53e", "1x3", tint=TINT),
    "q": VectorPreset("#e0603a", "1x3", tint=TINT),
    "kv": VectorPreset(("#d75f94", "#8fbf4d"), "2x3", tint=TINT),
    "attended": VectorPreset("#4ec9a0", "1x3", tint=TINT),
    "output": VectorPreset("#8a7de8", "1x3", tint=TINT),
}

MLP_LABEL = "#9fe1cb"
"""A mint caption on the dark teal MLP body.

One component differing from its palette is author paint, not a palette change:
"ink" still has to serve every other label in the panel.
"""

ATTENTION_LABEL = (
    TextRun("softmax(QK"),
    TextRun("T", baseline_shift="super"),
    TextRun(")V"),
)

CAPTION_WEIGHT = 400
EMPHASIS_WEIGHT = 600
"""Q and K, V are set apart from the muted captions by weight."""


def caption(text: str, weight: int = CAPTION_WEIGHT) -> tuple[TextRun, ...]:
    return (TextRun(text, weight=weight),)


def attention_module(*, order: str = "ramp") -> FigureSpec:
    """The panel, with every glyph ramped or every glyph shuffled."""

    shades = {name: replace(preset, order=order) for name, preset in PRESETS.items()}
    # Every box is one cell stack tall, so its side ports share the vectors' y.
    mlp = {
        "width": MLP_WIDTH,
        "height": vector_stack_height(STYLE, CELLS),
        "motif": False,
        "paint": {"label": MLP_LABEL},
    }
    with Figure("attention-module", width="double-column") as figure:  # noqa: SIM117
        with figure.root.group(
            "attention",
            label="Attention module",
            layout="grid",
            columns=7,
            row_gap=GAP,
            column_gap=GAP,
            padding=PADDING,
            column_widths={3: FORMULA_LANE},
            align="start",
            role="module",
            title_side="right",
        ) as module:
            # The first three cells of row 0 flow; everything past the empty
            # formula lane names its cell, because flow would fall into it.
            nodes = module.vector(
                "nodes",
                label=caption("Node\nfeatures"),
                preset=shades["nodes"],
            )
            q_mlp = module.mlp("q-mlp", input=nodes, **mlp)
            q = module.vector(
                "q",
                label=caption("Q", EMPHASIS_WEIGHT),
                preset=shades["q"],
                input=q_mlp,
            )
            attended = module.vector("attended", preset=shades["attended"], at=(0, 4))
            out_mlp = module.mlp("out-mlp", input=attended, at=(0, 5), **mlp)
            module.vector(
                "out",
                label=caption("Output"),
                preset=shades["output"],
                input=out_mlp,
                at=(0, 6),
            )
            # Row 1 is three cells long. The four cells to its right hold
            # nothing at all and cost nothing to leave out.
            embedding = module.vector(
                "embedding",
                label=caption("Embedding"),
                preset=shades["embedding"],
                at=(1, 0),
            )
            kv_mlp = module.mlp("kv-mlp", input=embedding, at=(1, 1), **mlp)
            kv = module.vector(
                "kv",
                label=caption("K, V", EMPHASIS_WEIGHT),
                preset=shades["kv"],
                input=kv_mlp,
                at=(1, 2),
            )
            # K, V joins the attention run about halfway along it, and the joint
            # is an arrowhead pointing into an unbroken run rather than a dot.
            module.merge(
                sinks=[q, kv],
                dst=attended,
                id=f"{module.id}.attention",
                label=ATTENTION_LABEL,
                rail_at=0.55,
                joint="arrow",
            )
    return figure.spec


def main() -> None:
    for stem, order in (("attention-module", "ramp"), ("attention-module-shuffled", "shuffled")):
        result = build(
            attention_module(order=order),
            OUTPUT,
            stem=stem,
            formats=("editable", "png"),
            dpi=DPI,
            style=STYLE,
            palette=PALETTE,
        )
        document = result.compilation.document
        print(f"{stem}: {document.width_mm:.1f}mm x {document.height_mm:.1f}mm")
        print(result.summary())


if __name__ == "__main__":
    main()
