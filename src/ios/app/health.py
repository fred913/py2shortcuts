"""Health intrinsics whose Shortcuts wire format is known to py2shortcuts."""

from .._runtime import compile_only
from ..types import HealthSample, SleepStage


def log_sleep(start: object, end: object, /, *, stage: SleepStage) -> HealthSample:
    """Log one Health sleep-category sample between ``start`` and ``end``.

    ``start`` and ``end`` are normally ISO-8601 strings or values produced by
    other compiler intrinsics. ``stage`` is intentionally a literal-like enum
    because the Shortcuts Health action encodes it as an enumeration.
    """
    return compile_only()
