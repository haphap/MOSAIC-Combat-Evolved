import { describe, expect, it } from "vitest";
import {
  MACRO_AGENT_IDS,
  MACRO_COHORT_LENSES,
  MACRO_PROMPT_COHORT_IDS,
  MACRO_ROLE_CONTRACTS,
  MACRO_SUBMISSION_FIELD_NAMES,
  renderMacroPromptBody,
  renderMacroRuntimeContract,
} from "../src/agents/macro/_contracts.js";
import {
  macroSnapshotEchoView,
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
    expect(spec.fieldNames).toEqual(MACRO_SUBMISSION_FIELD_NAMES);
    expect(spec.requiredTools).toEqual(MACRO_ROLE_CONTRACTS[spec.agentId].requiredTools);
    expect(spec.requiredTools).toHaveLength(1);
  });

  it("requires claims, drivers, channels, refs, and exact component membership", () => {
    const base = macroSubmission(spec.agentId);
    expect(spec.schema.safeParse({ ...base, claims: [] }).success).toBe(false);
    expect(spec.schema.safeParse({ ...base, key_drivers: [] }).success).toBe(false);
    if (base.mode === "DIRECT") {
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

  it("keeps every cohort behavior distinct while immutable role/tool text stays present", () => {
    expect(new Set(MACRO_PROMPT_COHORT_IDS.map((id) => MACRO_COHORT_LENSES[id].zh)).size).toBe(8);
    expect(new Set(MACRO_PROMPT_COHORT_IDS.map((id) => MACRO_COHORT_LENSES[id].en)).size).toBe(8);
    for (const agent of MACRO_AGENT_IDS) {
      for (const language of ["zh", "en"] as const) {
        const bodies = MACRO_PROMPT_COHORT_IDS.map((cohort) =>
          renderMacroPromptBody(agent, language, cohort),
        );
        expect(new Set(bodies).size).toBe(8);
        expect(bodies[0]).toContain(MACRO_ROLE_CONTRACTS[agent].responsibility[language]);
        expect(renderMacroRuntimeContract(agent, language)).toContain(
          MACRO_ROLE_CONTRACTS[agent].requiredTools[0],
        );
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
  it("accepts exact observation echoes and rejects altered values", () => {
    const snapshot = {
      schema_version: "macro_role_snapshot_v2",
      role: "us_economy",
      as_of_date: "2026-07-15",
      observations: [
        {
          series_id: "CPIAUCSL",
          evidence_id: "us-cpi-vintage",
          actual: 3.2,
          previous: 3.3,
          expected: 3.1,
        },
      ],
    };
    const exact = macroSubmission("us_economy");
    const firstClaim = exact.claims[0];
    if (!firstClaim) throw new Error("fixture claim required");
    exact.claims[0] = {
      ...firstClaim,
      evidence_ids: ["us-cpi-vintage"],
      structured_conclusion: {
        series_id: "CPIAUCSL",
        actual: 3.2,
        expected: 3.1,
        evaluation_horizon_trading_days: 5,
      },
    };
    expect(validateMacroSnapshotEchoes(exact, snapshot)).toEqual([]);
    exact.claims[0] = {
      ...firstClaim,
      structured_conclusion: { actual: 3.2, expected: 3.1, surprise: 0.1 },
    };
    expect(validateMacroSnapshotEchoes(exact, snapshot)).toEqual([]);
    expect(
      validateMacroSnapshotEchoes(exact, {
        ...snapshot,
        observations: [
          ...snapshot.observations,
          {
            series_id: "duplicate",
            evidence_id: "duplicate",
            actual: 3.2,
            previous: 3.3,
            expected: 3.1,
          },
        ],
      }),
    ).toEqual([
      expect.objectContaining({ reason_code: "SNAPSHOT_REFERENCE_REQUIRED" }),
      expect.objectContaining({ reason_code: "SNAPSHOT_REFERENCE_REQUIRED" }),
      expect.objectContaining({ reason_code: "SNAPSHOT_REFERENCE_REQUIRED" }),
    ]);
    exact.claims[0] = {
      ...firstClaim,
      structured_conclusion: { evaluation_horizon_trading_days: 20 },
    };
    expect(validateMacroSnapshotEchoes(exact, snapshot)).toEqual([
      expect.objectContaining({ reason_code: "CONTRACT_NUMERIC_MISMATCH" }),
    ]);
    exact.claims[0] = {
      ...firstClaim,
      structured_conclusion: { series_id: "CPIAUCSL", actual: 3.4 },
    };
    expect(validateMacroSnapshotEchoes(exact, snapshot)).toEqual([
      expect.objectContaining({ reason_code: "SNAPSHOT_NUMERIC_MISMATCH" }),
    ]);
  });

  it("separates snapshot echo locators from claim evidence ids", () => {
    const snapshot = {
      schema_version: "macro_role_snapshot_v2",
      role: "commodities",
      as_of_date: "2026-07-15",
      observations: [
        {
          series_id: "energy_oil",
          evidence_id: "private-source-evidence",
          actual: 101.2,
          previous: 100.8,
          expected: 101,
        },
      ],
    };
    const view = macroSnapshotEchoView(snapshot);
    const row = (view.observations as Array<Record<string, unknown>>)[0];
    expect(row).toMatchObject({ snapshot_echo_id: "series:energy_oil", actual: 101.2 });
    expect(row).not.toHaveProperty("evidence_id");

    const output = macroSubmission("commodities");
    const firstClaim = output.claims[0];
    if (!firstClaim) throw new Error("fixture claim required");
    output.claims[0] = {
      ...firstClaim,
      structured_conclusion: {
        snapshot_echo_id: "series:energy_oil",
        actual: 101.2,
      },
    };
    expect(validateMacroSnapshotEchoes(output, snapshot)).toEqual([]);

    output.claims[0] = {
      ...firstClaim,
      structured_conclusion: {
        snapshot_echo_id: "role-snapshot:commodities:2026-07-15",
        series_id: "energy_oil",
        value: 101.2,
      },
    };
    expect(validateMacroSnapshotEchoes(output, snapshot)).toEqual([]);
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
        snapshot_echo_id: "role-event:calendar-event-1:r1",
        actual: 101.2,
        expected: 100.9,
        previous: 100.7,
      },
    };
    expect(validateMacroSnapshotEchoes(output, snapshot)).toEqual([]);
  });

  it("accepts exact deterministic direct data quality but rejects invented weights", () => {
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
      structured_conclusion: { readiness: "READY", direct_data_quality: 1 },
    };
    expect(validateMacroSnapshotEchoes(output, snapshot)).toEqual([]);
    output.claims[0] = {
      ...firstClaim,
      structured_conclusion: { direct_shock_weight: 1 },
    };
    expect(validateMacroSnapshotEchoes(output, snapshot)).toEqual([
      expect.objectContaining({ reason_code: "SNAPSHOT_REFERENCE_REQUIRED" }),
    ]);
  });
});
