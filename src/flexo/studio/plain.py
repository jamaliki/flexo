"""What went wrong, in words: an error as a studio page shows it, never in Python's own.

A document a person writes by hand is often not what the code reading it expects (a list
where settings go, words where a number goes), and the code then fails in its own terms:
``'int' object has no attribute 'get'``. ``explain`` says instead what was found where.
"""

from __future__ import annotations

import json
import re

import yaml

from flexo.diagnostics import FlexoError

KINDS = {
    "dict": "a set of settings",
    "CommentedMap": "a set of settings",
    "list": "a list",
    "CommentedSeq": "a list",
    "tuple": "a list",
    "str": "words",
    "SingleQuotedScalarString": "words",
    "DoubleQuotedScalarString": "words",
    "int": "a number",
    "float": "a number",
    "bool": "yes or no",
    "NoneType": "nothing",
}


def explain(error: BaseException, where: str = "") -> str:
    """``error`` as a person reads it, with ``where`` (a place in the document) first."""

    said = _said(error)
    return f"{where}: {said}" if where and not said.startswith(where) else said


def _said(error: BaseException) -> str:
    if isinstance(error, FlexoError):
        return (
            "; ".join(
                item.message + (f" ({item.hint})" if item.hint else "")
                for item in error.diagnostics
            )
            or "the document does not read"
        )
    if isinstance(error, yaml.YAMLError):
        mark = getattr(error, "problem_mark", None)
        problem = getattr(error, "problem", None) or "it is not written as YAML expects"
        return f"line {mark.line + 1}: {problem}" if mark else problem
    if isinstance(error, json.JSONDecodeError):
        return f"line {error.lineno}: {error.msg.lower()}"
    if isinstance(error, UnicodeDecodeError):
        return "the file is not text (or not in UTF-8)"
    if isinstance(error, FileNotFoundError):
        name = error.filename or (str(error.args[0]) if error.args else "")
        return f"there is no file {name}".strip() if error.filename else _plain(str(error))
    if isinstance(error, PermissionError):
        return (
            f"not allowed: {_plain(str(error))}"
            if not error.strerror
            else "the file may not be read or written"
        )
    if isinstance(error, OSError):
        return (error.strerror or "the file could not be read or written").lower()
    if isinstance(error, MemoryError):
        return "it is too large to draw"
    if isinstance(error, RecursionError):
        return "it is nested too deeply to read"
    if isinstance(error, KeyError):
        key = error.args[0] if error.args else "something"
        return f"{key} is missing" if isinstance(key, str) else "something it needs is missing"
    if isinstance(error, IndexError):
        return "a list is shorter than it needs to be"
    if isinstance(error, (AttributeError, TypeError, ValueError)):
        return _plain(str(error))
    return _plain(str(error)) or "something went wrong (the log has the details)"


# Python's own ways of saying a document is not the shape expected, and what each means.
SHAPES = [
    (
        r"'(\w+)' object has no attribute '(?:get|items|keys|values)'",
        "{kind} is written where settings belong",
    ),
    (r"'(\w+)' object is not iterable", "{kind} is written where a list belongs"),
    (r"'(\w+)' object is not subscriptable", "{kind} is written where a list or settings belong"),
    (r"'(\w+)' object has no attribute", "{kind} is written where something else belongs"),
    (r"string indices must be integers", "words are written where settings belong"),
    (r"unhashable type: '(\w+)'", "{kind} is written where a single value belongs"),
    (
        r"(?:float|int)\(\) argument must be a string or a (?:real )?number, not '(\w+)'",
        "a number is wanted, not {kind}",
    ),
    (r"could not convert string to float: '(.*)'", 'a number is wanted, not "{raw}"'),
    (r"invalid literal for int\(\) with base \d+: '(.*)'", 'a whole number is wanted, not "{raw}"'),
    (r"unsupported operand type", "a number is wanted where something else is written"),
    (
        r"takes \d+ positional arguments? but \d+ (?:was|were) given",
        "it is given more than it takes",
    ),
    (r"missing \d+ required positional argument", "it is given less than it needs"),
    (r"'(\w+)' object is not callable", "{kind} is written where something to run belongs"),
]


def _plain(text: str) -> str:
    text = re.sub(r"^(?:\w+Error|FlexoError): ", "", text.strip())
    # flexo's own error lines (``error: schema.invalid [edge.3]: …``), perhaps inside another's.
    text = re.sub(r"(?m)(?:^|(?<=: ))error: [\w.-]+(?: \[[^\]\n]*\])?: ", "", text)
    for pattern, said in SHAPES:
        found = re.search(pattern, text)
        if found:
            raw = found.group(1) if found.groups() else ""
            return said.format(kind=_kind(raw), raw=raw)
    # A message written for people may still name one of Python's types, quoted or not.
    text = re.sub(
        r"'(dict|list|str|int|float|bool|tuple|NoneType)'",
        lambda match: KINDS.get(match.group(1), match.group(1)), text,
    )
    return re.sub(
        r"\b(NoneType|CommentedSeq|CommentedMap|SingleQuotedScalarString|DoubleQuotedScalarString)\b",
        lambda match: KINDS.get(match.group(1), match.group(1)), text,
    )


def _kind(name: str) -> str:
    return KINDS.get(name, "something else")
