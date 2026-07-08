import { alphaDiscoverySpec } from "../decision/alpha_discovery.js";
import { autonomousExecutionSpec } from "../decision/autonomous_execution.js";
import { cioSpec } from "../decision/cio.js";
import { croSpec } from "../decision/cro.js";
import { centralBankSpec } from "../macro/central_bank.js";
import { chinaSpec } from "../macro/china.js";
import { commoditiesSpec } from "../macro/commodities.js";
import { dollarSpec } from "../macro/dollar.js";
import { emergingMarketsSpec } from "../macro/emerging_markets.js";
import { geopoliticalSpec } from "../macro/geopolitical.js";
import { institutionalFlowSpec } from "../macro/institutional_flow.js";
import { newsSentimentSpec } from "../macro/news_sentiment.js";
import { volatilitySpec } from "../macro/volatility.js";
import { yieldCurveSpec } from "../macro/yield_curve.js";
import { biotechSpec } from "../sector/biotech.js";
import { consumerSpec } from "../sector/consumer.js";
import { energySpec } from "../sector/energy.js";
import { financialsSpec } from "../sector/financials.js";
import { industrialsSpec } from "../sector/industrials.js";
import { relationshipMapperSpec } from "../sector/relationship_mapper.js";
import { semiconductorSpec } from "../sector/semiconductor.js";
import { ackmanSpec } from "../superinvestor/ackman.js";
import { burrySpec } from "../superinvestor/burry.js";
import { druckenmillerSpec } from "../superinvestor/druckenmiller.js";
import { mungerSpec } from "../superinvestor/munger.js";
import type { Layer } from "./cohorts.js";

export interface RuntimeAgentSpec {
  agent: string;
  layer: Layer;
  promptIrAgentId: string;
  fieldNames: ReadonlyArray<string>;
  requiredTools: ReadonlyArray<string>;
}

function runtimeSpec(
  layer: Layer,
  spec: {
    agentId: string;
    fieldNames: ReadonlyArray<string>;
    requiredTools?: ReadonlyArray<string>;
  },
): RuntimeAgentSpec {
  return {
    agent: spec.agentId,
    layer,
    promptIrAgentId: `${layer}.${spec.agentId}`,
    fieldNames: spec.fieldNames,
    requiredTools: spec.requiredTools ?? [],
  };
}

export const RUNTIME_AGENT_SPECS: ReadonlyArray<RuntimeAgentSpec> = [
  runtimeSpec("macro", centralBankSpec),
  runtimeSpec("macro", geopoliticalSpec),
  runtimeSpec("macro", chinaSpec),
  runtimeSpec("macro", dollarSpec),
  runtimeSpec("macro", yieldCurveSpec),
  runtimeSpec("macro", commoditiesSpec),
  runtimeSpec("macro", volatilitySpec),
  runtimeSpec("macro", emergingMarketsSpec),
  runtimeSpec("macro", newsSentimentSpec),
  runtimeSpec("macro", institutionalFlowSpec),
  runtimeSpec("sector", semiconductorSpec),
  runtimeSpec("sector", energySpec),
  runtimeSpec("sector", biotechSpec),
  runtimeSpec("sector", consumerSpec),
  runtimeSpec("sector", industrialsSpec),
  runtimeSpec("sector", financialsSpec),
  runtimeSpec("sector", relationshipMapperSpec),
  runtimeSpec("superinvestor", druckenmillerSpec),
  runtimeSpec("superinvestor", mungerSpec),
  runtimeSpec("superinvestor", burrySpec),
  runtimeSpec("superinvestor", ackmanSpec),
  runtimeSpec("decision", croSpec),
  runtimeSpec("decision", alphaDiscoverySpec),
  runtimeSpec("decision", autonomousExecutionSpec),
  runtimeSpec("decision", cioSpec),
];

export const RUNTIME_AGENT_SPEC_BY_AGENT: ReadonlyMap<string, RuntimeAgentSpec> = new Map(
  RUNTIME_AGENT_SPECS.map((spec) => [spec.agent, spec]),
);
