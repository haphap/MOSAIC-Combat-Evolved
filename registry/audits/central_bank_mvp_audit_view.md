# RKE Audit Trace View

- Trace: central-bank-mvp
- Complete: true
- Nodes: 8
- Edges: 15
- Missing references: 0
- Broken edges: 0

## Nodes

- source:SRC-CB-20260605-0001 | registry/sources/central_bank_sources.jsonl | {"license_status": "approved", "point_in_time_available": true, "publish_date": "2026-06-05", "source_hash": "sha256:025df5e75c9c922e9a3060a91f688402ebe1af46451d84f14a33db13995e02d3", "source_type": "official_pboc_policy_notice_seed"}
- claim:CLAIM-CB-20260605-0001 | registry/claims/central_bank_claims.jsonl | {"cause_variables": ["pboc_net_injection"], "claim_type": "causal_mechanism", "direction": "positive", "target_variables": ["short_term_liquidity_pressure"], "verifier_status": "passed"}
- hypothesis:HYP-CB-20260605-0001 | registry/hypotheses/central_bank_hypotheses.jsonl | {"hypothesis_type": "market_transmission", "requires_validation": true, "status": "candidate"}
- rule:macro.central_bank.soft.001 | registry/rule_packs/macro.central_bank.liquidity.v1.json | {"rule_pack_id": "macro.central_bank.liquidity.v1", "rule_type": "soft", "status": "candidate", "validation_status": "pending"}
- parameter_path:/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value | registry/rule_packs/macro.central_bank.liquidity.v1.json | {"candidate_values": [5, 7, 10, 20], "current_value": 7, "parameter_path": "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value", "parameter_proposal_id": "PARAM-CB-20260605-0001", "rule_pack_id": "macro.central_bank.liquidity.v1", "status": "candidate"}
- experiment:EXP-CB-20260605-0001 | registry/experiments/central_bank_validation_experiment_v2.json | {"adjusted_q_value": 0.012, "effective_n": 80, "experiment_family_id": "FAM-CB-LIQUIDITY-2026Q2", "pre_registered": true}
- patch:PATCH-CB-20260605-0001 | registry/patches/central_bank_paper_trading_patch.json | {"new_value": 10, "old_value": 7, "operation": "replace", "promotion_state": "paper_trading"}
- agent_output:OUT-CB-20260605-0001 | registry/runtime_outputs/macro.central_bank.20260605.json | {"actionability": "watchlist_or_tiny_tilt", "confidence": 0.64, "progress_status": "completed", "target_signal": "risk_appetite"}

## Edges

- claim:CLAIM-CB-20260605-0001 --source_ids-> source:SRC-CB-20260605-0001
- hypothesis:HYP-CB-20260605-0001 --claim_ids-> claim:CLAIM-CB-20260605-0001
- rule:macro.central_bank.soft.001 --claim_ids-> claim:CLAIM-CB-20260605-0001
- rule:macro.central_bank.soft.001 --hypothesis_ids-> hypothesis:HYP-CB-20260605-0001
- rule:macro.central_bank.soft.001 --parameter_paths-> parameter_path:/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value
- parameter_path:/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value --claim_ids-> claim:CLAIM-CB-20260605-0001
- parameter_path:/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value --hypothesis_ids-> hypothesis:HYP-CB-20260605-0001
- parameter_path:/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value --rule_ids-> rule:macro.central_bank.soft.001
- experiment:EXP-CB-20260605-0001 --rule_ids-> rule:macro.central_bank.soft.001
- experiment:EXP-CB-20260605-0001 --parameter_paths-> parameter_path:/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value
- patch:PATCH-CB-20260605-0001 --parameter_paths-> parameter_path:/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/net_injection_window_days/value
- patch:PATCH-CB-20260605-0001 --experiment_ids-> experiment:EXP-CB-20260605-0001
- agent_output:OUT-CB-20260605-0001 --claim_ids-> claim:CLAIM-CB-20260605-0001
- agent_output:OUT-CB-20260605-0001 --hypothesis_ids-> hypothesis:HYP-CB-20260605-0001
- agent_output:OUT-CB-20260605-0001 --rule_ids-> rule:macro.central_bank.soft.001
