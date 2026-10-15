"""Every script of the studio's is read as the module the page loads it as.

A module that declares one name twice (two pieces of work each adding a ``drawingOf`` to the
figure editor) is not run at all: the page it belongs to opens on nothing. Node reads a ``.js``
file as a script, which lets that pass, so each is checked as a ``.mjs`` copy.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).parents[2] / "src" / "flexo" / "studio" / "static"


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
@pytest.mark.parametrize(
    "script", sorted(STATIC.rglob("*.js")), ids=lambda script: str(script.relative_to(STATIC))
)
def test_a_studio_script_reads_as_a_module(script: Path, tmp_path: Path) -> None:
    copy = tmp_path / f"{script.stem}.mjs"
    copy.write_bytes(script.read_bytes())
    result = subprocess.run(["node", "--check", str(copy)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
