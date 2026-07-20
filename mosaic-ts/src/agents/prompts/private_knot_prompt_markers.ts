/** Terms that would expose private KNOT policy or evolution state to a model. */
export const PRIVATE_KNOT_PROMPT_MARKERS: ReadonlyArray<RegExp> = [
  /```research-knobs\b/i,
  /research[-_ ]knobs?/i,
  /\ballowed_research_rule_ids\b/i,
  /\bprediction_targets\b/i,
  /\bmutation(?:[_ -](?:targets?|manifest))?\b/i,
  /\bdomain[_ -]knob(?:[_ -]catalog)?\b/i,
  /\bconfidence[_ -]caps?\b/i,
  /\bevidence[_ -]weights?\b/i,
  /\bknot\b/i,
  /\bdarwin(?:ian)?\b/i,
  /\b(?:raw|evolution) (?:weights?|ranks?)\b/i,
  /\bevolution state\b/i,
  /\b(?:champion|challenger) behavior\b/i,
  /\b(?:promotion|rollback) gates?\b/i,
  /研究旋钮|领域旋钮|置信度上限|证据权重|允许的研究规则标识/u,
  /预测目标|突变目标|变异目标|突变清单|变异清单/u,
  /原始(?:权重|排名)|演化(?:权重|排名|状态)|进化(?:权重|排名|状态)/u,
  /冠军行为|挑战者行为|晋级门槛|回滚门槛|达尔文权重/u,
  /研究规则\s*ID/iu,
];

export function containsPrivateKnotPromptContent(prompt: string): boolean {
  return PRIVATE_KNOT_PROMPT_MARKERS.some((pattern) => pattern.test(prompt));
}
