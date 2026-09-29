"""Biology beyond the construct: a pathway, protein domain maps, trees, and the bench.

What this example is here to show:

* **reaction arrows** -- ``cofactors=("ATP", "ADP")`` curves beside a step,
  ``arrow="reversible"`` draws a reversible step as two harpoons with a rate
  constant each side, and ``head=`` draws regulation after SBGN (a bar for
  inhibition, an open circle for catalysis, ...);
* **``protein``** draws a chain to scale by residue, with domains, sites, and
  bonds; its ``tracks`` line up the constructs of a study;
* **``secondary``** draws a protein's helices, strands, and turns from its DSSP
  string, numbered, with the sequence under them when the scale has room;
* **``tree``** reads Newick and draws a phylogram, rectangular or circular,
  with its clades coloured and named;
* **``wellplate``** and **``timeline``** draw a methods figure's plate layout
  and protocol.

A domain, a clade, or a condition takes a colour by its name, as a gene does:
the kinase domain is one colour in both protein maps.
"""

from __future__ import annotations

from pathlib import Path

import flexo
from flexo import build

OUTPUT = Path(__file__).resolve().parent / "build"
DPI = 240

ABL1 = [
    {"type": "domain", "label": "SH3", "start": 61, "end": 121},
    {"type": "domain", "label": "SH2", "start": 127, "end": 217},
    {"type": "domain", "label": "Kinase", "start": 242, "end": 493, "id": "kinase"},
    {"type": "region", "label": "Disordered", "start": 540, "end": 960},
    {"type": "motif", "label": "NLS", "start": 605, "end": 609},
    {"type": "domain", "label": "F-actin binding", "start": 1026, "end": 1130},
    {"type": "mutation", "label": "Y253H", "at": 253},
    {"type": "mutation", "label": "E255K", "at": 255},
    {"type": "mutation", "label": "T315I", "at": 315},
    {"type": "phosphorylation", "label": "Y412", "at": 412},
]

MAMMALS = (
    "(((Human:0.08,Chimpanzee:0.09)100:0.12,Gorilla:0.21)98:0.25,"
    "((Mouse:0.35,Rat:0.33)100:0.30,(Cow:0.28,(Dog:0.25,Cat:0.22)87:0.06)91:0.08)76:0.05,"
    "Opossum:0.72);"
)


def pathway() -> flexo.FigureSpec:
    with flexo.Figure("pathway", width="double-column") as figure:
        column = figure.root.column("all", gap=26)
        steps = column.row("glycolysis", gap=84)
        glucose = steps.text("glucose", label="Glucose")
        g6p = steps.text("g6p", label="Glucose-6-P")
        f6p = steps.text("f6p", label="Fructose-6-P")
        fbp = steps.text("fbp", label="Fructose-1,6-BP")
        figure.connect(glucose, g6p, label="hexokinase", cofactors=("ATP", "ADP"))
        figure.connect(g6p, f6p, arrow="reversible", label="$k_1$", back_label="$k_{-1}$")
        figure.connect(f6p, fbp, label="PFK-1", cofactors=("ATP", "ADP"))
        circuit = column.row("regulation", gap=40)
        atc = circuit.text("atc", label="aTc")
        tetr = circuit.block("tetr", label="TetR")
        ptet = circuit.block("ptet", label="pTet")
        gfp = circuit.block("gfp", label="GFP", tone="GFP")
        figure.connect(atc, tetr, head="inhibition")
        figure.connect(tetr, ptet, head="inhibition")
        figure.connect(ptet, gfp, head="stimulation")
    return figure.spec


def proteins() -> flexo.FigureSpec:
    # One scale and one gutter for track names: the two maps line up by residue.
    with flexo.Figure("proteins", width="double-column") as figure:
        maps = figure.root.column("maps", gap=18, align="start")
        maps.protein("abl1", 1130, ABL1, label="ABL1", scale=0.3, gutter=70)
        maps.protein(
            "constructs",
            1130,
            [feature for feature in ABL1 if feature["type"] in {"domain", "motif"}],
            label="Constructs",
            scale=0.3,
            gutter=70,
            tracks=[
                {"label": "Full length"},
                {"label": "ΔSH3", "delete": "61-121"},
                {"label": "Kinase domain", "start": 229, "end": 500},
            ],
        )
    return figure.spec


UBIQUITIN = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"
# DSSP for 1UBQ: H helix, G 3-10 helix, E strand, T turn, anything else loop.
UBIQUITIN_DSSP = "CEEEEEETTSCEEEEEECTTSBHHHHHHHHHHHHCCCGGGEEEEETTEEECTTSBTTTTTCCTTCEEEEEEECCCC"


def structure() -> flexo.FigureSpec:
    with flexo.Figure("structure", width="double-column") as figure:
        maps = figure.root.column("maps", gap=16, align="start")
        maps.protein("ubiquitin", 76, label="Ubiquitin (1UBQ)", secondary=UBIQUITIN_DSSP,
                     sequence=UBIQUITIN, scale=6.2)
        maps.protein("close", 76, label="Residues 18-42, closer", secondary=UBIQUITIN_DSSP,
                     sequence=UBIQUITIN, scale=12, helix="cylinder",
                     tracks=[{"start": 18, "end": 42}])
    return figure.spec


E2_STRUCTURE = Path(__file__).resolve().parents[1] / "tests" / "unit" / "data" / "1a7g.cif"


def molecule() -> flexo.FigureSpec:
    """A structure drawn by mol-sketch beside its own secondary structure, read from
    the same file: the map's helix and strand colours are the molecule's."""

    with flexo.Figure("molecule", width="double-column") as figure:
        row = figure.root.row("row", gap=24, align="center")
        row.structure("model", E2_STRUCTURE, label="E2 DNA-binding domain", yaw=30,
                      width=150, height=120)
        read = flexo.from_structure(E2_STRUCTURE)
        row.protein("map", **{**read, "label": "Its secondary structure"}, scale=3.2)
    return figure.spec


def trees() -> flexo.FigureSpec:
    clades = [
        {"tips": "Human, Gorilla", "label": "Primates"},
        {"tips": "Mouse, Rat", "label": "Rodents"},
        {"tips": "Cow, Cat", "label": "Laurasiatheria"},
    ]
    with flexo.Figure("trees", width="double-column") as figure:
        row = figure.root.row("row", gap=24)
        row.tree("phylogram", MAMMALS, label="Mammals", support=True, italic=True, depth=150,
                 clades=clades)
        row.tree("ring", MAMMALS, layout="circular", italic=True, clades=clades[:2])
    return figure.spec


def bench() -> flexo.FigureSpec:
    with flexo.Figure("bench", width="double-column") as figure:
        row = figure.root.row("row", gap=28)
        row.wellplate("plate", [
            {"wells": "A1-A12", "label": "Control"},
            {"wells": "B-D", "label": "Drug, 1 µM"},
            {"wells": "E-G", "label": "Drug, 10 µM"},
            {"wells": "H1-H6", "label": "Blank"},
        ], label="Plate layout")
        row.timeline("protocol", events=[
            {"at": 0, "label": "Seed"},
            {"at": 1, "label": "Transfect"},
            {"at": 2, "label": "Induce"},
            {"at": 5, "label": "Harvest"},
        ], spans=[
            {"start": 0, "end": 1, "label": "Serum-free"},
            {"start": 2, "end": 5, "label": "Doxycycline"},
            {"start": 3, "end": 5, "label": "Drug"},
        ], unit="day", label="Protocol")
    return figure.spec


def _can_draw_molecules() -> bool:
    try:
        import gemmi  # noqa: F401
        import molsketch  # noqa: F401
    except ImportError:
        print("molecule: skipped (needs gemmi and mol-sketch)")
        return False
    return True


def main() -> None:
    for name, spec in (
        ("pathway", pathway()),
        ("proteins", proteins()),
        ("trees", trees()),
        ("structure", structure()),
        *((("molecule", molecule()),) if _can_draw_molecules() else ()),
        ("bench", bench()),
    ):
        result = build(spec, OUTPUT, stem=name, formats=("editable", "png"), dpi=DPI)
        document = result.compilation.document
        print(f"{name}: {document.width_mm:.1f}mm x {document.height_mm:.1f}mm")
        print(result.summary())


if __name__ == "__main__":
    main()
