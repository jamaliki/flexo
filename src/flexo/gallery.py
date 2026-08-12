"""Bundled semantic figures used as documentation and acceptance fixtures."""

from __future__ import annotations

from flexo.builder import Figure
from flexo.ir.semantic import FigureSpec


def vertical_slice() -> FigureSpec:
    with Figure("vertical-slice", width="double-column") as figure:  # noqa: SIM117
        with figure.module(
            "cryo",
            label="Cryo-EM information flow",
            gap="12pt",
            justify="center",
        ) as module:
            with module.column(
                "branches",
                gap="12pt",
                padding=0,
                align="end",
                role="layout",
            ) as branches:
                with branches.row(
                    "feature-path",
                    gap="12pt",
                    padding=0,
                    role="layout",
                ) as feature_path:
                    with feature_path.column(
                        "inputs",
                        gap="8pt",
                        padding=0,
                        role="layout",
                    ) as inputs:
                        nodes = inputs.feature_strip("nodes", label="Node features", cells=7)
                        distances = inputs.feature_strip("distances", label="Distances", cells=5)
                    combined = feature_path.concat("concat", inputs=[nodes, distances])
                    projection = feature_path.mlp(
                        "projection",
                        label="Feature MLP",
                        input=combined,
                    )
                    q, v = feature_path.channels(
                        "query-value",
                        labels=["Q", "V"],
                        input=projection,
                    )
                with branches.row(
                    "edge-path",
                    gap="12pt",
                    padding=0,
                    role="layout",
                ) as edge_path:
                    neighbourhoods = edge_path.inset(
                        "neighbourhoods",
                        label="Edge neighbourhoods",
                        width="82pt",
                        height="48pt",
                    )
                    keys = edge_path.cnn("keys", label="Edge CNN", input=neighbourhoods)
                    (k,) = edge_path.channels("key", labels=["K"], input=keys)
            attended = module.attention("attention", q=q, k=k, v=v)
            prediction = module.prediction("prediction", input=attended)
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
