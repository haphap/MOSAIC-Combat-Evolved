import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { z } from "zod";
import { ActivePromptReleaseManifestSchema } from "../src/agents/prompts/prompt_release_contract.js";
import { PROMPT_OPTIMIZER_PUBLIC_SCHEMAS } from "../src/autoresearch/prompt_optimizer_contract.js";

const schemas = {
  ...PROMPT_OPTIMIZER_PUBLIC_SCHEMAS,
  active_prompt_release_manifest_v2: ActivePromptReleaseManifestSchema,
};

for (const [schemaId, schema] of Object.entries(schemas)) {
  const output = resolve(process.cwd(), "..", "schemas", `${schemaId}.schema.json`);
  const jsonSchema = z.toJSONSchema(schema);
  writeFileSync(output, `${JSON.stringify(jsonSchema, null, 2)}\n`, "utf8");
}
