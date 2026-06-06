"""Rule-pack checker for RKE compiler and promotion contracts."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .p0 import validate_rule_id, validate_rule_pack_id
from .phase_minus1 import load_jsonl_with_errors


RULE_PACK_VALIDATION_REPORT_PATH = (
    "registry/rule_checks/rule_pack_validation_report.json"
)
RULE_PACK_PATHS = (
    "registry/rule_packs/macro.central_bank.liquidity.v1.json",
    "registry/rule_packs/sector.semiconductor.policy_substitution.v1.json",
)
CLAIM_PATHS = (
    "registry/claims/central_bank_claims.jsonl",
    "registry/claims/semiconductor_claims.jsonl",
)
HYPOTHESIS_PATHS = (
    "registry/hypotheses/central_bank_hypotheses.jsonl",
    "registry/hypotheses/semiconductor_hypotheses.jsonl",
)
DATA_MATRIX_PATHS = (
    "registry/data_availability/central_bank_data_availability.json",
    "registry/data_availability/semiconductor_sandbox_data_availability.json",
    "registry/data_availability/macro_expansion_data_availability.json",
)
ALLOWED_RULE_TYPES = {"soft", "hard", "guard", "prior", "policy", "risk"}
ALLOWED_RULE_STATUSES = {
    "candidate",
    "validated",
    "paper_trading",
    "production",
    "deprecated",
}
ALLOWED_PACK_STATUSES = {"candidate", "validated", "paper_trading", "production"}
PRODUCTION_VALIDATION_STATES = {"lockbox_reviewed", "production"}
PARAMETER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
AGENT_ID_RE = re.compile(r"^(macro|sector|superinvestor|decision)\.[a-z0-9_]+$")


@dataclass(frozen=True)
class RulePackValidationRecord:
    check_id: str
    artifact_paths: Sequence[str]
    accepted: bool
    failures: Sequence[str]
    details: Mapping[str, Any]


@dataclass(frozen=True)
class RulePackValidationReport:
    report_id: str
    records: Sequence[RulePackValidationRecord]

    @property
    def accepted(self) -> bool:
        return all(record.accepted for record in self.records)

    @property
    def failure_count(self) -> int:
        return sum(len(record.failures) for record in self.records)


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
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": 1}


def _record(
    check_id: str,
    artifact_paths: Sequence[str],
    failures: Sequence[str],
    details: Mapping[str, Any] | None = None,
) -> RulePackValidationRecord:
    return RulePackValidationRecord(
        check_id=check_id,
        artifact_paths=tuple(artifact_paths),
        accepted=not failures,
        failures=tuple(failures),
        details=dict(details or {}),
    )


def _read_json_object(
    path: Path, relative: str
) -> tuple[Mapping[str, Any] | None, str]:
    if not path.exists():
        return None, f"{relative}: missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"{relative} must contain valid JSON: {exc.msg}"
    if not isinstance(payload, Mapping):
        return None, f"{relative} must be object"
    return payload, ""


def _load_mapping_rows(
    root_path: Path,
    paths: Sequence[str],
    *,
    id_field: str,
    label: str,
) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    rows_by_id: dict[str, Mapping[str, Any]] = {}
    failures: list[str] = []
    for relative in paths:
        path = root_path / relative
        if not path.exists():
            failures.append(f"{relative}: missing")
            continue
        rows, parse_failures = load_jsonl_with_errors(path, label=relative)
        failures.extend(parse_failures)
        for index, row in enumerate(rows, 1):
            if not isinstance(row, Mapping):
                failures.append(f"{relative} row {index} must be object")
                continue
            row_id = str(row.get(id_field) or "").strip()
            if not row_id:
                failures.append(f"{relative} row {index}: {id_field} required")
                continue
            if row_id in rows_by_id:
                failures.append(f"{row_id}: duplicate {id_field}")
            rows_by_id[row_id] = row
    if not rows_by_id:
        failures.append(f"{label}: required non-empty")
    return rows_by_id, failures


def _load_rule_packs(
    root_path: Path,
) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    packs: dict[str, Mapping[str, Any]] = {}
    failures: list[str] = []
    for relative in RULE_PACK_PATHS:
        payload, error = _read_json_object(root_path / relative, relative)
        if error:
            failures.append(error)
            continue
        rule_pack_id = str(payload.get("rule_pack_id") or "").strip()
        if not rule_pack_id:
            failures.append(f"{relative}: rule_pack_id required")
            continue
        if rule_pack_id in packs:
            failures.append(f"{rule_pack_id}: duplicate rule_pack_id")
        packs[relative] = payload
    if not packs:
        failures.append("rule_packs: required non-empty")
    return packs, failures


def _load_data_matrix(
    root_path: Path,
) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    proxies: dict[str, Mapping[str, Any]] = {}
    failures: list[str] = []
    for relative in DATA_MATRIX_PATHS:
        matrix, error = _read_json_object(root_path / relative, relative)
        if error:
            failures.append(error)
            continue
        raw_proxies = matrix.get("proxies")
        if not isinstance(raw_proxies, Mapping):
            failures.append(f"{relative}.proxies: required object")
            continue
        for key, proxy in raw_proxies.items():
            if not isinstance(proxy, Mapping):
                failures.append(f"{relative}.proxies.{key}: proxy must be object")
                continue
            proxy_name = str(proxy.get("metric_proxy") or key).strip()
            if not proxy_name:
                failures.append(f"{relative}.proxies.{key}: metric_proxy required")
                continue
            proxies[proxy_name] = proxy
    if not proxies:
        failures.append("data availability proxies: required non-empty")
    return proxies, failures


def _sequence_of_strings(value: Any) -> list[str] | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        strings = [str(item).strip() for item in value if str(item).strip()]
        return strings
    return None


def _horizon_tuple(value: Any) -> tuple[int, int] | None:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 2
    ):
        return None
    low, high = value
    if not isinstance(low, int) or isinstance(low, bool):
        return None
    if not isinstance(high, int) or isinstance(high, bool):
        return None
    return low, high


def _parameter_failures(rule_id: str, name: str, parameter: Any) -> list[str]:
    failures: list[str] = []
    label = f"{rule_id}.{name}"
    if not PARAMETER_NAME_RE.fullmatch(name):
        failures.append(f"{label}: learnable parameter name is not canonical")
    if not isinstance(parameter, Mapping):
        return failures + [f"{label}: learnable parameter must be object"]
    parameter_type = str(parameter.get("type") or "")
    value = parameter.get("value")
    if parameter_type not in {"integer", "float", "string", "boolean"}:
        failures.append(f"{label}: parameter type invalid")
    elif parameter_type == "integer" and (
        not isinstance(value, int) or isinstance(value, bool)
    ):
        failures.append(f"{label}: integer parameter requires int value")
    elif parameter_type == "float" and (
        not isinstance(value, (int, float)) or isinstance(value, bool)
    ):
        failures.append(f"{label}: float parameter requires numeric value")
    elif parameter_type == "string" and not isinstance(value, str):
        failures.append(f"{label}: string parameter requires string value")
    elif parameter_type == "boolean" and not isinstance(value, bool):
        failures.append(f"{label}: boolean parameter requires bool value")

    for bound in ("min", "max"):
        bound_value = parameter.get(bound)
        if bound_value is not None and (
            not isinstance(bound_value, (int, float)) or isinstance(bound_value, bool)
        ):
            failures.append(f"{label}: {bound} must be numeric when present")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = parameter.get("min")
        maximum = parameter.get("max")
        if isinstance(minimum, (int, float)) and not isinstance(minimum, bool):
            if value < minimum:
                failures.append(f"{label}: value below min")
        if isinstance(maximum, (int, float)) and not isinstance(maximum, bool):
            if value > maximum:
                failures.append(f"{label}: value above max")
        if (
            isinstance(minimum, (int, float))
            and isinstance(maximum, (int, float))
            and not isinstance(minimum, bool)
            and not isinstance(maximum, bool)
            and minimum > maximum
        ):
            failures.append(f"{label}: min cannot exceed max")
    return failures


def _iter_rule_items(
    packs: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[str, Mapping[str, Any], str, Mapping[str, Any]], ...]:
    items: list[tuple[str, Mapping[str, Any], str, Mapping[str, Any]]] = []
    for relative, pack in packs.items():
        rules = pack.get("rules")
        if not isinstance(rules, Mapping):
            continue
        for rule_key, rule in rules.items():
            if isinstance(rule, Mapping):
                items.append((relative, pack, str(rule_key), rule))
    return tuple(items)


def _contract_record(
    packs: Mapping[str, Mapping[str, Any]],
    load_failures: Sequence[str],
    known_claim_ids: set[str],
    known_hypothesis_ids: set[str],
) -> RulePackValidationRecord:
    failures = list(load_failures)
    checked_rule_count = 0
    for relative, pack in packs.items():
        rule_pack_id = str(pack.get("rule_pack_id") or "").strip()
        agent_id = str(pack.get("agent_id") or "").strip()
        status = str(pack.get("status") or "").strip()
        if not validate_rule_pack_id(rule_pack_id):
            failures.append(f"{relative}: rule_pack_id is not canonical")
        if not AGENT_ID_RE.fullmatch(agent_id):
            failures.append(f"{relative}: agent_id is not canonical")
        if agent_id and rule_pack_id and not rule_pack_id.startswith(f"{agent_id}."):
            failures.append(f"{relative}: rule_pack_id must start with agent_id")
        if status not in ALLOWED_PACK_STATUSES:
            failures.append(f"{relative}: status invalid")
        rules = pack.get("rules")
        if not isinstance(rules, Mapping) or not rules:
            failures.append(f"{relative}.rules: required non-empty object")
            continue
        for rule_key, rule in rules.items():
            checked_rule_count += 1
            if not isinstance(rule, Mapping):
                failures.append(f"{relative}.rules.{rule_key}: rule must be object")
                continue
            rule_id = str(rule.get("rule_id") or "").strip()
            if rule_key != rule_id:
                failures.append(f"{rule_key}: rule map key mismatch")
            if not validate_rule_id(rule_id):
                failures.append(f"{rule_id or rule_key}: rule_id is not canonical")
            if agent_id and rule_id and not rule_id.startswith(f"{agent_id}."):
                failures.append(f"{rule_id}: rule_id must start with agent_id")
            rule_type = str(rule.get("rule_type") or "")
            if rule_type not in ALLOWED_RULE_TYPES:
                failures.append(f"{rule_id}: rule_type invalid")
            rule_status = str(rule.get("status") or "")
            if rule_status not in ALLOWED_RULE_STATUSES:
                failures.append(f"{rule_id}: status invalid")
            source_claim_ids = _sequence_of_strings(rule.get("source_claim_ids"))
            if not source_claim_ids:
                failures.append(f"{rule_id}: source_claim_ids required")
            else:
                unknown = sorted(set(source_claim_ids) - known_claim_ids)
                if unknown:
                    failures.append(f"{rule_id}: unknown source_claim_ids: {unknown}")
            hypothesis_ids = _sequence_of_strings(rule.get("hypothesis_ids"))
            if hypothesis_ids is None:
                failures.append(f"{rule_id}: hypothesis_ids must be array")
            elif set(hypothesis_ids) - known_hypothesis_ids:
                unknown = sorted(set(hypothesis_ids) - known_hypothesis_ids)
                failures.append(f"{rule_id}: unknown hypothesis_ids: {unknown}")
            if not _sequence_of_strings(rule.get("mechanism_chain")):
                failures.append(f"{rule_id}: mechanism_chain required")
            if not _sequence_of_strings(rule.get("metric_proxies")):
                failures.append(f"{rule_id}: metric_proxies required")
    return _record(
        "RULE-PACK-CONTRACT",
        (*RULE_PACK_PATHS, *CLAIM_PATHS, *HYPOTHESIS_PATHS),
        failures,
        {
            "rule_pack_count": len(packs),
            "checked_rule_count": checked_rule_count,
        },
    )


def _data_matrix_record(
    packs: Mapping[str, Mapping[str, Any]],
    proxy_index: Mapping[str, Mapping[str, Any]],
    load_failures: Sequence[str],
) -> RulePackValidationRecord:
    failures = list(load_failures)
    checked_proxy_count = 0
    sandbox_only_proxy_count = 0
    production_proxy_count = 0
    for _, pack, _, rule in _iter_rule_items(packs):
        rule_id = str(rule.get("rule_id") or "").strip()
        rule_status = str(rule.get("status") or "")
        validation_status = str(rule.get("validation_status") or "")
        production_rule = (
            rule_status == "production" or pack.get("status") == "production"
        )
        for proxy_name in _sequence_of_strings(rule.get("metric_proxies")) or []:
            checked_proxy_count += 1
            proxy = proxy_index.get(proxy_name)
            if proxy is None:
                failures.append(f"{rule_id}: metric proxy not found: {proxy_name}")
                continue
            if proxy.get("point_in_time_available") is not True:
                failures.append(
                    f"{rule_id}.{proxy_name}: point_in_time_available must be true"
                )
            validation_ready = proxy.get("allowed_for_validation") is True
            production_ready = proxy.get("allowed_for_production") is True
            if production_rule and not production_ready:
                failures.append(
                    f"{rule_id}.{proxy_name}: production proxy is not allowed"
                )
            if validation_status == "sandbox_only" and not validation_ready:
                sandbox_only_proxy_count += 1
            elif not validation_ready:
                failures.append(
                    f"{rule_id}.{proxy_name}: validation proxy is not allowed"
                )
            if production_ready:
                production_proxy_count += 1
    return _record(
        "RULE-PACK-DATA-MATRIX",
        (*RULE_PACK_PATHS, *DATA_MATRIX_PATHS),
        failures,
        {
            "checked_proxy_count": checked_proxy_count,
            "production_proxy_count": production_proxy_count,
            "sandbox_only_proxy_count": sandbox_only_proxy_count,
        },
    )


def _horizon_parameter_record(
    packs: Mapping[str, Mapping[str, Any]],
) -> RulePackValidationRecord:
    failures: list[str] = []
    checked_parameter_count = 0
    horizon_ranges: dict[str, list[int]] = {}
    for _, _, _, rule in _iter_rule_items(packs):
        rule_id = str(rule.get("rule_id") or "").strip()
        horizon = _horizon_tuple(rule.get("horizon_days"))
        if horizon is None:
            failures.append(f"{rule_id}: horizon_days must be [min_days, max_days]")
        else:
            low, high = horizon
            horizon_ranges[rule_id] = [low, high]
            if low <= 0:
                failures.append(f"{rule_id}: horizon min must be positive")
            if high < low:
                failures.append(f"{rule_id}: horizon max must be >= min")
        parameters = rule.get("learnable_parameters")
        if not isinstance(parameters, Mapping) or not parameters:
            failures.append(f"{rule_id}: learnable_parameters required")
            continue
        for parameter_name, parameter in parameters.items():
            checked_parameter_count += 1
            failures.extend(
                _parameter_failures(rule_id, str(parameter_name), parameter)
            )
    return _record(
        "RULE-PACK-HORIZON-PARAMETERS",
        RULE_PACK_PATHS,
        failures,
        {
            "checked_parameter_count": checked_parameter_count,
            "horizon_ranges": horizon_ranges,
        },
    )


def _promotion_gate_record(
    packs: Mapping[str, Mapping[str, Any]],
) -> RulePackValidationRecord:
    failures: list[str] = []
    production_rule_count = 0
    validation_required_count = 0
    for _, pack, _, rule in _iter_rule_items(packs):
        rule_id = str(rule.get("rule_id") or "").strip()
        rule_status = str(rule.get("status") or "")
        validation_status = str(rule.get("validation_status") or "")
        production_rule = (
            rule_status == "production" or pack.get("status") == "production"
        )
        if rule.get("validation_required") is not True:
            failures.append(f"{rule_id}: validation_required must be true")
        else:
            validation_required_count += 1
        if production_rule:
            production_rule_count += 1
            if validation_status not in PRODUCTION_VALIDATION_STATES:
                failures.append(
                    f"{rule_id}: production requires lockbox-reviewed validation"
                )
    return _record(
        "RULE-PACK-PROMOTION-GATES",
        RULE_PACK_PATHS,
        failures,
        {
            "production_rule_count": production_rule_count,
            "validation_required_count": validation_required_count,
        },
    )


def build_rule_pack_validation_report(
    root: str | Path = ".",
) -> RulePackValidationReport:
    root_path = Path(root)
    claims_by_id, claim_failures = _load_mapping_rows(
        root_path, CLAIM_PATHS, id_field="claim_id", label="claims"
    )
    hypotheses_by_id, hypothesis_failures = _load_mapping_rows(
        root_path, HYPOTHESIS_PATHS, id_field="hypothesis_id", label="hypotheses"
    )
    packs, pack_failures = _load_rule_packs(root_path)
    proxy_index, proxy_failures = _load_data_matrix(root_path)
    return RulePackValidationReport(
        report_id="RKE-RULE-PACK-VALIDATION-REPORT-20260606",
        records=(
            _contract_record(
                packs,
                (*pack_failures, *claim_failures, *hypothesis_failures),
                set(claims_by_id),
                set(hypotheses_by_id),
            ),
            _data_matrix_record(packs, proxy_index, proxy_failures),
            _horizon_parameter_record(packs),
            _promotion_gate_record(packs),
        ),
    )


def write_rule_pack_validation_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_rule_pack_validation_report(root_path)
    return _write_json(
        root_path / RULE_PACK_VALIDATION_REPORT_PATH,
        {
            **asdict(report),
            "accepted": report.accepted,
            "failure_count": report.failure_count,
        },
    )
