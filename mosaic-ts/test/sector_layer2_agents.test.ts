import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { z } from "zod";
import { adaptStrictProviderJsonSchema } from "../src/agents/helpers/structured_provider_adapters.js";
import { MACRO_AGENT_IDS } from "../src/agents/macro/_contracts.js";
import { validateMacroInputs } from "../src/agents/macro/_input_gate.js";
import { renderBundledPrompt } from "../src/agents/prompts/bundled_prompt_renderer.js";
import { AGENTS_BY_LAYER } from "../src/agents/prompts/cohorts.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import {
  SECTOR_AGENT_IDS,
  STANDARD_SECTOR_AGENT_IDS,
  STANDARD_SECTOR_ROLE_CONTRACTS,
} from "../src/agents/sector/_contracts.js";
import {
  buildLayerTwoUserContext,
  buildSectorCoverageDirective,
  compactRelationshipExtractorAnalysis,
  renderSectorDirectionResearchPayloads,
} from "../src/agents/sector/_factory.js";
import {
  buildRelationshipMapperSchema,
  buildStandardSectorSchema,
  RELATIONSHIP_MAPPER_MAX_CLAIMS,
  RELATIONSHIP_MAPPER_MAX_FACTUAL_EDGES,
  RELATIONSHIP_MAPPER_MAX_PREDICTIVE_EDGES,
  RelationshipMapperSchema,
  STANDARD_SECTOR_MAX_CLAIMS,
} from "../src/agents/sector/_schemas.js";
import { standardSectorSpec } from "../src/agents/sector/_spec.js";
import { MAX_SECTOR_COVERAGE_EVIDENCE_IDS } from "../src/agents/sector/comparison.js";
import { buildEnergyNode } from "../src/agents/sector/energy.js";
import { SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT } from "../src/agents/sector/registry.js";
import { relationshipMapperSpec } from "../src/agents/sector/relationship_mapper.js";
import {
  SECURITY_SCORING_CONTRACT_HASH,
  SECURITY_SCORING_CONTRACT_VERSION,
  validateFinalSelectionAgainstDirective,
} from "../src/agents/sector/selection.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import { emptyCurrentPositions, emptyLayer4, emptyPositionAudit } from "../src/agents/state.js";
import type {
  BridgeApi,
  MosaicConfig,
  SectorModelUsageReport,
  SectorModelUsageSummaryReceipt,
  SignedAgentToolCapability,
  ToolCapabilityPrepareRequest,
} from "../src/bridge/types.js";
import { fakeAgentStructuredOutput } from "../src/cli/fake_agent_output.js";
import { LAYER2_AGENT_NODES } from "../src/graph/layer2.js";
import type { LlmHandle } from "../src/llm/factory.js";
import { macroOutput } from "./helpers/macro.js";
import { sectorOutput } from "./helpers/sector.js";

describe("Layer-2 roster and role contracts", () => {
  it("has nine disjoint standard roles plus relationship mapper", () => {
    expect(STANDARD_SECTOR_AGENT_IDS).toHaveLength(9);
    expect(SECTOR_AGENT_IDS).toHaveLength(10);
    expect([...AGENTS_BY_LAYER.sector]).toEqual([...SECTOR_AGENT_IDS]);
    expect([...LAYER2_AGENT_NODES]).toEqual([...SECTOR_AGENT_IDS]);
  });

  it.each(STANDARD_SECTOR_AGENT_IDS)("%s owns an exact direction registry", (agent) => {
    const role = STANDARD_SECTOR_ROLE_CONTRACTS[agent];
    expect(role.directionIds.length).toBeGreaterThanOrEqual(3);
    expect(new Set(role.directionIds).size).toBe(role.directionIds.length);
    expect(role.requiredTools).toEqual(
      agent === "biotech"
        ? ["get_sector_research_snapshot"]
        : ["get_sector_research_snapshot", "get_role_event_snapshot"],
    );
    expect(role.responsibility.zh).not.toBe(role.responsibility.en);
    expect(role.prohibited.zh.length).toBeGreaterThan(0);
  });

  it("preserves the requested industry ownership boundaries", () => {
    expect(STANDARD_SECTOR_ROLE_CONTRACTS.energy.directionIds).toEqual(
      expect.arrayContaining(["coal", "oil_gas", "solar", "wind", "battery_storage"]),
    );
    expect(STANDARD_SECTOR_ROLE_CONTRACTS.consumer.directionIds).toContain("automobiles");
    expect(STANDARD_SECTOR_ROLE_CONTRACTS.industrials.directionIds).toEqual(
      expect.arrayContaining(["basic_chemicals", "steel", "nonferrous_metals"]),
    );
    expect(STANDARD_SECTOR_ROLE_CONTRACTS.real_estate_construction.directionIds).toEqual([
      "real_estate",
      "building_materials",
      "construction_decoration",
    ]);
    expect(STANDARD_SECTOR_ROLE_CONTRACTS.financials.directionIds).toEqual([
      "banking",
      "securities",
      "insurance",
      "diversified_financials",
    ]);
    expect(STANDARD_SECTOR_ROLE_CONTRACTS.semiconductor.directionIds).toHaveLength(4);
    expect(STANDARD_SECTOR_ROLE_CONTRACTS.biotech.directionIds).toHaveLength(6);
  });

  it("requires both directions and permits security abstention only for an empty shortlist", () => {
    const context = buildLayerTwoUserContext(sectorPipelineState(), "energy");
    expect(context).toContain("select one distinct least-preferred direction");
    expect(context).toContain("runtime-proven empty frozen shortlist");
    expect(context).toContain("a non-empty shortlist requires picks");
    expect(context).not.toContain("least-preferred direction only when");
    const enPrompt = renderBundledPrompt("energy", "en");
    const zhPrompt = renderBundledPrompt("energy", "zh");
    expect(enPrompt).toContain("only when runtime proves its frozen shortlist is empty");
    expect(enPrompt).toContain("a non-empty shortlist requires picks");
    expect(zhPrompt).toContain("运行时证明对应冻结 shortlist 为空");
    expect(zhPrompt).toContain("shortlist 非空必须输出 picks");
  });

  it("keeps source ids distinct from the runtime claim-evidence catalog", () => {
    const rendered = renderSectorDirectionResearchPayloads(
      new Map([
        [
          "get_sector_research_snapshot",
          JSON.stringify({
            direction_cards: [
              { direction_id: "chip_design", evidence_ids: ["source-card-evidence"] },
            ],
            evidence_catalog: [{ evidence_id: "source-card-evidence" }],
          }),
        ],
        ["get_role_event_snapshot", JSON.stringify({ coverage_evidence_ids: ["coverage-id"] })],
      ]),
    );
    expect(rendered).not.toContain("source-card-evidence");
    expect(rendered).toContain("coverage-id");
  });

  it("fails closed on missing/tampered role-event coverage outside the no-tool role", () => {
    expect(() => buildSectorCoverageDirective(new Map(), "energy", "2026-07-19")).toThrow(
      "required role-event snapshot payload is missing",
    );
    expect(buildSectorCoverageDirective(new Map(), "biotech", "2026-07-19")).toMatchObject({
      macro_event_fit: { coverage_state: "SOURCE_UNAVAILABLE" },
      catalysts: { coverage_state: "SOURCE_UNAVAILABLE" },
    });
    const valid = new Map([["get_role_event_snapshot", roleEventSnapshot()]]);
    expect(buildSectorCoverageDirective(valid, "energy", "2026-07-19")).toMatchObject({
      macro_event_fit: { coverage_state: "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT" },
    });
    const tampered = JSON.parse(roleEventSnapshot()) as Record<string, unknown>;
    tampered.role_event_snapshot_hash = `sha256:${"f".repeat(64)}`;
    expect(() =>
      buildSectorCoverageDirective(
        new Map([["get_role_event_snapshot", JSON.stringify(tampered)]]),
        "energy",
        "2026-07-19",
      ),
    ).toThrow("identity/hash binding is invalid");

    const emptyRoutes = JSON.parse(roleEventSnapshot()) as Record<string, unknown>;
    (emptyRoutes.coverage as Record<string, unknown>).required_route_ids = [];
    (emptyRoutes.coverage as Record<string, unknown>).healthy_route_ids = [];
    expect(() =>
      buildSectorCoverageDirective(
        new Map([["get_role_event_snapshot", rehashRoleEventSnapshot(emptyRoutes)]]),
        "energy",
        "2026-07-19",
      ),
    ).toThrow("required_route_ids must be a non-empty string array");

    const contradictoryUnavailable = JSON.parse(roleEventSnapshot()) as Record<string, unknown>;
    (contradictoryUnavailable.coverage as Record<string, unknown>).coverage_state =
      "SOURCE_UNAVAILABLE";
    expect(() =>
      buildSectorCoverageDirective(
        new Map([["get_role_event_snapshot", rehashRoleEventSnapshot(contradictoryUnavailable)]]),
        "energy",
        "2026-07-19",
      ),
    ).toThrow("material-event coverage binding is invalid");

    const oversizedEvidence = JSON.parse(roleEventSnapshot()) as Record<string, unknown>;
    (oversizedEvidence.coverage as Record<string, unknown>).coverage_evidence_ids = Array.from(
      { length: MAX_SECTOR_COVERAGE_EVIDENCE_IDS + 1 },
      (_, index) => `coverage-${String(index + 1).padStart(3, "0")}`,
    );
    expect(() =>
      buildSectorCoverageDirective(
        new Map([["get_role_event_snapshot", rehashRoleEventSnapshot(oversizedEvidence)]]),
        "energy",
        "2026-07-19",
      ),
    ).toThrow(`coverage_evidence_ids exceed ${MAX_SECTOR_COVERAGE_EVIDENCE_IDS}`);
  });
});

describe("standard sector output contracts", () => {
  it.each(
    STANDARD_SECTOR_AGENT_IDS,
  )("%s accepts the final selection without research rows", (agent) => {
    const schema = buildStandardSectorSchema(agent);
    const parsed = schema.parse(sectorOutput(agent));
    expect(parsed).not.toHaveProperty("direction_comparisons");
    expect(parsed.macro_input_attributions.map((item) => item.agent_id).sort()).toEqual(
      [...MACRO_AGENT_IDS].sort(),
    );
  });

  it("rejects research rows submitted during final selection", () => {
    const output = { ...sectorOutput("energy"), direction_comparisons: [] };
    expect(buildStandardSectorSchema("energy").safeParse(output).success).toBe(false);
  });

  it("accepts the fourteen-claim worst case and rejects a fifteenth claim", () => {
    const output = sectorOutput("energy");
    const claimIds = Array.from(
      { length: STANDARD_SECTOR_MAX_CLAIMS },
      (_, index) => `energy-claim-${index + 1}`,
    );
    const makeClaim = (claimId: string, index: number) => ({
      claim_id: claimId,
      claim_kind: "RISK_FLAG" as const,
      statement: `fixture sector conclusion ${index + 1}`,
      structured_conclusion: {
        conclusion_type: "SECTOR_RISK" as const,
        target_local_ref: null,
        selection_status: null,
        direction_id: null,
        position_action: null,
        summary: `Fixture sector conclusion ${index + 1}.`,
      },
      evidence_ids: ["fixture:energy"],
      research_rule_refs: [],
    });
    output.claims = claimIds.map(makeClaim);
    output.claim_refs = [...claimIds];
    output.preferred_direction.claim_refs = [claimIds[0] as string];
    output.least_preferred_direction.claim_refs = [claimIds[1] as string];
    const firstDriver = output.key_drivers[0];
    const firstRisk = output.risks[0];
    if (!firstDriver || !firstRisk) throw new Error("sector fixture requires one driver and risk");
    firstDriver.claim_refs = [claimIds[2] as string];
    firstRisk.claim_refs = [claimIds[3] as string];
    output.preferred_security_status = "PICKS_PRESENT";
    output.preferred_security_abstention_confidence = null;
    output.least_preferred_security_status = "PICKS_PRESENT";
    output.least_preferred_security_abstention_confidence = null;
    output.long_picks = Array.from({ length: 5 }, (_, index) => ({
      pick_local_id: `energy-long-${index + 1}`,
      ts_code: `${String(index + 1).padStart(6, "0")}.SZ`,
      direction_local_id: output.preferred_direction.direction_local_id,
      position_action: "LONG" as const,
      conviction: 0.2,
      thesis: `fixture long pick ${index + 1}`,
      claim_refs: [claimIds[index + 4] as string],
    }));
    output.short_or_avoid_picks = Array.from({ length: 5 }, (_, index) => ({
      pick_local_id: `energy-avoid-${index + 1}`,
      ts_code: `${String(index + 101).padStart(6, "0")}.SH`,
      direction_local_id: output.least_preferred_direction.direction_local_id,
      position_action: "AVOID" as const,
      conviction: 0.2,
      thesis: `fixture avoid pick ${index + 1}`,
      claim_refs: [claimIds[index + 9] as string],
    }));
    const schema = buildStandardSectorSchema("energy");
    expect(schema.safeParse(output).success).toBe(true);

    const fifteenthClaimId = "energy-claim-15";
    expect(
      schema.safeParse({
        ...output,
        claims: [...output.claims, makeClaim(fifteenthClaimId, 14)],
        claim_refs: [...output.claim_refs, fifteenthClaimId],
      }).success,
    ).toBe(false);
  });

  it("rejects duplicate or incomplete Macro attribution", () => {
    const output = sectorOutput("consumer");
    const duplicate = output.macro_input_attributions[1];
    if (!duplicate) throw new Error("fixture requires at least two Macro attributions");
    output.macro_input_attributions[0] = duplicate;
    expect(buildStandardSectorSchema("consumer").safeParse(output).success).toBe(false);
  });

  it("rejects a direction owned by another role", () => {
    const output = sectorOutput("consumer");
    if (output.selection_status !== "SELECTED" || !("direction_id" in output.preferred_direction)) {
      throw new Error("fixture must select");
    }
    output.preferred_direction.direction_id = "coal";
    expect(buildStandardSectorSchema("consumer").safeParse(output).success).toBe(false);
  });

  it("binds final selection to the exact runtime direction and empty security shortlist", () => {
    const directive = {
      selection_status: "SELECTED" as const,
      preferred_direction_id: "coal",
      least_preferred_direction_id: "battery_storage",
      allowed_preferred_security_ids: [],
      allowed_least_preferred_security_ids: [],
    };
    const output = sectorOutput("energy");
    if (!("direction_id" in output.preferred_direction)) throw new Error("fixture must select");
    output.preferred_direction.direction_id = "coal";
    output.preferred_direction.direction_local_id = "coal";
    if (!("direction_id" in output.least_preferred_direction)) {
      throw new Error("fixture must have a least-preferred direction");
    }
    output.least_preferred_direction.direction_id = "battery_storage";
    output.least_preferred_direction.direction_local_id = "battery_storage";
    const schema = buildStandardSectorSchema("energy", "SELECTED", directive);
    expect(schema.safeParse(output).success).toBe(true);
    output.preferred_direction.direction_id = "oil_gas";
    expect(schema.safeParse(output).success).toBe(false);
  });

  it("requires picks whenever a frozen security shortlist is non-empty", () => {
    const directive = {
      selection_status: "SELECTED" as const,
      preferred_direction_id: "coal",
      least_preferred_direction_id: "battery_storage",
      allowed_preferred_security_ids: ["600000.SH"],
      allowed_least_preferred_security_ids: ["600001.SH"],
    };
    const output = sectorOutput("energy");
    output.preferred_direction.direction_id = "coal";
    output.preferred_direction.direction_local_id = "coal";
    output.least_preferred_direction.direction_id = "battery_storage";
    output.least_preferred_direction.direction_local_id = "battery_storage";
    const schema = buildStandardSectorSchema("energy", "SELECTED", directive);
    expect(schema.safeParse(output).success).toBe(false);
    expect(
      schema.safeParse({
        ...output,
        preferred_security_status: "PICKS_PRESENT",
        preferred_security_abstention_confidence: null,
        long_picks: [
          {
            pick_local_id: "long-1",
            ts_code: "600000.SH",
            direction_local_id: "coal",
            position_action: "LONG",
            conviction: 0.5,
            thesis: "Frozen score row supports the long leg.",
            claim_refs: ["energy-claim"],
          },
        ],
        least_preferred_security_status: "PICKS_PRESENT",
        least_preferred_security_abstention_confidence: null,
        short_or_avoid_picks: [
          {
            pick_local_id: "avoid-1",
            ts_code: "600001.SH",
            direction_local_id: "battery_storage",
            position_action: "AVOID",
            conviction: 0.5,
            thesis: "Frozen score row supports avoiding the weak leg.",
            claim_refs: ["energy-claim"],
          },
        ],
      }).success,
    ).toBe(true);
  });

  it("requires complete decisive evidence coverage on both final legs", () => {
    const output = sectorOutput("energy");
    output.preferred_direction.direction_id = "coal";
    output.preferred_direction.direction_local_id = "coal";
    output.least_preferred_direction.direction_id = "battery_storage";
    output.least_preferred_direction.direction_local_id = "battery_storage";
    const issues = validateFinalSelectionAgainstDirective(output, {
      selection_status: "SELECTED",
      preferred_direction_id: "coal",
      least_preferred_direction_id: "battery_storage",
      preferred_security_shortlist_id: "preferred-empty",
      preferred_security_shortlist_hash: `sha256:${"a".repeat(64)}`,
      least_preferred_security_shortlist_id: "least-empty",
      least_preferred_security_shortlist_hash: `sha256:${"b".repeat(64)}`,
      security_scoring_contract_version: SECURITY_SCORING_CONTRACT_VERSION,
      security_scoring_contract_hash: SECURITY_SCORING_CONTRACT_HASH,
      allowed_preferred_security_ids: [],
      allowed_least_preferred_security_ids: [],
      required_preferred_evidence_ids: ["fixture:energy", "missing:preferred"],
      required_least_preferred_evidence_ids: ["fixture:energy"],
      required_final_evidence_ids: ["fixture:energy", "missing:preferred"],
    });
    expect(issues).toContain(
      "preferred conclusion claims do not cite every required decisive evidence id",
    );
    expect(issues).toContain(
      "final conclusion claims do not cite every required decisive evidence id",
    );
  });

  it.each(STANDARD_SECTOR_AGENT_IDS)("%s spec exposes its closed snapshot tools", (agent) => {
    const spec = standardSectorSpec(agent, buildStandardSectorSchema(agent));
    expect(spec.requiredTools).toEqual(
      agent === "biotech"
        ? ["get_sector_research_snapshot"]
        : ["get_sector_research_snapshot", "get_role_event_snapshot"],
    );
    expect(spec.fieldNames).toEqual(
      expect.arrayContaining([
        "agent",
        "preferred_direction",
        "least_preferred_direction",
        "long_picks",
        "short_or_avoid_picks",
        "macro_input_attributions",
      ]),
    );
  });
});

describe("relationship mapper", () => {
  it("bounds extractor context while preserving both analysis ends", () => {
    const analysis = `${"head".repeat(2_000)}${"tail".repeat(2_000)}`;
    const compact = compactRelationshipExtractorAnalysis(analysis);
    expect(compact).toHaveLength(6_000);
    expect(compact.startsWith("head")).toBe(true);
    expect(compact.endsWith("tail")).toBe(true);
  });

  it("uses its dedicated frozen-domain snapshot", () => {
    expect(relationshipMapperSpec.requiredTools).toEqual(["get_relationship_graph_snapshot"]);
    expect(relationshipMapperSpec.fieldNames).toContain("agent");
  });

  it("requires structured relationships, risks, evidence, and claims", () => {
    const valid = {
      agent: "relationship_mapper",
      factual_edges: [
        {
          edge_local_id: "edge-1",
          source_entity: "300750.SZ",
          target_entity: "battery_storage",
          edge_type: "supply_chain",
          claim_refs: ["relationship-claim"],
        },
      ],
      predictive_graph_status: "NO_QUALIFIED_PREDICTIVE_EDGE",
      predictive_edges: [],
      predictive_graph_abstention_confidence: 0.5,
      key_drivers: [
        {
          driver_local_id: "driver-1",
          summary: "frozen accepted direction domain",
          claim_refs: ["relationship-claim"],
        },
      ],
      risks: [
        {
          risk_local_id: "risk-1",
          summary: "shared supplier",
          claim_refs: ["relationship-claim"],
        },
      ],
      claims: [
        {
          claim_id: "relationship-claim",
          claim_kind: "FACT",
          statement: "A frozen-domain relationship is observed.",
          structured_conclusion: { relationship: "supply_chain" },
          evidence_ids: ["sector:relationship"],
          research_rule_refs: [],
        },
      ],
      claim_refs: ["relationship-claim"],
      macro_input_attributions: MACRO_AGENT_IDS.map((macroAgentId) => ({
        agent_id: macroAgentId,
        target_type: "SUBMISSION_SUMMARY",
        target_local_ref: "$SUBMISSION",
        claim_refs_used: [],
        effect: "NOT_MATERIAL",
      })),
    } as const;
    expect(RelationshipMapperSchema.parse(valid).agent).toBe("relationship_mapper");
    const frozenExactSchema = buildRelationshipMapperSchema({
      maxFactualEdges: 1,
      maxPredictiveEdges: 1,
      factualRelationships: [
        {
          source_entity: "300750.SZ",
          target_entity: "battery_storage",
          edge_type: "supply_chain",
        },
      ],
    });
    expect(
      frozenExactSchema.safeParse({
        ...valid,
        factual_edges: [],
      }).success,
    ).toBe(false);
    expect(
      RelationshipMapperSchema.safeParse({
        ...valid,
        factual_edges: [
          valid.factual_edges[0],
          {
            ...valid.factual_edges[0],
            target_entity: "battery_recycling",
          },
        ],
      }).success,
    ).toBe(false);
    expect(
      RelationshipMapperSchema.safeParse({
        ...valid,
        factual_edges: [
          valid.factual_edges[0],
          {
            ...valid.factual_edges[0],
            edge_local_id: "edge-2",
          },
        ],
      }).success,
    ).toBe(false);
    const maximumClaimIds = Array.from(
      { length: RELATIONSHIP_MAPPER_MAX_CLAIMS },
      (_, index) => `relationship-claim-${index + 1}`,
    );
    expect(
      RelationshipMapperSchema.safeParse({
        ...valid,
        factual_edges: [
          {
            ...valid.factual_edges[0],
            claim_refs: maximumClaimIds,
          },
        ],
        key_drivers: [{ ...valid.key_drivers[0], claim_refs: maximumClaimIds }],
        risks: [{ ...valid.risks[0], claim_refs: maximumClaimIds }],
        claims: maximumClaimIds.map((claimId, index) => ({
          ...valid.claims[0],
          claim_id: claimId,
          statement: `Relationship conclusion ${index + 1}.`,
        })),
        claim_refs: maximumClaimIds,
      }).success,
    ).toBe(true);
    expect(
      RelationshipMapperSchema.safeParse({
        ...valid,
        factual_edges: [
          {
            ...valid.factual_edges[0],
            source_entity: "x".repeat(129),
          },
        ],
      }).success,
    ).toBe(false);
    expect(() =>
      buildRelationshipMapperSchema({
        maxFactualEdges: 1,
        maxPredictiveEdges: 1,
        factualRelationships: [
          {
            source_entity: "x".repeat(129),
            target_entity: "battery_storage",
            edge_type: "supply_chain",
          },
        ],
      }),
    ).toThrow();
    expect(() =>
      buildRelationshipMapperSchema({
        maxFactualEdges: 1,
        maxPredictiveEdges: 1,
        factualRelationships: [
          {
            source_entity: " 300750.SZ",
            target_entity: "battery_storage",
            edge_type: "supply_chain",
          },
        ],
      }),
    ).toThrow("must already be trimmed");
    expect(() =>
      buildRelationshipMapperSchema({
        maxFactualEdges: 2,
        maxPredictiveEdges: 1,
        factualRelationships: [
          {
            source_entity: "300750.SZ",
            target_entity: "battery_storage",
            edge_type: "supply_chain",
          },
          {
            source_entity: "300750.SZ",
            target_entity: "battery_storage",
            edge_type: "supply_chain",
          },
        ],
      }),
    ).toThrow("frozen factual relationship tuples must be unique");
    expect(() =>
      buildRelationshipMapperSchema({
        maxFactualEdges: RELATIONSHIP_MAPPER_MAX_FACTUAL_EDGES + 1,
        maxPredictiveEdges: 1,
      }),
    ).toThrow("factual domain must contain at most 32 rows");
    expect(() =>
      buildRelationshipMapperSchema({
        maxFactualEdges: 1,
        maxPredictiveEdges: RELATIONSHIP_MAPPER_MAX_PREDICTIVE_EDGES + 1,
      }),
    ).toThrow("predictive domain must contain between 1 and 32 rows");
    expect(() =>
      buildRelationshipMapperSchema({
        maxFactualEdges: RELATIONSHIP_MAPPER_MAX_FACTUAL_EDGES,
        maxPredictiveEdges: 1,
        factualRelationships: Array.from(
          { length: RELATIONSHIP_MAPPER_MAX_FACTUAL_EDGES + 1 },
          (_, index) => ({
            source_entity: `source-${index + 1}`,
            target_entity: `target-${index + 1}`,
            edge_type: "supply_chain",
          }),
        ),
      }),
    ).toThrow("factual domain exceeds its frozen bound");
    expect(
      RelationshipMapperSchema.safeParse({
        ...valid,
        factual_edges: Array.from(
          { length: RELATIONSHIP_MAPPER_MAX_FACTUAL_EDGES + 1 },
          (_, index) => ({
            ...valid.factual_edges[0],
            edge_local_id: `edge-${index + 1}`,
          }),
        ),
      }).success,
    ).toBe(false);
    expect(
      RelationshipMapperSchema.safeParse({
        ...valid,
        claims: Array.from({ length: RELATIONSHIP_MAPPER_MAX_CLAIMS + 1 }, (_, index) => ({
          ...valid.claims[0],
          claim_id: `relationship-claim-${index + 1}`,
        })),
      }).success,
    ).toBe(false);
    expect(
      RelationshipMapperSchema.safeParse({
        ...valid,
        predictive_graph_status: "EDGES_PRESENT",
        predictive_graph_abstention_confidence: null,
        predictive_edges: Array.from(
          { length: RELATIONSHIP_MAPPER_MAX_PREDICTIVE_EDGES + 1 },
          (_, index) => ({
            edge_local_id: `predictive-edge-${index + 1}`,
            edge_candidate_id: `candidate-${index + 1}`,
            source_entity: "energy",
            target_entity: "industrials",
            edge_type: "input_cost",
            transmission_direction: "NEGATIVE",
            activation_trigger: "Input costs rise materially.",
            evaluation_horizon_trading_days: 20,
            model_confidence: 0.6,
            claim_refs: ["relationship-claim"],
          }),
        ),
      }).success,
    ).toBe(false);
    expect(
      RelationshipMapperSchema.safeParse({
        ...valid,
        predictive_graph_status: "EDGES_PRESENT",
        predictive_graph_abstention_confidence: null,
        predictive_edges: [
          {
            edge_local_id: "predictive-edge-1",
            edge_candidate_id: "candidate-1",
            source_entity: "energy",
            target_entity: "industrials",
            edge_type: "input_cost",
            transmission_direction: "NEGATIVE",
            activation_trigger: "x".repeat(321),
            evaluation_horizon_trading_days: 20,
            model_confidence: 0.6,
            claim_refs: ["relationship-claim"],
          },
        ],
      }).success,
    ).toBe(false);

    const jsonSchema = z.toJSONSchema(RelationshipMapperSchema) as unknown as {
      oneOf: Array<{
        properties: {
          factual_edges: { maxItems: number };
          predictive_edges: { maxItems?: number; items?: false };
          claims: { maxItems: number };
        };
      }>;
    };
    expect(jsonSchema.oneOf[0]?.properties.factual_edges.maxItems).toBe(
      RELATIONSHIP_MAPPER_MAX_FACTUAL_EDGES,
    );
    expect(jsonSchema.oneOf[0]?.properties.predictive_edges.maxItems).toBe(
      RELATIONSHIP_MAPPER_MAX_PREDICTIVE_EDGES,
    );
    expect(jsonSchema.oneOf[0]?.properties.claims.maxItems).toBe(RELATIONSHIP_MAPPER_MAX_CLAIMS);
    const providerSchema = adaptStrictProviderJsonSchema(jsonSchema) as {
      properties: {
        factual_edges: {
          maxItems: number;
          items: { properties: { source_entity: { maxLength: number } } };
        };
        predictive_edges: {
          maxItems: number;
          items: { properties: { activation_trigger: { maxLength: number } } };
        };
      };
    };
    expect(providerSchema.properties.factual_edges.maxItems).toBe(
      RELATIONSHIP_MAPPER_MAX_FACTUAL_EDGES,
    );
    expect(providerSchema.properties.predictive_edges.maxItems).toBe(
      RELATIONSHIP_MAPPER_MAX_PREDICTIVE_EDGES,
    );
    expect(providerSchema.properties.factual_edges.items.properties.source_entity.maxLength).toBe(
      128,
    );
    expect(
      providerSchema.properties.predictive_edges.items.properties.activation_trigger.maxLength,
    ).toBe(320);
  });
});

class InstrumentedSectorLlm {
  readonly prompts: string[] = [];
  private neutralResearch: Record<string, unknown> | null = null;

  constructor(
    private readonly failFinal = false,
    private readonly forcedDirectionFailure:
      | "NONE"
      | "RESOLVED_AFTER_REVIEW"
      | "NO_UNIQUE_PAIR"
      | "NO_UNIQUE_LOSER"
      | "NO_NON_ETF_EDGE" = "NONE",
  ) {}

  withStructuredOutput(
    schema: unknown,
    options?: { name?: string },
  ): { invoke: (input: unknown) => Promise<unknown> } {
    return {
      invoke: async (input) => {
        this.prompts.push(JSON.stringify(input));
        const name = options?.name ?? "energy";
        if (this.failFinal && name === "energy_final_selection") {
          throw new Error("503 service unavailable");
        }
        if (this.forcedDirectionFailure !== "NONE" && name === "energy_conflict_review") {
          if (!this.neutralResearch) throw new Error("neutral research fixture is missing");
          return conflictReviewFromNeutralResearch(
            this.neutralResearch,
            this.forcedDirectionFailure,
          );
        }
        const output = fakeAgentStructuredOutput(schema, name, input);
        if (this.forcedDirectionFailure !== "NONE" && name === "energy_direction_research") {
          const neutral = forceDirectionFailure(output, this.forcedDirectionFailure) as Record<
            string,
            unknown
          >;
          this.neutralResearch = neutral;
          return neutral;
        }
        return output;
      },
    };
  }
}

class MacroSensitiveSectorLlm {
  withStructuredOutput(
    schema: unknown,
    options?: { name?: string },
  ): { invoke: (input: unknown) => Promise<unknown> } {
    return {
      invoke: async (input) => {
        const output = fakeAgentStructuredOutput(schema, options?.name ?? "energy", input);
        if (options?.name !== "energy_direction_research") return output;
        const rendered = JSON.stringify(input);
        const preferred = rendered.includes("SUPPORTIVE") ? "coal" : "solar";
        return forceEnergyDirectionRanking(output, preferred);
      },
    };
  }
}

function forceEnergyDirectionRanking(value: unknown, preferred: "coal" | "solar"): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const record = value as Record<string, unknown>;
  if (!Array.isArray(record.direction_comparisons)) return value;
  const directions = STANDARD_SECTOR_ROLE_CONTRACTS.energy.directionIds;
  const least = preferred === "coal" ? "solar" : "coal";
  const ranking = [
    preferred,
    ...directions.filter((item) => item !== preferred && item !== least),
    least,
  ];
  return {
    ...record,
    direction_comparisons: record.direction_comparisons.map((comparison) => {
      const row = comparison as Record<string, unknown>;
      const aRank = ranking.indexOf(String(row.direction_a_id));
      const bRank = ranking.indexOf(String(row.direction_b_id));
      return {
        ...row,
        criterion_results: Array.isArray(row.criterion_results)
          ? row.criterion_results.map((criterion) => {
              const result = criterion as Record<string, unknown>;
              if (
                result.comparison_status !== "COMPARABLE" ||
                !["FUNDAMENTALS", "VALUATION", "BASKET_TECHNICALS", "RISK_ASYMMETRY"].includes(
                  String(result.criterion),
                )
              ) {
                return result;
              }
              return { ...result, verdict: aRank < bRank ? "FAVORS_A" : "FAVORS_B" };
            })
          : [],
      };
    }),
  };
}

function conflictReviewFromNeutralResearch(
  research: Record<string, unknown>,
  mode: "RESOLVED_AFTER_REVIEW" | "NO_UNIQUE_PAIR" | "NO_UNIQUE_LOSER" | "NO_NON_ETF_EDGE",
): unknown {
  const sourceClaims = Array.isArray(research.comparison_claims) ? research.comparison_claims : [];
  const reviewClaimId = "review-claim-energy-no-qualified";
  const comparisonClaims = sourceClaims.map((value) => {
    const claim = value as Record<string, unknown>;
    return {
      ...claim,
      claim_id: reviewClaimId,
      statement: "Bounded conflict review found no evidence-supported direction.",
      structured_conclusion: { research_mode: "CONFLICT_REVIEW" },
    };
  });
  const comparisons = Array.isArray(research.direction_comparisons)
    ? research.direction_comparisons
    : [];
  const firstDirection = STANDARD_SECTOR_ROLE_CONTRACTS.energy.directionIds[0];
  const reviewComparisons =
    mode === "NO_UNIQUE_LOSER"
      ? comparisons.filter((value) => {
          const comparison = value as Record<string, unknown>;
          return (
            comparison.direction_a_id !== firstDirection &&
            comparison.direction_b_id !== firstDirection
          );
        })
      : comparisons;
  return {
    review_round: 1,
    comparison_claims: comparisonClaims,
    revised_comparisons: reviewComparisons.map((value, index) => {
      const comparison = value as Record<string, unknown>;
      const criterionResults = Array.isArray(comparison.criterion_results)
        ? comparison.criterion_results
        : [];
      return {
        ...comparison,
        comparison_local_id: `review-pair-${index + 1}`,
        criterion_results: criterionResults.map((criterion) => {
          const row = criterion as Record<string, unknown>;
          return {
            ...row,
            ...(mode === "RESOLVED_AFTER_REVIEW" &&
            row.comparison_status === "COMPARABLE" &&
            (row.criterion === "FUNDAMENTALS" || row.criterion === "VALUATION")
              ? { verdict: "FAVORS_A" }
              : {}),
            claim_refs:
              Array.isArray(row.claim_refs) && row.claim_refs.length > 0 ? [reviewClaimId] : [],
          };
        }),
        claim_refs: [reviewClaimId],
      };
    }),
  };
}

function forceDirectionFailure(
  value: unknown,
  mode: "RESOLVED_AFTER_REVIEW" | "NO_UNIQUE_PAIR" | "NO_UNIQUE_LOSER" | "NO_NON_ETF_EDGE",
): unknown {
  if (Array.isArray(value)) return value.map((item) => forceDirectionFailure(item, mode));
  if (!value || typeof value !== "object") return value;
  const record = value as Record<string, unknown>;
  if (Array.isArray(record.direction_comparisons)) {
    const firstDirection = STANDARD_SECTOR_ROLE_CONTRACTS.energy.directionIds[0];
    return {
      ...record,
      direction_comparisons: record.direction_comparisons.map((comparison) => {
        const row = comparison as Record<string, unknown>;
        const keepFirstWinner = mode === "NO_UNIQUE_LOSER" && row.direction_a_id === firstDirection;
        return {
          ...row,
          criterion_results: Array.isArray(row.criterion_results)
            ? row.criterion_results.map((criterion) => {
                const result = criterion as Record<string, unknown>;
                if (keepFirstWinner) return result;
                if (mode === "NO_NON_ETF_EDGE") {
                  const isEtf =
                    result.criterion === "ETF_PRICE_CONFIRMATION" ||
                    result.criterion === "ETF_SHARE_FLOW_CONFIRMATION";
                  return {
                    ...result,
                    verdict: isEtf ? "FAVORS_A" : "NEUTRAL",
                    comparison_status: isEtf ? "COMPARABLE" : result.comparison_status,
                    claim_refs: isEtf ? row.claim_refs : result.claim_refs,
                  };
                }
                if (result.comparison_status !== "COMPARABLE") return result;
                return { ...result, verdict: "NEUTRAL" };
              })
            : [],
        };
      }),
    };
  }
  return Object.fromEntries(
    Object.entries(record).map(([key, child]) => [
      key,
      key === "verdict" && record.comparison_status === "COMPARABLE"
        ? "NEUTRAL"
        : forceDirectionFailure(child, mode),
    ]),
  );
}

function canonicalHash(value: unknown): string {
  const canonicalize = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(canonicalize);
    if (item && typeof item === "object") {
      return Object.fromEntries(
        Object.entries(item as Record<string, unknown>)
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([key, child]) => [key, canonicalize(child)]),
      );
    }
    return item;
  };
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(value)))
    .digest("hex")}`;
}

function sectorSnapshot(): string {
  const directions = STANDARD_SECTOR_ROLE_CONTRACTS.energy.directionIds;
  const roleEvent = JSON.parse(roleEventSnapshot()) as Record<string, unknown>;
  const securityScoringRows = directions
    .map((directionId, index) => {
      const body = {
        ts_code: `${String(600000 + index).padStart(6, "0")}.SH`,
        direction_id: directionId,
        availability_status: "AVAILABLE",
        unavailability_reason: null,
        observation_date: "2026-07-19T08:00:00Z",
        released_at: "2026-07-19T08:00:00Z",
        vintage_at: "2026-07-19T08:00:00Z",
        pit_status: "PIT_VERIFIED",
        adjusted_return_20d: 0.1 - index * 0.01,
        realized_volatility_20d: 0.2 + index * 0.01,
        median_amount_20d_cny: 1_000_000 - index,
        net_moneyflow_20d_cny: 10_000 - index,
        observation_count: 20,
        required_observation_count: 20,
        coverage_ratio: 1,
        evidence_ids: [`sector-score-${index}`],
      };
      return { ...body, security_scoring_row_hash: canonicalHash(body) };
    })
    .sort((left, right) =>
      `${left.direction_id}\0${left.ts_code}`.localeCompare(
        `${right.direction_id}\0${right.ts_code}`,
      ),
    );
  const snapshot = {
    schema_version: "sector_research_snapshot_v4",
    sector_agent_id: "energy",
    as_of_date: "2026-07-19",
    direction_ids: directions,
    direction_cards: directions.map((directionId, index) => ({
      direction_id: directionId,
      eligible_count: 1,
      readiness_status: "READY",
      membership_hash: canonicalHash({ directionId }),
      etf_family: {
        etf_family_id: `etf-family:${directionId}`,
        direction_id: directionId,
        etf_ts_codes: [`51${String(index).padStart(4, "0")}.SH`],
      },
      metrics: [
        {
          metric_id: "ETF_RELATIVE_RETURN_20D",
          metric_family: "ETF_CONFIRMATION",
          unit: "RATIO",
          availability_status: "AVAILABLE",
          value: index === 0 ? 0.42 : -0.1,
          observation_date: "2026-07-19",
          released_at: "2026-07-19T08:00:00Z",
          vintage_at: "2026-07-19T08:00:00Z",
          pit_status: "PIT_VERIFIED",
          observation_count: 20,
          eligible_count: 1,
          observed_count: 1,
          coverage_ratio: 1,
          etf_family_id: `etf-family:${directionId}`,
          etf_family_hash: canonicalHash({ directionId, family: true }),
          metric_observation_hash: canonicalHash({ directionId, metric: true }),
        },
      ],
      direction_card_hash: canonicalHash({ directionId, card: true }),
    })),
    eligible_security_universe: directions.map((directionId, index) => ({
      ts_code: `${String(600000 + index).padStart(6, "0")}.SH`,
      direction_id: directionId,
      l1_code: null,
      l2_code: null,
      l3_code: null,
      in_date: "2020-01-01",
      out_date: null,
      released_at: "2026-07-19T08:00:00Z",
      vintage_at: "2026-07-19T08:00:00Z",
      pit_status: "PIT_VERIFIED",
      membership_row_hash: canonicalHash({ directionId, member: true }),
    })),
    eligible_count: directions.length,
    security_scoring_contract_version: SECURITY_SCORING_CONTRACT_VERSION,
    security_scoring_contract_hash: SECURITY_SCORING_CONTRACT_HASH,
    security_scoring_rows: securityScoringRows,
    security_scoring_rows_hash: canonicalHash(securityScoringRows),
    event_coverage: roleEvent.coverage,
    role_event_snapshot_ref: {
      role_event_snapshot_id: roleEvent.role_event_snapshot_id,
      role_event_snapshot_hash: roleEvent.role_event_snapshot_hash,
    },
  };
  return JSON.stringify({ ...snapshot, snapshot_hash: canonicalHash(snapshot) });
}

function roleEventSnapshot(): string {
  const withoutId = {
    schema_version: "role_event_snapshot_v2",
    consumer_agent: "energy",
    as_of: "2026-07-19T08:00:00Z",
    contract_version: "role_event_coverage_v2",
    coverage: {
      coverage_state: "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT",
      event_presence_state: "NO_MATERIAL_EVENT_OBSERVED",
      coverage_completeness: "COMPLETE",
      coverage_as_of: "2026-07-19T08:00:00Z",
      query_complete: true,
      required_route_ids: ["eco-cal:fixture:CNY:China"],
      healthy_route_ids: ["eco-cal:fixture:CNY:China"],
      unhealthy_route_ids: [],
      coverage_evidence_ids: ["role-event-coverage"],
      material_event_revision_ids: [],
      coverage_contract_version: "role_event_coverage_v2",
    },
    projections: [],
  };
  const body = {
    role_event_snapshot_id: `role-event-snapshot:${canonicalHash(withoutId).slice("sha256:".length)}`,
    ...withoutId,
  };
  return JSON.stringify({ ...body, role_event_snapshot_hash: canonicalHash(body) });
}

function rehashRoleEventSnapshot(payload: Record<string, unknown>): string {
  const withoutId = Object.fromEntries(
    Object.entries(payload).filter(
      ([key]) => key !== "role_event_snapshot_id" && key !== "role_event_snapshot_hash",
    ),
  );
  const body = {
    role_event_snapshot_id: `role-event-snapshot:${canonicalHash(withoutId).slice("sha256:".length)}`,
    ...withoutId,
  };
  return JSON.stringify({ ...body, role_event_snapshot_hash: canonicalHash(body) });
}

function rehashSectorSnapshot(payload: Record<string, unknown>): string {
  const body = Object.fromEntries(
    Object.entries(payload).filter(([key]) => key !== "snapshot_hash"),
  );
  return JSON.stringify({ ...body, snapshot_hash: canonicalHash(body) });
}

function instrumentedSectorApi(
  events: {
    reports: SectorModelUsageReport[];
    lifecycle: string[];
  },
  overrides: { sectorSnapshot?: string; roleEventSnapshot?: string } = {},
): BridgeApi {
  let preparedRequest: ToolCapabilityPrepareRequest | null = null;
  const capabilityHash = `sha256:${"a".repeat(64)}`;
  return {
    toolsPrepareCapability: async (request: ToolCapabilityPrepareRequest) => {
      preparedRequest = request;
      const tools = STANDARD_SECTOR_ROLE_CONTRACTS.energy.requiredTools;
      const bundle = {
        snapshot_bundle_id: "bundle-sector-instrumented",
        snapshot_bundle_hash: capabilityHash,
        snapshot_bundle_contract_version: "agent_snapshot_bundle_v1" as const,
        materialization_request_id: request.materialization_request_id,
        agent_id: "energy" as const,
        stage: "energy" as const,
        as_of: request.as_of,
        candidate_scope_hash: `sha256:${"b".repeat(64)}`,
        runtime_input_hash: `sha256:${"c".repeat(64)}`,
        tool_payload_hashes: Object.fromEntries(
          tools.map((name, index) => [name, `sha256:${String(index + 1).repeat(64)}`]),
        ),
        materialized_at: "2026-07-19T08:00:00Z",
      };
      return {
        bundle,
        capability: {
          manifest: {
            capability_contract_version: "agent_tool_capability_v1" as const,
            capability_id: "cap-sector-instrumented",
            graph_run_id: request.graph_run_id,
            run_slot_id: request.run_slot_id,
            run_id: request.run_id,
            node_id: request.node_id,
            agent_id: "energy" as const,
            stage: "energy" as const,
            allowed_tools: [...tools],
            as_of: request.as_of,
            candidate_scope_hash: bundle.candidate_scope_hash,
            snapshot_bundle_id: bundle.snapshot_bundle_id,
            snapshot_bundle_hash: bundle.snapshot_bundle_hash,
            issued_at: "2026-07-19T08:00:00Z",
            expires_at: "2026-07-19T08:15:00Z",
            nonce: "fixture-nonce",
          },
          signing_key_id: "fixture-key",
          signature: `hmac-sha256:${"d".repeat(64)}`,
        },
      };
    },
    toolsList: async () =>
      STANDARD_SECTOR_ROLE_CONTRACTS.energy.requiredTools.map((name) => ({
        name,
        description: name,
        args_schema: { type: "object", properties: {}, additionalProperties: false },
      })),
    toolsCall: async (name: string) => ({
      text:
        name === "get_sector_research_snapshot"
          ? (overrides.sectorSnapshot ?? sectorSnapshot())
          : (overrides.roleEventSnapshot ?? roleEventSnapshot()),
    }),
    toolsRecordModelUsage: async (
      _capability: SignedAgentToolCapability,
      report: SectorModelUsageReport,
    ) => {
      events.reports.push(report);
      events.lifecycle.push(`record:${report.attempted_stage}:${report.attempt_index}`);
      return {};
    },
    toolsFinalizeModelUsage: async (capability: SignedAgentToolCapability) => {
      events.lifecycle.push("finalize");
      const finalReport = events.reports.at(-1);
      const completed =
        finalReport?.attempted_stage === "FINAL_SELECTION" &&
        finalReport.attempt_status === "ACCEPTED";
      const instrumentation = {
        instrumentation_contract_id: "sector_inference_usage_instrumentation",
        instrumentation_contract_version: "sector_inference_usage_instrumentation_v1",
        source_contract_version: "server_owned_model_usage_ledger_v1",
        measurement_rule: "sum_provider_reported_tokens_and_count_attempted_model_subcalls",
      };
      const unsigned = {
        schema_version: "sector_model_usage_summary_receipt_v1" as const,
        usage_summary_receipt_id: "sector-usage-summary:instrumented",
        capability_id: capability.manifest.capability_id,
        capability_manifest_hash: canonicalHash(capability.manifest),
        graph_run_id: capability.manifest.graph_run_id,
        run_slot_id: capability.manifest.run_slot_id,
        run_id: capability.manifest.run_id,
        node_id: capability.manifest.node_id,
        agent_id: capability.manifest.agent_id,
        stage: capability.manifest.stage,
        as_of: capability.manifest.as_of,
        snapshot_bundle_id: capability.manifest.snapshot_bundle_id,
        snapshot_bundle_hash: capability.manifest.snapshot_bundle_hash,
        pair_root_reservation_id: null,
        pair_side: null,
        budget_contract_ref: null,
        model_subcall_count: events.reports.length,
        last_attempted_stage: completed
          ? ("COMPLETED" as const)
          : (finalReport?.attempted_stage ?? ("PRE_MODEL" as const)),
        conflict_review_triggered: events.reports.some(
          (report) => report.attempted_stage === "CONFLICT_REVIEW",
        ),
        input_tokens: events.reports.reduce((sum, report) => sum + report.input_tokens, 0),
        output_tokens: events.reports.reduce((sum, report) => sum + report.output_tokens, 0),
        model_path_disposition: completed ? ("COMPLETED" as const) : ("INCOMPLETE" as const),
        direction_comparison_audit_id: completed
          ? (finalReport?.direction_comparison_audit_id ?? null)
          : null,
        direction_comparison_audit_hash: completed
          ? (finalReport?.direction_comparison_audit_hash ?? null)
          : null,
        conflict_review_id: completed ? (finalReport?.conflict_review_id ?? null) : null,
        conflict_review_hash: completed ? (finalReport?.conflict_review_hash ?? null) : null,
        ...instrumentation,
        instrumentation_contract_hash: canonicalHash(instrumentation),
        usage_ledger_record_id: "sector-usage-ledger:instrumented",
        usage_ledger_record_hash: canonicalHash(events.reports),
        measured_at: "2026-07-19T08:01:00Z",
        finalized_at: "2026-07-19T08:01:01Z",
        receipt_signing_key_id: "fixture-key",
      };
      const receiptHash = canonicalHash(unsigned);
      return {
        ...unsigned,
        usage_summary_receipt_hash: receiptHash,
        receipt_signature: `hmac-sha256:${"e".repeat(64)}`,
      } satisfies SectorModelUsageSummaryReceipt;
    },
    toolsTerminateCapability: async () => {
      events.lifecycle.push("terminate");
      expect(preparedRequest).not.toBeNull();
      return { terminated: true as const };
    },
  } as unknown as BridgeApi;
}

function sectorPipelineState(): DailyCycleStateType {
  return {
    messages: [],
    active_cohort: "cohort_default",
    as_of_date: "2026-07-19",
    mode: "live",
    trace_id: "sector-instrumented-run",
    darwinian_runtime_binding: null,
    darwinian_weight_snapshot: null,
    component_weight_snapshot: null,
    component_calibration_inputs: {},
    outcome_schedule_plan: null,
    outcome_stage_skips: {},
    outcome_opportunity_bindings: {},
    accepted_output_refs: {},
    continuity_context: {},
    lesson_context: {},
    method_context: {},
    layer1_outputs: {},
    macro_input_gate: null,
    layer2_outputs: {},
    layer3_outputs: {},
    layer4_outputs: emptyLayer4(),
    current_positions: emptyCurrentPositions(),
    position_reviews: [],
    position_audit: emptyPositionAudit(),
    portfolio_actions: [],
    replay_triggered: false,
    llm_calls: [],
  };
}

function sectorPipelineStateWithChina(direction: "SUPPORTIVE" | "ADVERSE"): DailyCycleStateType {
  const state = sectorPipelineState();
  const outputs = Object.fromEntries(
    MACRO_AGENT_IDS.map((agent) => [
      agent,
      macroOutput(agent, {
        ...(agent === "china" ? { direction, strength: 5 as const } : {}),
      }),
    ]),
  ) as DailyCycleStateType["layer1_outputs"];
  state.layer1_outputs = outputs;
  state.macro_input_gate = validateMacroInputs(
    outputs as Parameters<typeof validateMacroInputs>[0],
  );
  return state;
}

describe("standard Sector usage lifecycle", () => {
  let promptDir: string;
  const config: MosaicConfig = {
    llm_provider: "openai",
    deep_think_llm: "fixture-model",
    quick_think_llm: "fixture-model",
    backend_url: null,
    anthropic_base_url: null,
    anthropic_effort: null,
    output_language: "Chinese",
    research_depth_name: "标准",
    active_cohort: "cohort_default",
    cohorts: { cohort_default: { start: "2000-01-01", end: "2099-12-31" } },
    autoresearch: {
      agent_mutation_cooldown_hours: 24,
      keep_revert_lockout_days: 3,
      keep_threshold_delta_sharpe: 0.1,
      monthly_modification_cap_per_cohort: 100,
      evaluation_horizon_trading_days: 5,
    },
    data_vendors: {},
    tool_vendors: {},
  };

  beforeEach(() => {
    promptDir = mkdtempSync(join(tmpdir(), "mosaic-sector-usage-"));
    const dir = join(promptDir, "cohort_default", "sector");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "energy.zh.md"), "FIXTURE", "utf8");
    writeFileSync(join(dir, "energy.en.md"), "FIXTURE", "utf8");
    clearPromptCache();
  });

  afterEach(() => {
    rmSync(promptDir, { recursive: true, force: true });
    clearPromptCache();
  });

  it("does not let the fake provider bypass v4 scoring evidence and PIT semantics", async () => {
    const snapshot = JSON.parse(sectorSnapshot()) as Record<string, unknown>;
    const rows = snapshot.security_scoring_rows as Array<Record<string, unknown>>;
    const first = { ...rows[0], evidence_ids: [], vintage_at: "2026-07-20T00:00:00Z" };
    const firstBody = Object.fromEntries(
      Object.entries(first).filter(([key]) => key !== "security_scoring_row_hash"),
    );
    rows[0] = { ...firstBody, security_scoring_row_hash: canonicalHash(firstBody) };
    snapshot.security_scoring_rows_hash = canonicalHash(rows);
    const events = { reports: [] as SectorModelUsageReport[], lifecycle: [] as string[] };
    const handle: LlmHandle = {
      llm: new InstrumentedSectorLlm() as unknown as LlmHandle["llm"],
      provider: "fake",
      model: "fixture-model",
      baseUrl: undefined,
    };

    await expect(
      buildEnergyNode({
        llmHandle: handle,
        api: instrumentedSectorApi(events, {
          sectorSnapshot: rehashSectorSnapshot(snapshot),
        }),
        config,
        promptsRoot: promptDir,
      })(sectorPipelineState()),
    ).rejects.toThrow("snapshot security scoring rows are not exact PIT bindings");
    expect(events.reports).toEqual([]);
    expect(events.lifecycle.at(-1)).toBe("terminate");
  });

  it("rejects individually hashed Sector and role-event snapshots that are not cross-bound", async () => {
    const snapshot = JSON.parse(sectorSnapshot()) as Record<string, unknown>;
    (snapshot.role_event_snapshot_ref as Record<string, unknown>).role_event_snapshot_hash =
      `sha256:${"f".repeat(64)}`;
    const events = { reports: [] as SectorModelUsageReport[], lifecycle: [] as string[] };
    const handle: LlmHandle = {
      llm: new InstrumentedSectorLlm() as unknown as LlmHandle["llm"],
      provider: "openai",
      model: "fixture-model",
      baseUrl: undefined,
    };

    await expect(
      buildEnergyNode({
        llmHandle: handle,
        api: instrumentedSectorApi(events, {
          sectorSnapshot: rehashSectorSnapshot(snapshot),
        }),
        config,
        promptsRoot: promptDir,
      })(sectorPipelineState()),
    ).rejects.toThrow("Sector/role-event snapshot cross-binding mismatch");
    expect(events.reports).toEqual([]);
    expect(events.lifecycle.at(-1)).toBe("terminate");
  });

  it("records every successful stage, grounds final selection, finalizes, then terminates", async () => {
    const events = { reports: [] as SectorModelUsageReport[], lifecycle: [] as string[] };
    const llm = new InstrumentedSectorLlm();
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "openai",
      model: "fixture-model",
      baseUrl: undefined,
    };
    const update = await buildEnergyNode({
      llmHandle: handle,
      api: instrumentedSectorApi(events),
      config,
      promptsRoot: promptDir,
    })(sectorPipelineState());

    expect(update.layer2_outputs).toMatchObject({ energy: expect.any(Object) });
    expect(events.reports.map((report) => report.attempted_stage)).toEqual([
      "DIRECTION_RESEARCH",
      "FINAL_SELECTION",
    ]);
    expect(events.lifecycle.at(-2)).toBe("finalize");
    expect(events.lifecycle.at(-1)).toBe("terminate");
    const finalPrompt = llm.prompts.at(-1) ?? "";
    expect(finalPrompt).toContain("sector_final_grounding_projection_v1");
    expect(finalPrompt).toContain("ETF_RELATIVE_RETURN_20D");
    expect(finalPrompt).toContain("0.42");
    expect(finalPrompt).toContain("finalized_comparisons");
    expect(finalPrompt).toContain("comparison_claims");
    expect(finalPrompt).toContain("evidence_aliases");
    const calls = update.llm_calls as
      | Array<{
          sector_inference_audit?: {
            direction_comparison_audit: Record<string, unknown>;
          };
        }>
      | undefined;
    const comparisonAudit = calls?.[0]?.sector_inference_audit?.direction_comparison_audit;
    expect(comparisonAudit).toMatchObject({
      resolver_contract_id: SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT.resolver_contract_id,
      resolver_contract_version:
        SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT.resolver_contract_version,
      resolver_contract_hash: SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT.resolver_contract_hash,
      reducer_contract_version:
        SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT.resolver_contract_version,
    });
  });

  it("can propagate one audited Macro judgment delta into a real Sector selection", async () => {
    const run = async (direction: "SUPPORTIVE" | "ADVERSE") => {
      const events = { reports: [] as SectorModelUsageReport[], lifecycle: [] as string[] };
      const handle: LlmHandle = {
        llm: new MacroSensitiveSectorLlm() as unknown as LlmHandle["llm"],
        provider: "fake",
        model: "fixture-model",
        baseUrl: undefined,
      };
      return buildEnergyNode({
        llmHandle: handle,
        api: instrumentedSectorApi(events),
        config,
        promptsRoot: promptDir,
      })(sectorPipelineStateWithChina(direction));
    };

    const supportive = await run("SUPPORTIVE");
    const adverse = await run("ADVERSE");
    const selected = (update: Awaited<ReturnType<typeof run>>) =>
      (update.layer2_outputs as Record<string, { preferred_direction: { direction_id: string } }>)
        .energy?.preferred_direction.direction_id;
    expect(selected(supportive)).toBe("coal");
    expect(selected(adverse)).toBe("solar");
  });

  it("preserves the triggering conflict after a successful bounded review", async () => {
    const events = { reports: [] as SectorModelUsageReport[], lifecycle: [] as string[] };
    const llm = new InstrumentedSectorLlm(false, "RESOLVED_AFTER_REVIEW");
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "openai",
      model: "fixture-model",
      baseUrl: undefined,
    };
    const update = await buildEnergyNode({
      llmHandle: handle,
      api: instrumentedSectorApi(events),
      config,
      promptsRoot: promptDir,
    })(sectorPipelineState());

    expect(events.reports.map((report) => report.attempted_stage)).toEqual([
      "DIRECTION_RESEARCH",
      "CONFLICT_REVIEW",
      "FINAL_SELECTION",
    ]);
    const calls = update.llm_calls as
      | Array<{
          sector_inference_audit?: {
            direction_comparison_audit: Record<string, unknown>;
          };
        }>
      | undefined;
    const comparisonAudit = calls?.[0]?.sector_inference_audit?.direction_comparison_audit;
    expect(comparisonAudit).toMatchObject({
      conflict_review_status: "COMPLETED",
      final_conflict_type: "NONE",
      final_conflict_direction_ids: [],
      condorcet_winner_direction_id: expect.any(String),
      condorcet_loser_direction_id: expect.any(String),
    });
    expect(comparisonAudit?.conflict_type).not.toBe("NONE");
    expect(comparisonAudit?.conflict_direction_ids).toEqual(expect.any(Array));
    expect((comparisonAudit?.conflict_direction_ids as unknown[]).length).toBeGreaterThan(0);
    expect(llm.prompts[1]).toContain("sector_research_snapshot_v4");
    expect(llm.prompts[1]).toContain("ETF_RELATIVE_RETURN_20D");
  });

  it("rejects the stage when conflict review still has no unique best/worst pair", async () => {
    const events = { reports: [] as SectorModelUsageReport[], lifecycle: [] as string[] };
    const llm = new InstrumentedSectorLlm(false, "NO_UNIQUE_PAIR");
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "openai",
      model: "fixture-model",
      baseUrl: undefined,
    };

    await expect(
      buildEnergyNode({
        llmHandle: handle,
        api: instrumentedSectorApi(events),
        config,
        promptsRoot: promptDir,
      })(sectorPipelineState()),
    ).rejects.toThrow("Sector stage rejected: no unique Condorcet winner");
    expect(events.reports.map((report) => report.attempted_stage)).toEqual([
      "DIRECTION_RESEARCH",
      "CONFLICT_REVIEW",
    ]);
    expect(events.lifecycle.slice(-2)).toEqual(["finalize", "terminate"]);
    expect(llm.prompts.some((prompt) => prompt.includes("Runtime substage: final_selection"))).toBe(
      false,
    );
  });

  it("rejects the stage when a unique winner has no unique least-preferred direction", async () => {
    const events = { reports: [] as SectorModelUsageReport[], lifecycle: [] as string[] };
    const llm = new InstrumentedSectorLlm(false, "NO_UNIQUE_LOSER");
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "openai",
      model: "fixture-model",
      baseUrl: undefined,
    };

    await expect(
      buildEnergyNode({
        llmHandle: handle,
        api: instrumentedSectorApi(events),
        config,
        promptsRoot: promptDir,
      })(sectorPipelineState()),
    ).rejects.toThrow(/no unique Condorcet loser/);
    expect(events.reports.map((report) => report.attempted_stage)).toEqual([
      "DIRECTION_RESEARCH",
      "CONFLICT_REVIEW",
    ]);
    expect(events.lifecycle.slice(-2)).toEqual(["finalize", "terminate"]);
  });

  it("rejects the stage when ETF-only comparisons have no decisive non-ETF edge", async () => {
    const events = { reports: [] as SectorModelUsageReport[], lifecycle: [] as string[] };
    const llm = new InstrumentedSectorLlm(false, "NO_NON_ETF_EDGE");
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "openai",
      model: "fixture-model",
      baseUrl: undefined,
    };

    await expect(
      buildEnergyNode({
        llmHandle: handle,
        api: instrumentedSectorApi(events),
        config,
        promptsRoot: promptDir,
      })(sectorPipelineState()),
    ).rejects.toThrow("Sector stage rejected: no unique Condorcet winner");
    expect(events.reports.map((report) => report.attempted_stage)).toEqual([
      "DIRECTION_RESEARCH",
      "CONFLICT_REVIEW",
    ]);
    expect(events.lifecycle.slice(-2)).toEqual(["finalize", "terminate"]);
  });

  it("records and finalizes an operational final-stage failure before termination", async () => {
    const events = { reports: [] as SectorModelUsageReport[], lifecycle: [] as string[] };
    const llm = new InstrumentedSectorLlm(true);
    const handle: LlmHandle = {
      llm: llm as unknown as LlmHandle["llm"],
      provider: "openai",
      model: "fixture-model",
      baseUrl: undefined,
    };

    await expect(
      buildEnergyNode({
        llmHandle: handle,
        api: instrumentedSectorApi(events),
        config,
        promptsRoot: promptDir,
      })(sectorPipelineState()),
    ).rejects.toThrow(/MODEL_SERVICE_ERROR/);
    expect(events.reports.at(-1)).toMatchObject({
      attempted_stage: "FINAL_SELECTION",
      attempt_status: "OPERATIONAL_FAILURE",
    });
    expect(events.lifecycle.at(-2)).toBe("finalize");
    expect(events.lifecycle.at(-1)).toBe("terminate");
  });
});
