/**
 * Python interpreter discovery.
 *
 * Resolution order:
 *   1. `MOSAIC_PYTHON` env var (explicit override).
 *   2. `<repoRoot>/.venv/bin/python` on POSIX.
 *   3. `<repoRoot>/.venv/Scripts/python.exe` on Windows.
 *   4. Fail with a clear message asking the user to set up the project venv.
 *
 * We deliberately do NOT fall back to `python` on PATH — the system Python
 * almost certainly doesn't have the project deps and the failure would
 * surface inside LangChain / Tushare imports rather than at startup.
 */

import { existsSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { BridgeStartupError } from "./errors.js";

/** Path to `mosaic/bridge/__main__.py` relative to the resolved repo root. */
const BRIDGE_MARKER = join("mosaic", "bridge", "__main__.py");

/** Walk up from `start` until a directory containing `marker` is found. */
function findUpward(start: string, marker: string, limit = 8): string | null {
  let dir = resolve(start);
  for (let i = 0; i < limit; i++) {
    if (existsSync(join(dir, marker))) {
      return dir;
    }
    const parent = dirname(dir);
    if (parent === dir) {
      return null;
    }
    dir = parent;
  }
  return null;
}

/** Resolve the directory that contains `mosaic/bridge/__main__.py`. */
export function findRepoRoot(): string {
  // Search relative to this module (works for both tsx dev and built dist).
  const here = dirname(fileURLToPath(import.meta.url));
  const fromHere = findUpward(here, BRIDGE_MARKER);
  if (fromHere) {
    return fromHere;
  }
  // Fallback: search relative to cwd.
  const fromCwd = findUpward(process.cwd(), BRIDGE_MARKER);
  if (fromCwd) {
    return fromCwd;
  }
  throw new BridgeStartupError(
    `Could not locate the MOSAIC repo root. Looked for ${BRIDGE_MARKER} ` +
      `upward from ${here} and ${process.cwd()}.`,
  );
}

interface ResolvedPython {
  /** Absolute path to the python interpreter. */
  python: string;
  /** Absolute path to the repo root (passed as cwd to the subprocess). */
  repoRoot: string;
  /** Where the path came from — useful for error messages and debugging. */
  source: "env" | "venv-posix" | "venv-windows";
}

function isExecutableFile(path: string): boolean {
  try {
    const stat = statSync(path);
    return stat.isFile();
  } catch {
    return false;
  }
}

/**
 * Resolve the Python interpreter to spawn. Throws ``BridgeStartupError``
 * with an actionable message if no candidate is usable.
 */
export function resolvePython(repoRoot: string = findRepoRoot()): ResolvedPython {
  const envPath = process.env.MOSAIC_PYTHON;
  if (envPath && envPath.trim() !== "") {
    if (!isExecutableFile(envPath)) {
      throw new BridgeStartupError(
        `MOSAIC_PYTHON=${envPath} does not exist or is not a file. ` +
          `Set it to a valid python interpreter path or unset it to use ${repoRoot}/.venv.`,
      );
    }
    return { python: envPath, repoRoot, source: "env" };
  }

  const isWindows = process.platform === "win32";
  const venvPosix = join(repoRoot, ".venv", "bin", "python");
  const venvWindows = join(repoRoot, ".venv", "Scripts", "python.exe");

  if (!isWindows && isExecutableFile(venvPosix)) {
    return { python: venvPosix, repoRoot, source: "venv-posix" };
  }
  if (isWindows && isExecutableFile(venvWindows)) {
    return { python: venvWindows, repoRoot, source: "venv-windows" };
  }

  // Cross-platform: also check the "wrong" path in case someone set up a
  // POSIX venv on Windows under WSL or vice-versa.
  if (isExecutableFile(venvPosix)) {
    return { python: venvPosix, repoRoot, source: "venv-posix" };
  }
  if (isExecutableFile(venvWindows)) {
    return { python: venvWindows, repoRoot, source: "venv-windows" };
  }

  throw new BridgeStartupError(
    `No Python interpreter found.\n` +
      `  - $MOSAIC_PYTHON is unset.\n` +
      `  - ${venvPosix} does not exist.\n` +
      `  - ${venvWindows} does not exist.\n` +
      `Set up the venv with:\n` +
      `    cd ${repoRoot}\n` +
      `    uv venv\n` +
      `    uv pip install -e ".[data]"\n` +
      `or set MOSAIC_PYTHON to a python that has the mosaic package installed.`,
  );
}

export type { ResolvedPython };
