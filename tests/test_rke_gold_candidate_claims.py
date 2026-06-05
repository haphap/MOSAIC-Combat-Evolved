from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_gold_candidate_claim_summary,
    build_gold_candidate_claims,
    merge_candidate_claims_into_review_template,
    write_gold_candidate_claims,
)


def test_gold_candidate_claims_cover_current_manual_queue():
    claims = build_gold_candidate_claims(".")
    summary = build_gold_candidate_claim_summary(".", candidate_claims=claims)

    assert len(claims) == 500
    assert summary.candidate_claim_count == 500
    assert summary.candidate_available_count == 500
    assert summary.missing_variable_mapping_count < 500
    assert {claim.verifier_status for claim in claims} == {"requires_review"}
    assert all(claim.claim_id.startswith("GOLD-SRC-TSRR-") for claim in claims)
    assert all(claim.source_text_hash.startswith("sha256:") for claim in claims)
    assert any(claim.cause_variables and claim.target_variables for claim in claims)


def test_gold_candidate_claims_merge_preserves_manual_fields(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["manual_claim_text"] = "manual label"
    rows[0]["claim_correct"] = True
    review_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    result = merge_candidate_claims_into_review_template(tmp_path)
    merged = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]

    assert result["rows_with_candidate_fields"] == 500
    assert result["manual_fields_preserved"] is True
    assert merged[0]["manual_claim_text"] == "manual label"
    assert merged[0]["claim_correct"] is True
    assert merged[0]["proposed_claim_text"]
    assert merged[0]["proposed_verifier_status"] == "requires_review"


def test_gold_candidate_claim_writer_outputs_claims_summary_and_review_fields(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")

    paths = write_gold_candidate_claims(tmp_path)
    claims = (tmp_path / paths["candidate_claims"]).read_text(encoding="utf-8").splitlines()
    summary = json.loads((tmp_path / paths["summary"]).read_text(encoding="utf-8"))
    review_row = json.loads(
        (tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )

    assert len(claims) == 500
    assert summary["candidate_claim_count"] == 500
    assert summary["review_rows_with_candidate_fields"] == 500
    assert summary["manual_fields_preserved"] is True
    assert review_row["proposed_claim_text"]
    assert review_row["manual_claim_text"] == ""
