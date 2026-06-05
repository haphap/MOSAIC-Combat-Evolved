import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { findRepoRoot } from "../bridge/python.js";

export function loadProjectEnv(repoRoot = findRepoRoot()): void {
  const envPath = join(repoRoot, ".env");
  if (!existsSync(envPath)) return;

  for (const rawLine of readFileSync(envPath, "utf-8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;

    const normalized = line.startsWith("export ") ? line.slice("export ".length).trim() : line;
    const idx = normalized.indexOf("=");
    if (idx <= 0) continue;

    const key = normalized.slice(0, idx).trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) continue;
    if (process.env[key] !== undefined) continue;

    process.env[key] = parseEnvValue(normalized.slice(idx + 1).trim());
  }
}

function parseEnvValue(value: string): string {
  const trimmed = value.trim();
  if (trimmed.startsWith('"')) {
    const end = findClosingQuote(trimmed, '"');
    if (end > 0) {
      return trimmed
        .slice(1, end)
        .replace(/\\n/g, "\n")
        .replace(/\\r/g, "\r")
        .replace(/\\"/g, '"')
        .replace(/\\\\/g, "\\");
    }
  }
  if (trimmed.startsWith("'")) {
    const end = findClosingQuote(trimmed, "'");
    if (end > 0) {
      return trimmed.slice(1, end);
    }
  }
  return stripUnquotedInlineComment(trimmed).trimEnd();
}

function findClosingQuote(value: string, quote: "'" | '"'): number {
  for (let i = 1; i < value.length; i += 1) {
    if (quote === '"' && value[i] === "\\") {
      i += 1;
      continue;
    }
    if (value[i] === quote) {
      return i;
    }
  }
  return -1;
}

function stripUnquotedInlineComment(value: string): string {
  let quote: "'" | '"' | null = null;
  for (let i = 0; i < value.length; i += 1) {
    const ch = value[i];
    if (quote) {
      if (quote === '"' && ch === "\\") {
        i += 1;
        continue;
      }
      if (ch === quote) {
        quote = null;
      }
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      continue;
    }
    if (ch === "#" && i > 0 && /\s/.test(value[i - 1] ?? "")) {
      return value.slice(0, i);
    }
  }
  return value;
}
