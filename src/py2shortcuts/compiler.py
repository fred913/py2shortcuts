"""Public compiler pipeline: Python source -> IR -> Apple Shortcuts workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .backend import ShortcutsBackend
from .frontend import PythonFrontend
from .ir import Module
from .plist import Workflow, compile_binary_plist, compile_xml_plist
from .plugin_loader import load_local_plugins_for_source
from .plugins import PluginRegistry
from .validate import validate_workflow
from .errors import CompileError
from .config import ShortcutConfig, load_project_config


@dataclass(frozen=True, slots=True)
class Compilation:
    ir: Module
    workflow: Workflow

    def xml(self) -> bytes:
        return compile_xml_plist(self.workflow)

    def binary(self) -> bytes:
        return compile_binary_plist(self.workflow)


def compile_source(
    source: str,
    *,
    name: str = "Python Shortcut",
    filename: str = "<string>",
    plugins: PluginRegistry | None = None,
    include_header_comment: bool = True,
    config: ShortcutConfig | None = None,
) -> Compilation:
    plugin_registry = PluginRegistry()
    if plugins is not None:
        plugin_registry.extend(plugins, override=True)

    if filename != "<string>":
        source_path = Path(filename)
        if source_path.exists() and source_path.is_file():
            load_local_plugins_for_source(source_path, plugin_registry)

    frontend = PythonFrontend(filename=filename)
    module = frontend.compile(source)
    effective_config = config or ShortcutConfig()
    backend = ShortcutsBackend(
        name=name,
        plugins=plugin_registry,
        include_header_comment=include_header_comment,
        input_classes=effective_config.input_classes,
        workflow_types=effective_config.workflow_types,
    )
    compiled_workflow = backend.compile(module)
    validate_workflow(compiled_workflow)
    return Compilation(module, compiled_workflow)


def resolve_entrypoint(path: str | Path) -> Path:
    source_path = Path(path)
    if source_path.is_dir():
        entrypoint = source_path / "main.py"
        if not entrypoint.is_file():
            raise CompileError(f"directory {source_path} does not contain a main.py entrypoint")
        return entrypoint
    return source_path


def compile_file(
    path: str | Path,
    *,
    name: str | None = None,
    plugins: PluginRegistry | None = None,
    include_header_comment: bool = True,
) -> Compilation:
    requested_path = Path(path)
    source_path = resolve_entrypoint(requested_path)
    project_dir = requested_path if requested_path.is_dir() else source_path.parent
    project_config = load_project_config(project_dir)
    source = source_path.read_text(encoding="utf-8")
    return compile_source(
        source,
        name=name or project_config.name or source_path.stem.replace("_", " ").title(),
        filename=str(source_path),
        plugins=plugins,
        include_header_comment=include_header_comment,
        config=project_config,
    )
