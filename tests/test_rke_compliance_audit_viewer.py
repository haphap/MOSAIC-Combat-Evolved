from __future__ import annotations

import json
from pathlib import Path

from mosaic.rke import (
    SourceLicenseReviewRecord,
    apply_source_license_reviews,
    build_audit_view,
    build_audit_trace_view,
    build_registry_index,
    build_source_license_review_template,
    evaluate_source_license,
    filter_sources_for_runtime,
    write_central_bank_mvp_registry,
    write_audit_trace_view,
    write_source_license_review_template,
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


def test_license_review_template_and_approval_gate(tmp_path: Path):
    row = _first_jsonl_row(Path("registry/sources/tushare_research_reports.jsonl"))
    template = build_source_license_review_template((row,))
    out = write_source_license_review_template((row,), tmp_path / "license_review.jsonl")
    approved_sources = apply_source_license_reviews(
        (row,),
        (
            SourceLicenseReviewRecord(
                source_id=row["source_id"],
                approved_for_derived_claim_storage=True,
                approved_for_production_runtime=True,
                reviewer="compliance",
                review_date="2026-06-05",
            ),
        ),
    )
    approved_decision = evaluate_source_license(approved_sources[0])

    assert out["rows"] == 1
    assert template[0]["approved_for_production_runtime"] is None
    assert approved_sources[0]["license_status"] == "approved"
    assert "production_runtime_retrieval" in approved_sources[0]["allowed_uses"]
    assert approved_decision.allowed_for_production_runtime


def test_license_review_restriction_keeps_source_out_of_production():
    row = _first_jsonl_row(Path("registry/sources/tushare_research_reports.jsonl"))
    restricted_sources = apply_source_license_reviews(
        (row,),
        (
            {
                "source_id": row["source_id"],
                "approved_for_derived_claim_storage": True,
                "approved_for_production_runtime": False,
                "reviewer": "compliance",
                "review_date": "2026-06-05",
            },
        ),
    )
    decision = evaluate_source_license(restricted_sources[0])

    assert restricted_sources[0]["license_status"] == "restricted"
    assert not decision.allowed_for_production_runtime
    assert "production_runtime_retrieval is forbidden" in decision.reasons


def test_license_review_application_ignores_malformed_review_rows_conservatively():
    row = _first_jsonl_row(Path("registry/sources/tushare_research_reports.jsonl"))

    updated = apply_source_license_reviews(
        (row,),
        (
            "not an object",
            ["also", "not", "object"],
            {"approved_for_derived_claim_storage": True, "approved_for_production_runtime": True},
        ),
    )
    decision = evaluate_source_license(updated[0])

    assert updated[0]["license_status"] == row["license_status"]
    assert "allowed_uses" not in updated[0]
    assert not decision.allowed_for_production_runtime
    assert "pending_review source is sandbox-only until compliance approval" in decision.reasons


def test_tushare_license_review_template_is_pending_manual_approval():
    source_rows = [
        json.loads(line)
        for line in Path("registry/sources/tushare_research_reports.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    rows = [
        json.loads(line)
        for line in Path("registry/compliance/tushare_license_review_template.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert len(rows) == len(source_rows)
    assert {row["current_license_status"] for row in rows} == {"pending_review"}
    assert {row["approved_for_production_runtime"] for row in rows} == {None}
    assert {row["approved_for_derived_claim_storage"] for row in rows} == {None}


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


def test_audit_trace_view_resolves_required_edges(tmp_path: Path):
    write_central_bank_mvp_registry(tmp_path)

    view = build_audit_trace_view(tmp_path)

    assert view.complete
    assert view.node_count == 8
    assert view.edge_count >= 12
    assert view.missing_references == ()
    assert view.broken_edges == ()
    assert {node.ref_type for node in view.nodes} == {
        "source",
        "claim",
        "hypothesis",
        "rule",
        "parameter_path",
        "experiment",
        "patch",
        "agent_output",
    }
    assert ("claim", "source") in {(edge.source_type, edge.target_type) for edge in view.edges}
    assert ("agent_output", "rule") in {
        (edge.source_type, edge.target_type) for edge in view.edges
    }


def test_audit_trace_view_reports_missing_reference(tmp_path: Path):
    outputs = write_central_bank_mvp_registry(tmp_path)
    trace_path = Path(outputs["audit"])
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["claim_ids"] = ["CLAIM-CB-MISSING"]
    trace_path.write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")

    view = build_audit_trace_view(tmp_path)

    assert not view.complete
    assert view.missing_references == ("claim_ids:CLAIM-CB-MISSING",)


def test_audit_trace_view_reports_broken_required_edge(tmp_path: Path):
    outputs = write_central_bank_mvp_registry(tmp_path)
    trace_path = Path(outputs["audit"])
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["source_ids"] = []
    trace_path.write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")

    view = build_audit_trace_view(tmp_path)

    assert not view.complete
    assert any("claim:CLAIM-CB-20260605-0001 missing trace-linked source claim" in item for item in view.broken_edges)


def test_audit_trace_view_reports_malformed_jsonl_rows(tmp_path: Path):
    write_central_bank_mvp_registry(tmp_path)
    claim_path = tmp_path / "registry/claims/central_bank_claims.jsonl"
    claim_path.write_text(
        claim_path.read_text(encoding="utf-8") + json.dumps("not an object") + "\n",
        encoding="utf-8",
    )

    index = build_registry_index(tmp_path)
    view = build_audit_trace_view(tmp_path)

    assert ("claim", "CLAIM-CB-20260605-0001") in index
    assert not view.complete
    assert "registry/claims/central_bank_claims.jsonl row 2 must be object" in view.broken_edges


def test_write_audit_trace_view_outputs_json_and_markdown(tmp_path: Path):
    write_central_bank_mvp_registry(tmp_path)

    paths = write_audit_trace_view(tmp_path)
    payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")

    assert payload["complete"] is True
    assert payload["edge_count"] >= 12
    assert markdown.startswith("# RKE Audit Trace View")
