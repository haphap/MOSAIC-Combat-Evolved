export const COHORT_BEHAVIOR_START = "<!-- cohort-behavior:start -->";
export const COHORT_BEHAVIOR_END = "<!-- cohort-behavior:end -->";

const COHORT_BEHAVIOR_RE =
  /<!-- cohort-behavior:start -->\n([\s\S]*?)\n<!-- cohort-behavior:end -->/gu;

export function renderCohortBehavior(content: string): string {
  const normalized = validateCohortBehaviorContent(content);
  return `${COHORT_BEHAVIOR_START}\n${normalized}\n${COHORT_BEHAVIOR_END}`;
}

export function extractCohortBehavior(prompt: string): string {
  const matches = [...prompt.matchAll(COHORT_BEHAVIOR_RE)];
  if (matches.length !== 1 || matches[0]?.[1] === undefined) {
    throw new Error("prompt must contain exactly one cohort behavior block");
  }
  return validateCohortBehaviorContent(matches[0][1]);
}

export function replaceCohortBehavior(prompt: string, content: string): string {
  extractCohortBehavior(prompt);
  return prompt.replace(COHORT_BEHAVIOR_RE, renderCohortBehavior(content));
}

export function immutablePromptContractText(prompt: string): string {
  extractCohortBehavior(prompt);
  return prompt.replace(
    COHORT_BEHAVIOR_RE,
    `${COHORT_BEHAVIOR_START}\n{{COHORT_BEHAVIOR}}\n${COHORT_BEHAVIOR_END}`,
  );
}

export function validateCohortBehaviorContent(content: string): string {
  const normalized = content.trim();
  if (normalized.length < 8 || normalized.length > 1200) {
    throw new Error("cohort behavior must contain 8..1200 characters");
  }
  if (/(?:research[-_ ]knobs?|get_[a-z0-9_]+|```|<\/?(?:script|tool)|\{\s*")/iu.test(normalized)) {
    throw new Error("cohort behavior contains a forbidden contract or tool token");
  }
  return normalized;
}
