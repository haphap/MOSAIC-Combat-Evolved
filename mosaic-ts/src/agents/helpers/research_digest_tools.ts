import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import type { StructuredToolInterface } from "@langchain/core/tools";
import { tool } from "@langchain/core/tools";
import { z } from "zod";
import {
  type BridgeApi,
  type BridgeToolFactoryOptions,
  pickBridgeTools,
} from "../../bridge/index.js";
import type { LlmHandle } from "../../llm/factory.js";
import { toolCallFingerprint } from "./agent_loop.js";
import { extractTextContent } from "./content.js";

const DIGEST_RAW_TOOL: Record<string, string> = {
  get_broker_research_digest: "get_broker_research",
  get_industry_policy_digest: "get_industry_policy",
  get_stock_research_digest: "get_stock_research",
};

const digestCache = new Map<string, string>();
const DIGEST_CHUNK_CHARS = Number.parseInt(
  process.env.MOSAIC_AGENT_DIGEST_CHUNK_CHARS ?? "48000",
  10,
);

export async function pickResearchDigestTools(args: {
  api: BridgeApi;
  names: ReadonlyArray<string>;
  options: BridgeToolFactoryOptions;
  llmHandle: LlmHandle;
  onLog: (msg: string) => void;
  signal: AbortSignal;
}): Promise<StructuredToolInterface[]> {
  const digestNames = new Set(Object.keys(DIGEST_RAW_TOOL));
  const compactNames = new Set(["get_etf_holdings"]);
  const regularNames = args.names.filter(
    (name) => !digestNames.has(name) && !compactNames.has(name),
  );
  const regularTools = await pickBridgeTools(args.api, regularNames, args.options);
  const regularByName = new Map(regularTools.map((entry) => [entry.name, entry] as const));

  if (args.names.some((name) => digestNames.has(name))) {
    const available = new Set((await args.api.toolsList()).map((entry) => entry.name));
    for (const digestName of args.names.filter((name) => digestNames.has(name))) {
      const rawName = DIGEST_RAW_TOOL[digestName];
      if (!rawName) continue;
      if (!available.has(rawName)) {
        throw new Error(`Bridge does not expose raw digest source tool: ${rawName}`);
      }
    }
  }
  if (args.names.includes("get_etf_holdings")) {
    const available = new Set((await args.api.toolsList()).map((entry) => entry.name));
    if (!available.has("get_etf_holdings")) {
      throw new Error("Bridge does not expose compact source tool: get_etf_holdings");
    }
  }

  return args.names.map((name) => {
    if (name === "get_broker_research_digest") return buildBrokerResearchDigestTool(args);
    if (name === "get_industry_policy_digest") return buildIndustryPolicyDigestTool(args);
    if (name === "get_stock_research_digest") return buildStockResearchDigestTool(args);
    if (name === "get_etf_holdings") return buildEtfHoldingsCandidateTool(args);
    const existing = regularByName.get(name);
    if (!existing) throw new Error(`Bridge tool ${name} was not built`);
    return existing;
  });
}

function buildEtfHoldingsCandidateTool(args: ResearchDigestDeps): StructuredToolInterface {
  return tool(
    async (input) => {
      const { top_n: topN, ...rawInput } = input as { top_n?: unknown } & Record<string, unknown>;
      const result = await args.api.toolsCall("get_etf_holdings", rawInput, args.options.context);
      const compact = compactEtfHoldings(result.text, Number(topN));
      args.onLog(
        `compact_source name=get_etf_holdings raw_chars=${result.text.length} compact_chars=${compact.length}`,
      );
      return compact;
    },
    {
      name: "get_etf_holdings",
      description:
        "Return a compact sector ETF constituent candidate pool as JSON. " +
        "Use it to identify leaders, then verify at most the most relevant candidates with stock tools.",
      schema: z.object({
        ticker: z.string().describe("Sector ETF ticker, e.g. 512010.SH."),
        curr_date: z.string().describe("Current date in yyyy-mm-dd format."),
        top_n: z
          .number()
          .int()
          .default(8)
          .describe("Maximum ETF constituents to return in the candidate pool."),
      }),
    },
  );
}

function buildBrokerResearchDigestTool(args: ResearchDigestDeps): StructuredToolInterface {
  return tool(
    async (input) =>
      runDigestSubagent({
        ...args,
        digestToolName: "get_broker_research_digest",
        rawToolName: "get_broker_research",
        input: input as Record<string, unknown>,
        system: brokerDigestSystem(),
      }),
    {
      name: "get_broker_research_digest",
      description:
        "Summarize full industry broker research into structured sector logic JSON. " +
        "Internally scans get_broker_research output; returns digest only, with evidence refs.",
      schema: z.object({
        ticker: z
          .string()
          .describe("A-share ticker whose broker-report industry should be researched."),
        start_date: z.string().describe("Start date in yyyy-mm-dd format, inclusive."),
        end_date: z.string().describe("End date in yyyy-mm-dd format, inclusive."),
        max_reports: z
          .number()
          .int()
          .default(30)
          .describe(
            "Maximum reports requested from the raw source; digest layer does not lower it.",
          ),
      }),
    },
  );
}

function buildStockResearchDigestTool(args: ResearchDigestDeps): StructuredToolInterface {
  return tool(
    async (input) =>
      runDigestSubagent({
        ...args,
        digestToolName: "get_stock_research_digest",
        rawToolName: "get_stock_research",
        input: input as Record<string, unknown>,
        system: stockDigestSystem(),
      }),
    {
      name: "get_stock_research_digest",
      description:
        "Summarize full individual-stock research into structured thesis JSON. " +
        "Internally scans get_stock_research output; returns digest only, with evidence refs.",
      schema: z.object({
        ticker: z.string().describe("A-share ticker to research."),
        start_date: z.string().describe("Start date in yyyy-mm-dd format, inclusive."),
        end_date: z.string().describe("End date in yyyy-mm-dd format, inclusive."),
        max_reports: z
          .number()
          .int()
          .default(30)
          .describe(
            "Maximum reports requested from the raw source; digest layer does not lower it.",
          ),
      }),
    },
  );
}

function buildIndustryPolicyDigestTool(args: ResearchDigestDeps): StructuredToolInterface {
  return tool(
    async (input) =>
      runDigestSubagent({
        ...args,
        digestToolName: "get_industry_policy_digest",
        rawToolName: "get_industry_policy",
        input: input as Record<string, unknown>,
        system: policyDigestSystem(),
      }),
    {
      name: "get_industry_policy_digest",
      description:
        "Summarize full industry policy search results into structured sector-impact JSON. " +
        "Internally scans get_industry_policy output; returns digest only, with evidence refs.",
      schema: z.object({
        curr_date: z.string().describe("Current date in yyyy-mm-dd format."),
        look_back_days: z
          .number()
          .int()
          .default(7)
          .describe("Raw policy lookback window; digest layer does not shorten it."),
        src: z.string().default("govcn").describe("Policy source, usually govcn."),
      }),
    },
  );
}

interface ResearchDigestDeps {
  api: BridgeApi;
  options: BridgeToolFactoryOptions;
  llmHandle: LlmHandle;
  onLog: (msg: string) => void;
  signal: AbortSignal;
}

async function runDigestSubagent(
  args: ResearchDigestDeps & {
    digestToolName: string;
    rawToolName: string;
    input: Record<string, unknown>;
    system: string;
  },
): Promise<string> {
  const cacheKey = [
    args.llmHandle.model,
    args.digestToolName,
    toolCallFingerprint(args.rawToolName, args.input),
    JSON.stringify(args.options.context ?? {}),
  ].join("|");
  const cached = digestCache.get(cacheKey);
  if (cached) {
    args.onLog(`digest_cache_hit name=${args.digestToolName}`);
    return cached;
  }

  const raw = await args.api.toolsCall(args.rawToolName, args.input, args.options.context);
  const chunks = chunkText(raw.text, validDigestChunkChars());
  args.onLog(
    `digest_source name=${args.digestToolName} raw_chars=${raw.text.length} chunks=${chunks.length}`,
  );

  const partials: string[] = [];
  for (const [index, chunk] of chunks.entries()) {
    const response = await args.llmHandle.llm.invoke(
      [
        new SystemMessage(args.system),
        new HumanMessage(
          `Digest chunk ${index + 1}/${chunks.length}. Return JSON only.\n\n${chunk}`,
        ),
      ],
      { signal: args.signal },
    );
    partials.push(extractTextContent(response.content));
  }

  const digest =
    partials.length === 1
      ? (partials[0] ?? "")
      : await reduceDigestPartials(args, partials.join("\n\n"));
  digestCache.set(cacheKey, digest);
  return digest;
}

async function reduceDigestPartials(
  args: { llmHandle: LlmHandle; signal: AbortSignal; system: string },
  partials: string,
): Promise<string> {
  const response = await args.llmHandle.llm.invoke(
    [
      new SystemMessage(args.system),
      new HumanMessage(
        "Merge these partial JSON digests into one final JSON digest. " +
          "Keep conflicting views, preserve evidence refs, and return JSON only.\n\n" +
          partials,
      ),
    ],
    { signal: args.signal },
  );
  return extractTextContent(response.content);
}

function validDigestChunkChars(): number {
  return Number.isFinite(DIGEST_CHUNK_CHARS) && DIGEST_CHUNK_CHARS > 4000
    ? DIGEST_CHUNK_CHARS
    : 48000;
}

function chunkText(text: string, size: number): string[] {
  if (text.length <= size) return [text];
  const chunks: string[] = [];
  for (let index = 0; index < text.length; index += size) {
    chunks.push(text.slice(index, index + size));
  }
  return chunks;
}

function compactEtfHoldings(text: string, requestedTopN: number): string {
  const topN =
    Number.isFinite(requestedTopN) && requestedTopN > 0 ? Math.min(requestedTopN, 12) : 8;
  const lines = text.split(/\r?\n/);
  const summary = new Map<string, string>();
  for (const line of lines) {
    const match = line.match(/^([^:#][^:]+):\s*(.+)$/);
    if (match?.[1] && match[2]) summary.set(match[1].trim(), match[2].trim());
  }

  const headerIndex = lines.findIndex((line) => line.startsWith("ts_code,"));
  if (headerIndex < 0) {
    return JSON.stringify({ kind: "etf_holdings_candidates", note: text.slice(0, 1200) });
  }

  const headers = lines[headerIndex]?.split(",") ?? [];
  const rows = lines
    .slice(headerIndex + 1)
    .filter((line) => line.trim().length > 0)
    .slice(0, topN)
    .map((line, index) => {
      const values = line.split(",");
      const row = Object.fromEntries(headers.map((header, i) => [header, values[i] ?? ""]));
      return {
        rank: index + 1,
        ticker: row.symbol || row.stk_code,
        name: row.stk_name,
        weight_pct: toNumber(row.stk_mkv_ratio),
        float_ratio_pct: toNumber(row.stk_float_ratio),
      };
    });

  return JSON.stringify({
    kind: "etf_holdings_candidates",
    etf: summary.get("Ticker"),
    disclosure_date: summary.get("Disclosure Date"),
    report_date: summary.get("Report Date"),
    candidates: rows,
    usage: "Use this as a candidate pool only; verify at most 3 tickers with stock tools.",
  });
}

function toNumber(value: string | undefined): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function brokerDigestSystem(): string {
  return (
    "You are broker_research_subagent. Convert industry broker research into compact JSON for a sector agent. " +
    "Extract industry-chain logic, demand/supply/price/inventory/policy/technology/capex/export drivers, direction, " +
    "consensus, disagreements, risks, affected tickers or subindustries, and evidence refs using report number/date/broker/title. " +
    "Do not quote long abstracts. Keep the digest dense and decision-useful."
  );
}

function stockDigestSystem(): string {
  return (
    "You are stock_research_subagent. Convert individual-stock broker research into compact JSON for a superinvestor agent. " +
    "Extract thesis, valuation/rating/target-price direction, growth drivers, quality signals, balance-sheet or cash-flow concerns, " +
    "risks, disagreements, holding-period fit, and evidence refs using report number/date/broker/title. Do not quote long abstracts. " +
    "Keep the digest dense and decision-useful."
  );
}

function policyDigestSystem(): string {
  return (
    "You are industry_policy_subagent. Convert policy search results into compact JSON for an investment agent. " +
    "Extract policy themes, affected industries, transmission chain, direction, time decay, beneficiaries, risks, " +
    "conflicting signals, and evidence refs using document date/department/title. Do not quote long policy text. " +
    "Keep the digest dense and decision-useful."
  );
}
