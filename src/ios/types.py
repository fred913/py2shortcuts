"""Public type vocabulary for the compile-time :mod:`ios` API."""

from typing import Literal, final


type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]
type HTTPMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
type DeviceDetail = Literal[
    "Device Name",
    "Device Model",
    "System Version",
    "Screen Width",
    "Screen Height",
    "Current Volume",
    "Current Brightness",
]
type FlashlightMode = Literal["Off", "On", "Toggle"]
type SleepStage = Literal[
    "Awake",
    "Asleep",
    "Core",
    "Deep",
    "REM",
    "Asleep Core",
    "Asleep Deep",
    "Asleep REM",
]


class ShortcutContent:
    """Opaque Shortcuts content item returned by actions with polymorphic output."""


@final
class Location:
    """Opaque Core Location value produced by ``ios.location.current()``."""


@final
class HealthSample:
    """Opaque Health sample returned by a Health logging action."""
