"""Colours matched (``studio/static/studio/colourmatch.js``): the colours a page draws, counted
for the colour picker's "On This Slide" and "In This Figure", the most used first; a colour
sampled from the screen put back to a colour the document has -- by the theme's name where the
control takes it -- when a screen's rounding is all that parts them, and left as sampled
otherwise; and a colour's hue, saturation and brightness, for the picker's plane. Run in Node,
a drawing stood in for."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from flexo import freeform

STATIC = Path(freeform.__file__).parent / "studio" / "static" / "studio"
SCRIPT = STATIC / "colourmatch.js"


def run(body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = (
        f"const M = await import({json.dumps(SCRIPT.as_uri())});\n"
        f"console.log(JSON.stringify(await (async () => {{ {body} }})()));\n"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_a_colour_goes_to_its_hue_saturation_and_brightness_and_back_to_the_step() -> None:
    made = run("""
      const wrong = [];
      for (let r = 0; r < 256; r += 15) {
        for (let g = 0; g < 256; g += 17) {
          for (let b = 0; b < 256; b += 5) {
            const hex = M.hexOfRgb([r, g, b]);
            if (M.hexOfHsv(M.hsvOf(hex)) !== hex) wrong.push(hex);
          }
        }
      }
      return { wrong, red: M.hsvOf("#ff0000"), grey: M.hsvOf("#808080"), black: M.hsvOf("#000000"),
        teal: M.hexOfHsv({ h: 180, s: 1, v: 0.5 }), round: M.hexOfHsv({ h: 360, s: 1, v: 1 }),
        none: M.hsvOf("accent") };
    """)
    assert made["wrong"] == []
    assert made["red"] == {"h": 0, "s": 1, "v": 1}
    assert made["grey"]["s"] == 0 and made["black"] == {"h": 0, "s": 0, "v": 0}
    assert (made["teal"], made["round"], made["none"]) == ("#008080", "#ff0000", None)


def test_the_colours_drawn_are_counted_the_most_used_first() -> None:
    made = run("""
      const paints = ["#1F77B4", "none", "#d62728", "#1f77b4", "url(#gradient)", "white",
        "currentColor", "rgb(214, 39, 40)", "#17b", "#1f77b4", "transparent", "#ffffff80",
        "#00000000", "context-stroke"];
      return {
        all: M.countPaints(paints),
        // The page's paper and its words' ink left out, as the picker leaves them.
        skipped: M.countPaints(paints, { skip: ["#ffffff", "#000"] }),
        two: M.countPaints(paints, { limit: 2 }),
        tie: M.countPaints(["#aaaaaa", "#bbbbbb", "#bbbbbb", "#aaaaaa", "#cccccc"]),
      };
    """)
    assert made == {
        "all": ["#1f77b4", "#d62728", "#ffffff", "#1177bb"],
        "skipped": ["#1f77b4", "#d62728", "#1177bb"],
        "two": ["#1f77b4", "#d62728"],
        "tie": ["#aaaaaa", "#bbbbbb", "#cccccc"],
    }


def test_the_paints_of_a_drawing_are_read_from_its_attributes_and_styles() -> None:
    made = run("""
      const node = (attributes) => ({ getAttribute: (name) => attributes[name] ?? null });
      let asked = null;
      const root = { querySelectorAll: (selector) => { asked = selector; return [
        node({ fill: "#1f77b4", stroke: "#d62728" }),
        node({ style: "fill: #2ca02c; stroke-width: 2; stroke:#9467bd" }),
        node({ "stop-color": "#8c564b" }),
        node({ fill: "none", style: "opacity: 0.5" }),
      ]; } };
      return { paints: M.paintsIn(root), used: M.usedColours(root), none: M.paintsIn(null), asked };
    """)
    assert made["paints"] == ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#8c564b", "none"]
    assert made["used"] == ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#8c564b"]
    assert made["none"] == []
    # (Only what is painted is looked at: a slide's thousands of nodes, not all of them.)
    assert "[fill]" in made["asked"] and "[stroke]" in made["asked"]


def test_a_colour_sampled_a_screens_rounding_off_one_the_document_has_is_that_one() -> None:
    made = run("""
      const offered = [{ value: "accent", colour: "#1a5d9b" },
        { value: "accent2-fill", colour: "#FEE4CE" }, { value: null, colour: null }];
      const candidates = M.candidatesFor({ offered, used: ["#7b3fa0", "#1a5d9b", "#d95f02"],
        theme: ["#246c2d", "#1a5d9b"], recent: ["#2ca02c", "#7b3fa0"] });
      const match = (hex) => M.matchSample(hex, candidates);
      return {
        candidates,
        // A theme's colour, a step off on a P3 screen: by its name.
        accent: match("#1b5c9a"), tint: match("#fde5cf"),
        // A colour the slide draws, or one applied last: its very code.
        purple: match("#7c40a1"), orange: match("#d95f02"), green: match("#2ba12d"),
        // One of the theme's the slide does not draw (a swatch of the inspector's): its code.
        theme: match("#256b2e"),
        // Further off than a screen rounds: as sampled.
        apart: match("#7b3fa5"), micrograph: match("#2ecc71"),
        nothing: match("none"),
        nearest: M.snapped("#101010", [{ value: "a", hex: "#121212" },
          { value: "b", hex: "#111111" }]),
        first: M.snapped("#101010", [{ value: "a", hex: "#111111" },
          { value: "b", hex: "#0f0f0f" }]),
      };
    """)
    assert made["candidates"] == [
        {"value": "accent", "hex": "#1a5d9b"},
        {"value": "accent2-fill", "hex": "#fee4ce"},
        {"value": "#7b3fa0", "hex": "#7b3fa0"},
        {"value": "#1a5d9b", "hex": "#1a5d9b"},
        {"value": "#d95f02", "hex": "#d95f02"},
        {"value": "#246c2d", "hex": "#246c2d"},
        {"value": "#2ca02c", "hex": "#2ca02c"},
    ]
    assert made["accent"] == {"value": "accent", "hex": "#1a5d9b", "matched": True}
    assert made["tint"] == {"value": "accent2-fill", "hex": "#fee4ce", "matched": True}
    assert made["purple"] == {"value": "#7b3fa0", "hex": "#7b3fa0", "matched": True}
    assert made["orange"]["value"] == "#d95f02" and made["green"]["value"] == "#2ca02c"
    assert made["theme"] == {"value": "#246c2d", "hex": "#246c2d", "matched": True}
    assert made["apart"] == {"value": "#7b3fa5", "hex": "#7b3fa5", "matched": False}
    assert made["micrograph"] == {"value": "#2ecc71", "hex": "#2ecc71", "matched": False}
    assert made["nothing"] is None
    assert made["nearest"]["value"] == "b" and made["first"]["value"] == "a"


def test_a_colour_drawn_in_a_theme_colour_is_given_by_its_name_where_the_control_has_it() -> None:
    made = run("""
      const fills = [{ value: "accent-fill", colour: "#dbebfd" },
        { value: "accent", colour: "#1a5d9b" }, { value: "#1a5d9b", colour: "#1a5d9b" }];
      const tones = [{ value: "1", colour: "#1a5d9b" }, { value: "neutral", colour: "#76707d" }];
      return [M.valueFor("#1A5D9B", fills), M.valueFor("#dbebfd", fills),
        M.valueFor("#1a5d9c", fills), M.valueFor("#1a5d9b", tones), M.valueFor("#1a5d9b", []),
        M.valueFor("none", fills)];
    """)
    assert made == ["accent", "accent-fill", "#1a5d9c", "1", "#1a5d9b", None]
