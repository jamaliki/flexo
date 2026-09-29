"""A protein's map from its data: a structure file, or its UniProt entry.

Writing a protein's domains, sites, and secondary structure by hand is where a
domain map costs time. These read them instead, and return the arguments
``protein()`` takes, so a map is one line::

    figure.root.protein("ubq", **flexo.from_structure("1ubq.cif"))
    figure.root.protein("abl1", **flexo.from_uniprot("P00519"))
    figure.root.protein("abl1", **flexo.from_uniprot("P00519.json", sites=True))

- ``from_structure`` reads a PDB or mmCIF file (with ``gemmi``: ``pip install
  "flexo[structures]"``): the chain's sequence, and its secondary structure --
  the helix and sheet records the file carries or, for a model without them (a
  design, a prediction), an assignment of its own after DSSP's hydrogen bonds.
  Residues are numbered from 1 along the modelled chain.
- ``from_uniprot`` reads an entry from the UniProt REST service, or a saved
  entry (``https://rest.uniprot.org/uniprotkb/P00519.json``): its length,
  sequence, domains, regions, motifs, transmembrane helices, signal peptide,
  and disulfides; its modified residues and glycosylations with ``sites=True``,
  its variants with ``variants=True``, and its helices and strands with
  ``structure=True``.

Either result is a plain dict: edit it, add to its ``features``, or merge the
two (``{**uniprot, "secondary": structure["secondary"]}``) before drawing.
"""

from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from collections.abc import Iterable
from pathlib import Path

__all__ = ["assign_secondary", "from_structure", "from_uniprot"]

_UNIPROT = "https://rest.uniprot.org/uniprotkb/{accession}.json"


# -- structures ---------------------------------------------------------------------------


def from_structure(
    path: str | Path,
    chain: str | None = None,
    *,
    assign: bool = False,
    numbering: str = "chain",
) -> dict:
    """``protein()``'s arguments for ``chain`` (the first protein chain by default)
    of the structure at ``path``: ``length``, ``sequence``, and ``secondary``.

    The file's own helix and sheet records are used when it has them;
    ``assign=True`` (or a file without them) assigns the secondary structure from
    the backbone's hydrogen bonds instead.

    ``numbering="chain"`` numbers the modelled residues from 1. ``"author"`` keeps
    the file's own residue numbers -- a domain modelled from residue 151 starts at
    151, so its secondary structure lines up with the full-length protein's map:
    ``length`` is then the last residue's number, and ``secondary_start`` and
    ``sequence_start`` the first's (residues the model lacks are loop, ``-``).
    """

    if numbering not in {"chain", "author"}:
        raise ValueError(f'numbering is "chain" or "author", not "{numbering}".')

    try:
        import gemmi
    except ImportError:  # pragma: no cover - exercised without the extra
        raise ImportError(
            'Reading a structure needs gemmi: pip install "flexo[structures]" (or gemmi).'
        ) from None
    structure = gemmi.read_structure(str(path))
    structure.setup_entities()
    model = structure[0]
    candidates = [
        item for item in model if item.get_polymer().check_polymer_type().name.startswith("Peptide")
    ]
    if chain is not None:
        candidates = [item for item in candidates if item.name == chain]
    if not candidates:
        where = f"chain {chain}" if chain is not None else "any protein chain"
        raise ValueError(f"{path}: found no {where}.")
    polymer = candidates[0].get_polymer()
    residues = list(polymer)
    sequence = "".join(_letter(gemmi, residue.name) for residue in residues)
    by_author = {
        (residue.seqid.num, residue.seqid.icode): index for index, residue in enumerate(residues)
    }
    letters = ["C"] * len(residues)
    recorded = False
    if not assign:
        name = candidates[0].name
        for helix in structure.helices:
            if helix.start.chain_name != name:
                continue
            recorded = True
            _mark(letters, by_author, helix.start.res_id.seqid, helix.end.res_id.seqid, "H")
        for sheet in structure.sheets:
            for strand in sheet.strands:
                if strand.start.chain_name != name:
                    continue
                recorded = True
                _mark(letters, by_author, strand.start.res_id.seqid, strand.end.res_id.seqid, "E")
    if not recorded:
        letters = list(assign_secondary(_backbone(residues)))
    if numbering == "author":
        numbers = [residue.seqid.num for residue in residues]
        first, last = min(numbers), max(numbers)
        if first >= 1:
            span_letters = ["-"] * (last - first + 1)
            span_sequence = ["-"] * (last - first + 1)
            for residue, letter, code in zip(residues, letters, sequence, strict=True):
                span_letters[residue.seqid.num - first] = letter
                span_sequence[residue.seqid.num - first] = code
            info = structure.info
            title = (info["_struct.title"] if "_struct.title" in info else "") or structure.name  # noqa: SIM401
            return {
                "length": last,
                "sequence": "".join(span_sequence),
                "sequence_start": first,
                "secondary": "".join(span_letters),
                "secondary_start": first,
                "label": title.strip() if len(title.strip()) <= 60 else structure.name,
            }
    info = structure.info
    title = (info["_struct.title"] if "_struct.title" in info else "") or structure.name  # noqa: SIM401 - InfoMap has no get
    return {
        "length": len(residues),
        "sequence": sequence,
        "secondary": "".join(letters),
        "label": title.strip() if len(title.strip()) <= 60 else structure.name,
    }


def _letter(gemmi, name: str) -> str:
    """A residue's one-letter code; a modified one (MSE) as its parent (M)."""

    found = gemmi.find_tabulated_residue(name)
    code = found.one_letter_code if found is not None else " "
    return code.upper() if code.strip() else "X"


def _mark(letters: list[str], by_author: dict, start, end, letter: str) -> None:
    first = by_author.get((start.num, start.icode))
    last = by_author.get((end.num, end.icode))
    if first is None or last is None:
        return
    for index in range(min(first, last), max(first, last) + 1):
        letters[index] = letter


type _Vector = tuple[float, float, float]


def _backbone(residues: Iterable) -> list[dict[str, _Vector] | None]:
    atoms = []
    for residue in residues:
        found: dict[str, _Vector] = {}
        for name in ("N", "CA", "C", "O"):
            atom = residue.find_atom(name, "*")
            if atom is not None:
                found[name] = (atom.pos.x, atom.pos.y, atom.pos.z)
        atoms.append(found if len(found) == 4 else None)
    return atoms


def _sub(a: _Vector, b: _Vector) -> _Vector:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _distance(a: _Vector, b: _Vector) -> float:
    return math.dist(a, b)


def assign_secondary(backbone: list[dict[str, _Vector] | None]) -> str:
    """A DSSP-style string for a chain's backbone (``N``, ``CA``, ``C``, ``O`` of each
    residue, ``None`` where one is missing): ``H`` alpha helix, ``G`` 3-10 helix,
    ``E`` strand, ``B`` lone bridge, ``T`` turn, ``C`` anything else.

    After Kabsch and Sander's DSSP: a hydrogen bond wherever the electrostatic
    energy between a C=O and an N-H is below -0.5 kcal/mol; a helix where two
    consecutive n-turns start; a strand where bridges between two stretches
    ladder. It leaves out DSSP's pi-helices and bends, and its finer points of
    ladder bulges -- enough to draw, not to publish as DSSP.
    """

    n = len(backbone)
    hydrogens: list[_Vector | None] = [None] * n
    for i in range(1, n):
        here, before = backbone[i], backbone[i - 1]
        if here is None or before is None:
            continue
        co = _sub(before["C"], before["O"])
        length = math.sqrt(sum(value * value for value in co)) or 1.0
        hydrogens[i] = tuple(here["N"][k] + co[k] / length for k in range(3))  # type: ignore[assignment]

    def energy(i: int, j: int) -> float:
        """C=O of ``i`` to N-H of ``j``."""

        a, b, h = backbone[i], backbone[j], hydrogens[j]
        if a is None or b is None or h is None:
            return 0.0
        r_on = _distance(a["O"], b["N"])
        r_ch = _distance(a["C"], h)
        r_oh = _distance(a["O"], h)
        r_cn = _distance(a["C"], b["N"])
        if min(r_on, r_ch, r_oh, r_cn) < 0.5:
            return -9.9
        return 0.084 * 332.0 * (1 / r_on + 1 / r_ch - 1 / r_oh - 1 / r_cn)

    bonds: set[tuple[int, int]] = set()
    for i in range(n):
        if backbone[i] is None:
            continue
        for j in range(n):
            if abs(i - j) < 2 or backbone[j] is None:
                continue
            if _distance(backbone[i]["CA"], backbone[j]["CA"]) > 9.0:  # type: ignore[index]
                continue
            if energy(i, j) < -0.5:
                bonds.add((i, j))

    def bond(i: int, j: int) -> bool:
        return (i, j) in bonds

    letters = ["C"] * n
    for turn, letter in ((3, "G"), (4, "H")):
        starts = [i for i in range(n - turn) if bond(i, i + turn)]
        for i in starts:
            if i - 1 in starts:
                for k in range(i, i + turn):
                    if letter == "H" or letters[k] == "C":
                        letters[k] = letter
    for turn in (3, 4, 5):
        for i in range(n - turn):
            if bond(i, i + turn):
                for k in range(i + 1, i + turn):
                    if letters[k] == "C":
                        letters[k] = "T"
    partners: dict[int, set[int]] = {}
    for i in range(1, n - 1):
        for j in range(1, n - 1):
            if abs(i - j) < 3:
                continue
            parallel = (bond(i - 1, j) and bond(j, i + 1)) or (bond(j - 1, i) and bond(i, j + 1))
            antiparallel = (bond(i, j) and bond(j, i)) or (
                bond(i - 1, j + 1) and bond(j - 1, i + 1)
            )
            if parallel or antiparallel:
                partners.setdefault(i, set()).add(j)
    for i, others in partners.items():
        laddered = any(
            (i + step) in partners
            and any(abs(o2 - o1) == 1 for o1 in others for o2 in partners[i + step])
            for step in (-1, 1)
        )
        if letters[i] not in {"H"}:
            letters[i] = "E" if laddered else ("B" if letters[i] in {"C", "T"} else letters[i])
    return "".join(letters)


# -- UniProt ------------------------------------------------------------------------------

_SPANS = {
    "Domain": "domain",
    "Region": "region",
    "Motif": "motif",
    "Transmembrane": "transmembrane",
    "Intramembrane": "transmembrane",
    "Signal": "signal",
    "Transit peptide": "signal",
    "Propeptide": "signal",
    "Zinc finger": "domain",
    "Coiled coil": "region",
    "Repeat": "domain",
}
_STRUCTURE = {"Helix": "helix", "Beta strand": "strand", "Turn": "turn"}


def from_uniprot(
    entry: str | Path,
    *,
    sites: bool = False,
    variants: bool = False,
    structure: bool = False,
    disordered: bool = True,
    timeout: float = 20.0,
) -> dict:
    """``protein()``'s arguments from a UniProt entry: an accession (``"P00519"``),
    fetched from the UniProt REST service, or a saved entry's JSON file.

    Returns ``length``, ``sequence``, ``label`` (the gene name), and ``features``:
    domains, regions (``disordered=False`` leaves out the disordered ones),
    motifs, transmembrane and signal segments, and disulfides; modified residues
    and glycosylation sites with ``sites=True``; natural variants and mutagenesis
    with ``variants=True``; helices, strands, and turns with ``structure=True``.
    """

    data = _uniprot_entry(entry, timeout)
    sequence = data.get("sequence", {}).get("value", "")
    length = int(data.get("sequence", {}).get("length") or len(sequence))
    features: list[dict] = []
    for item in data.get("features", []):
        kind = item.get("type", "")
        start, end = _location(item)
        if start is None or end is None:
            continue
        description = (item.get("description") or "").strip()
        if kind in _SPANS:
            if kind == "Region" and description.lower().startswith("disordered") and not disordered:
                continue
            feature = {"type": _SPANS[kind], "start": start, "end": end}
            if description and _SPANS[kind] != "transmembrane":
                feature["label"] = _short(description)
            features.append(feature)
        elif kind == "Disulfide bond":
            features.append({"type": "disulfide", "start": start, "end": end})
        elif kind in _STRUCTURE and structure:
            features.append({"type": _STRUCTURE[kind], "start": start, "end": end})
        elif kind in {"Modified residue", "Glycosylation", "Lipidation"} and sites:
            residue = sequence[start - 1] if 0 < start <= len(sequence) else ""
            features.append(
                {
                    "type": _modification(kind, description),
                    "at": start,
                    "label": f"{residue}{start}",
                }
            )
        elif kind in {"Natural variant", "Mutagenesis"} and variants and start == end:
            change = item.get("alternativeSequence", {})
            original = change.get("originalSequence") or (
                sequence[start - 1] if 0 < start <= len(sequence) else ""
            )
            replaced = (change.get("alternativeSequences") or [""])[0]
            if original and replaced and len(original) == 1 and len(replaced) == 1:
                features.append(
                    {"type": "mutation", "at": start, "label": f"{original}{start}{replaced}"}
                )
    genes = data.get("genes") or []
    name = (genes[0].get("geneName", {}).get("value") if genes else None) or data.get(
        "primaryAccession", "protein"
    )
    return {"length": length, "sequence": sequence, "label": name, "features": features}


def _uniprot_entry(entry: str | Path, timeout: float) -> dict:
    path = Path(entry)
    if path.suffix == ".json" or path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    accession = str(entry).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", accession):
        raise ValueError(f"{entry!r} is neither a UniProt accession nor a saved entry.")
    url = _UNIPROT.format(accession=accession)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as error:
        raise ValueError(
            f"Could not fetch {accession} from UniProt ({error}). Save {url} and pass its path."
        ) from None


def _location(item: dict) -> tuple[int | None, int | None]:
    location = item.get("location", {})

    def value(key: str) -> int | None:
        point = location.get(key, {})
        number = point.get("value")
        return int(number) if isinstance(number, int | float) else None

    return value("start"), value("end")


def _short(text: str) -> str:
    """A UniProt description trimmed to a name: ``"Protein kinase; ..."`` is ``Protein kinase``."""

    return text.split(";")[0].strip()


def _modification(kind: str, description: str) -> str:
    lowered = description.lower()
    if kind == "Glycosylation":
        return "glycosylation"
    for word, name in (
        ("phospho", "phosphorylation"),
        ("acetyl", "acetylation"),
        ("methyl", "methylation"),
        ("ubiquitin", "ubiquitination"),
    ):
        if word in lowered:
            return name
    return "modification"
