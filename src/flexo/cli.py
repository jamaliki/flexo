"""Command-line interface for compiling, checking, inspecting, and exporting."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from flexo import __version__
from flexo.colour import design_palettes
from flexo.compiler import compile_figure
from flexo.diagnostics import FlexoError
from flexo.export import build
from flexo.fonts import bundled_families
from flexo.gallery import GALLERY, gallery_figure
from flexo.ir.semantic import FigureSpec
from flexo.lint import lint_compilation, lint_svg
from flexo.schema import load_schema
from flexo.serialization import load_figure
from flexo.theme import retheme_svg
from flexo.themes import THEMES, resolve_palette


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="flexo",
        description="Compile semantic scientific figures into editable SVG.",
    )
    result.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = result.add_subparsers(dest="command")

    build = subcommands.add_parser("build", help="Compile a YAML or JSON figure specification.")
    build.add_argument("source", type=Path)
    _output_arguments(build)

    check = subcommands.add_parser("check", help="Validate a specification or generated SVG.")
    check.add_argument("source", type=Path)

    inspect = subcommands.add_parser("inspect", help="Report semantic and geometric information.")
    inspect.add_argument("source", type=Path)
    inspect.add_argument("--json", action="store_true", dest="as_json")

    gallery = subcommands.add_parser("gallery", help="Build bundled gallery figures.")
    gallery.add_argument("names", nargs="*", choices=tuple(GALLERY))
    _output_arguments(gallery)

    schema = subcommands.add_parser("schema", help="Print or save the interchange JSON Schema.")
    schema.add_argument("--output", type=Path)

    retheme = subcommands.add_parser("retheme", help="Patch paint roles without changing geometry.")
    retheme.add_argument("source", type=Path)
    retheme.add_argument(
        "palette",
        help="A palette name (see `flexo themes`), '#hex,#hex,...', or 'default'.",
    )
    retheme.add_argument(
        "--theme",
        default="paper",
        help="Whose colour rules to paint with (paint only: geometry is kept).",
    )
    retheme.add_argument("--output", "-o", type=Path, required=True)

    parts = subcommands.add_parser(
        "to-parts",
        help="Make a diagram drawn as shapes (a figure's, or a file listing them) the figure's "
        "own parts: shapes, lines and groups, laid out as drawn.",
    )
    parts.add_argument(
        "source", type=Path, help="A figure file with shapes drawn over it, or a list of shapes."
    )
    parts.add_argument(
        "--shapes",
        help="Which of its shapes, by id or by place (0 is the first), comma-separated: all if "
        "not given.",
    )
    parts.add_argument("--output", "-o", type=Path, help="Write the figure here, not to stdout.")

    subcommands.add_parser(
        "studio",
        help="Edit figures, themes (and decks, with flexo-talk) in the browser; "
        "`flexo studio mcp` gives an agent its tools.",
        add_help=False,
    )

    subcommands.add_parser("themes", help="List themes, palettes, and bundled fonts.")
    theme = subcommands.add_parser(
        "theme", help="Print a theme as a file to start your own from (see docs/tutorial.md)."
    )
    theme.add_argument("name", help="A theme name, or a theme file.")
    theme.add_argument("--output", "-o", type=Path, help="Write the file here instead.")
    imported = subcommands.add_parser(
        "import-svg",
        help="Make a drawing (SVG, or a PDF's page) the shapes a slide or a figure draws.",
    )
    imported.add_argument("source", type=Path, help="An .svg, .pdf or .ai file.")
    imported.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Write the shapes (YAML) here, its pictures in assets/ beside it; else print them.",
    )
    imported.add_argument(
        "--figure", action="store_true", help="Words in a figure's markup, not a slide's."
    )
    imported.add_argument(
        "--exact", action="store_true", help="Keep every colour as drawn, none the theme's."
    )
    imported.add_argument(
        "--fit",
        nargs=2,
        type=float,
        metavar=("WIDTH", "HEIGHT"),
        help="Make it smaller to fit, in points (a slide's shapes: 960 by 540 across).",
    )
    imported.add_argument(
        "--at", nargs=2, type=float, metavar=("X", "Y"), help="Its top left, in points."
    )
    return result


def _output_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--output", "-o", type=Path, default=Path("build"))
    command.add_argument(
        "--formats",
        default="editable,portable,pdf,png",
        help="Comma-separated: editable, portable, pdf, png.",
    )
    command.add_argument("--dpi", type=float, default=192.0)
    command.add_argument("--theme", help="Override the figure's theme (see `flexo themes`).")
    command.add_argument("--palette", help="Override the figure's palette.")
    command.add_argument("--font", help="Set the figure in another font family.")


def main(argv: Sequence[str] | None = None) -> int:
    given = list(sys.argv[1:] if argv is None else argv)
    if given[:1] == ["studio"]:
        from flexo.studio.server import main as studio_main

        return studio_main(given[1:])
    arguments = parser().parse_args(given)
    try:
        if arguments.command == "build":
            return _build(arguments)
        if arguments.command == "check":
            return _check(arguments)
        if arguments.command == "inspect":
            return _inspect(arguments)
        if arguments.command == "gallery":
            return _gallery(arguments)
        if arguments.command == "schema":
            return _schema(arguments)
        if arguments.command == "retheme":
            return _retheme(arguments)
        if arguments.command == "to-parts":
            return _to_parts(arguments)
        if arguments.command == "themes":
            return _themes()
        if arguments.command == "theme":
            return _theme(arguments)
        if arguments.command == "import-svg":
            return _import_svg(arguments)
        parser().print_help()
        return 0
    except (FlexoError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


def _import_svg(arguments: argparse.Namespace) -> int:
    """A drawing as shapes (``flexo.svgimport``): its YAML, and what is kept as pictures."""

    import yaml

    from flexo.svgimport import shapes_of

    source: Path = arguments.source
    if source.suffix.lower() in (".pdf", ".ai"):
        from flexo.pdfart import read_page

        drawing = read_page(str(source), 1, source.stat().st_mtime_ns).markup
    else:
        drawing = source.read_text(encoding="utf-8")
    output: Path | None = arguments.output
    folder = output.parent if output else Path.cwd()
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def keep(data: bytes, suffix: str) -> str:
        target = folder / "assets" / f"{source.stem}-part-{len(written) + 1}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(target)
        return target.relative_to(folder).as_posix()

    made = shapes_of(
        drawing,
        exact=arguments.exact,
        markup="figure" if arguments.figure else "slide",
        fit=arguments.fit,
        at=arguments.at or [0.0, 0.0],
        picture=keep,
        name=source.stem,
    )

    class Dumper(yaml.SafeDumper):
        pass

    def listed(dumper: yaml.SafeDumper, value: list) -> yaml.Node:
        short = len(value) <= 4 and all(isinstance(item, int | float | str) for item in value)
        return dumper.represent_sequence("tag:yaml.org,2002:seq", value, flow_style=short)

    Dumper.add_representer(list, listed)
    text = yaml.dump(
        {"shapes": made.shapes}, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=100
    )
    if output:
        output.write_text(text, encoding="utf-8")
        print(output)
    else:
        sys.stdout.write(text)
    said = [
        f"{made.count} shapes from {made.elements} elements, {made.box[2]:g} by "
        f"{made.box[3]:g} points"
    ]
    said += [f"kept as a picture: {item}" for item in made.kept]
    said += [f"near enough: {item}" for item in made.approximated]
    print("\n".join(said), file=sys.stderr)
    return 0


def _build(arguments: argparse.Namespace) -> int:
    return _write(load_figure(arguments.source), arguments, stem=arguments.source.stem)


def _check(arguments: argparse.Namespace) -> int:
    if arguments.source.suffix.lower() == ".svg":
        report = lint_svg(arguments.source.read_text(encoding="utf-8"))
    else:
        report = lint_compilation(compile_figure(load_figure(arguments.source)))
    print(report.format())
    return 0 if report.ok else 1


def _inspect(arguments: argparse.Namespace) -> int:
    compilation = compile_figure(load_figure(arguments.source))
    value = {
        "figure": compilation.measured.semantic.id,
        "nodes": len(compilation.measured.nodes),
        "groups": len(compilation.measured.groups),
        "edges": len(compilation.routed.edges),
        "width_mm": compilation.document.width_mm,
        "height_mm": compilation.document.height_mm,
    }
    if arguments.as_json:
        print(json.dumps(value, indent=2, sort_keys=True))
    else:
        print("\n".join(f"{name}: {content}" for name, content in value.items()))
    return 0


def _gallery(arguments: argparse.Namespace) -> int:
    exit_code = 0
    for name in arguments.names or list(GALLERY):
        exit_code = max(exit_code, _write(gallery_figure(name), arguments, stem=name))
    return exit_code


def _write(figure: FigureSpec, arguments: argparse.Namespace, *, stem: str) -> int:
    """Build one figure into the requested outputs and report its lint severity.

    Outputs are always written: a figure that lints with errors must stay
    inspectable. Errors go to stderr and make the command exit nonzero; a clean
    or warning-only report is printed to stdout.
    """

    if arguments.theme:
        figure = replace(figure, style=arguments.theme)
    if arguments.palette:
        figure = replace(figure, palette=arguments.palette)
    if arguments.font:
        figure = replace(figure, font=arguments.font)
    result = build(
        figure,
        arguments.output,
        stem=stem,
        formats=_formats(arguments.formats),
        dpi=arguments.dpi,
    )
    for target_file in result.outputs.existing():
        print(target_file)
    if result.report.diagnostics:
        print(
            result.report.format(),
            file=sys.stderr if result.report.errors else sys.stdout,
        )
    return 0 if result.ok else 1


def _schema(arguments: argparse.Namespace) -> int:
    text = json.dumps(load_schema(), indent=2, ensure_ascii=False) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(text, encoding="utf-8")
        print(arguments.output)
    else:
        print(text, end="")
    return 0


def _retheme(arguments: argparse.Namespace) -> int:
    source = arguments.source.read_text(encoding="utf-8")
    themed = retheme_svg(source, resolve_palette(arguments.theme, arguments.palette))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(themed, encoding="utf-8")
    print(arguments.output)
    return 0


def _to_parts(arguments: argparse.Namespace) -> int:
    """Convert to Figure Parts: a figure file's shapes (or a list of shapes, a figure of their
    own) made its parts, written as the studio writes them (``flexo.studio.figure_edit``)."""

    import yaml

    from flexo.recognise import slug
    from flexo.studio.figure_edit import EditError, apply

    source: Path = arguments.source
    suffix = ".json" if source.suffix.lower() == ".json" else ".yaml"
    text = source.read_text(encoding="utf-8")
    data = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
    if isinstance(data, list):
        # Shapes alone: a figure of their own, named for the file.
        data = {"figure": {"id": slug(source.stem)}, "nodes": [], "shapes": data}
        suffix = ".yaml"
        text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    if not isinstance(data, dict) or not isinstance(data.get("shapes"), list):
        raise ValueError(f"{source} has no shapes: a figure file's shapes, or a list of shapes")
    drawn = data["shapes"]
    ids = {str(item.get("id")): at for at, item in enumerate(drawn) if isinstance(item, dict)}
    named = [item.strip() for item in (arguments.shapes or "").split(",") if item.strip()]
    places = [ids[item] if item in ids else int(item) for item in named] or list(range(len(drawn)))
    try:
        result = apply(text, {"do": "convert", "shapes": places}, suffix=suffix, base=source.parent)
    except EditError as error:
        raise ValueError(str(error)) from None
    if arguments.output is None:
        print(result["text"], end="")
    else:
        arguments.output.write_text(result["text"], encoding="utf-8")
        print(arguments.output)
    if result.get("said"):
        print(f"{result['said']}.", file=sys.stderr)
    return 0


def _theme(arguments: argparse.Namespace) -> int:
    from flexo.theme_files import dump_theme
    from flexo.themes import theme

    name = theme(arguments.name).name
    text = dump_theme(name)
    if arguments.output is None:
        print(text, end="")
    else:
        arguments.output.write_text(text, encoding="utf-8")
        print(f"wrote {arguments.output}")
    return 0


def _themes() -> int:
    from flexo.theme_files import CUSTOM_PALETTES, _load_environment

    _load_environment()
    width = max(len(name) for name in THEMES)
    print("Themes (Figure(theme=...)):")
    for name, entry in THEMES.items():
        print(f"  {name:<{width}}  {entry.description}")
    print("\nPalettes (Figure(palette=...), or a list of hex colours):")
    for name, colours in design_palettes().items():
        print(f"  {name:<24} {' '.join(colours)}")
    for name, colours in CUSTOM_PALETTES.items():
        print(f"  {name:<24} {' '.join(colours)}  (registered)")
    print("\nBundled fonts (Figure(font=...); any installed font works too):")
    for family in bundled_families():
        print(f"  {family}")
    return 0


def _formats(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())
