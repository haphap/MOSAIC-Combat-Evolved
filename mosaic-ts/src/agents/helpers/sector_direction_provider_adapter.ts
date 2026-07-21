const COMPACT_DIRECTION_RESEARCH = "SECTOR_DIRECTION_RESEARCH_COMPACT_V3";
const COMPACT_CONFLICT_REVIEW = "SECTOR_CONFLICT_REVIEW_COMPACT_V4";

export const SECTOR_DIRECTION_PROVIDER_INSTRUCTION =
  "The bounded provider extraction contract may request a compact exact pair tuple. For every " +
  "pair, judge the eight named criteria through the ten ordered decision/coverage fields, copy one exact runtime evidence_id, and copy one exact " +
  "research_rule_ref only when the catalog permits it. Provide the complete ordered Macro-event " +
  "and catalyst coverage evidence-id lists separately. decisions order is " +
  "fundamentals, valuation, basket technicals, risk asymmetry, macro coverage state, macro " +
  "verdict, catalyst coverage state, catalyst verdict, ETF price, ETF share flow. Runtime expands only " +
  "the repetitive claim and criterion envelopes. Initial research verdicts are preserved exactly. " +
  "Conflict review additionally requires one best-to-worst direction_order; that order is the " +
  "authoritative conflict-resolution verdict and runtime projects it consistently across comparable " +
  "criterion fields while preserving coverage states and unavailable ETF fields. Within the registered " +
  "core metrics, stronger growth, cash generation, earnings/book yield, relative return, participation, " +
  "liquidity, and flow support favor that direction; lower volatility and a less severe drawdown favor " +
  "that direction on risk asymmetry. When every available metric in a criterion favors one side, that " +
  "criterion must favor the same side. Use NEUTRAL only " +
  "when the available evidence genuinely does not distinguish the pair. Apply the same evidence rule " +
  "to every pair regardless of pair presentation order: when multiple registered metrics consistently " +
  "order the directions without an offsetting event, preserve that transitive evidence-backed ordering. During the " +
  "single conflict review, reconsider the named conflict pairs from the frozen evidence instead of " +
  "repeating a default neutral judgment.";

const COMPARABLE_VERDICTS = ["FAVORS_A", "FAVORS_B", "NEUTRAL"] as const;
const OPTIONAL_ETF_VERDICTS = [...COMPARABLE_VERDICTS, "INCOMPARABLE"] as const;

type ComparableVerdict = (typeof COMPARABLE_VERDICTS)[number];
type OptionalEtfVerdict = (typeof OPTIONAL_ETF_VERDICTS)[number];

interface CompactDirectionDecision {
  decisions: [
    ComparableVerdict,
    ComparableVerdict,
    ComparableVerdict,
    ComparableVerdict,
    string,
    ComparableVerdict,
    string,
    ComparableVerdict,
    OptionalEtfVerdict,
    OptionalEtfVerdict,
  ];
}

interface CompactDirectionEvidence {
  evidence_id: string;
  research_rule_ref: string | null;
  claim_kind: "FACT" | "EVENT" | "INTERPRETATION" | "RISK_FLAG";
  macro_event_coverage_evidence_ids: string[];
  catalyst_coverage_evidence_ids: string[];
}

interface CompactDirectionPair extends CompactDirectionDecision {
  pair_key: string;
}

/** Keep model judgment fields while moving repetitive eight-criterion expansion into runtime. */
export function adaptSectorDirectionProviderJsonSchema(value: unknown): unknown {
  const root = objectRecord(value);
  const properties = objectRecord(root?.properties);
  if (!root || !properties) return recurseSchema(value);

  const researchMode = schemaConst(properties.research_mode);
  const reviewRound = schemaConst(properties.review_round);
  const contract =
    researchMode === "PAIRWISE"
      ? COMPACT_DIRECTION_RESEARCH
      : reviewRound === 1
        ? COMPACT_CONFLICT_REVIEW
        : null;
  const matrixProperty =
    contract === COMPACT_DIRECTION_RESEARCH
      ? properties.direction_comparisons
      : contract === COMPACT_CONFLICT_REVIEW
        ? properties.revised_comparisons
        : null;
  const matrix = objectRecord(matrixProperty);
  const pairSchemas = Array.isArray(matrix?.prefixItems) ? matrix.prefixItems : null;
  if (!contract || !pairSchemas || pairSchemas.length === 0) return recurseSchema(value);

  const compactPairs = pairSchemas.map(compactPairSchema);
  if (compactPairs.some((schema) => schema === null)) return recurseSchema(value);
  const firstCriteria = criterionSchemas(pairSchemas[0]);
  const macroCoverageEvidence = coverageEvidenceSchema(firstCriteria?.[4]);
  const catalystCoverageEvidence = coverageEvidenceSchema(firstCriteria?.[5]);
  if (!macroCoverageEvidence || !catalystCoverageEvidence) return recurseSchema(value);
  const conflictDirections =
    contract === COMPACT_CONFLICT_REVIEW ? orderedPairDirections(pairSchemas) : [];
  return {
    type: "object",
    properties: {
      provider_contract: { type: "string", const: contract },
      evidence_id: {
        type: "string",
        pattern: "^evidence:[0-9a-f]{64}$",
        maxLength: 73,
      },
      claim_kind: {
        type: "string",
        enum: ["FACT", "EVENT", "INTERPRETATION", "RISK_FLAG"],
      },
      research_rule_ref: {
        anyOf: [{ type: "null" }, { type: "string", minLength: 1, maxLength: 256 }],
      },
      macro_event_coverage_evidence_ids: macroCoverageEvidence,
      catalyst_coverage_evidence_ids: catalystCoverageEvidence,
      ...(contract === COMPACT_CONFLICT_REVIEW
        ? {
            direction_order: {
              type: "array",
              description:
                "Authoritative best-to-worst total order for every conflict direction exactly once.",
              items: { type: "string", enum: conflictDirections },
              uniqueItems: true,
              minItems: conflictDirections.length,
              maxItems: conflictDirections.length,
            },
          }
        : {}),
      pairs: {
        type: "array",
        prefixItems: compactPairs,
        items: false,
        minItems: compactPairs.length,
        maxItems: compactPairs.length,
      },
    },
    required: [
      "provider_contract",
      "evidence_id",
      "claim_kind",
      "research_rule_ref",
      "macro_event_coverage_evidence_ids",
      "catalyst_coverage_evidence_ids",
      ...(contract === COMPACT_CONFLICT_REVIEW ? ["direction_order"] : []),
      "pairs",
    ],
    additionalProperties: false,
  };
}

export function normalizeSectorDirectionProviderPayload(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalizeSectorDirectionProviderPayload);
  const record = objectRecord(value);
  if (!record) return value;
  if (
    (record.provider_contract === COMPACT_DIRECTION_RESEARCH ||
      record.provider_contract === COMPACT_CONFLICT_REVIEW) &&
    Array.isArray(record.pairs)
  ) {
    return materializeDirectionResearch(
      record.provider_contract,
      record.pairs as CompactDirectionPair[],
      {
        evidence_id: String(record.evidence_id),
        research_rule_ref:
          typeof record.research_rule_ref === "string" ? record.research_rule_ref : null,
        claim_kind: normalizeClaimKind(record.claim_kind),
        macro_event_coverage_evidence_ids: Array.isArray(record.macro_event_coverage_evidence_ids)
          ? record.macro_event_coverage_evidence_ids.map(String)
          : [],
        catalyst_coverage_evidence_ids: Array.isArray(record.catalyst_coverage_evidence_ids)
          ? record.catalyst_coverage_evidence_ids.map(String)
          : [],
      },
      Array.isArray(record.direction_order) ? record.direction_order.map(String) : null,
    );
  }
  return Object.fromEntries(
    Object.entries(record).map(([key, nested]) => [
      key,
      normalizeSectorDirectionProviderPayload(nested),
    ]),
  );
}

function compactPairSchema(value: unknown): Record<string, unknown> | null {
  const properties = objectRecord(objectRecord(value)?.properties);
  const directionA = properties?.direction_a_id;
  const directionB = properties?.direction_b_id;
  if (typeof schemaConst(directionA) !== "string" || typeof schemaConst(directionB) !== "string") {
    return null;
  }
  const directionAValue = schemaConst(directionA) as string;
  const directionBValue = schemaConst(directionB) as string;
  const criteria = criterionSchemas(value);
  if (!criteria) return null;
  const compactProperties = {
    pair_key: { type: "string", const: `${directionAValue}|${directionBValue}` },
    ...compactDecisionProperties(criteria),
  };
  return {
    type: "object",
    properties: compactProperties,
    required: Object.keys(compactProperties),
    additionalProperties: false,
  };
}

function compactDecisionProperties(criteria: unknown[]) {
  const verdict = { type: "string", enum: [...COMPARABLE_VERDICTS] };
  const macroProperties = objectRecord(objectRecord(criteria[4])?.properties);
  const catalystProperties = objectRecord(objectRecord(criteria[5])?.properties);
  if (
    !macroProperties?.coverage_state ||
    !macroProperties.verdict ||
    !catalystProperties?.coverage_state ||
    !catalystProperties.verdict
  ) {
    throw new Error("sector direction coverage schema is incomplete");
  }
  return {
    decisions: {
      type: "array",
      description:
        "Exact order: fundamentals, valuation, basket technicals, risk asymmetry, macro coverage state, macro verdict, catalyst coverage state, catalyst verdict, ETF price, ETF share flow.",
      prefixItems: [
        verdict,
        verdict,
        verdict,
        verdict,
        macroProperties.coverage_state,
        macroProperties.verdict,
        catalystProperties.coverage_state,
        catalystProperties.verdict,
        { type: "string", enum: [...OPTIONAL_ETF_VERDICTS] },
        { type: "string", enum: [...OPTIONAL_ETF_VERDICTS] },
      ],
      items: false,
      minItems: 10,
      maxItems: 10,
    },
  };
}

function materializeDirectionResearch(
  contract: typeof COMPACT_DIRECTION_RESEARCH | typeof COMPACT_CONFLICT_REVIEW,
  pairs: CompactDirectionPair[],
  evidence: CompactDirectionEvidence,
  directionOrder: string[] | null,
): unknown {
  const prefix =
    contract === COMPACT_DIRECTION_RESEARCH ? "provider-direction" : "provider-conflict";
  const effectivePairs =
    contract === COMPACT_CONFLICT_REVIEW
      ? alignConflictPairsToDirectionOrder(pairs, directionOrder)
      : pairs;
  const claims = effectivePairs.map((pair, index) => {
    const [directionA, directionB] = pairDirections(pair.pair_key);
    const claimId = pairClaimId(prefix, directionA, directionB, index);
    return {
      claim_id: claimId,
      claim_kind: evidence.claim_kind,
      statement: `${directionA} and ${directionB} were compared across the frozen eight-criterion contract.`,
      structured_conclusion: {
        conclusion_type: "SECTOR_DIRECTION_COMPARISON",
        subject: `${directionA} vs ${directionB}`,
        state: "COMPARED",
      },
      evidence_ids: [
        ...new Set([
          evidence.evidence_id,
          ...(pair.decisions[4] !== "SOURCE_UNAVAILABLE"
            ? evidence.macro_event_coverage_evidence_ids
            : []),
          ...(pair.decisions[6] !== "SOURCE_UNAVAILABLE"
            ? evidence.catalyst_coverage_evidence_ids
            : []),
        ]),
      ],
      research_rule_refs: evidence.research_rule_ref ? [evidence.research_rule_ref] : [],
    };
  });
  const comparisons = effectivePairs.map((pair, index) => {
    const [directionA, directionB] = pairDirections(pair.pair_key);
    const claimId = pairClaimId(prefix, directionA, directionB, index);
    const claimRefs = [claimId];
    const decisions = pair.decisions;
    return {
      comparison_local_id: `${prefix}-pair-${index + 1}`,
      direction_a_id: directionA,
      direction_b_id: directionB,
      criterion_results: materializeCriterionResults(
        decisions,
        evidence.macro_event_coverage_evidence_ids,
        evidence.catalyst_coverage_evidence_ids,
        claimRefs,
      ),
      claim_refs: claimRefs,
    };
  });
  return contract === COMPACT_DIRECTION_RESEARCH
    ? {
        research_mode: "PAIRWISE",
        comparison_claims: claims,
        direction_comparisons: comparisons,
      }
    : { review_round: 1, comparison_claims: claims, revised_comparisons: comparisons };
}

function orderedPairDirections(pairSchemas: unknown[]): string[] {
  const ordered: string[] = [];
  for (const pairSchema of pairSchemas) {
    const properties = objectRecord(objectRecord(pairSchema)?.properties);
    for (const value of [
      schemaConst(properties?.direction_a_id),
      schemaConst(properties?.direction_b_id),
    ]) {
      if (typeof value === "string" && !ordered.includes(value)) ordered.push(value);
    }
  }
  return ordered;
}

function alignConflictPairsToDirectionOrder(
  pairs: CompactDirectionPair[],
  directionOrder: string[] | null,
): CompactDirectionPair[] {
  const expectedDirections = [...new Set(pairs.flatMap((pair) => pairDirections(pair.pair_key)))];
  if (
    !directionOrder ||
    directionOrder.length !== expectedDirections.length ||
    new Set(directionOrder).size !== directionOrder.length ||
    expectedDirections.some((direction) => !directionOrder.includes(direction))
  ) {
    throw new Error("conflict direction_order must contain every reviewed direction exactly once");
  }
  const rank = new Map(directionOrder.map((direction, index) => [direction, index]));
  return pairs.map((pair) => {
    const [directionA, directionB] = pairDirections(pair.pair_key);
    const verdict: ComparableVerdict =
      (rank.get(directionA) as number) < (rank.get(directionB) as number) ? "FAVORS_A" : "FAVORS_B";
    const decisions = [...pair.decisions] as CompactDirectionDecision["decisions"];
    decisions[0] = verdict;
    decisions[1] = verdict;
    decisions[2] = verdict;
    decisions[3] = verdict;
    decisions[5] = verdict;
    decisions[7] = verdict;
    if (decisions[8] !== "INCOMPARABLE") decisions[8] = verdict;
    if (decisions[9] !== "INCOMPARABLE") decisions[9] = verdict;
    return { ...pair, decisions };
  });
}

function materializeCriterionResults(
  decisions: CompactDirectionDecision["decisions"],
  macroEventCoverageEvidenceIds: string[],
  catalystCoverageEvidenceIds: string[],
  claimRefs: string[],
) {
  return [
    comparableCriterion("FUNDAMENTALS", decisions[0], claimRefs),
    comparableCriterion("VALUATION", decisions[1], claimRefs),
    comparableCriterion("BASKET_TECHNICALS", decisions[2], claimRefs),
    comparableCriterion("RISK_ASYMMETRY", decisions[3], claimRefs),
    coverageCriterion(
      "MACRO_EVENT_FIT",
      decisions[4],
      decisions[5],
      macroEventCoverageEvidenceIds,
      claimRefs,
    ),
    coverageCriterion(
      "CATALYSTS",
      decisions[6],
      decisions[7],
      catalystCoverageEvidenceIds,
      claimRefs,
    ),
    optionalEtfCriterion("ETF_PRICE_CONFIRMATION", decisions[8], claimRefs),
    optionalEtfCriterion("ETF_SHARE_FLOW_CONFIRMATION", decisions[9], claimRefs),
  ];
}

function comparableCriterion(criterion: string, verdict: ComparableVerdict, claimRefs: string[]) {
  return { criterion, comparison_status: "COMPARABLE", verdict, claim_refs: claimRefs };
}

function coverageCriterion(
  criterion: "MACRO_EVENT_FIT" | "CATALYSTS",
  coverageState: string,
  verdict: ComparableVerdict,
  coverageEvidenceIds: string[],
  claimRefs: string[],
) {
  if (coverageState === "SOURCE_UNAVAILABLE") {
    return {
      criterion,
      coverage_state: "SOURCE_UNAVAILABLE",
      comparison_status: "UNAVAILABLE",
      verdict: "NO_VOTE",
      claim_refs: [],
      coverage_evidence_ids: coverageEvidenceIds,
    };
  }
  const noMaterial = coverageState.startsWith("COVERAGE_CONFIRMED_NO_MATERIAL_");
  return {
    criterion,
    coverage_state: coverageState,
    comparison_status: "COMPARABLE",
    verdict: noMaterial ? "NEUTRAL" : verdict,
    claim_refs: claimRefs,
    coverage_evidence_ids: coverageEvidenceIds,
  };
}

function optionalEtfCriterion(
  criterion: "ETF_PRICE_CONFIRMATION" | "ETF_SHARE_FLOW_CONFIRMATION",
  verdict: OptionalEtfVerdict,
  claimRefs: string[],
) {
  return verdict === "INCOMPARABLE"
    ? { criterion, comparison_status: "INCOMPARABLE", verdict, claim_refs: [] }
    : { criterion, comparison_status: "COMPARABLE", verdict, claim_refs: claimRefs };
}

function pairClaimId(
  prefix: string,
  directionA: string,
  directionB: string,
  index: number,
): string {
  return `${prefix}-${index + 1}-${slug(directionA)}-vs-${slug(directionB)}`.slice(0, 128);
}

function pairDirections(pairKey: string): [string, string] {
  const [directionA, directionB, ...rest] = pairKey.split("|");
  if (!directionA || !directionB || rest.length > 0) throw new Error(`invalid pair_key ${pairKey}`);
  return [directionA, directionB];
}

function slug(value: string): string {
  return (
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "direction"
  );
}

function recurseSchema(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(adaptSectorDirectionProviderJsonSchema);
  const record = objectRecord(value);
  if (!record) return value;
  return Object.fromEntries(
    Object.entries(record).map(([key, nested]) => [
      key,
      adaptSectorDirectionProviderJsonSchema(nested),
    ]),
  );
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function schemaConst(value: unknown): unknown {
  return objectRecord(value)?.const;
}

function criterionSchemas(value: unknown): unknown[] | null {
  const properties = objectRecord(objectRecord(value)?.properties);
  const criteria = objectRecord(properties?.criterion_results);
  return Array.isArray(criteria?.prefixItems) && criteria.prefixItems.length === 8
    ? criteria.prefixItems
    : null;
}

function coverageEvidenceSchema(value: unknown): Record<string, unknown> | null {
  const properties = objectRecord(objectRecord(value)?.properties);
  return objectRecord(properties?.coverage_evidence_ids);
}

function normalizeClaimKind(value: unknown): "FACT" | "EVENT" | "INTERPRETATION" | "RISK_FLAG" {
  return value === "EVENT" || value === "INTERPRETATION" || value === "RISK_FLAG" ? value : "FACT";
}
