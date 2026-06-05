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

## Statistical Controls

Validation reports must expose enough information to reject specification
search bias:

- experiment family ID;
- planned test count;
- selected experiment ID;
- adjusted q-value or equivalent family correction;
- deflated Sharpe ratio when selecting over Sharpe-like metrics;
- confidence interval for the after-cost primary metric;
- effective sample size;
- overlap correction method;
- walk-forward status;
- lockbox status and open count.

The acceptance rule is not satisfied when only an in-sample best bucket passes.
Regime buckets with small effective sample sizes are diagnostic only unless the
partial-pooling policy marks them eligible.

## Cost-Aware Acceptance

The primary metric must be after cost:

```text
net_alpha_after_cost = gross_alpha - transaction_cost - slippage - funding_cost
```

Acceptance requires:

- positive after-cost mean;
- confidence interval excluding zero;
- turnover and cost not worse than the registered limit;
- calibration not degraded;
- max drawdown not worse than the registered limit.

## Promotion Boundary

Passing validation moves a rule to paper trading, not direct production.

Production eligibility also requires:

- claim gold-set gate passed;
- source compliance gate passed;
- paper trading monitor ready;
- lockbox policy not violated;
- runtime output checker passing.
