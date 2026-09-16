"""Notification intrinsics."""

from ._runtime import compile_only


def notify(body: object, /, title: object = "", *, sound: bool = True) -> None:
    """Post a local notification from the running shortcut."""
    compile_only()
