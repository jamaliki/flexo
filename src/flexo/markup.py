# ruff: noqa: RUF001 -- Greek letters are the point of this table.
"""Math in labels: a small, TeX-shaped language between dollar signs.

A string label is plain text, except for what sits between a pair of ``$``:

- ``x_t`` and ``x_{t-1}`` are subscripts; ``x^2`` and ``Q K^{T}`` superscripts.
  A script is one character, or everything inside ``{...}``. A superscript and
  a subscript on one letter (``\\sigma^2_B``) are stacked, as in TeX.
- Latin letters are italic, as in TeX; digits, punctuation, and Greek capitals
  are upright. ``\\text{out}`` and ``\\mathrm{out}`` set words upright, and
  ``\\mathbf{x}`` sets them bold.
- ``\\alpha`` ... ``\\omega``, ``\\Gamma`` ... ``\\Omega``, and common operators
  and relations (``\\times``, ``\\cdot``, ``\\sim``, ``\\in``, ``\\nabla``,
  ``\\to``, ``\\sum``, ``\\le``, ...) become their symbols; ``-`` becomes a
  minus sign. ``\\log``, ``\\exp``, ``\\max`` and the other named functions are
  upright. ``\\mathcal{L}``, ``\\mathbb{E}`` and ``\\mathfrak{g}`` give script,
  blackboard, and fraktur capitals.
- ``\\hat{x}``, ``\\bar{x}``, ``\\tilde{x}`` and ``\\dot{x}`` put the accent on
  the character. ``\\sqrt{d}`` is a radical sign before its argument, with no
  bar over it, and ``\\frac{a}{b}`` is set inline as ``a/b`` (a sum or
  difference in parentheses: ``(a+b)/c``).

Spacing follows TeX. A binary operator (``+``, ``-``, ``\\times``, ``\\cdot``,
...) or a relation (``=``, ``<``, ``\\in``, ``\\sim``, ``\\to``, ...) gets one
space on each side, whatever was typed around it -- except in a sub- or
superscript, and except a sign that opens a formula or follows ``(``, ``,`` or
another operator, which get none. The space that ends a command name
(``\\alpha x``) is dropped, and a named function is set apart from an
operand that follows it (``\\log x``). Every other space is kept as typed.

``\\$`` is a literal dollar sign anywhere, and a lone
``$`` with no partner is literal too. Scripts do not nest: ``x_{a_b}`` sets
``a`` and ``b`` at the same subscript level.
"""

from __future__ import annotations

import re
from dataclasses import replace

from flexo.ir.semantic import TextRun

THIN = "\u202f"
"""Maths' thin space (``\\,``, and after a comma): narrow, and no place to break a line."""

SYMBOLS = {
    # Greek, lower case
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ϵ",  # as TeX sets it: \varepsilon is the curly ε
    "varepsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "iota": "ι",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "upsilon": "υ",
    "phi": "ϕ",  # as TeX sets it: \varphi is the open φ
    "varphi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    # Greek, upper case
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Upsilon": "Υ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
    # operators and relations
    "in": "∈",
    "notin": "∉",
    "subset": "⊂",
    "cup": "∪",
    "cap": "∩",
    "forall": "∀",
    "exists": "∃",
    "nabla": "∇",
    "top": "⊤",
    "perp": "⊥",
    "propto": "∝",
    "mid": "∣",
    "times": "×",
    "cdot": "·",
    "sim": "∼",
    "to": "→",
    "rightarrow": "→",
    "leftarrow": "←",
    "sum": "Σ",
    "prod": "Π",
    "le": "≤",
    "leq": "≤",
    "ge": "≥",
    "geq": "≥",
    "ne": "≠",
    "neq": "≠",
    "approx": "≈",
    "pm": "±",
    "infty": "∞",
    "partial": "∂",
    "ell": "ℓ",
    "prime": "′",
    "odot": "⊙",
    "oplus": "⊕",
    "otimes": "⊗",
    "circ": "∘",
    "ldots": "…",
    "dots": "…",
    "cdots": "⋯",
    "langle": "⟨",
    "rangle": "⟩",
    "ll": "≪",
    "gg": "≫",
    "simeq": "≃",
    "equiv": "≡",
    "cong": "≅",
    "int": "∫",
    "oint": "∮",
    "subseteq": "⊆",
    "supset": "⊃",
    "supseteq": "⊇",
    "emptyset": "∅",
    "varnothing": "∅",
    "Rightarrow": "⇒",
    "Leftarrow": "⇐",
    "Leftrightarrow": "⇔",
    "iff": "⟺",
    "implies": "⟹",
    "leftrightarrow": "↔",
    "mapsto": "↦",
    "uparrow": "↑",
    "downarrow": "↓",
    "mp": "∓",
    "div": "÷",
    "star": "⋆",
    "ast": "∗",
    "dagger": "†",
    "parallel": "∥",
    "Vert": "‖",
    "lVert": "‖",
    "rVert": "‖",
    "lvert": "|",
    "rvert": "|",
    "lfloor": "⌊",
    "rfloor": "⌋",
    "lceil": "⌈",
    "rceil": "⌉",
    "hbar": "ℏ",
    "Re": "ℜ",
    "Im": "ℑ",
    "aleph": "ℵ",
    "neg": "¬",
    "lnot": "¬",
    "land": "∧",
    "lor": "∨",
    "wedge": "∧",
    "vee": "∨",
    "setminus": "∖",
    "vartheta": "ϑ",
    "intercal": "⊺",
    "square": "□",
    "checkmark": "✓",
    "|": "‖",
    ",": THIN,
    " ": " ",
    "$": "$",
    "{": "{",
    "}": "}",
    "_": "_",
    "^": "^",
}
"""Commands that stand for one symbol."""

ACCENTS = {"hat": "̂", "bar": "̄", "tilde": "̃", "dot": "̇"}
"""Commands that put a combining accent on their argument."""

OVER = {"vec": "→", "overrightarrow": "→", "overleftarrow": "←"}
"""Commands that set a mark over their whole argument, drawn by Flexo itself."""

UPRIGHT = {"text", "mathrm", "mathdefault", "operatorname"}
CODE = {"texttt", "mathtt", "code"}
"""Commands whose argument is set as code, in the monospace family."""

OPERATORS = frozenset(
    {
        "log", "exp", "max", "min", "sin", "cos", "tan", "tanh", "arg", "det", "lim", "sup",
        "inf", "argmax", "argmin", "ln", "Pr", "tr", "diag", "softmax", "KL",
    }
)
"""Named functions TeX sets upright: ``\\log x``, ``\\max_i``."""

ALPHABETS = {
    "mathcal": (
        0x1D49C,
        {"B": "ℬ", "E": "ℰ", "F": "ℱ", "H": "ℋ", "I": "ℐ", "L": "ℒ", "M": "ℳ", "R": "ℛ"},
    ),
    "mathbb": (0x1D538, {"C": "ℂ", "H": "ℍ", "N": "ℕ", "P": "ℙ", "Q": "ℚ", "R": "ℝ", "Z": "ℤ"}),
    "mathfrak": (0x1D504, {"C": "ℭ", "H": "ℌ", "I": "ℑ", "R": "ℜ", "Z": "ℨ"}),
}
"""Capital-letter alphabets by their first Unicode code point, with the letters
Unicode placed early in its Letterlike Symbols block instead."""
BOLD = {"mathbf", "boldsymbol"}

_REPLACEMENTS = {"-": "−", "*": "∗", "'": "′"}
_MATH_ITALIC = {
    **{chr(0x03B1 + index): chr(0x1D6FC + index) for index in range(25)},
    **{
        chr(code): chr(0x1D716 + index)
        for index, code in enumerate((0x3F5, 0x3D1, 0x3F0, 0x3D5, 0x3F1, 0x3D6))
    },
}
"""Lower-case Greek and its mathematical italic letters (U+1D6FC on)."""
BINARY = frozenset("+−×·±∓∘⊙⊕⊗∗∪∩∧∨÷⋆∖")
"""Symbols TeX spaces as binary operators: ``a + b``, but ``-a`` for a sign."""
RELATIONS = frozenset("=<>≤≥≠≈≡∼≃≅∝∈∉⊂⊆⊃⊇→←↔⇒⇐⇔⟺⟹↦∣≪≫∥")
"""Symbols TeX spaces as relations: always ``a = b``."""
_OPENING = frozenset("([{⟨,;")
_UPRIGHT_GREEK = frozenset("ΓΔΘΛΞΠΣΥΦΨΩ")
_COMMAND = re.compile(r"\\([A-Za-z]+|.)")


_COLOURED = re.compile(r"\[([^\]\n]+)\]\{(#[0-9a-fA-F]{3,6}|[a-z][a-z0-9-]*)\}")
"""``[words]{accent}``: words in a colour -- a palette role, a friendly name, or a hex."""
_LINK = re.compile(r"\[([^\]\n]+)\]\(((?:https?|mailto|file):[^)\s]+)\)")
"""``[words](url)``: words that link somewhere."""


_CONTROLS = {code: None for code in range(32) if code != 10} | {9: " ", 127: None}


def parse_label(text: str) -> tuple[TextRun, ...]:
    """The runs a string label stands for: plain text, with math between ``$``
    and code between backticks (set in the monospace family). ``\\n`` typed in its words
    (not in its maths or code, where ``\\nu`` and ``\\n`` are their own) starts a new
    line, as Graphviz reads it."""

    # A tab in words is a space between them; other control characters (a stray \r)
    # draw nothing -- a font has no glyph for either. A new line after the last words
    # (as a block in YAML ends) is no line of its own.
    text = text.translate(_CONTROLS).rstrip("\n")
    while text.endswith("\\n") and not text.endswith("\\\\n"):
        text = text[:-2].rstrip("\n")
    if not text:
        return ()
    if (
        "$" not in text and "`" not in text and "](" not in text and "]{" not in text
        and "\\(" not in text and "\\[" not in text
    ):
        return (TextRun(text.replace("\\n", "\n")),)
    runs: list[TextRun] = []
    plain: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\\" and text[index + 1 : index + 2] == "$":
            plain.append("$")
            index += 2
            continue
        if character == "\\" and text[index + 1 : index + 2] == "`":
            plain.append("`")
            index += 2
            continue
        if character == "\\" and text[index + 1 : index + 2] == "n":
            plain.append("\n")
            index += 2
            continue
        if character == "[" and (coloured := _COLOURED.match(text, index)):
            if plain:
                runs.append(TextRun("".join(plain)))
                plain = []
            colour = coloured.group(2)
            runs.extend(replace(run, color=colour) for run in parse_label(coloured.group(1)))
            index = coloured.end()
            continue
        if character == "[" and (link := _LINK.match(text, index)):
            if plain:
                runs.append(TextRun("".join(plain)))
                plain = []
            runs.extend(replace(run, link=link.group(2)) for run in parse_label(link.group(1)))
            index = link.end()
            continue
        if character == "`":
            end = text.find("`", index + 1)
            if end > index:
                if plain:
                    runs.append(TextRun("".join(plain)))
                    plain = []
                runs.append(TextRun(text[index + 1 : end], code=True))
                index = end + 1
                continue
        display = text.startswith("$$", index) or text.startswith("\\[", index)
        if display:
            closing = "$$" if character == "$" else "\\]"
            end = text.find(closing, index + 2)
            if end > index + 2:
                if plain:
                    runs.append(TextRun("".join(plain)))
                    plain = []
                # A formula on its own line, in display style.
                if runs:
                    runs.append(TextRun("\n"))
                runs.extend(_math(text[index + 2 : end], display=True))
                index = end + 2
                if index < len(text):
                    runs.append(TextRun("\n"))
                    while index < len(text) and text[index] == " ":
                        index += 1
                continue
        if character == "\\" and text.startswith("\\(", index):
            end = text.find("\\)", index + 2)
            if end > index + 2:
                if plain:
                    runs.append(TextRun("".join(plain)))
                    plain = []
                runs.extend(_math(text[index + 2 : end]))
                index = end + 2
                continue
        if character == "$":
            end = _closing_dollar(text, index + 1)
            if end is not None:
                if plain:
                    runs.append(TextRun("".join(plain)))
                    plain = []
                runs.extend(_math(text[index + 1 : end]))
                index = end + 1
                continue
        plain.append(character)
        index += 1
    if plain:
        runs.append(TextRun("".join(plain)))
    return _merged(runs)


def math_spans(text: str) -> list[tuple[int, int]]:
    """Where maths is in ``text``, delimiters and all, as ``parse_label`` reads it:
    ``$...$``, ``\\(...\\)``, ``$$...$$`` and ``\\[...\\]``; not an escaped ``\\$``, not
    a price (``$5``), not inside backticks."""

    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\\" and text[index + 1 : index + 2] in {"$", "`"}:
            index += 2
            continue
        if character == "`":
            end = text.find("`", index + 1)
            if end > index:
                index = end + 1
                continue
        if text.startswith("$$", index) or text.startswith("\\[", index):
            end = text.find("$$" if character == "$" else "\\]", index + 2)
            if end > index + 2:
                spans.append((index, end + 2))
                index = end + 2
                continue
        if text.startswith("\\(", index):
            end = text.find("\\)", index + 2)
            if end > index + 2:
                spans.append((index, end + 2))
                index = end + 2
                continue
        if character == "$":
            end = _closing_dollar(text, index + 1)
            if end is not None:
                spans.append((index, end + 1))
                index = end + 1
                continue
        index += 1
    return spans


def has_markup(text: str) -> bool:
    """Whether ``parse_label(text)`` differs from the plain run ``TextRun(text)``."""

    return parse_label(text) != ((TextRun(text),) if text else ())


def _closing_dollar(text: str, start: int) -> int | None:
    """Where the ``$`` that closes maths opened just before ``start`` is, if any.

    As pandoc reads dollars: maths starts with no space after its ``$`` and ends
    with none before its ``$``, and that ``$`` is not followed by a digit -- so
    "it costs $5 and $10" and "$5-$10" are prices, not maths. Maths that is plainly
    TeX (a command, a script, a brace) may have spaces inside (``$ \\alpha $``) and a
    digit after it: ``P2$_1$2$_1$2$_1$``, a space group.
    """

    index = start
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "$":
            inside = text[start:index]
            if not inside:
                return None
            plainly_tex = any(ch in inside.replace("\\$", "") for ch in "\\^_{")
            if text[index + 1 : index + 2].isdigit() and not plainly_tex:
                return None
            if (inside[0].isspace() or inside[-1].isspace()) and not plainly_tex:
                return None
            return index
        index += 1
    return None


def _math(source: str, *, display: bool = False) -> list[TextRun]:
    source = source.strip()
    runs: list[TextRun] = []
    _read(source, runs, shift="normal", mode="math", weight=400)
    while runs and runs[-1].text == " ":
        runs.pop()
    if display or needs_layout(source):
        # Set in two dimensions (flexo.texmath); the words are what it reads as.
        words = "".join(run.text for run in runs).replace("\\", "").replace("\n", " ").strip()
        prefix = "\\displaystyle " if display else ""
        return [TextRun(words or source.strip(), math=prefix + source.strip())]
    return [replace(run, maths=True) for run in runs]


_LINEAR = frozenset({
    *(name for name, symbol in SYMBOLS.items() if symbol.isalpha() and name.isalpha()),
    "times", "cdot", "pm", "mp", "le", "leq", "ge", "geq", "ne", "neq", "approx", "sim",
    "simeq", "equiv", "propto", "in", "notin", "to", "rightarrow", "leftarrow", "infty",
    "partial", "nabla", "ell", "prime", "circ", ",", "{", "}", "$", "_",
    *ACCENTS, *OVER, *UPRIGHT, *CODE, *ALPHABETS, *OPERATORS, *BOLD,
}) - {"sum", "prod", "int", "oint"}
"""Commands maths set as a line of words shows as well as a laid-out formula would:
letters, the everyday signs, words and alphabets. Everything else is laid out."""


def needs_layout(source: str) -> bool:
    """Whether maths needs setting in two dimensions (``flexo.texmath``): a fraction,
    a radical, a matrix, a big operator, brackets that grow, scripts on scripts, or a
    command the words cannot show -- rather than as a line of styled words."""

    if "&" in source:
        return True
    if not _paired(source):
        # A brace not closed (x^{2), or closing none: TeX's reader says so, in words.
        return True
    names = _COMMAND.findall(source)
    if any(name not in _LINEAR for name in names):
        return True
    # An accent set as a combining mark collides with a Greek letter, or takes the letter
    # into another face; bold Greek is no face's: TeX places and draws them. An arrow
    # Flexo draws over one letter (\\vec{h}); over more, TeX's stretches across them.
    if any(name in ACCENTS or name == "boldsymbol" for name in names):
        return True
    # A prime with a subscript (q'_{2i}): the subscript goes under the prime, not after it.
    if re.search(r"(?:'|\\prime\}?)\s*_", source):
        return True
    for match in re.finditer(r"\\(?:" + "|".join(OVER) + r")\s*(?:\{([^{}]*)\}|(\S))", source):
        if len((match.group(1) or match.group(2) or "").strip()) > 1:
            return True
    # A blackboard, fraktur or script alphabet as words has its capitals only.
    for match in re.finditer(r"\\(?:mathbb|mathfrak|mathcal)\s*(?:\{([^{}]*)\}|(\S))", source):
        if not re.fullmatch(r"[A-Z]+", (match.group(1) or match.group(2) or "").strip()):
            return True
    # Words set upright (\mathrm{H_2O}) are read as words: their scripts need laying out.
    words = "|".join(sorted(UPRIGHT | CODE | BOLD))
    for match in re.finditer(r"\\(?:" + words + r")\s*\{([^{}]*)", source):
        if "_" in match.group(1) or "^" in match.group(1):
            return True
    # Scripts inside scripts (e^{-E_a/RT}): words have one level of each.
    for match in re.finditer(r"[_^]\{", source):
        depth, index = 0, match.end() - 1
        while index < len(source):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    break
            elif source[index] in "_^" and source[index - 1] != "\\":
                return True
            index += 1
    return False


def _paired(source: str) -> bool:
    """Whether every ``{`` in ``source`` is closed by a ``}``, escaped ones (``\\{``) aside."""

    depth, index = 0, 0
    while index < len(source):
        if source[index] == "\\":
            index += 2
            continue
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth < 0:
                return False
        index += 1
    return depth == 0


def _operator(runs: list[TextRun], symbol: str, weight: int, shift: str) -> None:
    """Append a binary operator or relation, spaced the way TeX spaces it."""

    atoms = [run for run in runs if run.text.strip()]
    previous = atoms[-1].text.strip()[-1:] if atoms else ""
    # After a sign, a relation, an opening or a comma, + and - are signs: (-1), a, -b.
    sign = symbol in BINARY and (not previous or previous in BINARY | RELATIONS | _OPENING | {","})
    if sign:
        runs.append(TextRun(symbol, weight, False, shift))  # type: ignore[arg-type]
        return
    while runs and runs[-1].text == " ":
        runs.pop()
    spaced = shift == "normal" and bool(previous)
    if spaced and atoms and atoms[-1].italic and atoms[-1].baseline_shift == "normal":
        # An italic letter leans into the space before a sign (f + g): its correction.
        runs.append(TextRun("\u200a", weight, False, shift))  # type: ignore[arg-type]
    if spaced:
        runs.append(TextRun(" ", weight, False, shift))  # type: ignore[arg-type]
    runs.append(TextRun(symbol, weight, False, shift))  # type: ignore[arg-type]
    if spaced:
        runs.append(TextRun(" ", weight, False, shift))  # type: ignore[arg-type]


def _skip_spaces(source: str, index: int) -> int:
    while index < len(source) and source[index] == " ":
        index += 1
    return index


def _read(source: str, runs: list[TextRun], *, shift: str, mode: str, weight: int) -> None:
    """Append the runs of ``source`` to ``runs`` at baseline ``shift``."""

    index = 0
    while index < len(source):
        character = source[index]
        if character in "_^" and mode == "math":
            argument, index = _argument(source, index + 1)
            if character == "^" and argument.strip() in {"\\circ", "\\degree"}:
                # ``^\circ`` is a degree: the degree sign, which stands high of itself, not a
                # ring operator made small.
                runs.append(TextRun("°", weight, False, shift))  # type: ignore[arg-type]
                continue
            script = "sub" if character == "_" else "super"
            _read(argument, runs, shift=script, mode=mode, weight=weight)
            continue
        if character == "\\":
            match = _COMMAND.match(source, index)
            name = match.group(1) if match else ""
            index = match.end() if match else index + 1
            if name.isalpha():
                index = _skip_spaces(source, index)  # the space ends the name
            if name in ACCENTS:
                argument, index = _argument(source, index)
                accented: list[TextRun] = []
                _read(argument, accented, shift=shift, mode=mode, weight=weight)
                if accented:
                    last = accented[-1]
                    accented[-1] = TextRun(
                        last.text + ACCENTS[name], last.weight, last.italic, last.baseline_shift
                    )  # type: ignore[arg-type]
                runs.extend(accented)
                continue
            if name in OVER:
                argument, index = _argument(source, index)
                marked: list[TextRun] = []
                _read(argument, marked, shift=shift, mode=mode, weight=weight)
                if marked:
                    text = "".join(run.text for run in marked)
                    first = marked[0]
                    runs.append(
                        TextRun(text, first.weight, first.italic, first.baseline_shift, OVER[name])  # type: ignore[arg-type]
                    )
                continue
            if name in ALPHABETS:
                argument, index = _argument(source, index)
                start, exceptions = ALPHABETS[name]
                letters = "".join(
                    exceptions.get(letter)
                    or (chr(start + ord(letter) - ord("A")) if "A" <= letter <= "Z" else letter)
                    for letter in argument
                )
                runs.append(TextRun(letters, weight, False, shift))  # type: ignore[arg-type]
                continue
            if name in OPERATORS:
                shown = {"argmax": "arg max", "argmin": "arg min"}.get(name, name)
                atoms = [run for run in runs if run.text.strip()]
                previous = atoms[-1].text.strip()[-1:] if atoms else ""
                if (
                    previous
                    and previous not in BINARY | RELATIONS | _OPENING
                    and not runs[-1].text.isspace()
                ):
                    # ``RT \ln K``: a named function is set apart from what comes before
                    # it too, as TeX sets an operator after an ordinary or a closing atom.
                    runs.append(TextRun(" ", weight, False, shift))  # type: ignore[arg-type]
                runs.append(TextRun(shown, weight, False, shift))  # type: ignore[arg-type]
                following = source[index : index + 1]
                if following.isalnum() or following == "\\":
                    # ``\log x``: a named function is set apart from its
                    # operand, but not from ``(`` or a script.
                    runs.append(TextRun(" ", weight, False, shift))  # type: ignore[arg-type]
                continue
            if name in {"frac", "tfrac", "dfrac"}:
                # Set inline, as a solidus: ``\frac{n_k}{n}`` is ``n_k/n``.
                # A numerator or denominator of more than one atom keeps its
                # grouping in parentheses.
                numerator, index = _argument(source, index)
                denominator, index = _argument(source, index)
                for part, last in ((numerator, False), (denominator, True)):
                    grouped = _compound(part)
                    if grouped:
                        runs.append(TextRun("(", weight, False, shift))  # type: ignore[arg-type]
                    _read(part, runs, shift=shift, mode=mode, weight=weight)
                    if grouped:
                        runs.append(TextRun(")", weight, False, shift))  # type: ignore[arg-type]
                    if not last:
                        runs.append(TextRun("/", weight, False, shift))  # type: ignore[arg-type]
                continue
            if name == "sqrt":
                runs.append(TextRun("√", weight, False, shift))  # type: ignore[arg-type]
                argument, index = _argument(source, index)
                _read(argument, runs, shift=shift, mode=mode, weight=weight)
                continue
            if name in CODE:
                argument, index = _argument(source, index)
                start = len(runs)
                _read(argument, runs, shift=shift, mode="text", weight=weight)
                runs[start:] = [replace(run, code=True, italic=False) for run in runs[start:]]
                continue
            if name in UPRIGHT or name in BOLD:
                argument, index = _argument(source, index)
                _read(
                    argument,
                    runs,
                    shift=shift,
                    mode="text",
                    weight=700 if name in BOLD else weight,
                )
                continue
            symbol = SYMBOLS.get(name, "\\" + name)
            if mode == "math" and symbol in BINARY | RELATIONS:
                _operator(runs, symbol, weight, shift)
                index = _skip_spaces(source, index)
                continue
            italic = (
                mode == "math"
                and name in SYMBOLS
                and symbol.isalpha()
                and (
                    symbol not in _UPRIGHT_GREEK
                    and name[:1].islower()
                    and len(symbol) == 1
                    and name not in {"sum", "prod", "partial", "infty"}
                )
            )
            if italic and symbol in _MATH_ITALIC:
                # TeX's italic Greek is the maths font's own letter, the one formulas
                # are set in: a text face's italic θ may be drawn as ϑ.
                symbol, italic = _MATH_ITALIC[symbol], False
            runs.append(TextRun(symbol, weight, italic, shift))  # type: ignore[arg-type]
            continue
        if character in "{}":
            index += 1
            continue
        index += 1
        if mode == "math":
            spaced_bar = source[index - 2 : index - 1] == " " and source[index : index + 1] == " "
            if character == "|" and spaced_bar:
                # A bar typed with room each side is a "given" (\\mid), spaced as a relation.
                _operator(runs, "|", weight, shift)
                index = _skip_spaces(source, index)
                continue
            if character.isspace():
                continue  # TeX spaces maths itself; what is typed between is not a space
            character = _REPLACEMENTS.get(character, character)
            if character in BINARY | RELATIONS:
                _operator(runs, character, weight, shift)
                index = _skip_spaces(source, index)
                continue
            if character == "," and source[index:].strip():
                # A comma in maths is followed by a thin space, as TeX sets it: (r, t).
                runs.append(TextRun(",", weight, False, shift))  # type: ignore[arg-type]
                runs.append(TextRun(THIN, weight, False, shift))  # type: ignore[arg-type]
                index = _skip_spaces(source, index)
                continue
        italic = mode == "math" and character.isascii() and character.isalpha()
        runs.append(TextRun(character, weight, italic, shift))  # type: ignore[arg-type]


def _compound(part: str) -> bool:
    """Whether ``part`` holds an operator at its own level: ``a+b``, not ``a_{i+1}``."""

    depth = 0
    for position, character in enumerate(part):
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
        elif depth == 0 and position > 0 and character in "+-" and part[position - 1] not in "_^":
            return True
    return False


def _argument(source: str, index: int) -> tuple[str, int]:
    """The script or command argument at ``index``: one unit, or a braced group."""

    if index >= len(source):
        return "", index
    if source[index] == "{":
        depth = 0
        for end in range(index, len(source)):
            if source[end] == "{":
                depth += 1
            elif source[end] == "}":
                depth -= 1
                if depth == 0:
                    return source[index + 1 : end], end + 1
        return source[index + 1 :], len(source)
    if source[index] == "\\":
        match = _COMMAND.match(source, index)
        if match:
            return match.group(0), match.end()
    return source[index], index + 1


def _merged(runs: list[TextRun]) -> tuple[TextRun, ...]:
    """Neighbouring runs that look alike, joined into one."""

    result: list[TextRun] = []
    for run in runs:
        if not run.text:
            continue
        if result and not run.accent and not result[-1].accent and not run.math \
                and not result[-1].math and (
            result[-1].weight,
            result[-1].italic,
            result[-1].baseline_shift,
            result[-1].code,
            result[-1].link,
            result[-1].color,
            result[-1].maths,
        ) == (run.weight, run.italic, run.baseline_shift, run.code, run.link, run.color, run.maths):
            result[-1] = replace(result[-1], text=result[-1].text + run.text)
            continue
        result.append(run)
    return tuple(result)
