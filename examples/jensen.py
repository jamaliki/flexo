"""After Alfred Jensen: two number squares, their colours counted in rings.

Jensen's squares are rings around a centre. In the odd square (13 x 13) the
rings hold 1, 8, 16, ... 48 cells -- 169 in all -- and in the even one (14 x 14)
4, 12, 20, ... 52 -- 196. Every other ring is painted in a cycle of four colours
(yellow, red, blue, purple, clockwise from its top-left corner); the rest are
black and white, like a board. The arithmetic he wrote around them is the same
rings counted, so here it is computed, not copied: change ``13`` and ``14`` and
the words change with the squares.

What this example shows:

* **``cells``** drawing a grid from text, its symbols given exact colours and a
  mark (``key``), the grid ruled in blue ink and numbered along two sides;
* the **sketch** theme with the **``gouache``** fill: each square painted by hand,
  with an uneven edge, uneven density, and the streaks of the brush;
* a figure set in a **handwriting** font (Caveat, bundled).

Run it with ``uv run python examples/jensen.py``.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from flexo import Figure, build

OUTPUT = Path(__file__).parent / "build"

INK_BLUE = "#2b4a9c"
TIMES = "\N{MULTIPLICATION SIGN}"
KEY = {
    "Y": {"color": "#f1bf24", "mark": "з"},
    "R": {"color": "#dd3b35", "mark": "я"},
    "B": "#2263c4",
    "P": "#4a2c72",
    "K": "#262422",
}
CYCLE = "YRBP"


def perimeter(n: int, ring: int) -> list[tuple[int, int]]:
    """A ring's cells, clockwise from its top-left corner."""

    top = (n - 1) // 2 - ring if n % 2 else n // 2 - 1 - ring
    side = n - 2 * top
    cells = [(top, top + i) for i in range(side)]
    cells += [(top + i, top + side - 1) for i in range(1, side)]
    cells += [(top + side - 1, top + side - 1 - i) for i in range(1, side)]
    cells += [(top + side - 1 - i, top) for i in range(1, side - 1)]
    return list(dict.fromkeys(cells))


def square(n: int) -> tuple[str, list[int]]:
    """The grid of an n x n square as text, and its ring sizes from the centre out."""

    grid = [["." for _ in range(n)] for _ in range(n)]
    sizes = []
    for ring in range((n + 1) // 2):
        cells = perimeter(n, ring)
        sizes.append(len(cells))
        for index, (r, c) in enumerate(cells):
            if ring % 2 == 1:  # the rings the colours run round
                grid[r][c] = CYCLE[index % 4]
            elif not (ring == 0 and n % 2) and (r + c) % 2 == 0:
                grid[r][c] = "K"
    return "\n".join(" ".join(row) for row in grid), sizes


def mixed(value: Fraction) -> str:
    whole, part = divmod(value, 1)
    return f"{whole}" if not part else f"{whole} {part.numerator}/{part.denominator}"


def jensen(odd: int = 13, even: int = 14) -> Figure:
    with (
        Figure(
            "jensen",
            width=620,
            theme="sketch",
            font="Caveat",
            sketch={"fill": "gouache", "roughness": 0.6, "seed": 7},
            background=True,
        ) as figure,
        figure.root.column("page", gap=18) as page,
    ):
        with page.row("squares", gap=60) as squares:
            for n in (odd, even):
                grid, sizes = square(n)
                coloured = sizes[1::2]
                parity = ("even", "odd") if n % 2 else ("odd", "even")
                with squares.column(f"s{n}", gap=6) as side:
                    side.text("f", "  -  ".join(f"{size // 4}{TIMES}4" for size in coloured) + " =")
                    counts = "  —  ".join(str(size) for size in coloured)
                    side.text("c", f"{counts}  = {parity[0]} color")
                    side.text("count", f"count in {parity[1]} square.")
                    side.cells(
                        "grid", grid, KEY, cell=12, gap=0.1, corner=0.18,
                        lines=INK_BLUE, row_labels="numbers", row_side="right",
                        column_labels="numbers", column_side="bottom",
                    )  # fmt: skip
                    side.text("sum", "+".join(map(str, sizes)) + f" = {n * n}.")
                    side.text("product", f"{n} {TIMES} {n} = {n * n}.")
                    side.text(
                        "sevens",
                        f"7 : {n * n} = {mixed(Fraction(n * n, 7))}.",
                        paint={"label": INK_BLUE},
                    )
        year = odd * odd + even * even
        page.text("year", f"{odd * odd} + {even * even} = {year}.")
        page.text(
            "weeks",
            f"7 : {year} = {mixed(Fraction(year, 7))}, the weeks in a year of {year} days.",
            paint={"label": INK_BLUE},
        )
    return figure


def main() -> None:
    print(build(jensen(), OUTPUT, formats=("editable", "png"), dpi=200).summary())


if __name__ == "__main__":
    main()
