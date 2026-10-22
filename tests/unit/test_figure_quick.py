"""The figure editor kept quick (``studio/static/figure/parts.css``): no drag's class has every
element of the page styled again as it begins and ends."""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).parents[2] / "src/flexo/studio/static"

# The classes a drag, a size, a landing or a turn puts on the page or the body as it begins and
# takes off as it ends.
STATES = ("fig-grabbing", "fig-copying", "fig-dragging", "fig-landing", "fig-sizing", "fig-ending")


def test_no_drag_has_every_element_of_the_page_styled_again_as_it_begins_and_ends() -> None:
    sheet = (STATIC / "figure/parts.css").read_text(encoding="utf-8")
    sheet = re.sub(r"/\*.*?\*/", "", sheet, flags=re.S)
    universal = []
    for selectors in re.findall(r"([^{}]+)\{", sheet):
        for selector in selectors.split(","):
            words = selector.split()
            # A state's class before a universal selector (`.fig-dragging .x *`,
            # `body.fig-grabbing *`): every element under it, the slide's whole drawing, styled
            # again when it changes.
            for at, word in enumerate(words):
                if any(f".{state}" in word for state in STATES) and any(
                    after == "*" or after.startswith("*") for after in words[at + 1 :]
                ):
                    universal.append(selector.strip())
    assert universal == []
