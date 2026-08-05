import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { z } from "zod";
import {
  ACTIVE_DETERMINISTIC_DECISION_POLICY_RELEASE,
  DeterministicDecisionPolicyReleaseSchema,
} from "../src/agents/decision/deterministic_policy.js";

const root = resolve(process.cwd(), "..");
const schemaPath = resolve(root, "schemas/deterministic_decision_policy_release_v1.schema.json");
const releasePath = resolve(
  root,
  "registry/prompt_checks/deterministic_decision_policy_release_v1.json",
);
mkdirSync(resolve(root, "registry/prompt_checks"), { recursive: true });
writeFileSync(
  schemaPath,
  `${JSON.stringify(z.toJSONSchema(DeterministicDecisionPolicyReleaseSchema), null, 2)}\n`,
  "utf8",
);
writeFileSync(
  releasePath,
  `${JSON.stringify(ACTIVE_DETERMINISTIC_DECISION_POLICY_RELEASE, null, 2)}\n`,
  "utf8",
);
