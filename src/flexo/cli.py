"""Command-line interface for compiling, checking, inspecting, and exporting."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from flexo import __version__
from flexo.compiler import compile_figure
from flexo.diagnostics import FlexoError
from flexo.export import export_outputs
from flexo.gallery import GALLERY, gallery_figure
from flexo.lint import LintReport, lint_compilation, lint_svg
from flexo.schema import load_schema
from flexo.serialization import load_figure
from flexo.style import PALETTES
from flexo.theme import retheme_svg


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
    retheme.add_argument("palette", choices=tuple(PALETTES))
    retheme.add_argument("--output", "-o", type=Path, required=True)
    return result


def _output_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--output", "-o", type=Path, default=Path("build"))
    command.add_argument(
        "--formats",
        default="editable,portable,pdf,png",
        help="Comma-separated: editable, portable, pdf, png.",
    )
    command.add_argument("--dpi", type=float, default=192.0)
    command.add_argument("--palette", choices=tuple(PALETTES))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
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
        parser().print_help()
        return 0
    except (FlexoError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


def _build(arguments: argparse.Namespace) -> int:
    figure = load_figure(arguments.source)
    if arguments.palette:
        from dataclasses import replace

        figure = replace(figure, palette=arguments.palette)
    compilation = compile_figure(figure)
    outputs = export_outputs(
        compilation,
        arguments.output,
        stem=arguments.source.stem,
        formats=_formats(arguments.formats),
        dpi=arguments.dpi,
    )
    for target_file in outputs.existing():
        print(target_file)
    return _report_exit_code(lint_compilation(compilation))


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
    names = arguments.names or list(GALLERY)
    formats = _formats(arguments.formats)
    exit_code = 0
    for name in names:
        figure = gallery_figure(name)
        if arguments.palette:
            from dataclasses import replace

            figure = replace(figure, palette=arguments.palette)
        compilation = compile_figure(figure)
        outputs = export_outputs(
            compilation,
            arguments.output,
            stem=name,
            formats=formats,
            dpi=arguments.dpi,
        )
        for target_file in outputs.existing():
            print(target_file)
        exit_code = max(exit_code, _report_exit_code(lint_compilation(compilation)))
    return exit_code


def _report_exit_code(report: LintReport) -> int:
    """Print a lint report next to written outputs and report its severity.

    Outputs are always written: a figure that lints with errors must stay
    inspectable. Errors go to stderr and make the command exit nonzero; a clean
    or warning-only report is printed to stdout.
    """

    if report.diagnostics:
        print(report.format(), file=sys.stderr if report.errors else sys.stdout)
    return 0 if report.ok else 1


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
    themed = retheme_svg(source, PALETTES[arguments.palette])
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(themed, encoding="utf-8")
    print(arguments.output)
    return 0


def _formats(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())
