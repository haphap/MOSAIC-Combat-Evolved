from __future__ import annotations

import json
from pathlib import Path

from mosaic.rke import (
    build_dashboard_report,
    render_dashboard_markdown,
    write_dashboard_reports,
)


def test_dashboard_report_summarizes_completion_and_monitoring():
    report = build_dashboard_report(".")

    assert report["dashboard_id"] == "RKE-DASHBOARD-20260605"
    assert report["ready_for_broad_rollout"] is False
    assert report["completion"]["passed"] == 10
    assert report["completion"]["total"] == 12
    assert report["paper_trading"]["ready"] is True
    assert report["lockbox"]["result"] == "not_opened"
    assert report["lockbox"]["production_allowed"] is False
    assert report["validation_hardening"]["ablation_accepted"] is True
    assert report["validation_hardening"]["horizon_metric_failures"] == []
    assert report["sector_demo"]["demo_status"] == "sandbox"
    assert report["sector_demo"]["production_allowed"] is False
    assert report["sector_demo"]["recommendation_actionability"] == "monitor_only"
    assert report["audit_trace"]["agent_output_count"] == 1
    assert "manual" in " ".join(report["completion"]["blockers"])


def test_dashboard_markdown_renders_blockers():
    markdown = render_dashboard_markdown(build_dashboard_report("."))

    assert "# RKE Dashboard" in markdown
    assert "Broad rollout ready: false" in markdown
    assert "Validation ablations accepted: True" in markdown
    assert "Sector demo: sandbox" in markdown
    assert "manual" in markdown
    assert "license" in markdown


def test_dashboard_report_writer_outputs_json_and_markdown():
    # Reuse current repo registry by validating writer on the repository root.
    paths = write_dashboard_reports(".")
    payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")

    assert payload["completion"]["total"] == 12
    assert markdown.startswith("# RKE Dashboard")
