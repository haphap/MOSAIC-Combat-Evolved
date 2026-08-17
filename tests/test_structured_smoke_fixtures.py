from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

import mosaic.bridge.tool_capabilities as tool_capabilities_module
import scripts.build_structured_smoke_fixtures as structured_smoke_fixtures_module
from mosaic.bridge.tool_capabilities import (
    ADAPTIVE_QUERY_TOOL_IDS,
    AGENT_TOOL_MATRIX,
    ALL_AGENT_IDS,
    INITIAL_SNAPSHOT_TOOL_IDS,
    materialize_tool_payload,
)
from mosaic.dataflows.cninfo_supply_chain import CninfoSupplyChainDisclosureCollector
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.forward_archive_queries import ForwardArchiveQueryReader
from mosaic.dataflows.macro_snapshots import validate_role_snapshot
from mosaic.dataflows.china_agent_data_archive import (
    CURVE_ROUTE_GROUP,
    INSTITUTIONAL_ROUTE_GROUP,
    ChinaAgentDataArchiveStore,
    china_archive_source_receipt,
)
from mosaic.dataflows.china_archive_queries import ChinaArchiveQueryReader
from mosaic.dataflows.outcome_runtime_inputs import (
    load_evaluation_opportunity_projection,
)
from mosaic.dataflows.sector_archive import SectorArchiveStore
from mosaic.dataflows.sector_archive_queries import SectorArchiveQueryReader
from mosaic.dataflows.supply_chain_disclosures import (
    OfficialSupplyChainDisclosureArchive,
)
from mosaic.rke.agent_research_context import (
    build_rke_agent_research_materialization,
)
from mosaic.scorecard.darwinian_v2 import canonical_hash
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.opportunity_authority import materialize_pre_run_authority
from scripts.build_structured_smoke_fixtures import (
    build_structured_smoke_fixtures,
    render_shell_exports,
)


def _bind_structured_smoke(
    bindings: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in bindings.items():
        monkeypatch.setenv(key, value)


def _write_eligibility_artifact(
    tmp_path: Path, *, mutation: str | None = None
) -> Path:
    as_of = "2025-06-17"
    as_of_api = "20250617"
    codes = sorted(structured_smoke_fixtures_module._approved_etf_authority())
    fetched_at = "2025-06-17T12:00:00Z"

    def record(
        endpoint: str,
        params: dict[str, str],
        row: dict[str, object],
        identity: str,
    ) -> dict[str, object]:
        base = {
            "evidence_id": f"test:{endpoint}:{identity}",
            "query": {"endpoint": endpoint, "params": params},
            "fetched_at": fetched_at,
            "row": row,
            "content_hash": canonical_hash(row),
        }
        return {**base, "record_hash": canonical_hash(base)}

    basic_records = []
    daily_records = []
    for code in codes:
        list_date = "2020-01-01"
        delist_date = None
        if mutation == "future_listing" and code == codes[0]:
            list_date = "2025-06-18"
        if mutation == "expired_delist" and code == codes[0]:
            delist_date = as_of
        basic_records.append(
            record(
                "fund_basic",
                {
                    "ts_code": code,
                    "market": "E",
                    "fields": structured_smoke_fixtures_module.FUND_BASIC_FIELDS,
                },
                {
                    "ts_code": code,
                    "name": f"ETF {code}",
                    "fund_type": "股票型",
                    "list_date": list_date,
                    "delist_date": delist_date,
                },
                code,
            )
        )
        daily_records.append(
            record(
                "fund_daily",
                {
                    "ts_code": code,
                    "trade_date": as_of_api,
                    "fields": structured_smoke_fixtures_module.FUND_DAILY_FIELDS,
                },
                {
                    "ts_code": code,
                    "trade_date": as_of_api,
                    "vol": 0 if mutation == "zero_activity" and code == codes[0] else 1000,
                    "amount": 0 if mutation == "zero_activity" and code == codes[0] else 100000,
                },
                code,
            )
        )

    exchange_rows = {
        "SSE": {"exchange": "SSE", "cal_date": as_of_api, "is_open": 1},
        "SZSE": {"exchange": "SZSE", "cal_date": as_of_api, "is_open": 1},
    }
    calendar_records = [
        record(
            "trade_cal",
            {
                "exchange": exchange,
                "start_date": as_of_api,
                "end_date": as_of_api,
                "fields": structured_smoke_fixtures_module.TRADE_CAL_FIELDS,
            },
            row,
            exchange,
        )
        for exchange, row in sorted(exchange_rows.items())
    ]
    if mutation == "missing_code":
        basic_records.pop()
        daily_records.pop()
    if mutation == "duplicate_evidence_id":
        duplicate = daily_records[0]
        duplicate["evidence_id"] = basic_records[0]["evidence_id"]
        duplicate["record_hash"] = canonical_hash(
            {key: value for key, value in duplicate.items() if key != "record_hash"}
        )
    body = {
        "schema_version": structured_smoke_fixtures_module.ELIGIBILITY_ARTIFACT_SCHEMA_VERSION,
        "as_of_date": "2025-06-18" if mutation == "wrong_as_of" else as_of,
        "codes": codes,
        "fund_basic": basic_records,
        "fund_daily": daily_records,
        "trade_cal": calendar_records,
        "provenance": {
            "collector": "focused-test",
            "preflight_registry_version": "test-preflight-v1",
            "rule": "focused eligibility contract",
        },
    }
    artifact = {
        **body,
        "artifact_hash": (
            "sha256:" + "0" * 64
            if mutation == "wrong_hash"
            else canonical_hash(body)
        ),
    }
    path = tmp_path / "structured-smoke-etf-eligibility.json"
    path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def test_structured_smoke_eligibility_artifact_binds_real_candidates_and_hash(
    tmp_path: Path,
) -> None:
    artifact_path = _write_eligibility_artifact(tmp_path)
    cache_root = tmp_path / "cache"
    bindings = build_structured_smoke_fixtures(
        cache_root, "2025-06-17", eligibility_artifact_path=artifact_path
    )
    expected_codes = set(structured_smoke_fixtures_module._approved_etf_authority())
    proposal = json.loads(
        (
            cache_root
            / "runtime_snapshots/2025-06-17/cio.cio_proposal.get_cio_decision_snapshot.json"
        ).read_text(encoding="utf-8")
    )
    candidates = proposal["candidate_universe"]
    assert len(candidates) == 1
    candidate = candidates[0]
    validated = structured_smoke_fixtures_module._load_eligibility_artifact(
        artifact_path, date(2025, 6, 17)
    )
    direction_id = validated["authority"][candidate["ts_code"]]["direction_id"]
    projection = load_evaluation_opportunity_projection(
        "2025-06-17T15:00:00+08:00",
        "semiconductor",
        root=cache_root / "outcome_runtime",
    )
    shortlist = next(
        member
        for member in projection["member_refs"]
        if member["subindustry_id"] == direction_id
    )
    assert shortlist["security_ts_codes"] == [candidate["ts_code"]]
    artifact = validated["payload"]
    assert set(artifact["codes"]) == expected_codes
    assert "eligibility_proofs" not in artifact
    assert candidate["ts_code"] in expected_codes
    assert not candidate["ts_code"].startswith("600")
    proof = validated["proof_by_code"][candidate["ts_code"]]
    assert proof["security_type"] == "ETF"
    assert proof["tradability"] == "TRADABLE"
    evidence_by_id = {
        row["evidence_id"]: row for row in proposal["evidence_ledger"]
    }
    evidence_id = f"structured-smoke:eligibility-proof:{candidate['ts_code']}"
    assert evidence_id in candidate["evidence_ids"]
    assert evidence_by_id[evidence_id]["source_fingerprint"] == proof["content_hash"]
    copied = cache_root / structured_smoke_fixtures_module._ELIGIBILITY_ARTIFACT_RELATIVE_PATH
    assert json.loads(copied.read_text(encoding="utf-8")) == artifact
    marker = json.loads(
        (cache_root / "structured_smoke_fixture_bundle.json").read_text(encoding="utf-8")
    )
    assert any(
        row["relative_path"] == structured_smoke_fixtures_module._ELIGIBILITY_ARTIFACT_RELATIVE_PATH
        for row in marker["artifact_inventory"]
    )
    assert bindings["MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH"] == marker["bundle_hash"]


def test_structured_smoke_eligibility_authority_rows_lead_scoring_and_shortlists(
    tmp_path: Path,
) -> None:
    artifact_path = _write_eligibility_artifact(tmp_path)
    cache_root = tmp_path / "cache"
    build_structured_smoke_fixtures(
        cache_root, "2025-06-17", eligibility_artifact_path=artifact_path
    )
    families = [
        family
        for family in structured_smoke_fixtures_module.SECTOR_ETF_DIRECTION_AUTHORITY[
            "direction_families"
        ]
        if family["etf_ts_codes"]
    ]
    assert len(families) == 9
    for family in families:
        agent_id = family["sector_agent_id"]
        direction_id = family["direction_id"]
        authority_code = family["etf_ts_codes"][0]
        snapshot = json.loads(
            (
                cache_root
                / "sector_snapshots"
                / "2025-06-17"
                / f"{agent_id}.json"
            ).read_text(encoding="utf-8")
        )
        rows = snapshot["security_scoring_rows"]
        authority_row = next(row for row in rows if row["ts_code"] == authority_code)
        available_rows = [
            row for row in rows if row["availability_status"] == "AVAILABLE"
        ]
        assert available_rows
        assert all(not row["ts_code"].startswith("600") for row in available_rows)
        assert all(
            row["availability_status"] == "UNAVAILABLE"
            for row in rows
            if row["ts_code"].startswith("600")
        )
        assert authority_row["direction_id"] == direction_id
        assert authority_row["adjusted_return_20d"] == max(
            row["adjusted_return_20d"] for row in available_rows
        )
        assert authority_row["realized_volatility_20d"] == min(
            row["realized_volatility_20d"] for row in available_rows
        )
        assert authority_row["median_amount_20d_cny"] == max(
            row["median_amount_20d_cny"] for row in available_rows
        )
        assert authority_row["net_moneyflow_20d_cny"] == max(
            row["net_moneyflow_20d_cny"] for row in available_rows
        )
        projection = load_evaluation_opportunity_projection(
            "2025-06-17T15:00:00+08:00",
            agent_id,
            root=cache_root / "outcome_runtime",
        )
        shortlist = next(
            member
            for member in projection["member_refs"]
            if member["subindustry_id"] == direction_id
        )
        assert shortlist["security_ts_codes"][0] == authority_code
        assert all(
            not code.startswith("600") for code in shortlist["security_ts_codes"]
        )
        direction_cards = {
            card["direction_id"]: card for card in snapshot["direction_cards"]
        }
        authority_drawdown = next(
            metric["value"]
            for metric in direction_cards[direction_id]["metrics"]
            if metric["metric_id"] == "CURRENT_DRAWDOWN_252D"
        )
        assert authority_drawdown == max(
            next(
                metric["value"]
                for metric in direction_cards[card_direction]["metrics"]
                if metric["metric_id"] == "CURRENT_DRAWDOWN_252D"
            )
            for card_direction in direction_cards
        )


def test_structured_smoke_non_eligibility_preserves_original_synthetic_universe_and_scores(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    build_structured_smoke_fixtures(cache_root, "2026-07-17")
    ticker_ordinal = 0
    for agent_id, direction_ids in structured_smoke_fixtures_module.SECTOR_DIRECTION_IDS.items():
        snapshot = json.loads(
            (
                cache_root
                / "sector_snapshots"
                / "2026-07-17"
                / f"{agent_id}.json"
            ).read_text(encoding="utf-8")
        )
        expected_codes: dict[str, str] = {}
        for direction_id in direction_ids:
            ticker_ordinal += 1
            expected_codes[direction_id] = f"{600000 + ticker_ordinal:06d}.SH"
        assert {
            row["direction_id"]: row["ts_code"]
            for row in snapshot["eligible_security_universe"]
        } == expected_codes
        assert all(code.startswith("600") for code in expected_codes.values())
        rows = snapshot["security_scoring_rows"]
        for security_ordinal, row in enumerate(rows, start=1):
            direction_quality = len(rows) - security_ordinal + 1
            assert row["adjusted_return_20d"] == round(0.04 * direction_quality, 6)
            assert row["realized_volatility_20d"] == round(
                0.08 + 0.06 * security_ordinal, 6
            )
            assert row["median_amount_20d_cny"] == float(
                100_000_000 - security_ordinal * 10_000
            )
            assert row["net_moneyflow_20d_cny"] == float(
                1_000_000 + direction_quality * 100_000
            )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_code",
        "future_listing",
        "expired_delist",
        "zero_activity",
        "wrong_as_of",
        "wrong_hash",
        "duplicate_evidence_id",
    ],
)
def test_structured_smoke_eligibility_artifact_fails_closed(
    tmp_path: Path, mutation: str
) -> None:
    artifact_path = _write_eligibility_artifact(tmp_path, mutation=mutation)
    with pytest.raises(RuntimeError):
        build_structured_smoke_fixtures(
            tmp_path / "cache", "2025-06-17", eligibility_artifact_path=artifact_path
        )


def test_structured_smoke_artifact_root_allowlists_are_identical() -> None:
    assert set(structured_smoke_fixtures_module._FIXTURE_ARTIFACT_ROOTS) == set(
        tool_capabilities_module._SYNTHETIC_FIXTURE_ARTIFACT_ROOTS
    )


def test_structured_smoke_macro_snapshot_uses_fixed_etf_share_changes(
    tmp_path: Path,
) -> None:
    as_of = date(2026, 7, 17)
    structured_smoke_fixtures_module._build_macro_snapshots(tmp_path, as_of)
    payload = json.loads(
        (tmp_path / "macro_snapshots" / as_of.isoformat() / "institutional_flow.json")
        .read_text(encoding="utf-8")
    )

    assert [row["series_id"] for row in payload["observations"]] == [
        f"etf_share_{ticker.replace('.', '_')}_change"
        for ticker in structured_smoke_fixtures_module.INSTITUTIONAL_ETF_UNIVERSE
    ]
    assert {row["source"] for row in payload["observations"]} == {
        "tushare.fund_share"
    }
    assert payload["component_coverage"] == {
        "etf_share": {
            "eligible_count": 5,
            "observed_count": 5,
            "coverage_ratio": 1.0,
        }
    }
    validate_role_snapshot(payload, "institutional_flow", as_of.isoformat())


def test_structured_smoke_bundle_materializes_all_26_stage_initial_snapshots(
    tmp_path: Path, monkeypatch
) -> None:
    as_of = "2026-07-17"
    bindings = build_structured_smoke_fixtures(tmp_path / "cache", as_of)
    for key, value in bindings.items():
        if key == "MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS":
            continue
        monkeypatch.setenv(key, value)
    monkeypatch.setenv(
        "MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS",
        bindings["MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS"],
    )

    stages = [
        (agent_id, stage)
        for agent_id in ALL_AGENT_IDS
        for stage in (
            ("cio_proposal", "cio_final") if agent_id == "cio" else (agent_id,)
        )
    ]
    assert len(stages) == 26
    for agent_id, stage in stages:
        tool_ids = AGENT_TOOL_MATRIX[agent_id]
        initial_tools = tuple(
            tool_id for tool_id in tool_ids if tool_id in INITIAL_SNAPSHOT_TOOL_IDS
        )
        adaptive_tools = tuple(
            tool_id for tool_id in tool_ids if tool_id in ADAPTIVE_QUERY_TOOL_IDS
        )
        assert set(tool_ids) == set(initial_tools) | set(adaptive_tools)
        assert set(initial_tools).isdisjoint(adaptive_tools)
        for tool_id in initial_tools:
            payload = json.loads(
                materialize_tool_payload(
                    tool_id,
                    agent_id=agent_id,
                    stage=stage,
                    as_of=as_of,
                )
            )
            assert isinstance(payload, dict)
            assert payload

    marker = json.loads(
        (tmp_path / "cache" / "structured_smoke_fixture_bundle.json").read_text(
            encoding="utf-8"
        )
    )
    assert marker["fixture_class"] == "SYNTHETIC_NON_PRODUCTION"
    assert marker["contains_vendor_prose"] is False
    body = {key: value for key, value in marker.items() if key != "bundle_hash"}
    assert marker["bundle_hash"] == canonical_hash(body)


def test_structured_smoke_early_semiconductor_materialization_requires_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    as_of = "2025-06-17"
    bindings = build_structured_smoke_fixtures(
        tmp_path / "cache",
        as_of,
        eligibility_artifact_path=_write_eligibility_artifact(tmp_path),
    )
    _bind_structured_smoke(bindings, monkeypatch)
    monkeypatch.setenv(
        "MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS",
        "structured_smoke",
    )

    payload = json.loads(
        materialize_tool_payload(
            "get_sector_research_snapshot",
            agent_id="semiconductor",
            stage="semiconductor",
            as_of=as_of,
        )
    )
    assert payload["fixture_class"] == "SYNTHETIC_NON_PRODUCTION"
    assert payload["snapshot_hash"] == canonical_hash(
        {key: value for key, value in payload.items() if key != "snapshot_hash"}
    )

    monkeypatch.delenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS")
    with pytest.raises(
        DataVendorUnavailable,
        match="sector ETF direction authority is not effective for as_of",
    ):
        materialize_tool_payload(
            "get_sector_research_snapshot",
            agent_id="semiconductor",
            stage="semiconductor",
            as_of=as_of,
        )


def test_structured_smoke_sector_fixture_has_a_semantically_ordered_direction_signal(
    tmp_path: Path,
) -> None:
    as_of = "2026-07-17"
    build_structured_smoke_fixtures(tmp_path / "cache", as_of)
    snapshot = json.loads(
        (
            tmp_path
            / "cache"
            / "sector_snapshots"
            / as_of
            / "semiconductor.json"
        ).read_text(encoding="utf-8")
    )

    direction_cards = snapshot["direction_cards"]
    metric_values = {
        metric_id: [
            next(
                metric["value"]
                for metric in card["metrics"]
                if metric["metric_id"] == metric_id
            )
            for card in direction_cards
        ]
        for metric_id in (
            "REVENUE_GROWTH_TTM_YOY",
            "OPERATING_CASHFLOW_MARGIN_TTM",
            "EARNINGS_YIELD_TTM",
            "BOOK_TO_PRICE_LF",
            "RELATIVE_TOTAL_RETURN_20D",
            "ABOVE_MA20_PCT",
            "TURNOVER_EXPANSION_20D_PCT",
            "REALIZED_VOLATILITY_60D",
            "CURRENT_DRAWDOWN_252D",
        )
    }
    for metric_id, values in metric_values.items():
        expected = sorted(values) if metric_id == "REALIZED_VOLATILITY_60D" else sorted(values, reverse=True)
        assert values == expected
        assert len(set(values)) == len(values)

    security_rows = snapshot["security_scoring_rows"]
    assert [row["adjusted_return_20d"] for row in security_rows] == sorted(
        (row["adjusted_return_20d"] for row in security_rows), reverse=True
    )
    assert [row["realized_volatility_20d"] for row in security_rows] == sorted(
        row["realized_volatility_20d"] for row in security_rows
    )
    assert [row["net_moneyflow_20d_cny"] for row in security_rows] == sorted(
        (row["net_moneyflow_20d_cny"] for row in security_rows), reverse=True
    )


def test_structured_smoke_superinvestors_receive_lineage_bound_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    as_of = "2026-07-17"
    bindings = build_structured_smoke_fixtures(tmp_path / "cache", as_of)
    _bind_structured_smoke(bindings, monkeypatch)

    for agent_id in structured_smoke_fixtures_module.SUPERINVESTOR_AGENTS:
        payload = json.loads(
            materialize_tool_payload(
                "get_superinvestor_candidate_snapshot",
                agent_id=agent_id,
                stage=agent_id,
                as_of=as_of,
            )
        )
        assert payload["candidate_status"] == "AVAILABLE"
        assert len(payload["candidate_universe"]) == 1
        assert payload["constraints"]["cash_only"] is False
        assert payload["constraints"]["allow_new_positions"] is True

        candidate = payload["candidate_universe"][0]
        source_ref = next(
            ref
            for ref in payload["upstream_accepted_output_refs"]
            if ref["accepted_output_id"] == candidate["source_output_id"]
        )
        assert source_ref["accepted_output_kind"] == "STANDARD_SECTOR_SELECTION"
        assert source_ref["accepted_output_hash"] == candidate["source_output_hash"]
        assert source_ref["agent_id"] == candidate["source_sector_agent_id"]
        assert candidate["evidence_ids"] == source_ref["evidence_ids"]
        assert payload["role_context"]["candidate_origin_set_hash"] == canonical_hash(
            payload["candidate_universe"]
        )


def test_structured_smoke_materializes_all_bound_runtime_queries_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    as_of = "2026-07-17"
    cache_root = tmp_path / "cache"
    bindings = build_structured_smoke_fixtures(cache_root, as_of)
    _bind_structured_smoke(bindings, monkeypatch)

    class FakeDigestBuilder:
        def __call__(
            self, tool_id: str, raw_payload: str, args: dict[str, object]
        ) -> dict[str, str]:
            return {
                "digest": json.dumps(
                    {
                        "tool_id": tool_id,
                        "source_hash": canonical_hash({"text": raw_payload}),
                    },
                    sort_keys=True,
                ),
                "model_hash": canonical_hash(
                    {"model": "structured-smoke-offline"}
                ),
                "prompt_hash": canonical_hash({"tool_id": tool_id, "args": args}),
            }

    monkeypatch.setattr(
        tool_capabilities_module,
        "FrozenResearchDigestBuilder",
        FakeDigestBuilder,
    )
    store = tool_capabilities_module.get_capability_store()
    cases = [
        (agent_id, agent_id, "get_superinvestor_candidate_snapshot")
        for agent_id in structured_smoke_fixtures_module.SUPERINVESTOR_AGENTS
    ]
    cases.extend(
        (
            ("alpha_discovery", "alpha_discovery", "get_alpha_candidate_snapshot"),
            ("cro", "cro", "get_cro_risk_snapshot"),
            (
                "autonomous_execution",
                "autonomous_execution",
                "get_execution_snapshot",
            ),
            ("cio", "cio_proposal", "get_cio_decision_snapshot"),
            ("cio", "cio_final", "get_cio_decision_snapshot"),
        )
    )
    for agent_id, stage, tool_id in cases:
        frozen = json.loads(
            (
                cache_root
                / "runtime_snapshots"
                / as_of
                / f"{agent_id}.{stage}.{tool_id}.json"
            ).read_text(encoding="utf-8")
        )
        accepted_refs = {
            f"{ref['accepted_output_kind']}:{ref['agent_id']}:{index}": {
                key: ref[key]
                for key in (
                    "accepted_output_kind",
                    "agent_id",
                    "accepted_output_id",
                    "accepted_output_hash",
                )
            }
            for index, ref in enumerate(frozen["upstream_accepted_output_refs"])
        }
        prepared = store.prepare(
            {
                "graph_run_id": f"structured-smoke-graph-{agent_id}-{stage}",
                "run_slot_id": f"structured-smoke-slot-{agent_id}-{stage}",
                "run_id": f"structured-smoke-run-{agent_id}-{stage}",
                "node_id": f"structured-smoke-node-{agent_id}-{stage}",
                "agent_id": agent_id,
                "stage": stage,
                "as_of": as_of,
                "materialization_request_id": (
                    f"structured-smoke-request-{agent_id}-{stage}"
                ),
                "runtime_inputs": {"accepted_output_refs": accepted_refs},
                "candidate_scope": {"accepted_output_refs": accepted_refs},
                "ttl_seconds": 300,
            }
        )
        assert {
            tool["name"] for tool in store.list_tools(prepared["capability"])
        } == set(tool_capabilities_module.allowed_tools_for_agent(agent_id))


def test_structured_smoke_empty_position_buy_lineage_rebinds_without_stage_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    as_of = "2025-06-17"
    cache_root = tmp_path / "cache"
    eligibility_artifact = _write_eligibility_artifact(tmp_path)
    bindings = build_structured_smoke_fixtures(
        cache_root,
        as_of,
        eligibility_artifact_path=eligibility_artifact,
    )
    _bind_structured_smoke(bindings, monkeypatch)

    proposal_lineage = [
        *[
            ("MACRO_TRANSMISSION", agent_id, agent_id)
            for agent_id in structured_smoke_fixtures_module.AGENTS_BY_LAYER["macro"]
        ],
        *[
            ("STANDARD_SECTOR_SELECTION", agent_id, agent_id)
            for agent_id in structured_smoke_fixtures_module.STANDARD_SECTOR_AGENTS
        ],
        *[
            ("SUPERINVESTOR_SELECTION", agent_id, agent_id)
            for agent_id in structured_smoke_fixtures_module.SUPERINVESTOR_AGENTS
        ],
        ("ALPHA_DISCOVERY", "alpha_discovery", "alpha_discovery"),
    ]
    cases = {
        ("cio", "cio_proposal", "get_cio_decision_snapshot"): proposal_lineage,
        ("cro", "cro", "get_cro_risk_snapshot"): [
            ("CIO_PROPOSAL", "cio", "cio_proposal")
        ],
        ("autonomous_execution", "autonomous_execution", "get_execution_snapshot"): [
            ("CIO_PROPOSAL", "cio", "cio_proposal"),
            ("CRO_RISK_REVIEW", "cro", "cro"),
        ],
        ("cio", "cio_final", "get_cio_decision_snapshot"): [
            ("CIO_PROPOSAL", "cio", "cio_proposal"),
            ("CRO_RISK_REVIEW", "cro", "cro"),
            (
                "EXECUTION_ASSESSMENT",
                "autonomous_execution",
                "autonomous_execution",
            ),
        ],
    }
    proposal_payload = json.loads(
        (
            cache_root
            / "runtime_snapshots"
            / as_of
            / "cio.cio_proposal.get_cio_decision_snapshot.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal_payload["role_context"]["position_snapshot_hash"] == canonical_hash([])
    assert proposal_payload["candidate_status"] == "AVAILABLE"
    proposal_candidates = proposal_payload["candidate_universe"]
    assert len(proposal_candidates) == 1
    proposal_candidate = proposal_candidates[0]
    assert proposal_candidate["ts_code"] in structured_smoke_fixtures_module._approved_etf_authority()
    assert not proposal_candidate["ts_code"].startswith("600")
    assert proposal_candidate["current_weight"] == 0.0
    assert proposal_candidate["reference_target_weight"] == 0.1
    assert proposal_candidate["metrics"]["delta_weight"] == 0.1
    assert proposal_candidate["source_kind"] == "SECTOR_SELECTION"
    proposal_source_ref = next(
        ref
        for ref in proposal_payload["upstream_accepted_output_refs"]
        if ref["accepted_output_id"] == proposal_candidate["source_output_id"]
    )
    assert proposal_source_ref["accepted_output_kind"] == "STANDARD_SECTOR_SELECTION"
    assert proposal_source_ref["accepted_output_hash"] == proposal_candidate["source_output_hash"]
    assert set(proposal_source_ref["evidence_ids"]).issubset(
        proposal_candidate["evidence_ids"]
    )
    validated = structured_smoke_fixtures_module._load_eligibility_artifact(
        eligibility_artifact, date(2025, 6, 17)
    )
    assert set(validated["proof_by_code"]) == set(
        structured_smoke_fixtures_module._approved_etf_authority()
    )
    proof_id = f"structured-smoke:eligibility-proof:{proposal_candidate['ts_code']}"

    for (agent_id, stage, tool_id), expected_lineage in cases.items():
        payload = json.loads(
            (
                cache_root
                / "runtime_snapshots"
                / as_of
                / f"{agent_id}.{stage}.{tool_id}.json"
            ).read_text(encoding="utf-8")
        )
        assert payload["candidate_status"] == "AVAILABLE"
        assert len(payload["candidate_universe"]) == 1
        candidate = payload["candidate_universe"][0]
        assert candidate["ts_code"] == proposal_candidate["ts_code"]
        assert candidate["candidate_ref"] == proposal_candidate["candidate_ref"]
        assert candidate["current_weight"] == 0.0
        assert proof_id in candidate["evidence_ids"]
        if stage == "cio_proposal":
            assert set(proposal_source_ref["evidence_ids"]).issubset(
                candidate["evidence_ids"]
            )
            assert candidate["reference_target_weight"] == 0.1
            assert candidate["metrics"]["delta_weight"] == 0.1
            assert candidate["source_output_id"] == proposal_candidate["source_output_id"]
            assert candidate["source_output_hash"] == proposal_candidate["source_output_hash"]
        elif stage == "cio_final":
            proposal_accepted_ref = next(
                ref
                for ref in payload["upstream_accepted_output_refs"]
                if ref["accepted_output_kind"] == "CIO_PROPOSAL"
            )
            assert set(proposal_accepted_ref["evidence_ids"]).issubset(
                candidate["evidence_ids"]
            )
        else:
            assert {
                evidence_id
                for ref in payload["upstream_accepted_output_refs"]
                for evidence_id in ref["evidence_ids"]
            }.issubset(candidate["evidence_ids"])
        if agent_id == "autonomous_execution":
            assert candidate["target_weight"] == 0.1
            assert candidate["requested_delta_weight"] == 0.1
            assert candidate["side"] == "BUY"
        elif stage != "cio_proposal":
            assert candidate["proposed_target_weight"] == 0.1
            assert candidate["proposed_delta_weight"] == 0.1
        assert candidate["evidence_ids"]
        if stage == "cro":
            assert payload["role_context"]["portfolio_exposure_snapshot_hash"] == canonical_hash(
                {"total_weight": 0.0, "sector_weights": {}}
            )
        expected_identities = [
            {
                "accepted_output_kind": accepted_output_kind,
                "agent_id": upstream_agent_id,
                "stage": upstream_stage,
                "as_of": as_of,
                "accepted_output_id": (
                    f"structured-smoke:accepted:{upstream_agent_id}:{upstream_stage}"
                ),
                "accepted_output_hash": canonical_hash(
                    {
                        "agent_id": upstream_agent_id,
                        "stage": upstream_stage,
                        "accepted_output_kind": accepted_output_kind,
                        "as_of": as_of,
                    }
                ),
            }
            for accepted_output_kind, upstream_agent_id, upstream_stage in expected_lineage
        ]
        assert [
            {
                key: ref[key]
                for key in (
                    "accepted_output_kind",
                    "agent_id",
                    "stage",
                    "as_of",
                    "accepted_output_id",
                    "accepted_output_hash",
                )
            }
            for ref in payload["upstream_accepted_output_refs"]
        ] == expected_identities
        controls = [
            value
            for key, value in payload["role_context"].items()
            if key.endswith("_control_source")
        ]
        if stage == "cio_final":
            assert all(
                control["source_status"] == "ACCEPTED_OUTPUT"
                for control in controls
            )
            assert all(control["accepted_output_id"] for control in controls)
            assert all(control["accepted_output_hash"] for control in controls)
            assert all(control["stage_skip_id"] is None for control in controls)
            assert all(control["stage_skip_hash"] is None for control in controls)
        else:
            assert all(control["source_status"] == "ACCEPTED_OUTPUT" for control in controls)
            assert all(control["stage_skip_id"] is None for control in controls)
        accepted_refs = {
            f"{ref['accepted_output_kind']}:{ref['agent_id']}": {
                key: ref[key]
                for key in (
                    "accepted_output_kind",
                    "agent_id",
                    "accepted_output_id",
                    "accepted_output_hash",
                )
            }
            for ref in payload["upstream_accepted_output_refs"]
        }
        rebound = json.loads(
            materialize_tool_payload(
                tool_id,
                agent_id=agent_id,
                stage=stage,
                as_of=as_of,
                graph_run_id="structured-smoke-decision-lineage",
                accepted_output_refs=accepted_refs,
            )
        )
        assert rebound["graph_run_id"] == "structured-smoke-decision-lineage"
        assert [
            {
                key: ref[key]
                for key in (
                    "accepted_output_kind",
                    "agent_id",
                    "stage",
                    "as_of",
                    "accepted_output_id",
                    "accepted_output_hash",
                )
            }
            for ref in rebound["upstream_accepted_output_refs"]
        ] == expected_identities


def test_structured_smoke_disables_forward_source_prepare_without_archive_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    as_of = "2026-07-17"
    cache_root = tmp_path / "cache"
    bindings = build_structured_smoke_fixtures(cache_root, as_of)
    _bind_structured_smoke(bindings, monkeypatch)
    monkeypatch.setenv(
        "MOSAIC_AGENT_TOOL_LEDGER_PATH",
        str(tmp_path / "agent_tool_capabilities.sqlite3"),
    )

    store = tool_capabilities_module.get_capability_store()
    materializer = store.adaptive_query_materializer
    assert materializer is not None
    assert materializer.source_preparer is None

    with pytest.raises(
        DataVendorUnavailable,
        match="policy forward archive has no proven coverage",
    ):
        materializer(
            "get_industry_policy_digest",
            {
                "as_of": as_of,
                "lookback_days": 7,
                "source": "govcn",
                "topic": "__fixture_topic_miss__",
            },
        )

    sector_payload = json.loads(
        materialize_tool_payload(
            "get_sector_research_snapshot",
            agent_id="semiconductor",
            stage="semiconductor",
            as_of=as_of,
        )
    )
    assert sector_payload["fixture_class"] == "SYNTHETIC_NON_PRODUCTION"
    assert not (
        Path(bindings["MOSAIC_FORWARD_ARCHIVE_ROOT"])
        / ".mosaic/agent_data/forward_archive_sources.lock"
    ).exists()


def test_structured_smoke_sector_role_event_binding_matches_runtime_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    as_of = "2025-06-17"
    bindings = build_structured_smoke_fixtures(
        tmp_path / "cache",
        as_of,
        eligibility_artifact_path=_write_eligibility_artifact(tmp_path),
    )
    _bind_structured_smoke(bindings, monkeypatch)

    payloads = {
        role: json.loads(
            materialize_tool_payload(
                "get_sector_research_snapshot",
                agent_id=role,
                stage=role,
                as_of=as_of,
            )
        )
        for role in ("biotech", "energy")
    }

    biotech = payloads["biotech"]
    assert "event_coverage" not in biotech
    assert "role_event_snapshot_ref" not in biotech
    assert biotech["snapshot_hash"] == canonical_hash(
        {key: value for key, value in biotech.items() if key != "snapshot_hash"}
    )

    energy = payloads["energy"]
    assert "event_coverage" in energy
    assert "role_event_snapshot_ref" in energy
    assert energy["snapshot_hash"] == canonical_hash(
        {key: value for key, value in energy.items() if key != "snapshot_hash"}
    )


def test_structured_smoke_bundle_seals_sector_adaptive_archive(
    tmp_path: Path,
) -> None:
    as_of = "2026-07-17"
    bindings = build_structured_smoke_fixtures(tmp_path / "cache", as_of)
    store = SectorArchiveStore(
        Path(bindings["MOSAIC_SECTOR_ARCHIVE_PATH"]), create=False
    )
    reader = SectorArchiveQueryReader(store=store)
    snapshot = json.loads(
        (
            tmp_path
            / "cache"
            / "sector_snapshots"
            / as_of
            / "semiconductor.json"
        ).read_text(encoding="utf-8")
    )
    security = snapshot["eligible_security_universe"][0]
    ticker = security["ts_code"]
    etf = next(
        ticker
        for card in snapshot["direction_cards"]
        for ticker in card["etf_family"]["etf_ts_codes"]
    )

    assert reader("get_stock_data", ticker, "2025-07-18", as_of)
    assert reader("get_indicators", ticker, "close_200_sma", as_of, 365)
    for method in (
        "get_income_statement",
        "get_balance_sheet",
        "get_cashflow",
    ):
        assert reader(method, ticker, "annual", as_of)
        assert reader(method, ticker, "quarterly", as_of)
    assert reader("get_etf_holdings", etf, as_of)

    forward_reader = ForwardArchiveQueryReader(
        root=Path(bindings["MOSAIC_FORWARD_ARCHIVE_ROOT"]),
        sector_archive_store=store,
        policy_cache_dir=tmp_path / "cache" / "gov_policy",
    )
    start_date = "2026-06-18"
    assert forward_reader("get_stock_research", ticker, start_date, as_of, 10)
    assert forward_reader("get_broker_research", ticker, start_date, as_of, 10)
    assert forward_reader("get_industry_policy", as_of, 365, "govcn")
    rke_materialization = build_rke_agent_research_materialization(
        root=Path(bindings["MOSAIC_FORWARD_ARCHIVE_ROOT"]),
        registry_dir=bindings["MOSAIC_REGISTRY_DIR"],
        agent_id="semiconductor",
        as_of_date=as_of,
        layer="sector",
        ticker=ticker,
        sector=security["direction_id"],
        max_items=12,
    )
    assert rke_materialization["source_ids"] == ()
    assert rke_materialization["context"]["summary"]["item_count"] == 0

    supply_chain_archive = OfficialSupplyChainDisclosureArchive(
        Path(bindings["MOSAIC_SUPPLY_CHAIN_ARCHIVE_PATH"]), create=False
    )

    def unexpected_supply_chain_transport(*_args, **_kwargs):
        raise AssertionError("warm synthetic supply-chain archive used transport")

    supply_chain_collector = CninfoSupplyChainDisclosureCollector(
        archive=supply_chain_archive,
        get_bytes=unexpected_supply_chain_transport,
        post_form=unexpected_supply_chain_transport,
        pdf_text_extractor=unexpected_supply_chain_transport,
    )
    for relationship_ticker in ("000001.SZ", "000002.SZ"):
        supply_chain_payload = json.loads(
            supply_chain_collector.materialize(
                ticker=relationship_ticker,
                as_of=as_of,
            )["payload"]
        )
        assert supply_chain_payload["edges"]
    supply_chain_path = Path(bindings["MOSAIC_SUPPLY_CHAIN_ARCHIVE_PATH"])
    assert not Path(f"{supply_chain_path}-wal").exists()
    assert not Path(f"{supply_chain_path}-shm").exists()

    china_store = ChinaAgentDataArchiveStore(
        Path(bindings["MOSAIC_CHINA_AGENT_ARCHIVE_DB"]), create=False
    )
    china_reader = ChinaArchiveQueryReader(store=china_store)
    institutional_group = china_store.load_route_group(
        as_of, INSTITUTIONAL_ROUTE_GROUP
    )
    assert {row["ts_code"] for row in institutional_group["fund_share_rows"]} == set(
        structured_smoke_fixtures_module.INSTITUTIONAL_ETF_UNIVERSE
    )
    assert china_reader("get_yield_curve_cn", as_of, 365)
    for route_group in (INSTITUTIONAL_ROUTE_GROUP, CURVE_ROUTE_GROUP):
        group = china_store.load_route_group(as_of, route_group)
        assert china_archive_source_receipt(group, route_group).receipt_hash.startswith(
            "sha256:"
        )


def test_structured_smoke_l1_l3_opportunities_use_exact_member_authorities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    as_of_date = "2026-07-17"
    as_of = f"{as_of_date}T15:00:00+08:00"
    cache_root = tmp_path / "cache"
    bindings = build_structured_smoke_fixtures(cache_root, as_of_date)
    _bind_structured_smoke(bindings, monkeypatch)

    expected_fields = {
        "MACRO_TRANSMISSION": None,
        "SECTOR_TILT_PICKS": {
            "subindustry_id",
            "security_shortlist_id",
            "security_shortlist_hash",
            "security_ts_codes",
        },
        "SUPERINVESTOR_PICKS": {"candidate_ref", "ts_code"},
    }
    for agent_id, contract in OUTCOME_CONTRACTS.items():
        if contract["layer"] == "DECISION":
            continue
        projection = load_evaluation_opportunity_projection(
            as_of,
            agent_id,
            root=cache_root / "outcome_runtime",
        )
        members = projection["member_refs"]
        object_type = contract["evaluation_object_type"]
        if object_type == "SUPERINVESTOR_PICKS":
            assert members == []
            continue
        assert members
        fields = expected_fields[object_type]
        if fields is None:
            member_field = (
                "event_id"
                if contract["sample_schedule"]["kind"] == "EVENT_TRIGGERED"
                else "path_snapshot_id"
            )
            fields = {member_field}
        assert all(set(member) == fields for member in members)
        authority = materialize_pre_run_authority(
            agent_id=agent_id,
            as_of=as_of,
            graph_run_id="structured-smoke-opportunity-test",
            schedule_slot={
                "outcome_schedule_slot_hash": "sha256:" + "1" * 64,
                "trigger_event": (
                    {
                        "event_id": (
                            f"structured-smoke:event:{agent_id}:{as_of_date}"
                        )
                    }
                    if contract["sample_schedule"]["kind"] == "EVENT_TRIGGERED"
                    else None
                ),
            },
        )
        assert members == authority["member_refs"]


@pytest.mark.parametrize("mutation", ["tamper", "extra", "missing"])
def test_structured_smoke_runtime_rejects_artifact_inventory_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    as_of = "2026-07-17"
    cache_root = tmp_path / "cache"
    bindings = build_structured_smoke_fixtures(cache_root, as_of)
    _bind_structured_smoke(bindings, monkeypatch)

    macro_fixture = cache_root / "macro_snapshots" / as_of / "china.json"
    if mutation == "tamper":
        macro_fixture.write_bytes(macro_fixture.read_bytes() + b"\n")
    elif mutation == "extra":
        extra = cache_root / "sector_snapshots" / as_of / "unexpected.json"
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("{}\n", encoding="utf-8")
    else:
        macro_fixture.unlink()

    with pytest.raises(DataVendorUnavailable, match="artifact inventory mismatch"):
        materialize_tool_payload(
            "get_superinvestor_candidate_snapshot",
            agent_id="ackman",
            stage="ackman",
            as_of=as_of,
        )


def test_structured_smoke_builder_rejects_nonempty_root_without_deleting_it(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    retained = cache_root / "preexisting.txt"
    retained.write_text("must remain untouched\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="fresh empty directory"):
        build_structured_smoke_fixtures(cache_root, "2026-07-17")

    assert retained.read_text(encoding="utf-8") == "must remain untouched\n"
    assert not (cache_root / "structured_smoke_fixture_bundle.json").exists()


def test_structured_smoke_shell_exports_quote_every_binding() -> None:
    rendered = render_shell_exports(
        {
            "MOSAIC_CACHE_DIR": "/tmp/root with spaces",
            "MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS": "structured_smoke",
        }
    )

    assert rendered.splitlines() == [
        "export MOSAIC_CACHE_DIR='/tmp/root with spaces'",
        "export MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS=structured_smoke",
    ]
