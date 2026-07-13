import { describe, expect, it } from "vitest";
import {
  type CommandRunner,
  preflightQwen35bPreset,
  QWEN_35B_NVFP4_PRESET,
  resolveQwen35bPreset,
  verifyQwen35bRuntimeImage,
} from "../src/runtime/sndr.js";

const preset = {
  id: QWEN_35B_NVFP4_PRESET,
  model: "qwen3.6-35b-a3b-nvfp4-5090",
  hardware: "rtx-5090d-1x-32gbvram",
  profile: "nvidia-qwen3.6-35b-a3b-nvfp4-tq-k8v4-5090",
  card: {
    status: "experimental",
    card_version: 2,
    card_updated: "2026-07-13",
    context: { max_model_len: 128000 },
    concurrency: { canonical: 1 },
    hardware_fit: { engine_pin: "0.23.1rc1.dev424+g3f5a1e173" },
  },
};

const rendered = [
  "vllm serve",
  "--gpu-memory-utilization 0.85",
  "--max-model-len 128000",
  "--max-num-seqs 1",
  "--max-num-batched-tokens 2048",
  "--kv-cache-dtype turboquant_4bit_nc",
  "--served-model-name qwen3.6-35b-a3b-nvfp4",
  "--tool-call-parser qwen3_xml",
  "--reasoning-parser qwen3",
  "--port 8000",
  `--speculative-config '{"method": "mtp", "num_speculative_tokens": 3}'`,
  "--name vllm-qwen3.6-35b-a3b-nvfp4-5090-5090d",
  "vllm/vllm-openai@sha256:c4fac672fcab4560b6572cc216ddbde94b5ed28f90cc8119b996fc868fe728d4",
].join(" ");

describe("sndr Qwen 35B preset resolution", () => {
  it("uses the current sndr card and rendered launch instead of stale constants", () => {
    const resolution = resolveQwen35bPreset(runner());

    expect(resolution.profileId).toBe("nvidia-qwen3.6-35b-a3b-nvfp4-tq-k8v4-5090");
    expect(resolution.maxModelLen).toBe(128_000);
    expect(resolution.gpuMemoryUtilization).toBe(0.85);
    expect(resolution.maxNumBatchedTokens).toBe(2_048);
    expect(resolution.kvCacheDtype).toBe("turboquant_4bit_nc");
    expect(resolution.speculativeTokens).toBe(3);
    expect(resolution.toolCallParser).toBe("qwen3_xml");
    expect(resolution.containerName).toBe("vllm-qwen3.6-35b-a3b-nvfp4-5090-5090d");
    expect(resolution.imageRef).toMatch(/^vllm\/vllm-openai@sha256:/);
    expect(resolution.hash).toMatch(/^sha256:[0-9a-f]{64}$/);
  });

  it("binds the running container to the image rendered by sndr", () => {
    const base = runner();
    const imageId = `sha256:${"a".repeat(64)}`;
    const dockerRunner: CommandRunner = (command, args) => {
      if (command === "docker") return ok(`${imageId}\n`);
      return base(command, args);
    };

    expect(verifyQwen35bRuntimeImage(resolveQwen35bPreset(base), dockerRunner)).toBe(imageId);
  });

  it("fails closed when preflight is not runnable", () => {
    expect(() => preflightQwen35bPreset(runner("VERDICT: CANNOT RUN"))).toThrow(
      /did not report RUNNABLE/,
    );
  });
});

function runner(preflight = "VERDICT: RUNNABLE (with warnings)"): CommandRunner {
  return (_command, args) => {
    if (args[0] === "--version") return ok("sndr 12.0.0.dev0\n");
    if (args[0] === "preset") return ok(`${JSON.stringify(preset)}\n`);
    if (args[0] === "launch") return ok(rendered);
    if (args[0] === "preflight") return ok(preflight);
    return { status: 1, stdout: "", stderr: "unexpected command" };
  };
}

function ok(stdout: string) {
  return { status: 0, stdout, stderr: "" };
}
