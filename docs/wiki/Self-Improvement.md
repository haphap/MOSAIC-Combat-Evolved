# Self-Improvement

MOSAIC keeps evaluation and prompt evolution separate:

- Darwinian evaluates each Agent against its own point-in-time outcome contract
  and supplies per-Agent usage weights where that contract permits.
- KNOT evolves production prompt behavior through a private, hash-pinned
  runtime and private prompt release.
- Component calibration is a separate semiannual, shadow-gated release path
  for the seven composed Macro contracts. Its versioned weight releases apply
  prospectively and are append-only/rollback-capable; neither Darwinian nor
  KNOT directly changes those component weights.

Macro outputs remain independent; no public six-factor bundle or aggregate
stance discards their information. Decision roles consume explicit control
objects and do not copy CIO portfolio results back to upstream Agents.

The public repository defines Agent roles, tools, output schemas, evidence
lineage, release references, and fail-closed integrity checks. It does not
contain KNOT algorithms, thresholds, candidate policy, mutation targets,
scheduler policy, or research-knob values. Those details, their tests, and the
operator runbook live in the private repository and stay outside model-visible
prompts.

Production prompt releases still use bounded `canary` traffic and support
`rollback`; those release operations do not reveal or redefine the private
evolution contract.

See [Macro Agent Role Contracts](../macro_agent_role_contracts.md) and the
[public boundary runbook](../runbooks/position_aware_prompt_evolution.md).
