"""Reusable image preparation and decoding utilities."""

from typing import Literal

from ios.types import ShortcutContent
from ._runtime import compile_only


type ImageDecodeMode = Literal["grayscale", "rgb", "bgr"]


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
    """Decode a supported 24/32-bit BMP into normalized grayscale pixels.

    The Shortcuts backend reads the BMP header at runtime, honors the pixel-data
    offset and row padding, and accepts BI_RGB 24-bit BGR / 32-bit BGRA plus the
    standard byte-aligned 32-bit BI_BITFIELDS layout (B, G, R, X/A). Pixels are
    returned top-to-bottom in row-major order as values in ``[0, 1]``.

    This utility is intentionally implemented by the compiler rather than by an
    iOS API: it expands to ordinary Shortcuts text/dictionary/math actions over
    the backend's Base64-backed ``bytes`` representation.
    """
    return compile_only()


def decode_image(
    value: ShortcutContent,
    /,
    *,
    width: int,
    height: int,
    mode: ImageDecodeMode = "grayscale",
    invert: bool = False,
) -> list[float]:
    """Decode image-like Shortcut content into normalized pixels.

    The Shortcuts backend coerces ``value`` to an image and converts the original
    dimensions to a stable BMP intermediate. Resizing is then performed by the
    generated workflow itself with a fixed 2x2 supersampling kernel, avoiding the
    platform Resize Image action and its implementation-dependent sampling. ``mode``
    is ``"grayscale"`` for one value per pixel or ``"rgb"`` / ``"bgr"`` for
    interleaved three-channel output. Values are normalized to ``[0, 1]``.
    """
    return compile_only()
