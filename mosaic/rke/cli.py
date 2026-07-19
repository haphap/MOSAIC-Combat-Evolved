"""Command-line entry points for RKE registry operations."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .audit_viewer import build_audit_trace_view, write_audit_trace_view
from .agent_research_context import build_rke_agent_research_context
from .claim_vocabulary import (
    build_claim_variable_validation_report,
    write_claim_variable_validation_report,
)
from .claim_grounding_validation import (
    write_claim_grounding_validation_report,
)
from .completion_auditor import write_completion_audit
from .dashboard_reports import write_dashboard_reports
from .experiment_validation import (
    build_experiment_validation_report,
    write_experiment_validation_report,
)
from .gold_candidate_claims import (
    GOLD_CANDIDATES_PATH,
    select_gold_set_candidates_for_claim_review,
    write_gold_candidate_claims,
)
from .gold_review_packet import build_gold_review_packet, write_gold_review_packet
from .license_review_packet import (
    build_license_review_packet,
    write_license_review_packet,
)
from .license_policy_import import (
    DEFAULT_LICENSE_POLICY_IMPORT_PATH,
    SOURCE_LICENSE_REVIEWED_POLICY_PATH,
    build_source_license_policy_import,
    write_source_license_reviewed_policy_starter,
)
from .lockbox_review_import import apply_lockbox_review_import
from .manual_review_aids import manual_review_aid_paths, manual_review_field_contract
from .manual_review_import import (
    apply_gold_set_review_import,
    apply_source_license_review_import,
)
from .manual_review_batches import (
    GOLD_FULL_REVIEWED_IMPORT_PATH,
    GOLD_REVIEWED_IMPORT_PATH,
    backfill_gold_review_from_prior,
    build_manual_review_batch_status,
    write_gold_review_assist,
    write_gold_review_evidence,
    write_gold_review_starter,
    write_manual_review_batches,
)
from .operator_handoff import (
    LOCKBOX_REVIEWED_IMPORT_PATH,
    lockbox_upstream_review_blockers,
    write_lockbox_review_starter,
    write_operator_handoff,
)
from .operator_readiness import (
    build_operator_readiness_report,
    write_operator_readiness_report,
)
from .phase_minus1 import (
    load_jsonl,
    write_gold_set_candidates,
)
from .master_plan_coverage import (
    build_master_plan_coverage_report,
    write_master_plan_coverage_report,
)
from .monitoring_diagnostics import (
    build_production_monitor_diagnostics,
    write_production_monitor_diagnostics,
)
from .rollback_readiness import (
    build_rollback_readiness_report,
    write_rollback_readiness_report,
)
from .policy_doc_validation import (
    build_policy_doc_validation_report,
    write_policy_doc_validation_report,
)
from .prompt_asset_validation import (
    build_prompt_asset_validation_report,
    write_prompt_asset_validation_report,
)
from .promotion_gate import (
    build_production_promotion_gate_report,
    write_production_promotion_gate_report,
)
from .promotion_dry_run import (
    build_promotion_dry_run_report,
    write_promotion_dry_run_report,
)
from .private_registries import (
    export_private_registries,
    hydrate_private_registries,
    registries_preflight,
    resolve_report_intelligence_registry_dir,
)
from .rule_pack_validation import (
    build_rule_pack_validation_report,
    write_rule_pack_validation_report,
)
from .registry_manifest import (
    build_registry_manifest,
    validate_required_registry,
    validate_required_registry_content,
    write_registry_manifest,
)
from .report_intelligence import (
    ANALYTICAL_FOOTPRINT_NEGATIVE_EXAMPLE_APPROVAL_DRAFT_JSONL_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_APPROVAL_DRAFT_JSONL_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
    ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
    DEFAULT_MINERU_BACKEND,
    DEFAULT_VLLM_TIMEOUT_SECONDS,
    ReportIntelligenceConfig,
    _footprint_review_quality_gap_targets_from_summary,
    _gold_review_quality_gap_targets_from_summary,
    apply_analytical_footprint_review_import,
    build_analytical_footprint_negative_example_progress,
    build_local_macro_strategy_report_sources,
    export_macro_agent_research_priors,
    merge_report_intelligence_batch_outputs,
    prepare_analytical_footprint_negative_examples,
    prepare_analytical_footprint_review_import,
    write_analytical_footprint_negative_example_approved_import,
    write_analytical_footprint_negative_example_approval_draft,
    run_report_intelligence_refresh,
    write_analytical_footprint_review_approved_import,
    write_analytical_footprint_review_approval_draft,
    write_analytical_footprint_review_assist,
    write_analytical_footprint_review_evidence,
    write_report_intelligence_evolution_readiness_gate,
    write_report_intelligence_prompt_mutation_candidates,
)
from .review_progress import (
    ACTION_QUEUE_STATES,
    _manual_review_progress_report_payload,
    build_manual_review_action_queue,
    build_manual_review_progress_summary,
    build_manual_review_progress,
    write_manual_review_progress_report,
    write_manual_review_runbook,
)
from .review_gates import (
    summarize_gold_set_review,
    summarize_source_license_review,
    write_gold_set_review_summary,
    write_source_license_review_summary,
)
from .schema_validation import (
    build_schema_validation_report,
    write_schema_validation_report,
)
from .source_registry_validation import (
    build_source_registry_validation_report,
    write_source_registry_validation_report,
)
from .source_text_redaction import (
    build_source_text_redaction_report,
    write_source_text_redaction_report,
)
from .temp_paths import operator_command
from .tushare_reports import (
    P9_REPORT_INTELLIGENCE_CORPUS_PROFILE,
    refresh_tushare_research_report_registry,
)
from .validation_hardening import (
    build_central_bank_statistical_significance_report,
    build_central_bank_validation_hardening_report,
    write_statistical_significance_report,
    write_validation_hardening_report,
)
from .workflows import run_full_rke_refresh


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _print_json(payload: Any) -> None:
    print(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True))


def _read_cli_mapping_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _schema_status_quality_gap_targets(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    gold_summary = _read_cli_mapping_json(
        root_path / "registry/gold_sets/tushare_research_reports.review_summary.json"
    )
    footprint_summary = _read_cli_mapping_json(
        root_path
        / "registry/report_intelligence/analytical_footprint_review_summary.json"
    )
    return {
        key: value
        for key, value in {
            "gold_set": _gold_review_quality_gap_targets_from_summary(gold_summary),
            "footprint_review": _footprint_review_quality_gap_targets_from_summary(
                footprint_summary
            ),
        }.items()
        if value
    }


def _current_review_action_context(
    root: str | Path,
    review_kind: str,
) -> dict[str, Any]:
    try:
        report = build_manual_review_progress(root)
        action_queue = build_manual_review_action_queue(
            report,
            review_kinds=(review_kind,),
        )
    except Exception:
        return {}
    actions = action_queue.get("actions")
    if not isinstance(actions, Sequence) or not actions:
        return {}
    action = actions[0]
    if not isinstance(action, Mapping):
        return {}
    raw_commands = action.get("commands")
    commands = raw_commands if isinstance(raw_commands, Mapping) else {}
    key_map = {
        "assist": "write_assist",
        "evidence": "write_evidence",
        "dry_run": "dry_run_current_batch",
    }
    context: dict[str, Any] = {
        "commands": {
            output_key: str(commands[source_key])
            for source_key, output_key in key_map.items()
            if str(commands.get(source_key) or "").strip()
        }
    }
    for field in (
        "next_manual_action",
        "action_state",
        "can_run_now",
        "blocks_promotion",
        "operator_hint",
        "post_current_batch_action",
        "blocked_by_review_kinds",
        "manual_input_path",
        "promotion_input_path",
        "current_batch_path",
        "current_batch_pending_rows",
        "evidence_aligned",
    ):
        if field in action:
            context[field] = action[field]
    batch_overview = action.get("batch_overview")
    if isinstance(batch_overview, Mapping) and batch_overview:
        context["batch_overview"] = dict(batch_overview)
    after_dry_run_accepts = action.get("after_dry_run_accepts")
    if isinstance(after_dry_run_accepts, Mapping) and after_dry_run_accepts:
        context["after_dry_run_accepts"] = dict(after_dry_run_accepts)
    return context


def _current_review_action_context_parts(
    root: str | Path,
    review_kind: str,
) -> tuple[dict[str, str], dict[str, Any], dict[str, str]]:
    context = _current_review_action_context(root, review_kind)
    commands = context.get("commands")
    batch_overview = context.get("batch_overview")
    after_dry_run_accepts = context.get("after_dry_run_accepts")
    return (
        dict(commands) if isinstance(commands, Mapping) else {},
        dict(batch_overview) if isinstance(batch_overview, Mapping) else {},
        (
            dict(after_dry_run_accepts)
            if isinstance(after_dry_run_accepts, Mapping)
            else {}
        ),
    )


def _current_review_action_command_overrides(
    root: str | Path,
    review_kind: str,
) -> dict[str, str]:
    commands, _, _ = _current_review_action_context_parts(root, review_kind)
    return commands


def _current_review_action_public_context(
    root: str | Path,
    review_kind: str,
) -> dict[str, Any]:
    context = _current_review_action_context(root, review_kind)
    return {
        key: value
        for key, value in context.items()
        if key not in {"commands", "after_dry_run_accepts"}
        and value not in ("", None, [], {})
    }


def _merge_review_action_context(
    action: Mapping[str, Any],
    *,
    root: str | Path,
    review_kind: str,
) -> dict[str, Any]:
    merged = dict(action)
    context = _current_review_action_context(root, review_kind)
    context_commands = context.get("commands")
    if isinstance(context_commands, Mapping) and context_commands:
        merged["commands"] = {
            **dict(merged.get("commands") if isinstance(merged.get("commands"), Mapping) else {}),
            **dict(context_commands),
        }
    batch_overview = context.get("batch_overview")
    if isinstance(batch_overview, Mapping) and batch_overview:
        merged["batch_overview"] = dict(batch_overview)
    after_dry_run_accepts = context.get("after_dry_run_accepts")
    if isinstance(after_dry_run_accepts, Mapping) and after_dry_run_accepts:
        merged["after_dry_run_accepts"] = dict(after_dry_run_accepts)
    for key, value in _current_review_action_public_context(root, review_kind).items():
        merged[key] = value
    return merged


def _augment_evolution_readiness_manual_actions(
    result: Mapping[str, Any],
    *,
    root: str | Path,
) -> dict[str, Any]:
    actions = result.get("next_actions")
    if not isinstance(actions, Sequence) or isinstance(actions, str):
        return dict(result)
    augmented_actions: list[dict[str, Any]] = []
    for raw_action in actions:
        if not isinstance(raw_action, Mapping):
            continue
        action_id = str(raw_action.get("action_id") or "")
        if action_id == "complete_manual_forecast_gold_review":
            action = _merge_review_action_context(
                raw_action,
                root=root,
                review_kind="gold_set",
            )
        elif action_id == "complete_manual_analytical_footprint_review":
            action = _merge_review_action_context(
                raw_action,
                root=root,
                review_kind="footprint_review",
            )
        elif action_id == "clear_current_schema_and_audit_blockers":
            action = dict(raw_action)
            review_gate_actions = {
                "gold_set": _current_review_action_public_context(root, "gold_set"),
                "footprint_review": _current_review_action_public_context(
                    root,
                    "footprint_review",
                ),
            }
            action["review_gate_actions"] = {
                key: value for key, value in review_gate_actions.items() if value
            }
        else:
            action = dict(raw_action)
        augmented_actions.append(action)
    return {**dict(result), "next_actions": augmented_actions}


def _schema_status_next_actions(
    records: Sequence[Any],
    *,
    root: str | Path = ".",
) -> list[dict[str, Any]]:
    """Map known schema-status failures to public-safe operator commands."""
    failed_schema_paths = {
        str(getattr(record, "schema_path", "") or "")
        for record in records
        if getattr(record, "accepted", False) is not True
        or bool(getattr(record, "failures", ()))
    }
    quality_gaps = _schema_status_quality_gap_targets(root)
    (
        gold_current_commands,
        gold_current_batch_overview,
        gold_current_after_dry_run_accepts,
    ) = (
        _current_review_action_context_parts(root, "gold_set")
    )
    (
        footprint_current_commands,
        footprint_current_batch_overview,
        footprint_current_after_dry_run_accepts,
    ) = (
        _current_review_action_context_parts(root, "footprint_review")
    )
    actions: list[dict[str, Any]] = []

    def add_action(
        *,
        action_id: str,
        reason: str,
        commands: dict[str, str],
        notes: Sequence[str] = (),
        review_aids: Mapping[str, Any] | None = None,
        field_contract: Mapping[str, Any] | None = None,
        quality_gap_targets: Mapping[str, Any] | None = None,
        batch_overview: Mapping[str, Any] | None = None,
        after_dry_run_accepts: Mapping[str, str] | None = None,
        review_action_context: Mapping[str, Any] | None = None,
        review_gate_actions: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        if any(action["action_id"] == action_id for action in actions):
            return
        action = {
            "action_id": action_id,
            "reason": reason,
            "commands": commands,
            "notes": [str(note) for note in notes if str(note).strip()],
        }
        if review_aids:
            action["review_aids"] = dict(review_aids)
        if field_contract:
            action["field_contract"] = dict(field_contract)
        if quality_gap_targets:
            action["quality_gap_targets"] = dict(quality_gap_targets)
        if batch_overview:
            action["batch_overview"] = dict(batch_overview)
        if after_dry_run_accepts:
            action["after_dry_run_accepts"] = dict(after_dry_run_accepts)
        if review_action_context:
            action.update(dict(review_action_context))
        if review_gate_actions:
            gate_actions = {
                str(kind): dict(context)
                for kind, context in review_gate_actions.items()
                if context
            }
            if gate_actions:
                action["review_gate_actions"] = gate_actions
        actions.append(action)

    if "schemas/report_intelligence_gold_review_gate_rules" in failed_schema_paths:
        add_action(
            action_id="complete_manual_forecast_gold_review",
            reason=(
                "Gold-set review summary cannot pass until manual forecast "
                "claim review rows are complete and quality metrics pass."
            ),
            commands={
                "inspect": operator_command(
                    "mosaic-rke review-progress --root . --actions-only "
                    "--no-write --review-kind gold_set"
                ),
                "write_assist": operator_command(
                    "mosaic-rke write-gold-review-assist --root . --review-input "
                    f"{GOLD_REVIEWED_IMPORT_PATH}"
                ),
                "write_evidence": operator_command(
                    "mosaic-rke write-gold-review-evidence --root . --limit 50 "
                    f"--offset 0 --review-input {GOLD_REVIEWED_IMPORT_PATH}"
                ),
                "refresh_source_candidates": operator_command(
                    "mosaic-rke fetch-tushare-reports --root . --p9-profile "
                    "--start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD> "
                    "--merge-existing-source"
                ),
                "expand_candidate_review_rows": operator_command(
                    "mosaic-rke gold-candidate-claims --root . "
                    "--refresh-candidates-from-source --ensure-candidate-review-rows"
                ),
                "prepare_expanded_batch": operator_command(
                    "mosaic-rke prepare-gold-review --root . "
                    "--gold-batch-size 50 --offset 0 --force "
                    "--reviewer <name> --review-date <YYYY-MM-DD>"
                ),
                "dry_run_current_batch": operator_command(
                    "mosaic-rke apply-gold-review --root . --input "
                    f"{GOLD_REVIEWED_IMPORT_PATH} --dry-run"
                ),
                "schema_after_review": operator_command(
                    "mosaic-rke schema-status --root . --failures-only --no-write"
                ),
            }
            | gold_current_commands,
            notes=(
                "Assist and evidence outputs are private review aids, not import files.",
                "If sample_size_documents is below threshold, refresh/merge private "
                "sources if needed, then run gold-candidate-claims with "
                "--refresh-candidates-from-source --ensure-candidate-review-rows "
                "to append missing candidate rows without overwriting existing "
                "manual review fields.",
                "Promotion uses the full reviewed import only after every gold-set batch is complete.",
            ),
            review_aids=manual_review_aid_paths("gold_set"),
            field_contract=manual_review_field_contract("gold_set"),
            quality_gap_targets=quality_gaps.get("gold_set"),
            batch_overview=gold_current_batch_overview,
            after_dry_run_accepts=gold_current_after_dry_run_accepts,
            review_action_context=_current_review_action_public_context(
                root, "gold_set"
            ),
        )

    if "schemas/report_intelligence_analytical_footprint_review_rules" in failed_schema_paths:
        add_action(
            action_id="complete_manual_analytical_footprint_review",
            reason=(
                "Analytical-footprint review summary cannot pass until the "
                "manual footprint review rows are completed, imported, and the "
                "quality metrics are available."
            ),
            commands={
                "inspect": operator_command(
                    "mosaic-rke review-progress --root . --actions-only "
                    "--no-write --review-kind footprint_review"
                ),
                "write_assist": operator_command(
                    "mosaic-rke write-footprint-review-assist --root . "
                    f"--review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
                ),
                "write_evidence": operator_command(
                    "mosaic-rke write-footprint-review-evidence --root . "
                    "--limit 50 --offset 0 --review-input "
                    f"{ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
                ),
                "dry_run_current_batch": operator_command(
                    "mosaic-rke apply-footprint-review --root . --input "
                    f"{ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH} --dry-run"
                ),
                "schema_after_review": operator_command(
                    "mosaic-rke schema-status --root . --failures-only --no-write"
                ),
            }
            | footprint_current_commands,
            notes=(
                "Assist and evidence outputs are private review aids, not import files.",
                "The full reviewed import is used only after all footprint batches are complete.",
            ),
            review_aids=manual_review_aid_paths("footprint_review"),
            field_contract=manual_review_field_contract("footprint_review"),
            quality_gap_targets=quality_gaps.get("footprint_review"),
            batch_overview=footprint_current_batch_overview,
            after_dry_run_accepts=footprint_current_after_dry_run_accepts,
            review_action_context=_current_review_action_public_context(
                root, "footprint_review"
            ),
        )

    if "schemas/report_intelligence_patch_v1_5_coverage_rules" in failed_schema_paths:
        add_action(
            action_id="clear_patch_v1_5_manual_review_coverage",
            reason=(
                "Patch v1.5 coverage remains blocked while Phase B gold-set "
                "review or Phase D footprint quality gates are incomplete."
            ),
            commands={
                "inspect_manual_queue": operator_command(
                    "mosaic-rke review-progress --root . --actions-only --no-write"
                ),
                "inspect_gold": operator_command(
                    "mosaic-rke review-progress --root . --actions-only "
                    "--no-write --review-kind gold_set"
                ),
                "inspect_footprint": operator_command(
                    "mosaic-rke review-progress --root . --actions-only "
                    "--no-write --review-kind footprint_review"
                ),
                "check_evolution": operator_command(
                    "mosaic-rke evolution-readiness --root . --no-write"
                ),
            },
            notes=(
                "Coverage status is downstream of manual review gates; do not "
                "edit coverage artifacts directly.",
            ),
            review_aids={
                "gold_set": manual_review_aid_paths("gold_set"),
                "footprint_review": manual_review_aid_paths("footprint_review"),
            },
            field_contract={
                "gold_set": manual_review_field_contract("gold_set"),
                "footprint_review": manual_review_field_contract("footprint_review"),
            },
            quality_gap_targets={
                key: value
                for key, value in quality_gaps.items()
                if key in {"gold_set", "footprint_review"}
            },
            review_gate_actions={
                "gold_set": _current_review_action_public_context(root, "gold_set"),
                "footprint_review": _current_review_action_public_context(
                    root, "footprint_review"
                ),
            },
        )

    return actions


def _master_plan_status_next_actions(root: str | Path, result: Any) -> list[dict[str, Any]]:
    """Map incomplete master-plan coverage to public-safe operator commands."""
    records = [
        *getattr(result, "records", ()),
        *getattr(result, "mvp_deliverable_records", ()),
        *getattr(result, "mvp_exit_records", ()),
        *getattr(result, "final_acceptance_records", ()),
    ]
    blockers = [
        str(getattr(record, "blocker", "") or "")
        for record in records
        if str(getattr(record, "status", "") or "") != "passed"
    ]
    if not blockers:
        return []

    actions: list[dict[str, Any]] = [
        {
            "action_id": "inspect_master_plan_schema_blockers",
            "reason": (
                "Master-plan coverage is incomplete; current known blockers are "
                "downstream of schema-status and manual review gates."
            ),
            "commands": {
                "master_plan_status": operator_command(
                    "mosaic-rke master-plan-status --root . --no-write"
                ),
                "schema_failures": operator_command(
                    "mosaic-rke schema-status --root . --failures-only --no-write"
                ),
                "manual_queue": operator_command(
                    "mosaic-rke review-progress --root . --actions-only --no-write"
                ),
                "evolution_readiness": operator_command(
                    "mosaic-rke evolution-readiness --root . --no-write"
                ),
            },
            "notes": [
                "Do not edit master-plan coverage artifacts directly.",
                "Clear the underlying schema/manual-review gates, then rerun master-plan-status.",
            ],
            "review_aids": {
                "gold_set": manual_review_aid_paths("gold_set"),
                "footprint_review": manual_review_aid_paths("footprint_review"),
            },
            "field_contract": {
                "gold_set": manual_review_field_contract("gold_set"),
                "footprint_review": manual_review_field_contract("footprint_review"),
            },
            "review_gate_actions": {
                key: value
                for key, value in {
                    "gold_set": _current_review_action_public_context(
                        root,
                        "gold_set",
                    ),
                    "footprint_review": _current_review_action_public_context(
                        root,
                        "footprint_review",
                    ),
                }.items()
                if value
            },
        }
    ]

    if any(
        "schema validation report accepted must be true" in blocker
        or "patch_v1_5_coverage_report" in blocker
        for blocker in blockers
    ):
        schema_report = build_schema_validation_report(root)
        failed_records = [
            record
            for record in schema_report.records
            if not record.accepted or record.failures
        ]
        for action in _schema_status_next_actions(failed_records):
            if not any(existing["action_id"] == action["action_id"] for existing in actions):
                actions.append(action)

    return actions


def _promotion_status_next_actions(
    result: Any,
    *,
    root: str | Path = ".",
) -> list[dict[str, Any]]:
    """Map failed promotion criteria to public-safe operator commands."""
    criteria_by_id = {
        str(getattr(criterion, "criterion_id", "") or ""): criterion
        for criterion in getattr(result, "criteria", ())
    }
    failed_criteria = {
        str(getattr(criterion, "criterion_id", "") or ""): str(
            getattr(criterion, "blocker", "") or ""
        )
        for criterion in getattr(result, "criteria", ())
        if getattr(criterion, "passed", False) is not True
    }
    actions: list[dict[str, Any]] = []

    def add_action(
        *,
        action_id: str,
        reason: str,
        commands: dict[str, str],
        notes: Sequence[str] = (),
        review_aids: Mapping[str, Any] | None = None,
        field_contract: Mapping[str, Any] | None = None,
        review_action_context: Mapping[str, Any] | None = None,
        review_gate_actions: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        if any(action["action_id"] == action_id for action in actions):
            return
        action = {
            "action_id": action_id,
            "reason": reason,
            "commands": commands,
            "notes": [str(note) for note in notes if str(note).strip()],
        }
        if review_aids:
            action["review_aids"] = dict(review_aids)
        if field_contract:
            action["field_contract"] = dict(field_contract)
        if review_action_context:
            action.update(dict(review_action_context))
        if review_gate_actions:
            gate_actions = {
                str(kind): dict(context)
                for kind, context in review_gate_actions.items()
                if context
            }
            if gate_actions:
                action["review_gate_actions"] = gate_actions
        actions.append(action)

    source_license_passed = (
        getattr(criteria_by_id.get("PG03"), "passed", False) is True
    )
    gold_current_commands = _current_review_action_command_overrides(root, "gold_set")
    if source_license_passed:
        promotion_dry_run_after_all_reviews = operator_command(
            "mosaic-rke promotion-dry-run --root . "
            f"--gold-input {GOLD_FULL_REVIEWED_IMPORT_PATH} "
            f"--footprint-input {ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH} "
            f"--lockbox-input {LOCKBOX_REVIEWED_IMPORT_PATH}"
        )
    else:
        promotion_dry_run_after_all_reviews = operator_command(
            "mosaic-rke build-license-review-import --root . "
            f"--policy {SOURCE_LICENSE_REVIEWED_POLICY_PATH} "
            f"--output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
            "mosaic-rke promotion-dry-run --root . "
            f"--gold-input {GOLD_FULL_REVIEWED_IMPORT_PATH} "
            f"--footprint-input {ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH} "
            f"--license-input {DEFAULT_LICENSE_POLICY_IMPORT_PATH} "
            f"--lockbox-input {LOCKBOX_REVIEWED_IMPORT_PATH}"
        )

    if "PG02" in failed_criteria:
        add_action(
            action_id="complete_manual_forecast_gold_review",
            reason=(
                "PG02 blocks staged production until the manual gold-set review "
                "passes and its summary metrics clear the configured thresholds."
            ),
            commands={
                "inspect": operator_command(
                    "mosaic-rke review-progress --root . --actions-only "
                    "--no-write --review-kind gold_set"
                ),
                "write_assist": operator_command(
                    "mosaic-rke write-gold-review-assist --root . "
                    f"--review-input {GOLD_REVIEWED_IMPORT_PATH}"
                ),
                "write_evidence": operator_command(
                    "mosaic-rke write-gold-review-evidence --root . --limit 50 "
                    f"--offset 0 --review-input {GOLD_REVIEWED_IMPORT_PATH}"
                ),
                "refresh_source_candidates": operator_command(
                    "mosaic-rke fetch-tushare-reports --root . --p9-profile "
                    "--start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD> "
                    "--merge-existing-source"
                ),
                "expand_candidate_review_rows": operator_command(
                    "mosaic-rke gold-candidate-claims --root . "
                    "--refresh-candidates-from-source --ensure-candidate-review-rows"
                ),
                "prepare_expanded_batch": operator_command(
                    "mosaic-rke prepare-gold-review --root . "
                    "--gold-batch-size 50 --offset 0 --force "
                    "--reviewer <name> --review-date <YYYY-MM-DD>"
                ),
                "dry_run_current_batch": operator_command(
                    f"mosaic-rke apply-gold-review --root . --input "
                    f"{GOLD_REVIEWED_IMPORT_PATH} --dry-run"
                ),
                "check_promotion_after_review": operator_command(
                    "mosaic-rke promotion-status --root . --no-write"
                ),
            }
            | gold_current_commands,
            notes=(
                "Evidence outputs are private review aids and do not fill the "
                "required human review fields.",
                "If document coverage is below threshold, append missing "
                "candidate rows with gold-candidate-claims "
                "--refresh-candidates-from-source --ensure-candidate-review-rows "
                "before preparing the next gold review batch.",
            ),
            review_aids=manual_review_aid_paths("gold_set"),
            field_contract=manual_review_field_contract("gold_set"),
            review_action_context=_current_review_action_public_context(
                root,
                "gold_set",
            ),
        )

    if "PG09" in failed_criteria:
        add_action(
            action_id="prepare_lockbox_after_upstream_manual_gates",
            reason=(
                "PG09 blocks final production until lockbox review passes; the "
                "lockbox must stay closed while upstream manual review gates are "
                "still pending."
            ),
            commands={
                "inspect_lockbox_dependencies": operator_command(
                    "mosaic-rke review-progress --root . --actions-only "
                    "--no-write --review-kind lockbox"
                ),
                "inspect_manual_queue": operator_command(
                    "mosaic-rke review-progress --root . --actions-only --no-write"
                ),
                "operator_readiness": operator_command(
                    "mosaic-rke operator-readiness --root . --no-write"
                ),
                "prepare_lockbox_when_ready": operator_command(
                    "mosaic-rke prepare-lockbox-review --root ."
                ),
                "dry_run_lockbox_when_ready": operator_command(
                    f"mosaic-rke apply-lockbox-review --root . --input "
                    f"{LOCKBOX_REVIEWED_IMPORT_PATH} --dry-run"
                ),
                "promotion_dry_run_after_all_reviews": (
                    promotion_dry_run_after_all_reviews
                ),
            },
            notes=(
                "Run prepare/dry-run lockbox commands only after review-progress "
                "shows gold-set, analytical-footprint, and source-license gates "
                "ready.",
                "Direct production remains forbidden until all PG01-PG10 criteria pass.",
            ),
            review_aids={
                "gold_set": manual_review_aid_paths("gold_set"),
                "footprint_review": manual_review_aid_paths("footprint_review"),
                "lockbox": manual_review_aid_paths("lockbox"),
            },
            field_contract={
                "gold_set": manual_review_field_contract("gold_set"),
                "footprint_review": manual_review_field_contract("footprint_review"),
                "lockbox": manual_review_field_contract("lockbox"),
            },
            review_gate_actions={
                "gold_set": _current_review_action_public_context(root, "gold_set"),
                "footprint_review": _current_review_action_public_context(
                    root,
                    "footprint_review",
                ),
                "lockbox": _current_review_action_public_context(root, "lockbox"),
            },
        )

    return actions


def _sampled_sequence(
    values: Sequence[Any], *, sample_size: int = 10
) -> dict[str, Any]:
    items = list(values)
    return {
        "count": len(items),
        "sample": items[:sample_size],
        "truncated": len(items) > sample_size,
    }


def _source_license_status_stdout(summary: Any) -> dict[str, Any]:
    payload = asdict(summary)
    missing = payload.pop("missing_review_source_ids", ())
    extra = payload.pop("extra_review_source_ids", ())
    payload["missing_review_source_ids"] = _sampled_sequence(missing)
    payload["extra_review_source_ids"] = _sampled_sequence(extra)
    payload["full_summary_path"] = (
        "registry/compliance/tushare_license_review_summary.json"
    )
    return payload


def _load_env_file(path: str | None) -> None:
    if not path:
        return
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError("python-dotenv is required to load --env-file") from exc
    load_dotenv(path, override=False)


def _split_repeated_csv(values: Sequence[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    out: list[str] = []
    for value in values:
        out.extend(item.strip() for item in value.split(",") if item.strip())
    return tuple(out)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mosaic-rke")
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh = subparsers.add_parser(
        "refresh", help="Regenerate local RKE registry artifacts."
    )
    refresh.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    refresh.add_argument(
        "--overwrite-review-templates",
        action="store_true",
        help="Regenerate gold-set and license review templates even when they exist.",
    )

    manifest = subparsers.add_parser("manifest", help="Write the registry manifest.")
    manifest.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    audit = subparsers.add_parser("audit", help="Recompute completion audit.")
    audit.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    audit_view = subparsers.add_parser(
        "audit-view",
        help="Write and print the central-bank source-to-output audit trace viewer.",
    )
    audit_view.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    master_plan_status = subparsers.add_parser(
        "master-plan-status",
        help="Write and print the master-plan coverage audit.",
    )
    master_plan_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    master_plan_status.add_argument(
        "--no-write",
        action="store_true",
        help="Do not rewrite audit or master-plan coverage artifacts.",
    )

    dashboard = subparsers.add_parser(
        "dashboard", help="Write dashboard JSON and Markdown reports."
    )
    dashboard.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    policy_doc_status = subparsers.add_parser(
        "policy-doc-status",
        help="Write and print the RKE policy documentation validation report.",
    )
    policy_doc_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    schema_status = subparsers.add_parser(
        "schema-status",
        help="Write and print the Phase 1 schema validation report.",
    )
    schema_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    schema_status.add_argument(
        "--failures-only",
        action="store_true",
        help="Print only schema records that failed validation.",
    )
    schema_status.add_argument(
        "--no-write",
        action="store_true",
        help="Do not rewrite schema validation report artifacts.",
    )

    rule_pack_status = subparsers.add_parser(
        "rule-pack-status",
        help="Write and print the rule-pack validation report.",
    )
    rule_pack_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    prompt_status = subparsers.add_parser(
        "prompt-status",
        help="Write and print the rendered prompt asset validation report.",
    )
    prompt_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    claim_status = subparsers.add_parser(
        "claim-status",
        help="Write and print the claim variable vocabulary validation report.",
    )
    claim_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    source_status = subparsers.add_parser(
        "source-status",
        help="Write and print the source registry validation report.",
    )
    source_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    source_text_status = subparsers.add_parser(
        "source-text-status",
        help="Write and print the Tushare source-text redaction audit report.",
    )
    source_text_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    validation_status = subparsers.add_parser(
        "validation-status",
        help="Write and print the validation-hardening and statistical-significance reports.",
    )
    validation_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    experiment_status = subparsers.add_parser(
        "experiment-status",
        help="Write and print the hardened experiment-governance validation report.",
    )
    experiment_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    monitoring_diagnostics = subparsers.add_parser(
        "monitoring-diagnostics",
        help="Write and print production-monitor diagnostic scenarios.",
    )
    monitoring_diagnostics.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    rollback_readiness = subparsers.add_parser(
        "rollback-readiness",
        help="Write and print soft/hard/compliance rollback readiness checks.",
    )
    rollback_readiness.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    promotion_status = subparsers.add_parser(
        "promotion-status",
        help="Write and print the production-promotion gate report.",
    )
    promotion_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    promotion_status.add_argument(
        "--no-write",
        action="store_true",
        help="Do not rewrite promotion gate artifacts; print the current check result only.",
    )

    promotion_dry_run = subparsers.add_parser(
        "promotion-dry-run",
        help="Simulate reviewed gold/footprint/license/lockbox inputs without mutating the registry.",
    )
    promotion_dry_run.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    promotion_dry_run.add_argument(
        "--gold-input", help="Reviewed gold-set JSONL input."
    )
    promotion_dry_run.add_argument(
        "--license-input", help="Reviewed source-license JSONL input."
    )
    promotion_dry_run.add_argument(
        "--footprint-input", help="Reviewed analytical-footprint JSONL input."
    )
    promotion_dry_run.add_argument(
        "--lockbox-input", help="Reviewed lockbox JSON input."
    )
    promotion_dry_run.add_argument(
        "--write-report",
        action="store_true",
        help="Write registry/promotion/rke_promotion_dry_run_report.json.",
    )

    gold_status = subparsers.add_parser(
        "gold-set-status",
        help="Write and print the manual gold-set review gate summary.",
    )
    gold_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    gold_packet = subparsers.add_parser(
        "gold-review-packet",
        help="Write and print the Phase -1 gold-set manual review packet summary.",
    )
    gold_packet.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    gold_candidate_claims = subparsers.add_parser(
        "gold-candidate-claims",
        help="Write and print deterministic source-bound candidate claims for gold-set review.",
    )
    gold_candidate_claims.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    gold_candidate_claims.add_argument(
        "--refresh-candidates-from-source",
        action="store_true",
        help=(
            "Rebuild registry/sources/tushare_research_reports.gold_candidates.jsonl "
            "from the local source JSONL before writing candidate claims. This is "
            "local-only and does not call Tushare."
        ),
    )
    gold_candidate_claims.add_argument(
        "--source-path",
        default="registry/sources/tushare_research_reports.jsonl",
        help=(
            "Local research-report source JSONL used with "
            "--refresh-candidates-from-source. Defaults to the Tushare source registry path."
        ),
    )
    gold_candidate_claims.add_argument(
        "--ensure-candidate-review-rows",
        action="store_true",
        help=(
            "Append blank review starter rows for gold candidates missing from "
            "the review template before merging candidate claims. Existing "
            "manual review fields are preserved."
        ),
    )

    license_status = subparsers.add_parser(
        "license-status",
        help="Write and print the source license review gate summary.",
    )
    license_status.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    license_packet = subparsers.add_parser(
        "license-review-packet",
        help="Write and print the source license manual review packet summary.",
    )
    license_packet.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    apply_gold_review = subparsers.add_parser(
        "apply-gold-review",
        help="Validate and apply a JSONL manual gold-set review import.",
    )
    apply_gold_review.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    apply_gold_review.add_argument(
        "--input", required=True, help="JSONL file containing reviewed gold-set rows."
    )
    apply_gold_review.add_argument(
        "--dry-run", action="store_true", help="Validate without changing review rows."
    )

    prepare_gold_review = subparsers.add_parser(
        "prepare-gold-review",
        help="Write a reviewer-editable gold-set JSONL starter without overwriting existing reviews.",
    )
    prepare_gold_review.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    prepare_gold_review.add_argument(
        "--output",
        help=(
            f"Reviewed gold-set output path. Defaults to {GOLD_REVIEWED_IMPORT_PATH}, "
            f"or {GOLD_FULL_REVIEWED_IMPORT_PATH} with --full."
        ),
    )
    prepare_gold_review.add_argument(
        "--full",
        action="store_true",
        help="Export all pending gold-set rows instead of the next batch.",
    )
    prepare_gold_review.add_argument(
        "--reviewed-failures",
        action="store_true",
        help=(
            "Export already reviewed gold-set rows with failed quality labels for "
            "targeted re-review. Cannot be combined with --full."
        ),
    )
    prepare_gold_review.add_argument(
        "--gold-batch-size",
        type=int,
        default=50,
        help="Rows for the next-batch starter when --full is not used. Defaults to 50.",
    )
    prepare_gold_review.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Pending-row offset when --full is not used. Use with --gold-batch-size for review batches.",
    )
    prepare_gold_review.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing reviewed gold-set starter.",
    )
    prepare_gold_review.add_argument(
        "--reviewer",
        default="",
        help="Optional reviewer name to prefill in each starter row.",
    )
    prepare_gold_review.add_argument(
        "--review-date",
        default="",
        help="Optional YYYY-MM-DD review date to prefill in each starter row.",
    )

    backfill_gold_review = subparsers.add_parser(
        "backfill-gold-review",
        help="Backfill a gold-set review scratch from existing human-reviewed rows.",
    )
    backfill_gold_review.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    backfill_gold_review.add_argument(
        "--input",
        default=GOLD_REVIEWED_IMPORT_PATH,
        help=f"Gold-set review scratch to backfill. Defaults to {GOLD_REVIEWED_IMPORT_PATH}.",
    )
    backfill_gold_review.add_argument(
        "--prior-reviewed",
        default="registry/gold_sets/tushare_research_reports.review_template.jsonl",
        help="Existing human-reviewed gold-set JSONL to copy manual fields from.",
    )
    backfill_gold_review.add_argument(
        "--output",
        help="Optional output JSONL. Defaults to overwriting --input when --write is set.",
    )
    backfill_gold_review.add_argument(
        "--write",
        action="store_true",
        help="Write the backfilled scratch. Omit for dry-run.",
    )

    write_gold_review_evidence = subparsers.add_parser(
        "write-gold-review-evidence",
        help="Write private gold-set evidence snippets and draft review suggestions.",
    )
    write_gold_review_evidence.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    write_gold_review_evidence.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum pending rows to include. Defaults to 50.",
    )
    write_gold_review_evidence.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Pending-row offset after priority sorting. Use with --limit for review batches.",
    )
    write_gold_review_evidence.add_argument(
        "--review-input",
        help=(
            "Optional reviewed JSONL scratch file. When set, evidence rows follow "
            "this input order and are matched back to the full gold review template."
        ),
    )

    write_gold_review_assist = subparsers.add_parser(
        "write-gold-review-assist",
        help="Write private gold-set assist rows and workbook for the current review input.",
    )
    write_gold_review_assist.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    write_gold_review_assist.add_argument(
        "--review-input",
        help=(
            "Optional reviewed JSONL scratch file. When set, assist rows follow "
            "this input order and are matched back to the full gold review template."
        ),
    )

    apply_license_review = subparsers.add_parser(
        "apply-license-review",
        help="Validate and apply a JSONL source-license review import.",
    )
    apply_license_review.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    apply_license_review.add_argument(
        "--input", required=True, help="JSONL file containing source license decisions."
    )
    apply_license_review.add_argument(
        "--dry-run", action="store_true", help="Validate without changing review rows."
    )

    build_license_import = subparsers.add_parser(
        "build-license-review-import",
        help="Expand a signed source-license policy JSON into an apply-license-review JSONL input.",
    )
    build_license_import.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    build_license_import.add_argument(
        "--policy",
        required=True,
        help="JSON policy file with reviewer/date, decisions, and filters.",
    )
    build_license_import.add_argument(
        "--output",
        default="registry/review_batches/source_license_policy_import.jsonl",
        help="Output JSONL path. Defaults to registry/review_batches/source_license_policy_import.jsonl.",
    )
    build_license_import.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report without writing output JSONL.",
    )

    prepare_license_policy = subparsers.add_parser(
        "prepare-license-policy-review",
        help="Write a reviewer-editable source-license policy starter without overwriting existing reviews.",
    )
    prepare_license_policy.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    prepare_license_policy.add_argument(
        "--output",
        default=SOURCE_LICENSE_REVIEWED_POLICY_PATH,
        help=f"Reviewed policy output path. Defaults to {SOURCE_LICENSE_REVIEWED_POLICY_PATH}.",
    )
    prepare_license_policy.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing reviewed policy starter.",
    )

    apply_lockbox_review = subparsers.add_parser(
        "apply-lockbox-review",
        help="Validate and apply a JSON lockbox review record.",
    )
    apply_lockbox_review.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    apply_lockbox_review.add_argument(
        "--input", required=True, help="JSON file containing one lockbox review record."
    )
    apply_lockbox_review.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without changing the lockbox record.",
    )
    apply_lockbox_review.add_argument(
        "--allow-pending-upstream",
        action="store_true",
        help=(
            "Allow validating or applying the lockbox review before gold-set, "
            "analytical-footprint, and source-license gates are ready."
        ),
    )

    prepare_lockbox_review = subparsers.add_parser(
        "prepare-lockbox-review",
        help="Write a reviewer-editable lockbox JSON starter without overwriting existing reviews.",
    )
    prepare_lockbox_review.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    prepare_lockbox_review.add_argument(
        "--output",
        default=LOCKBOX_REVIEWED_IMPORT_PATH,
        help=f"Reviewed lockbox output path. Defaults to {LOCKBOX_REVIEWED_IMPORT_PATH}.",
    )
    prepare_lockbox_review.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing reviewed lockbox starter.",
    )
    prepare_lockbox_review.add_argument(
        "--allow-pending-upstream",
        action="store_true",
        help=(
            "Allow writing the lockbox starter before gold-set, "
            "analytical-footprint, and source-license gates are ready."
        ),
    )

    review_batches = subparsers.add_parser(
        "review-batches",
        help="Write next-batch import templates for manual gold-set and source-license reviews.",
    )
    review_batches.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    review_batches.add_argument(
        "--gold-batch-size",
        type=int,
        default=50,
        help="Number of pending gold-set review rows to export. Defaults to 50.",
    )
    review_batches.add_argument(
        "--license-batch-size",
        type=int,
        default=50,
        help="Number of pending source-license review rows to export. Defaults to 50.",
    )

    operator_handoff = subparsers.add_parser(
        "operator-handoff",
        help="Write and print the remaining manual gate handoff package.",
    )
    operator_handoff.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )

    operator_readiness = subparsers.add_parser(
        "operator-readiness",
        help="Write and print operator handoff bundle integrity checks.",
    )
    operator_readiness.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    operator_readiness.add_argument(
        "--no-write",
        action="store_true",
        help="Do not rewrite operator handoff or readiness artifacts; print the current check result only.",
    )

    review_progress = subparsers.add_parser(
        "review-progress",
        help="Check reviewer-edited scratch files without mutating the working registry.",
    )
    review_progress.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    review_progress.add_argument(
        "--summary",
        action="store_true",
        help=(
            "Print a compact public-safe summary instead of the full gate and "
            "batch plan payload."
        ),
    )
    review_progress.add_argument(
        "--actions-only",
        action="store_true",
        help="Print only the next public-safe manual review action queue.",
    )
    review_progress.add_argument(
        "--no-write",
        action="store_true",
        help=(
            "Do not rewrite manual review progress or runbook artifacts; print "
            "the current in-memory check result only."
        ),
    )
    review_progress.add_argument(
        "--review-kind",
        action="append",
        choices=("gold_set", "footprint_review", "source_license", "lockbox"),
        help=(
            "Limit --summary or --actions-only output to one review kind. "
            "May be repeated."
        ),
    )
    review_progress.add_argument(
        "--action-state",
        action="append",
        choices=ACTION_QUEUE_STATES,
        help=(
            "Limit --actions-only output to one action_state. May be repeated."
        ),
    )

    fetch_reports = subparsers.add_parser(
        "fetch-tushare-reports",
        help="Fetch Tushare research reports and refresh dependent Phase -1 registry artifacts.",
    )
    fetch_reports.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    fetch_reports.add_argument(
        "--start-date", help="Inclusive YYYY-MM-DD query start date."
    )
    fetch_reports.add_argument(
        "--end-date", help="Inclusive YYYY-MM-DD query end date."
    )
    fetch_reports.add_argument(
        "--input-path",
        help=(
            "Local Tushare research_report CSV/JSONL to import instead of calling Tushare. "
            "When omitted, --start-date/--end-date and a query target are required."
        ),
    )
    fetch_reports.add_argument(
        "--stock-code",
        action="append",
        dest="stock_codes",
        help="Tushare stock code. May be repeated or comma-separated.",
    )
    fetch_reports.add_argument(
        "--industry-keyword",
        action="append",
        dest="industry_keywords",
        help="Tushare industry keyword. May be repeated or comma-separated.",
    )
    fetch_reports.add_argument(
        "--report-type",
        action="append",
        dest="report_types",
        help=(
            "Tushare report_type to query across the whole market by date window. "
            "May be repeated or comma-separated, e.g. 行业研报,个股研报."
        ),
    )
    fetch_reports.add_argument(
        "--p9-profile",
        action="store_true",
        help=(
            "Use the P9 Report Intelligence corpus profile: add stock, industry, "
            "strategy, macro, fixed-income, and financial-engineering report types "
            "to the private source query set and record P9 coverage targets in the manifest."
        ),
    )
    fetch_reports.add_argument(
        "--max-reports-per-query",
        type=int,
        default=6000,
        help="Local per-query cap after Tushare returns rows. Defaults to 6000.",
    )
    fetch_reports.add_argument(
        "--stock-query-batch-size",
        type=int,
        default=50,
        help="Number of stock codes to join in one Tushare ts_code query. Defaults to 50.",
    )
    fetch_reports.add_argument(
        "--date-chunk-days",
        type=int,
        help=(
            "Days per full-market report_type query window. Defaults to 31, or 7 "
            "when --p9-profile is set."
        ),
    )
    fetch_reports.add_argument(
        "--merge-existing-source",
        action="store_true",
        help=(
            "Merge fetched reports into the existing local research-report source "
            "instead of replacing it."
        ),
    )
    fetch_reports.add_argument(
        "--overwrite-review-templates",
        action="store_true",
        help="Regenerate gold-set and license review templates even when they contain manual values.",
    )
    fetch_reports.add_argument(
        "--source-only",
        action="store_true",
        help=(
            "Only refresh the private Tushare source registry and source manifest; "
            "skip review, gold-set, dashboard, and registry-derived outputs."
        ),
    )
    fetch_reports.add_argument(
        "--env-file",
        help="Optional .env file to load before initializing the Tushare client.",
    )

    local_macro_sources = subparsers.add_parser(
        "build-local-macro-report-sources",
        help="Build a private local source JSONL by recursively scanning macro strategy PDFs.",
    )
    local_macro_sources.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    local_macro_sources.add_argument(
        "--input-dir",
        required=True,
        help="Directory containing local macro strategy PDFs. All *.pdf files are scanned recursively.",
    )
    local_macro_sources.add_argument(
        "--output-path",
        default="registry/sources/local_macro_strategy_reports.jsonl",
        help="Private output JSONL path under the repo.",
    )
    local_macro_sources.add_argument(
        "--manifest-path",
        default="registry/sources/local_macro_strategy_reports.manifest.json",
        help="Private manifest JSON path under the repo.",
    )
    local_macro_sources.add_argument(
        "--replace",
        action="store_true",
        help=(
            "Replace the existing source registry with the current scan instead of "
            "preserving hydrated historical rows."
        ),
    )

    report_intelligence = subparsers.add_parser(
        "report-intelligence",
        help=(
            "Materialize Tushare report PDFs, convert with MinerU, and extract "
            "Report Intelligence Loop objects with local vLLM."
        ),
    )
    report_intelligence.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    report_intelligence.add_argument(
        "--env-file",
        help="Optional .env file to load before reading vLLM/OpenAI API keys.",
    )
    report_intelligence.add_argument(
        "--source-path",
        default="registry/sources/tushare_research_reports.jsonl",
        help="Source JSONL path. Defaults to registry/sources/tushare_research_reports.jsonl.",
    )
    report_intelligence.add_argument(
        "--cache-dir",
        default=".mosaic/rke/report_intelligence",
        help="Local PDF/Markdown cache directory. Defaults to .mosaic/rke/report_intelligence.",
    )
    report_intelligence.add_argument(
        "--registry-dir",
        help=(
            "Report Intelligence output registry directory. Defaults to "
            "MOSAIC_REGISTRY_DIR, MOSAIC_REGISTRIES_REPO/registry/report_intelligence, "
            "or registry/report_intelligence."
        ),
    )
    report_intelligence.add_argument(
        "--source-id",
        action="append",
        dest="source_ids",
        help="Source id to process. May be repeated or comma-separated.",
    )
    report_intelligence.add_argument(
        "--exclude-processed-registry-dir",
        action="append",
        dest="exclude_processed_registry_dirs",
        help=(
            "Registry output directory whose processing_status.jsonl marks "
            "already-processed source ids to skip. May be repeated or comma-separated."
        ),
    )
    report_intelligence.add_argument(
        "--require-cached-markdown",
        action="store_true",
        help=(
            "Only select source rows whose cache-dir markdown file already exists. "
            "Useful for LLM-only incremental batches."
        ),
    )
    report_intelligence.add_argument(
        "--limit",
        type=int,
        help="Maximum selected source rows to process.",
    )
    report_intelligence.add_argument(
        "--min-publish-date",
        help="Only process reports with publish_date >= this YYYY-MM-DD date.",
    )
    report_intelligence.add_argument(
        "--max-publish-date",
        help="Only process reports with publish_date <= this YYYY-MM-DD date.",
    )
    report_intelligence.add_argument(
        "--selection-order",
        choices=("latest", "oldest", "stratified"),
        default="latest",
        help=(
            "Order source selection before applying --limit. Use stratified for "
            "P9 coverage sampling across report type, time, institution, sector, "
            "and stock-code buckets. Defaults to latest."
        ),
    )
    report_intelligence.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download/re-convert existing local artifacts.",
    )
    report_intelligence.add_argument(
        "--skip-download",
        action="store_true",
        help="Do not download PDFs; use existing local cache only.",
    )
    report_intelligence.add_argument(
        "--skip-convert",
        action="store_true",
        help="Do not run MinerU; use existing Markdown cache only.",
    )
    report_intelligence.add_argument(
        "--skip-llm",
        action="store_true",
        help="Do not call local vLLM; only materialize PDF/Markdown status.",
    )
    report_intelligence.add_argument(
        "--refresh-derived-only",
        action="store_true",
        help=(
            "Recompute derived report-intelligence artifacts from existing "
            "registry extraction outputs without downloading, converting, or "
            "calling local vLLM."
        ),
    )
    report_intelligence.add_argument(
        "--download-timeout-seconds",
        type=int,
        default=60,
        help="PDF download timeout in seconds. Defaults to 60.",
    )
    report_intelligence.add_argument(
        "--mineru-command",
        default="mineru",
        help="MinerU command. Defaults to mineru.",
    )
    report_intelligence.add_argument(
        "--mineru-backend",
        default=DEFAULT_MINERU_BACKEND,
        choices=(
            "hybrid-auto-engine",
            "vlm-auto-engine",
            "pipeline",
            "vlm-http-client",
            "hybrid-http-client",
        ),
        help=f"MinerU backend. Defaults to {DEFAULT_MINERU_BACKEND}.",
    )
    report_intelligence.add_argument(
        "--mineru-server-url",
        help="MinerU VLM/hybrid HTTP backend server URL, passed as -u/--url.",
    )
    report_intelligence.add_argument(
        "--mineru-args-template",
        default="-p {pdf} -o {output_dir} -b {backend} -m auto",
        help=(
            "MinerU args template. Supports {pdf}, {output_dir}, and {backend}. "
            "Defaults to '-p {pdf} -o {output_dir} -b {backend} -m auto'."
        ),
    )
    report_intelligence.add_argument(
        "--mineru-batch-size",
        type=int,
        default=4,
        help="PDF files per MinerU directory batch. Defaults to 4.",
    )
    report_intelligence.add_argument(
        "--mineru-timeout-seconds",
        type=int,
        default=900,
        help="MinerU timeout per batch in seconds. Defaults to 900.",
    )
    report_intelligence.add_argument(
        "--mineru-batch-max-bytes",
        type=int,
        default=5_000_000,
        help=(
            "Maximum total PDF bytes per MinerU batch; <=0 disables byte bucketing. "
            "Defaults to 5000000."
        ),
    )
    report_intelligence.add_argument(
        "--vllm-base-url",
        help=(
            "OpenAI-compatible vLLM base URL. Defaults to "
            "MOSAIC_RKE_VLLM_BASE_URL or http://127.0.0.1:8020/v1."
        ),
    )
    report_intelligence.add_argument(
        "--vllm-model",
        help=(
            "vLLM model id. Defaults to MOSAIC_RKE_VLLM_MODEL; when omitted, "
            "/models first result is used."
        ),
    )
    report_intelligence.add_argument(
        "--vllm-api-key-env",
        default="MOSAIC_VLLM_API_KEY,OPENAI_API_KEY",
        help=(
            "Comma-separated environment variable names for an OpenAI-compatible "
            "chat API key. Defaults to MOSAIC_VLLM_API_KEY,OPENAI_API_KEY."
        ),
    )
    report_intelligence.add_argument(
        "--vllm-timeout-seconds",
        type=int,
        default=DEFAULT_VLLM_TIMEOUT_SECONDS,
        help=(
            "OpenAI-compatible chat request timeout in seconds. "
            f"Defaults to {DEFAULT_VLLM_TIMEOUT_SECONDS}."
        ),
    )
    report_intelligence.add_argument(
        "--max-llm-output-tokens",
        type=int,
        default=4096,
        help="Maximum output tokens per LLM extraction chunk. Defaults to 4096.",
    )
    report_intelligence.add_argument(
        "--qlib-etf-dir",
        default="~/.qlib/qlib_data/cn_etf",
        help="Local qlib ETF data directory for proxy outcome labels.",
    )
    report_intelligence.add_argument(
        "--qlib-stock-dir",
        default="~/.qlib/qlib_data/cn_data",
        help="Local qlib stock data directory for stock proxy outcome labels.",
    )
    report_intelligence.add_argument(
        "--scorecard-db-path",
        default=None,
        help=(
            "Optional existing scorecard SQLite DB path for PIT macro_series "
            "direct outcome labels. Defaults to MOSAIC_DATA_DIR/scorecard.db "
            "or ./data/scorecard.db."
        ),
    )
    report_intelligence.add_argument(
        "--chunk-chars",
        type=int,
        default=60000,
        help="Characters per Markdown chunk sent to vLLM. Defaults to 60000.",
    )
    report_intelligence.add_argument(
        "--max-chunks",
        type=int,
        default=8,
        help="Maximum Markdown chunks per report. Defaults to 8.",
    )
    report_intelligence.add_argument(
        "--progress-jsonl",
        action="store_true",
        help=(
            "Emit redacted progress JSON lines to stderr for long PDF/LLM runs."
        ),
    )

    export_macro_priors = subparsers.add_parser(
        "export-macro-agent-priors",
        help="Export redacted shadow macro agent research priors for downstream agents.",
    )
    export_macro_priors.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    export_macro_priors.add_argument(
        "--registry-dir",
        help=(
            "Report Intelligence registry directory. Defaults to the shared private "
            "registry resolver."
        ),
    )
    export_macro_priors.add_argument(
        "--as-of-date",
        default="",
        help="Only include priors with as_of_date <= this YYYY-MM-DD date.",
    )
    export_macro_priors.add_argument(
        "--agent-id",
        default="",
        help="Optional macro agent id such as macro.central_bank.",
    )
    export_macro_priors.add_argument(
        "--no-source-prose",
        action="store_true",
        help="Drop any row that fails the public-safe no-source-prose guard.",
    )

    export_agent_context = subparsers.add_parser(
        "export-rke-agent-context",
        help="Export redacted ranked RKE research context for one downstream agent.",
    )
    export_agent_context.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    export_agent_context.add_argument(
        "--registry-dir",
        help=(
            "Report Intelligence registry directory. Defaults to the shared private "
            "registry resolver."
        ),
    )
    export_agent_context.add_argument(
        "--agent-id",
        required=True,
        help=(
            "Agent id such as macro.us_financial_conditions, "
            "sector.semiconductor, munger, or cio; tombstoned Macro ids are "
            "read-only legacy audit inputs."
        ),
    )
    export_agent_context.add_argument(
        "--as-of-date",
        default="",
        help="Only include context available on or before this YYYY-MM-DD date.",
    )
    export_agent_context.add_argument(
        "--layer",
        default="",
        help="Optional agent layer for TS-style ids, e.g. macro or superinvestor.",
    )
    export_agent_context.add_argument(
        "--ticker",
        default="",
        help="Optional stock ticker filter.",
    )
    export_agent_context.add_argument(
        "--sector",
        default="",
        help="Optional sector filter.",
    )
    export_agent_context.add_argument(
        "--max-items",
        type=int,
        default=12,
        help="Maximum ranked context items to return. Defaults to 12.",
    )

    macro_series_backfill = subparsers.add_parser(
        "macro-series-backfill",
        help="Backfill scorecard macro_series from existing macro dataflow adapters.",
    )
    macro_series_backfill.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    macro_series_backfill.add_argument(
        "--start-date",
        required=True,
        help="Inclusive start date (YYYY-MM-DD).",
    )
    macro_series_backfill.add_argument(
        "--end-date",
        required=True,
        help="Inclusive end date (YYYY-MM-DD).",
    )
    macro_series_backfill.add_argument(
        "--series-id",
        action="append",
        dest="series_ids",
        default=[],
        help=(
            "Macro series id to backfill, repeatable or comma-separated. "
            "Defaults to all supported series."
        ),
    )
    macro_series_backfill.add_argument(
        "--scorecard-db-path",
        default=None,
        help="Optional scorecard SQLite DB path. Defaults to the scorecard store default.",
    )

    evolution_gate = subparsers.add_parser(
        "report-intelligence-evolution-gate",
        help=(
            "Rebuild only report-intelligence evolution gate artifacts from "
            "existing registry evidence."
        ),
    )
    evolution_gate.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    evolution_gate.add_argument(
        "--run-id",
        default="RIR-PUBLIC-EVOLUTION-GATE",
        help="Run id to stamp on the rebuilt evolution gate.",
    )
    evolution_gate.add_argument(
        "--registry-dir",
        help="Report Intelligence registry directory. Defaults to the shared resolver.",
    )
    evolution_gate.add_argument(
        "--refresh-prompt-mutations",
        action="store_true",
        help="Also rebuild prompt mutation candidates after writing the gate.",
    )
    evolution_gate.add_argument(
        "--no-write",
        action="store_true",
        help="Do not rewrite evolution gate artifacts; print the current check result only.",
    )
    evolution_readiness = subparsers.add_parser(
        "evolution-readiness",
        help=(
            "Alias for report-intelligence-evolution-gate; rebuild evolution "
            "readiness gate artifacts from existing registry evidence."
        ),
    )
    evolution_readiness.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    evolution_readiness.add_argument(
        "--run-id",
        default="RIR-PUBLIC-EVOLUTION-GATE",
        help="Run id to stamp on the rebuilt evolution gate.",
    )
    evolution_readiness.add_argument(
        "--registry-dir",
        help="Report Intelligence registry directory. Defaults to the shared resolver.",
    )
    evolution_readiness.add_argument(
        "--refresh-prompt-mutations",
        action="store_true",
        help="Also rebuild prompt mutation candidates after writing the gate.",
    )
    evolution_readiness.add_argument(
        "--no-write",
        action="store_true",
        help="Do not rewrite evolution gate artifacts; print the current check result only.",
    )
    merge_report_batches = subparsers.add_parser(
        "merge-report-intelligence-batches",
        help=(
            "Merge multiple local report-intelligence batch output directories "
            "into the registry JSONL inputs."
        ),
    )
    merge_report_batches.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    merge_report_batches.add_argument(
        "--input-dir",
        action="append",
        required=True,
        help=(
            "Batch output directory containing report-intelligence JSONL files. "
            "May be repeated."
        ),
    )
    merge_report_batches.add_argument(
        "--registry-dir",
        help="Report Intelligence registry directory. Defaults to the shared resolver.",
    )
    merge_report_batches.add_argument(
        "--refresh-derived",
        action="store_true",
        help="After merging rows, recompute public derived report-intelligence artifacts.",
    )
    merge_report_batches.add_argument(
        "--replace",
        action="store_true",
        help=(
            "Replace registry JSONL inputs from the supplied batches instead of "
            "preserving existing registry rows first."
        ),
    )
    merge_report_batches.add_argument(
        "--replace-source-ids",
        action="store_true",
        help=(
            "When preserving existing registry rows, remove rows for source_ids "
            "present in the supplied batches before appending the batch rows."
        ),
    )
    registries_preflight_parser = subparsers.add_parser(
        "registries-preflight",
        help="Check the resolved private MOSAIC-Registries checkout.",
    )
    registries_preflight_parser.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    registries_preflight_parser.add_argument(
        "--registry-dir",
        help="Report Intelligence registry directory. Defaults to the shared resolver.",
    )
    export_private_registries_parser = subparsers.add_parser(
        "export-private-registries",
        help="Export gitignored private registry JSON/JSONL files to MOSAIC-Registries.",
    )
    export_private_registries_parser.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    export_private_registries_parser.add_argument(
        "--output-dir",
        required=True,
        help="Output MOSAIC-Registries checkout directory.",
    )
    export_private_registries_parser.add_argument(
        "--registry-dir",
        help="Source Report Intelligence registry directory. Defaults to the shared resolver.",
    )
    hydrate_private_registries_parser = subparsers.add_parser(
        "hydrate-private-registries",
        help="Restore a validated MOSAIC-Registries snapshot into local ignored staging.",
    )
    hydrate_private_registries_parser.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    hydrate_private_registries_parser.add_argument(
        "--source-dir",
        help="MOSAIC-Registries checkout. Defaults to MOSAIC_REGISTRIES_REPO.",
    )

    apply_footprint_review = subparsers.add_parser(
        "apply-footprint-review",
        help="Validate and apply an analytical-footprint manual review JSONL import.",
    )
    apply_footprint_review.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    apply_footprint_review.add_argument(
        "--input",
        required=True,
        help="JSONL file containing analytical-footprint review decisions.",
    )
    apply_footprint_review.add_argument(
        "--dry-run", action="store_true", help="Validate without mutating the registry."
    )

    prepare_footprint_review = subparsers.add_parser(
        "prepare-footprint-review",
        help="Prepare a gitignored analytical-footprint review import scaffold.",
    )
    prepare_footprint_review.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    prepare_footprint_review.add_argument(
        "--output",
        help=(
            "Output JSONL import scaffold. Defaults to the full reviewed path, "
            "or the batch reviewed path when --limit is set."
        ),
    )
    prepare_footprint_review.add_argument(
        "--reviewer",
        default="",
        help="Optional reviewer name to prefill in each scaffold row.",
    )
    prepare_footprint_review.add_argument(
        "--review-date",
        default="",
        help="Optional YYYY-MM-DD review date to prefill in each scaffold row.",
    )
    prepare_footprint_review.add_argument(
        "--limit",
        type=int,
        help="Maximum rows to scaffold. Omit for all rows.",
    )
    prepare_footprint_review.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Review-row offset before applying --limit. Defaults to 0.",
    )
    prepare_footprint_review.add_argument(
        "--priority",
        action="store_true",
        help=(
            "Select pending rows by analytical-footprint review priority before "
            "applying --offset/--limit."
        ),
    )
    prepare_footprint_review.add_argument(
        "--quality-gap-only",
        action="store_true",
        help=(
            "Select completed analytical-footprint review rows with at least one "
            "failed quality-gate field for re-review."
        ),
    )
    prepare_footprint_review.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing output scaffold.",
    )

    prepare_footprint_negative_examples = subparsers.add_parser(
        "prepare-footprint-negative-examples",
        help=(
            "Prepare a gitignored analytical-footprint negative-example recall "
            "scaffold for human review."
        ),
    )
    prepare_footprint_negative_examples.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    prepare_footprint_negative_examples.add_argument(
        "--output",
        help=(
            "Output JSONL scaffold. Defaults to the private analytical footprint "
            "negative examples path."
        ),
    )
    prepare_footprint_negative_examples.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Maximum rows to scaffold. Defaults to 200.",
    )
    prepare_footprint_negative_examples.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Candidate-row offset before applying --limit. Defaults to 0.",
    )
    prepare_footprint_negative_examples.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing output scaffold.",
    )

    footprint_negative_progress = subparsers.add_parser(
        "footprint-negative-progress",
        help=(
            "Summarize private analytical-footprint negative-example recall "
            "review progress."
        ),
    )
    footprint_negative_progress.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    footprint_negative_progress.add_argument(
        "--input",
        help=(
            "Input JSONL file. Defaults to the private analytical footprint "
            "negative examples path."
        ),
    )
    footprint_negative_progress.add_argument(
        "--minimum-sample-target",
        type=int,
        default=200,
        help="Minimum human negative-example rows required. Defaults to 200.",
    )
    footprint_negative_progress.add_argument(
        "--expected-positive-minimum-target",
        type=int,
        default=50,
        help="Minimum expected-positive human examples required. Defaults to 50.",
    )

    write_footprint_negative_approval_draft = subparsers.add_parser(
        "write-footprint-negative-approval-draft",
        help=(
            "Write a private machine-suggestion draft for human approval of "
            "analytical-footprint negative-example recall rows."
        ),
    )
    write_footprint_negative_approval_draft.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    write_footprint_negative_approval_draft.add_argument(
        "--input",
        help=(
            "Negative-example JSONL input to draft from. Defaults to the private "
            "analytical footprint negative examples path."
        ),
    )
    write_footprint_negative_approval_draft.add_argument(
        "--expected-positive-minimum-target",
        type=int,
        default=50,
        help="Minimum expected-positive examples to propose. Defaults to 50.",
    )

    approve_footprint_negative_draft = subparsers.add_parser(
        "approve-footprint-negative-draft",
        help=(
            "Convert a private analytical-footprint negative-example approval "
            "draft into the formal negative-example recall input after human approval."
        ),
    )
    approve_footprint_negative_draft.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    approve_footprint_negative_draft.add_argument(
        "--approval-draft",
        default=ANALYTICAL_FOOTPRINT_NEGATIVE_EXAMPLE_APPROVAL_DRAFT_JSONL_PATH,
        help="Negative-example approval draft JSONL to convert.",
    )
    approve_footprint_negative_draft.add_argument(
        "--output",
        help=(
            "Formal negative-example JSONL output. Defaults to the private "
            "analytical footprint negative examples path."
        ),
    )
    approve_footprint_negative_draft.add_argument(
        "--reviewer",
        required=True,
        help="Human reviewer identifier to write into approved rows.",
    )
    approve_footprint_negative_draft.add_argument(
        "--review-date",
        required=True,
        help="Human review date in YYYY-MM-DD format.",
    )
    approve_footprint_negative_draft.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing formal negative-example input output.",
    )

    write_footprint_review_assist = subparsers.add_parser(
        "write-footprint-review-assist",
        help="Write private analytical-footprint review assist JSONL and workbook files.",
    )
    write_footprint_review_assist.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    write_footprint_review_assist.add_argument(
        "--review-input",
        help=(
            "Optional reviewed JSONL scratch file. When set, assist rows follow "
            "this input order and are matched back to the full footprint review template."
        ),
    )

    write_footprint_review_evidence = subparsers.add_parser(
        "write-footprint-review-evidence",
        help=(
            "Write private analytical-footprint evidence snippets and draft "
            "review suggestions."
        ),
    )
    write_footprint_review_evidence.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    write_footprint_review_evidence.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum pending rows to include. Defaults to 25.",
    )
    write_footprint_review_evidence.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Pending-row offset after priority sorting. Use with --limit for review batches.",
    )
    write_footprint_review_evidence.add_argument(
        "--review-input",
        help=(
            "Optional reviewed JSONL scratch file. When set, evidence rows follow "
            "this input order and are matched back to the full footprint review template."
        ),
    )

    write_footprint_review_approval_draft = subparsers.add_parser(
        "write-footprint-review-approval-draft",
        help=(
            "Write a private machine-suggestion draft for human approval of the "
            "current analytical-footprint review batch."
        ),
    )
    write_footprint_review_approval_draft.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    write_footprint_review_approval_draft.add_argument(
        "--review-input",
        default=ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
        help=(
            "Review JSONL input to align suggestions with. Defaults to the "
            "current footprint review batch."
        ),
    )

    approve_footprint_review_draft = subparsers.add_parser(
        "approve-footprint-review-draft",
        help=(
            "Convert a private analytical-footprint approval draft into a formal "
            "review import after human approval."
        ),
    )
    approve_footprint_review_draft.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    approve_footprint_review_draft.add_argument(
        "--approval-draft",
        default=ANALYTICAL_FOOTPRINT_REVIEW_APPROVAL_DRAFT_JSONL_PATH,
        help="Approval draft JSONL to convert.",
    )
    approve_footprint_review_draft.add_argument(
        "--output",
        default=ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
        help="Formal review import JSONL output.",
    )
    approve_footprint_review_draft.add_argument(
        "--reviewer",
        required=True,
        help="Human reviewer identifier to write into approved rows.",
    )
    approve_footprint_review_draft.add_argument(
        "--review-date",
        required=True,
        help="Human review date in YYYY-MM-DD format.",
    )
    approve_footprint_review_draft.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing formal review import output.",
    )

    validate = subparsers.add_parser(
        "validate-required", help="Validate required registry files."
    )
    validate.add_argument(
        "--root", default=".", help="Repository root. Defaults to current directory."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root)

    if args.command == "refresh":
        result = run_full_rke_refresh(
            root,
            preserve_review_templates=not args.overwrite_review_templates,
        )
        _print_json(asdict(result))
        return 0 if result.manifest_valid else 2
    if args.command == "manifest":
        result = write_registry_manifest(root)
        _print_json(result)
        return 0 if result["valid"] else 2
    if args.command == "audit":
        result = write_completion_audit(root)
        _print_json(result)
        return 0
    if args.command == "audit-view":
        paths = write_audit_trace_view(root)
        view = build_audit_trace_view(root)
        _print_json(
            {
                "paths": paths,
                "complete": view.complete,
                "node_count": view.node_count,
                "edge_count": view.edge_count,
                "missing_references": view.missing_references,
                "broken_edges": view.broken_edges,
            }
        )
        return 0 if view.complete else 2
    if args.command == "master-plan-status":
        if not args.no_write:
            write_audit_trace_view(root)
            write_completion_audit(root)
            write_master_plan_coverage_report(root)
        result = build_master_plan_coverage_report(root)
        _print_json(
            {
                **asdict(result),
                "next_actions": _master_plan_status_next_actions(root, result),
            }
        )
        return 0 if result.coverage_complete else 2
    if args.command == "dashboard":
        result = write_dashboard_reports(root)
        _print_json(result)
        return 0
    if args.command == "policy-doc-status":
        write_policy_doc_validation_report(root)
        result = build_policy_doc_validation_report(root)
        _print_json(asdict(result))
        return 0 if result.accepted else 2
    if args.command == "schema-status":
        if not args.no_write:
            write_schema_validation_report(root)
            write_rule_pack_validation_report(root)
        result = build_schema_validation_report(root)
        records = list(result.records)
        if args.failures_only:
            records = [
                record
                for record in records
                if not record.accepted or record.failures
            ]
        _print_json(
            {
                "accepted": result.accepted,
                "failure_count": result.failure_count,
                "next_actions": _schema_status_next_actions(records, root=root),
                "record_count": len(result.records),
                "reported_record_count": len(records),
                "records": [asdict(record) for record in records],
            }
        )
        return 0 if result.accepted else 2
    if args.command == "rule-pack-status":
        write_rule_pack_validation_report(root)
        result = build_rule_pack_validation_report(root)
        _print_json(
            {
                "accepted": result.accepted,
                "failure_count": result.failure_count,
                "records": [asdict(record) for record in result.records],
            }
        )
        return 0 if result.accepted else 2
    if args.command == "prompt-status":
        write_prompt_asset_validation_report(root)
        result = build_prompt_asset_validation_report(root)
        _print_json(
            {
                "accepted": result.accepted,
                "failure_count": result.failure_count,
                "records": [asdict(record) for record in result.records],
            }
        )
        return 0 if result.accepted else 2
    if args.command == "claim-status":
        write_claim_grounding_validation_report(root)
        write_claim_variable_validation_report(root)
        result = build_claim_variable_validation_report(root)
        _print_json(
            {
                "accepted": result.accepted,
                "failure_count": result.failure_count,
                "records": [asdict(record) for record in result.records],
            }
        )
        return 0 if result.accepted else 2
    if args.command == "source-status":
        write_source_registry_validation_report(root)
        result = build_source_registry_validation_report(root)
        _print_json(asdict(result))
        return 0 if result.accepted_for_sandbox else 2
    if args.command == "source-text-status":
        write_source_text_redaction_report(root)
        result = build_source_text_redaction_report(root)
        _print_json(asdict(result))
        return 0 if result.accepted else 2
    if args.command == "validation-status":
        write_validation_hardening_report(root)
        write_statistical_significance_report(root)
        write_experiment_validation_report(root)
        hardening = build_central_bank_validation_hardening_report()
        significance = build_central_bank_statistical_significance_report()
        experiment_validation = build_experiment_validation_report(root)
        accepted = (
            not hardening["horizon_metric_failures"]
            and not hardening["precision_failures"]
            and hardening["ablation_checks"]["accepted"] is True
            and significance.accepted
            and experiment_validation.accepted
        )
        _print_json(
            {
                "accepted": accepted,
                "experiment_id": significance.experiment_id,
                "experiment_validation": {
                    "accepted": experiment_validation.accepted,
                    "failure_count": experiment_validation.failure_count,
                    "records": [
                        asdict(record) for record in experiment_validation.records
                    ],
                },
                "statistical_significance": asdict(significance),
                "validation_hardening": hardening,
            }
        )
        return 0 if accepted else 2
    if args.command == "experiment-status":
        write_experiment_validation_report(root)
        result = build_experiment_validation_report(root)
        _print_json(
            {
                "accepted": result.accepted,
                "failure_count": result.failure_count,
                "records": [asdict(record) for record in result.records],
            }
        )
        return 0 if result.accepted else 2
    if args.command == "monitoring-diagnostics":
        write_production_monitor_diagnostics(root)
        result = build_production_monitor_diagnostics()
        _print_json(asdict(result))
        return 0 if result.accepted else 2
    if args.command == "rollback-readiness":
        result = write_rollback_readiness_report(root)
        report = build_rollback_readiness_report(root)
        _print_json({"path": result["path"], **asdict(report)})
        return 0 if report.accepted else 2
    if args.command == "promotion-status":
        if not args.no_write:
            write_production_promotion_gate_report(root)
        result = build_production_promotion_gate_report(root)
        _print_json(
            {
                **asdict(result),
                "next_actions": _promotion_status_next_actions(result, root=root),
            }
        )
        return 0 if result.paper_trading_allowed else 2
    if args.command == "promotion-dry-run":
        if args.write_report:
            write_promotion_dry_run_report(
                root,
                gold_input=args.gold_input,
                footprint_input=args.footprint_input,
                license_input=args.license_input,
                lockbox_input=args.lockbox_input,
            )
        result = build_promotion_dry_run_report(
            root,
            gold_input=args.gold_input,
            footprint_input=args.footprint_input,
            license_input=args.license_input,
            lockbox_input=args.lockbox_input,
        )
        _print_json(asdict(result))
        return 0 if result.accepted else 2
    if args.command == "gold-set-status":
        write_gold_set_review_summary(root)
        _print_json(asdict(summarize_gold_set_review(root)))
        return 0
    if args.command == "gold-review-packet":
        paths = write_gold_review_packet(root)
        packet = build_gold_review_packet(root)
        _print_json(
            {
                "paths": paths,
                "packet_id": packet.packet_id,
                "status": packet.status,
                "document_count": packet.document_count,
                "review_row_count": packet.review_row_count,
                "pending_review_rows": packet.pending_review_rows,
                "candidate_claim_count": packet.candidate_claim_count,
                "candidate_claim_available_count": packet.candidate_claim_available_count,
                "review_rows_with_candidate_fields": packet.review_rows_with_candidate_fields,
                "candidate_span_ref_count": packet.candidate_span_ref_count,
                "domain_counts": packet.domain_counts,
                "manual_review_required": packet.manual_review_required,
                "risk_flag_counts": packet.risk_flag_counts,
            }
        )
        return 0
    if args.command == "gold-candidate-claims":
        candidate_refresh: dict[str, Any] = {}
        if args.refresh_candidates_from_source:
            source_path = Path(args.source_path)
            if not source_path.is_absolute():
                source_path = root / source_path
            candidates = select_gold_set_candidates_for_claim_review(
                root,
                load_jsonl(source_path),
            )
            candidate_refresh = write_gold_set_candidates(
                candidates,
                root / GOLD_CANDIDATES_PATH,
            )
            candidate_refresh = {
                "candidate_rows": int(candidate_refresh["rows"]),
                "path": str(candidate_refresh["path"]),
                "source_path": str(source_path),
            }
        paths = write_gold_candidate_claims(
            root,
            ensure_candidate_review_rows=args.ensure_candidate_review_rows,
        )
        summary = json.loads(Path(paths["summary"]).read_text(encoding="utf-8"))
        _print_json(
            {
                "paths": paths,
                "summary_id": summary["summary_id"],
                "candidate_claim_count": summary["candidate_claim_count"],
                "candidate_available_count": summary["candidate_available_count"],
                "missing_variable_mapping_count": summary[
                    "missing_variable_mapping_count"
                ],
                "review_rows_with_candidate_fields": summary[
                    "review_rows_with_candidate_fields"
                ],
                "manual_fields_preserved": summary["manual_fields_preserved"],
                "direction_counts": summary["direction_counts"],
                "claim_type_counts": summary["claim_type_counts"],
                "ensure_candidate_review_rows": paths[
                    "ensure_candidate_review_rows"
                ],
                "candidate_review_documents_added": paths[
                    "candidate_review_documents_added"
                ],
                "candidate_review_rows_added": paths[
                    "candidate_review_rows_added"
                ],
                "candidate_refresh": candidate_refresh,
                "blockers": summary.get("blockers", []),
            }
        )
        return 0
    if args.command == "license-status":
        write_source_license_review_summary(root)
        _print_json(
            _source_license_status_stdout(summarize_source_license_review(root))
        )
        return 0
    if args.command == "license-review-packet":
        paths = write_license_review_packet(root)
        packet = build_license_review_packet(root)
        _print_json(
            {
                "paths": paths,
                "packet_id": packet.packet_id,
                "status": packet.status,
                "source_count": packet.source_count,
                "review_row_count": packet.review_row_count,
                "pending_sources": packet.pending_sources,
                "approved_for_derived_claim_storage": packet.approved_for_derived_claim_storage,
                "approved_for_production_runtime": packet.approved_for_production_runtime,
                "manual_review_required": packet.manual_review_required,
                "policy_reason_counts": packet.policy_reason_counts,
            }
        )
        return 0
    if args.command == "apply-gold-review":
        report = apply_gold_set_review_import(root, args.input, dry_run=args.dry_run)
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "prepare-gold-review":
        if args.full and args.reviewed_failures:
            _print_json(
                {
                    "blockers": [
                        "--full and --reviewed-failures cannot be combined"
                    ],
                    "force": args.force,
                    "full": args.full,
                    "reviewed_failures": args.reviewed_failures,
                    "written": False,
                }
            )
            return 2
        result = write_gold_review_starter(
            root,
            output_path=args.output,
            full=args.full,
            reviewed_failures=args.reviewed_failures,
            force=args.force,
            gold_batch_size=args.gold_batch_size,
            offset=args.offset,
            reviewer=args.reviewer,
            review_date=args.review_date,
        )
        _print_json(asdict(result))
        return 0 if result.written else 2
    if args.command == "backfill-gold-review":
        result = backfill_gold_review_from_prior(
            root,
            input_path=args.input,
            prior_review_path=args.prior_reviewed,
            output_path=args.output,
            dry_run=not args.write,
        )
        _print_json(asdict(result))
        return 0 if not result.blockers else 2
    if args.command == "write-gold-review-evidence":
        result = write_gold_review_evidence(
            root,
            limit=args.limit,
            offset=args.offset,
            review_input_path=args.review_input,
        )
        _print_json(result)
        return 0 if result["blockers"] == 0 else 2
    if args.command == "write-gold-review-assist":
        result = write_gold_review_assist(
            root,
            review_input_path=args.review_input,
        )
        _print_json(result)
        return 0 if result["blockers"] == 0 else 2
    if args.command == "apply-license-review":
        report = apply_source_license_review_import(
            root, args.input, dry_run=args.dry_run
        )
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "build-license-review-import":
        report = build_source_license_policy_import(
            root,
            args.policy,
            output_path=args.output,
            dry_run=args.dry_run,
        )
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "prepare-license-policy-review":
        result = write_source_license_reviewed_policy_starter(
            root,
            output_path=args.output,
            force=args.force,
        )
        _print_json(asdict(result))
        return 0 if result.written else 2
    if args.command == "apply-lockbox-review":
        upstream_blockers = (
            ()
            if args.allow_pending_upstream
            else lockbox_upstream_review_blockers(root)
        )
        if upstream_blockers:
            _print_json(
                {
                    "accepted": False,
                    "applied": False,
                    "allow_pending_upstream": False,
                    "rejected_reasons": list(upstream_blockers),
                    "upstream_blockers": list(upstream_blockers),
                }
            )
            return 2
        report = apply_lockbox_review_import(root, args.input, dry_run=args.dry_run)
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "prepare-lockbox-review":
        result = write_lockbox_review_starter(
            root,
            output_path=args.output,
            force=args.force,
            allow_pending_upstream=args.allow_pending_upstream,
        )
        _print_json(asdict(result))
        return 0 if result.written else 2
    if args.command == "review-batches":
        paths = write_manual_review_batches(
            root,
            gold_batch_size=args.gold_batch_size,
            license_batch_size=args.license_batch_size,
        )
        status, _, _ = build_manual_review_batch_status(
            root,
            gold_batch_size=args.gold_batch_size,
            license_batch_size=args.license_batch_size,
        )
        _print_json({"paths": paths, "status": asdict(status)})
        return 0 if status.ready_for_manual_review else 2
    if args.command == "operator-handoff":
        paths = write_operator_handoff(root)
        handoff = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
        _print_json({"paths": paths, "handoff": handoff})
        return 0 if bool(handoff.get("ready_for_operator_review")) else 2
    if args.command == "operator-readiness":
        if args.no_write:
            result = {
                "path": str(root / "registry/handoffs/rke_operator_readiness_report.json")
            }
            report = build_operator_readiness_report(
                root,
                write_supporting_artifacts=False,
            )
        else:
            result = write_operator_readiness_report(root)
            report = build_operator_readiness_report(root)
        _print_json({"path": result["path"], **asdict(report)})
        return 0 if report.accepted else 2
    if args.command == "review-progress":
        if args.review_kind and not (args.summary or args.actions_only):
            _print_json(
                {
                    "accepted": False,
                    "blockers": ["--review-kind requires --summary or --actions-only"],
                }
            )
            return 2
        if args.action_state and not args.actions_only:
            _print_json(
                {
                    "accepted": False,
                    "blockers": ["--action-state requires --actions-only"],
                }
            )
            return 2
        report = build_manual_review_progress(root)
        if args.no_write:
            result = {"path": str(root / "registry/review_batches/manual_review_progress_report.json")}
            runbook = {"path": str(root / "registry/review_batches/manual_review_runbook.md")}
        else:
            result = write_manual_review_progress_report(root)
            runbook = write_manual_review_runbook(root)
        if args.actions_only:
            action_queue = build_manual_review_action_queue(
                report,
                path=result["path"],
                runbook_path=runbook["path"],
                review_kinds=tuple(args.review_kind or ()),
                action_states=tuple(args.action_state or ()),
            )
            _print_json(action_queue)
            return 0 if bool(action_queue["ready_for_promotion_dry_run"]) else 2
        if args.summary:
            summary = build_manual_review_progress_summary(
                report,
                path=result["path"],
                runbook_path=runbook["path"],
                review_kinds=tuple(args.review_kind or ()),
            )
            _print_json(summary)
            return 0 if bool(summary["ready_for_promotion_dry_run"]) else 2
        else:
            _print_json(
                {
                    "path": result["path"],
                    "runbook_path": runbook["path"],
                    **_manual_review_progress_report_payload(report),
                }
            )
            return 0 if report.ready_for_promotion_dry_run else 2
    if args.command == "fetch-tushare-reports":
        _load_env_file(args.env_file)
        date_chunk_days = args.date_chunk_days
        if date_chunk_days is None:
            date_chunk_days = 7 if args.p9_profile else 31
        result = refresh_tushare_research_report_registry(
            root,
            stock_codes=_split_repeated_csv(args.stock_codes),
            industry_keywords=_split_repeated_csv(args.industry_keywords),
            report_types=_split_repeated_csv(args.report_types),
            start_date=args.start_date,
            end_date=args.end_date,
            input_path=args.input_path,
            max_reports_per_query=args.max_reports_per_query,
            stock_query_batch_size=args.stock_query_batch_size,
            date_chunk_days=date_chunk_days,
            merge_existing_source=args.merge_existing_source,
            preserve_review_templates=not args.overwrite_review_templates,
            source_only=args.source_only,
            corpus_profile=(
                P9_REPORT_INTELLIGENCE_CORPUS_PROFILE if args.p9_profile else None
            ),
        )
        _print_json(asdict(result))
        return 0 if result.manifest_valid else 2
    if args.command == "build-local-macro-report-sources":
        result = build_local_macro_strategy_report_sources(
            root=root,
            input_dir=args.input_dir,
            output_path=args.output_path,
            manifest_path=args.manifest_path,
            merge_existing=not args.replace,
        )
        _print_json(asdict(result))
        return 0 if not result.blockers else 2
    if args.command == "report-intelligence":
        _load_env_file(args.env_file)
        result = run_report_intelligence_refresh(
            ReportIntelligenceConfig(
                root=root,
                source_path=args.source_path,
                registry_dir=args.registry_dir,
                cache_dir=args.cache_dir,
                source_ids=_split_repeated_csv(args.source_ids),
                exclude_processed_registry_dirs=_split_repeated_csv(
                    args.exclude_processed_registry_dirs
                ),
                require_cached_markdown=args.require_cached_markdown,
                limit=args.limit,
                min_publish_date=args.min_publish_date,
                max_publish_date=args.max_publish_date,
                selection_order=args.selection_order,
                overwrite=args.overwrite,
                skip_download=args.skip_download,
                skip_convert=args.skip_convert,
                skip_llm=args.skip_llm,
                refresh_derived_only=args.refresh_derived_only,
                download_timeout_seconds=args.download_timeout_seconds,
                mineru_command=args.mineru_command,
                mineru_backend=args.mineru_backend,
                mineru_server_url=args.mineru_server_url,
                mineru_args_template=args.mineru_args_template,
                mineru_timeout_seconds=args.mineru_timeout_seconds,
                mineru_batch_size=args.mineru_batch_size,
                mineru_batch_max_bytes=args.mineru_batch_max_bytes,
                vllm_base_url=args.vllm_base_url
                or os.environ.get("MOSAIC_RKE_VLLM_BASE_URL")
                or "http://127.0.0.1:8020/v1",
                vllm_model=args.vllm_model
                or os.environ.get("MOSAIC_RKE_VLLM_MODEL"),
                vllm_api_key=next(
                    (
                        os.environ[name.strip()]
                        for name in str(args.vllm_api_key_env or "").split(",")
                        if name.strip() and os.environ.get(name.strip())
                    ),
                    None,
                ),
                qlib_etf_dir=args.qlib_etf_dir,
                qlib_stock_dir=args.qlib_stock_dir,
                scorecard_db_path=args.scorecard_db_path,
                vllm_timeout_seconds=args.vllm_timeout_seconds,
                chunk_chars=args.chunk_chars,
                max_chunks=args.max_chunks,
                max_llm_output_tokens=args.max_llm_output_tokens,
                progress_jsonl=args.progress_jsonl,
            )
        )
        _print_json(asdict(result))
        return 0 if result.blocker_count == 0 else 2

    if args.command == "export-macro-agent-priors":
        result = export_macro_agent_research_priors(
            root=root,
            registry_dir=args.registry_dir,
            as_of_date=args.as_of_date,
            agent_id=args.agent_id,
            no_source_prose=args.no_source_prose,
        )
        _print_json(result)
        return 0 if result.get("accepted") else 2

    if args.command == "export-rke-agent-context":
        result = build_rke_agent_research_context(
            root=root,
            registry_dir=args.registry_dir,
            agent_id=args.agent_id,
            as_of_date=args.as_of_date,
            layer=args.layer,
            ticker=args.ticker,
            sector=args.sector,
            max_items=args.max_items,
        )
        _print_json(result)
        return 0

    if args.command == "macro-series-backfill":
        from mosaic.scorecard.macro_series_backfill import backfill_macro_series

        result = backfill_macro_series(
            start_date=args.start_date,
            end_date=args.end_date,
            series_ids=_split_repeated_csv(args.series_ids),
            db_path=args.scorecard_db_path,
        )
        _print_json(result)
        return 0 if result.get("accepted") else 1

    if args.command in {"report-intelligence-evolution-gate", "evolution-readiness"}:
        if args.no_write and args.refresh_prompt_mutations:
            _print_json(
                {
                    "accepted": False,
                    "blockers": [
                        "--no-write cannot be combined with --refresh-prompt-mutations"
                    ],
                }
            )
            return 2
        registry_dir = resolve_report_intelligence_registry_dir(
            root,
            args.registry_dir,
        )
        if args.no_write:
            result = write_report_intelligence_evolution_readiness_gate(
                registry_dir,
                run_id=args.run_id,
                write=False,
            )
        else:
            result = write_report_intelligence_evolution_readiness_gate(
                registry_dir,
                run_id=args.run_id,
            )
        if args.refresh_prompt_mutations:
            result = {
                **result,
                **write_report_intelligence_prompt_mutation_candidates(
                    registry_dir,
                    run_id=args.run_id,
                ),
            }
        result = _augment_evolution_readiness_manual_actions(result, root=root)
        _print_json(result)
        return (
            0
            if not result.get("input_load_blockers")
            and result.get("gate_status") == "passed"
            else 2
        )
    if args.command == "merge-report-intelligence-batches":
        result = merge_report_intelligence_batch_outputs(
            root=root,
            input_dirs=args.input_dir,
            registry_dir=args.registry_dir,
            include_existing_registry=not args.replace,
            replace_source_ids=args.replace_source_ids,
        )
        if args.refresh_derived and result["blocker_count"] == 0:
            refresh = run_report_intelligence_refresh(
                ReportIntelligenceConfig(
                    root=root,
                    registry_dir=args.registry_dir,
                    refresh_derived_only=True,
                )
            )
            result = {**result, "derived_refresh": asdict(refresh)}
        _print_json(result)
        return 0 if result["blocker_count"] == 0 else 2
    if args.command == "registries-preflight":
        result = registries_preflight(root=root, registry_dir=args.registry_dir)
        _print_json(result)
        return 0 if result["blocker_count"] == 0 else 2
    if args.command == "export-private-registries":
        result = export_private_registries(
            root=root,
            output_dir=args.output_dir,
            registry_dir=args.registry_dir,
        )
        _print_json(result)
        return 0 if result["accepted"] else 2
    if args.command == "hydrate-private-registries":
        result = hydrate_private_registries(
            root=root,
            source_dir=args.source_dir,
        )
        _print_json(result)
        return 0 if result["accepted"] else 2
    if args.command == "apply-footprint-review":
        report = apply_analytical_footprint_review_import(
            root,
            args.input,
            dry_run=args.dry_run,
        )
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "prepare-footprint-review":
        if args.output:
            footprint_output = args.output
        elif args.limit is not None:
            footprint_output = ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH
        else:
            footprint_output = ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH
        report = prepare_analytical_footprint_review_import(
            root,
            footprint_output,
            reviewer=args.reviewer,
            review_date=args.review_date,
            limit=args.limit,
            offset=args.offset,
            overwrite=args.overwrite,
            priority=args.priority,
            quality_gap_only=args.quality_gap_only,
        )
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "prepare-footprint-negative-examples":
        if args.output:
            report = prepare_analytical_footprint_negative_examples(
                root,
                output_path=args.output,
                limit=args.limit,
                offset=args.offset,
                overwrite=args.overwrite,
            )
        else:
            report = prepare_analytical_footprint_negative_examples(
                root,
                limit=args.limit,
                offset=args.offset,
                overwrite=args.overwrite,
            )
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "footprint-negative-progress":
        if args.input:
            report = build_analytical_footprint_negative_example_progress(
                root,
                input_path=args.input,
                minimum_sample_target=args.minimum_sample_target,
                expected_positive_minimum_target=(
                    args.expected_positive_minimum_target
                ),
            )
        else:
            report = build_analytical_footprint_negative_example_progress(
                root,
                minimum_sample_target=args.minimum_sample_target,
                expected_positive_minimum_target=(
                    args.expected_positive_minimum_target
                ),
            )
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "write-footprint-negative-approval-draft":
        if args.input:
            report = write_analytical_footprint_negative_example_approval_draft(
                root,
                input_path=args.input,
                expected_positive_minimum_target=(
                    args.expected_positive_minimum_target
                ),
            )
        else:
            report = write_analytical_footprint_negative_example_approval_draft(
                root,
                expected_positive_minimum_target=(
                    args.expected_positive_minimum_target
                ),
            )
        _print_json(asdict(report))
        return 0 if not report.blockers else 2
    if args.command == "approve-footprint-negative-draft":
        if args.output:
            report = write_analytical_footprint_negative_example_approved_import(
                root,
                approval_draft_path=args.approval_draft,
                output_path=args.output,
                reviewer=args.reviewer,
                review_date=args.review_date,
                overwrite=args.overwrite,
            )
        else:
            report = write_analytical_footprint_negative_example_approved_import(
                root,
                approval_draft_path=args.approval_draft,
                reviewer=args.reviewer,
                review_date=args.review_date,
                overwrite=args.overwrite,
            )
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "write-footprint-review-assist":
        report = write_analytical_footprint_review_assist(
            root,
            review_input_path=args.review_input,
        )
        _print_json(asdict(report))
        return 0 if not report.blockers else 2
    if args.command == "write-footprint-review-evidence":
        report = write_analytical_footprint_review_evidence(
            root,
            limit=args.limit,
            offset=args.offset,
            review_input_path=args.review_input,
        )
        _print_json(asdict(report))
        return 0 if not report.blockers else 2
    if args.command == "write-footprint-review-approval-draft":
        report = write_analytical_footprint_review_approval_draft(
            root,
            review_input_path=args.review_input,
        )
        _print_json(asdict(report))
        return 0 if not report.blockers else 2
    if args.command == "approve-footprint-review-draft":
        report = write_analytical_footprint_review_approved_import(
            root,
            approval_draft_path=args.approval_draft,
            output_path=args.output,
            reviewer=args.reviewer,
            review_date=args.review_date,
            overwrite=args.overwrite,
        )
        _print_json(asdict(report))
        return 0 if report.accepted else 2
    if args.command == "validate-required":
        missing, empty = validate_required_registry(root)
        invalid = validate_required_registry_content(root)
        manifest = build_registry_manifest(root) if not missing and not empty else None
        valid = not missing and not empty and not invalid
        _print_json(
            {
                "valid": valid,
                "missing_required": missing,
                "empty_required": empty,
                "invalid_required": invalid,
                "artifact_count": manifest.artifact_count if manifest else None,
            }
        )
        return 0 if valid else 2
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
