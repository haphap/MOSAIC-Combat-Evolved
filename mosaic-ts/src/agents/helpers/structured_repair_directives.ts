export const STRUCTURED_REPAIR_DIRECTIVE_CONTRACT_VERSION = "structured_repair_directive_v1";

const STRUCTURED_REPAIR_SYSTEM_MESSAGES = [
  "Structured repair 1/3. Correct the complete prior object directly. Return a complete object; do not omit disposition fields or add prose. Copy exact evidence_id and opaque permitted citation identifiers from the immutable catalog: every claim needs evidence_ids, and every INTERPRETATION also needs research_rule_refs.",
  "Structured repair 2/3. Regenerate one complete object from the original immutable evidence. Satisfy every machine constraint and all cumulative errors. Use only exact catalog ids; all claims require evidence_ids and INTERPRETATION claims require research_rule_refs.",
  "FINAL structured repair 3/3. Rebuild the complete object under the strict contract. Use only exact catalog ids; all claims require evidence_ids and INTERPRETATION claims require research_rule_refs. You may choose an explicitly supported empty disposition, but disposition and conclusion references are mandatory. Return no prose.",
] as const;

interface StructuredRepairIssue {
  validator: string;
  reason_code: string;
  json_path: string;
  message?: string;
}

export interface StructuredRepairDirectiveInput {
  attempt: number;
  immutableEvidenceHash: string;
  allowedEvidenceIds: ReadonlyArray<string>;
  allowedCitationIds: ReadonlyArray<string>;
  originalEvidenceAndTask: unknown;
  priorOutput: unknown;
  validationErrors: ReadonlyArray<StructuredRepairIssue>;
  completeJsonSchema: unknown;
}

export interface StructuredRepairDirectiveMessages {
  systemMessage: string;
  userMessage: string;
}

/** Build the exact repair messages sent to the structured-output model. */
export function buildStructuredRepairDirectiveMessages(
  input: StructuredRepairDirectiveInput,
): StructuredRepairDirectiveMessages {
  const common = {
    immutable_evidence_hash: input.immutableEvidenceHash,
    allowed_evidence_ids: [...input.allowedEvidenceIds],
    allowed_citation_ids: [...input.allowedCitationIds],
    original_evidence_and_task: input.originalEvidenceAndTask,
  };
  if (input.attempt === 1) {
    return {
      systemMessage: STRUCTURED_REPAIR_SYSTEM_MESSAGES[0],
      userMessage: JSON.stringify({
        ...common,
        prior_output: input.priorOutput,
        validation_errors: input.validationErrors,
      }),
    };
  }
  if (input.attempt === 2) {
    return {
      systemMessage: STRUCTURED_REPAIR_SYSTEM_MESSAGES[1],
      userMessage: JSON.stringify({
        ...common,
        cumulative_validation_errors: input.validationErrors,
        complete_json_schema: input.completeJsonSchema,
      }),
    };
  }
  return {
    systemMessage: STRUCTURED_REPAIR_SYSTEM_MESSAGES[2],
    userMessage: JSON.stringify({
      ...common,
      normalized_errors: input.validationErrors.map(({ validator, reason_code, json_path }) => ({
        validator,
        reason_code,
        json_path,
      })),
      complete_json_schema: input.completeJsonSchema,
    }),
  };
}

/** Stable sentinel rendering of every message shape whose bytes affect model behavior. */
export function canonicalStructuredRepairDirectiveManifest(): ReadonlyArray<{
  attempt: 1 | 2 | 3;
  system_message: string;
  user_message_template: string;
}> {
  const sentinel = {
    immutableEvidenceHash: "{{IMMUTABLE_EVIDENCE_HASH}}",
    allowedEvidenceIds: ["{{ALLOWED_EVIDENCE_ID}}"],
    allowedCitationIds: ["{{ALLOWED_CITATION_ID}}"],
    originalEvidenceAndTask: "{{ORIGINAL_EVIDENCE_AND_TASK}}",
    priorOutput: "{{PRIOR_OUTPUT}}",
    validationErrors: [
      {
        validator: "{{VALIDATOR}}",
        reason_code: "{{REASON_CODE}}",
        json_path: "{{JSON_PATH}}",
        message: "{{MESSAGE}}",
      },
    ],
    completeJsonSchema: "{{COMPLETE_JSON_SCHEMA}}",
  } as const;
  return ([1, 2, 3] as const).map((attempt) => {
    const messages = buildStructuredRepairDirectiveMessages({ ...sentinel, attempt });
    return {
      attempt,
      system_message: messages.systemMessage,
      user_message_template: messages.userMessage,
    };
  });
}
