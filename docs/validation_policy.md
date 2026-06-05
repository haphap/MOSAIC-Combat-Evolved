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

## Production Promotion Gate

Run the promotion gate audit with:

```bash
mosaic-rke promotion-status --root .
```

Before applying reviewed manual inputs, simulate the combined promotion result
without mutating the working registry:

```bash
mosaic-rke promotion-dry-run --root . \
  --gold-input reviewed_gold_set.jsonl \
  --license-input reviewed_sources.jsonl \
  --lockbox-input reviewed_lockbox.json
```

The command copies the registry into a temporary directory, applies the supplied
review files there, and reports the resulting promotion gate.

The gate combines completion audit, manual gold-set status, source-license
review, source-text redaction, production source validation, paper-trading
readiness, production monitor state, rollback rule, and lockbox review into one
decision. It must report `production_allowed = false` until staged gates and the
one-time lockbox review pass. It is an audit artifact, not an automatic deploy
command.

Import a one-time lockbox review with:

```bash
mosaic-rke apply-lockbox-review --root . --input reviewed_lockbox.json --dry-run
mosaic-rke apply-lockbox-review --root . --input reviewed_lockbox.json
```

The import validates experiment identity, open count, reviewer fields, result,
and post-open search flags. It can record a failed lockbox review, but production
remains blocked unless the evaluated lockbox decision is production-eligible.

Production eligibility also requires:

- claim gold-set gate passed;
- source compliance gate passed;
- paper trading monitor ready;
- lockbox policy not violated;
- runtime output checker passing.
