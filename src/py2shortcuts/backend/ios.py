"""Built-in adapters for the typed :mod:`ios` compile-time facade."""

from __future__ import annotations

from collections.abc import Callable

from .. import ir
from ..errors import CompileError
from ..plist import PlistValue, action, raw_action
from ..plugins import PluginRegistry
from .shortcuts import ShortcutsBackend, ValueRef


_DEVICE_DETAILS = {
    "Device Name",
    "Device Model",
    "System Version",
    "Screen Width",
    "Screen Height",
    "Current Volume",
    "Current Brightness",
}
_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_FLASHLIGHT_MODES = {"Off", "On", "Toggle"}
_SLEEP_STAGES = {
    "Awake",
    "Asleep",
    "Core",
    "Deep",
    "REM",
    "Asleep Core",
    "Asleep Deep",
    "Asleep REM",
}


def _unknown_kwargs(call: ir.Call, allowed: set[str]) -> set[str]:
    return {name for name, _ in call.kwargs} - allowed


def _literal_string(expression: ir.Expr | None, *, name: str) -> str:
    if isinstance(expression, ir.Literal) and isinstance(expression.value, str):
        return expression.value
    raise CompileError(f"{name} must be a literal string")


def _literal_bool(expression: ir.Expr | None, *, name: str) -> bool:
    if isinstance(expression, ir.Literal) and isinstance(expression.value, bool):
        return expression.value
    raise CompileError(f"{name} must be a literal bool")


def _literal_number(expression: ir.Expr | None, *, name: str) -> int | float:
    if (
        isinstance(expression, ir.Literal)
        and isinstance(expression.value, (int, float))
        and not isinstance(expression.value, bool)
    ):
        return expression.value
    raise CompileError(f"{name} must currently be a literal int or float")


def _one_arg(call: ir.Call, *, display: str) -> ir.Expr:
    if len(call.args) != 1:
        raise CompileError(f"{display} expects exactly one positional argument")
    return call.args[0]


def _no_args(call: ir.Call, *, display: str) -> None:
    if call.args or call.kwargs:
        raise CompileError(f"{display} does not accept arguments")


def _text_token(backend: ShortcutsBackend, expression: ir.Expr) -> PlistValue:
    value = backend.text_param(expression)
    if isinstance(value, str):
        return backend.static_text_token(value)
    return value



_CONTENT_CLASSES = {
    "ios.content.Image": "WFImageContentItem",
}
_IMAGE_FORMATS = {"BMP", "GIF", "HEIF", "JPEG", "PDF", "PNG", "TIFF"}


def _literal_int(expression: ir.Expr | None, *, name: str) -> int:
    if isinstance(expression, ir.Literal) and isinstance(expression.value, int) and not isinstance(expression.value, bool):
        return expression.value
    raise CompileError(f"{name} must currently be a literal int")


def _shortcut_input(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    _no_args(call, display="ios.shortcuts.input()")
    backend.uses_shortcut_input = True
    return ValueRef.shortcut_input()


def _content_coerce(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    if len(call.args) != 2 or call.kwargs:
        raise CompileError("ios.content.coerce(value, target) expects two positional arguments")
    value = backend.require_value(backend.emit_expr(call.args[0]), context="content coercion")
    target = call.args[1]
    if not isinstance(target, ir.Symbol):
        raise CompileError("ios.content.coerce() target must be an imported ios.content type")
    item_class = _CONTENT_CLASSES.get(target.name)
    if item_class is None:
        raise CompileError(f"unsupported Content Graph coercion target {target.name!r}")
    return value.coerced(item_class)


def _image_resize(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    image_expr = _one_arg(call, display="ios.images.resize(image, *, width=..., height=...)")
    unknown = _unknown_kwargs(call, {"width", "height"})
    if unknown:
        raise CompileError(f"ios.images.resize() does not accept keyword(s): {', '.join(sorted(unknown))}")
    width = _literal_int(call.keyword("width"), name="image width")
    height = _literal_int(call.keyword("height"), name="image height")
    if width <= 0 or height <= 0:
        raise CompileError("image width and height must be positive")
    image = backend.require_value(backend.emit_expr(image_expr), context="image resize")
    result = action(
        "image.resize",
        WFImage=image.attachment(),
        WFImageResizeKey="Size",
        WFImageResizeWidth=str(width),
        WFImageResizeHeight=str(height),
    )
    backend.actions.append(result)
    return ValueRef.action(result, "Resized Image")


def _image_convert(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    image_expr = _one_arg(call, display="ios.images.convert(image, *, format=...)")
    unknown = _unknown_kwargs(call, {"format"})
    if unknown:
        raise CompileError(f"ios.images.convert() does not accept keyword(s): {', '.join(sorted(unknown))}")
    fmt = _literal_string(call.keyword("format"), name="image format").upper()
    if fmt not in _IMAGE_FORMATS:
        raise CompileError(f"unsupported image format {fmt!r}")
    image = backend.require_value(backend.emit_expr(image_expr), context="image conversion")
    result = action(
        "image.convert",
        WFInput=image.attachment(),
        WFImageFormat=fmt,
        WFImagePreserveMetadata=False,
    )
    backend.actions.append(result)
    return ValueRef.action(result, "Converted Image")


def _data_as_bytes(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    value_expr = _one_arg(call, display="ios.data.as_bytes(value)")
    if call.kwargs:
        raise CompileError("ios.data.as_bytes() does not accept keyword arguments")
    value = backend.require_value(backend.emit_expr(value_expr), context="binary content")
    result = action("base64encode", WFInput=value.attachment(), WFEncodeMode="Encode")
    backend.actions.append(result)
    # This is an implementation representation of the IR-level bytes value.
    return ValueRef.action(result, "Base64 Encoded")

# UI / notifications -------------------------------------------------------


def _ui_alert(backend: ShortcutsBackend, call: ir.Call) -> None:
    if not 1 <= len(call.args) <= 2:
        raise CompileError("ios.ui.alert(message, title='') expects one or two positional arguments")
    unknown = _unknown_kwargs(call, {"title"})
    if unknown:
        raise CompileError(f"ios.ui.alert() does not accept keyword(s): {', '.join(sorted(unknown))}")
    if len(call.args) == 2 and call.keyword("title") is not None:
        raise CompileError("ios.ui.alert(): title supplied twice")
    title = call.args[1] if len(call.args) == 2 else call.keyword("title")
    params: dict[str, PlistValue] = {"WFAlertActionMessage": backend.text_param(call.args[0])}
    if title is not None:
        params["WFAlertActionTitle"] = backend.text_param(title)
    backend.actions.append(action("alert", **params))
    return None


def _ui_ask_text(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    if len(call.args) > 1 or call.kwargs:
        raise CompileError("ios.ui.ask_text(prompt='') accepts at most one positional prompt")
    prompt: PlistValue = ""
    if call.args:
        prompt = backend.text_param(call.args[0])
    result = action("ask", WFAskActionPrompt=prompt, WFInputType="Text")
    backend.actions.append(result)
    return ValueRef.action(result, "Provided Input")


def _ui_show(backend: ShortcutsBackend, call: ir.Call) -> None:
    value = _one_arg(call, display="ios.ui.show(value)")
    if call.kwargs:
        raise CompileError("ios.ui.show() does not accept keyword arguments")
    backend.actions.append(action("showresult", Text=backend.text_param(value)))
    return None


def _notify(backend: ShortcutsBackend, call: ir.Call) -> None:
    if not 1 <= len(call.args) <= 2:
        raise CompileError("ios.notifications.notify(body, title='', *, sound=True) expects one or two positional arguments")
    unknown = _unknown_kwargs(call, {"title", "sound"})
    if unknown:
        raise CompileError(f"ios.notifications.notify() does not accept keyword(s): {', '.join(sorted(unknown))}")
    if len(call.args) == 2 and call.keyword("title") is not None:
        raise CompileError("ios.notifications.notify(): title supplied twice")
    title = call.args[1] if len(call.args) == 2 else call.keyword("title")
    sound_expr = call.keyword("sound")
    sound = True if sound_expr is None else _literal_bool(sound_expr, name="notification sound")
    params: dict[str, PlistValue] = {
        "WFNotificationActionBody": backend.text_param(call.args[0]),
        "WFNotificationActionSound": sound,
    }
    if title is not None:
        params["WFNotificationActionTitle"] = backend.text_param(title)
    backend.actions.append(action("notification", **params))
    return None


# Web ----------------------------------------------------------------------


def _download(backend: ShortcutsBackend, url: ir.Expr, method: str = "GET") -> ValueRef:
    result = action("downloadurl", WFURL=backend.text_param(url), WFHTTPMethod=method)
    backend.actions.append(result)
    return ValueRef.action(result, "Contents of URL")


def _web_request(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    url = _one_arg(call, display="ios.web.request(url, *, method='GET')")
    unknown = _unknown_kwargs(call, {"method"})
    if unknown:
        raise CompileError(f"ios.web.request() does not accept keyword(s): {', '.join(sorted(unknown))}")
    method_expr = call.keyword("method")
    method = "GET" if method_expr is None else _literal_string(method_expr, name="HTTP method").upper()
    if method not in _HTTP_METHODS:
        raise CompileError(f"unsupported HTTP method {method!r}")
    return _download(backend, url, method)


def _web_get_text(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    url = _one_arg(call, display="ios.web.get_text(url)")
    if call.kwargs:
        raise CompileError("ios.web.get_text() does not accept keyword arguments")
    downloaded = _download(backend, url)
    result = action("detect.text", WFInput=downloaded.attachment())
    backend.actions.append(result)
    return ValueRef.action(result, "Text")


def _web_get_json(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    url = _one_arg(call, display="ios.web.get_json(url)")
    if call.kwargs:
        raise CompileError("ios.web.get_json() does not accept keyword arguments")
    downloaded = _download(backend, url)
    result = action("detect.dictionary", WFInput=downloaded.attachment())
    backend.actions.append(result)
    return ValueRef.action(result, "Dictionary")


def _web_open(backend: ShortcutsBackend, call: ir.Call) -> None:
    url_expr = _one_arg(call, display="ios.web.open(url)")
    if call.kwargs:
        raise CompileError("ios.web.open() does not accept keyword arguments")
    url_action = action("url", WFURLActionURL=backend.text_param(url_expr))
    backend.actions.append(url_action)
    backend.actions.append(action("openurl", WFInput=ValueRef.action(url_action, "URL").attachment()))
    return None


# Clipboard ----------------------------------------------------------------


def _clipboard_get(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    _no_args(call, display="ios.clipboard.get()")
    result = action("getclipboard")
    backend.actions.append(result)
    return ValueRef.action(result, "Clipboard")


def _clipboard_get_text(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    _no_args(call, display="ios.clipboard.get_text()")
    clipboard = action("getclipboard")
    backend.actions.append(clipboard)
    text = action("detect.text", WFInput=ValueRef.action(clipboard, "Clipboard").attachment())
    backend.actions.append(text)
    return ValueRef.action(text, "Text")


def _clipboard_set(backend: ShortcutsBackend, call: ir.Call) -> None:
    value_expr = _one_arg(call, display="ios.clipboard.set(value, *, local_only=False)")
    unknown = _unknown_kwargs(call, {"local_only"})
    if unknown:
        raise CompileError(f"ios.clipboard.set() does not accept keyword(s): {', '.join(sorted(unknown))}")
    local_expr = call.keyword("local_only")
    local_only = False if local_expr is None else _literal_bool(local_expr, name="local_only")
    value = backend.require_value(backend.emit_expr(value_expr), context="clipboard value")
    backend.actions.append(action("setclipboard", WFInput=value.attachment(), WFLocalOnly=local_only))
    return None


# Location -----------------------------------------------------------------


def _location_current(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    _no_args(call, display="ios.location.current()")
    result = action("getcurrentlocation", Accuracy="Best")
    backend.actions.append(result)
    return ValueRef.action(result, "Current Location")


def _location_maps_url(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    location_expr = _one_arg(call, display="ios.location.maps_url(location)")
    if call.kwargs:
        raise CompileError("ios.location.maps_url() does not accept keyword arguments")
    location = backend.require_value(backend.emit_expr(location_expr), context="maps URL location")
    result = action("getmapslink", WFInput=location.attachment())
    backend.actions.append(result)
    return ValueRef.action(result, "Maps URL")


# Device -------------------------------------------------------------------


def _emit_device_detail(backend: ShortcutsBackend, detail: str) -> ValueRef:
    result = action("getdevicedetails", WFDeviceDetail=detail)
    backend.actions.append(result)
    return ValueRef.action(result, "Device Details")


def _device_detail(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    kind_expr = _one_arg(call, display="ios.device.detail(kind)")
    if call.kwargs:
        raise CompileError("ios.device.detail() does not accept keyword arguments")
    kind = _literal_string(kind_expr, name="device detail")
    if kind not in _DEVICE_DETAILS:
        raise CompileError(f"unsupported device detail {kind!r}")
    return _emit_device_detail(backend, kind)


def _fixed_device_detail(detail: str) -> Callable[[ShortcutsBackend, ir.Call], ValueRef]:
    def lower(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
        _no_args(call, display=f"ios.device.{detail.lower().replace(' ', '_')}()")
        return _emit_device_detail(backend, detail)

    return lower


def _device_battery(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    _no_args(call, display="ios.device.battery_level()")
    result = action("getbatterylevel")
    backend.actions.append(result)
    return ValueRef.action(result, "Battery Level")


def _device_toggle(identifier: str, api_name: str) -> Callable[[ShortcutsBackend, ir.Call], None]:
    def lower(backend: ShortcutsBackend, call: ir.Call) -> None:
        enabled_expr = _one_arg(call, display=f"{api_name}(enabled)")
        if call.kwargs:
            raise CompileError(f"{api_name}() does not accept keyword arguments")
        enabled = _literal_bool(enabled_expr, name=f"{api_name} enabled")
        backend.actions.append(action(identifier, OnValue=enabled))
        return None

    return lower


def _device_low_power(backend: ShortcutsBackend, call: ir.Call) -> None:
    if len(call.args) > 1:
        raise CompileError("ios.device.set_low_power_mode(enabled=True) accepts at most one positional argument")
    if call.kwargs:
        raise CompileError("ios.device.set_low_power_mode() does not accept keyword arguments")
    enabled = True if not call.args else _literal_bool(call.args[0], name="low power mode enabled")
    backend.actions.append(action("lowpowermode.set", OnValue=enabled))
    return None


def _device_set_level(
    identifier: str,
    parameter: str,
    api_name: str,
) -> Callable[[ShortcutsBackend, ir.Call], None]:
    def lower(backend: ShortcutsBackend, call: ir.Call) -> None:
        level_expr = _one_arg(call, display=f"{api_name}(level)")
        if call.kwargs:
            raise CompileError(f"{api_name}() does not accept keyword arguments")
        level = _literal_number(level_expr, name=f"{api_name} level")
        if not 0 <= level <= 1:
            raise CompileError(f"{api_name} level must be between 0 and 1")
        backend.actions.append(action(identifier, **{parameter: float(level)}))
        return None

    return lower


def _device_flashlight(backend: ShortcutsBackend, call: ir.Call) -> None:
    mode_expr = _one_arg(call, display="ios.device.set_flashlight(mode)")
    if call.kwargs:
        raise CompileError("ios.device.set_flashlight() does not accept keyword arguments")
    mode = _literal_string(mode_expr, name="flashlight mode")
    if mode not in _FLASHLIGHT_MODES:
        raise CompileError(f"unsupported flashlight mode {mode!r}")
    backend.actions.append(action("flashlight", WFFlashlightSetting=mode))
    return None


# Health -------------------------------------------------------------------


def _health_log_sleep(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    if len(call.args) != 2:
        raise CompileError("ios.app.health.log_sleep(start, end, *, stage=...) expects two positional dates")
    unknown = _unknown_kwargs(call, {"stage"})
    if unknown:
        raise CompileError(f"ios.app.health.log_sleep() does not accept keyword(s): {', '.join(sorted(unknown))}")
    stage_expr = call.keyword("stage")
    if stage_expr is None:
        raise CompileError("ios.app.health.log_sleep() requires stage=")
    stage = _literal_string(stage_expr, name="sleep stage")
    if stage not in _SLEEP_STAGES:
        raise CompileError(f"unsupported sleep stage {stage!r}")
    result = action(
        "health.quantity.log",
        WFQuantitySampleType="Sleep",
        WFCategorySampleEnumeration=stage,
        WFQuantitySampleDate=_text_token(backend, call.args[0]),
        WFSampleEndDate=_text_token(backend, call.args[1]),
    )
    backend.actions.append(result)
    return ValueRef.action(result, "Health Sample")


# Low-level ----------------------------------------------------------------


def _shortcuts_comment(backend: ShortcutsBackend, call: ir.Call) -> None:
    text_expr = _one_arg(call, display="ios.shortcuts.comment(text)")
    if call.kwargs:
        raise CompileError("ios.shortcuts.comment() does not accept keyword arguments")
    text = _literal_string(text_expr, name="comment text")
    backend.actions.append(action("comment", WFCommentActionText=text))
    return None


def _shortcuts_raw_action(backend: ShortcutsBackend, call: ir.Call) -> ValueRef | None:
    identifier_expr = _one_arg(call, display="ios.shortcuts.raw_action(identifier, **parameters)")
    identifier = _literal_string(identifier_expr, name="raw action identifier")
    if "." not in identifier:
        raise CompileError("raw action identifier must be a reverse-DNS-like string")
    params: dict[str, PlistValue] = {}
    output_name: str | None = None
    for key, value_expr in call.kwargs:
        if key == "output":
            if isinstance(value_expr, ir.Literal) and value_expr.value is None:
                output_name = None
            else:
                output_name = _literal_string(value_expr, name="raw action output")
            continue
        params[key] = backend.static_value(value_expr)
    result = raw_action(identifier, **params)
    backend.actions.append(result)
    return None if output_name is None else ValueRef.action(result, output_name)


def _shortcuts_stop(backend: ShortcutsBackend, call: ir.Call) -> None:
    _no_args(call, display="ios.shortcuts.stop()")
    backend.actions.append(action("exit"))
    return None


def register_ios_plugins(registry: PluginRegistry) -> None:
    """Register the built-in first-party ``ios`` compile-time API."""

    registry.register_call("ios.ui.alert", _ui_alert)
    registry.register_call("ios.ui.ask_text", _ui_ask_text, result_type="text")
    registry.register_call("ios.ui.show", _ui_show)
    registry.register_call("ios.notifications.notify", _notify)

    registry.register_call("ios.web.request", _web_request)
    registry.register_call("ios.web.get_text", _web_get_text, result_type="text")
    registry.register_call("ios.web.get_json", _web_get_json, result_type="dict")
    registry.register_call("ios.web.open", _web_open)

    registry.register_call("ios.clipboard.get", _clipboard_get)
    registry.register_call("ios.clipboard.get_text", _clipboard_get_text, result_type="text")
    registry.register_call("ios.clipboard.set", _clipboard_set)

    registry.register_call("ios.location.current", _location_current)
    registry.register_call("ios.location.maps_url", _location_maps_url, result_type="text")

    registry.register_call("ios.device.detail", _device_detail)
    registry.register_call("ios.device.name", _fixed_device_detail("Device Name"), result_type="text")
    registry.register_call("ios.device.model", _fixed_device_detail("Device Model"), result_type="text")
    registry.register_call("ios.device.system_version", _fixed_device_detail("System Version"), result_type="text")
    registry.register_call("ios.device.screen_width", _fixed_device_detail("Screen Width"), result_type="number")
    registry.register_call("ios.device.screen_height", _fixed_device_detail("Screen Height"), result_type="number")
    registry.register_call("ios.device.volume", _fixed_device_detail("Current Volume"), result_type="number")
    registry.register_call("ios.device.brightness", _fixed_device_detail("Current Brightness"), result_type="number")
    registry.register_call("ios.device.battery_level", _device_battery, result_type="number")
    registry.register_call("ios.device.set_wifi", _device_toggle("wifi.set", "ios.device.set_wifi"))
    registry.register_call("ios.device.set_bluetooth", _device_toggle("bluetooth.set", "ios.device.set_bluetooth"))
    registry.register_call("ios.device.set_cellular_data", _device_toggle("cellulardata.set", "ios.device.set_cellular_data"))
    registry.register_call("ios.device.set_low_power_mode", _device_low_power)
    registry.register_call("ios.device.set_brightness", _device_set_level("setbrightness", "WFBrightness", "ios.device.set_brightness"))
    registry.register_call("ios.device.set_volume", _device_set_level("setvolume", "WFVolume", "ios.device.set_volume"))
    registry.register_call("ios.device.set_flashlight", _device_flashlight)

    registry.register_call("ios.app.health.log_sleep", _health_log_sleep)

    registry.register_call("ios.shortcuts.input", _shortcut_input)
    registry.register_call("ios.content.coerce", _content_coerce)
    registry.register_call("ios.images.resize", _image_resize)
    registry.register_call("ios.images.convert", _image_convert)
    registry.register_call("ios.data.as_bytes", _data_as_bytes, result_type="bytes")

    registry.register_call("ios.shortcuts.comment", _shortcuts_comment)
    registry.register_call("ios.shortcuts.raw_action", _shortcuts_raw_action)
    registry.register_call("ios.shortcuts.stop", _shortcuts_stop)
