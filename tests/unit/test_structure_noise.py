"""A structure noised as a diffusion model draws it on its way, from a random coil to the
file: one trajectory for each file, seed and what is held, a moment of it at each noise."""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from flexo import structure_noise as sn  # noqa: E402

DATA = Path(__file__).parent / "data"
SOURCE = DATA / "1a7g.cif"


@pytest.fixture(autouse=True)
def _own_cache(tmp_path, monkeypatch):
    """Trajectories kept in a folder of the test's own, and none from before in memory."""

    monkeypatch.setattr(sn, "_cache_folder", lambda: tmp_path / "noise")
    sn._KEPT_RUNS.clear()
    sn._KEPT_NOISED.clear()
    sn._KEPT_MOLECULES.clear()
    yield
    sn._KEPT_RUNS.clear()
    sn._KEPT_NOISED.clear()


def _text() -> str:
    return SOURCE.read_text()


def _chain():
    noised = sn.noised(_text())
    (_, _, chain), trajectory = noised.chains[0], noised.trajectories[0]
    return noised, chain, trajectory


def _distances(points):
    return np.linalg.norm(points[:, None] - points[None], axis=-1)


def _bonds(x, bonded):
    return np.linalg.norm(np.diff(x, axis=0), axis=1)[bonded]


def test_a_trajectory_is_the_same_for_the_same_seed_and_another_for_another() -> None:
    _, chain, trajectory = _chain()
    again = sn.fold(chain, 0, "E")
    assert np.array_equal(trajectory, again)
    other = sn.fold(chain, 1, "E")
    assert not np.allclose(other[0], trajectory[0])
    # (Each is the file at its end, whatever the seed.)
    assert np.array_equal(other[-1], trajectory[-1])


def test_the_chain_is_never_broken_nor_bent_out_of_a_proteins_shape() -> None:
    _, chain, trajectory = _chain()
    bonded = np.asarray(chain.bonded)
    own = _bonds(np.asarray(chain.trace), bonded)
    shape = sn._Shape(chain)
    # Every moment, a snapshot or a blend of two: the bonds the file's (never so long that
    # mol-sketch would break the trace, nor squashed), the angles a protein's.
    for noise in np.linspace(0, 1, 401):
        x = sn.at_noise(trajectory, noise, shape)
        bonds = _bonds(x, bonded)
        assert bonds.max() <= min(4.2, own.max() + 0.05), noise
        assert bonds.min() >= own.min() - 0.1, noise
        angles = sn._angles(x, bonded)
        assert angles.min() >= 79 and angles.max() <= 151, noise


def test_noise_zero_is_the_file_itself() -> None:
    noised, chain, trajectory = _chain()
    assert np.allclose(sn.at_noise(trajectory, 0), np.asarray(chain.trace), atol=1e-5)
    xyz, _ = noised.at(0)
    assert np.array_equal(xyz, noised.molecule.xyz)
    assert sn._Molecule(noised.text(0)).xyz.tolist() == noised.molecule.xyz.tolist()
    # (Drawn at noise 0, a structure is the file itself: it is not noised at all.)
    from flexo.structures import _noised

    class Asked:
        noise = 0.0

    assert _noised(Asked()) is None


def test_noise_one_is_a_coil_and_the_way_to_the_file_is_paced() -> None:
    _, chain, trajectory = _chain()
    x0 = np.asarray(chain.trace)

    def off(noise):
        x = sn._laid_over(sn.at_noise(trajectory, noise), x0)
        return float(np.sqrt(((x - x0) ** 2).sum(1).mean()))

    prior = off(1)
    assert prior > 8
    # Each moment nearer the file than the one before it, by the pace.
    assert prior >= off(0.3) > off(0.16) > off(0.06) > 0
    assert off(0.3) <= 0.75 * prior and off(0.16) <= 0.3 * prior and off(0.06) <= 0.12 * prior
    # The prior's turns are a protein's: none straight.
    angles = sn._angles(sn.at_noise(trajectory, 1), np.asarray(chain.bonded))
    assert angles.min() >= 84 and angles.max() <= 136


def test_helices_form_right_handed_and_are_drawn_only_once_formed() -> None:
    noised, chain, trajectory = _chain()
    x0 = np.asarray(chain.trace)
    bonded = np.asarray(chain.bonded)
    helical = [k for k, kind in enumerate(noised.file_ss[0]) if kind == "H"]
    quads = np.array(
        [
            k
            for k in np.flatnonzero(bonded[:-2] & bonded[1:-1] & bonded[2:])
            if k + 1 in helical and k + 2 in helical
        ]
    )
    assert len(quads)
    x = sn.at_noise(trajectory, 0.16)
    turned = np.sign(sn._volumes(x, quads)) == np.sign(sn._volumes(x0, quads))
    assert turned.mean() > 0.95
    # A coil has nothing drawn as helix; the file at noise 0 has the file's.
    assert not sn._formed(x0, sn.at_noise(trajectory, 1), bonded).any()
    assert sn._formed(x0, x0, bonded).all()
    _, spans = noised.at(1)
    assert spans == []
    text = noised.text(1)
    assert sn._Molecule(text).records  # one record naming no residue: all of it loops


def test_held_residues_and_ligands_do_not_move_and_the_rest_moves_whole() -> None:
    molecule = sn._Molecule(_text())
    residues = [g for g in molecule.groups if g.trace >= 0 and not g.het]
    held = frozenset((g.chain, g.resi, g.resn) for g in (residues[10], residues[40])) | frozenset(
        (g.chain, g.resi, g.resn) for g in molecule.groups if g.resn == "SO4"
    )
    noised = sn.noised(_text(), 0, held)
    groups = molecule.groups
    fixed = [
        index
        for group in groups
        if (group.chain, group.resi, group.resn) in held
        for index in group.atoms
    ]
    assert fixed
    for noise in (1.0, 0.5, 0.3, 0.16, 0.06):
        xyz, _ = noised.at(noise)
        assert np.array_equal(xyz[fixed], molecule.xyz[fixed])
        # Every residue and water moves rigidly: its atoms keep their distances.
        for group in groups[::7]:
            atoms = group.atoms
            assert np.allclose(_distances(molecule.xyz[atoms]), _distances(xyz[atoms]), atol=1e-6)
    # The held C-alphas sit where the file has them in the trace at every noise, too.
    (_, _, chain), trajectory = noised.chains[0], noised.trajectories[0]
    held_trace = np.asarray(chain.fixed)
    assert held_trace.sum() == 2
    for noise in np.linspace(0, 1, 21):
        x = sn.at_noise(trajectory, noise)
        assert np.abs(x[held_trace] - np.asarray(chain.trace)[held_trace]).max() < 1e-4


def test_a_ligand_not_held_moves_with_the_residue_nearest_it() -> None:
    molecule = sn._Molecule(_text())
    noised = sn.noised(_text())
    sulphate = next(k for k, group in enumerate(molecule.groups) if group.resn == "SO4")
    carrier = noised.carrier[sulphate]
    members = [k for _, chain_members, _ in noised.chains for k in chain_members]
    residue = molecule.groups[members[carrier]]
    atoms = molecule.groups[sulphate].atoms + residue.atoms
    xyz, _ = noised.at(0.3)
    assert np.allclose(_distances(molecule.xyz[atoms]), _distances(xyz[atoms]), atol=1e-6)


def test_a_noised_file_reads_back_as_the_same_atoms_in_either_format() -> None:
    gemmi = pytest.importorskip("gemmi")
    structure = gemmi.read_structure(str(SOURCE))
    pdb = structure.make_pdb_string()
    for text in (_text(), pdb):
        noised = sn.noised(text, 3)
        out = noised.text(0.3)
        again = sn._Molecule(out)
        xyz, spans = noised.at(0.3)
        assert again.cif == noised.molecule.cif
        assert len(again.xyz) == len(noised.molecule.xyz)
        assert np.abs(again.xyz - xyz).max() < 6e-4  # (written to a thousandth)
        assert [g.resi for g in again.groups] == [g.resi for g in noised.molecule.groups]
        assert len(sn._records(again)) == len(spans) or not spans
        # No two noise levels begin alike (mol-sketch knows a file by its ends).
        assert noised.text(0.3)[:64] != noised.text(0.32)[:64]


def test_a_trajectory_is_worked_out_once_and_kept_on_disk(monkeypatch) -> None:
    sn.noised(_text()).text(0.3)
    assert list(sn._cache_folder().glob("*.npy"))
    sn._KEPT_RUNS.clear()
    sn._KEPT_NOISED.clear()

    def refold(*args, **kwargs):
        raise AssertionError("worked out again")

    monkeypatch.setattr(sn, "fold", refold)
    sn.noised(_text()).text(0.16)
    # Another seed is another run.
    with pytest.raises(AssertionError, match="worked out again"):
        sn.noised(_text(), seed=2)


def test_the_cα_assignment_is_mol_sketchs() -> None:
    pytest.importorskip("molsketch")
    gemmi = pytest.importorskip("gemmi")
    import molsketch as ms

    structure = gemmi.read_structure(str(SOURCE))
    structure.helices.clear()
    structure.sheets.clear()
    text = structure.make_pdb_string()
    scene = ms.load(text, name="plain", format="pdb").scene()
    atoms = scene["keyframes"][0]["atoms"].values()
    theirs = [atom["ss"] for atom in atoms if atom.get("name") == "CA" and not atom.get("het")]
    molecule = sn._Molecule(text)
    trace = [molecule.xyz[g.trace] for g in molecule.groups if g.trace >= 0 and not g.het]
    assert sn.assigned(np.array(trace)) == theirs


def test_a_noised_structure_is_drawn_and_seen_as_the_file_is(tmp_path: Path) -> None:
    pytest.importorskip("molsketch")
    import flexo
    from flexo.compiler import compile_figure
    from flexo.lint import lint_compilation
    from flexo.serialization import dump_figure
    from flexo.studio.figure_kind import FigureKind

    with flexo.Figure("noised") as figure:
        row = figure.root.row("row", gap=10)
        for name, noise in (("t30", 0.3), ("t2", 0.02), ("t0", None)):
            row.structure(
                name,
                SOURCE,
                look="flat",
                yaw=30,
                pitch=-15,
                noise=noise,
                fixed="resi 300",
                seed=4,
                width=80,
                height=80,
            )
    compiled = compile_figure(figure.spec)
    assert not lint_compilation(compiled).diagnostics
    text = dump_figure(figure.spec)
    assert "noise: 0.3" in text and "seed: 4" in text

    def view(name):
        action = {"do": "structure-view", "id": f"row.{name}"}
        return FigureKind().act({"text": text}, action, tmp_path)["view"]

    views = {name: view(name) for name in ("t2", "t0")}
    # Dragged round, it turns from its own yaw and pitch, and lies as the file does.
    assert views["t2"]["camera"]["yaw"] == 30 and views["t2"]["camera"]["pitch"] == -15
    near = np.array([p for chain in views["t2"]["chains"] for p in chain])
    file = np.array([p for chain in views["t0"]["chains"] for p in chain])
    assert near.shape == file.shape
    assert np.sqrt(((near - near.mean(0)) - (file - file.mean(0))) ** 2).sum(1).mean() < 1.5


def test_a_noise_out_of_range_or_a_seed_not_whole_is_said() -> None:
    import flexo
    from flexo.structures import structure_problem
    from flexo.themes import figure_style

    for settings, said in (
        ({"noise": 1.5}, "noise"),
        ({"noise": 0.3, "seed": 1.5}, "seed"),
        ({"noise": "high"}, "noise"),
    ):
        with flexo.Figure("bad") as figure:
            figure.root.structure("model", SOURCE, **settings)
        problem = structure_problem(figure.spec.nodes[0], figure_style(figure.spec))
        assert problem is not None and problem.code == f"structure.{said}"


def test_a_fixed_selection_that_holds_nothing_is_said_where_it_is_typed(tmp_path: Path) -> None:
    pytest.importorskip("molsketch")
    import flexo
    from flexo.serialization import dump_figure
    from flexo.studio.figure_kind import FigureKind

    with flexo.Figure("held") as figure:
        figure.root.structure("model", SOURCE, noise=0.3, fixed="resi 9000")
    action = {"do": "structure-settings", "id": "model"}
    settings = FigureKind().act({"text": dump_figure(figure.spec)}, action, tmp_path)["settings"]
    assert "Selects nothing" in settings["selections"]["properties.fixed"]
