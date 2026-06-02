import { sep } from "node:path";

const PRIVATE_PLACEHOLDER = "<private-prompt-repo>";
const PROMPT_BODY_PLACEHOLDER = "<redacted-prompt-body>";

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function configuredPrivateRoots(extraRoots: ReadonlyArray<string> = []): string[] {
  const roots = new Set<string>();
  for (const root of extraRoots) {
    if (root.trim()) roots.add(root.trim());
  }
  const privateRepo = process.env.MOSAIC_PRIVATE_PROMPT_REPO?.trim();
  if (privateRepo) {
    roots.add(privateRepo);
    roots.add(`${privateRepo}${sep}prompts${sep}mosaic`);
    roots.add(`${privateRepo}/prompts/mosaic`);
  }
  return [...roots].sort((a, b) => b.length - a.length);
}

export function redactPrivatePromptPaths(
  value: string,
  extraRoots: ReadonlyArray<string> = [],
): string {
  let out = value;
  for (const root of configuredPrivateRoots(extraRoots)) {
    out = out.replace(new RegExp(escapeRegExp(root), "g"), PRIVATE_PLACEHOLDER);
  }
  out = out.replace(
    /(?:[A-Za-z]:)?[^\s|]*\/(?:private-prompts[^/\s|)]*|prompt-store|data\/private-prompts)(?:\/[^\s|)]*)?/g,
    PRIVATE_PLACEHOLDER,
  );
  return out;
}

export function redactPromptFields(value: string): string {
  return value
    .replace(
      /(zh_prompt["']?\s*[:=]\s*)("[\s\S]*?"|'[\s\S]*?')/gi,
      `$1"${PROMPT_BODY_PLACEHOLDER}"`,
    )
    .replace(
      /(en_prompt["']?\s*[:=]\s*)("[\s\S]*?"|'[\s\S]*?')/gi,
      `$1"${PROMPT_BODY_PLACEHOLDER}"`,
    )
    .replace(
      /(prompt_body["']?\s*[:=]\s*)("[\s\S]*?"|'[\s\S]*?')/gi,
      `$1"${PROMPT_BODY_PLACEHOLDER}"`,
    );
}

export function redactSensitiveText(value: string, extraRoots: ReadonlyArray<string> = []): string {
  return redactPromptFields(redactPrivatePromptPaths(value, extraRoots));
}
