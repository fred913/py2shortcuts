"""Built-in reusable utilities that expand to ordinary Shortcuts actions."""

from __future__ import annotations

from .. import ir
from ..errors import CompileError
from ..plist import PlistValue, action
from ..plugins import PluginRegistry
from .shortcuts import ShortcutsBackend, ValueRef


_BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def _literal_int(expr: ir.Expr | None, *, name: str) -> int:
    if isinstance(expr, ir.Literal) and isinstance(expr.value, int) and not isinstance(expr.value, bool):
        return expr.value
    raise CompileError(f"{name} must currently be a literal int")


def _literal_bool(expr: ir.Expr | None, *, name: str, default: bool = False) -> bool:
    if expr is None:
        return default
    if isinstance(expr, ir.Literal) and isinstance(expr.value, bool):
        return expr.value
    raise CompileError(f"{name} must currently be a literal bool")


def _math(backend: ShortcutsBackend, left: ValueRef, op: str, right: ValueRef | int | float | str) -> ValueRef:
    operand: PlistValue
    if isinstance(right, ValueRef):
        operand = right.attachment()
    else:
        operand = str(right)
    return backend.emit_math(left, op, operand)


def _mod(backend: ShortcutsBackend, left: ValueRef, right: ValueRef | int) -> ValueRef:
    operand: PlistValue = right.attachment() if isinstance(right, ValueRef) else str(right)
    result = action(
        "math",
        WFInput=left.attachment(),
        WFMathOperation="…",
        WFScientificMathOperation="Modulus",
        WFScientificMathOperand=operand,
    )
    backend.actions.append(result)
    return ValueRef.action(result, "Calculation Result")


def _number(backend: ShortcutsBackend, value: int | float) -> ValueRef:
    return backend.emit_literal(value)


def _base64_table(backend: ShortcutsBackend) -> ValueRef:
    fields: list[PlistValue] = []
    for value, char in enumerate(_BASE64_ALPHABET):
        fields.append(
            {
                "WFItemType": 0,
                "WFKey": backend.static_text_token(char),
                "WFValue": backend.static_text_token(str(value)),
            }
        )
    # Padding is only observed in the final quartet. Mapping it to zero makes
    # byte 0/1 decoding of a padded quartet work while unused trailing bytes
    # remain irrelevant.
    fields.append(
        {
            "WFItemType": 0,
            "WFKey": backend.static_text_token("="),
            "WFValue": backend.static_text_token("0"),
        }
    )
    result = action(
        "dictionary",
        WFItems={
            "Value": {"WFDictionaryFieldValueItems": fields},
            "WFSerializationType": "WFDictionaryFieldValue",
        },
    )
    backend.actions.append(result)
    return ValueRef.action(result, "Dictionary")


def _base64_chars(backend: ShortcutsBackend, encoded: ValueRef) -> ValueRef:
    # Match only the Base64 alphabet and padding so any visual/newline wrapping
    # inserted by Shortcuts is ignored.
    result = action(
        "text.match",
        WFMatchTextPattern=r"[A-Za-z0-9+/=]",
        WFMatchTextCaseSensitive=True,
        text=backend.text_token_from_refs((encoded,)),
    )
    backend.actions.append(result)
    return ValueRef.action(result, "Matches")


def _list_item(backend: ShortcutsBackend, values: ValueRef, index_zero: int | ValueRef) -> ValueRef:
    if isinstance(index_zero, int):
        index: PlistValue = str(index_zero + 1)
    else:
        one_based = _math(backend, index_zero, "+", 1)
        index = one_based.attachment()
    result = action(
        "getitemfromlist",
        WFInput=values.attachment(),
        WFItemSpecifier="Item At Index",
        WFItemIndex=index,
    )
    backend.actions.append(result)
    return ValueRef.action(result, "Item from List")


def _base64_value(backend: ShortcutsBackend, table: ValueRef, char: ValueRef) -> ValueRef:
    result = action(
        "getvalueforkey",
        WFInput=table.attachment(),
        WFDictionaryKey=backend.text_token_from_refs((char,)),
    )
    backend.actions.append(result)
    return ValueRef.action(result, "Dictionary Value")


def _decode_triplet(
    backend: ShortcutsBackend,
    chars: ValueRef,
    table: ValueRef,
    base_char_index: int | ValueRef,
) -> tuple[ValueRef, ValueRef, ValueRef]:
    positions: list[int | ValueRef] = []
    for delta in range(4):
        if isinstance(base_char_index, int):
            positions.append(base_char_index + delta)
        elif delta == 0:
            positions.append(base_char_index)
        else:
            positions.append(_math(backend, base_char_index, "+", delta))
    c0, c1, c2, c3 = (_list_item(backend, chars, p) for p in positions)
    v0 = _base64_value(backend, table, c0)
    v1 = _base64_value(backend, table, c1)
    v2 = _base64_value(backend, table, c2)
    v3 = _base64_value(backend, table, c3)

    v1_mod16 = _mod(backend, v1, 16)
    v1_high = _math(backend, _math(backend, v1, "-", v1_mod16), "/", 16)
    byte0 = _math(backend, _math(backend, v0, "*", 4), "+", v1_high)

    v2_mod4 = _mod(backend, v2, 4)
    v2_high = _math(backend, _math(backend, v2, "-", v2_mod4), "/", 4)
    byte1 = _math(backend, _math(backend, v1_mod16, "*", 16), "+", v2_high)
    byte2 = _math(backend, _math(backend, v2_mod4, "*", 64), "+", v3)
    return byte0, byte1, byte2


def _byte_at(
    backend: ShortcutsBackend,
    chars: ValueRef,
    table: ValueRef,
    index: int | ValueRef,
) -> ValueRef:
    if isinstance(index, int):
        group, phase = divmod(index, 3)
        return _decode_triplet(backend, chars, table, group * 4)[phase]

    phase = _mod(backend, index, 3)
    aligned = _math(backend, index, "-", phase)
    group = _math(backend, aligned, "/", 3)
    base = _math(backend, group, "*", 4)
    b0, b1, b2 = _decode_triplet(backend, chars, table, base)

    outer = backend.new_uuid()
    backend.actions.append(
        action(
            "conditional",
            GroupingIdentifier=outer,
            WFControlFlowMode=0,
            **backend.ref_equals_params(phase, "0"),
        )
    )
    # Materialize the branch value as an ordinary math output so the enclosing
    # If Result carries a numeric value.
    _math(backend, b0, "+", 0)
    backend.actions.append(action("conditional", GroupingIdentifier=outer, WFControlFlowMode=1))

    inner = backend.new_uuid()
    backend.actions.append(
        action(
            "conditional",
            GroupingIdentifier=inner,
            WFControlFlowMode=0,
            **backend.ref_equals_params(phase, "1"),
        )
    )
    _math(backend, b1, "+", 0)
    backend.actions.append(action("conditional", GroupingIdentifier=inner, WFControlFlowMode=1))
    _math(backend, b2, "+", 0)
    inner_end = action("conditional", GroupingIdentifier=inner, WFControlFlowMode=2)
    backend.actions.append(inner_end)
    backend.actions.append(action("conditional", GroupingIdentifier=outer, WFControlFlowMode=2))
    outer_end = backend.actions[-1]
    return ValueRef.action(outer_end, "If Result")


def _u16le(backend: ShortcutsBackend, chars: ValueRef, table: ValueRef, offset: int) -> ValueRef:
    lo = _byte_at(backend, chars, table, offset)
    hi = _byte_at(backend, chars, table, offset + 1)
    return _math(backend, lo, "+", _math(backend, hi, "*", 256))


def _u32le(backend: ShortcutsBackend, chars: ValueRef, table: ValueRef, offset: int) -> ValueRef:
    b0 = _byte_at(backend, chars, table, offset)
    b1 = _byte_at(backend, chars, table, offset + 1)
    b2 = _byte_at(backend, chars, table, offset + 2)
    b3 = _byte_at(backend, chars, table, offset + 3)
    value = _math(backend, b0, "+", _math(backend, b1, "*", 256))
    value = _math(backend, value, "+", _math(backend, b2, "*", 65536))
    return _math(backend, value, "+", _math(backend, b3, "*", 16777216))



def _guard_equals(
    backend: ShortcutsBackend,
    value: ValueRef,
    expected: int | str,
    *,
    title: str,
    message: str,
) -> None:
    group = backend.new_uuid()
    backend.actions.append(
        action(
            "conditional",
            GroupingIdentifier=group,
            WFControlFlowMode=0,
            WFInput=value.condition_input(),
            WFCondition=5,  # is not
            WFConditionalActionString=str(expected),
        )
    )
    backend.actions.append(
        action(
            "alert",
            WFAlertActionTitle=title,
            WFAlertActionMessage=message,
        )
    )
    backend.actions.append(action("exit"))
    backend.actions.append(action("conditional", GroupingIdentifier=group, WFControlFlowMode=2))

def _to_bmp_bytes(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    if len(call.args) != 1:
        raise CompileError("shortcutslib.image.to_bmp_bytes(value, *, width=..., height=...) expects one positional value")
    unknown = {name for name, _ in call.kwargs} - {"width", "height"}
    if unknown:
        raise CompileError(f"shortcutslib.image.to_bmp_bytes() does not accept keyword(s): {', '.join(sorted(unknown))}")
    width = _literal_int(call.keyword("width"), name="BMP width")
    height = _literal_int(call.keyword("height"), name="BMP height")
    if width <= 0 or height <= 0:
        raise CompileError("BMP width and height must be positive")

    source = backend.require_value(backend.emit_expr(call.args[0]), context="BMP source")
    image = source.coerced("WFImageContentItem")
    resized = action(
        "image.resize",
        WFImage=image.attachment(),
        WFImageResizeKey="Size",
        WFImageResizeWidth=str(width),
        WFImageResizeHeight=str(height),
    )
    backend.actions.append(resized)
    converted = action(
        "image.convert",
        WFInput=ValueRef.action(resized, "Resized Image").attachment(),
        WFImageFormat="BMP",
        WFImagePreserveMetadata=False,
    )
    backend.actions.append(converted)
    encoded = action(
        "base64encode",
        WFInput=ValueRef.action(converted, "Converted Image").attachment(),
        WFEncodeMode="Encode",
    )
    backend.actions.append(encoded)
    return ValueRef.action(encoded, "Base64 Encoded")


def _decode_bmp_grayscale(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    if len(call.args) != 1:
        raise CompileError(
            "shortcutslib.image.decode_bmp_grayscale(data, *, width=..., height=..., invert=False) "
            "expects one positional bytes value"
        )
    unknown = {name for name, _ in call.kwargs} - {"width", "height", "invert"}
    if unknown:
        raise CompileError(
            "shortcutslib.image.decode_bmp_grayscale() does not accept keyword(s): "
            + ", ".join(sorted(unknown))
        )
    width = _literal_int(call.keyword("width"), name="BMP width")
    height = _literal_int(call.keyword("height"), name="BMP height")
    invert = _literal_bool(call.keyword("invert"), name="invert", default=False)
    if width <= 0 or height <= 0:
        raise CompileError("BMP width and height must be positive")

    encoded = backend.require_value(backend.emit_expr(call.args[0]), context="BMP bytes")
    chars = _base64_chars(backend, encoded)
    table = _base64_table(backend)

    signature_b = _byte_at(backend, chars, table, 0)
    signature_m = _byte_at(backend, chars, table, 1)
    pixel_offset = _u32le(backend, chars, table, 10)
    encoded_width = _u32le(backend, chars, table, 18)
    encoded_height = _u32le(backend, chars, table, 22)
    bits_per_pixel = _u16le(backend, chars, table, 28)
    compression = _u32le(backend, chars, table, 30)

    _guard_equals(backend, signature_b, 66, title="Invalid BMP", message="BMP signature is missing.")
    _guard_equals(backend, signature_m, 77, title="Invalid BMP", message="BMP signature is missing.")
    _guard_equals(backend, encoded_width, width, title="Unexpected BMP", message="BMP width does not match the requested decode width.")
    _guard_equals(backend, encoded_height, height, title="Unexpected BMP", message="Only ordinary bottom-up BMP images with the requested height are supported.")
    _guard_equals(backend, compression, 0, title="Unsupported BMP", message="Only uncompressed BMP (BI_RGB) is supported.")
    supported_bpp = _math(
        backend,
        _math(backend, bits_per_pixel, "-", 24),
        "*",
        _math(backend, bits_per_pixel, "-", 32),
    )
    _guard_equals(backend, supported_bpp, 0, title="Unsupported BMP", message="Only 24-bit BGR and 32-bit BGRA BMP images are supported.")

    # bytes_per_pixel = bpp / 8; row_stride = ceil(width*bpp/32)*4.
    bytes_per_pixel = _math(backend, bits_per_pixel, "/", 8)
    row_bits = _math(backend, bits_per_pixel, "*", width)
    row_bits_plus = _math(backend, row_bits, "+", 31)
    row_bits_aligned = _math(backend, row_bits_plus, "-", _mod(backend, row_bits_plus, 32))
    row_stride = _math(backend, row_bits_aligned, "/", 8)

    pixels: list[ValueRef] = []
    for y in range(height):
        source_y = height - 1 - y  # ordinary positive-height BMPs are bottom-up
        row_start = pixel_offset if source_y == 0 else _math(
            backend, pixel_offset, "+", _math(backend, row_stride, "*", source_y)
        )
        for x in range(width):
            pixel_start = row_start if x == 0 else _math(
                backend, row_start, "+", _math(backend, bytes_per_pixel, "*", x)
            )
            blue = _byte_at(backend, chars, table, pixel_start)
            green = _byte_at(backend, chars, table, _math(backend, pixel_start, "+", 1))
            red = _byte_at(backend, chars, table, _math(backend, pixel_start, "+", 2))
            total = _math(backend, _math(backend, red, "+", green), "+", blue)
            gray = _math(backend, total, "/", 765)
            if invert:
                gray = _math(backend, _number(backend, 1), "-", gray)
            pixels.append(gray)

    result = action(
        "list",
        WFItems=[backend.text_token_from_refs((pixel,)) for pixel in pixels],
    )
    backend.actions.append(result)
    return ValueRef.action(result, "List")


def register_stdlib_plugins(registry: PluginRegistry) -> None:
    registry.register_call("shortcutslib.image.to_bmp_bytes", _to_bmp_bytes, result_type="bytes")
    registry.register_call(
        "shortcutslib.image.decode_bmp_grayscale",
        _decode_bmp_grayscale,
        result_type="list",
    )
