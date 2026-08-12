"""Read restored research and policy queries from existing forward archives."""

from __future__ import annotations

import fcntl
import json
import threading
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Callable, Iterator
from zoneinfo import ZoneInfo

import pandas as pd

from mosaic.dataflows.agent_materialization import SourceCaptureReceipt
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.gov_policy import (
    GOV_POLICY_CATEGORIES,
    _date_window,
    _records_in_window,
    _records_to_markdown_csv,
    gov_policy_cache_dir,
    load_gov_policy_records,
)
from mosaic.dataflows.sector_archive import sector_archive_source_receipt
from mosaic.dataflows.tushare import (
    _classify_market,
    _extract_most_common_ind_name,
    _normalize_ts_code,
    _render_broker_research_frame,
    _render_stock_research_frame,
)
from mosaic.scorecard.canonical_json import canonical_hash


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_RESEARCH_ROUTE = "private.tushare_research_reports"
_POLICY_ROUTE = "official.govcn_policy"
_RESEARCH_FIELDS = (
    "abstract",
    "author",
    "discovered_at",
    "industry",
    "institution",
    "publish_date",
    "query_key",
    "report_type",
    "source_hash",
    "source_id",
    "title",
    "ts_code",
    "url",
)
_POLICY_FIELDS = (
    "article_id",
    "category",
    "category_id",
    "childtype",
    "discovered_at",
    "matched_queries",
    "pcode",
    "pub_date",
    "puborg",
    "raw_sha256",
    "summary",
    "title",
    "url",
)


@dataclass(frozen=True)
class _Selection:
    route_id: str
    source_family: str
    request: dict[str, Any]
    rows: tuple[dict[str, Any], ...]
    payload: str
    captured_at: datetime
    release_at: datetime
    observed_start: str
    observed_end: str
    redacted_url: str
    parser_version: str
    schema_fields: tuple[str, ...]
    parent_capture_hash: str | None = None


def _timestamp(value: Any, field: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise DataVendorUnavailable(f"{field} is unavailable")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataVendorUnavailable(f"{field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DataVendorUnavailable(f"{field} must include a timezone")
    return parsed


def _published_at(value: Any, field: str) -> datetime:
    try:
        published = date.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise DataVendorUnavailable(f"{field} is invalid") from exc
    return datetime.combine(published, time.min, tzinfo=_SHANGHAI)


def _cutoff(as_of: str) -> datetime:
    try:
        parsed = date.fromisoformat(as_of)
    except ValueError as exc:
        raise DataVendorUnavailable("query as_of is invalid") from exc
    return datetime.combine(parsed, time.max, tzinfo=_SHANGHAI)


def _strict_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise DataVendorUnavailable(f"{label} archive is unavailable")
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("row is not an object")
            rows.append(row)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(f"{label} archive is malformed") from exc
    return rows


def _report_frame(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": str(row["publish_date"]).replace("-", ""),
                "title": row.get("title", ""),
                "abstr": row.get("abstract", ""),
                "author": row.get("author", ""),
                "inst_csname": row.get("institution", ""),
                "ts_code": row.get("ts_code", ""),
                "ind_name": row.get("industry", ""),
                "url": row.get("url", ""),
            }
            for row in rows
        ]
    )


class ForwardArchiveQueryReader:
    """Render research/policy queries without live transport or implicit fallback."""

    def __init__(
        self,
        *,
        root: str | Path,
        sector_archive_store: Any | None = None,
        policy_cache_dir: str | Path | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.sector_archive_store = sector_archive_store
        self.policy_cache_dir = (
            Path(policy_cache_dir).expanduser().resolve()
            if policy_cache_dir is not None
            else None
        )

    @property
    def research_source_path(self) -> Path:
        return self.root / "registry/sources/tushare_research_reports.jsonl"

    def _research_rows(self, as_of: str) -> list[dict[str, Any]]:
        cutoff = _cutoff(as_of)
        rows = _strict_jsonl(self.research_source_path, "research report")
        visible: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if row.get("point_in_time_available") is False:
                continue
            captured = _timestamp(row.get("discovered_at"), "report discovered_at")
            if captured > cutoff:
                continue
            source_hash = str(row.get("source_hash") or "").strip()
            if not source_hash or source_hash in seen:
                continue
            _published_at(row.get("publish_date"), "report publish_date")
            seen.add(source_hash)
            visible.append(dict(row))
        return visible

    def _basic_industry(
        self, ticker: str, as_of: str, *, required: bool
    ) -> tuple[str, str | None, datetime | None]:
        if self.sector_archive_store is None:
            if required:
                raise DataVendorUnavailable("broker industry archive coverage is unavailable")
            return "", None, None
        try:
            group = self.sector_archive_store.load_group(
                as_of,
                required_route_ids=("tushare.sector_fundamentals",),
                required_security_code=ticker,
            )
            batches = [
                batch
                for batch in group.get("batches", ())
                if isinstance(batch, Mapping) and batch.get("endpoint") == "stock_basic"
            ]
            if len(batches) != 1 or not isinstance(batches[0].get("rows"), Sequence):
                raise ValueError("stock_basic batch unavailable")
            match = next(
                (
                    row
                    for row in batches[0]["rows"]
                    if isinstance(row, Mapping)
                    and str(row.get("ts_code") or "") == ticker
                    and str(row.get("industry") or "").strip()
                ),
                None,
            )
            if match is None:
                raise ValueError("ticker industry unavailable")
            industry = str(match["industry"]).strip()
            if not required:
                return industry, None, None
            parent = sector_archive_source_receipt(
                group, "tushare.sector_fundamentals"
            ).as_dict()
            return (
                industry,
                str(parent["receipt_hash"]),
                _timestamp(parent["time"]["captured_at"], "sector capture time"),
            )
        except (FileNotFoundError, OSError, StopIteration, ValueError) as exc:
            if required:
                raise DataVendorUnavailable(
                    "broker industry archive coverage is unavailable"
                ) from exc
            return "", None, None

    def _broker_industry_authority(
        self,
        *,
        rows: Sequence[Mapping[str, Any]],
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> tuple[str, str, str, str | None, datetime | None]:
        stock_rows = self._research_window(
            rows,
            report_type="个股研报",
            start_date=start_date,
            end_date=end_date,
            ticker=ticker,
        )
        report_industry = _extract_most_common_ind_name(_report_frame(stock_rows))
        basic_industry, parent_hash, parent_captured = self._basic_industry(
            ticker, end_date, required=not report_industry
        )
        industry = report_industry or basic_industry
        if not industry:
            raise DataVendorUnavailable("broker industry archive coverage is unavailable")
        industry_source = (
            "stock-report ind_name" if report_industry else "stock_basic industry"
        )
        return (
            industry,
            industry_source,
            basic_industry,
            parent_hash,
            parent_captured,
        )

    def broker_refresh_industry(
        self, ticker: str, start_date: str, end_date: str
    ) -> str:
        """Resolve one trusted industry before an exact industry refresh."""
        ts_code = _normalize_ts_code(ticker)
        if _classify_market(ts_code) != "a_share":
            raise DataVendorUnavailable("research archive supports A-share tickers only")
        try:
            rows = self._research_rows(end_date)
        except DataVendorUnavailable as exc:
            if str(exc) != "research report archive is unavailable":
                raise
            rows = []
        return self._broker_industry_authority(
            rows=rows,
            ticker=ts_code,
            start_date=start_date,
            end_date=end_date,
        )[0]

    @staticmethod
    def _research_window(
        rows: Sequence[Mapping[str, Any]],
        *,
        report_type: str,
        start_date: str,
        end_date: str,
        ticker: str = "",
        industry: str = "",
    ) -> list[dict[str, Any]]:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        if end < start:
            raise DataVendorUnavailable("research query date window is invalid")
        selected = []
        for row in rows:
            published = date.fromisoformat(str(row.get("publish_date") or ""))
            if not start <= published <= end or row.get("report_type") != report_type:
                continue
            if ticker and str(row.get("ts_code") or "") != ticker:
                continue
            if industry and str(row.get("industry") or "") != industry:
                continue
            selected.append(dict(row))
        return selected

    def _stock_selection(
        self, ticker: str, start_date: str, end_date: str, max_reports: int
    ) -> _Selection:
        ts_code = _normalize_ts_code(ticker)
        if _classify_market(ts_code) != "a_share":
            raise DataVendorUnavailable("research archive supports A-share tickers only")
        if max_reports <= 0:
            raise DataVendorUnavailable("max_reports must be > 0")
        rows = self._research_rows(end_date)
        selected = self._research_window(
            rows,
            report_type="个股研报",
            start_date=start_date,
            end_date=end_date,
            ticker=ts_code,
        )
        selected.sort(
            key=lambda row: (str(row["publish_date"]), str(row.get("source_id") or "")),
            reverse=True,
        )
        selected = selected[:max_reports]
        if not selected:
            raise DataVendorUnavailable("research forward archive has no proven coverage")
        payload = _render_stock_research_frame(
            _report_frame(selected),
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            max_reports=max_reports,
        )
        request = {
            "end_date": end_date,
            "max_reports": max_reports,
            "report_type": "个股研报",
            "start_date": start_date,
            "ts_code": ts_code,
        }
        return self._selection(
            route_id=_RESEARCH_ROUTE,
            source_family="tushare",
            request=request,
            rows=selected,
            payload=payload,
            date_field="publish_date",
            redacted_url="https://api.tushare.pro/research_report",
            parser_version="private_research_report_forward_archive_v1",
            schema_fields=_RESEARCH_FIELDS,
        )

    def _broker_selection(
        self, ticker: str, start_date: str, end_date: str, max_reports: int
    ) -> _Selection:
        ts_code = _normalize_ts_code(ticker)
        if _classify_market(ts_code) != "a_share":
            raise DataVendorUnavailable("research archive supports A-share tickers only")
        if max_reports <= 0:
            raise DataVendorUnavailable("max_reports must be > 0")
        rows = self._research_rows(end_date)
        (
            industry,
            industry_source,
            basic_industry,
            parent_hash,
            parent_captured,
        ) = self._broker_industry_authority(
            rows=rows,
            ticker=ts_code,
            start_date=start_date,
            end_date=end_date,
        )
        selected = self._research_window(
            rows,
            report_type="行业研报",
            start_date=start_date,
            end_date=end_date,
            industry=industry,
        )
        selected.sort(
            key=lambda row: (str(row["publish_date"]), str(row.get("source_id") or "")),
            reverse=True,
        )
        selected = selected[:max_reports]
        if not selected:
            raise DataVendorUnavailable("research forward archive has no proven coverage")
        payload = _render_broker_research_frame(
            _report_frame(selected),
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            max_reports=max_reports,
            matched_industry=industry,
            industry_source=industry_source,
            basic_industry=basic_industry,
        )
        request = {
            "end_date": end_date,
            "industry": industry,
            "industry_source": industry_source,
            "max_reports": max_reports,
            "report_type": "行业研报",
            "start_date": start_date,
            "ts_code": ts_code,
        }
        return self._selection(
            route_id=_RESEARCH_ROUTE,
            source_family="tushare",
            request=request,
            rows=selected,
            payload=payload,
            date_field="publish_date",
            redacted_url="https://api.tushare.pro/research_report",
            parser_version="private_research_report_forward_archive_v1",
            schema_fields=_RESEARCH_FIELDS,
            parent_capture_hash=parent_hash,
            additional_capture=parent_captured,
        )

    def _policy_selection(
        self,
        as_of: str,
        lookback: int,
        source: str,
        topic: str | None = None,
    ) -> _Selection:
        del source
        if lookback < 0:
            raise DataVendorUnavailable("look_back_days must be >= 0")
        normalized_topic = str(topic or "").strip()
        start_date, end_date = _date_window(as_of, lookback)
        cache_root = gov_policy_cache_dir(self.policy_cache_dir)
        rows = load_gov_policy_records(cache_root)
        cutoff = _cutoff(as_of)
        visible = []
        for row in rows:
            discovered = _timestamp(
                row.get("discovered_at") or row.get("parsed_at"),
                "policy discovered_at",
            )
            if discovered <= cutoff:
                normalized = dict(row)
                normalized.setdefault("discovered_at", discovered.isoformat())
                visible.append(normalized)
        selected = _records_in_window(visible, start_date, end_date)
        if normalized_topic:
            selected = [
                row
                for row in selected
                if normalized_topic in row.get("matched_queries", ())
            ]
        if not selected:
            raise DataVendorUnavailable("policy forward archive has no proven coverage")
        category_names = " / ".join(category.name for category in GOV_POLICY_CATEGORIES)
        topic_suffix = f"; topic={normalized_topic}" if normalized_topic else ""
        payload = _records_to_markdown_csv(
            selected,
            title=f"产业政策 / Gov.cn Policy Documents ({start_date} → {end_date})",
            subtitle=(
                "Source: State Council policy document library (forward archive). "
                f"Categories: {category_names}{topic_suffix}."
            ),
            empty_note=(
                f"No gov.cn policy documents recorded between {start_date} and {end_date}."
            ),
        )
        request = {
            "end_date": end_date,
            "look_back_days": lookback,
            "source": "govcn",
            "start_date": start_date,
        }
        if normalized_topic:
            request["q"] = normalized_topic
        return self._selection(
            route_id=_POLICY_ROUTE,
            source_family="govcn",
            request=request,
            rows=selected,
            payload=payload,
            date_field="pub_date",
            redacted_url="https://sousuo.www.gov.cn/search-gov/data",
            parser_version="govcn_policy_forward_archive_v1",
            schema_fields=_POLICY_FIELDS,
        )

    @staticmethod
    def _selection(
        *,
        route_id: str,
        source_family: str,
        request: dict[str, Any],
        rows: Sequence[Mapping[str, Any]],
        payload: str,
        date_field: str,
        redacted_url: str,
        parser_version: str,
        schema_fields: tuple[str, ...],
        parent_capture_hash: str | None = None,
        additional_capture: datetime | None = None,
    ) -> _Selection:
        captures = [
            _timestamp(row.get("discovered_at"), f"{source_family} discovered_at")
            for row in rows
        ]
        if additional_capture is not None:
            captures.append(additional_capture)
        dates = sorted(str(row.get(date_field) or "") for row in rows)
        releases = [_published_at(value, f"{source_family} publish date") for value in dates]
        captured = max(captures)
        released = max(releases)
        if captured < released:
            raise DataVendorUnavailable("forward archive capture precedes publication")
        return _Selection(
            route_id=route_id,
            source_family=source_family,
            request=request,
            rows=tuple(dict(row) for row in rows),
            payload=payload,
            captured_at=captured,
            release_at=released,
            observed_start=dates[0],
            observed_end=dates[-1],
            redacted_url=redacted_url,
            parser_version=parser_version,
            schema_fields=schema_fields,
            parent_capture_hash=parent_capture_hash,
        )

    def _select(self, method: str, route_args: Sequence[Any]) -> _Selection:
        if method == "get_stock_research":
            return self._stock_selection(
                str(route_args[0]),
                str(route_args[1]),
                str(route_args[2]),
                int(route_args[3]),
            )
        if method == "get_broker_research":
            return self._broker_selection(
                str(route_args[0]),
                str(route_args[1]),
                str(route_args[2]),
                int(route_args[3]),
            )
        if method == "get_industry_policy":
            return self._policy_selection(
                str(route_args[0]),
                int(route_args[1]),
                str(route_args[2]),
                str(route_args[3]) if len(route_args) > 3 else None,
            )
        raise ValueError(f"forward archive reader does not own route method {method}")

    def __call__(self, method: str, *route_args: Any) -> str:
        return self._select(method, route_args).payload

    def source_receipt(
        self,
        tool_id: str,
        args: Mapping[str, Any],
        raw_payload: str,
        descriptor: Mapping[str, Any],
    ) -> SourceCaptureReceipt:
        if tool_id in {"get_broker_research", "get_stock_research"}:
            method = tool_id
            route_args = (
                args["ticker"],
                args["date_from"],
                args["date_to"],
                args["max_reports"],
            )
        elif tool_id == "get_industry_policy_digest":
            method = "get_industry_policy"
            route_args = (args["as_of"], args["lookback_days"], args["source"])
            if "topic" in args:
                route_args += (args["topic"],)
        else:
            raise ValueError(f"forward archive reader has no receipt for {tool_id}")
        selection = self._select(method, route_args)
        if selection.payload != raw_payload or descriptor.get("content_hash") != canonical_hash(
            {"text": raw_payload}
        ):
            raise DataVendorUnavailable("forward archive payload/evidence selection drift")
        if descriptor.get("route_id") != selection.route_id:
            raise DataVendorUnavailable("forward archive route/evidence selection drift")
        return self._seal_source_receipt(selection, str(descriptor["as_of"]))

    @staticmethod
    def _seal_source_receipt(
        selection: _Selection, as_of: str
    ) -> SourceCaptureReceipt:
        cutoff = _cutoff(as_of)
        if selection.captured_at > cutoff:
            raise DataVendorUnavailable("forward archive capture is after query as_of")
        request_hash = canonical_hash(selection.request)
        content_identity = {
            "request": selection.request,
            "rows": list(selection.rows),
        }
        capture_id = canonical_hash(
            {
                "route_id": selection.route_id,
                "request_hash": request_hash,
                "raw_content_hash": canonical_hash(content_identity),
            }
        ).removeprefix("sha256:")
        return SourceCaptureReceipt.seal(
            {
                "schema_version": "source_capture_receipt_v1",
                "identity": {
                    "source_family": selection.source_family,
                    "route_id": selection.route_id,
                    "request_hash": request_hash,
                    "capture_id": f"forward-archive:{capture_id}",
                },
                "transport": {
                    "redacted_url": selection.redacted_url,
                    "method": "FILE",
                    "query_keys": sorted(selection.request),
                    "pagination_policy": "PRIVATE_FORWARD_ARCHIVE_EXACT_SELECTION",
                    "page_count": 1,
                },
                "authority": {
                    "provider": selection.source_family,
                    "permission_tier": "trusted_local_forward_archive",
                    "api_version": "archive-v1",
                    "parser_version": selection.parser_version,
                },
                "time": {
                    "released_at": selection.release_at.isoformat(),
                    "vintage_at": selection.release_at.isoformat(),
                    "captured_at": selection.captured_at.isoformat(),
                    "knowledge_available_at": selection.captured_at.isoformat(),
                },
                "pit": {
                    "pit_mode": "OBSERVED_LIVE",
                    "as_of_cutoff": cutoff.isoformat(),
                    "eligible": True,
                    "blocker_codes": [],
                    "vintage_query": None,
                },
                "content": {
                    "raw_content_hash": canonical_hash(content_identity),
                    "normalized_row_count": len(selection.rows),
                    "schema_hash": canonical_hash(
                        {
                            "parser_version": selection.parser_version,
                            "fields": list(selection.schema_fields),
                        }
                    ),
                },
                "coverage": {
                    "requested_start": str(selection.request["start_date"]),
                    "requested_end": str(selection.request["end_date"]),
                    "observed_start": selection.observed_start,
                    "observed_end": selection.observed_end,
                    "dimensions": {
                        "route_id": [selection.route_id],
                    },
                },
                "completeness": {
                    "truncated": False,
                    "next_page_token_present": False,
                    "duplicate_count": 0,
                    "empty_result_semantics": "NON_EMPTY",
                },
                "provenance": {
                    "parent_capture_hash": selection.parent_capture_hash,
                    "previous_revision_hash": None,
                    "revision_reason": None,
                },
            }
        )


class ForwardArchiveSourcePreparer:
    """Populate trusted forward archives during prepare, never during tool calls."""

    _thread_locks_guard = threading.Lock()
    _thread_locks: dict[str, threading.Lock] = {}
    _RECOVERABLE_MISSES = {
        "research report archive is unavailable",
        "research forward archive has no proven coverage",
        "policy forward archive has no proven coverage",
    }

    def __init__(
        self,
        *,
        reader: ForwardArchiveQueryReader,
        research_refresher: Callable[..., Any] | None = None,
        policy_refresher: Callable[..., Any] | None = None,
        lock_path: str | Path | None = None,
    ) -> None:
        self.reader = reader
        self.research_refresher = research_refresher
        self.policy_refresher = policy_refresher
        self.lock_path = (
            Path(lock_path).expanduser().resolve()
            if lock_path is not None
            else reader.root / ".mosaic/agent_data/forward_archive_sources.lock"
        )

    @classmethod
    def _thread_lock_for(cls, key: str) -> threading.Lock:
        with cls._thread_locks_guard:
            return cls._thread_locks.setdefault(key, threading.Lock())

    @contextmanager
    def _capture_lock(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_key = str(self.lock_path)
        with self._thread_lock_for(lock_key), self.lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _route(tool_id: str, args: Mapping[str, Any]) -> tuple[str, tuple[Any, ...]] | None:
        if tool_id in {"get_broker_research", "get_stock_research"}:
            return tool_id, (
                args["ticker"],
                args["date_from"],
                args["date_to"],
                args["max_reports"],
            )
        if tool_id == "get_industry_policy_digest":
            route_args: tuple[Any, ...] = (
                args["as_of"],
                args["lookback_days"],
                args["source"],
            )
            if "topic" in args:
                route_args += (args["topic"],)
            return "get_industry_policy", route_args
        return None

    def _archive_ready(self, method: str, route_args: Sequence[Any]) -> bool:
        try:
            self.reader(method, *route_args)
        except DataVendorUnavailable as exc:
            if str(exc) in self._RECOVERABLE_MISSES:
                return False
            raise
        return True

    def _refresh_research(self, tool_id: str, args: Mapping[str, Any]) -> None:
        refresher = self.research_refresher
        if refresher is None:
            from mosaic.rke.tushare_reports import (  # noqa: PLC0415
                refresh_tushare_research_report_registry,
            )

            refresher = refresh_tushare_research_report_registry
        broker = tool_id == "get_broker_research"
        industry_keywords = (
            (
                self.reader.broker_refresh_industry(
                    str(args["ticker"]),
                    str(args["date_from"]),
                    str(args["date_to"]),
                ),
            )
            if broker
            else ()
        )
        try:
            refresher(
                root=self.reader.root,
                stock_codes=() if broker else (str(args["ticker"]),),
                industry_keywords=industry_keywords,
                report_types=(),
                start_date=str(args["date_from"]),
                end_date=str(args["date_to"]),
                merge_existing_source=True,
                source_only=True,
            )
        except DataVendorUnavailable:
            raise
        except Exception as exc:
            raise DataVendorUnavailable("research forward capture failed") from exc

    def _refresh_policy(self, args: Mapping[str, Any]) -> None:
        refresher = self.policy_refresher
        if refresher is None:
            from mosaic.dataflows.gov_policy import (  # noqa: PLC0415
                ensure_gov_policy_documents_updated,
            )

            refresher = ensure_gov_policy_documents_updated
        start_date, end_date = _date_window(
            str(args["as_of"]), int(args["lookback_days"])
        )
        topic = str(args.get("topic") or "").strip()
        try:
            refresher(
                cache_dir=self.reader.policy_cache_dir,
                start_date=start_date,
                end_date=end_date,
                **(
                    {
                        "q": topic,
                    }
                    if topic
                    else {}
                ),
            )
        except DataVendorUnavailable:
            raise
        except Exception as exc:
            raise DataVendorUnavailable("policy forward capture failed") from exc

    def __call__(self, tool_id: str, args: Mapping[str, Any]) -> None:
        route = self._route(tool_id, args)
        if route is None:
            return
        method, route_args = route
        if self._archive_ready(method, route_args):
            return
        with self._capture_lock():
            if self._archive_ready(method, route_args):
                return
            if tool_id in {"get_broker_research", "get_stock_research"}:
                self._refresh_research(tool_id, args)
            else:
                self._refresh_policy(args)
            self.reader(method, *route_args)


__all__ = ["ForwardArchiveQueryReader", "ForwardArchiveSourcePreparer"]
