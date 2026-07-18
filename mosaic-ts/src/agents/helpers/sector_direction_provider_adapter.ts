const COMPACT_DIRECTION_RESEARCH = "SECTOR_DIRECTION_RESEARCH_COMPACT_V1";
const COMPACT_SINGLE_DIRECTION = "SECTOR_SINGLE_DIRECTION_COMPACT_V1";
const COMPACT_CONFLICT_REVIEW = "SECTOR_CONFLICT_REVIEW_COMPACT_V1";

export const SECTOR_DIRECTION_PROVIDER_INSTRUCTION =
  "The bounded provider extraction contract may request a compact exact pair tuple. For every " +
  "pair, judge all eight named criteria, copy one exact runtime evidence_id and one allowed " +
  "research_rule_ref, and provide the exact event-coverage evidence id. decisions order is " +
  "fundamentals, valuation, basket technicals, risk asymmetry, macro coverage state, macro " +
  "verdict, catalyst coverage state, catalyst verdict, ETF price, ETF share flow. Runtime expands only " +
  "the repetitive claim and criterion envelopes; it never changes your verdicts.";

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
  summary: string;
  evidence_id: string;
  research_rule_ref: string;
  coverage_evidence_id: string;
}

interface CompactDirectionPair extends CompactDirectionDecision {
  pair_key: string;
}

interface CompactSingleDirection extends CompactDirectionDecision, CompactDirectionEvidence {
  direction_id: string;
  null_benchmark_contract_id: string;
}

/** Keep model judgment fields while moving repetitive eight-criterion expansion into runtime. */
export function adaptSectorDirectionProviderJsonSchema(value: unknown): unknown {
  const root = objectRecord(value);
  const properties = objectRecord(root?.properties);
  if (!root || !properties) return recurseSchema(value);

  const researchMode = schemaConst(properties.research_mode);
  const reviewRound = schemaConst(properties.review_round);
  if (researchMode === "SINGLE_DIRECTION_QUALIFICATION") {
    const qualification = objectRecord(properties.single_direction_qualification);
    const qualificationProperties = objectRecord(qualification?.properties);
    const directionId = qualificationProperties?.direction_id;
    const nullBenchmarkId = qualificationProperties?.null_benchmark_contract_id;
    if (
      typeof schemaConst(directionId) === "string" &&
      typeof schemaConst(nullBenchmarkId) === "string"
    ) {
      const compactProperties = {
        direction_id: directionId,
        null_benchmark_contract_id: nullBenchmarkId,
        ...compactDirectionEvidenceProperties(),
        ...compactDecisionProperties(),
      };
      return {
        type: "object",
        properties: {
          provider_contract: { type: "string", const: COMPACT_SINGLE_DIRECTION },
          qualification: {
            type: "object",
            properties: compactProperties,
            required: Object.keys(compactProperties),
            additionalProperties: false,
          },
        },
        required: ["provider_contract", "qualification"],
        additionalProperties: false,
      };
    }
  }
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
  return {
    type: "object",
    properties: {
      provider_contract: { type: "string", const: contract },
      evidence_id: {
        type: "string",
        pattern: "^evidence:[0-9a-f]{64}$",
        maxLength: 73,
      },
      research_rule_ref: { type: "string", minLength: 1, maxLength: 256 },
      coverage_evidence_id: { type: "string", minLength: 1, maxLength: 256 },
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
      "research_rule_ref",
      "coverage_evidence_id",
      "pairs",
    ],
    additionalProperties: false,
  };
}

export function normalizeSectorDirectionProviderPayload(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalizeSectorDirectionProviderPayload);
  const record = objectRecord(value);
  if (!record) return value;
  if (record.provider_contract === COMPACT_SINGLE_DIRECTION && objectRecord(record.qualification)) {
    return materializeSingleDirection(record.qualification as unknown as CompactSingleDirection);
  }
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
        research_rule_ref: String(record.research_rule_ref),
        coverage_evidence_id: String(record.coverage_evidence_id),
      },
    );
  }
  if (record.research_mode === "SINGLE_DIRECTION_QUALIFICATION") {
    const qualification = objectRecord(record.single_direction_qualification);
    const criteria = Array.isArray(qualification?.criterion_results)
      ? qualification.criterion_results
      : null;
    if (qualification && criteria) {
      const claimRefs = [
        ...new Set(
          criteria.flatMap((criterion) => {
            const refs = objectRecord(criterion)?.claim_refs;
            return Array.isArray(refs)
              ? refs.filter((ref): ref is string => typeof ref === "string")
              : [];
          }),
        ),
      ].sort();
      return {
        ...record,
        single_direction_qualification: { ...qualification, claim_refs: claimRefs },
      };
    }
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
  const compactProperties = {
    pair_key: { type: "string", const: `${directionAValue}|${directionBValue}` },
    ...compactDecisionProperties(),
  };
  return {
    type: "object",
    properties: compactProperties,
    required: Object.keys(compactProperties),
    additionalProperties: false,
  };
}

function compactDecisionProperties() {
  const verdict = { type: "string", enum: [...COMPARABLE_VERDICTS] };
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
        {
          type: "string",
          enum: [
            "AVAILABLE_MATERIAL_EVENTS",
            "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT",
            "SOURCE_UNAVAILABLE",
          ],
        },
        verdict,
        {
          type: "string",
          enum: [
            "AVAILABLE_MATERIAL_CATALYSTS",
            "COVERAGE_CONFIRMED_NO_MATERIAL_CATALYST",
            "SOURCE_UNAVAILABLE",
          ],
        },
        verdict,
        { type: "string", enum: [...OPTIONAL_ETF_VERDICTS] },
        { type: "string", enum: [...OPTIONAL_ETF_VERDICTS] },
      ],
      items: false,
      minItems: 10,
      maxItems: 10,
    },
  };
}

function compactDirectionEvidenceProperties() {
  return {
    summary: { type: "string", minLength: 1, maxLength: 160 },
    evidence_id: {
      type: "string",
      pattern: "^evidence:[0-9a-f]{64}$",
      maxLength: 73,
    },
    research_rule_ref: { type: "string", minLength: 1, maxLength: 256 },
    coverage_evidence_id: { type: "string", minLength: 1, maxLength: 256 },
  };
}

function materializeDirectionResearch(
  contract: typeof COMPACT_DIRECTION_RESEARCH | typeof COMPACT_CONFLICT_REVIEW,
  pairs: CompactDirectionPair[],
  evidence: Omit<CompactDirectionEvidence, "summary">,
): unknown {
  const prefix =
    contract === COMPACT_DIRECTION_RESEARCH ? "provider-direction" : "provider-conflict";
  const claims = pairs.map((pair, index) => {
    const [directionA, directionB] = pairDirections(pair.pair_key);
    const claimId = pairClaimId(prefix, directionA, directionB, index);
    return {
      claim_id: claimId,
      claim_kind: "INTERPRETATION",
      statement: `${directionA} and ${directionB} were compared across the frozen eight-criterion contract.`,
      structured_conclusion: {
        conclusion_type: "SECTOR_DIRECTION_COMPARISON",
        subject: `${directionA} vs ${directionB}`,
        state: "COMPARED",
      },
      evidence_ids: [evidence.evidence_id],
      research_rule_refs: [evidence.research_rule_ref],
    };
  });
  const comparisons = pairs.map((pair, index) => {
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
        evidence.coverage_evidence_id,
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
        single_direction_qualification: null,
      }
    : { review_round: 1, comparison_claims: claims, revised_comparisons: comparisons };
}

function materializeSingleDirection(input: CompactSingleDirection): unknown {
  const claimId = `provider-single-${slug(input.direction_id)}`.slice(0, 128);
  const claimRefs = [claimId];
  return {
    research_mode: "SINGLE_DIRECTION_QUALIFICATION",
    comparison_claims: [
      {
        claim_id: claimId,
        claim_kind: "INTERPRETATION",
        statement: input.summary,
        structured_conclusion: {
          conclusion_type: "SECTOR_SINGLE_DIRECTION_QUALIFICATION",
          subject: input.direction_id,
          state: "QUALIFICATION_REVIEWED",
        },
        evidence_ids: [input.evidence_id],
        research_rule_refs: [input.research_rule_ref],
      },
    ],
    direction_comparisons: [],
    single_direction_qualification: {
      qualification_local_id: `provider-single-${slug(input.direction_id)}`,
      direction_id: input.direction_id,
      null_benchmark_contract_id: input.null_benchmark_contract_id,
      criterion_results: materializeCriterionResults(
        input.decisions,
        input.coverage_evidence_id,
        claimRefs,
      ),
      claim_refs: claimRefs,
    },
  };
}

function materializeCriterionResults(
  decisions: CompactDirectionDecision["decisions"],
  coverageEvidenceId: string,
  claimRefs: string[],
) {
  return [
    comparableCriterion("FUNDAMENTALS", decisions[0], claimRefs),
    comparableCriterion("VALUATION", decisions[1], claimRefs),
    comparableCriterion("BASKET_TECHNICALS", decisions[2], claimRefs),
    comparableCriterion("RISK_ASYMMETRY", decisions[3], claimRefs),
    coverageCriterion("MACRO_EVENT_FIT", decisions[4], decisions[5], coverageEvidenceId, claimRefs),
    coverageCriterion("CATALYSTS", decisions[6], decisions[7], coverageEvidenceId, claimRefs),
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
  coverageEvidenceId: string,
  claimRefs: string[],
) {
  if (coverageState === "SOURCE_UNAVAILABLE") {
    return {
      criterion,
      coverage_state: "SOURCE_UNAVAILABLE",
      comparison_status: "UNAVAILABLE",
      verdict: "NO_VOTE",
      claim_refs: [],
      coverage_evidence_ids: [coverageEvidenceId],
    };
  }
  const noMaterial = coverageState.startsWith("COVERAGE_CONFIRMED_NO_MATERIAL_");
  return {
    criterion,
    coverage_state: coverageState,
    comparison_status: "COMPARABLE",
    verdict: noMaterial ? "NEUTRAL" : verdict,
    claim_refs: claimRefs,
    coverage_evidence_ids: [coverageEvidenceId],
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
