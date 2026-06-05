"""Controlled vocabulary gate for source-grounded claim variables."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .phase_minus1 import load_jsonl


@dataclass(frozen=True)
class ClaimVariableDefinition:
    variable_id: str
    domain: str
    variable_type: Literal["cause", "target", "both"]
    description: str
    status: Literal["active", "sandbox", "deprecated"] = "active"


@dataclass(frozen=True)
class ClaimVariableVocabulary:
    vocabulary_id: str
    variables: Sequence[ClaimVariableDefinition]


@dataclass(frozen=True)
class ClaimVariableValidationRecord:
    check_id: str
    artifact_paths: Sequence[str]
    accepted: bool
    failures: Sequence[str]
    details: Mapping[str, Any]


@dataclass(frozen=True)
class ClaimVariableValidationReport:
    report_id: str
    records: Sequence[ClaimVariableValidationRecord]

    @property
    def accepted(self) -> bool:
        return all(record.accepted for record in self.records)

    @property
    def failure_count(self) -> int:
        return sum(len(record.failures) for record in self.records)


VOCABULARY_PATH = "registry/vocabularies/claim_variable_vocabulary.json"
VALIDATION_REPORT_PATH = "registry/claim_checks/claim_variable_validation_report.json"
CLAIM_PATHS = (
    "registry/claims/central_bank_claims.jsonl",
    "registry/claims/semiconductor_claims.jsonl",
)
VARIABLE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


DEFAULT_VARIABLES = (
    ClaimVariableDefinition(
        variable_id="pboc_net_injection",
        domain="macro.central_bank",
        variable_type="cause",
        description="Net liquidity injection by the PBOC open-market operation channel.",
    ),
    ClaimVariableDefinition(
        variable_id="short_term_liquidity_pressure",
        domain="macro.central_bank",
        variable_type="target",
        description="Short-horizon funding and liquidity pressure affected by central-bank operations.",
    ),
    ClaimVariableDefinition(
        variable_id="ai_compute_demand",
        domain="sector.semiconductor",
        variable_type="cause",
        description="Demand impulse from AI compute, storage, and data-center workloads.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="semiconductor_storage_cycle",
        domain="sector.semiconductor",
        variable_type="target",
        description="Semiconductor storage-cycle tightness and pricing cycle state.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="valuation_percentile",
        domain="cross_asset.valuation",
        variable_type="cause",
        description="Relative or historical valuation percentile used as a failure-mode condition.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="forward_alpha_after_policy_catalyst",
        domain="sector.semiconductor",
        variable_type="target",
        description="Forward relative alpha after a policy or industrial catalyst.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="trade_friction_intensity",
        domain="macro.geopolitics",
        variable_type="cause",
        description="External trade or technology-friction intensity that can cap policy-substitution themes.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="semiconductor_policy_substitution_alpha",
        domain="sector.semiconductor",
        variable_type="target",
        description="Relative return potential attributed to domestic policy-substitution logic.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="ev_battery_technology_iteration",
        domain="sector.ev_battery",
        variable_type="cause",
        description="Battery product and process technology iteration affecting competitive position.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="ev_charging_ecosystem_demand",
        domain="sector.ev_battery",
        variable_type="both",
        description="Charging, swapping, and downstream replenishment ecosystem demand.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="battery_profitability_expectation",
        domain="sector.ev_battery",
        variable_type="target",
        description="Expected profitability of battery leaders after product and demand changes.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="liquor_demand_recovery",
        domain="sector.consumer",
        variable_type="cause",
        description="Demand recovery and channel inventory normalization for liquor leaders.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="consumer_leader_profitability_expectation",
        domain="sector.consumer",
        variable_type="target",
        description="Expected profitability and pricing power of consumer sector leaders.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="bank_credit_supply",
        domain="sector.bank",
        variable_type="cause",
        description="Credit supply, loan growth, and financial support intensity for banks.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="bank_net_interest_margin_pressure",
        domain="sector.bank",
        variable_type="target",
        description="Net interest margin and profitability pressure in the banking sector.",
        status="sandbox",
    ),
)


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


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_default_claim_variable_vocabulary() -> ClaimVariableVocabulary:
    return ClaimVariableVocabulary(
        vocabulary_id="CLAIM-VARIABLE-VOCABULARY-20260606",
        variables=DEFAULT_VARIABLES,
    )


def write_claim_variable_vocabulary(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    return _write_json(root_path / VOCABULARY_PATH, asdict(build_default_claim_variable_vocabulary()))


def load_claim_variable_vocabulary(root: str | Path = ".") -> ClaimVariableVocabulary:
    root_path = Path(root)
    payload = _read_json(root_path / VOCABULARY_PATH)
    return ClaimVariableVocabulary(
        vocabulary_id=str(payload["vocabulary_id"]),
        variables=tuple(
            ClaimVariableDefinition(
                variable_id=str(row["variable_id"]),
                domain=str(row["domain"]),
                variable_type=row["variable_type"],
                description=str(row["description"]),
                status=row.get("status", "active"),
            )
            for row in payload.get("variables", ())
        ),
    )


def _record(
    check_id: str,
    artifact_paths: Sequence[str],
    failures: Sequence[str],
    details: Mapping[str, Any] | None = None,
) -> ClaimVariableValidationRecord:
    return ClaimVariableValidationRecord(
        check_id=check_id,
        artifact_paths=tuple(artifact_paths),
        accepted=not failures,
        failures=tuple(failures),
        details=dict(details or {}),
    )


def _load_claim_rows(root_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative in CLAIM_PATHS:
        path = root_path / relative
        if path.exists():
            rows.extend(load_jsonl(path))
    return rows


def build_claim_variable_validation_report(root: str | Path = ".") -> ClaimVariableValidationReport:
    root_path = Path(root)
    records: list[ClaimVariableValidationRecord] = []
    if not (root_path / VOCABULARY_PATH).exists():
        records.append(
            _record(
                "CLAIM-VOCABULARY-FILE",
                (VOCABULARY_PATH,),
                (f"{VOCABULARY_PATH}: missing",),
            )
        )
        return ClaimVariableValidationReport(
            report_id="RKE-CLAIM-VARIABLE-VALIDATION-REPORT-20260606",
            records=tuple(records),
        )

    vocabulary = load_claim_variable_vocabulary(root_path)
    variable_ids = [item.variable_id for item in vocabulary.variables]
    duplicate_ids = sorted({variable_id for variable_id in variable_ids if variable_ids.count(variable_id) > 1})
    vocab_failures: list[str] = []
    if not vocabulary.variables:
        vocab_failures.append("vocabulary variables: required non-empty")
    if duplicate_ids:
        vocab_failures.append(f"duplicate variable_ids: {duplicate_ids}")
    for variable in vocabulary.variables:
        if not VARIABLE_ID_RE.fullmatch(variable.variable_id):
            vocab_failures.append(f"{variable.variable_id}: variable_id is not canonical snake_case")
        if len(variable.variable_id) <= 1:
            vocab_failures.append(f"{variable.variable_id}: variable_id too short")
        if variable.variable_type not in {"cause", "target", "both"}:
            vocab_failures.append(f"{variable.variable_id}: invalid variable_type")
        if variable.status not in {"active", "sandbox", "deprecated"}:
            vocab_failures.append(f"{variable.variable_id}: invalid status")
    records.append(
        _record(
            "CLAIM-VOCABULARY-SCHEMA",
            (VOCABULARY_PATH,),
            vocab_failures,
            {"variable_count": len(vocabulary.variables)},
        )
    )

    allowed = {variable.variable_id: variable for variable in vocabulary.variables}
    claims = _load_claim_rows(root_path)
    claim_failures: list[str] = []
    used_variables: set[str] = set()
    for claim in claims:
        claim_id = str(claim.get("claim_id") or "<unknown>")
        cause_variables = tuple(str(item) for item in claim.get("cause_variables") or ())
        target_variables = tuple(str(item) for item in claim.get("target_variables") or ())
        if not cause_variables:
            claim_failures.append(f"{claim_id}: cause_variables required")
        if not target_variables:
            claim_failures.append(f"{claim_id}: target_variables required")
        for field_name, variables, allowed_types in (
            ("cause_variables", cause_variables, {"cause", "both"}),
            ("target_variables", target_variables, {"target", "both"}),
        ):
            for variable_id in variables:
                used_variables.add(variable_id)
                definition = allowed.get(variable_id)
                if len(variable_id) <= 1:
                    claim_failures.append(f"{claim_id}.{field_name}: {variable_id!r} looks like character leakage")
                    continue
                if not VARIABLE_ID_RE.fullmatch(variable_id):
                    claim_failures.append(f"{claim_id}.{field_name}: {variable_id!r} is not canonical")
                if definition is None:
                    claim_failures.append(f"{claim_id}.{field_name}: unknown variable {variable_id!r}")
                elif definition.variable_type not in allowed_types:
                    claim_failures.append(
                        f"{claim_id}.{field_name}: {variable_id!r} is typed as {definition.variable_type}"
                    )
                elif definition.status == "deprecated":
                    claim_failures.append(f"{claim_id}.{field_name}: {variable_id!r} is deprecated")
    records.append(
        _record(
            "CLAIM-VARIABLE-MAPPING",
            CLAIM_PATHS,
            claim_failures,
            {
                "claim_count": len(claims),
                "used_variable_count": len(used_variables),
                "unused_variable_count": len(set(allowed) - used_variables),
            },
        )
    )

    return ClaimVariableValidationReport(
        report_id="RKE-CLAIM-VARIABLE-VALIDATION-REPORT-20260606",
        records=tuple(records),
    )


def write_claim_variable_validation_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_claim_variable_validation_report(root_path)
    return _write_json(
        root_path / VALIDATION_REPORT_PATH,
        {
            **asdict(report),
            "accepted": report.accepted,
            "failure_count": report.failure_count,
        },
    )
