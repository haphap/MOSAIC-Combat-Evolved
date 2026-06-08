# RKE Confidence Policy

Confidence is capped by the weakest part of the evidence chain.

## Components

- `data_confidence`: freshness, completeness, fallback use, and tool quality.
- `research_weight_confidence`: source/viewpoint reliability, extraction quality,
  disagreement, and independent-source support.
- `empirical_validation_confidence`: validation, walk-forward, and paper-trading evidence.
- `method_tool_confidence`: tool coverage, point-in-time availability, tool
  correctness, recipe validation, and shadow-runtime status.
- `regime_match_confidence`: whether current regime matches the rule conditions.

## Conservative Function

```text
pre_cap_confidence = min(
  data_confidence,
  research_weight_confidence,
  empirical_validation_confidence,
  method_tool_confidence,
  regime_match_confidence
)

final_confidence = min(pre_cap_confidence, confidence_cap)
```

## Actionability

- `< 0.55`: no trade or monitor only.
- `0.55 <= confidence < 0.65`: watchlist or tiny tilt only if current data confirms.
- `0.65 <= confidence < 0.75`: modest tilt subject to risk and cost constraints.
- `>= 0.75`: stronger action requires risk approval.

## Research-Only Rule

If current data does not confirm the research prior:

- `data_confidence <= 0.50`;
- `final_confidence <= 0.50`;
- actionability must be `no_trade` or `monitor_only`.

## Required Runtime Components

Runtime confidence must be traceable to:

- evidence ledger entries with tool, metric, value, as-of date, freshness, and
  fallback status;
- rule fire outputs with rule IDs, validation status, and source claim IDs;
- aggregation summary with correlated-rule de-duplication;
- conflict objects when opposing rules fire;
- downstream handoff and progress event.

Research-derived adjustments are capped at three levels:

- single rule;
- rule group;
- global research adjustment.

## Calibration

Confidence buckets must be compared against realized outcomes.

Each bucket should track:

- expected hit rate;
- realized hit rate;
- calibration error;
- sample size;
- degradation status;
- required action.

If calibration degrades, confidence mapping must be lowered or the rule must be
revalidated. LLM-written confidence values without calibration evidence are not
valid production confidence.
