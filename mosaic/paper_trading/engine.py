"""Paper trading engine with SQLite persistence and multi-user support.

Ported from ETFAgents ``paper_trading/engine.py`` (Plan §4.1 / Phase 8 刀1) with
``etfagents`` → ``mosaic`` package + path renames. The signal→order linkage
(``suggest_order_from_signal``) is a stub here; it lands in Phase 8 刀2 together
with the ``mosaic.backtest.signals`` port.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

import bcrypt

from mosaic.paper_trading.rules import (
    calc_commission,
    validate_quantity,
)

logger = logging.getLogger(__name__)

SESSION_PATH_DEFAULT = Path(os.path.expanduser("~/.mosaic/paper_session.json"))
DB_PATH_DEFAULT = Path(os.path.expanduser("~/.mosaic/paper_trading.db"))


class PaperTradingEngine:
    DB_PATH = DB_PATH_DEFAULT
    SESSION_PATH = SESSION_PATH_DEFAULT

    def __init__(self, db_path: Path | None = None, config: dict | None = None):
        self._db = db_path or self.DB_PATH
        self._config = copy.deepcopy(config) if config is not None else None
        self._ensure_schema()
        self._ensure_session_consistency()

    # ------------------------------------------------------------------ auth

    def register(self, username: str, password: str) -> None:
        if not username or not username.strip():
            raise ValueError("Username cannot be empty")
        if username == "default":
            raise ValueError("Cannot register as 'default' user")
        if not password:
            raise ValueError("Password cannot be empty")
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username.strip(), password_hash),
                )
        except sqlite3.IntegrityError:
            raise ValueError(f"User '{username}' already exists")
        # Create account for new user
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO account (user_id) VALUES (?)",
                (username.strip(),),
            )
        logger.info("Registered user '%s'", username)

    def login(self, username: str, password: str) -> bool:
        if not self._verify_password(username, password):
            return False
        session = {"username": username, "login_at": datetime.now().isoformat()}
        session_json = json.dumps(session, ensure_ascii=False)
        session_dir = self.SESSION_PATH.parent
        session_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(session_dir))
        try:
            os.write(fd, session_json.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, str(self.SESSION_PATH))
        logger.info("User '%s' logged in", username)
        return True

    def logout(self) -> str:
        """Remove session file. Returns the username that was logged out, or empty string."""
        if self.SESSION_PATH.exists():
            username = self._get_current_user()
            self.SESSION_PATH.unlink()
            logger.info("Logged out '%s'", username)
            return username
        logger.debug("No active session to clear")
        return ""

    @property
    def current_user(self) -> str:
        """Public accessor for the current logged-in user."""
        return self._get_current_user()

    def _get_current_user(self) -> str:
        session_path = self.SESSION_PATH
        if session_path.exists():
            try:
                data = json.loads(session_path.read_text())
                return data["username"]
            except Exception:
                pass
        return "default"

    def _verify_password(self, username: str, password: str) -> bool:
        if username == "default":
            return True
        with self._connect() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return False
        return bcrypt.checkpw(password.encode(), row["password_hash"].encode())

    def _require_user(self, user_id: str | None) -> str:
        """Resolve and enforce the user for mutating operations.

        Returns the effective user_id.  If *user_id* is explicitly given
        and is not "default", the session must match it.
        """
        current = self._get_current_user()
        if user_id is not None and user_id != "default":
            if current == "default":
                raise PermissionError(
                    f"Not logged in.  Run 'mosaic paper login {user_id}' first."
                )
            if current != user_id:
                raise PermissionError(
                    f"Logged in as '{current}', not '{user_id}'.  "
                    f"Run 'mosaic paper login {user_id}' first."
                )
            return user_id
        return user_id or current

    # ---------------------------------------------------------------- account

    def get_account(self, user_id: str | None = None) -> dict:
        uid = self._require_user(user_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cash, realized_pnl, total_commission, updated_at "
                "FROM account WHERE user_id = ?",
                (uid,),
            ).fetchone()
            if row is None:
                user = conn.execute(
                    "SELECT username FROM users WHERE username = ?",
                    (uid,),
                ).fetchone()
                if user is None:
                    raise RuntimeError(f"Account not found for user '{uid}'. Register first.")
                conn.execute(
                    "INSERT OR IGNORE INTO account (user_id) VALUES (?)",
                    (uid,),
                )
                row = conn.execute(
                    "SELECT cash, realized_pnl, total_commission, updated_at "
                    "FROM account WHERE user_id = ?",
                    (uid,),
                ).fetchone()
                if row is None:
                    raise RuntimeError(
                        f"Account not found for user '{uid}'. Register first."
                    )
        cash = row["cash"]
        realized_pnl = row["realized_pnl"]
        total_commission = row["total_commission"]
        updated_at = row["updated_at"]
        positions = self.get_positions(user_id=uid)
        market_value = sum(p["market_value"] for p in positions)
        unrealized_pnl = sum(p["unrealized_pnl"] for p in positions)
        return {
            "cash": cash,
            "realized_pnl": realized_pnl,
            "total_commission": total_commission,
            "market_value": market_value,
            "total_assets": cash + market_value,
            "unrealized_pnl": unrealized_pnl,
            "updated_at": updated_at,
            "user_id": uid,
        }

    def reset_account(self, user_id: str | None = None,
                      initial_cash: float = 1_000_000.0) -> None:
        uid = self._require_user(user_id)
        # All statements inside a single with-block: sqlite3 commits on clean exit.
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM trades WHERE user_id = ?", (uid,))
            conn.execute(
                "DELETE FROM positions WHERE user_id = ?", (uid,))
            conn.execute(
                "INSERT INTO account (user_id, cash, realized_pnl, total_commission) "
                "VALUES (?, ?, 0.0, 0.0) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "cash=excluded.cash, realized_pnl=excluded.realized_pnl, "
                "total_commission=excluded.total_commission, updated_at=datetime('now')",
                (uid, initial_cash),
            )
        logger.info("Account '%s' reset to %.2f", uid, initial_cash)

    # ------------------------------------------------------------------ trade

    def buy(self, ticker: str, quantity: int, user_id: str | None = None,
            analysis_id: str | None = None) -> dict:
        uid = self._require_user(user_id)
        validate_quantity(quantity)
        self._update_day_barrier(uid)
        price = self._get_current_price(ticker)
        amount = price * quantity
        commission = calc_commission(amount)
        total_cost = amount + commission

        with self._connect() as conn:
            account = conn.execute(
                "SELECT cash FROM account WHERE user_id = ?", (uid,)
            ).fetchone()
            if account is None:
                raise RuntimeError(f"Account not found for user '{uid}'. Register first.")
            if account["cash"] < total_cost:
                raise ValueError(
                    f"Insufficient cash: need {total_cost:.2f}, have {account['cash']:.2f}"
                )
            name = self._auto_fill_name(ticker)
            # Update or insert position
            existing = conn.execute(
                "SELECT quantity, avg_cost FROM positions WHERE user_id = ? AND ticker = ?",
                (uid, ticker),
            ).fetchone()
            if existing:
                old_qty = existing["quantity"]
                old_avg = existing["avg_cost"]
                new_total_value = old_qty * old_avg + amount
                new_qty = old_qty + quantity
                new_avg = new_total_value / new_qty if new_qty else 0.0
                conn.execute(
                    "UPDATE positions SET quantity = ?, avg_cost = ?, name = ?, updated_at = datetime('now') "
                    "WHERE user_id = ? AND ticker = ?",
                    (new_qty, round(new_avg, 6), name, uid, ticker),
                )
            else:
                conn.execute(
                    "INSERT INTO positions (user_id, ticker, name, quantity, available_qty, avg_cost) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (uid, ticker, name, quantity, 0, round(price, 6)),
                )
            # Deduct cash
            conn.execute(
                "UPDATE account SET cash = cash - ?, total_commission = total_commission + ?, "
                "updated_at = datetime('now') WHERE user_id = ?",
                (total_cost, commission, uid),
            )
            # Record trade
            conn.execute(
                "INSERT INTO trades (user_id, ticker, name, side, quantity, price, amount, "
                "commission, analysis_id) VALUES (?, ?, ?, 'buy', ?, ?, ?, ?, ?)",
                (uid, ticker, name, quantity, price, amount, commission, analysis_id),
            )
        logger.info(
            "%s bought %d x %s @ %.4f (total: %.2f, commission: %.2f)",
            uid, quantity, ticker, price, total_cost, commission,
        )
        return {
            "ticker": ticker,
            "side": "buy",
            "quantity": quantity,
            "price": price,
            "amount": amount,
            "commission": commission,
            "total_cost": total_cost,
        }

    def sell(self, ticker: str, quantity: int, user_id: str | None = None,
             analysis_id: str | None = None) -> dict:
        uid = self._require_user(user_id)
        validate_quantity(quantity)
        self._update_day_barrier(uid)
        price = self._get_current_price(ticker)
        amount = price * quantity
        commission = calc_commission(amount)

        with self._connect() as conn:
            position = conn.execute(
                "SELECT name, quantity, available_qty, avg_cost "
                "FROM positions WHERE user_id = ? AND ticker = ?",
                (uid, ticker),
            ).fetchone()
            if position is None:
                raise ValueError(f"No position found for {ticker}")
            if position["available_qty"] < quantity:
                raise ValueError(
                    f"Insufficient available shares for {ticker}: "
                    f"need {quantity}, have {position['available_qty']} "
                    f"(T+1: {position['quantity'] - position['available_qty']} unavailable)"
                )
            name = position["name"] or self._auto_fill_name(ticker)
            avg_cost = position["avg_cost"]
            pnl = (price - avg_cost) * quantity - commission
            new_qty = position["quantity"] - quantity
            new_avail = position["available_qty"] - quantity
            if new_qty <= 0:
                conn.execute(
                    "DELETE FROM positions WHERE user_id = ? AND ticker = ?",
                    (uid, ticker),
                )
            else:
                conn.execute(
                    "UPDATE positions SET quantity = ?, available_qty = ?, "
                    "updated_at = datetime('now') WHERE user_id = ? AND ticker = ?",
                    (new_qty, new_avail, uid, ticker),
                )
            # Update account
            conn.execute(
                "UPDATE account SET cash = cash + ?, realized_pnl = realized_pnl + ?, "
                "total_commission = total_commission + ?, updated_at = datetime('now') "
                "WHERE user_id = ?",
                (amount - commission, pnl, commission, uid),
            )
            conn.execute(
                "INSERT INTO trades (user_id, ticker, name, side, quantity, price, amount, "
                "commission, pnl, analysis_id) VALUES (?, ?, ?, 'sell', ?, ?, ?, ?, ?, ?)",
                (uid, ticker, name, quantity, price, amount, commission, round(pnl, 2), analysis_id),
            )
        logger.info(
            "%s sold %d x %s @ %.4f (amount: %.2f, commission: %.2f, PnL: %.2f)",
            uid, quantity, ticker, price, amount, commission, pnl,
        )
        return {
            "ticker": ticker,
            "side": "sell",
            "quantity": quantity,
            "price": price,
            "amount": amount,
            "commission": commission,
            "pnl": round(pnl, 2),
        }

    # ---------------------------------------------------------------- queries

    def get_positions(self, user_id: str | None = None) -> list[dict]:
        uid = self._require_user(user_id)
        self._update_day_barrier(uid)  # unlock T+1 shares on a new day before reading
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ticker, name, quantity, available_qty, avg_cost, updated_at "
                "FROM positions WHERE user_id = ? AND quantity > 0 ORDER BY ticker",
                (uid,),
            ).fetchall()
        results: list[dict] = []
        for r in rows:
            try:
                price = self._get_current_price(r["ticker"])
            except Exception:
                price = r["avg_cost"]
            market_value = round(price * r["quantity"], 2)
            unrealized_pnl = round((price - r["avg_cost"]) * r["quantity"], 2)
            pnl_pct = (
                round((price - r["avg_cost"]) / r["avg_cost"] * 100, 2)
                if r["avg_cost"] != 0 else 0.0
            )
            results.append({
                "ticker": r["ticker"],
                "name": r["name"],
                "quantity": r["quantity"],
                "available_qty": r["available_qty"],
                "avg_cost": r["avg_cost"],
                "current_price": price,
                "market_value": market_value,
                "unrealized_pnl": unrealized_pnl,
                "pnl_pct": pnl_pct,
                "updated_at": r["updated_at"],
            })
        return results

    def get_trades(self, user_id: str | None = None, limit: int = 50) -> list[dict]:
        uid = self._require_user(user_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, user_id, ticker, name, side, quantity, price, amount, "
                "commission, pnl, analysis_id, created_at "
                "FROM trades WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (uid, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------- signal linkage

    def suggest_order_from_signal(self, ticker: str, state: dict,
                                  user_id: str | None = None) -> dict | None:
        from mosaic.backtest.signals import BacktestSignal, build_state_backtest_signal
        from mosaic.dataflows.exceptions import DataVendorUnavailable
        signal_dict = build_state_backtest_signal(state)
        signal = BacktestSignal(**signal_dict) if signal_dict else None
        if not signal or signal.target_weight_pct is None:
            return None
        signal_ticker = signal.ticker or ticker
        if signal_ticker != ticker:
            raise ValueError(
                f"Signal ticker '{signal_ticker}' does not match requested ticker '{ticker}'"
            )

        uid = user_id or self._get_current_user()
        account = self.get_account(uid)
        try:
            price = self._get_current_price(signal_ticker)
        except (DataVendorUnavailable, RuntimeError):
            logger.warning("Cannot fetch price for %s, skipping suggestion", signal_ticker)
            return None
        target_value = account["total_assets"] * signal.target_weight_pct / 100
        current_value = self._position_market_value(signal_ticker, uid)
        delta_value = target_value - current_value

        if delta_value > 0:
            qty = int(delta_value / price / 100) * 100
            if qty >= 100:
                return {
                    "ticker": signal_ticker,
                    "side": "buy",
                    "quantity": qty,
                    "price": price,
                    "target_weight_pct": signal.target_weight_pct,
                    "rating": signal.rating,
                }
        elif delta_value < 0:
            qty = int(abs(delta_value) / price / 100) * 100
            avail = self._available_qty(signal_ticker, uid)
            qty = min(qty, avail)
            if qty >= 100:
                return {
                    "ticker": signal_ticker,
                    "side": "sell",
                    "quantity": qty,
                    "price": price,
                    "target_weight_pct": signal.target_weight_pct,
                    "rating": signal.rating,
                }
        return None

    # --------------------------------------------------------------- internal

    @contextmanager
    def _vendor_config_context(self):
        if self._config is None:
            yield
            return

        from mosaic.dataflows.config import get_config, set_config

        previous_config = get_config()
        set_config(self._config)
        try:
            yield
        finally:
            set_config(previous_config)

    def _get_current_price(self, ticker: str) -> float:
        from mosaic.dataflows.interface import route_to_vendor
        today = date.today().isoformat()
        start = (date.today() - timedelta(days=30)).isoformat()
        with self._vendor_config_context():
            csv_text = route_to_vendor("get_etf_price_data", ticker, start, today)
        if not csv_text:
            raise RuntimeError(f"No price data returned for {ticker}")
        from mosaic.paper_trading._detail import _parse_csv_last_row, _safe_float
        row = _parse_csv_last_row(csv_text)
        if row is None:
            raise RuntimeError(f"No price data for {ticker}")
        close = _safe_float(row.get("close"))
        if close is None:
            raise RuntimeError(f"Could not parse close price for {ticker}")
        return close

    def _update_day_barrier(self, user_id: str) -> None:
        # Persists the last unlock date in account.last_unlock_date.
        # On a new calendar day, all positions unlock (available_qty = quantity).
        # Same-day process restarts will NOT re-unlock because the DB date
        # matches today — preserving the T+1 guarantee across restarts.
        today = date.today().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT last_unlock_date FROM account WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row and row["last_unlock_date"] == today:
                return
            conn.execute(
                "UPDATE positions SET available_qty = quantity WHERE user_id = ?",
                (user_id,),
            )
            conn.execute(
                "UPDATE account SET last_unlock_date = ? WHERE user_id = ?",
                (today, user_id),
            )

    def _auto_fill_name(self, ticker: str) -> str:
        try:
            from mosaic.dataflows.interface import route_to_vendor
            today_iso = date.today().isoformat()
            with self._vendor_config_context():
                csv_text = route_to_vendor("get_etf_info", ticker, today_iso)
            if not csv_text or "No ETF profile" in csv_text:
                return ticker
            import csv as csv_mod
            import io
            clean_lines = []
            for line in csv_text.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    clean_lines.append(line)
            reader = csv_mod.DictReader(io.StringIO("\n".join(clean_lines)))
            for row in reader:
                if "name" in row and row["name"].strip():
                    return row["name"].strip()
            return ticker
        except Exception:
            return ticker

    def _ensure_schema(self) -> None:
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    username        TEXT    PRIMARY KEY,
                    password_hash   TEXT    NOT NULL DEFAULT '',
                    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
                );
                INSERT OR IGNORE INTO users (username) VALUES ('default');

                CREATE TABLE IF NOT EXISTS account (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id         TEXT    NOT NULL REFERENCES users(username),
                    cash            REAL    NOT NULL DEFAULT 1000000.0,
                    realized_pnl    REAL    NOT NULL DEFAULT 0.0,
                    total_commission REAL   NOT NULL DEFAULT 0.0,
                    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                    last_unlock_date TEXT,
                    UNIQUE(user_id)
                );

                CREATE TABLE IF NOT EXISTS positions (
                    user_id         TEXT    NOT NULL REFERENCES users(username),
                    ticker          TEXT    NOT NULL,
                    name            TEXT    NOT NULL DEFAULT '',
                    quantity        INTEGER NOT NULL DEFAULT 0,
                    available_qty   INTEGER NOT NULL DEFAULT 0,
                    avg_cost        REAL    NOT NULL DEFAULT 0.0,
                    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (user_id, ticker)
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id         TEXT    NOT NULL REFERENCES users(username),
                    ticker          TEXT    NOT NULL,
                    name            TEXT    NOT NULL DEFAULT '',
                    side            TEXT    NOT NULL CHECK (side IN ('buy', 'sell')),
                    quantity        INTEGER NOT NULL,
                    price           REAL    NOT NULL,
                    amount          REAL    NOT NULL,
                    commission      REAL    NOT NULL DEFAULT 0.0,
                    pnl             REAL    DEFAULT NULL,
                    analysis_id     TEXT    DEFAULT NULL,
                    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_trades_user ON trades(user_id);
                CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(user_id, ticker);
                CREATE INDEX IF NOT EXISTS idx_trades_created ON trades(user_id, created_at DESC);
            """)
            # Migration: add last_unlock_date to existing databases
            try:
                conn.execute(
                    "ALTER TABLE account ADD COLUMN last_unlock_date TEXT"
                )
            except sqlite3.OperationalError:
                pass
            conn.execute(
                "INSERT OR IGNORE INTO account (user_id) VALUES ('default')"
            )

    def _ensure_session_consistency(self) -> None:
        if not self.SESSION_PATH.exists():
            return
        try:
            data = json.loads(self.SESSION_PATH.read_text())
            username = data.get("username", "")
        except Exception:
            return
        if not username:
            return
        with self._connect() as conn:
            row = conn.execute(
                "SELECT username FROM users WHERE username = ?", (username,)
            ).fetchone()
        if row is None:
            self.SESSION_PATH.unlink(missing_ok=True)
            logger.warning(
                "Session user '%s' not found in DB, session cleared", username
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _position_market_value(self, ticker: str, user_id: str) -> float:
        with self._connect() as conn:
            pos = conn.execute(
                "SELECT quantity, avg_cost FROM positions WHERE user_id = ? AND ticker = ?",
                (user_id, ticker),
            ).fetchone()
        if pos is None:
            return 0.0
        try:
            price = self._get_current_price(ticker)
        except Exception:
            price = pos["avg_cost"]
        return round(price * pos["quantity"], 2)

    def _available_qty(self, ticker: str, user_id: str) -> int:
        with self._connect() as conn:
            pos = conn.execute(
                "SELECT available_qty FROM positions WHERE user_id = ? AND ticker = ?",
                (user_id, ticker),
            ).fetchone()
        return pos["available_qty"] if pos else 0
