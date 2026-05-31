import copy
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping

import mosaic.default_config as default_config

_DEFAULT_CONFIG = copy.deepcopy(default_config.DEFAULT_CONFIG)

# Persisted user overrides. Absent file ⇒ pure DEFAULT_CONFIG (today's behavior).
_CONFIG_FILE = Path(os.path.expanduser(os.environ.get("MOSAIC_CONFIG", "~/.mosaic/config.json")))
_config_var: ContextVar[Dict[str, Any]] = ContextVar(
    "mosaic_config",
    default=copy.deepcopy(_DEFAULT_CONFIG),
)


@dataclass(frozen=True)
class BacktestContext:
    mode: str = "live"
    as_of_date: str | None = None


@dataclass
class BacktestHealthState:
    clamp_hits: int = 0
    blocked_calls: int = 0


_backtest_context_var: ContextVar[BacktestContext] = ContextVar(
    "mosaic_backtest_context",
    default=BacktestContext(),
)
_backtest_health_var: ContextVar[BacktestHealthState | None] = ContextVar(
    "mosaic_backtest_health",
    default=None,
)


def _merged_config(config: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    merged = copy.deepcopy(_DEFAULT_CONFIG)
    if config:
        for key, value in config.items():
            merged[key] = copy.deepcopy(value)
    return merged


def _load_persisted() -> Dict[str, Any] | None:
    """Read ~/.mosaic/config.json if present; None on absent/invalid (fail-soft)."""
    if not _CONFIG_FILE.is_file():
        return None
    try:
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def initialize_config() -> None:
    """Initialize the current execution context, merging any persisted overrides
    from ~/.mosaic/config.json over DEFAULT_CONFIG (absent file ⇒ defaults only)."""
    _config_var.set(_merged_config(_load_persisted()))


def set_config(config: Mapping[str, Any] | None) -> None:
    """Set the configuration for the current execution context."""
    _config_var.set(_merged_config(config))


def save_config(config: Mapping[str, Any] | None) -> Dict[str, Any]:
    """Persist ``config`` to ~/.mosaic/config.json and apply it to this context.

    Returns the new active (merged) config. Writes the raw overrides given
    (merged-with-defaults shape is fine — load re-merges over defaults anyway).
    """
    merged = _merged_config(config)
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    _config_var.set(merged)
    return copy.deepcopy(merged)


def get_config() -> Dict[str, Any]:
    """Return a deep-copied configuration for the current execution context."""
    return copy.deepcopy(_config_var.get())


def get_backtest_context() -> BacktestContext:
    """Return the current backtest/runtime date context for this execution context."""
    return _backtest_context_var.get()


def set_backtest_context(as_of_date: str | None, mode: str = "backtest") -> None:
    """Set the backtest/runtime date context for the current execution context."""
    _backtest_context_var.set(
        BacktestContext(
            mode=(mode or "backtest").strip().lower(),
            as_of_date=copy.deepcopy(as_of_date),
        )
    )


def clear_backtest_context() -> None:
    """Clear the backtest/runtime date context for the current execution context."""
    _backtest_context_var.set(BacktestContext())


def get_backtest_health_state() -> BacktestHealthState:
    state = _backtest_health_var.get()
    if state is None:
        return BacktestHealthState()
    return copy.deepcopy(state)


def increment_backtest_health(*, clamp_hit: bool = False, blocked_call: bool = False) -> None:
    state = _backtest_health_var.get()
    if state is None:
        return
    if clamp_hit:
        state.clamp_hits += 1
    if blocked_call:
        state.blocked_calls += 1


@contextmanager
def backtest_health_context():
    token = _backtest_health_var.set(BacktestHealthState())
    try:
        yield _backtest_health_var.get()
    finally:
        _backtest_health_var.reset(token)


@contextmanager
def backtest_context(as_of_date: str | None, mode: str = "backtest"):
    """Temporarily set a backtest/runtime date context for nested tool routing."""
    token = _backtest_context_var.set(
        BacktestContext(
            mode=(mode or "backtest").strip().lower(),
            as_of_date=copy.deepcopy(as_of_date),
        )
    )
    try:
        yield _backtest_context_var.get()
    finally:
        _backtest_context_var.reset(token)


initialize_config()
