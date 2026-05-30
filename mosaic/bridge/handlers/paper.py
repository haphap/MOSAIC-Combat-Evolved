"""``paper.*`` JSON-RPC handlers wrapping ``PaperTradingEngine``.

Stateless: a fresh engine is constructed per call (matching the existing CLI
pattern in ``cli/commands/paper.py``). The engine's SQLite connection is
opened/closed inside its own methods so each RPC is self-contained.

Engine ported in Phase 8. All ``paper.*`` methods are live, including
``suggest_order_from_signal`` (the signal→order linkage, 刀2). The lazy import
maps a missing ``.[trading]`` extra (bcrypt) to ``PAPER_ERROR``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..protocol import INVALID_PARAMS, PAPER_ERROR, RpcError
from ..registry import method


def _engine(params: dict[str, Any]):
    try:
        from mosaic.dataflows.config import get_config
        from mosaic.paper_trading.engine import PaperTradingEngine
    except ImportError as exc:
        raise RpcError(
            PAPER_ERROR,
            "paper trading needs the '.[trading]' extra (bcrypt): " + str(exc),
        ) from exc

    db_path = params.get("db_path")
    return PaperTradingEngine(
        db_path=Path(db_path) if db_path else None,
        config=get_config(),
    )


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return value


def _opt_str(params: dict[str, Any], key: str) -> str | None:
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a string when provided")
    return value


def _require_int(params: dict[str, Any], key: str) -> int:
    value = params.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be an integer")
    return value


def _wrap(callable_, *args, **kwargs):
    """Run an engine method, mapping its exceptions to PAPER_ERROR."""
    try:
        return callable_(*args, **kwargs)
    except RpcError:
        raise
    except Exception as exc:
        raise RpcError(PAPER_ERROR, f"{type(exc).__name__}: {exc}") from exc


# -------------------------------------------------------------------- auth


@method("paper.register")
def paper_register(params: dict[str, Any]) -> dict[str, Any]:
    username = _require_str(params, "username")
    password = _require_str(params, "password")
    _wrap(_engine(params).register, username, password)
    return {"username": username}


@method("paper.login")
def paper_login(params: dict[str, Any]) -> dict[str, Any]:
    username = _require_str(params, "username")
    password = _require_str(params, "password")
    ok = _wrap(_engine(params).login, username, password)
    return {"ok": bool(ok), "username": username if ok else None}


@method("paper.logout")
def paper_logout(params: dict[str, Any]) -> dict[str, Any]:
    logged_out = _wrap(_engine(params).logout)
    return {"logged_out": logged_out or None}


@method("paper.current_user")
def paper_current_user(params: dict[str, Any]) -> dict[str, Any]:
    # ``current_user`` is a @property on the engine, not a method.
    try:
        user = _engine(params).current_user
    except Exception as exc:
        raise RpcError(PAPER_ERROR, f"{type(exc).__name__}: {exc}") from exc
    return {"user": user}


# ---------------------------------------------------------------- account


@method("paper.get_account")
def paper_get_account(params: dict[str, Any]) -> dict[str, Any]:
    return _wrap(_engine(params).get_account, user_id=_opt_str(params, "user_id"))


@method("paper.reset_account")
def paper_reset_account(params: dict[str, Any]) -> dict[str, Any]:
    initial_cash = params.get("initial_cash", 1_000_000.0)
    if not isinstance(initial_cash, (int, float)) or isinstance(initial_cash, bool):
        raise RpcError(INVALID_PARAMS, "'initial_cash' must be numeric")
    _wrap(
        _engine(params).reset_account,
        user_id=_opt_str(params, "user_id"),
        initial_cash=float(initial_cash),
    )
    return {"ok": True}


# ------------------------------------------------------------------ trade


@method("paper.buy")
def paper_buy(params: dict[str, Any]) -> dict[str, Any]:
    return _wrap(
        _engine(params).buy,
        ticker=_require_str(params, "ticker"),
        quantity=_require_int(params, "quantity"),
        user_id=_opt_str(params, "user_id"),
        analysis_id=_opt_str(params, "analysis_id"),
    )


@method("paper.sell")
def paper_sell(params: dict[str, Any]) -> dict[str, Any]:
    return _wrap(
        _engine(params).sell,
        ticker=_require_str(params, "ticker"),
        quantity=_require_int(params, "quantity"),
        user_id=_opt_str(params, "user_id"),
        analysis_id=_opt_str(params, "analysis_id"),
    )


# ---------------------------------------------------------------- queries


@method("paper.get_positions")
def paper_get_positions(params: dict[str, Any]) -> list[dict[str, Any]]:
    return _wrap(_engine(params).get_positions, user_id=_opt_str(params, "user_id"))


@method("paper.get_trades")
def paper_get_trades(params: dict[str, Any]) -> list[dict[str, Any]]:
    limit = params.get("limit", 50)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise RpcError(INVALID_PARAMS, "'limit' must be a positive integer")
    return _wrap(
        _engine(params).get_trades,
        user_id=_opt_str(params, "user_id"),
        limit=limit,
    )


# -------------------------------------------------------- signal linkage


@method("paper.suggest_order_from_signal")
def paper_suggest_order_from_signal(params: dict[str, Any]) -> dict[str, Any] | None:
    state = params.get("state")
    if not isinstance(state, dict):
        raise RpcError(INVALID_PARAMS, "'state' must be an object")
    return _wrap(
        _engine(params).suggest_order_from_signal,
        ticker=_require_str(params, "ticker"),
        state=state,
        user_id=_opt_str(params, "user_id"),
    )
