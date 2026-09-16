"""Python AST frontend for the supported py2shortcuts language subset."""

from __future__ import annotations

import ast
from collections.abc import Iterable

from . import ir
from .errors import CompileError


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


class PythonFrontend:
    """Lower a deliberately small Python subset into :mod:`py2shortcuts.ir`."""

    def __init__(self, *, filename: str = "<string>") -> None:
        self.filename = filename
        self._functions: dict[str, ast.FunctionDef] = {}
        self._aliases: dict[str, str] = {}
        self._inline_stack: list[str] = []
        self._locals: list[dict[str, ir.Expr]] = []

    def compile(self, source: str) -> ir.Module:
        try:
            tree = ast.parse(source, filename=self.filename)
        except SyntaxError as error:
            raise CompileError(
                error.msg,
                filename=self.filename,
                lineno=error.lineno,
                col_offset=(error.offset - 1) if error.offset else None,
            ) from error

        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                if node.name in self._functions:
                    self._error(node, f"duplicate function definition {node.name!r}")
                self._functions[node.name] = node
            elif isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef)):
                self._error(node, f"{type(node).__name__} is not supported")

        statements: list[ir.Stmt] = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                self._validate_inline_function(node)
                continue
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self._record_import(node)
                continue
            statement = self._stmt(node)
            if statement is not None:
                statements.append(statement)
        return ir.Module(tuple(statements))

    def _record_import(self, node: ast.Import | ast.ImportFrom) -> None:
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
        body = list(node.body)
        if body and self._is_docstring(body[0]):
            body.pop(0)
        if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
            self._error(
                node,
                "user functions must currently be a single `return <expression>`; "
                "use a backend plugin for more complex helpers",
            )

    @staticmethod
    def _is_docstring(node: ast.stmt) -> bool:
        return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)

    def _stmt(self, node: ast.stmt) -> ir.Stmt | None:
        if isinstance(node, ast.Expr):
            if self._is_docstring(node):
                return None
            return ir.ExprStmt(self._expr(node.value))

        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                self._error(node, "only assignment to one simple variable is supported")
            return ir.Assign(node.targets[0].id, self._expr(node.value))

        if isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name) or node.value is None:
                self._error(node, "only initialized annotations on simple variables are supported")
            return ir.Assign(node.target.id, self._expr(node.value))

        if isinstance(node, ast.AugAssign):
            if not isinstance(node.target, ast.Name):
                self._error(node, "augmented assignment requires a simple variable")
            op = _BINOPS.get(type(node.op))
            if op is None:
                self._error(node, f"unsupported augmented operator {type(node.op).__name__}")
            return ir.Assign(node.target.id, ir.Binary(op, ir.Var(node.target.id), self._expr(node.value)))

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
            body = self._block(node.body)
            range_args = self._range_args(node.iter)
            if range_args is not None:
                start, stop, step = range_args
                if not isinstance(step, ir.Literal) or step.value != 1:
                    self._error(node, "range() currently requires step=1")
                return ir.ForRangeStmt(node.target.id, start, stop, step, body)
            return ir.ForEachStmt(node.target.id, self._expr(node.iter), body)

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
            self._error(node, "return is only valid inside a supported inline function")

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
        if isinstance(node, ast.Constant):
            if node.value is Ellipsis or isinstance(node.value, (complex, bytes)):
                self._error(node, f"unsupported constant {node.value!r}")
            return ir.Literal(node.value)

        if isinstance(node, ast.Name):
            for scope in reversed(self._locals):
                if node.id in scope:
                    return scope[node.id]
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
            if target in self._functions:
                return self._inline_function(target, node)
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

        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.Lambda, ast.NamedExpr)):
            self._error(node, f"{type(node).__name__} is not supported")

        self._error(node, f"unsupported expression: {type(node).__name__}")

    def _inline_function(self, name: str, call: ast.Call) -> ir.Expr:
        if call.keywords:
            self._error(call, "inline function calls currently use positional arguments only")
        if name in self._inline_stack:
            self._error(call, f"recursive inline function {name!r} is not supported")
        function = self._functions[name]
        parameters = [argument.arg for argument in function.args.args]
        if len(call.args) != len(parameters):
            self._error(call, f"{name}() expects {len(parameters)} argument(s), got {len(call.args)}")
        arguments = [self._expr(arg) for arg in call.args]
        if not all(self._is_pure(argument) for argument in arguments):
            self._error(
                call,
                f"arguments to inline function {name}() must currently be side-effect-free; "
                "bind input()/plugin calls to variables first",
            )
        body = list(function.body)
        if body and self._is_docstring(body[0]):
            body.pop(0)
        return_node = body[0]
        assert isinstance(return_node, ast.Return) and return_node.value is not None
        self._inline_stack.append(name)
        self._locals.append(dict(zip(parameters, arguments, strict=True)))
        try:
            return self._expr(return_node.value)
        finally:
            self._locals.pop()
            self._inline_stack.pop()

    @staticmethod
    def _is_pure(expr: ir.Expr) -> bool:
        if isinstance(expr, (ir.Literal, ir.Var)):
            return True
        if isinstance(expr, ir.Binary):
            return PythonFrontend._is_pure(expr.left) and PythonFrontend._is_pure(expr.right)
        if isinstance(expr, ir.Unary):
            return PythonFrontend._is_pure(expr.operand)
        if isinstance(expr, ir.Compare):
            return PythonFrontend._is_pure(expr.left) and PythonFrontend._is_pure(expr.right)
        if isinstance(expr, ir.BoolExpr):
            return all(PythonFrontend._is_pure(value) for value in expr.values)
        if isinstance(expr, ir.FormatString):
            return all(isinstance(part, str) or PythonFrontend._is_pure(part) for part in expr.parts)
        return False

    def _call_target(self, node: ast.expr) -> str:
        parts: list[str] = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name):
            self._error(node, "call target must be a name or dotted attribute")
        root = self._aliases.get(current.id, current.id)
        parts.append(root)
        return ".".join(reversed(parts))

    def _error(self, node: ast.AST, message: str) -> None:
        raise CompileError(
            message,
            filename=self.filename,
            lineno=getattr(node, "lineno", None),
            col_offset=getattr(node, "col_offset", None),
        )
