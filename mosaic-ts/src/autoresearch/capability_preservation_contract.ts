import { readFileSync } from "node:fs";
import { z } from "zod";
import { canonicalJsonHash } from "../agents/helpers/canonical_json.js";

const Id = z.string().min(1);
const Sha256 = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const BindingId = z.string().regex(/^binding:[0-9a-f]{64}$/);

const AdaptiveQueryContractSchema = z
  .object({
    max_rounds: z.number().int().nonnegative(),
    model_selects_arguments: z.boolean(),
    transport_allowed_during_prepare: z.literal(true).optional(),
    transport_allowed_during_call: z.literal(false),
  })
  .strict();

export const CapabilityBindingSchema = z
  .object({
    binding_id: BindingId,
    agent_id: Id,
    stage: Id,
    phase: Id,
    semantic_capability_id: Id,
    tool_id: Id,
    argument_schema_hash: Sha256,
    argument_domain_selector_hash: Sha256,
    output_semantics_hash: Sha256,
    source_route_ids: z.array(Id).min(1),
    route_contract_hash: Sha256,
    materializer_contract_hash: Sha256,
    query_bundle_contract_version: Id,
    privacy_contract_hash: Sha256,
    adaptive_query_contract: AdaptiveQueryContractSchema,
    activation_state: z.enum(["active", "staged"]),
  })
  .strict()
  .superRefine((binding, ctx) => {
    const { binding_id: _, ...body } = binding;
    if (binding.binding_id !== canonicalCapabilityBindingId(body)) {
      ctx.addIssue({ code: "custom", path: ["binding_id"], message: "binding id hash mismatch" });
    }
  });

export type CapabilityBinding = z.infer<typeof CapabilityBindingSchema>;

export function canonicalCapabilityBindingId(
  bindingBody: Omit<CapabilityBinding, "binding_id"> | Record<string, unknown>,
): string {
  return `binding:${canonicalJsonHash(bindingBody).slice("sha256:".length)}`;
}

export const CapabilityBindingManifestSchema = z
  .object({
    schema_version: z.literal("agent_capability_binding_manifest_v1"),
    source_agent_tool_manifest_hash: Sha256,
    source_agent_data_route_manifest_hash: Sha256,
    bindings: z.array(CapabilityBindingSchema).min(1),
    manifest_hash: Sha256,
  })
  .strict()
  .superRefine((manifest, ctx) => {
    const { manifest_hash: _, ...body } = manifest;
    if (manifest.manifest_hash !== canonicalJsonHash(body)) {
      ctx.addIssue({ code: "custom", path: ["manifest_hash"], message: "manifest hash mismatch" });
    }
    const ids = manifest.bindings.map((row) => row.binding_id);
    if (new Set(ids).size !== ids.length) {
      ctx.addIssue({ code: "custom", path: ["bindings"], message: "duplicate binding id" });
    }
  });

export const StagedAgentToolEntrySchema = z
  .object({
    agent_id: Id,
    stage: Id,
    phase: Id,
    tool_id: Id,
    activation_state: z.literal("staged"),
    capability_binding_ids: z.array(BindingId).min(1),
    semantic_capability_ids: z.array(Id).min(1),
    argument_schema_hash: Sha256,
    authorized_query_domain_hash: Sha256,
    output_semantics_hash: Sha256,
    source_route_ids: z.array(Id).min(1),
    route_contract_hash: Sha256,
    query_bundle_contract_version: Id,
    materializer_contract_hash: Sha256,
    privacy_contract_hash: Sha256,
    adaptive_query_contract: AdaptiveQueryContractSchema,
  })
  .strict();

export const StagedAgentToolContractManifestSchema = z
  .object({
    schema_version: z.literal("staged_agent_tool_contract_manifest_v2"),
    base_active_agent_tool_manifest_hash: Sha256,
    base_agent_data_route_manifest_hash: Sha256,
    capability_binding_manifest_hash: Sha256,
    tools: z.array(StagedAgentToolEntrySchema).min(1),
    manifest_hash: Sha256,
  })
  .strict()
  .superRefine((manifest, ctx) => {
    const { manifest_hash: _, ...body } = manifest;
    if (manifest.manifest_hash !== canonicalJsonHash(body)) {
      ctx.addIssue({ code: "custom", path: ["manifest_hash"], message: "manifest hash mismatch" });
    }
    const keys = manifest.tools.map((row) => `${row.agent_id}\0${row.stage}\0${row.tool_id}`);
    if (new Set(keys).size !== keys.length) {
      ctx.addIssue({ code: "custom", path: ["tools"], message: "duplicate staged tool" });
    }
  });

export const ToolEnvironmentEntrySchema = z
  .object({
    agent_id: Id,
    stage: Id,
    phase: Id,
    allowed_tools: z.array(Id).min(1),
    binding_ids: z.array(BindingId).min(1),
    argument_schema_hashes: z.record(Id, Sha256),
    authorized_query_domain_hashes: z.record(Id, Sha256),
    snapshot_bundle_contract_version: Id,
    query_bundle_contract_version: Id,
    materializer_contract_hash: Sha256,
    capability_contract_version: Id,
    privacy_contract_hash: Sha256,
    execution_behavior_release_id: Id,
    execution_behavior_release_hash: Sha256,
    code_commit: z.string().regex(/^[0-9a-f]{40}$/),
    activation_state: z.literal("staged_contract_for_active_surface"),
  })
  .strict();

export const ToolEnvironmentManifestSchema = z
  .object({
    schema_version: z.literal("tool_environment_manifest_v1"),
    source_agent_tool_manifest_hash: Sha256,
    capability_binding_manifest_hash: Sha256,
    staged_agent_tool_contract_manifest_hash: Sha256,
    environments: z.array(ToolEnvironmentEntrySchema).min(1),
    manifest_hash: Sha256,
  })
  .strict()
  .superRefine((manifest, ctx) => {
    if (manifest.manifest_hash !== canonicalToolEnvironmentHash(manifest)) {
      ctx.addIssue({ code: "custom", path: ["manifest_hash"], message: "manifest hash mismatch" });
    }
    const keys = manifest.environments.map((row) => `${row.agent_id}\0${row.stage}\0${row.phase}`);
    if (new Set(keys).size !== keys.length) {
      ctx.addIssue({ code: "custom", path: ["environments"], message: "duplicate environment" });
    }
  });

export type ToolEnvironmentManifest = z.infer<typeof ToolEnvironmentManifestSchema>;

export function canonicalToolEnvironmentHash(
  value: ToolEnvironmentManifest | Record<string, unknown>,
): string {
  const { manifest_hash: _, ...body } = value;
  return canonicalJsonHash(body);
}

export function validateToolConfigHash(toolConfigHash: string, environment: unknown): void {
  const parsed = ToolEnvironmentManifestSchema.parse(environment);
  if (toolConfigHash !== canonicalToolEnvironmentHash(parsed)) {
    throw new Error("toolConfigHash must equal canonical tool environment hash");
  }
}

export const KnotCoverageRowSchema = z
  .object({
    binding_id: BindingId,
    agent_id: Id,
    stage: Id,
    phase: Id,
    semantic_capability_id: Id,
    tool_id: Id,
    argument_schema_hash: Sha256,
    argument_domain_selector_hash: Sha256,
    route_contract_hash: Sha256,
    materializer_contract_hash: Sha256,
    privacy_contract_hash: Sha256,
    tool_environment_hash: Sha256,
    availability_evaluator_version: Id,
    call_evaluator_version: Id,
    success_evaluator_version: Id,
    accepted_lineage_evaluator_version: Id,
    counterevidence_evaluator_version: Id,
    coverage_row_hash: Sha256,
  })
  .strict()
  .superRefine((row, ctx) => {
    const { coverage_row_hash: _, ...body } = row;
    if (row.coverage_row_hash !== canonicalJsonHash(body)) {
      ctx.addIssue({ code: "custom", path: ["coverage_row_hash"], message: "row hash mismatch" });
    }
  });

export const KnotToolCoverageManifestSchema = z
  .object({
    schema_version: z.literal("knot_tool_coverage_manifest_v1"),
    capability_binding_manifest_hash: Sha256,
    tool_environment_hash: Sha256,
    coverage: z.array(KnotCoverageRowSchema).min(1),
    manifest_hash: Sha256,
  })
  .strict()
  .superRefine((manifest, ctx) => {
    const { manifest_hash: _, ...body } = manifest;
    if (manifest.manifest_hash !== canonicalJsonHash(body)) {
      ctx.addIssue({ code: "custom", path: ["manifest_hash"], message: "manifest hash mismatch" });
    }
    const ids = manifest.coverage.map((row) => row.binding_id);
    if (new Set(ids).size !== ids.length) {
      ctx.addIssue({ code: "custom", path: ["coverage"], message: "duplicate coverage binding" });
    }
  });

export function validateKnotExactClosure(input: {
  bindingManifest: unknown;
  toolEnvironmentManifest: unknown;
  knotCoverageManifest: unknown;
}): void {
  const bindings = CapabilityBindingManifestSchema.parse(input.bindingManifest);
  const environment = ToolEnvironmentManifestSchema.parse(input.toolEnvironmentManifest);
  const coverage = KnotToolCoverageManifestSchema.parse(input.knotCoverageManifest);
  const bindingIds = new Set(bindings.bindings.map((row) => row.binding_id));
  const coverageIds = new Set(coverage.coverage.map((row) => row.binding_id));
  if (
    bindingIds.size !== coverageIds.size ||
    [...bindingIds].some((bindingId) => !coverageIds.has(bindingId))
  ) {
    throw new Error("KNOT coverage exact closure mismatch");
  }
  const environmentHash = canonicalToolEnvironmentHash(environment);
  if (
    environmentHash !== coverage.tool_environment_hash ||
    coverage.coverage.some((row) => row.tool_environment_hash !== environmentHash) ||
    environment.capability_binding_manifest_hash !== bindings.manifest_hash ||
    coverage.capability_binding_manifest_hash !== bindings.manifest_hash
  ) {
    throw new Error("KNOT fixed-point hash mismatch");
  }
}

export const KnotCapabilityUseAggregateSchema = z
  .object({
    schema_version: z.literal("knot_capability_use_aggregate_v1"),
    binding_id: BindingId,
    eligible_count: z.number().int().nonnegative(),
    ready_count: z.number().int().nonnegative(),
    called_count: z.number().int().nonnegative(),
    succeeded_count: z.number().int().nonnegative(),
    used_in_accepted_evidence_count: z.number().int().nonnegative(),
    counterevidence_available_count: z.number().int().nonnegative(),
    counterevidence_handled_count: z.number().int().nonnegative(),
    runtime_blocker_count: z.number().int().nonnegative(),
    excluded_count: z.number().int().nonnegative(),
    gap_counts: z
      .object({
        not_called: z.number().int().nonnegative(),
        call_failed: z.number().int().nonnegative(),
        succeeded_not_used: z.number().int().nonnegative(),
        counterevidence_ignored: z.number().int().nonnegative(),
      })
      .strict(),
    model_controllable_gap_count: z.number().int().nonnegative(),
    opaque_failure_refs: z.array(Id),
    aggregate_hash: Sha256,
  })
  .strict()
  .superRefine((aggregate, ctx) => {
    const { aggregate_hash: _, ...body } = aggregate;
    if (aggregate.aggregate_hash !== canonicalJsonHash(body)) {
      ctx.addIssue({
        code: "custom",
        path: ["aggregate_hash"],
        message: "aggregate hash mismatch",
      });
    }
    const expected = Object.values(aggregate.gap_counts).reduce((sum, value) => sum + value, 0);
    if (aggregate.model_controllable_gap_count !== expected) {
      ctx.addIssue({
        code: "custom",
        path: ["model_controllable_gap_count"],
        message: "gap total mismatch",
      });
    }
    if (
      aggregate.eligible_count !== aggregate.ready_count + aggregate.runtime_blocker_count ||
      aggregate.ready_count !== aggregate.called_count + aggregate.gap_counts.not_called ||
      aggregate.called_count !== aggregate.succeeded_count + aggregate.gap_counts.call_failed ||
      aggregate.succeeded_count !==
        aggregate.used_in_accepted_evidence_count + aggregate.gap_counts.succeeded_not_used ||
      aggregate.counterevidence_available_count !==
        aggregate.counterevidence_handled_count + aggregate.gap_counts.counterevidence_ignored ||
      aggregate.counterevidence_available_count > aggregate.used_in_accepted_evidence_count
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["eligible_count"],
        message: "count conservation mismatch",
      });
    }
  });

export const CapabilityTrackSchema = z
  .object({
    schema_version: z.literal("accepted_output_capability_track_v1"),
    tool_environment_hash: Sha256,
    execution_behavior_release_hash: Sha256,
    capability_binding_manifest_hash: Sha256,
    knot_coverage_manifest_hash: Sha256,
    capability_bundle_hash: Sha256,
  })
  .strict()
  .superRefine((track, ctx) => {
    const { capability_bundle_hash: _, ...body } = track;
    if (track.capability_bundle_hash !== canonicalJsonHash(body)) {
      ctx.addIssue({
        code: "custom",
        path: ["capability_bundle_hash"],
        message: "capability bundle hash mismatch",
      });
    }
  });

export type CapabilityTrack = z.infer<typeof CapabilityTrackSchema>;

type CurrentCapabilityContractBundle = {
  bindingManifest: z.infer<typeof CapabilityBindingManifestSchema>;
  stagedManifest: z.infer<typeof StagedAgentToolContractManifestSchema>;
  environmentManifest: ToolEnvironmentManifest;
  coverageManifest: z.infer<typeof KnotToolCoverageManifestSchema>;
  capabilityTrack: CapabilityTrack;
};

let currentCapabilityBundle: CurrentCapabilityContractBundle | undefined;

function loadJson(url: URL): unknown {
  return JSON.parse(readFileSync(url, "utf8"));
}

function validateStagedBundleClosure(bundle: {
  bindingManifest: z.infer<typeof CapabilityBindingManifestSchema>;
  stagedManifest: z.infer<typeof StagedAgentToolContractManifestSchema>;
  environmentManifest: ToolEnvironmentManifest;
}): void {
  const { bindingManifest, stagedManifest, environmentManifest } = bundle;
  const bindingsByTool = new Map<string, CapabilityBinding[]>();
  for (const binding of bindingManifest.bindings) {
    const key = `${binding.agent_id}\0${binding.stage}\0${binding.tool_id}`;
    const rows = bindingsByTool.get(key) ?? [];
    rows.push(binding);
    bindingsByTool.set(key, rows);
  }
  if (bindingsByTool.size !== stagedManifest.tools.length) {
    throw new Error("staged tool binding exact closure mismatch");
  }
  for (const staged of stagedManifest.tools) {
    const key = `${staged.agent_id}\0${staged.stage}\0${staged.tool_id}`;
    const bindings = bindingsByTool.get(key);
    if (!bindings) {
      throw new Error("staged tool binding exact closure mismatch");
    }
    const first = bindings[0];
    if (!first) {
      throw new Error("staged tool binding exact closure mismatch");
    }
    const outputSemanticsHash = canonicalJsonHash(
      Object.fromEntries(
        [...bindings]
          .sort((left, right) =>
            left.semantic_capability_id.localeCompare(right.semantic_capability_id),
          )
          .map((row) => [row.semantic_capability_id, row.output_semantics_hash]),
      ),
    );
    const exact =
      staged.phase === first.phase &&
      canonicalJsonHash(staged.capability_binding_ids) ===
        canonicalJsonHash(bindings.map((row) => row.binding_id).sort()) &&
      canonicalJsonHash(staged.semantic_capability_ids) ===
        canonicalJsonHash(bindings.map((row) => row.semantic_capability_id).sort()) &&
      staged.argument_schema_hash === first.argument_schema_hash &&
      staged.authorized_query_domain_hash === first.argument_domain_selector_hash &&
      staged.output_semantics_hash === outputSemanticsHash &&
      canonicalJsonHash(staged.source_route_ids) === canonicalJsonHash(first.source_route_ids) &&
      staged.route_contract_hash === first.route_contract_hash &&
      staged.query_bundle_contract_version === first.query_bundle_contract_version &&
      staged.materializer_contract_hash === first.materializer_contract_hash &&
      staged.privacy_contract_hash === first.privacy_contract_hash &&
      canonicalJsonHash(staged.adaptive_query_contract) ===
        canonicalJsonHash(first.adaptive_query_contract);
    if (!exact) {
      throw new Error("staged tool binding exact closure mismatch");
    }
  }

  const stagedByEnvironment = new Map<string, Array<z.infer<typeof StagedAgentToolEntrySchema>>>();
  for (const staged of stagedManifest.tools) {
    const key = `${staged.agent_id}\0${staged.stage}\0${staged.phase}`;
    const rows = stagedByEnvironment.get(key) ?? [];
    rows.push(staged);
    stagedByEnvironment.set(key, rows);
  }
  if (stagedByEnvironment.size !== environmentManifest.environments.length) {
    throw new Error("tool environment staged exact closure mismatch");
  }
  for (const environment of environmentManifest.environments) {
    const key = `${environment.agent_id}\0${environment.stage}\0${environment.phase}`;
    const stagedRows = stagedByEnvironment.get(key);
    if (!stagedRows) {
      throw new Error("tool environment staged exact closure mismatch");
    }
    const allowedTools = stagedRows.map((row) => row.tool_id).sort();
    const bindingIds = stagedRows.flatMap((row) => row.capability_binding_ids).sort();
    if (
      canonicalJsonHash([...environment.allowed_tools].sort()) !==
        canonicalJsonHash(allowedTools) ||
      canonicalJsonHash(environment.binding_ids) !== canonicalJsonHash(bindingIds) ||
      stagedRows.some(
        (row) =>
          environment.argument_schema_hashes[row.tool_id] !== row.argument_schema_hash ||
          environment.authorized_query_domain_hashes[row.tool_id] !==
            row.authorized_query_domain_hash,
      )
    ) {
      throw new Error("tool environment staged exact closure mismatch");
    }
  }
}

function loadCurrentCapabilityContractBundle(): CurrentCapabilityContractBundle {
  if (currentCapabilityBundle) {
    return currentCapabilityBundle;
  }
  const contractRoot = new URL(
    "../../../registry/prompt_checks/capability_preservation/",
    import.meta.url,
  );
  const currentToolManifest = loadJson(
    new URL(
      "../../../registry/prompt_checks/agent_tool_contract_manifest_v1.json",
      import.meta.url,
    ),
  );
  const routeManifest = loadJson(
    new URL("../../../registry/data_sources/agent_data_route_manifest_v1.json", import.meta.url),
  );
  const bindingManifest = CapabilityBindingManifestSchema.parse(
    loadJson(new URL("agent_capability_binding_manifest_v1.json", contractRoot)),
  );
  const stagedManifest = StagedAgentToolContractManifestSchema.parse(
    loadJson(new URL("staged_agent_tool_contract_manifest_v2.json", contractRoot)),
  );
  const environmentManifest = ToolEnvironmentManifestSchema.parse(
    loadJson(new URL("tool_environment_manifest_v1.json", contractRoot)),
  );
  const coverageManifest = KnotToolCoverageManifestSchema.parse(
    loadJson(new URL("knot_tool_coverage_manifest_v1.json", contractRoot)),
  );
  const currentToolHash = canonicalJsonHash(currentToolManifest);
  const routeHash = canonicalJsonHash(routeManifest);
  if (
    bindingManifest.source_agent_tool_manifest_hash !== currentToolHash ||
    bindingManifest.source_agent_data_route_manifest_hash !== routeHash ||
    stagedManifest.base_active_agent_tool_manifest_hash !== currentToolHash ||
    stagedManifest.base_agent_data_route_manifest_hash !== routeHash ||
    stagedManifest.capability_binding_manifest_hash !== bindingManifest.manifest_hash ||
    environmentManifest.source_agent_tool_manifest_hash !== currentToolHash ||
    environmentManifest.capability_binding_manifest_hash !== bindingManifest.manifest_hash ||
    environmentManifest.staged_agent_tool_contract_manifest_hash !== stagedManifest.manifest_hash
  ) {
    throw new Error("current capability contract source hash mismatch");
  }
  validateStagedBundleClosure({ bindingManifest, stagedManifest, environmentManifest });
  validateKnotExactClosure({
    bindingManifest,
    toolEnvironmentManifest: environmentManifest,
    knotCoverageManifest: coverageManifest,
  });
  const executionHashes = new Set(
    environmentManifest.environments.map((row) => row.execution_behavior_release_hash),
  );
  if (executionHashes.size !== 1) {
    throw new Error("current capability contract must bind one execution release");
  }
  const trackBody = {
    schema_version: "accepted_output_capability_track_v1" as const,
    tool_environment_hash: canonicalToolEnvironmentHash(environmentManifest),
    execution_behavior_release_hash: [...executionHashes][0],
    capability_binding_manifest_hash: bindingManifest.manifest_hash,
    knot_coverage_manifest_hash: coverageManifest.manifest_hash,
  };
  const expectedTrack = CapabilityTrackSchema.parse({
    ...trackBody,
    capability_bundle_hash: canonicalJsonHash(trackBody),
  });
  const artifactTrack = CapabilityTrackSchema.parse(
    loadJson(new URL("accepted_output_capability_track_v1.json", contractRoot)),
  );
  if (canonicalJsonHash(artifactTrack) !== canonicalJsonHash(expectedTrack)) {
    throw new Error("accepted output capability track artifact fixed-point mismatch");
  }
  currentCapabilityBundle = {
    bindingManifest,
    stagedManifest,
    environmentManifest,
    coverageManifest,
    capabilityTrack: expectedTrack,
  };
  return currentCapabilityBundle;
}

export function loadCurrentAcceptedOutputCapabilityTrack(): CapabilityTrack {
  return structuredClone(loadCurrentCapabilityContractBundle().capabilityTrack);
}

export function validateAcceptedOutputCapabilityTrack(track: unknown): CapabilityTrack {
  return CapabilityTrackSchema.parse(track);
}

export function validateCurrentAcceptedOutputCapabilityTrack(track: unknown): CapabilityTrack {
  const parsed = validateAcceptedOutputCapabilityTrack(track);
  const expected = loadCurrentAcceptedOutputCapabilityTrack();
  if (canonicalJsonHash(parsed) !== canonicalJsonHash(expected)) {
    throw new Error("accepted output capability track fixed-point mismatch");
  }
  return parsed;
}

const CounterevidenceRuleV1Schema = z
  .object({
    rule_version: z.literal("counterevidence_rule_v1"),
    dimension: Id,
    polarity_extractor_version: z.literal("signed_numeric_v1"),
    aggregation: z.literal("max_strength_v1"),
    comparison: z.literal("support_minus_contradiction"),
    threshold: z.number().finite().nonnegative(),
    unknown_policy: z.literal("abstain"),
  })
  .strict();

const ToolResultFingerprintBodySchema = z
  .object({
    semantic_capability_id: Id,
    binding_id: BindingId,
    tool_id: Id,
    canonical_args_hash: Sha256,
    payload_hash: Sha256,
    build_receipt_hash: Sha256,
    tool_environment_hash: Sha256,
  })
  .strict();

export function canonicalToolResultFingerprint(
  body: z.infer<typeof ToolResultFingerprintBodySchema>,
): string {
  return canonicalJsonHash(ToolResultFingerprintBodySchema.parse(body));
}

function evaluateCounterevidence(
  threshold: number,
  supporting: number | null,
  contradicting: number | null,
): "rebutted_with_evidence" | "qualified" | "abstained" | "reversed" {
  if (supporting === null || contradicting === null) {
    return "abstained";
  }
  const delta = supporting - contradicting;
  if (delta > threshold) {
    return "rebutted_with_evidence";
  }
  if (delta < -threshold) {
    return "reversed";
  }
  return "qualified";
}

export const EvidenceClaimGraphV2Schema = z
  .object({
    schema_version: z.literal("evidence_claim_graph_v2"),
    run_id: Id,
    agent_id: Id,
    stage: Id,
    capability_track: CapabilityTrackSchema,
    counterevidence_rule: CounterevidenceRuleV1Schema,
    tool_results: z
      .array(
        z
          .object({
            fingerprint: Sha256,
            ...ToolResultFingerprintBodySchema.shape,
            status: z.enum(["SUCCEEDED", "FAILED"]),
          })
          .strict(),
      )
      .min(1),
    evidence_edges: z
      .array(
        z
          .object({
            edge_id: Id,
            claim_id: Id,
            tool_result_fingerprint: Sha256,
            relation: z.enum(["supports", "contradicts", "bounds"]),
            polarity: z.enum(["supporting", "contradicting"]),
            comparison_value: z.number().finite().min(0).max(1),
          })
          .strict(),
      )
      .min(1),
    accepted_claims: z
      .array(
        z
          .object({
            claim_id: Id,
            accepted: z.literal(true),
            comparison_witness: z
              .object({
                supporting_edge_ids: z.array(Id),
                contradicting_edge_ids: z.array(Id),
                supporting_value: z.number().finite().min(0).max(1).nullable(),
                contradicting_value: z.number().finite().min(0).max(1).nullable(),
              })
              .strict(),
            resolution_code: z.enum([
              "rebutted_with_evidence",
              "qualified",
              "abstained",
              "reversed",
            ]),
          })
          .strict(),
      )
      .min(1),
  })
  .strict()
  .superRefine((graph, ctx) => {
    const current = loadCurrentCapabilityContractBundle();
    if (canonicalJsonHash(graph.capability_track) !== canonicalJsonHash(current.capabilityTrack)) {
      ctx.addIssue({
        code: "custom",
        path: ["capability_track"],
        message: "capability track fixed-point mismatch",
      });
    }
    const bindings = new Map(
      current.bindingManifest.bindings.map((row) => [row.binding_id, row] as const),
    );
    const successful = new Set(
      graph.tool_results.filter((row) => row.status === "SUCCEEDED").map((row) => row.fingerprint),
    );
    const fingerprints = new Set<string>();
    for (const [index, result] of graph.tool_results.entries()) {
      const binding = bindings.get(result.binding_id);
      if (
        !binding ||
        binding.agent_id !== graph.agent_id ||
        binding.stage !== graph.stage ||
        binding.semantic_capability_id !== result.semantic_capability_id ||
        binding.tool_id !== result.tool_id
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["tool_results", index, "binding_id"],
          message: "tool result binding exact lookup mismatch",
        });
      }
      const { fingerprint: _, status: __, ...fingerprintBody } = result;
      if (result.fingerprint !== canonicalToolResultFingerprint(fingerprintBody)) {
        ctx.addIssue({
          code: "custom",
          path: ["tool_results", index, "fingerprint"],
          message: "tool result fingerprint mismatch",
        });
      }
      if (result.tool_environment_hash !== graph.capability_track.tool_environment_hash) {
        ctx.addIssue({
          code: "custom",
          path: ["tool_results", index, "tool_environment_hash"],
          message: "tool result capability track environment mismatch",
        });
      }
      if (fingerprints.has(result.fingerprint)) {
        ctx.addIssue({
          code: "custom",
          path: ["tool_results", index, "fingerprint"],
          message: "duplicate tool result fingerprint",
        });
      }
      fingerprints.add(result.fingerprint);
    }
    const claims = new Set(graph.accepted_claims.map((row) => row.claim_id));
    if (claims.size !== graph.accepted_claims.length) {
      ctx.addIssue({ code: "custom", path: ["accepted_claims"], message: "duplicate claim id" });
    }
    const edgeIds = new Set<string>();
    for (const [index, edge] of graph.evidence_edges.entries()) {
      if (!successful.has(edge.tool_result_fingerprint) || !claims.has(edge.claim_id)) {
        ctx.addIssue({
          code: "custom",
          path: ["evidence_edges", index],
          message: "edge lacks successful accepted lineage",
        });
      }
      if (
        (edge.relation === "supports" && edge.polarity !== "supporting") ||
        (edge.relation === "contradicts" && edge.polarity !== "contradicting")
      ) {
        ctx.addIssue({
          code: "custom",
          path: ["evidence_edges", index, "polarity"],
          message: "evidence relation polarity mismatch",
        });
      }
      if (edgeIds.has(edge.edge_id)) {
        ctx.addIssue({
          code: "custom",
          path: ["evidence_edges", index, "edge_id"],
          message: "duplicate evidence edge id",
        });
      }
      edgeIds.add(edge.edge_id);
    }
    for (const [index, claim] of graph.accepted_claims.entries()) {
      const claimEdges = graph.evidence_edges.filter((edge) => edge.claim_id === claim.claim_id);
      if (claimEdges.length === 0) {
        ctx.addIssue({
          code: "custom",
          path: ["accepted_claims", index],
          message: "accepted claim lacks typed evidence",
        });
        continue;
      }
      const supporting = claimEdges
        .filter((edge) => edge.polarity === "supporting")
        .sort((left, right) => left.edge_id.localeCompare(right.edge_id));
      const contradicting = claimEdges
        .filter((edge) => edge.polarity === "contradicting")
        .sort((left, right) => left.edge_id.localeCompare(right.edge_id));
      const supportingValue = supporting.length
        ? Math.max(...supporting.map((edge) => edge.comparison_value))
        : null;
      const contradictingValue = contradicting.length
        ? Math.max(...contradicting.map((edge) => edge.comparison_value))
        : null;
      const expectedWitness = {
        supporting_edge_ids: supporting.map((edge) => edge.edge_id),
        contradicting_edge_ids: contradicting.map((edge) => edge.edge_id),
        supporting_value: supportingValue,
        contradicting_value: contradictingValue,
      };
      if (canonicalJsonHash(claim.comparison_witness) !== canonicalJsonHash(expectedWitness)) {
        ctx.addIssue({
          code: "custom",
          path: ["accepted_claims", index, "comparison_witness"],
          message: "comparison witness mismatch",
        });
      }
      const expectedResolution = evaluateCounterevidence(
        graph.counterevidence_rule.threshold,
        supportingValue,
        contradictingValue,
      );
      if (claim.resolution_code !== expectedResolution) {
        ctx.addIssue({
          code: "custom",
          path: ["accepted_claims", index, "resolution_code"],
          message: "resolution derivation mismatch",
        });
      }
    }
  });

export const ActivePromptReleaseV4Schema = z
  .object({
    schema_version: z.literal("active_prompt_release_manifest_v4"),
    release_id: Id,
    lifecycle_state: z.enum(["staged", "canary", "active", "rolled_back"]),
    prompt_hash: Sha256,
    execution_behavior_release_hash: Sha256,
    production_variant_roster_hash: Sha256,
    runtime_agent_manifest_hash: Sha256,
    agent_tool_manifest_hash: Sha256,
    tool_environment_hash: Sha256,
    capability_binding_manifest_hash: Sha256,
    knot_coverage_manifest_hash: Sha256,
    private_companion_pin_hash: Sha256,
    full_bundle_hash: Sha256,
  })
  .strict()
  .superRefine((release, ctx) => {
    const { full_bundle_hash: _, ...body } = release;
    if (release.full_bundle_hash !== canonicalJsonHash(body)) {
      ctx.addIssue({
        code: "custom",
        path: ["full_bundle_hash"],
        message: "full-bundle hash mismatch",
      });
    }
  });

export const PromptTrainingProjectionV2Schema = z
  .object({
    schemaVersion: z.literal("prompt_training_projection_v2"),
    target: z.record(Id, z.unknown()),
    projectionId: Id,
    projectionHash: Sha256,
    datasetSnapshotHash: Sha256,
    eligibleSampleIdsHash: Sha256,
    excludedSampleIdsHash: Sha256,
    cutoffAt: z.iso.datetime({ offset: true }),
    outcomeContract: z.record(Id, z.unknown()),
    evaluator: z.record(Id, z.unknown()),
    capabilityTrack: CapabilityTrackSchema,
    capabilityUseAggregates: z.array(KnotCapabilityUseAggregateSchema),
    maturityContract: z
      .object({
        horizonId: Id,
        horizonContractHash: Sha256,
        outcomeContractHash: Sha256,
        tradingCalendarHash: Sha256,
        labelReceiptSetHash: Sha256,
        eligibilityEvaluatorVersion: z.literal("mature_sample_eligibility_v1"),
      })
      .strict(),
    matureSampleCount: z.number().int().nonnegative(),
    scoreSummary: z.record(Id, z.number().finite()),
    tailFailureCaseRefs: z.array(Id),
    failureCategoryCounts: z.record(Id, z.number().int().nonnegative()),
    directComponents: z.array(z.unknown()),
    controlledExperiments: z.array(z.unknown()),
  })
  .strict()
  .superRefine((projection, ctx) => {
    const { projectionHash: _, ...body } = projection;
    if (projection.projectionHash !== canonicalJsonHash(body)) {
      ctx.addIssue({
        code: "custom",
        path: ["projectionHash"],
        message: "projection hash mismatch",
      });
    }
    const current = loadCurrentCapabilityContractBundle();
    if (
      canonicalJsonHash(projection.capabilityTrack) !== canonicalJsonHash(current.capabilityTrack)
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["capabilityTrack"],
        message: "training capability track fixed-point mismatch",
      });
    }
    const expectedBindingIds = new Set(
      current.bindingManifest.bindings.map((row) => row.binding_id),
    );
    const actualBindingIds = projection.capabilityUseAggregates.map((row) => row.binding_id);
    if (
      new Set(actualBindingIds).size !== actualBindingIds.length ||
      expectedBindingIds.size !== actualBindingIds.length ||
      actualBindingIds.some((bindingId) => !expectedBindingIds.has(bindingId))
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["capabilityUseAggregates"],
        message: "training aggregate binding exact closure mismatch",
      });
    }
  });

export function assertKnotTransitionAction(
  action: string,
  transitionFreeze: { state: string; allowed_actions: ReadonlyArray<string> },
): void {
  if (
    transitionFreeze.state !== "FROZEN_UNTIL_GATE_D" ||
    !transitionFreeze.allowed_actions.includes(action)
  ) {
    throw new Error(`KNOT evolution frozen until Gate D: ${action}`);
  }
}

let currentTransitionFreeze: { state: string; allowed_actions: ReadonlyArray<string> } | undefined;

export function assertCurrentKnotTransitionAction(action: string): void {
  if (!currentTransitionFreeze) {
    const artifactUrl = new URL(
      "../../../registry/prompt_checks/capability_preservation/agent_capability_preservation_manifest_v1.json",
      import.meta.url,
    );
    const artifact = JSON.parse(readFileSync(artifactUrl, "utf8")) as Record<string, unknown>;
    const manifestHash = artifact.manifest_hash;
    const { manifest_hash: _, ...body } = artifact;
    const transitionFreeze = artifact.transition_freeze;
    if (
      typeof manifestHash !== "string" ||
      manifestHash !== canonicalJsonHash(body) ||
      typeof transitionFreeze !== "object" ||
      transitionFreeze === null ||
      !("state" in transitionFreeze) ||
      !("allowed_actions" in transitionFreeze) ||
      typeof transitionFreeze.state !== "string" ||
      !Array.isArray(transitionFreeze.allowed_actions) ||
      !transitionFreeze.allowed_actions.every((value) => typeof value === "string")
    ) {
      throw new Error("current KNOT transition freeze artifact is invalid");
    }
    currentTransitionFreeze = {
      state: transitionFreeze.state,
      allowed_actions: transitionFreeze.allowed_actions,
    };
  }
  assertKnotTransitionAction(action, currentTransitionFreeze);
}
