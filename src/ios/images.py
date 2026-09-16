"""Native Shortcuts image transforms."""

from typing import Literal

from ._runtime import compile_only
from .content import Image

type ImageFormat = Literal["BMP", "GIF", "HEIF", "JPEG", "PDF", "PNG", "TIFF"]


def resize(image: Image, /, *, width: int, height: int) -> Image:
    return compile_only()


def convert(image: Image, /, *, format: ImageFormat) -> Image:
    return compile_only()
