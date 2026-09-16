"""Editor/type-checker facade for compile-time Shortcuts intrinsics.

These functions are not a Python runtime implementation. Source code using
this module is intended to be consumed by :mod:`py2shortcuts`.
"""

from __future__ import annotations

from typing import Any, Never


def _compile_only() -> Never:
    raise RuntimeError("py2shortcuts.shortcuts intrinsics are compile-time only; compile this file with py2shortcuts")


def comment(text: str) -> None:
    _compile_only()


def notification(body: object, title: object = "") -> None:
    _compile_only()


def alert(message: object, title: object = "") -> None:
    _compile_only()


def get_url(url: object, *, method: str = "GET") -> Any:
    _compile_only()


def open_url(url: object) -> None:
    _compile_only()


def raw_action(identifier: str, *, output: str | None = None, **parameters: object) -> Any:
    _compile_only()
