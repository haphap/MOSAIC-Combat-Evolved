import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  buildSectorUniverseManifest,
  SectorUniverseManifestSchema,
} from "../src/agents/sector/registry.ts";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "../..");
const artifactPath = resolve(
  repoRoot,
  "registry/prompt_checks/sector_universe_manifest_v1.json",
);
const schemaPath = resolve(repoRoot, "schemas/sector_universe_manifest_v1.schema.json");
const manifest = SectorUniverseManifestSchema.parse(buildSectorUniverseManifest());
const schema = SectorUniverseManifestSchema.toJSONSchema();
mkdirSync(dirname(artifactPath), { recursive: true });
writeFileSync(artifactPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
writeFileSync(schemaPath, `${JSON.stringify(schema, null, 2)}\n`, "utf8");
