"""A genetic circuit: two constructs in SBOL Visual glyphs, the plasmid that carries
them, and the gene's product wired to the part that makes it.

What this example is here to show:

* **``construct``** sets parts on a backbone -- promoter, RBS, gene, terminator --
  and turns a part on the ``-`` strand over;
* **``plasmid``** places features by their base pairs, stacks overlapping ones,
  and names each outside the circle, a cluster of restriction sites included;
* **a part with an ``id``** is a port, so ``circuit.port("gfp")`` is where the
  arrow to the protein leaves;
* **a gene's colour is its name's**: GFP is one colour in the construct, on the
  plasmid, and in the box toned ``"GFP"``.
"""

from __future__ import annotations

from pathlib import Path

import flexo
from flexo import build

OUTPUT = Path(__file__).resolve().parent / "build"
DPI = 240

SITES = [("HindIII", 400), ("PstI", 418), ("XbaI", 430), ("BamHI", 436), ("EcoRI", 459)]


def genetic_circuit() -> flexo.FigureSpec:
    with flexo.Figure("genetic-circuit", width="double-column") as figure:
        with figure.root.row("designs", gap=32) as designs:
            with designs.column("constructs", gap=18) as constructs:
                reporter = constructs.construct("reporter", label="pTet-GFP reporter", parts=[
                    {"type": "promoter", "label": "pTet"},
                    {"type": "rbs", "label": "B0034"},
                    {"type": "cds", "label": "GFP", "id": "gfp"},
                    {"type": "terminator", "label": "B0015"},
                ])
                protein = constructs.block("protein", label="Green fluorescence", tone="GFP")
                constructs.construct("repressor", label="TetR cassette", parts=[
                    {"type": "promoter", "label": "pLac"},
                    {"type": "rbs", "label": "B0034"},
                    {"type": "cds", "label": "TetR"},
                    {"type": "terminator", "label": "B0015"},
                    {"type": "operator", "label": "tetO", "strand": "-"},
                ])
            designs.plasmid("vector", 5421, label="pTet-GFP", features=[
                {"type": "promoter", "label": "pTet", "start": 120, "end": 180},
                {"type": "cds", "label": "GFP", "start": 220, "end": 940},
                {"type": "terminator", "label": "B0015", "start": 960, "end": 1090},
                {"type": "cds", "label": "TetR", "start": 1300, "end": 1920, "strand": "-"},
                {"type": "origin", "label": "ColE1", "start": 2500, "end": 3090},
                {"type": "cds", "label": "AmpR", "start": 3300, "end": 4160, "strand": "-"},
                {"type": "promoter", "label": "AmpR promoter", "start": 4161, "end": 4265,
                 "strand": "-"},
                *({"type": "site", "label": name, "start": at} for name, at in SITES),
            ])
        figure.connect(reporter.port("gfp"), protein)
    return figure.spec


def main() -> None:
    result = build(genetic_circuit(), OUTPUT, stem="genetic-circuit", formats=("editable", "png"),
                   dpi=DPI)
    document = result.compilation.document
    print(f"genetic-circuit: {document.width_mm:.1f}mm x {document.height_mm:.1f}mm")
    print(result.summary())


if __name__ == "__main__":
    main()
