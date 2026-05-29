/**
 * Shared CLI table formatting (§14 R-T2).
 *
 * Terminal column padding that accounts for:
 *   - ANSI colour escapes (picocolors) — stripped before width calc so a
 *     colourised cell still aligns;
 *   - CJK / full-width characters — Chinese agent names, dissent_notes and
 *     rationale occupy 2 terminal columns each, so naive ``.length`` padding
 *     misaligns every table with Chinese content.
 *
 * Replaces the per-command ``pad()`` helpers that previously lived (and
 * diverged) across scorecard / darwinian / backtest / daily-cycle /
 * autoresearch / prism.
 */

// biome-ignore lint/suspicious/noControlCharactersInRegex: strip ANSI SGR escapes
const ANSI_RE = /\u001B\[[0-9;]*m/g;

/**
 * Display width of ``s`` in terminal columns: ANSI escapes count 0, East-Asian
 * wide / full-width code points count 2, everything else 1.
 */
export function displayWidth(s: string): number {
  let w = 0;
  for (const ch of s.replace(ANSI_RE, "")) {
    w += isWide(ch.codePointAt(0) ?? 0) ? 2 : 1;
  }
  return w;
}

/** Right-pad ``s`` to ``width`` terminal columns (CJK- and ANSI-aware). */
export function pad(s: string, width: number): string {
  const used = displayWidth(s);
  return used >= width ? s : s + " ".repeat(width - used);
}

/** East-Asian Wide / Fullwidth ranges (Unicode EAW W + F), enough for CJK CLI. */
function isWide(cp: number): boolean {
  return (
    cp >= 0x1100 &&
    (cp <= 0x115f || // Hangul Jamo
      cp === 0x2329 ||
      cp === 0x232a ||
      (cp >= 0x2e80 && cp <= 0x303e) || // CJK radicals, Kangxi
      (cp >= 0x3041 && cp <= 0x33ff) || // Hiragana..CJK symbols
      (cp >= 0x3400 && cp <= 0x4dbf) || // CJK Ext A
      (cp >= 0x4e00 && cp <= 0x9fff) || // CJK Unified
      (cp >= 0xa000 && cp <= 0xa4cf) || // Yi
      (cp >= 0xac00 && cp <= 0xd7a3) || // Hangul syllables
      (cp >= 0xf900 && cp <= 0xfaff) || // CJK compat ideographs
      (cp >= 0xfe30 && cp <= 0xfe4f) || // CJK compat forms
      (cp >= 0xff00 && cp <= 0xff60) || // Fullwidth forms
      (cp >= 0xffe0 && cp <= 0xffe6) ||
      (cp >= 0x1f300 && cp <= 0x1faff) || // emoji / symbols
      (cp >= 0x20000 && cp <= 0x3fffd)) // CJK Ext B+
  );
}
