"""Make Editable (``flexo.studio.editable``): a drawing placed as a picture made the shapes it
draws, one group put exactly where its picture was drawn and scaled to its box, read as the
picture showed it (restyled), its colours the theme's, its ids its own; and ``svgimport``'s
``origin``, which puts a drawing's page where its picture was."""

from __future__ import annotations

from pathlib import Path

import pytest

from flexo import freeform, svgimport
from flexo.restyle import restyle_of
from flexo.studio.editable import NotEditable, is_drawing, keeper, shapes_of_picture

# A page of 200 by 100 pixels (150 by 75 points): a box in its top left quarter, a named one,
# words, and a black line across its foot.
DRAWING = """<?xml version="1.0" encoding="UTF-8"?>
<!-- Created with Inkscape -->
<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100" id="svg1">
  <g id="g20">
    <rect id="rect3" x="0" y="0" width="100" height="50" fill="#4a90d9"/>
    <rect id="encoder" x="120" y="10" width="60" height="30" fill="#ffffff" stroke="#000000"/>
    <text id="text4" x="10" y="80" font-size="12" fill="#000000">Encoder</text>
    <path id="path5" d="M 0 95 L 200 95" stroke="#000000" stroke-width="2" fill="none"/>
  </g>
</svg>
"""


def written(folder: Path, name: str = "module.svg", text: str = DRAWING) -> Path:
    (folder / "assets").mkdir(exist_ok=True)
    target = folder / "assets" / name
    target.write_text(text, encoding="utf-8")
    return target


def flat(shapes: list) -> list[dict]:
    out = []
    for shape in shapes:
        out.append(shape)
        if shape.get("kind") == "group":
            out += flat(shape.get("shapes") or [])
    return out


def test_the_drawings_page_is_put_in_the_box_its_picture_was_drawn_in(tmp_path: Path) -> None:
    source = written(tmp_path)
    # Its page, 150 by 75 points, drawn 400 by 200 at (500, 100): every place and length
    # scaled by 8/3 from there.
    made = shapes_of_picture(source, (500, 100, 400, 200), family="IBM Plex Sans")
    group = made.group
    assert group["kind"] == "group" and group["id"] == "module"
    shapes = {shape.get("id"): shape for shape in flat(group["shapes"])}
    # (A program's own ids, rect3, name nothing: the first box is the blue one.)
    box = next(shape for shape in flat(group["shapes"]) if shape["kind"] == "rectangle")
    assert box["at"] == pytest.approx([500, 100], abs=0.05)
    assert box["size"] == pytest.approx([200, 100], abs=0.05)
    left, top, right, bottom = freeform.bounds(group)
    assert (left, right) == pytest.approx((500, 900), abs=1.5)
    assert bottom <= 300.5 and top >= 99.5
    # (The drawing's one outer group is gone: its pieces are the group's own, one Ungroup away.)
    assert len(group["shapes"]) == 4
    # Its ids its own, as the drawer named them -- not the program's, nor prefixed.
    assert "encoder" in shapes and not any(str(key).startswith("flexo-editable") for key in shapes)
    assert made.count == 5 and made.cropped == 0


def test_it_is_read_as_its_picture_was_drawn_its_colours_the_themes(tmp_path: Path) -> None:
    source = written(tmp_path)
    restyle = restyle_of(
        None, [{"id": "text4", "words": "Decoder", "bold": True}], {"#4a90d9": "#2e7d32"}
    )
    made = shapes_of_picture(
        source,
        (0, 0, 150, 75),
        restyle=restyle,
        family="IBM Plex Sans",
        roles={"ink": "#111111", "canvas": "#ffffff"},
    )
    shapes = flat(made.group["shapes"])
    words = next(shape for shape in shapes if shape["kind"] == "text")
    # Its words as the picture showed them: changed, bold, in the font they were set in.
    assert (
        words["text"] == "Decoder"
        and words.get("bold") is True
        and words.get("font") == "IBM Plex Sans"
    )
    # A colour changed for the picture is that colour; black and white the theme's ink and paper.
    assert any(shape.get("fill") == "#2e7d32" for shape in shapes)
    line = next(shape for shape in shapes if shape["kind"] == "line")
    assert line.get("line", "ink") == "ink"
    encoder = next(shape for shape in shapes if shape.get("id") == "encoder")
    assert encoder["fill"] == "paper"


def test_a_crop_leaves_out_what_it_hid_and_the_name_is_free(tmp_path: Path) -> None:
    source = written(tmp_path)
    # Only its left half shown: the named box, wholly in the right half, is left out.
    made = shapes_of_picture(source, (0, 0, 150, 75), kept_box=(0, 0, 75, 75), taken=["module"])
    assert made.cropped == 1
    assert not any(shape.get("id") == "encoder" for shape in flat(made.group["shapes"]))
    assert made.group["id"] == "module-2"


def test_what_is_no_drawing_is_said(tmp_path: Path) -> None:
    (tmp_path / "photo.png").write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c6360f8cf00000301010018dd8db00000000049454e44ae426082"
        )
    )
    with pytest.raises(NotEditable, match="photograph"):
        shapes_of_picture(tmp_path / "photo.png", (0, 0, 10, 10))
    with pytest.raises(NotEditable, match="can\u2019t be read"):
        shapes_of_picture(tmp_path / "gone.svg", (0, 0, 10, 10))
    assert is_drawing("assets/a.svg") and is_drawing("art.ai#2") and is_drawing("x.PDF")
    assert not is_drawing("photo.png") and not is_drawing(None)


def test_a_picture_kept_among_the_shapes_is_written_beside_the_document(tmp_path: Path) -> None:
    keep = keeper(tmp_path, "module")
    assert keep(b"\x89PNG", ".png") == "assets/module-part-1.png"
    assert keep(b"\x89PNG", ".png") == "assets/module-part-1.png"  # (the same bytes: the same file)
    assert keep(b"other", ".png") == "assets/module-part-2.png"
    assert (tmp_path / "assets" / "module-part-2.png").read_bytes() == b"other"


def test_svgimport_puts_the_page_at_its_origin() -> None:
    made = svgimport.shapes_of(DRAWING, scale=2.0, origin=(40, 30))
    rectangle = next(shape for shape in flat(made.shapes) if shape["kind"] == "rectangle")
    # (The page's top left at the origin, scaled from there: a pixel is 0.75 of a point.)
    assert rectangle["at"] == pytest.approx([40, 30]) and rectangle["size"] == pytest.approx(
        [150, 75]
    )
