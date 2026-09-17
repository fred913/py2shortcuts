"""Python AST frontend for the supported py2shortcuts language subset."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from . import ir
from .errors import CompileError
from .source_modules import (
    ConstantBinding,
    ExternalBinding,
    FunctionBinding,
    ModuleBinding,
    SourceBinding,
    SourceFunction,
    SourceModule,
    SourceModuleResolver,
    StaticValue,
)


_BINOPS: dict[type[ast.operator], str] = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.Mod: "%",
    ast.Pow: "**",
}

_UNARYOPS: dict[type[ast.unaryop], str] = {
    ast.UAdd: "+",
    ast.USub: "-",
    ast.Not: "not",
}

_CMPOPS: dict[type[ast.cmpop], str] = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
}


@dataclass(frozen=True, slots=True)
class _FunctionSpec:
    name: str
    node: ast.FunctionDef
    module: SourceModule | None


class PythonFrontend:
    """Lower a deliberately small Python subset into :mod:`py2shortcuts.ir`."""

    def __init__(
        self,
        *,
        filename: str = "<string>",
        source_resolver: SourceModuleResolver | None = None,
    ) -> None:
        self.filename = filename
        self._source_resolver = source_resolver
        self._functions: dict[str, _FunctionSpec] = {}
        self._aliases: dict[str, str] = {}
        self._inline_stack: list[str] = []
        self._locals: list[dict[str, ir.Expr]] = []
        self._module_stack: list[SourceModule | None] = []
        self._inline_counter = 0
        self._temp_counter = 0

    def compile(self, source: str) -> ir.Module:
        module: SourceModule | None = None
        if self._source_resolver is not None and self.filename != "<string>":
            module = self._source_resolver.load_entry(source, Path(self.filename))
            tree = module.tree
        else:
            try:
                tree = ast.parse(source, filename=self.filename)
            except SyntaxError as error:
                raise CompileError(
                    error.msg,
                    filename=self.filename,
                    lineno=error.lineno,
                    col_offset=(error.offset - 1) if error.offset else None,
                ) from error

        self._module_stack.append(module)
        try:
            for node in tree.body:
                if isinstance(node, ast.FunctionDef):
                    name = self._function_name(node.name, module)
                    if name in self._functions:
                        self._error(node, f"duplicate function definition {node.name!r}")
                    self._functions[name] = _FunctionSpec(name, node, module)
                elif isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef)):
                    self._error(node, f"{type(node).__name__} is not supported")

            statements: list[ir.Stmt] = []
            for node in tree.body:
                if isinstance(node, ast.FunctionDef):
                    self._validate_inline_function(node)
                    continue
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if module is None:
                        self._record_legacy_import(node)
                    continue
                statement = self._stmt(node)
                if statement is not None:
                    statements.append(statement)
            return ir.Module(tuple(statements))
        finally:
            self._module_stack.pop()

    def _record_legacy_import(self, node: ast.Import | ast.ImportFrom) -> None:
        # Imports are compile-time namespaces only. No runtime import action is emitted.
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                target = "shortcuts" if alias.name == "py2shortcuts.shortcuts" else alias.name
                self._aliases[local] = target
            return

        if node.module is None:
            self._error(node, "relative imports are not supported")
        module = node.module
        for alias in node.names:
            if alias.name == "*":
                self._error(node, "star imports are not supported")
            local = alias.asname or alias.name
            if module == "py2shortcuts" and alias.name == "shortcuts":
                target = "shortcuts"
            elif module == "py2shortcuts.shortcuts":
                target = f"shortcuts.{alias.name}"
            else:
                target = f"{module}.{alias.name}"
            self._aliases[local] = target

    def _validate_inline_function(self, node: ast.FunctionDef) -> None:
        if node.decorator_list:
            self._error(node, "decorators are not supported on inline functions")
        args = node.args
        if args.posonlyargs or args.vararg or args.kwonlyargs or args.kwarg or args.defaults:
            self._error(node, "inline functions currently accept only required positional parameters")
        body = self._function_body(node)
        if not body or not isinstance(body[-1], ast.Return) or body[-1].value is None:
            self._error(node, "user functions must end with `return <expression>`")
        for statement in body[:-1]:
            if any(isinstance(child, ast.Return) for child in ast.walk(statement)):
                self._error(statement, "early return is not supported in inline functions yet")

    @staticmethod
    def _function_body(node: ast.FunctionDef) -> list[ast.stmt]:
        body = list(node.body)
        if body and PythonFrontend._is_docstring(body[0]):
            body.pop(0)
        return body

    @staticmethod
    def _is_docstring(node: ast.stmt) -> bool:
        return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)

    def _stmt(self, node: ast.stmt) -> ir.Stmt | None:
        if isinstance(node, ast.Expr):
            if self._is_docstring(node):
                return None
            append = self._append_stmt(node.value)
            if append is not None:
                return append
            return ir.ExprStmt(self._expr(node.value))

        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                self._error(node, "only assignment to one simple variable is supported")
            return ir.Assign(self._target_name(node.targets[0].id), self._expr(node.value))

        if isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name) or node.value is None:
                self._error(node, "only initialized annotations on simple variables are supported")
            return ir.Assign(self._target_name(node.target.id), self._expr(node.value))

        if isinstance(node, ast.AugAssign):
            if not isinstance(node.target, ast.Name):
                self._error(node, "augmented assignment requires a simple variable")
            op = _BINOPS.get(type(node.op))
            if op is None:
                self._error(node, f"unsupported augmented operator {type(node.op).__name__}")
            target = self._target_name(node.target.id)
            return ir.Assign(target, ir.Binary(op, ir.Var(target), self._expr(node.value)))

        if isinstance(node, ast.If):
            return ir.IfStmt(
                self._expr(node.test),
                self._block(node.body),
                self._block(node.orelse),
            )

        if isinstance(node, ast.For):
            if node.orelse:
                self._error(node, "for ... else is not supported")
            if not isinstance(node.target, ast.Name):
                self._error(node, "for-loop target must be one simple variable")
            target = self._target_name(node.target.id)
            body = self._block(node.body)
            range_args = self._range_args(node.iter)
            if range_args is not None:
                start, stop, step = range_args
                if not isinstance(step, ir.Literal) or step.value != 1:
                    self._error(node, "range() currently requires step=1")
                return ir.ForRangeStmt(target, start, stop, step, body)
            return ir.ForEachStmt(target, self._expr(node.iter), body)

        if isinstance(node, ast.Pass):
            return None

        if isinstance(node, ast.While):
            self._error(
                node,
                "while is not natively representable by Shortcuts Repeat; use for/range "
                "or provide a backend adapter/plugin",
            )

        if isinstance(node, (ast.Break, ast.Continue)):
            self._error(node, f"{type(node).__name__.lower()} is not supported by the current loop lowering")

        if isinstance(node, (ast.Try, ast.Raise, ast.With, ast.Match, ast.Delete, ast.Global, ast.Nonlocal)):
            self._error(node, f"{type(node).__name__} is not supported")

        if isinstance(node, ast.Return):
            self._error(node, "return is only valid as the final statement of a supported inline function")

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self._error(node, "nested function/class definitions are not supported")

        self._error(node, f"unsupported statement: {type(node).__name__}")

    def _block(self, nodes: Iterable[ast.stmt]) -> tuple[ir.Stmt, ...]:
        out: list[ir.Stmt] = []
        for node in nodes:
            statement = self._stmt(node)
            if statement is not None:
                out.append(statement)
        return tuple(out)

    def _range_args(self, node: ast.expr) -> tuple[ir.Expr, ir.Expr, ir.Expr] | None:
        if not isinstance(node, ast.Call) or self._call_target(node.func) != "range" or node.keywords:
            return None
        args = node.args
        if len(args) == 1:
            return ir.Literal(0), self._expr(args[0]), ir.Literal(1)
        if len(args) == 2:
            return self._expr(args[0]), self._expr(args[1]), ir.Literal(1)
        if len(args) == 3:
            return self._expr(args[0]), self._expr(args[1]), self._expr(args[2])
        self._error(node, "range() expects 1 to 3 positional arguments")

    def _expr(self, node: ast.expr) -> ir.Expr:
        static = self._try_static_eval(node)
        if static is not _NO_STATIC:
            return self._static_to_ir(static)

        if isinstance(node, ast.Constant):
            if node.value is Ellipsis or isinstance(node.value, (complex, bytes)):
                self._error(node, f"unsupported constant {node.value!r}")
            return ir.Literal(node.value)

        if isinstance(node, ast.Name):
            for scope in reversed(self._locals):
                if node.id in scope:
                    return scope[node.id]
            binding = self._lookup_binding(node.id)
            if isinstance(binding, ConstantBinding):
                return self._static_to_ir(binding.value)
            if isinstance(binding, ExternalBinding):
                return ir.Symbol(binding.target)
            if isinstance(binding, FunctionBinding):
                self._register_source_function(binding.function)
                return ir.Symbol(binding.function.qualified_name)
            if isinstance(binding, ModuleBinding):
                return ir.Symbol(binding.module.name)
            imported = self._aliases.get(node.id)
            if imported is not None:
                return ir.Symbol(imported)
            return ir.Var(node.id)

        if isinstance(node, ast.BinOp):
            op = _BINOPS.get(type(node.op))
            if op is None:
                self._error(node, f"unsupported binary operator {type(node.op).__name__}")
            return ir.Binary(op, self._expr(node.left), self._expr(node.right))

        if isinstance(node, ast.UnaryOp):
            op = _UNARYOPS.get(type(node.op))
            if op is None:
                self._error(node, f"unsupported unary operator {type(node.op).__name__}")
            return ir.Unary(op, self._expr(node.operand))

        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or len(node.comparators) != 1:
                self._error(node, "chained comparisons are not supported yet")
            op = _CMPOPS.get(type(node.ops[0]))
            if op is None:
                self._error(node, f"unsupported comparison {type(node.ops[0]).__name__}")
            return ir.Compare(op, self._expr(node.left), self._expr(node.comparators[0]))

        if isinstance(node, ast.BoolOp):
            op = "and" if isinstance(node.op, ast.And) else "or"
            return ir.BoolExpr(op, tuple(self._expr(value) for value in node.values))

        if isinstance(node, ast.Call):
            target = self._call_target(node.func)
            spec = self._functions.get(target)
            if spec is not None:
                return self._inline_function(spec, node)
            args = tuple(self._expr(value) for value in node.args)
            kwargs: list[tuple[str, ir.Expr]] = []
            for keyword in node.keywords:
                if keyword.arg is None:
                    self._error(node, "**kwargs expansion is not supported")
                kwargs.append((keyword.arg, self._expr(keyword.value)))
            return ir.Call(target, args, tuple(kwargs))

        if isinstance(node, (ast.List, ast.Tuple)):
            return ir.ListExpr(tuple(self._expr(value) for value in node.elts))

        if isinstance(node, ast.Dict):
            items: list[tuple[ir.Expr, ir.Expr]] = []
            for key, value in zip(node.keys, node.values, strict=True):
                if key is None:
                    self._error(node, "dictionary unpacking is not supported")
                items.append((self._expr(key), self._expr(value)))
            return ir.DictExpr(tuple(items))

        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Slice):
                self._error(node, "slices are not supported yet")
            return ir.Subscript(self._expr(node.value), self._expr(node.slice))

        if isinstance(node, ast.JoinedStr):
            parts: list[str | ir.Expr] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                    continue
                if isinstance(value, ast.FormattedValue):
                    if value.conversion != -1 or value.format_spec is not None:
                        self._error(value, "f-string conversions and format specs are not supported yet")
                    parts.append(self._expr(value.value))
                    continue
                self._error(value, "unsupported f-string component")
            return ir.FormatString(tuple(parts))

        if isinstance(node, ast.IfExp):
            self._error(node, "conditional expressions are not supported yet; use an if statement")

        if isinstance(node, ast.ListComp):
            return self._list_comprehension(node)

        if isinstance(node, (ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.Lambda, ast.NamedExpr)):
            self._error(node, f"{type(node).__name__} is not supported")

        self._error(node, f"unsupported expression: {type(node).__name__}")


    def _append_stmt(self, node: ast.expr) -> ir.AppendStmt | None:
        """Lower ``name.append(value)`` used as a statement.

        Shortcuts has a native Add to Variable action.  Keeping append as an IR
        statement makes list mutation explicit and also gives list-comprehension
        lowering a small primitive to target.
        """
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            return None
        if node.func.attr != "append":
            return None
        if not isinstance(node.func.value, ast.Name):
            self._error(node, "list.append() currently requires a simple list variable")
        if len(node.args) != 1 or node.keywords:
            self._error(node, "list.append() expects exactly one positional argument")
        target = self._target_name(node.func.value.id)
        return ir.AppendStmt(target, self._expr(node.args[0]))

    def _list_comprehension(self, node: ast.ListComp) -> ir.BlockExpr:
        """Desugar a simple list comprehension into list + loop + append IR.

        ``[expr for x in values if cond]`` becomes conceptually::

            __result = []
            for __x in values:
                if cond:
                    __result.append(expr)

        The target variable is scoped only while compiling the comprehension,
        matching Python 3's non-leaking comprehension variable semantics.
        """
        if len(node.generators) != 1:
            self._error(node, "list comprehensions currently support exactly one for-clause")
        generator = node.generators[0]
        if generator.is_async:
            self._error(node, "async list comprehensions are not supported")
        if not isinstance(generator.target, ast.Name):
            self._error(generator.target, "list-comprehension target must be one simple variable")

        iterable = self._expr(generator.iter)
        self._temp_counter += 1
        suffix = self._temp_counter
        result_name = f"__py2s_listcomp_{suffix}_result"
        item_name = f"__py2s_listcomp_{suffix}_item"

        self._locals.append({generator.target.id: ir.Var(item_name)})
        try:
            value = self._expr(node.elt)
            body: ir.Stmt = ir.AppendStmt(result_name, value)
            for condition in reversed(generator.ifs):
                body = ir.IfStmt(self._expr(condition), (body,), ())
        finally:
            self._locals.pop()

        return ir.BlockExpr(
            (
                ir.Assign(result_name, ir.ListExpr(())),
                ir.ForEachStmt(item_name, iterable, (body,)),
            ),
            ir.Var(result_name),
        )

    def _inline_function(self, spec: _FunctionSpec, call: ast.Call) -> ir.Expr:
        if call.keywords:
            self._error(call, "inline function calls currently use positional arguments only")
        if spec.name in self._inline_stack:
            self._error(call, f"recursive inline function {spec.name!r} is not supported")
        function = spec.node
        parameters = [argument.arg for argument in function.args.args]
        if len(call.args) != len(parameters):
            self._error(call, f"{function.name}() expects {len(parameters)} argument(s), got {len(call.args)}")

        # Compile argument expressions in the caller's environment, then bind them
        # once to mangled locals.  This preserves Python's call-by-value evaluation
        # count even when a parameter is referenced many times in the inlined body.
        arguments = [self._expr(arg) for arg in call.args]
        self._inline_counter += 1
        prefix = f"__py2s_{self._sanitize_name(spec.name)}_{self._inline_counter}_"
        local_names = self._collect_function_locals(function)
        scope = {name: ir.Var(prefix + name) for name in local_names}
        bindings = [ir.Assign(scope[name].name, value) for name, value in zip(parameters, arguments, strict=True)]

        body = self._function_body(function)
        return_node = body[-1]
        assert isinstance(return_node, ast.Return) and return_node.value is not None

        self._inline_stack.append(spec.name)
        self._module_stack.append(spec.module)
        self._locals.append(scope)
        try:
            statements = list(self._block(body[:-1]))
            result = self._expr(return_node.value)
        finally:
            self._locals.pop()
            self._module_stack.pop()
            self._inline_stack.pop()
        return ir.BlockExpr(tuple((*bindings, *statements)), result)

    @staticmethod
    def _collect_function_locals(function: ast.FunctionDef) -> set[str]:
        names = {argument.arg for argument in function.args.args}

        class Collector(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
                if node is function:
                    for statement in node.body:
                        self.visit(statement)
                # Do not descend into nested functions.

            def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
                if isinstance(node.ctx, ast.Store):
                    names.add(node.id)

        Collector().visit(function)
        return names

    def _target_name(self, name: str) -> str:
        for scope in reversed(self._locals):
            value = scope.get(name)
            if isinstance(value, ir.Var):
                return value.name
        return name

    def _lookup_binding(self, name: str) -> SourceBinding | None:
        module = self._module_stack[-1] if self._module_stack else None
        if module is None:
            return None
        return module.bindings.get(name)

    def _call_target(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            binding = self._lookup_binding(node.id)
            if isinstance(binding, FunctionBinding):
                self._register_source_function(binding.function)
                return binding.function.qualified_name
            if isinstance(binding, ExternalBinding):
                return binding.target
            imported = self._aliases.get(node.id)
            if imported is not None:
                return imported
            # Entry-module function definitions are registered under a qualified
            # name when source resolution is active.
            module = self._module_stack[-1] if self._module_stack else None
            if module is not None:
                candidate = module.bindings.get(node.id)
                if isinstance(candidate, FunctionBinding):
                    self._register_source_function(candidate.function)
                    return candidate.function.qualified_name
            return node.id

        if isinstance(node, ast.Attribute):
            binding = self._resolve_attribute_binding(node)
            if isinstance(binding, FunctionBinding):
                self._register_source_function(binding.function)
                return binding.function.qualified_name
            if isinstance(binding, ExternalBinding):
                return binding.target

            parts: list[str] = []
            current = node
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if not isinstance(current, ast.Name):
                self._error(node, "call target must be a name or dotted attribute")
            root_binding = self._lookup_binding(current.id)
            if isinstance(root_binding, ExternalBinding):
                root = root_binding.target
            else:
                root = self._aliases.get(current.id, current.id)
            parts.append(root)
            return ".".join(reversed(parts))

        self._error(node, "call target must be a name or dotted attribute")

    def _resolve_attribute_binding(self, node: ast.Attribute) -> SourceBinding | None:
        attrs: list[str] = []
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            attrs.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name):
            return None
        binding = self._lookup_binding(current.id)
        for attr in reversed(attrs):
            if isinstance(binding, ModuleBinding):
                binding = binding.module.bindings.get(attr)
            elif isinstance(binding, ExternalBinding):
                binding = ExternalBinding(f"{binding.target}.{attr}")
            else:
                return None
        return binding

    def _register_source_function(self, function: SourceFunction) -> None:
        self._functions.setdefault(
            function.qualified_name,
            _FunctionSpec(function.qualified_name, function.node, function.module),
        )
        self._validate_inline_function(function.node)

    def _function_name(self, name: str, module: SourceModule | None) -> str:
        if module is None:
            return name
        binding = module.bindings.get(name)
        if isinstance(binding, FunctionBinding):
            return binding.function.qualified_name
        return f"{module.name}.{name}"

    def _try_static_eval(self, node: ast.expr) -> StaticValue | object:
        if isinstance(node, ast.Constant):
            if node.value is None or isinstance(node.value, (str, int, float, bool)):
                return node.value
            return _NO_STATIC
        if isinstance(node, ast.Name):
            # Locals shadow compile-time constants.
            if any(node.id in scope for scope in self._locals):
                return _NO_STATIC
            binding = self._lookup_binding(node.id)
            if isinstance(binding, ConstantBinding):
                return binding.value
            return _NO_STATIC
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = self._try_static_eval(node.operand)
            if value is _NO_STATIC or isinstance(value, (str, bool, type(None), list, tuple, dict)):
                return _NO_STATIC
            return +value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
            container = self._try_static_eval(node.value)
            key = self._try_static_eval(node.slice)
            if container is _NO_STATIC or key is _NO_STATIC:
                return _NO_STATIC
            try:
                if isinstance(container, (list, tuple)) and isinstance(key, int) and not isinstance(key, bool):
                    return container[key]
                if isinstance(container, dict) and key in container:
                    return container[key]
            except (IndexError, KeyError, TypeError):
                return _NO_STATIC
        if isinstance(node, ast.Attribute):
            binding = self._resolve_attribute_binding(node)
            if isinstance(binding, ConstantBinding):
                return binding.value
        return _NO_STATIC

    def _static_to_ir(self, value: StaticValue) -> ir.Expr:
        if value is None or isinstance(value, (str, int, float, bool)):
            return ir.Literal(value)
        if isinstance(value, (list, tuple)):
            return ir.ListExpr(tuple(self._static_to_ir(item) for item in value))
        if isinstance(value, dict):
            return ir.DictExpr(tuple((self._static_to_ir(key), self._static_to_ir(item)) for key, item in value.items()))
        raise TypeError(f"unsupported static value {value!r}")

    @staticmethod
    def _sanitize_name(name: str) -> str:
        return "".join(character if character.isalnum() else "_" for character in name)

    def _error(self, node: ast.AST, message: str) -> None:
        module = self._module_stack[-1] if self._module_stack else None
        filename = str(module.path) if module is not None else self.filename
        raise CompileError(
            message,
            filename=filename,
            lineno=getattr(node, "lineno", None),
            col_offset=getattr(node, "col_offset", None),
        )


_NO_STATIC = object()
