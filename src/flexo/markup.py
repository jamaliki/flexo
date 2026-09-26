# ruff: noqa: RUF001 -- Greek letters are the point of this table.
"""Math in labels: a small, TeX-shaped language between dollar signs.

A string label is plain text, except for what sits between a pair of ``$``:

- ``x_t`` and ``x_{t-1}`` are subscripts; ``x^2`` and ``Q K^{T}`` superscripts.
  A script is one character, or everything inside ``{...}``.
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
  bar over it.

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

from flexo.ir.semantic import TextRun

SYMBOLS = {
    # Greek, lower case
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
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
    "phi": "φ",
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
    "|": "‖",
    ",": " ",
    " ": " ",
    "$": "$",
    "{": "{",
    "}": "}",
    "_": "_",
    "^": "^",
}
"""Commands that stand for one symbol."""

ACCENTS = {"hat": "̂", "bar": "̄", "tilde": "̃", "dot": "̇", "vec": "⃗"}
"""Commands that put a combining accent on their argument."""

UPRIGHT = {"text", "mathrm", "operatorname"}

OPERATORS = frozenset(
    {"log", "exp", "max", "min", "sin", "cos", "tanh", "arg", "det", "lim", "sup", "inf"}
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
BINARY = frozenset("+−×·±∓∘⊙⊕⊗∗∪∩∧∨÷⋆")
"""Symbols TeX spaces as binary operators: ``a + b``, but ``-a`` for a sign."""
RELATIONS = frozenset("=<>≤≥≠≈≡∼≃∝∈∉⊂⊆⊃⊇→←↔⇒⇐⇔↦∣")
"""Symbols TeX spaces as relations: always ``a = b``."""
_OPENING = frozenset("([{⟨,;")
_UPRIGHT_GREEK = frozenset("ΓΔΘΛΞΠΣΥΦΨΩ")
_COMMAND = re.compile(r"\\([A-Za-z]+|.)")


def parse_label(text: str) -> tuple[TextRun, ...]:
    """The runs a string label stands for: plain text, with math between ``$``."""

    if not text:
        return ()
    if "$" not in text:
        return (TextRun(text),)
    runs: list[TextRun] = []
    plain: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\\" and text[index + 1 : index + 2] == "$":
            plain.append("$")
            index += 2
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


def has_markup(text: str) -> bool:
    """Whether ``parse_label(text)`` differs from the plain run ``TextRun(text)``."""

    return parse_label(text) != ((TextRun(text),) if text else ())


def _closing_dollar(text: str, start: int) -> int | None:
    index = start
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "$":
            return index
        index += 1
    return None


def _math(source: str) -> list[TextRun]:
    runs: list[TextRun] = []
    _read(source, runs, shift="normal", mode="math", weight=400)
    while runs and runs[-1].text == " ":
        runs.pop()
    return runs


def _operator(runs: list[TextRun], symbol: str, weight: int, shift: str) -> None:
    """Append a binary operator or relation, spaced the way TeX spaces it."""

    atoms = [run for run in runs if run.text != " "]
    previous = atoms[-1].text[-1:] if atoms else ""
    sign = symbol in BINARY and (not previous or previous in BINARY | RELATIONS | _OPENING)
    if sign:
        runs.append(TextRun(symbol, weight, False, shift))  # type: ignore[arg-type]
        return
    while runs and runs[-1].text == " ":
        runs.pop()
    spaced = shift == "normal" and bool(previous)
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
                runs.append(TextRun(name, weight, False, shift))  # type: ignore[arg-type]
                following = source[index : index + 1]
                if following.isalnum() or following == "\\":
                    # ``\log x``: a named function is set apart from its
                    # operand, but not from ``(`` or a script.
                    runs.append(TextRun(" ", weight, False, shift))  # type: ignore[arg-type]
                continue
            if name == "sqrt":
                runs.append(TextRun("√", weight, False, shift))  # type: ignore[arg-type]
                argument, index = _argument(source, index)
                _read(argument, runs, shift=shift, mode=mode, weight=weight)
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
            runs.append(TextRun(symbol, weight, italic, shift))  # type: ignore[arg-type]
            continue
        if character in "{}":
            index += 1
            continue
        index += 1
        if mode == "math":
            character = _REPLACEMENTS.get(character, character)
            if character in BINARY | RELATIONS:
                _operator(runs, character, weight, shift)
                index = _skip_spaces(source, index)
                continue
        italic = mode == "math" and character.isascii() and character.isalpha()
        runs.append(TextRun(character, weight, italic, shift))  # type: ignore[arg-type]


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
        if result and (
            result[-1].weight,
            result[-1].italic,
            result[-1].baseline_shift,
        ) == (run.weight, run.italic, run.baseline_shift):
            last = result[-1]
            result[-1] = TextRun(
                last.text + run.text, last.weight, last.italic, last.baseline_shift
            )
            continue
        result.append(run)
    return tuple(result)
