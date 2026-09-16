from __future__ import annotations

from py2shortcuts import ir
from py2shortcuts.errors import CompileError
from py2shortcuts.plist import action


def dot(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("dot requires same-length vectors")
    return sum(x * y for x, y in zip(a, b))


def add(a: list[float], b: list[float]) -> list[float]:
    if len(a) != len(b):
        raise ValueError("add requires same-length vectors")
    return [x + y for x, y in zip(a, b)]


def argmax(values: list[float]) -> int:
    if not values:
        raise ValueError("argmax requires at least one value")
    return max(range(len(values)), key=values.__getitem__)


def _list_items(expr: ir.Expr, *, name: str) -> tuple[ir.Expr, ...]:
    if not isinstance(expr, ir.ListExpr):
        raise CompileError(f"{name} must currently be a statically-shaped list")
    return expr.items


def _set_number(backend, name: str, value) -> None:
    backend.actions.append(action("setvariable", WFVariableName=name, WFInput=value.attachment()))
    backend.var_types[name] = "number"


def register(registry):
    @registry.call("tensors.dot", result_type="number")
    def lower_dot(backend, call):
        if len(call.args) != 2 or call.kwargs:
            raise CompileError("tensors.dot expects exactly two positional arguments")
        left = _list_items(call.args[0], name="tensors.dot() left operand")
        right = _list_items(call.args[1], name="tensors.dot() right operand")
        if len(left) != len(right):
            raise CompileError("tensors.dot requires same-length vectors")
        if not left:
            return backend.emit_literal(0)

        total = None
        for x, y in zip(left, right, strict=True):
            product = backend.require_value(
                backend.emit_expr(ir.Binary("*", x, y)), context="tensors.dot product"
            )
            total = product if total is None else backend.emit_math(total, "+", product)
        return total

    @registry.call("tensors.add", result_type="list")
    def lower_add(backend, call):
        if len(call.args) != 2 or call.kwargs:
            raise CompileError("tensors.add expects exactly two positional arguments")
        left = _list_items(call.args[0], name="tensors.add() left operand")
        right = _list_items(call.args[1], name="tensors.add() right operand")
        if len(left) != len(right):
            raise CompileError("tensors.add requires same-length vectors")
        return backend.emit_expr(
            ir.ListExpr(tuple(ir.Binary("+", x, y) for x, y in zip(left, right, strict=True)))
        )

    @registry.call("tensors.argmax", result_type="number")
    def lower_argmax(backend, call):
        if len(call.args) != 1 or call.kwargs:
            raise CompileError("tensors.argmax expects exactly one positional argument")
        items = _list_items(call.args[0], name="tensors.argmax() argument")
        if not items:
            raise CompileError("tensors.argmax requires at least one value")

        token = backend.new_uuid().replace("-", "")
        best_value_name = f"__py2s_argmax_value_{token}"
        best_index_name = f"__py2s_argmax_index_{token}"
        current_name = f"__py2s_argmax_current_{token}"

        first = backend.require_value(backend.emit_expr(items[0]), context="tensors.argmax first value")
        _set_number(backend, best_value_name, first)
        _set_number(backend, best_index_name, backend.emit_literal(0))

        for index, item in enumerate(items[1:], start=1):
            current = backend.require_value(backend.emit_expr(item), context="tensors.argmax value")
            _set_number(backend, current_name, current)

            group = backend.new_uuid()
            params = backend.condition_params(
                ir.Compare(">", ir.Var(current_name), ir.Var(best_value_name))
            )
            backend.actions.append(
                action("conditional", GroupingIdentifier=group, WFControlFlowMode=0, **params)
            )
            current_ref = backend.require_value(
                backend.emit_expr(ir.Var(current_name)), context="tensors.argmax current value"
            )
            _set_number(backend, best_value_name, current_ref)
            _set_number(backend, best_index_name, backend.emit_literal(index))
            backend.actions.append(
                action("conditional", GroupingIdentifier=group, WFControlFlowMode=2)
            )

        return backend.require_value(
            backend.emit_expr(ir.Var(best_index_name)), context="tensors.argmax result"
        )
