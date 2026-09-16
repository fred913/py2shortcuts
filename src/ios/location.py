"""Location and Maps intrinsics."""

from ._runtime import compile_only
from .types import Location


def current() -> Location:
    """Get the device's current location using best accuracy."""
    return compile_only()


def maps_url(location: Location, /) -> str:
    """Create an Apple Maps URL for a location."""
    return compile_only()
