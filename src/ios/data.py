"""Binary-data bridge for the Shortcuts backend."""

from ._runtime import compile_only
from .types import ShortcutContent


def as_bytes(value: ShortcutContent, /) -> bytes:
    """Expose binary content as the compiler's byte-sequence abstraction.

    The Shortcuts backend currently transports this as Base64 text; callers
    should depend on ``bytes`` semantics rather than that representation.
    """
    return compile_only()
