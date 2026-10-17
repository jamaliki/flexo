"""A figure open in the studio is drawn again when a file its parts draw is edited -- its
picture, a PDF's page, the picture drawn over it -- as when its theme or a plot's data is: the
studio watches what a drawing says it was drawn from (``Drawing.files``)."""

from __future__ import annotations

from pathlib import Path

from flexo.studio.figure_kind import FigureKind

SVG_NS = "http://www.w3.org/2000/svg"


def test_a_figure_s_pictures_are_what_it_is_drawn_from(tmp_path: Path) -> None:
    (tmp_path / "art.svg").write_text(
        f'<svg xmlns="{SVG_NS}" viewBox="0 0 40 20" width="40" height="20">'
        '<rect width="40" height="20" fill="#3f7fc0"/></svg>',
        encoding="utf-8",
    )
    (tmp_path / "over.svg").write_text((tmp_path / "art.svg").read_text(), encoding="utf-8")
    text = (
        "figure: {id: pictures}\n"
        "nodes:\n"
        "  - {id: art, kind: image, properties: {source: art.svg}}\n"
        "  - {id: next, label: Next}\n"
        "shapes:\n"
        "  - {kind: picture, at: [0, 0], size: [20, 10], source: over.svg}\n"
    )
    drawing = FigureKind().draw({"text": text}, tmp_path)
    assert drawing.pages and drawing.pages[0].svg
    files = {Path(file).resolve() for file in drawing.files}
    assert (tmp_path / "art.svg").resolve() in files
    assert (tmp_path / "over.svg").resolve() in files
