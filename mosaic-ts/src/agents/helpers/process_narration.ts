/**
 * Detection of "process narration" — text where the model describes its
 * workflow ("data has been gathered, now I will write the report") instead of
 * producing the actual report. Mirrors ``etfagents.process_narration`` and the
 * private detection helpers in ``etfagents.tool_report_utils``.
 *
 * The regex shapes are deliberately verbatim ports of the Python source so
 * the same false-positive / false-negative profile applies on both sides.
 * If MOSAIC's 25 agents surface new false-positive patterns, extend the
 * fragments below — do not rewrite the structure.
 */

const PROCESS_DATA_READY_FRAGMENT =
  "(?:(?:全部|所有|必要|所需)?(?:数据|资料|信息).{0,20}?(?:已经|已)?(?:全部|所有|必要|所需)?" +
  ".{0,20}?(?:获取|收集|拿到|完成|掌握|到位|就绪|齐备)(?:完毕)?" +
  "|(?:已经|已).{0,20}?(?:获取|收集|拿到|完成|掌握|到位|就绪|齐备).{0,20}?(?:数据|资料|信息))";

const PROCESS_REPORT_READY_FRAGMENT =
  "(?:报告|分析|内容).{0,12}(?:已|已经)?(?:就绪|完成|生成|整理好|准备好)";

const PROCESS_REPORT_ACTION_FRAGMENT =
  "(?:以下|下面|现在|接下来|下一步|随后|开始|将|马上|准备|继续|直接|正式|可以|能够).{0,80}?" +
  "(?:撰写|生成|输出|写|整合|展开|梳理|汇总|组织|呈现|给出|形成|进入)" +
  "[^。！？!?；;\\n]{0,60}?" +
  "(?:分析报告|研究报告|诊断报告|研究分析|报告|分析|诊断|研究|正文|结论|观点|判断|框架)" +
  "[^。！？!?；;\\n]{0,20}";

const PROCESS_PRESENTATION_FRAGMENT =
  "(?:以下|下面)(?:是|为).{0,100}?" +
  "(?:分析报告|研究报告|诊断报告|研究分析|报告|分析|诊断|研究|正文|结论|观点|判断|框架|计划|决策|配置)";

const OPENING_DELIVERY_PREAMBLE_RE = new RegExp(
  "^\\s*(?:" +
    PROCESS_REPORT_READY_FRAGMENT +
    "[。！!；;，,]?\\s*" +
    "(?:" +
    PROCESS_REPORT_ACTION_FRAGMENT +
    "|" +
    PROCESS_PRESENTATION_FRAGMENT +
    "|(?:以下|下面|现在|接下来|下一步)" +
    ")" +
    "|" +
    PROCESS_DATA_READY_FRAGMENT +
    "[。！!；;，,]?\\s*" +
    "(?:" +
    PROCESS_REPORT_ACTION_FRAGMENT +
    "|" +
    PROCESS_PRESENTATION_FRAGMENT +
    ")" +
    "|以下(?:是|为).{0,60}(?:报告|分析)" +
    ")",
);

const EN_DATA_READY_RE =
  "(?:" +
  "(?:all\\s+)?(?:required|retrieved|necessary|needed)\\s+data" +
  "|(?:retrieved|gathered|collected|obtained)\\s+(?:all\\s+)?" +
  "(?:(?:required|necessary|needed)\\s+)?(?:data|information)" +
  "|(?:all\\s+)?data\\s+(?:has\\s+been\\s+)?(?:retrieved|gathered|collected|obtained)" +
  "|(?:data|information)\\s+(?:is\\s+)?(?:ready|available)" +
  ")";
const EN_REPORT_ACTION_RE =
  "(?:write|draft|compile|generate|produce)" +
  "(?:\\s+the)?(?:\\s+(?:full|complete|final))?" +
  "(?:\\s+cross-analysis)?(?:\\s+analysis)?\\s+report";

const CN_REPORT_ACTION_RE = `(?:${PROCESS_REPORT_ACTION_FRAGMENT}|${PROCESS_PRESENTATION_FRAGMENT})`;

const PROCESS_ONLY_REPORT_RE = new RegExp(
  "(?:(?:现在|好的|接下来|下一步|我|所有|数据|资料|信息|已获取|已经获取)[\\s\\S]{0,80}?)?" +
    PROCESS_DATA_READY_FRAGMENT +
    "[\\s\\S]{0,120}?" +
    CN_REPORT_ACTION_RE,
  "i",
);

const EN_PROCESS_ONLY_REPORT_RE = new RegExp(
  "(?:now|okay|alright|next|let me|i(?:'ll| will)?|we(?:'ll| will)?|with all)" +
    "[\\s\\S]{0,80}?" +
    "(?:" +
    EN_DATA_READY_RE +
    "[\\s\\S]{0,120}?" +
    EN_REPORT_ACTION_RE +
    "|" +
    EN_REPORT_ACTION_RE +
    "[\\s\\S]{0,120}?(?:based on|using|from)?[\\s\\S]{0,40}?" +
    EN_DATA_READY_RE +
    ")",
  "i",
);

const PROCESS_ONLY_REPORT_PREFIX_RE = new RegExp(
  `${PROCESS_ONLY_REPORT_RE.source}[。.!！]?\\s*`,
  "i",
);
const EN_PROCESS_ONLY_REPORT_PREFIX_RE = new RegExp(
  `${EN_PROCESS_ONLY_REPORT_RE.source}[。.!！]?\\s*`,
  "i",
);

const SECTION_HEADING_LINE_RE = /(?:^|\n)\s*[一二三四五六七八九十]+、/;

const XML_TOOL_CALL_RE = /<tool_call>|<function[=\s]|<\/?function_call>/i;

function firstNonemptyLine(text: string | undefined): string {
  if (!text) return "";
  const lines = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  for (const line of lines) {
    if (line.trim()) return line.trim();
  }
  return "";
}

/**
 * Detect leading workflow/status narration rather than report content.
 * Mirrors ``looks_like_process_narration`` in ``process_narration.py``.
 */
export function looksLikeProcessNarration(text: string | undefined): boolean {
  const firstLine = firstNonemptyLine(text);
  if (!firstLine || firstLine.length > 240) return false;
  return OPENING_DELIVERY_PREAMBLE_RE.test(firstLine);
}

/** True when the text appears to be an XML-formatted tool call rather than a report. */
export function isToolCallText(text: string | undefined): boolean {
  if (!text) return false;
  return XML_TOOL_CALL_RE.test(text);
}

/**
 * True for short status notes like "I have the data and will write now".
 * Mirrors ``_is_process_only_report_text``.
 */
export function isProcessOnlyReportText(text: string | undefined): boolean {
  const stripped = (text ?? "").trim();
  if (!stripped || stripped.length > 700) return false;
  if (SECTION_HEADING_LINE_RE.test(stripped)) return false;
  const head = stripped.slice(0, 240);
  return (
    looksLikeProcessNarration(head) ||
    PROCESS_ONLY_REPORT_RE.test(head) ||
    EN_PROCESS_ONLY_REPORT_RE.test(head)
  );
}

/**
 * Remove leading process-only status lines from otherwise valid reports.
 * Mirrors ``_strip_process_only_report_prefix``.
 */
export function stripProcessOnlyReportPrefix(text: string | undefined): string {
  const original = (text ?? "").trim();
  if (!original) return "";
  const lines = original.split("\n");
  let changed = false;

  while (lines.length > 0) {
    const firstLine = (lines[0] ?? "").trim();
    if (!firstLine) {
      lines.shift();
      changed = true;
      continue;
    }
    const head = firstLine.slice(0, 240);
    const isProcess =
      looksLikeProcessNarration(firstLine) ||
      PROCESS_ONLY_REPORT_RE.test(head) ||
      EN_PROCESS_ONLY_REPORT_RE.test(head);
    if (!isProcess) break;

    const cnPrefix = PROCESS_ONLY_REPORT_PREFIX_RE.exec(firstLine);
    const enPrefix = !cnPrefix ? EN_PROCESS_ONLY_REPORT_PREFIX_RE.exec(firstLine) : null;
    const prefixMatch = cnPrefix ?? enPrefix;
    if (!prefixMatch) break;
    const remainder = firstLine.slice(prefixMatch[0].length).trim();
    if (remainder) {
      lines[0] = remainder;
      changed = true;
      break;
    }
    lines.shift();
    changed = true;
  }

  return (changed ? lines.join("\n") : original).trim();
}

/**
 * Build a "you must call a tool now" detection regex for a given tool name.
 * Mirrors ``_UNEXECUTED_TOOL_INTENT_TEMPLATE`` + ``_looks_like_unexecuted_tool_intent``.
 */
export function looksLikeUnexecutedToolIntent(text: string | undefined, toolName: string): boolean {
  if (!text || !toolName) return false;
  const stripped = text.trim();
  if (stripped.length > 700) return false;
  if (!stripped.includes(toolName)) return false;
  if (SECTION_HEADING_LINE_RE.test(stripped)) return false;
  const escaped = toolName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern =
    "(?:好的[，,]\\s*)?(?:接下来|下一步|现在|我将|将会|准备|需要)" +
    "[\\s\\S]{0,180}?(?:调用|使用|获取)" +
    `[\\s\\S]{0,120}?${escaped}`;
  return new RegExp(pattern).test(stripped);
}
