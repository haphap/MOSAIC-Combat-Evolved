import {
  type ActivePromptReleaseManifest,
  ActivePromptReleaseManifestV4Schema,
  assertKnotGateDReleaseFixedPoint,
} from "../agents/prompts/prompt_release_contract.js";
import { loadCurrentKnotGateDReleaseAuthority } from "./capability_preservation_contract.js";

export function validateKnotGateDReleaseManifest(
  manifest: ActivePromptReleaseManifest | unknown,
): ReturnType<typeof ActivePromptReleaseManifestV4Schema.parse> {
  const parsed = ActivePromptReleaseManifestV4Schema.parse(manifest);
  assertKnotGateDReleaseFixedPoint(parsed, loadCurrentKnotGateDReleaseAuthority());
  const candidate = parsed.gate_d_receipt.candidate;
  const pin = candidate.public_private_pin;
  if (candidate.paired_environment.code_commit !== parsed.code_commit) {
    throw new Error("Gate D experiment code commit mismatch");
  }
  if (pin.public_commit !== parsed.code_commit || pin.private_commit !== parsed.prompt_commit) {
    throw new Error("Gate D release commit pin mismatch");
  }
  return parsed;
}
