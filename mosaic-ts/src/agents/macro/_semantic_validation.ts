import type { BaseMessage } from "@langchain/core/messages";
import type { AgentContractIssue } from "../helpers/agent_run_contract.js";
import type { ToolStatus } from "../helpers/research_knobs.js";
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
const ASSESSMENT_NUMERIC_KEYS = new Set(["confidence", "strength"]);

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
  return { issues, snapshot: issues.length === 0 ? snapshot : null };
}

export function validateMacroSnapshotEchoes(
  output: MacroAgentSubmission,
  snapshot: SnapshotRecord,
): AgentContractIssue[] {
  const issues: AgentContractIssue[] = [];
  const evaluationHorizon =
    output.mode === "DIRECT"
      ? output.signal.evaluation_horizon_trading_days
      : output.components[0]?.evaluation_horizon_trading_days;
  const observations = [
    ...(Array.isArray(snapshot.observations) ? snapshot.observations.filter(isRecord) : []),
    ...(Array.isArray(snapshot.coverage_by_event_type)
      ? snapshot.coverage_by_event_type.filter(isRecord)
      : []),
    ...(Array.isArray(snapshot.events) ? snapshot.events.filter(isRecord) : []),
    ...(isRecord(snapshot.role_event_snapshot) &&
    Array.isArray(snapshot.role_event_snapshot.projections)
      ? snapshot.role_event_snapshot.projections.filter(isRecord)
      : []),
  ];

  for (const [claimIndex, claim] of output.claims.entries()) {
    inspectConclusion(
      claim.structured_conclusion,
      `$.claims.${claimIndex}.structured_conclusion`,
      null,
    );
  }
  return issues;

  function inspectConclusion(
    value: unknown,
    path: string,
    referenced: SnapshotRecord | null,
  ): void {
    if (Array.isArray(value)) {
      value.forEach((item, index) => {
        inspectConclusion(item, `${path}.${index}`, referenced);
      });
      return;
    }
    if (!isRecord(value)) return;
    const explicitObservation = resolveSnapshotRecord(value, observations, snapshot);
    const declaresSnapshotReference =
      typeof value.evidence_id === "string" ||
      typeof value.series_id === "string" ||
      typeof value.snapshot_echo_id === "string";
    const inferredObservation = declaresSnapshotReference
      ? null
      : resolveUniqueNumericObservation(value, observations);
    const observation = declaresSnapshotReference
      ? explicitObservation
      : (referenced ?? inferredObservation);
    if (declaresSnapshotReference && !explicitObservation) {
      issues.push(issue("SNAPSHOT_REFERENCE_UNKNOWN", path));
    }
    for (const [key, item] of Object.entries(value)) {
      const itemPath = `${path}.${key}`;
      if (typeof item === "number") {
        if (ASSESSMENT_NUMERIC_KEYS.has(key)) continue;
        if (key === "evaluation_horizon_trading_days") {
          if (item !== evaluationHorizon) {
            issues.push(issue("CONTRACT_NUMERIC_MISMATCH", itemPath));
          }
          continue;
        }
        if (key === "direct_data_quality") {
          if (item !== snapshot.direct_data_quality) {
            issues.push(issue("CONTRACT_NUMERIC_MISMATCH", itemPath));
          }
          continue;
        }
        if (observation) {
          const canonicalKey = SNAPSHOT_NUMERIC_ALIASES[key] ?? key;
          const expected = observation[canonicalKey];
          if (typeof expected === "number") {
            if (!Object.is(item, expected)) {
              issues.push(issue("SNAPSHOT_NUMERIC_MISMATCH", itemPath));
            }
          } else if (matchesDerivedSnapshotValue(key, item, observation)) {
            // Deterministic actual-vs-expected or actual-vs-previous arithmetic.
          } else if (Object.values(observation).some((candidate) => Object.is(candidate, item))) {
            // Accept a renamed but exact numeric echo when the record identity is explicit.
          } else {
            issues.push(issue("UNSUPPORTED_NUMERIC_ECHO", itemPath));
          }
        } else if (declaresSnapshotReference) {
          issues.push(issue("UNSUPPORTED_NUMERIC_ECHO", itemPath));
        } else {
          issues.push(
            issue(
              "SNAPSHOT_REFERENCE_REQUIRED",
              itemPath,
              "Remove invented numeric assessments/weights, or copy an exact snapshot number in an object with its matching snapshot_echo_id or series_id.",
            ),
          );
        }
      } else if (typeof item === "string" && /[+-]?(?:\d+(?:\.\d+)?|\.\d+)\s*%/.test(item)) {
        issues.push(issue("PERCENTAGE_MUST_BE_NUMERIC_SNAPSHOT_ECHO", itemPath));
      } else {
        inspectConclusion(item, itemPath, observation);
      }
    }
  }
}

function resolveUniqueNumericObservation(
  value: SnapshotRecord,
  observations: ReadonlyArray<SnapshotRecord>,
): SnapshotRecord | null {
  const numericEntries = Object.entries(value).filter(
    ([key, item]) =>
      typeof item === "number" &&
      !ASSESSMENT_NUMERIC_KEYS.has(key) &&
      key !== "evaluation_horizon_trading_days" &&
      key !== "direct_data_quality",
  ) as Array<[string, number]>;
  if (numericEntries.length === 0) return null;
  const matches = observations.filter((observation) =>
    numericEntries.every(([key, item]) => numericValueMatchesObservation(key, item, observation)),
  );
  return matches.length === 1 ? (matches[0] ?? null) : null;
}

function numericValueMatchesObservation(
  key: string,
  item: number,
  observation: SnapshotRecord,
): boolean {
  const canonicalKey = SNAPSHOT_NUMERIC_ALIASES[key] ?? key;
  const expected = observation[canonicalKey];
  if (typeof expected === "number") return Object.is(item, expected);
  if (matchesDerivedSnapshotValue(key, item, observation)) return true;
  return Object.values(observation).some(
    (candidate) => typeof candidate === "number" && Object.is(candidate, item),
  );
}

/**
 * Give the extractor exact numeric rows without exposing source evidence IDs
 * that could be confused with the runtime-owned claim evidence catalog.
 */
export function macroSnapshotEchoView(snapshot: SnapshotRecord): Record<string, unknown> {
  return sanitize(snapshot) as Record<string, unknown>;

  function sanitize(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(sanitize);
    if (!isRecord(value)) return value;
    const result: Record<string, unknown> = {};
    const echoId = snapshotEchoId(value);
    if (echoId) result.snapshot_echo_id = echoId;
    for (const [key, item] of Object.entries(value)) {
      if (key === "evidence_id" || key.endsWith("_evidence_ids")) continue;
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

function resolveSnapshotRecord(
  value: SnapshotRecord,
  observations: ReadonlyArray<SnapshotRecord>,
  snapshot: SnapshotRecord,
): SnapshotRecord | null {
  // A model may retain the root role-snapshot locator while also supplying the
  // exact series/event identity. Resolve the most specific identity first so
  // an exact observation is not accidentally compared against the envelope.
  if (typeof value.series_id === "string") {
    const match = observations.find((row) => row.series_id === value.series_id);
    if (match) return match;
  }
  if (typeof value.evidence_id === "string") {
    const match = observations.find((row) => row.evidence_id === value.evidence_id);
    if (match) return match;
    if (snapshot.evidence_id === value.evidence_id) return snapshot;
  }
  if (typeof value.snapshot_echo_id === "string") {
    const match = observations.find((row) => snapshotEchoId(row) === value.snapshot_echo_id);
    if (match) return match;
    if (snapshotEchoId(snapshot) === value.snapshot_echo_id) return snapshot;
  }
  return null;
}

function snapshotEchoId(value: SnapshotRecord): string | null {
  if (typeof value.series_id === "string") return `series:${value.series_id}`;
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
    validator: "macro_snapshot_semantics_v1",
    reason_code: reasonCode,
    json_path: jsonPath,
    message,
  };
}
