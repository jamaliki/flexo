"""The tutorial's figures, built from the tutorial itself.

Every ```python block in ``docs/tutorial.md`` that starts with ``# step: <name>``
is run as written. A block leaves either ``figure`` (one figure) or ``figures``
(a mapping from a short name to a figure, for one figure in several looks), and
each figure is built into ``examples/build/tutorial/<name>[-<look>]``. The
```yaml block marked ``# step: yaml`` is loaded as a figure file. So the code a
reader copies is the code that drew the picture beside it, and
``tests/unit/test_tutorial.py`` checks that every step compiles clean.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import flexo

HERE = Path(__file__).resolve().parent
TUTORIAL = HERE.parent / "docs" / "tutorial.md"
OUT = HERE / "build" / "tutorial"

_BLOCK = re.compile(r"```(python|yaml)\n(# step: ([\w-]+)\n.*?)```", re.DOTALL)


def steps() -> dict[str, dict[str, flexo.Figure | flexo.FigureSpec]]:
    """Each step's figures, by step name and then by look (``""`` for a lone figure)."""

    result: dict[str, dict[str, flexo.Figure | flexo.FigureSpec]] = {}
    for language, source, name in _BLOCK.findall(TUTORIAL.read_text()):
        if language == "yaml":
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / f"{name}.yaml"
                path.write_text(source)
                result[name] = {"": flexo.load_figure(path)}
            continue
        scope: dict[str, object] = {}
        exec(compile(source, f"tutorial:{name}", "exec"), scope)
        if "figures" in scope:
            result[name] = dict(scope["figures"])  # type: ignore[call-overload]
        else:
            result[name] = {"": scope["figure"]}  # type: ignore[dict-item]
    return result


def main() -> None:
    for name, figures in steps().items():
        for look, figure in figures.items():
            result = flexo.build(
                figure,
                OUT,
                stem=f"{name}-{look}" if look else name,
                formats=("editable", "png"),
                dpi=200,
            )
            print(result.summary())


if __name__ == "__main__":
    main()
