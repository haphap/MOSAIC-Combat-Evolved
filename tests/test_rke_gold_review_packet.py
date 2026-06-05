from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_gold_review_packet,
    render_gold_review_packet_markdown,
    write_gold_review_packet,
)


def test_gold_review_packet_summarizes_current_manual_queue():
    packet = build_gold_review_packet(".")

    assert packet.packet_id == "RKE-GOLD-REVIEW-PACKET-20260606"
    assert packet.status == "manual_review_pending"
    assert packet.manual_review_required
    assert packet.document_count == 50
    assert packet.review_row_count == 500
    assert packet.pending_review_rows == 500
    assert packet.candidate_span_ref_count > 0
    assert packet.risk_flag_counts["manual_review_required"] == 50
    assert packet.risk_flag_counts["license_pending"] == 50
    assert all(document.pending_claim_rows == 10 for document in packet.documents)


def test_gold_review_packet_uses_offsets_not_source_text_for_span_refs():
    packet = build_gold_review_packet(".")
    document = next(document for document in packet.documents if document.candidate_span_refs)
    span = document.candidate_span_refs[0]

    assert span.source_span_id == document.source_span_id
    assert span.start_char < span.end_char
    assert span.text_hash.startswith("sha256:")
    assert not hasattr(span, "text")


def test_gold_review_packet_markdown_renders_review_queue_summary():
    markdown = render_gold_review_packet_markdown(build_gold_review_packet("."))

    assert markdown.startswith("# RKE Gold Review Packet")
    assert "Status: manual_review_pending" in markdown
    assert "Pending review rows: 500" in markdown
    assert "Review Queue" in markdown


def test_gold_review_packet_writer_outputs_json_and_markdown(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")

    paths = write_gold_review_packet(tmp_path)
    payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")

    assert payload["document_count"] == 50
    assert payload["manual_review_required"] is True
    assert markdown.startswith("# RKE Gold Review Packet")
