import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";

export const QWEN_35B_NVFP4_PRESET = "nvidia-qwen3.6-35b-a3b-nvfp4-5090";
export const QWEN_35B_SERVED_MODEL = "qwen3.6-35b-a3b-nvfp4";

export interface SndrPresetResolution {
  sndrVersion: string;
  presetId: string;
  modelId: string;
  hardwareId: string;
  profileId: string;
  cardVersion: number;
  cardUpdated: string;
  status: string;
  enginePin: string;
  servedModel: string;
  port: number;
  maxModelLen: number;
  maxNumSeqs: number;
  maxNumBatchedTokens: number;
  gpuMemoryUtilization: number;
  kvCacheDtype: string;
  speculativeMethod: string;
  speculativeTokens: number;
  toolCallParser: string;
  reasoningParser: string;
  containerName: string;
  imageRef: string;
  hash: string;
}

export interface CommandResult {
  status: number;
  stdout: string;
  stderr: string;
}

export type CommandRunner = (command: string, args: ReadonlyArray<string>) => CommandResult;

const defaultRunner: CommandRunner = (command, args) => {
  const result = spawnSync(command, [...args], { encoding: "utf-8" });
  return {
    status: result.status ?? 1,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
  };
};

function runOrThrow(
  runner: CommandRunner,
  command: string,
  args: ReadonlyArray<string>,
): CommandResult {
  const result = runner(command, args);
  if (result.status !== 0) {
    throw new Error(
      `${command} ${args.join(" ")} failed: ${(result.stderr || result.stdout).trim()}`,
    );
  }
  return result;
}

function flagNumber(rendered: string, flag: string): number {
  const match = rendered.match(new RegExp(`${flag.replaceAll("-", "\\-")}\\s+([0-9.]+)`));
  const value = match ? Number(match[1]) : Number.NaN;
  if (!Number.isFinite(value)) throw new Error(`sndr rendered launch is missing ${flag}`);
  return value;
}

function flagString(rendered: string, flag: string): string {
  const match = rendered.match(new RegExp(`${flag.replaceAll("-", "\\-")}\\s+([^\\s'\\"]+)`));
  if (!match?.[1]) throw new Error(`sndr rendered launch is missing ${flag}`);
  return match[1];
}

function resolutionHash(value: Omit<SndrPresetResolution, "hash">): string {
  const payload = JSON.stringify(
    Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right))),
  );
  return `sha256:${createHash("sha256").update(payload).digest("hex")}`;
}

export function resolveQwen35bPreset(runner: CommandRunner = defaultRunner): SndrPresetResolution {
  const versionResult = runOrThrow(runner, "sndr", ["--version"]);
  const showResult = runOrThrow(runner, "sndr", [
    "preset",
    "show",
    QWEN_35B_NVFP4_PRESET,
    "--json",
  ]);
  const renderResult = runOrThrow(runner, "sndr", [
    "launch",
    QWEN_35B_NVFP4_PRESET,
    "--dry-run",
    "--skip-autodetect",
  ]);
  const preset = JSON.parse(showResult.stdout) as {
    id?: string;
    model?: string;
    hardware?: string;
    profile?: string;
    card?: {
      status?: string;
      card_version?: number;
      card_updated?: string;
      context?: { max_model_len?: number };
      concurrency?: { canonical?: number };
      hardware_fit?: { engine_pin?: string };
    };
  };
  if (preset.id !== QWEN_35B_NVFP4_PRESET) {
    throw new Error(`sndr resolved unexpected preset: ${String(preset.id)}`);
  }
  const rendered = `${renderResult.stdout}\n${renderResult.stderr}`;
  const withoutHash: Omit<SndrPresetResolution, "hash"> = {
    sndrVersion: versionResult.stdout.trim(),
    presetId: preset.id,
    modelId: String(preset.model ?? ""),
    hardwareId: String(preset.hardware ?? ""),
    profileId: String(preset.profile ?? ""),
    cardVersion: Number(preset.card?.card_version ?? 0),
    cardUpdated: String(preset.card?.card_updated ?? ""),
    status: String(preset.card?.status ?? ""),
    enginePin: String(preset.card?.hardware_fit?.engine_pin ?? ""),
    servedModel: flagString(rendered, "--served-model-name"),
    port: flagNumber(rendered, "--port"),
    maxModelLen: flagNumber(rendered, "--max-model-len"),
    maxNumSeqs: flagNumber(rendered, "--max-num-seqs"),
    maxNumBatchedTokens: flagNumber(rendered, "--max-num-batched-tokens"),
    gpuMemoryUtilization: flagNumber(rendered, "--gpu-memory-utilization"),
    kvCacheDtype: flagString(rendered, "--kv-cache-dtype"),
    speculativeMethod: rendered.includes('"method": "mtp"') ? "mtp" : "unknown",
    speculativeTokens: Number(
      rendered.match(/"num_speculative_tokens":\s*([0-9]+)/)?.[1] ?? Number.NaN,
    ),
    toolCallParser: flagString(rendered, "--tool-call-parser"),
    reasoningParser: flagString(rendered, "--reasoning-parser"),
    containerName:
      rendered.match(/\bvllm-qwen3\.6-35b-a3b-nvfp4-5090-[A-Za-z0-9._-]+\b/)?.[0] ?? "",
    imageRef: rendered.match(/\bvllm\/vllm-openai@sha256:[0-9a-f]{64}\b/)?.[0] ?? "",
  };
  if (
    withoutHash.servedModel !== QWEN_35B_SERVED_MODEL ||
    withoutHash.maxModelLen !== preset.card?.context?.max_model_len ||
    withoutHash.maxNumSeqs !== preset.card?.concurrency?.canonical ||
    !Number.isFinite(withoutHash.speculativeTokens) ||
    !withoutHash.containerName ||
    !withoutHash.imageRef
  ) {
    throw new Error("sndr 35B preset card and rendered launch disagree");
  }
  return { ...withoutHash, hash: resolutionHash(withoutHash) };
}

export function verifyQwen35bRuntimeImage(
  resolution: SndrPresetResolution,
  runner: CommandRunner = defaultRunner,
): string {
  const expected = runOrThrow(runner, "docker", [
    "image",
    "inspect",
    resolution.imageRef,
    "--format",
    "{{.Id}}",
  ]).stdout.trim();
  const running = runOrThrow(runner, "docker", [
    "inspect",
    resolution.containerName,
    "--format",
    "{{.Image}}",
  ]).stdout.trim();
  if (!/^sha256:[0-9a-f]{64}$/.test(expected) || running !== expected) {
    throw new Error(
      `running Qwen container image mismatch: expected=${expected || "missing"} actual=${running || "missing"}`,
    );
  }
  return running;
}

export function preflightQwen35bPreset(runner: CommandRunner = defaultRunner): string {
  const result = runOrThrow(runner, "sndr", ["preflight", QWEN_35B_NVFP4_PRESET]);
  const output = `${result.stdout}\n${result.stderr}`.trim();
  if (!output.includes("VERDICT: RUNNABLE")) {
    throw new Error(`sndr preflight did not report RUNNABLE:\n${output}`);
  }
  return output;
}

export function launchQwen35bPreset(runner: CommandRunner = defaultRunner): void {
  runOrThrow(runner, "sndr", ["launch", QWEN_35B_NVFP4_PRESET, "--skip-autodetect"]);
}

export async function waitForQwen35bService(opts: {
  resolution: SndrPresetResolution;
  attempts?: number;
  intervalMs?: number;
  apiKey?: string;
}): Promise<void> {
  const attempts = opts.attempts ?? 120;
  const intervalMs = opts.intervalMs ?? 5_000;
  const baseUrl = `http://127.0.0.1:${opts.resolution.port}`;
  let lastError = "service not checked";
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const health = await fetch(`${baseUrl}/health`);
      if (!health.ok) throw new Error(`health HTTP ${health.status}`);
      const headers = opts.apiKey ? { Authorization: `Bearer ${opts.apiKey}` } : undefined;
      const models = await fetch(`${baseUrl}/v1/models`, ...(headers ? [{ headers }] : []));
      if (!models.ok) throw new Error(`models HTTP ${models.status}`);
      const payload = (await models.json()) as { data?: Array<{ id?: string }> };
      if (!payload.data?.some((model) => model.id === opts.resolution.servedModel)) {
        throw new Error(`served model ${opts.resolution.servedModel} not advertised`);
      }
      return;
    } catch (error) {
      lastError = (error as Error).message;
      if (attempt + 1 < attempts) {
        await new Promise((resolve) => setTimeout(resolve, intervalMs));
      }
    }
  }
  throw new Error(`Qwen 35B service did not become ready: ${lastError}`);
}
