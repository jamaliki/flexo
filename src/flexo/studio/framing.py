"""A drawing sent to the page with its pictures as they are, not written into JSON again.

A slide drawing a protein is half a megabyte of SVG and more, full of quotation marks: put
into a JSON answer, every one of them is escaped as it is written, and read back as it is
read -- a few milliseconds in the studio and as many in the page, at every key typed on it.
A page that says it reads them so (``ACCEPT``, in its ``Accept``) is answered instead with
the answer's JSON, on a line of its own, with each page's ``svg`` left out of it, and the
SVGs after it, as they are: where each one is, in bytes after that line, is said in the JSON
(``"framed": [[path, start, length], ...]``, ``path`` the keys and indices from the answer
to the ``svg`` it is). Anything else is answered in JSON, as before.
"""

from __future__ import annotations

import json
from typing import Any

ACCEPT = "application/x-flexo-framed"
"""What a page that reads framed answers says it accepts, and what such an answer is."""


def framed(answer: Any) -> bytes | None:
    """``answer`` framed, or None when it carries no drawing to frame."""

    if not isinstance(answer, dict):
        return None
    found: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for path, drawing in ((("pages",), answer), (("drawing", "pages"), answer.get("drawing"))):
        if not isinstance(drawing, dict) or not isinstance(drawing.get("pages"), list):
            continue
        for index, page in enumerate(drawing["pages"]):
            if isinstance(page, dict) and isinstance(page.get("svg"), str):
                found.append(((*path, index, "svg"), page))
    if not found:
        return None
    # (The answer as it is, but for the pages carrying an SVG: those copied without it.)
    head = dict(answer)
    if isinstance(answer.get("drawing"), dict):
        head["drawing"] = dict(answer["drawing"])
    for holder in (head, head.get("drawing")):
        if isinstance(holder, dict) and isinstance(holder.get("pages"), list):
            holder["pages"] = [
                {key: value for key, value in page.items() if key != "svg"}
                if isinstance(page, dict) and isinstance(page.get("svg"), str)
                else page
                for page in holder["pages"]
            ]
    pictures: list[bytes] = []
    places: list[list[Any]] = []
    start = 0
    for path, page in found:
        data = page["svg"].encode("utf-8")
        places.append([list(path), start, len(data)])
        pictures.append(data)
        start += len(data)
    head["framed"] = places
    line = json.dumps(head, ensure_ascii=False, default=str).encode("utf-8")
    return b"".join([line, b"\n", *pictures])


def read(body: bytes) -> Any:
    """A framed answer read back, as the page reads it: the JSON, each ``svg`` put back."""

    end = body.index(b"\n")
    answer = json.loads(body[:end])
    tail = body[end + 1 :]
    for path, start, length in answer.pop("framed", []):
        holder = answer
        for key in path[:-1]:
            holder = holder[key]
        holder[path[-1]] = tail[start : start + length].decode("utf-8")
    return answer
