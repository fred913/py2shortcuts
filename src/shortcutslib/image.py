"""Reusable image preparation and decoding utilities."""

from ios.types import ShortcutContent
from ._runtime import compile_only


def to_bmp_bytes(value: ShortcutContent, /, *, width: int, height: int) -> bytes:
    """Coerce content to an image, resize it, convert to BMP, and expose bytes."""
    return compile_only()


def decode_bmp_grayscale(
    data: bytes,
    /,
    *,
    width: int,
    height: int,
    invert: bool = False,
) -> list[float]:
    """Decode an uncompressed 24/32-bit BMP into normalized grayscale pixels.

    The Shortcuts backend reads the BMP header at runtime, honors the pixel-data
    offset and row padding, and accepts both 24-bit BGR and 32-bit BGRA output.
    Pixels are returned top-to-bottom in row-major order as values in ``[0, 1]``.

    This utility is intentionally implemented by the compiler rather than by an
    iOS API: it expands to ordinary Shortcuts text/dictionary/math actions over
    the backend's Base64-backed ``bytes`` representation.
    """
    return compile_only()
