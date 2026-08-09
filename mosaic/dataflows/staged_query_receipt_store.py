"""Append-only authority for exact staged-query source receipts."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.staged_query_receipts import (
    seal_staged_query_source_receipt,
    validate_staged_query_source_receipt,
)
from mosaic.scorecard.canonical_json import canonical_hash


_DESCRIPTOR_FIELDS = (
    "tool_id",
    "route_id",
    "as_of",
    "request_hash",
    "content_hash",
    "pit_mode",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _aware_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("staged query receipt clock must return an aware datetime")
    return value.astimezone(timezone.utc)


class StagedQueryReceiptStore:
    """Persist immutable receipt evidence and sign only legal live captures."""

    def __init__(
        self,
        db_path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = db_path
        if "registry" in db_path.parts:
            raise ValueError("staged query receipts must not be stored in registry")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS staged_query_receipts (
                    descriptor_hash TEXT PRIMARY KEY,
                    descriptor_json TEXT NOT NULL,
                    receipt_hash TEXT NOT NULL UNIQUE,
                    receipt_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS staged_query_receipts_no_update
                BEFORE UPDATE ON staged_query_receipts
                BEGIN
                    SELECT RAISE(ABORT, 'staged query receipts are append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS staged_query_receipts_no_delete
                BEFORE DELETE ON staged_query_receipts
                BEGIN
                    SELECT RAISE(ABORT, 'staged query receipts are append-only');
                END;
                """
            )

    @staticmethod
    def _descriptor(value: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping) or set(value) != set(_DESCRIPTOR_FIELDS):
            raise ValueError("staged query descriptor fields do not match the contract")
        return {field: value[field] for field in _DESCRIPTOR_FIELDS}

    @staticmethod
    def _read_existing(
        row: sqlite3.Row, *, expected_descriptor: Mapping[str, Any]
    ) -> dict[str, Any]:
        descriptor = json.loads(row["descriptor_json"])
        if descriptor != dict(expected_descriptor):
            raise ValueError("staged query receipt descriptor hash collision")
        receipt = json.loads(row["receipt_json"])
        if (
            validate_staged_query_source_receipt(
                receipt,
                expected_descriptor=expected_descriptor,
                require_eligible=True,
            )
            != row["receipt_hash"]
        ):
            raise ValueError("staged query receipt storage hash mismatch")
        return receipt

    def resolve(self, descriptor: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Reuse an exact receipt or capture a same-window OBSERVED_LIVE result."""

        exact = self._descriptor(descriptor)
        descriptor_hash = canonical_hash(exact)
        now = _aware_now(self.clock)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM staged_query_receipts WHERE descriptor_hash = ?",
                (descriptor_hash,),
            ).fetchone()
            if row is not None:
                return [self._read_existing(row, expected_descriptor=exact)]
            if exact.get("pit_mode") != "OBSERVED_LIVE":
                raise DataVendorUnavailable(
                    "query requires an authoritative source receipt before materialization"
                )
            try:
                receipt = seal_staged_query_source_receipt(
                    exact,
                    knowledge_available_at=now.isoformat(),
                    captured_at=now.isoformat(),
                )
            except ValueError as exc:
                raise DataVendorUnavailable(
                    "historical OBSERVED_LIVE query has no exact eligible capture"
                ) from exc
            connection.execute(
                """
                INSERT INTO staged_query_receipts (
                    descriptor_hash,
                    descriptor_json,
                    receipt_hash,
                    receipt_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    descriptor_hash,
                    _canonical_json(exact),
                    receipt["receipt_hash"],
                    _canonical_json(receipt),
                    now.isoformat(),
                ),
            )
            return [receipt]

    def register(self, receipt: Mapping[str, Any]) -> str:
        """Register an independently proven vintage/archive receipt exactly once."""

        if not isinstance(receipt, Mapping):
            raise ValueError("staged query receipt must be an object")
        try:
            descriptor = {field: receipt[field] for field in _DESCRIPTOR_FIELDS}
        except KeyError as exc:
            raise ValueError("staged query receipt descriptor is incomplete") from exc
        exact = self._descriptor(descriptor)
        receipt_hash = validate_staged_query_source_receipt(
            receipt,
            expected_descriptor=exact,
            require_eligible=True,
        )
        descriptor_hash = canonical_hash(exact)
        now = _aware_now(self.clock)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM staged_query_receipts WHERE descriptor_hash = ?",
                (descriptor_hash,),
            ).fetchone()
            if row is not None:
                existing = self._read_existing(row, expected_descriptor=exact)
                if existing["receipt_hash"] != receipt_hash:
                    raise ValueError("conflicting staged query receipt for descriptor")
                return receipt_hash
            connection.execute(
                """
                INSERT INTO staged_query_receipts (
                    descriptor_hash,
                    descriptor_json,
                    receipt_hash,
                    receipt_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    descriptor_hash,
                    _canonical_json(exact),
                    receipt_hash,
                    _canonical_json(dict(receipt)),
                    now.isoformat(),
                ),
            )
        return receipt_hash

    def __call__(self, descriptor: Mapping[str, Any]) -> list[dict[str, Any]]:
        return self.resolve(descriptor)


__all__ = ["StagedQueryReceiptStore"]
