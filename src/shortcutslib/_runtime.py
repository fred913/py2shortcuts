from typing import Never

def compile_only() -> Never:
    raise RuntimeError("shortcutslib utilities are compile-time only; compile this source with py2shortcuts")
