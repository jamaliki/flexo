"""Build the first coordinate-free Flexo acceptance figure."""

from __future__ import annotations

from pathlib import Path

from flexo.compiler import compile_figure
from flexo.gallery import vertical_slice
from flexo.serialization import save_figure


def main() -> None:
    destination = Path(__file__).parent / "build"
    figure = vertical_slice()
    save_figure(figure, Path(__file__).with_suffix(".yaml"))
    compile_figure(figure).document.write(destination / "vertical-slice.editable.svg")


if __name__ == "__main__":
    main()
