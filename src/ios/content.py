"""Shortcuts Content Graph types and explicit runtime coercions."""

from typing import final

from ._runtime import compile_only
from .types import ShortcutContent


@final
class Image(ShortcutContent):
    """An image value accepted by image actions."""


def coerce[T: ShortcutContent](value: ShortcutContent, target: type[T], /) -> T:
    """Ask Shortcuts' Content Graph to view ``value`` as ``target`` at runtime."""
    return compile_only()
