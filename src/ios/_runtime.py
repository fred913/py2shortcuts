"""Runtime guard shared by the compile-time-only :mod:`ios` facade."""

from typing import Never


def compile_only() -> Never:
    """Fail if an ``ios`` intrinsic is accidentally executed by CPython."""
    raise RuntimeError(
        "The ios package installed by py2shortcuts is a compile-time API facade. "
        "Compile this source with py2shortcuts instead of executing the intrinsic in CPython."
    )
