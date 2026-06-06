"""Local registry audit viewer for RKE provenance chains."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


AUDIT_TRACE_VIEW_JSON_PATH = "registry/audits/central_bank_mvp_audit_view.json"
AUDIT_TRACE_VIEW_MD_PATH = "registry/audits/central_bank_mvp_audit_view.md"
DEFAULT_AUDIT_TRACE_PATH = "registry/audits/central_bank_mvp_audit_trace.json"


@dataclass(frozen=True)
class AuditReference:
    ref_type: str
    ref_id: str
    registry_path: str


@dataclass(frozen=True)
class AuditView:
    trace_id: str
    references: Sequence[AuditReference]
    missing_references: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing_references


@dataclass(frozen=True)
class AuditRecord:
    ref_type: str
    ref_id: str
    registry_path: str
    links: Mapping[str, Sequence[str]]
    summary: Mapping[str, Any]


@dataclass(frozen=True)
class AuditEdge:
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relationship: str


@dataclass(frozen=True)
class AuditTraceView:
    trace_id: str
    trace_path: str
    complete: bool
    node_count: int
    edge_count: int
    missing_references: Sequence[str]
    broken_edges: Sequence[str]
    nodes: Sequence[AuditRecord]
    edges: Sequence[AuditEdge]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[Any]:
    rows: list[Any] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _path_label(root_path: Path, path: Path) -> str:
    try:
        return path.relative_to(root_path).as_posix()
    except ValueError:
        return path.as_posix()


def _read_mapping_jsonl(path: Path, root_path: Path) -> tuple[list[Mapping[str, Any]], tuple[str, ...]]:
    rows: list[Mapping[str, Any]] = []
    blockers: list[str] = []
    for index, row in enumerate(_read_jsonl(path), 1):
        if isinstance(row, Mapping):
            rows.append(row)
        else:
            blockers.append(f"{_path_label(root_path, path)} row {index} must be object")
    return rows, tuple(blockers)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(path), "rows": 1}


def _add(index: dict[tuple[str, str], AuditReference], ref_type: str, ref_id: Any, path: Path) -> None:
    if ref_id:
        key = (ref_type, str(ref_id))
        index.setdefault(key, AuditReference(ref_type=ref_type, ref_id=str(ref_id), registry_path=str(path)))


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if str(item))
    return (str(value),)


def _target_path_rule_id(target_path: str) -> str:
    match = re.search(r"/rules/([^/]+)/learnable_parameters/", target_path)
    return match.group(1) if match else ""


def _upsert_record(
    index: dict[tuple[str, str], dict[str, Any]],
    *,
    ref_type: str,
    ref_id: Any,
    path: Path,
    links: Mapping[str, Sequence[str]] | None = None,
    summary: Mapping[str, Any] | None = None,
) -> None:
    if not ref_id:
        return
    key = (ref_type, str(ref_id))
    record = index.setdefault(
        key,
        {
            "ref_type": ref_type,
            "ref_id": str(ref_id),
            "registry_path": str(path),
            "links": {},
            "summary": {},
        },
    )
    for link_key, link_values in dict(links or {}).items():
        existing = set(record["links"].get(link_key, ()))
        existing.update(_as_str_tuple(link_values))
        record["links"][link_key] = tuple(sorted(existing))
    record["summary"].update(dict(summary or {}))


def _build_registry_audit_records_with_blockers(
    root: str | Path,
) -> tuple[Mapping[tuple[str, str], AuditRecord], tuple[str, ...]]:
    """Index registry records and their provenance links without storing source text."""
    root_path = Path(root)
    raw_index: dict[tuple[str, str], dict[str, Any]] = {}
    blockers: list[str] = []

    for path in (root_path / "registry/sources").glob("*.jsonl"):
        rows, row_blockers = _read_mapping_jsonl(path, root_path)
        blockers.extend(row_blockers)
        for row in rows:
            _upsert_record(
                raw_index,
                ref_type="source",
                ref_id=row.get("source_id"),
                path=path,
                summary={
                    "source_type": row.get("source_type"),
                    "publish_date": row.get("publish_date"),
                    "license_status": row.get("license_status"),
                    "point_in_time_available": row.get("point_in_time_available"),
                    "source_hash": row.get("source_hash"),
                },
            )
    for path in (root_path / "registry/claims").glob("*.jsonl"):
        rows, row_blockers = _read_mapping_jsonl(path, root_path)
        blockers.extend(row_blockers)
        for row in rows:
            _upsert_record(
                raw_index,
                ref_type="claim",
                ref_id=row.get("claim_id"),
                path=path,
                links={"source_ids": _as_str_tuple(row.get("source_id"))},
                summary={
                    "claim_type": row.get("claim_type"),
                    "direction": row.get("direction"),
                    "verifier_status": row.get("verifier_status"),
                    "cause_variables": row.get("cause_variables"),
                    "target_variables": row.get("target_variables"),
                },
            )
    for path in (root_path / "registry/hypotheses").glob("*.jsonl"):
        rows, row_blockers = _read_mapping_jsonl(path, root_path)
        blockers.extend(row_blockers)
        for row in rows:
            _upsert_record(
                raw_index,
                ref_type="hypothesis",
                ref_id=row.get("hypothesis_id"),
                path=path,
                links={"claim_ids": _as_str_tuple(row.get("derived_from_claim_ids"))},
                summary={
                    "hypothesis_type": row.get("hypothesis_type"),
                    "status": row.get("status"),
                    "requires_validation": row.get("requires_validation"),
                },
            )
    for path in (root_path / "registry/rule_packs").glob("*.json"):
        payload = _read_json(path)
        rule_pack_id = str(payload.get("rule_pack_id") or "")
        for rule_id, rule in dict(payload.get("rules") or {}).items():
            resolved_rule_id = str(rule.get("rule_id") or rule_id)
            parameter_paths = tuple(
                f"/rule_packs/{rule_pack_id}/rules/{resolved_rule_id}/learnable_parameters/{parameter_name}/value"
                for parameter_name in dict(rule.get("learnable_parameters") or {})
            )
            _upsert_record(
                raw_index,
                ref_type="rule",
                ref_id=resolved_rule_id,
                path=path,
                links={
                    "claim_ids": _as_str_tuple(rule.get("source_claim_ids")),
                    "hypothesis_ids": _as_str_tuple(rule.get("hypothesis_ids")),
                    "parameter_paths": parameter_paths,
                },
                summary={
                    "rule_pack_id": rule_pack_id,
                    "rule_type": rule.get("rule_type"),
                    "status": rule.get("status"),
                    "validation_status": rule.get("validation_status"),
                },
            )
            for parameter_path in parameter_paths:
                _upsert_record(
                    raw_index,
                    ref_type="parameter_path",
                    ref_id=parameter_path,
                    path=path,
                    links={"rule_ids": (resolved_rule_id,)},
                    summary={"rule_pack_id": rule_pack_id, "parameter_path": parameter_path},
                )
    for path in (root_path / "registry/parameter_priors").glob("*.jsonl"):
        rows, row_blockers = _read_mapping_jsonl(path, root_path)
        blockers.extend(row_blockers)
        for row in rows:
            target_path = str(row.get("target_path") or "")
            _upsert_record(
                raw_index,
                ref_type="parameter_path",
                ref_id=target_path,
                path=path,
                links={
                    "claim_ids": _as_str_tuple(row.get("prior_source_claim_ids")),
                    "hypothesis_ids": _as_str_tuple(row.get("prior_hypothesis_ids")),
                    "rule_ids": _as_str_tuple(_target_path_rule_id(target_path)),
                },
                summary={
                    "parameter_proposal_id": row.get("parameter_proposal_id"),
                    "current_value": row.get("current_value"),
                    "candidate_values": row.get("candidate_values"),
                    "status": row.get("status"),
                },
            )
    for path in (root_path / "registry/experiments").glob("*.json"):
        payload = _read_json(path)
        _upsert_record(
            raw_index,
            ref_type="experiment",
            ref_id=payload.get("experiment_id"),
            path=path,
            links={
                "rule_ids": _as_str_tuple(payload.get("rule_ids")),
                "parameter_paths": _as_str_tuple(payload.get("parameter_paths")),
            },
            summary={
                "experiment_family_id": payload.get("experiment_family_id"),
                "pre_registered": payload.get("pre_registered"),
                "effective_n": (payload.get("sampling_design") or {}).get("effective_n"),
                "adjusted_q_value": (payload.get("multiple_testing_control") or {}).get("adjusted_q_value"),
            },
        )
    for path in (root_path / "registry/patches").glob("*.json"):
        payload = _read_json(path)
        _upsert_record(
            raw_index,
            ref_type="patch",
            ref_id=payload.get("patch_id"),
            path=path,
            links={
                "experiment_ids": _as_str_tuple(payload.get("source_experiment_id")),
                "parameter_paths": _as_str_tuple(payload.get("target_path")),
            },
            summary={
                "operation": payload.get("operation"),
                "old_value": payload.get("old_value"),
                "new_value": payload.get("new_value"),
                "promotion_state": (payload.get("validation_summary") or {}).get("promotion_state"),
            },
        )
    for path in (root_path / "registry/runtime_outputs").glob("*.json"):
        payload = _read_json(path)
        recommendation = (payload.get("recommendations") or [{}])[0]
        _upsert_record(
            raw_index,
            ref_type="agent_output",
            ref_id=payload.get("agent_output_id"),
            path=path,
            links={
                "claim_ids": _as_str_tuple(payload.get("source_claim_ids_used")),
                "hypothesis_ids": _as_str_tuple(payload.get("hypothesis_ids_used")),
                "rule_ids": _as_str_tuple(payload.get("research_rule_ids_used")),
            },
            summary={
                "confidence": recommendation.get("confidence"),
                "actionability": recommendation.get("actionability"),
                "progress_status": (payload.get("progress_event") or {}).get("status"),
                "target_signal": (payload.get("rule_aggregation_summary") or {}).get("target_signal"),
            },
        )

    records = {
        key: AuditRecord(
            ref_type=str(record["ref_type"]),
            ref_id=str(record["ref_id"]),
            registry_path=str(record["registry_path"]),
            links={str(k): tuple(v) for k, v in dict(record["links"]).items()},
            summary=dict(record["summary"]),
        )
        for key, record in raw_index.items()
    }
    return records, tuple(blockers)


def build_registry_audit_records(root: str | Path) -> Mapping[tuple[str, str], AuditRecord]:
    records, _ = _build_registry_audit_records_with_blockers(root)
    return records


def build_registry_index(root: str | Path) -> Mapping[tuple[str, str], AuditReference]:
    root_path = Path(root)
    index: dict[tuple[str, str], AuditReference] = {}

    for path in (root_path / "registry/sources").glob("*.jsonl"):
        rows, _ = _read_mapping_jsonl(path, root_path)
        for row in rows:
            _add(index, "source", row.get("source_id"), path)
    for path in (root_path / "registry/claims").glob("*.jsonl"):
        rows, _ = _read_mapping_jsonl(path, root_path)
        for row in rows:
            _add(index, "claim", row.get("claim_id"), path)
    for path in (root_path / "registry/hypotheses").glob("*.jsonl"):
        rows, _ = _read_mapping_jsonl(path, root_path)
        for row in rows:
            _add(index, "hypothesis", row.get("hypothesis_id"), path)
    for path in (root_path / "registry/rule_packs").glob("*.json"):
        payload = _read_json(path)
        for rule_id, rule in dict(payload.get("rules") or {}).items():
            _add(index, "rule", rule.get("rule_id") or rule_id, path)
            for parameter_name in dict(rule.get("learnable_parameters") or {}):
                target_path = (
                    f"/rule_packs/{payload.get('rule_pack_id')}/rules/"
                    f"{rule.get('rule_id') or rule_id}/learnable_parameters/{parameter_name}/value"
                )
                _add(index, "parameter_path", target_path, path)
    for path in (root_path / "registry/parameter_priors").glob("*.jsonl"):
        rows, _ = _read_mapping_jsonl(path, root_path)
        for row in rows:
            _add(index, "parameter_path", row.get("target_path"), path)
    for path in (root_path / "registry/experiments").glob("*.json"):
        _add(index, "experiment", _read_json(path).get("experiment_id"), path)
    for path in (root_path / "registry/patches").glob("*.json"):
        _add(index, "patch", _read_json(path).get("patch_id"), path)
    for path in (root_path / "registry/runtime_outputs").glob("*.json"):
        payload = _read_json(path)
        _add(index, "agent_output", payload.get("agent_output_id"), path)
    return index


def build_audit_view(
    trace: Mapping[str, Sequence[str]],
    *,
    registry_index: Mapping[tuple[str, str], AuditReference],
    trace_id: str = "audit-trace",
) -> AuditView:
    trace_fields = {
        "source_ids": "source",
        "claim_ids": "claim",
        "hypothesis_ids": "hypothesis",
        "rule_ids": "rule",
        "parameter_paths": "parameter_path",
        "experiment_ids": "experiment",
        "patch_ids": "patch",
        "agent_output_ids": "agent_output",
    }
    references: list[AuditReference] = []
    missing: list[str] = []
    for field_name, ref_type in trace_fields.items():
        for ref_id in trace.get(field_name, ()):
            reference = registry_index.get((ref_type, str(ref_id)))
            if reference is None:
                missing.append(f"{field_name}:{ref_id}")
            else:
                references.append(reference)
    return AuditView(
        trace_id=trace_id,
        references=tuple(references),
        missing_references=tuple(missing),
    )


TRACE_FIELDS: Mapping[str, str] = {
    "source_ids": "source",
    "claim_ids": "claim",
    "hypothesis_ids": "hypothesis",
    "rule_ids": "rule",
    "parameter_paths": "parameter_path",
    "experiment_ids": "experiment",
    "patch_ids": "patch",
    "agent_output_ids": "agent_output",
}
LINK_FIELD_TARGET_TYPE: Mapping[str, str] = {
    "source_ids": "source",
    "claim_ids": "claim",
    "hypothesis_ids": "hypothesis",
    "rule_ids": "rule",
    "parameter_paths": "parameter_path",
    "experiment_ids": "experiment",
}
REQUIRED_LINKS: Mapping[str, tuple[tuple[str, str, str], ...]] = {
    "claim": (("source_ids", "source", "source claim"),),
    "hypothesis": (("claim_ids", "claim", "claim hypothesis"),),
    "rule": (
        ("claim_ids", "claim", "claim rule"),
        ("hypothesis_ids", "hypothesis", "hypothesis rule"),
        ("parameter_paths", "parameter_path", "rule parameter"),
    ),
    "parameter_path": (
        ("rule_ids", "rule", "rule parameter"),
        ("claim_ids", "claim", "claim parameter prior"),
        ("hypothesis_ids", "hypothesis", "hypothesis parameter prior"),
    ),
    "experiment": (
        ("rule_ids", "rule", "rule experiment"),
        ("parameter_paths", "parameter_path", "parameter experiment"),
    ),
    "patch": (
        ("experiment_ids", "experiment", "experiment patch"),
        ("parameter_paths", "parameter_path", "parameter patch"),
    ),
    "agent_output": (
        ("claim_ids", "claim", "claim output"),
        ("hypothesis_ids", "hypothesis", "hypothesis output"),
        ("rule_ids", "rule", "rule output"),
    ),
}


def _has_trace_link(
    node: AuditRecord,
    *,
    field_name: str,
    target_type: str,
    node_keys: set[tuple[str, str]],
) -> bool:
    return any((target_type, ref_id) in node_keys for ref_id in node.links.get(field_name, ()))


def build_audit_trace_view(
    root: str | Path = ".",
    *,
    trace_path: str | Path = DEFAULT_AUDIT_TRACE_PATH,
    trace_id: str = "central-bank-mvp",
) -> AuditTraceView:
    root_path = Path(root)
    resolved_trace_path = Path(trace_path)
    if not resolved_trace_path.is_absolute():
        resolved_trace_path = root_path / resolved_trace_path
    trace = _read_json(resolved_trace_path)
    records, registry_blockers = _build_registry_audit_records_with_blockers(root_path)

    nodes: list[AuditRecord] = []
    missing: list[str] = []
    for field_name, ref_type in TRACE_FIELDS.items():
        for ref_id in trace.get(field_name, ()):
            record = records.get((ref_type, str(ref_id)))
            if record is None:
                missing.append(f"{field_name}:{ref_id}")
            else:
                nodes.append(record)

    node_keys = {(node.ref_type, node.ref_id) for node in nodes}
    edges: list[AuditEdge] = []
    edge_keys: set[tuple[str, str, str, str, str]] = set()
    for node in nodes:
        for field_name, target_type in LINK_FIELD_TARGET_TYPE.items():
            for target_id in node.links.get(field_name, ()):
                if (target_type, target_id) not in node_keys:
                    continue
                edge_key = (node.ref_type, node.ref_id, target_type, target_id, field_name)
                if edge_key in edge_keys:
                    continue
                edge_keys.add(edge_key)
                edges.append(
                    AuditEdge(
                        source_type=node.ref_type,
                        source_id=node.ref_id,
                        target_type=target_type,
                        target_id=target_id,
                        relationship=field_name,
                    )
                )

    broken_edges: list[str] = list(registry_blockers)
    for node in nodes:
        for field_name, target_type, label in REQUIRED_LINKS.get(node.ref_type, ()):
            if not _has_trace_link(node, field_name=field_name, target_type=target_type, node_keys=node_keys):
                broken_edges.append(f"{node.ref_type}:{node.ref_id} missing trace-linked {label}")

    complete = not missing and not broken_edges
    return AuditTraceView(
        trace_id=trace_id,
        trace_path=str(resolved_trace_path.relative_to(root_path) if resolved_trace_path.is_relative_to(root_path) else resolved_trace_path),
        complete=complete,
        node_count=len(nodes),
        edge_count=len(edges),
        missing_references=tuple(missing),
        broken_edges=tuple(broken_edges),
        nodes=tuple(nodes),
        edges=tuple(edges),
    )


def render_audit_trace_markdown(view: AuditTraceView) -> str:
    lines = [
        "# RKE Audit Trace View",
        "",
        f"- Trace: {view.trace_id}",
        f"- Complete: {str(view.complete).lower()}",
        f"- Nodes: {view.node_count}",
        f"- Edges: {view.edge_count}",
        f"- Missing references: {len(view.missing_references)}",
        f"- Broken edges: {len(view.broken_edges)}",
        "",
        "## Nodes",
        "",
    ]
    for node in view.nodes:
        summary = json.dumps(_jsonable(node.summary), ensure_ascii=False, sort_keys=True)
        lines.append(f"- {node.ref_type}:{node.ref_id} | {node.registry_path} | {summary}")
    lines.extend(["", "## Edges", ""])
    for edge in view.edges:
        lines.append(
            f"- {edge.source_type}:{edge.source_id} --{edge.relationship}-> "
            f"{edge.target_type}:{edge.target_id}"
        )
    if view.missing_references or view.broken_edges:
        lines.extend(["", "## Gaps", ""])
        for item in view.missing_references:
            lines.append(f"- missing reference: {item}")
        for item in view.broken_edges:
            lines.append(f"- broken edge: {item}")
    return "\n".join(lines)


def write_audit_trace_view(
    root: str | Path = ".",
    *,
    trace_path: str | Path = DEFAULT_AUDIT_TRACE_PATH,
) -> dict[str, str]:
    root_path = Path(root)
    view = build_audit_trace_view(root_path, trace_path=trace_path)
    json_result = _write_json(root_path / AUDIT_TRACE_VIEW_JSON_PATH, asdict(view))
    md_path = root_path / AUDIT_TRACE_VIEW_MD_PATH
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_audit_trace_markdown(view) + "\n", encoding="utf-8")
    return {"json": str(json_result["path"]), "markdown": str(md_path)}
