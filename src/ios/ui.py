"""User-interface intrinsics backed by first-party Shortcuts actions."""

from ._runtime import compile_only


def alert(message: object, /, title: object = "") -> None:
    """Show a modal alert."""
    compile_only()


def ask_text(prompt: object = "", /) -> str:
    """Ask the user for textual input and return the supplied string."""
    return compile_only()


def show(value: object, /) -> None:
    """Show a result using the Shortcuts result UI."""
    compile_only()
