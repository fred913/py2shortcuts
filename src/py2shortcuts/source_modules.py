"""Static loader for local Python modules compiled as source.

Local application modules are parsed, never imported.  This keeps compiler-only
facades and application code from executing inside CPython while still allowing
ordinary helper functions and literal weight/constants modules to participate in
frontend lowering.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CompileError


type StaticValue = str | int | float | bool | None | list[StaticValue] | tuple[StaticValue, ...] | dict[StaticValue, StaticValue]


@dataclass(frozen=True, slots=True)
class ExternalBinding:
    target: str


@dataclass(frozen=True, slots=True)
class ConstantBinding:
    value: StaticValue


@dataclass(frozen=True, slots=True)
class FunctionBinding:
    function: "SourceFunction"


@dataclass(frozen=True, slots=True)
class ModuleBinding:
    module: "SourceModule"


type SourceBinding = ExternalBinding | ConstantBinding | FunctionBinding | ModuleBinding


@dataclass(slots=True)
class SourceFunction:
    qualified_name: str
    node: ast.FunctionDef
    module: "SourceModule"


@dataclass(slots=True)
class SourceModule:
    name: str
    path: Path
    tree: ast.Module
    bindings: dict[str, SourceBinding] = field(default_factory=dict)
    functions: dict[str, SourceFunction] = field(default_factory=dict)


class SourceModuleResolver:
    """Resolve sibling/project Python modules without executing them."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir.resolve()
        self._by_path: dict[Path, SourceModule] = {}
        self._loading: set[Path] = set()

    def load_entry(self, source: str, path: Path) -> SourceModule:
        return self._load_source("__entry__", path.resolve(), source, allow_executable=True)

    def resolve_local_module(self, module_name: str, *, importer: SourceModule) -> SourceModule | None:
        # Keep the first version deliberately small and predictable: absolute
        # imports rooted at the project directory, either foo.py or foo/__init__.py.
        relative = Path(*module_name.split("."))
        candidates = [
            self.project_dir / relative.with_suffix(".py"),
            self.project_dir / relative / "__init__.py",
        ]
        for candidate in candidates:
            if candidate.is_file():
                if self._declares_register(candidate):
                    # Files that define register(registry) are compiler plugins, not
                    # source modules. Plugin discovery owns their execution/lowering.
                    return None
                return self._load_file(module_name, candidate)
        return None

    def _load_file(self, name: str, path: Path) -> SourceModule:
        path = path.resolve()
        cached = self._by_path.get(path)
        if cached is not None:
            return cached
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as error:
            raise CompileError(f"cannot read local source module {path}: {error}") from error
        return self._load_source(name, path, source, allow_executable=False)

    def _load_source(self, name: str, path: Path, source: str, *, allow_executable: bool) -> SourceModule:
        cached = self._by_path.get(path)
        if cached is not None:
            return cached
        if path in self._loading:
            raise CompileError(f"circular local source import involving {path}")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as error:
            raise CompileError(
                error.msg,
                filename=str(path),
                lineno=error.lineno,
                col_offset=(error.offset - 1) if error.offset else None,
            ) from error

        module = SourceModule(name=name, path=path, tree=tree)
        self._by_path[path] = module
        self._loading.add(path)
        try:
            # First register functions and literal constants so sibling imports can
            # refer to them without executing module code.
            for node in tree.body:
                if isinstance(node, ast.FunctionDef):
                    function = SourceFunction(f"{name}.{node.name}", node, module)
                    module.functions[node.name] = function
                    module.bindings[node.name] = FunctionBinding(function)
                    continue
                if isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef)):
                    self._error(module, node, f"{type(node).__name__} is not supported in compiled local modules")
                if not allow_executable and isinstance(node, ast.Assign):
                    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                        self._error(module, node, "compiled local-module constants require one simple name")
                    module.bindings[node.targets[0].id] = ConstantBinding(self._literal_value(module, node.value))
                    continue
                if not allow_executable and isinstance(node, ast.AnnAssign):
                    if not isinstance(node.target, ast.Name) or node.value is None:
                        self._error(module, node, "compiled local-module constants require an initialized simple name")
                    module.bindings[node.target.id] = ConstantBinding(self._literal_value(module, node.value))

            # Then resolve imports.  Local modules become source bindings; external
            # modules remain symbolic compiler namespaces exactly as before.
            for node in tree.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        local = alias.asname or alias.name.split(".", 1)[0]
                        local_module = self.resolve_local_module(alias.name, importer=module)
                        if local_module is not None:
                            module.bindings[local] = ModuleBinding(local_module)
                        else:
                            target = "shortcuts" if alias.name == "py2shortcuts.shortcuts" else alias.name
                            module.bindings[local] = ExternalBinding(target)
                    continue
                if isinstance(node, ast.ImportFrom):
                    if node.module == "__future__":
                        continue
                    if node.level:
                        self._error(module, node, "relative imports are not supported in compiled local modules yet")
                    if node.module is None:
                        self._error(module, node, "import-from requires a module name")
                    local_module = self.resolve_local_module(node.module, importer=module)
                    for alias in node.names:
                        if alias.name == "*":
                            self._error(module, node, "star imports are not supported")
                        local_name = alias.asname or alias.name
                        if local_module is not None:
                            binding = local_module.bindings.get(alias.name)
                            if binding is None:
                                self._error(module, node, f"local module {node.module!r} has no symbol {alias.name!r}")
                            module.bindings[local_name] = binding
                        else:
                            if node.module == "py2shortcuts" and alias.name == "shortcuts":
                                target = "shortcuts"
                            elif node.module == "py2shortcuts.shortcuts":
                                target = f"shortcuts.{alias.name}"
                            else:
                                target = f"{node.module}.{alias.name}"
                            module.bindings[local_name] = ExternalBinding(target)

            if not allow_executable:
                # Imported local modules are compile-time libraries.  Arbitrary module
                # side effects are intentionally rejected because we never execute them.
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)):
                        continue
                    if self._is_docstring(node):
                        continue
                    if isinstance(node, ast.Pass):
                        continue
                    self._error(
                        module,
                        node,
                        "compiled local modules may contain only imports, literal constants, and function definitions; "
                        "move executable application code to the entrypoint",
                    )
        finally:
            self._loading.remove(path)
        return module

    @staticmethod
    def _declares_register(path: Path) -> bool:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError):
            return False
        return any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "register"
            for node in tree.body
        )

    @staticmethod
    def _is_docstring(node: ast.stmt) -> bool:
        return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)

    @staticmethod
    def _literal_value(module: SourceModule, node: ast.expr) -> StaticValue:
        try:
            value = ast.literal_eval(node)
        except (ValueError, TypeError, SyntaxError) as error:
            raise CompileError(
                "compiled local-module constants must be Python literals",
                filename=str(module.path),
                lineno=getattr(node, "lineno", None),
                col_offset=getattr(node, "col_offset", None),
            ) from error
        return value

    @staticmethod
    def _error(module: SourceModule, node: ast.AST, message: str) -> None:
        raise CompileError(
            message,
            filename=str(module.path),
            lineno=getattr(node, "lineno", None),
            col_offset=getattr(node, "col_offset", None),
        )
