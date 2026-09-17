"""Built-in reusable utilities that expand to ordinary Shortcuts actions."""

from __future__ import annotations

from dataclasses import dataclass

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


def _literal_str(expr: ir.Expr | None, *, name: str, default: str | None = None) -> str:
    if expr is None and default is not None:
        return default
    if isinstance(expr, ir.Literal) and isinstance(expr.value, str):
        return expr.value
    raise CompileError(f"{name} must currently be a literal str")


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


def _numeric_predicate(
    backend: ShortcutsBackend,
    value: ValueRef,
    *,
    condition: int,
    number: int | float,
) -> ValueRef:
    """Materialize a numeric Shortcuts condition as 1 or 0."""
    group = backend.new_uuid()
    backend.actions.append(
        action(
            "conditional",
            GroupingIdentifier=group,
            WFControlFlowMode=0,
            WFInput=value.condition_input(),
            WFCondition=condition,
            WFNumberValue=str(number),
        )
    )
    backend.emit_literal(1)
    backend.actions.append(action("conditional", GroupingIdentifier=group, WFControlFlowMode=1))
    backend.emit_literal(0)
    end = action("conditional", GroupingIdentifier=group, WFControlFlowMode=2)
    backend.actions.append(end)
    return ValueRef.action(end, "If Result")



def _diagnostic_text(backend: ShortcutsBackend, *parts: str | ValueRef) -> PlistValue:
    string_parts: list[str] = []
    attachments: dict[str, PlistValue] = {}
    utf16_offset = 0
    for part in parts:
        if isinstance(part, str):
            string_parts.append(part)
            utf16_offset += len(part.encode("utf-16-le")) // 2
            continue
        string_parts.append("\ufffc")
        attachments[f"{{{utf16_offset}, 1}}"] = part.value()
        utf16_offset += 1
    return {
        "Value": {"string": "".join(string_parts), "attachmentsByRange": attachments},
        "WFSerializationType": "WFTextTokenString",
    }


def _guard_equals(
    backend: ShortcutsBackend,
    value: ValueRef,
    expected: int | str,
    *,
    title: str,
    message: PlistValue,
) -> None:
    if isinstance(expected, int):
        # Shortcuts' generic equality conditions (4/5) compare against a text
        # operand.  A numeric action output can therefore compare unequal to
        # the textual representation of the same number (for example Number
        # 66 vs Text "66").  Use the native numeric comparison conditions
        # instead.  For an exact integer match, failing either < N or > N is
        # equivalent to != N.
        for condition in (0, 2):  # less than, greater than
            group = backend.new_uuid()
            backend.actions.append(
                action(
                    "conditional",
                    GroupingIdentifier=group,
                    WFControlFlowMode=0,
                    WFInput=value.condition_input(),
                    WFCondition=condition,
                    WFNumberValue=str(expected),
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
        return

    group = backend.new_uuid()
    backend.actions.append(
        action(
            "conditional",
            GroupingIdentifier=group,
            WFControlFlowMode=0,
            WFInput=value.condition_input(),
            WFCondition=5,  # string is not
            WFConditionalActionString=expected,
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



@dataclass(frozen=True, slots=True)
class _BmpRuntime:
    chars: ValueRef
    table: ValueRef
    pixel_offset: ValueRef
    dib_header_size: ValueRef
    width: ValueRef
    signed_height: ValueRef
    height: ValueRef
    top_down: ValueRef
    bits_per_pixel: ValueRef
    compression: ValueRef
    bytes_per_pixel: ValueRef
    row_stride: ValueRef


def _parse_bmp_runtime(backend: ShortcutsBackend, encoded: ValueRef) -> _BmpRuntime:
    chars = _base64_chars(backend, encoded)
    table = _base64_table(backend)

    signature_b = _byte_at(backend, chars, table, 0)
    signature_m = _byte_at(backend, chars, table, 1)
    prefix = tuple(_list_item(backend, chars, index) for index in range(4))
    pixel_offset = _u32le(backend, chars, table, 10)
    dib_header_size = _u32le(backend, chars, table, 14)
    encoded_width = _u32le(backend, chars, table, 18)
    encoded_height_raw = _u32le(backend, chars, table, 22)
    height_sign_byte = _byte_at(backend, chars, table, 25)
    # BITMAPINFOHEADER stores height as a signed 32-bit integer. A negative
    # height is valid and means the pixel array is top-down instead of the
    # traditional bottom-up layout.
    top_down = _numeric_predicate(backend, height_sign_byte, condition=2, number=127)
    signed_height = _math(
        backend,
        encoded_height_raw,
        "-",
        _math(backend, top_down, "*", 4294967296),
    )
    height_twice = _math(backend, encoded_height_raw, "*", 2)
    top_down_abs_correction = _math(
        backend,
        _number(backend, 4294967296),
        "-",
        height_twice,
    )
    absolute_height = _math(
        backend,
        encoded_height_raw,
        "+",
        _math(backend, top_down, "*", top_down_abs_correction),
    )
    bits_per_pixel = _u16le(backend, chars, table, 28)
    compression = _u32le(backend, chars, table, 30)

    signature_message = _diagnostic_text(
        backend,
        'Invalid BMP signature.\n\nExpected bytes[0:2]: 66, 77 (0x42 0x4D, "BM")\nActual bytes[0:2]: ',
        signature_b,
        ", ",
        signature_m,
        "\nBase64 prefix: ",
        *prefix,
        "...\n\nThe image conversion produced Base64 data, but the Base64-backed byte decoder did not yield the expected BMP header. If the Base64 prefix starts with Qk, this indicates a py2shortcuts binary-backend bug rather than an invalid input image.",
    )
    _guard_equals(backend, signature_b, 66, title="Invalid BMP signature", message=signature_message)
    _guard_equals(backend, signature_m, 77, title="Invalid BMP signature", message=signature_message)

    # We support ordinary BI_RGB and the byte-aligned 32-bit BI_BITFIELDS
    # layout emitted by Apple's Convert Image -> BMP action. compression is
    # therefore allowed to be either 0 or 3. x * (x - 3) == 0 exactly for
    # those two integer values and lets us use the numeric-equality guard.
    supported_compression = _math(
        backend,
        compression,
        "*",
        _math(backend, compression, "-", 3),
    )
    _guard_equals(
        backend,
        supported_compression,
        0,
        title="Unsupported BMP compression",
        message=_diagnostic_text(
            backend,
            "Supported BMP compression modes are BI_RGB (0) and BI_BITFIELDS (3).\n\nActual compression=",
            compression,
            "\nDIB header size=",
            dib_header_size,
            "\nBits per pixel=",
            bits_per_pixel,
            "\nPixel offset=",
            pixel_offset,
            ".",
        ),
    )

    # Read/validate masks only inside the BI_BITFIELDS branch. On a tiny
    # BI_RGB image, offsets 54/58/62 can already be pixel data or past EOF.
    bitfields_group = backend.new_uuid()
    backend.actions.append(
        action(
            "conditional",
            GroupingIdentifier=bitfields_group,
            WFControlFlowMode=0,
            WFInput=compression.condition_input(),
            WFCondition=2,  # greater than
            WFNumberValue="0",
        )
    )
    _guard_equals(
        backend,
        bits_per_pixel,
        32,
        title="Unsupported BI_BITFIELDS pixel format",
        message=_diagnostic_text(
            backend,
            "BI_BITFIELDS decoding currently requires 32 bits per pixel.\n\nActual bits_per_pixel=",
            bits_per_pixel,
            "\nDIB header size=",
            dib_header_size,
            "\nPixel offset=",
            pixel_offset,
            ".",
        ),
    )
    red_mask = _u32le(backend, chars, table, 54)
    green_mask = _u32le(backend, chars, table, 58)
    blue_mask = _u32le(backend, chars, table, 62)
    bitfields_message = _diagnostic_text(
        backend,
        "Unsupported BI_BITFIELDS channel masks.\n\nExpected:\nR mask = 16711680 (0x00FF0000)\nG mask = 65280 (0x0000FF00)\nB mask = 255 (0x000000FF)\n\nActual:\nR mask = ",
        red_mask,
        "\nG mask = ",
        green_mask,
        "\nB mask = ",
        blue_mask,
        "\nDIB header size = ",
        dib_header_size,
        "\nPixel offset = ",
        pixel_offset,
        ".",
    )
    _guard_equals(
        backend, red_mask, 16711680,
        title="Unsupported BI_BITFIELDS masks", message=bitfields_message,
    )
    _guard_equals(
        backend, green_mask, 65280,
        title="Unsupported BI_BITFIELDS masks", message=bitfields_message,
    )
    _guard_equals(
        backend, blue_mask, 255,
        title="Unsupported BI_BITFIELDS masks", message=bitfields_message,
    )
    backend.actions.append(
        action("conditional", GroupingIdentifier=bitfields_group, WFControlFlowMode=2)
    )

    supported_bpp = _math(
        backend,
        _math(backend, bits_per_pixel, "-", 24),
        "*",
        _math(backend, bits_per_pixel, "-", 32),
    )
    _guard_equals(
        backend,
        supported_bpp,
        0,
        title="Unsupported BMP pixel format",
        message=_diagnostic_text(
            backend,
            "Expected 24-bit BGR or 32-bit BGRA, but the BMP header reports bits_per_pixel=",
            bits_per_pixel,
            ".",
        ),
    )

    bytes_per_pixel = _math(backend, bits_per_pixel, "/", 8)
    row_bits = _math(backend, bits_per_pixel, "*", encoded_width)
    row_bits_plus = _math(backend, row_bits, "+", 31)
    row_bits_aligned = _math(backend, row_bits_plus, "-", _mod(backend, row_bits_plus, 32))
    row_stride = _math(backend, row_bits_aligned, "/", 8)

    return _BmpRuntime(
        chars=chars,
        table=table,
        pixel_offset=pixel_offset,
        dib_header_size=dib_header_size,
        width=encoded_width,
        signed_height=signed_height,
        height=absolute_height,
        top_down=top_down,
        bits_per_pixel=bits_per_pixel,
        compression=compression,
        bytes_per_pixel=bytes_per_pixel,
        row_stride=row_stride,
    )


def _bmp_row_start(
    backend: ShortcutsBackend,
    info: _BmpRuntime,
    logical_y: int | ValueRef,
) -> ValueRef:
    y = _number(backend, logical_y) if isinstance(logical_y, int) else logical_y
    height_minus_one = _math(backend, info.height, "-", 1)
    bottom_up_y = _math(backend, height_minus_one, "-", y)
    # top_down is 0 or 1, so this branchless expression selects y for a
    # top-down BMP and (height - 1 - y) for a bottom-up BMP.
    physical_y = _math(
        backend,
        bottom_up_y,
        "+",
        _math(backend, info.top_down, "*", _math(backend, y, "-", bottom_up_y)),
    )
    return _math(
        backend,
        info.pixel_offset,
        "+",
        _math(backend, info.row_stride, "*", physical_y),
    )


def _bmp_channels_at(
    backend: ShortcutsBackend,
    info: _BmpRuntime,
    row_start: ValueRef,
    logical_x: int | ValueRef,
) -> tuple[ValueRef, ValueRef, ValueRef]:
    if isinstance(logical_x, int):
        if logical_x == 0:
            pixel_start = row_start
        else:
            pixel_start = _math(
                backend,
                row_start,
                "+",
                _math(backend, info.bytes_per_pixel, "*", logical_x),
            )
    else:
        pixel_start = _math(
            backend,
            row_start,
            "+",
            _math(backend, info.bytes_per_pixel, "*", logical_x),
        )
    blue = _byte_at(backend, info.chars, info.table, pixel_start)
    green = _byte_at(backend, info.chars, info.table, _math(backend, pixel_start, "+", 1))
    red = _byte_at(backend, info.chars, info.table, _math(backend, pixel_start, "+", 2))
    return red, green, blue


def _decode_bmp_pixels(
    backend: ShortcutsBackend,
    encoded: ValueRef,
    *,
    width: int,
    height: int,
    mode: str,
    invert: bool,
) -> ValueRef:
    info = _parse_bmp_runtime(backend, encoded)
    _guard_equals(
        backend,
        info.width,
        width,
        title="Unexpected BMP width",
        message=_diagnostic_text(
            backend,
            f"decode_image() requested width={width}, but the BMP header reports width=",
            info.width,
            ".",
        ),
    )
    _guard_equals(
        backend,
        info.height,
        height,
        title="Unexpected BMP height",
        message=_diagnostic_text(
            backend,
            f"decode_image() requested height={height}, but the BMP header reports signed height=",
            info.signed_height,
            " (absolute height=",
            info.height,
            "). BMP height is a signed int32; negative heights are valid top-down images.",
        ),
    )

    pixels: list[ValueRef] = []
    for y in range(height):
        row_start = _bmp_row_start(backend, info, y)
        for x in range(width):
            red, green, blue = _bmp_channels_at(backend, info, row_start, x)
            if mode == "grayscale":
                total = _math(backend, _math(backend, red, "+", green), "+", blue)
                gray = _math(backend, total, "/", 765)
                if invert:
                    gray = _math(backend, _number(backend, 1), "-", gray)
                pixels.append(gray)
                continue

            channels = (red, green, blue) if mode == "rgb" else (blue, green, red)
            for channel in channels:
                normalized = _math(backend, channel, "/", 255)
                if invert:
                    normalized = _math(backend, _number(backend, 1), "-", normalized)
                pixels.append(normalized)

    return backend.emit_runtime_list(pixels)


def _positive_floor_ratio(
    backend: ShortcutsBackend,
    value: ValueRef,
    denominator: int,
) -> ValueRef:
    """floor(value / denominator) for a non-negative integer-valued ValueRef."""
    remainder = _mod(backend, value, denominator)
    return _math(backend, _math(backend, value, "-", remainder), "/", denominator)


def _supersample_axis(
    backend: ShortcutsBackend,
    source_extent: ValueRef,
    *,
    target_extent: int,
    target_index: int,
) -> tuple[ValueRef, ValueRef]:
    """Return the 1/4 and 3/4 source-pixel samples for one target cell.

    Using integer arithmetic avoids floor/round actions. For a target cell x,
    the two sample locations are the nearest source pixels to the quarter-cell
    positions. The indices are always in [0, source_extent - 1] for a positive
    source extent, including both upsampling and downsampling cases.
    """
    denominator = 4 * target_extent
    first = _math(backend, source_extent, "*", 4 * target_index + 1)
    second = _math(backend, source_extent, "*", 4 * target_index + 3)
    return (
        _positive_floor_ratio(backend, first, denominator),
        _positive_floor_ratio(backend, second, denominator),
    )


def _decode_bmp_supersampled(
    backend: ShortcutsBackend,
    encoded: ValueRef,
    *,
    width: int,
    height: int,
    mode: str,
    invert: bool,
) -> ValueRef:
    """Resize an original-size BMP using fixed 2x2 software supersampling."""
    info = _parse_bmp_runtime(backend, encoded)

    x_samples = [
        _supersample_axis(
            backend,
            info.width,
            target_extent=width,
            target_index=x,
        )
        for x in range(width)
    ]
    y_samples = [
        _supersample_axis(
            backend,
            info.height,
            target_extent=height,
            target_index=y,
        )
        for y in range(height)
    ]

    pixels: list[ValueRef] = []
    for y0, y1 in y_samples:
        row0 = _bmp_row_start(backend, info, y0)
        row1 = _bmp_row_start(backend, info, y1)
        for x0, x1 in x_samples:
            # Four stratified source samples approximate an area/antialiased
            # downsample while keeping the generated Shortcut size fixed at
            # O(output_width * output_height), independent of source size.
            samples = (
                _bmp_channels_at(backend, info, row0, x0),
                _bmp_channels_at(backend, info, row0, x1),
                _bmp_channels_at(backend, info, row1, x0),
                _bmp_channels_at(backend, info, row1, x1),
            )

            if mode == "grayscale":
                total: ValueRef | None = None
                for red, green, blue in samples:
                    sample_sum = _math(backend, _math(backend, red, "+", green), "+", blue)
                    total = sample_sum if total is None else _math(backend, total, "+", sample_sum)
                assert total is not None
                gray = _math(backend, total, "/", 3060)  # 4 samples * 3 channels * 255
                if invert:
                    gray = _math(backend, _number(backend, 1), "-", gray)
                pixels.append(gray)
                continue

            order = (0, 1, 2) if mode == "rgb" else (2, 1, 0)
            for channel_index in order:
                channel_total: ValueRef | None = None
                for sample in samples:
                    channel = sample[channel_index]
                    channel_total = channel if channel_total is None else _math(
                        backend, channel_total, "+", channel
                    )
                assert channel_total is not None
                normalized = _math(backend, channel_total, "/", 1020)  # 4 * 255
                if invert:
                    normalized = _math(backend, _number(backend, 1), "-", normalized)
                pixels.append(normalized)

    return backend.emit_runtime_list(pixels)

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
    return _decode_bmp_pixels(backend, encoded, width=width, height=height, mode="grayscale", invert=invert)


def _decode_image(backend: ShortcutsBackend, call: ir.Call) -> ValueRef:
    if len(call.args) != 1:
        raise CompileError(
            "shortcutslib.image.decode_image(value, *, width=..., height=..., mode='grayscale', invert=False) "
            "expects one positional image-like value"
        )
    unknown = {name for name, _ in call.kwargs} - {"width", "height", "mode", "invert"}
    if unknown:
        raise CompileError(
            "shortcutslib.image.decode_image() does not accept keyword(s): " + ", ".join(sorted(unknown))
        )
    width = _literal_int(call.keyword("width"), name="image width")
    height = _literal_int(call.keyword("height"), name="image height")
    mode = _literal_str(call.keyword("mode"), name="image decode mode", default="grayscale").lower()
    invert = _literal_bool(call.keyword("invert"), name="invert", default=False)
    if width <= 0 or height <= 0:
        raise CompileError("image width and height must be positive")
    if mode not in {"grayscale", "rgb", "bgr"}:
        raise CompileError("image decode mode must be one of: grayscale, rgb, bgr")

    source = backend.require_value(backend.emit_expr(call.args[0]), context="image source")
    image = source.coerced("WFImageContentItem")
    # Keep the source dimensions. Resizing through Shortcuts itself can use a
    # different sampling kernel from the one used to train a model, which is
    # especially visible when shrinking MNIST-like images all the way to 7x7.
    converted = action(
        "image.convert",
        WFInput=image.attachment(),
        WFImageFormat="BMP",
        WFImagePreserveMetadata=False,
    )
    backend.actions.append(converted)
    encoded_action = action(
        "base64encode",
        WFInput=ValueRef.action(converted, "Converted Image").attachment(),
        WFEncodeMode="Encode",
    )
    backend.actions.append(encoded_action)
    encoded = ValueRef.action(encoded_action, "Base64 Encoded")
    return _decode_bmp_supersampled(
        backend,
        encoded,
        width=width,
        height=height,
        mode=mode,
        invert=invert,
    )


def register_stdlib_plugins(registry: PluginRegistry) -> None:
    registry.register_call("shortcutslib.image.to_bmp_bytes", _to_bmp_bytes, result_type="bytes")
    registry.register_call(
        "shortcutslib.image.decode_bmp_grayscale",
        _decode_bmp_grayscale,
        result_type="list",
    )
    registry.register_call(
        "shortcutslib.image.decode_image",
        _decode_image,
        result_type="list",
    )
