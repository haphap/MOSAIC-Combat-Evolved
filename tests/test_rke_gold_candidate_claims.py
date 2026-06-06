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


def test_gold_candidate_claims_report_malformed_rows_without_rewriting_review_template(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    candidates_path = tmp_path / "registry/sources/tushare_research_reports.gold_candidates.jsonl"
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    candidate_count = sum(1 for line in candidates_path.read_text(encoding="utf-8").splitlines() if line.strip())
    review_count = sum(1 for line in review_path.read_text(encoding="utf-8").splitlines() if line.strip())
    candidates_path.write_text(
        candidates_path.read_text(encoding="utf-8") + json.dumps("not an object") + "\n",
        encoding="utf-8",
    )
    review_path.write_text(
        review_path.read_text(encoding="utf-8") + json.dumps(["not", "an", "object"]) + "\n",
        encoding="utf-8",
    )
    original_review = review_path.read_text(encoding="utf-8")

    claims = build_gold_candidate_claims(tmp_path)
    merge_result = merge_candidate_claims_into_review_template(tmp_path, candidate_claims=claims)
    paths = write_gold_candidate_claims(tmp_path)
    summary = json.loads((tmp_path / paths["summary"]).read_text(encoding="utf-8"))

    assert len(claims) == review_count
    assert merge_result["applied"] is False
    assert merge_result["rows"] == review_count + 1
    assert f"gold-set review row must be object at row(s): {review_count + 1}" in merge_result["blockers"]
    assert review_path.read_text(encoding="utf-8") == original_review
    assert summary["candidate_claim_count"] == review_count
    assert f"gold candidate row must be object at row(s): {candidate_count + 1}" in summary["blockers"]
    assert f"gold-set review row must be object at row(s): {review_count + 1}" in summary["blockers"]


def test_gold_candidate_claims_report_malformed_jsonl_without_rewriting_review_template(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    candidates_path = tmp_path / "registry/sources/tushare_research_reports.gold_candidates.jsonl"
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    candidate_count = sum(1 for line in candidates_path.read_text(encoding="utf-8").splitlines() if line.strip())
    review_count = sum(1 for line in review_path.read_text(encoding="utf-8").splitlines() if line.strip())
    candidates_path.write_text(candidates_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8")
    review_path.write_text(review_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8")
    original_review = review_path.read_text(encoding="utf-8")

    claims = build_gold_candidate_claims(tmp_path)
    merge_result = merge_candidate_claims_into_review_template(tmp_path, candidate_claims=claims)
    paths = write_gold_candidate_claims(tmp_path)
    summary = json.loads((tmp_path / paths["summary"]).read_text(encoding="utf-8"))

    assert len(claims) == review_count
    assert merge_result["applied"] is False
    assert merge_result["rows"] == review_count + 1
    assert any(
        f"gold-set review row {review_count + 1} must contain valid JSON" in blocker
        for blocker in merge_result["blockers"]
    )
    assert review_path.read_text(encoding="utf-8") == original_review
    assert summary["candidate_claim_count"] == review_count
    assert any(
        f"gold candidate row {candidate_count + 1} must contain valid JSON" in blocker
        for blocker in summary["blockers"]
    )
    assert any(
        f"gold-set review row {review_count + 1} must contain valid JSON" in blocker
        for blocker in summary["blockers"]
    )


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
