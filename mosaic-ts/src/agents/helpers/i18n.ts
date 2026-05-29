/**
 * Locale helpers shared by the prompt builder + structured-output fallback.
 *
 * Extracted from ETFAgents' ``ts/src/agents/schemas/rating.ts`` so that
 * ``helpers/structured_output.ts`` does not have to depend on the schemas
 * directory (which holds ETF-specific rating logic we are not porting).
 */

const CHINESE_OUTPUT_VALUES = new Set([
  "chinese",
  "中文",
  "zh",
  "zh-cn",
  "zh-hans",
  "bilingual", // MOSAIC bilingual mode includes a Chinese half — treat as Chinese for prompt-language rules.
]);

/** True when the bridge's ``output_language`` config maps to a Chinese-output mode. */
export function isChinese(language: string | undefined): boolean {
  if (!language) return false;
  return CHINESE_OUTPUT_VALUES.has(language.trim().toLowerCase());
}
