/**
 * Extract plain text from provider-specific LLM content structures.
 * Mirrors ``etfagents.content_utils.extract_text_content`` and ``contains_cjk``.
 *
 * LangChain.js BaseMessage.content can be:
 *   - string
 *   - Array of { type: "text" | "output_text", text: string }
 *   - Array of strings
 *   - dict with `text` and optional `type`
 *   - nested arrays / dicts (e.g. Anthropic content blocks)
 */

const TEXT_BLOCK_TYPES = new Set(["text", "output_text"]);
const CJK_RE = /[\u4e00-\u9fff]/;

export function containsCjk(text: string | undefined | null): boolean {
  if (!text) return false;
  return CJK_RE.test(text);
}

function cleanText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function collectTextParts(content: unknown): string[] {
  if (content === null || content === undefined) return [];

  if (typeof content === "string") {
    const text = cleanText(content);
    return text ? [text] : [];
  }

  if (Array.isArray(content)) {
    const parts: string[] = [];
    for (const item of content) {
      parts.push(...collectTextParts(item));
    }
    return parts;
  }

  if (typeof content === "object") {
    const obj = content as Record<string, unknown>;
    const blockType = obj.type;
    const text = cleanText(obj.text);
    if (text && (typeof blockType === "string" ? TEXT_BLOCK_TYPES.has(blockType) : true)) {
      return [text];
    }
    const nested = obj.content;
    if (nested !== undefined && nested !== content) {
      return collectTextParts(nested);
    }
    return [];
  }

  return [];
}

export function extractTextContent(content: unknown): string {
  return collectTextParts(content).join("\n");
}
