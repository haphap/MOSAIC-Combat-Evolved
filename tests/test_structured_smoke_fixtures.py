from __future__ import annotations

import json
from pathlib import Path

import pytest

import mosaic.bridge.tool_capabilities as tool_capabilities_module
import mosaic.dataflows.geopolitical_events as geopolitical_events_module
import scripts.build_structured_smoke_fixtures as structured_smoke_fixtures_module
from mosaic.bridge.tool_capabilities import (
    ADAPTIVE_QUERY_TOOL_IDS,
    AGENT_TOOL_MATRIX,
    ALL_AGENT_IDS,
    INITIAL_SNAPSHOT_TOOL_IDS,
    materialize_tool_payload,
)
from mosaic.dataflows.agent_materialization import AgentDataMaterializationLedger
from mosaic.dataflows.cninfo_supply_chain import CninfoSupplyChainDisclosureCollector
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.forward_archive_queries import ForwardArchiveQueryReader
from mosaic.dataflows.geopolitical_events import load_geopolitical_events_snapshot
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
from mosaic.dataflows.sector_relationship_source_evidence import (
    SectorRelationshipSourceEvidenceAuthority,
)
from mosaic.dataflows.staged_query_receipt_store import StagedQueryReceiptStore
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


def test_structured_smoke_artifact_root_allowlists_are_identical() -> None:
    assert set(structured_smoke_fixtures_module._FIXTURE_ARTIFACT_ROOTS) == set(
        tool_capabilities_module._SYNTHETIC_FIXTURE_ARTIFACT_ROOTS
    ) == set(geopolitical_events_module._STRUCTURED_SMOKE_ARTIFACT_ROOTS)


def test_structured_smoke_bundle_materializes_all_28_stage_initial_snapshots(
    tmp_path: Path, monkeypatch
) -> None:
    as_of = "2026-07-17"
    bindings = build_structured_smoke_fixtures(tmp_path / "cache", as_of)
    for key, value in bindings.items():
        if key == "MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS":
            continue
        monkeypatch.setenv(key, value)
    with pytest.raises(DataVendorUnavailable, match="snapshot rejected"):
        load_geopolitical_events_snapshot(as_of)
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
    assert len(stages) == 28
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
            if agent_id == "geopolitical" and tool_id == "get_geopolitical_events_snapshot":
                assert payload["schema_version"] == "geopolitical_role_snapshot_v2"
                assert payload["direct_data_quality"] == 1.0
                assert "route_source_coverage" not in payload
                assert len(json.dumps(payload)) < 100_000

    marker = json.loads(
        (tmp_path / "cache" / "structured_smoke_fixture_bundle.json").read_text(
            encoding="utf-8"
        )
    )
    assert marker["fixture_class"] == "SYNTHETIC_NON_PRODUCTION"
    assert marker["contains_vendor_prose"] is False
    body = {key: value for key, value in marker.items() if key != "bundle_hash"}
    assert marker["bundle_hash"] == canonical_hash(body)


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


def test_structured_smoke_bundle_supports_a_non_trading_as_of_date(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    as_of = "2024-06-30"  # Sunday.
    bindings = build_structured_smoke_fixtures(tmp_path / "cache", as_of)
    _bind_structured_smoke(bindings, monkeypatch)

    payload = json.loads(
        materialize_tool_payload(
            "get_market_breadth_snapshot",
            agent_id="market_breadth",
            stage="market_breadth",
            as_of=as_of,
        )
    )
    assert payload["as_of_date"] == as_of
    assert payload["coverage_ratio"] == 1.0


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
    assert rke_materialization["source_ids"]
    assert rke_materialization["context"]["summary"]["item_count"] >= 1
    raw_rke_payload = json.dumps(rke_materialization["context"], sort_keys=True)
    descriptor = {
        "tool_id": "get_rke_research_context",
        "route_id": "private.rke_report_intelligence",
        "as_of": as_of,
        "request_hash": canonical_hash(
            {
                "agent_id": "semiconductor",
                "ticker": ticker,
                "sector": security["direction_id"],
            }
        ),
        "content_hash": canonical_hash({"text": raw_rke_payload}),
        "pit_mode": "DERIVED_FROM_PIT_ARCHIVE",
    }
    ledger = AgentDataMaterializationLedger(tmp_path / "agent-data.sqlite3")
    evidence_authority = SectorRelationshipSourceEvidenceAuthority(
        root=Path(bindings["MOSAIC_FORWARD_ARCHIVE_ROOT"]),
        receipt_store=StagedQueryReceiptStore(tmp_path / "query-receipts.sqlite3"),
        agent_data_ledger=ledger,
    )
    receipts = evidence_authority(
        "get_rke_research_context",
        {
            "agent_id": "semiconductor",
            "as_of": as_of,
            "layer": "sector",
            "ticker": ticker,
            "sector": security["direction_id"],
            "max_items": 12,
        },
        raw_rke_payload,
        descriptor,
        rke_materialization["source_ids"],
    )
    assert receipts
    upstream = ledger.source_capture_receipt(
        receipt_hash=receipts[0]["upstream_evidence_hashes"][0]
    )
    assert upstream is not None
    assert upstream.as_dict()["identity"]["route_id"] == (
        "private.rke_report_intelligence"
    )

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
    assert china_reader("get_industry_moneyflow", as_of, 365, "银行")
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


def test_geopolitical_structured_smoke_requires_expected_bundle_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bindings = build_structured_smoke_fixtures(tmp_path / "cache", "2026-07-17")
    _bind_structured_smoke(bindings, monkeypatch)
    monkeypatch.delenv("MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH")

    with pytest.raises(DataVendorUnavailable, match="marker binding mismatch"):
        load_geopolitical_events_snapshot("2026-07-17")


def test_geopolitical_structured_smoke_rejects_symlinked_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_root = tmp_path / "cache"
    bindings = build_structured_smoke_fixtures(cache_root, "2026-07-17")
    _bind_structured_smoke(bindings, monkeypatch)
    marker_path = cache_root / "structured_smoke_fixture_bundle.json"
    marker_copy = cache_root / "marker-copy.json"
    marker_copy.write_bytes(marker_path.read_bytes())
    marker_path.unlink()
    marker_path.symlink_to(marker_copy.name)

    with pytest.raises(DataVendorUnavailable, match="marker is unavailable"):
        load_geopolitical_events_snapshot("2026-07-17")
