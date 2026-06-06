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


def test_license_review_packet_summarizes_current_manual_queue():
    packet = build_license_review_packet(".")
    source_count = _license_review_source_count(Path("."))

    assert packet.packet_id == "RKE-SOURCE-LICENSE-REVIEW-PACKET-20260606"
    assert packet.status == "manual_review_pending"
    assert packet.manual_review_required
    assert packet.source_count == source_count
    assert packet.review_row_count == source_count
    assert packet.reviewed_sources == 0
    assert packet.pending_sources == source_count
    assert packet.approved_for_derived_claim_storage == 0
    assert packet.approved_for_production_runtime == 0
    assert packet.current_license_status_counts == {"pending_review": source_count}
    assert packet.policy_reason_counts[
        "pending_review source is sandbox-only until compliance approval"
    ] == source_count


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
    assert packet.pending_sources == source_count
    assert f"source registry row must be object at row(s): {source_count + 1}" in packet.blockers
    assert f"source license review row must be object at row(s): {review_count + 1}" in packet.blockers
    assert payload["blockers"] == list(packet.blockers)


def test_license_review_packet_records_missing_manual_fields():
    packet = build_license_review_packet(".")
    record = packet.records[0]

    assert record.reviewed is False
    assert set(record.missing_review_fields) == set(packet.required_review_fields)
    assert record.allowed_for_sandbox is True
    assert record.allowed_for_production_runtime is False


def test_license_review_packet_markdown_renders_review_queue_summary():
    markdown = render_license_review_packet_markdown(build_license_review_packet("."))
    source_count = _license_review_source_count(Path("."))

    assert markdown.startswith("# RKE Source License Review Packet")
    assert "Status: manual_review_pending" in markdown
    assert f"Pending sources: {source_count}" in markdown
    assert "Review Queue" in markdown


def test_license_review_packet_writer_outputs_json_and_markdown(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")

    paths = write_license_review_packet(tmp_path)
    payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")

    assert payload["source_count"] == _license_review_source_count(tmp_path)
    assert payload["manual_review_required"] is True
    assert markdown.startswith("# RKE Source License Review Packet")
