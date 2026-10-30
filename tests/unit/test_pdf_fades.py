"""A PDF's pages faded to as a reader presents them full screen (``write_pdf``'s ``fades``): a
slide that morphs into the next, where a PDF can do no more than fade."""

from __future__ import annotations

import re

from flexo.pdf import pdf_bytes

PAGE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50" viewBox="0 0 100 50">'
    '<rect x="10" y="10" width="30" height="20" fill="#336699"/></svg>'
)


def test_a_page_given_a_fade_is_faded_to_and_the_rest_cut_to() -> None:
    data = pdf_bytes([PAGE, PAGE, PAGE], fades=[None, 1.5])
    found = re.findall(rb"/Type /Page /Parent[^\n]*", data)
    assert len(found) == 3
    assert b"/Trans" not in found[0] and b"/Trans" not in found[2]
    assert b"/Trans << /Type /Trans /S /Fade /D 1.5 >>" in found[1]
    # None given, none faded.
    assert b"/Trans" not in pdf_bytes([PAGE, PAGE])
