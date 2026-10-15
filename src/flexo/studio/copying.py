"""Copying out of the studio: what the page copies, drawn for other apps to paste.

The page has its document drawn (each page's SVG, as the studio drew it for it) and knows
what is chosen in it. Copying, it sends that drawing and the ids of what is copied; here
they are cut out of it (``flexo.copied``), the photographs the page was shown by address
carried at their full size. The Mac app puts the drawing on the Mac's clipboard itself,
each form when an app asks for it; a browser is answered (``/api/copy``) with what a web
page may put there: a picture, and the drawing as SVG.
"""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import parse_qs, urlparse

from flexo.copied import Copied, cut_out

PICTURE_ROUTE = "/api/picture"


def copied(workspace: Any, svg: str, keep: list[str] | None = None, *, title: str = "") -> Copied:
    """What is copied (the ids ``keep``; all of it, none named) out of the page's drawing
    ``svg``. Raises ``ValueError`` when it draws nothing."""

    def picture(href: str) -> str | None:
        found = urlparse(href)
        if found.path != PICTURE_ROUTE:
            return None
        name = (parse_qs(found.query).get("path") or [""])[0]
        try:
            from flexo.artwork import load_artwork

            return load_artwork("picture", str(workspace.path(name))).data_uri or None
        except Exception:  # gone since, or not a picture: left out
            return None

    # (Photographs carried only once the copy is first drawn: copying takes no longer for one.)
    return Copied(
        cut_out(str(svg or ""), [str(each) for each in keep or []]), title=title, picture=picture
    )


def answer(workspace: Any, data: dict[str, Any]) -> dict[str, Any]:
    """``/api/copy``: what is copied, as a web page puts it on the clipboard -- its picture
    (``png``, base64) and the drawing as SVG, its words outlines (``svg``) -- and its size in
    points and in pixels."""

    made = copied(
        workspace, data.get("svg", ""), data.get("keep"), title=str(data.get("title") or "")
    )
    width, height = made.size
    across, down = made.pixels()
    return {
        "png": base64.b64encode(made.png()).decode("ascii"),
        "svg": made.svg(),
        "width": width,
        "height": height,
        "pixels": [across, down],
    }
