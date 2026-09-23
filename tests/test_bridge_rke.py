from __future__ import annotations

import json

from mosaic.bridge import handlers as _handlers_pkg  # noqa: F401
from mosaic.bridge.registry import get_handler


def dispatch(method: str, params: dict):
    handler = get_handler(method)
    if handler is None:
        raise AssertionError(f"method '{method}' not registered")
    return handler(params)


def _write_jsonl(path, rows):
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_rke_agent_research_context_bridge_returns_redacted_ranked_context(tmp_path):
    registry = tmp_path / "registry" / "report_intelligence"
    registry.mkdir(parents=True)
    _write_jsonl(
        registry / "analytical_footprints.jsonl",
        [
            {
                "footprint_id": "FC-BRIDGE-1",
                "source_id": "SRC-BRIDGE",
                "source_span_ids": ["PRIVATE"],
                "research_case": {"question": "Can margins recover?", "reasoning_chain": ["Inventory falls", "Discounting slows"]},
                "report_id": "RPT-BRIDGE-1",
                "claim_text": "private source prose",
                "target": {"target_type": "stock", "target_id": "600519.SH"},
                "metric_proxy_mapping": ["stock_forward_return"],
                "direction": "positive",
            }
        ],
    )
    _write_jsonl(
        registry / "report_metadata.jsonl",
        [
            {
                "report_id": "RPT-BRIDGE-1",
                "source_id": "SRC-BRIDGE",
                "license_class": "operator_approved_internal_research_use",
                "derived_claim_storage_allowed": True,
                "report_type": "个股研报",
                "ts_code": "600519.SH",
                "publish_datetime": "2026-01-01T00:00:00+08:00",
            }
        ],
    )

    payload = dispatch(
        "rke.agentResearchContext",
        {
            "root": str(tmp_path),
            "agent_id": "cio",
            "layer": "decision",
            "as_of_date": "2026-02-01",
        },
    )

    assert payload["agent_id"] == "decision.cio"
    assert payload["production_signal_allowed"] is False
    assert payload["ranking_policy_id"] == "rke_agent_research_context_rank_v6"
    assert payload["summary"]["item_count"] == 1
    assert payload["context_items"][0]["retrieval_rank"] == 1
    assert "claim_text" not in json.dumps(payload, ensure_ascii=False)
    assert "private source prose" not in json.dumps(payload, ensure_ascii=False)


def test_standalone_macro_prior_export_is_removed():
    assert get_handler("rke.macroAgentPriors") is None
