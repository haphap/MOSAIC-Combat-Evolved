# RKE Lockbox Review Checklist

Use this checklist only after gold-set, analytical-footprint, and source-license gates pass.
The lockbox is a one-time final holdout gate; do not open it while other manual gates are still pending.

## Target

- Experiment family: `FAM-CB-LIQUIDITY-2026Q2`
- Experiment ID: `EXP-CB-20260605-0001`
- Current result: `not_opened`
- Current open count: `0`
- Target review path: `registry/lockbox/central_bank_lockbox_review.json`
- Target row hash: `sha256:0b39a20fcd0826937d42a0425a2bb9a9b50379eab8aff24d58247d8ced70f08b`

## Policy

- Policy path: `registry/evaluation/lockbox/lockbox_policy.json`
- Policy status: `paper_trading_only`
- Direct production allowed: `false`
- Lockbox required for final promotion: `true`
- Review context hash: `sha256:068512fdfb2632887dd093af770d61dd340e199604a22aa5249e7958edd478cf`

## Required Manual Fields

- `opened_at`: ISO-8601 datetime with timezone.
- `opened_by`: reviewer identity.
- `open_count`: integer; production requires this to be `1` for the first opening.
- `result`: `passed` or `failed`; production requires `passed`.
- `parameter_search_after_open`: must stay `false` for production.
- `rule_design_after_open`: must stay `false` for production.
- `notes`: concise reviewer note; no source prose.

## Commands

- Prepare scratch: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke prepare-lockbox-review --root .`
- Reviewed scratch: `registry/review_batches/lockbox_reviewed.json`
- Dry run: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json --dry-run`
- Apply: `MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke apply-lockbox-review --root . --input registry/review_batches/lockbox_reviewed.json`

## Do Not Proceed If

- Gold-set review has pending rows or failed metrics.
- Analytical-footprint review has pending rows or failed quality metrics.
- Source-license policy is not accepted.
- The target or policy hash in the reviewed scratch differs from this checklist.
- Any parameter search or rule design happened after opening the lockbox.
