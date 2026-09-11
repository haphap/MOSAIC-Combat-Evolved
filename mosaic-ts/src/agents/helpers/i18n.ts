/** Locale helpers shared by agent prompts and output rendering. */

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
