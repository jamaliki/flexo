"""What a structure file names its molecules, as a person would read them: an mmCIF's
entities by their descriptions (``_entity.pdbx_description``: ``28S rRNA (3773-MER)`` read
as ``28S rRNA``), a PDB file's chains by the molecule its COMPND records give them
(``HEMOGLOBIN (DEOXY) (ALPHA CHAIN)`` as ``Hemoglobin (deoxy) (alpha chain)``).

mol-sketch reads an mmCIF's entities to tell a ribosome's subunits apart, but keeps their
names to itself: they are read here, from the file, and only as far as they go -- an mmCIF's
``_entity`` category is near its top, a PDB file's COMPND records at its head, so a
ribosome's 25 MB are not read through for them.
"""

from __future__ import annotations

import functools
import os
import re
from pathlib import Path

from flexo.structures import ACRONYMS

_PID = re.compile(r"[0-9][A-Za-z0-9]{3}")


def structure_file(source: str) -> Path | None:
    """The file a structure's ``source`` is read from: the file itself, or a PDB entry's as a
    bundle keeps it or mol-sketch downloaded it (its cache) -- None for one there is no file
    of yet."""

    path = Path(source)
    if path.is_file():
        return path
    if not _PID.fullmatch(source.strip()):
        return None
    from flexo.bundle import kept_entry
    from flexo.confine import folder_root

    kept = kept_entry(source, folder_root.get())
    if kept is not None:
        return kept
    cache = Path(os.environ.get("MOLSKETCH_CACHE", Path.home() / ".cache" / "molsketch"))
    fetched = cache / f"{source.strip().upper()}.cif"
    return fetched if fetched.is_file() else None


def entity_names(source: str) -> dict[str, str]:
    """An mmCIF's entities by their names, by entity ID (``{"1": "28S rRNA"}``): none for a
    file that is no mmCIF, names none, or can't be read."""

    path = structure_file(source)
    if path is None or path.suffix.lower() not in (".cif", ".mmcif"):
        return {}
    try:
        return dict(_entity_names(str(path), path.stat().st_mtime))
    except OSError:
        return {}


def compound_names(source: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """A PDB file's molecules, as its COMPND records give them: each one's name and its
    chains, in the file's order. None for a file that is no PDB file, or names none."""

    path = structure_file(source)
    if path is None or path.suffix.lower() not in (".pdb", ".ent"):
        return ()
    try:
        return _compounds(str(path), path.stat().st_mtime)
    except OSError:
        return ()


def readable(name: str) -> str:
    """A molecule's name as a person writes it: without a polymer's length (``(3773-MER)``),
    and one in capitals in sentence case -- an acronym (RNA, ATP), a word with a digit (L7a,
    P53) or a Roman numeral (II) as written."""

    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"\s*\(\d+-MER\)$", "", name, flags=re.IGNORECASE).strip()
    if name in ("?", "."):
        return ""
    if not name.isupper():
        return name

    def piece(word: str) -> str:
        letters = re.sub(r"[^A-Z]", "", word)
        kept = letters in ACRONYMS or re.fullmatch(r"[IVX]{2,4}", letters) is not None
        return word if kept or any(ch.isdigit() for ch in word) else word.lower()

    words = " ".join("-".join(piece(part) for part in word.split("-")) for word in name.split())
    return words[:1].upper() + words[1:]


# -- an mmCIF's _entity category --

_TOKEN = re.compile(r"""'(.*?)'(?=\s|$)|"(.*?)"(?=\s|$)|(\S+)""")
"""A value of an mmCIF row: quoted (a quote closes it only where a space follows), or bare."""


@functools.lru_cache(maxsize=16)
def _entity_names(path: str, stamp: float) -> tuple[tuple[str, str], ...]:
    del stamp  # part of the cache key: an edited file is read again
    with open(path, encoding="utf-8", errors="replace") as file:
        lines = iter(file)
        for line in lines:
            start = line.lstrip()
            if start.startswith("_entity."):
                return _named(_pairs(_category(line, lines, looped=False)))
            if start.startswith("loop_"):
                head = next(lines, "")
                if head.lstrip().startswith("_entity."):
                    return _named(_rows(_category(head, lines, looped=True)))
    return ()


def _category(first: str, lines, *, looped: bool) -> list[tuple[str, bool]]:
    """The tags and values of the category that starts at ``first``, read up to where the
    next one starts: each as (its text, whether it is a tag)."""

    found: list[tuple[str, bool]] = []
    line = first
    while line is not None:
        if line.startswith(";"):
            # A value of lines of its own, up to the line that starts with ; again.
            text = [line[1:].rstrip("\n")]
            for line in lines:  # (read on, from the same file)
                if line.startswith(";"):
                    break
                text.append(line.rstrip("\n"))
            found.append(("\n".join(text).strip(), False))
            line = next(lines, None)
            continue
        if found and _ends(line.lstrip(), looped, found[-1][1]):
            break
        for match in _TOKEN.finditer(line):
            quoted, double, bare = match.groups()
            if bare is not None and bare.startswith("#"):
                break  # (the rest of the line a comment)
            value = quoted if quoted is not None else double if double is not None else bare
            found.append((value, bare is not None and bare.startswith("_")))
        line = next(lines, None)
    return found


def _ends(start: str, looped: bool, after_tag: bool) -> bool:
    """Whether a line starting ``start`` is past the category: another's tag or loop, or --
    its values begun -- a tag of its own (a loop's rows end there) or a comment."""

    if start.startswith(("loop_", "data_", "save_")):
        return True
    if start.startswith("_"):
        return not start.startswith("_entity.") or (looped and not after_tag)
    return start.startswith("#") and not after_tag


def _rows(found: list[tuple[str, bool]]) -> list[dict[str, str]]:
    tags = [value for value, tag in found if tag]
    values = [value for value, tag in found if not tag]
    if not tags:
        return []
    return [
        dict(zip(tags, values[at : at + len(tags)], strict=False))
        for at in range(0, len(values) - len(tags) + 1, len(tags))
    ]


def _pairs(found: list[tuple[str, bool]]) -> list[dict[str, str]]:
    row: dict[str, str] = {}
    for at, (value, tag) in enumerate(found):
        if tag and at + 1 < len(found) and not found[at + 1][1]:
            row[value] = found[at + 1][0]
    return [row]


def _named(rows: list[dict[str, str]]) -> tuple[tuple[str, str], ...]:
    named = []
    for row in rows:
        entity, name = row.get("_entity.id"), readable(row.get("_entity.pdbx_description", ""))
        if entity and name:
            named.append((entity, name))
    return tuple(named)


# -- a PDB file's COMPND records --


@functools.lru_cache(maxsize=16)
def _compounds(path: str, stamp: float) -> tuple[tuple[str, tuple[str, ...]], ...]:
    del stamp
    said: list[str] = []
    with open(path, encoding="utf-8", errors="replace") as file:
        for line in file:
            if line.startswith(("ATOM", "HETATM", "MODEL")):
                break
            if line.startswith("COMPND"):
                said.append(line[10:80].rstrip())
    molecules: list[tuple[str, tuple[str, ...]]] = []
    name, chains = "", ()
    for entry in " ".join(part.strip() for part in said).split(";"):
        key, colon, value = entry.partition(":")
        key, value = key.strip().upper(), value.strip()
        if not colon:
            continue
        if key == "MOL_ID":
            if name and chains:
                molecules.append((name, chains))
            name, chains = "", ()
        elif key == "MOLECULE":
            name = readable(value)
        elif key == "CHAIN":
            chains = tuple(chain.strip() for chain in value.split(",") if chain.strip())
    if name and chains:
        molecules.append((name, chains))
    return tuple(molecules)
