"""Build the ModelAngelo GNN panel -- Flexo's largest bundled figure.

The figure's authoring source is ``modelangelo_gnn`` in
`flexo/gallery.py <../src/flexo/gallery.py>`_, because the tests and
``uv run flexo gallery`` compile the same function; read it there for the whole
composition. This script is the export side of it, and a short tour of what to
look for in that source:

* **band rows.** The root is a column of bands, and module bands alternate with
  thin strip bands carrying one Add/LN block each. Every band opens with the
  same margin lane and the same fixed-width spine cell, so the spine blocks
  share one x and the recycle rail has an empty column to climb.
* **modules as port-aligned grids.** Each module is a ``grid`` with
  ``align="ports"``: rows are chains, columns line the chains up, and every run
  along a row is straight by construction.
* **vector glyphs and formula arrows.** Every feature value is a labelled cell
  stack in its own palette ramp role, and attention is a captioned ``merge``
  rather than a matrix component.
* **defaulted ports pick their side.** Almost no ``PortSpec`` appears: the spine
  reads downward and the readout heads are entered from above, and the compiler
  points each defaulted port at whatever it is wired to.

Run it with ``uv run python examples/modelangelo_gnn.py``.
"""

from __future__ import annotations

from pathlib import Path

from flexo import build
from flexo.gallery import modelangelo_gnn

OUTPUT = Path(__file__).parent / "build"


def main() -> None:
    result = build(
        modelangelo_gnn(),
        OUTPUT,
        stem="modelangelo-gnn",
        formats=("editable", "png"),
        dpi=200.0,
    )
    print(result.summary())


if __name__ == "__main__":
    main()
