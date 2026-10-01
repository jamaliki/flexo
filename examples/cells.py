"""Grids of cells: a plate map written as text, and a heatmap from numbers.

``cells`` reads a grid one row per line and one symbol per word. The plate map
names its conditions in a key (a colour each, and a legend entry); the heatmap
is rows of numbers, shaded along a ramp and written in their cells.

Run it with ``uv run python examples/cells.py``.
"""

from __future__ import annotations

import math
from pathlib import Path

from flexo import Figure, build

OUTPUT = Path(__file__).parent / "build"

PLATE = """
    C  C  C  D1 D1 D1 D2 D2 D2 D3 D3 D3
    C  C  C  D1 D1 D1 D2 D2 D2 D3 D3 D3
    V  V  V  .  .  .  .  .  .  .  .  .
"""


def grids(theme: str = "paper") -> Figure:
    with Figure("cells", theme=theme) as figure, figure.root.row("grids", gap=36) as row:
        row.cells(
            "plate",
            PLATE,
            {
                "C": {"label": "Control"},
                "V": {"label": "Vehicle", "mark": "v"},
                "D1": {"label": "1 µM"},
                "D2": {"label": "10 µM"},
                "D3": {"label": "100 µM"},
            },
            label="Dose response",
            row_labels="letters",
            column_labels="numbers",
            lines="muted",
        )
        contacts = [[round(math.exp(-abs(r - c) / 2.0), 2) for c in range(8)] for r in range(8)]
        row.cells(
            "contacts",
            contacts,
            label="Contact map",
            ramp=("#fbf6ee", "#7a1f1f"),
            values=True,
            cell=20,
            gap=0.03,
            corner=0.0,
            row_labels="numbers",
            column_labels="numbers",
        )
    return figure


def main() -> None:
    print(build(grids(), OUTPUT, formats=("editable", "png"), dpi=200).summary())


if __name__ == "__main__":
    main()
