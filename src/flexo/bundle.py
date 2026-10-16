"""A document and every file it names, as one file: a Flexo bundle (``.flexo``).

A deck is a folder -- ``talk.yaml``, its figures, pictures, data, its plots' Python,
structures, maps, theme files and the pictures kept from drawings pasted in -- and a folder
is awkward to send. A bundle is that folder as one file, to email, AirDrop or Slack, open
on another Mac, edit, save and send back, as Keynote's ``.key`` is one file. It is a zip::

    manifest.json              what it is (below)
    talk.yaml                  the document, at its root
    figures/model.yaml         every file the document names, by the name it names it,
    plots.py                   from the document's folder -- and every file those name:
    data/loss.csv              a figure file's pictures, a plot's data and the modules
    assets/drawing-part-1.svg  its Python imports from beside it, a theme's fonts
    .flexo/pdb/1UBQ.cif        a PDB entry a structure names by its ID, kept as it was
                               fetched, so the deck draws with no network

``manifest.json`` says what the bundle holds::

    {"format": "flexo-bundle", "version": 1, "document": "talk.yaml", "kind": "deck",
     "app": "Flexo Studio 0.3.0", "created": "2026-10-15T09:12:03Z",
     "modified": "2026-10-15T10:40:51Z", "files": 14,
     "missing": [{"name": "old.png", "where": "slides[3].body[0]"}],
     "outside": [{"name": "/Users/k/logo.png", "where": "deck.logos[0]"}]}

``missing`` are files the document names that were not there when it was bundled, and
``outside`` those it names outside its folder (a whole path, ``../``): neither is in the
bundle, and nothing the document says is rewritten -- each file keeps the name it is named
by. A bundle opens on Linux and in a browser's studio as on a Mac: it is a plain zip, not a
macOS package.

What names what is found as each loader finds it (``gather``): a kind of document says what
it names (its ``references``: flexo's figures and themes here, a deck in flexo-talk), and the
files named are followed in turn -- a figure file's own pictures, a theme file's fonts, the
modules a plot's Python imports from beside it and the files its words name.

A bundle someone sends is opened as one from a stranger (``Bundle``): no name that is a
whole path or climbs out with ``..``, no link, no entry encrypted or packed in another way
than stored or deflated, nothing larger in all than ``MOST_BYTES`` however small it is
packed, and two names a Mac would take for one are refused. Its Python runs only once its
person trusts it (the studio's trust, as for a folder).
"""

from __future__ import annotations

import ast
import contextlib
import glob
import json
import os
import re
import secrets
import shutil
import stat
import struct
import time
import unicodedata
import zipfile
import zlib
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

SUFFIX = ".flexo"
FORMAT = "flexo-bundle"
VERSION = 1
MANIFEST = "manifest.json"
OWN = ".flexo"
"""The bundle's own folder in it: what it keeps that no document names (fetched entries)."""
PDB = f"{OWN}/pdb"
"""Where a bundle keeps the PDB entries its structures name by their IDs."""
DOCUMENTS = (".yaml", ".yml", ".json")
MOST_FILES = 20_000
"""Files a bundle may hold, at most."""
MOST_BYTES = 3 * 1024**3
"""Bytes a bundle's files may come to, unpacked, at most: a cryo-EM map is hundreds of
megabytes, but a bundle claiming more than this is refused rather than unpacked (a zip of a
few kilobytes can claim gigabytes)."""
MOST_MANIFEST = 1_000_000
FOLDER_MOST = 2_000
"""Files taken from one folder a document names (a plot's data folder), at most."""
APP = ""
"""Who writes bundles in this process, for the manifest ("Flexo Studio 0.3.0"): the Mac app
says; else flexo's version is given."""
PACKED = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".heic",
        ".gz",
        ".tgz",
        ".zip",
        ".xz",
        ".bz2",
        ".zst",
        ".7z",
        ".npz",
        ".parquet",
        ".mp4",
        ".mov",
        ".m4v",
        ".woff",
        ".woff2",
        ".flexo",
        ".pptx",
        ".docx",
        ".xlsx",
        ".key",
    }
)
"""Files packed already: stored as they are, not deflated again."""
FONTS = (".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2")
_PID = re.compile(r"[0-9][A-Za-z0-9]{3}")
_LOOKS_LIKE_A_FILE = re.compile(r"[/\\]|\.[A-Za-z0-9]{1,6}(?:\.gz)?$")
_TEMPORARY = re.compile(r"^\..*\.(?:saving|bundling)(?:\.[^.]*)?$")
_SKIPPED_FOLDERS = frozenset({"__MACOSX", "__pycache__", ".git", ".venv", "node_modules"})
_SKIPPED_FILES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini", "Icon\r"})


class BundleError(ValueError):
    """A bundle that cannot be read, or written, as asked: said in a sentence."""


# -- what a document names --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Reference:
    """A file a document names, as it names it.

    ``role`` says how it is found and followed: ``file`` (a picture, a map, a scene, a
    palette file), ``document`` (a figure or theme file, whose own references are followed),
    ``python`` (a plot's or a figure's Python: the modules it imports from beside it and the
    files its words name are followed; ``function`` names the function used), ``data`` (what a
    plot's ``data`` names: files, folders, patterns), ``structure`` (a structure file, or a PDB
    ID), ``density`` (a map file, or an EMDB ID or ``auto``) and ``font`` (a font file or a
    folder of them)."""

    name: str
    where: str
    base: Path
    role: str = "file"
    function: str = ""


def figure_references(data: object, base: Path, where: str = "") -> list[Reference]:
    """What a figure document names (a figure file's, or one written in a deck): its theme
    and palette files, each part's picture, structure, map, scene, plot and the plot's data,
    and the pictures among the shapes drawn over it -- found from ``base``, as
    ``flexo.studio.figure_kind.parse`` finds them."""

    found: list[Reference] = []
    if not isinstance(data, Mapping):
        return found
    prefix = f"{where}." if where else ""
    figure = data.get("figure")
    if isinstance(figure, Mapping):
        for key in ("theme", "style", "palette"):
            value = figure.get(key)
            if _names_document(value):
                role = "file" if key == "palette" else "document"
                found.append(Reference(str(value), f"{prefix}figure.{key}", base, role))
    nodes = data.get("nodes")
    for index, node in enumerate(nodes if isinstance(nodes, list) else []):
        if not isinstance(node, Mapping):
            continue
        properties = node.get("properties")
        if not isinstance(properties, Mapping):
            continue
        here = f"{prefix}nodes[{index}]"
        kind = str(node.get("kind") or "")
        source = properties.get("source")
        if isinstance(source, str) and source.strip():
            if kind == "plot":
                function = str(properties.get("function") or "")
                found.append(Reference(source, f"{here}.source", base, "python", function))
            elif kind == "structure":
                found.append(Reference(source, f"{here}.source", base, "structure"))
            else:
                found.append(Reference(source, f"{here}.source", base, "file"))
        density = properties.get("density")
        if isinstance(density, str) and density.strip():
            found.append(Reference(density, f"{here}.density", base, "density"))
        if kind == "plot" and properties.get("data") is not None:
            from flexo.plots import named

            for name in named(properties.get("data")):
                found.append(Reference(name, f"{here}.data", base, "data"))
    found += shape_references(data.get("shapes"), base, f"{prefix}shapes")
    return found


def shape_references(shapes: object, base: Path, where: str) -> list[Reference]:
    """The pictures among shapes drawn where they are put (a group's too): each a part of a
    drawing kept as drawn, its ``source`` a file (``flexo.shape_pictures``)."""

    found: list[Reference] = []
    for index, shape in enumerate(shapes if isinstance(shapes, list) else []):
        if not isinstance(shape, Mapping):
            continue
        here = f"{where}[{index}]"
        if shape.get("kind") == "group":
            found += shape_references(shape.get("shapes"), base, f"{here}.shapes")
        elif shape.get("kind") == "picture" and isinstance(shape.get("source"), str):
            found.append(Reference(str(shape["source"]), f"{here}.source", base))
    return found


def theme_references(data: object, base: Path) -> list[Reference]:
    """What a theme file names: the fonts it is set in (files, or folders of them, beside
    it) and the theme it starts from, when that is a file of its own."""

    found: list[Reference] = []
    if not isinstance(data, Mapping):
        return found
    fonts = data.get("fonts")
    for index, entry in enumerate([fonts] if isinstance(fonts, str) else fonts or []):
        if isinstance(entry, str) and entry.strip():
            found.append(Reference(entry, f"fonts[{index}]", base, "font"))
    settings = data.get("theme")
    if isinstance(settings, Mapping):
        for key in ("base", "extends", "inherits", "parent", "from"):
            if _names_document(settings.get(key)):
                found.append(Reference(str(settings[key]), f"theme.{key}", base, "document"))
    return found


def _names_document(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower().endswith(DOCUMENTS)


# -- gathering ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Left:
    """A file a document names that is not in its bundle, and why: ``missing`` (not there),
    ``outside`` (a whole path, or one out of the document's folder) or ``reserved`` (named
    ``manifest.json``, as the bundle's own file is, beside the document)."""

    name: str
    where: str
    why: str = "missing"
    document: str = ""
    """The document naming it, from the bundle's root (when it is not the bundle's own)."""

    def said(self) -> dict[str, str]:
        return {
            "name": self.name,
            "where": self.where,
            **({"document": self.document} if self.document else {}),
            **({"why": self.why} if self.why == "reserved" else {}),
        }


@dataclass(slots=True)
class Gathered:
    """What a bundle of a document holds: each file by the name it is kept under (from the
    document's folder), and where it is now; and what was left out, and why."""

    root: Path
    document: str
    kind: str = ""
    files: dict[str, Path] = field(default_factory=dict)
    left: list[Left] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)
    """Documents named that do not read (their own references unknown): kept as they are."""

    @property
    def missing(self) -> list[Left]:
        return [item for item in self.left if item.why != "outside"]

    @property
    def outside(self) -> list[Left]:
        return [item for item in self.left if item.why == "outside"]

    @property
    def python(self) -> list[str]:
        return [name for name in self.files if name.endswith(".py")]

    def size(self) -> int:
        return sum(_size(path) for path in self.files.values())


def gather(document: str | Path, *, text: str | None = None) -> Gathered:
    """Everything a document names, followed through the files it names, found from its
    folder: what a bundle of it holds. ``text``: the document's words as they are now, if
    not as its file has them (a studio's edits not yet written)."""

    path = Path(document).expanduser()
    lexical = Path(os.path.abspath(path))
    root = lexical.parent
    gathered = Gathered(root=root, document=lexical.name)
    walker = _Walker(gathered, root)
    gathered.files[lexical.name] = path.resolve()
    walker.document(lexical, "", main=True, text=text)
    return gathered


class _Walker:
    def __init__(self, gathered: Gathered, root: Path) -> None:
        self.gathered = gathered
        self.root = root
        self.real = root.resolve()
        self.documents: set[Path] = set()
        self.modules: set[Path] = set()
        self.spelled: set[tuple[Path, str]] = set()
        self._kinds: dict[str, Any] | None = None
        self._lower: dict[str, str] = {}
        """Each name kept, case folded: one file named two ways (``Logo.png``, ``logo.png``)
        is kept once, as a Mac would take both for one."""

    # -- documents --

    @property
    def kinds(self) -> dict[str, Any]:
        if self._kinds is None:
            from flexo.studio import kinds

            self._kinds = kinds()
        return self._kinds

    def document(
        self, path: Path, where: str, *, main: bool = False, text: str | None = None
    ) -> None:
        real = path.resolve()
        if real in self.documents:
            return
        self.documents.add(real)
        try:
            words = text if text is not None else path.read_text(encoding="utf-8")
            data = _parsed(words, path.suffix)
        except Exception:
            self.gathered.unread.append(self.name_of(path))
            return
        kind = self.kind_of(data)
        if main:
            self.gathered.kind = kind or ""
        references = getattr(self.kinds.get(kind or ""), "references", None)
        if references is None:
            return
        try:
            found = list(references(data, path.parent))
        except Exception:
            self.gathered.unread.append(self.name_of(path))
            return
        named_in = "" if main else self.name_of(path)
        for reference in found:
            with contextlib.suppress(OSError, ValueError):
                self.follow(reference, named_in)

    def kind_of(self, data: object) -> str | None:
        # (The figure kind claims broadly: every other kind is asked first.)
        for kind in sorted(self.kinds.values(), key=lambda item: item.name == "figure"):
            with contextlib.suppress(Exception):
                if kind.claims(data):
                    return kind.name
        return None

    def name_of(self, path: Path) -> str:
        try:
            return Path(os.path.abspath(path)).relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    # -- references --

    def follow(self, reference: Reference, named_in: str) -> None:
        name = reference.name.strip()
        if not name:
            return
        role = reference.role
        if role == "data":
            self.data(reference, named_in)
            return
        path = self.place(name, reference.base)
        if role == "file" and not path.exists():
            # A PDF's or an Illustrator file's page: ``art.pdf#2`` is art.pdf's second.
            whole, mark, number = name.rpartition("#")
            if mark and number.isdigit() and self.place(whole, reference.base).is_file():
                name, path = whole, self.place(whole, reference.base)
        if role in ("structure", "density") and not path.exists():
            if role == "structure" and _PID.fullmatch(name) and not _LOOKS_LIKE_A_FILE.search(name):
                self.fetched(name.upper())
                return
            if not _LOOKS_LIKE_A_FILE.search(name) or name.lower() == "auto":
                return  # an EMDB ID, ``auto``: fetched as it is drawn, not a file
        if not self.inside(path, reference.base, name):
            self.leave(name, reference.where, "outside", named_in)
            return
        if not path.exists():
            self.leave(name, reference.where, "missing", named_in)
            return
        if path.relative_to(self.root).as_posix() == MANIFEST:
            # (The bundle's own name for what it is: a file so named is not kept in it.)
            self.leave(name, reference.where, "reserved", named_in)
            return
        if path.is_dir():
            if role in ("font", "structure", "file", "density"):
                self.folder(path, FONTS if role == "font" else None)
            return
        self.keep(path)
        if role == "document":
            self.document(path, reference.where)
        elif role == "python":
            self.python(path, reference.function)

    def place(self, name: str, base: Path) -> Path:
        """Where a name is, from ``base``: as written, never its links followed (``a/../b`` is
        ``b``), so it is kept under the name the document finds it by."""

        given = Path(name).expanduser()
        return Path(os.path.normpath(given if given.is_absolute() else base / given))

    def inside(self, path: Path, base: Path, name: str) -> bool:
        """Whether a file named so is the folder's own: named from it (no whole path, no way
        out), and, links followed, still in it."""

        if Path(name).expanduser().is_absolute():
            return False
        try:
            path.relative_to(self.root)
        except ValueError:
            return False
        real = path.resolve()
        return real == self.real or self.real in real.parents

    def leave(self, name: str, where: str, why: str, named_in: str) -> None:
        left = Left(name, where, why, named_in)
        if left not in self.gathered.left:
            self.gathered.left.append(left)

    def keep(self, path: Path) -> str | None:
        """Keep a file of the folder, by its name from the bundle's root."""

        name = path.relative_to(self.root).as_posix()
        if not _kept_name(name):
            return None
        folded = unicodedata.normalize("NFC", name).casefold()
        if folded in self._lower:
            return self._lower[folded]
        if len(self.gathered.files) >= MOST_FILES:
            raise BundleError(f"A bundle holds at most {MOST_FILES:,} files.")
        self._lower[folded] = name
        self.gathered.files[name] = path.resolve()
        return name

    def folder(self, folder: Path, suffixes: tuple[str, ...] | None = None) -> None:
        """Every file in a folder a document names (a theme's fonts, a plot's data)."""

        if folder.resolve() == self.real:
            return  # (the whole folder is not what is meant)
        count = 0
        for file in _files_in(folder):
            if suffixes is not None and file.suffix.lower() not in suffixes:
                continue
            if self.inside(file, folder, file.name):
                self.keep(file)
                count += 1
            if count >= FOLDER_MOST:
                break

    def data(self, reference: Reference, named_in: str) -> None:
        """What a plot's ``data`` names, found from its figure's folder: a file, a folder (all
        that is in it), or a pattern (what it finds now)."""

        name = os.path.expanduser(reference.name.strip())
        if glob.has_magic(name):
            if os.path.isabs(name):
                self.leave(name, reference.where, "outside", named_in)
                return
            found = sorted(glob.glob(name, root_dir=reference.base, recursive=True))[:FOLDER_MOST]
            for each in found:
                path = self.place(each, reference.base)
                if path.is_file() and self.inside(path, reference.base, each):
                    self.keep(path)
            return
        self.follow(Reference(name, reference.where, reference.base, "file"), named_in)

    def fetched(self, pid: str) -> None:
        """A PDB entry a structure names by its ID: kept as it was fetched, when it was (the
        bundle's own copy, or mol-sketch's), so the deck draws with no network."""

        name = f"{PDB}/{pid}.cif"
        if name in self.gathered.files:
            return
        own = self.root / PDB / f"{pid}.cif"
        cached = _molsketch_cache() / f"{pid}.cif"
        for source in (own, cached):
            if source.is_file() and _is_entry(source, pid):
                self.gathered.files[name] = source.resolve()
                return

    # -- Python --

    def python(self, path: Path, function: str = "") -> None:
        """A plot's Python, and what it is drawn from beside it: the modules it imports
        from its folder (and theirs), and the files its words name -- each that is there --
        as ``flexo.plots`` watches them; and what it read when it was last run here."""

        real = path.resolve()
        if (real, function) in self.spelled:
            return
        # (Each function of a file names files of its own: its words are read for each.)
        self.spelled.add((real, function))
        self.keep(path)
        if real not in self.modules:
            self.modules.add(real)
            try:
                tree = ast.parse(path.read_bytes())
            except (OSError, SyntaxError, ValueError):
                return
            for module in self.imported(tree, path):
                if (
                    module.suffix == ".py"
                    and module.is_file()
                    and self.inside(module, path.parent, module.name)
                ):
                    self.python(module)
        self.spelt(path, function)
        with contextlib.suppress(Exception):
            from flexo.plots import files

            for read in files(path, function)[1:]:
                found = Path(read)
                if self.inside(found, self.root, found.name):
                    if found.is_dir():
                        self.folder(found)
                    elif found.is_file():
                        self.keep(found)

    def imported(self, tree: ast.AST, path: Path) -> Iterator[Path]:
        """The modules a Python file imports that are beside it (or in a package beside it):
        found there as Python finds them, its folder being first on its path."""

        folder = path.parent
        for node in ast.walk(tree):
            dotted: list[tuple[Path, list[str]]] = []
            if isinstance(node, ast.Import):
                dotted = [(folder, alias.name.split(".")) for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                start = folder
                for _ in range(max(node.level - 1, 0)):
                    start = start.parent
                module = (node.module or "").split(".") if node.module else []
                dotted = [(start, module)] if module else []
                dotted += [
                    (start, [*module, alias.name]) for alias in node.names if alias.name != "*"
                ]
            for start, parts in dotted:
                at = start
                for part in parts:
                    if not part.isidentifier():
                        break
                    if (at / f"{part}.py").is_file():
                        yield at / f"{part}.py"
                        break
                    if (at / part / "__init__.py").is_file():
                        yield at / part / "__init__.py"
                    if not (at / part).is_dir():
                        break
                    at = at / part

    def spelt(self, path: Path, function: str) -> None:
        """The files a Python file names in so many words (``"loss.csv"``, ``HERE / "runs" /
        "a.parquet"``, ``"runs/*.h5"``), from its folder and the bundle's: a folder so named
        is kept whole."""

        from flexo.plots import _pattern, _spelt

        own = path.parent
        for word in _spelt(str(path), function):
            if _pattern(word):
                for each in sorted(glob.glob(word, root_dir=own, recursive=True))[:FOLDER_MOST]:
                    found = self.place(each, own)
                    if found.is_file() and self.inside(found, own, each):
                        self.keep(found)
                continue
            word = os.path.expanduser(word)
            if os.path.isabs(word) or word in (".", ".."):
                continue
            for base in dict.fromkeys((own, self.root)):
                found = self.place(word, base)
                if not self.inside(found, base, word) or found.resolve() == self.real:
                    continue
                if found.is_file():
                    self.keep(found)
                elif found.is_dir() and not _ignored(found.relative_to(self.root).parts):
                    self.folder(found)


def _parsed(text: str, suffix: str) -> Any:
    if suffix.lower() == ".json":
        return json.loads(text)
    import yaml

    return yaml.load(text, getattr(yaml, "CSafeLoader", yaml.SafeLoader))


def _files_in(folder: Path) -> Iterator[Path]:
    """The files under ``folder``, by name, none of a hidden or a tool's folder (no link to
    a folder followed)."""

    try:
        entries = sorted(os.scandir(folder), key=lambda entry: entry.name)
    except OSError:
        return
    for entry in entries:
        if entry.name in _SKIPPED_FILES or entry.name.startswith("."):
            continue
        try:
            if entry.is_dir(follow_symlinks=False):
                if entry.name not in _SKIPPED_FOLDERS:
                    yield from _files_in(Path(entry.path))
            elif entry.is_file():
                yield Path(entry.path)
        except OSError:
            continue


def _ignored(parts: tuple[str, ...]) -> bool:
    from flexo.studio.workspace import IGNORED

    return any(part in IGNORED or part.startswith(".") for part in parts)


def _molsketch_cache() -> Path:
    return Path(os.environ.get("MOLSKETCH_CACHE") or Path.home() / ".cache" / "molsketch")


def _is_entry(path: Path, pid: str) -> bool:
    """Whether a file is the PDB's mmCIF entry ``pid`` (as RCSB serves one: ``data_1UBQ``)."""

    try:
        with path.open("rb") as handle:
            head = handle.read(64)
    except OSError:
        return False
    return head.lstrip().upper().startswith(f"DATA_{pid.upper()}".encode())


def kept_entry(pid: str, folder: Path | None) -> Path | None:
    """The PDB entry ``pid`` as a bundle opened in ``folder`` keeps it, if it does: a
    structure named by its ID draws from it with no network."""

    if folder is None or not _PID.fullmatch(pid.strip()):
        return None
    path = Path(folder) / PDB / f"{pid.strip().upper()}.cif"
    return path if path.is_file() and _is_entry(path, pid.strip()) else None


def _kept_name(name: str) -> bool:
    """Whether a file of a folder belongs in a bundle of it: not the Finder's or a tool's
    own (``.DS_Store``, ``__pycache__``), nor a file half written (the studio's ``.saving``)."""

    parts = name.split("/")
    if parts[-1] in _SKIPPED_FILES or parts[-1].startswith("._") or parts[-1].endswith(".pyc"):
        return False
    if _TEMPORARY.match(parts[-1]):
        return False
    return not any(part in _SKIPPED_FOLDERS for part in parts[:-1]) and name != MANIFEST


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


# -- writing -----------------------------------------------------------------------------


Known = dict[str, tuple[int, int, int]]
"""What each file was when it was last written into a bundle: its file's time (ns) and size,
and its CRC -- for the next writing to copy what has not changed as it is."""


def manifest(
    document: str,
    kind: str = "",
    *,
    created: str | None = None,
    left: Iterable[Left] = (),
    files: int = 0,
) -> dict[str, Any]:
    """A bundle's ``manifest.json``: what it is, its document, who made it and when."""

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    left = list(left)
    return {
        "format": FORMAT,
        "version": VERSION,
        "document": document,
        **({"kind": kind} if kind else {}),
        "app": APP or _made_by(),
        "created": created or now,
        "modified": now,
        "files": files,
        **(
            {"missing": [item.said() for item in left if item.why != "outside"]}
            if any(item.why != "outside" for item in left)
            else {}
        ),
        **(
            {"outside": [item.said() for item in left if item.why == "outside"]}
            if any(item.why == "outside" for item in left)
            else {}
        ),
    }


def _made_by() -> str:
    from importlib import metadata

    for package, name in (
        ("flexo-studio", "Flexo Studio"),
        ("flexo-talk", "flexo-talk"),
        ("flexo", "flexo"),
    ):
        with contextlib.suppress(metadata.PackageNotFoundError):
            return f"{name} {metadata.version(package)}"
    return "flexo"


def write(
    target: str | Path,
    files: Mapping[str, Path],
    about: Mapping[str, Any],
    *,
    previous: Path | None = None,
    known: Known | None = None,
) -> Known:
    """Write a bundle of ``files`` (each by its name in it) and the manifest ``about``, as
    one file at ``target``: written beside it and moved over it, so a write cut short (a full
    disk, the app quitting) leaves the bundle as it was, never half of the new one.

    ``previous``: a bundle of these files written before, whose entries for files unchanged
    since (``known`` says what they were; else each is read again) are copied as they are --
    a bundle of 50 MB of structures is written again in a moment when only its deck changed.
    Answers what each file was as it was written, for the next time."""

    target = Path(target)
    names = [name for name in files if name != MANIFEST]
    if len(names) > MOST_FILES:
        raise BundleError(
            f"A bundle holds at most {MOST_FILES:,} files; this one would hold {len(names):,}."
        )
    for name in names:
        if _unsafe(name):
            raise BundleError(f"{name} can\u2019t be kept in a bundle under that name.")
    old = _Previous(previous) if previous is not None else None
    partial = target.with_name(f".{target.name}.{secrets.token_hex(4)}.bundling")
    written: Known = {}
    try:
        with partial.open("wb") as handle:
            zipped = _Writer(handle)
            body = json.dumps(dict(about), indent=2, ensure_ascii=False).encode("utf-8")
            zipped.add_bytes(MANIFEST, body, time.time())
            total = 0
            for name in sorted(names, key=lambda item: (item != about.get("document"), item)):
                source = files[name]
                facts = os.stat(source)
                total += facts.st_size
                if total > MOST_BYTES:
                    raise BundleError("A bundle holds at most 3 GB of files.")
                stamp = (facts.st_mtime_ns, facts.st_size)
                was = (known or {}).get(name)
                entry = old.entry(name) if old is not None else None
                same = entry is not None and entry.file_size == facts.st_size
                if same and was is not None and was[:2] == stamp:
                    same = was[2] == entry.CRC
                elif same:
                    # (Not known: read, and copied as it is packed if it reads the same.)
                    same = _crc(source) == entry.CRC
                if same and entry is not None and old is not None:
                    zipped.add_raw(old, entry, facts.st_mtime)
                    written[name] = (*stamp, entry.CRC)
                    continue
                crc = zipped.add_file(name, source, facts.st_mtime)
                written[name] = (*stamp, crc)
            zipped.close()
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            os.chmod(partial, target.stat().st_mode & 0o7777 if target.exists() else 0o644)
        os.replace(partial, target)
    except BaseException:
        with contextlib.suppress(OSError):
            partial.unlink()
        raise
    finally:
        if old is not None:
            old.close()
    return written


def _unsafe(name: str) -> bool:
    if (
        not name
        or "\\" in name
        or "\0" in name
        or name.startswith("/")
        or re.match(r"^[A-Za-z]:", name)
    ):
        return True
    return any(part in ("", ".", "..") for part in name.split("/"))


class _Previous:
    """A bundle written before, whose entries are copied as they are where nothing changed."""

    def __init__(self, path: Path) -> None:
        self.archive: zipfile.ZipFile | None = None
        self.raw: BinaryIO | None = None
        try:
            self.archive = zipfile.ZipFile(path)
            self.raw = path.open("rb")
        except (OSError, zipfile.BadZipFile):
            self.close()

    def entry(self, name: str) -> zipfile.ZipInfo | None:
        if self.archive is None:
            return None
        try:
            info = self.archive.getinfo(name)
        except KeyError:
            return None
        plain = info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
        return info if plain and not info.flag_bits & 0x1 else None

    def data(self, info: zipfile.ZipInfo) -> Iterator[bytes]:
        """An entry's bytes as they are packed in the bundle."""

        assert self.raw is not None
        self.raw.seek(info.header_offset)
        header = self.raw.read(30)
        if len(header) != 30 or header[:4] != b"PK\x03\x04":
            raise BundleError("The bundle written before has changed under it.")
        name_length, extra_length = struct.unpack("<HH", header[26:30])
        self.raw.seek(info.header_offset + 30 + name_length + extra_length)
        left = info.compress_size
        while left > 0:
            chunk = self.raw.read(min(left, 1 << 20))
            if not chunk:
                raise BundleError("The bundle written before is cut short.")
            left -= len(chunk)
            yield chunk

    def close(self) -> None:
        for handle in (self.archive, self.raw):
            with contextlib.suppress(Exception):
                if handle is not None:
                    handle.close()
        self.archive = self.raw = None


class _Writer:
    """A zip written plainly: each file stored or deflated, its name in UTF-8, a file of the
    owner's to read and write (0644) -- and, where nothing changed, an entry of a bundle
    written before copied as it is packed. (No ZIP64: a bundle holds less than 4 GB.)"""

    def __init__(self, handle: BinaryIO) -> None:
        self.handle = handle
        self.entries: list[tuple[bytes, int, int, int, int, int, int, int]] = []

    def _header(
        self, name: bytes, method: int, when: tuple[int, int], crc: int, packed: int, size: int
    ) -> bytes:
        return (
            struct.pack(
                "<IHHHHHIIIHH",
                0x04034B50,
                20,
                0x0800,
                method,
                when[0],
                when[1],
                crc,
                packed,
                size,
                len(name),
                0,
            )
            + name
        )

    def add_bytes(self, name: str, data: bytes, mtime: float) -> int:
        encoded, when = name.encode("utf-8"), _dos(mtime)
        crc = zlib.crc32(data)
        packed = _deflated(data)
        method = zipfile.ZIP_DEFLATED if len(packed) < len(data) else zipfile.ZIP_STORED
        body = packed if method == zipfile.ZIP_DEFLATED else data
        offset = self.handle.tell()
        self.handle.write(self._header(encoded, method, when, crc, len(body), len(data)))
        self.handle.write(body)
        self.entries.append((encoded, method, *when, crc, len(body), len(data), offset))
        return crc

    def add_file(self, name: str, source: Path, mtime: float) -> int:
        encoded, when = name.encode("utf-8"), _dos(mtime)
        offset = self.handle.tell()
        deflate = Path(name).suffix.lower() not in PACKED and not _dense(source)
        method = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
        self.handle.write(self._header(encoded, method, when, 0, 0, 0))
        start = self.handle.tell()
        crc, size = 0, 0
        squeeze = zlib.compressobj(6, zlib.DEFLATED, -15) if deflate else None
        with open(source, "rb") as reading:
            while chunk := reading.read(1 << 20):
                crc = zlib.crc32(chunk, crc)
                size += len(chunk)
                self.handle.write(squeeze.compress(chunk) if squeeze is not None else chunk)
        if squeeze is not None:
            self.handle.write(squeeze.flush())
        packed = self.handle.tell() - start
        if deflate and packed >= size:
            # Deflating made it no smaller: stored as it is instead.
            self.handle.seek(offset)
            self.handle.truncate()
            self.handle.write(self._header(encoded, zipfile.ZIP_STORED, when, 0, 0, 0))
            with open(source, "rb") as reading:
                shutil.copyfileobj(reading, self.handle, 1 << 20)
            method, packed = zipfile.ZIP_STORED, size
            start = offset + 30 + len(encoded)
        end = self.handle.tell()
        self.handle.seek(offset + 14)
        self.handle.write(struct.pack("<III", crc, packed, size))
        self.handle.seek(end)
        if end - start != packed:
            raise BundleError(f"{name} changed as it was written into the bundle.")
        self.entries.append((encoded, method, *when, crc, packed, size, offset))
        return crc

    def add_raw(self, old: _Previous, info: zipfile.ZipInfo, mtime: float) -> None:
        encoded, when = info.filename.encode("utf-8"), _dos(mtime)
        offset = self.handle.tell()
        method = info.compress_type
        self.handle.write(
            self._header(encoded, method, when, info.CRC, info.compress_size, info.file_size)
        )
        for chunk in old.data(info):
            self.handle.write(chunk)
        self.entries.append(
            (encoded, method, *when, info.CRC, info.compress_size, info.file_size, offset)
        )

    def close(self) -> None:
        start = self.handle.tell()
        for name, method, clock, day, crc, packed, size, offset in self.entries:
            self.handle.write(
                struct.pack(
                    "<IHHHHHHIIIHHHHHII",
                    0x02014B50,
                    (3 << 8) | 20,
                    20,
                    0x0800,
                    method,
                    clock,
                    day,
                    crc,
                    packed,
                    size,
                    len(name),
                    0,
                    0,
                    0,
                    0,
                    (stat.S_IFREG | 0o644) << 16,
                    offset,
                )
                + name
            )
        end = self.handle.tell()
        if end >= 0xFFFFFFFF or len(self.entries) >= 0xFFFF:
            raise BundleError("A bundle holds less than 4 GB.")
        self.handle.write(
            struct.pack(
                "<IHHHHIIH",
                0x06054B50,
                0,
                0,
                len(self.entries),
                len(self.entries),
                end - start,
                start,
                0,
            )
        )


def _dense(path: Path) -> bool:
    """Whether a file packs no smaller (a map's values, a photograph by another name): told
    by its first quarter megabyte, so it is stored as it is rather than deflated in vain."""

    with open(path, "rb") as reading:
        sample = reading.read(1 << 18)
    return len(sample) >= 1 << 16 and len(zlib.compress(sample, 1)) > 0.97 * len(sample)


def _crc(path: Path) -> int:
    crc = 0
    with open(path, "rb") as reading:
        while chunk := reading.read(1 << 20):
            crc = zlib.crc32(chunk, crc)
    return crc


def _deflated(data: bytes) -> bytes:
    squeeze = zlib.compressobj(6, zlib.DEFLATED, -15)
    return squeeze.compress(data) + squeeze.flush()


def _dos(mtime: float) -> tuple[int, int]:
    """A time as a zip keeps it: the clock (two-second steps) and the day, from 1980."""

    moment = time.localtime(max(mtime, 315532800.0))
    if moment.tm_year < 1980:
        return 0, (1 << 5) | 1
    clock = (moment.tm_hour << 11) | (moment.tm_min << 5) | (moment.tm_sec // 2)
    day = ((min(moment.tm_year, 2107) - 1980) << 9) | (moment.tm_mon << 5) | moment.tm_mday
    return clock, day


@dataclass(slots=True)
class Packed:
    """A bundle written of a document: where, what it holds, and what was left out."""

    path: Path
    gathered: Gathered
    size: int
    about: dict[str, Any]


def pack(
    document: str | Path,
    target: str | Path | None = None,
    *,
    text: str | None = None,
    embed: bool = True,
) -> Packed:
    """A bundle of ``document`` and everything it names (``gather``), written to ``target``
    (beside it, named as it is, by default). What it names that is missing, or outside its
    folder, is left out and said in the manifest (and in what this answers): never an error.

    ``embed``: what its kind keeps inside a bundled document rather than beside it is put
    there as it is packed -- a deck's figures, shown from figure files of their own, written
    into the deck (its kind's ``bundled``), those files left out unless something else names
    them. The document's own file is left as it is."""

    source = Path(document).expanduser()
    if not source.is_file():
        raise BundleError(f"{source.name} isn\u2019t there to bundle.")
    if source.suffix.lower() not in DOCUMENTS:
        raise BundleError(
            f"{source.name} isn\u2019t a document: a deck or a figure is a .yaml or .json file."
        )
    if embed:
        text = _embedded(source, text)
    gathered = gather(source, text=text)
    target = Path(target).expanduser() if target else source.with_suffix(SUFFIX)
    if target.suffix.lower() != SUFFIX:
        target = target.with_name(target.name + SUFFIX)
    files = dict(gathered.files)
    staged: Path | None = None
    if text is not None:
        # The document as it is now, not as its file was last written.
        staged = target.with_name(f".{target.name}.{secrets.token_hex(4)}.saving{source.suffix}")
        staged.write_text(text, encoding="utf-8")
        files[gathered.document] = staged
    try:
        about = manifest(gathered.document, gathered.kind, left=gathered.left, files=len(files))
        target.parent.mkdir(parents=True, exist_ok=True)
        write(target, files, about)
    finally:
        if staged is not None:
            with contextlib.suppress(OSError):
                staged.unlink()
    return Packed(target, gathered, target.stat().st_size, about)


def _embedded(source: Path, text: str | None) -> str | None:
    """A document's words as a bundle keeps them: with what its kind keeps inside it rather
    than beside it written in (``bundled``: a deck's figure files) -- else as given. Its
    comments and quoting are kept, as the studio keeps them."""

    import tempfile

    try:
        words = text if text is not None else source.read_text(encoding="utf-8")
        data = _parsed(words, source.suffix)
    except Exception:
        return text  # (said as it is gathered: a document that does not read)
    walker = _Walker(Gathered(root=source.parent, document=source.name), source.parent)
    kind = walker.kinds.get(walker.kind_of(data) or "")
    bundled = getattr(kind, "bundled", None)
    if bundled is None:
        return text
    made = bundled(data, source.parent.resolve())
    if made is None or made == data:
        return text
    with tempfile.TemporaryDirectory(prefix="flexo-bundling-") as aside:
        scratch = Path(aside) / source.name
        try:
            kind.save(scratch, made, previous=words)
        except TypeError:
            kind.save(scratch, made)
        return scratch.read_text(encoding="utf-8")


# -- reading -----------------------------------------------------------------------------


class Bundle:
    """A bundle, read as one from a stranger: every entry's name, kind and size checked
    before anything of it is written, and what is written never outside the folder asked.

    A bundle made by hand (a folder zipped in the Finder) opens too: with no manifest, its
    document is the one document at its root (a deck first), and a Finder's ``__MACOSX``
    and a zip of one folder are seen through."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        try:
            self.archive = zipfile.ZipFile(self.path)
        except FileNotFoundError:
            raise BundleError(f"{self.path.name} isn\u2019t there.") from None
        except (zipfile.BadZipFile, OSError, ValueError) as error:
            said = getattr(error, "strerror", None) or "it doesn\u2019t read as a zip"
            raise BundleError(
                f"{self.path.name} can\u2019t be opened as a Flexo bundle: {said}."
            ) from None
        try:
            self.entries, self.prefix = self._checked()
            self.manifest = self._manifest()
            self.document = self._document()
        except BaseException:
            self.archive.close()
            raise

    def __enter__(self) -> Bundle:
        return self

    def __exit__(self, *error: object) -> None:
        self.close()

    def close(self) -> None:
        self.archive.close()

    @property
    def names(self) -> list[str]:
        """Its files, by their names from its root (the manifest aside)."""

        return [name for name in self.entries if name != MANIFEST]

    @property
    def kind(self) -> str:
        return str(self.manifest.get("kind") or "")

    @property
    def left(self) -> list[dict[str, str]]:
        """What its maker's document named that is not in it (``missing``, ``outside``)."""

        said = []
        for why in ("missing", "outside"):
            for item in self.manifest.get(why) or []:
                if isinstance(item, Mapping) and isinstance(item.get("name"), str):
                    said.append(
                        {
                            "name": str(item["name"]),
                            "where": str(item.get("where") or ""),
                            "why": why,
                        }
                    )
        return said[:200]

    def info(self, name: str) -> zipfile.ZipInfo:
        return self.entries[name]

    def _checked(self) -> tuple[dict[str, zipfile.ZipInfo], str]:
        infos = self.archive.infolist()
        if len(infos) > MOST_FILES:
            raise BundleError(
                f"{self.path.name} holds more than {MOST_FILES:,} files: it isn\u2019t opened."
            )
        total = 0
        found: dict[str, zipfile.ZipInfo] = {}
        folded: dict[str, str] = {}
        folders: set[str] = set()
        for info in infos:
            name = info.filename
            if name.startswith("__MACOSX/") or name.split("/")[-1] in _SKIPPED_FILES:
                continue
            if (
                _unsafe(name.rstrip("/"))
                or len(name.encode("utf-8")) > 1024
                or any(len(part.encode("utf-8")) > 255 for part in name.split("/"))
            ):
                raise BundleError(
                    f"{self.path.name} names a file \u201c{name[:80]}\u201d outside itself: "
                    "it isn\u2019t opened."
                )
            mode = (info.external_attr >> 16) & 0o170000
            if info.is_dir() or mode == stat.S_IFDIR:
                folders.add(name.rstrip("/"))
                continue
            if mode not in (0, stat.S_IFREG):
                what = "a link" if mode == stat.S_IFLNK else "something that is not a file"
                raise BundleError(
                    f"{self.path.name} holds {what} (\u201c{name[:80]}\u201d): "
                    "it isn\u2019t opened."
                )
            if info.flag_bits & 0x1:
                raise BundleError(f"{self.path.name} is encrypted: it isn\u2019t opened.")
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise BundleError(
                    f"{self.path.name} is packed in a way Flexo doesn\u2019t read: "
                    "it isn\u2019t opened."
                )
            total += info.file_size
            if total > MOST_BYTES:
                raise BundleError(
                    f"{self.path.name} would unpack to more than 3 GB: it isn\u2019t opened."
                )
            if info.compress_size and info.file_size / info.compress_size > 2000:
                raise BundleError(
                    f"{self.path.name} packs \u201c{name[:80]}\u201d too tightly to be real: "
                    "it isn\u2019t opened."
                )
            key = unicodedata.normalize("NFC", name).casefold()
            if key in folded:
                raise BundleError(
                    f"{self.path.name} holds two files a Mac would take for one "
                    f"(\u201c{folded[key][:80]}\u201d and \u201c{name[:80]}\u201d): "
                    "it isn\u2019t opened."
                )
            folded[key] = name
            found[name] = info
        for name in found:
            parts = name.split("/")
            for depth in range(1, len(parts)):
                folder = unicodedata.normalize("NFC", "/".join(parts[:depth])).casefold()
                if folder in folded:
                    raise BundleError(
                        f"{self.path.name} holds \u201c{folded[folder][:80]}\u201d as a file and a "
                        "folder: it isn\u2019t opened."
                    )
        # A folder zipped in the Finder (talk/talk.yaml...): its folder is seen through.
        prefix = ""
        tops = {name.split("/")[0] for name in found}
        if MANIFEST not in found and len(tops) == 1 and all("/" in name for name in found):
            prefix = f"{tops.pop()}/"
            found = {name[len(prefix) :]: info for name, info in found.items()}
        return found, prefix

    def _manifest(self) -> dict[str, Any]:
        info = self.entries.get(MANIFEST)
        if info is None or info.file_size > MOST_MANIFEST:
            return {}
        try:
            said = json.loads(self.archive.read(info).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, zipfile.BadZipFile, OSError):
            return {}
        if not isinstance(said, dict) or said.get("format") != FORMAT:
            return {}
        return said

    def _document(self) -> str:
        named = self.manifest.get("document")
        if isinstance(named, str) and named in self.entries and named.lower().endswith(DOCUMENTS):
            return named
        roots = [
            name for name in self.names if "/" not in name and name.lower().endswith(DOCUMENTS)
        ]
        if len(roots) == 1:
            return roots[0]
        # Several: a deck, else a figure -- told by their keys, as the studio tells them.
        for keys in (("slides",), ("nodes", "figure")):
            for name in sorted(roots):
                with contextlib.suppress(Exception):
                    data = _parsed(
                        self.read(name, most=10_000_000).decode("utf-8"), Path(name).suffix
                    )
                    if isinstance(data, dict) and any(key in data for key in keys):
                        return name
        if roots:
            return sorted(roots)[0]
        raise BundleError(f"{self.path.name} holds no deck or figure to open.")

    def read(self, name: str, *, most: int = MOST_BYTES) -> bytes:
        info = self.entries[name]
        if info.file_size > most:
            raise BundleError(f"{name} is too large to read.")
        return self.archive.read(info)

    def extract(
        self, folder: str | Path, names: Iterable[str] | None = None, *, replace: bool = False
    ) -> list[str]:
        """Write its files (``names``, else all but the manifest) into ``folder``, each at
        its name: never outside it, whatever is there already (a link to elsewhere is not
        written through). ``replace``: each written beside its file and moved over it, so
        what reads it meanwhile reads the old or the new, never half of either. The names
        written."""

        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        real = folder.resolve()
        written: list[str] = []
        for name in self.names if names is None else list(names):
            info = self.entries[name]
            target = folder.joinpath(*name.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            place = target.parent.resolve()
            if place != real and real not in place.parents:
                raise BundleError(f"{name} would be written outside the folder: it isn\u2019t.")
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise BundleError(
                    f"{name} is not a file in the folder: it isn\u2019t written over."
                )
            partial = target.with_name(f".{target.name}.{secrets.token_hex(4)}.saving")
            try:
                with self.archive.open(info) as reading, open(partial, "xb") as writing:
                    shutil.copyfileobj(reading, writing, 1 << 20)
                os.chmod(partial, 0o644)
                if not replace and target.exists():
                    raise BundleError(
                        f"{name} is in the folder already: it isn\u2019t written over."
                    )
                os.replace(partial, target)
            except zipfile.BadZipFile as error:
                raise BundleError(
                    f"{self.path.name} is damaged: {name} doesn\u2019t read ({error})."
                ) from None
            finally:
                with contextlib.suppress(OSError):
                    partial.unlink()
            written.append(name)
        return written


def unpack(bundle: str | Path, folder: str | Path) -> Bundle:
    """Write a bundle's files as a plain folder: ``folder``, made if it is not there, and
    never written over (a file of the bundle's name there already is an error, said before
    anything is written). The bundle, read (closed)."""

    folder = Path(folder).expanduser()
    with Bundle(bundle) as opened:
        taken = [name for name in opened.names if folder.joinpath(*name.split("/")).exists()]
        if taken:
            listed = ", ".join(taken[:3]) + (
                f" and {len(taken) - 3} more" if len(taken) > 3 else ""
            )
            raise BundleError(f"{folder.name} has {listed} already: choose another folder.")
        opened.extract(folder)
    return opened


def is_bundle(path: str | Path) -> bool:
    return Path(path).suffix.lower() == SUFFIX


def runs_python(bundle: Bundle) -> list[str]:
    """The Python files a bundle holds: what would run, were its plots drawn."""

    return [name for name in bundle.names if name.lower().endswith(".py")]


def snapshot(folder: Path, *, keep_build: bool = False) -> dict[str, tuple[int, int]]:
    """Every file of a folder a bundle of it holds (``_kept_name``), by its name in the
    bundle, with its time (ns) and size: what has changed since, at a glance. A ``build``
    folder of exports is left out, unless the bundle had one when it was opened."""

    found: dict[str, tuple[int, int]] = {}

    def walk(at: Path, prefix: str) -> None:
        try:
            entries = list(os.scandir(at))
        except OSError:
            return
        for entry in entries:
            name = f"{prefix}{entry.name}"
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name in _SKIPPED_FOLDERS or (name == "build" and not keep_build):
                        continue
                    walk(Path(entry.path), f"{name}/")
                elif entry.is_file(follow_symlinks=False) and _kept_name(name):
                    facts = entry.stat(follow_symlinks=False)
                    found[name] = (facts.st_mtime_ns, facts.st_size)
            except OSError:
                continue
            if len(found) > MOST_FILES:
                raise BundleError(f"A bundle holds at most {MOST_FILES:,} files.")

    walk(folder, "")
    return found
