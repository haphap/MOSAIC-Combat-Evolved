import { z } from "zod";
import { canonicalJsonHash } from "../helpers/canonical_json.js";

const Sha256Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);

export const DETERMINISTIC_DECISION_POLICY_DEFINITIONS = {
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

const PolicyValuesSchema = z
  .object({
    cro: z
      .object({
        stop_loss_pct: z.number().finite(),
        max_single_name_weight: z.number().finite(),
        max_sector_weight: z.number().finite(),
      })
      .strict(),
    cio: z.object({ stale_thesis_days: z.number().int() }).strict(),
    autonomous_execution: z
      .object({
        min_delta_trade_weight: z.number().finite(),
        slippage_cap: z.number().finite(),
        liquidity_floor: z.number().finite(),
      })
      .strict(),
  })
  .strict();

export const DeterministicDecisionPolicyReleaseSchema = z
  .object({
    schema_version: z.literal("deterministic_decision_policy_release_v1"),
    policy_release_id: z.string().regex(/^decision-policy:[0-9a-f]{64}$/),
    effective_at: z.iso.datetime({ offset: true }),
    owner_revisions: z
      .object({
        cro: z.literal("cro_risk_policy_v1"),
        cio: z.literal("cio_portfolio_governance_policy_v1"),
        autonomous_execution: z.literal("autonomous_execution_policy_v1"),
      })
      .strict(),
    policies: PolicyValuesSchema,
    release_hash: Sha256Schema,
  })
  .strict()
  .superRefine((release, ctx) => {
    const values = {
      "cro.stop_loss_pct": release.policies.cro.stop_loss_pct,
      "cro.max_single_name_weight": release.policies.cro.max_single_name_weight,
      "cro.max_sector_weight": release.policies.cro.max_sector_weight,
      "cio.stale_thesis_days": release.policies.cio.stale_thesis_days,
      "autonomous_execution.min_delta_trade_weight":
        release.policies.autonomous_execution.min_delta_trade_weight,
      "autonomous_execution.slippage_cap": release.policies.autonomous_execution.slippage_cap,
      "autonomous_execution.liquidity_floor": release.policies.autonomous_execution.liquidity_floor,
    } as const;
    for (const [policyId, value] of Object.entries(values)) {
      const definition =
        DETERMINISTIC_DECISION_POLICY_DEFINITIONS[
          policyId as keyof typeof DETERMINISTIC_DECISION_POLICY_DEFINITIONS
        ];
      if (value < definition.minimum || value > definition.maximum) {
        ctx.addIssue({
          code: "custom",
          path: ["policies"],
          message: `${policyId} is outside its owner-approved range`,
        });
      }
      const steps = (value - definition.minimum) / definition.step;
      if (Math.abs(steps - Math.round(steps)) > 1e-9) {
        ctx.addIssue({
          code: "custom",
          path: ["policies"],
          message: `${policyId} is not on its owner-approved step`,
        });
      }
    }
    const { release_hash: _releaseHash, ...withIdentity } = release;
    const { policy_release_id: _releaseId, ...identityBody } = withIdentity;
    const expectedId = `decision-policy:${canonicalJsonHash(identityBody).slice("sha256:".length)}`;
    if (release.policy_release_id !== expectedId) {
      ctx.addIssue({
        code: "custom",
        path: ["policy_release_id"],
        message: "policy release ID mismatch",
      });
    }
    if (release.release_hash !== canonicalJsonHash(withIdentity)) {
      ctx.addIssue({
        code: "custom",
        path: ["release_hash"],
        message: "policy release hash mismatch",
      });
    }
  });

export type DeterministicDecisionPolicyRelease = z.infer<
  typeof DeterministicDecisionPolicyReleaseSchema
>;

export function buildDeterministicDecisionPolicyRelease(input: {
  effectiveAt: string;
  policies: z.input<typeof PolicyValuesSchema>;
}): DeterministicDecisionPolicyRelease {
  const identityBody = {
    schema_version: "deterministic_decision_policy_release_v1" as const,
    effective_at: input.effectiveAt,
    owner_revisions: {
      cro: "cro_risk_policy_v1" as const,
      cio: "cio_portfolio_governance_policy_v1" as const,
      autonomous_execution: "autonomous_execution_policy_v1" as const,
    },
    policies: PolicyValuesSchema.parse(input.policies),
  };
  const policyReleaseId = `decision-policy:${canonicalJsonHash(identityBody).slice("sha256:".length)}`;
  const withIdentity = { ...identityBody, policy_release_id: policyReleaseId };
  return DeterministicDecisionPolicyReleaseSchema.parse({
    ...withIdentity,
    release_hash: canonicalJsonHash(withIdentity),
  });
}

export function validateDeterministicDecisionPolicyRelease(
  value: unknown,
): DeterministicDecisionPolicyRelease {
  return DeterministicDecisionPolicyReleaseSchema.parse(value);
}

export const ACTIVE_DETERMINISTIC_DECISION_POLICY_RELEASE = buildDeterministicDecisionPolicyRelease(
  {
    effectiveAt: "2026-08-05T00:00:00+08:00",
    policies: {
      cro: {
        stop_loss_pct: DETERMINISTIC_DECISION_POLICY_DEFINITIONS["cro.stop_loss_pct"].defaultValue,
        max_single_name_weight:
          DETERMINISTIC_DECISION_POLICY_DEFINITIONS["cro.max_single_name_weight"].defaultValue,
        max_sector_weight:
          DETERMINISTIC_DECISION_POLICY_DEFINITIONS["cro.max_sector_weight"].defaultValue,
      },
      cio: {
        stale_thesis_days:
          DETERMINISTIC_DECISION_POLICY_DEFINITIONS["cio.stale_thesis_days"].defaultValue,
      },
      autonomous_execution: {
        min_delta_trade_weight:
          DETERMINISTIC_DECISION_POLICY_DEFINITIONS["autonomous_execution.min_delta_trade_weight"]
            .defaultValue,
        slippage_cap:
          DETERMINISTIC_DECISION_POLICY_DEFINITIONS["autonomous_execution.slippage_cap"]
            .defaultValue,
        liquidity_floor:
          DETERMINISTIC_DECISION_POLICY_DEFINITIONS["autonomous_execution.liquidity_floor"]
            .defaultValue,
      },
    },
  },
);
