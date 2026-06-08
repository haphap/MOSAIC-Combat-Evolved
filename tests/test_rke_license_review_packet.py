from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_license_review_packet,
    render_license_review_packet_markdown,
    write_license_review_packet,
)


def _license_review_source_count(root: Path) -> int:
    path = root / "registry/compliance/tushare_license_review_template.jsonl"
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _jsonl_count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_pending_license_fixture(root: Path) -> None:
    source = {
        "license_status": "pending_review",
        "point_in_time_available": True,
        "publish_date": "2026-06-05",
        "source_hash": "sha256:test",
        "source_id": "SRC-PENDING-001",
        "source_type": "tushare_research_report",
        "title": "Pending fixture",
    }
    review = {
        "approved_for_derived_claim_storage": None,
        "approved_for_production_runtime": None,
        "review_date": "",
        "reviewer": "",
        "source_id": source["source_id"],
    }
    _write_jsonl(root / "registry/sources/tushare_research_reports.jsonl", [source])
    _write_jsonl(
        root / "registry/compliance/tushare_license_review_template.jsonl",
        [review],
    )


def test_license_review_packet_summarizes_current_manual_queue():
    packet = build_license_review_packet(".")
    source_count = _license_review_source_count(Path("."))

    assert packet.packet_id == "RKE-SOURCE-LICENSE-REVIEW-PACKET-20260606"
    assert packet.status == "manual_review_complete"
    assert not packet.manual_review_required
    assert packet.source_count == source_count
    assert packet.review_row_count == source_count
    assert packet.reviewed_sources == source_count
    assert packet.pending_sources == 0
    assert packet.approved_for_derived_claim_storage == source_count
    assert packet.approved_for_production_runtime == source_count
    assert packet.current_license_status_counts == {"pending_review": source_count}
    assert packet.policy_reason_counts == {}


def test_license_review_packet_reports_malformed_source_and_review_rows(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    source_count = _jsonl_count(source_path)
    review_count = _jsonl_count(review_path)
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + json.dumps("not an object") + "\n",
        encoding="utf-8",
    )
    review_path.write_text(
        review_path.read_text(encoding="utf-8") + json.dumps(["not", "an", "object"]) + "\n",
        encoding="utf-8",
    )

    packet = build_license_review_packet(tmp_path)
    paths = write_license_review_packet(tmp_path)
    payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))

    assert packet.status == "manual_review_blocked"
    assert packet.source_count == source_count + 1
    assert packet.review_row_count == review_count + 1
    assert packet.pending_sources == 0
    assert f"source registry row must be object at row(s): {source_count + 1}" in packet.blockers
    assert f"source license review row must be object at row(s): {review_count + 1}" in packet.blockers
    assert payload["blockers"] == list(packet.blockers)


def test_license_review_packet_reports_malformed_jsonl_rows(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    source_count = _jsonl_count(source_path)
    review_count = _jsonl_count(review_path)
    source_path.write_text(source_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8")
    review_path.write_text(review_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8")

    packet = build_license_review_packet(tmp_path)
    paths = write_license_review_packet(tmp_path)
    payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))

    assert packet.status == "manual_review_blocked"
    assert packet.source_count == source_count + 1
    assert packet.review_row_count == review_count + 1
    assert any(
        f"source registry row {source_count + 1} must contain valid JSON" in blocker
        for blocker in packet.blockers
    )
    assert any(
        f"source license review row {review_count + 1} must contain valid JSON" in blocker
        for blocker in packet.blockers
    )
    assert payload["blockers"] == list(packet.blockers)


def test_license_review_packet_records_missing_manual_fields(tmp_path: Path):
    _write_pending_license_fixture(tmp_path)

    packet = build_license_review_packet(tmp_path)
    record = packet.records[0]

    assert packet.status == "manual_review_pending"
    assert packet.manual_review_required
    assert record.reviewed is False
    assert set(record.missing_review_fields) == set(packet.required_review_fields)
    assert record.allowed_for_sandbox is True
    assert record.allowed_for_production_runtime is False


def test_license_review_packet_markdown_renders_review_queue_summary():
    markdown = render_license_review_packet_markdown(build_license_review_packet("."))
    source_count = _license_review_source_count(Path("."))

    assert markdown.startswith("# RKE Source License Review Packet")
    assert "Status: manual_review_complete" in markdown
    assert "Pending sources: 0" in markdown
    assert f"Approved for production runtime: {source_count}" in markdown
    assert "Review Queue" in markdown


def test_license_review_packet_writer_outputs_json_and_markdown(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")

    paths = write_license_review_packet(tmp_path)
    payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")

    assert payload["source_count"] == _license_review_source_count(tmp_path)
    assert payload["manual_review_required"] is False
    assert payload["status"] == "manual_review_complete"
    assert markdown.startswith("# RKE Source License Review Packet")
