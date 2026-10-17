"""What a row of a structure's colours is offered to colour, as the molecule has it: its
subunits (a ribosome's large and small), its entities of more than one chain, and its chains
by the names of what they are -- and chains told apart by their case, as the file writes
them: a ribosome's Le is not its LE."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import flexo
from flexo.structure_names import compound_names, entity_names, readable
from flexo.structures import structure_problem
from flexo.themes import figure_palette, figure_style

# A small ribosome, of sorts: a 28S rRNA (L5) and a 60S protein (LE) of the large subunit, a
# 40S protein of the small (Le: LE's name in another case), and a molecule of two chains (A
# and B) that is of neither. Its third entity's name is a value of lines of its own.
_CIF_HEAD = """data_TOYR
_entry.id TOYR
#
loop_
_entity.id
_entity.type
_entity.src_method
_entity.pdbx_description
1 polymer nat '28S rRNA (3773-MER)'
2 polymer nat '60S ribosomal protein L8'
3 polymer nat
;40S ribosomal protein SA
;
4 polymer man 'HEMOGLOBIN ALPHA CHAIN'
#
loop_
_entity_poly.entity_id
_entity_poly.type
_entity_poly.pdbx_strand_id
1 polyribonucleotide L5
2 'polypeptide(L)' LE
3 'polypeptide(L)' Le
4 'polypeptide(L)' A,B
#
"""

_ATOMS = """loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.auth_seq_id
_atom_site.auth_asym_id
_atom_site.pdbx_PDB_model_num
"""


def _ribosome(path: Path, *, residues: dict[str, int] | None = None) -> Path:
    """The toy ribosome as an mmCIF: ``residues`` alanines in each chain (LE three, Le two)."""

    counts = residues or {"L5": 2, "LE": 3, "Le": 2, "A": 2, "B": 2}
    entity = {"L5": 1, "LE": 2, "Le": 3, "A": 4, "B": 4}
    rows, serial = [], 0
    for place, (chain, count) in enumerate(counts.items()):
        for resi in range(1, count + 1):
            x, y, z = 12.0 * place, 0.0, 3.8 * resi
            for name, (dx, dy, dz) in (
                ("N", (-0.6, 0.6, -0.5)),
                ("CA", (0.0, 0.0, 0.0)),
                ("C", (0.6, -0.6, 0.5)),
                ("O", (1.2, -0.6, 1.2)),
            ):
                serial += 1
                rows.append(
                    f"ATOM {serial} {name[0]} {name} . ALA {chain} {entity[chain]} {resi} "
                    f"{x + dx:.3f} {y + dy:.3f} {z + dz:.3f} {resi} {chain} 1"
                )
    path.write_text(_CIF_HEAD + _ATOMS + "\n".join(rows) + "\n#\n", encoding="utf-8")
    return path


def _settings(source: Path, colours: list[dict[str, str]], folder: Path) -> dict:
    from flexo.studio.figure_kind import FigureKind

    rows = ", ".join(f"{{group: '{row['group']}', color: '{row['color']}'}}" for row in colours)
    text = (
        "figure: {id: rows}\nnodes:\n  - id: model\n    kind: structure\n"
        f"    properties: {{source: {source}, look: flat, colors: [{rows}]}}\n"
    )
    return FigureKind().act({"text": text}, {"do": "structure-settings", "id": "model"}, folder)[
        "settings"
    ]


def _handed(source: Path, colors: dict[str, str]) -> dict[str, str]:
    from flexo import structures

    with flexo.Figure("coloured") as figure:
        figure.root.structure("model", source, look="flat", colors=colors)
    spec = figure.spec
    assert structure_problem(spec.nodes[0], figure_style(spec)) is None
    ask = structures._ask(spec.nodes[0], figure_style(spec), figure_palette(spec))
    return dict(structures._one_at_a_time(structures._drawn, ask)._colors or {})


def test_a_row_is_offered_the_molecules_subunits_entities_and_named_chains(
    tmp_path: Path,
) -> None:
    pytest.importorskip("molsketch")
    source = _ribosome(tmp_path / "toyr.cif")
    settings = _settings(source, [{"group": "subunit:L", "color": "#3f7fc0"}], tmp_path)
    offered = settings["colours"]["choices"]
    # Its subunits, as mol-sketch tells them by its entities' names; the chains of neither
    # (A and B) are of none, and offered as no subunit.
    assert offered["subunits"] == [
        {"group": "subunit:L", "label": "Large Subunit", "chains": 2},
        {"group": "subunit:S", "label": "Small Subunit", "chains": 1},
    ]
    # An entity of more than one chain, by name: in sentence case, as its capitals are not.
    assert offered["entities"] == [
        {"group": "entity:4", "label": "Hemoglobin alpha chain", "chains": ["A", "B"]},
    ]
    # Each chain by the name of what it is, without an RNA's length -- in the file's order.
    assert offered["chains"] == [
        {"chain": "L5", "name": "28S rRNA"},
        {"chain": "LE", "name": "60S ribosomal protein L8"},
        {"chain": "Le", "name": "40S ribosomal protein SA"},
        {"chain": "A", "name": "Hemoglobin alpha chain"},
        {"chain": "B", "name": "Hemoglobin alpha chain"},
    ]
    assert settings["chains"] == ["L5", "LE", "Le", "A", "B"]
    # And the subunit chosen colours what it says.
    assert settings["colours"]["groups"]["subunit:L"]["residues"] == 5


def test_a_molecule_of_one_subunit_or_none_is_offered_none(tmp_path: Path) -> None:
    from flexo.structure_colours import Molecule, Residue, choices

    def residue(chain: str, entity: str, subunit: str) -> Residue:
        return Residue(f"ALA1.{chain}", "ALA", 1, chain, entity, subunit, False, "L")

    one = Molecule((residue("A", "1", "L"), residue("B", "2", "X")), (), ())
    offered = choices(one, {"1": "28S rRNA"})
    assert offered["subunits"] == [] and offered["entities"] == []
    assert offered["chains"] == [{"chain": "A", "name": "28S rRNA"}, {"chain": "B", "name": ""}]
    # A tRNA and an mRNA are of neither subunit: said by which they are.
    both = Molecule((residue("L5", "1", "L"), residue("T", "2", "T")), (), ())
    assert choices(both, {"1": "28S rRNA", "2": "E site tRNA (75-MER)"})["subunits"][1] == {
        "group": "subunit:T",
        "label": "tRNA",
        "chains": 1,
    }


def test_chains_named_alike_but_for_their_case_are_told_apart(tmp_path: Path) -> None:
    """A ribosome's chains LE and Le are two: a row for Le -- by its name, or selected by
    ``chain Le`` -- colours Le alone, and its residues are counted as Le's; ``chain le``, as
    the file writes no chain, selects nothing and says so (as mol-sketch matches a chain)."""

    pytest.importorskip("molsketch")
    source = _ribosome(tmp_path / "toyr.cif")
    rows = [
        {"group": "Le", "color": "#e08a2e"},
        {"group": "chain LE", "color": "#3f7fc0"},
        {"group": "chain le", "color": "#111111"},
    ]
    groups = _settings(source, rows, tmp_path)["colours"]["groups"]
    assert groups["Le"]["residues"] == 2 and not groups["Le"]["problem"]
    assert groups["chain LE"]["residues"] == 3
    assert groups["chain le"]["residues"] == 0
    assert "selects nothing" in groups["chain le"]["problem"]
    assert "Its chains are L5, LE, Le, A, B" in groups["chain le"]["hint"]
    # Handed to mol-sketch by the chain's own name, in its case.
    assert _handed(source, {"Le": "#e08a2e"}) == {"Le": "#e08a2e"}
    assert _handed(source, {"chain Le": "#e08a2e", "chain LE": "#3f7fc0"}) == {
        "Le": "#e08a2e",
        "LE": "#3f7fc0",
    }


def test_a_selection_matches_a_chain_in_its_case_and_residues_in_any() -> None:
    from flexo.structures import _Atom, _selection, _selection_problem

    def atom(chain: str, resn: str = "ALA") -> _Atom:
        return _Atom("C", resn, 1, chain, "CA", False, "L", "1", "L")

    atoms = (atom("LE"), atom("Le", "his"))
    picked = lambda text: [each.chain for each in atoms if _selection(text)(each)]  # noqa: E731
    assert picked("chain Le") == ["Le"] and picked("c. LE") == ["LE"]
    assert picked("chain LE+Le") == ["LE", "Le"] and picked("chain le") == []
    # A residue's name, an atom's and an element's in any case.
    assert picked("resn HIS") == ["Le"] and picked("name ca and elem c") == ["LE", "Le"]
    said = _selection_problem("chain le", atoms, "toyr", ["LE", "Le"])
    assert said == "Selects nothing in toyr. Its chains are LE, Le."


def test_an_mmcifs_entities_are_read_by_name_without_reading_it_through(tmp_path: Path) -> None:
    source = _ribosome(tmp_path / "toyr.cif")
    assert entity_names(str(source)) == {
        "1": "28S rRNA",
        "2": "60S ribosomal protein L8",
        "3": "40S ribosomal protein SA",
        "4": "Hemoglobin alpha chain",
    }
    # One entity, written as a list of tags and values, not as a loop.
    single = tmp_path / "one.cif"
    single.write_text(
        "data_ONE\n#\n_entity.id                1\n_entity.type              polymer\n"
        '_entity.pdbx_description  "Carbonic anhydrase 2"\n#\n_entity_poly.entity_id 1\n',
        encoding="utf-8",
    )
    assert entity_names(str(single)) == {"1": "Carbonic anhydrase 2"}
    # Read no further than its entities: what comes after them is not looked at.
    cut = tmp_path / "cut.cif"
    cut.write_bytes(_CIF_HEAD.encode() + b"loop_\n_atom_site.id\n\xff\xfe" * 3)
    assert len(entity_names(str(cut))) == 4
    # A file that is no mmCIF, or isn't there, names none.
    assert entity_names(str(tmp_path / "missing.cif")) == {}
    assert entity_names(str(tmp_path)) == {}


def test_a_pdb_files_molecules_are_read_from_its_compnd_records(tmp_path: Path) -> None:
    source = tmp_path / "4hhb.pdb"
    source.write_text(
        "HEADER    OXYGEN TRANSPORT                        07-MAR-84   4HHB              \n"
        "COMPND    MOL_ID: 1;                                                            \n"
        "COMPND   2 MOLECULE: HEMOGLOBIN (DEOXY) (ALPHA CHAIN);                          \n"
        "COMPND   3 CHAIN: A, C;                                                         \n"
        "COMPND   4 MOL_ID: 2;                                                           \n"
        "COMPND   5 MOLECULE: HEMOGLOBIN (DEOXY) (BETA CHAIN);                           \n"
        "COMPND   6 CHAIN: B, D                                                          \n"
        "ATOM      1  N   VAL A   1       6.204  16.869   4.854  1.00 49.05           N  \n",
        encoding="utf-8",
    )
    assert compound_names(str(source)) == (
        ("Hemoglobin (deoxy) (alpha chain)", ("A", "C")),
        ("Hemoglobin (deoxy) (beta chain)", ("B", "D")),
    )
    from flexo.structure_colours import Molecule, Residue, choices

    molecule = Molecule(
        tuple(Residue(f"VAL1.{chain}", "VAL", 1, chain, "", "X", False, "L") for chain in "ABCD"),
        (),
        (),
    )
    offered = choices(molecule, {}, compound_names(str(source)))
    # (A PDB file has no entities: a molecule of several chains is offered as them.)
    assert offered["entities"][0] == {
        "group": "chain A+C",
        "label": "Hemoglobin (deoxy) (alpha chain)",
        "chains": ["A", "C"],
    }
    assert offered["chains"][1] == {"chain": "B", "name": "Hemoglobin (deoxy) (beta chain)"}


def test_a_molecules_name_reads_as_a_person_writes_it() -> None:
    assert readable("28S rRNA (3773-MER)") == "28S rRNA"
    assert readable("CARBONIC ANHYDRASE II") == "Carbonic anhydrase II"
    assert readable("DNA POLYMERASE BETA") == "DNA polymerase beta"
    assert readable("60S RIBOSOMAL PROTEIN L7A") == "60S ribosomal protein L7A"
    assert readable("Ubiquitin-60S ribosomal protein L40") == "Ubiquitin-60S ribosomal protein L40"
    assert readable("?") == ""


# -- the studio's page (figure/structurepick.js, figure/structurecolours.js) --

OFFERED = {
    "chains": ["L5", "LE", "Le"],
    "colours": {
        "choices": {
            "subunits": [
                {"group": "subunit:L", "label": "Large Subunit", "chains": 2},
                {"group": "subunit:S", "label": "Small Subunit", "chains": 1},
            ],
            "entities": [],
            "chains": [
                {"chain": "L5", "name": "28S rRNA"},
                {"chain": "LE", "name": "60S ribosomal protein L8"},
                {"chain": "Le", "name": ""},
            ],
        },
        "ligands": [{"group": "ZN301", "label": "ZN 301"}],
    },
}


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_page_offers_a_row_what_the_molecule_has() -> None:
    from test_pages import _studio

    seen = _studio(
        "await (async () => {\n"
        'const pick = await import("/static/kinds/figure/structurepick.js");\n'
        f"const items = pick.pickItems({json.dumps(OFFERED)}, (text) => text);\n"
        'return items.map((item) => item === "-" ? "-" : item.title ? `# ${item.title}`'
        ' : [item.label, item.keys || "", item.run]);\n'
        "})()"
    )
    assert seen == [
        "# Subunits",
        ["Large Subunit", "", "subunit:L"],
        ["Small Subunit", "", "subunit:S"],
        "-",
        "# Chains",
        ["28S rRNA", "L5", "L5"],
        ["60S ribosomal protein L8", "LE", "LE"],
        ["Chain Le", "", "Le"],
        "-",
        "# Secondary Structure",
        ["Helices", "", "ss H"],
        ["Strands", "", "ss E"],
        ["Loops", "", "ss L and polymer"],
        "-",
        "# Ligands",
        ["Every Ligand", "", "hetatm and not water"],
        ["ZN 301", "", "ZN301"],
    ]
    # Settings from before the studio said what a molecule has: its chains, by their names.
    old = _studio(
        "await (async () => {\n"
        'const pick = await import("/static/kinds/figure/structurepick.js");\n'
        'return pick.pickItems({ chains: ["A"] }, (text) => text).slice(0, 2);\n'
        "})()"
    )
    assert old == [{"title": "Chains"}, {"label": "Chain A", "chain": "A", "run": "A"}]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_scheme_chosen_takes_back_the_structures_own_colours_under_it() -> None:
    """The owner's protein had its own helix, strand and loop colours: The Figure's scheme
    chosen changed nothing to be seen, as they win over it. Chosen, a scheme takes them back
    in the same step -- its own ink and its rows of colours stay."""

    from test_pages import _studio

    from flexo.studio.figure_parts import catalogue

    part = catalogue()["parts"]["structure"]
    field = next(each for each in part["fields"] if each["key"] == "properties.scheme")
    assert field["clears"][:3] == [
        "properties.style.palette.helix",
        "properties.style.palette.sheet",
        "properties.style.palette.loop",
    ]
    node = {
        "id": "protein",
        "kind": "structure",
        "properties": {
            "source": "3KS3.cif",
            "look": "flat",
            "style": {
                "palette": {
                    "helix": "#3f7fc0",
                    "sheet": "#e08a2e",
                    "loop": "#d9d5de",
                    "ink": "#242126",
                }
            },
            "colors": [{"group": "resi 94+96+119", "color": "#3a3060"}],
        },
    }
    seen = _studio(
        "await (async () => {\n"
        'const colours = await import("/static/kinds/figure/structurecolours.js");\n'
        "const valueAt = (item, key) => key.split('.').reduce("
        "(at, part) => (at == null ? undefined : at[part]), item);\n"
        f"const field = {json.dumps(field)}, node = {json.dumps(node)};\n"
        "const figure = { ...node, properties: { ...node.properties, scheme: 'figure' } };\n"
        "return {\n"
        "  figure: colours.schemeClears(field, node, 'figure', valueAt),\n"
        "  same: colours.schemeClears(field, node, null, valueAt),\n"
        "  back: colours.schemeClears(field, figure, null, valueAt),\n"
        "  other: colours.schemeClears({ key: 'properties.look' }, node, 'textbook', valueAt),\n"
        "};\n"
        "})()"
    )
    taken = {
        "properties.style.palette.helix": None,
        "properties.style.palette.sheet": None,
        "properties.style.palette.loop": None,
    }
    assert seen == {"figure": taken, "same": {}, "back": taken, "other": {}}
