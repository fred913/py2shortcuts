"""Load explicit compiler plugins from Python files for the CLI."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

from .plugins import PluginRegistry


class PluginLoadError(RuntimeError):
    pass


def _load_plugin_module(path: Path, *, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PluginLoadError(f"Cannot load plugin {path}")
    module = importlib.util.module_from_spec(spec)
    resolved_dir = path.resolve().parent
    plugin_dir = str(resolved_dir)

    # A local plugin often imports sibling helpers such as ``weights.py``.
    # Those short module names must not leak between separately compiled
    # projects in the same Python process. Temporarily hide any pre-existing
    # modules with sibling stems, then restore the process-wide cache after the
    # plugin has captured its own local imports.
    sibling_names = {candidate.stem for candidate in resolved_dir.glob("*.py")}
    missing = object()
    saved_modules = {name: sys.modules.get(name, missing) for name in sibling_names}
    for name in sibling_names:
        sys.modules.pop(name, None)

    sys.path.insert(0, plugin_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(plugin_dir)
        except ValueError:
            pass
        for name in sibling_names:
            sys.modules.pop(name, None)
        for name, previous in saved_modules.items():
            if previous is not missing:
                sys.modules[name] = previous
    return module


def _declares_register(path: Path) -> bool:
    """Return whether *path* statically declares a top-level ``register`` function.

    Local plugin discovery must not execute arbitrary sibling source files just to
    determine whether they are plugins. Doing so would run example/application code
    at compiler startup (including compile-time-only ``ios`` facade calls).
    """
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return False

    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "register"
        for node in tree.body
    )


def load_plugin_file(path: str | Path, registry: PluginRegistry) -> ModuleType:
    plugin_path = Path(path)
    module_name = f"py2shortcuts_user_plugin_{abs(hash(plugin_path.resolve()))}"
    module = _load_plugin_module(plugin_path, module_name=module_name)
    register = getattr(module, "register", None)
    if not callable(register):
        raise PluginLoadError(f"Plugin {plugin_path} must define register(registry)")
    register(registry)
    return module


def load_local_plugins_for_source(
    path: str | Path, registry: PluginRegistry
) -> list[ModuleType]:
    source_path = Path(path).resolve()
    if not source_path.is_file():
        return []

    loaded: list[ModuleType] = []
    for candidate in sorted(source_path.parent.glob("*.py")):
        if candidate.name in {"__init__.py", source_path.name}:
            continue
        if not _declares_register(candidate):
            continue
        module_name = f"py2shortcuts_local_plugin_{source_path.parent.name}_{candidate.stem}_{abs(hash(candidate.resolve()))}"
        module = _load_plugin_module(candidate, module_name=module_name)
        register = getattr(module, "register", None)
        if callable(register):
            register(registry)
            loaded.append(module)
    return loaded
