from __future__ import annotations


class CompileError(Exception):
    """A source-level error raised for unsupported or invalid Python."""

    def __init__(
        self,
        message: str,
        *,
        filename: str = "<string>",
        lineno: int | None = None,
        col_offset: int | None = None,
    ) -> None:
        self.message = message
        self.filename = filename
        self.lineno = lineno
        self.col_offset = col_offset
        location = filename
        if lineno is not None:
            location += f":{lineno}"
            if col_offset is not None:
                location += f":{col_offset + 1}"
        super().__init__(f"{location}: {message}")
