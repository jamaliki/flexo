# ruff: noqa: RUF001, RUF002 -- Greek letters and maths symbols are the point here.
"""Maths set in two dimensions, the way TeX sets it.

``flexo.markup`` sets simple maths (``$x_t$``, ``$\\alpha \\cdot \\beta$``) as styled
runs of text. Maths that is not a line of text -- a fraction, a radical, a matrix, a
sum with its limits above and below, brackets that grow with what they hold -- is set
here: parsed from LaTeX, laid out box by box by the rules of TeX's Appendix G, with
every measure taken from an OpenType MATH font (Latin Modern Math, bundled), and drawn
as outlines. Letters and digits are the typography's own, as in a Beamer talk, so a
formula reads as part of the words around it; operators, delimiters, radicals and big
operators come from the maths font, which knows how to make them larger.

``typeset(source, typography, size)`` lays a formula out once (it is cached) and says
what it could not read; ``draw`` puts it in an SVG. A formula is paths and rules only,
so every writer (PDF, PNG, PowerPoint) draws it as it is drawn here.
"""

from __future__ import annotations

import itertools
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

import uharfbuzz as hb

from flexo.fonts import FontFace, family_faces, hb_font, load_face, select_face
from flexo.style import TypographyStyle
from flexo.svg import element, number

# -- what the symbols are ---------------------------------------------------------------

ORD, OP, BIN, REL, OPEN, CLOSE, PUNCT, INNER = range(8)

# fmt: off
GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ϵ", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "varkappa": "ϰ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "omicron": "ο", "pi": "π",
    "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ", "sigma": "σ", "varsigma": "ς", "tau": "τ",
    "upsilon": "υ", "phi": "ϕ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "digamma": "ϝ", "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "varGamma": "𝛤", "varDelta": "𝛥", "varTheta": "𝛩", "varLambda": "𝛬", "varXi": "𝛯",
    "varPi": "𝛱", "varSigma": "𝛴", "varUpsilon": "𝛶", "varPhi": "𝛷", "varPsi": "𝛹",
    "varOmega": "𝛺",
}
# fmt: on

# fmt: off
ORDINARY = {
    "infty": "∞", "partial": "∂", "nabla": "∇", "emptyset": "∅", "varnothing": "∅", "ell": "ℓ",
    "hbar": "ℏ", "hslash": "ℏ", "aleph": "ℵ", "beth": "ℶ", "gimel": "ℷ", "Re": "ℜ", "Im": "ℑ",
    "wp": "℘", "forall": "∀", "exists": "∃", "nexists": "∄", "neg": "¬", "lnot": "¬",
    "top": "⊤", "bot": "⊥", "angle": "∠", "measuredangle": "∡", "triangle": "△", "square": "□",
    "Box": "□", "blacksquare": "■", "Diamond": "◇", "diamond": "⋄", "clubsuit": "♣",
    "diamondsuit": "♢", "heartsuit": "♡", "spadesuit": "♠", "flat": "♭", "natural": "♮",
    "sharp": "♯", "prime": "′", "backprime": "‵", "checkmark": "✓", "dagger": "†",
    "ddagger": "‡", "S": "§", "P": "¶", "copyright": "©", "circledR": "®", "degree": "°",
    "imath": "ı", "jmath": "ȷ", "mho": "℧", "eth": "ð", "complement": "∁", "Finv": "Ⅎ",
    "Game": "⅁", "surd": "√", "infin": "∞", "vdots": "⋮", "ddots": "⋱", "iddots": "⋰",
    "ldots": "…", "dots": "…", "dotsc": "…", "dotso": "…", "cdots": "⋯", "dotsb": "⋯",
    "dotsm": "⋯", "dotsi": "⋯", "%": "%", "#": "#", "&": "&", "$": "$", "_": "_",
    "textbackslash": "\\", "backslash": "∖", "|": "‖", "Vert": "‖", "vert": "|", "lbrace": "{",
    "rbrace": "}", "{": "{", "}": "}", "colon": ":", "euro": "€", "pounds": "£", "yen": "¥",
    "textdegree": "°", "blacktriangle": "▲", "bigstar": "★", "smallsetminus": "∖",
    "therefore": "∴", "because": "∵", "lozenge": "◊",
}
# fmt: on

# fmt: off
BINARY = {
    "pm": "±", "mp": "∓", "times": "×", "div": "÷", "cdot": "⋅", "ast": "∗", "star": "⋆",
    "circ": "∘", "bullet": "∙", "oplus": "⊕", "ominus": "⊖", "otimes": "⊗", "oslash": "⊘",
    "odot": "⊙", "cup": "∪", "cap": "∩", "sqcup": "⊔", "sqcap": "⊓", "uplus": "⊎", "wedge": "∧",
    "land": "∧", "vee": "∨", "lor": "∨", "setminus": "∖", "wr": "≀", "amalg": "⨿",
    "triangleleft": "◁", "triangleright": "▷", "bigtriangleup": "△", "bigtriangledown": "▽",
    "dotplus": "∔", "ltimes": "⋉", "rtimes": "⋊", "boxplus": "⊞", "boxminus": "⊟",
    "boxtimes": "⊠", "boxdot": "⊡", "circledast": "⊛", "circledcirc": "⊚", "centerdot": "⋅",
    "intercal": "⊺", "barwedge": "⌅", "curlywedge": "⋏", "curlyvee": "⋎", "divideontimes": "⋇",
    "gtrdot": "⋗", "lessdot": "⋖", "And": "&",
}
# fmt: on

# fmt: off
RELATION = {
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "leqslant": "⩽", "geqslant": "⩾", "ne": "≠",
    "neq": "≠", "approx": "≈", "approxeq": "≊", "equiv": "≡", "sim": "∼", "simeq": "≃",
    "cong": "≅", "propto": "∝", "varpropto": "∝", "in": "∈", "notin": "∉", "ni": "∋",
    "owns": "∋", "subset": "⊂", "supset": "⊃", "subseteq": "⊆", "supseteq": "⊇",
    "subsetneq": "⊊", "supsetneq": "⊋", "nsubseteq": "⊈", "nsupseteq": "⊉", "sqsubset": "⊏",
    "sqsupset": "⊐", "sqsubseteq": "⊑", "sqsupseteq": "⊒", "ll": "≪", "gg": "≫", "lll": "⋘",
    "ggg": "⋙", "prec": "≺", "succ": "≻", "preceq": "⪯", "succeq": "⪰", "mid": "∣", "nmid": "∤",
    "parallel": "∥", "nparallel": "∦", "perp": "⊥", "vdash": "⊢", "dashv": "⊣", "models": "⊨",
    "vDash": "⊨", "Vdash": "⊩", "asymp": "≍", "doteq": "≐", "doteqdot": "≑", "triangleq": "≜",
    "coloneqq": "≔", "eqqcolon": "≕", "coloneq": "≔", "bowtie": "⋈", "Join": "⋈", "smile": "⌣",
    "frown": "⌢", "lesssim": "≲", "gtrsim": "≳", "lessapprox": "⪅", "gtrapprox": "⪆",
    "lessgtr": "≶", "gtrless": "≷", "nless": "≮", "ngtr": "≯", "nleq": "≰", "ngeq": "≱",
    "nsim": "≁", "ncong": "≇", "nequiv": "≢", "napprox": "≉", "neqsim": "≂", "backsim": "∽",
    "thicksim": "∼", "thickapprox": "≈", "multimap": "⊸", "pitchfork": "⋔",
    "vartriangleleft": "⊲", "vartriangleright": "⊳", "trianglelefteq": "⊴",
    "trianglerighteq": "⊵", "to": "→", "rightarrow": "→", "leftarrow": "←", "gets": "←",
    "leftrightarrow": "↔", "Rightarrow": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔",
    "implies": "⟹", "impliedby": "⟸", "iff": "⟺", "longrightarrow": "⟶", "longleftarrow": "⟵",
    "longleftrightarrow": "⟷", "Longrightarrow": "⟹", "Longleftarrow": "⟸",
    "Longleftrightarrow": "⟺", "mapsto": "↦", "longmapsto": "⟼", "uparrow": "↑",
    "downarrow": "↓", "updownarrow": "↕", "Uparrow": "⇑", "Downarrow": "⇓", "Updownarrow": "⇕",
    "nearrow": "↗", "searrow": "↘", "swarrow": "↙", "nwarrow": "↖", "hookrightarrow": "↪",
    "hookleftarrow": "↩", "rightharpoonup": "⇀", "rightharpoondown": "⇁", "leftharpoonup": "↼",
    "leftharpoondown": "↽", "rightleftharpoons": "⇌", "leftrightharpoons": "⇋",
    "rightrightarrows": "⇉", "leftleftarrows": "⇇", "rightleftarrows": "⇄",
    "leftrightarrows": "⇆", "twoheadrightarrow": "↠", "twoheadleftarrow": "↞",
    "rightsquigarrow": "⇝", "leadsto": "⇝", "leftrightsquigarrow": "↭", "circlearrowleft": "↺",
    "circlearrowright": "↻", "curvearrowleft": "↶", "curvearrowright": "↷", "nrightarrow": "↛",
    "nleftarrow": "↚", "nRightarrow": "⇏", "nLeftarrow": "⇍", "nleftrightarrow": "↮",
    "nLeftrightarrow": "⇎", "upharpoonright": "↾", "downharpoonright": "⇂", "restriction": "↾",
    "Lsh": "↰", "Rsh": "↱", "precsim": "≾", "succsim": "≿", "eqsim": "≂", "risingdotseq": "≓",
    "fallingdotseq": "≒", "circeq": "≗", "bumpeq": "≏", "Bumpeq": "≎", "between": "≬",
    "shortmid": "∣", "shortparallel": "∥", "smallsmile": "⌣", "smallfrown": "⌢",
    "sqsubsetneq": "⊏", "notni": "∌", "nni": "∌", "nsubset": "⊄", "nsupset": "⊅", "lneq": "⪇",
    "gneq": "⪈", "lneqq": "≨", "gneqq": "≩", "leqq": "≦", "geqq": "≧", "eqcirc": "≖",
    "Subset": "⋐", "Supset": "⋑", "nprec": "⊀", "nsucc": "⊁", "vartriangle": "△",
}
# fmt: on

PUNCTUATION = {",": ",", ";": ";", "colon": ":", "ldotp": ".", "cdotp": "⋅"}

# fmt: off
OPENING = {
    "(": "(", "[": "[", "{": "{", "lbrace": "{", "lbrack": "[", "langle": "⟨", "lfloor": "⌊",
    "lceil": "⌈", "lvert": "|", "lVert": "‖", "ulcorner": "⌜", "llcorner": "⌞", "lgroup": "⟮",
    "lmoustache": "⎰", "llbracket": "⟦", "lBrack": "⟦", "lparen": "(",
}
# fmt: on
# fmt: off
CLOSING = {
    ")": ")", "]": "]", "}": "}", "rbrace": "}", "rbrack": "]", "rangle": "⟩", "rfloor": "⌋",
    "rceil": "⌉", "rvert": "|", "rVert": "‖", "urcorner": "⌝", "lrcorner": "⌟", "rgroup": "⟯",
    "rmoustache": "⎱", "rrbracket": "⟧", "rBrack": "⟧", "rparen": ")",
}
# fmt: on
DELIMITERS = {
    **OPENING,
    **CLOSING,
    "|": "|",
    "vert": "|",
    "Vert": "‖",
    "\\|": "‖",
    "/": "/",
    "backslash": "\\",
    "uparrow": "↑",
    "downarrow": "↓",
    "updownarrow": "↕",
    "Uparrow": "⇑",
    "Downarrow": "⇓",
    "Updownarrow": "⇕",
    ".": "",
    "<": "⟨",
    ">": "⟩",
    "lt": "⟨",
    "gt": "⟩",
    "arrowvert": "|",
    "Arrowvert": "‖",
    "bracevert": "|",
}

# fmt: off
BIG_OPERATORS = {
    "sum": "∑", "prod": "∏", "coprod": "∐", "int": "∫", "iint": "∬", "iiint": "∭",
    "iiiint": "⨌", "oint": "∮", "oiint": "∯", "oiiint": "∰", "bigcup": "⋃", "bigcap": "⋂",
    "bigoplus": "⨁", "bigotimes": "⨂", "bigodot": "⨀", "bigvee": "⋁", "bigwedge": "⋀",
    "biguplus": "⨄", "bigsqcup": "⨆", "intop": "∫", "smallint": "∫",
}
# fmt: on
INTEGRALS = frozenset("∫∬∭⨌∮∯∰")

NAMED = {
    "arccos",
    "arcsin",
    "arctan",
    "arg",
    "cos",
    "cosh",
    "cot",
    "coth",
    "csc",
    "deg",
    "dim",
    "exp",
    "hom",
    "ker",
    "lg",
    "ln",
    "log",
    "sec",
    "sin",
    "sinh",
    "tan",
    "tanh",
    "sgn",
    "tr",
    "Tr",
    "diag",
    "rank",
    "softmax",
    "KL",
    "Var",
    "Cov",
    "erf",
    "erfc",
    "span",
    "sech",
    "csch",
    "arcsinh",
    "arccosh",
    "arctanh",
    "arccot",
    "cotg",
    "tg",
    "th",
    "sh",
    "ch",
}
NAMED_LIMITS = {
    "det",
    "gcd",
    "lcm",
    "inf",
    "lim",
    "liminf",
    "limsup",
    "max",
    "min",
    "Pr",
    "sup",
    "argmax",
    "argmin",
    "injlim",
    "projlim",
    "esssup",
    "essinf",
}
# fmt: off
_NAMED_SHOWN = {
    "liminf": "lim inf", "limsup": "lim sup", "argmax": "arg max", "argmin": "arg min",
    "injlim": "inj lim", "projlim": "proj lim", "esssup": "ess sup", "essinf": "ess inf",
}
# fmt: on

# fmt: off
ACCENTS = {
    "hat": "\u0302", "check": "\u030c", "tilde": "\u0303", "acute": "\u0301", "grave": "\u0300",
    "dot": "\u0307", "ddot": "\u0308", "dddot": "\u20db", "ddddot": "\u20dc", "breve": "\u0306",
    "bar": "\u0304", "vec": "\u20d7", "mathring": "\u030a", "widehat": "\u0302",
    "widetilde": "\u0303", "widecheck": "\u030c",
}
# fmt: on
WIDE_ACCENTS = frozenset({"widehat", "widetilde", "widecheck"})

SPACES = {
    ",": 3 / 18,
    ":": 4 / 18,
    ">": 4 / 18,
    ";": 5 / 18,
    "!": -3 / 18,
    " ": 0.25,
    "quad": 1.0,
    "qquad": 2.0,
    "enspace": 0.5,
    "thinspace": 3 / 18,
    "medspace": 4 / 18,
    "thickspace": 5 / 18,
    "negthinspace": -3 / 18,
    "negmedspace": -4 / 18,
    "negthickspace": -5 / 18,
    "enskip": 0.5,
    "nobreakspace": 0.25,
    "space": 0.25,
}
"""Spaces, in em of the current size (a thin space is 3 mu, 18 mu to the em)."""

FONT_COMMANDS = {
    "mathrm": "rm",
    "mathdefault": "rm",  # matplotlib's: the words' upright face (its log ticks use it)
    "mathit": "it",
    "mathbf": "bf",
    "mathsf": "sf",
    "mathtt": "tt",
    "mathcal": "cal",
    "mathscr": "scr",
    "mathbb": "bb",
    "mathfrak": "frak",
    "boldsymbol": "bi",
    "bm": "bi",
    "pmb": "bi",
    "mathbfit": "bi",
    "mathnormal": None,
    "mathsfit": "sfit",
    "mathbfsf": "bfsf",
    "Bbb": "bb",
    "bold": "bf",
    "mathds": "bb",
    "mathbbm": "bb",
}
FONT_SWITCHES = {
    "rm": "rm",
    "it": "it",
    "bf": "bf",
    "sf": "sf",
    "tt": "tt",
    "cal": "cal",
    "mit": None,
    "bold": "bf",
    "Bbb": "bb",
    "frak": "frak",
    "boldmath": "bi",
}
# fmt: off
TEXT_COMMANDS = {
    "text": "rm", "textrm": "rm", "textup": "rm", "textnormal": "rm", "mbox": "rm",
    "hbox": "rm", "textit": "it", "emph": "it", "textbf": "bf", "textsf": "sf", "texttt": "tt",
    "textmd": "rm", "textsl": "it",
}
# fmt: on

_ALPHABETS = {
    # font: (capital A, small a, digit 0, exceptions)
    "bf": (0x1D400, 0x1D41A, 0x1D7CE, {}),
    "it": (0x1D434, 0x1D44E, None, {"h": "ℎ"}),
    "bi": (0x1D468, 0x1D482, 0x1D7CE, {}),
    "cal": (
        0x1D49C,
        0x1D4B6,
        None,
        {
            "B": "ℬ",
            "E": "ℰ",
            "F": "ℱ",
            "H": "ℋ",
            "I": "ℐ",
            "L": "ℒ",
            "M": "ℳ",
            "R": "ℛ",
            "e": "ℯ",
            "g": "ℊ",
            "o": "ℴ",
        },
    ),
    "scr": (
        0x1D49C,
        0x1D4B6,
        None,
        {
            "B": "ℬ",
            "E": "ℰ",
            "F": "ℱ",
            "H": "ℋ",
            "I": "ℐ",
            "L": "ℒ",
            "M": "ℳ",
            "R": "ℛ",
            "e": "ℯ",
            "g": "ℊ",
            "o": "ℴ",
        },
    ),
    "frak": (0x1D504, 0x1D51E, None, {"C": "ℭ", "H": "ℌ", "I": "ℑ", "R": "ℜ", "Z": "ℨ"}),
    "bb": (
        0x1D538,
        0x1D552,
        0x1D7D8,
        {"C": "ℂ", "H": "ℍ", "N": "ℕ", "P": "ℙ", "Q": "ℚ", "R": "ℝ", "Z": "ℤ"},
    ),
    "sf": (0x1D5A0, 0x1D5BA, 0x1D7E2, {}),
    "sfit": (0x1D608, 0x1D622, 0x1D7E2, {}),
    "bfsf": (0x1D5D4, 0x1D5EE, 0x1D7EC, {}),
    "tt": (0x1D670, 0x1D68A, 0x1D7F6, {}),
}
_GREEK_BOLD = {
    **{chr(0x391 + i): chr(0x1D6A8 + i) for i in range(25)},
    **{chr(0x3B1 + i): chr(0x1D6C2 + i) for i in range(25)},
}
_GREEK_BOLD_ITALIC = {
    **{chr(0x391 + i): chr(0x1D71C + i) for i in range(25)},
    **{chr(0x3B1 + i): chr(0x1D736 + i) for i in range(25)},
}
_GREEK_ITALIC = {
    **{chr(0x391 + i): chr(0x1D6E2 + i) for i in range(25)},
    **{chr(0x3B1 + i): chr(0x1D6FC + i) for i in range(25)},
    "ϵ": "𝜖",
    "ϑ": "𝜗",
    "ϰ": "𝜘",
    "ϕ": "𝜙",
    "ϱ": "𝜚",
    "ϖ": "𝜛",
    "∂": "𝜕",
}

_CLASS_OF = {
    **dict.fromkeys("+−±∓×÷⋅∗⋆∘∙⊕⊖⊗⊘⊙∪∩⊔⊓⊎∧∨∖≀⨿◁▷∔⋉⋊⊞⊟⊠⊡", BIN),
    **dict.fromkeys(
        "=<>≤≥⩽⩾≠≈≊≡∼≃≅∝∈∉∋⊂⊃⊆⊇⊊⊋⊈⊉⊏⊐⊑⊒≪≫⋘⋙≺≻⪯⪰∣∤∥∦⊥⊢⊣⊨⊩≍≐≑≜≔≕⋈⌣⌢"
        "≲≳⪅⪆≶≷≮≯≰≱≁≇≢≉≂∽⊸⋔⊲⊳⊴⊵→←↔⇒⇐⇔⟹⟸⟺⟶⟵⟷↦⟼↑↓↕⇑⇓⇕↗↘↙↖↪↩⇀⇁↼↽⇌⇋⇉⇇⇄⇆"
        "↠↞⇝↭↺↻↶↷↛↚⇏⇍↮⇎↾⇂↰↱≾≿≓≒≗≏≎≬⊄⊅⪇⪈≨≩≦≧≖⋐⋑⊀⊁∶:",
        REL,
    ),
    **dict.fromkeys("([{⟨⌊⌈⟮⎰⟦⌜⌞", OPEN),
    **dict.fromkeys(")]}⟩⌋⌉⟯⎱⟧⌝⌟!", CLOSE),
    **dict.fromkeys(",;", PUNCT),
    **dict.fromkeys("∑∏∐∫∬∭⨌∮∯∰⋃⋂⨁⨂⨀⋁⋀⨄⨆", OP),
}

# fmt: off
_NEGATED = {
    "=": "≠", "<": "≮", ">": "≯", "≤": "≰", "≥": "≱", "∈": "∉", "∋": "∌", "⊂": "⊄", "⊃": "⊅",
    "⊆": "⊈", "⊇": "⊉", "≡": "≢", "∼": "≁", "≅": "≇", "≈": "≉", "∣": "∤", "∥": "∦", "→": "↛",
    "←": "↚", "↔": "↮", "⇒": "⇏", "⇐": "⇍", "⇔": "⇎", "≺": "⊀", "≻": "⊁", "⊢": "⊬", "⊨": "⊭",
    "∃": "∄",
}
# fmt: on

ENVIRONMENTS = {
    # name: (left, right, column alignment, cell style, kind)
    "matrix": ("", "", "c", "T", "matrix"),
    "pmatrix": ("(", ")", "c", "T", "matrix"),
    "bmatrix": ("[", "]", "c", "T", "matrix"),
    "Bmatrix": ("{", "}", "c", "T", "matrix"),
    "vmatrix": ("|", "|", "c", "T", "matrix"),
    "Vmatrix": ("‖", "‖", "c", "T", "matrix"),
    "smallmatrix": ("", "", "c", "S", "small"),
    "psmallmatrix": ("(", ")", "c", "S", "small"),
    "bsmallmatrix": ("[", "]", "c", "S", "small"),
    "cases": ("{", "", "l", "T", "cases"),
    "dcases": ("{", "", "l", "D", "cases"),
    "rcases": ("", "}", "l", "T", "cases"),
    "array": ("", "", "c", "T", "array"),
    "aligned": ("", "", "rl", "D", "aligned"),
    "align": ("", "", "rl", "D", "aligned"),
    "align*": ("", "", "rl", "D", "aligned"),
    "alignat": ("", "", "rl", "D", "aligned"),
    "alignat*": ("", "", "rl", "D", "aligned"),
    "alignedat": ("", "", "rl", "D", "aligned"),
    "split": ("", "", "rl", "D", "aligned"),
    "eqnarray": ("", "", "rcl", "D", "array"),
    "eqnarray*": ("", "", "rcl", "D", "array"),
    "gather": ("", "", "c", "D", "gathered"),
    "gather*": ("", "", "c", "D", "gathered"),
    "gathered": ("", "", "c", "D", "gathered"),
    "equation": ("", "", "c", "D", "gathered"),
    "equation*": ("", "", "c", "D", "gathered"),
    "multline": ("", "", "c", "D", "gathered"),
    "multline*": ("", "", "c", "D", "gathered"),
    "displaymath": ("", "", "c", "D", "gathered"),
    "math": ("", "", "c", "T", "gathered"),
    "subarray": ("", "", "c", "S", "small"),
    "matrix*": ("", "", "c", "T", "matrix"),
    "pmatrix*": ("(", ")", "c", "T", "matrix"),
    "bmatrix*": ("[", "]", "c", "T", "matrix"),
}
_ARGUMENT_ENVIRONMENTS = {
    "array",
    "alignat",
    "alignat*",
    "alignedat",
    "subarray",
    "matrix*",
    "pmatrix*",
    "bmatrix*",
}

ERROR_COLOUR = "#c0392b"

# -- the parsed formula -----------------------------------------------------------------


@dataclass(slots=True)
class Sym:
    """One symbol: a letter, a digit, an operator, a delimiter."""

    char: str
    kind: int = ORD
    font: str | None = None
    """``rm``, ``it``, ``bf``, ``bi``, ``sf``, ``tt``, ``cal``, ``bb``, ``frak``: or None,
    which sets Latin and lower-case Greek letters italic and everything else upright."""


@dataclass(slots=True)
class Text:
    """Words inside maths (``\\text{if}``), set as text."""

    words: str
    font: str = "rm"


@dataclass(slots=True)
class Group:
    items: list
    kind: int = ORD


@dataclass(slots=True)
class Scripts:
    base: object
    sup: list | None = None
    sub: list | None = None
    prime: str = ""
    """Primes on the base (q' is q with ′): set at the base's size and height, the
    subscript under them and the superscript after them, as TeX sets q'_{2i}."""


@dataclass(slots=True)
class Operator:
    """A big operator (``\\sum``) or a named one (``\\max``): with limits above and below
    in display (``limits``), or scripts beside it."""

    symbol: str
    named: bool = False
    limits: bool | None = None
    body: list | None = None
    """``\\mathop{...}``: an operator made of what it holds (``\\mathop{\\mathrm{Res}}``),
    set as written, its limits above and below in display as any operator's."""


@dataclass(slots=True)
class Fraction:
    numerator: list
    denominator: list
    rule: bool = True
    style: str | None = None
    left: str = ""
    right: str = ""


@dataclass(slots=True)
class Radical:
    body: list
    degree: list | None = None


@dataclass(slots=True)
class Fenced:
    left: str
    body: list
    right: str


@dataclass(slots=True)
class Middle:
    delimiter: str


@dataclass(slots=True)
class Big:
    delimiter: str
    size: int
    kind: int


@dataclass(slots=True)
class Accent:
    body: list
    mark: str
    wide: bool = False


@dataclass(slots=True)
class Line:
    body: list
    over: bool = True


@dataclass(slots=True)
class Brace:
    body: list
    over: bool = True
    label: list | None = None


@dataclass(slots=True)
class Arrow:
    """An arrow over or under its argument that stretches to it (``\\overrightarrow``),
    or a relation arrow that stretches over words (``\\xrightarrow{k}``)."""

    char: str
    body: list | None = None
    over: list | None = None
    under: list | None = None
    below: bool = False


@dataclass(slots=True)
class Stack:
    base: list
    over: list | None = None
    under: list | None = None
    kind: int = ORD


@dataclass(slots=True)
class Array:
    rows: list
    columns: str
    left: str = ""
    right: str = ""
    style: str = "T"
    kind: str = "matrix"
    lines: frozenset = frozenset()
    """Row indices with a rule above them (``\\hline``); ``len(rows)`` for below the last."""
    bars: frozenset = frozenset()
    """Column indices with a rule before them (``|`` in an array's columns)."""


@dataclass(slots=True)
class Space:
    em: float
    inline: float | None = None
    """The width out of display style, where it differs: amsmath's ``\\pmod`` is set
    18mu from what it follows in display and 8mu within words."""


@dataclass(slots=True)
class StyleChange:
    style: str


@dataclass(slots=True)
class Coloured:
    colour: str
    body: list


@dataclass(slots=True)
class Phantom:
    body: list
    width: bool = True
    height: bool = True
    shown: bool = False
    """``\\smash``: drawn, but with no height or depth."""


@dataclass(slots=True)
class Boxed:
    body: list


@dataclass(slots=True)
class Negated:
    body: object


@dataclass(slots=True)
class Classed:
    kind: int
    body: list


@dataclass(slots=True)
class Mistake:
    """What could not be read, shown as written, in red."""

    words: str


@dataclass(slots=True)
class Infix:
    command: str


@dataclass(slots=True)
class NewRow:
    pass


@dataclass(slots=True)
class Tab:
    pass


@dataclass(slots=True)
class HLine:
    pass


# -- reading LaTeX ----------------------------------------------------------------------

_TOKEN = re.compile(r"\\([A-Za-z]+\*?|.)|(\s+)|(.)", re.DOTALL)
_STARRED = frozenset({"operatorname", "hspace"})
"""Commands whose starred form is a command of its own; any other star is a star."""


@dataclass(slots=True)
class _Token:
    kind: str  # "command", "char", "space"
    value: str


def _tokens(source: str) -> list[_Token]:
    found: list[_Token] = []
    for match in _TOKEN.finditer(source):
        command, space, char = match.groups()
        if command is not None:
            if command.endswith("*") and command[:-1] not in _STARRED:
                found.append(_Token("command", command[:-1]))
                found.append(_Token("char", "*"))
            else:
                found.append(_Token("command", command))
        elif space is not None:
            found.append(_Token("space", space))
        else:
            found.append(_Token("char", char))
    return found


class ParseError(Exception):
    pass


class _Parser:
    def __init__(self, source: str) -> None:
        self.tokens = _tokens(source)
        self.at = 0
        self.problems: list[str] = []

    # -- tokens --

    def peek(self, skip_spaces: bool = True) -> _Token | None:
        at = self.at
        while skip_spaces and at < len(self.tokens) and self.tokens[at].kind == "space":
            at += 1
        return self.tokens[at] if at < len(self.tokens) else None

    def take(self, skip_spaces: bool = True) -> _Token | None:
        while skip_spaces and self.at < len(self.tokens) and self.tokens[self.at].kind == "space":
            self.at += 1
        if self.at >= len(self.tokens):
            return None
        token = self.tokens[self.at]
        self.at += 1
        return token

    def said(self, problem: str) -> None:
        if problem not in self.problems:
            self.problems.append(problem)

    # -- lists --

    def parse(self) -> list:
        items = self.items(stop=set())
        while self.peek() is not None:
            token = self.take()
            assert token is not None
            if token.kind == "char" and token.value == "}":
                self.said("a } closes no {")
            elif token.kind == "command" and token.value == "right":
                self.said("\\right has no \\left before it")
                self.delimiter("\\right")
            elif token.kind == "command" and token.value == "end":
                name = self.word_argument()
                self.said(f"\\end{{{name}}} has no \\begin{{{name}}}")
            items += self.items(stop=set())
        return items

    def items(self, stop: set[str], font: str | None = None) -> list:
        """A list of atoms, up to (not taking) a ``}`` or a command in ``stop``
        (``right``, ``end``). ``&`` and ``\\\\`` are kept in it, for an array to split on."""

        items: list = []
        while (token := self.peek()) is not None:
            if token.kind == "char" and token.value == "}":
                break
            if token.kind == "command" and (token.value in stop or token.value in {"right", "end"}):
                break
            self.take()
            if token.kind == "char" and token.value == "&":
                items.append(Tab())
                continue
            if token.kind == "command" and token.value in {"\\", "cr", "newline"}:
                self.optional_argument()
                items.append(NewRow())
                continue
            if token.kind == "command" and token.value in FONT_SWITCHES:
                font = FONT_SWITCHES[token.value]
                continue
            if token.kind == "command" and token.value in {"color", "colour"}:
                colour = self.word_argument()
                items.append(Coloured(colour, self.items(stop, font)))
                continue
            atom = self.atom(token, font)
            if atom is None:
                continue
            if isinstance(atom, (Infix, StyleChange, Space, Tab, NewRow, HLine, Middle)):
                items.append(atom)
                continue
            if isinstance(atom, Operator):
                self.limits(atom)
            items.append(self.scripts(atom, font))
        return _infix(items)

    def limits(self, operator: Operator) -> None:
        while (
            (token := self.peek()) is not None
            and token.kind == "command"
            and token.value in {"limits", "nolimits", "displaylimits"}
        ):
            self.take()
            operator.limits = {"limits": True, "nolimits": False}.get(token.value)

    def scripts(self, base: object, font: str | None) -> object:
        sup: list | None = None
        sub: list | None = None
        prime = ""
        while (token := self.peek()) is not None and token.kind == "char" and token.value in "^_'":
            self.take()
            if token.value == "'":
                primes = 1
                while (
                    next_token := self.peek(skip_spaces=False)
                ) is not None and next_token.value == "'":
                    self.take(skip_spaces=False)
                    primes += 1
                # A maths font's prime is drawn raised already: it follows its letter.
                prime += {1: "′", 2: "″", 3: "‴", 4: "⁗"}.get(primes, "′" * primes)
                continue
            argument = self.argument(font)
            if argument is None:
                self.said(f"{token.value} has nothing after it")
                argument = []
            if (
                token.value == "^"
                and argument
                and all(isinstance(item, Sym) and item.char in "′″‴⁗" for item in argument)
            ):
                prime += "".join(item.char for item in argument)  # y^{\prime}, as y'
                continue
            if token.value == "^":
                if sup is not None:
                    self.said("a symbol has two superscripts: group them, as x^{a b}")
                sup = [*(sup or []), *argument]
            else:
                if sub is not None:
                    self.said("a symbol has two subscripts: group them, as x_{a b}")
                sub = [*(sub or []), *argument]
        if sup is None and sub is None:
            return Group([base, Sym(prime)]) if prime else base
        if prime:
            return Scripts(base, sup, sub, prime)
        if isinstance(base, Brace) and base.label is None:
            label = sup if base.over else sub
            if label is not None:
                base.label = label
                rest_sup = None if base.over else sup
                rest_sub = sub if base.over else None
                if rest_sup is None and rest_sub is None:
                    return base
                return Scripts(base, rest_sup, rest_sub)
        return Scripts(base, sup, sub)

    def argument(self, font: str | None = None) -> list | None:
        """One argument: a braced group, or one token (with a command's own arguments)."""

        token = self.take()
        if token is None:
            return None
        if token.kind == "char" and token.value == "{":
            items = self.items(stop=set(), font=font)
            closing = self.take()
            if closing is None or closing.kind != "char" or closing.value != "}":
                self.said("a { is not closed")
            return items
        if token.kind == "char" and token.value in "}&^_":
            self.at -= 1
            return None
        if token.kind == "command" and token.value in FONT_SWITCHES:
            return []
        atom = self.atom(token, font)
        return [] if atom is None else [atom]

    def optional_argument(self) -> list | None:
        token = self.peek(skip_spaces=False)
        if token is None or token.value != "[":
            return None
        self.take(skip_spaces=False)
        items: list = []
        depth = 0
        while (token := self.peek()) is not None:
            if token.kind == "char" and token.value == "]" and depth == 0:
                self.take()
                return _infix(items)
            if token.kind == "char" and token.value == "{":
                depth += 1
            if token.kind == "char" and token.value == "}":
                if depth == 0:
                    break
                depth -= 1
            self.take()
            atom = self.atom(token, None)
            if atom is not None:
                atom = self.scripts(atom, None)
                items.append(atom)
        self.said("a [ is not closed")
        return _infix(items)

    def word_argument(self) -> str:
        """An argument read as plain words: a colour, an environment's name."""

        token = self.take()
        if token is None:
            return ""
        if token.value != "{":
            return token.value
        words = []
        while (token := self.take(skip_spaces=False)) is not None and token.value != "}":
            words.append(("\\" + token.value) if token.kind == "command" else token.value)
        if token is None:
            self.said("a { is not closed")
        return "".join(words).strip()

    def text_argument(self) -> str:
        """``\\text{...}``: the words as written, spaces kept, a few commands read."""

        token = self.take()
        if token is None:
            return ""
        if token.value != "{":
            return token.value
        words: list[str] = []
        depth = 0
        while (token := self.take(skip_spaces=False)) is not None:
            if token.kind == "char" and token.value == "{":
                depth += 1
                continue
            if token.kind == "char" and token.value == "}":
                if depth == 0:
                    return "".join(words)
                depth -= 1
                continue
            if token.kind == "command":
                words.append(
                    _TEXT_SYMBOLS.get(token.value, "" if token.value.isalpha() else token.value)
                )
            elif token.kind == "char" and token.value == "~":
                words.append("\u00a0")
            elif token.kind == "char" and token.value == "$":
                continue
            else:
                words.append(" " if token.kind == "space" else token.value)
        self.said("a { is not closed")
        return "".join(words)

    def delimiter(self, command: str) -> str:
        token = self.take()
        if token is None:
            self.said(f"{command} needs a delimiter after it, as {command}(")
            return ""
        key = token.value
        if token.kind == "command" and key == "|":
            key = "\\|"
        if key in DELIMITERS:
            return DELIMITERS[key]
        if token.kind == "char" and len(key) == 1 and not key.isalnum():
            return key
        self.said(f"{command} needs a delimiter after it, as {command}(, not {key}")
        return ""

    # -- atoms --

    def atom(self, token: _Token, font: str | None) -> object | None:
        if token.kind == "space":
            return None
        if token.kind == "char":
            return self.char(token.value, font)
        return self.command(token.value, font)

    def char(self, char: str, font: str | None) -> object | None:
        if char == "{":
            # Up to the brace that closes it: an escaped \} (a brace to be drawn) is not one.
            items = self.items(stop=set(), font=font)
            closing = self.take()
            if closing is None or closing.kind != "char" or closing.value != "}":
                self.said("a { is not closed")
            return Group(items)
        if char == "}":
            return None
        if char == "~":
            return Space(0.25)
        if char in "^_":
            self.at -= 1
            return Group([])
        if char == "'":
            return Sym("′")
        if char == "-":
            char = "−"
        if char == "*":
            char = "∗"
        if char == "`":
            char = "‘"
        kind = _CLASS_OF.get(char, ORD)
        if char in ".":
            kind = ORD
        if char == ":":
            kind = REL
        if char == "|":
            kind = ORD
        if char in "∑∏∐∫∬∭⨌∮∯∰⋃⋂⨁⨂⨀⋁⋀⨄⨆":
            return Operator(char)
        return Sym(char, kind, font)

    def command(self, name: str, font: str | None) -> object | None:
        if name in GREEK:
            char = GREEK[name]
            return Sym(char, ORD, font)
        if name in BIG_OPERATORS:
            return Operator(BIG_OPERATORS[name])
        if name in NAMED or name in NAMED_LIMITS:
            return Operator(
                _NAMED_SHOWN.get(name, name),
                named=True,
                limits=None if name in NAMED_LIMITS else False,
            )
        if name in ("operatorname", "operatorname*", "DeclareMathOperator"):
            words = self.text_argument()
            return Operator(words.strip(), named=True, limits=None if name.endswith("*") else False)
        if name in SPACES:
            return Space(SPACES[name])
        if name in {"hspace", "hspace*", "hskip", "mspace", "mkern", "kern", "mskip"}:
            return Space(self.length(name))
        if name in {"displaystyle", "textstyle", "scriptstyle", "scriptscriptstyle"}:
            return StyleChange(
                {
                    "displaystyle": "D",
                    "textstyle": "T",
                    "scriptstyle": "S",
                    "scriptscriptstyle": "SS",
                }[name]
            )
        if name in {"frac", "dfrac", "tfrac", "cfrac", "binom", "dbinom", "tbinom"}:
            numerator = self.argument(font)
            denominator = self.argument(font)
            if numerator is None or denominator is None:
                self.said(f"\\{name} takes two arguments, as \\{name}{{a}}{{b}}")
            style = {"dfrac": "D", "tfrac": "T", "dbinom": "D", "tbinom": "T", "cfrac": "D"}.get(
                name
            )
            binomial = "binom" in name
            return Fraction(
                numerator or [],
                denominator or [],
                rule=not binomial,
                style=style,
                left="(" if binomial else "",
                right=")" if binomial else "",
            )
        if name in {"over", "choose", "atop", "brace", "brack"}:
            return Infix(name)
        if name == "sqrt":
            degree = self.optional_argument()
            body = self.argument(font)
            if body is None:
                self.said("\\sqrt takes an argument, as \\sqrt{x}")
            return Radical(body or [], degree)
        if name == "left":
            left = self.delimiter("\\left")
            body = self.items(stop={"right"}, font=font)
            token = self.take()
            if token is None or token.value != "right":
                self.said("\\left has no \\right after it")
                return Fenced(left, body, "")
            right = self.delimiter("\\right")
            return Fenced(left, body, right)
        if name == "middle":
            return Middle(self.delimiter("\\middle"))
        if name.rstrip("lrm") in {"big", "Big", "bigg", "Bigg"}:
            base = name.rstrip("lrm")
            size = {"big": 1, "Big": 2, "bigg": 3, "Bigg": 4}[base]
            ending = name[len(base) :]
            delimiter = self.delimiter(f"\\{name}")
            kind = {"l": OPEN, "r": CLOSE, "m": REL}.get(ending, _CLASS_OF.get(delimiter, ORD))
            return Big(delimiter, size, kind)
        if name in ACCENTS:
            body = self.argument(font)
            if body is None:
                self.said(f"\\{name} takes an argument, as \\{name}{{x}}")
            return Accent(body or [], ACCENTS[name], wide=name in WIDE_ACCENTS)
        if name in {"overline", "underline"}:
            body = self.argument(font)
            return Line(body or [], over=name == "overline")
        if name in {"overbrace", "underbrace"}:
            body = self.argument(font)
            return Brace(body or [], over=name == "overbrace")
        if name in {
            "overrightarrow",
            "overleftarrow",
            "overleftrightarrow",
            "underrightarrow",
            "underleftarrow",
            "underleftrightarrow",
            "overset_arrow",
        }:
            body = self.argument(font)
            char = "↔" if "leftright" in name else ("→" if "right" in name else "←")
            return Arrow(char, body=body or [], below=name.startswith("under"))
        if name in {
            "xrightarrow",
            "xleftarrow",
            "xleftrightarrow",
            "xRightarrow",
            "xLeftarrow",
            "xLeftrightarrow",
            "xmapsto",
            "xrightleftharpoons",
            "xhookrightarrow",
            "xlongequal",
            "xtofrom",
        }:
            under = self.optional_argument()
            over = self.argument(font)
            char = {
                "xrightarrow": "→",
                "xleftarrow": "←",
                "xleftrightarrow": "↔",
                "xRightarrow": "⇒",
                "xLeftarrow": "⇐",
                "xLeftrightarrow": "⇔",
                "xmapsto": "↦",
                "xrightleftharpoons": "⇌",
                "xhookrightarrow": "↪",
                "xlongequal": "=",
                "xtofrom": "⇄",
            }[name]
            return Arrow(char, over=over or [], under=under)
        if name in {"overset", "underset", "stackrel"}:
            top = self.argument(font)
            base = self.argument(font)
            if top is None or base is None:
                self.said(f"\\{name} takes two arguments, as \\{name}{{a}}{{b}}")
            kind = REL if name == "stackrel" else _kind_of(base or [])
            if name == "underset":
                return Stack(base or [], under=top or [], kind=kind)
            return Stack(base or [], over=top or [], kind=kind)
        if name == "substack":
            body = self.argument(font) or []
            return Array(_rows(body), "c", style="S", kind="small")
        if name in FONT_COMMANDS:
            body = self.argument(FONT_COMMANDS[name])
            return Group(body or [])
        if name in TEXT_COMMANDS:
            return Text(self.text_argument(), TEXT_COMMANDS[name])
        if name in {
            "mathop",
            "mathbin",
            "mathrel",
            "mathord",
            "mathopen",
            "mathclose",
            "mathpunct",
            "mathinner",
        }:
            kind = {
                "mathop": OP,
                "mathbin": BIN,
                "mathrel": REL,
                "mathord": ORD,
                "mathopen": OPEN,
                "mathclose": CLOSE,
                "mathpunct": PUNCT,
                "mathinner": INNER,
            }[name]
            body = self.argument(font) or []
            if kind == OP:
                return Operator("", named=True, limits=None, body=body)
            return Classed(kind, body)
        if name in {"textcolor", "colorbox"}:
            colour = self.word_argument()
            body = self.argument(font) or []
            return Coloured(colour, body) if name == "textcolor" else Boxed(body)
        if name in {"phantom", "hphantom", "vphantom"}:
            body = self.argument(font) or []
            return Phantom(body, width=name != "vphantom", height=name != "hphantom")
        if name == "smash":
            self.optional_argument()
            return Phantom(self.argument(font) or [], width=True, height=False, shown=True)
        if name in {"mathstrut", "strut"}:
            return Phantom([Sym("(", OPEN)], width=False)
        if name in {"boxed", "fbox", "framebox"}:
            if name == "fbox":
                return Boxed([Text(self.text_argument())])
            return Boxed(self.argument(font) or [])
        if name in {"not", "cancel", "bcancel", "xcancel", "sout"}:
            token = self.take()
            if token is None:
                self.said(f"\\{name} needs something after it, as \\{name}=")
                return None
            if name == "not" and token.kind == "char" and token.value in _NEGATED:
                return Sym(_NEGATED[token.value], REL)
            if name == "not" and token.kind == "command":
                inner = self.command(token.value, font)
                if isinstance(inner, Sym) and inner.char in _NEGATED:
                    return Sym(_NEGATED[inner.char], inner.kind)
                return Negated(inner)
            if token.value == "{":
                self.at -= 1
                return Negated(Group(self.argument(font) or []))
            return Negated(self.atom(token, font))
        if name == "begin":
            return self.environment()
        if name == "hline" or name == "midrule" or name == "toprule" or name == "bottomrule":
            return HLine()
        if name in {"label", "tag", "tag*", "ref", "eqref"}:
            self.word_argument()
            return None
        if name in {
            "nonumber",
            "notag",
            "limits",
            "nolimits",
            "displaylimits",
            "relax",
            "allowbreak",
            "nobreak",
            "protect",
            "noindent",
            "centering",
            "normalsize",
            "small",
            "large",
            "Large",
            "footnotesize",
            "scriptsize",
            "tiny",
            "huge",
            "Huge",
            "LARGE",
            "leavevmode",
        }:
            return None
        if name in {"pmod", "pod", "mod"}:
            # amsmath's: 18mu from what it follows in display, less within words; "mod"
            # in the operators' face but an ordinary atom, 6mu from its argument.
            mod = [Classed(ORD, [Operator("mod", named=True, limits=False)]), Space(6 / 18)]
            if name == "mod":
                return Group([Space(1.0, inline=12 / 18), *mod])
            body = self.argument(font) or []
            inside = [*mod, *body] if name == "pmod" else body
            return Group([Space(1.0, inline=8 / 18), Sym("(", OPEN), *inside, Sym(")", CLOSE)])
        if name == "bmod":
            return Classed(BIN, [Operator("mod", named=True, limits=False)])
        if name in BINARY:
            return Sym(BINARY[name], BIN)
        if name in RELATION:
            return Sym(RELATION[name], REL)
        if name in OPENING and name != "{":
            return Sym(OPENING[name], OPEN)
        if name in CLOSING and name != "}":
            return Sym(CLOSING[name], CLOSE)
        if name in PUNCTUATION:
            return Sym(PUNCTUATION[name], PUNCT)
        if name in ORDINARY:
            char = ORDINARY[name]
            if name in {"{", "lbrace"}:
                return Sym("{", OPEN)
            if name in {"}", "rbrace"}:
                return Sym("}", CLOSE)
            return Sym(char, _CLASS_OF.get(char, ORD) if name not in {"|", "Vert", "vert"} else ORD)
        if name == "ce":
            return self.chemistry()
        if name in {"si", "unit"}:
            return Group(_units(self.word_argument()))
        if name in {"SI", "qty"}:
            value = self.word_argument()
            unit = self.word_argument()
            return Group([*_number(value), Space(3 / 18), *_units(unit)])
        if name == "num":
            return Group(_number(self.word_argument()))
        if name == "ang":
            return Group([*_number(self.word_argument()), Sym("°")])
        if name == "degree":
            return Sym("°")
        self.said(f"\\{name} is not a maths command flexo knows{_nearest(name)}")
        return Mistake(f"\\{name}")

    def length(self, command: str) -> float:
        words = self.word_argument() if command in {"hspace", "hspace*", "mspace"} else ""
        if not words:
            # \kern 3pt, \hskip 1em: read the words up to the unit.
            collected = ""
            while (token := self.peek(skip_spaces=False)) is not None and (
                (token.kind == "char"
                and (token.value.isdigit() or token.value in ".-"))
                or (token.kind == "space"
                and not collected)
            ):
                self.take(skip_spaces=False)
                collected += token.value if token.kind == "char" else ""
            unit = ""
            while (
                (token := self.peek(skip_spaces=False)) is not None
                and token.kind == "char"
                and token.value.isalpha()
                and len(unit) < 2
            ):
                self.take(skip_spaces=False)
                unit += token.value
            words = collected + unit
        match = re.fullmatch(r"\s*(-?[\d.]+)\s*(em|ex|pt|mu|px|mm|cm|in|bp|pc)?\s*", words)
        if not match:
            self.said(f"\\{command} takes a length, as \\{command}{{1em}}")
            return 0.0
        value = float(match.group(1))
        unit = match.group(2) or "em"
        return (
            value
            * {
                "em": 1.0,
                "ex": 0.43,
                "pt": 0.1,
                "mu": 1 / 18,
                "px": 0.075,
                "mm": 0.2845,
                "cm": 2.845,
                "in": 7.227,
                "bp": 0.1004,
                "pc": 1.2,
            }[unit]
        )

    def environment(self) -> object:
        name = self.word_argument()
        if name not in ENVIRONMENTS:
            self.said(
                f"\\begin{{{name}}} is not an environment flexo knows: "
                "try pmatrix, cases or aligned"
            )
        left, right, columns, style, kind = ENVIRONMENTS.get(name, ("", "", "c", "T", "matrix"))
        if name in _ARGUMENT_ENVIRONMENTS:
            spec = self.word_argument()
            if name in {"alignat", "alignat*", "alignedat"}:
                columns = "rl"
            elif name == "subarray":
                columns = spec or "c"
            else:
                columns = spec
        body = self.items(stop={"end"})
        token = self.take()
        if token is None or token.value != "end":
            self.said(f"\\begin{{{name}}} has no \\end{{{name}}}")
        else:
            closing = self.word_argument()
            if closing != name:
                self.said(f"\\begin{{{name}}} is closed by \\end{{{closing}}}")
        bars: set[int] = set()
        if kind == "array":
            aligned = ""
            for char in columns.replace(" ", ""):
                if char == "|":
                    bars.add(len(aligned))
                elif char in "lcr":
                    aligned += char
                elif char in "pmb":
                    aligned += "l"
            columns = aligned or "c"
        rows, lines = _rows_and_lines(body)
        return Array(rows, columns, left, right, style, kind, frozenset(lines), frozenset(bars))

    def chemistry(self) -> Group:
        """``\\ce{...}`` (mhchem), as chemists write it: ``\\ce{2H2 + O2 -> 2H2O}``."""

        return Group(_chemistry(self.raw_argument()))

    def raw_argument(self) -> str:
        """A braced argument as it was written, braces inside it kept: Fe^{3+}."""

        token = self.take()
        if token is None:
            return ""
        if token.value != "{" or token.kind != "char":
            return ("\\" + token.value) if token.kind == "command" else token.value
        words, depth = [], 0
        while (token := self.take(skip_spaces=False)) is not None:
            if token.kind == "char" and token.value == "{":
                depth += 1
            elif token.kind == "char" and token.value == "}":
                if depth == 0:
                    return "".join(words)
                depth -= 1
            words.append(("\\" + token.value) if token.kind == "command" else token.value)
        self.said("a { is not closed")
        return "".join(words)


# fmt: off
_COMMANDS = frozenset({
    *GREEK, *ORDINARY, *BINARY, *RELATION, *OPENING, *CLOSING, *PUNCTUATION, *BIG_OPERATORS,
    *NAMED, *NAMED_LIMITS, *ACCENTS, *SPACES, *FONT_COMMANDS, *FONT_SWITCHES, *TEXT_COMMANDS,
    "frac", "dfrac", "tfrac", "cfrac", "binom", "dbinom", "tbinom", "over", "choose", "atop",
    "sqrt", "left", "right", "middle", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl",
    "Bigr", "biggl", "biggr", "Biggl", "Biggr", "overline", "underline", "overbrace",
    "underbrace", "overrightarrow", "overleftarrow", "overleftrightarrow", "xrightarrow",
    "xleftarrow", "xleftrightarrow", "xRightarrow", "xLeftarrow", "xmapsto", "overset",
    "underset", "stackrel", "substack", "operatorname", "mathop", "mathbin", "mathrel",
    "mathord", "textcolor", "color", "phantom", "hphantom", "vphantom", "smash", "boxed",
    "not", "begin", "end", "hline", "pmod", "bmod", "mod", "ce", "si", "SI", "num", "ang",
    "displaystyle", "textstyle", "scriptstyle", "hspace", "limits", "nolimits",
})
"""Every command the reader knows, for suggesting one when a name is mistyped."""


def _nearest(name: str) -> str:
    """A command near ``name`` (``\\xrigtarrow``: ``\\xrightarrow``), as a suggestion."""

    import difflib

    found = difflib.get_close_matches(name, [c for c in _COMMANDS if len(c) > 1], n=1, cutoff=0.75)
    return f": did you mean \\{found[0]}?" if found and len(name) > 1 else ""


_TEXT_SYMBOLS = {
    "%": "%", "&": "&", "#": "#", "$": "$", "_": "_", "{": "{", "}": "}", " ": " ",
    ",": "\u2009", ";": "\u2005", "quad": "\u2003", "qquad": "\u2003\u2003",
    "textbackslash": "\\", "ldots": "…", "dots": "…", "textendash": "–", "textemdash": "—",
    "textdegree": "°", "alpha": "α", "beta": "β", "mu": "μ", "times": "×", "pm": "±", "\\": " ",
}
# fmt: on


def _kind_of(items: list) -> int:
    if len(items) == 1 and isinstance(items[0], Sym):
        return items[0].kind
    if len(items) == 1 and isinstance(items[0], Operator):
        return OP
    return ORD


def _infix(items: list) -> list:
    """``a \\over b`` (and ``\\choose``, ``\\atop``): the list either side, a fraction."""

    for index, item in enumerate(items):
        if isinstance(item, Infix):
            before, after = items[:index], _infix(items[index + 1 :])
            if item.command == "choose":
                return [Fraction(before, after, rule=False, left="(", right=")")]
            if item.command == "brace":
                return [Fraction(before, after, rule=False, left="{", right="}")]
            if item.command == "brack":
                return [Fraction(before, after, rule=False, left="[", right="]")]
            return [Fraction(before, after, rule=item.command == "over")]
    return items


def _rows(items: list) -> list:
    return _rows_and_lines(items)[0]


def _rows_and_lines(items: list) -> tuple[list, set[int]]:
    rows: list[list[list]] = [[[]]]
    lines: set[int] = set()
    for item in items:
        if isinstance(item, NewRow):
            rows.append([[]])
        elif isinstance(item, Tab):
            rows[-1].append([])
        elif isinstance(item, HLine):
            lines.add(len(rows) - 1)  # a rule above the row about to start
        else:
            rows[-1][-1].append(item)
    if len(rows) > 1 and rows[-1] == [[]]:
        rows.pop()
        lines = {min(line, len(rows)) for line in lines}
    return rows, lines


def _number(words: str) -> list:
    """siunitx's numbers: ``1.5e-3`` as 1.5 × 10⁻³, a minus as a minus."""

    mantissa, _, power = words.strip().replace("E", "e").partition("e")

    def digits(text: str) -> list:
        return [
            Sym("−" if ch == "-" else ("±" if ch == "±" else ch), ORD, "rm")
            for ch in text
            if not ch.isspace()
        ]

    items = digits(mantissa.replace("+-", "±"))
    if power:
        ten = Group([Sym("1", ORD, "rm"), Sym("0", ORD, "rm")])
        items += (
            [Sym("×", BIN), Scripts(ten, digits(power.lstrip("+")))]
            if mantissa
            else [Scripts(ten, digits(power))]
        )
    return items


# fmt: off
_UNITS = {
    "metre": "m", "meter": "m", "second": "s", "kilogram": "kg", "gram": "g", "mole": "mol",
    "kelvin": "K", "ampere": "A", "candela": "cd", "hertz": "Hz", "newton": "N", "pascal": "Pa",
    "joule": "J", "watt": "W", "coulomb": "C", "volt": "V", "ohm": "Ω", "siemens": "S",
    "farad": "F", "tesla": "T", "weber": "Wb", "henry": "H", "liter": "L", "litre": "L",
    "molar": "M", "dalton": "Da", "electronvolt": "eV", "angstrom": "Å", "minute": "min",
    "hour": "h", "day": "d", "degree": "°", "celsius": "°C", "degreeCelsius": "°C",
    "percent": "%", "bar": "bar", "atm": "atm", "calorie": "cal", "becquerel": "Bq",
    "gray": "Gy", "sievert": "Sv", "lumen": "lm", "lux": "lx", "radian": "rad",
    "steradian": "sr", "bit": "bit", "byte": "B", "rpm": "rpm", "molal": "m", "gauss": "G",
}
# fmt: on
# fmt: off
_PREFIXES = {
    "yocto": "y", "zepto": "z", "atto": "a", "femto": "f", "pico": "p", "nano": "n",
    "micro": "μ", "milli": "m", "centi": "c", "deci": "d", "deca": "da", "deka": "da",
    "hecto": "h", "kilo": "k", "mega": "M", "giga": "G", "tera": "T", "peta": "P", "exa": "E",
    "zetta": "Z", "yotta": "Y",
}
# fmt: on


def _units(words: str) -> list:
    """siunitx's units, upright, as it sets them by default: ``\\per`` a negative power
    of the unit after it (``\\joule\\per\\mole\\per\\kelvin``: J mol⁻¹ K⁻¹), powers
    after (``\\squared``) or before (``\\square``) a unit, and units written out
    (``m.s^{-1}``, ``m/s``) as written."""

    # Each unit: [its letters, its power (as written, or a number), whether \per came first].
    parts: list = []
    prefix = ""
    inverse, before = False, 1

    def unit(letters: str) -> None:
        nonlocal prefix, inverse, before
        parts.append([Group([Sym(ch, ORD, "rm") for ch in prefix + letters]), before, inverse])
        prefix, inverse, before = "", False, 1

    for token in re.findall(r"\\[A-Za-z]+|\^\{?-?\d+\}?|[A-Za-zΩμÅ°%]+|[.~]|/|\S", words):
        if token.startswith("\\"):
            name = token[1:]
            if name in _PREFIXES:
                prefix += _PREFIXES[name]
            elif name == "per":
                inverse = True
            elif name in {"squared", "cubed"}:
                if parts and isinstance(parts[-1], list):
                    parts[-1][1] = 2 if name == "squared" else 3
            elif name in {"square", "cubic"}:
                before = 2 if name == "square" else 3
            else:
                unit(_UNITS.get(name, name))
        elif token.startswith("^"):
            if parts and isinstance(parts[-1], list):
                parts[-1][1] = token.strip("^{}")
        elif token in ".~":
            continue  # units are spaced apart anyway
        elif token == "/":
            parts.append("/")
        else:
            unit(token)
    items: list = []
    for part in parts:
        if part == "/":
            items.append(Sym("/", ORD, "rm"))
            continue
        letters, power, per = part
        if items and not (isinstance(items[-1], Sym) and items[-1].char == "/"):
            items.append(Space(3 / 18))
        exponent = str(power)
        if per and not exponent.startswith("-"):
            exponent = "-" + exponent
        if exponent == "1":
            items.append(letters)
        else:
            power_symbols = [Sym(ch, ORD, "rm") for ch in exponent.replace("-", "−")]
            items.append(Scripts(letters, power_symbols))
    return items


def _chemistry(words: str) -> list:
    """mhchem's formulas and equations: counts are subscripts, charges superscripts,
    elements upright, arrows arrows."""

    items: list = []
    arrows = {"<=>": "⇌", "<->": "↔", "->": "→", "<-": "←", "=": "=", "<=>>": "⇌", "<<=>": "⇌"}
    pattern = r"(\s+|(?:<=>>|<<=>|<=>|<->|->|<-)(?:\[[^\]]*\]){0,2})"
    for part in re.split(pattern, words):
        if not part or part.isspace():
            continue
        arrow = re.fullmatch(r"(<=>>|<<=>|<=>|<->|->|<-)((?:\[[^\]]*\]){0,2})", part)
        if arrow:
            labels = re.findall(r"\[([^\]]*)\]", arrow.group(2))
            if labels:
                # ->[\Delta][-H2O]: words over the arrow (and under it), as in TeX.
                over = parse(labels[0])[0] if labels[0] else []
                under = parse(labels[1])[0] if len(labels) > 1 and labels[1] else None
                items.append(Arrow(arrows[arrow.group(1)], over=over, under=under))
            else:
                items.append(Sym(arrows[arrow.group(1)], REL))
            continue
        if part == "+":
            items.append(Sym("+", BIN))
            continue
        if part in {"v", "^"}:
            items.append(Sym("↓" if part == "v" else "↑", ORD, "rm"))  # a precipitate, a gas
            continue
        items.append(Group(_species(part)))
    return items


def _species(words: str) -> list:
    items: list = []
    at = 0
    leading = re.match(r"\d+(?:/\d+)?", words)
    if leading:
        items += [Sym(ch, ORD, "rm") for ch in leading.group(0)]
        items.append(Space(2 / 18))
        at = leading.end()
    # An isotope's mass and number before its element: ^{14}_{6}C, ^{235}U.
    pre = re.match(r"(?:\^\{([^}]*)\}|\^(\d+))?(?:_\{([^}]*)\}|_(\d+))?", words[at:])
    if pre and pre.group(0):
        mass = pre.group(1) or pre.group(2)
        number = pre.group(3) or pre.group(4)
        items.append(Scripts(
            Group([]),
            [Sym(c, ORD, "rm") for c in mass] if mass else None,
            [Sym(c, ORD, "rm") for c in number] if number else None,
        ))
        at += pre.end()
    while at < len(words):
        char = words[at]
        if char == "^":
            match = re.match(r"\^\{([^}]*)\}|\^(\S+)", words[at:])
            charge = (match.group(1) or match.group(2)) if match else ""
            at += match.end() if match else 1
            if items:
                items[-1] = _scripted(
                    items[-1],
                    sup=[
                        Sym(
                            "−" if c == "-" else c,
                            _CLASS_OF.get(c, ORD) if c in "+−" else ORD,
                            "rm",
                        )
                        for c in charge
                    ],
                )
            continue
        if char == "_":
            match = re.match(r"_\{([^}]*)\}|_(\S)", words[at:])
            count = (match.group(1) or match.group(2)) if match else ""
            at += match.end() if match else 1
            if items:
                items[-1] = _scripted(items[-1], sub=[Sym(c, ORD, "rm") for c in count])
            continue
        if char.isdigit() and items:
            number_match = re.match(r"\d+", words[at:])
            assert number_match
            at += number_match.end()
            items[-1] = _scripted(items[-1], sub=[Sym(c, ORD, "rm") for c in number_match.group(0)])
            continue
        if char in "+-" and at == len(words) - 1 and items:
            # A charge written plainly at the end: Na+, Cl-.
            items[-1] = _scripted(items[-1], sup=[Sym("−" if char == "-" else "+", ORD, "rm")])
            at += 1
            continue
        if char == "(" and re.match(r"\((aq|s|l|g)\)", words[at:]):
            state = re.match(r"\((aq|s|l|g)\)", words[at:])
            assert state
            items += [
                Sym("(", OPEN, "rm"),
                *(Sym(c, ORD, "rm") for c in state.group(1)),
                Sym(")", CLOSE, "rm"),
            ]
            at += state.end()
            continue
        if char == ".":
            items.append(Sym("⋅", BIN))
            at += 1
            continue
        items.append(Sym(char, _CLASS_OF.get(char, ORD) if char in "()[]" else ORD, "rm"))
        at += 1
    return items


def _scripted(base: object, sup: list | None = None, sub: list | None = None) -> object:
    if isinstance(base, Scripts):
        return Scripts(
            base.base, sup if sup is not None else base.sup, sub if sub is not None else base.sub
        )
    return Scripts(base, sup, sub)


def parse(source: str) -> tuple[list, list[str]]:
    """The formula ``source`` as atoms, and what could not be read in it (in words)."""

    parser = _Parser(source)
    try:
        items = parser.parse()
    except RecursionError:
        return [Mistake(source[:60])], ["the formula is nested too deeply to set"]
    return items, parser.problems


# -- the fonts --------------------------------------------------------------------------


class Face:
    """One face at one weight, for shaping, measuring and drawing glyphs."""

    def __init__(self, face: FontFace, weight: int) -> None:
        self.face = face
        self.weight = weight
        loaded = load_face(face)
        self.upem = loaded.upem
        self.hb = hb_font(face, weight)
        self.italic = face.italic
        self.key = (face.source, face.index, weight)
        self.has_math = bool(self.hb.get_math_constant(hb.OTMathConstant.AXIS_HEIGHT))
        self._paths: dict[int, str] = {}

    def glyph(self, char: str) -> int | None:
        gid = self.hb.get_nominal_glyph(ord(char)) if len(char) == 1 else None
        return gid or None

    def advance(self, gid: int) -> float:
        return self.hb.get_glyph_h_advance(gid) / self.upem

    def extents(self, gid: int) -> tuple[float, float, float, float]:
        """Left, right, bottom, top of the glyph's ink, in em."""

        found = self.hb.get_glyph_extents(gid)
        if found is None:
            return 0.0, 0.0, 0.0, 0.0
        left = found.x_bearing / self.upem
        top = found.y_bearing / self.upem
        return left, left + found.width / self.upem, top + found.height / self.upem, top

    def path(self, gid: int) -> str:
        """The glyph's outline in font units, y up."""

        known = self._paths.get(gid)
        if known is None:
            pen = _Pen()
            self.hb.draw_glyph_with_pen(gid, pen)
            known = self._paths[gid] = pen.value()
        return known

    def shape(self, words: str) -> list[tuple[int, float, float]]:
        """``words`` shaped: each glyph and its advance and offset, in em."""

        buffer = hb.Buffer()
        buffer.add_str(words)
        buffer.guess_segment_properties()
        hb.shape(self.hb, buffer, {"kern": True, "liga": True})
        return [
            (info.codepoint, position.x_advance / self.upem, position.x_offset / self.upem)
            for info, position in zip(buffer.glyph_infos, buffer.glyph_positions, strict=True)
        ]


class _Pen:
    def __init__(self) -> None:
        self.parts: list[str] = []

    @staticmethod
    def _xy(point: tuple[float, float]) -> str:
        return f"{round(point[0], 1):g} {round(point[1], 1):g}"

    def moveTo(self, point):
        self.parts.append("M" + self._xy(point))

    def lineTo(self, point):
        self.parts.append("L" + self._xy(point))

    def curveTo(self, *points):
        self.parts.append("C" + " ".join(self._xy(point) for point in points))

    def qCurveTo(self, *points):
        # Consecutive off-curve points have an on-curve point midway between them.
        *controls, end = points
        for index, control in enumerate(controls):
            if index + 1 < len(controls):
                following = controls[index + 1]
                middle = ((control[0] + following[0]) / 2, (control[1] + following[1]) / 2)
                self.parts.append("Q" + self._xy(control) + " " + self._xy(middle))
            else:
                self.parts.append("Q" + self._xy(control) + " " + self._xy(end))

    def closePath(self):
        self.parts.append("Z")

    def endPath(self):
        pass

    def value(self) -> str:
        return "".join(self.parts)


@lru_cache(maxsize=64)
def _face(face: FontFace, weight: int) -> Face:
    return Face(face, weight)


@lru_cache(maxsize=8)
def _math_face(family: str | None) -> Face:
    """The maths font ``family``, if it is one (has a MATH table); else Latin Modern Math."""

    for name in (family, "Latin Modern Math"):
        if not name:
            continue
        faces = family_faces(name)
        if faces:
            candidate = _face(select_face(faces, 400, False), 400)
            if candidate.hb.get_math_constant(hb.OTMathConstant.AXIS_HEIGHT):
                return candidate
    raise LookupError("no maths font: Latin Modern Math is bundled with flexo, and was not found")


class Fonts:
    """Where each symbol of a formula comes from: letters, digits and words from the
    typography's faces (so maths reads with the words around it), the rest from the
    maths font, whose measures set the whole formula."""

    def __init__(self, typography: TypographyStyle) -> None:
        from flexo.text import font_stack, maths_family

        self.typography = typography
        self.stack = font_stack(typography)
        # The maths font that suits the words (Fira Math beside a sans face, Latin Modern
        # Math beside a serif) sets the formula; Latin Modern Math draws what it lacks
        # (Fira Math has no script or fraktur capitals).
        self.maths = _math_face(maths_family(typography))
        spare = _math_face("Latin Modern Math")
        self.spare = spare if spare is not self.maths else None
        self._constants: dict[str, float] = {}

    def maths_for(self, char: str) -> tuple[Face, int | None]:
        """The maths face that has ``char``, and its glyph: the chosen one, else the spare."""

        gid = self.maths.glyph(char)
        if gid is None and self.spare is not None:
            spare = self.spare.glyph(char)
            if spare is not None:
                return self.spare, spare
        return self.maths, gid

    def constant(self, name: str) -> float:
        """A MATH table constant in em (a percentage for the ``*_PERCENT*`` ones)."""

        known = self._constants.get(name)
        if known is None:
            value = self.maths.hb.get_math_constant(getattr(hb.OTMathConstant, name))
            known = value if "PERCENT" in name else value / self.maths.upem
            self._constants[name] = known
        return known

    def text_face(self, char: str, italic: bool, weight: int) -> tuple[Face, bool]:
        """The typography's face for ``char``, and whether it must be slanted by hand
        (the family has no italic)."""

        (face, _), *_ = self.stack.segments(char, weight, italic)
        return _face(face, weight), italic and not face.italic


# -- boxes ------------------------------------------------------------------------------


@dataclass(slots=True)
class GlyphItem:
    face: Face
    gid: int
    size: float
    colour: str | None = None
    slant: bool = False


@dataclass(slots=True)
class RuleItem:
    width: float
    height: float
    colour: str | None = None


@dataclass(slots=True)
class Box:
    """Laid out maths: its ink and rules at offsets from its origin (y up), and its
    width, height above the baseline, and depth below it, in points."""

    width: float = 0.0
    height: float = 0.0
    depth: float = 0.0
    items: list = field(default_factory=list)
    italic: float = 0.0
    """How far the ink leans out past the width, for a superscript to clear."""
    accent_at: float | None = None
    """Where an accent over a single symbol centres (its top accent attachment)."""
    single: bool = False
    """A single symbol: scripts sit at fixed heights rather than against its ink."""

    def put(self, other: Box, x: float, y: float) -> None:
        for ox, oy, item in other.items:
            self.items.append((x + ox, y + oy, item))

    def raised(self, shift: float) -> Box:
        moved = Box(self.width, self.height + shift, self.depth - shift, italic=self.italic)
        moved.put(self, 0.0, shift)
        return moved


def _row(boxes: list[tuple[Box, float]]) -> Box:
    """Boxes side by side on one baseline, each after a kern."""

    row = Box()
    x = 0.0
    for box, kern in boxes:
        x += kern
        row.put(box, x, 0.0)
        x += box.width
        row.height = max(row.height, box.height)
        row.depth = max(row.depth, box.depth)
    row.width = x
    if boxes:
        row.italic = boxes[-1][0].italic
    return row


def _kern(width: float) -> Box:
    return Box(width=width)


def _rule(width: float, thickness: float, bottom: float, colour: str | None) -> Box:
    box = Box(width, bottom + thickness, max(0.0, -bottom))
    box.items.append((0.0, bottom, RuleItem(width, thickness, colour)))
    return box


# -- laying out -------------------------------------------------------------------------

_STYLES = ("D", "T", "S", "SS")
_SPACING = (
    # Ord Op Bin Rel Open Close Punct Inner, for each left atom; negative: display/text only.
    (0, 1, -2, -3, 0, 0, 0, -1),
    (1, 1, 0, -3, 0, 0, 0, -1),
    (-2, -2, 0, 0, -2, 0, 0, -2),
    (-3, -3, 0, 0, -3, 0, 0, -3),
    (0, 0, 0, 0, 0, 0, 0, 0),
    (0, 1, -2, -3, 0, 0, 0, -1),
    (-1, -1, 0, -1, -1, -1, -1, -1),
    (-1, 1, -2, -3, -1, 0, -1, -1),
)
_MU = {1: 3 / 18, 2: 4 / 18, 3: 5 / 18}


@dataclass(frozen=True, slots=True)
class _Style:
    level: int  # 0 display, 1 text, 2 script, 3 scriptscript
    cramped: bool = False

    def up(self) -> _Style:
        return _Style(2 if self.level < 2 else 3, self.cramped)

    def down(self) -> _Style:
        return _Style(2 if self.level < 2 else 3, True)

    def numerator(self) -> _Style:
        return _Style({0: 1, 1: 2, 2: 3, 3: 3}[self.level], self.cramped)

    def denominator(self) -> _Style:
        return _Style({0: 1, 1: 2, 2: 3, 3: 3}[self.level], True)

    def cramp(self) -> _Style:
        return _Style(self.level, True)


class _Layout:
    def __init__(self, fonts: Fonts, size: float, weight: int) -> None:
        self.fonts = fonts
        self.base = size
        self.weight = weight
        self.colour: str | None = None
        self.depth = 0

    # -- sizes --

    def size(self, style: _Style) -> float:
        if style.level == 2:
            return self.base * self.fonts.constant("SCRIPT_PERCENT_SCALE_DOWN") / 100.0
        if style.level == 3:
            return self.base * self.fonts.constant("SCRIPT_SCRIPT_PERCENT_SCALE_DOWN") / 100.0
        return self.base

    def c(self, name: str, style: _Style) -> float:
        return self.fonts.constant(name) * self.size(style)

    # -- glyphs --

    def glyph(self, face: Face, gid: int, size: float, slant: bool = False) -> Box:
        left, right, bottom, top = face.extents(gid)
        advance = face.advance(gid)
        box = Box(advance * size, max(top, 0.0) * size, max(-bottom, 0.0) * size, single=True)
        lean = _SLANT * top if slant else 0.0
        if face.has_math:
            italic = face.hb.get_math_glyph_italics_correction(gid) / face.upem
            attach = face.hb.get_math_glyph_top_accent_attachment(gid) / face.upem
            box.accent_at = (attach if attach else (left + right) / 2) * size
        else:
            italic = max(0.0, right + lean - advance)
            # Over a slanted letter an accent sits over its top, right of its middle.
            lean_at_top = _SLANT * top if slant else (0.5 * _SLANT * top if face.italic else 0.0)
            box.accent_at = ((left + right) / 2 + lean_at_top) * size
        box.italic = italic * size
        box.items.append((0.0, 0.0, GlyphItem(face, gid, size, self.colour, slant)))
        return box

    def maths_glyph(self, char: str, style: _Style) -> Box | None:
        face, gid = self.fonts.maths_for(char)
        if gid is None:
            return None
        return self.glyph(face, gid, self.size(style))

    def symbol(self, sym: Sym, style: _Style) -> Box:
        char, font, size = sym.char, sym.font, self.size(style)
        if font in {"cal", "scr", "bb", "frak", "sf", "tt", "sfit", "bfsf"}:
            # Alphabets the maths font carries: script, blackboard, fraktur, sans, typewriter.
            mapped = alphabet(char, font)
            box = self.maths_glyph(mapped, style) if mapped != char else None
            if box is not None:
                return box
        letter = char.isascii() and char.isalpha()
        greek = "\u0370" <= char <= "\u03ff"
        if greek and font in {"bf", "bi"}:
            box = self.maths_glyph(alphabet(char, font), style)
            if box is not None:
                return box
        if (
            letter
            or greek
            or char.isdigit()
            or (font in {"rm", "it", "bf", "bi"} and sym.kind == ORD)
        ):
            italic = font in {"it", "bi"} or (
                font is None and (letter or (greek and char.islower()))
            )
            weight = 700 if font in {"bf", "bi"} else self.weight
            face, slant = self.fonts.text_face(char, italic, weight)
            if greek and italic:
                # TeX's lower-case Greek is italic, and the maths font's own letter -- the
                # one maths set as words has too; a text face's italic θ may be drawn as ϑ.
                box = self.maths_glyph(_GREEK_ITALIC.get(char, char), style)
                if box is not None:
                    return box
            gid = face.glyph(char)
            if gid is not None:
                return self.glyph(face, gid, size, slant)
        if font in {None, "rm", "it", "bf", "bi"} and (
            char in _WORDS_OWN or sym.kind in {BIN, REL, PUNCT, ORD}
        ):
            # Signs and brackets are the words' own where their faces have them, as maths
            # set as words has them; the maths font's take over where they must grow.
            face, slant = self.fonts.text_face(char, False, self.weight)
            gid = face.glyph(char)
            if gid is not None and not face.has_math:
                return self.glyph(face, gid, size)
        # Operators, relations, delimiters and the rest: the maths font's, which grow.
        box = self.maths_glyph(char, style)
        if box is not None:
            return box
        face, slant = self.fonts.text_face(char, False, self.weight)
        gid = face.glyph(char)
        if gid is not None:
            return self.glyph(face, gid, size, slant)
        return Box(0.5 * size, 0.7 * size, 0.0)

    def words(self, text: Text, style: _Style) -> Box:
        size = self.size(style)
        italic = text.font == "it"
        weight = 700 if text.font == "bf" else self.weight
        pieces: list[tuple[Box, float]] = []
        for face_spec, piece in self.fonts.stack.segments(
            text.words, weight, italic, code=text.font == "tt"
        ):
            face = _face(face_spec, weight)
            slant = italic and not face.italic
            x = 0.0
            row = Box()
            for gid, advance, offset in face.shape(piece):
                if gid:
                    glyph = self.glyph(face, gid, size, slant)
                    row.put(glyph, x + offset * size, 0.0)
                    row.height = max(row.height, glyph.height)
                    row.depth = max(row.depth, glyph.depth)
                x += advance * size
            row.width = x
            pieces.append((row, 0.0))
        return _row(pieces)

    # -- lists --

    def items(self, items: list, style: _Style) -> Box:
        self.depth += 1
        if self.depth > 60:
            self.depth -= 1
            raise RecursionError
        try:
            return self._items(items, style)
        finally:
            self.depth -= 1

    def _items(self, items: list, style: _Style) -> Box:
        atoms: list[tuple[int | None, Box]] = []
        for item in items:
            if isinstance(item, StyleChange):
                style = _Style(_STYLES.index(item.style), style.cramped)
                continue
            if isinstance(item, Space):
                em = item.em if item.inline is None or style.level == 0 else item.inline
                atoms.append((None, _kern(em * self.size(style))))
                continue
            if isinstance(item, (Tab, NewRow, HLine, Infix)):
                continue
            kind, box = self.atom(item, style)
            atoms.append((kind, box))
        # A binary operator with nothing to join is ordinary: -x, (+1), a = -b.
        kinds = [kind for kind, _ in atoms]
        previous: int | None = None
        for index, kind in enumerate(kinds):
            if kind is None:
                continue
            if kind == BIN and (previous is None or kinds[previous] in {BIN, OP, REL, OPEN, PUNCT}):
                kinds[index] = ORD
            if kind in {REL, CLOSE, PUNCT} and previous is not None and kinds[previous] == BIN:
                kinds[previous] = ORD
            previous = index
        if previous is not None and kinds[previous] == BIN:
            kinds[previous] = ORD
        placed: list[tuple[Box, float]] = []
        last: int | None = None
        for (_, box), kind in zip(atoms, kinds, strict=True):
            kern = 0.0
            if kind is not None and last is not None:
                amount = _SPACING[last][kind]
                if amount > 0 or (amount < 0 and style.level < 2):
                    kern = _MU[abs(amount)] * self.size(style)
            if kind is not None and placed and placed[-1][0].single and placed[-1][0].italic > 0:
                # An italic letter leans into what follows -- a sign as much as a letter --
                # so it is given its italic correction (TeX's rule 17): f + b, not f+ b.
                kern += placed[-1][0].italic
            placed.append((box, kern))
            if kind is not None:
                last = kind
        alone = len(placed) == 1
        if len(placed) > 1 and placed[-1][0].single and placed[-1][0].italic > 0:
            # And at the end of a list, so a closing bracket clears it: \left| f \right|.
            placed.append((_kern(placed[-1][0].italic), 0.0))
        row = _row(placed)
        if alone:
            row.single = placed[0][0].single
            row.accent_at = placed[0][0].accent_at
        return row

    def atom(self, item: object, style: _Style) -> tuple[int, Box]:
        if isinstance(item, Sym):
            return item.kind, self.symbol(item, style)
        if isinstance(item, Text):
            return ORD, self.words(item, style)
        if isinstance(item, Group):
            return item.kind, self.items(item.items, style)
        if isinstance(item, Classed):
            return item.kind, self.items(item.body, style)
        if isinstance(item, Scripts):
            return self.scripts(item, style)
        if isinstance(item, Operator):
            return OP, self.operator(item, style)[0]
        if isinstance(item, Fraction):
            return INNER if item.left or item.right else ORD, self.fraction(item, style)
        if isinstance(item, Radical):
            return ORD, self.radical(item, style)
        if isinstance(item, Fenced):
            return INNER, self.fenced(item, style)
        if isinstance(item, Middle):
            return REL, self.delimiter(item.delimiter, 0.0, style)
        if isinstance(item, Big):
            # 1.2, 1.8, 2.4 or 3 ems, as TeX's: a maths font's variants of those sizes are
            # drawn a little under them (Latin Modern Math's 1.2 em bracket is 1.195 em,
            # Fira Math's 3 em one 2.96), and are what LuaTeX takes, not the next size up.
            target = 0.98 * (0.0, 1.2, 1.8, 2.4, 3.0)[item.size] * self.size(style)
            return item.kind, self.delimiter(item.delimiter, target, style, exact=True)
        if isinstance(item, Accent):
            return ORD, self.accent(item, style)
        if isinstance(item, Line):
            return ORD, self.line(item, style)
        if isinstance(item, Brace):
            return OP, self.brace(item, style)
        if isinstance(item, Arrow):
            return (REL if item.body is None else ORD), self.arrow(item, style)
        if isinstance(item, Stack):
            return item.kind, self.stack(item, style)
        if isinstance(item, Array):
            return ORD if not (item.left or item.right) else INNER, self.array(item, style)
        if isinstance(item, Coloured):
            before = self.colour
            self.colour = item.colour
            try:
                return ORD, self.items(item.body, style)
            finally:
                self.colour = before
        if isinstance(item, Phantom):
            body = self.items(item.body, style)
            box = Box(
                body.width if item.width else 0.0,
                body.height if item.height else 0.0,
                body.depth if item.height else 0.0,
            )
            if item.shown:
                box.put(body, 0.0, 0.0)
            return ORD, box
        if isinstance(item, Boxed):
            return ORD, self.boxed(item, style)
        if isinstance(item, Negated):
            kind, body = self.atom(item.body, style) if item.body is not None else (ORD, Box())
            return kind, self.negated(body, style)
        if isinstance(item, Mistake):
            before = self.colour
            self.colour = ERROR_COLOUR
            try:
                return ORD, self.words(Text(item.words, "rm"), style)
            finally:
                self.colour = before
        if isinstance(item, Space):
            return ORD, _kern(item.em * self.size(style))
        if isinstance(item, Array):
            return ORD, self.array(item, style)
        return ORD, Box()

    # -- scripts (TeX's rule 18) --

    def scripts(self, item: Scripts, style: _Style) -> tuple[int, Box]:
        base_item = item.base
        if isinstance(base_item, Operator):
            limits = base_item.limits
            if limits is None:
                limits = style.level == 0 and (base_item.named or base_item.symbol not in INTEGRALS)
            if limits:
                return OP, self.limits(base_item, item.sup, item.sub, style)
        if isinstance(base_item, Brace):
            kind, base = OP, self.brace(base_item, style)
        elif base_item is None:
            kind, base = ORD, Box()
        else:
            kind, base = self.atom(base_item, style)
        if item.prime:
            return kind, self.primed(base, item, style)
        return kind, self.attach(
            base, item.sup, item.sub, style, operator=isinstance(base_item, Operator)
        )

    def primed(self, base: Box, item: Scripts, style: _Style) -> Box:
        """A base with primes: the primes after it at its size (a maths font's prime is
        raised already), a superscript after them, a subscript under them."""

        mark = self.atom(Sym(item.prime), style)[1]
        x = base.width + base.italic
        marked = Box(x + mark.width, max(base.height, mark.height), max(base.depth, mark.depth))
        marked.put(base, 0.0, 0.0)
        marked.put(mark, x, 0.0)
        box = self.attach(marked, item.sup, None, style) if item.sup else marked
        if item.sub is not None:
            sub = self.items(item.sub, style.down())
            v = max(
                self.c("SUBSCRIPT_SHIFT_DOWN", style),
                sub.height - self.c("SUBSCRIPT_TOP_MAX", style),
                0.0 if base.single
                else base.depth + self.c("SUBSCRIPT_BASELINE_DROP_MIN", style.up()),
            )
            box.put(sub, base.width, -v)
            box.depth = max(box.depth, v + sub.depth)
            box.width = max(box.width, base.width + sub.width + self.c("SPACE_AFTER_SCRIPT", style))
        return box

    def attach(
        self,
        base: Box,
        sup_items: list | None,
        sub_items: list | None,
        style: _Style,
        *,
        operator: bool = False,
    ) -> Box:
        sup = self.items(sup_items, style.up()) if sup_items is not None else None
        sub = self.items(sub_items, style.down()) if sub_items is not None else None
        script = style.up()
        if base.single:
            u = v = 0.0
        else:
            u = base.height - self.c("SUPERSCRIPT_BASELINE_DROP_MAX", script)
            v = base.depth + self.c("SUBSCRIPT_BASELINE_DROP_MIN", script)
        italic = base.italic
        if sup is not None:
            shift = self.c(
                "SUPERSCRIPT_SHIFT_UP_CRAMPED" if style.cramped else "SUPERSCRIPT_SHIFT_UP", style
            )
            u = max(u, shift, sup.depth + self.c("SUPERSCRIPT_BOTTOM_MIN", style))
        if sub is not None:
            if sup is None:
                v = max(
                    v,
                    self.c("SUBSCRIPT_SHIFT_DOWN", style),
                    sub.height - self.c("SUBSCRIPT_TOP_MAX", style),
                )
            else:
                v = max(v, self.c("SUBSCRIPT_SHIFT_DOWN", style))
                gap = (u - sup.depth) - (sub.height - v)
                least = self.c("SUB_SUPERSCRIPT_GAP_MIN", style)
                if gap < least:
                    v += least - gap
                    lift = self.c("SUPERSCRIPT_BOTTOM_MAX_WITH_SUBSCRIPT", style) - (u - sup.depth)
                    if lift > 0:
                        u += lift
                        v -= lift
        after = self.c("SPACE_AFTER_SCRIPT", style)
        box = Box(base.width, base.height, base.depth)
        box.put(base, 0.0, 0.0)
        right = base.width
        # A letter's superscript clears its lean (its italic correction); a big
        # operator's subscript tucks under it instead (MathML Core's rule).
        if sup is not None:
            x = base.width + (0.0 if operator else italic)
            box.put(sup, x, u)
            box.height = max(box.height, u + sup.height)
            box.depth = max(box.depth, sup.depth - u)
            right = max(right, x + sup.width)
        if sub is not None:
            x = base.width - (italic if operator else 0.0)
            box.put(sub, x, -v)
            box.depth = max(box.depth, v + sub.depth)
            box.height = max(box.height, sub.height - v)
            right = max(right, x + sub.width)
        box.width = right + after
        return box

    # -- operators (rules 13, 13a) --

    def operator(self, item: Operator, style: _Style) -> tuple[Box, bool]:
        size = self.size(style)
        if item.body is not None:
            box = self.items(item.body, style)
            box.single = False
            return box, True
        if item.named:
            if not item.symbol:
                return Box(), False
            box = self.words(Text(item.symbol, "rm"), style)
            box.single = False
            return box, True
        face, gid = self.fonts.maths_for(item.symbol)
        if gid is None:
            return self.symbol(Sym(item.symbol, OP), style), False
        if style.level == 0:
            least = self.fonts.constant("DISPLAY_OPERATOR_MIN_HEIGHT")
            for variant in face.hb.get_math_glyph_variants(gid, "ttb"):
                gid = variant.glyph
                if variant.advance / face.upem >= least:
                    break
        box = self.glyph(face, gid, size)
        axis = self.c("AXIS_HEIGHT", style)
        shift = axis - (box.height - box.depth) / 2.0
        centred = box.raised(shift)
        centred.italic = box.italic
        # Centred on the axis it is a box, not a character: its scripts go by its ink (rule 13).
        centred.single = False
        return centred, False

    def limits(
        self, item: Operator, sup_items: list | None, sub_items: list | None, style: _Style
    ) -> Box:
        nucleus, _ = self.operator(item, style)
        sup = self.items(sup_items, style.up()) if sup_items is not None else None
        sub = self.items(sub_items, style.down()) if sub_items is not None else None
        italic = 0.0 if item.named else nucleus.italic
        width = max(nucleus.width, sup.width if sup else 0.0, sub.width if sub else 0.0)
        box = Box(width, nucleus.height, nucleus.depth)
        box.put(nucleus, (width - nucleus.width) / 2.0, 0.0)
        if sup is not None:
            rise = nucleus.height + max(
                self.c("UPPER_LIMIT_GAP_MIN", style) + sup.depth,
                self.c("UPPER_LIMIT_BASELINE_RISE_MIN", style),
            )
            box.put(sup, (width - sup.width) / 2.0 + italic / 2.0, rise)
            box.height = rise + sup.height
        if sub is not None:
            drop = nucleus.depth + max(
                self.c("LOWER_LIMIT_GAP_MIN", style) + sub.height,
                self.c("LOWER_LIMIT_BASELINE_DROP_MIN", style),
            )
            box.put(sub, (width - sub.width) / 2.0 - italic / 2.0, -drop)
            box.depth = drop + sub.depth
        return box

    # -- fractions (rule 15) --

    def fraction(self, item: Fraction, style: _Style) -> Box:
        if item.style is not None:
            style = _Style(_STYLES.index(item.style), style.cramped)
        display = style.level == 0
        numerator = self.items(item.numerator, style.numerator())
        denominator = self.items(item.denominator, style.denominator())
        axis = self.c("AXIS_HEIGHT", style)
        if item.rule:
            thickness = self.c("FRACTION_RULE_THICKNESS", style)
            if display:
                up = self.c("FRACTION_NUMERATOR_DISPLAY_STYLE_SHIFT_UP", style)
                down = self.c("FRACTION_DENOMINATOR_DISPLAY_STYLE_SHIFT_DOWN", style)
                above = self.c("FRACTION_NUM_DISPLAY_STYLE_GAP_MIN", style)
                below = self.c("FRACTION_DENOM_DISPLAY_STYLE_GAP_MIN", style)
            else:
                up = self.c("FRACTION_NUMERATOR_SHIFT_UP", style)
                down = self.c("FRACTION_DENOMINATOR_SHIFT_DOWN", style)
                above = self.c("FRACTION_NUMERATOR_GAP_MIN", style)
                below = self.c("FRACTION_DENOMINATOR_GAP_MIN", style)
            up = max(up, axis + thickness / 2.0 + above + numerator.depth)
            down = max(down, denominator.height + below - (axis - thickness / 2.0))
        else:
            thickness = 0.0
            if display:
                up = self.c("STACK_TOP_DISPLAY_STYLE_SHIFT_UP", style)
                down = self.c("STACK_BOTTOM_DISPLAY_STYLE_SHIFT_DOWN", style)
                least = self.c("STACK_DISPLAY_STYLE_GAP_MIN", style)
            else:
                up = self.c("STACK_TOP_SHIFT_UP", style)
                down = self.c("STACK_BOTTOM_SHIFT_DOWN", style)
                least = self.c("STACK_GAP_MIN", style)
            gap = (up - numerator.depth) - (denominator.height - down)
            if gap < least:
                up += (least - gap) / 2.0
                down += (least - gap) / 2.0
        # TeX's null delimiters: a little room either side of the rule.
        pad = 0.12 * self.size(style)
        inner = max(numerator.width, denominator.width)
        width = inner + 2 * pad
        box = Box(width, up + numerator.height, down + denominator.depth)
        box.put(numerator, (width - numerator.width) / 2.0, up)
        box.put(denominator, (width - denominator.width) / 2.0, -down)
        if thickness:
            box.put(_rule(inner, thickness, axis - thickness / 2.0, self.colour), pad, 0.0)
        if item.left or item.right:
            return self.fence(item.left, box, item.right, style)
        return box

    # -- radicals (rule 11) --

    def radical(self, item: Radical, style: _Style) -> Box:
        body = self.items(item.body, style.cramp())
        display = style.level == 0
        gap = self.c(
            "RADICAL_DISPLAY_STYLE_VERTICAL_GAP" if display else "RADICAL_VERTICAL_GAP", style
        )
        thickness = self.c("RADICAL_RULE_THICKNESS", style)
        extra = self.c("RADICAL_EXTRA_ASCENDER", style)
        inner = body.height + body.depth
        sign = self.stretched("√", inner + gap + thickness, style, vertical=True)
        excess = sign.height + sign.depth - (inner + gap + thickness)
        if excess > 0:
            # A radical taller than its body is needs: the room goes above the body.
            gap += excess / 2.0
        top = body.height + gap + thickness
        # The sign's top meets the rule's top.
        sign_box = sign.raised(top - sign.height)
        box = Box()
        x = 0.0
        if item.degree:
            degree = self.items(item.degree, _Style(3, False))
            before = self.fonts.constant("RADICAL_KERN_BEFORE_DEGREE") * self.size(style)
            after = self.fonts.constant("RADICAL_KERN_AFTER_DEGREE") * self.size(style)
            raise_by = self.fonts.constant("RADICAL_DEGREE_BOTTOM_RAISE_PERCENT") / 100.0
            bottom = -sign_box.depth + raise_by * (sign_box.height + sign_box.depth)
            box.put(degree, before, bottom + degree.depth)
            box.height = max(box.height, bottom + degree.depth + degree.height)
            x = max(0.0, before + degree.width + after)
        box.put(sign_box, x, 0.0)
        x += sign_box.width
        box.put(_rule(body.width, thickness, top - thickness, self.colour), x, 0.0)
        box.put(body, x, 0.0)
        box.width = x + body.width
        box.height = max(box.height, top + extra)
        box.depth = max(body.depth, sign_box.depth)
        return box

    # -- delimiters --

    def stretched(self, char: str, target: float, style: _Style, *, vertical: bool) -> Box:
        """``char`` from the maths font at least ``target`` points long (tall, or wide):
        a larger variant, or else one built from its parts."""

        face, gid = self.fonts.maths_for(char)
        size = self.size(style)
        if gid is None:
            box = self.symbol(Sym(char), style)
            return box
        direction = "ttb" if vertical else "ltr"
        chosen = gid
        for variant in face.hb.get_math_glyph_variants(gid, direction):
            chosen = variant.glyph
            if variant.advance / face.upem * size >= target:
                return self.glyph(face, chosen, size)
        parts, _ = face.hb.get_math_glyph_assembly(gid, direction)
        if not parts:
            return self.glyph(face, chosen, size)
        return self.assembly(face, parts, target, size, vertical)

    def assembly(self, face: Face, parts, target: float, size: float, vertical: bool) -> Box:
        overlap = (
            face.hb.get_math_min_connector_overlap("ttb" if vertical else "ltr") / face.upem * size
        )
        repeats = 0
        while True:
            sequence = []
            for part in parts:
                count = repeats if int(part.flags) & 1 else 1
                sequence += [part] * count
            lengths = [part.full_advance / face.upem * size for part in sequence]
            longest = sum(lengths) - overlap * max(0, len(sequence) - 1)
            if longest >= target or repeats > 60:
                break
            repeats += 1
        joints = max(1, len(sequence) - 1)
        spare = max(0.0, longest - target)
        overlaps = []
        for first, second in itertools.pairwise(sequence):
            allowed = (
                min(first.end_connector_length, second.start_connector_length) / face.upem * size
            )
            overlaps.append(min(allowed, overlap + spare / joints))
        box = Box()
        at = 0.0
        for index, part in enumerate(sequence):
            glyph = self.glyph(face, part.glyph, size)
            if vertical:
                # Parts run from the bottom up.
                box.put(glyph, 0.0, at)
                box.width = max(box.width, glyph.width)
                box.height = max(box.height, at + glyph.height)
                box.depth = max(box.depth, glyph.depth - at)
            else:
                box.put(glyph, at, 0.0)
                box.height = max(box.height, glyph.height)
                box.depth = max(box.depth, glyph.depth)
            at += part.full_advance / face.upem * size - (
                overlaps[index] if index < len(overlaps) else 0.0
            )
        if not vertical:
            box.width = at
        return box

    def delimiter(self, char: str, target: float, style: _Style, *, exact: bool = False) -> Box:
        """A delimiter at least ``target`` points tall, centred on the maths axis."""

        size = self.size(style)
        if not char:
            return _kern(0.12 * size)
        box = self.stretched(char, target, style, vertical=True)
        if not exact and target <= 0:
            box = self.symbol(Sym(char), style)
        axis = self.c("AXIS_HEIGHT", style)
        centred = box.raised(axis - (box.height - box.depth) / 2.0)
        centred.single = False
        return centred

    def reach(self, height: float, depth: float, style: _Style, *, whole: bool = False) -> float:
        """How tall brackets around a body of ``height`` and ``depth`` are: TeX's 90% of
        it, falling short by at most half an em -- or all of it (``whole``), for an array
        whose rules run to its top and foot and would stand out past shorter brackets."""

        axis = self.c("AXIS_HEIGHT", style)
        reach = max(height - axis, depth + axis)
        if whole:
            return 2 * reach
        return max(2 * reach * 0.901, 2 * reach - 0.5 * self.size(style))

    def fence(self, left: str, body: Box, right: str, style: _Style, *, whole: bool = False) -> Box:
        target = self.reach(body.height, body.depth, style, whole=whole)
        opening = self.delimiter(left, target, style)
        closing = self.delimiter(right, target, style)
        return _row([(opening, 0.0), (body, 0.0), (closing, 0.0)])

    def fenced(self, item: Fenced, style: _Style) -> Box:
        pieces: list[list] = [[]]
        middles: list[str] = []
        for thing in item.body:
            if isinstance(thing, Middle):
                middles.append(thing.delimiter)
                pieces.append([])
            else:
                pieces[-1].append(thing)
        whole = any(isinstance(thing, Array) and (thing.lines or thing.bars) for thing in item.body)
        if not middles:
            body = self.items(item.body, style)
            return self.fence(item.left, body, item.right, style, whole=whole)
        boxes = [self.items(piece, style) for piece in pieces]
        height = max(box.height for box in boxes)
        depth = max(box.depth for box in boxes)
        target = self.reach(height, depth, style, whole=whole)
        thick = _MU[3] * self.size(style)
        row: list[tuple[Box, float]] = [(self.delimiter(item.left, target, style), 0.0)]
        for index, box in enumerate(boxes):
            row.append((box, 0.0))
            if index < len(middles):
                row.append((self.delimiter(middles[index], target, style), thick))
                row.append((_kern(thick), 0.0))
        row.append((self.delimiter(item.right, target, style), 0.0))
        return _row(row)

    # -- accents and marks over and under --

    def accent(self, item: Accent, style: _Style) -> Box:
        body = self.items(item.body, style.cramp())
        face, gid = self.fonts.maths_for(item.mark)
        if gid is None:
            return body
        size = self.size(style)
        if item.wide or len(item.body) > 1 or not body.single:
            for variant in face.hb.get_math_glyph_variants(gid, "ltr"):
                extents = face.extents(variant.glyph)
                gid = variant.glyph
                if (extents[1] - extents[0]) * size >= body.width * 0.9:
                    break
        mark = self.glyph(face, gid, size)
        left, right, _, _ = face.extents(gid)
        attach = face.hb.get_math_glyph_top_accent_attachment(gid) / face.upem * size
        if not attach:
            attach = (left + right) / 2 * size
        centre = (
            body.accent_at if (body.single and body.accent_at is not None) else body.width / 2.0
        )
        base_height = self.c("ACCENT_BASE_HEIGHT", style)
        rise = max(0.0, body.height - base_height)
        box = Box(body.width, max(body.height, rise + mark.height), body.depth)
        box.put(body, 0.0, 0.0)
        box.put(mark, centre - attach, rise)
        box.italic = body.italic
        box.single = body.single
        box.accent_at = body.accent_at
        return box

    def line(self, item: Line, style: _Style) -> Box:
        body = self.items(item.body, style.cramp() if item.over else style)
        if item.over:
            gap = self.c("OVERBAR_VERTICAL_GAP", style)
            thickness = self.c("OVERBAR_RULE_THICKNESS", style)
            extra = self.c("OVERBAR_EXTRA_ASCENDER", style)
            box = Box(body.width, body.height + gap + thickness + extra, body.depth)
            box.put(body, 0.0, 0.0)
            box.put(_rule(body.width, thickness, body.height + gap, self.colour), 0.0, 0.0)
            return box
        gap = self.c("UNDERBAR_VERTICAL_GAP", style)
        thickness = self.c("UNDERBAR_RULE_THICKNESS", style)
        extra = self.c("UNDERBAR_EXTRA_DESCENDER", style)
        box = Box(body.width, body.height, body.depth + gap + thickness + extra)
        box.put(body, 0.0, 0.0)
        box.put(
            _rule(body.width, thickness, -(body.depth + gap + thickness), self.colour), 0.0, 0.0
        )
        return box

    def brace(self, item: Brace, style: _Style) -> Box:
        body = self.items(item.body, style)
        char = "⏞" if item.over else "⏟"
        brace = self.stretched(char, body.width, style, vertical=False)
        label = (
            self.items(item.label, style.up() if item.over else style.down())
            if item.label
            else None
        )
        width = max(body.width, brace.width, label.width if label else 0.0)
        box = Box(width, body.height, body.depth)
        box.put(body, (width - body.width) / 2.0, 0.0)
        if item.over:
            gap = self.c("STRETCH_STACK_GAP_BELOW_MIN", style)
            bottom = body.height + gap
            box.put(brace, (width - brace.width) / 2.0, bottom + brace.depth)
            box.height = bottom + brace.depth + brace.height
            if label is not None:
                rise = box.height + self.c("STRETCH_STACK_GAP_ABOVE_MIN", style) * 0.5 + label.depth
                box.put(label, (width - label.width) / 2.0, rise)
                box.height = rise + label.height
        else:
            gap = self.c("STRETCH_STACK_GAP_ABOVE_MIN", style)
            top = -(body.depth + gap)
            box.put(brace, (width - brace.width) / 2.0, top - brace.height)
            box.depth = -(top - brace.height - brace.depth)
            if label is not None:
                drop = box.depth + self.c("STRETCH_STACK_GAP_BELOW_MIN", style) * 0.5 + label.height
                box.put(label, (width - label.width) / 2.0, -drop)
                box.depth = drop + label.depth
        return box

    def arrow(self, item: Arrow, style: _Style) -> Box:
        size = self.size(style)
        if item.body is not None:
            body = self.items(item.body, style.cramp())
            arrow = self.stretched(item.char, body.width, style, vertical=False)
            if arrow.width < body.width * 0.9:
                arrow = self.drawn_arrow(item.char, body.width, style)
            width = max(body.width, arrow.width)
            box = Box(width, body.height, body.depth)
            box.put(body, (width - body.width) / 2.0, 0.0)
            gap = 0.08 * size
            if item.below:
                top = -(body.depth + gap)
                box.put(arrow, (width - arrow.width) / 2.0, top - arrow.height)
                box.depth = -(top - arrow.height - arrow.depth)
            else:
                bottom = body.height + gap
                box.put(arrow, (width - arrow.width) / 2.0, bottom + arrow.depth)
                box.height = bottom + arrow.depth + arrow.height
            return box
        over = self.items(item.over or [], style.up())
        under = self.items(item.under, style.down()) if item.under else None
        pad = 0.5 * size
        need = max(over.width, under.width if under else 0.0) + pad
        arrow = self.stretched(item.char, need, style, vertical=False)
        if arrow.width < need * 0.95:
            arrow = self.drawn_arrow(item.char, need, style)
        width = max(arrow.width, need)
        box = Box(width, arrow.height, arrow.depth)
        box.put(arrow, (width - arrow.width) / 2.0, 0.0)
        gap = 0.1 * size
        rise = arrow.height + gap + over.depth
        box.put(over, (width - over.width) / 2.0, rise)
        box.height = rise + over.height
        if under is not None:
            drop = arrow.depth + gap + under.height
            box.put(under, (width - under.width) / 2.0, -drop)
            box.depth = drop + under.depth
        return box

    def drawn_arrow(self, char: str, width: float, style: _Style) -> Box:
        """An arrow the maths font cannot stretch: its head, and a shaft ruled to length."""

        size = self.size(style)
        head = self.maths_glyph(char, style)
        if head is None:
            return Box(width)
        axis = self.c("AXIS_HEIGHT", style)
        thickness = self.c("FRACTION_RULE_THICKNESS", style) * 1.1
        box = Box(max(width, head.width), head.height, head.depth)
        shaft = _rule(box.width - head.width, thickness, axis - thickness / 2, self.colour)
        if char == "↔":
            left, right = self.maths_glyph("←", style), self.maths_glyph("→", style)
            if left is not None and right is not None:
                box.put(left, 0.0, 0.0)
                box.put(shaft, head.width * 0.5, 0.0)
                box.put(right, box.width - right.width, 0.0)
                return box
        if char in "←⇐":
            box.put(head, 0.0, 0.0)
            box.put(shaft, head.width * 0.5, 0.0)
        else:
            box.put(shaft, head.width * 0.5, 0.0)
            box.put(head, box.width - head.width, 0.0)
        del size
        return box

    def stack(self, item: Stack, style: _Style) -> Box:
        base = self.items(item.base, style)
        over = self.items(item.over, style.up()) if item.over is not None else None
        under = self.items(item.under, style.down()) if item.under is not None else None
        width = max(base.width, over.width if over else 0.0, under.width if under else 0.0)
        box = Box(width, base.height, base.depth)
        box.put(base, (width - base.width) / 2.0, 0.0)
        gap = 0.12 * self.size(style)
        if over is not None:
            rise = base.height + gap + over.depth
            box.put(over, (width - over.width) / 2.0, rise)
            box.height = rise + over.height
        if under is not None:
            drop = base.depth + gap + under.height
            box.put(under, (width - under.width) / 2.0, -drop)
            box.depth = drop + under.depth
        return box

    # -- arrays --

    def array(self, item: Array, style: _Style) -> Box:
        cell_style = _Style(_STYLES.index(item.style), False)
        if item.style == "D" and style.level > 0 and item.kind in {"aligned", "gathered"}:
            cell_style = _Style(0, False)
        if item.style == "T" and style.level >= 2:
            cell_style = style
        size = self.size(cell_style)
        rows = item.rows or [[[]]]
        count = max(len(row) for row in rows)
        aligned = item.kind == "aligned"
        grid: list[list[Box]] = []
        for row in rows:
            cells = []
            for index in range(count):
                content = row[index] if index < len(row) else []
                if aligned and index % 2 == 1:
                    # The right half of an aligned pair starts after an empty atom, so
                    # "&= b" spaces its relation as TeX does.
                    content = [Group([]), *content]
                cells.append(self.items(content, cell_style))
            grid.append(cells)
        widths = [max(cells[index].width for cells in grid) for index in range(count)]
        strut_height, strut_depth = 0.7 * 1.2 * size, 0.3 * 1.2 * size
        if item.kind == "small":
            strut_height, strut_depth = 0.7 * size, 0.3 * size
        heights = [max([strut_height, *(cell.height for cell in cells)]) for cells in grid]
        depths = [max([strut_depth, *(cell.depth for cell in cells)]) for cells in grid]
        under = self.c("UNDERBAR_VERTICAL_GAP", cell_style)
        over = self.c("OVERBAR_VERTICAL_GAP", cell_style)
        for line in item.lines:
            # A rule keeps the gap a bar over or under keeps from the ink beside it,
            # where a row's scripts reach past its strut (as a maths font's may).
            if 0 < line <= len(grid):
                ink = max(cell.depth for cell in grid[line - 1])
                depths[line - 1] = max(depths[line - 1], ink + under)
            if line < len(grid):
                heights[line] = max(heights[line], max(cell.height for cell in grid[line]) + over)
        jot = 0.3 * size if item.kind in {"aligned", "gathered"} else 0.0
        if item.kind == "cases":
            jot = 0.1 * size
        gaps: list[float] = []
        for index in range(count):
            if index == count - 1:
                gaps.append(0.0)
            elif aligned:
                gaps.append(0.0 if index % 2 == 0 else 2.0 * size)
            elif item.kind == "cases":
                gaps.append(1.0 * size)
            elif item.kind == "small":
                gaps.append(0.5 * size)
            elif item.kind == "array":
                gaps.append(1.0 * size)
            else:
                gaps.append(1.0 * size)
        edge = 0.5 * size if item.kind == "array" else 0.0
        columns = (item.columns or "c").replace(" ", "")
        thickness = self.c("FRACTION_RULE_THICKNESS", cell_style)
        box = Box()
        # Rows hang from the top down. A rule (\hline) takes room of its own between
        # the depth of the row above and the height of the row below, as LaTeX's array
        # sets it, so it never strikes through a row's scripts.
        bottom = 0.0
        rules: list[float] = []
        for index, cells in enumerate(grid):
            gap = jot if index > 0 else 0.0
            if index in item.lines:
                rules.append(bottom - gap / 2.0 - thickness)
                gap += thickness
            y = bottom - gap - heights[index]
            bottom = y - depths[index]
            x = edge
            for column, cell in enumerate(cells):
                align = (
                    columns[column]
                    if column < len(columns)
                    else (("r" if column % 2 == 0 else "l") if aligned else columns[-1])
                )
                if aligned:
                    align = "r" if column % 2 == 0 else "l"
                offset = {"l": 0.0, "r": widths[column] - cell.width}.get(
                    align, (widths[column] - cell.width) / 2.0
                )
                box.put(cell, x + offset, y)
                x += widths[column] + gaps[column]
        if len(grid) in item.lines:
            rules.append(bottom - thickness)
            bottom -= thickness
        width = sum(widths) + sum(gaps) + 2 * edge
        box.width = width
        for level in rules:
            box.put(_rule(width, thickness, level, self.colour), 0.0, 0.0)
        for bar in item.bars:
            x = (
                edge
                + sum(widths[:bar])
                + sum(gaps[:bar])
                - (gaps[bar - 1] / 2.0 if bar > 0 else edge / 2.0)
            )
            if bar >= count:
                x = width - edge / 2.0
            # From the top of the array to its foot, meeting the rules across it.
            box.put(_rule(thickness, -bottom, bottom, self.colour), x - thickness / 2.0, 0.0)
        # Centre the whole on the maths axis.
        axis = self.c("AXIS_HEIGHT", style)
        box.depth = -bottom
        centred = box.raised(axis - bottom / 2.0)
        if item.left or item.right:
            ruled = bool(item.lines or item.bars)
            return self.fence(item.left, centred, item.right, style, whole=ruled)
        return centred

    # -- the rest --

    def boxed(self, item: Boxed, style: _Style) -> Box:
        body = self.items(item.body, style)
        size = self.size(style)
        pad = 0.2 * size
        thickness = 0.04 * size
        width = body.width + 2 * pad
        box = Box(width, body.height + pad, body.depth + pad)
        box.put(body, pad, 0.0)
        bottom = -(body.depth + pad)
        box.put(_rule(width, thickness, bottom, self.colour), 0.0, 0.0)
        box.put(_rule(width, thickness, body.height + pad - thickness, self.colour), 0.0, 0.0)
        box.put(_rule(thickness, body.height + body.depth + 2 * pad, bottom, self.colour), 0.0, 0.0)
        box.put(
            _rule(thickness, body.height + body.depth + 2 * pad, bottom, self.colour),
            width - thickness,
            0.0,
        )
        return box

    def negated(self, body: Box, style: _Style) -> Box:
        slash = self.maths_glyph("/", style)
        if slash is None:
            return body
        box = Box(body.width, max(body.height, slash.height), max(body.depth, slash.depth))
        box.put(body, 0.0, 0.0)
        box.put(slash, (body.width - slash.width) / 2.0, 0.0)
        return box


_SLANT = math.tan(math.radians(12.0))
_WORDS_OWN = frozenset("+−=<>±×÷()[]|/!,;:.")
"""Signs set in the typography's face rather than the maths font's."""


def alphabet(char: str, font: str | None) -> str:
    if font == "bf" and char in _GREEK_BOLD:
        return _GREEK_BOLD[char]
    if font == "bi" and char in _GREEK_BOLD_ITALIC:
        return _GREEK_BOLD_ITALIC[char]
    if font == "bi" and char.isascii() and char.isalpha():
        start, small, _, _ = _ALPHABETS["bi"]
        return chr(
            (start if char.isupper() else small)
            + ord(char.upper() if char.isupper() else char)
            - ord("A" if char.isupper() else "a")
        )
    table = _ALPHABETS.get(font or "")
    if table is None:
        return char
    capital, small, digit, exceptions = table
    if char in exceptions:
        return exceptions[char]
    if "A" <= char <= "Z":
        return chr(capital + ord(char) - ord("A"))
    if "a" <= char <= "z" and small is not None:
        if font in {"cal", "scr"}:
            return char
        return chr(small + ord(char) - ord("a"))
    if "0" <= char <= "9" and digit is not None:
        return chr(digit + ord(char) - ord("0"))
    return char


# -- the whole ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Typeset:
    """A formula laid out: its box (in points, y up) and what could not be read."""

    box: Box
    problems: tuple[str, ...]
    source: str

    @property
    def width(self) -> float:
        return self.box.width

    @property
    def height(self) -> float:
        return self.box.height

    @property
    def depth(self) -> float:
        return self.box.depth


@lru_cache(maxsize=4096)
def typeset(
    source: str,
    typography: TypographyStyle,
    size: float,
    *,
    display: bool = False,
    weight: int = 400,
) -> Typeset:
    """``source`` (LaTeX maths, without its ``$``) laid out at ``size`` points, in
    display style (a formula on its own line) or text style (one within words)."""

    display = display or source.lstrip().startswith("\\displaystyle")
    items, problems = parse(source)
    items = _implicit_rows(items, display)
    layout = _Layout(Fonts(typography), size, weight)
    try:
        box = layout.items(items, _Style(0 if display else 1))
    except RecursionError:
        box = layout.items([Mistake(source[:40] + ("…" if len(source) > 40 else ""))], _Style(1))
        problems = [*problems, "the formula is nested too deeply to set"]
    return Typeset(box, tuple(problems), source)


def _implicit_rows(items: list, display: bool) -> list:
    """Rows (``\\\\``) and alignment (``&``) written without an environment: in display,
    the lines of an aligned formula; within words, the words as they are."""

    if not any(isinstance(item, (NewRow, Tab)) for item in items):
        return items
    rows, lines = _rows_and_lines(items)
    aligned = any(len(row) > 1 for row in rows)
    return [
        Array(
            rows,
            "rl" if aligned else "c",
            style="D" if display else "T",
            kind="aligned" if aligned else "gathered",
            lines=frozenset(lines),
        )
    ]


@lru_cache(maxsize=1024)
def breakable(source: str) -> tuple[str, ...]:
    """``source`` cut where TeX may break a line of maths: after each relation and
    operator at its top level (not inside braces, brackets that grow, or an
    environment), which ends its line. A piece ending in a sign ends with an empty
    atom too, so set side by side the pieces space their signs as the whole would."""

    tokens = _tokens(source)
    pieces: list[str] = [""]
    depth = 0
    for index, token in enumerate(tokens):
        raw = ("\\" + token.value) if token.kind == "command" else token.value
        if token.kind == "char" and token.value == "{":
            depth += 1
        elif token.kind == "char" and token.value == "}":
            depth = max(0, depth - 1)
        elif token.kind == "command" and token.value in {"left", "begin"}:
            depth += 1
        elif token.kind == "command" and token.value in {"right", "end"}:
            depth = max(0, depth - 1)
        sign = (token.kind == "char" and token.value in "=<>+-") or (
            token.kind == "command" and (token.value in RELATION or token.value in BINARY)
        )
        previous = next((t for t in reversed(tokens[:index]) if t.kind != "space"), None)
        scripted = previous is not None and previous.kind == "char" and previous.value in "^_"
        if depth == 0 and sign and not scripted and pieces[-1].strip():
            pieces[-1] += raw + "{}"
            pieces.append("")
            continue
        pieces[-1] += raw
    return tuple(piece for piece in pieces if piece.strip())


@lru_cache(maxsize=4096)
def problems_in(source: str) -> tuple[str, ...]:
    """What could not be read in ``source``, in words (nothing when it reads)."""

    return tuple(parse(source)[1])


# -- drawing -----------------------------------------------------------------------------


@lru_cache(maxsize=8192)
def _scaled_path(face: Face, gid: int, size: float, slant: bool) -> str:
    """A glyph's outline at ``size`` points, SVG's way up (y down), its origin at 0."""

    scale = size / face.upem
    outline = face.path(gid)
    shear = _SLANT if slant else 0.0

    def point(match: re.Match[str]) -> str:
        x, y = float(match.group(1)), float(match.group(2))
        return f"{_n((x + y * shear) * scale)} {_n(-y * scale)}"

    return re.sub(r"(-?[\d.]+) (-?[\d.]+)", point, outline)


def _n(value: float) -> str:
    rounded = round(value, 2)
    if rounded == 0:
        return "0"
    return f"{rounded:g}"


def draw(
    parent: ET.Element,
    formula: Typeset,
    x: float,
    y: float,
    *,
    colour: Callable[[str], tuple[str | None, str | None]] | None = None,
    attributes: dict[str, str] | None = None,
) -> ET.Element:
    """``formula`` drawn into ``parent`` with its baseline's left end at ``(x, y)``.

    The group names its source (``data-flexo-math``) for whoever reads the SVG
    again. ``colour`` turns a colour the formula names (``\\color{accent}``) into a
    fill and the palette role that painted it; the group's own fill is ``attributes``'.
    """

    group = element(
        parent,
        "g",
        **{
            "class": "flexo-math",
            "transform": f"translate({number(x)} {number(y)})",
            "data__flexo__math": formula.source,
            "aria__label": formula.source,
            "role": "img",
            **(attributes or {}),
        },
    )
    for ox, oy, item in formula.box.items:
        paint: dict[str, str | None] = {}
        if item.colour:
            fill, role = colour(item.colour) if colour else (item.colour, None)
            paint = {"fill": fill, "data__flexo__fill": role}
        if isinstance(item, GlyphItem):
            d = _scaled_path(item.face, item.gid, item.size, item.slant)
            if d:
                element(group, "path", d=d, transform=f"translate({_n(ox)} {_n(-oy)})", **paint)
        else:
            element(
                group,
                "rect",
                x=_n(ox),
                y=_n(-(oy + item.height)),
                width=_n(item.width),
                height=_n(item.height),
                **paint,
            )
    return group
