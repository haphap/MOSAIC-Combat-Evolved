# RKE Validation Policy

Validation is a governed experiment, not a filter over backtest results.

## Required Gates

- Every candidate must belong to an experiment family.
- Every experiment must be pre-registered before validation results are used.
- The frozen specification must include rule IDs, parameter paths, candidate values, metric proxies, sampling design, multiple-testing policy, and acceptance rules.
- Effective sample size is measured in independent events, not raw daily rows.
- Overlapping windows must use non-overlap, block bootstrap, stationary bootstrap, or Newey-West style correction.
- Family-level multiple-testing correction is required before promotion.
- The primary metric must be after-cost.
- Walk-forward validation is required before paper trading.
- Lockbox review is required before production eligibility.
- Direct production promotion is prohibited.

## Evidence Artifacts

- Data availability matrix for all metric proxies.
- Validation experiment v2 object.
- Frozen spec hash.
- Hardened validation report containing effective N, overlap policy, adjusted q-value, net alpha after cost, walk-forward status, lockbox status, and promotion decision.
- Rollback rule for every accepted production patch.
