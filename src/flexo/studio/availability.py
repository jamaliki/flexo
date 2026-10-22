"""Who can answer the assistant, as last found on this computer.

A page's first call, /api/session, says whether the assistant can answer, and finding that
out imports the providers' SDKs and makes their clients: a second of Python and two thousand
modules, which the window's first slide waited for. What decides it -- the SDKs installed and
their versions, the environment's keys and settings, the Anthropic SDK's configuration folder
-- is told by a fingerprint (no key itself kept, only a hash of them); while that is the same,
the answer last found is the answer, given at once while the studio finds it out again on a
thread of its own (``flexo.studio.warmup.warm_assistant``).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

_PREFIXES = ("ANTHROPIC_", "OPENAI_", "FLEXO_STUDIO_")
"""The environment's settings the providers read (their keys, addresses, models, hints)."""
FILE = "assistant.json"


def _config_folder() -> Path:
    """The Anthropic SDK's configuration folder (its profiles, ``ant auth login``'s)."""

    given = os.environ.get("ANTHROPIC_CONFIG_DIR")
    if given:
        return Path(given)
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        return (Path(appdata) if appdata else Path.home() / "AppData" / "Roaming") / "Anthropic"
    return Path.home() / ".config" / "anthropic"


def fingerprint() -> str:
    """What decides who can answer, hashed."""

    import importlib.metadata

    said = hashlib.sha256()
    for name in sorted(os.environ):
        if name.startswith(_PREFIXES):
            said.update(f"{name}={os.environ[name]}\n".encode("utf-8", "replace"))
    for package in ("anthropic", "openai"):
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            version = "-"
        said.update(f"{package} {version}\n".encode())
    # (And who is asked, as this flexo asks them.)
    with contextlib.suppress(OSError):
        facts = (Path(__file__).parent / "assistant.py").stat()
        said.update(f"assistant {facts.st_mtime_ns} {facts.st_size}\n".encode())
    folder = _config_folder()
    said.update(f"{folder}\n".encode("utf-8", "replace"))
    with contextlib.suppress(OSError):
        for path in sorted(folder.rglob("*")):
            facts = path.stat()
            said.update(f"{path} {facts.st_mtime_ns} {facts.st_size}\n".encode("utf-8", "replace"))
    return said.hexdigest()


def _file() -> Path:
    from flexo.studio.sessions import _folder

    return _folder().parent / FILE


def remembered() -> dict[str, Any] | None:
    """Who can answer, as last found here -- if nothing that decides it has changed since."""

    try:
        kept = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(kept, dict) or kept.get("fingerprint") != fingerprint():
        return None
    said = kept.get("availability")
    return said if isinstance(said, dict) else None


def remember(said: dict[str, Any]) -> None:
    """Keep who can answer (``Assistant.availability``), as a new assistant finds it now --
    before anyone has chosen another to answer, or another model."""

    keys = ("available", "why", "provider", "name", "model", "providers")
    kept = {"fingerprint": fingerprint(), "availability": {key: said.get(key) for key in keys}}
    with contextlib.suppress(OSError):
        target = _file()
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{target.name}.{secrets.token_hex(4)}")
        partial.write_text(json.dumps(kept), encoding="utf-8")
        os.replace(partial, target)
