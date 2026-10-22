"""What a cache of drawings parsed into the page keeps (``studio/static/studio/keeping.js``):
those on screen, and of the rest the newest, up to a count and a total size -- run in Node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import freeform

SCRIPT = Path(freeform.__file__).parent / "studio" / "static" / "studio" / "keeping.js"


def run(body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = (
        f"const K = await import({json.dumps(SCRIPT.as_uri())});\n"
        f"console.log(JSON.stringify(await (async () => {{ {body} }})()));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_oldest_drawings_off_screen_go_past_a_count() -> None:
    assert run("""
      const entries = [1, 2, 3, 4, 5].map((n) => [`d${n}`, { shown: n === 1, size: 10 }]);
      return K.overflow(entries, { inUse: (d) => d.shown, size: (d) => d.size, most: 2 });
    """) == ["d3", "d2"]


def test_large_drawings_go_past_a_size_in_all_however_few() -> None:
    # A slide edited key by key: each drawing of it half a megabyte, a megabyte kept at most.
    assert run("""
      const entries = Array.from({ length: 6 }, (_, n) => [`d${n}`, { shown: false, size: 5e5 }]);
      return K.overflow(entries, { inUse: (d) => d.shown, size: (d) => d.size, budget: 1e6 });
    """) == ["d3", "d2", "d1", "d0"]


def test_drawings_on_screen_stay_whatever_their_size() -> None:
    assert (
        run("""
      const entries = [["big", { shown: true, size: 9e9 }], ["small", { shown: false, size: 1 }]];
      const options = { inUse: (d) => d.shown, size: (d) => d.size, most: 1, budget: 10 };
      return K.overflow(entries, options);
    """)
        == []
    )
