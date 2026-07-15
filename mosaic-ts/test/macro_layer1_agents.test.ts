import { describe, expect, it } from "vitest";
import {
  MACRO_AGENT_IDS,
  MACRO_COHORT_LENSES,
  MACRO_OUTPUT_FIELD_NAMES,
  MACRO_PROMPT_COHORT_IDS,
  MACRO_ROLE_CONTRACTS,
  renderMacroPromptBody,
  renderMacroRuntimeContract,
} from "../src/agents/macro/_contracts.js";
import { validateMacroSnapshotEchoes } from "../src/agents/macro/_semantic_validation.js";
import { centralBankSpec } from "../src/agents/macro/central_bank.js";
import { chinaSpec } from "../src/agents/macro/china.js";
import { commoditiesSpec } from "../src/agents/macro/commodities.js";
import { dollarSpec } from "../src/agents/macro/dollar.js";
import { geopoliticalSpec } from "../src/agents/macro/geopolitical.js";
import { institutionalFlowSpec } from "../src/agents/macro/institutional_flow.js";
import { marketBreadthSpec } from "../src/agents/macro/market_breadth.js";
import { usEconomySpec } from "../src/agents/macro/us_economy.js";
import { volatilitySpec } from "../src/agents/macro/volatility.js";
import { yieldCurveSpec } from "../src/agents/macro/yield_curve.js";
import type { MacroAgentId } from "../src/agents/types.js";
import { macroOutput } from "./helpers/macro.js";

const specs = [
  chinaSpec,
  usEconomySpec,
  centralBankSpec,
  dollarSpec,
  yieldCurveSpec,
  commoditiesSpec,
  geopoliticalSpec,
  volatilitySpec,
  marketBreadthSpec,
  institutionalFlowSpec,
];

describe.each(specs)("$agentId macro role contract", (spec) => {
  it("uses the shared schema and its single role-scoped snapshot tool", () => {
    const parsed = spec.schema.parse(macroOutput(spec.agentId));
    expect(parsed.agent).toBe(spec.agentId);
    expect(spec.fieldNames).toEqual(MACRO_OUTPUT_FIELD_NAMES);
    expect(spec.requiredTools).toEqual(MACRO_ROLE_CONTRACTS[spec.agentId].requiredTools);
    expect(spec.requiredTools).toHaveLength(1);
  });

  it("requires non-empty claims, conclusion refs, drivers, and channels", () => {
    for (const field of ["claims", "claim_refs", "key_drivers", "channels"] as const) {
      expect(spec.schema.safeParse({ ...macroOutput(spec.agentId), [field]: [] }).success).toBe(
        false,
      );
    }
  });

  it("enforces direction-strength consistency", () => {
    expect(
      spec.schema.safeParse({
        ...macroOutput(spec.agentId),
        direction: "NEUTRAL",
        strength: 1,
      }).success,
    ).toBe(false);
    expect(
      spec.schema.safeParse({
        ...macroOutput(spec.agentId),
        direction: "ADVERSE",
        strength: 0,
      }).success,
    ).toBe(false);
  });
});

describe("macro responsibility matrix", () => {
  it("contains exactly the ten current roles and excludes both legacy roles", () => {
    expect(specs.map((spec) => spec.agentId)).toEqual(MACRO_AGENT_IDS);
    expect(MACRO_AGENT_IDS).not.toContain("emerging_markets");
    expect(MACRO_AGENT_IDS).not.toContain("news_sentiment");
  });

  it.each(MACRO_AGENT_IDS)("generates immutable bilingual role/tool text for %s", (agent) => {
    const zh = renderMacroRuntimeContract(agent, "zh");
    const en = renderMacroRuntimeContract(agent, "en");
    expect(zh).toContain(MACRO_ROLE_CONTRACTS[agent].requiredTools[0]);
    expect(en).toContain(MACRO_ROLE_CONTRACTS[agent].requiredTools[0]);
    expect(zh).toContain(MACRO_ROLE_CONTRACTS[agent].responsibility.zh);
    expect(en).toContain(MACRO_ROLE_CONTRACTS[agent].responsibility.en);
    expect(zh).not.toContain("```json");
    expect(en).not.toContain("```json");
  });

  it("keeps cohort lenses distinct without changing role-scoped contracts", () => {
    expect(
      new Set(MACRO_PROMPT_COHORT_IDS.map((cohort) => MACRO_COHORT_LENSES[cohort].en)).size,
    ).toBe(MACRO_PROMPT_COHORT_IDS.length);
    expect(
      new Set(MACRO_PROMPT_COHORT_IDS.map((cohort) => MACRO_COHORT_LENSES[cohort].zh)).size,
    ).toBe(MACRO_PROMPT_COHORT_IDS.length);
    for (const agent of MACRO_AGENT_IDS) {
      for (const language of ["zh", "en"] as const) {
        const bodies = MACRO_PROMPT_COHORT_IDS.map((cohort) =>
          renderMacroPromptBody(agent, language, cohort),
        );
        expect(new Set(bodies).size, `${agent}:${language}`).toBe(MACRO_PROMPT_COHORT_IDS.length);
        for (const [index, cohort] of MACRO_PROMPT_COHORT_IDS.entries()) {
          expect(bodies[index]).toContain(MACRO_COHORT_LENSES[cohort][language]);
          expect(bodies[index]).toContain(MACRO_ROLE_CONTRACTS[agent].responsibility[language]);
        }
      }
      const zh = renderMacroPromptBody(agent, "zh", "cohort_default");
      expect(zh).not.toMatch(/^## (Runtime|Analysis|Cohort|Prohibited)/m);
      expect(zh).not.toContain("When evidence is insufficient");
      expect(zh).not.toContain("Layer-1");
    }
  });

  it("keeps news event evidence limited to China and geopolitical snapshots", () => {
    const allowed = new Set<MacroAgentId>(["china", "geopolitical"]);
    for (const agent of MACRO_AGENT_IDS) {
      const text = [
        MACRO_ROLE_CONTRACTS[agent].responsibility.zh,
        ...MACRO_ROLE_CONTRACTS[agent].prohibited.zh,
      ].join(" ");
      if (!allowed.has(agent)) expect(text).not.toContain("新闻情绪票");
    }
  });

  it("keeps central_bank China-centric and routes Fed transmission through market paths", () => {
    const role = MACRO_ROLE_CONTRACTS.central_bank;
    expect(role.responsibility.zh).toContain("PBOC");
    expect(role.responsibility.en).toContain("PBOC");
    expect(role.responsibility.zh).not.toContain("Fed");
    expect(role.responsibility.en).not.toContain("Fed");
    expect(role.prohibited.zh).toContain("不得判断 Fed 政策方向");
    expect(MACRO_ROLE_CONTRACTS.dollar.prohibited.zh.join(" ")).toContain("Fed 政策方向");
    expect(MACRO_ROLE_CONTRACTS.yield_curve.prohibited.zh.join(" ")).toContain("央行政策结论");
  });
});

describe("macro snapshot semantic validation", () => {
  it("accepts exact observation echoes and rejects altered values", () => {
    const snapshot = {
      schema_version: "macro_role_snapshot_v1",
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
    const baseClaim = macroOutput("us_economy").claims[0];
    if (!baseClaim) throw new Error("macro fixture claim missing");
    const exact = macroOutput("us_economy", {
      claims: [
        {
          ...baseClaim,
          structured_conclusion: { series_id: "CPIAUCSL", actual: 3.2, expected: 3.1 },
        },
      ],
    });
    expect(validateMacroSnapshotEchoes(exact, snapshot)).toEqual([]);
    const altered = macroOutput("us_economy", {
      claims: [
        {
          ...baseClaim,
          structured_conclusion: { series_id: "CPIAUCSL", actual: 3.4 },
        },
      ],
    });
    expect(validateMacroSnapshotEchoes(altered, snapshot)).toEqual([
      expect.objectContaining({ reason_code: "SNAPSHOT_NUMERIC_MISMATCH" }),
    ]);
  });

  it("rejects invented breadth percentages", () => {
    const baseClaim = macroOutput("market_breadth").claims[0];
    if (!baseClaim) throw new Error("macro fixture claim missing");
    const output = macroOutput("market_breadth", {
      claims: [
        {
          ...baseClaim,
          structured_conclusion: {
            evidence_id: "market_breadth:2026-07-15",
            above_ma20_pct: 0.75,
          },
        },
      ],
    });
    expect(
      validateMacroSnapshotEchoes(output, {
        schema_version: "market_breadth_snapshot_v1",
        as_of_date: "2026-07-15",
        evidence_id: "market_breadth:2026-07-15",
        above_ma20_pct: 0.7,
      }),
    ).toEqual([expect.objectContaining({ reason_code: "SNAPSHOT_NUMERIC_MISMATCH" })]);
  });

  it("rejects fabricated numerics without an explicit snapshot reference", () => {
    const baseClaim = macroOutput("geopolitical").claims[0];
    if (!baseClaim) throw new Error("macro fixture claim missing");
    const output = macroOutput("geopolitical", {
      claims: [
        {
          ...baseClaim,
          structured_conclusion: { price_impact_pct: 37 },
        },
      ],
    });
    expect(
      validateMacroSnapshotEchoes(output, {
        schema_version: "macro_role_snapshot_v1",
        role: "geopolitical",
        as_of_date: "2026-07-15",
        observations: [],
      }),
    ).toEqual([expect.objectContaining({ reason_code: "SNAPSHOT_REFERENCE_REQUIRED" })]);
  });

  it("rejects unknown references and percentages hidden in prose", () => {
    const baseClaim = macroOutput("geopolitical").claims[0];
    if (!baseClaim) throw new Error("macro fixture claim missing");
    const output = macroOutput("geopolitical", {
      claims: [
        {
          ...baseClaim,
          structured_conclusion: {
            evidence_id: "missing:event",
            description: "estimated impact=37%",
          },
        },
      ],
    });
    expect(
      validateMacroSnapshotEchoes(output, {
        schema_version: "macro_role_snapshot_v1",
        role: "geopolitical",
        as_of_date: "2026-07-15",
        observations: [],
      }),
    ).toEqual([
      expect.objectContaining({ reason_code: "SNAPSHOT_REFERENCE_UNKNOWN" }),
      expect.objectContaining({ reason_code: "PERCENTAGE_MUST_BE_NUMERIC_SNAPSHOT_ECHO" }),
    ]);
  });

  it("allows assessment scores that are not observation echoes", () => {
    const baseClaim = macroOutput("china").claims[0];
    if (!baseClaim) throw new Error("macro fixture claim missing");
    const output = macroOutput("china", {
      claims: [
        {
          ...baseClaim,
          structured_conclusion: { direction: "supportive", strength: 3 },
        },
      ],
    });
    expect(
      validateMacroSnapshotEchoes(output, {
        schema_version: "macro_role_snapshot_v1",
        role: "china",
        as_of_date: "2026-07-15",
        observations: [],
      }),
    ).toEqual([]);
  });

  it("validates explicit aliases and deterministic surprise arithmetic", () => {
    const baseClaim = macroOutput("central_bank").claims[0];
    if (!baseClaim) throw new Error("macro fixture claim missing");
    const output = macroOutput("central_bank", {
      claims: [
        {
          ...baseClaim,
          structured_conclusion: {
            series_id: "smoke_central_bank",
            observed_index_value: 0.3,
            previous_value: 0.2,
            expected_value: 0.25,
            surprise: 0.05,
          },
        },
      ],
    });
    expect(
      validateMacroSnapshotEchoes(output, {
        schema_version: "macro_role_snapshot_v1",
        role: "central_bank",
        as_of_date: "2026-07-15",
        observations: [
          {
            series_id: "smoke_central_bank",
            evidence_id: "smoke:central_bank:2026-06",
            actual: 0.3,
            previous: 0.2,
            expected: 0.25,
          },
        ],
      }),
    ).toEqual([]);
  });
});
