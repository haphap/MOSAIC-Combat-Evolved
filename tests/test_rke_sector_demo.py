from __future__ import annotations

import json
from pathlib import Path

import pytest

from mosaic.rke import (
    build_sector_semiconductor_demo,
    check_runtime_output,
    write_sector_semiconductor_demo_registry,
)


def test_sector_semiconductor_demo_is_source_grounded_and_sandbox_only():
    bundle = build_sector_semiconductor_demo()
    spans = {str(row["source_span_id"]): str(row["abstract"]) for row in bundle.source_rows}
    known_claim_ids = {claim.claim_id for claim in bundle.claims}
    known_hypothesis_ids = {hypothesis.hypothesis_id for hypothesis in bundle.hypotheses}

    for claim in bundle.claims:
        assert claim.verifier_status == "passed"
        assert claim.claim_text in spans[claim.source_span_id]
        assert all(len(variable) > 1 for variable in claim.cause_variables)
        assert all(len(variable) > 1 for variable in claim.target_variables)

    trade_risk_claim = next(
        claim for claim in bundle.claims if claim.claim_id == "CLAIM-SEMI-20260605-0003"
    )
    assert trade_risk_claim.target_variables == ("semiconductor_policy_substitution_alpha",)

    failures = bundle.rule_pack.gate_failures(
        data_matrix=bundle.data_matrix,
        known_claim_ids=known_claim_ids,
        known_hypothesis_ids=known_hypothesis_ids,
        production=True,
    )

    assert bundle.rule_pack.rule_pack_id == "sector.semiconductor.policy_substitution.v1"
    assert any("not allowed for validation" in failure for failure in failures)
    assert any("not allowed for production" in failure for failure in failures)
    assert "sell-side research license_status=pending_review" in (
        bundle.disagreement_cluster.production_blockers
    )
    assert bundle.disagreement_cluster.confidence_cap == 0.60


def test_sector_semiconductor_runtime_is_monitor_only_under_research_only_gate():
    bundle = build_sector_semiconductor_demo()
    result = check_runtime_output(
        bundle.runtime_output,
        verified_claim_ids={claim.claim_id for claim in bundle.claims},
        confidence_cap=0.60,
        research_only=True,
    )

    assert result.accepted
    assert bundle.runtime_output.recommendations[0].actionability == "monitor_only"
    assert bundle.runtime_output.recommendations[0].confidence == 0.50
    assert bundle.runtime_output.rule_aggregation_summary["research_only"] is True


def test_sector_semiconductor_demo_registry_writer(tmp_path: Path):
    source_dir = tmp_path / "registry/sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "tushare_research_reports.jsonl").write_text(
        Path("registry/sources/tushare_research_reports.jsonl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    outputs = write_sector_semiconductor_demo_registry(tmp_path)
    sources = [
        json.loads(line)
        for line in Path(outputs["sources"]).read_text(encoding="utf-8").splitlines()
    ]
    rule_pack = json.loads(Path(outputs["rule_pack"]).read_text(encoding="utf-8"))
    disagreement = json.loads(Path(outputs["disagreement"]).read_text(encoding="utf-8"))
    runtime = json.loads(Path(outputs["runtime_output"]).read_text(encoding="utf-8"))

    assert sources
    assert "abstract" not in sources[0]
    assert sources[0]["source_hash"].startswith("sha256:")
    assert sources[0]["claim_span_previews"]
    assert rule_pack["demo_status"] == "sandbox"
    assert rule_pack["production_allowed"] is False
    assert rule_pack["empirical_confidence_bin"] == "low"
    assert disagreement["cluster"]["cluster_id"] == "DISAGREE-SEMI-POLICY-SUB-20260605"
    assert runtime["agent_output_id"] == "OUT-SEMI-20260605-0001"


def test_sector_semiconductor_demo_rejects_malformed_source_rows(tmp_path: Path):
    source_dir = tmp_path / "registry/sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / "tushare_research_reports.jsonl"
    source_text = Path("registry/sources/tushare_research_reports.jsonl").read_text(encoding="utf-8")
    expected_row = len(source_text.splitlines()) + 1
    source_path.write_text(
        source_text + json.dumps("not an object") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=rf"semiconductor source row\(s\) must be object: {expected_row}",
    ):
        write_sector_semiconductor_demo_registry(tmp_path)


def test_sector_semiconductor_repo_registry_is_sandbox_only():
    rule_pack = json.loads(
        Path("registry/rule_packs/sector.semiconductor.policy_substitution.v1.json").read_text(
            encoding="utf-8"
        )
    )
    runtime = json.loads(
        Path("registry/runtime_outputs/sector.semiconductor.demo.20260605.json").read_text(
            encoding="utf-8"
        )
    )

    assert rule_pack["demo_status"] == "sandbox"
    assert rule_pack["production_allowed"] is False
    assert runtime["recommendations"][0]["actionability"] == "monitor_only"
