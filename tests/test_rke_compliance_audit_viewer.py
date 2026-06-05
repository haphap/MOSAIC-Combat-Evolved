from __future__ import annotations

import json
from pathlib import Path

from mosaic.rke import (
    build_audit_view,
    build_registry_index,
    evaluate_source_license,
    filter_sources_for_runtime,
    write_central_bank_mvp_registry,
)


def _first_jsonl_row(path: Path) -> dict:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            return json.loads(line)
    raise AssertionError(f"{path} is empty")


def test_tushare_pending_review_reports_are_sandbox_only():
    row = _first_jsonl_row(Path("registry/sources/tushare_research_reports.jsonl"))

    decision = evaluate_source_license(row)
    production_sources, decisions = filter_sources_for_runtime((row,), production=True)
    sandbox_sources, _ = filter_sources_for_runtime((row,), production=False)

    assert row["source_type"] == "tushare_research_report"
    assert decision.license_status == "pending_review"
    assert decision.allowed_for_sandbox
    assert not decision.allowed_for_production_runtime
    assert not decision.allowed_for_derived_claim_storage
    assert "sandbox-only" in " ".join(decision.reasons)
    assert production_sources == ()
    assert decisions == (decision,)
    assert sandbox_sources == (row,)


def test_audit_viewer_resolves_central_bank_registry_chain(tmp_path: Path):
    outputs = write_central_bank_mvp_registry(tmp_path)
    trace = json.loads(Path(outputs["audit"]).read_text(encoding="utf-8"))
    runtime_output = json.loads(Path(outputs["runtime_output"]).read_text(encoding="utf-8"))

    index = build_registry_index(tmp_path)
    view = build_audit_view(trace, registry_index=index, trace_id="central-bank-mvp")

    assert runtime_output["agent_output_id"] == "OUT-CB-20260605-0001"
    assert view.complete
    assert view.missing_references == ()
    assert {reference.ref_type for reference in view.references} == {
        "source",
        "claim",
        "hypothesis",
        "rule",
        "parameter_path",
        "experiment",
        "patch",
        "agent_output",
    }
