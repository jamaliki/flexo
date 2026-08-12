"""Command-line entry point. Commands are added as compiler slices land."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from flexo import __version__


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="flexo",
        description="Compile semantic scientific figures into editable SVG.",
    )
    result.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = result.add_subparsers(dest="command")
    subcommands.add_parser("build", help="Compile a YAML or JSON figure specification.")
    subcommands.add_parser("check", help="Validate a specification or generated SVG.")
    subcommands.add_parser("inspect", help="Report semantic and geometric figure information.")
    subcommands.add_parser("gallery", help="Build bundled gallery figures.")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    if arguments.command is None:
        parser().print_help()
    else:
        parser().error(f"{arguments.command} is not implemented in this checkpoint")
    return 0
