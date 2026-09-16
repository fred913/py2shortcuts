"""System clipboard intrinsics."""

from ._runtime import compile_only
from .types import ShortcutContent


def get() -> ShortcutContent:
    """Return the current clipboard contents without coercing their type."""
    return compile_only()


def get_text() -> str:
    """Return the current clipboard contents coerced to text."""
    return compile_only()


def set(value: object, /, *, local_only: bool = False) -> None:
    """Copy a value to the clipboard."""
    compile_only()
