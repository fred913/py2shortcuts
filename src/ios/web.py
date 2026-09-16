"""HTTP and URL intrinsics."""

from ._runtime import compile_only
from .types import HTTPMethod, JSONValue, ShortcutContent


def request(url: object, /, *, method: HTTPMethod = "GET") -> ShortcutContent:
    """Perform a basic HTTP request and return the polymorphic Shortcuts content."""
    return compile_only()


def get_text(url: object, /) -> str:
    """GET a URL and coerce the response to text."""
    return compile_only()


def get_json(url: object, /) -> dict[str, JSONValue]:
    """GET a URL and coerce its response to a Shortcuts dictionary."""
    return compile_only()


def open(url: object, /) -> None:
    """Open a URL with the system URL handler."""
    compile_only()
