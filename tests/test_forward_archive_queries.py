from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import mosaic.dataflows.forward_archive_queries as forward_module
from mosaic.dataflows.adaptive_query_archives import TrustedArchiveQueryRouter
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.forward_archive_queries import (
    ForwardArchiveQueryReader,
    ForwardArchiveSourcePreparer,
)
from mosaic.dataflows.sector_relationship_queries import (
    SectorRelationshipQueryMaterializer,
)
from mosaic.dataflows.sector_relationship_source_evidence import (
    SectorRelationshipSourceEvidenceAuthority,
)
from mosaic.dataflows.staged_query_receipt_store import StagedQueryReceiptStore
from mosaic.scorecard.canonical_json import canonical_hash


class _SectorStore:
    def __init__(self, group: dict) -> None:
        self.group = group
        self.calls: list[tuple[str, dict]] = []

    def load_group(self, as_of: str, **kwargs) -> dict:
        self.calls.append((as_of, dict(kwargs)))
        if self.group.get("as_of_date") != as_of:
            raise FileNotFoundError(as_of)
        return self.group


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _research_row(
    *,
    source_id: str,
    report_type: str,
    publish_date: str,
    discovered_at: str,
    title: str,
    ts_code: str = "",
    industry: str = "",
) -> dict:
    row = {
        "source_id": source_id,
        "source_span_id": f"{source_id}:abstract",
        "source_type": "tushare_research_report",
        "report_type": report_type,
        "query_key": ts_code or industry,
        "publish_date": publish_date,
        "discovered_at": discovered_at,
        "title": title,
        "abstract": f"{title} full abstract",
        "author": "Analyst",
        "institution": "Broker",
        "ts_code": ts_code,
        "industry": industry,
        "url": f"https://reports.example/{source_id}",
        "source_hash": canonical_hash({"source_id": source_id, "title": title}),
        "point_in_time_available": True,
        "license_status": "pending_review",
    }
    return row


def _policy_row(
    *, article_id: str, title: str, pub_date: str, discovered_at: str
) -> dict:
    return {
        "article_id": article_id,
        "source": "gov.cn policy document library",
        "category_id": "gongwen",
        "category": "国务院文件",
        "pub_date": pub_date,
        "puborg": "国务院",
        "pcode": "国发〔2026〕1号",
        "index": "",
        "childtype": "国土资源、能源",
        "title": title,
        "summary": f"{title} summary",
        "url": f"https://www.gov.cn/{article_id}",
        "raw_id": article_id,
        "raw_pubtime": None,
        "raw_ptime": None,
        "raw_sha256": canonical_hash({"article_id": article_id})[7:],
        "parsed_at": discovered_at,
        "discovered_at": discovered_at,
    }


def _reader(tmp_path: Path, research_rows: list[dict], policy_rows: list[dict]):
    root = tmp_path / "repo"
    source = root / "registry/sources/tushare_research_reports.jsonl"
    policy = tmp_path / "gov-policy"
    _write_jsonl(source, research_rows)
    _write_jsonl(policy / "parsed/policy_documents.jsonl", policy_rows)
    sector_store = _SectorStore(
        {
            "as_of_date": "2026-06-05",
            "captured_at": "2026-06-05T07:00:00+00:00",
            "batches": [
                {
                    "endpoint": "stock_basic",
                    "rows": [
                        {
                            "ts_code": "600000.SH",
                            "industry": "Semiconductors",
                        }
                    ],
                }
            ],
        }
    )
    return ForwardArchiveQueryReader(
        root=root,
        sector_archive_store=sector_store,
        policy_cache_dir=policy,
    )


def _descriptor(tool_id: str, route_id: str, args: dict, payload: str) -> dict:
    return {
        "tool_id": tool_id,
        "route_id": route_id,
        "as_of": args.get("as_of", args.get("date_to")),
        "request_hash": canonical_hash(args),
        "content_hash": canonical_hash({"text": payload}),
        "pit_mode": "DERIVED_FROM_PIT_ARCHIVE",
    }


def test_stock_research_reads_only_rows_discovered_by_as_of(tmp_path):
    eligible = _research_row(
        source_id="SRC-STOCK-1",
        report_type="个股研报",
        publish_date="2026-06-03",
        discovered_at="2026-06-03T06:00:00+00:00",
        title="Eligible stock report",
        ts_code="600000.SH",
        industry="Semiconductors",
    )
    late = _research_row(
        source_id="SRC-STOCK-2",
        report_type="个股研报",
        publish_date="2026-06-04",
        discovered_at="2026-06-06T06:00:00+00:00",
        title="Late-discovered stock report",
        ts_code="600000.SH",
        industry="Semiconductors",
    )
    reader = _reader(tmp_path, [eligible, late], [])

    payload = reader(
        "get_stock_research", "600000.SH", "2026-06-01", "2026-06-05", 30
    )

    assert "Individual Stock Research Reports for 600000.SH" in payload
    assert "Eligible stock report full abstract" in payload
    assert "Late-discovered stock report" not in payload
    args = {
        "ticker": "600000.SH",
        "date_from": "2026-06-01",
        "date_to": "2026-06-05",
        "max_reports": 30,
    }
    receipt = reader.source_receipt(
        "get_stock_research",
        args,
        payload,
        _descriptor(
            "get_stock_research",
            "private.tushare_research_reports",
            args,
            payload,
        ),
    ).as_dict()
    assert receipt["identity"]["route_id"] == "private.tushare_research_reports"
    assert receipt["pit"]["pit_mode"] == "OBSERVED_LIVE"
    assert receipt["content"]["normalized_row_count"] == 1


def test_broker_research_reuses_archived_industry_resolution(tmp_path):
    rows = [
        _research_row(
            source_id="SRC-STOCK-IND",
            report_type="个股研报",
            publish_date="2026-06-03",
            discovered_at="2026-06-03T06:00:00+00:00",
            title="Industry resolver",
            ts_code="600000.SH",
            industry="Semiconductors",
        ),
        _research_row(
            source_id="SRC-IND-1",
            report_type="行业研报",
            publish_date="2026-06-02",
            discovered_at="2026-06-02T06:00:00+00:00",
            title="Industry deep dive",
            industry="Semiconductors",
        ),
    ]
    reader = _reader(tmp_path, rows, [])

    payload = reader(
        "get_broker_research", "600000.SH", "2026-06-01", "2026-06-05", 30
    )

    assert "Industry Research Reports for Semiconductors" in payload
    assert "Industry keyword source: stock-report ind_name" in payload
    assert "Industry deep dive full abstract" in payload


def test_broker_research_falls_back_to_archived_stock_basic_with_parent_lineage(
    tmp_path, monkeypatch
):
    reader = _reader(
        tmp_path,
        [
            _research_row(
                source_id="SRC-STOCK-OUTSIDE-WINDOW",
                report_type="个股研报",
                publish_date="2026-05-20",
                discovered_at="2026-05-20T06:00:00+00:00",
                title="Outside-window resolver",
                ts_code="600000.SH",
                industry="Banks",
            ),
            _research_row(
                source_id="SRC-IND-FALLBACK",
                report_type="行业研报",
                publish_date="2026-06-02",
                discovered_at="2026-06-02T06:00:00+00:00",
                title="Fallback industry report",
                industry="Semiconductors",
            )
        ],
        [],
    )
    parent_hash = canonical_hash({"sector": "parent"})

    class _ParentReceipt:
        def as_dict(self):
            return {
                "receipt_hash": parent_hash,
                "time": {"captured_at": "2026-06-05T07:00:00+00:00"},
            }

    monkeypatch.setattr(
        forward_module,
        "sector_archive_source_receipt",
        lambda group, route_id: _ParentReceipt(),
    )

    payload = reader(
        "get_broker_research", "600000.SH", "2026-06-01", "2026-06-05", 30
    )
    args = {
        "ticker": "600000.SH",
        "date_from": "2026-06-01",
        "date_to": "2026-06-05",
        "max_reports": 30,
    }
    receipt = reader.source_receipt(
        "get_broker_research",
        args,
        payload,
        _descriptor(
            "get_broker_research",
            "private.tushare_research_reports",
            args,
            payload,
        ),
    ).as_dict()

    assert "Industry keyword source: stock_basic industry" in payload
    assert receipt["provenance"]["parent_capture_hash"] == parent_hash
    assert reader.sector_archive_store.calls == 2 * [
        (
            "2026-06-05",
            {
                "required_route_ids": ("tushare.sector_fundamentals",),
                "required_security_code": "600000.SH",
            },
        )
    ]


def test_late_captured_policy_materializes_by_pub_date_window_and_topic(tmp_path):
    reader = _reader(
        tmp_path,
        [],
        [
            {
                **_policy_row(
                    article_id="biotech-late",
                    title="正文命中但标题摘要不含主题",
                    pub_date="2026-06-20",
                    discovered_at="2026-08-12T06:00:00+00:00",
                ),
                "matched_queries": ["生物制品"],
            },
            {
                **_policy_row(
                    article_id="other-topic",
                    title="农业政策",
                    pub_date="2026-06-20",
                    discovered_at="2026-08-12T06:00:00+00:00",
                ),
                "matched_queries": ["农业"],
            },
        ],
    )
    store = StagedQueryReceiptStore(tmp_path / "policy-staged.sqlite3")
    authority = SectorRelationshipSourceEvidenceAuthority(
        root=tmp_path,
        receipt_store=store,
        forward_archive_reader=reader,
    )
    captured: dict[str, object] = {}

    def source_evidence(tool_id, args, raw_payload, descriptor, source_ids):
        captured.update(
            args=dict(args), raw_payload=raw_payload, descriptor=dict(descriptor)
        )
        return authority(tool_id, args, raw_payload, descriptor, source_ids)

    materializer = SectorRelationshipQueryMaterializer(
        receipt_authority=lambda descriptor: pytest.fail(
            f"generic authority must not attest policy archive: {descriptor}"
        ),
        route_caller=TrustedArchiveQueryRouter({"get_industry_policy": reader}),
        digest_builder=lambda tool_id, raw, args: {
            "digest": "policy digest",
            "model_hash": canonical_hash({"model": "fixture"}),
            "prompt_hash": canonical_hash({"prompt": "fixture"}),
        },
        source_evidence_authority=source_evidence,
    )
    args = {
        "as_of": "2026-07-08",
        "lookback_days": 30,
        "source": "govcn",
        "topic": "生物制品",
    }

    result = materializer("get_industry_policy_digest", args)

    assert result["payload"] == "policy digest"
    assert len(result["source_receipt_hashes"]) == 1
    assert captured["descriptor"]["pit_mode"] == "OBSERVED_LIVE"
    assert "正文命中但标题摘要不含主题" in captured["raw_payload"]
    assert "农业政策" not in captured["raw_payload"]
    receipt = reader.source_receipt(
        "get_industry_policy_digest",
        args,
        captured["raw_payload"],
        captured["descriptor"],
    ).as_dict()
    assert receipt["time"]["captured_at"] == "2026-08-12T06:00:00+00:00"
    assert receipt["pit"]["pit_mode"] == "OBSERVED_LIVE"


def test_policy_topic_is_bound_to_archive_selection_and_receipt(tmp_path):
    reader = _reader(
        tmp_path,
        [],
        [
            {
                **_policy_row(
                    article_id="semi",
                    title="正文命中但标题不含主题",
                    pub_date="2026-06-12",
                    discovered_at="2026-06-12T06:00:00+00:00",
                ),
                "matched_queries": ["半导体"],
            },
            {
                **_policy_row(
                    article_id="other",
                    title="农业政策",
                    pub_date="2026-06-12",
                    discovered_at="2026-06-12T06:00:00+00:00",
                ),
                "matched_queries": ["农业"],
            },
        ],
    )
    args = {
        "as_of": "2026-06-17",
        "lookback_days": 7,
        "source": "govcn",
        "topic": "半导体",
    }
    payload = reader("get_industry_policy", "2026-06-17", 7, "govcn", "半导体")
    assert "正文命中但标题不含主题" in payload
    assert "农业政策" not in payload

    receipt = reader.source_receipt(
        "get_industry_policy_digest",
        args,
        payload,
        _descriptor(
            "get_industry_policy_digest",
            "official.govcn_policy",
            args,
            payload,
        )
        | {"pit_mode": "OBSERVED_LIVE"},
    ).as_dict()
    assert receipt["identity"]["request_hash"] == canonical_hash(
        {
            "end_date": "2026-06-17",
            "look_back_days": 7,
            "q": "半导体",
            "source": "govcn",
            "start_date": "2026-06-10",
        }
    )
    assert "q" in receipt["transport"]["query_keys"]


def test_forward_archive_queries_fail_closed_without_eligible_rows(tmp_path):
    reader = _reader(
        tmp_path,
        [
            _research_row(
                source_id="SRC-LATE",
                report_type="个股研报",
                publish_date="2026-06-03",
                discovered_at="2026-06-06T06:00:00+00:00",
                title="Late",
                ts_code="600000.SH",
            )
        ],
        [],
    )

    with pytest.raises(DataVendorUnavailable, match="coverage"):
        reader(
            "get_stock_research", "600000.SH", "2026-06-01", "2026-06-05", 30
        )
    with pytest.raises(DataVendorUnavailable, match="coverage"):
        reader("get_industry_policy", "2026-06-05", 7, "govcn", "能源")


def test_forward_archive_receipt_is_bound_into_staged_query_evidence(tmp_path):
    row = _research_row(
        source_id="SRC-STAGED-1",
        report_type="个股研报",
        publish_date="2026-06-03",
        discovered_at="2026-06-03T06:00:00+00:00",
        title="Staged evidence report",
        ts_code="600000.SH",
    )
    reader = _reader(tmp_path, [row], [])
    args = {
        "ticker": "600000.SH",
        "date_from": "2026-06-01",
        "date_to": "2026-06-05",
        "max_reports": 30,
    }
    payload = reader(
        "get_stock_research", "600000.SH", "2026-06-01", "2026-06-05", 30
    )
    descriptor = _descriptor(
        "get_stock_research",
        "private.tushare_research_reports",
        args,
        payload,
    )
    upstream = reader.source_receipt(
        "get_stock_research", args, payload, descriptor
    ).as_dict()
    store = StagedQueryReceiptStore(tmp_path / "staged.sqlite3")
    authority = SectorRelationshipSourceEvidenceAuthority(
        root=tmp_path,
        receipt_store=store,
        forward_archive_reader=reader,
    )

    receipts = authority(
        "get_stock_research", args, payload, descriptor, ()
    )

    assert receipts[0]["pit_mode"] == "DERIVED_FROM_PIT_ARCHIVE"
    assert receipts[0]["upstream_evidence_hashes"] == [upstream["receipt_hash"]]
    assert store.resolve(descriptor) == receipts


def test_materializer_uses_forward_archive_and_never_generic_live_authority(tmp_path):
    row = _research_row(
        source_id="SRC-MATERIALIZED-1",
        report_type="个股研报",
        publish_date="2026-06-03",
        discovered_at="2026-06-03T06:00:00+00:00",
        title="Materialized report",
        ts_code="600000.SH",
    )
    reader = _reader(tmp_path, [row], [])
    store = StagedQueryReceiptStore(tmp_path / "materialized-staged.sqlite3")
    authority = SectorRelationshipSourceEvidenceAuthority(
        root=tmp_path,
        receipt_store=store,
        forward_archive_reader=reader,
    )
    digest = "private-safe frozen digest"
    materializer = SectorRelationshipQueryMaterializer(
        receipt_authority=lambda descriptor: pytest.fail(
            f"generic authority must not attest forward archive: {descriptor}"
        ),
        route_caller=TrustedArchiveQueryRouter(
            {"get_stock_research": reader}
        ),
        digest_builder=lambda tool_id, raw, args: {
            "digest": digest,
            "model_hash": canonical_hash({"model": "fixture"}),
            "prompt_hash": canonical_hash({"prompt": "fixture"}),
        },
        source_evidence_authority=authority,
    )

    result = materializer(
        "get_stock_research",
        {
            "ticker": "600000.SH",
            "date_from": "2026-06-01",
            "date_to": "2026-06-05",
            "max_reports": 30,
        },
    )

    assert result["payload"] == digest
    assert len(result["source_receipt_hashes"]) == 1
    assert result["derivation"]["source_payload_hash"].startswith("sha256:")


def test_forward_source_preparer_reuses_warm_research_without_refresh(tmp_path):
    row = _research_row(
        source_id="SRC-WARM-1",
        report_type="个股研报",
        publish_date="2026-06-03",
        discovered_at="2026-06-03T06:00:00+00:00",
        title="Warm report",
        ts_code="600000.SH",
    )
    reader = _reader(tmp_path, [row], [])
    refresh_calls: list[dict] = []
    preparer = ForwardArchiveSourcePreparer(
        reader=reader,
        research_refresher=lambda **kwargs: refresh_calls.append(kwargs),
    )
    args = {
        "ticker": "600000.SH",
        "date_from": "2026-06-01",
        "date_to": "2026-06-05",
        "max_reports": 30,
    }

    preparer("get_stock_research", args)

    assert refresh_calls == []


def test_forward_source_preparer_serializes_cold_research_refresh_and_rechecks(
    tmp_path,
):
    reader = _reader(tmp_path, [], [])
    refresh_calls: list[dict] = []

    def refresh(**kwargs):
        refresh_calls.append(kwargs)
        _write_jsonl(
            reader.research_source_path,
            [
                _research_row(
                    source_id="SRC-COLD-1",
                    report_type="个股研报",
                    publish_date="2026-06-03",
                    discovered_at="2026-06-03T06:00:00+00:00",
                    title="Cold report",
                    ts_code="600000.SH",
                )
            ],
        )

    preparer = ForwardArchiveSourcePreparer(
        reader=reader,
        research_refresher=refresh,
        lock_path=tmp_path / "forward-source.lock",
    )
    args = {
        "ticker": "600000.SH",
        "date_from": "2026-06-01",
        "date_to": "2026-06-05",
        "max_reports": 30,
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda _: preparer("get_stock_research", args), range(2))
        )

    assert results == [None, None]
    assert len(refresh_calls) == 1
    assert refresh_calls[0] == {
        "root": reader.root,
        "stock_codes": ("600000.SH",),
        "industry_keywords": (),
        "report_types": (),
        "start_date": "2026-06-01",
        "end_date": "2026-06-05",
        "merge_existing_source": True,
        "source_only": True,
    }


def test_forward_source_preparer_captures_broker_and_policy_sources(
    tmp_path, monkeypatch
):
    reader = _reader(tmp_path, [], [])
    research_calls: list[dict] = []
    policy_calls: list[dict] = []

    class _ParentReceipt:
        def as_dict(self):
            return {
                "receipt_hash": canonical_hash({"sector": "cold-parent"}),
                "time": {"captured_at": "2026-06-05T07:00:00+00:00"},
            }

    monkeypatch.setattr(
        forward_module,
        "sector_archive_source_receipt",
        lambda group, route_id: _ParentReceipt(),
    )

    def refresh_research(**kwargs):
        research_calls.append(kwargs)
        _write_jsonl(
            reader.research_source_path,
            [
                _research_row(
                    source_id="SRC-BROKER-STOCK",
                    report_type="个股研报",
                    publish_date="2026-06-03",
                    discovered_at="2026-06-03T06:00:00+00:00",
                    title="Broker resolver",
                    ts_code="600000.SH",
                    industry="Semiconductors",
                ),
                _research_row(
                    source_id="SRC-BROKER-INDUSTRY",
                    report_type="行业研报",
                    publish_date="2026-06-04",
                    discovered_at="2026-06-04T06:00:00+00:00",
                    title="Broker industry report",
                    industry="Semiconductors",
                ),
            ],
        )

    def refresh_policy(**kwargs):
        policy_calls.append(kwargs)
        _write_jsonl(
            Path(kwargs["cache_dir"]) / "parsed/policy_documents.jsonl",
            [
                {
                    **_policy_row(
                        article_id="POLICY-COLD-1",
                        title="半导体 Cold policy",
                        pub_date="2026-06-04",
                        discovered_at="2026-06-04T06:00:00+00:00",
                    ),
                    "matched_queries": ["半导体"],
                }
            ],
        )

    preparer = ForwardArchiveSourcePreparer(
        reader=reader,
        research_refresher=refresh_research,
        policy_refresher=refresh_policy,
        lock_path=tmp_path / "forward-source.lock",
    )
    preparer(
        "get_broker_research",
        {
            "ticker": "600000.SH",
            "date_from": "2026-06-01",
            "date_to": "2026-06-05",
            "max_reports": 30,
        },
    )
    preparer(
        "get_industry_policy_digest",
        {
            "as_of": "2026-06-05",
            "lookback_days": 4,
            "source": "govcn",
            "topic": "半导体",
        },
    )

    assert research_calls[0]["stock_codes"] == ()
    assert research_calls[0]["industry_keywords"] == ("Semiconductors",)
    assert research_calls[0]["report_types"] == ()
    assert research_calls[0]["source_only"] is True
    assert policy_calls == [
        {
            "cache_dir": reader.policy_cache_dir,
            "start_date": "2026-06-01",
            "end_date": "2026-06-05",
            "q": "半导体",
        }
    ]


def test_forward_source_preparer_does_not_repair_malformed_archive(tmp_path):
    reader = _reader(tmp_path, [], [])
    reader.research_source_path.write_text("{malformed\n", encoding="utf-8")
    refresh_calls: list[dict] = []
    preparer = ForwardArchiveSourcePreparer(
        reader=reader,
        research_refresher=lambda **kwargs: refresh_calls.append(kwargs),
    )

    with pytest.raises(DataVendorUnavailable, match="archive is malformed"):
        preparer(
            "get_stock_research",
            {
                "ticker": "600000.SH",
                "date_from": "2026-06-01",
                "date_to": "2026-06-05",
                "max_reports": 30,
            },
        )

    assert refresh_calls == []


def test_broker_source_preparer_fails_closed_without_industry_authority(tmp_path):
    root = tmp_path / "repo"
    _write_jsonl(root / "registry/sources/tushare_research_reports.jsonl", [])
    refresh_calls: list[dict] = []
    preparer = ForwardArchiveSourcePreparer(
        reader=ForwardArchiveQueryReader(root=root),
        research_refresher=lambda **kwargs: refresh_calls.append(kwargs),
    )

    with pytest.raises(
        DataVendorUnavailable, match="broker industry archive coverage is unavailable"
    ):
        preparer(
            "get_broker_research",
            {
                "ticker": "600000.SH",
                "date_from": "2026-06-01",
                "date_to": "2026-06-05",
                "max_reports": 30,
            },
        )

    assert refresh_calls == []
