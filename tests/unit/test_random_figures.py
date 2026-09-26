"""Random figures: whatever an author wires, compiling succeeds and the ink is sound.

Layout quality -- crossings, crowding -- is judged by the literature figures.
Here the bar is lower and absolute: no crash, and no broken geometry (a diagonal
in an orthogonal route, a route that misses its port, an arrowhead without room).
"""

from __future__ import annotations

import random

import pytest

import flexo
from flexo.builder import Figure
from flexo.compiler import compile_figure
from flexo.lint import lint_compilation

BROKEN = {
    "routing.non-orthogonal",
    "routing.source.mismatch",
    "routing.target.mismatch",
    "routing.marker.clearance",
    "routing.marker.orientation",
    "routing.canvas.clipped",
}


def _random_figure(seed: int) -> Figure:
    rnd = random.Random(seed)
    lines = rnd.choice(["orthogonal", "orthogonal", "orthogonal", "straight"])
    with (
        Figure(
            f"f{seed}", theme=rnd.choice(list(flexo.THEMES)), conventions={"lines": lines}
        ) as figure,
        figure.module("m", label="Random", layout=rnd.choice(["row", "column"])) as m,
    ):
        nodes = []
        for g in range(rnd.randint(1, 3)):
            kind = rnd.choice(["row", "column", "grid"])
            options = {"columns": rnd.randint(2, 3)} if kind == "grid" else {}
            with getattr(m, kind)(f"g{g}", **options) as group:
                for i in range(rnd.randint(1, 4)):
                    name = f"n{g}_{i}"
                    factory = rnd.choice(["block", "mlp", "circle", "text", "add", "decision"])
                    if factory == "block":
                        label = rnd.choice(["A", "Encoder", "A long label for a block"])
                        nodes.append(group.block(name, label=label))
                    elif factory == "mlp":
                        nodes.append(group.mlp(name, label="MLP"))
                    elif factory == "circle":
                        nodes.append(group.circle(name, f"$x_{i}$"))
                    elif factory == "text":
                        nodes.append(group.text(name, "Input"))
                    elif factory == "add":
                        nodes.append(group.add(name))
                    else:
                        nodes.append(group.decision(name, label="ok?"))
        for _ in range(rnd.randint(1, len(nodes) + 2)):
            if len(nodes) < 2:
                break
            source, target = rnd.sample(nodes, 2)
            m.connect(source, target, label=rnd.choice(["", "", "x"]))
        if len(nodes) >= 3 and rnd.random() < 0.4:
            source, *sinks = rnd.sample(nodes, 3)
            figure.net(src=source, sinks=sinks)
    return figure


@pytest.mark.parametrize("seed", range(24))
def test_a_random_figure_compiles_with_sound_ink(seed: int) -> None:
    compiled = compile_figure(_random_figure(seed).spec)
    broken = [item for item in lint_compilation(compiled).errors if item.code in BROKEN]
    assert not broken, [(item.code, item.entity_id) for item in broken]
