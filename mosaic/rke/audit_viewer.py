"""Local registry audit viewer for RKE provenance chains."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


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


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _add(index: dict[tuple[str, str], AuditReference], ref_type: str, ref_id: Any, path: Path) -> None:
    if ref_id:
        key = (ref_type, str(ref_id))
        index.setdefault(key, AuditReference(ref_type=ref_type, ref_id=str(ref_id), registry_path=str(path)))


def build_registry_index(root: str | Path) -> Mapping[tuple[str, str], AuditReference]:
    root_path = Path(root)
    index: dict[tuple[str, str], AuditReference] = {}

    for path in (root_path / "registry/sources").glob("*.jsonl"):
        for row in _read_jsonl(path):
            _add(index, "source", row.get("source_id"), path)
    for path in (root_path / "registry/claims").glob("*.jsonl"):
        for row in _read_jsonl(path):
            _add(index, "claim", row.get("claim_id"), path)
    for path in (root_path / "registry/hypotheses").glob("*.jsonl"):
        for row in _read_jsonl(path):
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
        for row in _read_jsonl(path):
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
