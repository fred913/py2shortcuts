"""Compiler plugin for the tiny MNIST MLP used by the showcase."""

from __future__ import annotations

from py2shortcuts.backend.shortcuts import ValueRef
from py2shortcuts.errors import CompileError
from py2shortcuts.plist import action

from weights import B1, B2, HIDDEN_SIZE, INPUT_SIZE, NUM_CLASSES, W1, W2


def predict(pixels: list[float]) -> int:
    """Return the predicted digit. This function is compile-time only."""
    raise RuntimeError("model.predict() is compiled by py2shortcuts; do not execute it directly")


def _list_item(backend, values: ValueRef, index: int) -> ValueRef:
    result = action(
        "getitemfromlist",
        WFInput=values.attachment(),
        WFItemSpecifier="Item At Index",
        WFItemIndex=str(index + 1),
    )
    backend.actions.append(result)
    return ValueRef.action(result, "Item from List")


def _add_scaled(backend, total: ValueRef, value: ValueRef, weight: float) -> ValueRef:
    if weight == 0.0:
        return total
    product = backend.emit_math(value, "*", repr(float(weight)))
    return backend.emit_math(total, "+", product)


def _relu(backend, value: ValueRef) -> ValueRef:
    group = backend.new_uuid()
    backend.actions.append(
        action(
            "conditional",
            GroupingIdentifier=group,
            WFControlFlowMode=0,
            WFInput=value.condition_input(),
            WFCondition=2,  # greater than
            WFNumberValue="0",
        )
    )
    backend.emit_math(value, "+", "0")
    backend.actions.append(action("conditional", GroupingIdentifier=group, WFControlFlowMode=1))
    backend.emit_literal(0)
    end = action("conditional", GroupingIdentifier=group, WFControlFlowMode=2)
    backend.actions.append(end)
    return ValueRef.action(end, "If Result")


def _argmax(backend, values: list[ValueRef]) -> ValueRef:
    if not values:
        raise CompileError("MNIST model has no output classes")

    token = backend.new_uuid().replace("-", "")
    best_value_name = f"__py2s_mnist_best_value_{token}"
    best_index_name = f"__py2s_mnist_best_index_{token}"

    backend.actions.append(
        action("setvariable", WFVariableName=best_value_name, WFInput=values[0].attachment())
    )
    backend.var_types[best_value_name] = "number"
    zero = backend.emit_literal(0)
    backend.actions.append(
        action("setvariable", WFVariableName=best_index_name, WFInput=zero.attachment())
    )
    backend.var_types[best_index_name] = "number"

    for index, current in enumerate(values[1:], start=1):
        group = backend.new_uuid()
        backend.actions.append(
            action(
                "conditional",
                GroupingIdentifier=group,
                WFControlFlowMode=0,
                WFInput=current.condition_input(),
                WFCondition=2,  # greater than
                WFNumberValue=ValueRef.variable(best_value_name).attachment(),
            )
        )
        backend.actions.append(
            action("setvariable", WFVariableName=best_value_name, WFInput=current.attachment())
        )
        idx = backend.emit_literal(index)
        backend.actions.append(
            action("setvariable", WFVariableName=best_index_name, WFInput=idx.attachment())
        )
        backend.actions.append(action("conditional", GroupingIdentifier=group, WFControlFlowMode=2))

    return ValueRef.variable(best_index_name)


def register(registry):
    @registry.call("model.predict", result_type="number")
    def lower_predict(backend, call):
        if len(call.args) != 1 or call.kwargs:
            raise CompileError("model.predict(pixels) expects exactly one positional argument")
        if len(W1) != HIDDEN_SIZE or any(len(row) != INPUT_SIZE for row in W1):
            raise CompileError("weights.py W1 shape does not match model metadata")
        if len(B1) != HIDDEN_SIZE:
            raise CompileError("weights.py B1 shape does not match model metadata")
        if len(W2) != NUM_CLASSES or any(len(row) != HIDDEN_SIZE for row in W2):
            raise CompileError("weights.py W2 shape does not match model metadata")
        if len(B2) != NUM_CLASSES:
            raise CompileError("weights.py B2 shape does not match model metadata")

        pixels = backend.require_value(backend.emit_expr(call.args[0]), context="MNIST pixels")
        inputs = [_list_item(backend, pixels, index) for index in range(INPUT_SIZE)]

        hidden: list[ValueRef] = []
        for row, bias in zip(W1, B1, strict=True):
            total = backend.emit_literal(float(bias))
            for value, weight in zip(inputs, row, strict=True):
                total = _add_scaled(backend, total, value, float(weight))
            hidden.append(_relu(backend, total))

        outputs: list[ValueRef] = []
        for row, bias in zip(W2, B2, strict=True):
            total = backend.emit_literal(float(bias))
            for value, weight in zip(hidden, row, strict=True):
                total = _add_scaled(backend, total, value, float(weight))
            outputs.append(total)

        return _argmax(backend, outputs)
