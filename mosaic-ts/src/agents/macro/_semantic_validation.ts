import { createHash } from "node:crypto";
import type { BaseMessage } from "@langchain/core/messages";
import type { AgentContractIssue } from "../helpers/agent_run_contract.js";
import type { ToolStatus } from "../helpers/private_knot_boundary.js";
import type { MacroAgentId, MacroAgentSubmission } from "../types.js";

interface SnapshotRecord extends Record<string, unknown> {
  as_of_date?: unknown;
  observations?: unknown;
  role?: unknown;
  schema_version?: unknown;
}

const SNAPSHOT_NUMERIC_ALIASES: Readonly<Record<string, string>> = {
  actual_value: "actual",
  current_value: "actual",
  observed_index_value: "actual",
  observed_value: "actual",
  previous_value: "previous",
  prior_value: "previous",
  expected_value: "expected",
};
const RUNTIME_OWNED_ECHO_METRICS = new Set([
  "confidence",
  "strength",
  "direct_data_quality",
  "component_data_quality",
  "evaluation_horizon_trading_days",
]);

export const MACRO_SNAPSHOT_SEMANTIC_VALIDATOR_ID = "macro_snapshot_semantics_v2";

export function roleSnapshotFromToolLoop(input: {
  agent: MacroAgentId;
  asOfDate: string;
  messages: ReadonlyArray<BaseMessage>;
  requiredTool: string;
  toolStatuses: ReadonlyArray<ToolStatus>;
}): { issues: AgentContractIssue[]; snapshot: SnapshotRecord | null } {
  const status = [...input.toolStatuses]
    .reverse()
    .find(
      (item) =>
        item.name === input.requiredTool &&
        item.called &&
        !item.failed &&
        !item.missing &&
        !item.fallback &&
        isRecord(item.args) &&
        Object.keys(item.args).length === 0,
    );
  if (!status?.call_id) {
    return {
      issues: [issue("ROLE_SNAPSHOT_NOT_ACCEPTED", "$.claims")],
      snapshot: null,
    };
  }
  const toolMessage = [...input.messages].reverse().find((message) => {
    if (message.getType() !== "tool") return false;
    return (message as BaseMessage & { tool_call_id?: string }).tool_call_id === status.call_id;
  });
  const content = typeof toolMessage?.content === "string" ? toolMessage.content : null;
  if (!content) {
    return { issues: [issue("ROLE_SNAPSHOT_PAYLOAD_MISSING", "$.claims")], snapshot: null };
  }
  let snapshot: SnapshotRecord;
  try {
    const parsed = JSON.parse(content) as unknown;
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
    snapshot = parsed as SnapshotRecord;
  } catch {
    return { issues: [issue("ROLE_SNAPSHOT_PAYLOAD_INVALID", "$.claims")], snapshot: null };
  }
  const expectedSchema =
    input.agent === "market_breadth"
      ? "market_breadth_snapshot_v1"
      : input.agent === "geopolitical"
        ? "geopolitical_role_snapshot_v2"
        : "macro_role_snapshot_v2";
  const issues: AgentContractIssue[] = [];
  if (snapshot.schema_version !== expectedSchema) {
    issues.push(issue("ROLE_SNAPSHOT_SCHEMA_MISMATCH", "$.claims"));
  }
  if (snapshot.as_of_date !== input.asOfDate) {
    issues.push(issue("ROLE_SNAPSHOT_AS_OF_MISMATCH", "$.claims"));
  }
  if (input.agent !== "market_breadth" && snapshot.role !== input.agent) {
    issues.push(issue("ROLE_SNAPSHOT_AGENT_MISMATCH", "$.claims"));
  }
  if (issues.length === 0) issues.push(...snapshotEchoIndex(snapshot).issues);
  return { issues, snapshot: issues.length === 0 ? snapshot : null };
}

export function validateMacroSnapshotEchoes(
  output: MacroAgentSubmission,
  snapshot: SnapshotRecord,
): AgentContractIssue[] {
  const catalog = snapshotEchoIndex(snapshot);
  if (catalog.issues.length > 0) return catalog.issues;
  const issues: AgentContractIssue[] = [];

  for (const [claimIndex, claim] of output.claims.entries()) {
    const conclusion = claim.structured_conclusion as Record<string, unknown>;
    const path = `$.claims.${claimIndex}.structured_conclusion`;
    const locator = conclusion.snapshot_echo_id;
    const metric = conclusion.snapshot_metric;
    const value = conclusion.snapshot_value;
    if (locator === null && metric === null && value === null) continue;
    if (typeof locator !== "string" || typeof metric !== "string" || typeof value !== "number") {
      issues.push(issue("SNAPSHOT_ECHO_FIELDS_INCOMPLETE", path));
      continue;
    }
    const observation = catalog.records.get(locator);
    if (!observation) {
      issues.push(issue("SNAPSHOT_REFERENCE_UNKNOWN", `${path}.snapshot_echo_id`));
      continue;
    }
    if (RUNTIME_OWNED_ECHO_METRICS.has(metric)) {
      issues.push(
        issue(
          "RUNTIME_OWNED_NUMERIC_FIELD",
          `${path}.snapshot_metric`,
          `${metric} is runtime-owned and cannot be model-authored`,
        ),
      );
      continue;
    }
    const canonicalMetric = SNAPSHOT_NUMERIC_ALIASES[metric] ?? metric;
    const expected =
      canonicalMetric === "expected" && typeof observation.expected !== "number"
        ? observation.forecast
        : observation[canonicalMetric];
    if (typeof expected === "number") {
      if (!Object.is(value, expected)) {
        issues.push(issue("SNAPSHOT_NUMERIC_MISMATCH", `${path}.snapshot_value`));
      }
    } else if (!matchesDerivedSnapshotValue(metric, value, observation)) {
      issues.push(issue("UNSUPPORTED_NUMERIC_ECHO", `${path}.snapshot_metric`));
    }
  }
  return issues;
}

/**
 * Give the extractor exact numeric rows without exposing source evidence IDs
 * that could be confused with the runtime-owned claim evidence catalog.
 */
export function macroSnapshotEchoView(snapshot: SnapshotRecord): Record<string, unknown> {
  const echoRecords = new Set<SnapshotRecord>([snapshot, ...snapshotEchoRecords(snapshot)]);
  return sanitize(snapshot) as Record<string, unknown>;

  function sanitize(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(sanitize);
    if (!isRecord(value)) return value;
    const result: Record<string, unknown> = {};
    const echoId = echoRecords.has(value) ? snapshotEchoId(value) : null;
    if (echoId) result.snapshot_echo_id = echoId;
    for (const [key, item] of Object.entries(value)) {
      if (key === "evidence_id" || key === "evidence_ids" || key.endsWith("_evidence_ids"))
        continue;
      if (key === "snapshot_echo_id") continue;
      result[key] = sanitize(item);
    }
    return result;
  }
}

function matchesDerivedSnapshotValue(
  key: string,
  value: number,
  observation: SnapshotRecord,
): boolean {
  const actual = observation.actual;
  if (typeof actual !== "number") return false;
  const expected = observation.expected;
  if (
    ["surprise", "surprise_value", "actual_minus_expected"].includes(key) &&
    typeof expected === "number"
  ) {
    return nearlyEqual(value, actual - expected);
  }
  const previous = observation.previous;
  if (
    ["change", "change_value", "delta", "actual_minus_previous"].includes(key) &&
    typeof previous === "number"
  ) {
    return nearlyEqual(value, actual - previous);
  }
  return false;
}

function nearlyEqual(left: number, right: number): boolean {
  return Math.abs(left - right) <= 1e-12;
}

function snapshotEchoIndex(snapshot: SnapshotRecord): {
  records: ReadonlyMap<string, SnapshotRecord>;
  issues: AgentContractIssue[];
} {
  const records = new Map<string, SnapshotRecord>();
  const issues: AgentContractIssue[] = [];
  for (const record of [snapshot, ...snapshotEchoRecords(snapshot)]) {
    const locator = snapshotEchoId(record);
    if (!locator) {
      issues.push(issue("SNAPSHOT_REFERENCE_IDENTITY_INCOMPLETE", "$.snapshot_echo_catalog"));
      continue;
    }
    if (records.has(locator)) {
      issues.push(
        issue(
          "SNAPSHOT_REFERENCE_AMBIGUOUS",
          "$.snapshot_echo_catalog",
          `duplicate snapshot echo locator: ${locator}`,
        ),
      );
      continue;
    }
    records.set(locator, record);
  }
  return { records, issues };
}

function snapshotEchoRecords(snapshot: SnapshotRecord): SnapshotRecord[] {
  return [
    ...(Array.isArray(snapshot.observations) ? snapshot.observations.filter(isRecord) : []),
    ...(isRecord(snapshot.context_only_projection) &&
    isRecord(snapshot.context_only_projection.component_summaries)
      ? Object.values(snapshot.context_only_projection.component_summaries).filter(isRecord)
      : []),
    ...(Array.isArray(snapshot.coverage_by_event_type)
      ? snapshot.coverage_by_event_type.filter(isRecord)
      : []),
    ...(Array.isArray(snapshot.events) ? snapshot.events.filter(isRecord) : []),
    ...(isRecord(snapshot.role_event_snapshot) &&
    Array.isArray(snapshot.role_event_snapshot.projections)
      ? snapshot.role_event_snapshot.projections.filter(isRecord)
      : []),
  ];
}

function snapshotEchoId(value: SnapshotRecord): string | null {
  if (typeof value.series_id === "string") {
    const identity = [
      value.series_id,
      value.period_start,
      value.period_end,
      value.released_at,
      value.vintage_at,
    ];
    if (!identity.every((part) => typeof part === "string")) return null;
    const digest = createHash("sha256").update(JSON.stringify(identity)).digest("hex");
    return `series-observation:sha256:${digest}`;
  }
  if (
    value.usage_mode === "CONTEXT_ONLY" &&
    value.contributes_to_required_components === false &&
    typeof value.source_role === "string" &&
    typeof value.component === "string"
  ) {
    return `context-only:${value.source_role}:${value.component}`;
  }
  if (typeof value.event_revision_id === "string") {
    return typeof value.calendar_event_id === "string"
      ? `role-event:${value.event_revision_id}`
      : `geopolitical-event:${value.event_revision_id}`;
  }
  if (typeof value.event_type === "string" && typeof value.required_query_count === "number") {
    return `geopolitical-coverage:${value.event_type}`;
  }
  if (value.schema_version === "market_breadth_snapshot_v1") {
    return `market-breadth:${String(value.as_of_date ?? "unknown")}`;
  }
  if (typeof value.role === "string" && typeof value.as_of_date === "string") {
    return `role-snapshot:${value.role}:${value.as_of_date}`;
  }
  return null;
}

function isRecord(value: unknown): value is SnapshotRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function issue(reasonCode: string, jsonPath: string, message = reasonCode): AgentContractIssue {
  return {
    validator: MACRO_SNAPSHOT_SEMANTIC_VALIDATOR_ID,
    reason_code: reasonCode,
    json_path: jsonPath,
    message,
  };
}
