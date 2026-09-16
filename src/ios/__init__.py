"""Typed compile-time iOS API facade installed by :mod:`py2shortcuts`.

The functions in this package describe native Shortcuts actions to static
analysis tools and editors. They are not a CPython implementation of iOS APIs.
"""

from . import app, clipboard, content, data, device, images, location, notifications, shortcuts, ui, web

__all__ = [
    "app",
    "clipboard",
    "content",
    "data",
    "device",
    "images",
    "location",
    "notifications",
    "shortcuts",
    "ui",
    "web",
]
