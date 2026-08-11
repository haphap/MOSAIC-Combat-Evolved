from __future__ import annotations

from pathlib import Path

import pytest

import mosaic.bridge.tool_capabilities as capability_module
import mosaic.dataflows.sector_relationship_production as production_module
from mosaic.bridge.tool_capabilities import AgentToolCapabilityStore
from mosaic.dataflows.agent_stage_preparer import ensure_agent_stage_materialization
from mosaic.dataflows.bound_runtime_production import ActiveAdaptiveQueryPreparer
from mosaic.dataflows.frozen_adaptive_queries import FrozenAdaptiveQueryStore
from mosaic.dataflows.cninfo_supply_chain import CninfoSupplyChainDisclosureCollector
from mosaic.dataflows.forward_archive_queries import (
    ForwardArchiveQueryReader,
    ForwardArchiveSourcePreparer,
)
from mosaic.dataflows.sector_relationship_production import (
    SectorRelationshipAdaptiveQueryPreparer,
)
from mosaic.dataflows.sector_relationship_queries import (
    DIRECT_VENDOR_TOOL_IDS,
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
            "defer_materialization": True,
        }
    ]


def test_default_capability_store_wires_distinct_private_production_components(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    direct_owner_calls: list[tuple[str, tuple[object, ...]]] = []
    forward_owner_calls: list[tuple[str, tuple[object, ...]]] = []
    evidence_owner_calls: list[str] = []

    def direct_owner(method: str, *args: object) -> str:
        direct_owner_calls.append((method, args))
        return f"direct:{method}"

    def forward_owner(
        _reader: ForwardArchiveQueryReader, method: str, *args: object
    ) -> str:
        forward_owner_calls.append((method, args))
        return f"forward:{method}"

    def evidence_owner(
        _authority: SectorRelationshipSourceEvidenceAuthority,
        tool_id: str,
        *_args: object,
    ) -> list[dict[str, str]]:
        evidence_owner_calls.append(tool_id)
        return [{"owner": tool_id}]

    ledger = tmp_path / "runtime/agent_tool_capabilities.sqlite3"
    materialization_ledger = tmp_path / "runtime/agent_materialization.sqlite3"
    monkeypatch.setenv("MOSAIC_AGENT_TOOL_LEDGER_PATH", str(ledger))
    monkeypatch.setenv(
        "MOSAIC_AGENT_MATERIALIZATION_DB", str(materialization_ledger)
    )
    monkeypatch.setenv(
        "MOSAIC_SECTOR_ARCHIVE_PATH", str(tmp_path / "sector-archive.sqlite3")
    )
    monkeypatch.setenv(
        "MOSAIC_CHINA_AGENT_ARCHIVE_DB", str(tmp_path / "china-archive.sqlite3")
    )
    monkeypatch.delenv("MOSAIC_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("MOSAIC_LLM_MODEL", raising=False)
    monkeypatch.delenv("MOSAIC_LLM_API_KEY", raising=False)
    monkeypatch.setattr(capability_module, "route_to_vendor", direct_owner)
    monkeypatch.setattr(ForwardArchiveQueryReader, "__call__", forward_owner)
    monkeypatch.setattr(
        SectorRelationshipSourceEvidenceAuthority,
        "__call__",
        evidence_owner,
    )

    store = capability_module.get_capability_store()

    assert isinstance(store, AgentToolCapabilityStore)
    assert store.stage_materialization_preparer is ensure_agent_stage_materialization
    assert materialization_ledger.exists()
    assert isinstance(store.adaptive_query_store, FrozenAdaptiveQueryStore)
    assert store.adaptive_query_store.db_path == (
        ledger.parent / "agent_frozen_adaptive_queries.sqlite3"
    )
    assert isinstance(store.adaptive_query_preparer, ActiveAdaptiveQueryPreparer)
    sector_preparer = store.adaptive_query_preparer.sector_relationship_preparer
    bound_preparer = store.adaptive_query_preparer.bound_runtime_preparer
    assert isinstance(sector_preparer, SectorRelationshipAdaptiveQueryPreparer)
    assert bound_preparer.materializer is sector_preparer.materializer
    materializer = sector_preparer.materializer
    assert isinstance(materializer, SectorRelationshipQueryMaterializer)
    for tool_id in sorted(DIRECT_VENDOR_TOOL_IDS):
        assert materializer.route_caller(tool_id, "sentinel") == f"direct:{tool_id}"
    assert direct_owner_calls == [
        (tool_id, ("sentinel",)) for tool_id in sorted(DIRECT_VENDOR_TOOL_IDS)
    ]
    assert materializer.route_caller("get_industry_policy", "sentinel") == (
        "forward:get_industry_policy"
    )
    assert forward_owner_calls == [("get_industry_policy", ("sentinel",))]

    assert isinstance(materializer.source_preparer, ForwardArchiveSourcePreparer)
    forward_reader = materializer.source_preparer.reader
    assert isinstance(forward_reader, ForwardArchiveQueryReader)
    assert forward_reader.sector_archive_store is None
    assert not hasattr(materializer.route_caller, "owners")
    assert materializer.rke_renderer.__name__ == "_default_rke_renderer"

    for tool_id in sorted(DIRECT_VENDOR_TOOL_IDS):
        assert materializer.source_evidence_authority(
            tool_id, {}, "payload", {}, ()
        ) == []
    for tool_id in ("get_industry_policy_digest", "get_rke_research_context"):
        assert materializer.source_evidence_authority(
            tool_id, {}, "payload", {}, ()
        ) == [{"owner": tool_id}]
    assert evidence_owner_calls == [
        "get_industry_policy_digest",
        "get_rke_research_context",
    ]

    assert isinstance(
        materializer.supply_chain_archive,
        CninfoSupplyChainDisclosureCollector,
    )
    assert isinstance(
        materializer.supply_chain_archive.archive,
        OfficialSupplyChainDisclosureArchive,
    )
    assert isinstance(
        materializer.supply_chain_archive.receipt_store,
        StagedQueryReceiptStore,
    )
    assert materializer.supply_chain_archive.agent_data_ledger is not None
    component_paths = {
        store.db_path,
        store.adaptive_query_store.db_path,
        materializer.supply_chain_archive.receipt_store.db_path,
        materializer.supply_chain_archive.db_path,
    }
    assert len(component_paths) == 4
    assert all(path.parent == ledger.parent for path in component_paths)
