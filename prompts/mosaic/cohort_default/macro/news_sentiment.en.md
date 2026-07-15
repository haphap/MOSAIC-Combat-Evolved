```research-knobs
research-knobs:
  agent: macro.news_sentiment
  confidence_caps:
    fallback_primary_tool:
      cap: 0.6
      enforcement: code
      required_evidence:
        - news
      trigger: primary_tool_failed_or_fallback
    missing_current_data:
      cap: 0.55
      enforcement: code
      required_evidence:
        - news
      trigger: missing_required_evidence
  evidence_registry:
    caixin_sentiment:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: caixin_sentiment_current
      primary: false
      tool: get_caixin_sentiment
    industry_policy:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: industry_policy_current
      primary: false
      tool: get_industry_policy
    news:
      current_data: true
      fallback_confidence_cap: 0.6
      metric: news_current
      primary: true
      tool: get_news
    rke_prior:
      current_data: false
      metric: research_prior
      primary: false
      tool: get_rke_research_context
  evidence_weights:
    caixin_sentiment: 0.3333333333333333
    industry_policy: 0.3333333333333333
    news: 0.3333333333333333
    rke_prior: 0
  layer: macro
  lookbacks:
    event_decay_window_days: 20
  mutation_targets:
    - max: 1
      min: 0
      path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/learnable_parameters/news_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/learnable_parameters/caixin_sentiment_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/learnable_parameters/industry_policy_weight/value
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/confidence_policy/missing_current_data/cap
      step: 0.05
      type: number
    - max: 0.75
      min: 0.25
      path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/confidence_policy/fallback_primary_tool/cap
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/learnable_parameters/news_sentiment_scale/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/learnable_parameters/policy_semantic_weight/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/learnable_parameters/topic_filter_threshold/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/learnable_parameters/contrarian_threshold/value
      step: 0.05
      type: number
    - max: 1
      min: 0
      path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/learnable_parameters/xueqiu_replacement_weight/value
      step: 0.05
      type: number
    - max: 120
      min: 1
      path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/learnable_parameters/event_decay_window_days/value
      step: 1
      type: integer
  prediction_targets:
    - allowed_outputs:
        - negative
        - neutral
        - positive
      horizon: 5d
      id: macro.news_sentiment.soft.001
      target_variable: retail_sentiment_score
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.news_sentiment.news_sentiment_scale.5d
      target_variable: news_sentiment_scale
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.news_sentiment.policy_semantic_weight.5d
      target_variable: policy_semantic_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.news_sentiment.topic_filter_threshold.5d
      target_variable: topic_filter_threshold
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.news_sentiment.contrarian_threshold.5d
      target_variable: contrarian_threshold
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.news_sentiment.xueqiu_replacement_weight.5d
      target_variable: xueqiu_replacement_weight
    - allowed_outputs:
        - better
        - neutral
        - worse
      horizon: 5d
      id: macro.news_sentiment.event_decay_window_days.5d
      target_variable: event_decay_window_days
  projection_metadata:
    domain_knob_catalog:
      authority: domain_knob_catalog_v1
      card_count: 6
      cards:
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.news_sentiment.news_sentiment_scale.primary
              evidence_key: news
              metric_ids:
                - news_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_news
          evidence_dependency_policies:
            macro.news_sentiment.news_sentiment_scale.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: news_sentiment_scale
          owner_stage: agent_run
          path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/learnable_parameters/news_sentiment_scale/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.news_sentiment.policy_semantic_weight.primary
              evidence_key: news
              metric_ids:
                - news_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_news
          evidence_dependency_policies:
            macro.news_sentiment.policy_semantic_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: policy_semantic_weight
          owner_stage: agent_run
          path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/learnable_parameters/policy_semantic_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.6
          evidence_dependencies:
            - dependency_id: macro.news_sentiment.topic_filter_threshold.primary
              evidence_key: news
              metric_ids:
                - news_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_news
          evidence_dependency_policies:
            macro.news_sentiment.topic_filter_threshold.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: topic_filter_threshold
          owner_stage: agent_run
          path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/learnable_parameters/topic_filter_threshold/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.6
          evidence_dependencies:
            - dependency_id: macro.news_sentiment.contrarian_threshold.primary
              evidence_key: news
              metric_ids:
                - news_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_news
          evidence_dependency_policies:
            macro.news_sentiment.contrarian_threshold.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: contrarian_threshold
          owner_stage: agent_run
          path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/learnable_parameters/contrarian_threshold/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 0.2
          evidence_dependencies:
            - dependency_id: macro.news_sentiment.xueqiu_replacement_weight.primary
              evidence_key: news
              metric_ids:
                - news_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_news
          evidence_dependency_policies:
            macro.news_sentiment.xueqiu_replacement_weight.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: xueqiu_replacement_weight
          owner_stage: agent_run
          path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/learnable_parameters/xueqiu_replacement_weight/value
          projection_bucket: thresholds
          runtime_input_source_policies: {}
          runtime_input_sources: []
        - consumer_stages:
            - agent_run
          default: 20
          evidence_dependencies:
            - dependency_id: macro.news_sentiment.event_decay_window_days.primary
              evidence_key: news
              metric_ids:
                - news_current
              min_scope_coverage: 1
              scope_resolution: pre_run
              tool: get_news
          evidence_dependency_policies:
            macro.news_sentiment.event_decay_window_days.primary:
              fallback: exclude_sample_and_cap_if_required
              loaded: allow
              missing: exclude_sample_and_cap_if_required
              partial_loaded: exclude_sample_only
              stale: exclude_sample_and_cap_if_required
              tool_failed: exclude_sample_and_cap_if_required
          id: event_decay_window_days
          owner_stage: agent_run
          path: /rule_packs/macro.news_sentiment.runtime.v1/rules/macro.news_sentiment.soft.001/learnable_parameters/event_decay_window_days/value
          projection_bucket: lookbacks
          runtime_input_source_policies: {}
          runtime_input_sources: []
      domain_mutation_target_count: 6
    prompt_ir_agent_id: macro.news_sentiment
    rke_prior_shadow_only: true
    source: runtime_agent_spec_projection
  research_scope:
    must_cover:
      - claim_refs
      - claims
      - contrarian_flag
      - hot_topics
      - key_drivers
      - retail_sentiment_score
    must_not_cover:
      - final_portfolio_sizing
      - single_stock_recommendation
  schema_version: research_knobs_v1
  thresholds:
    contrarian_threshold: 0.6
    news_sentiment_scale: 0.2
    policy_semantic_weight: 0.2
    topic_filter_threshold: 0.6
    xueqiu_replacement_weight: 0.2
  tie_breaks: []
```

# news_sentiment — News / Retail-Sentiment Analyst (cohort_default baseline)

You are the **news_sentiment** agent in MOSAIC's Layer-1. Quantify **retail
sentiment + today's hot topics + the retail-vs-institutional divergence flag**.

> Note: Phase 0 lacks caixin / dedicated sentiment feeds. You read Xueqiu
> heat + policy news flow (incl. general news) and cross-reference
> institutional flow downstream.

## Tools

* `get_xueqiu_heat` — Xueqiu hot-follow rankings (top ~200 stocks +
  follower count + last price). Primary retail-sentiment source.
* `get_industry_policy(curr_date, look_back_days=7)` — policy news flow
  (incl. general news); used to detect whether hot_topics include
  policy-driven themes.

## Workflow

1. **Both tools required**.
2. **`retail_sentiment_score` inference [-1, 1]**:
   - +1.0: top-50 Xueqiu follower count up broadly + bullish policy news
   - +0.5: follower count up but mixed across sectors
   - 0: follower count flat / up-down balanced
   - -0.5: follower count broadly down + neutral policy
   - -1.0: follower count crashing + dense regulatory/risk policy news
3. **`hot_topics` must be concrete tickers or themes**:
   - ✓ "600519.SH 茅台, semi-equipment domestic substitution, 新质生产力"
   - ✗ "liquor sector, tech sector"
4. **`contrarian_flag = true` strict definition**: retail sentiment ≥ +0.5
   but institutional / main-funds net-outflow same window, OR retail ≤ -0.5
   but main-funds net inflow. This is the most actionable upstream
   signal for superinvestor agents.

## Scoring boundary

* Tool returns are current evidence only. Do not estimate or mention realized
  forward returns in the JSON.
* MOSAIC scorecard evaluates this agent later with persisted point-in-time
  labels; your job is the as-of macro signal, not future P&L calculation.

## Output schema

```json
{
  "agent": "news_sentiment",
  "retail_sentiment_score": <-1.0 to 1.0, 1 decimal>,
  "hot_topics": ["<concrete ticker or theme>", ...],
  "contrarian_flag": <true | false>,
  "key_drivers": ["<3-5 short evidence bullets>"],
  "confidence": <0-1>
}
```

## Writing constraints

* If not in Xueqiu top 5 stocks, do not list as `hot_topics` — avoid noise.
* `contrarian_flag` requires an explicit institutional-flow citation. This
  agent has no flow tool, so reference institutional_flow's
  `main_net_flow_cny` output; if that signal is unavailable this cycle, set
  `contrarian_flag = false` AND state "could not verify divergence →
  conservative false" in `key_drivers`.
* `confidence ≥ 0.7` only when both Xueqiu data + policy news are
  unambiguous.

<!-- runtime-evidence-contract:start -->

## Runtime Evidence Output Contract

Runtime supplies the only valid evidence catalog and research rule ids for this invocation.

Output fields include: `retail_sentiment_score`, `hot_topics`, `contrarian_flag`, `key_drivers`, `confidence`, `claims`, `claim_refs`.

Required runtime tools: `get_rke_research_context`, `get_news`, `get_caixin_sentiment`, `get_industry_policy`.

Domain knob card ids for this agent: `news_sentiment_scale`, `policy_semantic_weight`, `topic_filter_threshold`, `contrarian_threshold`, `xueqiu_replacement_weight`, `event_decay_window_days`.

Knob influence audit fields: `declared_knob_influence_ids`, `declared_influence_rationale`.

Emit `claims` and `claim_refs`. Every non-uncertainty claim must cite catalog `evidence_id` values through `evidence_refs`; every inference claim must also cite an allowed rule through `research_rule_refs`. Every recommendation, candidate, pick, position decision, portfolio action, risk adjustment, or execution check must use `claim_refs` to cite its supporting claim. When evidence is insufficient, emit an evidence-backed explicit empty disposition and an uncertainty claim; never invent evidence ids, fingerprints, rule ids, or cross-run references.

<!-- runtime-evidence-contract:end -->
