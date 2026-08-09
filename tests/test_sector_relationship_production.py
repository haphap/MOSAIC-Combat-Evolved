from __future__ import annotations

from pathlib import Path

import pytest

import mosaic.bridge.tool_capabilities as capability_module
import mosaic.dataflows.sector_relationship_production as production_module
from mosaic.bridge.tool_capabilities import AgentToolCapabilityStore
from mosaic.dataflows.adaptive_query_archives import TrustedArchiveQueryRouter
from mosaic.dataflows.china_agent_data_archive import ChinaAgentDataArchiveStore
from mosaic.dataflows.china_archive_queries import ChinaArchiveQueryReader
from mosaic.dataflows.frozen_adaptive_queries import FrozenAdaptiveQueryStore
from mosaic.dataflows.cninfo_supply_chain import CninfoSupplyChainDisclosureCollector
from mosaic.dataflows.forward_archive_queries import ForwardArchiveQueryReader
from mosaic.dataflows.sector_relationship_production import (
    SectorRelationshipAdaptiveQueryPreparer,
)
from mosaic.dataflows.sector_archive import SectorArchiveStore
from mosaic.dataflows.sector_archive_queries import SectorArchiveQueryReader
from mosaic.dataflows.sector_relationship_queries import (
    SectorRelationshipQueryMaterializer,
)
from mosaic.dataflows.sector_relationship_source_evidence import (
    SectorRelationshipSourceEvidenceAuthority,
)
from mosaic.dataflows.staged_query_receipt_store import StagedQueryReceiptStore
from mosaic.dataflows.supply_chain_disclosures import (
    OfficialSupplyChainDisclosureArchive,
)


def test_production_preparer_uses_only_validated_initial_scope_and_exact_allowed_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan_calls: list[dict] = []
    store_calls: list[dict] = []
    plan = {
        "authorized_scope": {
            "as_of": "2026-07-09",
            "earliest_date": "2025-07-09",
            "tickers": ["600000.SH"],
            "etfs": [],
            "sectors": ["银行"],
            "indicator_families": ["rsi"],
        },
        "query_requests": [
            {
                "tool_id": "get_indicators",
                "args": {
                    "ticker": "600000.SH",
                    "indicator": "rsi",
                    "as_of": "2026-07-09",
                    "lookback": 30,
                },
            }
        ],
    }

    def build_plan(**kwargs):
        plan_calls.append(kwargs)
        return plan

    class Store:
        def prepare(self, **kwargs):
            store_calls.append(kwargs)
            return {"bundle_id": "frozen_bundle_1", "public_projection": {"ok": True}}

    monkeypatch.setattr(production_module, "build_sector_relationship_query_plan", build_plan)
    monkeypatch.setattr(
        production_module,
        "build_sector_relationship_preservation_overlay",
        lambda root: {"overlay": str(root)},
    )
    def materializer(tool_id, args):
        return {"tool_id": tool_id, "args": args}
    preparer = SectorRelationshipAdaptiveQueryPreparer(
        root=tmp_path,
        frozen_store=Store(),
        materializer=materializer,
    )

    result = preparer(
        agent_id="financials",
        stage="financials",
        as_of="2026-07-09",
        initial_payloads={"get_sector_research_snapshot": "trusted"},
        runtime_inputs={"untrusted": "must-not-expand-scope"},
        candidate_scope={"tickers": ["FOREIGN"]},
        allowed_tools=("get_indicators",),
    )

    assert result == {"bundle_id": "frozen_bundle_1", "public_projection": {"ok": True}}
    assert plan_calls == [
        {
            "agent_id": "financials",
            "stage": "financials",
            "as_of": "2026-07-09",
            "initial_payloads": {"get_sector_research_snapshot": "trusted"},
            "allowed_tools": ("get_indicators",),
        }
    ]
    assert store_calls == [
        {
            "agent_id": "financials",
            "stage": "financials",
            "as_of": "2026-07-09",
            "authorized_scope": plan["authorized_scope"],
            "query_requests": plan["query_requests"],
            "preservation_overlay": {"overlay": str(tmp_path.resolve())},
            "materializer": materializer,
        }
    ]


def test_default_capability_store_wires_distinct_private_production_components(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "runtime/agent_tool_capabilities.sqlite3"
    monkeypatch.setenv("MOSAIC_AGENT_TOOL_LEDGER_PATH", str(ledger))
    monkeypatch.setenv(
        "MOSAIC_SECTOR_ARCHIVE_PATH", str(tmp_path / "sector-archive.sqlite3")
    )
    monkeypatch.setenv(
        "MOSAIC_CHINA_AGENT_ARCHIVE_DB", str(tmp_path / "china-archive.sqlite3")
    )
    monkeypatch.delenv("MOSAIC_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("MOSAIC_LLM_MODEL", raising=False)
    monkeypatch.delenv("MOSAIC_LLM_API_KEY", raising=False)

    store = capability_module.get_capability_store()

    assert isinstance(store, AgentToolCapabilityStore)
    assert isinstance(store.adaptive_query_store, FrozenAdaptiveQueryStore)
    assert store.adaptive_query_store.db_path == (
        ledger.parent / "agent_frozen_adaptive_queries.sqlite3"
    )
    assert isinstance(
        store.adaptive_query_preparer,
        SectorRelationshipAdaptiveQueryPreparer,
    )
    materializer = store.adaptive_query_preparer.materializer
    assert isinstance(materializer, SectorRelationshipQueryMaterializer)
    assert isinstance(materializer.route_caller, TrustedArchiveQueryRouter)
    assert set(materializer.route_caller.owners) == {
        "get_balance_sheet",
        "get_broker_research",
        "get_cashflow",
        "get_etf_holdings",
        "get_income_statement",
        "get_indicators",
        "get_industry_moneyflow",
        "get_industry_policy",
        "get_stock_data",
        "get_stock_research",
        "get_yield_curve_cn",
    }
    assert isinstance(
        materializer.route_caller.owners["get_stock_data"],
        SectorArchiveQueryReader,
    )
    assert isinstance(
        materializer.route_caller.owners["get_industry_moneyflow"],
        ChinaArchiveQueryReader,
    )
    forward_reader = materializer.route_caller.owners["get_stock_research"]
    assert isinstance(forward_reader, ForwardArchiveQueryReader)
    assert materializer.route_caller.owners["get_broker_research"] is forward_reader
    assert materializer.route_caller.owners["get_industry_policy"] is forward_reader
    assert isinstance(
        materializer.source_evidence_authority,
        SectorRelationshipSourceEvidenceAuthority,
    )
    assert isinstance(
        materializer.source_evidence_authority.receipt_store,
        StagedQueryReceiptStore,
    )
    assert isinstance(
        materializer.source_evidence_authority.sector_archive_store,
        SectorArchiveStore,
    )
    assert isinstance(
        materializer.source_evidence_authority.china_archive_store,
        ChinaAgentDataArchiveStore,
    )
    assert materializer.source_evidence_authority.forward_archive_reader is forward_reader
    assert isinstance(
        materializer.supply_chain_archive,
        CninfoSupplyChainDisclosureCollector,
    )
    assert isinstance(
        materializer.supply_chain_archive.archive,
        OfficialSupplyChainDisclosureArchive,
    )
    component_paths = {
        store.db_path,
        store.adaptive_query_store.db_path,
        materializer.source_evidence_authority.receipt_store.db_path,
        materializer.supply_chain_archive.db_path,
    }
    assert len(component_paths) == 4
    assert all(path.parent == ledger.parent for path in component_paths)
