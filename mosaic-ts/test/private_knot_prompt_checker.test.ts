import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { checkPrivateKnotPromptBoundary } from "../src/agents/prompts/private_knot_prompt_checker.js";
import { installTestPrivateKnotRuntime } from "./helpers/private_knot.js";

const PROMPTS_ROOT = resolve(process.cwd(), "..", "prompts", "mosaic");

describe("private KNOT prompt checker", () => {
  beforeEach(() => installTestPrivateKnotRuntime());

  it("checks every stage for a non-default production cohort", async () => {
    const report = await checkPrivateKnotPromptBoundary({
      cohort: "cohort_bull_2007",
      promptsRoot: PROMPTS_ROOT,
      requirePrivateKnot: true,
    });

    expect(report.ready).toBe(true);
    expect(report.enabled_agent_stages).toHaveLength(29);
    expect(report.bundled_fallback_agent_stages).toEqual([]);
    expect(report.unavailable_agent_stages).toEqual([]);
  });

  it("labels public no-private execution as bundled fallback", async () => {
    const report = await checkPrivateKnotPromptBoundary({
      cohort: "cohort_default",
      promptsRoot: PROMPTS_ROOT,
      requirePrivateKnot: false,
      enabledAgents: new Set(["china"]),
    });

    expect(report.ready).toBe(true);
    expect(report.enabled_agent_stages).toEqual([]);
    expect(report.bundled_fallback_agent_stages).toEqual(["china:agent_run"]);
    expect(report.unavailable_agent_stages).toEqual([]);
    expect(report.rows[0]?.status).toBe("bundled_fallback");
    expect(report.rows[0]?.snapshot_hash).toBeUndefined();
  });

  it("fails closed for an undeclared cohort instead of using the default cohort", async () => {
    const report = await checkPrivateKnotPromptBoundary({
      cohort: "cohort_unknown",
      promptsRoot: PROMPTS_ROOT,
      requirePrivateKnot: false,
      enabledAgents: new Set(["china"]),
    });

    expect(report.ready).toBe(false);
    expect(report.enabled_agent_stages).toEqual([]);
    expect(report.bundled_fallback_agent_stages).toEqual([]);
    expect(report.unavailable_agent_stages).toEqual(["china:agent_run"]);
    expect(report.rows[0]?.status).toBe("unavailable");
    expect(report.rows[0]?.reasons).toEqual(["private_knot_cohort_unavailable:cohort_unknown"]);
  });

  it("honors explicit agent and stage selections", async () => {
    const byAgent = await checkPrivateKnotPromptBoundary({
      cohort: "cohort_default",
      promptsRoot: PROMPTS_ROOT,
      requirePrivateKnot: true,
      enabledAgents: new Set(["china"]),
    });
    expect(byAgent.total_runtime_agents).toBe(1);
    expect(byAgent.rows.map((row) => `${row.agent}:${row.stage}`)).toEqual(["china:agent_run"]);

    const byStage = await checkPrivateKnotPromptBoundary({
      cohort: "cohort_default",
      promptsRoot: PROMPTS_ROOT,
      requirePrivateKnot: true,
      enabledAgentStages: new Set(["cio:cio_final"]),
    });
    expect(byStage.rows.map((row) => `${row.agent}:${row.stage}`)).toEqual(["cio:cio_final"]);
  });

  it("rejects unknown or empty selections", async () => {
    await expect(
      checkPrivateKnotPromptBoundary({
        cohort: "cohort_default",
        promptsRoot: PROMPTS_ROOT,
        enabledAgents: new Set(["unknown"]),
      }),
    ).rejects.toThrow("private_knot_selection_unknown:unknown");
    await expect(
      checkPrivateKnotPromptBoundary({
        cohort: "cohort_default",
        promptsRoot: PROMPTS_ROOT,
        enabledAgents: new Set(["china"]),
        enabledAgentStages: new Set(["cio:cio_final"]),
      }),
    ).rejects.toThrow("private_knot_selection_empty");
  });

  it("rejects model-visible private evolution vocabulary", async () => {
    const root = await mkdtemp(join(tmpdir(), "mosaic-private-prompt-check-"));
    try {
      const macroRoot = join(root, "cohort_default", "macro");
      await mkdir(macroRoot, { recursive: true });
      await Promise.all([
        writeFile(join(macroRoot, "china.zh.md"), "不要读取原始权重或演化状态。\n", "utf8"),
        writeFile(join(macroRoot, "china.en.md"), "Do not expose KNOT raw weights.\n", "utf8"),
      ]);

      const report = await checkPrivateKnotPromptBoundary({
        cohort: "cohort_default",
        promptsRoot: root,
        requirePrivateKnot: true,
        enabledAgents: new Set(["china"]),
      });

      expect(report.ready).toBe(false);
      expect(report.rows[0]?.reasons).toContain("private_knot_content_embedded_in_model_prompt");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it.each([
    "mutation manifest",
    "allowed_research_rule_ids",
    "champion behavior",
    "promotion gate",
    "raw ranks",
    "knot",
    "Darwin",
    "研究旋钮",
    "研究规则 ID",
    "变异目标",
    "冠军行为",
    "晋级门槛",
  ])("rejects private policy marker %s", async (marker) => {
    const root = await mkdtemp(join(tmpdir(), "mosaic-private-prompt-marker-"));
    try {
      const macroRoot = join(root, "cohort_default", "macro");
      await mkdir(macroRoot, { recursive: true });
      await Promise.all([
        writeFile(join(macroRoot, "china.zh.md"), `${marker}\n`, "utf8"),
        writeFile(join(macroRoot, "china.en.md"), "Public role contract.\n", "utf8"),
      ]);
      const report = await checkPrivateKnotPromptBoundary({
        cohort: "cohort_default",
        promptsRoot: root,
        enabledAgents: new Set(["china"]),
      });
      expect(report.ready).toBe(false);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
