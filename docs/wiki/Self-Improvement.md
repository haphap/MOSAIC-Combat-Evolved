# Self-Improvement

MOSAIC keeps evaluation and prompt evolution separate:

- Darwinian evaluates each Agent against its own point-in-time outcome contract
  and supplies per-Agent usage weights where that contract permits.
- KNOT is a private, training-only mutator that proposes bilingual Prompt
  Candidates from mature Agent-specific outcomes and failure summaries.
- The generic Autoresearch Runner evaluates champion and Candidate in a frozen
  validation/holdout environment; Prompt Release alone owns canary, activation,
  and rollback.
- Component calibration is a separate semiannual, shadow-gated release path
  for the seven composed Macro contracts. Its versioned weight releases apply
  prospectively and are append-only/rollback-capable; neither Darwinian nor
  KNOT directly changes those component weights.

Macro outputs remain independent; no public six-factor bundle or aggregate
stance discards their information. Decision roles consume explicit control
objects and do not copy CIO portfolio results back to upstream Agents.

The public repository defines Agent roles, tools, output schemas, evidence
lineage, release references, and fail-closed integrity checks. It does not
contain Prompt bodies, training/failure-case prose, mutator policy, or private
promotion thresholds. Those details and their tests live in the private
repository and stay outside model-visible prompts. The public repository owns
only public-safe Candidate/Split/Family/Experiment/Run/Decision contracts, the
generic shadow Runner, Promotion Authority, and Prompt Release.

Production prompt releases still use bounded `canary` traffic and support
`rollback`; those release operations do not reveal or redefine the private
evolution contract.

See [Macro Agent Role Contracts](../macro_agent_role_contracts.md) and the
[public boundary runbook](../runbooks/position_aware_prompt_evolution.md).
