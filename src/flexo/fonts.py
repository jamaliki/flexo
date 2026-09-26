"""Font discovery and face selection: any family, by name, measured exactly.

Flexo measures every word before it lays anything out, so the font a figure is
*measured* in and the font it is *drawn* in have to be the same file. This module
is where a family name becomes that file:

- **bundled families** ship with Flexo and always resolve, on every machine:
  IBM Plex Sans, Figtree, Liberation Sans (metric-compatible with Arial and
  Helvetica), Latin Modern Roman (the TeX/TikZ look), and the handwriting
  faces Kalam and Caveat (their Latin subsets; the ``sketch`` theme's type). Their licences
  (SIL OFL 1.1 and the GUST Font License) allow embedding and redistribution,
  so they are also the families Flexo embeds in the SVG and hands to Inkscape
  for export.
- **registered fonts** are files an author points at with ``register_font``,
  or directories named in ``FLEXO_FONT_PATH``.
- **system fonts** are found in the platform's standard font directories the
  first time a name is not bundled or registered. The scan is cached on disk.

A face is chosen for a weight and a style the way CSS chooses one, so the face a
browser or Inkscape draws for ``font-weight="500"`` is the face Flexo measured.
A variable font takes the weight directly on its ``wght`` axis.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from importlib import resources
from io import BytesIO
from pathlib import Path

import uharfbuzz as hb
from fontTools.ttLib import TTCollection, TTFont

from flexo.diagnostics import Diagnostic, FlexoError

# Font files in the wild carry small defects (a stray byte in ``post``, an odd
# timestamp) that fontTools reports and then reads past; none of them matter to
# Flexo, and a figure build should not print them.
logging.getLogger("fontTools").setLevel(logging.ERROR)

FONT_SUFFIXES = (".ttf", ".otf", ".ttc", ".otc")

METRIC_SUBSTITUTES = {
    "arial": "Liberation Sans",
    "helvetica": "Liberation Sans",
    "helvetica neue": "Liberation Sans",
    "arimo": "Liberation Sans",
}
"""Families a bundled face can stand in for without moving a single glyph.

Liberation Sans is drawn to Arial's advance widths, and Arial to Helvetica's, so
a figure written for a journal that asks for Helvetica compiles to the same
geometry on a machine that has none of them. The SVG still asks for the family
the author named first, so a reader who has it sees it.
"""

GENERIC_FAMILIES = frozenset({"sans-serif", "serif", "monospace", "cursive", "fantasy"})


@dataclass(frozen=True, slots=True)
class FontFace:
    """One face of one family: a file (and index inside a collection)."""

    family: str
    source: str
    index: int
    weight: int
    weight_min: int
    weight_max: int
    italic: bool
    bundled: bool = False

    @property
    def variable(self) -> bool:
        return self.weight_min != self.weight_max

    def covers_weight(self, weight: int) -> bool:
        return self.weight_min <= weight <= self.weight_max


@dataclass(frozen=True, slots=True)
class LoadedFace:
    """The measured facts of one face, read once."""

    face: FontFace
    raw: bytes
    upem: int
    ascent: int
    descent: int
    subscript_drop: int
    codepoints: frozenset[int]
    hb_face: hb.Face
    cap_height: int = 0
    superscript_rise: int = 0
    outlines: bool = True
    """Whether the glyphs are plain outlines, not bitmaps or colour layers (emoji)."""

    def has(self, character: str) -> bool:
        return ord(character) in self.codepoints


def _bundled_directory() -> Path:
    return Path(str(resources.files("flexo.resources.fonts")))


def bundled_font_directory() -> Path:
    """Where the bundled font files live, for handing to an external renderer."""

    return _bundled_directory()


def _names(font: TTFont) -> tuple[str, set[str]]:
    table = font["name"]
    preferred = table.getDebugName(16) or table.getDebugName(1) or ""
    aliases = {
        name
        for name in (
            table.getDebugName(1),
            table.getDebugName(16),
            table.getDebugName(21),
            table.getDebugName(4),
        )
        if name
    }
    return preferred, aliases


def _is_italic(font: TTFont) -> bool:
    os2 = font.get("OS/2", None)
    if os2 is not None and os2.fsSelection & (1 | 1 << 9):
        return True
    if "head" in font and font["head"].macStyle & 2:
        return True
    return "post" in font and font["post"].italicAngle != 0


def _describe(source: Path, index: int, font: TTFont, bundled: bool) -> list[dict[str, object]]:
    family, aliases = _names(font)
    if not family:
        return []
    weight = int(font["OS/2"].usWeightClass) if "OS/2" in font else 400
    low = high = weight
    if "fvar" in font:
        for axis in font["fvar"].axes:
            if axis.axisTag == "wght":
                low, high = int(axis.minValue), int(axis.maxValue)
    italic = _is_italic(font)
    return [
        {
            "family": name,
            "canonical": family,
            "source": str(source),
            "index": index,
            "weight": weight,
            "weight_min": low,
            "weight_max": high,
            "italic": italic,
            "bundled": bundled,
        }
        for name in sorted(aliases | {family})
    ]


def _scan_file(source: Path, bundled: bool = False) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    try:
        if source.suffix.lower() in {".ttc", ".otc"}:
            collection = TTCollection(str(source), lazy=True)
            for index, font in enumerate(collection.fonts):
                records.extend(_describe(source, index, font, bundled))
        else:
            records.extend(_describe(source, 0, TTFont(str(source), lazy=True), bundled))
    except Exception:
        return []
    return records


def _face(record: dict[str, object]) -> FontFace:
    return FontFace(
        family=str(record["canonical"]),
        source=str(record["source"]),
        index=int(record["index"]),  # type: ignore[arg-type]
        weight=int(record["weight"]),  # type: ignore[arg-type]
        weight_min=int(record["weight_min"]),  # type: ignore[arg-type]
        weight_max=int(record["weight_max"]),  # type: ignore[arg-type]
        italic=bool(record["italic"]),
        bundled=bool(record["bundled"]),
    )


class _Registry:
    """Family name -> faces, filled lazily from bundled, registered, and system fonts."""

    def __init__(self) -> None:
        self._families: dict[str, list[FontFace]] = {}
        self._display: dict[str, str] = {}
        self._bundled_loaded = False
        self._environment_loaded = False
        self._system_loaded = False
        self._registered_directories: list[Path] = []

    def _add(self, records: Iterable[dict[str, object]]) -> set[str]:
        added: set[str] = set()
        for record in records:
            key = str(record["family"]).casefold()
            face = _face(record)
            faces = self._families.setdefault(key, [])
            if face not in faces:
                faces.append(face)
            self._display.setdefault(key, str(record["family"]))
            added.add(face.family)
        return added

    def _ensure_bundled(self) -> None:
        if self._bundled_loaded:
            return
        self._bundled_loaded = True
        directory = _bundled_directory()
        for source in sorted(directory.iterdir()):
            if source.suffix.lower() in FONT_SUFFIXES:
                self._add(_scan_file(source, bundled=True))

    def _ensure_environment(self) -> None:
        if self._environment_loaded:
            return
        self._environment_loaded = True
        for entry in os.environ.get("FLEXO_FONT_PATH", "").split(os.pathsep):
            if entry:
                self.register(Path(entry).expanduser())

    def _ensure_system(self) -> None:
        if self._system_loaded:
            return
        self._system_loaded = True
        self._add(_system_records())

    def register(self, source: Path) -> tuple[str, ...]:
        self._ensure_bundled()
        if source.is_dir():
            files = sorted(
                item
                for item in source.rglob("*")
                if item.suffix.lower() in FONT_SUFFIXES and item.is_file()
            )
            self._registered_directories.append(source)
        elif source.is_file():
            files = [source]
            self._registered_directories.append(source.parent)
        else:
            raise FlexoError(
                Diagnostic(
                    "font.file.missing",
                    f'Font path "{source}" does not exist.',
                    hint="Pass a .ttf, .otf, or .ttc file, or a directory holding them.",
                )
            )
        added: set[str] = set()
        for item in files:
            added |= self._add(_scan_file(item))
        if not added:
            raise FlexoError(
                Diagnostic(
                    "font.file.unreadable",
                    f'No readable font faces in "{source}".',
                    hint="Pass a .ttf, .otf, or .ttc file, or a directory holding them.",
                )
            )
        return tuple(sorted(added))

    def lookup(self, family: str, *, search_system: bool = True) -> tuple[FontFace, ...]:
        self._ensure_bundled()
        self._ensure_environment()
        key = family.strip().strip("'\"").casefold()
        faces = self._families.get(key)
        if faces:
            return tuple(faces)
        if search_system:
            self._ensure_system()
            faces = self._families.get(key)
            if faces:
                return tuple(faces)
        return ()

    def known(self, *, include_system: bool = True) -> tuple[str, ...]:
        self._ensure_bundled()
        self._ensure_environment()
        if include_system:
            self._ensure_system()
        return tuple(sorted({faces[0].family for faces in self._families.values()}))

    def bundled(self) -> tuple[str, ...]:
        self._ensure_bundled()
        return tuple(
            sorted(
                {
                    face.family
                    for faces in self._families.values()
                    for face in faces
                    if face.bundled
                }
            )
        )

    def directories(self) -> tuple[Path, ...]:
        return (_bundled_directory(), *dict.fromkeys(self._registered_directories))


_REGISTRY = _Registry()


def register_font(source: str | os.PathLike[str]) -> tuple[str, ...]:
    """Make a font file, or every font in a directory, available by family name.

    Returns the family names it added. A registered face is measured exactly like
    a bundled one and is handed to Inkscape on export, so ``font="My Face"``
    comes out in that face in the PDF and PNG as well as the SVG.
    """

    return _REGISTRY.register(Path(source).expanduser())


def bundled_families() -> tuple[str, ...]:
    """The families that resolve on every machine, because Flexo ships them."""

    return _REGISTRY.bundled()


def available_families() -> tuple[str, ...]:
    """Every family Flexo can resolve here: bundled, registered, and installed."""

    return _REGISTRY.known()


def font_directories() -> tuple[Path, ...]:
    """Directories an external renderer needs to see to draw what Flexo measured."""

    return _REGISTRY.directories()


BROAD_FAMILIES = (
    "Noto Sans",
    "Noto Sans CJK SC",
    "PingFang SC",
    "Hiragino Sans",
    "Apple SD Gothic Neo",
    "Microsoft YaHei",
    "Arial Unicode MS",
    "DejaVu Sans",
    "Segoe UI",
)
"""Installed families that cover many scripts, tried first for a missing glyph."""

_COVERING: dict[frozenset[str], str | None] = {}


def family_covering(characters: Iterable[str]) -> str | None:
    """An installed family that has every one of ``characters``, if there is one.

    Families known for broad coverage are tried first, then every family
    installed here, so a label in a script the bundled faces lack -- Chinese,
    Japanese, Korean -- is set in a font that has it, the way a browser would.
    Hidden system families (named with a leading dot) and bitmap faces such as
    colour emoji are never chosen: a figure is drawn from outlines. The answer
    is cached per set of characters.
    """

    wanted = frozenset(characters)
    if wanted in _COVERING:
        return _COVERING[wanted]
    found: str | None = None
    names = list(BROAD_FAMILIES) + [
        name for name in available_families() if name not in BROAD_FAMILIES
    ]
    for name in names:
        if name.startswith("."):
            continue
        faces = family_faces(name)
        if not faces:
            continue
        try:
            loaded = load_face(select_face(faces, 400, False))
        except Exception:
            continue
        if loaded.outlines and all(loaded.has(character) for character in wanted):
            found = faces[0].family
            break
    _COVERING[wanted] = found
    return found


def family_faces(family: str) -> tuple[FontFace, ...]:
    """Every face of ``family``, or an empty tuple when nothing resolves.

    A metric substitute answers for a family that is not installed (Liberation
    Sans for Arial and Helvetica), so a figure measures identically either way.
    """

    faces = _REGISTRY.lookup(family)
    if faces:
        return faces
    substitute = METRIC_SUBSTITUTES.get(family.strip().casefold())
    return _REGISTRY.lookup(substitute) if substitute else ()


def require_family(family: str) -> tuple[FontFace, ...]:
    """The faces of ``family``, or a diagnostic naming the closest families."""

    faces = family_faces(family)
    if faces:
        return faces
    known = available_families()
    close = difflib.get_close_matches(family, known, n=4, cutoff=0.5)
    hint = (
        f"Did you mean {', '.join(repr(name) for name in close)}? "
        if close
        else ""
    ) + (
        f"Bundled families always work: {', '.join(bundled_families())}. "
        "Point flexo.register_font() at a .ttf/.otf file to use any other."
    )
    raise FlexoError(
        Diagnostic("font.family.unknown", f'Font family "{family}" was not found.', hint=hint)
    )


def select_face(faces: tuple[FontFace, ...], weight: int, italic: bool) -> FontFace:
    """The face CSS font matching would draw for ``weight`` and ``italic``.

    Style first -- an italic request takes an italic face when the family has one
    -- then weight by the CSS rules: a variable face covering the weight wins
    outright; otherwise for 400-500 look up to 500, then down, then up; below 400
    look down then up; above 500 look up then down.
    """

    styled = tuple(face for face in faces if face.italic == italic) or faces
    covering = [face for face in styled if face.covers_weight(weight)]
    if covering:
        return min(covering, key=lambda face: (face.variable, abs(face.weight - weight)))

    def nearest_above(limit: float | None = None) -> FontFace | None:
        above = [
            face
            for face in styled
            if face.weight_min > weight and (limit is None or face.weight_min <= limit)
        ]
        return min(above, key=lambda face: face.weight_min) if above else None

    def nearest_below() -> FontFace | None:
        below = [face for face in styled if face.weight_max < weight]
        return max(below, key=lambda face: face.weight_max) if below else None

    if 400 <= weight <= 500:
        order = (nearest_above(500), nearest_below(), nearest_above())
    elif weight < 400:
        order = (nearest_below(), nearest_above())
    else:
        order = (nearest_above(), nearest_below())
    for candidate in order:
        if candidate is not None:
            return candidate
    return styled[0]


def drawn_weight_for(face: FontFace, weight: int) -> int:
    """The ``wght`` a variable face is set to, clamped to its axis."""

    return max(face.weight_min, min(face.weight_max, weight))


@cache
def load_face(face: FontFace) -> LoadedFace:
    raw = Path(face.source).read_bytes()
    if face.source.lower().endswith((".ttc", ".otc")):
        font = TTCollection(BytesIO(raw), lazy=True).fonts[face.index]
    else:
        font = TTFont(BytesIO(raw), lazy=True)
    os2 = font.get("OS/2", None)
    return LoadedFace(
        face=face,
        raw=raw,
        upem=font["head"].unitsPerEm,
        ascent=font["hhea"].ascent,
        descent=abs(font["hhea"].descent),
        subscript_drop=os2.ySubscriptYOffset if os2 is not None else 0,
        codepoints=frozenset((font.getBestCmap() or {}).keys()),
        hb_face=hb.Face(raw, face.index),
        cap_height=int(getattr(os2, "sCapHeight", 0) or 0) if os2 is not None else 0,
        superscript_rise=os2.ySuperscriptYOffset if os2 is not None else 0,
        outlines=any(tag in font for tag in ("glyf", "CFF ", "CFF2"))
        and not any(tag in font for tag in ("sbix", "CBDT", "COLR", "SVG ")),
    )


@cache
def hb_font(face: FontFace, weight: int) -> hb.Font:
    loaded = load_face(face)
    font = hb.Font(loaded.hb_face)
    font.scale = (loaded.upem, loaded.upem)
    if face.variable:
        font.set_variations({"wght": float(drawn_weight_for(face, weight))})
    return font


def css_family_list(families: Iterable[str], generic: str = "sans-serif") -> str:
    """A ``font-family`` value: every family quoted once, then a generic."""

    seen: list[str] = []
    for family in families:
        name = family.strip().strip("'\"")
        if name and name.casefold() not in {item.casefold() for item in seen}:
            seen.append(name)
    rendered = [name if name in GENERIC_FAMILIES else f"'{name}'" for name in seen]
    if generic and generic not in seen:
        rendered.append(generic)
    return ", ".join(rendered)


# -- system font discovery ----------------------------------------------------------


def _system_directories() -> tuple[Path, ...]:
    home = Path.home()
    if sys.platform == "darwin":
        candidates = (
            Path("/System/Library/Fonts"),
            Path("/System/Library/Fonts/Supplemental"),
            Path("/Library/Fonts"),
            home / "Library/Fonts",
        )
    elif sys.platform.startswith("win"):
        windows = Path(os.environ.get("WINDIR", "C:/Windows"))
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        candidates = (windows / "Fonts", local / "Microsoft/Windows/Fonts")
    else:
        data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
        candidates = (
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            data_home / "fonts",
            home / ".fonts",
        )
    return tuple(candidate for candidate in candidates if candidate.is_dir())


def _cache_file() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library/Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "flexo" / "system-fonts-v1.json"


def _system_records() -> list[dict[str, object]]:
    """Every installed face, read through a cache keyed by file and mtime."""

    cache_file = _cache_file()
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    fresh: dict[str, dict[str, object]] = {}
    records: list[dict[str, object]] = []
    for directory in _system_directories():
        for source in directory.rglob("*"):
            if source.suffix.lower() not in FONT_SUFFIXES:
                continue
            try:
                stamp = source.stat().st_mtime
            except OSError:
                continue
            key = str(source)
            entry = cached.get(key)
            if not isinstance(entry, dict) or entry.get("mtime") != stamp:
                entry = {"mtime": stamp, "records": _scan_file(source)}
            fresh[key] = entry
            records.extend(entry["records"])  # type: ignore[arg-type]
    if fresh != cached:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(fresh), encoding="utf-8")
        except OSError:
            pass
    return records
