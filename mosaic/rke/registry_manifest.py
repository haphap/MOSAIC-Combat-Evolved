"""Registry manifest and required-artifact checks for RKE."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Sequence


REQUIRED_REGISTRY_FILES = (
    "registry/audits/central_bank_mvp_audit_trace.json",
    "registry/audits/rke_completion_audit.json",
    "registry/claims/central_bank_claims.jsonl",
    "registry/claims/semiconductor_claims.jsonl",
    "registry/compliance/tushare_license_review_summary.json",
    "registry/compliance/tushare_license_review_template.jsonl",
    "registry/dashboards/rke_dashboard.json",
    "registry/dashboards/rke_dashboard.md",
    "registry/data_availability/central_bank_data_availability.json",
    "registry/data_availability/macro_expansion_data_availability.json",
    "registry/data_availability/semiconductor_sandbox_data_availability.json",
    "registry/disagreement/semiconductor_policy_substitution.json",
    "registry/expansion/macro_phase6_expansion.json",
    "registry/experiments/central_bank_validation_experiment_v2.json",
    "registry/gold_sets/tushare_research_reports.review_summary.json",
    "registry/gold_sets/tushare_research_reports.review_template.jsonl",
    "registry/hypotheses/central_bank_hypotheses.jsonl",
    "registry/hypotheses/semiconductor_hypotheses.jsonl",
    "registry/integration/phase7_layer_integration_contracts.json",
    "registry/lockbox/central_bank_lockbox_review.json",
    "registry/monitoring/central_bank_paper_trading_report.json",
    "registry/parameter_priors/central_bank_parameter_priors.jsonl",
    "registry/patches/central_bank_paper_trading_patch.json",
    "registry/prompt_ir/macro.central_bank.json",
    "registry/rule_packs/macro.central_bank.liquidity.v1.json",
    "registry/rule_packs/sector.semiconductor.policy_substitution.v1.json",
    "registry/runtime_outputs/macro.central_bank.20260605.json",
    "registry/runtime_outputs/sector.semiconductor.demo.20260605.json",
    "registry/sources/central_bank_sources.jsonl",
    "registry/sources/semiconductor_demo_sources.jsonl",
    "registry/sources/tushare_research_reports.gold_candidates.jsonl",
    "registry/sources/tushare_research_reports.jsonl",
    "registry/sources/tushare_research_reports.manifest.json",
    "registry/validation_hardening/central_bank_hardening_report.json",
)


@dataclass(frozen=True)
class RegistryArtifact:
    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class RegistryManifest:
    manifest_id: str
    artifact_count: int
    artifacts: Sequence[RegistryArtifact]
    missing_required: Sequence[str]
    empty_required: Sequence[str]

    @property
    def valid(self) -> bool:
        return not self.missing_required and not self.empty_required


def file_sha256(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def validate_required_registry(root: str | Path = ".") -> tuple[tuple[str, ...], tuple[str, ...]]:
    root_path = Path(root)
    missing: list[str] = []
    empty: list[str] = []
    for relative in REQUIRED_REGISTRY_FILES:
        path = root_path / relative
        if not path.exists():
            missing.append(relative)
        elif path.stat().st_size <= 0:
            empty.append(relative)
    return tuple(missing), tuple(empty)


def build_registry_manifest(root: str | Path = ".") -> RegistryManifest:
    root_path = Path(root)
    artifacts: list[RegistryArtifact] = []
    for path in sorted((root_path / "registry").rglob("*")):
        if not path.is_file():
            continue
        if path.name == "rke_registry_manifest.json":
            continue
        relative = path.relative_to(root_path).as_posix()
        artifacts.append(
            RegistryArtifact(
                path=relative,
                bytes=path.stat().st_size,
                sha256=file_sha256(path),
            )
        )
    missing, empty = validate_required_registry(root_path)
    return RegistryManifest(
        manifest_id="RKE-REGISTRY-MANIFEST-20260606",
        artifact_count=len(artifacts),
        artifacts=tuple(artifacts),
        missing_required=missing,
        empty_required=empty,
    )


def write_registry_manifest(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    manifest = build_registry_manifest(root_path)
    output_path = root_path / "registry/manifests/rke_registry_manifest.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(output_path),
        "artifact_count": manifest.artifact_count,
        "valid": manifest.valid,
    }
