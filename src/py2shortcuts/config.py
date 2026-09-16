"""Project-level shortcut metadata loaded from ``py2shortcuts.toml``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from .errors import CompileError

_INPUT_TYPES = {
    "images": "WFImageContentItem",
    "files": "WFGenericFileContentItem",
    "pdfs": "WFPDFContentItem",
    "safari-webpages": "WFSafariWebPageContentItem",
    "text": "WFStringContentItem",
    "urls": "WFURLContentItem",
}

@dataclass(frozen=True, slots=True)
class ShortcutConfig:
    name: str | None = None
    input_classes: tuple[str, ...] = ()
    workflow_types: tuple[str, ...] = ()


def load_project_config(project_dir: Path) -> ShortcutConfig:
    path = project_dir / "py2shortcuts.toml"
    if not path.is_file():
        return ShortcutConfig()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as error:
        raise CompileError(f"cannot read {path}: {error}") from error
    shortcut = data.get("shortcut", {})
    if not isinstance(shortcut, dict):
        raise CompileError("[shortcut] must be a TOML table")
    name = shortcut.get("name")
    if name is not None and not isinstance(name, str):
        raise CompileError("shortcut.name must be a string")
    input_table = shortcut.get("input", {})
    if not isinstance(input_table, dict):
        raise CompileError("[shortcut.input] must be a TOML table")
    raw_types = input_table.get("types", [])
    if not isinstance(raw_types, list) or not all(isinstance(item, str) for item in raw_types):
        raise CompileError("shortcut.input.types must be an array of strings")
    unknown = [item for item in raw_types if item not in _INPUT_TYPES]
    if unknown:
        raise CompileError(f"unsupported shortcut input type(s): {', '.join(unknown)}")
    classes = tuple(dict.fromkeys(_INPUT_TYPES[item] for item in raw_types))
    show_share_sheet = shortcut.get("show-in-share-sheet", bool(classes))
    if not isinstance(show_share_sheet, bool):
        raise CompileError("shortcut.show-in-share-sheet must be a bool")
    workflow_types = ("ActionExtension",) if show_share_sheet else ()
    return ShortcutConfig(name=name, input_classes=classes, workflow_types=workflow_types)
