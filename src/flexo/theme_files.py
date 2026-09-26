"""Themes and palettes of your own, written as files.

A lab, a journal, or a talk has a look: its type, its colours, how heavy its
lines are. Written once as a YAML (or JSON) file, it is a theme like any other:

```yaml
theme:
  name: lab
  base: paper                  # start from a built-in theme; everything is optional
  description: Our group's figures.
  font: Helvetica              # any family Flexo can find
  type: {size: 7.5pt, label_weight: 400}
  palette: ["#1d4e89", "#f26419", "#2a9d8f", "#e9c46a"]
  page: {ink: "#1b1b1b", connector: "#333333"}
  tones: {rule: tinted, fill_lightness: 0.93}
  style: {corner_radius: 2pt, stroke_width: 0.6pt, arrow_shape: latex}
  conventions: {branch: dot}
  sketch: {roughness: 0.3}     # or leave out: drawn ruled
  background: false
```

``Figure(theme="lab.yaml")`` uses the file directly; ``flexo.register_theme``
makes it available by its name (``theme="lab"``); and every file in a directory
named by ``FLEXO_THEME_PATH`` is registered on first use, so a lab sets the
variable once. ``flexo theme paper`` prints any theme -- built in or
registered -- as a complete file to start from.

Palettes are the same: ``flexo.register_palette("Lab", ["#..", ...])``, a file
of named palettes (``palettes: {Lab: [...], Lab muted: [...]}``) registered with
``flexo.register_palette("palettes.yaml")``, or ``palettes:`` next to
``theme:`` in a theme file.
"""

from __future__ import annotations

import json
import os
import types
import typing
from collections.abc import Mapping, Sequence
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

import yaml

from flexo.conventions import Conventions, parse_conventions
from flexo.diagnostics import Diagnostic, FlexoError
from flexo.sketch import parse_sketch
from flexo.style import LayoutStyle, TypographyStyle, normalize_colour
from flexo.units import Length

SUFFIXES = (".yaml", ".yml", ".json")

CUSTOM_PALETTES: dict[str, tuple[str, ...]] = {}
"""Palettes registered by name, in the order they were given."""

_LOADED: dict[str, str] = {}
"""Theme files already registered: resolved path -> theme name."""

_ENVIRONMENT_LOADED = False

_STYLE_SKIPPED = frozenset(
    {"name", "typography", "conventions", "sketch", "widths", "background"}
)


def _fail(code: str, message: str, hint: str | None = None) -> FlexoError:
    return FlexoError(Diagnostic(code, message, hint=hint))


def _read(source: str | Path) -> dict[str, Any]:
    path = Path(source).expanduser()
    if not path.is_file():
        raise _fail("theme.file.missing", f'Theme file "{source}" does not exist.')
    text = path.read_text(encoding="utf-8")
    data = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(data, dict):
        raise _fail("theme.file.invalid", f'"{source}" is not a mapping of settings.')
    return data


def is_file_reference(value: str) -> bool:
    """Whether ``value`` names a theme or palette file rather than a registered name."""

    return value.strip().lower().endswith(SUFFIXES)


# -- values ---------------------------------------------------------------------------


def _convert(owner: type, name: str, value: object) -> object:
    """``value`` as the type ``owner.name`` is declared with."""

    hints = typing.get_type_hints(owner)
    if name not in hints:
        known = ", ".join(
            field.name for field in fields(owner) if field.name not in _STYLE_SKIPPED
        )
        raise _fail(
            "theme.setting.unknown",
            f'Unknown {owner.__name__} setting "{name}".',
            hint=f"Settings are: {known}.",
        )
    declared = hints[name]
    options = typing.get_args(declared) if _is_union(declared) else (declared,)
    if value is None and type(None) in options:
        return None
    for option in options:
        if option is Length:
            return Length.parse(value)  # type: ignore[arg-type]
        if typing.get_origin(option) is typing.Literal:
            allowed = typing.get_args(option)
            if value in allowed:
                return value
            raise _fail(
                "theme.setting.invalid",
                f'"{value}" is not a value of {name}.',
                hint=f"Use one of: {', '.join(map(str, allowed))}.",
            )
        if option is bool and isinstance(value, bool):
            return value
        number = isinstance(value, int | float) and not isinstance(value, bool)
        if option in (int, float) and number:
            return option(value)
        if option is str and isinstance(value, str):
            return value
        if typing.get_origin(option) is tuple and isinstance(value, list):
            return tuple(value)
    raise _fail("theme.setting.invalid", f'"{value}" does not suit the setting {name}.')


def _is_union(declared: object) -> bool:
    return typing.get_origin(declared) in (typing.Union, types.UnionType)


def _plain(value: object) -> object:
    """A setting as a file would write it."""

    if isinstance(value, Length):
        # A length set in millimetres (a column width) is written back in them.
        millimetres = value.points / 72.0 * 25.4
        if abs(value.points - round(value.points, 4)) > 1e-9 and abs(
            millimetres - round(millimetres, 2)
        ) < 1e-9:
            return f"{round(millimetres, 2):g}mm"
        rendered = f"{value.points:.4f}".rstrip("0").rstrip(".")
        return f"{rendered}pt"
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


# -- themes ---------------------------------------------------------------------------


def register_theme(source: str | Path | Mapping[str, Any]) -> str:
    """Register the theme a file (or a mapping) describes, and return its name.

    A file may also carry ``palettes:``, which are registered with it.
    """

    from flexo.themes import THEMES, Page, Theme, _register, theme, tone_rule

    path: Path | None = None
    if isinstance(source, Mapping):
        data = dict(source)
    else:
        path = Path(source).expanduser().resolve()
        if str(path) in _LOADED:
            return _LOADED[str(path)]
        data = _read(path)
    for name, colours in (data.get("palettes") or {}).items():
        register_palette(name, colours)
    settings = data.get("theme", data)
    if not isinstance(settings, Mapping) or "name" not in settings:
        raise _fail(
            "theme.file.invalid",
            "A theme needs a name.",
            hint='Write "theme: {name: my-theme, base: paper, ...}".',
        )
    name = str(settings["name"])
    base = theme(str(settings.get("base", "paper")))
    style = base.style
    typography = style.typography
    if "font" in settings:
        typography = typography.with_family(str(settings["font"]))
    for key, value in (settings.get("type") or {}).items():
        typography = replace(typography, **{key: _convert(TypographyStyle, key, value)})
    changes = {
        key: _convert(LayoutStyle, key, value)
        for key, value in (settings.get("style") or {}).items()
        if key != "widths"
    }
    if "widths" in (settings.get("style") or {}):
        widths = dict(style.widths)
        widths.update(
            {key: Length.parse(value) for key, value in settings["style"]["widths"].items()}
        )
        changes["widths"] = tuple(widths.items())
    style = replace(style, name=name, typography=typography, **changes)
    if "conventions" in settings:
        conventions = parse_conventions(settings["conventions"])
        style = replace(style, conventions=style.conventions.with_updates(conventions))
    if "sketch" in settings:
        style = replace(style, sketch=parse_sketch(settings["sketch"]))
    if "background" in settings:
        style = replace(style, background=settings["background"])
    page = base.page
    for key, value in (settings.get("page") or {}).items():
        if key not in {field.name for field in fields(Page)}:
            known = ", ".join(field.name for field in fields(Page))
            raise _fail(
                "theme.setting.unknown", f'Unknown page colour "{key}".', f"Colours: {known}."
            )
        page = replace(page, **{key: normalize_colour(str(value)) if value else None})
    palette = base.palette
    if "palette" in settings:
        palette = _palette_colours(settings["palette"])
    tones = base.tones
    if "tones" in settings:
        tones = tone_rule(dict(settings["tones"]))
    made = Theme(
        name,
        str(settings.get("description", base.description)),
        style,
        page,
        palette,
        tones,
        fixed_palette=bool(settings.get("fixed_palette", base.fixed_palette)),
    )
    THEMES.pop(name, None)
    _register(made)
    if path is not None:
        _LOADED[str(path)] = name
    return name


def resolve_theme(reference: str) -> str | None:
    """The registered name for ``reference``: a theme file, or one on ``FLEXO_THEME_PATH``."""

    _load_environment()
    if is_file_reference(reference):
        return register_theme(reference)
    return None


def theme_document(name: str) -> dict[str, Any]:
    """The theme ``name`` as a complete file: every setting it has, ready to edit."""

    from flexo.themes import Page, theme

    found = theme(name)
    style = found.style
    document: dict[str, Any] = {
        "name": found.name,
        "description": found.description,
        "font": style.typography.family,
        "type": {
            field.name: _plain(getattr(style.typography, field.name))
            for field in fields(TypographyStyle)
            if field.name != "family"
        },
        "palette": list(found.palette),
        "page": {field.name: getattr(found.page, field.name) for field in fields(Page)},
        "tones": getattr(found.tones, "settings", {"rule": "custom"}),
        "style": {
            field.name: _plain(getattr(style, field.name))
            for field in fields(LayoutStyle)
            if field.name not in _STYLE_SKIPPED
        },
        "conventions": {
            field.name: getattr(style.conventions, field.name) for field in fields(Conventions)
        },
        "background": style.background,
    }
    document["style"]["widths"] = {key: _plain(value) for key, value in style.widths}
    if style.sketch is not None:
        document["sketch"] = {
            field.name: getattr(style.sketch, field.name) for field in fields(style.sketch)
        }
    return {"theme": document}


def dump_theme(name: str) -> str:
    """``theme_document(name)`` as YAML."""

    return yaml.safe_dump(theme_document(name), sort_keys=False, allow_unicode=True)


def _load_environment() -> None:
    global _ENVIRONMENT_LOADED
    if _ENVIRONMENT_LOADED:
        return
    _ENVIRONMENT_LOADED = True
    for entry in os.environ.get("FLEXO_THEME_PATH", "").split(os.pathsep):
        if not entry:
            continue
        path = Path(entry).expanduser()
        files = (
            sorted(item for item in path.rglob("*") if item.suffix.lower() in SUFFIXES)
            if path.is_dir()
            else [path]
        )
        for item in files:
            data = _read(item)
            if "theme" in data:
                register_theme(item)
            elif "palettes" in data:
                register_palette(item)


# -- palettes -------------------------------------------------------------------------


def _palette_colours(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        from flexo.themes import parse_palette, unknown_palette

        colours = parse_palette(value)
        if colours is None:
            raise FlexoError(unknown_palette(value))
        return colours
    if isinstance(value, Sequence) and value:
        return tuple(normalize_colour(str(colour)) for colour in value)
    raise _fail("palette.invalid", "A palette is a name or a list of colours.")


def register_palette(
    source: str | Path, colours: Sequence[str] | None = None
) -> tuple[str, ...]:
    """Register a palette by name, or every palette in a file; return the names.

    ``register_palette("Lab", ["#1d4e89", "#f26419"])`` names one palette. With
    one argument, it reads a YAML or JSON file of ``palettes: {name: [colours]}``
    (or a bare ``colours: [...]``, named after the file).
    """

    if colours is not None:
        name = str(source)
        for existing in [key for key in CUSTOM_PALETTES if key.casefold() == name.casefold()]:
            del CUSTOM_PALETTES[existing]
        CUSTOM_PALETTES[name] = _palette_colours(list(colours))
        return (name,)
    path = Path(source).expanduser()
    data = _read(path)
    if "colours" in data or "colors" in data:
        return register_palette(path.stem, data.get("colours", data.get("colors")))
    names: list[str] = []
    for name, value in (data.get("palettes") or {}).items():
        names.extend(register_palette(name, value))
    if not names:
        raise _fail(
            "palette.file.invalid",
            f'"{source}" names no palettes.',
            hint='Write "palettes: {Lab: ["#1d4e89", "#f26419", ...]}".',
        )
    return tuple(names)


def custom_palette(reference: str) -> tuple[str, ...] | None:
    """A registered palette's colours, or a palette file's (its only or first one)."""

    _load_environment()
    if is_file_reference(reference):
        names = register_palette(reference)
        return CUSTOM_PALETTES[names[0]]
    wanted = reference.strip().casefold()
    return next((value for key, value in CUSTOM_PALETTES.items() if key.casefold() == wanted), None)
