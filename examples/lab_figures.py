"""Figures of the kind the lab draws, rebuilt in flexo to find what it still lacks.

* **ModelAngelo, overview** -- a cryo-EM map and sequences in, an atomic model
  out: the Ca-prediction network, the graph network's three modules and its
  recycling, and the sequence search that assigns each chain.
* **Reaction-aware enzyme design** -- a target reaction written as chemistry
  (cofactors, a reversible binding step), the generative loop that designs for
  it, and the bench it goes to: a plate, a protocol, and the data coming back.
* **A structure paper's Figure 1** -- HIV-1 capsid protein: its domain map with
  the constructs used, the C-terminal domain's secondary structure read from its
  crystal structure (1A8O) in the protein's own numbering, and the structure
  drawn by mol-sketch with the dimer-interface residues marked.

The structure panels need gemmi and mol-sketch; without them they are left out.
The structures (1A8O, and trypsin, 1GBT, standing in for a designed hydrolase)
are in ``examples/data``.
"""

from __future__ import annotations

from pathlib import Path

import flexo
from flexo import build

OUTPUT = Path(__file__).resolve().parent / "build"
DPI = 240
DATA = Path(__file__).resolve().parent / "data"
CAPSID = DATA / "1a8o.pdb"  # HIV-1 capsid C-terminal domain
TRYPSIN = DATA / "1gbt.cif"  # a serine hydrolase, standing in for a design


def _molecules() -> bool:
    try:
        import gemmi  # noqa: F401
        import molsketch  # noqa: F401
    except ImportError:
        return False
    return True


def modelangelo() -> flexo.FigureSpec:
    with flexo.Figure("modelangelo-overview", width=flexo.mm(290), layout="flow-right") as figure:
        root = figure.root
        density = root.inset("map", label="Cryo-EM map")
        sequences = root.sequence("sequences", label="Sequences")
        alpha = "\N{GREEK SMALL LETTER ALPHA}"
        unet = root.cnn("unet", label=f"C{alpha} prediction\n(U-Net)", input=density)
        with root.module("gnn", label="Graph network  \N{MULTIPLICATION SIGN}3") as gnn:
            cryo = gnn.block("cryo", label="Cryo-EM module", tone="map")
            language = gnn.block("seq", label="Sequence attention", tone="sequence")
            ipa = gnn.block("ipa", label="Invariant point attention", tone="geometry")
            figure.connect(cryo, language)
            figure.connect(language, ipa)
        figure.connect(unet, cryo, label=f"C{alpha} graph")
        plm = root.block("plm", label="Language model", tone="sequence")
        figure.connect(sequences, plm)
        figure.connect(plm, language, label="embeddings")
        figure.connect(ipa, cryo, label="recycle", line="dashed")
        search = root.block("hmm", label="HMM search\nand threading")
        figure.connect(ipa, search, label="amino-acid profiles")
        figure.connect(sequences, search)
        model = root.block("model", label="Atomic model", tone="geometry")
        figure.connect(search, model)
    return figure.spec


def enzyme_design() -> flexo.FigureSpec:
    with flexo.Figure("enzyme-design", width=flexo.mm(216)) as figure:
        # Centred: the rows are wired to each other, so "auto" would line up their
        # port lines, and the reaction row -- wired to none -- would sit off-centre.
        column = figure.root.column("all", gap=24, align="center")
        chemistry = column.row("reaction", gap=70, label="Target reaction")
        es = chemistry.text("es", label="E + ester")
        complex_ = chemistry.text("complex", label="E·ester")
        acyl = chemistry.text("acyl", label="Acyl-enzyme")
        product = chemistry.text("product", label="E + acid")
        figure.connect(es, complex_, arrow="reversible", label="$k_1$", back_label="$k_{-1}$")
        figure.connect(complex_, acyl, label="acylation", cofactors=("", "alcohol"))
        figure.connect(acyl, product, label="deacylation", cofactors=("H₂O", ""))
        loop = column.row("loop", gap=34)
        mechanism = loop.graph("mechanism", label="Mechanism\nrepresentation")
        generator = loop.block(
            "model", label="Reaction-conditioned\ngenerative model", tone="model"
        )
        if _molecules():
            design = loop.structure("design", TRYPSIN, label="Designed hydrolase", width=120,
                                    height=90, sticks="resi 57+102+195")
        else:
            design = loop.block("design", label="Designed hydrolase")
        filters = loop.block("filters", label="Refolding and\ndocking filters")
        figure.connect(mechanism, generator)
        figure.connect(generator, design)
        figure.connect(design, filters)
        bench = column.row("bench", gap=28)
        plate = bench.wellplate("screen", [
            {"wells": "A-F", "label": "Designs"},
            {"wells": "G1-G12", "label": "Wild type"},
            {"wells": "H1-H12", "label": "No enzyme"},
        ], label="Activity screen")
        bench.timeline("protocol", events=[
            {"at": 0, "label": "Transform"},
            {"at": 1, "label": "Induce"},
            {"at": 2, "label": "Lyse"},
            {"at": 3, "label": "Assay", "id": "assay"},
        ], spans=[{"start": 1, "end": 2, "label": "Expression, 18 °C"}], unit="day",
            label="Protocol")
        figure.connect(filters, plate, label="to the bench")
        figure.connect(plate, generator, label="activities: fine-tune", line="dashed",
                       head="stimulation")
    return figure.spec


def capsid() -> flexo.FigureSpec:
    features = [
        {"type": "domain", "label": "N-terminal domain", "start": 1, "end": 145},
        {"type": "domain", "label": "C-terminal domain", "start": 151, "end": 231},
        {"type": "motif", "label": "CypA loop", "start": 85, "end": 93},
        {"type": "motif", "label": "MHR", "start": 153, "end": 172},
        {"type": "mutation", "label": "W184A", "at": 184},
        {"type": "mutation", "label": "M185A", "at": 185},
    ]
    with flexo.Figure("capsid-figure-1", width=flexo.mm(210)) as figure:
        column = figure.root.column("all", gap=18, align="start")
        column.protein("ca", 231, features, label="HIV-1 capsid protein (CA)", scale=1.9, gutter=80,
                       tracks=[
                           {"label": "Full length"},
                           {"label": "CTD", "start": 146, "id": "ctd"},
                       ])
        if _molecules():
            structure = flexo.from_structure(CAPSID, numbering="author")
            row = column.row("structure", gap=26, align="center")
            row.protein("ss", 231, label="CTD secondary structure (1A8O)", scale=4.6, gutter=0,
                        secondary=structure["secondary"],
                        secondary_start=structure["secondary_start"],
                        tracks=[{"start": 146, "end": 231}])
            row.structure("model", CAPSID, label="CTD crystal structure", width=130, height=100,
                          sticks="resi 184+185", colors={"TRP184": "#b8342a", "MET185": "#b8342a"})
    return figure.spec


def main() -> None:
    for name, spec in (
        ("modelangelo-overview", modelangelo()),
        ("enzyme-design", enzyme_design()),
        ("capsid-figure-1", capsid()),
    ):
        result = build(spec, OUTPUT, stem=name, formats=("editable", "png"), dpi=DPI)
        document = result.compilation.document
        print(f"{name}: {document.width_mm:.1f}mm x {document.height_mm:.1f}mm")
        print(result.summary())


if __name__ == "__main__":
    main()
