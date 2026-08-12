"""Bundled semantic figures used as documentation and acceptance fixtures."""

from __future__ import annotations

from flexo.builder import Figure
from flexo.ir.semantic import FigureSpec


def vertical_slice() -> FigureSpec:
    with Figure("vertical-slice", width="double-column") as figure:  # noqa: SIM117
        with figure.module(
            "cryo",
            label="Cryo-EM information flow",
            gap="10pt",
            justify="center",
        ) as module:
            with module.column("inputs", gap="7pt", padding=0, role="layout") as inputs:
                nodes = inputs.feature_strip("nodes", label="Node features", cells=7)
                distances = inputs.feature_strip("distances", label="Distances", cells=5)
            with module.column("encoders", gap="9pt", padding=0, role="layout") as encoders:
                q, v = encoders.mlp(
                    "projection",
                    label="Feature MLP",
                    inputs=[nodes, distances],
                    outputs=["Q", "V"],
                )
                k = encoders.cnn(
                    "keys",
                    label="Edge CNN",
                    input=nodes.branch,
                    output="K",
                )
            attended = module.attention("attention", q=q, k=k, v=v)
            prediction = module.prediction("prediction", input=attended)
            module.inset("density", label="Scientific inset")
            module.residual(
                nodes,
                prediction,
                id="cryo.residual",
                lane="cryo-bottom",
            )
    return figure.spec


GALLERY = {"vertical-slice": vertical_slice}


def gallery_figure(name: str) -> FigureSpec:
    try:
        return GALLERY[name]()
    except KeyError as error:
        valid = ", ".join(GALLERY)
        raise ValueError(f'unknown gallery figure "{name}"; valid names: {valid}') from error
