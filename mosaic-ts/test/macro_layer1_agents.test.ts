import { ToolMessage } from "@langchain/core/messages";
import { describe, expect, it } from "vitest";
import {
  COMPONENT_MACRO_SUBMISSION_FIELD_NAMES,
  createMacroSubmissionSchema,
  DEFAULT_MACRO_COHORT_LENS,
  DIRECT_MACRO_SUBMISSION_FIELD_NAMES,
  MACRO_AGENT_IDS,
  MACRO_PROMPT_COHORT_IDS,
  MACRO_ROLE_CONTRACTS,
  macroSubmissionFieldNames,
  renderMacroPromptBody,
  renderMacroRuntimeContract,
} from "../src/agents/macro/_contracts.js";
import {
  MACRO_SNAPSHOT_SEMANTIC_VALIDATOR_ID,
  macroSnapshotEchoView,
  roleSnapshotFromToolLoop,
  validateMacroSnapshotEchoes,
} from "../src/agents/macro/_semantic_validation.js";
import { centralBankSpec } from "../src/agents/macro/central_bank.js";
import { chinaSpec } from "../src/agents/macro/china.js";
import { commoditiesSpec } from "../src/agents/macro/commodities.js";
import { euEconomySpec } from "../src/agents/macro/eu_economy.js";
import { euroAreaFinancialConditionsSpec } from "../src/agents/macro/euro_area_financial_conditions.js";
import { geopoliticalSpec } from "../src/agents/macro/geopolitical.js";
import { institutionalFlowSpec } from "../src/agents/macro/institutional_flow.js";
import { marketBreadthSpec } from "../src/agents/macro/market_breadth.js";
import { usEconomySpec } from "../src/agents/macro/us_economy.js";
import { usFinancialConditionsSpec } from "../src/agents/macro/us_financial_conditions.js";
import { macroSubmission } from "./helpers/macro.js";

const specs = [
  chinaSpec,
  usEconomySpec,
  euEconomySpec,
  centralBankSpec,
  usFinancialConditionsSpec,
  euroAreaFinancialConditionsSpec,
  commoditiesSpec,
  geopoliticalSpec,
  marketBreadthSpec,
  institutionalFlowSpec,
];

describe.each(specs)("$agentId macro role contract", (spec) => {
  it("uses one role snapshot and the fixed submission mode", () => {
    const parsed = spec.schema.parse(macroSubmission(spec.agentId));
    expect(parsed.mode).toBe(MACRO_ROLE_CONTRACTS[spec.agentId].mode);
    expect(spec.fieldNames).toEqual(macroSubmissionFieldNames(spec.agentId));
    expect(spec.fieldNames).toEqual(
      MACRO_ROLE_CONTRACTS[spec.agentId].mode === "DIRECT"
        ? DIRECT_MACRO_SUBMISSION_FIELD_NAMES
        : COMPONENT_MACRO_SUBMISSION_FIELD_NAMES,
    );
    expect(spec.requiredTools).toEqual(MACRO_ROLE_CONTRACTS[spec.agentId].requiredTools);
    expect(spec.requiredTools).toHaveLength(1);
  });

  it("requires claims, drivers, channels, refs, and exact component membership", () => {
    const base = macroSubmission(spec.agentId);
    expect(spec.schema.safeParse({ ...base, claims: [] }).success).toBe(false);
    expect(spec.schema.safeParse({ ...base, key_drivers: [] }).success).toBe(false);
    if (base.mode === "DIRECT") {
      expect(spec.schema.safeParse({ ...base, components: [] }).success).toBe(false);
      expect(
        spec.schema.safeParse({ ...base, signal: { ...base.signal, channels: [] } }).success,
      ).toBe(false);
      expect(
        spec.schema.safeParse({ ...base, signal: { ...base.signal, claim_refs: [] } }).success,
      ).toBe(false);
    } else {
      expect(
        spec.schema.safeParse({
          ...base,
          signal: {
            direction: "NEUTRAL",
            strength: 0,
            persistence_horizon: "DAYS",
            evaluation_horizon_trading_days: 5,
            confidence: 0.5,
            channels: ["supported channel"],
            claim_refs: [base.claims[0]?.claim_id],
          },
        }).success,
      ).toBe(false);
      expect(
        spec.schema.safeParse({ ...base, components: [...base.components].reverse() }).success,
      ).toBe(true);
      expect(
        spec.schema.safeParse({
          ...base,
          components: [{ ...base.components[0], direction: "NEUTRAL", strength: 1 }],
        }).success,
      ).toBe(false);
      expect(spec.schema.safeParse({ ...base, components: base.components.slice(1) }).success).toBe(
        false,
      );
    }
  });
});

describe("macro responsibility and prompt contract", () => {
  it("matches the target roster and China-view boundaries", () => {
    expect(specs.map((spec) => spec.agentId)).toEqual(MACRO_AGENT_IDS);
    expect(MACRO_ROLE_CONTRACTS.central_bank.responsibility.zh).toContain("PBOC");
    expect(MACRO_ROLE_CONTRACTS.central_bank.prohibited.zh.join(" ")).toContain("海外央行");
    expect(MACRO_ROLE_CONTRACTS.us_financial_conditions.responsibility.zh).toContain("Fed");
    expect(MACRO_ROLE_CONTRACTS.eu_economy.prohibited.zh.join(" ")).toContain("英国");
    expect(MACRO_ROLE_CONTRACTS.euro_area_financial_conditions.prohibited.zh.join(" ")).toContain(
      "非欧元区",
    );
  });

  it("renders only the public default behavior and rejects private cohorts", () => {
    expect(DEFAULT_MACRO_COHORT_LENS.zh).toContain("PIT");
    expect(DEFAULT_MACRO_COHORT_LENS.en).toContain("PIT");
    for (const agent of MACRO_AGENT_IDS) {
      for (const language of ["zh", "en"] as const) {
        const body = renderMacroPromptBody(agent, language, "cohort_default");
        expect(body).toContain(MACRO_ROLE_CONTRACTS[agent].responsibility[language]);
        expect(renderMacroRuntimeContract(agent, language)).toContain(
          MACRO_ROLE_CONTRACTS[agent].requiredTools[0],
        );
        for (const cohort of MACRO_PROMPT_COHORT_IDS.filter(
          (candidate) => candidate !== "cohort_default",
        )) {
          expect(() => renderMacroPromptBody(agent, language, cohort)).toThrow(
            "private cohort prompt generation is unavailable publicly",
          );
        }
      }
    }
  });

  it("does not expose research knobs, old fields, or a cross-agent stance", () => {
    for (const agent of MACRO_AGENT_IDS) {
      const body = `${renderMacroPromptBody(agent, "zh", "cohort_default")}\n${renderMacroPromptBody(
        agent,
        "en",
        "cohort_default",
      )}`;
      expect(body).not.toMatch(/research-knobs|domain knob|knob influence/i);
      expect(body).not.toMatch(/claim_type|evidence_refs|layer_1_consensus_score|macro stance/i);
    }
  });
});

describe("macro snapshot semantic validation", () => {
  it("publishes the validator version used by canary audit metadata", () => {
    expect(MACRO_SNAPSHOT_SEMANTIC_VALIDATOR_ID).toBe("macro_snapshot_semantics_v2");
  });

  it("accepts a schema-valid exact observation echo and rejects altered values", () => {
    const snapshot = {
      schema_version: "macro_role_snapshot_v2",
      role: "us_economy",
      as_of_date: "2026-07-15",
      observations: [
        {
          series_id: "CPIAUCSL",
          period_start: "2026-06-01",
          period_end: "2026-06-30",
          released_at: "2026-07-11T12:30:00Z",
          vintage_at: "2026-07-11T12:30:00Z",
          evidence_id: "us-cpi-vintage",
          actual: 3.2,
          previous: 3.3,
          expected: 3.1,
        },
      ],
    };
    const view = macroSnapshotEchoView(snapshot);
    const locator = String(
      (view.observations as Array<Record<string, unknown>>)[0]?.snapshot_echo_id,
    );
    const exact = macroSubmission("us_economy");
    const firstClaim = exact.claims[0];
    if (!firstClaim) throw new Error("fixture claim required");
    exact.claims[0] = {
      ...firstClaim,
      evidence_ids: ["us-cpi-vintage"],
      structured_conclusion: {
        ...firstClaim.structured_conclusion,
        snapshot_echo_id: locator,
        snapshot_metric: "actual",
        snapshot_value: 3.2,
      },
    };
    const parsed = createMacroSubmissionSchema("us_economy").parse(exact);
    expect(validateMacroSnapshotEchoes(parsed, snapshot)).toEqual([]);
    exact.claims[0] = {
      ...firstClaim,
      structured_conclusion: {
        ...firstClaim.structured_conclusion,
        snapshot_echo_id: locator,
        snapshot_metric: "actual",
        snapshot_value: 3.4,
      },
    };
    expect(validateMacroSnapshotEchoes(exact, snapshot)).toEqual([
      expect.objectContaining({ reason_code: "SNAPSHOT_NUMERIC_MISMATCH" }),
    ]);
    exact.claims[0] = {
      ...firstClaim,
      structured_conclusion: {
        ...firstClaim.structured_conclusion,
        snapshot_echo_id: locator,
        snapshot_metric: "surprise",
        snapshot_value: 0.1,
      },
    };
    expect(validateMacroSnapshotEchoes(exact, snapshot)).toEqual([]);
    exact.claims[0] = {
      ...firstClaim,
      structured_conclusion: {
        ...firstClaim.structured_conclusion,
        snapshot_echo_id: locator,
        snapshot_metric: "unsupported_label",
        snapshot_value: 3.2,
      },
    };
    expect(validateMacroSnapshotEchoes(exact, snapshot)).toEqual([
      expect.objectContaining({ reason_code: "UNSUPPORTED_NUMERIC_ECHO" }),
    ]);
  });

  it("makes the echo triple reachable in the real schema and closes numeric prose bypasses", () => {
    const base = macroSubmission("us_economy");
    const firstClaim = base.claims[0];
    if (!firstClaim || base.mode !== "COMPONENTS") throw new Error("fixture claim required");
    const schema = createMacroSubmissionSchema("us_economy");
    expect(
      schema.safeParse({
        ...base,
        claims: [
          {
            ...firstClaim,
            structured_conclusion: {
              ...firstClaim.structured_conclusion,
              snapshot_echo_id: "series:CPIAUCSL",
              snapshot_metric: null,
              snapshot_value: 3.2,
            },
          },
        ],
      }).success,
    ).toBe(false);
    for (const candidate of [
      { ...base, key_drivers: ["CPI rose 3.2 percent"] },
      {
        ...base,
        claims: [{ ...firstClaim, statement: "CPI rose 3.2 percent" }],
      },
      {
        ...base,
        claims: [
          {
            ...firstClaim,
            structured_conclusion: {
              ...firstClaim.structured_conclusion,
              state: "CPI rose 3.2 percent",
            },
          },
        ],
      },
      {
        ...base,
        components: base.components.map((component, index) =>
          index === 0 ? { ...component, channels: ["ten-year yield at 3.2 percent"] } : component,
        ),
      },
    ]) {
      expect(schema.safeParse(candidate).success).toBe(false);
    }
  });

  it("separates snapshot echo locators from claim evidence ids", () => {
    const snapshot = {
      schema_version: "macro_role_snapshot_v2",
      role: "commodities",
      as_of_date: "2026-07-15",
      observations: [
        {
          series_id: "energy_oil",
          period_start: "2026-07-01",
          period_end: "2026-07-15",
          released_at: "2026-07-15T06:00:00Z",
          vintage_at: "2026-07-15T06:00:00Z",
          evidence_id: "private-source-evidence",
          actual: 101.2,
          previous: 100.8,
          expected: 101,
        },
      ],
    };
    const view = macroSnapshotEchoView(snapshot);
    const row = (view.observations as Array<Record<string, unknown>>)[0];
    expect(row).toMatchObject({
      snapshot_echo_id: expect.stringMatching(/^series-observation:sha256:[0-9a-f]{64}$/),
      actual: 101.2,
    });
    expect(row).not.toHaveProperty("evidence_id");
    const locator = String(row?.snapshot_echo_id);

    const output = macroSubmission("commodities");
    const firstClaim = output.claims[0];
    if (!firstClaim) throw new Error("fixture claim required");
    output.claims[0] = {
      ...firstClaim,
      structured_conclusion: {
        ...firstClaim.structured_conclusion,
        snapshot_echo_id: locator,
        snapshot_metric: "actual",
        snapshot_value: 101.2,
      },
    };
    const parsed = createMacroSubmissionSchema("commodities").parse(output);
    expect(validateMacroSnapshotEchoes(parsed, snapshot)).toEqual([]);

    output.claims[0] = {
      ...firstClaim,
      structured_conclusion: {
        ...firstClaim.structured_conclusion,
        snapshot_echo_id: "series:unknown",
        snapshot_metric: "actual",
        snapshot_value: 101.2,
      },
    };
    expect(validateMacroSnapshotEchoes(output, snapshot)).toEqual([
      expect.objectContaining({ reason_code: "SNAPSHOT_REFERENCE_UNKNOWN" }),
    ]);
  });

  it("distinguishes vintages of one series and rejects duplicate frozen identities", () => {
    const first = {
      series_id: "shared_series",
      period_start: "2026-05-01",
      period_end: "2026-05-31",
      released_at: "2026-06-10T08:00:00Z",
      vintage_at: "2026-06-10T08:00:00Z",
      evidence_id: "shared-series-first",
      actual: 1.1,
      previous: 1,
      expected: 1,
    };
    const second = {
      ...first,
      period_start: "2026-06-01",
      period_end: "2026-06-30",
      released_at: "2026-07-10T08:00:00Z",
      vintage_at: "2026-07-10T09:00:00Z",
      evidence_id: "shared-series-second",
      actual: 1.4,
    };
    const snapshot = {
      schema_version: "macro_role_snapshot_v2",
      role: "us_economy",
      as_of_date: "2026-07-15",
      observations: [first, second],
    };
    const view = macroSnapshotEchoView(snapshot);
    const rows = view.observations as Array<Record<string, unknown>>;
    expect(rows[0]?.snapshot_echo_id).not.toBe(rows[1]?.snapshot_echo_id);

    const output = macroSubmission("us_economy");
    const claim = output.claims[0];
    if (!claim) throw new Error("fixture claim required");
    output.claims[0] = {
      ...claim,
      structured_conclusion: {
        ...claim.structured_conclusion,
        snapshot_echo_id: String(rows[1]?.snapshot_echo_id),
        snapshot_metric: "actual",
        snapshot_value: 1.4,
      },
    };
    expect(
      validateMacroSnapshotEchoes(
        createMacroSubmissionSchema("us_economy").parse(output),
        snapshot,
      ),
    ).toEqual([]);

    const duplicateIdentity = {
      ...snapshot,
      observations: [first, { ...first, evidence_id: "different-evidence", actual: 9.9 }],
    };
    expect(validateMacroSnapshotEchoes(macroSubmission("us_economy"), duplicateIdentity)).toEqual([
      expect.objectContaining({ reason_code: "SNAPSHOT_REFERENCE_AMBIGUOUS" }),
    ]);
    const earlyGate = roleSnapshotFromToolLoop({
      agent: "us_economy",
      asOfDate: "2026-07-15",
      messages: [
        new ToolMessage({ content: JSON.stringify(duplicateIdentity), tool_call_id: "snapshot-1" }),
      ],
      requiredTool: "get_us_macro_snapshot",
      toolStatuses: [
        {
          name: "get_us_macro_snapshot",
          call_id: "snapshot-1",
          called: true,
          failed: false,
          missing: false,
          fallback: false,
          cache_hit: false,
          args: {},
        },
      ],
    });
    expect(earlyGate.snapshot).toBeNull();
    expect(earlyGate.issues).toEqual([
      expect.objectContaining({ reason_code: "SNAPSHOT_REFERENCE_AMBIGUOUS" }),
    ]);
  });

  it("exposes deterministic real-economy context as an exact context-only echo", () => {
    const snapshot = {
      schema_version: "macro_role_snapshot_v2",
      role: "us_financial_conditions",
      as_of_date: "2026-07-15",
      observations: [],
      context_only_projection: {
        schema_version: "macro_real_economy_context_projection_v1",
        usage_mode: "CONTEXT_ONLY",
        source_role: "us_economy",
        contributes_to_required_components: false,
        component_summaries: {
          employment: {
            component: "employment",
            source_role: "us_economy",
            usage_mode: "CONTEXT_ONLY",
            contributes_to_required_components: false,
            observation_count: 2,
            latest_period_end: "2026-06-30",
            actual_vs_expected_balance: -1,
            actual_vs_previous_balance: 0,
            evidence_ids: ["private-context-row"],
          },
        },
        projection_hash: `sha256:${"3".repeat(64)}`,
      },
    };
    const view = macroSnapshotEchoView(snapshot);
    const projection = view.context_only_projection as Record<string, unknown>;
    const summaries = projection.component_summaries as Record<string, Record<string, unknown>>;
    expect(summaries.employment).toMatchObject({
      snapshot_echo_id: "context-only:us_economy:employment",
      usage_mode: "CONTEXT_ONLY",
      contributes_to_required_components: false,
      observation_count: 2,
    });
    expect(summaries.employment).not.toHaveProperty("evidence_ids");

    const output = macroSubmission("us_financial_conditions");
    const firstClaim = output.claims[0];
    if (!firstClaim) throw new Error("fixture claim required");
    output.claims[0] = {
      ...firstClaim,
      structured_conclusion: {
        ...firstClaim.structured_conclusion,
        snapshot_echo_id: "context-only:us_economy:employment",
        snapshot_metric: "observation_count",
        snapshot_value: 2,
      },
    };
    expect(
      validateMacroSnapshotEchoes(
        createMacroSubmissionSchema("us_financial_conditions").parse(output),
        snapshot,
      ),
    ).toEqual([]);
    output.claims[0] = {
      ...firstClaim,
      structured_conclusion: {
        ...firstClaim.structured_conclusion,
        snapshot_echo_id: "context-only:us_economy:employment",
        snapshot_metric: "observation_count",
        snapshot_value: 3,
      },
    };
    expect(validateMacroSnapshotEchoes(output, snapshot)).toEqual([
      expect.objectContaining({ reason_code: "SNAPSHOT_NUMERIC_MISMATCH" }),
    ]);
  });

  it("accepts exact bound role-event echoes", () => {
    const snapshot = {
      schema_version: "macro_role_snapshot_v2",
      role: "eu_economy",
      as_of_date: "2026-07-15",
      observations: [],
      role_event_snapshot: {
        projections: [
          {
            calendar_event_id: "calendar-event-1",
            event_revision_id: "calendar-event-1:r1",
            actual: 101.2,
            previous: 100.7,
            forecast: 100.9,
          },
        ],
      },
    };
    const output = macroSubmission("eu_economy");
    const firstClaim = output.claims[0];
    if (!firstClaim) throw new Error("fixture claim required");
    output.claims[0] = {
      ...firstClaim,
      structured_conclusion: {
        ...firstClaim.structured_conclusion,
        snapshot_echo_id: "role-event:calendar-event-1:r1",
        snapshot_metric: "expected",
        snapshot_value: 100.9,
      },
    };
    expect(
      validateMacroSnapshotEchoes(
        createMacroSubmissionSchema("eu_economy").parse(output),
        snapshot,
      ),
    ).toEqual([]);
  });

  it("rejects runtime-owned data quality even when its value is copied exactly", () => {
    const snapshot = {
      schema_version: "geopolitical_role_snapshot_v2",
      role: "geopolitical",
      as_of_date: "2026-07-15",
      direct_data_quality: 1,
    };
    const output = macroSubmission("geopolitical");
    const firstClaim = output.claims[0];
    if (!firstClaim) throw new Error("fixture claim required");
    output.claims[0] = {
      ...firstClaim,
      structured_conclusion: {
        ...firstClaim.structured_conclusion,
        snapshot_echo_id: "role-snapshot:geopolitical:2026-07-15",
        snapshot_metric: "direct_data_quality",
        snapshot_value: 1,
      },
    };
    expect(validateMacroSnapshotEchoes(output, snapshot)).toEqual([
      expect.objectContaining({ reason_code: "RUNTIME_OWNED_NUMERIC_FIELD" }),
    ]);
  });
});
