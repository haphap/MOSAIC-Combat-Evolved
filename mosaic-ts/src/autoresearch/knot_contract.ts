import { z } from "zod";

const Sha256Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);

/**
 * Public integrity reference for the private KNOT contract.
 *
 * Scoring, scheduling, mutation and promotion fields deliberately do not cross
 * this boundary. Production resolves the referenced contract from the pinned
 * private prompt/KNOT release and fails closed on a hash mismatch.
 */
export const KnotRuntimeContractRefSchema = z
  .object({
    knot_runtime_contract_manifest_id: z.string().min(1),
    knot_runtime_contract_manifest_version: z.string().min(1),
    knot_runtime_contract_manifest_hash: Sha256Schema,
    private_runtime_manifest_hash: Sha256Schema,
    research_score_contract_ref: z
      .object({
        research_score_contract_id: z.string().min(1),
        research_score_contract_version: z.string().min(1),
        research_score_contract_hash: Sha256Schema,
      })
      .strict(),
    scheduler_contract_ref: z
      .object({
        scheduler_contract_id: z.string().min(1),
        scheduler_contract_version: z.string().min(1),
        scheduler_contract_hash: Sha256Schema,
      })
      .strict(),
  })
  .strict();

export type KnotRuntimeContractRef = z.infer<typeof KnotRuntimeContractRefSchema>;

export const KNOT_RUNTIME_CONTRACT_REF: KnotRuntimeContractRef = KnotRuntimeContractRefSchema.parse(
  {
    knot_runtime_contract_manifest_id: "knot-runtime-contract",
    knot_runtime_contract_manifest_version: "knot_runtime_contract_manifest_v2",
    knot_runtime_contract_manifest_hash:
      "sha256:a8f5b1108df82be7e05d036593c4bd0826193025bfbffbb1b56824097aaa9076",
    private_runtime_manifest_hash:
      "sha256:a81cf8cca65dcc234548ee799a98c031f06a2b82b0d03d3f25b8628fdc853b49",
    research_score_contract_ref: {
      research_score_contract_id: "knot-research-score",
      research_score_contract_version: "knot_research_score_v2",
      research_score_contract_hash:
        "sha256:2ff2cdedb25b0208323190eed716498bfad6c8c18631f3bc5a1c6a01ae3843ec",
    },
    scheduler_contract_ref: {
      scheduler_contract_id: "knot-scheduler",
      scheduler_contract_version: "knot_scheduler_v2",
      scheduler_contract_hash:
        "sha256:5630393210fdf098049f9f9b93eadada90e00e2f96a5747efb6ce47169f2b6b0",
    },
  },
);

export function renderKnotRuntimeContractRefArtifact(): string {
  return `${JSON.stringify(KNOT_RUNTIME_CONTRACT_REF, null, 2)}\n`;
}
