import type { BaseMessage } from "@langchain/core/messages";
import type { AgentContractIssue } from "../helpers/agent_run_contract.js";
import type { ToolStatus } from "../helpers/research_knobs.js";
import type { MacroAgentId, MacroAgentOutput } from "../types.js";

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
        item.args.as_of_date === input.asOfDate,
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
    input.agent === "market_breadth" ? "market_breadth_snapshot_v1" : "macro_role_snapshot_v1";
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
  output: MacroAgentOutput,
  snapshot: SnapshotRecord,
): AgentContractIssue[] {
  const issues: AgentContractIssue[] = [];
  const observations = Array.isArray(snapshot.observations)
    ? snapshot.observations.filter(isRecord)
    : [];

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
    const resolvedObservation = resolveSnapshotRecord(value, observations, snapshot);
    const declaresSnapshotReference =
      typeof value.evidence_id === "string" || typeof value.series_id === "string";
    const observation = declaresSnapshotReference ? resolvedObservation : referenced;
    if (declaresSnapshotReference && !resolvedObservation) {
      issues.push(issue("SNAPSHOT_REFERENCE_UNKNOWN", path));
    }
    for (const [key, item] of Object.entries(value)) {
      const itemPath = `${path}.${key}`;
      if (typeof item === "number") {
        if (ASSESSMENT_NUMERIC_KEYS.has(key)) continue;
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
          issues.push(issue("SNAPSHOT_REFERENCE_REQUIRED", itemPath));
        }
      } else if (typeof item === "string" && /[+-]?(?:\d+(?:\.\d+)?|\.\d+)\s*%/.test(item)) {
        issues.push(issue("PERCENTAGE_MUST_BE_NUMERIC_SNAPSHOT_ECHO", itemPath));
      } else {
        inspectConclusion(item, itemPath, observation);
      }
    }
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
  if (typeof value.evidence_id === "string") {
    const match = observations.find((row) => row.evidence_id === value.evidence_id);
    if (match) return match;
    if (snapshot.evidence_id === value.evidence_id) return snapshot;
  }
  if (typeof value.series_id === "string") {
    const match = observations.find((row) => row.series_id === value.series_id);
    if (match) return match;
  }
  return null;
}

function isRecord(value: unknown): value is SnapshotRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function issue(reasonCode: string, jsonPath: string): AgentContractIssue {
  return {
    validator: "macro_snapshot_semantics_v1",
    reason_code: reasonCode,
    json_path: jsonPath,
    message: reasonCode,
  };
}
