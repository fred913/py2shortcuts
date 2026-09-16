"""Backend call-lowering plugin registry.

A call adapter maps a Python target such as ``ios.device.battery_level`` to a
Shortcuts backend handler. Adapters can also declare a compact result type so
later compiler passes keep useful type information after assignment.
"""

from __future__ import annotations

from collections.abc import Callable, ItemsView
from dataclasses import dataclass
from typing import Literal, Protocol, TYPE_CHECKING

from .ir import Call

if TYPE_CHECKING:
    from .backend.shortcuts import ShortcutsBackend, ValueRef


type ResultType = Literal["unknown", "none", "bool", "number", "text", "bytes", "list", "dict"]


class CallLowerer(Protocol):
    def __call__(self, backend: ShortcutsBackend, call: Call, /) -> ValueRef | None: ...


@dataclass(frozen=True, slots=True)
class CallAdapter:
    lowerer: CallLowerer
    result_type: ResultType = "unknown"


class PluginRegistry:
    def __init__(self) -> None:
        self._calls: dict[str, CallAdapter] = {}

    def register_call(
        self,
        target: str,
        lowerer: CallLowerer,
        *,
        result_type: ResultType = "unknown",
    ) -> None:
        if not target or target.startswith(".") or target.endswith("."):
            raise ValueError(f"Invalid plugin target: {target!r}")
        if target in self._calls:
            raise ValueError(f"A lowerer is already registered for {target!r}")
        self._calls[target] = CallAdapter(lowerer, result_type)

    def call(
        self,
        target: str,
        *,
        result_type: ResultType = "unknown",
    ) -> Callable[[CallLowerer], CallLowerer]:
        def decorator(lowerer: CallLowerer) -> CallLowerer:
            self.register_call(target, lowerer, result_type=result_type)
            return lowerer

        return decorator

    def get_call(self, target: str) -> CallLowerer | None:
        adapter = self._calls.get(target)
        return None if adapter is None else adapter.lowerer

    def result_type(self, target: str) -> ResultType:
        adapter = self._calls.get(target)
        return "unknown" if adapter is None else adapter.result_type

    def items(self) -> ItemsView[str, CallAdapter]:
        return self._calls.items()

    def extend(self, other: PluginRegistry, *, override: bool = False) -> None:
        for target, adapter in other.items():
            if target in self._calls and not override:
                raise ValueError(f"A lowerer is already registered for {target!r}")
            self._calls[target] = adapter

    def copy(self) -> PluginRegistry:
        result = PluginRegistry()
        result._calls.update(self._calls)
        return result
