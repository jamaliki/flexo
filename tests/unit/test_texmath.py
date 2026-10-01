"""Maths set in two dimensions: parsed from LaTeX, laid out by TeX's rules with the maths
font's measures, drawn as outlines, and said in words when it cannot be read."""

from __future__ import annotations

import random
import xml.etree.ElementTree as ET

import pytest

from flexo import Figure, compile_figure
from flexo.drawing import read_drawing
from flexo.markup import math_spans, needs_layout, parse_label
from flexo.style import TypographyStyle
from flexo.svg import SVG_NS
from flexo.texmath import draw, problems_in, typeset
from flexo.text import TextMeasurer

TYPE = TypographyStyle(family="Figtree")


def _set(source: str, *, display: bool = False, size: float = 20.0):
    return typeset(source, TYPE, size, display=display)


def test_a_fraction_stacks_over_a_rule_and_stands_taller_than_a_line_of_words() -> None:
    line = _set("x + y")
    fraction = _set(r"\frac{x}{y}")
    assert fraction.height > line.height and fraction.depth > line.depth
    rules = [item for _, _, item in fraction.box.items if type(item).__name__ == "RuleItem"]
    assert len(rules) == 1
    # Display style sets it larger than text style does, as TeX does.
    assert _set(r"\frac{x}{y}", display=True).height > fraction.height


def test_a_radical_has_its_bar_and_grows_with_what_it_holds() -> None:
    small = _set(r"\sqrt{x}")
    tall = _set(r"\sqrt{\frac{a}{b}}", display=True)
    assert any(type(item).__name__ == "RuleItem" for _, _, item in small.box.items)
    assert tall.height + tall.depth > (small.height + small.depth) * 1.5
    # A root's index sits in the crook of its sign, as TeX sets it.
    assert len(_set(r"\sqrt[3]{x}").box.items) > len(small.box.items)


def test_brackets_grow_to_hold_what_is_inside_them() -> None:
    plain = _set(r"\left( x \right)")
    grown = _set(r"\left( \frac{\frac{a}{b}}{c} \right)", display=True)
    assert grown.height + grown.depth > 2 * (plain.height + plain.depth)
    assert _set(r"\Bigg( x \Bigg)").height > _set(r"\big( x \big)").height


def test_a_sum_takes_its_limits_above_and_below_in_display_and_beside_it_in_words() -> None:
    display = _set(r"\sum_{i=1}^{n} i", display=True)
    words = _set(r"\sum_{i=1}^{n} i")
    assert display.height > words.height and display.width < words.width * 1.2
    # \limits and \nolimits say otherwise.
    assert _set(r"\sum\limits_{i=1}^{n} i").height > words.height


def test_matrices_cases_and_aligned_lines_are_laid_out_in_rows() -> None:
    one = _set("a")
    matrix = _set(r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}")
    assert matrix.height + matrix.depth > 2 * (one.height + one.depth)
    cases = _set(r"f(x) = \begin{cases} x & x \ge 0 \\ -x & x < 0 \end{cases}")
    assert cases.height + cases.depth > matrix.height
    # Lines broken with \\ and aligned at & need no environment in display.
    aligned = _set(r"a &= b \\ &= c", display=True)
    assert aligned.height + aligned.depth > 2 * (one.height + one.depth)
    assert not aligned.problems


@pytest.mark.parametrize(
    "source",
    [
        r"\mathcal{L}(\theta) = -\frac{1}{N}\sum_{i=1}^{N} \log p_\theta(y_i \mid x_i)",
        r"\mathrm{softmax}\left(\frac{QK^\top}{\sqrt{d_k}}\right)V",
        r"\int_0^\infty e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}",
        r"\binom{n}{k} = \frac{n!}{k!(n-k)!}",
        r"\overbrace{a + b}^{n} \underbrace{x}_{m} \overset{\text{def}}{=} \xrightarrow[low]{high}",
        r"\ce{2H2 + O2 -> 2H2O} \quad \SI{9.81}{\metre\per\second\squared}",
        r"\hat{x}\ \widehat{xyz}\ \overline{AB}\ \vec{v}\ \dot{x}\ \ddot{y}\ f'(x)\ g''",
        r"\mathbb{R}^n \setminus \{0\} \subseteq \mathbb{C}, \forall \epsilon > 0 \exists \delta",
        r"\color{red} x + \textcolor{accent}{y} \boxed{z} \phantom{w} \not="
        r" \operatorname*{arg\,max}_x",
        r"\begin{array}{c|c} a & b \\ \hline c & d \end{array}",
    ],
)
def test_what_people_write_in_talks_reads_without_complaint(source: str) -> None:
    formula = _set(source, display=True)
    assert formula.problems == ()
    assert formula.width > 0 and formula.height > 0


@pytest.mark.parametrize(
    ("source", "said"),
    [
        (r"\foo{x}", r"\foo is not a maths command flexo knows"),
        (r"\frac{1}{", "a { is not closed"),
        (r"\left( x", r"\left has no \right after it"),
        (r"x \right)", r"\right has no \left before it"),
        (r"\begin{pmatrix} a", r"\begin{pmatrix} has no \end{pmatrix}"),
        (
            r"\begin{wat} a \end{wat}",
            r"\begin{wat} is not an environment flexo knows: try pmatrix, cases or aligned",
        ),
        ("x^", "^ has nothing after it"),
        ("x^a^b", "a symbol has two superscripts: group them, as x^{a b}"),
        ("}", "a } closes no {"),
    ],
)
def test_what_cannot_be_read_is_said_in_words_and_the_rest_still_drawn(
    source: str, said: str
) -> None:
    assert said in problems_in(source)
    assert _set(source).width >= 0


def test_no_formula_however_broken_breaks_the_setter() -> None:
    pieces = [
        r"\frac",
        r"\sqrt",
        "{",
        "}",
        "^",
        "_",
        "&",
        r"\\",
        r"\left(",
        r"\right)",
        r"\begin{pmatrix}",
        r"\end{pmatrix}",
        "x",
        "2",
        r"\alpha",
        r"\sum",
        r"\middle|",
        r"\over",
        "'",
        r"\hat",
        r"\ce{",
        r"\text{",
        "[",
        "]",
        r"\color{red}",
        r"\overbrace",
        r"\not",
        r"\big",
        r"\mathbb",
        " ",
        r"\\\\",
    ]
    rng = random.Random(3)
    for _ in range(400):
        source = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 14)))
        formula = _set(source, display=rng.random() < 0.5)
        assert formula.width >= 0
        assert all(
            isinstance(problem, str) and "Error" not in problem for problem in formula.problems
        )


def test_deep_nesting_is_said_rather_than_crashing() -> None:
    source = r"\frac{" * 200 + "x" + "}{y}" * 200
    formula = _set(source)
    assert formula.problems


def test_a_formula_is_outlines_and_rules_that_every_writer_reads() -> None:
    root = ET.Element(f"{{{SVG_NS}}}svg", width="200", height="60", viewBox="0 0 200 60")
    group = draw(root, _set(r"\frac{a}{\sqrt{b}}"), 10.0, 40.0)
    assert group.get("data-flexo-math") == r"\frac{a}{\sqrt{b}}"
    tags = {child.tag.split("}")[1] for child in group}
    assert tags == {"path", "rect"}
    drawing = read_drawing(ET.tostring(root, encoding="unicode"))
    assert len(list(drawing.walk())) == len(group)


def test_simple_maths_stays_words_and_the_rest_is_laid_out() -> None:
    assert (
        not needs_layout("x_t^2")
        and not needs_layout(r"\alpha \cdot \beta")
        and not needs_layout(r"\vec{h}")
        and not needs_layout(r"\mathbb{R}")
    )
    for source in (
        r"\hat{x}",
        r"\overrightarrow{AB}",
        r"\mathfrak{g}",
        r"\boldsymbol{\theta}",
        r"\frac{a}{b}",
        r"\sqrt{x}",
        r"e^{-E_a/RT}",
        r"\sum_i x_i",
        r"\left( x \right)",
        r"\begin{cases} a \end{cases}",
        r"\mathrm{H_2O}",
        r"a \quad b",
        r"50\%",
    ):
        assert needs_layout(source), source
    (run,) = parse_label(r"$\frac{1}{2}$")
    assert run.math == r"\frac{1}{2}" and run.text == "1/2"


def test_dollars_read_as_pandoc_reads_them() -> None:
    assert math_spans("it costs $5 and $10") == []
    assert math_spans(r"a price of \$20 and $x$") == [(20, 23)]
    assert math_spans("$x$ and $y$") == [(0, 3), (8, 11)]
    assert math_spans(r"$ \alpha $") == [(0, 10)]
    assert math_spans(r"$$E = mc^2$$ and \(x\) and \[y\]") == [(0, 12), (17, 22), (27, 32)]
    assert math_spans("`echo $HOME $PATH` then $x$") == [(24, 27)]
    assert math_spans("between $5-$10") == []
    # Plainly TeX may be followed by a digit: a space group, P2₁2₁2₁.
    assert math_spans("P2$_1$2$_1$2$_1$") == [(2, 6), (7, 11), (12, 16)]


def test_matplotlibs_mathdefault_is_the_upright_face() -> None:
    from flexo.units import pt

    formula = typeset(r"\mathdefault{10^{-2}}", TypographyStyle(family="Figtree", size=pt(12)), 12)
    assert formula.problems == () and formula.width > 0


def test_display_maths_in_a_label_is_a_line_of_its_own() -> None:
    runs = parse_label(r"Loss: $$\frac{1}{N}\sum_i \ell_i$$ per batch")
    assert "".join(run.text for run in runs if not run.math) == "Loss: \n\nper batch"
    assert any(run.math.startswith(r"\displaystyle") for run in runs)
    metrics = TextMeasurer(TYPE).measure(runs)
    assert len(metrics.lines) == 3


def test_a_label_with_a_fraction_is_measured_and_drawn_with_it() -> None:
    with Figure("maths") as figure:
        figure.root.block(
            "attention", label=r"$\mathrm{softmax}\left(\frac{QK^\top}{\sqrt{d_k}}\right)V$"
        )
        figure.root.block("matrix", label=r"$\begin{pmatrix} a \\ b \\ c \end{pmatrix}$")
        figure.root.block("plain", label="softmax")
    compiled = compile_figure(figure.spec)
    root = ET.fromstring(compiled.document.text)
    label = next(item for item in root.iter() if item.get("id") == "attention.label")
    formulas = [item for item in label.iter() if item.get("data-flexo-math")]
    assert len(formulas) == 1
    boxes = {node.spec.id: node.intrinsic_size for node in compiled.measured.nodes}
    assert boxes["matrix"].height > boxes["plain"].height
    assert boxes["attention"].width > boxes["plain"].width


def test_maths_a_label_cannot_read_is_a_warning_on_its_part() -> None:
    from flexo.lint import lint_compilation

    with Figure("broken") as figure:
        figure.root.block("f", label=r"$\frac{1}{2} + \foo$")
        figure.root.block("g", label=r"$\frac{a}{b}$")
    warnings = [
        item
        for item in lint_compilation(compile_figure(figure.spec)).diagnostics
        if item.code == "label.math"
    ]
    assert [(item.entity_id, item.message) for item in warnings] == [
        (
            "f",
            "\\foo is not a maths command flexo knows, in the maths"
            " \u201c\\frac{1}{2} + \\foo\u201d.",
        ),
    ]


def test_a_formula_wider_than_its_line_breaks_after_a_sign_as_tex_breaks_it() -> None:
    from flexo.texmath import breakable

    assert breakable(r"a = b + \frac{c+d}{e} - \left(f + g\right)") == (
        "a ={}", " b +{}", r" \frac{c+d}{e} -{}", r" \left(f + g\right)",
    )
    assert breakable("-x = y^{a+b}") == ("-x ={}", " y^{a+b}")
    source = r"$\mathcal{L} = \mathcal{L}_{\mathrm{rec}} + \beta D_{\mathrm{KL}} + \lambda \|w\|^2$"
    whole = TextMeasurer(TYPE).measure(parse_label(source))
    half = whole.width / 2
    narrow = TextMeasurer(TYPE).measure(parse_label(source), max_width=half, balance=False)
    assert len(narrow.lines) >= 2 and max(line.width for line in narrow.lines) <= half + 1e-6
    # Set side by side, the pieces are as wide as the whole.
    pieces = sum(line.width for line in narrow.lines)
    assert pieces == pytest.approx(whole.width, abs=0.5)


def test_the_maths_font_suits_the_words_and_greek_is_its_own_everywhere() -> None:
    from flexo.texmath import Fonts, GlyphItem
    from flexo.text import font_stack, maths_family

    serif = TypographyStyle(family="Latin Modern Roman", generic="serif")
    assert maths_family(TYPE) == "Fira Math" and maths_family(serif) == "Latin Modern Math"
    assert maths_family(TypographyStyle(family="Figtree", math_family="Latin Modern Math")) == (
        "Latin Modern Math"
    )
    fonts = Fonts(TYPE)
    assert fonts.maths.face.family == "Fira Math" and fonts.spare.face.family == "Latin Modern Math"

    def families(source: str, typography: TypographyStyle = TYPE) -> set[str]:
        formula = typeset(source, typography, 20.0)
        items = formula.box.items
        return {item.face.face.family for _, _, item in items if isinstance(item, GlyphItem)}

    # Greek, signs and big operators in the maths font; letters the words' own.
    assert families(r"\theta") == {"Fira Math"}
    assert families(r"\sum_i x_i") == {"Fira Math", "Figtree"}
    # A text face's italic Greek is never used, even when it has Greek (IBM Plex Sans's
    # italic θ is drawn as ϑ).
    assert families(r"\theta", TypographyStyle(family="IBM Plex Sans")) == {"Fira Math"}
    # What the chosen maths font lacks comes from the spare: Fira Math has no script capitals.
    assert families(r"\mathcal{L}") == {"Latin Modern Math"}
    assert families(r"\theta", serif) == {"Latin Modern Math"}
    # Maths set as words takes its Greek from the same font.
    (theta,) = parse_label(r"$\theta$")
    assert theta.text == "\U0001d703"
    (face, _), *_ = font_stack(TYPE).segments(theta.text, 400, False)
    assert face.family == "Fira Math"


def test_code_is_set_in_the_bundled_monospace_on_every_machine() -> None:
    from flexo.text import font_stack

    (face, _), *_ = font_stack(TYPE).segments("def f(x):", 400, False, code=True)
    assert face.family == "IBM Plex Mono" and face.bundled


def test_escaped_braces_stay_inside_a_group() -> None:
    from flexo.units import pt

    typography = TypographyStyle(family="Figtree", size=pt(20))
    sources = (r"E_{t\sim\{1,T\}}", r"\sqrt{\{x\}}", r"\frac{\{a\}}{2}", r"{f \in \{\sin, \cos\}}")
    for source in sources:
        assert typeset(source, typography, 20).problems == (), source
    assert typeset(r"\frac{1}{2", typography, 20).problems == ("a { is not closed",)


def test_units_are_set_as_siunitx_sets_them() -> None:
    from flexo.texmath import Group, Scripts, Sym, _units

    def shown(items: list) -> str:
        parts = []
        for item in items:
            if isinstance(item, Group):
                parts.append("".join(symbol.char for symbol in item.items))
            elif isinstance(item, Scripts):
                base = "".join(symbol.char for symbol in item.base.items)
                parts.append(base + "^" + "".join(symbol.char for symbol in item.sup))
            elif isinstance(item, Sym):
                parts.append(item.char)
            else:
                parts.append(" ")
        return "".join(parts).replace("\u2212", "-")

    assert shown(_units(r"\per\mole")) == "mol^-1"
    assert shown(_units(r"\joule\per\mole\per\kelvin")) == "J mol^-1 K^-1"
    assert shown(_units(r"\metre\per\second\squared")) == "m s^-2"
    assert shown(_units(r"\square\metre")) == "m^2"
    assert shown(_units("m/s")) == "m/s"


def test_latex_colour_names_are_drawn_in_their_colours() -> None:
    from flexo.colour import named_colour
    from flexo.render_common import formula_paint
    from flexo.style import Palette

    assert named_colour("red") == "#ff0000" and named_colour("red!70!black") == "#b20000"
    assert named_colour("accent") is None
    palette = Palette("test", {"ink": "#222222", "tone-1-stroke": "#1a5d9b"})
    paint = formula_paint(palette)
    assert paint("blue") == ("#0000ff", None)
    assert paint("accent") == ("#1a5d9b", "tone-1-stroke")
    assert paint("not-a-colour") == (None, None)


def test_a_primes_subscript_sits_under_it_as_in_tex() -> None:
    from flexo.markup import needs_layout
    from flexo.texmath import GlyphItem
    from flexo.units import pt

    typography = TypographyStyle(family="Figtree", size=pt(20))

    def placed(source: str) -> list[tuple[float, float]]:
        formula = typeset(source, typography, 20)
        return [(x, y) for x, y, item in formula.box.items if isinstance(item, GlyphItem)]

    _, prime, two, _ = placed("q'_{2i}")
    assert two[0] < prime[0] + 1.0  # the subscript starts under the prime, not after it
    assert placed("q'_{2i}") == placed(r"q^{\prime}_{2i}")
    assert needs_layout("q'_{2i}") and not needs_layout("f'(x)")
