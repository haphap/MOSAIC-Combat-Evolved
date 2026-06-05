# RKE Confidence Policy

Confidence is capped by the weakest part of the evidence chain.

## Components

- `data_confidence`: freshness, completeness, fallback use, and tool quality.
- `research_confidence`: source-grounded claim quality and disagreement risk.
- `empirical_validation_confidence`: validation, walk-forward, and paper-trading evidence.
- `regime_match_confidence`: whether current regime matches the rule conditions.

## Conservative Function

```text
pre_cap_confidence = min(
  data_confidence,
  research_confidence,
  empirical_validation_confidence,
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
