"""Compile a practical Python subset into Apple Shortcuts workflows."""

from __future__ import annotations

from pathlib import Path
import pprint

import typer

from .compiler import Compilation, compile_file, compile_source, resolve_entrypoint
from .errors import CompileError
from .health import build_sleep_stage_probe
from .plist import compile_binary_plist, compile_xml_plist
from .plugin_loader import load_plugin_file
from .plugins import PluginRegistry
from .signing import sign_xml_plist
from .validate import WorkflowValidationError, validate_workflow

__all__ = [
    "Compilation",
    "CompileError",
    "app",
    "build_sleep_stage_probe",
    "compile_binary_plist",
    "compile_file",
    "compile_source",
    "resolve_entrypoint",
    "compile_xml_plist",
    "validate_workflow",
    "WorkflowValidationError",
]

app = typer.Typer(help=__doc__, no_args_is_help=True)


@app.command("dump-ir")
def dump_ir(source: Path) -> None:
    """Parse Python and print the intermediate representation."""
    compilation = compile_file(source, include_header_comment=False)
    pprint.pp(compilation.ir)


@app.command("build")
def build(
    source: Path,
    output: Path | None = typer.Option(None, "-o", "--output"),
    name: str | None = typer.Option(None, "--name"),
    binary: bool = typer.Option(
        False, "--binary", help="write a binary plist instead of XML"
    ),
    no_header_comment: bool = typer.Option(False, "--no-header-comment"),
    plugin: list[Path] = typer.Option(
        [],
        "--plugin",
        help="load a Python plugin file defining register(registry); may be repeated",
    ),
    sign: bool = typer.Option(
        False, "--sign", help="sign through the configured third-party signing service"
    ),
    signed_output: Path | None = typer.Option(None, "--signed-output"),
) -> None:
    """Compile Python to a Shortcuts workflow plist."""
    plugin_registry = PluginRegistry()
    for plugin_path in plugin:
        load_plugin_file(plugin_path, plugin_registry)

    entrypoint = resolve_entrypoint(source)
    compilation = compile_file(
        entrypoint,
        name=name,
        plugins=plugin_registry,
        include_header_comment=not no_header_comment,
    )
    suffix = ".bplist" if binary else ".plist"
    default_base = source if source.is_dir() else entrypoint
    target = output or default_base.with_suffix(suffix)
    payload = compilation.binary() if binary else compilation.xml()
    target.write_bytes(payload)
    print(f"Wrote {target}")

    if sign:
        # The existing signer expects XML, so always sign the XML representation.
        signed_target = signed_output or default_base.with_suffix(".shortcut")
        signed_target.write_bytes(sign_xml_plist(compilation.xml()))
        print(f"Wrote {signed_target}")


def main() -> None:
    app()
