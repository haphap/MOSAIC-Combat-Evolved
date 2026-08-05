import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { z } from "zod";
import {
  ACTIVE_DETERMINISTIC_DECISION_POLICY_RELEASE,
  buildDeterministicDecisionPolicyRelease,
  DETERMINISTIC_DECISION_POLICY_DEFINITIONS,
  DeterministicDecisionPolicyReleaseSchema,
  validateDeterministicDecisionPolicyRelease,
} from "../src/agents/decision/deterministic_policy.js";

const EXPECTED_DEFINITIONS = {
  "cro.stop_loss_pct": { defaultValue: -0.08, minimum: -0.2, maximum: -0.03, step: 0.01 },
  "cro.max_single_name_weight": {
    defaultValue: 0.12,
    minimum: 0.05,
    maximum: 0.2,
    step: 0.01,
  },
  "cro.max_sector_weight": { defaultValue: 0.3, minimum: 0.15, maximum: 0.45, step: 0.05 },
  "cio.stale_thesis_days": { defaultValue: 20, minimum: 5, maximum: 60, step: 5 },
  "autonomous_execution.min_delta_trade_weight": {
    defaultValue: 0.01,
    minimum: 0.005,
    maximum: 0.05,
    step: 0.005,
  },
  "autonomous_execution.slippage_cap": {
    defaultValue: 0.003,
    minimum: 0.001,
    maximum: 0.02,
    step: 0.001,
  },
  "autonomous_execution.liquidity_floor": {
    defaultValue: 0.6,
    minimum: 0.3,
    maximum: 0.9,
    step: 0.05,
  },
} as const;

describe("deterministic decision policy contract", () => {
  it("contains exactly the seven owner-controlled policies with preserved priors", () => {
    expect(DETERMINISTIC_DECISION_POLICY_DEFINITIONS).toEqual(EXPECTED_DEFINITIONS);
    expect(Object.keys(DETERMINISTIC_DECISION_POLICY_DEFINITIONS)).toHaveLength(7);
    expect(
      validateDeterministicDecisionPolicyRelease(ACTIVE_DETERMINISTIC_DECISION_POLICY_RELEASE),
    ).toEqual(ACTIVE_DETERMINISTIC_DECISION_POLICY_RELEASE);
  });

  it("fails closed on missing, out-of-range, off-step, or tampered releases", () => {
    const active = ACTIVE_DETERMINISTIC_DECISION_POLICY_RELEASE;
    expect(() =>
      validateDeterministicDecisionPolicyRelease({
        ...active,
        policies: { cro: active.policies.cro, cio: active.policies.cio },
      }),
    ).toThrow();
    expect(() =>
      buildDeterministicDecisionPolicyRelease({
        effectiveAt: active.effective_at,
        policies: {
          ...active.policies,
          cro: { ...active.policies.cro, max_single_name_weight: 0.21 },
        },
      }),
    ).toThrow(/outside its owner-approved range/);
    expect(() =>
      buildDeterministicDecisionPolicyRelease({
        effectiveAt: active.effective_at,
        policies: {
          ...active.policies,
          autonomous_execution: {
            ...active.policies.autonomous_execution,
            liquidity_floor: 0.61,
          },
        },
      }),
    ).toThrow(/not on its owner-approved step/);
    expect(() =>
      validateDeterministicDecisionPolicyRelease({
        ...active,
        release_hash: `sha256:${"0".repeat(64)}`,
      }),
    ).toThrow(/policy release hash mismatch/);
  });

  it("matches the committed generated schema and active release exactly", () => {
    const root = resolve(process.cwd(), "..");
    const schema = JSON.parse(
      readFileSync(
        resolve(root, "schemas/deterministic_decision_policy_release_v1.schema.json"),
        "utf8",
      ),
    );
    const release = JSON.parse(
      readFileSync(
        resolve(root, "registry/prompt_checks/deterministic_decision_policy_release_v1.json"),
        "utf8",
      ),
    );
    expect(schema).toEqual(z.toJSONSchema(DeterministicDecisionPolicyReleaseSchema));
    expect(release).toEqual(ACTIVE_DETERMINISTIC_DECISION_POLICY_RELEASE);
  });
});
