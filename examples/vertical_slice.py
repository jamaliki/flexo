"""Build the acceptance figure, and save it as YAML to show the two are one thing.

The Python builder lowers into exactly the validated, versioned schema that YAML
and JSON parse into, so this script writes both: the compiled figure, and
`vertical_slice.yaml <vertical_slice.yaml>`_ -- the same figure as interchange,
which ``uv run flexo build examples/vertical_slice.yaml`` compiles to the same
SVG. The authoring source is ``vertical_slice`` in
`flexo/gallery.py <../src/flexo/gallery.py>`_.

Run it with ``uv run python examples/vertical_slice.py``.
"""

from __future__ import annotations

from pathlib import Path

from flexo import build, save_figure
from flexo.gallery import vertical_slice

OUTPUT = Path(__file__).parent / "build"


def main() -> None:
    figure = vertical_slice()
    print(save_figure(figure, Path(__file__).with_suffix(".yaml")))
    result = build(
        figure,
        OUTPUT,
        stem="vertical-slice",
        formats=("editable", "png"),
        dpi=200.0,
    )
    print(result.summary())


if __name__ == "__main__":
    main()
