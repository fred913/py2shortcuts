"""Low-level Shortcuts escape hatches."""

from typing import Never

from ._runtime import compile_only
from .types import ShortcutContent


def shortcut_input() -> ShortcutContent:
    """Return the shortcut's incoming content (the ExtensionInput magic value)."""
    return compile_only()


def comment(text: str, /) -> None:
    compile_only()


def raw_action(identifier: str, /, *, output: str | None = None, **parameters: object) -> ShortcutContent | None:
    """Emit a raw action. Prefer a typed :mod:`ios` intrinsic when one exists."""
    return compile_only()


def stop() -> Never:
    """Stop the shortcut immediately."""
    return compile_only()
