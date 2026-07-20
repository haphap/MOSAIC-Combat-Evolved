"""RFC 8785/JCS hashing shared by Python producers and JavaScript consumers."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

_MAX_SAFE_INTEGER = 2**53 - 1
CANONICAL_JSON_CONTRACT_VERSION = "rfc8785_jcs_v1"


def _ecmascript_number(value: float) -> str:
    """Render one finite binary64 value with ECMAScript number semantics."""
    if not math.isfinite(value):
        raise ValueError("canonical JSON rejects non-finite numbers")
    if value == 0:
        return "0"
    negative = value < 0
    absolute = -value if negative else value
    rendered = repr(absolute).lower()
    if "e" in rendered:
        mantissa, exponent_text = rendered.split("e", 1)
        exponent = int(exponent_text)
        digits = mantissa.replace(".", "").rstrip("0") or "0"
        decimal_position = 1 + exponent
        if 1e-6 <= absolute < 1e21:
            if decimal_position <= 0:
                rendered = "0." + "0" * (-decimal_position) + digits
            elif decimal_position >= len(digits):
                rendered = digits + "0" * (decimal_position - len(digits))
            else:
                rendered = digits[:decimal_position] + "." + digits[decimal_position:]
        else:
            mantissa = digits[0]
            if len(digits) > 1:
                mantissa += "." + digits[1:]
            suffix = f"+{exponent}" if exponent >= 0 else str(exponent)
            rendered = f"{mantissa}e{suffix}"
    elif rendered.endswith(".0"):
        rendered = rendered[:-2]
    return f"-{rendered}" if negative else rendered


def _ecmascript_integer(value: int) -> str:
    if abs(value) <= _MAX_SAFE_INTEGER:
        return str(value)
    try:
        binary64 = float(value)
    except OverflowError as exc:
        raise ValueError("canonical JSON integer exceeds binary64 range") from exc
    if not math.isfinite(binary64) or int(binary64) != value:
        raise ValueError("canonical JSON integer is not exactly representable as binary64")
    return _ecmascript_number(binary64)


def canonical_json(value: Any) -> str:
    """Serialize the supported I-JSON subset identically to ``JSON.stringify``."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return _ecmascript_integer(value)
    if isinstance(value, float):
        return _ecmascript_number(value)
    if isinstance(value, str):
        _assert_valid_unicode(value)
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        keys = sorted(value, key=_utf16_sort_key)
        return "{" + ",".join(
            f"{json.dumps(key, ensure_ascii=False)}:{canonical_json(value[key])}"
            for key in keys
        ) + "}"
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def _assert_valid_unicode(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError("canonical JSON rejects unpaired Unicode surrogates")


def _utf16_sort_key(value: str) -> bytes:
    _assert_valid_unicode(value)
    return value.encode("utf-16-be")


def canonical_hash(value: Any) -> str:
    encoded = canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "CANONICAL_JSON_CONTRACT_VERSION",
    "canonical_hash",
    "canonical_json",
]
