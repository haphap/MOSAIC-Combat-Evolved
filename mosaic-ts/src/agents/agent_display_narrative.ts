import type {
  AcceptedAgentOutputRecord,
  AcceptedAgentOutputStore,
  AcceptedOutputRecordRef,
} from "./accepted_output.js";
import { canonicalHash } from "./helpers/agent_run_contract.js";
import { ALL_AGENTS, LAYER_BY_AGENT, type Language, type Layer } from "./prompts/cohorts.js";
import type { DailyCycleStateType } from "./state.js";

export const AGENT_DISPLAY_NARRATIVE_SCHEMA_VERSION = "agent_display_narrative_v1" as const;
export const AGENT_DISPLAY_NARRATIVE_BUNDLE_SCHEMA_VERSION =
  "agent_display_narrative_bundle_v1" as const;

export type AgentDisplayNarrativeSource =
  | "ACCEPTED_OUTPUT"
  | "NO_EVALUATION_OBJECT"
  | "NON_PRODUCTION_STRUCTURED_OUTPUT";

/** UI-only explanation derived from an Agent's accepted structured output.
 *
 * It is deliberately not part of any accepted-output payload or source-layer
 * DTO. The text is a deterministic projection of already accepted fields, not
 * a second model-authored fact channel or a chain-of-thought trace.
 */
export interface AgentDisplayNarrative {
  schema_version: typeof AGENT_DISPLAY_NARRATIVE_SCHEMA_VERSION;
  narrative_id: string;
  agent_id: string;
  layer: Layer;
  language: Language;
  source: AgentDisplayNarrativeSource;
  source_output_id: string | null;
  source_output_hash: string;
  narrative_text: string;
  ui_only: true;
}

export interface AgentDisplayNarrativeBundle {
  schema_version: typeof AGENT_DISPLAY_NARRATIVE_BUNDLE_SCHEMA_VERSION;
  trace_id: string;
  cohort: string;
  as_of_date: string;
  language: Language;
  narrative_count: 28;
  narratives: AgentDisplayNarrative[];
  bundle_hash: string;
}

type NarrativeState = Pick<
  DailyCycleStateType,
  | "trace_id"
  | "active_cohort"
  | "as_of_date"
  | "darwinian_runtime_binding"
  | "outcome_schedule_plan"
  | "outcome_stage_skips"
  | "accepted_output_refs"
  | "layer1_outputs"
  | "layer2_outputs"
  | "layer3_outputs"
  | "layer4_outputs"
>;

export function buildAgentDisplayNarrativeBundle(
  state: NarrativeState,
  acceptedOutputStore?: AcceptedAgentOutputStore,
): AgentDisplayNarrativeBundle {
  const language = state.outcome_schedule_plan?.language ?? "zh";
  const narratives = ALL_AGENTS.map((agentId) =>
    buildNarrative(state, agentId, language, acceptedOutputStore),
  );
  if (narratives.length !== 28 || new Set(narratives.map((row) => row.agent_id)).size !== 28) {
    throw new Error("agent display narrative bundle must cover exactly 28 logical Agents");
  }
  const body = {
    schema_version: AGENT_DISPLAY_NARRATIVE_BUNDLE_SCHEMA_VERSION,
    trace_id: requiredText(state.trace_id, "trace_id"),
    cohort: requiredText(state.active_cohort, "active_cohort"),
    as_of_date: requiredText(state.as_of_date, "as_of_date"),
    language,
    narrative_count: 28 as const,
    narratives,
  };
  return { ...body, bundle_hash: canonicalHash(body) };
}

function buildNarrative(
  state: NarrativeState,
  agentId: string,
  language: Language,
  acceptedOutputStore: AcceptedAgentOutputStore | undefined,
): AgentDisplayNarrative {
  const layer = LAYER_BY_AGENT[agentId];
  if (!layer) throw new Error(`unknown Agent for display narrative: ${agentId}`);
  const skip = state.outcome_stage_skips[agentId as keyof typeof state.outcome_stage_skips];
  const acceptedRefs = acceptedRefsFor(state, agentId);
  const acceptedRef = selectedAcceptedRef(agentId, acceptedRefs);
  const production = state.darwinian_runtime_binding !== null;

  if (production && !acceptedRef && !skip) {
    throw new Error(`${agentId}: production display narrative lacks accepted-output lineage`);
  }
  if (acceptedRefs.length > 0 && skip) {
    throw new Error(`${agentId}: display narrative cannot be both accepted and skipped`);
  }

  const sourceOutput = skip
    ? null
    : production
      ? acceptedPayloadFor(
          state,
          agentId,
          language,
          acceptedRef as AcceptedOutputRecordRef,
          acceptedOutputStore,
        )
      : outputFor(state, layer, agentId);
  if (!sourceOutput && !skip) {
    throw new Error(`${agentId}: display narrative source output is unavailable`);
  }
  const output =
    sourceOutput && production && acceptedRef
      ? acceptedNarrativeProjection(
          agentId,
          acceptedRef.accepted_output_kind,
          asRecord(sourceOutput),
        )
      : sourceOutput;

  const source: AgentDisplayNarrativeSource = skip
    ? "NO_EVALUATION_OBJECT"
    : acceptedRef
      ? "ACCEPTED_OUTPUT"
      : "NON_PRODUCTION_STRUCTURED_OUTPUT";
  const sourceOutputId = skip ? null : (acceptedRef?.accepted_output_id ?? null);
  const sourceOutputHash = skip
    ? skip.stage_skip_hash
    : (acceptedRef?.accepted_output_hash ?? canonicalHash(output));
  const narrativeText = skip
    ? language === "zh"
      ? "本轮没有符合该角色合同的可评价对象，因此运行时未调用模型并确定性跳过该阶段。该结果不是中性判断。"
      : "No object satisfied this role's evaluation contract, so runtime skipped the model call deterministically. This is not a neutral judgment."
    : renderStructuredNarrative(layer, agentId, asRecord(output), language);
  const idBody = {
    schema_version: AGENT_DISPLAY_NARRATIVE_SCHEMA_VERSION,
    agent_id: agentId,
    layer,
    language,
    source,
    source_output_id: sourceOutputId,
    source_output_hash: sourceOutputHash,
    narrative_text: narrativeText,
    ui_only: true as const,
  };
  return {
    ...idBody,
    narrative_id: `agent-display:${canonicalHash(idBody).slice("sha256:".length)}`,
  };
}

function outputFor(state: NarrativeState, layer: Layer, agentId: string): unknown {
  if (layer === "macro") return state.layer1_outputs[agentId];
  if (layer === "sector") return state.layer2_outputs[agentId];
  if (layer === "superinvestor") return state.layer3_outputs[agentId];
  return state.layer4_outputs[
    agentId as "cro" | "alpha_discovery" | "autonomous_execution" | "cio"
  ];
}

function acceptedRefsFor(state: NarrativeState, agentId: string): AcceptedOutputRecordRef[] {
  return Object.values(state.accepted_output_refs).filter(
    (ref): ref is AcceptedOutputRecordRef => ref.agent_id === agentId,
  );
}

function selectedAcceptedRef(
  agentId: string,
  refs: AcceptedOutputRecordRef[],
): AcceptedOutputRecordRef | undefined {
  if (agentId === "cio") {
    const finalRefs = refs.filter((ref) => ref.accepted_output_kind === "CIO_FINAL");
    if (finalRefs.length > 1) {
      throw new Error("cio: display narrative has duplicate final accepted-output refs");
    }
    return finalRefs[0];
  }
  if (refs.length > 1) {
    throw new Error(`${agentId}: display narrative has duplicate accepted-output refs`);
  }
  return refs[0];
}

function acceptedPayloadFor(
  state: NarrativeState,
  agentId: string,
  language: Language,
  ref: AcceptedOutputRecordRef,
  store: AcceptedAgentOutputStore | undefined,
): unknown {
  if (!store) {
    throw new Error(
      `${agentId}: production display narrative accepted-output store is unavailable`,
    );
  }
  const record = store.resolve(ref) as AcceptedAgentOutputRecord;
  const scheduleAsOf = state.outcome_schedule_plan?.as_of;
  if (
    record.graph_run_id !== state.trace_id ||
    record.cohort_id !== state.active_cohort ||
    !scheduleAsOf ||
    record.as_of !== scheduleAsOf ||
    record.as_of.slice(0, 10) !== state.as_of_date ||
    record.language !== language
  ) {
    throw new Error(`${agentId}: production display narrative accepted-output owner mismatch`);
  }
  return record.output.payload;
}

function acceptedNarrativeProjection(
  agentId: string,
  kind: AcceptedOutputRecordRef["accepted_output_kind"],
  payload: Record<string, unknown>,
): Record<string, unknown> {
  const nestedField =
    kind === "STANDARD_SECTOR_SELECTION" ||
    kind === "SUPERINVESTOR_SELECTION" ||
    kind === "ALPHA_DISCOVERY"
      ? "selection"
      : kind === "CRO_RISK_REVIEW"
        ? "review"
        : kind === "EXECUTION_ASSESSMENT"
          ? "assessment"
          : kind === "CIO_PROPOSAL" || kind === "CIO_FINAL"
            ? "decision"
            : null;
  if (nestedField === null) return payload;
  const nested = payload[nestedField];
  if (!isRecord(nested)) {
    throw new Error(`${agentId}: accepted display payload lacks ${nestedField}`);
  }
  return {
    ...nested,
    confidence: payload.model_confidence ?? payload.directional_confidence,
  };
}

function renderStructuredNarrative(
  layer: Layer,
  agentId: string,
  output: Record<string, unknown>,
  language: Language,
): string {
  const parts =
    layer === "macro"
      ? macroParts(output, language)
      : layer === "sector"
        ? sectorParts(agentId, output, language)
        : layer === "superinvestor"
          ? superinvestorParts(output, language)
          : decisionParts(agentId, output, language);
  const claims = claimStatements(output).slice(0, 3);
  if (claims.length > 0) {
    parts.push(section(language, "Evidence", "证据结论", claims));
  }
  return truncate(parts.filter(Boolean).join("\n"), 2_000);
}

function macroParts(output: Record<string, unknown>, language: Language): string[] {
  const conclusion =
    language === "zh"
      ? `结论：${text(output.direction)}，强度 ${text(output.strength)}/5，周期 ${text(output.persistence_horizon)}，置信度 ${pct(output.confidence)}。`
      : `Decision: ${text(output.direction)}, strength ${text(output.strength)}/5, horizon ${text(output.persistence_horizon)}, confidence ${pct(output.confidence)}.`;
  return [
    conclusion,
    section(language, "Transmission", "传导渠道", stringItems(output.channels).slice(0, 5)),
    section(language, "Drivers", "主要驱动", summaryItems(output.key_drivers).slice(0, 4)),
  ];
}

function sectorParts(
  agentId: string,
  output: Record<string, unknown>,
  language: Language,
): string[] {
  if (agentId === "relationship_mapper") {
    const status = text(output.predictive_graph_status);
    const factual = arrayItems(output.factual_edges).length;
    const predictive = arrayItems(output.predictive_edges).length;
    return [
      language === "zh"
        ? `结论：${status}；事实关系 ${factual} 条，可评价预测关系 ${predictive} 条。`
        : `Decision: ${status}; ${factual} factual and ${predictive} evaluable predictive relationships.`,
      section(
        language,
        "Predictive links",
        "预测关系",
        relationshipItems(output.predictive_edges, language).slice(0, 4),
      ),
      section(language, "Drivers", "主要驱动", summaryItems(output.key_drivers).slice(0, 4)),
      section(language, "Risks", "主要风险", summaryItems(output.risks).slice(0, 3)),
    ];
  }
  const preferred = directionName(output.preferred_direction);
  const least = directionName(output.least_preferred_direction);
  const longs = pickItems(output.long_picks, language);
  const avoids = pickItems(output.short_or_avoid_picks, language);
  return [
    language === "zh"
      ? `结论：最看好 ${preferred}，最不看好 ${least}，周期 ${text(output.persistence_horizon)}，置信度 ${pct(output.confidence)}。`
      : `Decision: preferred ${preferred}, least preferred ${least}, horizon ${text(output.persistence_horizon)}, confidence ${pct(output.confidence)}.`,
    section(language, "Drivers", "主要驱动", summaryItems(output.key_drivers).slice(0, 4)),
    section(
      language,
      "Preferred rationale",
      "看好逻辑",
      directionThesis(output.preferred_direction),
    ),
    section(
      language,
      "Least-preferred rationale",
      "看空逻辑",
      directionThesis(output.least_preferred_direction),
    ),
    section(language, "Long candidates", "看好标的", longs.slice(0, 5)),
    section(language, "Short or avoid", "看空或回避", avoids.slice(0, 5)),
    section(language, "Risks", "主要风险", summaryItems(output.risks).slice(0, 3)),
  ];
}

function superinvestorParts(output: Record<string, unknown>, language: Language): string[] {
  return [
    language === "zh"
      ? `结论：${text(output.selection_status)}，持有期 ${text(output.holding_period)}，置信度 ${pct(output.confidence)}。`
      : `Decision: ${text(output.selection_status)}, holding period ${text(output.holding_period)}, confidence ${pct(output.confidence)}.`,
    section(language, "Drivers", "主要驱动", summaryItems(output.key_drivers).slice(0, 4)),
    section(language, "Candidates", "候选标的", pickItems(output.picks, language).slice(0, 6)),
    section(language, "Risks", "主要风险", summaryItems(output.risks).slice(0, 3)),
  ];
}

function decisionParts(
  agentId: string,
  output: Record<string, unknown>,
  language: Language,
): string[] {
  if (agentId === "cro") {
    const actions = output.candidate_actions ?? output.rejected_picks;
    return [
      language === "zh"
        ? `结论：${text(output.review_disposition)}，风险处置 ${arrayItems(actions).length} 项，置信度 ${pct(output.confidence)}。`
        : `Decision: ${text(output.review_disposition)}, ${arrayItems(actions).length} risk actions, confidence ${pct(output.confidence)}.`,
      section(language, "Risk actions", "风险处置", riskActionItems(actions).slice(0, 5)),
      section(
        language,
        "Required adjustments",
        "必要调整",
        reasonItems(output.required_adjustments).slice(0, 5),
      ),
      section(
        language,
        "Correlated risks",
        "相关风险",
        summaryItems(output.correlated_risks).slice(0, 4),
      ),
      section(
        language,
        "Black swans",
        "黑天鹅情景",
        summaryItems(output.black_swan_scenarios).slice(0, 3),
      ),
    ];
  }
  if (agentId === "alpha_discovery") {
    return [
      language === "zh"
        ? `结论：${text(output.discovery_disposition)}，发现 ${arrayItems(output.novel_picks).length} 个增量候选，置信度 ${pct(output.confidence)}。`
        : `Decision: ${text(output.discovery_disposition)}, ${arrayItems(output.novel_picks).length} incremental candidates, confidence ${pct(output.confidence)}.`,
      section(
        language,
        "Candidates",
        "增量候选",
        alphaPickItems(output.novel_picks, language).slice(0, 6),
      ),
    ];
  }
  if (agentId === "autonomous_execution") {
    const assessments = output.order_assessments ?? output.trades;
    return [
      language === "zh"
        ? `结论：${text(output.execution_disposition)}，订单评估 ${arrayItems(assessments).length} 笔，置信度 ${pct(output.confidence)}。`
        : `Decision: ${text(output.execution_disposition)}, ${arrayItems(assessments).length} order assessments, confidence ${pct(output.confidence)}.`,
      section(
        language,
        "Order assessments",
        "订单评估",
        executionAssessmentItems(assessments).slice(0, 8),
      ),
      section(language, "Checks", "执行检查", reasonItems(output.execution_checks).slice(0, 5)),
    ];
  }
  const positions = output.target_positions ?? output.portfolio_actions;
  return [
    language === "zh"
      ? `结论：${text(output.decision_disposition)}，目标持仓 ${arrayItems(positions).length} 项，置信度 ${pct(output.confidence)}。${optionalSentence(output.decision_reason)}`
      : `Decision: ${text(output.decision_disposition)}, ${arrayItems(positions).length} target positions, confidence ${pct(output.confidence)}.${optionalSentence(output.decision_reason)}`,
    section(language, "Portfolio", "组合动作", portfolioItems(positions, language).slice(0, 10)),
  ];
}

function section(language: Language, en: string, zh: string, values: string[]): string {
  if (values.length === 0) return "";
  return language === "zh" ? `${zh}：${values.join("；")}。` : `${en}: ${values.join("; ")}.`;
}

function claimStatements(output: Record<string, unknown>): string[] {
  return arrayItems(output.claims).flatMap((claim) => {
    const statement = claim.statement;
    return typeof statement === "string" && statement.trim() ? [clean(statement)] : [];
  });
}

function summaryItems(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string" && item.trim()) return [clean(item)];
    if (!isRecord(item)) return [];
    const summary = item.summary;
    return typeof summary === "string" && summary.trim() ? [clean(summary)] : [];
  });
}

function pickItems(value: unknown, language: Language): string[] {
  return arrayItems(value).flatMap((item) => {
    const ticker = item.ts_code ?? item.ticker;
    if (typeof ticker !== "string" || !ticker.trim()) return [];
    const action = typeof item.position_action === "string" ? item.position_action : "";
    const conviction = typeof item.conviction === "number" ? ` ${pct(item.conviction)}` : "";
    const thesis =
      typeof item.thesis === "string"
        ? `${language === "zh" ? "：" : ": "}${clean(item.thesis)}`
        : "";
    return [`${clean(ticker)}${action ? ` ${action}` : ""}${conviction}${thesis}`];
  });
}

function alphaPickItems(value: unknown, language: Language): string[] {
  return arrayItems(value).flatMap((item) => {
    const ticker = item.ts_code ?? item.ticker;
    if (typeof ticker !== "string") return [];
    const why =
      typeof item.thesis === "string"
        ? item.thesis
        : typeof item.why_missed_by_others === "string"
          ? item.why_missed_by_others
          : "";
    return [`${clean(ticker)}${why ? `${language === "zh" ? "：" : ": "}${clean(why)}` : ""}`];
  });
}

function executionAssessmentItems(value: unknown): string[] {
  return arrayItems(value).flatMap((item) => {
    const ticker = item.ts_code ?? item.ticker;
    if (typeof ticker !== "string") return [];
    if (typeof item.feasibility === "string") {
      const delta =
        typeof item.requested_delta_weight === "number"
          ? ` ${pct(item.requested_delta_weight)}`
          : "";
      const cost =
        typeof item.predicted_cost_bps === "number" ? ` ${item.predicted_cost_bps}bps` : "";
      const reason = typeof item.reason === "string" ? `: ${clean(item.reason)}` : "";
      return [`${clean(ticker)} ${clean(item.feasibility)}${delta}${cost}${reason}`];
    }
    return [
      `${clean(ticker)} ${text(item.action)} ${typeof item.size_pct === "number" ? pct(item.size_pct) : ""}`.trim(),
    ];
  });
}

function portfolioItems(value: unknown, language: Language): string[] {
  return arrayItems(value).flatMap((item) => {
    const ticker = item.ts_code ?? item.ticker;
    if (typeof ticker !== "string") return [];
    const target = typeof item.target_weight === "number" ? pct(item.target_weight) : "-";
    const action = item.position_decision ?? item.action;
    const note =
      typeof item.position_decision_reason === "string"
        ? `${language === "zh" ? "：" : ": "}${clean(item.position_decision_reason)}`
        : "";
    return [`${clean(ticker)} ${text(action)} → ${target}${note}`];
  });
}

function riskActionItems(value: unknown): string[] {
  return arrayItems(value).flatMap((item) => {
    const ticker = item.ts_code ?? item.ticker;
    const reason = typeof item.reason === "string" ? clean(item.reason) : "";
    const action = typeof item.action === "string" ? clean(item.action) : "";
    if (!reason && !action) return [];
    return [
      [typeof ticker === "string" ? clean(ticker) : "", action, reason].filter(Boolean).join(" "),
    ];
  });
}

function reasonItems(value: unknown): string[] {
  return arrayItems(value).flatMap((item) => {
    const reason = item.reason;
    if (typeof reason !== "string" || !reason.trim()) return [];
    const ticker = typeof item.ticker === "string" ? `${clean(item.ticker)} ` : "";
    return [`${ticker}${clean(reason)}`];
  });
}

function directionName(value: unknown): string {
  if (!isRecord(value)) return "-";
  return text(value.direction_id ?? value.status);
}

function directionThesis(value: unknown): string[] {
  if (!isRecord(value) || typeof value.thesis !== "string" || !value.thesis.trim()) return [];
  return [clean(value.thesis)];
}

function relationshipItems(value: unknown, language: Language): string[] {
  return arrayItems(value).flatMap((item) => {
    if (typeof item.source_entity !== "string" || typeof item.target_entity !== "string") return [];
    const trigger =
      typeof item.activation_trigger === "string"
        ? `${language === "zh" ? "；触发条件：" : "; trigger: "}${clean(item.activation_trigger)}`
        : "";
    return [
      `${clean(item.source_entity)} → ${clean(item.target_entity)} (${text(item.transmission_direction)})${trigger}`,
    ];
  });
}

function stringItems(value: unknown): string[] {
  return Array.isArray(value)
    ? value.flatMap((item) => (typeof item === "string" && item.trim() ? [clean(item)] : []))
    : [];
}

function arrayItems(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function asRecord(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) throw new Error("Agent display narrative requires a structured output");
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function pct(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(0)}%` : "-";
}

function text(value: unknown): string {
  if (typeof value === "string" && value.trim()) return clean(value);
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return "-";
}

function optionalSentence(value: unknown): string {
  return typeof value === "string" && value.trim() ? ` ${clean(value)}` : "";
}

function clean(value: string): string {
  const printable = Array.from(value, (char) =>
    char >= " " && char !== "\u007f" ? char : " ",
  ).join("");
  return truncate(printable.replace(/\s+/g, " ").trim(), 320);
}

function truncate(value: string, max: number): string {
  return value.length <= max ? value : `${value.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
}

function requiredText(value: string, field: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error(`agent display narrative requires ${field}`);
  return normalized;
}
