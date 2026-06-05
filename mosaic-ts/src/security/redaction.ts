import { sep } from "node:path";

const PRIVATE_PLACEHOLDER = "<private-prompt-repo>";
const PROMPT_BODY_PLACEHOLDER = "<redacted-prompt-body>";
const SECRET_PLACEHOLDER = "<redacted-secret>";
const ENDPOINT_PLACEHOLDER = "<redacted-endpoint>";
const QUOTED_VALUE = String.raw`(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')`;
const PROMPT_BODY_KEYS = new Set(["zh_prompt", "en_prompt", "prompt_body"]);
const SECRET_KEYS = "(?:api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|app[_-]?key|key)";
const ENDPOINT_KEYS =
  "(?:base[_-]?url|baseUrl|backend[_-]?url|anthropic[_-]?base[_-]?url|anthropicApiUrl)";

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
      new RegExp(`(["']?zh_prompt["']?\\s*[:=]\\s*)${QUOTED_VALUE}`, "gi"),
      `$1"${PROMPT_BODY_PLACEHOLDER}"`,
    )
    .replace(
      new RegExp(`(["']?en_prompt["']?\\s*[:=]\\s*)${QUOTED_VALUE}`, "gi"),
      `$1"${PROMPT_BODY_PLACEHOLDER}"`,
    )
    .replace(
      new RegExp(`(["']?prompt_body["']?\\s*[:=]\\s*)${QUOTED_VALUE}`, "gi"),
      `$1"${PROMPT_BODY_PLACEHOLDER}"`,
    )
    .replace(
      /(["']?contents["']?\s*[:=]\s*\{)([\s\S]*?)(\})/gi,
      (_match, open, body, close) =>
        `${open}${String(body).replace(
          new RegExp(`(["']?(?:zh|en)["']?\\s*[:=]\\s*)${QUOTED_VALUE}`, "gi"),
          `$1"${PROMPT_BODY_PLACEHOLDER}"`,
        )}${close}`,
    );
}

export function redactSecretFields(value: string): string {
  return value
    .replace(new RegExp(`([?&]${SECRET_KEYS}=)([^\\s&#]+)`, "gi"), `$1${SECRET_PLACEHOLDER}`)
    .replace(
      new RegExp(`(["']?${SECRET_KEYS}["']?\\s*[:=]\\s*)${QUOTED_VALUE}`, "gi"),
      `$1"${SECRET_PLACEHOLDER}"`,
    )
    .replace(/\b(Authorization\s*[:=]\s*)(?:Bearer|Basic)?\s*[^\s,;]+/gi, `$1${SECRET_PLACEHOLDER}`)
    .replace(/\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+/gi, `$1 ${SECRET_PLACEHOLDER}`);
}

export function redactEndpointFields(value: string): string {
  return value
    .replace(/(^|\s)(--base-url\s+)([^\s]+)/gi, `$1$2${ENDPOINT_PLACEHOLDER}`)
    .replace(
      new RegExp(`(["']?${ENDPOINT_KEYS}["']?\\s*[:=]\\s*)${QUOTED_VALUE}`, "gi"),
      `$1"${ENDPOINT_PLACEHOLDER}"`,
    )
    .replace(/\b(base\s*=\s*)https?:\/\/[^\s,;]+/gi, `$1${ENDPOINT_PLACEHOLDER}`);
}

export function redactSensitiveText(value: string, extraRoots: ReadonlyArray<string> = []): string {
  return redactEndpointFields(
    redactSecretFields(redactPromptFields(redactPrivatePromptPaths(value, extraRoots))),
  );
}

export function redactSensitiveValue<T>(value: T, extraRoots: ReadonlyArray<string> = []): T {
  if (typeof value === "string") {
    return redactSensitiveText(value, extraRoots) as T;
  }
  if (Array.isArray(value)) {
    return value.map((item) => redactSensitiveValue(item, extraRoots)) as T;
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(value)) {
      if (PROMPT_BODY_KEYS.has(key)) {
        out[key] = PROMPT_BODY_PLACEHOLDER;
      } else if (
        key === "contents" &&
        child &&
        typeof child === "object" &&
        !Array.isArray(child)
      ) {
        out[key] = Object.fromEntries(
          Object.entries(child).map(([lang, text]) => [
            lang,
            lang === "zh" || lang === "en"
              ? PROMPT_BODY_PLACEHOLDER
              : redactSensitiveValue(text, extraRoots),
          ]),
        );
      } else {
        out[key] = redactSensitiveValue(child, extraRoots);
      }
    }
    return out as T;
  }
  return value;
}
