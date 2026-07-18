import { describe, expect, it } from "vitest";
import { MACRO_AGENT_IDS } from "../src/agents/macro/_contracts.js";
import { AGENTS_BY_LAYER } from "../src/agents/prompts/cohorts.js";
import {
  SECTOR_AGENT_IDS,
  STANDARD_SECTOR_AGENT_IDS,
  STANDARD_SECTOR_ROLE_CONTRACTS,
} from "../src/agents/sector/_contracts.js";
import {
  compactRelationshipExtractorAnalysis,
  renderSectorDirectionResearchPayloads,
} from "../src/agents/sector/_factory.js";
import {
  buildStandardSectorSchema,
  RelationshipMapperSchema,
} from "../src/agents/sector/_schemas.js";
import { standardSectorSpec } from "../src/agents/sector/_spec.js";
import { relationshipMapperSpec } from "../src/agents/sector/relationship_mapper.js";
import { LAYER2_AGENT_NODES } from "../src/graph/layer2.js";
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
    expect(role.directionIds.length).toBeGreaterThanOrEqual(1);
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
  });

  it("keeps source ids distinct from the runtime claim-evidence catalog", () => {
    const rendered = renderSectorDirectionResearchPayloads(
      new Map([
        [
          "get_sector_research_snapshot",
          JSON.stringify({
            direction_cards: [
              { direction_id: "semiconductor_core", evidence_ids: ["source-card-evidence"] },
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
      least_preferred_status: "NOT_QUALIFIED" as const,
      least_preferred_direction_id: null,
      least_preferred_reason: "NO_UNIQUE_CONDORCET_LOSER" as const,
      allowed_preferred_security_ids: [],
      allowed_least_preferred_security_ids: [],
    };
    const output = sectorOutput("energy");
    if (!("direction_id" in output.preferred_direction)) throw new Error("fixture must select");
    output.preferred_direction.direction_id = "coal";
    output.preferred_direction.direction_local_id = "coal";
    const schema = buildStandardSectorSchema("energy", "SELECTED", directive);
    expect(schema.safeParse(output).success).toBe(true);
    output.preferred_direction.direction_id = "oil_gas";
    expect(schema.safeParse(output).success).toBe(false);
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
  });

  it("requires structured relationships, risks, evidence, and claims", () => {
    expect(
      RelationshipMapperSchema.parse({
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
      }).agent,
    ).toBe("relationship_mapper");
  });
});
