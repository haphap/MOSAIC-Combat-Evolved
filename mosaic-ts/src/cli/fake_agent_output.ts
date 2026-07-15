import type { BaseMessage } from "@langchain/core/messages";
import { z } from "zod";

/** Deterministic schema-driven fake used only by CLI smoke runs. */
export function fakeAgentStructuredOutput(
  schema: unknown,
  name: string,
  messages: unknown,
): unknown {
  const jsonSchema = normalizeJsonSchema(schema);
  const output = synthesize(jsonSchema) as Record<string, unknown>;
  if (!("claims" in output)) return output;
  const text = messageText(messages);
  const evidenceId = firstEvidenceId(text);
  const claimId = `fake-claim-${name}`;
  const positions = currentPositions(text);
  const explicitEmpty = configureDisposition(output, positions, claimId);
  output.claims = [
    evidenceId && !explicitEmpty
      ? {
          claim_id: claimId,
          claim_type: "fact",
          statement: "Fake smoke output is bound to the runtime evidence snapshot.",
          structured_conclusion: { disposition: dispositionOf(output) },
          evidence_refs: [evidenceId],
          research_rule_refs: [],
        }
      : {
          claim_id: claimId,
          claim_type: "uncertainty",
          statement: "Fake smoke found no evidence-supported actionable conclusion.",
          structured_conclusion: { disposition: dispositionOf(output) },
          evidence_refs: [],
          research_rule_refs: [],
        },
  ];
  output.claim_refs = [claimId];
  if ("decision_claim_refs" in output) output.decision_claim_refs = [claimId];
  attachEntryClaimRefs(output, claimId);
  return output;
}

export function fakeContractOutput(
  authored: Record<string, unknown>,
  name: string,
  messages: unknown,
): Record<string, unknown> {
  const output = structuredClone(authored);
  const claimId = `fake-claim-${name}`;
  const evidenceId = firstEvidenceId(messageText(messages));
  const nonEmpty = (field: string) => Array.isArray(output[field]) && output[field].length > 0;
  if (
    ["semiconductor", "energy", "biotech", "consumer", "industrials", "financials"].includes(name)
  ) {
    output.selection_disposition =
      nonEmpty("longs") || nonEmpty("shorts") ? "CANDIDATES" : "NO_QUALIFIED_CANDIDATES";
  }
  if (["druckemiller", "druckenmiller", "munger", "burry", "ackman"].includes(name)) {
    output.selection_disposition = nonEmpty("picks") ? "CANDIDATES" : "NO_QUALIFIED_CANDIDATES";
  }
  if (name === "cro") {
    output.review_disposition =
      nonEmpty("rejected_picks") || nonEmpty("required_adjustments")
        ? "REVIEW_ACTIONS"
        : "NO_OBJECTION";
  }
  if (name === "alpha_discovery") {
    output.discovery_disposition = nonEmpty("novel_picks") ? "CANDIDATES" : "NONE_FOUND";
  }
  if (name === "autonomous_execution") {
    output.execution_disposition = nonEmpty("trades") ? "TRADES" : "NO_DELTA";
  }
  const explicitEmpty = [
    "NO_QUALIFIED_CANDIDATES",
    "NO_OBJECTION",
    "NONE_FOUND",
    "NO_DELTA",
    "BLOCKED",
  ].some((value) => Object.values(output).includes(value));
  output.claims = [
    evidenceId && !explicitEmpty
      ? {
          claim_id: claimId,
          claim_type: "fact",
          statement: "Fake authored output is bound to current runtime evidence.",
          structured_conclusion: { disposition: dispositionOf(output) },
          evidence_refs: [evidenceId],
          research_rule_refs: [],
        }
      : {
          claim_id: claimId,
          claim_type: "uncertainty",
          statement: "Fake authored output has no evidence-supported actionable conclusion.",
          structured_conclusion: { disposition: dispositionOf(output) },
          evidence_refs: [],
          research_rule_refs: [],
        },
  ];
  output.claim_refs = [claimId];
  if (name === "cio") output.decision_claim_refs = [claimId];
  attachEntryClaimRefs(output, claimId);
  return output;
}

export function fakeSchemaValue(schema: unknown): Record<string, unknown> {
  const value = synthesize(normalizeJsonSchema(schema));
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function normalizeJsonSchema(schema: unknown): unknown {
  if (schema !== null && typeof schema === "object" && !Array.isArray(schema)) {
    const record = schema as Record<string, unknown>;
    if (typeof record.$schema === "string") return schema;
  }
  return z.toJSONSchema(schema as z.ZodType);
}

function synthesize(schema: unknown): unknown {
  if (schema === null || typeof schema !== "object" || Array.isArray(schema)) return null;
  const record = schema as Record<string, unknown>;
  if ("const" in record) return record.const;
  if (Array.isArray(record.enum) && record.enum.length > 0) return record.enum[0];
  if (Array.isArray(record.anyOf)) {
    const branch = record.anyOf.find(
      (item) =>
        !(item && typeof item === "object" && (item as Record<string, unknown>).type === "null"),
    );
    return synthesize(branch);
  }
  if (record.type === "object" || record.properties) {
    const properties = (record.properties ?? {}) as Record<string, unknown>;
    const required = new Set((record.required as string[] | undefined) ?? []);
    return Object.fromEntries(
      Object.entries(properties)
        .filter(([key]) => required.has(key))
        .map(([key, value]) => [key, synthesize(value)]),
    );
  }
  if (record.type === "array") {
    const count = typeof record.minItems === "number" ? record.minItems : 0;
    return Array.from({ length: count }, () => synthesize(record.items));
  }
  if (record.type === "number" || record.type === "integer") {
    const minimum = typeof record.minimum === "number" ? record.minimum : 0;
    const maximum = typeof record.maximum === "number" ? record.maximum : Number.POSITIVE_INFINITY;
    return Math.min(Math.max(0, minimum), maximum);
  }
  if (record.type === "boolean") return false;
  return "fake";
}

function configureDisposition(
  output: Record<string, unknown>,
  positions: Array<{ ticker: string; weight: number }>,
  claimId: string,
): boolean {
  if ("selection_disposition" in output) {
    output.selection_disposition = "NO_QUALIFIED_CANDIDATES";
    output.longs = [];
    output.shorts = [];
    output.picks = [];
    return true;
  }
  if ("review_disposition" in output) {
    output.review_disposition = "NO_OBJECTION";
    output.rejected_picks = [];
    output.required_adjustments = [];
    return true;
  }
  if ("discovery_disposition" in output) {
    output.discovery_disposition = "NONE_FOUND";
    output.novel_picks = [];
    return true;
  }
  if ("execution_disposition" in output) {
    output.execution_disposition = "NO_DELTA";
    output.trades = [];
    output.execution_checks = [];
    return true;
  }
  if ("decision_disposition" in output) {
    output.decision_reason =
      positions.length === 0
        ? "No current positions and no evidence-supported target."
        : "Preserve every current position in the fake smoke run.";
    output.dissent_refs = [];
    if (positions.length === 0) {
      output.decision_disposition = "ALL_CASH";
      output.portfolio_actions = [];
      output.position_reviews = [];
      return false;
    }
    output.decision_disposition = "HOLD_CURRENT";
    output.portfolio_actions = positions.map(({ ticker, weight }) => ({
      ticker,
      action: "HOLD",
      position_decision: "HOLD",
      current_weight: weight,
      target_weight: weight,
      delta_weight: 0,
      holding_period: "1M",
      position_decision_reason: "Fake smoke preserves current exposure.",
      thesis_status: "intact",
      risk_flags: [],
      dissent_notes: "",
      claim_refs: [claimId],
    }));
    output.position_reviews = positions.map(({ ticker, weight }) => ({
      ticker,
      decision: "HOLD",
      target_weight: weight,
      reason: "Fake smoke preserves current exposure.",
      thesis_status: "intact",
      risk_flags: [],
      confidence: 0,
      claim_refs: [claimId],
    }));
  }
  return false;
}

function attachEntryClaimRefs(output: Record<string, unknown>, claimId: string): void {
  for (const field of [
    "longs",
    "shorts",
    "picks",
    "rejected_picks",
    "required_adjustments",
    "novel_picks",
    "trades",
    "execution_checks",
    "portfolio_actions",
    "position_reviews",
  ]) {
    if (!Array.isArray(output[field])) continue;
    output[field] = output[field].map((entry) =>
      entry !== null && typeof entry === "object"
        ? { ...(entry as Record<string, unknown>), claim_refs: [claimId] }
        : entry,
    );
  }
}

function currentPositions(text: string): Array<{ ticker: string; weight: number }> {
  return [...text.matchAll(/^\*\s+([0-9A-Z.]+): weight=([0-9.]+)/gm)].map((match) => ({
    ticker: match[1] as string,
    weight: Number(match[2]),
  }));
}

function firstEvidenceId(text: string): string | null {
  const marker = "Runtime-owned evidence catalog (use only these evidence_id values):";
  const markerIndex = text.indexOf(marker);
  if (markerIndex >= 0) {
    try {
      const catalog = JSON.parse(text.slice(markerIndex + marker.length).trim()) as {
        evidence?: Array<{ evidence_id?: unknown; freshness?: unknown }>;
      };
      const current = catalog.evidence?.find(
        (entry) => entry.freshness === "current" && typeof entry.evidence_id === "string",
      );
      if (typeof current?.evidence_id === "string") return current.evidence_id;
    } catch {
      // Repair prompts JSON-escape the immutable original task; use the scan below.
    }
  }
  for (const match of text.matchAll(
    /"evidence_id"\s*:\s*"([^"]+)"[\s\S]{0,1200}?"freshness"\s*:\s*"current"/g,
  )) {
    if (match[1]) return match[1];
  }
  return null;
}

function dispositionOf(output: Record<string, unknown>): unknown {
  return (
    output.selection_disposition ??
    output.review_disposition ??
    output.discovery_disposition ??
    output.execution_disposition ??
    output.decision_disposition ??
    "ANALYSIS"
  );
}

function messageText(messages: unknown): string {
  if (!Array.isArray(messages)) return String(messages ?? "");
  return (messages as BaseMessage[])
    .map((message) =>
      typeof message.content === "string" ? message.content : JSON.stringify(message.content),
    )
    .join("\n");
}
