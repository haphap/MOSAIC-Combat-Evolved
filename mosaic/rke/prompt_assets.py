"""Rendered prompt and mutation proposal artifacts for Prompt Evolution."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Mapping

from .governance import MutationProposal, PatchValidationResult
from .prompt_ir import AgentRuntimeInput, PromptIRContract


@dataclass(frozen=True)
class RenderedPromptArtifact:
    prompt_id: str
    agent_id: str
    prompt_version: str
    prompt_ir_ref: str
    runtime_input_ref: str
    rendered_prompt_path: str
    output_schema_ref: str
    progress_event_schema_ref: str
    handoff_schema_ref: str
    guardrails: tuple[str, ...]


@dataclass(frozen=True)
class MutationPatchArtifact:
    mutation: MutationProposal
    validation: PatchValidationResult
    promotion_state: str
    production_allowed: bool


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def render_prompt_markdown(contract: PromptIRContract, runtime_input: AgentRuntimeInput) -> str:
    required_tools = ", ".join(tool.name for tool in contract.required_tools if tool.required)
    required_tool_contracts = "\n".join(
        (
            f"- {tool.name}: metrics={list(tool.metric_ids)}, "
            f"metric_candidate_ids={list(tool.metric_candidate_ids)}, "
            f"analysis_recipe_ids={list(tool.analysis_recipe_ids)}, "
            f"pit_required_for_backtest={str(tool.pit_required_for_backtest).lower()}, "
            f"fallback_confidence_cap={tool.fallback_confidence_cap}, "
            f"lineage={json.dumps(_jsonable(tool.lineage), ensure_ascii=False, sort_keys=True)}"
        )
        for tool in contract.required_tools
        if tool.required
    )
    fallback_tools = ", ".join(
        f"{tool.name}(cap={tool.confidence_cap:.2f})" for tool in contract.fallback_tools
    )
    active_rules = ", ".join(runtime_input.active_rule_packs)
    guardrails = "\n".join(f"- {item}" for item in contract.guardrails)
    may_decide = "\n".join(f"- {item}" for item in contract.role_contract.may_decide)
    must_not_decide = "\n".join(f"- {item}" for item in contract.role_contract.must_not_decide)
    tool_rows = "\n".join(
        (
            f"- {item.tool_name}: {item.metric}={item.value} {item.unit}, "
            f"as_of={item.as_of}, freshness_days={item.freshness_days}, fallback={str(item.fallback).lower()}"
        )
        for item in runtime_input.tool_outputs_normalized
    )
    rule_scores = "\n".join(
        f"- {rule_id}: {json.dumps(score, ensure_ascii=False, sort_keys=True)}"
        for rule_id, score in sorted(runtime_input.rule_validation_scores.items())
    )
    return "\n".join(
        [
            f"# {contract.agent_id} RKE Runtime Prompt",
            "",
            f"Prompt version: {contract.prompt_version}",
            f"Cohort: {contract.cohort}",
            "",
            "## Role",
            "",
            contract.role_contract.responsibility,
            "",
            "### May Decide",
            may_decide,
            "",
            "### Must Not Decide",
            must_not_decide,
            "",
            "## Tools",
            "",
            f"Required: {required_tools}",
            required_tool_contracts,
            f"Fallback: {fallback_tools}",
            "",
            "## Runtime Evidence",
            "",
            tool_rows,
            "",
            "## Active Research Rules",
            "",
            f"Rule packs: {active_rules}",
            rule_scores,
            "",
            "## Output Schema",
            "",
            f"- output_schema_ref: {contract.output_schema_ref}",
            f"- progress_event_schema_ref: {contract.progress_event_schema_ref}",
            f"- handoff_schema_ref: {contract.handoff_schema_ref}",
            "",
            "## Guardrails",
            "",
            guardrails,
            "",
        ]
    )


def write_prompt_evolution_registry(
    root: str | Path,
    *,
    contract: PromptIRContract,
    runtime_input: AgentRuntimeInput,
    mutation: MutationProposal,
    mutation_validation: PatchValidationResult,
) -> dict[str, str]:
    root_path = Path(root)
    rendered_prompt_path = root_path / "registry/rendered_prompts/macro.central_bank.rke.md"
    rendered_prompt_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_prompt_path.write_text(render_prompt_markdown(contract, runtime_input), encoding="utf-8")

    artifact = RenderedPromptArtifact(
        prompt_id="PROMPT-MACRO-CENTRAL-BANK-RKE-20260606",
        agent_id=contract.agent_id,
        prompt_version=contract.prompt_version,
        prompt_ir_ref="registry/prompt_ir/macro.central_bank.json",
        runtime_input_ref="registry/runtime_inputs/macro.central_bank.20260605.json",
        rendered_prompt_path="registry/rendered_prompts/macro.central_bank.rke.md",
        output_schema_ref=contract.output_schema_ref,
        progress_event_schema_ref=contract.progress_event_schema_ref,
        handoff_schema_ref=contract.handoff_schema_ref,
        guardrails=tuple(contract.guardrails),
    )
    mutation_artifact = MutationPatchArtifact(
        mutation=mutation,
        validation=mutation_validation,
        promotion_state="paper_trading",
        production_allowed=False,
    )
    outputs = {
        "runtime_input": root_path / "registry/runtime_inputs/macro.central_bank.20260605.json",
        "rendered_prompt_metadata": root_path
        / "registry/rendered_prompts/macro.central_bank.rke.json",
        "rendered_prompt_markdown": rendered_prompt_path,
        "mutation_patch": root_path
        / "registry/mutation_patches/central_bank_parameter_update.json",
    }
    _write_json(outputs["runtime_input"], runtime_input)
    _write_json(outputs["rendered_prompt_metadata"], artifact)
    _write_json(outputs["mutation_patch"], mutation_artifact)
    return {key: str(path) for key, path in outputs.items()}
