"""Canonical JSON hashing shared by Python producers and JavaScript consumers."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

_MAX_SAFE_INTEGER = 2**53 - 1


def _ecmascript_number(value: int | float) -> str:
    """Render an I-JSON number with ECMAScript ``JSON.stringify`` semantics."""
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INTEGER:
            raise ValueError("canonical JSON integer exceeds IEEE-754 safe range")
        return str(value)

    number = float(value)
    if not math.isfinite(number):
        raise ValueError("canonical JSON cannot contain non-finite numbers")
    if number == 0:
        return "0"

    rendered = str(number)
    sign = ""
    if rendered.startswith("-"):
        sign, rendered = "-", rendered[1:]

    exponent = 0
    exponent_text = ""
    if "e" in rendered:
        rendered, raw_exponent = rendered.split("e", maxsplit=1)
        exponent = int(raw_exponent)
        exponent_text = f"e{exponent:+d}"

    if "." in rendered:
        first, last = rendered.split(".", maxsplit=1)
        dot = "."
    else:
        first, last, dot = rendered, "", ""
    if last == "0":
        last, dot = "", ""

    if 0 < exponent < 21:
        first += last
        last, dot, exponent_text = "", "", ""
        first += "0" * (exponent - len(first) + 1)
    elif -7 < exponent < 0:
        last = "0" * (-exponent - 1) + first + last
        first, dot, exponent_text = "0", ".", ""

    return sign + first + dot + last + exponent_text


def canonical_json(value: Any) -> str:
    """Serialize the supported I-JSON subset identically to ``JSON.stringify``."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return _ecmascript_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        keys = sorted(value, key=lambda key: key.encode("utf-16-be"))
        return "{" + ",".join(
            f"{json.dumps(key, ensure_ascii=False)}:{canonical_json(value[key])}"
            for key in keys
        ) + "}"
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_hash(value: Any) -> str:
    encoded = canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = ["canonical_hash", "canonical_json"]
