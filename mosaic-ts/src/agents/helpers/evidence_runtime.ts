import { createHash } from "node:crypto";
import {
  type ClaimEvidenceGraph,
  type EvidenceLedgerEntry,
  type LlmResearchClaim,
  LlmResearchClaimSchema,
  type RecommendationClaimReference,
  type ResearchClaim,
  validateClaimEvidenceGraph,
} from "../evidence_contract.js";
import { AGENTS_BY_LAYER } from "../prompts/cohorts.js";
import type { RuntimeAgentStageId } from "../prompts/runtime_agent_spec.js";
import type { DailyCycleStateType } from "../state.js";
import type {
  ResearchKnobsSnapshot,
  RuntimeSourceEvidenceObservation,
  RuntimeSourceStatus,
  ToolStatus,
} from "./research_knobs.js";

export interface RuntimeEvidenceSnapshot {
  runId: string;
  agentId: string;
  agentInvocationId: string;
  stage: RuntimeAgentStageId;
  snapshotHash: string;
  evidenceLedger: EvidenceLedgerEntry[];
  evidenceById: ReadonlyMap<string, EvidenceLedgerEntry>;
  allowedResearchRuleIds: ReadonlySet<string>;
  visibleCatalog: string;
}

export interface ClaimGraphSelection<T> {
  output: T;
  graph: ClaimEvidenceGraph;
  rawOutputAccepted: boolean;
  rejectionReasons: string[];
}

export function attachRuntimeOwnedFallbackClaims<T>(input: {
  output: T;
  sourceOutput: unknown;
  stage: RuntimeAgentStageId;
  fallbackReasonCode: string;
  rejectionReasons: ReadonlyArray<string>;
  statement: string;
}): T {
  const sourceRecord =
    input.sourceOutput !== null &&
    typeof input.sourceOutput === "object" &&
    !Array.isArray(input.sourceOutput)
      ? (input.sourceOutput as Record<string, unknown>)
      : null;
  const sourceGraph = sourceRecord?.verified_claim_graph as ClaimEvidenceGraph | undefined;
  if (!sourceGraph) return input.output;
  const fallbackEvidenceId = sourceGraph.evidence_ledger[0]?.evidence_id;
  if (!fallbackEvidenceId) return input.output;

  const claimId = `runtime-fallback:${input.stage}:${sourceGraph.run_id}`;
  const withRefs = withFallbackClaimRefs(input.output, claimId, fallbackEvidenceId);
  if (withRefs === null || typeof withRefs !== "object" || Array.isArray(withRefs)) {
    return input.output;
  }
  const record = withRefs as Record<string, unknown>;
  const fallbackClaim: LlmResearchClaim = {
    claim_id: claimId,
    claim_kind: "RISK_FLAG",
    statement: input.statement,
    structured_conclusion: { action_policy: "conservative_fallback" },
    evidence_ids: [fallbackEvidenceId],
    research_rule_refs: [],
  };
  record.claims = [fallbackClaim];
  const references = outputClaimReferences(record, input.stage);
  const graph: ClaimEvidenceGraph = {
    schema_version: "evidence_claim_graph_v1",
    run_id: sourceGraph.run_id,
    snapshot_hash: sourceGraph.snapshot_hash,
    evidence_ledger: sourceGraph.evidence_ledger,
    claims: [fallbackClaim],
    recommendation_claim_refs: references.references,
  };
  const runtimeEvidenceById = new Map(
    sourceGraph.evidence_ledger.map((entry) => [entry.evidence_id, entry]),
  );
  const validation = validateClaimEvidenceGraph(graph, {
    expectedRunId: sourceGraph.run_id,
    expectedSnapshotHash: sourceGraph.snapshot_hash,
    runtimeOwnedEvidenceById: runtimeEvidenceById,
    requiredOutputIds: references.requiredOutputIds,
    allowRiskFlagOnlyOutputIds: references.requiredOutputIds,
  });
  if (!validation.accepted) {
    throw new Error(`runtime_owned_fallback_claim_graph_invalid:${validation.reasons.join(";")}`);
  }
  const priorReasons = (
    sourceRecord?.verified_claim_audit as { rejection_reasons?: unknown } | undefined
  )?.rejection_reasons;
  return attachVerifiedClaimEnvelope(withRefs, graph, {
    raw_output_accepted: false,
    rejection_reasons: [
      ...(Array.isArray(priorReasons)
        ? priorReasons.filter((reason): reason is string => typeof reason === "string")
        : []),
      ...input.rejectionReasons,
    ],
    fallback_reason_code: input.fallbackReasonCode,
  });
}

const RUNTIME_SOURCE_ALIASES: Readonly<Record<string, string>> = {
  current_market_data: "current_market_data",
  current_position_snapshot: "current_position_snapshot",
  mirofish_context: "mirofish_context",
  upstream_context: "upstream_agent_outputs",
};

const SECTOR_PICK_AGENTS = new Set([
  "semiconductor",
  "technology",
  "energy",
  "biotech",
  "consumer",
  "industrials",
  "real_estate_construction",
  "financials",
  "agriculture",
]);
const SUPERINVESTOR_AGENTS = new Set<string>(AGENTS_BY_LAYER.superinvestor);

export function buildAgentInvocationId(input: {
  runId: string;
  agent: string;
  stage: RuntimeAgentStageId;
  cohort: string;
  asOf: string;
  snapshotHash: string;
}): string {
  const digest = canonicalHash({ schema_version: "agent_invocation_id_v1", ...input });
  return `agent-invocation:${digest.slice("sha256:".length)}`;
}

export function buildRuntimeEvidenceSnapshot(input: {
  state: DailyCycleStateType;
  agent: string;
  stage: RuntimeAgentStageId;
  knobSnapshot?: ResearchKnobsSnapshot | null;
  toolStatuses?: ReadonlyArray<ToolStatus>;
}): RuntimeEvidenceSnapshot {
  const runId = input.state.trace_id || input.state.as_of_date || "current_run";
  const snapshotHash =
    input.knobSnapshot?.hash ??
    canonicalHash({
      schema_version: "runtime_evidence_snapshot_v2",
      run_id: runId,
      agent: input.agent,
      stage: input.stage,
      tool_statuses: input.toolStatuses ?? [],
    });
  const agentInvocationId = buildAgentInvocationId({
    runId,
    agent: input.agent,
    stage: input.stage,
    cohort: input.state.active_cohort || "cohort_default",
    asOf: input.state.as_of_date || "live",
    snapshotHash,
  });
  const evidenceLedger: EvidenceLedgerEntry[] = [];
  const seen = new Set<string>();
  const evidenceRegistry =
    input.knobSnapshot?.knobs.evidence_registry ??
    Object.fromEntries(
      [...new Set((input.toolStatuses ?? []).map((status) => status.name))].map((name) => [
        name,
        { tool: name, metric: `${name}_snapshot` },
      ]),
    );
  for (const [evidenceKey, registryEntry] of Object.entries(evidenceRegistry)) {
    if (registryEntry.tool) {
      const statuses = (input.toolStatuses ?? []).filter(
        (status) => status.name === registryEntry.tool,
      );
      for (const status of statuses) {
        const entry = toolEvidenceEntry({
          status,
          evidenceKey,
          metric: registryEntry.metric,
          runId,
          agentInvocationId,
          snapshotHash,
          asOf: input.state.as_of_date || "live",
        });
        appendUniqueEvidence(evidenceLedger, seen, entry);
      }
      continue;
    }
    const sourceId = runtimeSourceId(evidenceKey, registryEntry.metric);
    const statuses = (input.knobSnapshot?.consumptionSnapshot.runtimeSourceStatuses ?? []).filter(
      (status) => status.source_id === sourceId,
    );
    for (const status of statuses) {
      const entry = runtimeSourceEvidenceEntry({
        state: input.state,
        status,
        sourceId,
        metric: registryEntry.metric,
        runId,
        agentInvocationId,
        snapshotHash,
      });
      appendUniqueEvidence(evidenceLedger, seen, entry);
    }
  }
  evidenceLedger.sort((left, right) => left.evidence_id.localeCompare(right.evidence_id));
  const evidenceById = new Map(evidenceLedger.map((entry) => [entry.evidence_id, entry]));
  const allowedResearchRuleIds = input.knobSnapshot
    ? researchRuleIds(input.knobSnapshot)
    : new Set<string>();
  return {
    runId,
    agentId: input.agent,
    agentInvocationId,
    stage: input.stage,
    snapshotHash,
    evidenceLedger,
    evidenceById,
    allowedResearchRuleIds,
    visibleCatalog: renderRuntimeEvidenceCatalog(
      evidenceLedger,
      allowedResearchRuleIds,
      agentInvocationId,
    ),
  };
}

export function selectOutputByClaimEvidence<T>(
  rawOutput: T,
  fallbackFactory: () => T,
  runtime: RuntimeEvidenceSnapshot,
): ClaimGraphSelection<T> {
  const rawGraph = claimGraphFromOutput(rawOutput, runtime);
  if (rawGraph.graph) {
    const validation = validateClaimEvidenceGraph(rawGraph.graph, {
      expectedRunId: runtime.runId,
      expectedSnapshotHash: runtime.snapshotHash,
      runtimeOwnedEvidenceById: runtime.evidenceById,
      requiredOutputIds: rawGraph.requiredOutputIds,
      allowedResearchRuleIds: runtime.allowedResearchRuleIds,
    });
    if (validation.accepted) {
      return {
        output: attachVerifiedClaimEnvelope(rawOutput, rawGraph.graph, {
          raw_output_accepted: true,
          rejection_reasons: [],
        }),
        graph: rawGraph.graph,
        rawOutputAccepted: true,
        rejectionReasons: [],
      };
    }
    return deterministicFallbackSelection(
      fallbackFactory(),
      runtime,
      validation.reasons,
      "CLAIM_EVIDENCE_GRAPH_REJECTED",
    );
  }
  return deterministicFallbackSelection(
    fallbackFactory(),
    runtime,
    rawGraph.reasons,
    "CLAIM_EVIDENCE_GRAPH_REJECTED",
  );
}

/** Pure validation path used by strict production runs. It never substitutes output. */
export function validateOutputByClaimEvidence<T>(
  rawOutput: T,
  runtime: RuntimeEvidenceSnapshot,
  options: { allowRiskFlagOnly?: boolean } = {},
): ClaimGraphSelection<T> {
  const rawGraph = claimGraphFromOutput(rawOutput, runtime);
  if (!rawGraph.graph) {
    return {
      output: rawOutput,
      graph: emptyClaimGraph(runtime),
      rawOutputAccepted: false,
      rejectionReasons: rawGraph.reasons,
    };
  }
  const validation = validateClaimEvidenceGraph(rawGraph.graph, {
    expectedRunId: runtime.runId,
    expectedSnapshotHash: runtime.snapshotHash,
    runtimeOwnedEvidenceById: runtime.evidenceById,
    requiredOutputIds: rawGraph.requiredOutputIds,
    ...(isExplicitEmptyDisposition(rawOutput) || options.allowRiskFlagOnly
      ? { allowRiskFlagOnlyOutputIds: rawGraph.requiredOutputIds }
      : {}),
    allowedResearchRuleIds: runtime.allowedResearchRuleIds,
  });
  if (!validation.accepted) {
    return {
      output: rawOutput,
      graph: rawGraph.graph,
      rawOutputAccepted: false,
      rejectionReasons: validation.reasons,
    };
  }
  return {
    output: attachVerifiedClaimEnvelope(rawOutput, rawGraph.graph, {
      raw_output_accepted: true,
      rejection_reasons: [],
    }),
    graph: rawGraph.graph,
    rawOutputAccepted: true,
    rejectionReasons: [],
  };
}

function isExplicitEmptyDisposition(output: unknown): boolean {
  if (output === null || typeof output !== "object" || Array.isArray(output)) return false;
  const record = output as Record<string, unknown>;
  return ["NO_QUALIFIED_CANDIDATES", "NO_OBJECTION", "NONE_FOUND", "NO_DELTA", "BLOCKED"].some(
    (value) => Object.values(record).includes(value),
  );
}

function emptyClaimGraph(runtime: RuntimeEvidenceSnapshot): ClaimEvidenceGraph {
  return {
    schema_version: "evidence_claim_graph_v1",
    run_id: runtime.runId,
    snapshot_hash: runtime.snapshotHash,
    evidence_ledger: runtime.evidenceLedger,
    claims: [],
    recommendation_claim_refs: [],
  };
}

export function attachDeterministicFallbackClaimGraph<T>(
  fallbackOutput: T,
  runtime: RuntimeEvidenceSnapshot,
  rejectionReasons: ReadonlyArray<string>,
  fallbackReasonCode: string,
): ClaimGraphSelection<T> {
  return deterministicFallbackSelection(
    fallbackOutput,
    runtime,
    [...rejectionReasons],
    fallbackReasonCode,
  );
}

export function renderRuntimeEvidenceCatalog(
  entries: ReadonlyArray<EvidenceLedgerEntry>,
  allowedResearchRuleIds: ReadonlySet<string>,
  agentInvocationId: string,
): string {
  const evidence = entries.map((entry) => ({
    evidence_id: entry.evidence_id,
    source_kind: entry.source_kind,
    tool_or_source: entry.tool_or_source,
    metric: entry.metric,
    value: visibleEvidenceValue(entry),
    unit: entry.unit,
    as_of: entry.as_of,
    freshness: entry.freshness,
    fallback: entry.fallback,
    direction: entry.direction,
  }));
  return [
    "Runtime-owned evidence catalog (use only these evidence_id values):",
    JSON.stringify(
      {
        agent_invocation_id: agentInvocationId,
        evidence,
        allowed_research_rule_ids: [...allowedResearchRuleIds].sort(),
      },
      null,
      2,
    ),
  ].join("\n");
}

function toolEvidenceEntry(input: {
  status: ToolStatus;
  evidenceKey: string;
  metric: string;
  runId: string;
  agentInvocationId: string;
  snapshotHash: string;
  asOf: string;
}): EvidenceLedgerEntry {
  const sourceFingerprint = validSha256(input.status.source_fingerprint)
    ? input.status.source_fingerprint
    : canonicalHash({
        schema_version: "tool_source_fingerprint_v1",
        tool: input.status.name,
        args_fingerprint: input.status.args_fingerprint ?? input.status.fingerprint ?? null,
        result_fingerprint: input.status.result_fingerprint ?? null,
        failed: input.status.failed,
        missing: input.status.missing,
        fallback: input.status.fallback,
        as_of: input.status.as_of ?? null,
      });
  const freshness = input.status.failed
    ? "tool_failed"
    : input.status.missing
      ? "missing"
      : input.status.fallback
        ? "fallback"
        : "current";
  return {
    evidence_id: evidenceId(input.agentInvocationId, sourceFingerprint, input.metric, "tool"),
    run_id: input.runId,
    snapshot_hash: input.snapshotHash,
    source_kind: "tool",
    tool_or_source: input.status.name,
    metric: input.metric,
    value: {
      evidence_key: input.evidenceKey,
      result_fingerprint: input.status.result_fingerprint ?? null,
      args_fingerprint: input.status.args_fingerprint ?? null,
    },
    unit: "result_snapshot",
    as_of: input.status.as_of ?? input.asOf,
    lookback: "tool_call",
    freshness,
    fallback: freshness === "fallback",
    source_fingerprint: sourceFingerprint,
    direction: "ambiguous",
    privacy_class: "private_runtime",
  };
}

function claimGraphFromOutput(
  output: unknown,
  runtime: RuntimeEvidenceSnapshot,
): {
  graph: ClaimEvidenceGraph | null;
  requiredOutputIds: ReadonlySet<string>;
  reasons: string[];
} {
  if (output === null || typeof output !== "object" || Array.isArray(output)) {
    return { graph: null, requiredOutputIds: new Set(), reasons: ["claim_output_not_object"] };
  }
  const record = output as Record<string, unknown>;
  const parsedClaims = LlmResearchClaimSchema.array().safeParse(record.claims);
  if (!parsedClaims.success) {
    return {
      graph: null,
      requiredOutputIds: new Set(),
      reasons: parsedClaims.error.issues.map(
        (issue) => `llm_claim_schema:${issue.path.join(".")}:${issue.message}`,
      ),
    };
  }
  const references = outputClaimReferences(record, runtime.stage, runtime.agentId);
  const claims: ResearchClaim[] = parsedClaims.data;
  return {
    graph: {
      schema_version: "evidence_claim_graph_v1",
      run_id: runtime.runId,
      snapshot_hash: runtime.snapshotHash,
      evidence_ledger: runtime.evidenceLedger,
      claims,
      recommendation_claim_refs: references.references,
    },
    requiredOutputIds: references.requiredOutputIds,
    reasons: [],
  };
}

function outputClaimReferences(
  record: Record<string, unknown>,
  stage: RuntimeAgentStageId,
  runtimeAgentId?: string,
): {
  references: RecommendationClaimReference[];
  requiredOutputIds: ReadonlySet<string>;
} {
  const agent =
    runtimeAgentId ??
    (typeof record.agent === "string"
      ? record.agent
      : typeof record.agent_id === "string"
        ? record.agent_id
        : "unknown");
  const configs =
    agent === "alpha_discovery"
      ? [{ field: "novel_picks", prefix: "novel_pick", type: "candidate" as const }]
      : agent === "cro"
        ? [
            {
              field: "candidate_actions",
              prefix: "cro_risk_action",
              type: "recommendation" as const,
            },
          ]
        : agent === "autonomous_execution"
          ? [
              {
                field: "order_assessments",
                prefix: "execution_assessment",
                type: "recommendation" as const,
              },
            ]
          : agent === "cio"
            ? [
                {
                  field: "target_positions",
                  prefix: "target_position",
                  type: "portfolio_action" as const,
                },
                ...(stage === "cio_final"
                  ? [
                      {
                        field: "cro_control_resolutions",
                        prefix: "cro_control_resolution",
                        type: "recommendation" as const,
                      },
                      {
                        field: "execution_control_resolutions",
                        prefix: "execution_control_resolution",
                        type: "recommendation" as const,
                      },
                    ]
                  : []),
              ]
            : SECTOR_PICK_AGENTS.has(agent)
              ? [
                  { field: "long_picks", prefix: "long_candidate", type: "candidate" as const },
                  {
                    field: "short_or_avoid_picks",
                    prefix: "short_or_avoid_candidate",
                    type: "candidate" as const,
                  },
                ]
              : SUPERINVESTOR_AGENTS.has(agent)
                ? [{ field: "picks", prefix: "pick", type: "candidate" as const }]
                : [];
  const references: RecommendationClaimReference[] = [];
  const requiredOutputIds = new Set<string>();
  if (agent !== "unknown") {
    const outputId = `recommendation:0:${agent}`;
    requiredOutputIds.add(outputId);
    const authoredRefs = record.claim_refs ?? macroSubmissionClaimRefs(record);
    const claimRefs = Array.isArray(authoredRefs)
      ? authoredRefs.filter((claimId): claimId is string => typeof claimId === "string")
      : [];
    if (claimRefs.length > 0) {
      references.push({
        output_id: outputId,
        output_type: "recommendation",
        claim_refs: claimRefs,
      });
    }
  }
  for (const config of configs) {
    const candidateEntries = record[config.field];
    const entries: unknown[] = Array.isArray(candidateEntries) ? candidateEntries : [];
    entries.forEach((entry, index) => {
      const item =
        entry !== null && typeof entry === "object" && !Array.isArray(entry)
          ? (entry as Record<string, unknown>)
          : {};
      const ticker =
        typeof item.ticker === "string"
          ? item.ticker
          : typeof item.ts_code === "string"
            ? item.ts_code
            : "unknown";
      const outputId = `${config.prefix}:${index}:${ticker}`;
      requiredOutputIds.add(outputId);
      const claimRefs = Array.isArray(item.claim_refs)
        ? item.claim_refs.filter((claimId): claimId is string => typeof claimId === "string")
        : [];
      if (claimRefs.length > 0) {
        references.push({ output_id: outputId, output_type: config.type, claim_refs: claimRefs });
      }
    });
  }
  return { references, requiredOutputIds };
}

function macroSubmissionClaimRefs(record: Record<string, unknown>): unknown {
  if (record.mode === "DIRECT") {
    const signal = record.signal;
    return signal && typeof signal === "object" && !Array.isArray(signal)
      ? (signal as Record<string, unknown>).claim_refs
      : undefined;
  }
  if (record.mode !== "COMPONENTS" || !Array.isArray(record.components)) {
    return undefined;
  }
  return [
    ...new Set(
      record.components.flatMap((component) => {
        if (component === null || typeof component !== "object" || Array.isArray(component)) {
          return [];
        }
        const claimRefs = (component as Record<string, unknown>).claim_refs;
        return Array.isArray(claimRefs)
          ? claimRefs.filter((claimRef): claimRef is string => typeof claimRef === "string")
          : [];
      }),
    ),
  ];
}

function deterministicFallbackSelection<T>(
  fallbackOutput: T,
  runtime: RuntimeEvidenceSnapshot,
  rejectionReasons: string[],
  fallbackReasonCode: string,
): ClaimGraphSelection<T> {
  const claimId = `runtime-fallback:${runtime.agentInvocationId}`;
  const fallbackEvidenceId = runtime.evidenceLedger[0]?.evidence_id;
  if (!fallbackEvidenceId) {
    throw new Error("deterministic_fallback_claim_graph_build_failed:no_runtime_evidence");
  }
  const output = withFallbackClaimRefs(fallbackOutput, claimId, fallbackEvidenceId);
  const graphParts = claimGraphFromOutput(output, runtime);
  if (!graphParts.graph) {
    throw new Error(
      `deterministic_fallback_claim_graph_build_failed:${graphParts.reasons.join(";")}`,
    );
  }
  const validation = validateClaimEvidenceGraph(graphParts.graph, {
    expectedRunId: runtime.runId,
    expectedSnapshotHash: runtime.snapshotHash,
    runtimeOwnedEvidenceById: runtime.evidenceById,
    requiredOutputIds: graphParts.requiredOutputIds,
    allowRiskFlagOnlyOutputIds: graphParts.requiredOutputIds,
    allowedResearchRuleIds: runtime.allowedResearchRuleIds,
  });
  if (!validation.accepted) {
    throw new Error(`deterministic_fallback_claim_graph_invalid:${validation.reasons.join(";")}`);
  }
  return {
    output: attachVerifiedClaimEnvelope(output, graphParts.graph, {
      raw_output_accepted: false,
      rejection_reasons: [...rejectionReasons],
      fallback_reason_code: fallbackReasonCode,
    }),
    graph: graphParts.graph,
    rawOutputAccepted: false,
    rejectionReasons: [...rejectionReasons],
  };
}

function withFallbackClaimRefs<T>(output: T, claimId: string, evidenceId: string): T {
  if (output === null || typeof output !== "object" || Array.isArray(output)) return output;
  const record = { ...(output as Record<string, unknown>) };
  record.claim_refs = [claimId];
  if (record.agent === "cio") record.decision_claim_refs = [claimId];
  record.claims = [
    {
      claim_id: claimId,
      claim_kind: "RISK_FLAG",
      statement: "Runtime selected a conservative fallback because raw evidence validation failed.",
      structured_conclusion: { action_policy: "conservative_fallback" },
      evidence_ids: [evidenceId],
      research_rule_refs: [],
    },
  ];
  for (const field of [
    "novel_picks",
    "candidate_actions",
    "order_assessments",
    "target_positions",
    "cro_control_resolutions",
    "execution_control_resolutions",
    "long_picks",
    "short_or_avoid_picks",
  ]) {
    if (!Array.isArray(record[field])) continue;
    record[field] = record[field].map((entry) =>
      entry !== null && typeof entry === "object" && !Array.isArray(entry)
        ? { ...(entry as Record<string, unknown>), claim_refs: [claimId] }
        : entry,
    );
  }
  return record as T;
}

function attachVerifiedClaimEnvelope<T>(
  output: T,
  graph: ClaimEvidenceGraph,
  audit: {
    raw_output_accepted: boolean;
    rejection_reasons: string[];
    fallback_reason_code?: string;
  },
): T {
  if (output === null || typeof output !== "object" || Array.isArray(output)) return output;
  return {
    ...(output as Record<string, unknown>),
    verified_claim_graph: graph,
    verified_claim_audit: audit,
  } as T;
}

function runtimeSourceEvidenceEntry(input: {
  state: DailyCycleStateType;
  status: RuntimeSourceStatus;
  sourceId: string;
  metric: string;
  runId: string;
  agentInvocationId: string;
  snapshotHash: string;
}): EvidenceLedgerEntry {
  const observation = sourceObservation(input.state, input.sourceId, input.status.scope);
  const sourceFingerprint = validSha256(observation?.source_fingerprint)
    ? observation.source_fingerprint
    : validSha256(input.status.snapshot_hash)
      ? input.status.snapshot_hash
      : canonicalHash({ schema_version: "runtime_source_fingerprint_v1", ...input.status });
  const freshness = runtimeFreshness(input.status.status);
  return {
    evidence_id: evidenceId(
      input.agentInvocationId,
      sourceFingerprint,
      input.metric,
      input.status.scope,
    ),
    run_id: input.runId,
    snapshot_hash: input.snapshotHash,
    source_kind: "runtime_source",
    tool_or_source: input.sourceId,
    metric: input.metric,
    value: observation?.value ?? sourceValue(input.state, input.sourceId, input.status),
    unit: observation?.unit ?? "snapshot",
    as_of: observation?.as_of ?? input.status.as_of ?? (input.state.as_of_date || "live"),
    lookback: observation?.lookback ?? "point_in_time",
    freshness,
    fallback: false,
    source_fingerprint: sourceFingerprint,
    direction: observation?.direction ?? "ambiguous",
    privacy_class: observation?.privacy_class ?? "private_runtime",
  };
}

function sourceValue(
  state: DailyCycleStateType,
  sourceId: string,
  status: RuntimeSourceStatus,
): unknown {
  const runtime = state.layer4_outputs?.runtime;
  if (sourceId === "current_position_snapshot") return state.current_positions;
  if (sourceId === "previous_target_state") return state.layer4_outputs?.previous_target_state;
  if (sourceId === "candidate_target_state") return runtime?.candidate_target_state;
  if (sourceId === "position_review_state") return runtime?.position_review_state;
  if (sourceId === "portfolio_exposure_state") return runtime?.portfolio_exposure_state;
  if (sourceId === "cro_review_state") return runtime?.cro_review_state;
  if (sourceId === "execution_feasibility_state") return runtime?.execution_feasibility_state;
  if (sourceId === "upstream_agent_outputs") {
    const agent = status.scope.match(/(?:^|\|)agent:([^|]+)/)?.[1];
    if (agent) {
      return (
        state.layer1_outputs[agent] ??
        state.layer2_outputs[agent] ??
        state.layer3_outputs[agent] ??
        (agent === "alpha_discovery" ? state.layer4_outputs.alpha_discovery : undefined) ??
        statusSummary(status)
      );
    }
  }
  return statusSummary(status);
}

function statusSummary(status: RuntimeSourceStatus): Record<string, unknown> {
  return {
    scope: status.scope,
    status: status.status,
    snapshot_hash: status.snapshot_hash ?? null,
    error_code: status.error_code ?? null,
  };
}

function sourceObservation(
  state: DailyCycleStateType,
  sourceId: string,
  scope: string,
): RuntimeSourceEvidenceObservation | undefined {
  return state.layer4_outputs?.runtime?.source_evidence_observations?.find(
    (entry) => entry.source_id === sourceId && entry.scope === scope,
  );
}

function runtimeSourceId(evidenceKey: string, metric: string): string {
  return RUNTIME_SOURCE_ALIASES[evidenceKey] ?? RUNTIME_SOURCE_ALIASES[metric] ?? evidenceKey;
}

function runtimeFreshness(status: RuntimeSourceStatus["status"]): EvidenceLedgerEntry["freshness"] {
  if (status === "loaded" || status === "empty_confirmed") return "current";
  if (status === "stale") return "stale";
  if (status === "source_error") return "tool_failed";
  return "missing";
}

function researchRuleIds(snapshot: ResearchKnobsSnapshot): ReadonlySet<string> {
  const ids = new Set<string>();
  for (const target of snapshot.knobs.mutation_targets) {
    const ruleId = target.path.match(/\/rules\/([^/]+)\//)?.[1];
    if (ruleId) ids.add(ruleId);
  }
  return ids;
}

function appendUniqueEvidence(
  entries: EvidenceLedgerEntry[],
  seen: Set<string>,
  entry: EvidenceLedgerEntry,
): void {
  if (seen.has(entry.evidence_id)) return;
  seen.add(entry.evidence_id);
  entries.push(entry);
}

function evidenceId(
  agentInvocationId: string,
  sourceFingerprint: string,
  metric: string,
  scope: string,
): string {
  const hash = canonicalHash({
    schema_version: "runtime_evidence_id_v1",
    agent_invocation_id: agentInvocationId,
    source_fingerprint: sourceFingerprint,
    metric,
    scope,
  });
  return `evidence:${hash.slice("sha256:".length)}`;
}

function visibleEvidenceValue(entry: EvidenceLedgerEntry): unknown {
  if (entry.privacy_class === "licensed_private") {
    return { source_fingerprint: entry.source_fingerprint };
  }
  const rendered = JSON.stringify(entry.value);
  if (rendered.length <= 2_000) return entry.value;
  return {
    source_fingerprint: entry.source_fingerprint,
    value_truncated: true,
    original_chars: rendered.length,
  };
}

function validSha256(value: string | undefined): value is string {
  return Boolean(value && /^sha256:[0-9a-f]{64}$/.test(value));
}

function canonicalHash(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(sortJson(value)))
    .digest("hex")}`;
}

function sortJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => sortJson(item));
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, item]) => item !== undefined)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, sortJson(item)]),
    );
  }
  return value;
}
