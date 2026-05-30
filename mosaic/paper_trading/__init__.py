"""Paper trading simulation package (Plan §4.1 / Phase 8).

Public names are lazily imported (PEP 562 ``__getattr__``) so importing the
package doesn't pull bcrypt/sqlite transitively at load time.
"""

from __future__ import annotations

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "PaperTradingEngine": (".engine", "PaperTradingEngine"),
    "calc_commission": (".rules", "calc_commission"),
    "calc_stamp_duty": (".rules", "calc_stamp_duty"),
    "COMMISSION_RATE": (".rules", "COMMISSION_RATE"),
    "estimate_trade_cost": (".rules", "estimate_trade_cost"),
    "get_t1_available": (".rules", "get_t1_available"),
    "LOT_SIZE": (".rules", "LOT_SIZE"),
    "MIN_COMMISSION": (".rules", "MIN_COMMISSION"),
    "STAMP_DUTY_RATE": (".rules", "STAMP_DUTY_RATE"),
    "validate_quantity": (".rules", "validate_quantity"),
}

__all__ = list(_LAZY_IMPORTS.keys())


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        import importlib

        module_path, attr = _LAZY_IMPORTS[name]
        value = getattr(importlib.import_module(module_path, __package__), attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
