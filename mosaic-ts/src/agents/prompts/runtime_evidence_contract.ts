import type { RuntimeAgentSpec } from "./runtime_agent_spec.js";

const LEGACY_PRIVATE_POLICY_BLOCK = /```research-knobs\s*\n[\s\S]*?```/g;
const EVIDENCE_CONTRACT_RE =
  /<!-- runtime-evidence-contract:start -->[\s\S]*?<!-- runtime-evidence-contract:end -->/g;

/** Migration-only sanitizer; production prompts must never contain this block. */
export function stripLegacyPrivatePolicyBlock(prompt: string): string {
  return prompt
    .replace(LEGACY_PRIVATE_POLICY_BLOCK, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function upsertRuntimeEvidenceContract(
  text: string,
  spec: RuntimeAgentSpec,
  language: "zh" | "en",
): string {
  if (!spec.fieldNames.includes("claims")) return text;
  const outputFields = spec.fieldNames.map((field) => `\`${field}\``).join(", ");
  const requiredTools = spec.requiredTools.map((tool) => `\`${tool}\``).join(", ");
  const macroClaimRefPath = spec.layer === "macro" ? exactMacroClaimRefPath(spec.fieldNames) : null;
  const macroSubmissionMode =
    macroClaimRefPath === "signal.claim_refs"
      ? "DIRECT"
      : macroClaimRefPath === "components[].claim_refs"
        ? "COMPONENTS"
        : null;
  const cioStageFields = spec.agent === "cio" ? exactCioStageFields(spec) : null;
  let body: string[];
  if (spec.layer === "macro" && language === "zh") {
    const conclusionRefs =
      macroSubmissionMode === "DIRECT"
        ? "提交 `mode=DIRECT`，只输出 `signal` 并省略 `components`；结论引用只放在 `signal.claim_refs`。"
        : "提交 `mode=COMPONENTS`，只输出 `components` 并省略 `signal`；每个组件分别在 `components[].claim_refs` 中提交结论引用。";
    body = [
      "## 运行时证据输出合同",
      "运行时提供本次调用唯一有效的证据目录与不透明引用标识。",
      `输出字段包括：${outputFields}。`,
      `必需运行时工具：${requiredTools || "（无）"}。`,
      conclusionRefs,
      "必须输出 `claims`，不得输出顶层 `claim_refs`。每个 claim 必须通过 " +
        "`evidence_ids` 引用证据目录中的 `evidence_id`；每个 `INTERPRETATION` claim 还必须通过 " +
        "`research_rule_refs` 引用允许的不透明标识。" +
        "必需证据不足时拒绝本阶段，不得生成宏观输出；只有证据有效但相互冲突时，才能输出带证据引用的 " +
        "`RISK_FLAG` 声明。不得伪造证据 ID、指纹、引用标识或跨运行引用。",
    ];
  } else if (spec.layer === "macro") {
    const conclusionRefs =
      macroSubmissionMode === "DIRECT"
        ? "Submit `mode=DIRECT`, emit only `signal`, and omit `components`; place conclusion references only in `signal.claim_refs`."
        : "Submit `mode=COMPONENTS`, emit only `components`, and omit `signal`; place conclusion references separately in each `components[].claim_refs`.";
    body = [
      "## Runtime Evidence Output Contract",
      "Runtime supplies the only valid evidence catalog and opaque permitted citation identifiers for this invocation.",
      `Output fields include: ${outputFields}.`,
      `Required runtime tools: ${requiredTools || "(none)"}.`,
      conclusionRefs,
      "Emit `claims` and do not emit a top-level `claim_refs` field. Every claim must cite catalog " +
        "`evidence_id` values through `evidence_ids`; every INTERPRETATION claim must also cite a " +
        "permitted opaque identifier through `research_rule_refs`. When required evidence is insufficient, reject the stage " +
        "without emitting a Macro output. Only valid but conflicting evidence may produce an evidence-backed " +
        "`RISK_FLAG` claim. Never invent evidence ids, fingerprints, citation identifiers, or cross-run references.",
    ];
  } else if (cioStageFields && language === "zh") {
    body = [
      "## 运行时证据输出合同",
      "运行时提供本次调用唯一有效的证据目录与不透明引用标识。",
      `\`decision_stage=PROPOSAL\` 时输出字段必须恰好为：${renderFields(cioStageFields.proposal)}；省略 ` +
        "`cro_control_resolutions` 和 `execution_control_resolutions`。",
      `\`decision_stage=FINAL\` 时输出字段必须恰好为：${renderFields(cioStageFields.final)}；包含 ` +
        "`cro_control_resolutions` 和 `execution_control_resolutions`。",
      `必需运行时工具：${requiredTools || "（无）"}。`,
      "必须输出 `claims` 与顶层 `claim_refs`。每个声明必须通过 `evidence_ids` 引用证据目录中的 " +
        "`evidence_id`；每个 `INTERPRETATION` 声明还必须通过 `research_rule_refs` 引用允许的不透明标识。" +
        "所有仓位决定和控制解析都必须用 `claim_refs` 引用支持它的声明。证据不足时，按当前阶段 schema " +
        "输出有证据支持的显式空处置和 `RISK_FLAG` 声明；不得伪造证据 ID、指纹、引用标识或跨运行引用。",
    ];
  } else if (cioStageFields) {
    body = [
      "## Runtime Evidence Output Contract",
      "Runtime supplies the only valid evidence catalog and opaque permitted citation identifiers for this invocation.",
      `When \`decision_stage=PROPOSAL\`, output fields must be exactly: ${renderFields(cioStageFields.proposal)}; omit ` +
        "`cro_control_resolutions` and `execution_control_resolutions`.",
      `When \`decision_stage=FINAL\`, output fields must be exactly: ${renderFields(cioStageFields.final)}; include ` +
        "`cro_control_resolutions` and `execution_control_resolutions`.",
      `Required runtime tools: ${requiredTools || "(none)"}.`,
      "Emit `claims` and top-level `claim_refs`. Every claim must cite catalog `evidence_id` values through " +
        "`evidence_ids`; every `INTERPRETATION` claim must also cite a permitted opaque identifier through " +
        "`research_rule_refs`. Every position decision and control resolution must cite supporting claims through " +
        "`claim_refs`. When evidence is insufficient, use the current stage schema to emit an evidence-backed " +
        "explicit empty disposition and a `RISK_FLAG` claim. Never invent evidence ids, fingerprints, citation " +
        "identifiers, or cross-run references.",
    ];
  } else if (spec.layer === "sector" && spec.agent !== "relationship_mapper" && language === "zh") {
    body = [
      "## 运行时证据输出合同",
      "运行时提供本次调用唯一有效的证据目录与不透明引用标识。",
      `输出字段包括：${outputFields}。`,
      `必需运行时工具：${requiredTools || "（无）"}。`,
      "必须输出 `claims` 与 `claim_refs`。每个声明必须通过 `evidence_ids` 引用证据目录中的 " +
        "`evidence_id`；每个 `INTERPRETATION` 声明还必须通过 `research_rule_refs` 引用允许的不透明标识。" +
        "所有方向和证券选择都必须用 `claim_refs` 引用支持声明。方向证据不足或无法形成唯一首尾方向时，" +
        "拒绝本阶段且不得生成行业输出；只有运行时证明相应冻结证券 shortlist 为空时，该证券侧才可按 schema " +
        "输出 `NO_QUALIFIED_SECURITY`，非空 shortlist 必须给出 picks。" +
        "不得伪造证据 ID、指纹、引用标识或跨运行引用。",
    ];
  } else if (spec.layer === "sector" && spec.agent !== "relationship_mapper") {
    body = [
      "## Runtime Evidence Output Contract",
      "Runtime supplies the only valid evidence catalog and opaque permitted citation identifiers for this invocation.",
      `Output fields include: ${outputFields}.`,
      `Required runtime tools: ${requiredTools || "(none)"}.`,
      "Emit `claims` and `claim_refs`. Every claim must cite catalog `evidence_id` values through " +
        "`evidence_ids`; every `INTERPRETATION` claim must also cite a permitted opaque identifier through " +
        "`research_rule_refs`. Every direction and security selection must cite supporting claims through " +
        "`claim_refs`. If direction evidence is insufficient or no unique preferred and least-preferred pair " +
        "can be established, reject the stage without a Sector output. Only an insufficient security candidate " +
        "set that runtime proves is an empty frozen shortlist may use `NO_QUALIFIED_SECURITY`; a non-empty " +
        "shortlist must produce picks. Never invent evidence ids, fingerprints, " +
        "citation identifiers, or cross-run references.",
    ];
  } else if (language === "zh") {
    body = [
      "## 运行时证据输出合同",
      "运行时提供本次调用唯一有效的证据目录与不透明引用标识。",
      `输出字段包括：${outputFields}。`,
      `必需运行时工具：${requiredTools || "（无）"}。`,
      "必须输出 `claims` 与 `claim_refs`。每个声明必须通过 `evidence_ids` 引用证据目录中的 " +
        "`evidence_id`；每个 `INTERPRETATION` 声明还必须通过 `research_rule_refs` 引用允许的不透明标识。" +
        "所有建议、候选、标的选择、仓位决定、组合操作、风险调整或执行检查，都必须用 `claim_refs` " +
        "引用支持它的声明。证据不足时，输出有证据支持的显式空处置和不确定性 `RISK_FLAG` 声明；" +
        "不得伪造证据 ID、指纹、引用标识或跨运行引用。",
    ];
  } else {
    body = [
      "## Runtime Evidence Output Contract",
      "Runtime supplies the only valid evidence catalog and opaque permitted citation identifiers for this invocation.",
      `Output fields include: ${outputFields}.`,
      `Required runtime tools: ${requiredTools || "(none)"}.`,
      "Emit `claims` and `claim_refs`. Every claim must cite catalog " +
        "`evidence_id` values through `evidence_ids`; every `INTERPRETATION` claim must also cite a " +
        "permitted opaque identifier through `research_rule_refs`. Every recommendation, candidate, pick, " +
        "position decision, portfolio action, risk adjustment, or execution check must use " +
        "`claim_refs` to cite its supporting claim. When evidence is insufficient, emit an " +
        "evidence-backed explicit empty disposition and a `RISK_FLAG` claim; never invent evidence ids, " +
        "fingerprints, citation identifiers, or cross-run references.",
    ];
  }
  if (spec.fieldNames.includes("macro_input_attributions")) {
    body.push(
      language === "zh"
        ? "`macro_input_attributions` 必须对十个 Macro Agent 各输出且只输出一条 `SUBMISSION_SUMMARY`，并按适用的方向、证券、风险动作或组合决策追加目标级归因。"
        : "`macro_input_attributions` must include exactly one `SUBMISSION_SUMMARY` row for each of the ten Macro Agents, plus applicable target-level rows for directions, securities, risk actions, or portfolio decisions.",
    );
  }
  const block = [
    "<!-- runtime-evidence-contract:start -->",
    ...body,
    "<!-- runtime-evidence-contract:end -->",
  ].join("\n\n");
  const cleaned = text.replace(EVIDENCE_CONTRACT_RE, "").trimEnd();
  return `${cleaned}\n\n${block}\n`;
}

function exactMacroClaimRefPath(fieldNames: ReadonlyArray<string>): string {
  const direct = fieldNames.includes("signal");
  const composed = fieldNames.includes("components");
  if (direct === composed)
    throw new Error("macro runtime fields must select exactly one output mode");
  return direct ? "signal.claim_refs" : "components[].claim_refs";
}

function exactCioStageFields(spec: RuntimeAgentSpec): {
  proposal: ReadonlyArray<string>;
  final: ReadonlyArray<string>;
} {
  const proposal = spec.stages.find((stage) => stage.stage === "cio_proposal")?.outputSchemaFields;
  const final = spec.stages.find((stage) => stage.stage === "cio_final")?.outputSchemaFields;
  if (!proposal || !final)
    throw new Error("CIO runtime contract requires proposal and final stages");
  return { proposal, final };
}

function renderFields(fields: ReadonlyArray<string>): string {
  return fields.map((field) => `\`${field}\``).join(", ");
}
