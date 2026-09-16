"""Device information and common device-control intrinsics."""

from typing import Literal, overload

from ._runtime import compile_only
from .types import DeviceDetail, FlashlightMode


@overload
def detail(kind: Literal["Device Name", "Device Model", "System Version"], /) -> str: ...


@overload
def detail(
    kind: Literal["Screen Width", "Screen Height", "Current Volume", "Current Brightness"],
    /,
) -> float: ...


def detail(kind: DeviceDetail, /) -> str | float:
    """Get one of the values exposed by Shortcuts' Get Device Details action."""
    return compile_only()


def name() -> str:
    return compile_only()


def model() -> str:
    return compile_only()


def system_version() -> str:
    return compile_only()


def screen_width() -> float:
    return compile_only()


def screen_height() -> float:
    return compile_only()


def volume() -> float:
    return compile_only()


def brightness() -> float:
    return compile_only()


def battery_level() -> float:
    """Return battery percentage in the range 0..100."""
    return compile_only()


def set_wifi(enabled: bool, /) -> None:
    compile_only()


def set_bluetooth(enabled: bool, /) -> None:
    compile_only()


def set_cellular_data(enabled: bool, /) -> None:
    compile_only()


def set_low_power_mode(enabled: bool = True, /) -> None:
    compile_only()


def set_brightness(level: float, /) -> None:
    """Set brightness using Shortcuts' native 0..1 level."""
    compile_only()


def set_volume(level: float, /) -> None:
    """Set output volume using Shortcuts' native 0..1 level."""
    compile_only()


def set_flashlight(mode: FlashlightMode, /) -> None:
    compile_only()
