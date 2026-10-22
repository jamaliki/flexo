"""Pictures a drawing carries in itself go to the studio's page by address: taken out of the
drawing as it is sent, sent once and kept by the browser, found again by a studio started
again, and copied out of the page as the very data they were."""

from __future__ import annotations

import base64
import hashlib
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from flexo.studio import Drawing, Page, inline_pictures
from flexo.studio.copying import copied
from flexo.studio.figure_kind import SAMPLE_FIGURE
from flexo.studio.server import start

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@pytest.fixture(autouse=True)
def _sessions(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("run")))
    # (Each test a studio of its own: what another kept in memory, kept on another's disk.)
    inline_pictures._KEPT.clear()


def _uri(kind: str, data: bytes) -> str:
    return f"data:{kind};base64,{base64.b64encode(data).decode('ascii')}"


def _picture(kind: str, size: int) -> bytes:
    """A picture of noise (it does not compress), ``size`` pixels square."""

    import io
    import random

    from PIL import Image

    noise = random.Random(size)
    image = Image.frombytes(
        "RGB", (size, size), bytes(noise.randrange(256) for _ in range(size * size * 3))
    )
    out = io.BytesIO()
    image.save(out, kind)
    return out.getvalue()


PNG = _picture("PNG", 64)
SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    + "".join(f'<rect x="1" y="1" width="8" height="8" fill="#{n:06x}"/>' for n in range(300))
    + "</svg>"
).encode()
SMALL = _picture("PNG", 8)
GIF = _picture("GIF", 96)


def _drawing() -> str:
    """A page carrying pictures: a large PNG and SVG (sent apart), a small PNG and a GIF (left
    where they are)."""

    images = [
        ("big", _uri("image/png", PNG)),
        ("vectors", _uri("image/svg+xml", SVG)),
        ("small", _uri("image/png", SMALL)),
        ("playing", _uri("image/gif", GIF)),
    ]
    inside = "\n".join(
        f'<image id="{name}" x="0" y="0" width="10" height="10" href="{href}"/>'
        for name, href in images
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100pt" '
        f'height="100pt">\n<rect id="paper" width="100" height="100" fill="#ffffff"/>\n{inside}\n'
        '<rect id="box" x="10" y="10" width="20" height="20" fill="#336699"/>\n</svg>'
    )


def _served(tmp_path: Path, drawn: str):
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    server, workspace = start(tmp_path, browser=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    doc = workspace.open("figure.yaml")
    doc.kind.draw = lambda document, base, hints: Drawing([Page("figure", drawn)])
    return server, workspace, doc


def _stop(server, workspace, doc) -> None:
    del doc.kind.draw
    workspace.close()
    server.shutdown()
    server.server_close()


def _get(url: str, **headers: str):
    try:
        return OPENER.open(urllib.request.Request(url, headers=headers))
    except urllib.error.HTTPError as error:
        return error


def test_pictures_a_drawing_carries_are_sent_to_the_page_once_by_address(tmp_path: Path) -> None:
    drawn = _drawing()
    server, workspace, doc = _served(tmp_path, drawn)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        result = workspace.draw("figure.yaml", doc.document, 1, {}, {})
        (page,) = result["pages"]
        svg = page["svg"]
        links = re.findall(r'href="(/api/picture\?made=[^"]+)"', svg)
        assert len(links) == 2 and all(f"&amp;token={workspace.token}" in link for link in links)
        # The large PNG and SVG are sent apart; the small picture and the GIF stay where they were.
        assert _uri("image/png", PNG) not in svg and _uri("image/svg+xml", SVG) not in svg
        assert _uri("image/png", SMALL) in svg and _uri("image/gif", GIF) in svg
        assert len(drawn) - len(svg) > len(PNG) + len(SVG)
        # (The rest of the drawing as the kind drew it.)
        unlinked = re.sub(r'href="/api/picture\?made=[^"]+"', 'href="?"', svg)
        expected = drawn.replace(_uri("image/png", PNG), "?").replace(
            _uri("image/svg+xml", SVG), "?"
        )
        assert unlinked == expected
        for link, body, kind in zip(links, (PNG, SVG), ("image/png", "image/svg+xml"), strict=True):
            address = url + link.replace("&amp;", "&")
            name = re.search(r"made=([^&]+)", address).group(1)
            assert name == f"{hashlib.sha256(base64.b64encode(body)).hexdigest()[:32]}.{kind[6:9]}"
            with _get(address) as answer:
                assert answer.status == 200 and answer.read() == body
                assert answer.headers["Content-Type"] == kind
                assert answer.headers["Cache-Control"] == "max-age=31536000, immutable"
                assert answer.headers["ETag"] == f'"{name}"'
            # Asked after by its tag, it has not changed.
            again = _get(address, **{"If-None-Match": f'"{name}"'})
            assert again.code == 304 and again.read() == b""
            # (It is the studio's: the page's token is wanted.)
            assert _get(address.replace(workspace.token, "another")).code == 403
        for wrong in ("0" * 32 + ".png", "../figure.yaml", "a" * 32 + ".gif"):
            assert _get(f"{url}/api/picture?made={wrong}&token={workspace.token}").code == 404
        # Drawn again unchanged, the drawing is not sent again: the page has it.
        again = workspace.draw("figure.yaml", doc.document, 2, {"figure": page["hash"]}, {})
        assert "svg" not in again["pages"][0]
    finally:
        _stop(server, workspace, doc)


def test_a_picture_sent_apart_is_found_by_a_studio_started_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drawn = _drawing()
    svg = inline_pictures.linked(drawn, "a-token")
    names = re.findall(r"made=([^&]+)&amp;token=a-token", svg)
    assert len(names) == 2
    # Another run of the studio: nothing in its memory, its pictures found where they were kept.
    inline_pictures._KEPT.clear()
    assert inline_pictures.found(names[0]) == (PNG, "image/png")
    assert inline_pictures.found(names[1]) == (SVG, "image/svg+xml")
    assert sorted(path.name for path in inline_pictures.folder().iterdir()) == sorted(names)
    # A page left open on it, its drawings carrying the token of the run before, is given this
    # run's (as a photograph's address is).
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    server, workspace, doc = _served(tmp_path, svg.replace("a-token", "another-run"))
    try:
        (page,) = workspace.draw("figure.yaml", doc.document, 1, {}, {})["pages"]
        assert (
            page["svg"].count(f"token={workspace.token}") == 2 and "another-run" not in page["svg"]
        )
    finally:
        _stop(server, workspace, doc)
    # None kept on disk where none is to be: kept in memory alone.
    monkeypatch.setenv("FLEXO_PICTURE_CACHE", "0")
    inline_pictures._KEPT.clear()
    other = (
        _drawing()
        .replace("#336699", "#993366")
        .replace(_uri("image/png", PNG), _uri("image/png", PNG + b"more"))
    )
    (name,) = re.findall(r"made=([^&]+)\.png", inline_pictures.linked(other, "t"))
    assert (
        inline_pictures.folder() is None
        and inline_pictures.found(f"{name}.png")[0] == PNG + b"more"
    )


def test_only_the_studio_s_page_is_sent_pictures_by_address(tmp_path: Path) -> None:
    drawn = _drawing()
    server, workspace, doc = _served(tmp_path, drawn)
    try:
        workspace.draw("figure.yaml", doc.document, 1, {}, {})
        # What the kind drew is as it was: an agent's look at the document carries its pictures.
        (looked,) = workspace.drawing_of("figure.yaml").pages
        assert looked.svg == drawn
    finally:
        _stop(server, workspace, doc)


def test_a_picture_sent_apart_is_copied_out_as_the_data_it_was(tmp_path: Path) -> None:
    drawn = _drawing()

    class Folder:
        def path(self, name: str) -> Path:
            return tmp_path / name

    linked = inline_pictures.linked(drawn, "t")
    for keep in ([], ["big"], ["vectors", "box"]):
        made, carried = copied(Folder(), linked, keep), copied(Folder(), drawn, keep)
        assert made.svg() == carried.svg() and "/api/picture" not in made.svg()
        assert made.png() == carried.png()
    assert _uri("image/png", PNG) in copied(Folder(), linked, ["big"]).svg()
    assert _uri("image/svg+xml", SVG) in copied(Folder(), linked, ["vectors"]).svg()


def test_a_picture_not_carried_as_its_bytes_say_is_left_in_its_drawing() -> None:
    # (Base64 that is not as Python writes it would not be carried back as it was.)
    payload = base64.b64encode(PNG).decode("ascii")
    folded = f'<svg><image href="data:image/png;base64,{payload[:76]}\n{payload[76:]}"/></svg>'
    assert inline_pictures.linked(folded, "t") == folded
    odd = f'<svg><image href="data:image/png;charset=x;base64,{payload}"/></svg>'
    assert inline_pictures.linked(odd, "t") == odd
