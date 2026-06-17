"""Controlled vocabulary gate for source-grounded claim variables."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .phase_minus1 import load_jsonl_with_errors


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
        domain="macro.geopolitical",
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
    ClaimVariableDefinition(
        variable_id="bank_credit_growth_expectation",
        domain="sector.bank",
        variable_type="target",
        description="Expected credit, loan, or social-financing growth impulse for bank and financing-sector views.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="wealth_management_nav_pressure",
        domain="sector.wealth_management",
        variable_type="target",
        description="NAV drawdown, break-even pressure, and risk-adjusted return state for wealth-management products.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="industry_policy_catalyst",
        domain="sector.cross_industry",
        variable_type="cause",
        description="Policy, regulatory, infrastructure, or fiscal catalyst affecting an industry view.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="industry_demand_cycle",
        domain="sector.cross_industry",
        variable_type="cause",
        description="Demand, order, utilization, and market-size cycle impulse behind an industry view.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="industry_supply_constraint",
        domain="sector.cross_industry",
        variable_type="cause",
        description="Supply, capacity, inventory, or bottleneck constraint behind an industry view.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="commodity_price_cycle",
        domain="sector.commodity",
        variable_type="cause",
        description="Commodity price or supply-demand cycle affecting commodity-linked industries.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="global_dollar_liquidity_pressure",
        domain="macro.dollar",
        variable_type="cause",
        description="Dollar, Fed-rate, FX, and global liquidity pressure affecting non-CNY assets.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="recent_price_momentum",
        domain="market.microstructure",
        variable_type="cause",
        description="Recent stock, sector, or index price momentum used as report context.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="technology_innovation_cycle",
        domain="sector.cross_industry",
        variable_type="cause",
        description="Product, model, process, or technology innovation cycle behind a research view.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="company_fundamental_momentum",
        domain="equity.single_name",
        variable_type="cause",
        description="Revenue, profit, margin, cash-flow, utilization, or balance-sheet momentum.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="competitive_intensity_pressure",
        domain="sector.cross_industry",
        variable_type="cause",
        description="Competition, price pressure, risk event, or below-expectation operating pressure.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="industry_etf_forward_return",
        domain="sector.cross_industry",
        variable_type="target",
        description="PIT industry ETF forward return used to label industry research report outcomes.",
        status="sandbox",
    ),
    ClaimVariableDefinition(
        variable_id="stock_forward_excess_return",
        domain="equity.single_name",
        variable_type="target",
        description="Single-name forward excess return used to label stock research report outcomes.",
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
    vocabulary, failures = _load_claim_variable_vocabulary_with_failures(root_path)
    if failures:
        raise ValueError("; ".join(failures))
    return vocabulary


def _load_claim_variable_vocabulary_with_failures(root_path: Path) -> tuple[ClaimVariableVocabulary, tuple[str, ...]]:
    failures: list[str] = []
    path = root_path / VOCABULARY_PATH
    try:
        payload = _read_json(path)
    except json.JSONDecodeError as exc:
        return (
            ClaimVariableVocabulary(vocabulary_id="", variables=()),
            (f"{VOCABULARY_PATH} must contain valid JSON: {exc.msg}",),
        )
    if not isinstance(payload, Mapping):
        return (
            ClaimVariableVocabulary(vocabulary_id="", variables=()),
            (f"{VOCABULARY_PATH} must be object",),
        )

    vocabulary_id = str(payload.get("vocabulary_id") or "")
    if not vocabulary_id:
        failures.append(f"{VOCABULARY_PATH}.vocabulary_id required")
    raw_variables = payload.get("variables", ())
    if not isinstance(raw_variables, Sequence) or isinstance(raw_variables, (str, bytes)):
        failures.append(f"{VOCABULARY_PATH}.variables must be array")
        raw_variables = ()

    variables: list[ClaimVariableDefinition] = []
    for index, row in enumerate(raw_variables, 1):
        if not isinstance(row, Mapping):
            failures.append(f"{VOCABULARY_PATH}.variables[{index}] must be object")
            continue
        for field_name in ("variable_id", "domain", "variable_type", "description"):
            if not row.get(field_name):
                failures.append(f"{VOCABULARY_PATH}.variables[{index}].{field_name} required")
        variables.append(
            ClaimVariableDefinition(
                variable_id=str(row.get("variable_id") or ""),
                domain=str(row.get("domain") or ""),
                variable_type=str(row.get("variable_type") or ""),  # type: ignore[arg-type]
                description=str(row.get("description") or ""),
                status=str(row.get("status") or "active"),  # type: ignore[arg-type]
            )
        )
    return ClaimVariableVocabulary(
        vocabulary_id=vocabulary_id,
        variables=tuple(variables),
    ), tuple(failures)


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


def _load_claim_rows(root_path: Path) -> tuple[list[Mapping[str, Any]], tuple[str, ...]]:
    rows: list[Mapping[str, Any]] = []
    failures: list[str] = []
    for relative in CLAIM_PATHS:
        path = root_path / relative
        if path.exists():
            loaded_rows, parse_failures = load_jsonl_with_errors(path, label=relative)
            failures.extend(parse_failures)
            for index, row in enumerate(loaded_rows, 1):
                if isinstance(row, Mapping):
                    rows.append(row)
                else:
                    failures.append(f"{relative} row {index} must be object")
    return rows, tuple(failures)


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

    vocabulary, vocabulary_load_failures = _load_claim_variable_vocabulary_with_failures(root_path)
    variable_ids = [item.variable_id for item in vocabulary.variables]
    duplicate_ids = sorted({variable_id for variable_id in variable_ids if variable_ids.count(variable_id) > 1})
    vocab_failures: list[str] = list(vocabulary_load_failures)
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
    claims, malformed_claim_row_failures = _load_claim_rows(root_path)
    claim_failures: list[str] = list(malformed_claim_row_failures)
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
                "malformed_claim_row_count": len(malformed_claim_row_failures),
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
